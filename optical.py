#!/usr/bin/python3
# optical.py: Optical disc handling module for darbrrb
# Copyright 2024, derived from darbrrb
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
Optical disc handling module for darbrrb.

This module provides automated BD-RE disc preparation, detection, and transitions
during multi-disc DAR backups. It is Linux-only due to reliance on /dev/sr0, 
UDF tools, and Linux optical media utilities.
"""

from __future__ import annotations

import subprocess
import logging
import time
import os
import json
import tempfile
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class DiscState:
    """Represents the state of an optical disc."""
    is_blank: bool
    filesystem: str  # "udf", "iso9660", "none", "unknown"
    contains_backup_set: bool
    backup_set_id: Optional[str] = None
    device_present: bool = True


class OpticalDiscHandler:
    """
    Handles optical disc operations for darbrrb backups.
    
    This class provides methods for ejecting, detecting, formatting, mounting,
    and validating optical discs for use in multi-disc DAR backups.
    """
    
    METADATA_FILENAME = ".darbrrb_metadata.json"
    DEFAULT_DEVICE = "/dev/sr0"
    DEFAULT_MOUNTPOINT = "/mnt/darbrrb_disc"
    
    def __init__(
        self,
        device: str = DEFAULT_DEVICE,
        mountpoint: str = DEFAULT_MOUNTPOINT,
        auto_continue: bool = False,
        force_overwrite: bool = False,
        no_overwrite: bool = False
    ):
        """
        Initialize the optical disc handler.
        
        Args:
            device: The optical drive device path (default: /dev/sr0)
            mountpoint: The directory to mount discs to (default: /mnt/darbrrb_disc)
            auto_continue: Automatically continue when a valid disc is inserted
            force_overwrite: Automatically overwrite non-blank discs
            no_overwrite: Never overwrite non-blank discs (reject them)
        """
        self.device = device
        self.mountpoint = Path(mountpoint)
        self.auto_continue = auto_continue
        self.force_overwrite = force_overwrite
        self.no_overwrite = no_overwrite
        self.log = logging.getLogger('darbrrb.optical')
        
    def eject_disc(self) -> bool:
        """
        Eject the optical disc.
        
        Returns:
            True if ejection was successful, False otherwise.
        """
        self.log.info(f"Ejecting disc from {self.device}")
        try:
            subprocess.run(['eject', self.device], check=True, 
                         capture_output=True, text=True)
            self.log.info("Disc ejected successfully")
            return True
        except subprocess.CalledProcessError as e:
            self.log.warning(f"Standard eject failed: {e.stderr}")
            self.log.info("Attempting eject with -s flag")
            try:
                subprocess.run(['eject', '-s', self.device], check=True,
                             capture_output=True, text=True)
                self.log.info("Disc ejected successfully with -s flag")
                return True
            except subprocess.CalledProcessError as e2:
                self.log.error(f"Eject failed: {e2.stderr}")
                return False
    
    def wait_for_disc(self, timeout: int = 300) -> bool:
        """
        Wait for a disc to be inserted.
        
        Polls /sys/block/{device_name} for media change events, where
        device_name is dynamically extracted from the device path.
        
        Args:
            timeout: Maximum time to wait in seconds (default: 300)
            
        Returns:
            True if a disc was detected, False if timeout occurred.
        """
        self.log.info(f"Waiting for disc insertion on {self.device}...")
        
        # Extract device name (e.g., "sr0" from "/dev/sr0")
        device_name = os.path.basename(self.device)
        sys_path = f"/sys/block/{device_name}"
        
        start_time = time.time()
        poll_interval = 2  # seconds
        
        while (time.time() - start_time) < timeout:
            # Check if device exists and has media
            if os.path.exists(sys_path):
                try:
                    # Try to open the device - will fail if no media present
                    with open(self.device, 'rb') as f:
                        # Read a small amount to verify media is accessible
                        f.read(512)
                    self.log.info("Disc detected")
                    # Give the system a moment to fully recognize the disc
                    time.sleep(2)
                    return True
                except (OSError, PermissionError, IOError):
                    # No media or not ready yet
                    pass
            
            time.sleep(poll_interval)
        
        self.log.warning(f"Timeout waiting for disc insertion after {timeout} seconds")
        return False
    
    def detect_disc_state(self) -> DiscState:
        """
        Detect the state of the currently inserted disc.
        
        Checks if the disc is blank, what filesystem it has, and whether
        it contains a darbrrb backup set.
        
        Returns:
            A DiscState object describing the disc.
        """
        self.log.info(f"Detecting state of disc in {self.device}")
        
        # Check if device exists
        if not os.path.exists(self.device):
            self.log.error(f"Device {self.device} does not exist")
            return DiscState(
                is_blank=False,
                filesystem="none",
                contains_backup_set=False,
                device_present=False
            )
        
        # Try dvd+rw-mediainfo first
        filesystem = "unknown"
        is_blank = False
        
        try:
            result = subprocess.run(
                ['dvd+rw-mediainfo', self.device],
                capture_output=True,
                text=True,
                timeout=30
            )
            output = result.stdout.lower()
            
            # Check if disc is blank
            if 'blank' in output or 'virgin' in output:
                is_blank = True
                filesystem = "none"
                self.log.info("Disc appears to be blank")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            self.log.warning(f"dvd+rw-mediainfo failed or not available: {e}")
        
        # Try blkid to detect filesystem
        if not is_blank:
            try:
                result = subprocess.run(
                    ['blkid', '-o', 'value', '-s', 'TYPE', self.device],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    filesystem = result.stdout.strip().lower()
                    self.log.info(f"Detected filesystem: {filesystem}")
                else:
                    # No filesystem detected, might be blank
                    is_blank = True
                    filesystem = "none"
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
                self.log.warning(f"blkid failed: {e}")
        
        # Check for backup set metadata if not blank
        contains_backup_set = False
        backup_set_id = None
        
        if not is_blank and filesystem in ["udf", "iso9660"]:
            # Try to mount and check for metadata
            temp_mount = None
            try:
                # Create a temporary mount point
                temp_mount = tempfile.mkdtemp(prefix='darbrrb_detect_')
                
                subprocess.run(
                    ['mount', '-o', 'ro', self.device, temp_mount],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                # Check for metadata file
                metadata_path = Path(temp_mount) / self.METADATA_FILENAME
                if metadata_path.exists():
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                        backup_set_id = metadata.get('backup_set_id')
                        contains_backup_set = True
                        self.log.info(f"Found backup set: {backup_set_id}")
                
            except Exception as e:
                self.log.warning(f"Could not check for backup metadata: {e}")
            finally:
                # Unmount temporary mount
                if temp_mount:
                    try:
                        subprocess.run(['umount', temp_mount], 
                                     capture_output=True, timeout=10)
                        os.rmdir(temp_mount)
                    except Exception as e:
                        self.log.warning(f"Failed to cleanup temp mount: {e}")
        
        return DiscState(
            is_blank=is_blank,
            filesystem=filesystem,
            contains_backup_set=contains_backup_set,
            backup_set_id=backup_set_id
        )
    
    def format_disc(self) -> bool:
        """
        Format a blank BD-RE disc with UDF filesystem.
        
        Uses mkudffs with --media-type=bd-re.
        
        Returns:
            True if formatting was successful, False otherwise.
        """
        self.log.info(f"Formatting disc in {self.device} with UDF filesystem")
        
        try:
            # Format with mkudffs
            subprocess.run(
                ['mkudffs', '--media-type=bd-re', self.device],
                check=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            self.log.info("Disc formatted successfully")
            return True
        except subprocess.CalledProcessError as e:
            self.log.error(f"Formatting failed: {e.stderr}")
            return False
        except FileNotFoundError:
            self.log.error("mkudffs not found - please install udftools")
            return False
        except subprocess.TimeoutExpired:
            self.log.error("Formatting timed out after 5 minutes")
            return False
    
    def mount_disc(self, read_only: bool = False) -> bool:
        """
        Mount the disc to the configured mountpoint.
        
        Args:
            read_only: Mount the disc as read-only
            
        Returns:
            True if mounting was successful, False otherwise.
        """
        self.log.info(f"Mounting {self.device} to {self.mountpoint}")
        
        # Create mountpoint if it doesn't exist
        try:
            self.mountpoint.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log.error(f"Failed to create mountpoint: {e}")
            return False
        
        # Check if mountpoint is already in use
        try:
            result = subprocess.run(
                ['mountpoint', '-q', str(self.mountpoint)],
                capture_output=True
            )
            if result.returncode == 0:
                self.log.warning(f"{self.mountpoint} is already a mountpoint")
                return True  # Already mounted
        except FileNotFoundError:
            # mountpoint command not available, proceed anyway
            pass
        
        # Mount the disc
        mount_opts = ['-o', 'ro'] if read_only else []
        try:
            subprocess.run(
                ['mount'] + mount_opts + [self.device, str(self.mountpoint)],
                check=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            self.log.info(f"Disc mounted successfully at {self.mountpoint}")
            return True
        except subprocess.CalledProcessError as e:
            self.log.error(f"Mounting failed: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            self.log.error("Mounting timed out")
            return False
    
    def unmount_disc(self) -> bool:
        """
        Unmount the disc from the configured mountpoint.
        
        Returns:
            True if unmounting was successful, False otherwise.
        """
        self.log.info(f"Unmounting {self.mountpoint}")
        
        try:
            subprocess.run(
                ['umount', str(self.mountpoint)],
                check=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            self.log.info("Disc unmounted successfully")
            return True
        except subprocess.CalledProcessError as e:
            self.log.error(f"Unmounting failed: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            self.log.error("Unmounting timed out")
            return False
    
    def validate_disc_for_backup(
        self, 
        backup_set_id: str,
        allow_prompt: bool = True
    ) -> bool:
        """
        Validate that a disc is suitable for the current backup.
        
        Checks disc state and handles prompts for non-blank discs.
        
        Args:
            backup_set_id: The ID of the current backup set
            allow_prompt: Allow prompting the user for decisions
            
        Returns:
            True if the disc is valid and ready to use, False otherwise.
        """
        self.log.info(f"Validating disc for backup set: {backup_set_id}")
        
        state = self.detect_disc_state()
        
        if not state.device_present:
            self.log.error("No device present")
            return False
        
        # Handle blank discs
        if state.is_blank:
            self.log.info("Disc is blank, will format")
            if not self.format_disc():
                return False
            if not self.mount_disc():
                return False
            # Write metadata
            self._write_metadata(backup_set_id)
            return True
        
        # Handle discs with existing backup set
        if state.contains_backup_set:
            if state.backup_set_id == backup_set_id:
                self.log.info("Disc belongs to current backup set, continuing")
                if not self.mount_disc():
                    return False
                return True
            else:
                self.log.warning(
                    f"Disc contains different backup set: {state.backup_set_id}"
                )
                if self.no_overwrite:
                    self.log.error("Disc rejected (--no-overwrite specified)")
                    return False
                
                if self.force_overwrite:
                    self.log.warning("Overwriting disc (--force-overwrite specified)")
                    return self._overwrite_and_prepare(backup_set_id)
                
                if allow_prompt:
                    return self._prompt_overwrite(backup_set_id)
                else:
                    self.log.error("Cannot prompt user and no overwrite flag set")
                    return False
        
        # Handle discs with other filesystems
        self.log.warning(f"Disc contains data (filesystem: {state.filesystem})")
        
        if self.no_overwrite:
            self.log.error("Disc rejected (--no-overwrite specified)")
            return False
        
        if self.force_overwrite:
            self.log.warning("Overwriting disc (--force-overwrite specified)")
            return self._overwrite_and_prepare(backup_set_id)
        
        if allow_prompt:
            return self._prompt_overwrite(backup_set_id)
        else:
            self.log.error("Cannot prompt user and no overwrite flag set")
            return False
    
    def _write_metadata(self, backup_set_id: str) -> None:
        """Write backup set metadata to the mounted disc."""
        metadata = {
            'backup_set_id': backup_set_id,
            'created': time.strftime('%Y-%m-%d %H:%M:%S'),
            'tool': 'darbrrb'
        }
        
        metadata_path = self.mountpoint / self.METADATA_FILENAME
        try:
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            self.log.info(f"Wrote metadata to {metadata_path}")
        except Exception as e:
            self.log.error(f"Failed to write metadata: {e}")
    
    def _overwrite_and_prepare(self, backup_set_id: str) -> bool:
        """Overwrite the disc and prepare it for backup."""
        if not self.format_disc():
            return False
        if not self.mount_disc():
            return False
        self._write_metadata(backup_set_id)
        return True
    
    def _prompt_overwrite(self, backup_set_id: str) -> bool:
        """Prompt the user whether to overwrite the disc."""
        while True:
            response = input("Disc contains existing data. Overwrite? [y/N]: ").strip().lower()
            if response in ['y', 'yes']:
                self.log.info("User confirmed overwrite")
                return self._overwrite_and_prepare(backup_set_id)
            elif response in ['n', 'no', '']:
                self.log.info("User rejected overwrite")
                return False
            else:
                print("Please answer 'y' or 'n'")

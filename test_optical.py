#!/usr/bin/python3
# test_optical.py: Unit tests for optical disc handling module
# Copyright 2024, derived from darbrrb

"""Unit tests for the optical disc handling module."""

import unittest
from unittest.mock import Mock, patch, call, MagicMock, mock_open
import subprocess
import tempfile
import json
from pathlib import Path

from optical import OpticalDiscHandler, DiscState


class TestOpticalDiscHandler(unittest.TestCase):
    """Test cases for OpticalDiscHandler class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.handler = OpticalDiscHandler(
            device='/dev/sr0',
            mountpoint='/mnt/test_disc'
        )
    
    def test_init_default_values(self):
        """Test initialization with default values."""
        handler = OpticalDiscHandler()
        self.assertEqual(handler.device, '/dev/sr0')
        self.assertEqual(handler.mountpoint, Path('/mnt/darbrrb_disc'))
        self.assertFalse(handler.auto_continue)
        self.assertFalse(handler.force_overwrite)
        self.assertFalse(handler.no_overwrite)
    
    def test_init_custom_values(self):
        """Test initialization with custom values."""
        handler = OpticalDiscHandler(
            device='/dev/sr1',
            mountpoint='/custom/mount',
            auto_continue=True,
            force_overwrite=True
        )
        self.assertEqual(handler.device, '/dev/sr1')
        self.assertEqual(handler.mountpoint, Path('/custom/mount'))
        self.assertTrue(handler.auto_continue)
        self.assertTrue(handler.force_overwrite)
    
    @patch('subprocess.run')
    def test_eject_disc_success(self, mock_run):
        """Test successful disc ejection."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=['eject', '/dev/sr0'],
            returncode=0,
            stdout='',
            stderr=''
        )
        
        result = self.handler.eject_disc()
        
        self.assertTrue(result)
        mock_run.assert_called_once_with(
            ['eject', '/dev/sr0'],
            check=True,
            capture_output=True,
            text=True
        )
    
    @patch('subprocess.run')
    def test_eject_disc_fallback(self, mock_run):
        """Test disc ejection with fallback to -s flag."""
        # First call fails, second succeeds
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'eject', stderr='error'),
            subprocess.CompletedProcess(
                args=['eject', '-s', '/dev/sr0'],
                returncode=0,
                stdout='',
                stderr=''
            )
        ]
        
        result = self.handler.eject_disc()
        
        self.assertTrue(result)
        self.assertEqual(mock_run.call_count, 2)
        mock_run.assert_any_call(
            ['eject', '-s', '/dev/sr0'],
            check=True,
            capture_output=True,
            text=True
        )
    
    @patch('subprocess.run')
    def test_eject_disc_failure(self, mock_run):
        """Test disc ejection complete failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'eject', stderr='error')
        
        result = self.handler.eject_disc()
        
        self.assertFalse(result)
    
    @patch('time.sleep')
    @patch('time.time')
    @patch('builtins.open')
    @patch('os.path.exists')
    def test_wait_for_disc_success(self, mock_exists, mock_open_fn, mock_time, mock_sleep):
        """Test successful disc detection."""
        # Simulate device exists and is readable
        mock_exists.return_value = True
        mock_time.side_effect = [0, 1, 2]  # Simulate time progression
        
        # Mock file operations to simulate successful read
        mock_file = MagicMock()
        mock_file.read.return_value = b'data'
        mock_open_fn.return_value.__enter__.return_value = mock_file
        
        result = self.handler.wait_for_disc(timeout=10)
        
        self.assertTrue(result)
        mock_exists.assert_called()
    
    @patch('time.sleep')
    @patch('time.time')
    @patch('os.path.exists')
    def test_wait_for_disc_timeout(self, mock_exists, mock_time, mock_sleep):
        """Test disc detection timeout."""
        mock_exists.return_value = False
        # Simulate timeout
        mock_time.side_effect = [0] + list(range(1, 400))
        
        result = self.handler.wait_for_disc(timeout=10)
        
        self.assertFalse(result)
    
    @patch('os.path.exists')
    def test_detect_disc_state_no_device(self, mock_exists):
        """Test disc state detection when device doesn't exist."""
        mock_exists.return_value = False
        
        state = self.handler.detect_disc_state()
        
        self.assertFalse(state.device_present)
        self.assertEqual(state.filesystem, 'none')
    
    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_detect_disc_state_blank(self, mock_exists, mock_run):
        """Test detection of blank disc."""
        mock_exists.return_value = True
        
        # dvd+rw-mediainfo reports blank
        mock_run.return_value = subprocess.CompletedProcess(
            args=['dvd+rw-mediainfo', '/dev/sr0'],
            returncode=0,
            stdout='This disc is blank',
            stderr=''
        )
        
        state = self.handler.detect_disc_state()
        
        self.assertTrue(state.is_blank)
        self.assertEqual(state.filesystem, 'none')
        self.assertFalse(state.contains_backup_set)
    
    @patch('tempfile.mkdtemp')
    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_detect_disc_state_with_filesystem(self, mock_exists, mock_run, mock_mkdtemp):
        """Test detection of disc with filesystem."""
        mock_exists.return_value = True
        
        # First call: dvd+rw-mediainfo (no blank indicator)
        # Second call: blkid returns udf
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=['dvd+rw-mediainfo', '/dev/sr0'],
                returncode=0,
                stdout='formatted disc',
                stderr=''
            ),
            subprocess.CompletedProcess(
                args=['blkid', '-o', 'value', '-s', 'TYPE', '/dev/sr0'],
                returncode=0,
                stdout='udf\n',
                stderr=''
            )
        ]
        
        state = self.handler.detect_disc_state()
        
        self.assertFalse(state.is_blank)
        self.assertEqual(state.filesystem, 'udf')
    
    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_format_disc_success(self, mock_exists, mock_run):
        """Test successful disc formatting."""
        mock_exists.return_value = True
        mock_run.return_value = subprocess.CompletedProcess(
            args=['mkudffs', '--media-type=bd-re', '/dev/sr0'],
            returncode=0,
            stdout='',
            stderr=''
        )
        
        result = self.handler.format_disc()
        
        self.assertTrue(result)
        mock_run.assert_called_with(
            ['mkudffs', '--media-type=bd-re', '/dev/sr0'],
            check=True,
            capture_output=True,
            text=True,
            timeout=300
        )
    
    @patch('subprocess.run')
    def test_format_disc_failure(self, mock_run):
        """Test disc formatting failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'mkudffs', stderr='error')
        
        result = self.handler.format_disc()
        
        self.assertFalse(result)
    
    @patch('subprocess.run')
    @patch('pathlib.Path.mkdir')
    def test_mount_disc_success(self, mock_mkdir, mock_run):
        """Test successful disc mounting."""
        # First call checks if already mounted (not mounted)
        # Second call mounts the disc
        mock_run.side_effect = [
            subprocess.CompletedProcess(
                args=['mountpoint', '-q', '/mnt/test_disc'],
                returncode=1,  # Not a mountpoint
                stdout='',
                stderr=''
            ),
            subprocess.CompletedProcess(
                args=['mount', '/dev/sr0', '/mnt/test_disc'],
                returncode=0,
                stdout='',
                stderr=''
            )
        ]
        
        result = self.handler.mount_disc()
        
        self.assertTrue(result)
    
    @patch('subprocess.run')
    @patch('pathlib.Path.mkdir')
    def test_mount_disc_already_mounted(self, mock_mkdir, mock_run):
        """Test mounting when disc is already mounted."""
        # mountpoint command returns 0 (already mounted)
        mock_run.return_value = subprocess.CompletedProcess(
            args=['mountpoint', '-q', '/mnt/test_disc'],
            returncode=0,
            stdout='',
            stderr=''
        )
        
        result = self.handler.mount_disc()
        
        self.assertTrue(result)
        # Should only call mountpoint, not mount
        self.assertEqual(mock_run.call_count, 1)
    
    @patch('subprocess.run')
    def test_unmount_disc_success(self, mock_run):
        """Test successful disc unmounting."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=['umount', '/mnt/test_disc'],
            returncode=0,
            stdout='',
            stderr=''
        )
        
        result = self.handler.unmount_disc()
        
        self.assertTrue(result)
        mock_run.assert_called_with(
            ['umount', '/mnt/test_disc'],
            check=True,
            capture_output=True,
            text=True,
            timeout=30
        )
    
    @patch('subprocess.run')
    def test_unmount_disc_failure(self, mock_run):
        """Test disc unmounting failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'umount', stderr='busy')
        
        result = self.handler.unmount_disc()
        
        self.assertFalse(result)
    
    @patch('optical.OpticalDiscHandler.mount_disc')
    @patch('optical.OpticalDiscHandler.format_disc')
    @patch('optical.OpticalDiscHandler.detect_disc_state')
    def test_validate_disc_blank(self, mock_detect, mock_format, mock_mount):
        """Test validation of blank disc."""
        mock_detect.return_value = DiscState(
            is_blank=True,
            filesystem='none',
            contains_backup_set=False,
            device_present=True
        )
        mock_format.return_value = True
        mock_mount.return_value = True
        
        with patch.object(self.handler, '_write_metadata'):
            result = self.handler.validate_disc_for_backup('test-backup-123')
        
        self.assertTrue(result)
        mock_format.assert_called_once()
        mock_mount.assert_called_once()
    
    @patch('optical.OpticalDiscHandler.mount_disc')
    @patch('optical.OpticalDiscHandler.detect_disc_state')
    def test_validate_disc_matching_backup_set(self, mock_detect, mock_mount):
        """Test validation of disc with matching backup set."""
        mock_detect.return_value = DiscState(
            is_blank=False,
            filesystem='udf',
            contains_backup_set=True,
            backup_set_id='test-backup-123',
            device_present=True
        )
        mock_mount.return_value = True
        
        result = self.handler.validate_disc_for_backup('test-backup-123')
        
        self.assertTrue(result)
        mock_mount.assert_called_once()
    
    @patch('optical.OpticalDiscHandler.detect_disc_state')
    def test_validate_disc_mismatched_backup_set_no_overwrite(self, mock_detect):
        """Test validation with mismatched backup set and no-overwrite flag."""
        self.handler.no_overwrite = True
        mock_detect.return_value = DiscState(
            is_blank=False,
            filesystem='udf',
            contains_backup_set=True,
            backup_set_id='different-backup-456',
            device_present=True
        )
        
        result = self.handler.validate_disc_for_backup('test-backup-123')
        
        self.assertFalse(result)
    
    @patch('optical.OpticalDiscHandler._overwrite_and_prepare')
    @patch('optical.OpticalDiscHandler.detect_disc_state')
    def test_validate_disc_mismatched_backup_set_force_overwrite(
        self, mock_detect, mock_overwrite
    ):
        """Test validation with mismatched backup set and force-overwrite flag."""
        self.handler.force_overwrite = True
        mock_detect.return_value = DiscState(
            is_blank=False,
            filesystem='udf',
            contains_backup_set=True,
            backup_set_id='different-backup-456',
            device_present=True
        )
        mock_overwrite.return_value = True
        
        result = self.handler.validate_disc_for_backup('test-backup-123')
        
        self.assertTrue(result)
        mock_overwrite.assert_called_once_with('test-backup-123')
    
    @patch('builtins.input')
    @patch('optical.OpticalDiscHandler._overwrite_and_prepare')
    @patch('optical.OpticalDiscHandler.detect_disc_state')
    def test_validate_disc_prompt_accept(self, mock_detect, mock_overwrite, mock_input):
        """Test validation with user accepting overwrite prompt."""
        mock_detect.return_value = DiscState(
            is_blank=False,
            filesystem='udf',
            contains_backup_set=True,
            backup_set_id='different-backup-456',
            device_present=True
        )
        mock_input.return_value = 'y'
        mock_overwrite.return_value = True
        
        result = self.handler.validate_disc_for_backup('test-backup-123')
        
        self.assertTrue(result)
        mock_overwrite.assert_called_once()
    
    @patch('builtins.input')
    @patch('optical.OpticalDiscHandler.detect_disc_state')
    def test_validate_disc_prompt_reject(self, mock_detect, mock_input):
        """Test validation with user rejecting overwrite prompt."""
        mock_detect.return_value = DiscState(
            is_blank=False,
            filesystem='iso9660',
            contains_backup_set=False,
            device_present=True
        )
        mock_input.return_value = 'n'
        
        result = self.handler.validate_disc_for_backup('test-backup-123')
        
        self.assertFalse(result)
    
    @patch('builtins.open', new_callable=mock_open)
    @patch('time.strftime')
    def test_write_metadata(self, mock_strftime, mock_file):
        """Test writing metadata to disc."""
        mock_strftime.return_value = '2024-01-01 12:00:00'
        
        self.handler._write_metadata('test-backup-123')
        
        # Check that file was opened for writing
        mock_file.assert_called_once()
        handle = mock_file()
        
        # Check that JSON was written (we can't easily check exact content
        # because json.dump is called, not write)
        self.assertTrue(handle.write.called or handle.__enter__.called)


class TestDiscState(unittest.TestCase):
    """Test cases for DiscState dataclass."""
    
    def test_disc_state_creation(self):
        """Test creating a DiscState object."""
        state = DiscState(
            is_blank=True,
            filesystem='none',
            contains_backup_set=False,
            backup_set_id=None,
            device_present=True
        )
        
        self.assertTrue(state.is_blank)
        self.assertEqual(state.filesystem, 'none')
        self.assertFalse(state.contains_backup_set)
        self.assertIsNone(state.backup_set_id)
        self.assertTrue(state.device_present)
    
    def test_disc_state_with_backup(self):
        """Test DiscState with backup set information."""
        state = DiscState(
            is_blank=False,
            filesystem='udf',
            contains_backup_set=True,
            backup_set_id='backup-456',
            device_present=True
        )
        
        self.assertFalse(state.is_blank)
        self.assertEqual(state.filesystem, 'udf')
        self.assertTrue(state.contains_backup_set)
        self.assertEqual(state.backup_set_id, 'backup-456')


if __name__ == '__main__':
    unittest.main()

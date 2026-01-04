darbrrb
=======

[![Build Status](https://travis-ci.org/jaredjennings/darbrrb.svg?branch=master)](https://travis-ci.org/jaredjennings/darbrrb)

This is dar-based Blu-Ray redundant backup. It exists to back up a few
hundred gigabytes of data onto dozens of optical discs in a way that
it can be restored ten years later.

Setting
-------

I've got a few hundred gigabytes of data and a fireproof box. The
directions say not to put a hard drive in the box and expect it to
work after a fire. My data is on an LVM logical volume, so I can make
a snapshot to ensure it won't change during backup. This is my data
I'm backing up, not my system, so I don't need bare-metal restore.

Problems
--------

When I tried to restore my DVD backup from six years ago, made with
dar and par2:

1. I couldn't figure out how I ran dar to make the backup, nor how to
   run it to restore the files.

2. Half the DVDs had scratches or media decay, and on those discs I/O
   errors caused the copying of the single, giant 4.5GB file to stop
   halfway through.

3. I had par2 files that gave me 5% data redundancy. These were not
   enough, and they were on the same disc as the data that was lost.

4. Nothing could save me if I had lost a whole disc containing a file
   I wanted.

5. Once I figured out how the backup was made, I found that current
   versions of dar and par2 work as well as could be expected with the
   incomplete data I had.

Solutions
---------

To prevent the reoccurrence of these problems, darbrrb is designed in
the following ways:

1. darbrrb puts a copy of itself, including vital parameters used to
   run it, on every backup disc.

2. darbrrb uses dar slice files smaller than the disc, and spreads the
   slices over sets of discs.

3. darbrrb fills one or more of the discs in a set entirely with
   redundancy data: like RAID, but with optical discs, and a
   configurable number of spare discs.

4. darbrrb uses [dar](http://dar.linux.free.fr) and
   [par](http://en.wikipedia.org/wiki/Parchive) 1 because they seem
   likely to be fetchable and usable in ten years.

What is it?
-----------

darbrrb is a single script, written in Python 3, which wraps dar and
parchive. dar provides a hook, where a program can be run every time dar
finishes a slice; darbrrb hooks into this to make the redundancy data
at the proper times, and burn discs using growisofs.

Optical Disc Automation (Linux only)
-------------------------------------

darbrrb now includes an optional optical disc automation module that
streamlines multi-disc backups by handling disc preparation, detection,
and transitions automatically. When enabled, it:

- **Auto-ejects** discs when full
- **Detects** disc insertion automatically via polling
- **Formats** blank BD-RE discs with UDF filesystem
- **Validates** discs against the current backup set
- **Tracks** backup set metadata to prevent mixing disc sets
- **Prompts** before overwriting discs with existing data (configurable)

### Requirements

For optical automation, you need:
- Linux system with optical drive
- `eject` command
- `mkudffs` (from udftools package)
- `blkid` (usually pre-installed)
- `dvd+rw-mediainfo` (optional, from dvd+rw-tools)

### Usage

Enable optical automation with the `--optical` flag:

```bash
python3 darbrrb.py -v --optical dar -c mybackup -R /path/to/backup
```

Additional optical options:
- `--auto-continue`: Automatically continue when a valid disc is inserted
- `--force-overwrite`: Automatically overwrite non-blank discs
- `--no-overwrite`: Reject non-blank discs without prompting
- `--optical-device /dev/sr1`: Specify a different optical drive
- `--optical-mountpoint /mnt/custom`: Specify a custom mount point

### Workflow

1. Insert a blank BD-RE disc
2. The script automatically formats it with UDF
3. Writes backup data to the disc
4. Ejects the disc when full
5. Waits for the next disc to be inserted
6. Validates the new disc (blank or matching backup set)
7. Continues automatically or prompts as configured


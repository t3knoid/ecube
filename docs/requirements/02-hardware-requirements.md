# 2. Hardware Requirements

## 2.1 Copy Machine

A dedicated Linux workstation that:

- Connects to one or more USB hubs
- Mounts encrypted USB drives (LUKS or hardware-encrypted)
- Mounts NFS and SMB shares
- Performs multi-threaded copy operations
- Runs the ECUBE system layer API

Minimum recommended:

- Multi-core CPU
- ≥16 GB RAM
- ≥512 GB SSD
- USB 3.0+ hub(s)

## 2.2 USB Hub & Port Mapping

ECUBE must:

- Identify hubs and ports via Linux sysfs (`/sys/bus/usb/devices`)
- Map physical port → block device → mount point
- Detect insertion/removal events
- Detect filesystem type on inserted drives (e.g., ext4, exFAT, NTFS, or unformatted)
- Track drive states: `EMPTY`, `AVAILABLE`, `IN_USE`
- Persist stable identifiers for hubs and ports

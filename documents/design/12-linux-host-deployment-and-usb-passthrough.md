# 12. Linux Host Deployment and USB Passthrough

This document explains how to deploy ECUBE into a Linux container host using Docker Compose and how to prepare USB passthrough so physical USB hubs/drives connected to the machine are visible inside the ECUBE runtime container.

## 12.1 Deployment Artifacts

- Compose file: `docker-compose.ecube-host.yml`
- Runtime image: `deploy/ecube-host/Dockerfile`

The compose stack includes:

- `ecube-host`: ECUBE API runtime container (FastAPI + hardware tooling)
- `postgres`: PostgreSQL database container

## 12.2 What this setup provides

- A Linux-based runtime for ECUBE service execution.
- PostgreSQL service for persistence.
- USB/udev visibility inside the runtime container for hub/device introspection workflows.
- Support for mount tooling (NFS/SMB utilities installed in the image).

## 12.3 Start the ECUBE host stack

From repository root:

```bash
docker compose -f docker-compose.ecube-host.yml up -d --build
```

Verify services:

```bash
docker compose -f docker-compose.ecube-host.yml ps
```

Migrations are applied automatically when `ecube-host` starts (entrypoint runs `alembic upgrade head` after DB is reachable).

Optional manual migration command (only if auto-migration is disabled):

```bash
docker compose -f docker-compose.ecube-host.yml exec ecube-host alembic upgrade head
```

Check health endpoint:

```bash
curl http://localhost:8000/health
```

Stop stack:

```bash
docker compose -f docker-compose.ecube-host.yml down
```

## 12.4 USB passthrough model

When running inside a VM, USB passthrough is a two-hop pipeline:

1. **Physical host → VM** (hypervisor USB passthrough)
2. **VM → container** (`/dev/bus/usb`, `/run/udev`, `/sys/bus/usb` mounted into container)

If either hop is not configured, ECUBE will not see connected USB hub/drives.

## 12.5 Prepare VM for USB hub and drives

### Step 1: Enable USB passthrough in hypervisor

In your hypervisor, attach the USB hub (or specific USB devices) to the Linux VM.

Typical settings (names vary by hypervisor):

- Enable VM USB controller.
- Add USB filter(s) for hub/vendor/product or specific device serials.
- Ensure VM captures the device (not the host OS).

### Step 2: Verify device visibility inside VM

Inside Linux VM:

```bash
lsusb
ls /dev/bus/usb
udevadm info --export-db | head
```

You should see the hub/device entries before trying container-level validation.

### Step 3: Verify Docker can access USB nodes

Ensure Docker daemon is running and the VM user can execute Docker commands.

The compose file already mounts USB/udev/sysfs nodes into `ecube-host` and enables required privileges/capabilities.

## 12.6 Validate USB visibility inside ECUBE container

Run checks in container:

```bash
docker compose -f docker-compose.ecube-host.yml exec ecube-host lsusb
docker compose -f docker-compose.ecube-host.yml exec ecube-host ls /dev/bus/usb
```

Then validate through API introspection:

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/introspection/usb/topology
curl -H "Authorization: Bearer <token>" http://localhost:8000/introspection/block-devices
```

## 12.7 Notes for reliable hardware operation

- Use a dedicated Linux VM for ECUBE hardware tests/deployment.
- Avoid host-side auto-mounting of test drives when VM should own devices.
- Keep stable USB port usage for repeatable hub topology mapping.
- Run hardware tests with explicit flags:

  ```bash
  python -m pytest tests/hardware/test_usb_hub_hil.py -s --run-hardware
  ```

## 12.8 Troubleshooting

- **No devices in container but visible in VM:** verify compose volume mounts and `privileged` mode are active.
- **No devices in VM:** fix hypervisor USB passthrough filters/controller first.
- **Permission denied on mount operations:** confirm container privileges/capabilities and host security profile constraints.
- **Intermittent disconnects:** check USB power stability, hub quality, and VM USB controller settings.

## 12.9 Image Security Hardening and Patch Cycle

The runtime image is built from a concrete Debian-based Python tag and applies OS package updates during build.

### Recommended rebuild cadence

- Rebuild with upstream updates at least weekly.
- Rebuild immediately when critical CVEs are announced for Python/Debian base layers.

### Rebuild with fresh base layers and packages

```bash
docker compose -f docker-compose.ecube-host.yml build --pull --no-cache ecube-host
docker compose -f docker-compose.ecube-host.yml up -d
```

### Verify running image

```bash
docker compose -f docker-compose.ecube-host.yml images
docker compose -f docker-compose.ecube-host.yml ps
```

### Vulnerability scanning (recommended)

Use your preferred scanner (for example Docker Scout, Trivy, or Grype) against the built `ecube-host` image and remediate findings by rebuilding with the latest base and package updates.

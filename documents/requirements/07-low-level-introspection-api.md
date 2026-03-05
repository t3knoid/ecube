# 7. Low-Level Introspection API

These endpoints expose hardware and system internals safely.

## 7.1 USB Topology

### `GET /introspection/usb/topology`

Returns hub → port → device mapping.

## 7.2 Block Devices

### `GET /introspection/block-devices`

Returns block device metadata.

## 7.3 Mount Table

### `GET /introspection/mounts`

Returns all mounted filesystems.

## 7.4 System Health

### `GET /introspection/system-health`

Returns CPU, memory, disk I/O, worker queue status.

## 7.5 Job Engine Debug

### `GET /introspection/jobs/{id}/debug`

Returns internal worker state.

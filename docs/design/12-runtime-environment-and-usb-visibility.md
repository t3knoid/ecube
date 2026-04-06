# 12. Runtime Environment and USB Visibility — Design

This document defines the runtime-environment design for ECUBE when hardware-aware services run on a Linux host or Linux guest and explains the architectural requirements for USB visibility when hardware is accessed through a virtual machine boundary.

Operational deployment steps and verification procedures belong in operations documentation.

## 12.1 Architectural Purpose

The Linux host deployment model exists to satisfy four requirements:

- provide a stable Linux execution environment for privileged hardware workflows,
- keep the trusted system layer close to the host OS and USB subsystem,
- support PostgreSQL-backed persistence for the API runtime,
- preserve visibility into physical USB topology for discovery, drive lifecycle, and introspection flows.

## 12.2 Runtime Topology

The containerized Linux-host deployment model consists of two main runtime concerns:

- an ECUBE application container with access to required OS and device interfaces,
- a PostgreSQL persistence service.

When the frontend is deployed separately, it remains outside this hardware-facing trust boundary and communicates only through the API layer.

## 12.3 USB Visibility Model

USB passthrough is a layered visibility problem rather than an application-specific feature.

When ECUBE runs inside a VM-backed container host, the visibility chain is:

1. physical USB device is attached to the hypervisor host,
2. the hypervisor exposes that device to the Linux guest,
3. the Linux guest exposes required USB, udev, and sysfs views to the ECUBE runtime,
4. ECUBE discovery services interpret that host-visible topology.

If any layer in this chain is absent, the application cannot correctly observe hubs, ports, or drives.

## 12.4 Container Capability Requirements

The hardware-aware ECUBE runtime requires access to host interfaces that are typically abstracted away in standard application containers.

At the design level, the runtime must be able to:

- inspect USB bus information,
- access udev-derived device metadata,
- inspect relevant sysfs paths,
- execute mount and filesystem tooling needed by the trusted system layer.

This makes the runtime container materially different from a stateless web application container and justifies a more privileged deployment profile.

## 12.5 Virtualization Boundary Implications

VM-based deployments introduce an additional trust and observability boundary.

Design implications:

- hypervisor passthrough configuration is a prerequisite for hardware discovery,
- host-side auto-mount or device capture can interfere with guest ownership,
- repeatable USB topology mapping benefits from stable physical cabling and port usage,
- hardware test results should be interpreted in the context of the full host-to-guest-to-container path.

## 12.6 Security and Maintenance Considerations

Because the ECUBE runtime depends on privileged host capabilities and OS-level tooling, the deployment model must assume:

- tighter patch discipline than a purely unprivileged web workload,
- explicit review of container privileges and mounted host interfaces,
- regular security maintenance for the runtime image and base OS.

These concerns are part of the deployment architecture, even though the exact operational patch cadence belongs outside the design set.

## 12.7 Related Documents

- `docs/design/03-system-architecture.md`
- `docs/design/04-functional-requirements.md`
- `docs/design/13-build-and-deployment.md`
- `docs/operations/`

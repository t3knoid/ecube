# ECUBE — Secure Evidence Export Appliance

> **Evidence Copying & USB Based Export** — Purpose-built for eDiscovery teams that need auditable, tamper-evident data exports to encrypted USB drives.

---

## What Is ECUBE?

ECUBE is a turnkey appliance that copies litigation and investigation data from network shares (NFS/SMB) to encrypted USB drives under strict chain-of-custody controls. Every file, every drive, and every operator action is logged in an immutable audit trail — purpose-built for legal hold compliance and forensic defensibility.

---

## Key Capabilities

### Multi-Drive Parallel Export

Copy data to **4, 8, or 12 USB drives simultaneously** using dedicated per-port USB 3.0 controllers. Each port gets its own 5 Gbps channel — writing to one drive never slows another. Produce identical evidence sets for multiple parties in a single pass.

### Project Isolation — Enforced by Design

Each USB drive is cryptographically bound to a single project at initialization. Every write operation is checked against the drive's assigned project **before** any data touches the media. Cross-project contamination is architecturally impossible, not just policy.

### Immutable Audit Trail

Every operation — authentication, drive initialization, file copy, hash verification, eject — is recorded as a structured JSON event with an immutable timestamp. Audit logs are append-only and cannot be modified after the fact. Export them alongside evidence for independent chain-of-custody verification.

### Multi-Threaded Copy Engine with Resume

Parallel file transfer threads keep USB drives fed at maximum write speed. If a job is interrupted, it resumes from where it left off — file-level retry ensures no data is lost or duplicated. SHA-256 checksums verify every file post-copy.

### Hardware-Aware Drive Management

ECUBE automatically discovers USB hubs, ports, and drives through the Linux sysfs topology. No manual device configuration. Drives are tracked through a deterministic state machine (Empty → Available → In Use) with full lifecycle auditability.

### Role-Based Access Control

Four built-in roles enforce least privilege across the platform:

| Role | Access |
|---|---|
| **Admin** | Full system control, user management |
| **Manager** | Drive lifecycle, mounts, port configuration |
| **Processor** | Create and run export jobs |
| **Auditor** | Read-only access to audit logs and file hashes |

Supports local OS authentication (PAM), LDAP/Active Directory, and OIDC single sign-on (Okta, Azure AD, Auth0).

### Web-Based Operator Interface

A modern browser-based UI provides real-time visibility into drive status, job progress, mount health, and audit history. Role-aware navigation shows each operator only what they need.

---

## Hardware Tiers

| | Standard | Professional | Enterprise |
|---|---|---|---|
| **USB Ports** | 4 | 8 | 12 |
| **Concurrent Exports** | 4 | 8 | 12 |
| **CPU** | 4-core | 8-core | 12+ core |
| **RAM** | 8 GB | 16 GB | 32 GB |
| **Network** | 10 Gbps | 10 Gbps | 10–25 Gbps |
| **USB Controller** | 1 × PCIe 4-port | 2 × PCIe 4-port | 3 × PCIe 4-port |

All tiers run the same ECUBE software. Scale by adding controller cards — no license changes required.

---

## Deployment Flexibility

| Model | Description |
|---|---|
| **Air-Gapped Appliance** | Single secured machine in a locked room. No external network. Ideal for classified or walled-off projects. |
| **Enterprise Separated** | Database, application, and UI on separate hosts with VLAN segmentation. Fits corporate data center policies. |
| **Containerized All-in-One** | Three Docker containers on one host. Quick setup for labs, evaluations, and small teams. |

The same appliance image deploys in all three models — only the infrastructure topology changes.

---

## Evidence Integrity at Every Step

```text
Source Share (NFS/SMB)
       │
       ▼
  Read via multi-threaded copy engine
       │
       ▼
  Write to project-bound USB drive
       │
       ▼
  SHA-256 verification (per file)
       │
       ▼
  Manifest generated (checksums, timestamps, byte counts)
       │
       ▼
  Audit log sealed (immutable, append-only)
       │
       ▼
  Safe eject (sync, unmount, audit recorded)
```

---

## Supported Protocols & Formats

| Category | Support |
|---|---|
| **Network Shares** | NFS, SMB/CIFS |
| **Filesystems** | ext4, exFAT, NTFS, FAT32, XFS |
| **Encryption** | LUKS, hardware-encrypted USB drives |
| **Authentication** | PAM (local), LDAP, OIDC (Okta, Azure AD, Auth0) |
| **API** | REST (OpenAPI/Swagger documented) |

---

<p align="center"><em>ECUBE — Because evidence integrity is not optional.</em></p>

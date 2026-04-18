# ECUBE — Secure Evidence Export Appliance

| Field | Value |
|---|---|
| Title | ECUBE Secure Evidence Export Appliance |
| Purpose | Provides an appliance-focused overview of ECUBE covering its hardware-led value proposition, core capabilities, and deployment fit for eDiscovery teams. |
| Updated on | 04/18/26 |
| Audience | Legal teams, IT decision-makers, compliance officers, evaluators. |

## What Is ECUBE?

ECUBE is a turnkey appliance and software platform that copies litigation and investigation data from network shares (NFS/SMB) to encrypted USB drives under strict chain-of-custody controls. Every file, every drive, and every operator action is logged in an immutable audit trail — purpose-built for legal hold compliance and forensic defensibility.

The turnkey appliance story is central to the product: ECUBE is designed to run on validated hardware with dedicated USB 3.1 controller architecture so export performance stays predictable, scalable, and operationally safe.

---

## Key Capabilities

### Multi-Drive Parallel Export

Copy data to **4, 8, or 12 USB drives simultaneously** using dedicated USB 3.1 controller hardware engineered for sustained export throughput. Each controller path is selected to minimize contention so one active drive does not unnecessarily slow another. The result is faster, more predictable delivery of identical evidence sets for multiple parties in a single pass.

### Project Isolation — Enforced by Design

Each USB drive is cryptographically bound to a single project at initialization. Every write operation is checked against the drive's assigned project **before** any data touches the media. Cross-project contamination is architecturally impossible, not just policy.

### Immutable Audit Trail

Every operation — authentication, drive initialization, file copy, hash verification, eject — is recorded as a structured JSON event with an immutable timestamp. Audit logs are append-only and cannot be modified after the fact. Export them alongside evidence for independent chain-of-custody verification.

### Multi-Threaded Copy Engine with Resume

Parallel file transfer threads keep USB drives fed at maximum write speed. If a job is interrupted, it resumes from where it left off — file-level retry ensures no data is lost or duplicated. SHA-256 checksums verify every file post-copy.

### Hardware-Aware Drive Management

ECUBE automatically discovers USB hubs, ports, and drives through the Linux sysfs topology. No manual device configuration. Drives are tracked through a deterministic state machine (Disconnected → Available → In Use) with full lifecycle auditability.

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

A modern browser-based UI provides real-time visibility into drive status, job progress, mount health, and audit history. The interface is intentionally simple and task-focused so each user sees the tools that matter for the job in front of them.

That means:

- IT administrators can focus on deployment, configuration, and infrastructure readiness;
- supervisors can set up projects and prepare the environment for evidence handling;
- processors can run export jobs without broad system access;
- managers and auditors can review logs, status, and compliance activity without operational clutter.

Role-aware navigation shows each operator only what they need.

---

## Why the Turnkey Appliance Matters

ECUBE is not just software dropped onto a generic workstation. The turnkey appliance combines the application with carefully chosen platform hardware so legal and forensic teams get repeatable export performance without trial-and-error tuning.

Key appliance advantages:

- validated USB 3.1 controller layouts for optimal concurrent write performance;
- predictable port density and throughput planning;
- reduced deployment risk compared with ad hoc operator PCs;
- a cleaner chain-of-custody story because the export station is purpose-built.

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

## References

- [00-marketing-index.md](00-marketing-index.md)
- [01-website-strategy.md](01-website-strategy.md)
- [02-website-sitemap-and-design.md](02-website-sitemap-and-design.md)
- [03-demo-and-screenshot-plan.md](03-demo-and-screenshot-plan.md)
- [docs/operations/00-operational-guide.md](../operations/00-operational-guide.md)

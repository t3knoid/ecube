# ECUBE Deployment Architecture Guide

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** IT Decision-Makers, Systems Architects, Administrators  
**Document Type:** Deployment Planning

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Layers](#2-system-layers)
3. [Deployment Profiles at a Glance](#3-deployment-profiles-at-a-glance)
4. [Profile A — Air-Gapped Appliance](#4-profile-a--air-gapped-appliance)
5. [Profile B — Enterprise Separated](#5-profile-b--enterprise-separated)
6. [Profile C — Containerized All-in-One](#6-profile-c--containerized-all-in-one)
7. [Hardware Sizing](#7-hardware-sizing)
8. [USB Hardware Considerations](#8-usb-hardware-considerations)
9. [Network Hardware Considerations](#9-network-hardware-considerations)
10. [Network and Security Considerations](#10-network-and-security-considerations)
11. [Choosing a Deployment Profile](#11-choosing-a-deployment-profile)
12. [Related Documents](#12-related-documents)

---

## 1. Introduction

ECUBE (Evidence Copying & USB Based Export) is a secure evidence export platform that copies eDiscovery data onto encrypted USB drives. It is designed to fit a range of operational environments — from a single air-gapped machine in a locked room to a multi-host enterprise deployment with network segmentation.

This document describes the available deployment profiles, explains the trade-offs of each, and helps administrators select the model that best matches their security posture, infrastructure, and operational requirements.

---

## 2. System Layers

Every ECUBE deployment consists of three logical layers. The profiles described in this document differ only in how those layers are distributed across physical or virtual hosts.

```text
┌─────────────────────────────────────────────────────────────┐
│  UI Layer                                                   │
│  Vue 3 SPA served by nginx; HTTPS only                      │
│  Communicates exclusively via the REST API                  │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTPS (REST API)
┌────────────────────▼────────────────────────────────────────┐
│  Application Layer (System Layer)                           │
│  FastAPI service — the sole trusted component               │
│  Enforces policy, executes copy jobs, manages USB drives,   │
│  writes audit logs, controls network mounts                 │
└────────────────────┬────────────────────────────────────────┘
                     │ PostgreSQL wire protocol
┌────────────────────▼────────────────────────────────────────┐
│  Data Layer                                                 │
│  PostgreSQL 14+ — job state, drive inventory, audit logs    │
│  Reachable only from the Application Layer                  │
└─────────────────────────────────────────────────────────────┘
```

### Trust Boundary

Only the Application Layer interacts with the database and hardware. The UI Layer is untrusted — it never touches the database or USB subsystem directly. This boundary is enforced regardless of deployment profile.

---

## 3. Deployment Profiles at a Glance

| | Profile A | Profile B | Profile C |
|---|---|---|---|
| **Name** | Air-Gapped Appliance | Enterprise Separated | Containerized All-in-One |
| **Hosts** | 1 physical machine | 3+ (DB VM, bare-metal app, UI VM) | 1 host, 3 Docker containers |
| **Network** | Isolated / air-gapped | Segmented VLANs | Single-host Docker network |
| **USB Access** | Direct (bare-metal) | Direct (bare-metal app host) | Passed through to container |
| **Hardware Tiers** | Standard / Professional / Enterprise | Standard / Professional / Enterprise | Standard / Professional / Enterprise |
| **Best For** | Walled-off projects, portable ops | Corporate data centers, compliance-heavy orgs | Quick evaluation, lab environments, small teams |
| **Complexity** | Low | High | Low–Medium |

All three deployment profiles support all three hardware tiers (4 / 8 / 12 USB ports). The deployment profile determines *where* the layers run; the hardware tier determines *how much concurrency* the system can handle. See [§7 Hardware Sizing](#7-hardware-sizing) for per-tier specifications.

---

## 4. Profile A — Air-Gapped Appliance

### Overview

A single dedicated machine — physically secured in a controlled area — runs the complete ECUBE stack. The machine has no external network connectivity beyond the evidence source shares it needs to reach (NFS/SMB). It may be completely air-gapped when evidence data is pre-staged to local storage.

This profile is built for chain-of-custody scenarios where physical security replaces network-level segmentation.

### Topology

```text
┌────────────────────────────────────────────────────────────────┐
│  Secured Room / Evidence Processing Area                       │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Dedicated Linux Host (bare-metal)                       │  │
│  │                                                          │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │  │
│  │  │  ecube-ui    │  │  ecube-app   │  │  postgres    │    │  │
│  │  │  (nginx)     │─▶│  (FastAPI)   │─▶│  (PostgreSQL)│    │  │
│  │  │  :443        │  │  :8000       │  │  :5432       │    │  │
│  │  └──────────────┘  └──────┬───────┘  └──────────────┘    │  │
│  │                           │                              │  │
│  │                    ┌──────▼───────┐                      │  │
│  │                    │  PCIe USB    │                      │  │
│  │                    │  Controller  │                      │  │
│  │                    └──┬───┬───┬───┘                      │  │
│  │                       │   │   │                          │  │
│  │                      USB Drives                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  Optional: NFS/SMB share on same isolated network segment      │
└────────────────────────────────────────────────────────────────┘
```

### Deployment Method

Services can run as Docker containers (using `docker-compose.ecube.yml`) or as native systemd services via package deployment. Both approaches are supported:

- **Docker Compose:** Three containers (`ecube-ui`, `ecube-app`, `postgres`) managed with a single compose file.
- **Package Deployment:** ECUBE installed as a systemd service alongside a local or containerized PostgreSQL instance. See [04-package-deployment.md](operations/04-package-deployment.md).

### Characteristics

| Aspect | Detail |
|---|---|
| **Physical security** | Machine resides in a locked, access-controlled room. Physical access replaces most network controls. |
| **Network posture** | Minimal or zero external connectivity. Evidence source may be available via a dedicated NFS/SMB mount on an isolated switch or pre-staged to local disk. |
| **USB access** | Direct bare-metal access to USB controllers — no virtualization layer to traverse. |
| **Authentication** | Local PAM authentication (OS users). LDAP/OIDC not required since the machine is isolated. |
| **Audit chain** | All operations logged to the local PostgreSQL database. Audit records can be exported to read-only media alongside the evidence. |
| **Portability** | The machine can be transported to different sites. Evidence data remains physically co-located with the operator. |

### When to Use

- A specific project requires physical data isolation (regulatory, legal, or client mandate).
- The organization needs a portable evidence processing station.
- The environment is classified or requires air-gap operation.
- Simplicity is paramount — one machine, one operator, one project at a time.

---

## 5. Profile B — Enterprise Separated

### Overview

Each ECUBE layer runs on its own host, connected through network-segmented VLANs. This profile maximizes separation of concerns: the database sits on a hardened VM, the application runs on bare metal for direct USB hardware access, and the UI runs behind a reverse proxy on a separate VM.

This model is suited to established corporate data centers where infrastructure teams maintain network segmentation, host hardening, and centralized monitoring.

### Topology

```text
 ┌─────────────────────────────────────────────────────┐
 │  VLAN: Management / User Access                     │
 │                                                     │
 │  ┌──────────────┐     ┌──────────────────────────┐  │
 │  │  Browser     │────▶│  UI Host (VM)            │  │
 │  │  (Operator)  │     │  nginx reverse proxy     │  │
 │  └──────────────┘     │  :443 (TLS termination)  │  │
 │                       └────────────┬─────────────┘  │
 └────────────────────────────────────┼────────────────┘
                             Firewall │ (HTTPS only)
 ┌────────────────────────────────────┼────────────────┐
 │  VLAN: Application                 │                │
 │                                    ▼                │
 │  ┌─────────────────────────────────────────────┐    │
 │  │  Application Host (bare-metal Linux)        │    │
 │  │  FastAPI + Uvicorn (systemd service)        │    │
 │  │  USB controllers attached directly          │    │
 │  │  NFS/SMB client for evidence source mounts  │    │
 │  └─────────────────────┬───────────────────────┘    │
 │                        │                            │
 └────────────────────────┼────────────────────────────┘
                 Firewall │ (PostgreSQL only, port 5432)
 ┌────────────────────────┼────────────────────────────┐
 │  VLAN: Data            │                            │
 │                        ▼                            │
 │  ┌─────────────────────────────────────────────┐    │
 │  │  Database Host (VM, hardened)               │    │
 │  │  PostgreSQL 14+                             │    │
 │  │  Encrypted storage, restricted access       │    │
 │  └─────────────────────────────────────────────┘    │
 └─────────────────────────────────────────────────────┘
```

### Deployment Method

- **Application Host:** Package deployment as a systemd service on bare-metal Linux. See [04-package-deployment.md](operations/04-package-deployment.md).
- **Database Host:** Standard PostgreSQL installation on a hardened VM (or managed database service).
- **UI Host:** nginx serving the Vue SPA, either as a Docker container or installed directly.

### Characteristics

| Aspect | Detail |
|---|---|
| **Network segmentation** | Each layer on its own VLAN. Firewall rules restrict traffic to the minimum required ports and directions. |
| **USB access** | Bare-metal application host — no hypervisor or container USB passthrough needed. Best possible hardware reliability. |
| **Authentication** | LDAP or OIDC integration recommended. PAM with SSSD/Kerberos also supported. Centralized identity management. |
| **Database hardening** | PostgreSQL on a dedicated VM with encrypted storage, restricted network access (Application VLAN only), and regular backups. |
| **Monitoring** | Each host can forward logs and metrics to centralized SIEM/monitoring (syslog, Prometheus, ELK). |
| **Scalability** | If copy throughput is the bottleneck, add a second bare-metal application host with its own USB bank (each registers independently with the same database). |

### When to Use

- The organization has existing VLAN infrastructure and network segmentation policies.
- Compliance frameworks require documented network isolation between data, application, and user tiers.
- Centralized identity (LDAP/OIDC) and monitoring (SIEM) are already in place.
- Multiple concurrent projects or operators require production-grade reliability.

---

## 6. Profile C — Containerized All-in-One

### Overview

All three layers run as Docker containers on a single Linux host, managed with Docker Compose. This profile requires the least infrastructure and is ideal for evaluation, lab testing, proof-of-concept deployments, and smaller teams that do not need physical network segmentation.

### Topology

```text
┌─────────────────────────────────────────────────────────────┐
│  Single Linux Host (bare-metal or VM)                       │
│                                                             │
│  ┌ Docker Compose ────────────────────────────────────────┐ │
│  │                                                        │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │ │
│  │  │  ecube-ui    │  │  ecube-app   │  │  postgres    │  │ │
│  │  │  nginx       │─▶│  FastAPI     │─▶│  PostgreSQL  │  │ │
│  │  │  :443        │  │  :8000       │  │  :5432       │  │ │
│  │  └──────────────┘  └──────┬───────┘  └──────────────┘  │ │
│  │                           │                            │ │
│  └───────────────────────────┼────────────────────────────┘ │
│                              │ USB passthrough              │
│                       ┌──────▼───────┐                      │
│                       │  USB Hub /   │                      │
│                       │  Controller  │                      │
│                       └──┬───┬───┬───┘                      │
│                          │   │   │                          │
│                         USB Drives                          │
└─────────────────────────────────────────────────────────────┘
```

### Deployment Method

Docker Compose with the provided `docker-compose.ecube.yml`. Bring up the stack with:

```bash
docker compose -f docker-compose.ecube.yml up -d --build
```

For detailed Docker deployment steps, see [05-docker-deployment.md](operations/05-docker-deployment.md).

### USB Passthrough

When running on a VM, USB devices must be passed from the physical host to the VM first, then into the container. This is a two-hop pipeline:

1. **Physical host → VM:** Configure hypervisor USB passthrough (device filters by vendor/product ID or serial).
2. **VM → Container:** The compose file mounts `/dev/bus/usb`, `/run/udev`, and `/sys/bus/usb` into the `ecube-app` container.

If the host is bare-metal, only the second hop applies (Docker handles device access directly).

For full USB passthrough setup, see [12-linux-host-deployment-and-usb-passthrough.md](design/12-linux-host-deployment-and-usb-passthrough.md).

### Characteristics

| Aspect | Detail |
|---|---|
| **Setup complexity** | Low. A single `docker compose up` command starts the entire stack. |
| **Network isolation** | Docker internal network. PostgreSQL is not exposed on the host network by default. |
| **USB access** | Passed through via Docker volume mounts. The `ecube-app` container runs with elevated privileges for hardware access. |
| **Authentication** | Local PAM (container-internal users) or OIDC/LDAP if the host has network access to the identity provider. |
| **Resource sharing** | All three layers share host CPU, memory, and disk I/O. For ECUBE's typical workload (sequential copy tasks, SHA-256 hashing, modest database writes), contention is minimal on recommended hardware. |
| **Upgrades** | Rebuild and restart containers. Database volume persists across upgrades. |

### When to Use

- Evaluating ECUBE before committing to a production infrastructure plan.
- Lab or QA testing.
- Small-team operational use where network segmentation is not mandated.
- Development and integration testing environments.

---

## 7. Hardware Sizing

ECUBE is offered in three hardware tiers based on the number of concurrent USB export ports. Each tier determines the system resources needed to keep all ports fed without bottlenecks.

| Tier | USB Ports | Concurrent Copy Sessions | Target Use Case |
|---|---|---|---|
| **Standard** | 4 | Up to 4 | Single operator, small-to-medium projects |
| **Professional** | 8 | Up to 8 | Multi-operator or high-volume projects |
| **Enterprise** | 12 | Up to 12 | Large-scale evidence processing, maximum throughput |

### Primary Resource Consumers

- **CPU:** SHA-256 hash computation during file verification (single-threaded per file) and Python/Uvicorn request handling. Each concurrent copy session consumes roughly one core during hashing.
- **Memory:** Copy buffers (one per active copy thread), PostgreSQL shared buffers, and the Uvicorn worker process.
- **Disk I/O:** PostgreSQL WAL writes and audit log inserts run concurrently with network-to-USB copy streams. An SSD is mandatory for the system/database volume.
- **Network:** NFS/SMB reads from evidence source shares scale linearly with concurrent sessions. See [§9 Network Hardware Considerations](#9-network-hardware-considerations).

### Specifications by Tier

| Resource | Standard (4 ports) | Professional (8 ports) | Enterprise (12 ports) |
|---|---|---|---|
| **CPU** | 4 cores, 2.0 GHz x86-64 | 8 cores, 2.0 GHz x86-64 | 12+ cores, 2.0 GHz x86-64 |
| **RAM** | 8 GB | 16 GB | 32 GB |
| **System Storage** | 256 GB SSD | 512 GB SSD | 512 GB+ SSD |
| **Network** | 10 Gbps Ethernet | 10 Gbps Ethernet | 10 Gbps Ethernet (or dual-NIC / 25 Gbps) |
| **USB** | 1 × PCIe USB controller (4-port) | 2 × PCIe USB controller (4-port) | 3 × PCIe USB controller (4-port) |
| **PCIe Slots** | 1 × x4 (USB) + 1 optional (NIC) | 2 × x4 (USB) + 1 optional (NIC) | 3 × x4 (USB) + 1 (NIC) |

**Sizing rationale:**

- **CPU:** One core per active copy session for SHA-256 hashing, plus overhead for the API, database, and OS. The Professional and Enterprise tiers add cores proportionally.
- **RAM:** Each copy thread's buffer is small (~64 KB), but PostgreSQL, the OS page cache, and multiple Uvicorn workers benefit from additional memory at higher concurrency. 32 GB at the Enterprise tier allows PostgreSQL `shared_buffers` of 512 MB+ with ample headroom.
- **Storage:** Larger tiers produce more audit log volume and manifest data. SSD is non-negotiable — spinning disks create I/O contention.
- **Network:** All tiers recommend 10 Gbps. At the Enterprise tier (12 drives × 150–350 MB/s each = 1.8–4.2 GB/s aggregate demand), a single 10G link may saturate; dual-NIC bonding or a 25 Gbps NIC provides additional headroom.

### Sizing by Deployment Profile

The tier specifications above assume a single-host deployment (Profile A or C). For Profile B (Enterprise Separated), resources are distributed across hosts:

| Host | Standard (4 ports) | Professional (8 ports) | Enterprise (12 ports) |
|---|---|---|---|
| **Application** (bare-metal) | 4 cores, 4 GB RAM, 128 GB SSD | 8 cores, 8 GB RAM, 256 GB SSD | 12+ cores, 16 GB RAM, 256 GB SSD |
| **Database** (VM) | 2 cores, 4 GB RAM, 256 GB SSD | 4 cores, 8 GB RAM, 512 GB SSD | 4 cores, 16 GB RAM, 512 GB+ SSD |
| **UI** (VM) | 1–2 cores, 1 GB RAM, 32 GB | 1–2 cores, 2 GB RAM, 32 GB | 2 cores, 2 GB RAM, 32 GB |

The application host needs the most CPU for hashing. The database host needs the most storage for audit logs and job metadata. The UI host is lightweight at all tiers.

### Notes

- Copy thread count is configurable. Each active thread allocates a read buffer (default 64 KB). Memory pressure is modest even with many threads.
- PostgreSQL `shared_buffers`: 128 MB (Standard), 256 MB (Professional), 512 MB (Enterprise). Adjust and add corresponding host RAM.
- These specifications assume ECUBE is the primary workload on the host. If co-located with other services, add resources accordingly.
- Tier selection is independent of deployment profile. A Standard-tier air-gapped appliance and a Standard-tier enterprise-separated deployment use the same total resources, just distributed differently.

### Theoretical Copy Performance

The table below estimates how long it takes to copy a **10 TB dataset** from an NFS or SMB network share to **a single USB drive** under ideal conditions (sustained sequential I/O, no source-side contention). Real-world times will be longer due to small-file overhead, metadata updates, network latency, and source share load.

These numbers are **the same regardless of hardware tier**. The tier determines how many of these copy jobs can run in parallel (4, 8, or 12), not how fast each individual copy completes.

**Assumptions:**

| Parameter | Value |
|---|---|
| Data set size | 10 TB (10,000 GB) |
| USB 3.0 drive sustained write | 200 MB/s (see note below) |
| NFS protocol efficiency | ~93% of wire speed |
| SMB protocol efficiency | ~85% of wire speed |
| 1 Gbps NIC practical throughput | ~115 MB/s |
| 10 Gbps NIC practical throughput | ~1,150 MB/s |

**Drive write speed (200 MB/s) explained:**

The USB 3.0 bus signals at 5 Gbps and delivers roughly 400–450 MB/s after protocol overhead — but the bus is not the limiting factor. The bottleneck is the drive's internal media:

| Drive Type | Typical Sustained Write | Limiting Factor |
|---|---|---|
| USB 3.0 portable HDD (5400 RPM) | 100–130 MB/s | Spindle speed, platter density |
| USB 3.0 portable HDD (7200 RPM) | 130–180 MB/s | Spindle speed |
| USB 3.0 external SSD (SATA-based) | 200–400 MB/s | SATA bridge or NAND write speed |
| USB 3.0 external SSD (NVMe-based) | 350–450 MB/s | USB 3.0 bus ceiling |

The 200 MB/s figure used throughout this section represents a **conservative estimate for a SATA-based USB 3.0 external SSD** — the most common class of drive used for evidence export. Actual throughput varies by drive model, capacity utilization, and thermal conditions. For planning purposes, 200 MB/s provides a realistic baseline; faster drives will complete sooner, slower HDDs will take proportionally longer.

#### Single-Drive Copy Time — 10 TB

| NIC Speed | Protocol | Effective Network Throughput | Drive Write Speed | Bottleneck | Copy Time |
|---|---|---|---|---|---|
| 1 Gbps | NFS | ~107 MB/s | 200 MB/s | **Network** | ~26 hours |
| 1 Gbps | SMB | ~98 MB/s | 200 MB/s | **Network** | ~28 hours |
| 10 Gbps | NFS | ~1,070 MB/s | 200 MB/s | **USB drive** | ~13 h 53 min |
| 10 Gbps | SMB | ~978 MB/s | 200 MB/s | **USB drive** | ~13 h 53 min |

#### Effect of Copy Threads on a Single-Drive Copy

ECUBE uses multiple copy threads within a single export job. Threads read different files from the network share concurrently and write them to the same USB drive. More threads help mask network latency (each thread can have a read in-flight while another thread writes) and keep the drive's write queue full, but the single drive's sequential write speed is the ultimate ceiling.

The table below shows the effective throughput of a single 10 TB copy to one USB drive over a 10 Gbps NFS share at different thread counts:

| Copy Threads | Behavior | Effective Throughput | Copy Time (10 TB) |
|---|---|---|---|
| 1 | One file at a time. Drive idles during network reads. | ~120–150 MB/s | ~18–23 hours |
| 2 | One thread reads while the other writes. Reduces idle gaps. | ~160–190 MB/s | ~14–17 hours |
| 4 | Read pipeline stays full; drive write queue rarely starves. Approaches drive's sustained write ceiling. | ~190–200 MB/s | ~13–14 hours |
| 8 | Marginal gain — drive is already saturated. Small benefit for directories with many small files. | ~195–200 MB/s | ~13–14 hours |
| 16+ | No additional throughput. Extra threads add context-switch overhead and memory usage with negligible benefit. | ~195–200 MB/s | ~13–14 hours |

**Why threads help — and where they stop:**

- **Network latency masking:** A single thread must wait for each network read to complete before starting the next. Multiple threads overlap reads and writes, keeping the USB drive busy.
- **Small-file acceleration:** Directories with thousands of small files benefit most from additional threads because per-file metadata operations (open, stat, close) dominate. With 4+ threads, multiple files are in-flight simultaneously.
- **Diminishing returns at the drive:** Once the read pipeline delivers data faster than the drive can write (~200 MB/s for USB 3.0 SSD), adding more threads cannot improve throughput. The drive's write speed is the hard ceiling.
- **Recommended default:** 4 threads per copy job provides the best balance of throughput and resource efficiency for most workloads. This is configurable in ECUBE's job settings.

On a **1 Gbps NIC**, the network is the bottleneck at every thread count. Additional threads still help slightly (latency masking fills the pipe more efficiently), but the ceiling drops to ~107 MB/s (NFS) or ~98 MB/s (SMB) instead of the drive's 200 MB/s.

#### Key Takeaways

- **A 1 Gbps NIC is the bottleneck even for a single drive.** At ~107 MB/s (NFS), the network is slower than the USB drive's 200 MB/s write speed, so the drive sits partially idle.
- **10 Gbps eliminates the network bottleneck for per-drive throughput.** Each copy runs at the USB drive's native write speed (~200 MB/s).
- **NFS outperforms SMB** at identical wire speeds. On a 1 Gbps link, the difference is ~3 MB/s (~2 hours over 10 TB). On 10 Gbps, both protocols exceed the drive's write speed, so the difference vanishes.
- **Higher tiers don't make individual copies faster — they make more copies simultaneous.** The value of the Professional and Enterprise tiers is producing multiple identical exports at once.
- **Post-copy verification** (SHA-256 hash comparison of source vs. destination) requires reading all data back from the USB drive. This adds roughly the same duration as the copy itself when performed as a separate pass, or ~50% overhead when hashing inline during copy.

---

## 8. USB Hardware Considerations

### Standard USB Hub

A multi-port USB 3.x hub is the simplest way to connect multiple drives. ECUBE discovers hubs and ports through the Linux sysfs tree (`/sys/bus/usb/devices`).

**Trade-offs:**
- Simple and inexpensive.
- All ports share the hub's upstream bandwidth (typically 5 Gbps for USB 3.0).
- Hub quality affects power delivery and signal integrity.

### PCIe USB Controller Card

For higher throughput and isolation, a dedicated PCIe USB controller card provides one or more independent USB host controllers. Cards with per-port controllers eliminate shared-bus contention entirely.

#### Reference Card: StarTech PEXUSB3S44V

The ECUBE turnkey appliance is designed around the **StarTech.com 4 Port USB 3.0 PCIe Card (PEXUSB3S44V)**. This card provides four USB 3.0 ports, each backed by its own dedicated 5 Gbps host controller channel. Higher-tier configurations use multiple cards.

| Specification | Detail |
|---|---|
| **Ports** | 4 × USB 3.0 Type-A per card |
| **Bandwidth** | 5 Gbps dedicated per port (not shared) |
| **Controllers** | 4 independent host controllers per card |
| **Interface** | PCIe x4 (compatible with x4, x8, x16 slots) |
| **Power** | SATA or LP4 power connector for reliable drive power delivery |

**Why this card fits ECUBE:**

- **No shared bus:** Each simultaneous copy-and-verify job gets the full 5 Gbps channel, so writing to one drive never throttles another.
- **Deterministic sysfs topology:** Each controller appears as a separate USB bus in `/sys/bus/usb/devices`. Port identity is stable across reboots — ECUBE maps each physical port to a fixed `usb_ports` record without relying on volatile `/dev/sdX` names.
- **Reliable power:** The auxiliary power connector avoids the voltage sag that can cause USB drives to disconnect mid-copy on bus-powered hubs.
- **Stackable:** Multiple cards install into adjacent PCIe slots. ECUBE discovers all controllers and ports automatically — no configuration changes are needed when scaling from one card to three.
- **VM passthrough friendly:** Each controller is its own PCI function, which simplifies IOMMU group assignment when passing individual ports (or the entire card) to a VM.

#### Multi-Card Configurations by Tier

| Tier | Cards | Total Ports | PCIe Slots Required | Aggregate USB Bandwidth |
|---|---|---|---|---|
| **Standard** | 1 × PEXUSB3S44V | 4 | 1 × x4 | 20 Gbps (4 × 5 Gbps) |
| **Professional** | 2 × PEXUSB3S44V | 8 | 2 × x4 | 40 Gbps (8 × 5 Gbps) |
| **Enterprise** | 3 × PEXUSB3S44V | 12 | 3 × x4 | 60 Gbps (12 × 5 Gbps) |

**Chassis considerations for multi-card installs:**

- The Professional tier requires a motherboard with at least 2 available PCIe x4 (or wider) slots; the Enterprise tier requires 3. Mid-tower and server-class chassis typically provide sufficient slots and airflow.
- Each card draws power through its SATA/LP4 connector. Verify the power supply has enough free connectors (2 for Professional, 3 for Enterprise) and adequate 12 V rail capacity.
- Space the cards to allow airflow between them. Avoid placing all three in adjacent slots on motherboards with tight slot spacing.

**Advantages (general PCIe cards):**
- Each port has dedicated bandwidth — no contention between simultaneous copies.
- Deterministic sysfs topology — port identity is stable across reboots and does not change when drives are inserted or removed.
- Better power delivery compared to bus-powered hubs.
- Ideal for the bare-metal Application Host in Profile A and Profile B deployments.

**Considerations:**
- Requires PCIe x4 (or wider) slots — slot count limits the maximum tier for a given chassis.
- VM USB passthrough may require per-controller passthrough at the IOMMU group level. The PEXUSB3S44V simplifies this because each controller is a separate PCI function.

### Recommendations by Tier and Profile

| Profile | Standard (4 ports) | Professional (8 ports) | Enterprise (12 ports) |
|---|---|---|---|
| **A — Air-Gapped Appliance** | 1 × PEXUSB3S44V | 2 × PEXUSB3S44V | 3 × PEXUSB3S44V |
| **B — Enterprise Separated** | 1 × PEXUSB3S44V on bare-metal app host | 2 × PEXUSB3S44V on bare-metal app host | 3 × PEXUSB3S44V on bare-metal app host |
| **C — Containerized All-in-One** | USB hub (VM) or 1 × PEXUSB3S44V (bare-metal) | 2 × PEXUSB3S44V (bare-metal recommended) | 3 × PEXUSB3S44V (bare-metal required) |

---

## 9. Network Hardware Considerations

ECUBE is designed to run multiple copy threads and concurrent export sessions. The number of active USB ports determines the aggregate read demand on the evidence source network. With higher hardware tiers, the network link is increasingly likely to become the bottleneck.

### Network Demand by Tier

A single USB 3.0 drive sustains roughly 150–350 MB/s sequential writes depending on the drive.

| Tier | Ports | Aggregate Write Demand | 1 Gbps NIC (~115 MB/s) | 10 Gbps NIC (~1,150 MB/s) | 25 Gbps NIC (~2,800 MB/s) |
|---|---|---|---|---|---|
| **Standard** (4 ports) | 4 | 600–1,400 MB/s | Bottleneck | Adequate | Headroom |
| **Professional** (8 ports) | 8 | 1,200–2,800 MB/s | Severe bottleneck | May saturate at peak | Adequate |
| **Enterprise** (12 ports) | 12 | 1,800–4,200 MB/s | Unusable | Bottleneck at peak | Adequate |

A 1 Gbps NIC caps at ~115 MB/s — below even a single fast USB drive's sustained write rate. At the Standard tier with four ports, a 10 Gbps NIC provides comfortable headroom. At Professional and Enterprise tiers, a single 10 Gbps link may saturate when all ports are active with fast drives; dual-NIC bonding (LACP) or a 25 Gbps NIC is recommended.

### Recommendations by Tier

| Tier | Minimum NIC | Recommended NIC | Notes |
|---|---|---|---|
| **Standard** (4 ports) | 1 Gbps | 10 Gbps | 1 Gbps is workable for slower drives, but 10 Gbps eliminates the network as a variable. |
| **Professional** (8 ports) | 10 Gbps | 10 Gbps (bonded pair or 25 Gbps) | A single 10G link handles most workloads; bonded NICs provide headroom at peak. |
| **Enterprise** (12 ports) | 10 Gbps | 25 Gbps or bonded 2 × 10 Gbps | 12 concurrent sessions can exceed a single 10G link. |

### Recommendations by Profile

| Profile | Recommendation |
|---|---|
| **A — Air-Gapped Appliance** | Match NIC to tier. If evidence data is pre-staged to local storage, NIC speed is only relevant for the UI and may remain at 1 Gbps. |
| **B — Enterprise Separated** | 10 Gbps (or higher per tier) on the bare-metal application host. Evidence source file server should also be on a matching network segment. |
| **C — Containerized All-in-One** | Match host NIC to tier. The container inherits the host's network interface. |

### Implementation Notes

- Most server-class motherboards and many workstation boards have 10 Gbps onboard Ethernet or an available PCIe slot for a 10G NIC.
- Ensure the upstream switch port and evidence source share also support 10 Gbps (or 25 Gbps); a fast NIC behind a slower switch provides no benefit.
- For air-gapped Profile A deployments where evidence is loaded onto local storage first (sneakernet), the NIC is only used for the ECUBE UI and may remain at 1 Gbps.
- When using bonded NICs (LACP), the switch must also support link aggregation on the corresponding ports.

---

## 10. Network and Security Considerations

### TLS Everywhere

All client-facing traffic must be encrypted with TLS 1.2 or later. In Profiles A and C, TLS terminates at the nginx container. In Profile B, TLS terminates at the UI host reverse proxy, and internal VLAN traffic may optionally use mTLS between network segments.

### Database Access

PostgreSQL is never exposed beyond the Application Layer. In Profile C, Docker networking enforces this by default. In Profile B, firewall rules on the Data VLAN restrict inbound connections to the Application VLAN on port 5432 only.

### Authentication Models

| Method | Profile A | Profile B | Profile C |
|---|---|---|---|
| Local PAM (OS users) | Recommended | Supported | Supported |
| LDAP (Active Directory) | N/A (air-gapped) | Recommended | Supported |
| OIDC (SSO) | N/A (air-gapped) | Recommended | Supported |
| PAM + SSSD/Kerberos | N/A | Supported | Supported |

### Audit Log Integrity

All deployment profiles generate identical audit records in the PostgreSQL `audit_logs` table. In air-gapped deployments (Profile A), consider periodically exporting audit data to write-once media (e.g., a separate USB drive formatted read-only after export) for independent evidence retention.

### Firewall Rules (Profile B)

| Source VLAN | Destination VLAN | Port | Protocol | Purpose |
|---|---|---|---|---|
| User / Management | UI | 443 | HTTPS | Browser → nginx |
| UI | Application | 8000 | HTTP | nginx → FastAPI |
| Application | Data | 5432 | TCP | FastAPI → PostgreSQL |
| Application | Evidence Source | 2049 / 445 | NFS / SMB | Mount evidence shares |

All other inter-VLAN traffic should be denied by default.

---

## 11. Choosing a Deployment Profile

Use the decision tree below to identify the profile that best fits your environment.

```text
Does the environment require physical air-gap
or complete network isolation?
    │
    ├── YES ──▶  Profile A  (Air-Gapped Appliance)
    │
    └── NO
         │
         Does your organization require VLAN segmentation
         between data, application, and user tiers?
             │
             ├── YES ──▶  Profile B  (Enterprise Separated)
             │
             └── NO
                  │
                  Is this for evaluation, lab use,
                  or a small team without compliance mandates?
                      │
                      ├── YES ──▶  Profile C  (Containerized All-in-One)
                      │
                      └── NO ──▶  Start with Profile C; plan migration
                                  to Profile B when infrastructure is ready.
```

### Hybrid Approaches

The profiles are not mutually exclusive across an organization. For example:

- **Headquarters** runs Profile B with centralized LDAP and SIEM integration.
- **Field offices** deploy Profile A appliances for on-site evidence collection, then ship sealed USB drives back to headquarters.
- **QA lab** uses Profile C for automated testing against the same API surface.

The ECUBE application is identical in all profiles. Only the host topology, network configuration, and authentication method change.

---

## 12. Related Documents

| Document | Description |
|---|---|
| [design/03-system-architecture.md](design/03-system-architecture.md) | Component view, platform abstraction, security design |
| [design/10-security-and-access-control.md](design/10-security-and-access-control.md) | Role model, authorization matrix, authentication flows |
| [design/12-linux-host-deployment-and-usb-passthrough.md](design/12-linux-host-deployment-and-usb-passthrough.md) | Docker USB passthrough setup |
| [design/13-build-and-deployment.md](design/13-build-and-deployment.md) | Build pipeline, package and Docker deployment paths |
| [design/15-frontend-architecture.md](design/15-frontend-architecture.md) | UI container topology and nginx configuration |
| [operations/03-installation.md](operations/03-installation.md) | Prerequisite software and hardware requirements |
| [operations/04-package-deployment.md](operations/04-package-deployment.md) | Systemd-based package deployment (Profile A/B application host) |
| [operations/05-docker-deployment.md](operations/05-docker-deployment.md) | Docker Compose deployment (Profile A/C) |
| [operations/07-security-best-practices.md](operations/07-security-best-practices.md) | TLS, credentials, firewall, and audit log guidelines |

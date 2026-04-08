# 17. Turnkey Appliance Design

| Field | Value |
|---|---|
| Title | Turnkey Appliance Design |
| Purpose | Defines the implementation design for ECUBE turnkey embedded appliance tiers, including hardware composition, topology, thermal and power behavior, and manufacturing and QA validation structure. |
| Updated on | 04/08/26 |
| Audience | Engineers, manufacturing, and QA teams. |

## 17.1 Audience and Scope

### 17.1.1 Primary Audience

- Engineers designing and integrating ECUBE appliance hardware profiles.
- Manufacturing teams assembling, provisioning, and validating production units.
- QA teams validating behavior under sustained load, fault, and recovery scenarios.

### 17.1.2 Scope

- Define turnkey appliance tiers and their hardware composition.
- Define component classes, model constraints, and scaling rules by tier.
- Define PCIe and USB-controller topology assumptions per tier.
- Define thermal and power design requirements for appliance stability.
- Define wiring, labeling, and manufacturing verification structure.
- Define QA validation skeleton for production readiness.

### 17.1.3 Explicit Exclusions

- Commercial pricing and GTM positioning.
- User stories and product planning narratives.
- Software feature behavior not tied to appliance hardware design.

## 17.2 Appliance Tier Matrix

| Tier | USB Export Ports | Motherboard / CPU | Max ECC RAM | PCIe | USB Subsystem | Storage | Networking | Chassis and Power |
|---|---:|---|---|---|---|---|---|---|
| ECUBE-4 | 4 | Appliance-grade, low-power, high-reliability board; prefer soldered CPU | 16GB UDIMM | 1 x x4 | 1x StarTech PEXUSB3S44V low-profile card | OS SSD (industrial class, size TBD) + internal storage for logs/manifests/job metadata | 10GbE recommended; 1GbE minimum supported | Standard ATX PS2 PSU, flexible fan orientation, quiet/reliable thermal profile |
| ECUBE-8 | 8 | Appliance-grade, low-power, high-reliability board | 64GB UDIMM | 1 x x4 | 2x StarTech PEXUSB3S44V low-profile cards | OS SSD (industrial class, size TBD) + internal storage for logs/manifests/job metadata | 10GbE recommended; 1GbE minimum supported | Standard ATX PS2 PSU, flexible fan orientation, quiet/reliable thermal profile |
| ECUBE-12 | 12 | Appliance-grade, low-power, high-reliability board | 128GB RDIMM | 1 x x16 (riser -> 3 cards) | 3x StarTech PEXUSB3S44V low-profile cards | OS SSD (industrial class, size TBD) + internal storage for logs/manifests/job metadata | 10GbE recommended; 1GbE minimum supported | Standard ATX PS2 PSU, flexible fan orientation, quiet/reliable thermal profile |

Notes:

- PCIe wording intentionally mirrors the embedded board and CPU reference matrix for consistency.
- Each PEXUSB3S44V card contributes four USB 3.0 ports; controller-level separation is treated as an intended isolation boundary that must be validated during QA.
- 10GbE is recommended for optimal network performance during concurrent ingest and export workflows; 1GbE remains the minimum supported network baseline.

### 17.2.1 Embedded Board and CPU Reference Matrix

| Tier | Motherboard | CPU (Embedded) | Max ECC RAM | PCIe | Notes |
|---|---|---|---|---|---|
| ECUBE-4 | Supermicro A2SDi-2C-HLN4F | Atom C3338 | 16GB UDIMM | 1 x x4 | Ultra-low power |
| ECUBE-8 | Supermicro A2SDi-4C-HLN4F | Atom C3558 | 64GB UDIMM | 1 x x4 | 4-core Atom |
| ECUBE-12 | Supermicro X11SDV-4C-TLN2F | Xeon-D 2123IT | 128GB RDIMM | 1 x x16 (riser -> 3 cards) | Server-grade |

Integration notes:

- The ECUBE-12 x16 slot is split via a validated riser topology to host three USB controller cards.
- Tier-specific motherboard and CPU choices are reference baselines and may be revised through controlled BOM change review.

## 17.3 Hardware Architecture Design

### 17.3.1 Compute and Board Profiles

- Define approved board and CPU families per tier with lifecycle support windows.
- Prefer soldered CPU designs for ECUBE-4 where field serviceability is not required.
- Constrain board choices to appliance-grade reliability, stable firmware support, and reproducible supply.

### 17.3.2 Memory Design

- ECUBE-4 uses 16GB ECC UDIMM baseline.
- ECUBE-8 uses 64GB ECC UDIMM baseline.
- ECUBE-12 uses 128GB ECC RDIMM baseline for higher concurrency and metadata pressure.
- Establish memory qualification tests for temperature, sustained I/O pressure, and long-run stability.

### 17.3.3 Storage Design

- Separate OS boot storage from operational metadata persistence responsibilities.
- Use industrial or appliance-appropriate SSD classes for OS reliability.
- Define minimum write-endurance requirements for metadata and audit-related local storage workloads.

### 17.3.4 Networking Design

- Recommend 10GbE NIC capability for all tiers to reduce network ingest bottlenecks and improve end-to-end job completion time.
- Support 1GbE as a minimum compatibility baseline for constrained deployments.
- Prioritize NIC and driver combinations with stable Linux support and low packet-loss behavior under sustained throughput.

## 17.3.5 Hardware Choice Justification

- Appliance-grade board and CPU classes are chosen for long-run stability, predictable firmware behavior, and supportable lifecycle management.
- ECC memory is chosen to reduce risk of silent memory corruption in long-running, evidence-sensitive workflows.
- Multi-controller USB topology is chosen to improve port-level fault containment and concurrent I/O behavior.
- Industrial SSD classes are chosen for endurance and reliability of OS and operational metadata workloads.
- 10GbE recommendation is chosen to avoid network-side throughput bottlenecks when multiple export workflows run concurrently.
- ATX PS2 power and controlled thermal design are chosen to preserve stable operation during sustained copy and verify load.

## 17.4 PCIe and USB Topology Design

### 17.4.1 PCIe Map Skeleton (Per Tier)

- ECUBE-4: allocate one PCIe slot for one USB controller card.
- ECUBE-8: allocate two PCIe slots for two USB controller cards.
- ECUBE-12: allocate three PCIe slots for three USB controller cards.
- Record root-complex mapping and lane allocation in per-tier PCIe map artifacts.

### 17.4.2 USB Controller Isolation Model

- Treat each controller card as a separate failure and contention domain where feasible.
- Preserve deterministic software mapping from physical port labels to logical port identity.
- Validate that contention or reset on one controller does not silently remap active media on another controller.

## 17.5 Thermal and Power Design

### 17.5.1 Thermal Envelope

- Design cooling for sustained copy and verify workloads at expected ambient temperatures.
- Define fan orientation profiles and airflow validation checkpoints per chassis build.
- Verify no persistent thermal throttling under representative worst-case concurrent workflows.

### 17.5.2 Power Budget and Stability

- Use standard ATX PS2 power supplies sized with margin for peak USB and host load.
- Define derating policy and rail stability checks under concurrent device attach and active transfer.
- Validate clean recovery behavior after transient power disturbances.

## 17.6 Wiring and Physical Build Design

### 17.6.1 Internal Wiring

- Route cables for serviceability and low accidental-disconnect risk.
- Standardize cable classes, retention, and routing across production tiers.

### 17.6.2 External Port Labeling and Mapping

- Enforce physically visible port labels consistent with software identity conventions.
- Require manufacturing verification of physical-to-logical mapping before unit release.

## 17.7 Manufacturing Validation Skeleton

- Confirm installed components match approved tier BOM profile.
- Confirm PCIe slot utilization and USB card count match tier definition.
- Confirm memory type/size and ECC capability match tier definition.
- Confirm thermal and power checks pass baseline qualification tests.
- Capture build records linking serial numbers to tier profile and validation artifacts.

## 17.8 QA Validation Skeleton

- Sustained transfer test under representative concurrent job load.
- Hot-plug and removal behavior validation across all tier ports.
- Controller fault containment and remapping safety checks.
- Restart and recovery validation preserving deterministic media mapping.
- Thermal-soak and power-stability regression checks by tier.

## 17.9 Open Items

- Finalize approved motherboard and CPU model lists per tier.
- Finalize OS SSD capacity and endurance targets.
- Finalize per-tier PCIe lane and root-complex map diagrams.
- Define measurable pass/fail criteria for controller-level isolation claims.

## References

- [docs/requirements/17-turnkey-appliance-requirements.md](../requirements/17-turnkey-appliance-requirements.md)
- [docs/design/02-hardware-design.md](02-hardware-design.md)
- [docs/design/03-system-architecture.md](03-system-architecture.md)
- [docs/requirements/02-hardware-requirements.md](../requirements/02-hardware-requirements.md)
- [docs/operations/01-installation.md](../operations/01-installation.md)

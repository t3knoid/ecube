# Recommended Hardware

This document lists validated hardware configurations for each ECUBE tier. All configurations use the SuperMicro embedded-NIC mini-ITX platform for compact, low-power deployment.

---

## Validated Configurations by Tier

| ECUBE Tier | USB Cards | Motherboard | CPU | Memory | Notes |
|---|---|---|---|---|---|
| **ECUBE-4** | 1× PEXUSB3S44V | A2SDi-2C-HLN4F | Intel Atom C3338 | 16 GB ECC UDIMM | Compact footprint; ideal for small matters (≤4 simultaneous drives) |
| **ECUBE-8** | 2× PEXUSB3S44V | A2SDi-4C-HLN4F | Intel Atom C3558 | 16 GB ECC UDIMM | Best all-around; balances cost, capacity, and power consumption |
| **ECUBE-12** | 3× PEXUSB3S44V | X11SDV-4C-TLN2F | Intel Xeon-D 2123IT | 32 GB ECC RDIMM | High-throughput ingest; required for 12-port Enterprise tier |

---

## Component Details

### USB Expansion Card — StarTech PEXUSB3S44V

Each card provides 4 independent USB 3.0 ports via 4 dedicated VIA VL805 host controllers (one controller per port). This architecture eliminates intra-card bus contention: every port operates at the full 5 Gbps USB 3.0 line rate regardless of activity on adjacent ports.

- **Interface:** PCIe x4 (compatible with x4, x8, and x16 slots)
- **Ports per card:** 4 × USB 3.0 Type-A
- **Controllers:** 4 × VIA VL805 (one per port)
- **Power connector:** SATA or LP4 auxiliary power (required)
- **sysfs topology:** Each controller appears as a separate USB bus — port assignments are stable across reboots

Scale by adding cards: one card for ECUBE-4, two for ECUBE-8, three for ECUBE-12.

---

### Motherboards

All three boards share the SuperMicro A2SDi / X11SDV mini-ITX form factor with onboard 10 Gbps Ethernet, out-of-band IPMI, ECC memory support, and low idle power consumption — making them well-suited for always-on appliance use.

#### SuperMicro A2SDi-2C-HLN4F (ECUBE-4)

| Attribute | Value |
|---|---|
| Form factor | Mini-ITX |
| CPU | Intel Atom C3338 (2-core, 2.2 GHz, 15 W TDP) |
| Memory slots | 2× DDR4 ECC UDIMM (max 64 GB) |
| PCIe slots | 1× PCIe 3.0 x8 (in x16 slot) |
| Onboard NIC | 4× 1 GbE + 1× 10 GbE (Intel X552) |
| IPMI | Yes (dedicated port) |
| Notes | Single PCIe slot limits to one USB card (4 ports); sufficient for standard-tier workloads |

#### SuperMicro A2SDi-4C-HLN4F (ECUBE-8)

| Attribute | Value |
|---|---|
| Form factor | Mini-ITX |
| CPU | Intel Atom C3558 (4-core, 2.0 GHz, 16 W TDP) |
| Memory slots | 2× DDR4 ECC UDIMM (max 64 GB) |
| PCIe slots | 1× PCIe 3.0 x8 (in x16 slot) + 1× PCIe 3.0 x4 (M.2 or riser) |
| Onboard NIC | 4× 1 GbE + 1× 10 GbE (Intel X552) |
| IPMI | Yes (dedicated port) |
| Notes | Two PCIe paths support two USB cards (8 ports); recommended tier for most deployments |

#### SuperMicro X11SDV-4C-TLN2F (ECUBE-12)

| Attribute | Value |
|---|---|
| Form factor | Mini-ITX |
| CPU | Intel Xeon-D 2123IT (4-core, 1.7 GHz, 35 W TDP) |
| Memory slots | 4× DDR4 ECC RDIMM (max 256 GB) |
| PCIe slots | 3× PCIe 3.0 x8 (via PLX switch) |
| Onboard NIC | 2× 10 GbE (Intel X722) |
| IPMI | Yes (dedicated port) |
| Notes | Three PCIe x8 slots accommodate three USB cards (12 ports); dual 10 GbE supports high-throughput evidence ingest |

---

### Memory

| Configuration | Type | Capacity | Notes |
|---|---|---|---|
| ECUBE-4 / ECUBE-8 | DDR4 ECC UDIMM | 16 GB (1× 16 GB or 2× 8 GB) | Unbuffered ECC; required by A2SDi platform |
| ECUBE-12 | DDR4 ECC RDIMM | 32 GB (2× 16 GB or 4× 8 GB) | Registered ECC; required by X11SDV platform |

ECC memory is strongly recommended for all tiers. Copy operations read and write large volumes of evidence data — a silent memory error that corrupts a byte in a file buffer would produce an incorrect hash without any visible error, undermining chain-of-custody integrity.

---

## Storage Recommendations

The operating system and ECUBE application should be installed on a dedicated drive separate from any evidence staging storage.

| Use | Recommended Type | Minimum Capacity |
|---|---|---|
| OS + application | SATA or NVMe SSD | 120 GB |
| Evidence staging (optional) | SATA or NVMe SSD / HDD | Sized to largest expected matter |
| Database | Same volume as OS is acceptable | — |

If evidence is copied directly from a network mount (the typical workflow), no local evidence staging storage is required.

---

## PCIe Slot Planning

The PEXUSB3S44V is a PCIe x4 card and is compatible with any x4, x8, or x16 physical slot.

| Tier | Cards | Slots Required | Compatible Boards |
|---|---|---|---|
| ECUBE-4 | 1 | 1× PCIe x4 or wider | A2SDi-2C-HLN4F, A2SDi-4C-HLN4F, X11SDV-4C-TLN2F |
| ECUBE-8 | 2 | 2× PCIe x4 or wider | A2SDi-4C-HLN4F, X11SDV-4C-TLN2F |
| ECUBE-12 | 3 | 3× PCIe x4 or wider | X11SDV-4C-TLN2F |

Space cards to allow airflow between them. The X11SDV-4C-TLN2F routes all three PCIe slots through a PLX bridge — this does not affect USB performance because USB host controllers generate short bursts of control traffic, not sustained PCIe bandwidth.

---

## Power Supply and Chassis

All three boards use the mini-ITX form factor and operate from a standard ATX power supply.

- **Minimum PSU:** 250 W (ECUBE-4 / ECUBE-8); 300 W (ECUBE-12)
- **+12 V rail connectors needed:** 1 SATA or LP4 per USB card (for the card's auxiliary power)
- **Chassis:** Any mini-ITX or micro-ATX chassis with sufficient PCIe slot clearance

A fanless or low-noise chassis is suitable for ECUBE-4 given the C3338's 15 W TDP. ECUBE-12 with the Xeon-D 2123IT (35 W) benefits from active cooling.

---

## Related Documentation

- [Deployment Architecture](../marketing/deployment-architecture.md) — deployment profiles (air-gapped, enterprise separated, containerized) and network hardware sizing
- [Installation Guide](03-installation.md) — OS and application installation procedures
- [Package Deployment](04-package-deployment.md) — deploying from a GitHub release package

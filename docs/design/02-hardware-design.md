# 2. Hardware Design

| Field | Value |
|---|---|
| Title | Hardware Design |
| Purpose | Defines how ECUBE hardware is built and integrated, including component selection, model profiles, PCIe topology, thermal behavior, and wiring architecture. |
| Updated on | 04/08/26 |
| Audience | Engineers, manufacturing, and QA teams. |

## 2.1 Audience and Scope

### 2.1.1 Primary Audience

- Engineers defining and integrating host hardware, I/O, and platform interfaces.
- Manufacturing teams assembling, validating, and reproducing hardware builds.
- QA teams validating hardware behavior, tolerance, and recovery profiles.

### 2.1.2 Scope

- Define reference hardware architecture and build composition for ECUBE deployment units.
- Define subsystem composition for compute, storage, removable-media I/O, and network I/O.
- Define PCIe and bus-topology mapping requirements used for predictable runtime behavior.
- Define thermal and power design constraints for sustained export workloads.
- Define wiring and port-mapping architecture to preserve deterministic device identity.

### 2.1.3 Explicit Exclusions

- Business justification for why the product exists.
- User stories, persona narratives, and product-planning rationale.
- Non-technical go-to-market or procurement policy commentary.

## 2.2 Compute and Chassis Design

### 2.2.1 Platform Composition

- Build around a dedicated host platform with predictable CPU, memory, storage, and I/O behavior.
- Use motherboard and chassis combinations that provide stable high-throughput external I/O paths.
- Use serviceable component layouts that permit maintenance without rewiring unrelated subsystems.

### 2.2.2 Reference Model Profiles

- Define at least one baseline model profile and one high-throughput model profile.
- Each profile must specify CPU class, memory class, storage class, and external I/O capability class.
- Manufacturing outputs must bind each produced unit to a declared model profile for traceability.

## 2.3 PCIe and I/O Topology Design

### 2.3.1 PCIe Mapping Strategy

- Allocate PCIe lanes so removable-media I/O, network I/O, and storage I/O avoid destructive contention under expected concurrency.
- Prefer direct CPU-connected lanes for high-priority removable-media and network controllers where available.
- Document topology decisions as a PCIe map artifact per approved hardware profile.

### 2.3.2 Bus and Controller Isolation

- Isolate critical I/O paths so a failure or saturation in one peripheral path does not mask device events on unrelated paths.
- Keep controller placement and root-complex mapping stable across production-equivalent builds.

## 2.4 USB and Removable-Media Design

### Port Identity Strategy

- Physically label hubs and ports to match software-visible identity conventions.
- Persist stable hub identity and port ordinals as the canonical physical-to-logical mapping basis.
- Resolve runtime block-device aliases dynamically; do not depend on transient device names.

### State Model

- `EMPTY` when no removable media is present on the mapped port.
- `AVAILABLE` when media is detected, validated, and eligible for assignment.
- `IN_USE` when media is actively assigned to an export workflow.

### Event Handling

- On insertion: detect media, evaluate usability signals, and bind to stable port identity.
- On removal: invalidate media bindings, preserve historical assignment traceability, and mark port `EMPTY`.
- On transient disconnect/reconnect: preserve deterministic remapping behavior and avoid cross-port ambiguity.

### Filesystem Detection

- Detect filesystem type using OS-backed probes with canonicalized reporting.
- Represent unrecognized media as `unformatted` and detection failure as `unknown`.
- Persist filesystem detection outputs on each discovery cycle for deterministic downstream behavior.

## 2.5 Thermal and Power Design

### 2.5.1 Thermal Envelope

- Design for sustained copy/verify workloads without thermal runaway or prolonged throttling.
- Size cooling paths (intake, exhaust, heatsink/fan profile) for worst-case concurrent I/O and CPU utilization.
- Define thermal alert thresholds and validation tests for production qualification.

### 2.5.2 Power Stability

- Provide stable power delivery margins for host, storage, and connected removable-media subsystems.
- Avoid over-subscription conditions that cause intermittent controller resets under peak I/O demand.

## 2.6 Wiring and Assembly Design

### 2.6.1 Internal Wiring

- Route power and data wiring to minimize accidental disconnection during service operations.
- Use consistent cable classes and retention mechanisms across production units.

### 2.6.2 External Port Wiring and Labeling

- Keep external wiring and hub orientation reproducible across units.
- Ensure physical labeling maps directly to configured logical port identity.
- Define assembly acceptance checks that verify physical-to-logical mapping before release.

## 2.7 Manufacturing and QA Verification Design

- Manufacturing verification must confirm component/model/profile match and PCIe-map conformance.
- QA verification must include thermal-soak, sustained I/O, hot-plug behavior, and restart reconciliation checks.
- Build records must retain profile, controller-map, and validation evidence for traceability.

## References

- [docs/requirements/02-hardware-requirements.md](../requirements/02-hardware-requirements.md)

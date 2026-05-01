# 18. ECUBE Cloud Copy Engine Requirements And Specification

| Field | Value |
|---|---|
| Document Title | ECUBE Cloud Copy Engine — Requirements & Specification |
| Version | 1.0 DRAFT |
| Date | May 2026 |
| Status | Draft for Review |
| Author | ECUBE Engineering Team |
| Reviewers | TBD |
| Approval | TBD |

## Terminology Convention

This document follows RFC 2119 keyword conventions. The words **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are to be interpreted as described in RFC 2119 when they appear in uppercase bold.

## 1. Purpose

This document defines the requirements, architecture, and behavioral specification for the **Cloud Copy Engine** component of the ECUBE system. The Cloud Copy Engine is responsible for downloading content from cloud-based sources and writing that content directly to USB storage devices, with no intermediate staging to local disk.

This specification serves as the **authoritative reference** for the development, testing, and integration of the Cloud Copy Engine. All implementation decisions, test plans, and integration contracts should trace back to requirements enumerated in this document.

The intended audience includes software engineers, QA engineers, system architects, and technical project managers working on the ECUBE platform.

## 2. Scope

### 2.1 In Scope

The following capabilities and concerns are within the scope of this specification:

- Cloud-to-USB data transfer, including streaming download and direct write
- Transactional file writing (commit/rollback semantics)
- Download management: authentication, retry, throttling, and error recovery
- Memory buffer pool management and backpressure
- Per-device worker lifecycle: creation, execution, draining, and teardown
- Small-file batching for write optimization
- Fairness scheduling across multiple connected USB devices
- Integration with the Shared Verification Service for post-write integrity checks
- Integration with the Shared Logging Service for chain-of-custody records
- Integration with the Job Scheduler for work assignment and progress reporting
- Integration with the Device Manager for device handle acquisition and status
- Integration with the Cloud Authentication Service for token management
- Pause, resume, and cancel operations at the job level

### 2.2 Out Of Scope

The following are explicitly **out of scope** for this document and are handled by other ECUBE components:

- **USB device enumeration and detection** — Handled by the Device Manager
- **Local-to-USB file copies** — Handled by the Local Copy Engine
- **Verification algorithm implementation** (hash computation, integrity algorithms) — Handled by the Shared Verification Service
- **User interface and UX layer** — Handled by the ECUBE UI module
- **USB device formatting or partitioning** — Handled by the Device Manager
- **Cloud account provisioning and user authentication** — Handled by the Cloud Authentication Service

## 3. System Context And Architecture Overview

### 3.1 Position In The ECUBE Architecture

The Cloud Copy Engine is one of several copy engines within the ECUBE platform. It occupies the data-plane layer between **cloud content sources** (cloud storage APIs, content delivery endpoints) and **USB storage devices** (flash drives, external HDDs/SSDs). It is a peer to the Local Copy Engine, which handles local-to-USB transfers, and both engines share common infrastructure services.

The Cloud Copy Engine does not directly interact with end users. It receives work assignments from the Job Scheduler, operates on USB devices managed by the Device Manager, and delegates verification and logging to shared platform services.

### 3.2 Dependencies

The Cloud Copy Engine depends on the following ECUBE services:

| Service | Role |
|---|---|
| Device Manager | Provides device handles, device status queries, write-readiness signals, and device removal notifications. The Cloud Copy Engine does not enumerate or manage devices directly. |
| Shared Verification Service | Performs hash computation and integrity checks on written files. The Cloud Copy Engine submits verification requests and receives pass/fail results. It does not implement any hash algorithms internally. |
| Shared Logging Service | Receives structured chain-of-custody records and operational log entries from the Cloud Copy Engine. Provides durable, immutable log storage. |
| Job Scheduler | Assigns file sets (jobs) to the Cloud Copy Engine, manages work distribution and fairness across devices, and receives progress and completion reports. |
| Cloud Authentication Service | Provides and refreshes access tokens for cloud content sources. The Cloud Copy Engine requests tokens before download operations and handles token expiration transparently. |
| Configuration Service | Supplies runtime configuration parameters (buffer sizes, retry policies, thresholds, throttling limits) to the Cloud Copy Engine. |

### 3.3 Data Flow

The end-to-end data flow for a cloud-to-USB copy operation proceeds as follows:

1. **Job Assignment:** The Job Scheduler assigns a file set (job) to the Cloud Copy Engine, specifying the list of files, their cloud source identifiers, expected sizes, and expected hashes.
2. **Device Allocation:** The Job Scheduler identifies target USB devices. The Cloud Copy Engine acquires device handles from the Device Manager and spawns a per-device worker for each device.
3. **Authentication:** The Cloud Copy Engine obtains or refreshes access tokens for the relevant cloud source(s) via the Cloud Authentication Service.
4. **Download & Stream:** The Cloud Copy Engine initiates asynchronous downloads from the cloud source. Downloaded data streams into pre-allocated memory buffers from the buffer pool. **No data is written to local/intermediate disk.**
5. **Direct USB Write:** As buffers fill, the per-device worker writes data directly to the target USB device. Each file write is transactional — either the entire file is committed or the operation is rolled back, leaving no partial files.
6. **Small-File Batching:** Files below the configurable small-file threshold are accumulated into a batch buffer. The batch is flushed to the USB device as a single transactional write operation.
7. **Verification:** After a successful write, the Cloud Copy Engine submits a verification request to the Shared Verification Service, providing the file path on the USB device and the expected hash from the cloud source.
8. **Chain-of-Custody Logging:** The Cloud Copy Engine constructs a chain-of-custody record capturing every detail of the operation (source, timestamps, hashes, byte counts, device ID, verification result) and submits it to the Shared Logging Service.
9. **Progress Reporting:** The Cloud Copy Engine reports file-level and job-level progress back to the Job Scheduler.
10. **Completion:** When all files in the job are written and verified (or have exhausted retries), the Cloud Copy Engine reports job completion or failure to the Job Scheduler and releases device handles.

### Key Architectural Constraint

The Cloud Copy Engine **SHALL NOT** stage any downloaded content on local disk. All data flows from cloud source -> memory buffer -> USB device. This constraint is fundamental to the system design and eliminates local disk as a point of failure, a storage bottleneck, and a security concern.

## 4. Functional Requirements

The following functional requirements define the mandatory behaviors of the Cloud Copy Engine. Each requirement is uniquely identified for traceability.

| ID | Requirement |
|---|---|
| ECCE-001 | The engine **SHALL** download files from cloud sources and write them directly to USB storage devices without intermediate local disk staging. Data **SHALL** flow exclusively through memory buffers. |
| ECCE-002 | All write operations to USB devices **SHALL** use a single, unified write path regardless of the file source, file type, or file size. There **SHALL NOT** be separate code paths for different file categories. |
| ECCE-003 | Each file write **SHALL** be transactional. On success, the file is fully committed to the USB device. On failure, the operation **SHALL** be rolled back cleanly, leaving no partial, corrupt, or orphaned files on the device. |
| ECCE-004 | The engine **SHALL** support concurrent writes to multiple USB devices by assigning a dedicated per-device worker to each connected target device. |
| ECCE-005 | Each per-device worker **SHALL** operate independently with its own I/O context and buffer references. Failure, slowdown, or error state of one worker **SHALL NOT** affect the operation of any other worker. |
| ECCE-006 | The engine **SHALL** batch small files (those below a configurable size threshold, default 256 KB) into grouped write operations. Each batch **SHALL** be written as a single transactional unit. |
| ECCE-007 | After every successful file write, the engine **SHALL** submit a verification request to the Shared Verification Service, providing the file path on the USB device and the expected hash from the cloud source metadata. |
| ECCE-008 | The engine **SHALL** produce a chain-of-custody log entry for every file operation, recording the full lifecycle from download initiation through verification result. Records **SHALL** be submitted to the Shared Logging Service. |
| ECCE-009 | The engine **SHALL** support pause, resume, and cancel operations at the job level. Pause **SHALL** halt new downloads and writes while allowing in-flight transactional writes to complete. Resume **SHALL** continue from the last uncommitted file. Cancel **SHALL** abort all operations and clean up any uncommitted writes. |
| ECCE-010 | The engine **SHALL** report progress at both the individual file level (bytes transferred, percentage complete) and the overall job level (files completed, files remaining, estimated time remaining). |
| ECCE-011 | The engine **SHALL** handle cloud source authentication transparently, obtaining access tokens from the Cloud Authentication Service before download operations and refreshing tokens automatically when they expire or are near expiration. |
| ECCE-012 | The engine **SHALL** retry failed downloads according to a configurable retry policy, including maximum retry count, exponential backoff, and jitter. Retry behavior **SHALL** be per-file, not per-job. |
| ECCE-013 | When multiple USB devices are connected, the engine **SHALL** respect fairness scheduling as directed by the Job Scheduler. Work distribution **SHALL** consider device speed and current queue depth so that no single device starves while others are idle. |
| ECCE-014 | Before initiating a download, the engine **SHALL** validate file metadata received from the job manifest, including file name, expected size, and expected hash. Files with missing or invalid metadata **SHALL** be rejected and logged. |
| ECCE-015 | The engine **SHALL** support configurable bandwidth throttling per cloud source, limiting the aggregate download rate (in bytes per second) to prevent exceeding source-imposed rate limits or consuming excessive network bandwidth. |
| ECCE-016 | The engine **SHALL** use asynchronous I/O for all download and write operations. No download or USB write operation **SHALL** block the main thread, worker management threads, or other device workers. |
| ECCE-017 | The engine **SHALL** implement a circuit breaker pattern for both cloud sources and USB devices. If a source or device exceeds a configurable failure threshold within a rolling window, the engine **SHALL** pause operations for that source/device and raise an alert to the Job Scheduler. |
| ECCE-018 | The engine **SHALL** gracefully handle device removal during a write operation by aborting the affected worker, logging the event, and continuing operations on all other devices without interruption. |
| ECCE-019 | The engine **SHALL** validate that sufficient free space exists on the target USB device before beginning a file write or batch write. If insufficient space is detected, the write **SHALL** be deferred and the condition reported to the Job Scheduler. |
| ECCE-020 | The engine **SHALL** support resumable downloads where the cloud source supports HTTP range requests. If a download is interrupted and retried, the engine **SHOULD** resume from the last successfully received byte offset rather than restarting from the beginning. |

## 5. Non-Functional Requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-001 | Performance | The engine **SHALL** sustain aggregate write throughput of at least 80% of the theoretical USB bus bandwidth when writing to a single device with a fast cloud source. For USB 3.0 devices, the target is >=300 MB/s sustained sequential write throughput (device hardware permitting). |
| NFR-002 | Performance | For small-file batches, the engine **SHALL** achieve a per-file latency overhead of no more than 5 ms (excluding network download time), measured from buffer availability to write commitment. |
| NFR-003 | Scalability | The engine **SHALL** support concurrent operations on up to 32 USB devices simultaneously without degradation of per-device throughput beyond 10% compared to single-device operation. |
| NFR-004 | Reliability | In the event of an engine crash or unexpected termination, no corrupt or partial files **SHALL** remain on any USB device. The transactional write mechanism **SHALL** ensure that only fully committed files persist. |
| NFR-005 | Memory | The engine **SHALL** operate within a bounded memory envelope. Total buffer pool memory **SHALL NOT** exceed a configurable ceiling (default: 64 MB). The engine **SHALL NOT** allocate unbounded memory under any workload condition. |
| NFR-006 | Resource Efficiency | Under full load (maximum concurrent downloads and device writes), the engine **SHOULD** maintain CPU utilization below 25% of a single core for engine orchestration logic (excluding I/O wait and OS-level I/O processing). |
| NFR-007 | Observability | The engine **SHALL** expose runtime metrics suitable for monitoring, including: active worker count, buffer pool utilization, download throughput per source, write throughput per device, retry counts, error counts, and job progress percentages. |
| NFR-008 | Testability | All engine components **SHALL** be unit-testable with mock I/O interfaces. Cloud sources, USB devices, and shared services **SHALL** be abstracted behind interfaces that can be replaced with test doubles. |
| NFR-009 | Portability | The engine **SHALL** target Windows as the primary platform. Platform-specific I/O operations **SHALL** be isolated behind abstraction layers to enable future cross-platform support (Linux, macOS) without rewriting core logic. |
| NFR-010 | Security | Cloud credentials and access tokens **SHALL NOT** be written to USB devices, logged in chain-of-custody records, or persisted in any non-secure storage. Tokens **SHALL** be held only in memory and cleared after use. |
| NFR-011 | Security | Buffers **SHALL** be zeroed upon return to the buffer pool to prevent data leakage between file operations. |
| NFR-012 | Maintainability | The single unified write path (ECCE-002) **SHALL** be the sole mechanism for USB writes across the entire Cloud Copy Engine codebase. This constraint **SHALL** be enforced by code review policy and automated static analysis. |
| NFR-013 | Reliability | The engine **SHALL** support graceful shutdown. Upon receiving a shutdown signal, the engine **SHALL** complete or roll back all in-flight transactions, drain all device workers within a configurable timeout, and release all resources before exiting. |

## 6. Threading Model

### 6.1 Per-Device Worker Architecture

The Cloud Copy Engine assigns one dedicated worker to each USB device that is an active target for write operations. Workers are created when the Job Scheduler assigns work to a device and are torn down when the device is released, the job completes, or the device is removed.

Each device worker encapsulates:

- A reference to the device handle (obtained from the Device Manager)
- An independent write queue of file operations assigned to that device
- Its own async I/O context for USB write operations
- Per-device retry counters, progress state, and error state

Workers do not share USB I/O paths. A slow or failing device worker does not contend with or block any other worker. This isolation is a core design principle.

### 6.2 Async I/O Model

All I/O operations in the Cloud Copy Engine use **async/await** patterns. This applies to:

- **Cloud downloads:** HTTP requests to cloud sources are fully asynchronous. Download streams are consumed asynchronously, filling buffers without blocking threads.
- **USB writes:** Writes to USB devices use asynchronous file I/O APIs. The device worker awaits write completion without occupying a thread during the I/O wait.
- **Verification requests:** Submissions to the Shared Verification Service are asynchronous. The engine can continue writing other files while verification proceeds.
- **Logging:** Chain-of-custody record submissions are fire-and-forget with async acknowledgment. Logging does not block the write pipeline.

No blocking I/O calls **SHALL** be made on the main engine thread, on worker management threads, or within device worker execution contexts.

### 6.3 Thread Pool Considerations

The engine uses two logically separate thread pool categories:

| Pool | Sizing | Purpose |
|---|---|---|
| Download Pool | Bounded; default 8 concurrent downloads (configurable via MaxConcurrentDownloads) | Handles concurrent HTTP download streams from cloud sources. Bounded to prevent overwhelming cloud source rate limits or local network bandwidth. |
| Device Worker Pool | One thread per active device; max 32 (configurable via MaxConcurrentDevices) | Each device worker runs in its own async execution context. Workers are lightweight due to async I/O — they do not block on write operations. |

The download pool and the device worker pool are independent. Downloads feed buffers; device workers consume buffers. The buffer pool (Section 7) serves as the coordination point between these two pools.

### 6.4 Synchronization

The engine is designed for **minimal shared state** between workers:

- **Buffer pool:** The shared buffer pool uses a thread-safe concurrent collection (e.g., `ConcurrentQueue`) for buffer checkout/return. No lock contention under normal load.
- **Job-level state:** Job progress counters and file status maps are protected by lightweight locks or concurrent data structures. These are updated infrequently relative to I/O operations.
- **Write path:** The unified write path has **no shared mutable state** during execution. Each invocation operates on its own buffer, its own device handle, and its own file metadata. No locks are acquired on the write path itself.
- **Metrics:** Metrics counters use atomic operations (interlocked increments) rather than locks.

### 6.5 Cancellation

The engine uses **cooperative cancellation** via cancellation tokens:

- A master cancellation token is created for each job.
- Each device worker receives a linked cancellation token that is triggered either by job-level cancellation or individual device-level cancellation (e.g., device removal).
- Cancellation tokens are propagated through the entire async pipeline: download operations, buffer waits, write operations, and verification requests all check for cancellation.
- When cancellation is requested, in-flight transactional writes complete or roll back (they are not forcibly interrupted mid-write). Downloads in progress are aborted at the next await point.

## 7. Buffer Management

### 7.1 Buffer Pool Design

The Cloud Copy Engine uses a **pre-allocated buffer pool** to manage memory for download and write operations. The buffer pool is allocated at engine startup and provides a fixed inventory of reusable byte buffers.

Key design properties:

- **Pre-allocation:** All buffers are allocated at startup to avoid garbage collection pressure and memory fragmentation during operation. No new buffers are allocated after initialization.
- **Checkout/return semantics:** When a download operation needs a buffer, it checks one out from the pool. When a write operation completes, the buffer is zeroed and returned to the pool.
- **Thread-safe:** The pool uses a lock-free concurrent collection to support concurrent checkout and return from multiple download and writer threads.

### 7.2 Buffer Sizing

| Parameter | Default | Rationale |
|---|---|---|
| Individual buffer size | 1 MB | Aligned to USB bulk transfer sizes for optimal write performance. Large enough to amortize per-write overhead; small enough to allow fine-grained backpressure. |
| Buffer pool count | 64 buffers | Supports up to 8 concurrent downloads and 32 concurrent device writers with sufficient buffer headroom. |
| Total memory ceiling | 64 MB | 64 buffers × 1 MB = 64 MB. This is the maximum memory the buffer pool will consume. It is capped and configurable. |

### 7.3 Backpressure

If all buffers are currently checked out (in use by downloads or writes), the download pipeline **SHALL** apply backpressure:

- The download operation awaits buffer availability asynchronously (it does not spin or block a thread).
- If no buffer becomes available within a configurable timeout, the download is paused (not failed).
- Backpressure naturally throttles the download rate to match the USB write rate, preventing unbounded memory growth.

Under no circumstances does the engine allocate buffers outside the pool. The memory envelope is strictly bounded.

### 7.4 Small-File Batching

Files smaller than the configurable small-file threshold (default: 256 KB) are eligible for batching:

- Multiple small files are packed sequentially into a single buffer.
- The batch is flushed to the USB device as a **single transactional write**. Either all files in the batch are committed, or the entire batch is rolled back.
- Batching reduces per-file USB write overhead (command overhead, seek time on rotational media) and minimizes write amplification.
- A batch is flushed when: (a) the buffer is full, (b) a configurable batch timeout expires, or (c) there are no more small files in the queue.

### Design Note

Small-file batching does not violate the single-write-path constraint (ECCE-002). Batched writes still flow through the same unified write path — the batch buffer is simply treated as a single write payload containing multiple logical files.

## 8. Verification Pipeline

### 8.1 Shared Verification Service Integration

Post-write verification is **not** implemented within the Cloud Copy Engine. All integrity verification is performed by the **Shared Verification Service**, which is a common platform service used by all copy engines in the ECUBE system (cloud, local, and any future engines).

This design ensures:

- Consistent verification behavior across all copy engines
- Single point of maintenance for hash algorithms and verification logic
- Clear separation of concerns: the Cloud Copy Engine writes; the Shared Verification Service verifies

### 8.2 Verification Workflow

After a successful transactional write, the Cloud Copy Engine executes the following verification sequence:

1. **Submit request:** The engine sends a verification request to the Shared Verification Service containing:
   - The file path on the USB device
   - The device handle/identifier
   - The expected hash value (obtained from cloud source metadata)
   - The hash algorithm identifier (e.g., SHA-256)
2. **Async processing:** Verification is asynchronous. The engine continues writing other files to the same or other devices while verification proceeds. The engine does not block waiting for verification results.
3. **Receive result:** The Shared Verification Service returns a result (pass or fail) with the computed hash. The engine receives this via callback or polling.
4. **Record result:** The verification result is recorded in the chain-of-custody log entry for the file.

### 8.3 Verification Failure Handling

When verification fails (computed hash does not match expected hash):

- The engine marks the file as **verification-failed** in the job manifest.
- The hash mismatch details (expected vs. actual) are logged in the chain-of-custody record.
- The file is enqueued for **retry** (re-download and re-write, not simply re-verification), since a verification failure implies the written data is suspect — the corruption may have occurred during download or write.
- If the file exceeds its maximum retry count, it is marked as permanently failed and the failure is escalated to the Job Scheduler.

### Critical Constraint

The Cloud Copy Engine **SHALL NOT** implement any hash algorithms internally. It **SHALL NOT** compute hashes, compare hashes, or make pass/fail determinations. All such logic resides in the Shared Verification Service.

## 9. Retry Logic

### 9.1 Cloud Download Retry Policy

Failed cloud downloads are retried according to the following policy:

| Parameter | Default | Description |
|---|---|---|
| Max retry count | 3 | Maximum number of retry attempts per file per download failure. |
| Backoff strategy | Exponential with jitter | Wait time doubles with each retry, plus a random jitter component (0–25% of the base interval) to avoid thundering herd effects. |
| Backoff base | 1,000 ms | Initial wait time before the first retry. |
| Backoff maximum | 30,000 ms | Upper bound on wait time regardless of retry count. |

Transient errors (HTTP 429, 500, 502, 503, 504, network timeouts) are retried. Permanent errors (HTTP 400, 403, 404, 410) are **not** retried — the file is immediately marked as failed.

### 9.2 USB Write Retry Policy

USB write failures are retried with a more conservative policy, since device-level errors are frequently non-transient (e.g., device disconnect, hardware failure, bad sectors):

- **Max retry count:** 2 (default). USB write errors are less likely to be transient than network errors.
- **No backoff:** Retries are immediate, since USB write failures are either recoverable quickly or not at all.
- **Escalation:** If write retries are exhausted for a file, the error is escalated. If multiple files fail on the same device, the circuit breaker triggers device-level failure (see Section 9.4).

### 9.3 Verification Failure Retry Policy

A verification failure triggers a **full re-download and re-write** of the file, not merely a re-verification. The rationale is that a hash mismatch means the data on the USB device does not match the source, and re-reading the same corrupt data would produce the same mismatch.

- **Max retry count:** 2 (default). After 2 re-download-and-rewrite cycles fail verification, the file is marked as permanently failed.
- **Each retry consumes one count from a separate verification-retry counter**, independent of the download retry counter.

### 9.4 Circuit Breaker

The engine implements the **circuit breaker pattern** for both cloud sources and USB devices:

- If a cloud source accumulates more than **N** failures (default: 5) within a rolling window, the circuit breaker trips. All downloads from that source are paused for a configurable cooldown period (default: 60 seconds).
- If a USB device accumulates more than **N** write failures, the circuit breaker trips. The device worker is paused, and an alert is raised to the Job Scheduler. Remaining files for that device may be reassigned.
- After the cooldown period, the circuit breaker transitions to a **half-open** state and allows a single test operation. If it succeeds, the circuit resets. If it fails, the circuit re-opens for another cooldown cycle.

## 10. Logging And Chain-Of-Custody

### 10.1 Chain-Of-Custody Record Structure

Every file operation produces a **chain-of-custody record** that captures the complete lifecycle of the file from cloud source to USB device. The following fields are included in each record:

| Field | Type | Description |
|---|---|---|
| Job ID | GUID | Unique identifier for the parent job. |
| File ID | GUID | Unique identifier for this file within the job. |
| Source Cloud URL/ID | String | The cloud source URL or object identifier from which the file was downloaded. |
| Source Hash | String | The expected hash value as reported by the cloud source metadata. |
| Download Start Timestamp | ISO 8601 | UTC timestamp when the download operation began. |
| Download End Timestamp | ISO 8601 | UTC timestamp when the download operation completed (or failed). |
| Bytes Downloaded | Long | Total bytes received from the cloud source. |
| Buffer ID | Int | Identifier of the buffer pool slot used for this transfer. |
| Write Start Timestamp | ISO 8601 | UTC timestamp when the USB write operation began. |
| Write End Timestamp | ISO 8601 | UTC timestamp when the USB write was committed (or rolled back). |
| USB Device ID | String | Unique identifier of the target USB device. |
| File Path on Device | String | The full file path where the file was written on the USB device. |
| Verification Request ID | GUID | Unique identifier of the verification request submitted to the Shared Verification Service. |
| Verification Result | Enum | Outcome of verification: `Pass`, `Fail`, or `Pending`. |
| Verification Hash | String | The actual hash computed by the Shared Verification Service (populated upon verification completion). |
| Final Status | Enum | Final outcome: `Success`, `Failed`, `Cancelled`, `Skipped`. |
| Retry Count | Int | Number of retry attempts made for this file (download + write + verification retries combined). |

### 10.2 Logging Mechanism

- **Submission:** Chain-of-custody records are formatted by the Cloud Copy Engine and submitted to the Shared Logging Service. The engine does not store or persist logs locally.
- **Immutability:** Once a chain-of-custody record is submitted, it is **immutable**. Updates (e.g., verification results arriving after initial submission) are recorded as supplementary entries linked by File ID, not as modifications to the original record.
- **Format:** Records are serialized as structured JSON for machine parseability and long-term archival.

### 10.3 Operational Logs

In addition to chain-of-custody records, the engine produces **operational logs** for debugging and monitoring. These are separate from chain-of-custody and serve different purposes:

| Log Level | Usage |
|---|---|
| Trace | Buffer checkout/return, individual I/O operation details, async state transitions. |
| Debug | Worker lifecycle events, retry decisions, backpressure triggers, batch composition. |
| Info | Job start/complete, device worker start/stop, file write committed, verification pass. |
| Warning | Transient download failures, retry attempts, token refresh, circuit breaker state changes. |
| Error | Permanent download failures, write failures after retry exhaustion, verification failures after retry exhaustion. |
| Critical | Device removal during write, circuit breaker tripped, buffer pool exhaustion, engine-level unhandled exceptions. |

## 11. Error Handling

### 11.1 Error Categories

| Category | Transient? | Examples | Handling |
|---|---|---|---|
| Transient Cloud Errors | Yes | HTTP 429 (rate limit), 500, 502, 503, 504; network timeout; connection reset | Retry with exponential backoff and jitter per download retry policy. |
| Permanent Cloud Errors | No | HTTP 400 (bad request), 403 (forbidden), 404 (not found), 410 (gone) | Mark file as permanently failed. No retry. Log and report to Job Scheduler. |
| Authentication Errors | Sometimes | HTTP 401 (unauthorized); expired token; invalid credentials | Attempt token refresh via Cloud Authentication Service. If refresh fails, escalate to permanent failure for the source. |
| USB Write Errors | Rarely | I/O exception; write timeout; bad sector | Retry with limited attempts. Escalate to device-level failure if threshold exceeded. |
| Verification Mismatch | N/A | Computed hash does not match expected hash | Re-download and re-write the file. Mark as failed after retry exhaustion. |
| Out-of-Space | No | USB device has insufficient free space for the file or batch | Defer write. Report condition to Job Scheduler. Do not retry until space is confirmed available. |
| Device Removal | No | USB device physically removed or disconnected during operation | Abort the affected device worker immediately. Roll back any in-flight transaction. Log the event as Critical. Continue operations on all other devices. |
| Metadata Validation Failure | No | File metadata missing required fields; size or hash format invalid | Reject the file before download. Mark as Skipped with reason. Log and report. |

### 11.2 Error Propagation

Errors propagate through the system in a structured hierarchy:

- **Operation level:** Individual download or write failures are caught by the operation handler and either retried (if policy allows) or marked as failed.
- **File level:** If all retries for a file are exhausted, the file is marked as failed in the job manifest. The per-file failure is recorded in the chain-of-custody log.
- **Device level:** If the circuit breaker trips for a device, the device worker is paused or stopped. The Job Scheduler is notified so it can reassign remaining files.
- **Job level:** Job-level error aggregation reports the total count and nature of failures. The job can be configured to either **continue on error** (default) or **fail-fast** (stop the entire job on the first file failure).

### 11.3 Graceful Degradation

The engine is designed for maximum resilience through isolation:

- One device failure **SHALL NOT** stop work on other devices.
- One file failure **SHALL NOT** stop the job (unless the job is configured for fail-fast behavior).
- One cloud source failure **SHALL NOT** affect downloads from other cloud sources (if the job spans multiple sources).
- Buffer pool exhaustion causes backpressure (slower downloads), not crashes or data loss.

## 12. Integration Points

The following table summarizes all external service integration points for the Cloud Copy Engine:

| Service | Operations | Direction | Notes |
|---|---|---|---|
| Device Manager | Acquire device handle; query device status (free space, write speed); receive device removal notifications; release device handle | Bidirectional | The Cloud Copy Engine subscribes to device removal events for immediate worker teardown. Device handles are opaque references — the engine does not manage device state. |
| Shared Verification Service | Submit verification request (file path, expected hash, algorithm); receive verification result (pass/fail, computed hash) | Request -> Response (Async) | Verification is asynchronous. The engine does not block while waiting for results. Verification timeout is configurable. |
| Shared Logging Service | Submit chain-of-custody records; submit operational log entries | Outbound | Fire-and-forget with async acknowledgment. Logging failures are recorded locally as a fallback but do not block write operations. |
| Job Scheduler | Receive job assignments (file sets, target devices); report file-level progress; report job completion or failure; receive pause/resume/cancel commands | Bidirectional | The Job Scheduler owns fairness scheduling decisions. The Cloud Copy Engine executes the assigned distribution. |
| Cloud Authentication Service | Request access token for a cloud source; refresh expiring token; report authentication failure | Request -> Response | Tokens are obtained before each download batch. Token caching and refresh timing are managed by the authentication service. |
| Configuration Service | Retrieve engine configuration (buffer sizes, retry policies, thresholds, throttling limits); subscribe to configuration change notifications | Inbound | Configuration is loaded at engine startup and can be refreshed at runtime for select parameters (e.g., throttling limits). Buffer pool size changes require engine restart. |

## 13. Configuration Parameters

The following parameters are configurable at runtime or startup. All parameters are retrieved from the Configuration Service. Parameters marked with an asterisk (*) require engine restart to take effect.

| Parameter Name | Type | Default | Description |
|---|---|---|---|
| BufferSizeBytes * | int | 1,048,576 (1 MB) | Size of each individual buffer in the buffer pool, in bytes. Should be aligned to USB bulk transfer boundaries. |
| BufferPoolMaxCount * | int | 64 | Maximum number of buffers in the pool. Total memory ceiling = BufferSizeBytes × BufferPoolMaxCount. |
| SmallFileBatchThresholdBytes | int | 262,144 (256 KB) | Files smaller than this threshold are eligible for batching into grouped write operations. |
| MaxRetryCountDownload | int | 3 | Maximum number of retry attempts for a failed cloud download, per file. |
| MaxRetryCountWrite | int | 2 | Maximum number of retry attempts for a failed USB write, per file. |
| MaxRetryCountVerification | int | 2 | Maximum number of re-download-and-rewrite cycles after a verification failure, per file. |
| RetryBackoffBaseMs | int | 1,000 | Base interval (in milliseconds) for exponential backoff on download retries. |
| RetryBackoffMaxMs | int | 30,000 | Maximum interval (in milliseconds) for exponential backoff, regardless of retry count. |
| MaxConcurrentDownloads | int | 8 | Maximum number of concurrent cloud download streams active at any time. |
| MaxConcurrentDevices | int | 32 | Maximum number of USB devices the engine can write to concurrently. |
| BandwidthThrottleBytesPerSec | long | 0 (unlimited) | Maximum aggregate download bandwidth in bytes per second. A value of 0 disables throttling. |
| CircuitBreakerFailureThreshold | int | 5 | Number of consecutive failures required to trip the circuit breaker for a cloud source or USB device. |
| CircuitBreakerCooldownMs | int | 60,000 | Duration (in milliseconds) that a tripped circuit breaker remains open before transitioning to half-open. |
| VerificationTimeoutMs | int | 30,000 | Maximum time (in milliseconds) to wait for a verification result from the Shared Verification Service before treating the request as timed out. |
| DeviceWorkerDrainTimeoutMs | int | 10,000 | Maximum time (in milliseconds) to wait for a device worker to drain its queue and complete in-flight writes during shutdown or device release. |
| SmallFileBatchFlushTimeoutMs | int | 500 | Maximum time (in milliseconds) to wait for additional small files before flushing a partially filled batch buffer. |
| ProgressReportIntervalMs | int | 1,000 | Interval (in milliseconds) at which the engine reports job-level progress to the Job Scheduler. |

## 14. Glossary

| Term | Definition |
|---|---|
| ECUBE | The parent platform and product name. ECUBE encompasses all modules for managing content distribution to USB storage devices, including copy engines, device management, verification, logging, and scheduling. |
| Cloud Copy Engine | The ECUBE component responsible for downloading content from cloud-based sources and writing it directly to USB storage devices. The subject of this specification. |
| Device Worker | A dedicated, isolated execution unit assigned to a single USB device. Each device worker manages its own write queue, I/O context, and error state. Workers operate independently to ensure fault isolation. |
| Transactional Write | A write operation with commit/rollback semantics. The entire file (or batch) is either fully written and committed to the USB device, or the operation is rolled back with no partial data remaining. This guarantees that no corrupt or incomplete files exist on the device. |
| Chain-of-Custody | A comprehensive, immutable log record that traces the complete lifecycle of a file from its cloud source through download, buffering, USB write, and verification. Provides an auditable trail for compliance and forensic analysis. |
| Buffer Pool | A pre-allocated, fixed-size collection of reusable memory buffers used to hold downloaded data before writing it to USB devices. The pool eliminates dynamic memory allocation during operation, reducing GC pressure and fragmentation. |
| Backpressure | A flow-control mechanism that slows or pauses upstream producers (cloud downloads) when downstream consumers (USB writes) cannot keep up. In the Cloud Copy Engine, backpressure is applied when all buffers in the pool are in use, preventing unbounded memory growth. |
| Circuit Breaker | A resilience pattern that monitors failure rates for a resource (cloud source or USB device). When failures exceed a threshold, the circuit breaker "trips" and temporarily halts operations to that resource, preventing cascading failures and allowing recovery time. |
| Fairness Scheduling | A work distribution strategy that ensures all connected USB devices receive a proportional share of write operations. No single device starves while others are idle. Fairness considers device speed and current queue depth. |
| Small-File Batch | A group of small files (each below a configurable size threshold) that are packed together into a single buffer and written to the USB device as one transactional unit. Batching reduces per-file overhead and improves write efficiency, especially on devices with high per-operation latency. |

— End of Document —

ECUBE Cloud Copy Engine — Requirements & Specification • Version 1.0 DRAFT • May 2026

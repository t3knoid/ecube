# 4. Functional Requirements — Design

## 4.1 Drive Lifecycle Management

- Implement a finite-state machine for drive states and legal transitions.
- Gate all transitions through a single service module to ensure consistency.

## 4.2 Project Isolation Design (Critical)

- Bind `current_project_id` on initialization and enforce at write time.
- Reject mismatched project writes before copy begins.
- Record denial in `audit_logs` with actor, drive, requested project, and reason.

## 4.3 Job Management Design

- Job entity stores immutable creation metadata plus mutable progress fields.
- File-level records enable resume and per-file retry semantics.

## 4.4 Multi-threaded Copy Engine Design

- Queue file units to worker pool sized by `thread_count`.
- Use atomic progress updates (`copied_bytes`, file status transitions).
- Verify checksums post-copy and mark verification status.

## 4.5 Network Mount Support Design

- Mount manager validates connectivity before exposing paths to job creation.
- Reference counting prevents unmount while active jobs still depend on a mount.

## 4.6 Manifest Generation Design

- Generate deterministic manifest per job completion (or on-demand regeneration).
- Include source metadata, checksums, byte totals, and generation timestamp.

## 4.7 Audit Logging Design

- Emit structured JSON payloads for all critical operations.
- Use append-only semantics and immutable timestamps.

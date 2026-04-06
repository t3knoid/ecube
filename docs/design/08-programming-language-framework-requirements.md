# 8. Programming Language & Framework Requirements — Design

This document defines the language and framework requirements for ECUBE and the rationale for the selected stack. It does not restate system topology or trust boundaries; those belong in [docs/design/03-system-architecture.md](docs/design/03-system-architecture.md).

## 8.1 Design Goals

The ECUBE stack must support a security-sensitive system that combines HTTP APIs, transactional state management, Linux host integration, hardware-aware workflows, and strong testability. The selected language and frameworks must therefore favor clear service boundaries, explicit data modeling, reliable database migration support, and practical interoperability with Linux tooling.

## 8.2 System Layer Language Requirements

The system-layer language must:

- support a mature Linux runtime environment,
- integrate cleanly with subprocess-based OS tooling and filesystem operations,
- provide strong library support for HTTP APIs, database access, authentication, and testing,
- support both synchronous infrastructure calls and asynchronous web-service execution patterns,
- make it practical to express interface-based abstractions for hardware and OS adapters.

Python is the selected language because it satisfies these requirements with low implementation friction and strong ecosystem support for service-oriented backend development.

## 8.3 API Framework Requirements

The API framework must:

- expose REST endpoints with explicit request and response schemas,
- generate and maintain an accurate OpenAPI contract,
- support dependency injection for auth, repositories, and infrastructure adapters,
- make role-gated and project-isolation checks straightforward to express,
- support background-friendly request handling and startup lifecycle hooks.

FastAPI is the selected API framework because it provides strong schema-driven API development, native OpenAPI generation, and dependency injection patterns that fit ECUBE's service and authorization model.

## 8.4 Persistence Layer Requirements

The persistence layer must:

- model relational state and constraints explicitly,
- support transactional workflows and concurrency-sensitive updates,
- work with Alembic-style schema evolution,
- remain testable against SQLite for fast automated tests while targeting PostgreSQL in production,
- keep repository and service logic independent from raw SQL where practical.

SQLAlchemy with Alembic is selected because it provides a mature ORM and migration toolchain that fits ECUBE's stateful domain model and test strategy.

## 8.5 Background Work Requirements

The job execution framework must support copy, verify, and manifest-generation workflows that may outlive a single HTTP request. It must allow work to be queued, monitored, retried where appropriate, and surfaced back through the API as durable job state.

Celery or RQ remain acceptable design choices because either can satisfy the need for off-request job execution. The design requirement is the queue-backed execution model, not a hard dependency on one specific worker library.

## 8.6 Introspection and Host Integration Requirements

The system layer must be able to inspect CPU, memory, disk, USB, mount, and process-level host information without collapsing host-specific behavior into business logic. Libraries such as `psutil` are appropriate where they simplify safe host introspection, but the key requirement is that host-observation concerns remain in infrastructure-facing modules rather than spreading through route handlers.

OS-specific operations must continue to be expressed through abstract interfaces in `app/infrastructure/` so that service code depends on contracts rather than Linux-specific implementations.

## 8.7 UI Framework Requirements

The UI technology must remain a presentation-layer concern only. It must:

- consume the HTTPS API without direct access to the database or hardware,
- support authenticated routing and role-gated views,
- render long-running job progress and operational status updates,
- support themeable presentation and branding without backend coupling.

Vue, React, or server-rendered templates are all acceptable at the design level provided the UI remains outside the trusted system boundary. The current implementation uses a Vue single-page application because it fits the desired client-side navigation and state-management model.

## 8.8 Database Requirements

The production database must support strong relational integrity, transactional updates, indexes for operational queries, and concurrency semantics suitable for reconciliation and state-transition workflows.

PostgreSQL 14+ is the selected production database because it provides the transactional behavior, indexing, and operational maturity required for ECUBE's authoritative state store.

## 8.9 Selection Principles

Any future change to the ECUBE language or framework stack should be evaluated against these principles:

- preserve the trust boundary between UI, system layer, and database,
- preserve explicit schema and migration management,
- preserve testability without requiring physical hardware for routine automated runs,
- preserve clean separation between business logic and host-specific integrations,
- avoid increasing operational complexity without a clear architectural gain.

# 8. Operational Readiness Requirements

## 8.1 Purpose

This document defines readiness requirements for production ECUBE deployments, covering health signaling, observability, alerting, performance baselines, and go-live gates.

## 8.2 Scope

These requirements apply to production and pre-production environments that host ECUBE API services, worker processes, database dependencies, mount dependencies, and monitoring integrations.

## 8.3 Health and Readiness Signaling

ECUBE must expose health endpoints that distinguish liveness from dependency readiness.

- A liveness endpoint must confirm process availability independent of external dependencies.
- A readiness endpoint must validate critical dependencies required to accept traffic.
- Readiness failures must return a non-success HTTP status and machine-readable reason details.
- Startup behavior must tolerate initialization windows without causing restart loops in service supervisors.

## 8.4 Metrics and Telemetry

ECUBE must emit operational telemetry adequate for capacity and reliability management.

- The system must expose machine-scrapable metrics covering at minimum: jobs, API latency, authentication outcomes, drive and mount status, and database pool behavior.
- Metric names and labels must be stable across patch releases unless a documented compatibility exception is approved.
- Metrics endpoint access must be restricted or segmented according to security policy.
- Metrics cardinality must be controlled to avoid telemetry-induced performance degradation.

## 8.5 Structured Logging and Correlation

Operational logs must support incident diagnosis and audit correlation.

- Service logs must use structured fields including timestamp, level, component, message, and context attributes.
- Request correlation identifiers must be included when available.
- Security-relevant and operationally critical failures must be logged at severity levels suitable for alerting.
- Log forwarding to centralized aggregation must be enabled for production.

## 8.6 Alerting and On-Call Integration

ECUBE production operations must include actionable alerting.

- Alert rules must be defined for service unavailability, dependency health degradation, sustained job failures, and abnormal auth failures.
- Alerts must route to an on-call rotation with severity mapping and acknowledgment workflow.
- Each critical alert class must have a runbook reference maintained by operations.
- Incident records for critical events must be retained for post-incident review.

## 8.7 Performance and Capacity Baselines

Deployments must establish measurable performance expectations before go-live.

- Baseline measurements must include API latency percentiles, copy throughput, job success rate, and recovery time objective.
- Baselines must be captured on representative hardware and datasets.
- Operational thresholds must be tuned from measured baselines and reviewed after significant release changes.

## 8.8 Readiness Gate for Production Promotion

A release may be promoted to production only when readiness checks pass.

- Health, readiness, metrics, logging, alerting, and backup dependencies must pass verification in pre-production.
- Security controls required for production operation must be validated before first live evidence export.
- A documented go-live checklist and sign-off record must exist for each environment.

## 8.9 Acceptance Criteria

A deployment satisfies this requirements document only when all statements below are true.

- Liveness and readiness endpoints are implemented and validated under failure scenarios.
- Metrics are collected, visualized, and retained per operations policy.
- Structured logs are centralized and correlated with request context.
- Alert routing, acknowledgment, and escalation flows are tested.
- Baseline performance and readiness sign-off artifacts are stored with release records.

## 8.10 Traceability

Primary operational reference: [docs/operations/08-operational-readiness.md](../operations/08-operational-readiness.md).
Related requirements: [docs/requirements/04-functional-requirements.md](04-functional-requirements.md), [docs/requirements/06-rest-api-requirements.md](06-rest-api-requirements.md), and [docs/requirements/10-security-and-access-control.md](10-security-and-access-control.md).
# ECUBE Operational Guide

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Systems Administrators, Operators, IT Staff, QA Personnel  

---

## Table of Contents

1. [Introduction](#introduction)
2. [System Overview](#system-overview)
3. [Operations Document Index](#operations-document-index)
4. [Getting Started](#getting-started)
5. [Design Documents](#design-documents)
6. [Support and Resources](#support-and-resources)

---

## Introduction

ECUBE (Evidence Copying & USB Based Export) is a secure, audited platform for exporting eDiscovery data to encrypted USB drives. This document is the central entry point for all ECUBE operational documentation. It provides a high-level overview of the system and directs readers to the detailed companion documents for specific topics.

**Key Characteristics:**

- Secure, single-purpose evidence export appliance
- Centralized audit logging of all operations
- Hardware-aware USB drive and mount management
- Role-based access control (admin, manager, processor, auditor)
- REST API for integration with external systems

---

## System Overview

### Architecture

ECUBE consists of three components:

```text
┌─────────────────────────────────────────────────────────────┐
│ UI Layer (Web Browser)                                      │
│ - Displays job status, drive inventory, audit logs          │
│ - Makes authenticated API calls via HTTPS                   │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTPS (REST API)
┌────────────────────▼────────────────────────────────────────┐
│ System Layer (FastAPI Service)                              │
│ - Validates tokens and authorizations                       │
│ - Manages mounts, drives, copy jobs                         │
│ - Writes audit logs to database                             │
│ - Executes copy operations                                  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ Data & Hardware                                             │
│ - PostgreSQL database (job state, audit logs, drive state)  │
│ - USB drives, NFS/SMB mounts, Linux /dev interfaces         │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. Operator logs in via UI with username/password or SSO token
2. UI authenticates against ECUBE API (`POST /auth/token` → JWT bearer token)
3. API validates credentials via PAM (or OIDC/LDAP)
4. Roles resolved using a **DB-first hybrid model**:
   - Check `user_roles` table for explicit role assignments → use if found
   - Fall back to OS group memberships + `LOCAL_GROUP_ROLE_MAP` → use if found
   - No roles from either source → 403 Forbidden
5. JWT issued with resolved roles
6. Each subsequent API call validates roles from JWT claims
7. Role checked against operation (e.g., "processor" can start jobs, "auditor" can only read)
8. Operation executed (e.g., mount network share, initialize drive, start copy)
9. All actions logged to audit table with timestamp, user, action, result

### Roles

| Role | Key Permissions |
|------|----------------|
| **admin** | Unrestricted access to all operations |
| **manager** | Drive lifecycle, mount management, job oversight |
| **processor** | Create and start jobs, view status |
| **auditor** | Read-only access to audit logs, file metadata |

---

## Operations Document Index

The companion documents below provide in-depth procedures for each operational area. Click through to the relevant document for detailed instructions, commands, and examples.

### [01 — Installation Guide](01-installation.md)

**Audience:** Systems Administrators, IT Staff

Step-by-step prerequisites and installation procedures. Covers hardware requirements (CPU, RAM, disk, USB hub, network), software requirements (OS, kernel, system packages), and deployment options overview. Use this as your starting point before choosing a deployment method (package or Docker).

### [02 — Manual Installation](02-manual-installation.md)

**Audience:** Systems Administrators, IT Staff

Manual procedure for deploying ECUBE as a native systemd service when `install.sh` cannot be used. Covers requirements, service account creation, package verification/extraction, single-host and enterprise split-host layouts, backend/frontend configuration, firewall hardening, upgrades, and advanced alternate web frontend hosting.

### [03 — Docker Deployment](03-docker-deployment.md)

**Audience:** Systems Administrators, IT Staff

Container-based deployment using Docker Compose. Covers quick start, `.env` configuration, starting and stopping containers, log viewing, and references to the USB passthrough design document for Docker-specific hardware access. Recommended for quick testing and evaluation environments.

### [04 — Configuration Reference](04-configuration-reference.md)

**Audience:** Systems Administrators, Operators

Complete reference for every ECUBE environment variable, organized by category: database connection, security and authentication (JWT, secret key rotation), local group-to-role mapping, LDAP configuration, OIDC/SSO integration, session management, copy engine tuning, and logging levels. Each variable lists its default value and a description. Maps 1-to-1 with the `Settings` class in `app/config.py`.

### [05 — TLS Certificates and Let's Encrypt](05-tls-certificates-and-letsencrypt.md)

**Audience:** Systems Administrators, Security Engineers

Certificate operations guide for package deployments: self-signed bootstrap certs, Let's Encrypt/certbot issuance, renewal workflow, hostname/IP validation behavior, split-host proxy TLS notes, firewall prerequisites, and key/cert permission guidance.

### [06 — Security Best Practices](06-security-best-practices.md)

**Audience:** Systems Administrators, Security Engineers

Hardening guide covering network isolation, TLS certificate management, credential management and secret rotation, access control policies, file permission lockdown, audit log monitoring and compliance exports, and firewall configuration (UFW rules for HTTPS and PostgreSQL).

### [09 — Administration Automation Guide](09-administration-automation-guide.md)

**Audience:** Systems Administrators, Operators, Automation Engineers

API-driven and script-oriented runbook for administrative operations after deployment. Covers first-run setup, authentication and role management, OS user/group administration via admin APIs, scripted management of mounts, drives, jobs, and audit queries, plus monitoring, troubleshooting, backup/recovery, and routine maintenance tasks.

### [11 — API Quick Reference](11-api-quick-reference.md)

**Audience:** Developers, Operators

Concise endpoint reference for the ECUBE REST API. Covers interactive API documentation (Swagger UI, ReDoc, OpenAPI schema), authentication requirements, and endpoint tables for drives, mounts, jobs, audit, and introspection — each with HTTP method, path, required role, and description. Includes filter parameters and curl examples.

### [12 — Third-Party Integration Guide](12-third-party-integration.md)

**Audience:** Developers, Integration Engineers

Guide for external system integration workflows using the ECUBE API: authentication, mount/drive selection, job orchestration, polling, verification, and manifest generation patterns.

### [13 — User Manual](13-user-manual.md)

**Audience:** Processors, Managers, Auditors, All End Users

End-user guide for the ECUBE web interface. Covers installation-orientation for users, first access, login, dashboard navigation, drive and mount workflows, export job creation and monitoring, verification and manifests, audit log browsing, and privileged user/system pages. Current draft includes screenshot placeholders for later UI capture.

### [14 — Theme and Branding Guide](14-theme-and-branding-guide.md)

**Audience:** Systems Administrators, Platform Engineers

Operational guide for UI theming and branding configuration. Covers built-in themes, custom theme creation, manifest registration, deployment mounting with `ECUBE_THEMES_DIR`, default-theme behavior, logo configuration (including supported image formats), and validation checklist.

### [08 — Operational Readiness](08-operational-readiness.md)

**Audience:** Operations Engineers, DevOps, Support Teams, Security Officers

Comprehensive guide for production readiness covering health checks and readiness probes, metrics collection (Prometheus), log aggregation, alerting setup, performance baselines, and pre-deployment readiness checklist. Specifies deployment verification steps, SLI targets, and configuration environment variables for a production-ready ECUBE instance.

### [07 — Compliance and Evidence Handling](07-compliance-and-evidence-handling.md)

**Audience:** Legal Teams, Compliance Officers, Evidence Managers, IT Security, Operations

Compliance and regulatory guidance for evidence handling, including mappings to FRCP, HIPAA, GDPR, GLBA and other jurisdictional requirements. Covers chain-of-custody procedures, forensic hashing, evidence integrity preservation, data retention and security, audit and accountability requirements, and incident response/breach notification procedures. **Critical for legal admissibility and audit defensibility.**

### [10 — Production Support Procedures](10-production-support-procedures.md)

**Audience:** Operations Engineers, Database Administrators, Support Teams, On-Call Engineers

Operational runbook for production support covering troubleshooting procedures for common failure modes (service startup, memory usage, job failures, network mounts, API latency), database backup and recovery strategies, application upgrade and migration procedures, security patching and vulnerability management, secrets and key rotation, and disaster recovery scenarios.

### [15 — DBA Data Model Reference](15-dba-data-model-reference.md)

**Audience:** Database Administrators, SQL Support Engineers, Data Governance Teams

Standalone schema reference focused on DBA workflows and SQL support. Includes conceptual, logical, and physical data models, table/object descriptions, integrity constraints, workflow visualizations, and a concise DBML companion file (`docs/database/ecube-schema.dbml`).

---

## Getting Started

Use this guide to find the right document for your task:

| Task | Start Here |
|------|-----------|
| First-time installation | [01 — Installation Guide](01-installation.md) → then [02 — Manual Installation](02-manual-installation.md) or [03 — Docker Deployment](03-docker-deployment.md) |
| Configure environment variables | [04 — Configuration Reference](04-configuration-reference.md) |
| Manage certificates / HTTPS | [05 — TLS Certificates and Let's Encrypt](05-tls-certificates-and-letsencrypt.md) |
| Day-to-day operations (mounts, drives, jobs) | [09 — Administration Automation Guide](09-administration-automation-guide.md) |
| Harden a production deployment | [06 — Security Best Practices](06-security-best-practices.md) |
| Explore the API | [11 — API Quick Reference](11-api-quick-reference.md) or Swagger UI at `/docs` |
| Integrate third-party systems | [12 — Third-Party Integration Guide](12-third-party-integration.md) |
| Manage themes and branding | [14 — Theme and Branding Guide](14-theme-and-branding-guide.md) |
| **Prepare for production deployment** | **[08 — Operational Readiness](08-operational-readiness.md)** (health checks, metrics, alerting, readiness checklist) |
| **Ensure compliance & evidence handling** | **[07 — Compliance and Evidence Handling](07-compliance-and-evidence-handling.md)** (FRCP, HIPAA, GDPR, chain-of-custody, audit requirements) |
| **Troubleshoot issues & support procedures** | **[10 — Production Support Procedures](10-production-support-procedures.md)** (troubleshooting, backup/recovery, upgrade, patching, key rotation) |
| **DBA schema and object reference** | **[15 — DBA Data Model Reference](15-dba-data-model-reference.md)** (conceptual/logical/physical model, workflow diagrams, DBML) |
| Monitor and maintain service | [08 — Operational Readiness](08-operational-readiness.md) § Monitoring & Alerting + [10 — Production Support Procedures](10-production-support-procedures.md) § Troubleshooting |

---

## Other Documentation

| Folder | Description |
|--------|-------------|
| [development/](../development/00-development-guide.md) | Developer setup, repository layout, testing, architecture, coding conventions |
| [testing/](../testing/01-qa-testing-guide-baremetal.md) | QA testing guide (bare-metal) and test-case tracking spreadsheet |
| [requirements/](../requirements/00-overview.md) | Requirements documents |

## Design Documents

For architecture decisions, data model details, and full API specifications, see `docs/design/`:

| Document | Description |
|----------|-------------|
| `03-system-architecture.md` | Component view and interaction patterns |
| `04-functional-requirements.md` | Drive FSM, project isolation, copy engine, audit |
| `05-data-model.md` | Table design and integrity constraints |
| `06-rest-api-specification.md` | Full API endpoint definitions with schemas |
| `10-security-and-access-control.md` | Role model, authorization matrix, `require_roles` pattern |
| `12-runtime-environment-and-usb-visibility.md` | Runtime environment and USB visibility architecture |

---

## Support and Resources

- **GitHub Issues:** <https://github.com/t3knoid/ecube/issues>
- **Repository:** <https://github.com/t3knoid/ecube>
- **Service Logs:** `journalctl -u ecube -f`
- **Database Logs:** PostgreSQL log file (check `postgresql.conf`)
- **API Errors:** Check response JSON for `code`, `message`, and `trace_id` fields

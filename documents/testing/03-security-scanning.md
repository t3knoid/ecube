# ECUBE — Security Scanning

**Audience:** Developers, DevOps, QA  
**Workflows:**
- `.github/workflows/security-scan.yml` — Bandit static analysis + pip-audit dependency scan
- `.github/workflows/schemathesis-fuzz.yml` — Schemathesis (OpenAPI fuzz testing)

---

## Overview

ECUBE provides a set of security and API testing workflows as GitHub Actions. All workflows are **manually triggered** via `workflow_dispatch` from the Actions tab. Results are available as downloadable artifacts in the Actions tab and the overall status is shown by badges in the repository README.

---

## Tool Summary

| Tool | Type | What It Scans For |
|------|------|-------------------|
| **Bandit** | Static analysis (SAST) | Hardcoded secrets, insecure functions (`eval`, `exec`, `shell=True`), SQL injection patterns, weak crypto, overly permissive file permissions |
| **pip-audit** | Dependency scan (SCA) | Known CVEs in installed Python packages (via OSV/PyPI advisory database) |
| **Schemathesis** | OpenAPI fuzz testing | Schema violations, unexpected 5xx responses, crash-inducing inputs, spec-conformance issues |

---

## Scans

### Bandit — Static Analysis

[Bandit](https://bandit.readthedocs.io/) analyses Python source code in `app/` for common security issues such as:

- Hardcoded passwords or secrets
- Use of insecure functions (`eval`, `exec`, `subprocess` with `shell=True`)
- SQL injection patterns
- Weak cryptographic primitives
- Overly permissive file permissions

| Setting | Value |
|---------|-------|
| Scan target | `app/` |
| Report format | JSON (`bandit-report.json`) + console |
| Failure threshold | Any **high-severity** finding fails the job |
| Artifact retention | 30 days |

### pip-audit — Dependency Vulnerability Scan

[pip-audit](https://github.com/pypa/pip-audit) checks installed Python packages against the [OSV](https://osv.dev/) and [PyPI advisory](https://warehouse.pypa.io/) databases for known CVEs.

| Setting | Value |
|---------|-------|
| Scan target | All installed packages (from `pip install -e ".[dev]"`) |
| Report format | JSON (`pip-audit-report.json`) + console |
| Failure threshold | Warns on known vulnerabilities (non-blocking) |
| Artifact retention | 30 days |

---

## Triggers

| Trigger | When |
|---------|------|
| `workflow_dispatch` | Manual trigger from the Actions tab |

---

## Viewing Results

### Status Badge

The README displays a live status badge:

```
[![Security Scan](https://github.com/t3knoid/ecube/actions/workflows/security-scan.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/security-scan.yml)
```

Green indicates both scans passed. Red indicates the Bandit job found high-severity issues.

### Detailed Reports

1. Navigate to **Actions** → **Security Scan** in the GitHub repository.
2. Select a workflow run.
3. Download the **bandit-report** or **pip-audit-report** artifact from the run summary.
4. Open the JSON file to review individual findings.

### Console Output

Each job also prints human-readable output directly in the workflow log. Click into the **Run Bandit scan** or **Run pip-audit** step to see findings inline.

---

## Running Locally

To run the same scans on your development machine:

```bash
# Bandit
pip install bandit[toml]
bandit -r app/ -f screen

# pip-audit
pip install pip-audit
pip-audit --desc
```

---

## Adding Exclusions

### Bandit

To suppress a specific finding across the project, add a `# nosec` comment on the flagged line, or configure exclusions in `pyproject.toml`:

```toml
[tool.bandit]
exclude_dirs = ["tests"]
skips = ["B101"]  # Example: skip assert warnings
```

### pip-audit

To acknowledge a known vulnerability that cannot be fixed yet:

```bash
pip-audit --ignore-vuln PYSEC-YYYY-NNNNN
```

---

## Failure Behaviour

| Job | Outcome on findings |
|-----|---------------------|
| Bandit | **Fails** if any high-severity issue is found. Medium/low findings are reported but do not block. |
| pip-audit | **Warns** but does not fail the workflow. Review the report and upgrade affected packages when fixes are available. |

If Bandit fails, the PR cannot merge until the finding is resolved or explicitly suppressed with justification.

---

## API Testing Workflows

In addition to static analysis and dependency scanning, ECUBE provides an API testing workflow as a GitHub Action. It starts a real API server backed by PostgreSQL and exercises endpoints.

### Schemathesis — OpenAPI Fuzz Testing

**Workflow:** `.github/workflows/schemathesis-fuzz.yml`

[Schemathesis](https://schemathesis.readthedocs.io/) reads the OpenAPI schema and auto-generates randomised requests to find:

- Server errors (5xx responses)
- Schema violations (response doesn't match the declared schema)
- Content-type mismatches
- Status code contradictions

| Setting | Value |
|---------|-------|
| Target | `http://localhost:8000/openapi.json` |
| Auth | Admin JWT via `--header` |
| Max examples per endpoint | 50 |
| Request timeout | 10 seconds |
| Report | CLI output (`schemathesis-output.txt`) |
| Failure threshold | Warns on issues (non-blocking) |
| Artifact retention | 30 days |

#### Running locally

```bash
pip install schemathesis
uvicorn app.main:app &
st run http://localhost:8000/openapi.json \
  --header "Authorization: Bearer <your-jwt>" \
  --checks all \
  --max-examples 50
```

---

## CI Environment

All API testing workflows share the same CI environment:

| Component | Details |
|-----------|---------|
| Python | 3.12 |
| Database | PostgreSQL 14 (GitHub Actions service container) |
| Auth | `role_resolver=local` with a CI-generated admin JWT |
| Session | Cookie-based (`SESSION_BACKEND=cookie`) |
| Secret key | CI-only throwaway key (not used in production) |

---

## Viewing Results

### Status Badges

The README displays live badges for all workflows:

| Badge | Workflow |
|-------|----------|
| Security Scan | Bandit + pip-audit |
| Schemathesis API Fuzz | OpenAPI property-based fuzzing |

### Downloading Reports

1. Navigate to **Actions** in the GitHub repository.
2. Select the desired workflow run.
3. Download the report artifact from the run summary.
4. Open JSON/HTML files to review individual findings.

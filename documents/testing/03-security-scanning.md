# ECUBE — Security Scanning

**Audience:** Developers, DevOps, QA  
**Workflows:**
- `.github/workflows/security-scan.yml` — Bandit static analysis + pip-audit dependency scan
- `.github/workflows/newman-api-tests.yml` — Newman (Postman collection runner)
- `.github/workflows/schemathesis-fuzz.yml` — Schemathesis (OpenAPI fuzz testing)
- `.github/workflows/zap-api-scan.yml` — OWASP ZAP (dynamic application security testing)

---

## Overview

ECUBE runs automated security scans as a set of GitHub Actions workflows on every push and pull request to `main`. These workflows can also be triggered manually via `workflow_dispatch`. Results are available as downloadable artifacts in the Actions tab and the overall status is shown by badges in the repository README.

---

## Tool Summary

| Tool | Type | What It Scans For |
|------|------|-------------------|
| **Bandit** | Static analysis (SAST) | Hardcoded secrets, insecure functions (`eval`, `exec`, `shell=True`), SQL injection patterns, weak crypto, overly permissive file permissions |
| **pip-audit** | Dependency scan (SCA) | Known CVEs in installed Python packages (via OSV/PyPI advisory database) |
| **Newman** | API integration tests | Status-code assertions, request failures, server errors (5xx) across Postman collection endpoints |
| **Schemathesis** | OpenAPI fuzz testing | Schema violations, unexpected 5xx responses, crash-inducing inputs, spec-conformance issues |
| **OWASP ZAP** | Dynamic analysis (DAST) | Injection flaws (SQL, XSS, command), insecure headers, information disclosure, authentication issues, OWASP Top 10 vulnerabilities |

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
| `push` | Any push to `main` |
| `pull_request` | Any PR targeting `main` |
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

In addition to static analysis and dependency scanning, ECUBE runs three API testing workflows as GitHub Actions. Each starts a real API server backed by PostgreSQL and exercises endpoints in different ways.

### Newman — Postman Collection Runner

**Workflow:** `.github/workflows/newman-api-tests.yml`

Runs the existing Postman collection (`postman/ecube-postman-collection.json`) against a live API server using [Newman](https://github.com/postmanlabs/newman).

| Setting | Value |
|---------|-------|
| Collection | `postman/ecube-postman-collection.json` |
| Auth | Admin JWT generated at CI time |
| Reports | JSON (`newman-report.json`) + HTML (`newman-report.html`) |
| Failure threshold | Any failed assertion fails the job |
| Artifact retention | 30 days |

#### Running locally

```bash
npm install -g newman newman-reporter-htmlextra
uvicorn app.main:app &
newman run postman/ecube-postman-collection.json \
  --env-var "base_url=http://localhost:8000" \
  --env-var "token=<your-jwt>"
```

---

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

### OWASP ZAP — Dynamic Application Security Testing

**Workflow:** `.github/workflows/zap-api-scan.yml`

[OWASP ZAP](https://www.zaproxy.org/) performs a DAST scan against the running API, probing for:

- Injection vulnerabilities (SQL, command, header)
- Cross-site scripting (XSS)
- Security header issues
- Authentication/session weaknesses
- Information disclosure

| Setting | Value |
|---------|-------|
| Target | `http://localhost:8000/openapi.json` (live URL so ZAP derives the base host) |
| Scan type | API scan (passive + active rules) |
| Reports | HTML, JSON, Markdown |
| Failure threshold | ZAP default (warns on alerts) |
| Artifact retention | 30 days |

#### Running locally

```bash
# Pull the ZAP Docker image
docker pull ghcr.io/zaproxy/zaproxy:stable

# Start your API server
uvicorn app.main:app &

# Run ZAP API scan (pass the live URL so ZAP knows the target host)
docker run --network host ghcr.io/zaproxy/zaproxy:stable \
  zap-api-scan.py -t http://localhost:8000/openapi.json -f openapi
```

---

## CI Environment

All three API testing workflows share the same CI environment:

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
| Newman API Tests | Postman collection runner |
| Schemathesis API Fuzz | OpenAPI property-based fuzzing |
| OWASP ZAP API Scan | Dynamic security testing |

### Downloading Reports

1. Navigate to **Actions** in the GitHub repository.
2. Select the desired workflow run.
3. Download the report artifact from the run summary.
4. Open JSON/HTML files to review individual findings.

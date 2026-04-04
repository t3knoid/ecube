# ECUBE CI Build and Installer Artifact Contract

**Version:** 1.1  
**Last Updated:** April 2026  
**Audience:** Developers, Release Engineers  
**Document Type:** Development Reference

---

## Purpose

This document defines the contract between GitHub Actions build workflows and the bare-metal installer (`install.sh`).

Use this as the source of truth when changing:

- GitHub Actions packaging workflows
- release artifact names or contents
- installer package extraction/copy logic

---

## Workflows That Build Installer Artifacts

### 1) Build artifact workflow (CI/internal artifact)

File: `.github/workflows/build-artifact.yml`

Trigger:

- `workflow_dispatch`
- `push` to `main`
- `push` tags matching `v*`

Output:

- Uploads build artifacts to GitHub Actions artifact storage (not GitHub Release assets)
- Artifact base name: `ecube-package-<short_sha>`
- Files produced:
  - `ecube-package-<short_sha>.tar.gz`
  - `ecube-package-<short_sha>.sha256`

### 2) Release artifact workflow (public release asset)

File: `.github/workflows/release-artifact.yml`

Trigger:

- `release.published`

Output:

- Uploads assets to GitHub Releases
- Artifact base name: `ecube-package-<release_tag>`
- Files produced:
  - `ecube-package-<release_tag>.tar.gz`
  - `ecube-package-<release_tag>.sha256`

---

## How to Publish a Release

This repository publishes installer assets when a GitHub Release is **published** (not just when a tag is pushed).

### Prerequisites

1. Changes are merged to `main`.
2. CI is green on `main`.
3. Release tag follows the expected format: `v<major>.<minor>.<patch>` (example: `v0.3.0`).

### Option A: Publish from GitHub UI (recommended)

1. Open GitHub: **Releases** → **Draft a new release**.
2. Create/select a tag in the exact `vX.Y.Z` format.
3. Set title and release notes.
4. Click **Publish release**.

Result:

- GitHub emits `release.published`.
- `.github/workflows/release-artifact.yml` runs.
- It uploads:
  - `ecube-package-<tag>.tar.gz`
  - `ecube-package-<tag>.sha256`

### Option B: Publish from Git CLI + GitHub UI

1. Create and push the annotated tag:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

2. In GitHub Releases, create a new release for that tag and click **Publish release**.

Important:

- Pushing a tag alone does **not** run `release-artifact.yml`.
- Assets are only generated when the Release is published.

### Post-publish verification checklist

After publishing, verify all of the following on the release page:

1. Assets exist with exact names:
   - `ecube-package-vX.Y.Z.tar.gz`
   - `ecube-package-vX.Y.Z.sha256`
2. `release-artifact.yml` workflow run completed successfully.
3. Optional smoke check:

```bash
curl -LO https://github.com/t3knoid/ecube/releases/download/vX.Y.Z/ecube-package-vX.Y.Z.tar.gz
curl -LO https://github.com/t3knoid/ecube/releases/download/vX.Y.Z/ecube-package-vX.Y.Z.sha256
sha256sum -c ecube-package-vX.Y.Z.sha256
```

4. Optional installer contract check:

```bash
sudo ./install.sh --version vX.Y.Z --yes --db-host <host> --db-user <user> --db-password <pass>
```

Use a non-production host for installer smoke tests.

---

## Package Build Steps (Shared Pattern)

Both workflows perform the same package-generation sequence:

1. Set up Node.js (`actions/setup-node@v4`) with npm cache enabled.
2. Build frontend bundle:
   - `npm ci`
   - `npm run build`
3. Create `tar.gz` package with a top-level folder transform.
4. Generate SHA-256 checksum file for the tarball.

Included payload paths in the tarball:

- `install.sh`
- `app/`
- `alembic/`
- `pyproject.toml`
- `alembic.ini`
- `frontend/dist/`
- `README.md`
- `LICENSE`

---

## Installer Contract: What `install.sh` Expects

### A) Release download naming (`--version` mode)

`install.sh --version <tag>` expects GitHub Release assets named exactly:

- `ecube-package-<tag>.tar.gz`
- `ecube-package-<tag>.sha256`

It downloads both from:

- `https://github.com/t3knoid/ecube/releases/download/<tag>/...`

If release naming changes, `--version` installs will fail.

### B) Package content required by installer

When preparing/copying package content into `INSTALL_DIR`, installer logic relies on these paths existing in the extracted package:

- `app`
- `alembic`
- `alembic.ini`
- `pyproject.toml`
- `README.md`
- `LICENSE`
- `frontend/dist`

If any of these are removed or renamed in CI packaging, installs can fail or result in partial deployments.

### C) Frontend-only mode dependency

`--frontend-only` mode requires a pre-built frontend bundle and searches:

1. `${INSTALL_DIR}/frontend/dist`
2. `$(pwd)/frontend/dist`
3. `$(pwd)/dist`

CI packages must continue to provide `frontend/dist` so frontend deployment works without a local frontend build step.

---

## Change Safety Checklist

When editing packaging workflows or installer copy logic, verify all items below:

1. Release assets keep the `ecube-package-<tag>.tar.gz` + `.sha256` naming scheme.
2. Tarball still includes all installer-required paths listed above.
3. `frontend/dist` is present in the package.
4. Checksum file format remains compatible with `sha256sum -c`.
5. `docs/operations/01-installation.md` remains accurate for operator-facing install steps.

---

## Related Documents

- `docs/operations/01-installation.md`
- `docs/testing/05-automated-test-requirements.md`
- `.github/workflows/build-artifact.yml`
- `.github/workflows/release-artifact.yml`
- `install.sh`

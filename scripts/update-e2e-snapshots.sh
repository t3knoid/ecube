#!/usr/bin/env bash
# Update Playwright E2E snapshots (bash equivalent of
# .github/workflows/update-e2e-snapshots.yml)
#
# Behavior parity with workflow:
# 1) npm ci
# 2) playwright browser install (chromium + webkit)
# 3) npm run build
# 4) playwright test --update-snapshots (continues on non-zero)
#


set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
FRONTEND_DIR="${REPO_ROOT}/frontend"
SNAPSHOT_GLOB="frontend/e2e/*.spec.js-snapshots/"
PLAYWRIGHT_EXIT=0

if [[ ! -f "${FRONTEND_DIR}/package.json" ]]; then
  echo "[ERROR] Could not find frontend/package.json at: ${FRONTEND_DIR}" >&2
  exit 1
fi

for cmd in npm npx git; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "[ERROR] ${cmd} is not available in PATH." >&2
    exit 1
  fi
done

echo "[INFO] Running frontend install/build/snapshot update..."
pushd "${FRONTEND_DIR}" >/dev/null

npm ci
npx playwright install --with-deps chromium webkit
npm run build

set +e
npx playwright test --update-snapshots --reporter=line
PLAYWRIGHT_EXIT=$?
set -e

if [[ ${PLAYWRIGHT_EXIT} -ne 0 ]]; then
  echo "[WARN] Playwright returned non-zero (${PLAYWRIGHT_EXIT})."
  echo "[WARN] Continuing to snapshot commit step to match workflow behavior."
fi

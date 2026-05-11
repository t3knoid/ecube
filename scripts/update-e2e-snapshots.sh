#!/usr/bin/env bash
# Update Playwright E2E snapshots locally.
#
# Steps:
# 1) npm ci
# 2) playwright browser install (chromium + webkit)
# 3) npm run build
# 4) playwright test --update-snapshots
#
# The script returns Playwright's exit status so callers can detect snapshot
# update failures in automation.


set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
FRONTEND_DIR="${REPO_ROOT}/frontend"
PLAYWRIGHT_EXIT=0

if [[ ! -f "${FRONTEND_DIR}/package.json" ]]; then
  echo "[ERROR] Could not find frontend/package.json at: ${FRONTEND_DIR}" >&2
  exit 1
fi

for cmd in npm npx; do
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
fi

exit ${PLAYWRIGHT_EXIT}

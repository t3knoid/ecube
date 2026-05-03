#!/usr/bin/env bash
# Update Playwright E2E snapshots (bash equivalent of
# .github/workflows/update-e2e-snapshots.yml)
#
# Behavior parity with workflow:
# 1) npm ci
# 2) playwright browser install (chromium + webkit)
# 3) npm run build
# 4) playwright test --update-snapshots (continues on non-zero)
# 5) git add frontend/e2e/*.spec.js-snapshots/
# 6) commit + push when there are staged changes
#
# Optional environment variables:
#   NO_PUSH=1       Skip git push after commit
#   COMMIT_MSG=...  Override default commit message
#   COMMIT_USER_NAME / COMMIT_USER_EMAIL
#                   Override the Git author/committer identity used for
#                   snapshot update commits. Defaults to the configured
#                   Frank Refol noreply identity.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
FRONTEND_DIR="${REPO_ROOT}/frontend"
SNAPSHOT_GLOB="frontend/e2e/*.spec.js-snapshots/"
PLAYWRIGHT_EXIT=0
COMMIT_USER_NAME="${COMMIT_USER_NAME:-Frank Refol}"
COMMIT_USER_EMAIL="${COMMIT_USER_EMAIL:-t3knoid@users.noreply.github.com}"

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

popd >/dev/null

echo "[INFO] Staging and committing snapshot changes (if any)..."
pushd "${REPO_ROOT}" >/dev/null

git config user.name "${COMMIT_USER_NAME}"
git config user.email "${COMMIT_USER_EMAIL}"

git add ${SNAPSHOT_GLOB} 2>/dev/null || true

if git diff --cached --quiet; then
  echo "[INFO] No snapshot changes to commit."
  popd >/dev/null
  exit ${PLAYWRIGHT_EXIT}
fi

COMMIT_MSG="${COMMIT_MSG:-chore: update e2e visual regression snapshots [skip ci]}"
git commit -m "${COMMIT_MSG}"

if [[ "${NO_PUSH:-0}" == "1" ]]; then
  echo "[INFO] NO_PUSH=1 set; skipping git push."
else
  git push
fi

popd >/dev/null
exit ${PLAYWRIGHT_EXIT}

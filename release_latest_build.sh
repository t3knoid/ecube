#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "GITHUB_TOKEN is required." >&2
  exit 2
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Commit or stash changes before releasing." >&2
  exit 2
fi

TARGET="${TARGET_COMMITISH:-HEAD}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="${SCRIPT_DIR}/version"

if [[ ! -f "${VERSION_FILE}" ]]; then
  echo "version file not found at ${VERSION_FILE}" >&2
  exit 2
fi

TAG="$(head -n 1 "${VERSION_FILE}" | tr -d '\r' | xargs)"
if [[ -z "${TAG}" ]]; then
  echo "version file is empty. Expected release tag in ${VERSION_FILE}" >&2
  exit 2
fi
TITLE="${RELEASE_TITLE:-ecube ${TAG}}"
PRERELEASE="${PRERELEASE:-true}"
DRAFT="${DRAFT_RELEASE:-false}"

ORIGIN_URL="$(git remote get-url origin)"
if [[ "${ORIGIN_URL}" =~ github.com[:/]([^/]+)/([^/.]+)(\.git)?$ ]]; then
  OWNER="${GITHUB_OWNER:-${BASH_REMATCH[1]}}"
  REPO="${GITHUB_REPO:-${BASH_REMATCH[2]}}"
else
  echo "Could not parse GitHub owner/repo from origin URL: ${ORIGIN_URL}" >&2
  exit 1
fi

RELEASE_BY_TAG_URL="https://api.github.com/repos/${OWNER}/${REPO}/releases/tags/${TAG}"
if curl -fsS \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "${RELEASE_BY_TAG_URL}" > /dev/null; then
  echo "Release already exists for tag ${TAG}" >&2
  exit 1
fi

CREATE_URL="https://api.github.com/repos/${OWNER}/${REPO}/releases"
PAYLOAD="$(cat <<JSON
{
  \"tag_name\": \"${TAG}\",
  \"target_commitish\": \"${TARGET}\",
  \"name\": \"${TITLE}\",
  \"draft\": ${DRAFT},
  \"prerelease\": ${PRERELEASE},
  \"generate_release_notes\": true
}
JSON
)"

RESPONSE_FILE="$(mktemp)"
HTTP_CODE="$(curl -sS -o "${RESPONSE_FILE}" -w "%{http_code}" \
  -X POST "${CREATE_URL}" \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "Content-Type: application/json" \
  --data "${PAYLOAD}")"

if [[ "${HTTP_CODE}" -lt 200 || "${HTTP_CODE}" -ge 300 ]]; then
  echo "GitHub API error (${HTTP_CODE}):" >&2
  cat "${RESPONSE_FILE}" >&2
  rm -f "${RESPONSE_FILE}"
  exit 1
fi

HTML_URL="$(python - <<'PY' "${RESPONSE_FILE}"
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    data = json.load(f)
print(data.get('html_url', ''))
PY
)"

rm -f "${RESPONSE_FILE}"

echo "Release created: ${TAG}"
if [[ -n "${HTML_URL}" ]]; then
  echo "URL: ${HTML_URL}"
fi
echo "The release-artifact workflow will publish package assets for this release."

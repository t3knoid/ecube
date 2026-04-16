#!/usr/bin/env bash
# Build the ECUBE deployment artifact.
# Source of truth for both local packaging and CI packaging workflows:
#   .github/workflows/build-artifact.yml
#   .github/workflows/tag-release.yml

set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/package-local.sh [OPTIONS]

Options:
  --artifact-name NAME   Explicit artifact base name (without extension)
  --tag TAG              Use release-style name: ecube-package-<TAG>
  --sha SHA              Use build-style name:   ecube-package-<SHA8>
  --build-only           Run build steps but skip tar/sha artifact packaging
  --skip-frontend-build  Skip npm ci/npm run build (use existing frontend/dist)
  -h, --help             Show this help

Default naming behavior (if no naming option is provided):
  ecube-package-<git short sha>

Outputs:
  dist/<artifact_name>.tar.gz
  dist/<artifact_name>.sha256

Build-only output:
  dist/<artifact_name>/   # Staging directory with packaged contents
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: Required command not found: ${cmd}" >&2
    exit 1
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

ARTIFACT_NAME=""
SKIP_FRONTEND_BUILD=false
BUILD_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact-name)
      [[ -n "${2-}" && "${2}" != --* ]] || { echo "ERROR: --artifact-name requires a value" >&2; exit 1; }
      ARTIFACT_NAME="$2"
      shift 2
      ;;
    --tag)
      [[ -n "${2-}" && "${2}" != --* ]] || { echo "ERROR: --tag requires a value" >&2; exit 1; }
      ARTIFACT_NAME="ecube-package-$2"
      shift 2
      ;;
    --sha)
      [[ -n "${2-}" && "${2}" != --* ]] || { echo "ERROR: --sha requires a value" >&2; exit 1; }
      ARTIFACT_NAME="ecube-package-${2:0:8}"
      shift 2
      ;;
    --skip-frontend-build)
      SKIP_FRONTEND_BUILD=true
      shift
      ;;
    --build-only)
      BUILD_ONLY=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${ARTIFACT_NAME}" ]]; then
  require_cmd git
  ARTIFACT_NAME="ecube-package-$(git rev-parse --short=8 HEAD)"
fi

# Keep artifact naming filesystem-safe and predictable.
if [[ ! "${ARTIFACT_NAME}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: Artifact name '${ARTIFACT_NAME}' contains unsupported characters." >&2
  exit 1
fi

require_cmd tar
require_cmd sha256sum

if [[ "${SKIP_FRONTEND_BUILD}" == false ]]; then
  require_cmd npm
  echo "==> Building frontend (npm ci && npm run build)"
  (
    cd frontend
    npm ci
    npm run build
  )
else
  echo "==> Skipping frontend build"
fi

if [[ ! -d "frontend/dist" ]]; then
  echo "ERROR: frontend/dist not found. Run without --skip-frontend-build or build frontend first." >&2
  exit 1
fi

for path in install.sh app alembic deploy pyproject.toml alembic.ini frontend/dist README.md LICENSE; do
  if [[ ! -e "${path}" ]]; then
    echo "ERROR: Required packaging path not found: ${path}" >&2
    exit 1
  fi
done

chmod 755 install.sh
mkdir -p dist

if [[ "${BUILD_ONLY}" == true ]]; then
  STAGING_DIR="dist/${ARTIFACT_NAME}"
  echo "==> Creating build-only staging directory ${STAGING_DIR}"
  rm -rf "${STAGING_DIR}"
  mkdir -p "${STAGING_DIR}"

  cp -a install.sh app alembic deploy pyproject.toml alembic.ini frontend/dist README.md LICENSE "${STAGING_DIR}/"

  echo "==> Build-only mode complete (no tar/sha generated)"
  echo "Staging directory: ${STAGING_DIR}"
  exit 0
fi

echo "==> Creating dist/${ARTIFACT_NAME}.tar.gz"

# Use a staging symlink so the archive root directory is portable across
# GNU tar (--transform) and BSD tar (no --transform).
staging_link="dist/${ARTIFACT_NAME}"
ln -snf "${REPO_ROOT}" "${staging_link}"
trap 'rm -f "${staging_link}"' EXIT
tar -czf "dist/${ARTIFACT_NAME}.tar.gz" \
  -C dist \
  "${ARTIFACT_NAME}/install.sh" \
  "${ARTIFACT_NAME}/app" \
  "${ARTIFACT_NAME}/alembic" \
  "${ARTIFACT_NAME}/deploy" \
  "${ARTIFACT_NAME}/pyproject.toml" \
  "${ARTIFACT_NAME}/alembic.ini" \
  "${ARTIFACT_NAME}/frontend/dist" \
  "${ARTIFACT_NAME}/README.md" \
  "${ARTIFACT_NAME}/LICENSE"

echo "==> Generating dist/${ARTIFACT_NAME}.sha256"
(
  cd dist
  sha256sum "${ARTIFACT_NAME}.tar.gz" > "${ARTIFACT_NAME}.sha256"
)

echo "==> Done"
echo "Artifact: dist/${ARTIFACT_NAME}.tar.gz"
echo "SHA256:   dist/${ARTIFACT_NAME}.sha256"

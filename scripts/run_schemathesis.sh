#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_schemathesis.sh — Spin up the ECUBE Docker stack and run Schemathesis
#
# Usage:
#   ./scripts/run_schemathesis.sh                    # full run (coverage + fuzzing)
#   ./scripts/run_schemathesis.sh --endpoint /drives  # single endpoint
#   ./scripts/run_schemathesis.sh --max-examples 100  # override example count
#
# Extra arguments are forwarded directly to the `st run` command.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---- Configurable defaults ----
HOST_PORT="${SCHEMATHESIS_PORT:-8000}"
POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-5432}"   # 0 = random ephemeral port (avoids conflicts)
SECRET_KEY="${SECRET_KEY:-change-me-in-production-please-rotate-32b}"
MAX_WAIT="${SCHEMATHESIS_MAX_WAIT:-60}"        # seconds to wait for /health
MAX_EXAMPLES="${SCHEMATHESIS_MAX_EXAMPLES:-50}"

COMPOSE_FILE="$PROJECT_ROOT/docker-compose.ecube.yml"
COMPOSE_PROJECT="ecube-schemathesis"

# ---- Preflight checks ----
for cmd in docker curl tee; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: '$cmd' is required but not found in PATH." >&2
    exit 1
  fi
done

# Detect Python: prefer $VIRTUAL_ENV interpreter, then python, then python3
if [[ -n "${VIRTUAL_ENV:-}" ]] && [[ -x "$VIRTUAL_ENV/bin/python" ]]; then
  PYTHON="$VIRTUAL_ENV/bin/python"
elif command -v python &>/dev/null; then
  PYTHON="python"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
else
  echo "ERROR: Python is required but neither 'python' nor 'python3' was found in PATH." >&2
  exit 1
fi

# Detect Compose command: prefer v2 plugin, fall back to legacy binary
if docker compose version &>/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
  COMPOSE_CMD="docker-compose"
else
  echo "ERROR: Neither 'docker compose' (plugin) nor 'docker-compose' (standalone) found." >&2
  exit 1
fi

# Use sudo only when the current user cannot reach the Docker daemon directly
if docker info &>/dev/null 2>&1; then
  SUDO=""
else
  SUDO="sudo"
fi

if ! "$PYTHON" -c "import jwt" 2>/dev/null; then
  echo "ERROR: PyJWT is required. Install it with: pip install PyJWT" >&2
  exit 1
fi

if ! command -v st &>/dev/null; then
  echo "ERROR: Schemathesis CLI ('st') is required. Install it with: pip install schemathesis" >&2
  exit 1
fi

# ---- Tear-down helper ----
cleanup() {
  echo ""
  echo "==> Stopping containers…"
  $SUDO $COMPOSE_CMD -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" down -v 2>/dev/null || true
}
trap cleanup EXIT

# ---- Start the stack with overrides ----
echo "==> Starting ECUBE stack (port $HOST_PORT)…"

HOST_PORT="$HOST_PORT" \
POSTGRES_HOST_PORT="$POSTGRES_HOST_PORT" \
USB_DISCOVERY_INTERVAL=0 \
LOCAL_GROUP_ROLE_MAP='{"evidence-admins": ["admin"]}' \
SECRET_KEY="$SECRET_KEY" \
$SUDO $COMPOSE_CMD -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" up -d --build \
  --force-recreate \
  2>&1

APP_CONTAINER="ecube-app"

# ---- Wait for API ----
echo "==> Waiting for API on http://localhost:$HOST_PORT/health …"
elapsed=0
while [ "$elapsed" -lt "$MAX_WAIT" ]; do
  if curl -sf "http://localhost:${HOST_PORT}/health" >/dev/null 2>&1; then
    echo "    API is ready."
    break
  fi
  sleep 2
  elapsed=$((elapsed + 2))
  echo "    … $elapsed s"
done

if [ "$elapsed" -ge "$MAX_WAIT" ]; then
  echo "ERROR: API did not become healthy within ${MAX_WAIT}s." >&2
  echo "       Check logs: $SUDO docker logs $APP_CONTAINER" >&2
  exit 1
fi

# ---- Generate JWT ----
echo "==> Generating admin JWT…"
TOKEN=$(SECRET_KEY="$SECRET_KEY" "$PYTHON" - <<'PY'
import jwt, time, os
payload = {
    "sub": "dev-admin",
    "username": "dev-admin",
    "groups": ["evidence-admins"],
    "roles": ["admin"],
    "exp": int(time.time()) + 3600,
}
print(jwt.encode(payload, os.environ["SECRET_KEY"], algorithm="HS256"))
PY
)

# ---- Run Schemathesis ----
echo "==> Running Schemathesis…"
echo ""

st run "http://localhost:${HOST_PORT}/openapi.json" \
  --header "Authorization: Bearer $TOKEN" \
  --checks all \
  --max-examples "$MAX_EXAMPLES" \
  --request-timeout 10 \
  --phases coverage,fuzzing \
  "$@" \
  2>&1 | tee "$PROJECT_ROOT/schemathesis-output.txt"

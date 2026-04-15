#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# run_schemathesis.sh — Spin up the ECUBE Docker stack and run Schemathesis
#
# Usage:
#   ./scripts/run_schemathesis.sh                    # local CI-like run (coverage only)
#   ./scripts/run_schemathesis.sh --endpoint /drives  # single endpoint
#   ./scripts/run_schemathesis.sh --max-examples 100  # override example count
#
# Extra arguments are forwarded directly to the `st run` command.
#
# Known false positives (correct server behaviour, not schema bugs):
#
#   POST /admin/os-users  422  — Fuzzed group names don't exist on the OS;
#                                the API correctly rejects them.
#   POST /setup/database/test-connection  503  — Fuzzed hostname is
#                                unreachable; 503 is the documented response.
#   PUT  /setup/database/settings  503  — After applying fuzzed settings the
#                                connection check fails; 503 is documented.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ECUBE_HELPER_PATH="$PROJECT_ROOT/scripts/lib/ecube_compose.sh"
if [[ -f "$ECUBE_HELPER_PATH" ]]; then
  . "$ECUBE_HELPER_PATH"
else
  echo "WARNING: $ECUBE_HELPER_PATH not found. Using built-in compose helper fallback." >&2

ecube_require_compose() {
  ECUBE_COMPOSE_FILE="${ECUBE_COMPOSE_FILE:-$PROJECT_ROOT/docker-compose.ecube.yml}"
  if [[ ! -f "$ECUBE_COMPOSE_FILE" ]]; then
    echo "ERROR: Compose file not found at $ECUBE_COMPOSE_FILE" >&2
    exit 1
  fi
  if docker compose version &>/dev/null; then
    ECUBE_COMPOSE_CMD="docker compose"
  elif command -v docker-compose &>/dev/null; then
    ECUBE_COMPOSE_CMD="docker-compose"
  else
    echo "ERROR: Neither 'docker compose' nor 'docker-compose' found." >&2
    exit 1
  fi
  if docker info &>/dev/null; then
    ECUBE_SUDO=""
  else
    ECUBE_SUDO="sudo"
  fi
}

ecube_compose_down() {
  echo ""
  echo "==> Stopping containers…"
  $ECUBE_SUDO env \
    SECRET_KEY="${ECUBE_SECRET_KEY:-dummy}" \
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-dummy}" \
    $ECUBE_COMPOSE_CMD -p "$ECUBE_COMPOSE_PROJECT" -f "$ECUBE_COMPOSE_FILE" down -v --rmi all 2>/dev/null || true
}

ecube_compose_up() {
  echo "==> Starting ECUBE stack (port $ECUBE_HOST_PORT)…"
  $ECUBE_SUDO env \
    UI_PORT="$ECUBE_HOST_PORT" \
    ECUBE_PORT="$ECUBE_HOST_PORT" \
    ECUBE_NO_TLS=true \
    HOST_PORT="$ECUBE_HOST_PORT" \
    POSTGRES_HOST_PORT="$ECUBE_POSTGRES_HOST_PORT" \
    USB_DISCOVERY_INTERVAL=0 \
    LOCAL_GROUP_ROLE_MAP='{"evidence-admins": ["admin"]}' \
    SECRET_KEY="$ECUBE_SECRET_KEY" \
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-ecube}" \
    $ECUBE_COMPOSE_CMD -p "$ECUBE_COMPOSE_PROJECT" -f "$ECUBE_COMPOSE_FILE" up -d --build \
      --force-recreate \
      2>&1
}

ecube_wait_for_health() {
  local base_url="$1"
  local elapsed=0
  echo "==> Waiting for API on $base_url/health …"
  while [ "$elapsed" -lt "$ECUBE_MAX_WAIT" ]; do
    if curl -sf "$base_url/health" >/dev/null 2>&1; then
      echo "    API is ready."
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
    echo "    … $elapsed s"
  done
  echo "ERROR: API did not become healthy within ${ECUBE_MAX_WAIT}s." >&2
  return 1
}

ecube_assert_health() {
  local base_url="$1"
  if ! curl -sS -m 3 "$base_url/health" >/dev/null; then
    echo "ERROR: API is not reachable at $base_url (health check failed)." >&2
    return 1
  fi
}

fi  # end built-in compose helper fallback

# ---- Configurable defaults ----
HOST_PORT="${HOST_PORT:-8000}"
POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-5432}"
SECRET_KEY="${SECRET_KEY:-change-me-in-production-please-rotate-32b}"
MAX_WAIT="${SCHEMATHESIS_MAX_WAIT:-60}"        # seconds to wait for /health
MAX_EXAMPLES="${SCHEMATHESIS_MAX_EXAMPLES:-5}"
REQUEST_TIMEOUT="${SCHEMATHESIS_REQUEST_TIMEOUT:-10}"
PHASES="${SCHEMATHESIS_PHASES:-coverage}"
WORKERS="${SCHEMATHESIS_WORKERS:-1}"
MAX_FAILURES="${SCHEMATHESIS_MAX_FAILURES:-1}"
CHECKS="${SCHEMATHESIS_CHECKS:-not_a_server_error,status_code_conformance}"
EXCLUDE_CHECKS="${SCHEMATHESIS_EXCLUDE_CHECKS:-unsupported_method,missing_required_header}"
INCLUDE_PATH_REGEX="${SCHEMATHESIS_INCLUDE_PATH_REGEX:-^/(health|introspection/version|setup/status)$}"
WAIT_FOR_SCHEMA="${SCHEMATHESIS_WAIT_FOR_SCHEMA:-30}"
SEED="${SCHEMATHESIS_SEED:-}"

ECUBE_COMPOSE_PROJECT="ecube-schemathesis"
ECUBE_HOST_PORT="$HOST_PORT"
ECUBE_POSTGRES_HOST_PORT="$POSTGRES_HOST_PORT"
ECUBE_SECRET_KEY="$SECRET_KEY"
ECUBE_MAX_WAIT="$MAX_WAIT"

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

ecube_require_compose

if ! "$PYTHON" -c "import jwt" 2>/dev/null; then
  echo "ERROR: PyJWT is required. Install it with: pip install PyJWT" >&2
  exit 1
fi

if command -v st &>/dev/null; then
  ST_CMD="st"
elif [[ -n "${VIRTUAL_ENV:-}" ]] && [[ -x "$VIRTUAL_ENV/bin/st" ]]; then
  ST_CMD="$VIRTUAL_ENV/bin/st"
elif [[ -x "$PROJECT_ROOT/.venv/bin/st" ]]; then
  ST_CMD="$PROJECT_ROOT/.venv/bin/st"
else
  echo "==> Schemathesis CLI ('st') not found. Installing…"
  "$PYTHON" -m pip install schemathesis
  if command -v st &>/dev/null; then
    ST_CMD="st"
  elif [[ -n "${VIRTUAL_ENV:-}" ]] && [[ -x "$VIRTUAL_ENV/bin/st" ]]; then
    ST_CMD="$VIRTUAL_ENV/bin/st"
  elif [[ -x "$PROJECT_ROOT/.venv/bin/st" ]]; then
    ST_CMD="$PROJECT_ROOT/.venv/bin/st"
  else
    echo "ERROR: Failed to install schemathesis." >&2
    exit 1
  fi
fi

# ---- Tear-down helper ----
cleanup() {
  ecube_compose_down
}
trap cleanup EXIT

# Ensure .env exists on the host so the bind mount works correctly.
_env_file="$PROJECT_ROOT/.env"
if [[ ! -f "$_env_file" ]]; then
  cat > "$_env_file" <<ENVEOF
SECRET_KEY=$SECRET_KEY
POSTGRES_PASSWORD=ecube
POSTGRES_USER=ecube
POSTGRES_DB=ecube
ENVEOF
fi

# The test needs DATABASE_URL so the app connects to the compose postgres
# service and reports /health/ready as 200 instead of 503.
_smoke_db_url="postgresql+psycopg2://ecube:ecube@postgres:5432/ecube"
_current_db_url=$(sed -n 's/^DATABASE_URL=//p' "$_env_file" | head -1)
# Strip one layer of surrounding quotes.
_current_db_url="${_current_db_url#\"}" ; _current_db_url="${_current_db_url%\"}"
_current_db_url="${_current_db_url#\'}" ; _current_db_url="${_current_db_url%\'}"
if [[ -z "$_current_db_url" ]]; then
  if grep -q '^DATABASE_URL=' "$_env_file" 2>/dev/null; then
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=$_smoke_db_url|" "$_env_file"
  else
    echo "DATABASE_URL=$_smoke_db_url" >> "$_env_file"
  fi
fi

ecube_compose_up
ecube_wait_for_health "http://localhost:${HOST_PORT}"

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

if ! ecube_assert_health "http://localhost:${HOST_PORT}"; then
  exit 1
fi

SCHEMATHESIS_ARGS=(
  run "http://localhost:${HOST_PORT}/openapi.json"
  --header "Authorization: Bearer $TOKEN"
  --checks "$CHECKS"
  --exclude-checks "$EXCLUDE_CHECKS"
  --workers "$WORKERS"
  --max-failures "$MAX_FAILURES"
  --max-examples "$MAX_EXAMPLES"
  --request-timeout "$REQUEST_TIMEOUT"
  --wait-for-schema "$WAIT_FOR_SCHEMA"
  --phases "$PHASES"
  --include-path-regex "$INCLUDE_PATH_REGEX"
)

if [[ -n "$SEED" ]]; then
  SCHEMATHESIS_ARGS+=(--seed "$SEED")
fi

"$ST_CMD" "${SCHEMATHESIS_ARGS[@]}" \
  "$@" \
  2>&1 | tee "$PROJECT_ROOT/schemathesis-output.txt"

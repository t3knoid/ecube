#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COLLECTION_PATH="$PROJECT_ROOT/postman/ecube-postman-collection.json"

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
fi

BASE_URL="${BASE_URL:-http://localhost:8000}"
ADMIN_USERNAME="${ECUBE_ADMIN_USERNAME:-ecube-admin}"
ADMIN_PASSWORD="${ECUBE_ADMIN_PASSWORD:-s3cret}"
ECUBE_TOKEN="${ECUBE_TOKEN:-}"
HOST_PORT="${HOST_PORT:-8000}"
POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-5432}"
SECRET_KEY="${SECRET_KEY:-change-me-in-production-please-rotate-32b}"
MAX_WAIT="${NEWMAN_MAX_WAIT:-60}"
ECUBE_COMPOSE_PROJECT="ecube-newman-smoke"
ECUBE_HOST_PORT="$HOST_PORT"
ECUBE_POSTGRES_HOST_PORT="$POSTGRES_HOST_PORT"
ECUBE_SECRET_KEY="$SECRET_KEY"
ECUBE_MAX_WAIT="$MAX_WAIT"

for cmd in docker curl npx; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: '$cmd' is required but not found in PATH." >&2
    exit 1
  fi
done

if [[ -n "${VIRTUAL_ENV:-}" ]] && [[ -x "$VIRTUAL_ENV/bin/python" ]]; then
  PYTHON="$VIRTUAL_ENV/bin/python"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "ERROR: Python is required but neither 'python' nor 'python3' was found in PATH." >&2
  exit 1
fi

if [[ ! -f "$COLLECTION_PATH" ]]; then
  echo "ERROR: Collection not found at $COLLECTION_PATH" >&2
  exit 1
fi

ecube_require_compose

cleanup() {
  ecube_compose_down
}
trap cleanup EXIT

if ! command -v npx >/dev/null 2>&1; then
  echo "ERROR: npx is required. Install Node.js 18+ to run Newman." >&2
  exit 1
fi

if [[ -z "$ECUBE_TOKEN" ]] && ! "$PYTHON" -c "import jwt" 2>/dev/null; then
  echo "ERROR: PyJWT is required to generate an ECUBE token. Install it with: pip install PyJWT" >&2
  exit 1
fi

# Ensure .env exists on the host so the bind mount works correctly.
# The compose file mounts ./.env into the container.
_env_file="$PROJECT_ROOT/.env"
if [[ ! -f "$_env_file" ]]; then
  cat > "$_env_file" <<ENVEOF
SECRET_KEY=$SECRET_KEY
POSTGRES_PASSWORD=ecube
POSTGRES_USER=ecube
POSTGRES_DB=ecube
ENVEOF
fi

# The smoke test needs DATABASE_URL so the app connects to the compose
# postgres service and reports /health/ready as 200 instead of 503.
_smoke_db_url="postgresql://ecube:ecube@postgres:5432/ecube"
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
ecube_wait_for_health "$BASE_URL"

echo "Running Newman smoke test against $BASE_URL"

if ! ecube_assert_health "$BASE_URL"; then
  exit 1
fi

if [[ -z "$ECUBE_TOKEN" ]]; then
  echo "==> Generating admin JWT…"
  ECUBE_TOKEN=$(SECRET_KEY="$SECRET_KEY" "$PYTHON" - <<'PY'
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
fi

NEWMAN_ARGS=(
  run "$COLLECTION_PATH"
  --env-var "base_url=$BASE_URL"
  --env-var "admin_username=$ADMIN_USERNAME"
  --env-var "admin_password=$ADMIN_PASSWORD"
  --env-var "token=$ECUBE_TOKEN"
  --folder "Health & Version"
  --folder "Introspection"
  --folder "Audit"
  --reporters cli
  --timeout-request 10000
  --bail
)

echo "Using ECUBE token: running authenticated smoke folders."

npx --yes newman "${NEWMAN_ARGS[@]}"

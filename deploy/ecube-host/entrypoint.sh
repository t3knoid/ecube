#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Guard: .env must be a regular file (not a directory).
# Docker creates a directory on the host when the bind-mount source does not
# exist.  Detect this early and provide a clear error message.
# ---------------------------------------------------------------------------
if [ -d /opt/ecube/.env ]; then
  echo "ERROR: /opt/ecube/.env is a directory, not a file." >&2
  echo "This happens when Docker creates the bind-mount source automatically." >&2
  echo "Fix: on the host run 'cp .env.example .env' then restart the stack." >&2
  exit 1
fi

ECUBE_RUN_MIGRATIONS_ON_START="${ECUBE_RUN_MIGRATIONS_ON_START:-true}"
ECUBE_DB_WAIT_MAX_RETRIES="${ECUBE_DB_WAIT_MAX_RETRIES:-30}"
ECUBE_DB_WAIT_SECONDS="${ECUBE_DB_WAIT_SECONDS:-2}"

# ---------------------------------------------------------------------------
# Pick up DATABASE_URL from .env when the compose environment leaves it empty.
# After the setup wizard provisions the database it writes DATABASE_URL to
# .env.  On subsequent container restarts the value needs to survive.
# ---------------------------------------------------------------------------
if [ -z "${DATABASE_URL:-}" ] && [ -f /opt/ecube/.env ]; then
  _env_db_url=$(sed -n 's/^DATABASE_URL=//p' /opt/ecube/.env | head -1 || true)
  if [ -n "${_env_db_url}" ]; then
    export DATABASE_URL="${_env_db_url}"
  fi
fi

wait_for_db() {
  python - <<'PY'
import os
import sys
import time

from sqlalchemy import create_engine, text

database_url = os.getenv("DATABASE_URL")
if not database_url:
    print("[entrypoint] DATABASE_URL is not set", file=sys.stderr)
    sys.exit(1)

retries = int(os.getenv("ECUBE_DB_WAIT_MAX_RETRIES", "30"))
sleep_seconds = int(os.getenv("ECUBE_DB_WAIT_SECONDS", "2"))

for attempt in range(1, retries + 1):
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[entrypoint] Database is reachable")
        sys.exit(0)
    except Exception as exc:
        print(f"[entrypoint] Waiting for database (attempt {attempt}/{retries}): {exc}")
        time.sleep(sleep_seconds)

print("[entrypoint] Database did not become ready in time", file=sys.stderr)
sys.exit(1)
PY
}

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] DATABASE_URL not configured — starting in setup wizard mode"
elif [ "${ECUBE_RUN_MIGRATIONS_ON_START}" = "true" ]; then
  echo "[entrypoint] Waiting for database before migrations..."
  wait_for_db
  echo "[entrypoint] Running Alembic migrations..."
  alembic upgrade head
else
  echo "[entrypoint] Migration step disabled (ECUBE_RUN_MIGRATIONS_ON_START=false)"
fi

# ---------------------------------------------------------------------------
# TLS / port configuration
# ---------------------------------------------------------------------------
# When the default CMD is "uvicorn …", append --port and optional TLS flags.
# If the user overrides CMD (e.g. "bash"), skip this logic entirely.
if [ "$1" = "uvicorn" ]; then
  if [ "${ECUBE_NO_TLS}" = "true" ]; then
    set -- "$@" --port "${ECUBE_PORT:-8000}"
    echo "[entrypoint] Starting uvicorn (no TLS, port ${ECUBE_PORT:-8000})"
  else
    TLS_KEYFILE="${TLS_KEYFILE:-/opt/ecube/certs/key.pem}"
    TLS_CERTFILE="${TLS_CERTFILE:-/opt/ecube/certs/cert.pem}"
    set -- "$@" --port "${ECUBE_PORT:-8443}" \
      --ssl-keyfile "${TLS_KEYFILE}" \
      --ssl-certfile "${TLS_CERTFILE}"
    echo "[entrypoint] Starting uvicorn (TLS, port ${ECUBE_PORT:-8443})"
  fi
fi

exec "$@"

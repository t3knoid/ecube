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
  # Strip one layer of surrounding quotes (single or double) in case
  # the operator hand-edited .env with quotes around the value.
  _env_db_url="${_env_db_url#\"}" ; _env_db_url="${_env_db_url%\"}"
  _env_db_url="${_env_db_url#\'}" ; _env_db_url="${_env_db_url%\'}"
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

# ---------------------------------------------------------------------------
# PG_SUPERUSER fallback: when compose passes empty PG_SUPERUSER_NAME/PASS,
# fall back to POSTGRES_USER / POSTGRES_PASSWORD so the setup wizard has
# working defaults without requiring nested variable expansion in compose.
#
# The pair is treated as all-or-nothing: only fall back to POSTGRES_* when
# BOTH are empty.  If exactly one is set, emit an error — mixing a custom
# username with the default password (or vice-versa) causes confusing
# setup-wizard failures.
# ---------------------------------------------------------------------------
if [ -n "${PG_SUPERUSER_NAME:-}" ] && [ -z "${PG_SUPERUSER_PASS:-}" ]; then
  echo "[entrypoint] ERROR: PG_SUPERUSER_NAME is set but PG_SUPERUSER_PASS is empty." >&2
  echo "             Set both PG_SUPERUSER_NAME and PG_SUPERUSER_PASS, or leave both unset" >&2
  echo "             to fall back to POSTGRES_USER / POSTGRES_PASSWORD." >&2
  exit 1
fi
if [ -z "${PG_SUPERUSER_NAME:-}" ] && [ -n "${PG_SUPERUSER_PASS:-}" ]; then
  echo "[entrypoint] ERROR: PG_SUPERUSER_PASS is set but PG_SUPERUSER_NAME is empty." >&2
  echo "             Set both PG_SUPERUSER_NAME and PG_SUPERUSER_PASS, or leave both unset" >&2
  echo "             to fall back to POSTGRES_USER / POSTGRES_PASSWORD." >&2
  exit 1
fi
if [ -z "${PG_SUPERUSER_NAME:-}" ] && [ -z "${PG_SUPERUSER_PASS:-}" ]; then
  export PG_SUPERUSER_NAME="${POSTGRES_USER:-}"
  export PG_SUPERUSER_PASS="${POSTGRES_PASSWORD:-}"
fi

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
  if [ "${ECUBE_NO_TLS:-false}" = "true" ]; then
    set -- "$@" --port "${ECUBE_PORT:-8000}"
    echo "[entrypoint] Starting uvicorn (no TLS, port ${ECUBE_PORT:-8000})"
  else
    TLS_KEYFILE="${TLS_KEYFILE:-/opt/ecube/certs/key.pem}"
    TLS_CERTFILE="${TLS_CERTFILE:-/opt/ecube/certs/cert.pem}"

    # Generate a self-signed certificate on first start if no cert exists.
    # Each container gets its own unique private key — nothing is baked
    # into the image layer.
    if [ ! -f "${TLS_KEYFILE}" ] || [ ! -f "${TLS_CERTFILE}" ]; then
      _cert_dir=$(dirname "${TLS_KEYFILE}")
      mkdir -p "${_cert_dir}"
      echo "[entrypoint] No TLS certificate found — generating self-signed cert"
      openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "${TLS_KEYFILE}" \
        -out    "${TLS_CERTFILE}" \
        -subj   "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" 2>/dev/null
      chmod 600 "${TLS_KEYFILE}"
      chmod 644 "${TLS_CERTFILE}"
      echo "[entrypoint] WARNING: Using auto-generated self-signed certificate." \
           "Mount real certs or set TLS_KEYFILE/TLS_CERTFILE for production."
    fi

    set -- "$@" --port "${ECUBE_PORT:-8443}" \
      --ssl-keyfile "${TLS_KEYFILE}" \
      --ssl-certfile "${TLS_CERTFILE}"
    echo "[entrypoint] Starting uvicorn (TLS, port ${ECUBE_PORT:-8443})"
  fi
fi

exec "$@"

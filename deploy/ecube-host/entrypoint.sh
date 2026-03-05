#!/usr/bin/env bash
set -euo pipefail

ECUBE_RUN_MIGRATIONS_ON_START="${ECUBE_RUN_MIGRATIONS_ON_START:-true}"
ECUBE_DB_WAIT_MAX_RETRIES="${ECUBE_DB_WAIT_MAX_RETRIES:-30}"
ECUBE_DB_WAIT_SECONDS="${ECUBE_DB_WAIT_SECONDS:-2}"

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

if [ "${ECUBE_RUN_MIGRATIONS_ON_START}" = "true" ]; then
  echo "[entrypoint] Waiting for database before migrations..."
  wait_for_db
  echo "[entrypoint] Running Alembic migrations..."
  alembic upgrade head
else
  echo "[entrypoint] Migration step disabled (ECUBE_RUN_MIGRATIONS_ON_START=false)"
fi

exec "$@"

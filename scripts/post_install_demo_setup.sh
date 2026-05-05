#!/usr/bin/env bash

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/ecube}"
SOURCE_METADATA="${SOURCE_METADATA:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/demo-metadata.json}"
SHARED_PASSWORD="${1:-}"
ENV_FILE="${ENV_FILE:-${INSTALL_DIR}/.env}"
DEFAULT_DATABASE_URL="${DEFAULT_DATABASE_URL:-postgresql://ecube:ecube@localhost/ecube}"

metadata_shared_password() {
  python3 - <<'PY' "$1"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)

value = payload.get("demo_config", {}).get("shared_password") if isinstance(payload, dict) else None
print(value.strip() if isinstance(value, str) else "")
PY
}

generate_demo_shared_password() {
  python3 - <<'PY'
import secrets
import string

alphabet = string.ascii_letters + string.digits
while True:
    candidate = ''.join(secrets.choice(alphabet) for _ in range(20))
    if (
        any(ch.islower() for ch in candidate)
        and any(ch.isupper() for ch in candidate)
        and any(ch.isdigit() for ch in candidate)
    ):
        print(candidate)
        break
PY
}

install_demo_metadata() {
  local source_metadata="$1"
  local target_metadata="$2"
  local shared_password="$3"

  sudo python3 - <<'PY' "${source_metadata}" "${target_metadata}" "${shared_password}"
import json
import sys
from pathlib import Path

source_path = Path(sys.argv[1])
target_path = Path(sys.argv[2])
shared_password = sys.argv[3].strip()
payload = json.loads(source_path.read_text(encoding="utf-8"))

if shared_password:
    demo_config = payload.get("demo_config")
    if not isinstance(demo_config, dict):
        demo_config = {}
        payload["demo_config"] = demo_config
    demo_config["shared_password"] = shared_password

target_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

usage() {
  cat <<EOF
Usage: ./scripts/post_install_demo_setup.sh [shared-password]

Copies the repository demo-metadata.json into the ECUBE install root and runs
the native demo bootstrap seed command documented in the post-install demo
setup steps. When no shared-password argument is provided, the helper uses
demo_config.shared_password from the source demo-metadata.json when present,
or generates a strong demo password when the metadata leaves it blank.

Environment overrides:
  INSTALL_DIR      ECUBE install root (default: /opt/ecube)
  SOURCE_METADATA  Source demo-metadata.json path (default: ./demo-metadata.json)
  ENV_FILE         Target ECUBE environment file (default: <INSTALL_DIR>/.env)
  DEFAULT_DATABASE_URL
                   DATABASE_URL written when the target env file does not
                   already define one (default: postgresql://ecube:ecube@localhost/ecube)
EOF
}

current_database_url() {
  local env_file="$1"
  local database_url=""

  if sudo test -f "${env_file}"; then
    database_url="$(sudo awk -F= '/^[[:space:]]*DATABASE_URL=/{value=$0} END{print value}' "${env_file}" 2>/dev/null || true)"
    database_url="${database_url#*=}"
    database_url="${database_url#${database_url%%[![:space:]]*}}"
    database_url="${database_url%${database_url##*[![:space:]]}}"
  fi

  printf '%s\n' "${database_url}"
}

ensure_database_url() {
  local env_file="$1"
  local database_url="$2"

  sudo install -d -m 0755 "$(dirname "${env_file}")"

  local existing_value=""
  existing_value="$(current_database_url "${env_file}")"

  if [[ -n "${existing_value}" ]]; then
    printf '%s\n' "${existing_value}"
    return 0
  fi

  if sudo test -f "${env_file}"; then
    sudo python3 - <<'PY' "${env_file}" "${database_url}"
from pathlib import Path
import sys

path = Path(sys.argv[1])
database_url = sys.argv[2]
text = path.read_text(encoding="utf-8")
lines = text.splitlines()
updated = False

for index, line in enumerate(lines):
    if line.strip().startswith("DATABASE_URL="):
        lines[index] = f"DATABASE_URL={database_url}"
        updated = True

if not updated:
    if text and not text.endswith("\n"):
        text += "\n"
    text += f"DATABASE_URL={database_url}\n"
    path.write_text(text, encoding="utf-8")
else:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
  else
    printf 'DATABASE_URL=%s\n' "${database_url}" | sudo tee "${env_file}" >/dev/null
  fi

  printf '%s\n' "${database_url}"
}

database_provision_values() {
  python3 - <<'PY' "$1"
from urllib.parse import urlparse
import sys

database_url = sys.argv[1].strip()
parsed = urlparse(database_url)
database_name = parsed.path.lstrip("/")
database_user = parsed.username or ""
database_host = (parsed.hostname or "").lower()
is_local = database_host in {"", "localhost", "127.0.0.1", "::1"}

if not database_name or not database_user:
    raise SystemExit(1)

print(f"{database_user}\t{database_name}\t{database_host}\t{1 if is_local else 0}")
PY
}

ensure_local_database_exists() {
  local database_url="$1"
  local parsed_values=""

  if ! parsed_values="$(database_provision_values "${database_url}")"; then
    echo "Unable to determine PostgreSQL database/user from DATABASE_URL=${database_url}" >&2
    exit 1
  fi

  local database_user=""
  local database_name=""
  local database_host=""
  local is_local_database=""
  IFS=$'\t' read -r database_user database_name database_host is_local_database <<<"${parsed_values}"

  if [[ "${is_local_database}" != "1" ]]; then
    return 0
  fi

  if ! command -v psql >/dev/null 2>&1; then
    echo "psql is required to create the local PostgreSQL database '${database_name}'" >&2
    exit 1
  fi

  if ! sudo -u postgres psql -d postgres -c "SELECT 1" >/dev/null 2>&1; then
    echo "Unable to reach local PostgreSQL as the postgres OS user" >&2
    exit 1
  fi

  local escaped_database_name_literal="${database_name//\'/\'\'}"
  if sudo -u postgres psql -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '${escaped_database_name_literal}'" 2>/dev/null | grep -q 1; then
    return 0
  fi

  local escaped_database_name_identifier="${database_name//\"/\"\"}"
  local escaped_database_user_identifier="${database_user//\"/\"\"}"
  sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${escaped_database_name_identifier}\" OWNER \"${escaped_database_user_identifier}\";" >/dev/null
}

if [[ ! -f "${SOURCE_METADATA}" ]]; then
  echo "Source metadata file not found: ${SOURCE_METADATA}" >&2
  exit 1
fi

if [[ -z "${SHARED_PASSWORD}" ]]; then
  SHARED_PASSWORD="$(metadata_shared_password "${SOURCE_METADATA}")"
fi

if [[ -z "${SHARED_PASSWORD}" ]]; then
  SHARED_PASSWORD="$(generate_demo_shared_password)"
fi

DATABASE_URL="$(ensure_database_url "${ENV_FILE}" "${DEFAULT_DATABASE_URL}")"
ensure_local_database_exists "${DATABASE_URL}"

sudo install -d -m 0755 "${INSTALL_DIR}"
install_demo_metadata "${SOURCE_METADATA}" "${INSTALL_DIR}/demo-metadata.json" "${SHARED_PASSWORD}"

bootstrap_cmd=(
  "${INSTALL_DIR}/venv/bin/ecube-demo-bootstrap"
  --metadata-path "${INSTALL_DIR}/demo-metadata.json"
  seed
)
bootstrap_cmd+=(--shared-password "${SHARED_PASSWORD}")

printf 'Generated or resolved demo shared password: %s\n' "${SHARED_PASSWORD}"

(
  cd "${INSTALL_DIR}"
  sudo "${bootstrap_cmd[@]}"
)
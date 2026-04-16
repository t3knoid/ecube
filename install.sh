#!/usr/bin/env bash
# ECUBE Native Installer
# Installs the ECUBE service (API + frontend) on Debian/Ubuntu.
#
# Usage:
#   sudo ./install.sh [OPTIONS]
#
# Run with --help to see all available options.

set -Eeuo pipefail

# ---------------------------------------------------------------------------
# Colour helpers (NO_COLOR / non-TTY aware)
# ---------------------------------------------------------------------------
_supports_color() {
  [[ -z "${NO_COLOR:-}" && -t 1 ]]
}

if _supports_color; then
  C_RESET='\033[0m'
  C_RED='\033[0;31m'
  C_YELLOW='\033[1;33m'
  C_GREEN='\033[0;32m'
  C_CYAN='\033[0;36m'
  C_BOLD='\033[1m'
else
  C_RESET='' C_RED='' C_YELLOW='' C_GREEN='' C_CYAN='' C_BOLD=''
fi

LOG_FILE="/var/log/ecube-install.log"

_log() {
  local level="$1"; shift
  local msg="$*"
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  # Always write plain text to the log file
  echo "${ts} [${level}] ${msg}" >> "${LOG_FILE}" 2>/dev/null || true
  case "${level}" in
    INFO)    echo -e "${C_CYAN}[INFO]${C_RESET}  ${msg}" ;;
    OK)      echo -e "${C_GREEN}[OK]${C_RESET}    ${msg}" ;;
    WARN)    echo -e "${C_YELLOW}[WARN]${C_RESET}  ${msg}" ;;
    ERROR)   echo -e "${C_RED}[ERROR]${C_RESET} ${msg}" >&2 ;;
    HEADER)  echo -e "${C_BOLD}${msg}${C_RESET}" ;;
  esac
}

info()   { _log INFO  "$@"; }
ok()     { _log OK    "$@"; }
warn()   { _log WARN  "$@"; }
error()  { _log ERROR "$@"; }
header() { _log HEADER "$@"; }

trap '_on_error $LINENO' ERR
_on_error() {
  error "Installer failed at line $1. Check ${LOG_FILE} for details."
  exit 1
}

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
INSTALL_DIR="/opt/ecube"
API_PORT="8443"
_EXPLICIT_API_PORT=false   # set when --api-port is passed explicitly
HOSTNAME_OVERRIDE=""
CERT_VALIDITY="730"
YES=false
UNINSTALL=false
DRY_RUN=false
VERSION_TAG=""
DROP_DATABASE=false
BACKEND_NO_TLS=false
FIREWALL_CIDR=""

# Credentials for the PostgreSQL superuser created during installation.
# Populated by _provision_pg_superuser and printed in the post-install summary
# so the operator knows what to enter in the setup wizard.
PG_SUPERUSER_NAME=""
PG_SUPERUSER_PASS=""

GITHUB_OWNER="t3knoid"
GITHUB_REPO="ecube"

# Runtime state

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
usage() {
  cat <<EOF
Usage: sudo ./install.sh [OPTIONS]

Options:
  --install-dir DIR      Root installation directory  (default: /opt/ecube)
  --api-port PORT        Port for the service          (default: 8443, or 80 with --no-tls)
  --no-tls               Disable TLS entirely (plain HTTP, default port 80).
                         WARNING: all traffic is unencrypted.
  --pg-superuser-name NAME
                         Name for the PostgreSQL superuser created during
                         installation (default: \$POSTGRES_USER or 'ecube').
                         Skips the interactive prompt when supplied.
  --pg-superuser-pass PASS
                         Password for the PostgreSQL superuser (default:
                         \$POSTGRES_PASSWORD or 'ecube'). Skips the interactive
                         prompt when supplied. Must be non-empty and contain
                         no whitespace.
  --hostname HOST        Hostname/IP for TLS cert CN  (default: \$(hostname -f))
  --cert-validity DAYS   Self-signed cert validity    (default: 730, max: 730 — 2 years)
  --yes, -y              Non-interactive / unattended mode
  --firewall-cidr CIDR   Source CIDR to allow through ufw for the API port
                         (e.g. 192.168.1.0/24).  In --yes mode, if this is not
                         provided the firewall rule is SKIPPED (safe default).
                         Use 'any' to explicitly open to all sources.
  --version TAG          Download and install a specific GitHub release tag.
                         Must be exact format: v<major>.<minor>.<patch> (e.g. v0.2.0).
                         Pre-releases, build metadata, and tags without a leading v
                         are not supported.
  --uninstall            Remove ECUBE from this host
  --drop-database        With --uninstall, also drop the configured application
                         database (best-effort; requires sufficient DB privileges)
  --dry-run              Print all actions without executing them
  -h, --help             Show this help message
EOF
}

# ---------------------------------------------------------------------------
# _extract_env_value  ENV_FILE  VAR_NAME
#
# Reads the last occurrence of VAR_NAME=... from ENV_FILE, strips
# leading/trailing whitespace and a single layer of matched surrounding
# quotes (double or single).  Prints the cleaned value to stdout.
# Returns 1 (with no output) when the file is missing, the variable is
# absent, the value is empty, or it looks like an unfilled placeholder
# (i.e. "<...>").
# ---------------------------------------------------------------------------
_extract_env_value() {
  local env_file="$1" var_name="$2"
  [[ -f "${env_file}" ]] || return 1

  local _line
  _line="$(grep -E "^[[:space:]]*${var_name}=" "${env_file}" 2>/dev/null | tail -1 || true)"
  [[ -n "${_line}" ]] || return 1

  local _val="${_line#*=}"
  # Trim leading/trailing whitespace.
  _val="${_val#"${_val%%[![:space:]]*}"}"
  _val="${_val%"${_val##*[![:space:]]}"}"
  # Strip one layer of matched surrounding quotes.
  if (( ${#_val} >= 2 )); then
    local _fc="${_val:0:1}" _lc="${_val: -1}"
    if [[ "${_fc}" == '"' && "${_lc}" == '"' ]] ||
       [[ "${_fc}" == "'" && "${_lc}" == "'" ]]; then
      _val="${_val:1:${#_val}-2}"
    fi
  fi
  [[ -n "${_val}" ]] || return 1
  [[ "${_val}" == "<"*">" ]] && return 1

  printf '%s' "${_val}"
  return 0
}

_extract_database_url_from_env() {
  _extract_env_value "$1" "DATABASE_URL"
}

_extract_setup_admin_username_from_env() {
  _extract_env_value "$1" "SETUP_DEFAULT_ADMIN_USERNAME"
}

_cleanup_pg_superuser_role() {
  local env_file="${INSTALL_DIR}/.env"

  if [[ ! -f "${env_file}" ]]; then
    warn "PostgreSQL superuser cleanup skipped: ${env_file} not found."
    return
  fi

  # Resolve from persisted install state only; do not guess/fallback.
  local su_name
  su_name="$(_extract_setup_admin_username_from_env "${env_file}" || true)"
  if [[ -z "${su_name}" ]]; then
    warn "PostgreSQL superuser cleanup skipped: SETUP_DEFAULT_ADMIN_USERNAME not found in ${env_file}."
    return
  fi

  if ! _is_valid_db_user "${su_name}"; then
    warn "PostgreSQL superuser cleanup skipped: invalid role name '${su_name}'."
    return
  fi

  if ! command -v psql &>/dev/null; then
    warn "PostgreSQL superuser cleanup skipped: psql not found."
    return
  fi

  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would drop PostgreSQL role '${su_name}' if it exists"
    return
  fi

  # Use peer authentication via the postgres OS user — avoids needing the
  # role's password and avoids the self-drop problem (connecting as the very
  # role you want to DROP).
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname = '${su_name}'" 2>/dev/null | grep -q 1; then
    info "PostgreSQL role '${su_name}' not found — skipping role cleanup."
    return
  fi

  local escaped_su_name
  escaped_su_name="${su_name//\"/\"\"}"
  local drop_out
  if ! drop_out="$(sudo -u postgres psql -v ON_ERROR_STOP=1 -c "DROP OWNED BY \"${escaped_su_name}\"; DROP ROLE IF EXISTS \"${escaped_su_name}\";" 2>&1)"; then
    warn "Failed to drop PostgreSQL role '${su_name}': ${drop_out}"
    return
  fi

  ok "PostgreSQL role '${su_name}' removed"
}

_cleanup_application_database() {
  local db_url=""
  local env_file="${INSTALL_DIR}/.env"

  # Cleanup target is derived strictly from DATABASE_URL in .env.
  db_url="$(_extract_database_url_from_env "${env_file}" || true)"

  if [[ -z "${db_url}" ]]; then
    warn "Database cleanup skipped: no usable DATABASE_URL found in ${env_file}."
    return 0
  fi

  if ! command -v psql &>/dev/null; then
    warn "Database cleanup skipped: psql not found."
    return 0
  fi

  local py_bin
  if command -v python3.11 &>/dev/null; then
    py_bin="python3.11"
  elif command -v python3 &>/dev/null; then
    py_bin="python3"
  else
    warn "Database cleanup skipped: python3 is required to parse DATABASE_URL safely."
    return 0
  fi

  # Extract only the database name from DATABASE_URL; connection is via peer auth.
  local target_db
  target_db="$(${py_bin} -c "
import sys
from urllib.parse import urlparse
db_name = urlparse(sys.argv[1]).path.lstrip('/')
if not db_name:
    raise SystemExit(1)
print(db_name)
" "${db_url}" 2>/dev/null)" || {
    warn "Database cleanup skipped: failed to parse DATABASE_URL."
    return 0
  }

  if [[ -z "${target_db}" ]]; then
    warn "Database cleanup skipped: could not determine database name from DATABASE_URL."
    return 0
  fi

  # Never drop PostgreSQL maintenance/system databases by default. During the
  # new setup flow, DATABASE_URL may temporarily point at /postgres before
  # the application database is provisioned.
  if [[ "${target_db}" == "postgres" || "${target_db}" == "template0" || "${target_db}" == "template1" ]]; then
    warn "Database cleanup skipped: DATABASE_URL points to maintenance database '${target_db}'."
    return 0
  fi

  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would drop application database '${target_db}'"
    return 0
  fi

  info "Attempting database cleanup for '${target_db}'..."

  # Use peer authentication via the postgres OS user — the cluster superuser
  # can always terminate sessions and drop databases without needing a password.
  if ! sudo -u postgres psql -v ON_ERROR_STOP=1 -v db_name="${target_db}" \
      -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :'db_name' AND pid <> pg_backend_pid();" \
      >/dev/null 2>&1; then
    warn "Could not terminate active sessions for '${target_db}' (continuing with drop attempt)."
  fi

  local _drop_out
  if ! _drop_out="$(sudo -u postgres psql -v ON_ERROR_STOP=1 \
      -c "DROP DATABASE IF EXISTS \"${target_db//\"/\"\"}\";" 2>&1)"; then
    # If sessions are still attached, retry with FORCE for PostgreSQL 13+.
    if printf '%s' "${_drop_out}" | grep -qi "being accessed by other users"; then
      if ! _drop_out="$(sudo -u postgres psql -v ON_ERROR_STOP=1 \
          -c "DROP DATABASE IF EXISTS \"${target_db//\"/\"\"}\" WITH (FORCE);" 2>&1)"; then
        warn "Database cleanup failed for '${target_db}': ${_drop_out}"
        return 0
      fi
    else
      warn "Database cleanup failed for '${target_db}': ${_drop_out}"
      return 0
    fi
  fi

  ok "Database '${target_db}' dropped"
}

# Validate that a hostname/IP argument contains only DNS- and IP-safe characters.
# Delegates to _is_valid_host so the allowed character set is defined once.
_validate_host_arg() {
  local flag="$1" val="$2"
  if ! _is_valid_host "${val}"; then
    echo "ERROR: ${flag} value '${val}' is not a valid hostname or IP address." >&2
    echo "       Accepted forms: DNS name (e.g. host.example.com), IPv4 (e.g. 192.168.1.1)," >&2
    echo "       bare IPv6 (e.g. 2001:db8::1), or bracketed IPv6 (e.g. [2001:db8::1])." >&2
    echo "       host:port forms are not accepted — supply the host and port separately." >&2
    exit 1
  fi
}

# Validate that a port argument is a number in the range 1–65535.
# Delegates to _is_valid_port so the rule is defined once.
_validate_port_arg() {
  local flag="$1" val="$2"
  if ! _is_valid_port "${val}"; then
    echo "ERROR: ${flag} must be a number between 1 and 65535." >&2
    exit 1
  fi
}

# Pure predicate: returns 0 if val is a valid port number (1–65535), 1 otherwise.
# No output and no exit — safe to use inside interactive prompt loops.
_is_valid_port() {
  local val="$1"
  [[ "${val}" =~ ^[0-9]+$ && "${val}" -ge 1 && "${val}" -le 65535 ]]
}

# Pure predicate: returns 0 if val is a valid CIDR block, 1 otherwise.
# Accepts IPv4 (e.g. 192.168.1.0/24, prefix 0-32) and IPv6
# (e.g. 2001:db8::/32, prefix 0-128).  Intentionally rejects bare IPs
# (no prefix length) since ufw requires the /prefix form.
_is_valid_cidr() {
  local val="$1"
  # IPv4 CIDR
  if [[ "${val}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]]; then
    return 0
  fi
  # IPv6 CIDR — loose check: hex/colon chars followed by /0-128
  if [[ "${val}" =~ ^[0-9A-Fa-f:]+/([0-9]|[1-9][0-9]|1[01][0-9]|12[0-8])$ ]]; then
    return 0
  fi
  return 1
}

# Pure predicate: returns 0 if val is a valid PostgreSQL database name
# (alphanumerics and underscores only, non-empty), 1 otherwise.
_is_valid_db_name() {
  local val="$1"
  [[ -n "${val}" && ! "${val}" =~ [^a-zA-Z0-9_] ]]
}

# Pure predicate: returns 0 if val is a valid PostgreSQL username
# (non-empty, alphanumerics and underscores only — no URL-reserved characters),
# 1 otherwise.
_is_valid_db_user() {
  local val="$1"
  [[ -n "${val}" && ! "${val}" =~ [^a-zA-Z0-9_] ]]
}

# Pure predicate: returns 0 if val is an acceptable PostgreSQL password
# (non-empty, no whitespace), 1 otherwise.
_is_valid_db_pass() {
  local val="$1"
  [[ -n "${val}" && ! "${val}" =~ [[:space:]] ]]
}

# Full RFC 3986 percent-encoder: encodes every character outside the unreserved
# set (A-Za-z0-9 - _ . ~) so any valid password produces a valid connection URL.
# The value is passed via stdin so it never appears in the process argument list.
_url_encode() {
  printf '%s' "$1" | python3.11 -c \
    "import sys, urllib.parse; sys.stdout.write(urllib.parse.quote(sys.stdin.read(), safe=''))"
}

# Pure predicate: returns 0 if val is a valid DNS name or IP address, 1 otherwise.
# No output and no exit — safe to use inside interactive prompt loops.
_is_valid_host() {
  local val="$1"

  # Reject empty values immediately.
  if [[ -z "${val}" ]]; then
    return 1
  fi

  # Bracketed IPv6 literal: [<content>]
  # Strip the brackets and require the interior to look like IPv6 (hex digits,
  # colons, dots only) and contain at least two colons — the shortest valid IPv6
  # address ("::" or "::1") always has two.
  if [[ "${val}" == \[*\] ]]; then
    local inner="${val:1:${#val}-2}"
    if [[ "${inner}" =~ ^[0-9A-Fa-f:.]+$ && "${inner}" == *:*:* ]]; then
      return 0
    fi
    return 1
  fi

  # Bare IPv6 literal (no brackets): must contain at least two colons.
  # This rejects "host:port" typos (exactly one colon) while accepting all
  # valid bare IPv6 forms ("::1", "2001:db8::1", etc.).
  if [[ "${val}" == *:* ]]; then
    if [[ "${val}" =~ ^[0-9A-Fa-f:.]+$ && "${val}" == *:*:* ]]; then
      return 0
    fi
    return 1
  fi

  # DNS name or IPv4 address: letters, digits, dots, and hyphens only.
  [[ "${val}" =~ ^[a-zA-Z0-9.-]+$ ]]
}

# Return the host in URL-safe form: raw IPv6 literals (containing ':' but not
# already bracketed) are wrapped in [...]; all other values pass through unchanged.
_url_host() {
  local val="$1"
  if [[ "${val}" == *:* && "${val}" != \[* ]]; then
    echo "[${val}]"
  else
    echo "${val}"
  fi
}

# Pure predicate: returns 0 if val is an IPv4 or IPv6 address literal, 1 if it
# is a DNS name.  Surrounding brackets on IPv6 (e.g. [::1]) are stripped before
# the test.  Used by cert generation to decide whether to emit an IP SAN or a
# DNS SAN for HOST — DNS SANs containing ':' or '[' are invalid per RFC 5280.
_is_ip() {
  local val="${1#[}"; val="${val%]}"

  # IPv4: exactly four dot-separated octets, each 0–255.
  if [[ "${val}" == *.* && "${val}" != *:* ]]; then
    local IFS='.'
    local octets
    read -r -a octets <<< "${val}"
    if [[ "${#octets[@]}" -eq 4 ]]; then
      local o valid_ipv4=1
      for o in "${octets[@]}"; do
        # Must be all digits.
        [[ "${o}" =~ ^[0-9]+$ ]] || { valid_ipv4=0; break; }
        # Each octet must be within 0–255.
        if ! (( o >= 0 && o <= 255 )); then
          valid_ipv4=0
          break
        fi
      done
      if [[ "${valid_ipv4}" -eq 1 ]]; then
        return 0
      fi
    fi
  fi

  # IPv6: require at least one colon and only hex digits, colons, and dots
  # (dots allow IPv4-mapped forms like ::ffff:192.0.2.1).
  if [[ "${val}" == *:* && "${val}" =~ ^[0-9A-Fa-f:.]+$ ]]; then
    return 0
  fi
  return 1
}

# Verify that a flag's value argument is present and does not look like the
# next flag.  Uses ${2-} (default-empty) so set -u does not abort first.
_require_arg() {
  local flag="$1" val="${2-}"
  if [[ -z "${val}" || "${val}" == --* ]]; then
    echo "ERROR: ${flag} requires a non-empty argument." >&2
    exit 1
  fi
}

_validate_install_dir_arg() {
  local flag="$1" val="$2"
  if [[ "${val}" != /* ]]; then
    echo "ERROR: ${flag} must be an absolute path (starting with /)." >&2
    exit 1
  fi
  if [[ "${val}" =~ [^A-Za-z0-9_./-] ]]; then
    echo "ERROR: ${flag} path may only contain letters, digits, '.', '_', '-', and '/' (got '${val}')." >&2
    exit 1
  fi
  local _canonical
  _canonical="$(realpath -m "${val}" 2>/dev/null || echo "${val}")"
  local _d
  local _dangerous=("/" "/bin" "/boot" "/dev" "/etc" "/home" "/lib" "/lib64"
                    "/media" "/mnt" "/opt" "/proc" "/root" "/run" "/sbin"
                    "/srv" "/sys" "/tmp" "/usr" "/var")
  for _d in "${_dangerous[@]}"; do
    if [[ "${_canonical}" == "${_d}" ]]; then
      echo "ERROR: ${flag} '${val}' is a protected system path." >&2; exit 1
    fi
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-tls)         BACKEND_NO_TLS=true; shift ;;
    --pg-superuser-name)
      _require_arg "$1" "${2-}"
      if ! _is_valid_db_user "$2"; then
        echo "ERROR: --pg-superuser-name must contain only alphanumerics and underscores." >&2; exit 1
      fi
      PG_SUPERUSER_NAME="$2"; shift 2 ;;
    --pg-superuser-pass)
      _require_arg "$1" "${2-}"
      if ! _is_valid_db_pass "$2"; then
        echo "ERROR: --pg-superuser-pass must be non-empty and contain no whitespace." >&2; exit 1
      fi
      PG_SUPERUSER_PASS="$2"; shift 2 ;;
    --install-dir)
      _require_arg "$1" "${2-}"
      _validate_install_dir_arg "$1" "$2"
      INSTALL_DIR="$2"; shift 2 ;;
    --api-port)
      _require_arg "$1" "${2-}"
      _validate_port_arg "$1" "$2"
      API_PORT="$2"; _EXPLICIT_API_PORT=true; shift 2 ;;
    --hostname)
      _require_arg "$1" "${2-}"
      _validate_host_arg "--hostname" "$2"
      HOSTNAME_OVERRIDE="$2"; shift 2 ;;
    --cert-validity)
      _require_arg "$1" "${2-}"
      if [[ ! "$2" =~ ^[0-9]+$ || "$2" -lt 1 || "$2" -gt 730 ]]; then
        echo "ERROR: --cert-validity must be a whole number between 1 and 730 (days). Maximum is 730 days (2 years)." >&2; exit 1
      fi
      CERT_VALIDITY="$2"; shift 2 ;;
    --yes|-y)         YES=true;  shift ;;
    --firewall-cidr)
      _require_arg "$1" "${2-}"
      FIREWALL_CIDR="$2"; shift 2 ;;
    --version)
      _require_arg "$1" "${2-}"
      if [[ ! "$2" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        error "--version value '$2' is invalid. Expected format: v<major>.<minor>.<patch> (e.g. v0.2.0)."
        exit 1
      fi
      VERSION_TAG="$2"; shift 2 ;;
    --uninstall)      UNINSTALL=true; shift ;;
    --drop-database)  DROP_DATABASE=true; shift ;;
    --dry-run)        DRY_RUN=true; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) error "Unknown option: $1"; usage; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Post-parse: --no-tls port defaults
# ---------------------------------------------------------------------------
if [[ "${BACKEND_NO_TLS}" == true ]]; then
  [[ "${_EXPLICIT_API_PORT}" == false ]] && API_PORT="80"
fi
# ---------------------------------------------------------------------------

run() {
  if [[ "${DRY_RUN}" == true ]]; then
    echo -e "${C_YELLOW}[DRY-RUN]${C_RESET} $*"
  else
    "$@"
  fi
}

# Run a command as the ecube user, dropping privileges from root.
# Prefers runuser(1) (util-linux, always present on Debian/Ubuntu and does not
# require a sudoers entry) and falls back to sudo -u for environments where
# runuser is somehow absent.  Dry-run is forwarded via run() so the command is
# only printed, never executed.
_run_as_ecube() {
  if command -v runuser &>/dev/null; then
    run runuser -u ecube -- "$@"
  else
    run sudo -u ecube "$@"
  fi
}

# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------
_detect_version() {
  local pyproject="${INSTALL_DIR}/pyproject.toml"
  if [[ -f "${pyproject}" ]]; then
    sed -n 's/^version = "\([^"]*\)".*/\1/p' "${pyproject}" 2>/dev/null || echo "unknown"
  else
    echo "unknown"
  fi
}

# ---------------------------------------------------------------------------
# Prompt helper
# ---------------------------------------------------------------------------
_confirm() {
  local prompt="$1"
  if [[ "${YES}" == true ]]; then
    info "${prompt} [auto-yes]"
    return 0
  fi
  read -r -p "$(echo -e "${C_YELLOW}${prompt}${C_RESET} [y/N] ")" answer
  [[ "${answer,,}" == "y" || "${answer,,}" == "yes" ]]
}

# ---------------------------------------------------------------------------
# Initialise log file
# ---------------------------------------------------------------------------
_init_log() {
  if [[ "${DRY_RUN}" == true ]]; then return; fi
  touch "${LOG_FILE}" 2>/dev/null || { warn "Cannot write to ${LOG_FILE}; continuing without file log."; LOG_FILE=/dev/null; }
  chmod 640 "${LOG_FILE}" 2>/dev/null || true
  info "Install log: ${LOG_FILE}"
}

# ===========================================================================
# PRE-FLIGHT CHECKS
# ===========================================================================
preflight() {
  header "\n── Pre-flight checks ──────────────────────────────────────────"

  # Running as root
  if [[ "${EUID}" -ne 0 ]]; then
    error "This script must be run as root (or via sudo)."
    exit 1
  fi
  ok "Running as root"

  # Debian / Ubuntu
  if [[ ! -f /etc/os-release ]]; then
    error "Cannot determine OS: /etc/os-release not found. Debian/Ubuntu required."
    exit 1
  fi
  # shellcheck source=/dev/null
  source /etc/os-release
  if [[ "${ID}" != "debian" && "${ID}" != "ubuntu" && "${ID_LIKE:-}" != *"debian"* ]]; then
    error "Unsupported OS '${ID}'. Only Debian/Ubuntu is supported."
    exit 1
  fi
  ok "OS: ${PRETTY_NAME}"

  # Disk space >= 2 GB at install dir
  local parent_dir
  parent_dir="$(dirname "${INSTALL_DIR}")"
  [[ -d "${INSTALL_DIR}" ]] && parent_dir="${INSTALL_DIR}"
  if [[ ! -d "${parent_dir}" ]]; then
    error "Parent directory '${parent_dir}' does not exist."
    error "Create it before running the installer, e.g.: sudo mkdir -p '${parent_dir}'"
    exit 1
  fi
  local free_kb
  free_kb=$(df -k "${parent_dir}" | awk 'NR==2 {print $4}')
  if [[ ! "${free_kb}" =~ ^[0-9]+$ ]]; then
    error "Could not determine free disk space at ${parent_dir} — df/awk returned '${free_kb}'. Is df from coreutils and the filesystem mounted?"
    exit 1
  fi
  if (( free_kb < 2097152 )); then
    error "Insufficient disk space at ${parent_dir}: need ≥ 2 GiB, have $(( free_kb / 1024 )) MiB."
    exit 1
  fi
  ok "Disk space: $(( free_kb / 1024 / 1024 )) GiB free"

  # Required commands
  local required_cmds=("curl" "openssl" "systemctl")
  # VERSION_TAG triggers _maybe_download_release, which unconditionally uses
  # mktemp, sha256sum, tar, and awk.  Catch missing tools here rather than
  # mid-run with a cryptic trap failure.
  if [[ -n "${VERSION_TAG}" ]]; then
    required_cmds+=("mktemp" "sha256sum" "tar" "awk")
  fi
  for cmd in "${required_cmds[@]}"; do
    if ! command -v "${cmd}" &>/dev/null; then
      error "Required command not found: ${cmd}"
      exit 1
    else
      ok "Command found: ${cmd}"
    fi
  done

  # Optional but recommended commands
  if ! command -v ip &>/dev/null; then
    warn "ip (iproute2) not found — host IP detection will fall back to 'hostname -I'. Install iproute2 for reliable results."
  else
    ok "Command found: ip"
  fi

  # Python 3.11
  # Privilege-drop tool: runuser (preferred) or sudo
    if ! command -v runuser &>/dev/null && ! command -v sudo &>/dev/null; then
      error "Neither 'runuser' nor 'sudo' was found. One of these is required to"
      error "run the Python venv/pip steps as the 'ecube' user."
      error "Install sudo (apt-get install sudo) or ensure util-linux is present."
      exit 1
    fi
    if command -v runuser &>/dev/null; then
      ok "Privilege-drop tool: runuser"
    else
      ok "Privilege-drop tool: sudo (runuser not found)"
    fi

    if ! command -v python3.11 &>/dev/null; then
      warn "python3.11 not found."
      if [[ "${ID}" == "ubuntu" ]]; then
        local prompt_msg="Install python3.11 via the deadsnakes PPA (ppa:deadsnakes/ppa)?"
      else
        local prompt_msg="Install python3.11 from official Debian repositories (backports if needed)?"
      fi
      if _confirm "${prompt_msg}"; then
        run apt-get update -qq
        if [[ "${ID}" == "ubuntu" ]]; then
          # deadsnakes PPA — Ubuntu only
          run apt-get install -y software-properties-common
          run add-apt-repository -y ppa:deadsnakes/ppa
        else
          # Debian: install python3.11 from official Debian repos / backports.
          # Debian 12 (Bookworm) ships python3.11 in main; Debian 11 (Bullseye)
          # requires bullseye-backports.  No remote script is executed.
          local codename
          codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-}")"
          # Reject anything that isn't a simple Debian codename (lowercase letters,
          # digits, hyphens) before interpolating into a bash -c string and a
          # sources.list.d filename executed as root.
          if [[ ! "${codename}" =~ ^[a-z][a-z0-9-]*$ ]]; then
            error "Cannot determine a safe Debian codename from /etc/os-release (got '${codename}')."
            error "Please add the backports repository manually and re-run."
            exit 1
          fi
          if ! apt-cache show python3.11 &>/dev/null; then
            info "python3.11 not in ${codename} main; enabling ${codename}-backports ..."
            run bash -c "echo 'deb https://deb.debian.org/debian ${codename}-backports main' \
              | tee /etc/apt/sources.list.d/${codename}-backports.list >/dev/null"
            run apt-get update -qq
            if ! apt-cache show python3.11 &>/dev/null; then
              error "python3.11 is not available in ${codename} main or ${codename}-backports."
              error "Please install python3.11 manually or upgrade to Debian 12 (Bookworm)."
              exit 1
            fi
          fi
        fi
        run apt-get update -qq
        run apt-get install -y python3.11 python3.11-venv
        # Optional: install distutils only when apt has an install candidate.
        # Some newer Debian/Ubuntu releases no longer provide python3-distutils.
        if apt-cache policy python3-distutils 2>/dev/null | grep -qv 'Candidate: (none)'; then
          run apt-get install -y python3-distutils || warn "python3-distutils install failed; continuing (optional package)."
        else
          info "python3-distutils not available in configured apt repositories; skipping (optional package)."
        fi
        ok "python3.11 installed"
      else
        error "python3.11 is required. Aborting."
        exit 1
      fi
    else
      # python3.11 is present; ensure the 'venv' module is available
      if python3.11 -m venv --help >/dev/null 2>&1; then
        ok "python3.11: $(python3.11 --version 2>&1) (venv available)"
      else
        warn "python3.11 is installed but the 'venv' module is not available."
        if [[ "${ID}" == "ubuntu" || "${ID}" == "debian" ]]; then
          if _confirm "Install python3.11-venv so virtual environments can be created?"; then
            apt-get update
            apt-get install -y python3.11-venv
            if python3.11 -m venv --help >/dev/null 2>&1; then
              ok "python3.11-venv installed; 'venv' module is now available."
            else
              error "python3.11-venv was installed but 'python3.11 -m venv' still fails. Aborting."
              exit 1
            fi
          else
            error "The 'venv' module for python3.11 is required to continue. Aborting."
            exit 1
          fi
        else
          error "The 'venv' module for python3.11 is missing. Please install the appropriate package for your distribution (e.g. python3.11-venv on Debian/Ubuntu)."
          exit 1
        fi
      fi
    fi

  # Port availability
  _check_port "${API_PORT}" "API"

  ok "Pre-flight checks passed"
}

_check_port() {
  local port="$1"
  local label="$2"
  if [[ "${DRY_RUN}" == true ]]; then
    echo -e "${C_YELLOW}[DRY-RUN]${C_RESET} Would check port ${port} (${label}) is available"
    return
  fi
  if ! command -v ss &>/dev/null; then
    warn "Port ${port} (${label}): ss not found — cannot verify availability. Install iproute2 to enable port checks."
    return
  fi
  if ss -tlnp 2>/dev/null | grep -qE ":${port}\b"; then
    error "Port ${port} (${label}) is already in use."
    exit 1
  fi
  ok "Port ${port} (${label}) is available"
}

# ===========================================================================
# RESOLVE HOSTNAME / IP
# ===========================================================================
_resolve_host() {
  HOST="${HOSTNAME_OVERRIDE:-$(hostname -f 2>/dev/null || hostname)}"

  # Validate HOST before it is embedded in an OpenSSL -subj field.
  # --hostname is already validated at parse time, so
  # this guard primarily catches unsafe values returned by `hostname -f`.
  if ! _is_valid_host "${HOST}"; then
    warn "Resolved hostname '${HOST}' contains characters unsafe for OpenSSL — falling back to 'localhost'."
    HOST="localhost"
  fi

  # Primary non-loopback IPv4 — prefer `ip` (iproute2), fall back to `hostname -I`.
  if command -v ip &>/dev/null; then
    HOST_IP=$(ip -4 addr show scope global 2>/dev/null | awk '/inet/{print $2}' | cut -d/ -f1 | head -1 || true)
  else
    HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
  fi
  HOST_IP="${HOST_IP:-127.0.0.1}"
  # Guard: ip/hostname -I can sometimes produce garbage on unusual network
  # configurations.  If the result isn't a valid IP, fall back to 127.0.0.1
  # so OpenSSL cert generation never receives a malformed IP SAN value.
  if ! _is_ip "${HOST_IP}"; then
    warn "Detected HOST_IP '${HOST_IP}' is not a valid IP address — falling back to 127.0.0.1."
    HOST_IP="127.0.0.1"
  fi
  info "Hostname: ${HOST}  IP: ${HOST_IP}"
}

# ===========================================================================
# TLS CERTIFICATES
# ===========================================================================
_reconcile_cert_permissions() {
  local cert_dir="$1"

  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would set ${cert_dir}/key.pem mode 600 owner ecube:ecube"
    echo "[DRY-RUN] Would set ${cert_dir}/cert.pem mode 644 owner ecube:ecube"
    return
  fi

  chmod 600 "${cert_dir}/key.pem"
  chmod 644 "${cert_dir}/cert.pem"
  chown ecube:ecube "${cert_dir}/key.pem" "${cert_dir}/cert.pem"
}

_generate_certs() {
  local cert_dir="${INSTALL_DIR}/certs"
  # Normalise bracketed IPv6 literals once ([2001:db8::1] → 2001:db8::1) so
  # the bare address is used consistently in the CN, SANs, and log messages.
  # For DNS names and IPv4, _bare_host == HOST (nothing is stripped).
  local _bare_host="${HOST#[}"; _bare_host="${_bare_host%]}"
  if [[ -f "${cert_dir}/cert.pem" && -f "${cert_dir}/key.pem" ]]; then
    info "TLS certificates already exist — skipping generation and reconciling permissions for current topology."
    _reconcile_cert_permissions "${cert_dir}"
    return
  fi
  info "Generating self-signed TLS certificate (CN=${_bare_host}, validity=${CERT_VALIDITY} days)..."
  run mkdir -p "${cert_dir}"
  # Build the SubjectAltName extension correctly based on whether HOST is an IP
  # literal or a DNS name.  A DNS SAN containing ':' or brackets (as produced
  # by an IPv6 HOST) is invalid per RFC 5280 §4.2.1.6 and is rejected by
  # modern TLS stacks.
  #   * IP literal (IPv4 or IPv6): emit IP SANs only; include HOST_IP as a
  #     second IP SAN (deduplicated when HOST and HOST_IP are the same address).
  #   * DNS name: emit DNS:_bare_host + IP:HOST_IP (original behaviour).
  local _san
  if _is_ip "${_bare_host}"; then
    if [[ "${_bare_host}" == "${HOST_IP}" ]]; then
      _san="IP:${_bare_host}"
    else
      _san="IP:${_bare_host},IP:${HOST_IP}"
    fi
  else
    _san="DNS:${_bare_host},IP:${HOST_IP}"
  fi
  info "Certificate SANs: ${_san}"
  run openssl req -x509 -nodes -days "${CERT_VALIDITY}" -newkey rsa:2048 \
    -keyout "${cert_dir}/key.pem" \
    -out    "${cert_dir}/cert.pem" \
    -subj   "/CN=${_bare_host}" \
    -addext "subjectAltName=${_san}" \
    2>>"${LOG_FILE}"
  _reconcile_cert_permissions "${cert_dir}"
  ok "TLS certificates written to ${cert_dir}"
}

# ===========================================================================
# ENSURE ECUBE SYSTEM USER 
# ===========================================================================
_ensure_ecube_user() {
  if ! id -u ecube &>/dev/null; then
    info "Creating system user 'ecube'..."
    run useradd --system --create-home --home-dir "${INSTALL_DIR}" \
      --shell /usr/sbin/nologin ecube
    ok "User 'ecube' created"
  else
    info "User 'ecube' already exists — skipping."
  fi
}

# ==========================================================================
# INSTALL SUDOERS POLICY FOR OS USER/GROUP MANAGEMENT + MOUNT OPERATIONS
# Required so the ecube service account can run narrowly-scoped user/group
# commands and mount/unmount commands non-interactively from API endpoints.
# ==========================================================================
_install_os_user_mgmt_sudoers() {
  local sudoers_file="/etc/sudoers.d/ecube-user-mgmt"
  local sudoers_tmp="${sudoers_file}.tmp"

  info "Installing sudoers policy for ECUBE OS user/group management, mount operations, and drive formatting/eject..."

  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would write ${sudoers_file} with NOPASSWD rules for user/group management, mount, sync, and mkfs binaries"
    return
  fi

  mkdir -p /etc/sudoers.d
  cat > "${sudoers_tmp}" <<'EOF_SUDOERS'
# /etc/sudoers.d/ecube-user-mgmt
# Narrowly scoped privilege escalation for the ECUBE service account.
ecube ALL=(root) NOPASSWD: /usr/sbin/useradd, /usr/sbin/usermod, /usr/sbin/userdel, /usr/sbin/groupadd, /usr/sbin/groupdel, /usr/sbin/chpasswd
ecube ALL=(root) NOPASSWD: /bin/mount, /bin/umount, /sbin/mount.nfs, /usr/sbin/mount.nfs
ecube ALL=(root) NOPASSWD: /bin/sync, /sbin/mkfs.ext4, /sbin/mkfs.exfat
ecube ALL=(root) NOPASSWD: /bin/mkdir, /bin/chown, /usr/bin/chown
EOF_SUDOERS
  chmod 0440 "${sudoers_tmp}"
  chown root:root "${sudoers_tmp}"

  # Validate before activating. If visudo is missing, keep the generated file
  # (static content) but warn the operator.
  if command -v visudo &>/dev/null; then
    if ! visudo -cf "${sudoers_tmp}" >/dev/null; then
      rm -f "${sudoers_tmp}"
      error "Generated sudoers policy failed validation: ${sudoers_tmp}"
      exit 1
    fi
  else
    warn "visudo not found — unable to validate ${sudoers_tmp}; installing static policy file."
  fi

  mv -f "${sudoers_tmp}" "${sudoers_file}"
  ok "Sudoers policy installed: ${sudoers_file}"
}

_install_pam_config() {
  local pam_dest="/etc/pam.d/ecube"
  local script_dir
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  local pam_src="${script_dir}/deploy/ecube-pam"

  info "Installing ECUBE PAM configuration..."

  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would install ${pam_src} → ${pam_dest}"
    return
  fi

  if [[ ! -f "${pam_src}" ]]; then
    warn "PAM config source not found: ${pam_src} — skipping PAM installation."
    return
  fi

  # Only install pam_sss line if SSSD is actually present on the host
  if command -v sssd &>/dev/null || [[ -f /lib/security/pam_sss.so || -f /lib/x86_64-linux-gnu/security/pam_sss.so ]]; then
    install -m 0644 -o root -g root "${pam_src}" "${pam_dest}"
    ok "PAM config installed with SSSD support: ${pam_dest}"
  else
    # SSSD not present — install a local-only (pam_unix) variant
    install -m 0644 -o root -g root /dev/stdin "${pam_dest}" <<'EOF_PAM'
# /etc/pam.d/ecube
# Local-only PAM configuration (SSSD not detected at install time).
# Re-run the installer after installing SSSD to enable domain user authentication.
auth    sufficient  pam_unix.so nullok
auth    required    pam_deny.so
account sufficient  pam_unix.so
account required    pam_deny.so
EOF_PAM
    ok "PAM config installed (local users only): ${pam_dest}"
  fi
}

# ===========================================================================
# DOWNLOAD / EXTRACT RELEASE PACKAGE (when --version is given)
# ===========================================================================
_maybe_download_release() {
  if [[ -z "${VERSION_TAG}" ]]; then
    # Running from an extracted release package: copy source files into
    # INSTALL_DIR. Resolve the package root from the install script location,
    # not the caller's current working directory, so invocation from another
    # directory (for example repo-root/install.sh while cwd=dist/) still stages
    # the correct files.
    # Skip the copy when INSTALL_DIR is the package directory itself.
    local src_dir
    src_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    local required_items=(app alembic alembic.ini pyproject.toml frontend/dist)
    local missing_items=()
    for item in "${required_items[@]}"; do
      if [[ ! -e "${src_dir}/${item}" ]]; then
        missing_items+=("${item}")
      fi
    done
    if [[ ${#missing_items[@]} -gt 0 ]]; then
      error "Local install source '${src_dir}' is incomplete. Missing required items:"
      for item in "${missing_items[@]}"; do
        error "  ${item}"
      done
      error "Run the installer from an extracted release package or from the repository root."
      exit 1
    fi
    if [[ "$(realpath "${INSTALL_DIR}" 2>/dev/null || echo "${INSTALL_DIR}")" == \
          "$(realpath "${src_dir}" 2>/dev/null || echo "${src_dir}")" ]]; then
      info "INSTALL_DIR matches the package source directory (${src_dir}) — no copy needed."
      return
    fi
    info "Copying package contents from ${src_dir} to ${INSTALL_DIR}..."
    for item in install.sh app alembic alembic.ini pyproject.toml README.md LICENSE frontend/dist; do
      if [[ -e "${src_dir}/${item}" ]]; then
        run mkdir -p "${INSTALL_DIR}/$(dirname "${item}")"
        # Remove a pre-existing destination *directory* before copying so that
        # GNU cp does not nest it (cp -r src/app existing/app → existing/app/app).
        if [[ -d "${src_dir}/${item}" ]]; then
          run rm -rf "${INSTALL_DIR}/${item}"
        fi
        run cp -r "${src_dir}/${item}" "${INSTALL_DIR}/${item}"
      fi
    done
    if [[ -f "${INSTALL_DIR}/install.sh" ]]; then
      run chmod 755 "${INSTALL_DIR}/install.sh"
    fi
    ok "Package contents copied to ${INSTALL_DIR}"
    return
  fi

  local tarball_name="ecube-package-${VERSION_TAG}.tar.gz"
  local checksum_name="ecube-package-${VERSION_TAG}.sha256"
  local base_url="https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/${VERSION_TAG}"

  # In dry-run mode short-circuit the entire download path.  mktemp, curl,
  # sha256sum, and tar all have real filesystem side-effects; printing the
  # intended actions is sufficient and keeps dry-run completely side-effect-free.
  if [[ "${DRY_RUN}" == true ]]; then
    echo -e "${C_YELLOW}[DRY-RUN]${C_RESET} Would download ${base_url}/${tarball_name}"
    echo -e "${C_YELLOW}[DRY-RUN]${C_RESET} Would download ${base_url}/${checksum_name}"
    echo -e "${C_YELLOW}[DRY-RUN]${C_RESET} Would verify sha256 checksum"
    echo -e "${C_YELLOW}[DRY-RUN]${C_RESET} Would extract ${tarball_name} to ${INSTALL_DIR}"
    return
  fi

  info "Downloading ECUBE ${VERSION_TAG} from GitHub Releases..."
  # Use mktemp paths so VERSION_TAG is never interpolated into the filesystem.
  local tmp_tarball tmp_checksum
  tmp_tarball=$(mktemp /tmp/ecube-package.XXXXXXXXXX.tar.gz)
  tmp_checksum=$(mktemp /tmp/ecube-package.XXXXXXXXXX.sha256)
  curl -fsSL -o "${tmp_tarball}" "${base_url}/${tarball_name}"
  curl -fsSL -o "${tmp_checksum}" "${base_url}/${checksum_name}"

  info "Verifying checksum..."
  # sha256sum -c expects "<hash>  <path>" where the path matches the file on
  # disk.  Rather than rewriting the recorded filename in-place with sed
  # (which treats the pattern as a regex, so '.' in typical release filenames
  # like "ecube-v1.2.3.tar.gz" can match unintended characters), extract just
  # the hex digest and construct a fresh verification line ourselves.
  local recorded_hash
  recorded_hash=$(awk '{print $1}' "${tmp_checksum}")
  # Validate before constructing the verification line: a non-hex or wrong-length
  # value would embed garbage into the sha256sum input file and produce a
  # misleading error.  A newline in the value (from a crafted file) could also
  # inject a second record.
  if [[ ! "${recorded_hash}" =~ ^[0-9a-fA-F]{64}$ ]]; then
    error "Downloaded checksum file does not contain a valid SHA-256 digest (got '${recorded_hash}')."
    rm -f "${tmp_tarball}" "${tmp_checksum}"
    exit 1
  fi
  printf '%s  %s\n' "${recorded_hash}" "${tmp_tarball}" > "${tmp_checksum}"
  sha256sum -c "${tmp_checksum}"
  ok "Checksum verified"

  info "Extracting package to ${INSTALL_DIR}..."
  mkdir -p "${INSTALL_DIR}"
  tar -xzf "${tmp_tarball}" -C "${INSTALL_DIR}" --strip-components=1 --no-same-owner --no-same-permissions
  rm -f "${tmp_tarball}" "${tmp_checksum}"
}

# ===========================================================================
# POSTGRESQL SUPERUSER PROVISIONING
# ===========================================================================
# Creates a dedicated PostgreSQL superuser that the operator will enter in the
# ECUBE setup wizard database provisioning screen.  Runs as root using
# "sudo -u postgres psql" — PostgreSQL must be installed and running locally.
#
# Populates the global PG_SUPERUSER_NAME and PG_SUPERUSER_PASS variables so
# the post-install summary can display them.
# ===========================================================================
_provision_pg_superuser() {
  header "\n── PostgreSQL superuser setup ──────────────────────────────────"

  # Verify psql is available.
  if ! command -v psql &>/dev/null; then
    warn "psql not found — skipping PostgreSQL superuser creation."
    warn "Install postgresql-client and re-run, or create the superuser manually."
    return
  fi

  # Verify the local postgres unix socket is reachable.
  if [[ "${DRY_RUN}" != true ]]; then
    if ! sudo -u postgres psql -c "SELECT 1" &>/dev/null 2>&1; then
      warn "Cannot reach local PostgreSQL via unix socket."
      warn "Ensure postgresql is installed and running, then create a superuser manually."
      warn "The setup wizard requires a superuser (or a role with CREATEDB privilege)."
      return
    fi
  fi

  # Superuser name — cascade: CLI flag → POSTGRES_USER → "ecube"
  # (mirrors Docker Compose: PG_SUPERUSER_NAME:-${POSTGRES_USER:-ecube})
  local su_name="${PG_SUPERUSER_NAME}"
  if [[ -z "${su_name}" ]]; then
    su_name="${POSTGRES_USER:-ecube}"
    info "Defaulting PostgreSQL superuser name to '${su_name}'"
  else
    info "Using --pg-superuser-name: ${su_name}"
  fi

  # Superuser password — cascade: CLI flag → POSTGRES_PASSWORD → "ecube"
  local su_pass="${PG_SUPERUSER_PASS}"
  if [[ -z "${su_pass}" ]]; then
    su_pass="${POSTGRES_PASSWORD:-ecube}"
    info "Defaulting PostgreSQL superuser password from POSTGRES_PASSWORD"
  else
    info "Using --pg-superuser-pass: <provided>"
  fi

  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would create PostgreSQL superuser '${su_name}'"
    PG_SUPERUSER_NAME="${su_name}"
    PG_SUPERUSER_PASS="<provided>"
    return
  fi

  # Create or update the superuser role.
  # SUPERUSER implies CREATEDB/CREATEROLE — sufficient for the setup wizard.
  local escaped_pass
  escaped_pass="${su_pass//\'/\'\'}"    # escape single-quotes for SQL literal

  if sudo -u postgres psql -tAc \
        "SELECT 1 FROM pg_roles WHERE rolname = '${su_name}'" 2>/dev/null \
        | grep -q 1; then
    # Role exists — ensure it has superuser and update the password.
    sudo -u postgres psql -c \
      "ALTER ROLE \"${su_name}\" WITH SUPERUSER LOGIN PASSWORD '${escaped_pass}';" \
      &>/dev/null
    ok "Updated existing PostgreSQL role '${su_name}' (SUPERUSER LOGIN)"
  else
    sudo -u postgres psql -c \
      "CREATE ROLE \"${su_name}\" WITH SUPERUSER LOGIN PASSWORD '${escaped_pass}';" \
      &>/dev/null
    ok "Created PostgreSQL superuser '${su_name}'"
  fi

  PG_SUPERUSER_NAME="${su_name}"
  PG_SUPERUSER_PASS="${su_pass}"

  # Keep setup wizard default admin username aligned with the superuser
  # created by install.sh.
  local env_file="${INSTALL_DIR}/.env"
  if [[ -f "${env_file}" ]]; then
    sed -i '/^SETUP_DEFAULT_ADMIN_USERNAME=/d' "${env_file}"
    printf 'SETUP_DEFAULT_ADMIN_USERNAME=%s\n' "${su_name}" >> "${env_file}"

    # Write PG_SUPERUSER_NAME and PG_SUPERUSER_PASS so the setup wizard can
    # auto-fill them — same behaviour as Docker Compose.  The wizard clears
    # both values from .env after successful provisioning.
    sed -i '/^PG_SUPERUSER_NAME=/d' "${env_file}"
    printf 'PG_SUPERUSER_NAME=%s\n' "${su_name}" >> "${env_file}"
    sed -i '/^PG_SUPERUSER_PASS=/d' "${env_file}"
    printf 'PG_SUPERUSER_PASS=%s\n' "${su_pass}" >> "${env_file}"

    chown ecube:ecube "${env_file}" 2>/dev/null || true
    chmod 600 "${env_file}" 2>/dev/null || true
  fi
}

# ===========================================================================
# BACKEND INSTALLATION
# ===========================================================================
install_backend() {
  header "\n── Backend installation ────────────────────────────────────────"

  # 1. System user and USB device access
  _ensure_ecube_user

  # Ensure setup endpoints can manage OS users/groups without interactive sudo.
  _install_os_user_mgmt_sudoers

  # Install the dedicated PAM config so both local and domain users can authenticate.
  _install_pam_config

  # 2. Add ecube to required system groups
  # 'shadow' membership allows PAM local password checks to work on hardened
  # hosts where unix_chkpwd helper privilege transitions are restricted.
  for grp in plugdev dialout shadow; do
    if getent group "${grp}" &>/dev/null; then
      run usermod -aG "${grp}" ecube
      ok "Added ecube to group '${grp}'"
    fi
  done

  # 3. Extract / prepare installation directory
  run mkdir -p "${INSTALL_DIR}"
  _maybe_download_release
  run chown -R ecube:ecube "${INSTALL_DIR}"
  run chmod 750 "${INSTALL_DIR}"

  # 4. /var/lib/ecube runtime directory
  run mkdir -p /var/lib/ecube
  run chown -R ecube:ecube /var/lib/ecube
  run chmod 700 /var/lib/ecube

  # 4b. Application log directory (used when LOG_FILE is enabled).
  run mkdir -p /var/log/ecube
  run chown -R ecube:ecube /var/log/ecube
  run chmod 750 /var/log/ecube

  # 4c. Managed network mount roots used for auto-generated mountpoints.
  # Must be service-account owned so mountpoint create/remove does not rely on
  # root-owned directories.
  run mkdir -p /nfs /smb
  run chown ecube:ecube /nfs /smb
  run chmod 755 /nfs /smb

  # 5. Python virtual environment
  # Run venv creation and pip installs as the ecube user so all files under
  # ${INSTALL_DIR} are owned by ecube:ecube from the start, and package
  # install hooks never execute with full root privileges.
  local venv_dir="${INSTALL_DIR}/venv"
  if [[ ! -d "${venv_dir}" ]]; then
    info "Creating Python virtual environment..."
    _run_as_ecube python3.11 -m venv "${venv_dir}"
  fi
  info "Installing Python dependencies..."
  _run_as_ecube "${venv_dir}/bin/pip" install --quiet --upgrade pip setuptools wheel
  _run_as_ecube "${venv_dir}/bin/pip" install --quiet -e "${INSTALL_DIR}"
  ok "Python environment ready at ${venv_dir}"

  # 6. TLS certificates
  if [[ "${BACKEND_NO_TLS}" == true ]]; then
    info "--no-tls: skipping TLS certificate generation."
  else
    _generate_certs
  fi

  # 7. .env file
  _write_env_file

  # 8. Deploy the pre-built frontend bundle so FastAPI can serve the SPA.
  #    Must run before the service starts because the SPA fallback route is
  #    registered at import time — if the www/ directory does not exist when
  #    uvicorn loads the app, the route is never created.
  _deploy_frontend

  # 9. Systemd unit
  _write_systemd_unit

  # 10. Reload and start
  run systemctl daemon-reload
  run systemctl enable ecube.service
  run systemctl restart ecube.service
  ok "ecube.service started and enabled"

  # 11. Health check
  _wait_for_healthy

  # 12. Create a PostgreSQL superuser for use in the setup wizard.
  _provision_pg_superuser
}

_write_env_file() {
  local env_file="${INSTALL_DIR}/.env"
  if [[ -f "${env_file}" ]]; then
    info ".env already exists — preserving operator secrets."
    info "DATABASE_URL is managed by the setup wizard and is not modified by install.sh."

    # Idempotently add or populate SERVE_FRONTEND_PATH so that upgrades from
    # a previous version (or a copied .env.example) enable frontend serving.
    if ! grep -Eq '^[[:space:]]*SERVE_FRONTEND_PATH=' "${env_file}"; then
      info "Adding missing SERVE_FRONTEND_PATH to existing .env..."
      if [[ "${DRY_RUN}" != true ]]; then
        printf '\n# Path to the pre-built frontend served by FastAPI (standalone mode).\nSERVE_FRONTEND_PATH=%s/www\n' "${INSTALL_DIR}" >> "${env_file}"
      fi
      ok "SERVE_FRONTEND_PATH added to .env"
    elif ! _extract_env_value "${env_file}" "SERVE_FRONTEND_PATH" >/dev/null 2>&1; then
      # Key exists but value is empty or commented — fill it in.
      info "SERVE_FRONTEND_PATH is empty in .env — setting to ${INSTALL_DIR}/www..."
      if [[ "${DRY_RUN}" != true ]]; then
        sed -i '/^[[:space:]]*SERVE_FRONTEND_PATH=/d' "${env_file}"
        printf 'SERVE_FRONTEND_PATH=%s/www\n' "${INSTALL_DIR}" >> "${env_file}"
      fi
      ok "SERVE_FRONTEND_PATH updated in .env"
    fi

    if ! grep -Eq '^[[:space:]]*TRUST_PROXY_HEADERS=' "${env_file}"; then
      info "Adding missing TRUST_PROXY_HEADERS to existing .env..."
      if [[ "${DRY_RUN}" != true ]]; then
        printf '\n# Set to true if a reverse proxy sits in front of uvicorn.\nTRUST_PROXY_HEADERS=false\n' >> "${env_file}"
      fi
      ok "TRUST_PROXY_HEADERS added to .env"
    fi

    # --- Standalone-topology safety: normalise proxy-era settings ----------
    #
    # Previous installations behind nginx may have TRUST_PROXY_HEADERS=true
    # and/or API_ROOT_PATH=/api.  In the new standalone topology the service
    # is exposed directly, so:
    #   • TRUST_PROXY_HEADERS=true  → enables client-IP spoofing via
    #     X-Forwarded-For / X-Real-IP.
    #   • A stale API_ROOT_PATH     → breaks OpenAPI/Swagger URLs.
    #
    # Reset both to safe defaults and warn loudly so the operator can opt back
    # in if they deliberately run behind a reverse proxy.

    if grep -Eq '^[[:space:]]*TRUST_PROXY_HEADERS=[[:space:]]*true' "${env_file}"; then
      warn "TRUST_PROXY_HEADERS is set to 'true' in .env."
      warn "The standalone topology exposes uvicorn directly — trusting proxy"
      warn "headers allows client-IP spoofing.  Resetting to 'false'."
      warn "If you run behind a reverse proxy, set TRUST_PROXY_HEADERS=true"
      warn "in ${env_file} after installation."
      if [[ "${DRY_RUN}" != true ]]; then
        sed -i 's/^[[:space:]]*TRUST_PROXY_HEADERS=.*/TRUST_PROXY_HEADERS=false/' "${env_file}"
      fi
      ok "TRUST_PROXY_HEADERS reset to false"
    fi

    local _old_root_path
    if _old_root_path="$(_extract_env_value "${env_file}" "API_ROOT_PATH")"; then
      warn "API_ROOT_PATH is set to '${_old_root_path}' in .env."
      warn "The standalone topology serves the API at the root — a stale"
      warn "API_ROOT_PATH can break OpenAPI/Swagger URLs.  Clearing it."
      warn "If you run behind a reverse proxy with a path prefix, restore"
      warn "API_ROOT_PATH in ${env_file} after installation."
      if [[ "${DRY_RUN}" != true ]]; then
        sed -i 's/^[[:space:]]*API_ROOT_PATH=.*/API_ROOT_PATH=/' "${env_file}"
      fi
      ok "API_ROOT_PATH cleared"
    fi

    return
  fi
  info "Writing .env file..."
  local secret_key
  if [[ "${DRY_RUN}" == true ]]; then
    secret_key="<random-hex-32>"
  else
    secret_key="$(openssl rand -hex 32)"
  fi

  if [[ "${DRY_RUN}" != true ]]; then
    cat > "${env_file}" <<EOF
# ECUBE environment configuration
# Generated by install.sh — edit as needed.

SECRET_KEY=${secret_key}
DATABASE_URL=
SETUP_DEFAULT_ADMIN_USERNAME=

# Set to true if a reverse proxy sits in front of uvicorn.
TRUST_PROXY_HEADERS=false

# Path to the pre-built frontend served by FastAPI (standalone mode).
SERVE_FRONTEND_PATH=${INSTALL_DIR}/www
EOF
    chmod 600 "${env_file}"
    chown ecube:ecube "${env_file}"
  else
    echo "[DRY-RUN] Would write ${env_file} with SECRET_KEY, DATABASE_URL=<set later by setup wizard>, SERVE_FRONTEND_PATH=${INSTALL_DIR}/www"
  fi
  ok ".env written"
}

_write_systemd_unit() {
  info "Writing systemd unit /etc/systemd/system/ecube.service..."

  # Ports below 1024 require CAP_NET_BIND_SERVICE for non-root users.
  local cap_section=""
  if [[ "${API_PORT}" -lt 1024 ]]; then
    cap_section=$'\nAmbientCapabilities=CAP_NET_BIND_SERVICE'
  fi

  if [[ "${DRY_RUN}" != true ]]; then
    if [[ "${BACKEND_NO_TLS}" == true ]]; then
      # Plain HTTP.
      cat > /etc/systemd/system/ecube.service <<EOF
[Unit]
Description=ECUBE Evidence Export Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ecube
Group=ecube
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=-${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn \
  --host 0.0.0.0 \
  --port ${API_PORT} \
  app.main:app
Restart=on-failure
RestartSec=10
PrivateTmp=yes${cap_section}
# ECUBE setup endpoints use tightly scoped sudoers rules for OS user/group
# management. NoNewPrivileges must be disabled so sudo can elevate.
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF
    else
      # HTTPS — uvicorn terminates TLS.
      cat > /etc/systemd/system/ecube.service <<EOF
[Unit]
Description=ECUBE Evidence Export Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ecube
Group=ecube
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=-${INSTALL_DIR}/.env
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn \
  --host 0.0.0.0 \
  --port ${API_PORT} \
  --ssl-keyfile=${INSTALL_DIR}/certs/key.pem \
  --ssl-certfile=${INSTALL_DIR}/certs/cert.pem \
  app.main:app
Restart=on-failure
RestartSec=10
PrivateTmp=yes${cap_section}
# ECUBE setup endpoints use tightly scoped sudoers rules for OS user/group
# management. NoNewPrivileges must be disabled so sudo can elevate.
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF
    fi
  else
    local proto; proto="$( [[ "${BACKEND_NO_TLS}" == true ]] && echo http || echo https)"
    echo "[DRY-RUN] Would write /etc/systemd/system/ecube.service (bind=${proto}://0.0.0.0:${API_PORT})"
  fi
  ok "Systemd unit written"
}

_wait_for_healthy() {
  local scheme="https"
  [[ "${BACKEND_NO_TLS}" == true ]] && scheme="http"
  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would poll ${scheme}://localhost:${API_PORT}/health for up to 30 s"
    return
  fi
  info "Waiting for service health check (up to 30 s)..."
  local i=0
  until curl -fsk "${scheme}://localhost:${API_PORT}/health" &>/dev/null; do
    sleep 2
    (( i+=2 ))
    if (( i >= 30 )); then
      warn "Service did not become healthy within 30 s. Check: journalctl -u ecube -n 50"
      return
    fi
  done
  ok "Service is healthy"
}

# ===========================================================================
# FRONTEND DEPLOYMENT
# ===========================================================================
# Copies the pre-built frontend bundle into the directory that FastAPI serves
# at runtime (SERVE_FRONTEND_PATH).  Reads the path from the existing .env so
# that an operator-customised SERVE_FRONTEND_PATH is respected on upgrades;
# falls back to ${INSTALL_DIR}/www for fresh installs.
# ===========================================================================
_deploy_frontend() {
  header "\n── Frontend deployment ─────────────────────────────────────────"

  local www_dir="${INSTALL_DIR}/www"
  local env_file="${INSTALL_DIR}/.env"
  local _env_val
  if _env_val="$(_extract_env_value "${env_file}" "SERVE_FRONTEND_PATH")"; then
    www_dir="${_env_val}"
    info "Using SERVE_FRONTEND_PATH from .env: ${www_dir}"
  fi

  # Validate www_dir before any destructive operations.  A misconfigured
  # SERVE_FRONTEND_PATH (e.g. "/" or "/etc") would otherwise cause rm -rf
  # to wipe critical system paths.
  if [[ "${www_dir}" != /* ]]; then
    error "SERVE_FRONTEND_PATH must be an absolute path (got '${www_dir}')."
    exit 1
  fi
  local _www_canonical
  _www_canonical="$(realpath -m "${www_dir}" 2>/dev/null || echo "${www_dir}")"
  local _protected=("/" "/bin" "/boot" "/dev" "/etc" "/home" "/lib" "/lib64"
                    "/media" "/mnt" "/opt" "/proc" "/root" "/run" "/sbin"
                    "/srv" "/sys" "/tmp" "/usr" "/var")
  local _p
  for _p in "${_protected[@]}"; do
    if [[ "${_www_canonical}" == "${_p}" ]]; then
      error "SERVE_FRONTEND_PATH '${www_dir}' resolves to protected system path '${_p}' — refusing to deploy."
      exit 1
    fi
  done

  # Guard against deploying into INSTALL_DIR itself or a parent of it.
  # Clearing such a path would destroy the app, venv, configs, etc.
  local _install_canonical
  _install_canonical="$(realpath -m "${INSTALL_DIR}" 2>/dev/null || echo "${INSTALL_DIR}")"
  if [[ "${_www_canonical}" == "${_install_canonical}" ]]; then
    error "SERVE_FRONTEND_PATH '${www_dir}' resolves to INSTALL_DIR '${INSTALL_DIR}' — refusing to deploy."
    exit 1
  fi
  if [[ "${_install_canonical}" == "${_www_canonical}"/* ]]; then
    error "SERVE_FRONTEND_PATH '${www_dir}' is a parent of INSTALL_DIR '${INSTALL_DIR}' — refusing to deploy."
    exit 1
  fi

  local dist_src=""
  for candidate in \
      "${INSTALL_DIR}/frontend/dist" \
      "$(pwd)/frontend/dist" \
      "$(pwd)/dist"; do
    if [[ -d "${candidate}" ]]; then
      dist_src="${candidate}"
      break
    fi
  done
  if [[ -z "${dist_src}" ]]; then
    error "Pre-built frontend dist/ not found. Checked: ${INSTALL_DIR}/frontend/dist, $(pwd)/frontend/dist, $(pwd)/dist"
    error "Build the frontend first: cd frontend && npm ci && npm run build"
    exit 1
  fi
  info "Using frontend bundle from ${dist_src}"

  # Clear existing contents rather than removing the directory itself to
  # reduce blast radius if www_dir is unexpectedly shared or bind-mounted.
  run mkdir -p "${www_dir}"
  if [[ "${DRY_RUN}" != true ]]; then
    find "${www_dir}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  else
    echo "[DRY-RUN] Would clear contents of ${www_dir}"
  fi
  run cp -r "${dist_src}/." "${www_dir}/"
  if [[ "${DRY_RUN}" != true ]]; then
    chown -R ecube:ecube "${www_dir}"
  fi
  ok "Frontend files deployed to ${www_dir}"
}

# ===========================================================================
# FIREWALL (ufw)
# ===========================================================================
configure_firewall() {
  header "\n── Firewall configuration ──────────────────────────────────────"

  if ! command -v ufw &>/dev/null; then
    info "ufw not found — skipping firewall configuration."
    return
  fi

  if ! ufw status 2>/dev/null | grep -q "Status: active"; then
    info "ufw is installed but not active — skipping firewall rules."
    return
  fi

  # Prompt for an optional source CIDR to scope the allow rule.  A blank
  # answer opens the port to all sources, but only after a clear warning.
  local cidr=""
  if [[ "${YES}" == true ]]; then
    if [[ -z "${FIREWALL_CIDR}" ]]; then
      # --yes without --firewall-cidr: safe default — skip rule creation.
      info "Skipping ufw rule in --yes mode (no --firewall-cidr provided)."
      info "To open the API port after install, run:"
      info "  sudo ufw allow from <trusted-cidr> to any port ${API_PORT} proto tcp"
      return
    fi

    if [[ "${FIREWALL_CIDR,,}" == "any" ]]; then
      # Operator explicitly chose to open to all sources.
      run ufw allow "${API_PORT}/tcp"
      ok "ufw: allowed ${API_PORT}/tcp (all sources)"
      warn "TIP — restrict to a trusted subnet later:"
      warn "  sudo ufw delete allow ${API_PORT}/tcp"
      warn "  sudo ufw allow from <trusted-cidr> to any port ${API_PORT} proto tcp"
    else
      if ! _is_valid_cidr "${FIREWALL_CIDR}"; then
        warn "Invalid --firewall-cidr '${FIREWALL_CIDR}' — skipping ufw rule."
        warn "To configure manually: sudo ufw allow from <cidr> to any port ${API_PORT} proto tcp"
        return
      fi
      if run ufw allow from "${FIREWALL_CIDR}" to any port "${API_PORT}" proto tcp; then
        ok "ufw: allowed ${FIREWALL_CIDR} → port ${API_PORT}/tcp"
      else
        warn "ufw: failed to add rule for '${FIREWALL_CIDR}' — configure manually: sudo ufw allow from ${FIREWALL_CIDR} to any port ${API_PORT} proto tcp"
      fi
    fi
  else
    echo ""
    warn "SECURITY: opening port ${API_PORT}/tcp to all sources allows any host to"
    warn "connect. If this machine is network-exposed, restrict access to a trusted"
    warn "subnet by entering a CIDR block (e.g. 192.168.1.0/24 or 10.0.0.0/8)."
    echo ""
    while true; do
      read -r -p "$(echo -e "${C_YELLOW}Source CIDR to allow for port ${API_PORT} (leave blank for all sources, 'skip' to add no rule):${C_RESET} ")" cidr
      if [[ -z "${cidr}" ]]; then
        break
      elif [[ "${cidr,,}" == "skip" ]]; then
        info "Skipping ufw rule — configure manually if needed:"
        info "  sudo ufw allow from <cidr> to any port ${API_PORT} proto tcp"
        return
      elif ! _is_valid_cidr "${cidr}"; then
        warn "Invalid CIDR '${cidr}' — expected n.n.n.n/prefix (IPv4) or hex::/prefix (IPv6). Leave blank for all, or 'skip'."
      else
        break
      fi
    done

    if [[ -n "${cidr}" ]]; then
      if run ufw allow from "${cidr}" to any port "${API_PORT}" proto tcp; then
        ok "ufw: allowed ${cidr} → port ${API_PORT}/tcp"
      else
        warn "ufw: failed to add rule for '${cidr}' — configure manually: sudo ufw allow from ${cidr} to any port ${API_PORT} proto tcp"
      fi
    else
      if _confirm "Allow TCP port ${API_PORT} from ALL sources through ufw?"; then
        run ufw allow "${API_PORT}/tcp"
        ok "ufw: allowed ${API_PORT}/tcp (all sources)"
        warn "TIP — restrict to a trusted subnet later:"
        warn "  sudo ufw delete allow ${API_PORT}/tcp"
        warn "  sudo ufw allow from <trusted-cidr> to any port ${API_PORT} proto tcp"
      fi
    fi
  fi
}

# ===========================================================================
# UNINSTALL
# ===========================================================================
do_uninstall() {
  # Ensure root and a known OS regardless of call order relative to preflight.
  if [[ "${EUID}" -ne 0 ]]; then
    error "This script must be run as root (or via sudo)."
    exit 1
  fi
  if [[ ! -f /etc/os-release ]]; then
    error "Cannot determine OS: /etc/os-release not found."
    exit 1
  fi
  # shellcheck source=/dev/null
  source /etc/os-release

  header "\n── Uninstall ECUBE ─────────────────────────────────────────────"

  if ! _confirm "This will remove ECUBE and all installed files. Continue?"; then
    info "Uninstall cancelled."
    exit 0
  fi

  # Smart service shutdown: stop/disable any ECUBE-related systemd units
  # before uninstalling files so no process continues running from removed
  # paths.
  local ecube_units=()
  if command -v systemctl &>/dev/null; then
    while IFS= read -r _unit; do
      [[ -n "${_unit}" ]] && ecube_units+=("${_unit}")
    done < <(systemctl list-unit-files "ecube*.service" --no-legend 2>/dev/null | awk '{print $1}' || true)
  fi

  if [[ ${#ecube_units[@]} -eq 0 ]]; then
    # Fallback for older/minimal systemctl outputs.
    ecube_units=("ecube.service")
  fi

  for _unit in "${ecube_units[@]}"; do
    if systemctl list-unit-files "${_unit}" --no-legend 2>/dev/null | grep -q "${_unit}"; then
      if systemctl is-active --quiet "${_unit}" 2>/dev/null; then
        run systemctl stop "${_unit}" || true
      fi
      if systemctl is-enabled --quiet "${_unit}" 2>/dev/null; then
        run systemctl disable "${_unit}" || true
      fi
    fi
  done

  if [[ -f /etc/systemd/system/ecube.service ]]; then
    run rm /etc/systemd/system/ecube.service
    run systemctl daemon-reload
    ok "ecube.service removed"
  fi

  # Remove ECUBE sudoers policy used by setup OS user/group management.
  if [[ -f /etc/sudoers.d/ecube-user-mgmt ]]; then
    run rm -f /etc/sudoers.d/ecube-user-mgmt
    ok "/etc/sudoers.d/ecube-user-mgmt removed"
  fi

  # Remove ECUBE PAM configuration.
  if [[ -f /etc/pam.d/ecube ]]; then
    run rm -f /etc/pam.d/ecube
    ok "/etc/pam.d/ecube removed"
  fi

  # Optionally clean up application database before removing install files.
  if [[ "${DROP_DATABASE}" == true ]]; then
    _cleanup_application_database
    # Best-effort cleanup of the PostgreSQL superuser created for setup wizard
    # provisioning, resolved from persisted install state in .env.
    _cleanup_pg_superuser_role
  fi

  # Remove nginx ecube site (legacy; may exist from an earlier install)
  if [[ -f /etc/nginx/sites-available/ecube ]]; then
    run rm -f /etc/nginx/sites-enabled/ecube
    run rm -f /etc/nginx/sites-available/ecube
    if systemctl is-active --quiet nginx 2>/dev/null; then
      run systemctl reload nginx
    fi
    ok "nginx ecube site removed (legacy)"
  fi

  # Remove install directory
  if [[ -d "${INSTALL_DIR}" ]]; then
    run rm -rf "${INSTALL_DIR}"
    ok "${INSTALL_DIR} removed"
  fi

  # Remove /var/lib/ecube
  if [[ -d /var/lib/ecube ]]; then
    run rm -rf /var/lib/ecube
    ok "/var/lib/ecube removed"
  fi

  # Remove ecube system user
  if id -u ecube &>/dev/null; then
    run userdel ecube
    ok "User 'ecube' removed"
  fi

  # Remove ecube group (if separate)
  if getent group ecube &>/dev/null; then
    if command -v groupdel &>/dev/null; then
      run groupdel ecube 2>/dev/null || true
    else
      warn "groupdel not found — group 'ecube' not removed; remove manually with: groupdel ecube"
    fi
  fi

  # Remove ecube-www bridge group (legacy; may exist from an earlier nginx install).
  if getent group ecube-www &>/dev/null; then
    # Remove any lingering members so groupdel can succeed.
    if command -v gpasswd &>/dev/null; then
      for _member in $(getent group ecube-www 2>/dev/null | cut -d: -f4 | tr ',' ' '); do
        gpasswd -d "${_member}" ecube-www 2>/dev/null || true
      done
    fi
    if command -v groupdel &>/dev/null; then
      if groupdel ecube-www 2>/dev/null; then
        ok "Group 'ecube-www' removed (legacy)"
      else
        warn "Could not remove legacy group 'ecube-www' — remove manually: sudo groupdel ecube-www"
      fi
    fi
  fi

  # Revoke ufw rules that configure_firewall may have added.
  # Removes the blanket allow rule; CIDR-scoped rules cannot be deleted without
  # the original source address, so warn the operator if any rule remains.
  if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw delete allow "${API_PORT}/tcp" 2>/dev/null || true
    ok "ufw: blanket allow rule for ${API_PORT}/tcp removed (if present)"
    if ufw status 2>/dev/null | grep -q "^${API_PORT}"; then
      warn "ufw: CIDR-scoped rule(s) for port ${API_PORT} may still be active — review with: sudo ufw status numbered"
    fi
  fi

  # Remove installer log file if present.
  if [[ -f "${LOG_FILE}" && "${LOG_FILE}" != "/dev/null" ]]; then
    run rm -f "${LOG_FILE}"
    ok "${LOG_FILE} removed"
  fi

  # Optionally remove deadsnakes repository.
  # Detect presence at runtime rather than relying on an in-process flag, so
  # that --uninstall works correctly even when run as a separate invocation.
  _deadsnakes_present() {
    ls /etc/apt/sources.list.d/deadsnakes*.list \
       /etc/apt/sources.list.d/*deadsnakes* \
       /etc/apt/sources.list.d/python3*.list 2>/dev/null | grep -qi deadsnakes || \
    (command -v apt-cache &>/dev/null && apt-cache policy 2>/dev/null | grep -q deadsnakes)
  }
  if _deadsnakes_present; then
    if [[ "${ID:-}" == "ubuntu" ]]; then
      run add-apt-repository -y --remove ppa:deadsnakes/ppa
    else
      run rm -f /etc/apt/sources.list.d/deadsnakes*.list \
                /etc/apt/trusted.gpg.d/deadsnakes*.gpg \
                /etc/apt/keyrings/deadsnakes*.gpg
      run apt-get update -qq
    fi
  fi

  ok "ECUBE uninstalled."
}

# ===========================================================================
# SUMMARY
# ===========================================================================
print_summary() {
  local installed_version
  installed_version="$(_detect_version)"

  # Normalize HOST for URL usage: wrap bare IPv6 literals in brackets.
  local HOST_URL
  HOST_URL="$(_url_host "${HOST}")"

  local _scheme="https"
  [[ "${BACKEND_NO_TLS}" == true ]] && _scheme="http"

  echo ""
  echo -e "${C_BOLD}=======================================================${C_RESET}"
  echo -e "${C_GREEN}  ECUBE ${installed_version} installed successfully${C_RESET}"
  echo -e "${C_BOLD}=======================================================${C_RESET}"
  echo -e "  UI:           ${_scheme}://${HOST_URL}:${API_PORT}"
  echo -e "  API:          ${_scheme}://${HOST_URL}:${API_PORT}/docs"
  echo -e "  Setup wizard: ${_scheme}://${HOST_URL}:${API_PORT}/setup"
  echo ""
  echo -e "  Complete initial configuration via the Setup Wizard."
  echo ""
  if [[ -n "${PG_SUPERUSER_NAME}" ]]; then
    echo -e "  Database provisioning — enter these in the setup wizard:"
    echo -e "    Host:     localhost"
    echo -e "    Port:     5432"
    echo -e "    Admin username: ${PG_SUPERUSER_NAME}"
    echo -e "    Admin password: ${PG_SUPERUSER_PASS}"
    echo ""
  else
    echo -e "  A PostgreSQL superuser (CREATEDB privilege) is required in the"
    echo -e "  setup wizard database provisioning screen."
    echo ""
  fi
  echo -e "  Service management:"
  echo -e "    sudo systemctl start   ecube"
  echo -e "    sudo systemctl stop    ecube"
  echo -e "    sudo systemctl restart ecube"
  echo -e "    sudo systemctl status  ecube"
  echo ""
  echo -e "  Logs:"
  echo -e "    sudo journalctl -u ecube -f"
  echo ""
  echo -e "  Install log: ${LOG_FILE}"
  echo -e "${C_BOLD}=======================================================${C_RESET}"
}

# ===========================================================================
# MAIN
# ===========================================================================
main() {
  _init_log

  if [[ "${UNINSTALL}" == true ]]; then
    do_uninstall
    exit 0
  fi

  header "\n${C_BOLD}ECUBE Installer${C_RESET}"
  [[ "${DRY_RUN}" == true ]] && warn "DRY-RUN mode: no changes will be made."

  # Stop running ECUBE service before pre-flight port checks so that a
  # re-run or upgrade does not fail because the port is already occupied by
  # the currently-installed instance.
  if systemctl is-active --quiet ecube.service 2>/dev/null; then
    info "Stopping ecube.service before pre-flight checks (will be restarted after install)..."
    run systemctl stop ecube.service
  fi

  preflight
  _resolve_host

  install_backend
  configure_firewall
  print_summary
}

main "$@"

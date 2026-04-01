#!/usr/bin/env bash
# ECUBE Bare-Metal Installer
# Installs the ECUBE backend service and/or the frontend (nginx) on Debian/Ubuntu.
#
# Usage:
#   sudo ./install.sh [OPTIONS]
#
# Run with --help to see all available options.

set -euo pipefail

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
UI_PORT="443"
HOSTNAME_OVERRIDE=""
CERT_VALIDITY="730"
YES=false
UNINSTALL=false
DRY_RUN=false
VERSION_TAG=""

INSTALL_BACKEND=true
INSTALL_FRONTEND=true
BACKEND_HOST="127.0.0.1"
ALLOW_INSECURE_BACKEND=true
_EXPLICIT_INSECURE=false   # set when --allow-insecure-backend is passed explicitly
_EXPLICIT_SECURE=false    # set when --secure-backend is passed explicitly
BACKEND_CA_FILE=""

# PostgreSQL connection — populated interactively or via CLI flags
DB_HOST=""
DB_PORT="5432"
DB_NAME="ecube"
DB_USER=""
DB_PASS=""
DATABASE_URL=""   # built by _collect_db_config
_EXPLICIT_DB=false   # set when any --db-* flag is passed explicitly

GITHUB_OWNER="t3knoid"
GITHUB_REPO="ecube"

# Runtime state

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
usage() {
  cat <<EOF
Usage: sudo ./install.sh [OPTIONS]

Component selection (default: install both):
  --backend-only         Install the backend service and systemd unit only
  --frontend-only        Install nginx and the pre-built frontend only

Options:
  --install-dir DIR      Root installation directory  (default: /opt/ecube)
  --api-port PORT        HTTPS port for the backend   (default: 8443)
  --ui-port PORT         HTTPS port for nginx         (default: 443)
  --backend-host HOST    Hostname/IP of the backend   (default: 127.0.0.1)
                         Set this when the backend is on a separate host.
  --allow-insecure-backend
                         Disable TLS certificate verification (proxy_ssl_verify
                         off) when proxying to a remote backend. Default: on.
                         A warning is printed when this is in effect.
  --secure-backend       Enable TLS certificate verification against the system
                         trust store (proxy_ssl_verify on). Use when the remote
                         backend has a CA-signed cert trusted by the OS and you
                         want strict verification without supplying a CA file.
                         Mutually exclusive with --allow-insecure-backend.
  --backend-ca-file FILE Path to a PEM CA certificate used to verify the remote
                         backend's TLS certificate (proxy_ssl_trusted_certificate).
                         Implies proxy_ssl_verify on. Ignored for loopback backends.
  --db-host HOST         PostgreSQL server hostname or IP  (prompted if omitted)
  --db-port PORT         PostgreSQL server port             (default: 5432)
  --db-name NAME         PostgreSQL database name           (default: ecube)
  --db-user USER         PostgreSQL username                (prompted if omitted)
  --db-password PASS     PostgreSQL password                (prompted if omitted)
  --hostname HOST        Hostname/IP for TLS cert CN  (default: \$(hostname -f))
  --cert-validity DAYS   Self-signed cert validity    (default: 730, max: 730 — 2 years)
  --yes, -y              Non-interactive / unattended mode
  --version TAG          Install a specific release tag instead of latest
  --uninstall            Remove ECUBE from this host
  --dry-run              Print all actions without executing them
  -h, --help             Show this help message
EOF
}

# Validate that a hostname/IP argument contains only DNS- and IP-safe characters.
# Delegates to _is_valid_host so the allowed character set is defined once.
_validate_host_arg() {
  local flag="$1" val="$2"
  if ! _is_valid_host "${val}"; then
    echo "ERROR: ${flag} value '${val}' contains invalid characters." >&2
    echo "       Allowed: alphanumerics, '.', '-', ':', '[', ']' (DNS names and IPv4/IPv6 addresses only)." >&2
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

  # If the value contains IPv6-specific syntax (':' or brackets), require it to look
  # like an IPv6 literal (optional brackets, hex digits, colons, and dots only).
  if [[ "${val}" == *[:\[\]]* ]]; then
    # Accept forms like "2001:db8::1" or "[2001:db8::1]".
    if [[ "${val}" =~ ^\[[0-9A-Fa-f:.]+\]$ || "${val}" =~ ^[0-9A-Fa-f:.]+$ ]]; then
      # Must contain at least one ':' to be considered IPv6-like.
      [[ "${val}" == *:* ]]
    else
      return 1
    fi
  else
    # DNS name or IPv4 address: letters, digits, dots, and hyphens only.
    [[ "${val}" =~ ^[a-zA-Z0-9.-]+$ ]]
  fi
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

# Pure predicate: returns 0 if val is a loopback address, 1 otherwise.
# Matches the full 127.0.0.0/8 range, the DNS name "localhost" (case-insensitive),
# the IPv6 loopback "::1", and the bracketed form "[::1]".
# Used by the post-parse normalisation step to canonicalise --backend-host so that
# every downstream same-host comparison (BACKEND_HOST == "127.0.0.1") is reliable.
_is_loopback() {
  local val="${1}"
  # Strip surrounding brackets from IPv6 literals ([::1] → ::1).
  val="${val#[}"
  val="${val%]}"
  # IPv4 loopback: entire 127.0.0.0/8 range.
  [[ "${val}" =~ ^127\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && return 0
  # DNS loopback name (case-insensitive).
  [[ "${val,,}" == "localhost" ]] && return 0
  # IPv6 loopback.
  [[ "${val}" == "::1" ]] && return 0
  return 1
}

# Pure predicate: returns 0 if val is an IPv4 or IPv6 address literal, 1 if it
# is a DNS name.  Surrounding brackets on IPv6 (e.g. [::1]) are stripped before
# the test.  Used by cert generation to decide whether to emit an IP SAN or a
# DNS SAN for HOST — DNS SANs containing ':' or '[' are invalid per RFC 5280.
_is_ip() {
  local val="${1#[}"; val="${val%]}"
  # IPv4: four dot-separated groups of digits
  [[ "${val}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && return 0
  # IPv6: presence of at least one colon
  [[ "${val}" == *:* ]] && return 0
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

# Validate a file-path argument intended for use inside an nginx config directive.
# Requires an absolute path and rejects any character that could break a directive
# (whitespace, newlines, semicolons, braces, quotes, backslashes, pipes, null bytes,
# '#' which starts an nginx comment and would silently truncate the directive,
# and '$' which nginx treats as a variable-expansion sigil).
# Also verifies the file exists and is readable so the installer fails fast with
# a clear message rather than letting nginx -t produce a cryptic error later.
_validate_ca_file_arg() {
  local flag="$1" val="$2"
  if [[ "${val}" != /* ]]; then
    echo "ERROR: ${flag} must be an absolute path (starting with /)." >&2
    exit 1
  fi
  if [[ "${val}" =~ [[:space:]\;\{\}\'\"\\|\#\$] ]]; then
    echo "ERROR: ${flag} path contains characters not allowed in an nginx config directive (whitespace, ;, {}, quotes, backslash, |, # or \$)." >&2
    exit 1
  fi
  if [[ ! -f "${val}" ]]; then
    echo "ERROR: ${flag} '${val}' does not exist or is not a regular file." >&2
    exit 1
  fi
  if [[ ! -r "${val}" ]]; then
    echo "ERROR: ${flag} '${val}' exists but is not readable by the current user." >&2
    exit 1
  fi
}

# Validate a directory path intended for use inside nginx configs and systemd
# unit files.  Restricts to the safe allowlist [A-Za-z0-9_./-] so characters
# that break config parsing (;, {}, #, quotes, backslashes, whitespace, etc.)
# are rejected at argument-parse time.  Also blocks / and common system roots
# so the installer cannot accidentally clobber critical paths.
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
    --backend-only)   INSTALL_FRONTEND=false; shift ;;
    --frontend-only)  INSTALL_BACKEND=false;  shift ;;
    --backend-host)
      _require_arg "$1" "${2-}"
      _validate_host_arg "--backend-host" "$2"
      BACKEND_HOST="$2"; shift 2 ;;
    --allow-insecure-backend)  ALLOW_INSECURE_BACKEND=true;  _EXPLICIT_INSECURE=true; shift ;;
    --secure-backend)          ALLOW_INSECURE_BACKEND=false; _EXPLICIT_SECURE=true;  shift ;;
    --backend-ca-file)
      _require_arg "$1" "${2-}"
      _validate_ca_file_arg "$1" "$2"
      BACKEND_CA_FILE="$2"; shift 2 ;;
    --db-host)
      _require_arg "$1" "${2-}"
      _validate_host_arg "--db-host" "$2"
      DB_HOST="$2"; _EXPLICIT_DB=true; shift 2 ;;
    --db-port)
      _require_arg "$1" "${2-}"
      _validate_port_arg "$1" "$2"
      DB_PORT="$2"; _EXPLICIT_DB=true; shift 2 ;;
    --db-name)
      _require_arg "$1" "${2-}"
      if ! _is_valid_db_name "$2"; then
        echo "ERROR: --db-name must contain only alphanumerics and underscores." >&2; exit 1
      fi
      DB_NAME="$2"; _EXPLICIT_DB=true; shift 2 ;;
    --db-user)
      _require_arg "$1" "${2-}"
      if ! _is_valid_db_user "$2"; then
        echo "ERROR: --db-user must contain only alphanumerics and underscores." >&2; exit 1
      fi
      DB_USER="$2"; _EXPLICIT_DB=true; shift 2 ;;
    --db-password)
      _require_arg "$1" "${2-}"
      if ! _is_valid_db_pass "$2"; then
        echo "ERROR: --db-password must not contain whitespace." >&2; exit 1
      fi
      DB_PASS="$2"; _EXPLICIT_DB=true; shift 2 ;;
    --install-dir)
      _require_arg "$1" "${2-}"
      _validate_install_dir_arg "$1" "$2"
      INSTALL_DIR="$2"; shift 2 ;;
    --api-port)
      _require_arg "$1" "${2-}"
      _validate_port_arg "$1" "$2"
      API_PORT="$2"; _EXPLICIT_API_PORT=true; shift 2 ;;
    --ui-port)
      _require_arg "$1" "${2-}"
      _validate_port_arg "$1" "$2"
      UI_PORT="$2"; shift 2 ;;
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
    --version)
      _require_arg "$1" "${2-}"
      if [[ ! "$2" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        error "--version value '$2' is invalid. Expected format: v<major>.<minor>.<patch> (e.g. v0.2.0)."
        exit 1
      fi
      VERSION_TAG="$2"; shift 2 ;;
    --uninstall)      UNINSTALL=true; shift ;;
    --dry-run)        DRY_RUN=true; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) error "Unknown option: $1"; usage; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Post-parse: reject conflicting TLS backend flag combinations
# ---------------------------------------------------------------------------
if [[ "${_EXPLICIT_INSECURE}" == true && "${_EXPLICIT_SECURE}" == true ]]; then
  error "--allow-insecure-backend and --secure-backend are mutually exclusive."
  exit 1
fi
if [[ "${_EXPLICIT_INSECURE}" == true && -n "${BACKEND_CA_FILE}" ]]; then
  error "--allow-insecure-backend and --backend-ca-file are mutually exclusive: supplying a CA file implies verification should be enabled."
  exit 1
fi
# ---------------------------------------------------------------------------
# Post-parse: canonicalise loopback variants of --backend-host to 127.0.0.1
# ---------------------------------------------------------------------------
# localhost, ::1, [::1], and the full 127.0.0.0/8 range are all equivalent to
# 127.0.0.1 for same-host detection.  Normalising here means every downstream
# comparison ([[ "${BACKEND_HOST}" == "127.0.0.1" ]]) works uniformly without
# needing to enumerate loopback variants at each call site.
if _is_loopback "${BACKEND_HOST}"; then
  if [[ "${BACKEND_HOST}" != "127.0.0.1" ]]; then
    warn "--backend-host '${BACKEND_HOST}' is a loopback address; treating as same-host (127.0.0.1)."
  fi
  BACKEND_HOST="127.0.0.1"
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
    grep -Po '(?<=^version = ")[^"]+' "${pyproject}" 2>/dev/null || echo "unknown"
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
  if [[ "${INSTALL_FRONTEND}" == true ]]; then
    required_cmds+=("nginx")
  fi
  # VERSION_TAG triggers _maybe_download_release, which unconditionally uses
  # mktemp, sha256sum, tar, and awk.  Catch missing tools here rather than
  # mid-run with a cryptic trap failure.
  if [[ -n "${VERSION_TAG}" ]]; then
    required_cmds+=("mktemp" "sha256sum" "tar" "awk")
  fi
  for cmd in "${required_cmds[@]}"; do
    if ! command -v "${cmd}" &>/dev/null; then
      if [[ "${cmd}" == "nginx" ]]; then
        info "nginx not found; it will be installed via apt."
      else
        error "Required command not found: ${cmd}"
        exit 1
      fi
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

  # Python 3.11 — only needed for backend installs
  if [[ "${INSTALL_BACKEND}" == true ]]; then
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
          codename="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
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
        run apt-get install -y python3.11 python3.11-venv python3.11-distutils
        ok "python3.11 installed"
      else
        error "python3.11 is required. Aborting."
        exit 1
      fi
    else
      ok "python3.11: $(python3.11 --version 2>&1)"
    fi
  fi

  # Port availability
  if [[ "${INSTALL_BACKEND}" == true ]]; then
    _check_port "${API_PORT}" "API"
  fi
  if [[ "${INSTALL_FRONTEND}" == true ]]; then
    _check_port "${UI_PORT}" "UI"
  fi

  ok "Pre-flight checks passed"
}

_check_port() {
  local port="$1"
  local label="$2"
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

  # Validate HOST before it is embedded in an OpenSSL -subj field or an nginx
  # server_name directive.  --hostname is already validated at parse time, so
  # this guard primarily catches unsafe values returned by `hostname -f`.
  if ! _is_valid_host "${HOST}"; then
    warn "Resolved hostname '${HOST}' contains characters unsafe for OpenSSL/nginx — falling back to 'localhost'."
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
_generate_certs() {
  local cert_dir="${INSTALL_DIR}/certs"
  # Normalise bracketed IPv6 literals once ([2001:db8::1] → 2001:db8::1) so
  # the bare address is used consistently in the CN, SANs, and log messages.
  # For DNS names and IPv4, _bare_host == HOST (nothing is stripped).
  local _bare_host="${HOST#[}"; _bare_host="${_bare_host%]}"
  if [[ -f "${cert_dir}/cert.pem" && -f "${cert_dir}/key.pem" ]]; then
    info "TLS certificates already exist — skipping generation."
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
    2>/dev/null
  if [[ "${DRY_RUN}" != true ]]; then
    chmod 600 "${cert_dir}/key.pem"
    chmod 644 "${cert_dir}/cert.pem"
    chown -R ecube:ecube "${cert_dir}"
  fi
  ok "TLS certificates written to ${cert_dir}"
}

# ===========================================================================
# ENSURE ECUBE SYSTEM USER 
# Called by both install_backend and install_frontend so that chown operations
# succeed regardless of which component is being installed.
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

# ===========================================================================
# DOWNLOAD / EXTRACT RELEASE PACKAGE (when --version is given)
# ===========================================================================
_maybe_download_release() {
  if [[ -z "${VERSION_TAG}" ]]; then
    # Running from an extracted release package: copy source files into
    # INSTALL_DIR.  Skip the copy when INSTALL_DIR is the current directory
    # (e.g., --install-dir set to the package directory itself).
    local src_dir
    src_dir="$(pwd)"
    if [[ "$(realpath "${INSTALL_DIR}" 2>/dev/null || echo "${INSTALL_DIR}")" == \
          "$(realpath "${src_dir}" 2>/dev/null || echo "${src_dir}")" ]]; then
      info "INSTALL_DIR is the current directory — no copy needed."
      return
    fi
    info "Copying package contents from ${src_dir} to ${INSTALL_DIR}..."
    for item in app alembic alembic.ini pyproject.toml README.md LICENSE frontend/dist; do
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
  tar -xzf "${tmp_tarball}" -C "${INSTALL_DIR}" --strip-components=1
  rm -f "${tmp_tarball}" "${tmp_checksum}"
}

# ===========================================================================
# DATABASE CONFIGURATION
# ===========================================================================
_collect_db_config() {
  header "\n── PostgreSQL database configuration ──────────────────────────"

  # ── Hostname ──────────────────────────────────────────────────────────────
  if [[ -z "${DB_HOST}" ]]; then
    if [[ "${YES}" == true ]]; then
      error "--db-host is required in non-interactive (--yes) mode."; exit 1
    fi
    while true; do
      read -r -p "$(echo -e "${C_YELLOW}PostgreSQL host (hostname or IP):${C_RESET} ")" DB_HOST
      _is_valid_host "${DB_HOST}" && break
      warn "Invalid host — use DNS name or IP address only (no spaces or special characters)."
    done
  fi

  # ── Port ──────────────────────────────────────────────────────────────────
  while ! _is_valid_port "${DB_PORT}"; do
    if [[ "${YES}" == true ]]; then
      error "--db-port '${DB_PORT}' is not a valid port number."; exit 1
    fi
    read -r -p "$(echo -e "${C_YELLOW}PostgreSQL port [${DB_PORT}]:${C_RESET} ")" _in
    DB_PORT="${_in:-${DB_PORT}}"
  done

  # ── Database name ─────────────────────────────────────────────────────────
  while ! _is_valid_db_name "${DB_NAME}"; do
    if [[ "${YES}" == true ]]; then
      error "--db-name '${DB_NAME}' contains invalid characters (alphanumerics and underscores only)."; exit 1
    fi
    read -r -p "$(echo -e "${C_YELLOW}PostgreSQL database name [ecube]:${C_RESET} ")" _in
    DB_NAME="${_in:-ecube}"
  done

  # ── Username ──────────────────────────────────────────────────────────────
  if [[ -z "${DB_USER}" ]]; then
    if [[ "${YES}" == true ]]; then
      error "--db-user is required in non-interactive (--yes) mode."; exit 1
    fi
    while true; do
      read -r -p "$(echo -e "${C_YELLOW}PostgreSQL username:${C_RESET} ")" DB_USER
      if ! _is_valid_db_user "${DB_USER}"; then
        warn "Invalid username — must be non-empty and contain only alphanumerics and underscores."
      else
        break
      fi
    done
  fi

  # ── Password ──────────────────────────────────────────────────────────────
  if [[ -z "${DB_PASS}" ]]; then
    if [[ "${YES}" == true ]]; then
      error "--db-password is required in non-interactive (--yes) mode."; exit 1
    fi
    while true; do
      # Read without echo
      read -r -s -p "$(echo -e "${C_YELLOW}PostgreSQL password:${C_RESET} ")" DB_PASS; echo
      if [[ -z "${DB_PASS}" ]]; then
        warn "Password must not be empty."
      elif ! _is_valid_db_pass "${DB_PASS}"; then
        warn "Password must not contain whitespace."
        DB_PASS=""
      else
        break
      fi
    done
  fi

  # Strip surrounding brackets from IPv6 literals — nc, /dev/tcp, psql, and
  # PGPASSFILE all expect a bare host (no brackets).
  local DB_HOST_BARE="${DB_HOST#[}"
  DB_HOST_BARE="${DB_HOST_BARE%]}"

  # ── TCP reachability check ─────────────────────────────────────────────────
  info "Checking TCP connectivity to ${DB_HOST}:${DB_PORT}..."
  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would check TCP ${DB_HOST}:${DB_PORT}"
  elif command -v nc &>/dev/null; then
    if ! nc -z -w5 "${DB_HOST_BARE}" "${DB_PORT}" 2>/dev/null; then
      error "Cannot reach PostgreSQL at ${DB_HOST}:${DB_PORT}. Check the host, port, and firewall rules."
      exit 1
    fi
    ok "TCP ${DB_HOST}:${DB_PORT} is reachable"
  elif command -v timeout &>/dev/null && timeout 5 bash -c "echo '' > /dev/tcp/${DB_HOST_BARE}/${DB_PORT}" 2>/dev/null; then
    ok "TCP ${DB_HOST}:${DB_PORT} is reachable (via /dev/tcp)"
  else
    warn "Neither 'nc' nor 'timeout' available — skipping TCP reachability check."
  fi

  # ── Credential check (psql) ────────────────────────────────────────────────
  if [[ "${DRY_RUN}" != true ]] && command -v psql &>/dev/null; then
    info "Verifying credentials with psql..."
    # Use a temporary PGPASSFILE instead of exposing the password via PGPASSWORD.
    local pgpass_file
    pgpass_file="$(mktemp)"
    chmod 600 "${pgpass_file}"
    printf '%s:%s:%s:%s:%s\n' "${DB_HOST_BARE}" "${DB_PORT}" "${DB_NAME}" "${DB_USER}" "${DB_PASS}" >"${pgpass_file}"

    local psql_status=0
    if PGPASSFILE="${pgpass_file}" psql \
        --host="${DB_HOST_BARE}" \
        --port="${DB_PORT}" \
        --username="${DB_USER}" \
        --dbname="${DB_NAME}" \
        --command='SELECT 1;' \
        &>/dev/null; then
      psql_status=0
    else
      psql_status=$?
    fi

    rm -f "${pgpass_file}"

    if [[ "${psql_status}" -eq 0 ]]; then
      ok "PostgreSQL credentials verified"
    else
      error "psql could not connect to ${DB_NAME}@${DB_HOST}:${DB_PORT} as '${DB_USER}'."
      error "Check the username, password, and that the database exists."
      exit 1
    fi
  else
    [[ "${DRY_RUN}" == true ]] || warn "psql not found — skipping credential verification."
  fi

  # ── URL-encode the password and assemble DATABASE_URL ─────────────────────
  if [[ "${DRY_RUN}" == true ]]; then
    local _db_host_url
    _db_host_url=$(_url_host "${DB_HOST}")
    DATABASE_URL="postgresql://${DB_USER}:<encoded-password>@${_db_host_url}:${DB_PORT}/${DB_NAME}"
    ok "DATABASE_URL configured (dry-run placeholder — password not encoded)"
  else
    local encoded_pass _db_host_url
    encoded_pass=$(_url_encode "${DB_PASS}")
    _db_host_url=$(_url_host "${DB_HOST}")
    DATABASE_URL="postgresql://${DB_USER}:${encoded_pass}@${_db_host_url}:${DB_PORT}/${DB_NAME}"
    ok "DATABASE_URL configured (password redacted)"
  fi
}

# ===========================================================================
# BACKEND INSTALLATION
# ===========================================================================
install_backend() {
  header "\n── Backend installation ────────────────────────────────────────"

  # 1. System user and USB device access
  _ensure_ecube_user

  for grp in plugdev dialout; do
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
  _generate_certs

  # 7. Database configuration
  # Skip credential collection when .env already exists and the operator has
  # not supplied any --db-* flags — the existing DATABASE_URL is preserved as-is.
  # When --db-* flags ARE given on a re-run, collect and validate the new
  # credentials; _write_env_file will then patch DATABASE_URL into the
  # existing file rather than overwriting it.
  local env_file_exists=false
  [[ -f "${INSTALL_DIR}/.env" ]] && env_file_exists=true

  if [[ "${env_file_exists}" == true && "${_EXPLICIT_DB}" == false ]]; then
    info ".env already exists and no --db-* flags supplied — skipping database credential collection."
    info "Existing DATABASE_URL will be preserved unchanged."
  else
    _collect_db_config
  fi

  # 8. .env file
  _write_env_file

  # 9. Systemd unit
  _write_systemd_unit

  # 10. Reload and start
  run systemctl daemon-reload
  run systemctl enable ecube.service
  run systemctl restart ecube.service
  ok "ecube.service started and enabled"

  # 11. Health check
  _wait_for_healthy
}

_patch_env_proxy_keys() {
  # Idempotently set/update proxy-related keys in an existing .env without
  # touching secrets (SECRET_KEY, DATABASE_URL, etc.).
  local env_file="${1}"
  local trust_val="${2}"   # "true" or "false"
  local root_path="${3}"   # "/api" or ""

  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would patch ${env_file}: TRUST_PROXY_HEADERS=${trust_val}, API_ROOT_PATH=${root_path}"
    return
  fi

  # sed -i: replace existing key if present, then add if still absent.
  for key_val in "TRUST_PROXY_HEADERS=${trust_val}" "API_ROOT_PATH=${root_path}"; do
    local key="${key_val%%=*}"
    local val="${key_val#*=}"
    if grep -q "^${key}=" "${env_file}" 2>/dev/null; then
      # Update in-place (GNU sed; escape val for sed replacement string)
      local escaped_val
      escaped_val=$(printf '%s\n' "${val}" | sed 's/[\/&]/\\&/g')
      sed -i "s|^${key}=.*|${key}=${escaped_val}|" "${env_file}"
    else
      # Append
      printf '\n%s=%s\n' "${key}" "${val}" >> "${env_file}"
    fi
  done
  ok ".env proxy keys patched (TRUST_PROXY_HEADERS=${trust_val}, API_ROOT_PATH=${root_path})"
}

_write_env_file() {
  local env_file="${INSTALL_DIR}/.env"
  if [[ -f "${env_file}" ]]; then
    info ".env already exists — preserving operator secrets."
    # If new DB credentials were collected this run, patch DATABASE_URL so the
    # operator's intent is honoured without touching SECRET_KEY or other keys.
    if [[ "${_EXPLICIT_DB}" == true && -n "${DATABASE_URL}" ]]; then
      info "Updating DATABASE_URL in existing .env with newly supplied credentials..."
      if [[ "${DRY_RUN}" != true ]]; then
        # Rewrite via a temp file so DATABASE_URL (which contains the
        # encoded password) never appears in a subprocess argv.
        # sed arguments are visible in /proc/<pid>/cmdline to other local
        # users; printf and the while-read loop are bash builtins and never
        # spawn a subprocess.
        local _db_tmp _db_replaced
        _db_tmp=$(mktemp "${env_file}.XXXXXXXXXX")
        chmod 600 "${_db_tmp}"
        _db_replaced=false
        while IFS= read -r _db_line || [[ -n "${_db_line}" ]]; do
          if [[ "${_db_line}" == DATABASE_URL=* ]]; then
            printf 'DATABASE_URL=%s\n' "${DATABASE_URL}"
            _db_replaced=true
          else
            printf '%s\n' "${_db_line}"
          fi
        done < "${env_file}" > "${_db_tmp}"
        [[ "${_db_replaced}" == false ]] && printf '\nDATABASE_URL=%s\n' "${DATABASE_URL}" >> "${_db_tmp}"
        chown ecube:ecube "${_db_tmp}"
        mv "${_db_tmp}" "${env_file}"
      else
        echo "[DRY-RUN] Would update DATABASE_URL in ${env_file}"
      fi
      ok "DATABASE_URL updated in .env"
    fi
    # When the topology includes nginx, ensure the proxy-related keys are
    # correct regardless of how the file was originally created.
    if [[ "${INSTALL_FRONTEND}" == true ]]; then
      info "Patching proxy-related keys for full-install topology..."
      _patch_env_proxy_keys "${env_file}" "true" "/api"
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

  local trust_proxy="false"
  local api_root_path=""
  if [[ "${INSTALL_FRONTEND}" == true ]]; then
    trust_proxy="true"
    # When nginx fronts uvicorn, set API_ROOT_PATH so FastAPI knows its
    # mount prefix for Swagger UI and the OpenAPI servers list.
    api_root_path="/api"
  fi

  if [[ "${DRY_RUN}" != true ]]; then
    cat > "${env_file}" <<EOF
# ECUBE environment configuration
# Generated by install.sh — edit as needed.

SECRET_KEY=${secret_key}
DATABASE_URL=${DATABASE_URL}

# Set to true if a reverse proxy (nginx) sits in front of uvicorn.
TRUST_PROXY_HEADERS=${trust_proxy}

# Mount prefix used by nginx to proxy /api/* to the backend.
# Affects Swagger UI and OpenAPI schema server URL.
API_ROOT_PATH=${api_root_path}
EOF
    chmod 600 "${env_file}"
    chown ecube:ecube "${env_file}"
  else
    echo "[DRY-RUN] Would write ${env_file} with SECRET_KEY, DATABASE_URL=${DATABASE_URL:-<collected>}, TRUST_PROXY_HEADERS=${trust_proxy}, API_ROOT_PATH=${api_root_path}"
  fi
  ok ".env written"
}

_write_systemd_unit() {
  info "Writing systemd unit /etc/systemd/system/ecube.service..."
  local bind_host="127.0.0.1"
  [[ "${INSTALL_FRONTEND}" == false ]] && bind_host="0.0.0.0"

  if [[ "${DRY_RUN}" != true ]]; then
    if [[ "${INSTALL_FRONTEND}" == false ]]; then
      # Backend-only: uvicorn terminates TLS itself; reachable directly from the network.
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
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn \\
  --host ${bind_host} \\
  --port ${API_PORT} \\
  --ssl-keyfile=${INSTALL_DIR}/certs/key.pem \\
  --ssl-certfile=${INSTALL_DIR}/certs/cert.pem \\
  app.main:app
Restart=on-failure
RestartSec=10
PrivateTmp=yes
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
    else
      # nginx-fronted: uvicorn serves plain HTTP on loopback; TLS terminated at nginx.
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
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn \\
  --host ${bind_host} \\
  --port ${API_PORT} \\
  app.main:app
Restart=on-failure
RestartSec=10
PrivateTmp=yes
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
    fi
  else
    local proto; proto="$( [[ "${INSTALL_FRONTEND}" == false ]] && echo https || echo http)"
    echo "[DRY-RUN] Would write /etc/systemd/system/ecube.service (bind=${proto}://${bind_host}:${API_PORT})"
  fi
  ok "Systemd unit written"
}

_wait_for_healthy() {
  # When nginx fronts uvicorn, the backend serves plain HTTP on loopback.
  local scheme="https"
  [[ "${INSTALL_FRONTEND}" == true ]] && scheme="http"
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
# FRONTEND INSTALLATION
# ===========================================================================
install_frontend() {
  header "\n── Frontend installation ───────────────────────────────────────"

  # Ensure the ecube user exists so that chown operations succeed even in
  # --frontend-only mode (i.e., when install_backend was not called).
  _ensure_ecube_user

  # When --version TAG is given and only the frontend is being installed,
  # install_backend has not run so _maybe_download_release has not been called.
  # Call it here to download/extract the release package (which includes
  # frontend/dist) into ${INSTALL_DIR} before the dist lookup below.
  if [[ -n "${VERSION_TAG}" && "${INSTALL_BACKEND}" == false ]]; then
    run mkdir -p "${INSTALL_DIR}"
    _maybe_download_release
  fi

  # When the frontend is added to an existing same-host backend-only install,
  # reconfigure the backend for the nginx topology: bind to 127.0.0.1 and set
  # TRUST_PROXY_HEADERS / API_ROOT_PATH in .env.
  # Skip this when --backend-host points to a remote host (nothing to reconfigure locally).
  local env_file="${INSTALL_DIR}/.env"
  local unit_file="/etc/systemd/system/ecube.service"
  if [[ "${INSTALL_BACKEND}" == false && "${BACKEND_HOST}" == "127.0.0.1" && -f "${unit_file}" ]]; then
    info "Updating existing backend configuration for nginx frontend..."

    # Detect the port the existing unit is already listening on.  Preserve it
    # unless the operator explicitly passed --api-port, so a non-default port
    # from the original backend-only install is not silently overwritten.
    if [[ "${_EXPLICIT_API_PORT}" == false ]]; then
      local _detected_port
      _detected_port=$(grep -oP -- '--port\s+\K[0-9]+' "${unit_file}" 2>/dev/null | head -1 || true)
      if [[ -n "${_detected_port}" && "${_detected_port}" != "${API_PORT}" ]]; then
        if _is_valid_port "${_detected_port}"; then
          info "Detected existing API port ${_detected_port} from unit file — using it (pass --api-port to override)."
          API_PORT="${_detected_port}"
        else
          warn "Detected port '${_detected_port}' from unit file is not a valid port number (1–65535) — keeping ${API_PORT}."
        fi
      fi
    fi

    # Patch .env — add or overwrite TRUST_PROXY_HEADERS and API_ROOT_PATH.
    if [[ -f "${env_file}" ]]; then
      _patch_env_proxy_keys "${env_file}" "true" "/api"
    else
      warn ".env not found at ${env_file} — skipping env patch (service may not exist yet)."
    fi

    # Rewrite the systemd unit so uvicorn binds to 127.0.0.1 instead of 0.0.0.0.
    # _write_systemd_unit reads INSTALL_FRONTEND which is already true here.
    _write_systemd_unit
    run systemctl daemon-reload
    if systemctl is-active --quiet ecube.service 2>/dev/null; then
      run systemctl restart ecube.service
      ok "ecube.service restarted with updated bind address (127.0.0.1:${API_PORT})"
    fi
  fi

  # Guard: --frontend-only + default BACKEND_HOST (127.0.0.1) with no local backend.
  # If the unit file does not exist and nothing is listening on the API port,
  # the generated nginx config will proxy to a dead loopback address.  Fail fast
  # so the operator is forced to supply --backend-host for a remote backend, or
  # to install the backend first.
  if [[ "${INSTALL_BACKEND}" == false && "${BACKEND_HOST}" == "127.0.0.1" && ! -f "${unit_file}" ]]; then
    local _loopback_listening=false
    if command -v ss &>/dev/null; then
      # Detect any TCP listener on API_PORT on any local address (127.0.0.1, 0.0.0.0, ::1, [::], etc.).
      # Using ss's sport filter avoids relying on distribution-specific address formatting.
      if ss -H -ltn "sport = :${API_PORT}" 2>/dev/null | grep -q .; then
        _loopback_listening=true
      fi
    fi
    if [[ "${_loopback_listening}" == false && "${DRY_RUN}" != true ]]; then
      error "--frontend-only was specified with the default --backend-host (127.0.0.1),"
      error "but no local ecube.service unit was found and nothing is listening on"
      error "127.0.0.1:${API_PORT}.  nginx would proxy to a dead address."
      error ""
      error "To fix this, choose one of:"
      error "  1. Install the backend first:    sudo ./install.sh --backend-only ..."
      error "  2. Specify the remote backend:   sudo ./install.sh --frontend-only --backend-host <host>"
      exit 1
    fi
  fi


  if ! command -v nginx &>/dev/null; then
    info "Installing nginx..."
    run apt-get update -qq
    run apt-get install -y nginx
    ok "nginx installed"
  fi

  # 2. Deploy pre-built frontend bundle
  local www_dir="${INSTALL_DIR}/www"
  local dist_src=""
  # Search order:
  #   1. ${INSTALL_DIR}/frontend/dist  — populated by --version extraction or
  #                                      when INSTALL_DIR == cwd (package dir)
  #   2. $(pwd)/frontend/dist          — running from inside an extracted package
  #   3. $(pwd)/dist                   — legacy / alternative layout
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
    exit 1
  fi
  info "Using frontend bundle from ${dist_src}"
  # Clear the web root before copying so upgrades never leave stale files behind.
  run rm -rf "${www_dir:?}"
  run mkdir -p "${www_dir}"
  run cp -r "${dist_src}/." "${www_dir}/"
  # Static files are read by nginx (www-data); root ownership with world-readable
  # permissions is correct here — the ecube service account does not need access.
  if [[ "${DRY_RUN}" != true ]]; then
    chown -R root:root "${www_dir}"
    find "${www_dir}" -type d -exec chmod 755 {} +
    find "${www_dir}" -type f -exec chmod 644 {} +
  fi
  ok "Frontend files deployed to ${www_dir}"

  # ${INSTALL_DIR} is owned ecube:ecube with mode 750, so nginx (www-data) cannot
  # traverse it to reach ${www_dir}.  Rather than granting world execute (o+x),
  # which exposes all world-readable sub-paths under ${INSTALL_DIR} to every
  # local user, create a small bridge group ecube-www containing only www-data
  # and grant that group traverse-only access (--x, no read/listing).
  #   ecube:ecube-www 710  → ecube owner keeps full rwx; ecube-www (=www-data)
  #                          gets --x (path traversal only, no listing); others
  #                          get nothing.
  if [[ "${DRY_RUN}" != true ]]; then
    if ! getent group ecube-www &>/dev/null; then
      groupadd --system ecube-www
      ok "Created system group 'ecube-www'"
    else
      info "Group 'ecube-www' already exists — skipping creation."
    fi
    # Add www-data to the bridge group so nginx can traverse ${INSTALL_DIR}.
    usermod -aG ecube-www www-data
    ok "Added www-data to group 'ecube-www'"
    # Re-own and tighten ${INSTALL_DIR}: group becomes ecube-www, mode 710.
    chown ecube:ecube-www "${INSTALL_DIR}"
    chmod 710 "${INSTALL_DIR}"
    ok "Set ${INSTALL_DIR} to ecube:ecube-www 710 (nginx traversal via group, no world execute)"
  else
    echo "[DRY-RUN] Would create group 'ecube-www', add www-data to it, and set ${INSTALL_DIR} to ecube:ecube-www 710"
  fi

  # 3. TLS certificates (shared with backend if co-installed, or generate fresh)
  _generate_certs

  # 4. nginx site config
  info "Writing nginx site config /etc/nginx/sites-available/ecube..."
  if [[ "${DRY_RUN}" != true ]]; then
        # nginx server_name does not accept IPv6 literals (colons are invalid
        # in that directive) and using an IP as server_name is fragile.  When
        # HOST is any IP literal, emit "server_name _;" (catch-all) so nginx
        # matches any request arriving on the bound port regardless of the
        # Host header value — which is the correct behaviour for an IP-bound
        # listener.  For DNS names, use the bare hostname (brackets stripped).
        local _bare_host _server_name_directive
        _bare_host="${HOST#[}"; _bare_host="${_bare_host%]}"
        if _is_ip "${_bare_host}"; then
          _server_name_directive="server_name _;"
        else
          _server_name_directive="server_name ${_bare_host};"
        fi
        cat > /etc/nginx/sites-available/ecube <<EOF_NGINX
server {
    listen ${UI_PORT} ssl;
    listen [::]:${UI_PORT} ssl;

    ${_server_name_directive}

    ssl_certificate     ${INSTALL_DIR}/certs/cert.pem;
    ssl_certificate_key ${INSTALL_DIR}/certs/key.pem;

    root ${www_dir};
    index index.html;

    # Single-page application fallback
    location / {
        try_files \$uri \$uri/ /index.html;
    }

    # Proxy API requests to the backend.
    # The trailing slash on proxy_pass strips the /api prefix so that
    # requests to /api/drives, /api/health, etc. reach the backend at
    # /drives, /health, etc. (FastAPI routes are at root level).
    # The exact-match redirect ensures GET /api (no trailing slash) is
    # normalised to /api/ rather than falling through to the SPA handler.
    location = /api {
        return 301 /api/;
    }
    location /api/ {
EOF_NGINX
  if [[ "${BACKEND_HOST}" == "127.0.0.1" ]]; then
    # Same-host: uvicorn serves plain HTTP on loopback; TLS is terminated here.
    local _bh_url
    _bh_url=$(_url_host "${BACKEND_HOST}")
    cat >> /etc/nginx/sites-available/ecube <<EOF_PROXY
        proxy_pass http://${_bh_url}:${API_PORT}/;
EOF_PROXY
  else
    # Remote backend: proxy over HTTPS.
    local _bh_url _bh_bare
    _bh_url=$(_url_host "${BACKEND_HOST}")
    # proxy_ssl_name must be a bare hostname or IP — never a bracketed IPv6
    # literal like [2001:db8::1], which would break SNI / cert verification.
    # Strip surrounding brackets if present; all other values pass through.
    _bh_bare="${BACKEND_HOST#[}"
    _bh_bare="${_bh_bare%]}"
    if [[ -n "${BACKEND_CA_FILE}" ]]; then
      # Custom CA certificate supplied — verify against it.
      # proxy_ssl_server_name on sends SNI in the TLS ClientHello so the backend
      # can select the right certificate on virtual-host setups. proxy_ssl_name
      # sets both the SNI value and the hostname used for CN/SAN verification;
      # this is critical when proxy_pass targets an IP literal. verify_depth 2
      # allows for one intermediate CA in the chain (nginx default is 1).
      cat >> /etc/nginx/sites-available/ecube <<EOF_PROXY
        proxy_pass https://${_bh_url}:${API_PORT}/;
        proxy_ssl_verify          on;
        proxy_ssl_trusted_certificate ${BACKEND_CA_FILE};
        proxy_ssl_server_name     on;
        proxy_ssl_name            ${_bh_bare};
        proxy_ssl_verify_depth    2;
EOF_PROXY
    elif [[ "${ALLOW_INSECURE_BACKEND}" == true ]]; then
      # Default fallback: TLS verification disabled for quick bring-up.
      # SECURITY WARNING: proxy_ssl_verify is off. The backend certificate is
      # not validated. Only acceptable on trusted networks (VPN, private subnet).
      # To enable verification pass --backend-ca-file or ensure the backend cert
      # is signed by a CA in the system trust store and remove this line.
      warn "TLS verification is DISABLED for remote backend ${BACKEND_HOST}:${API_PORT} (proxy_ssl_verify off)."
      warn "This is the default for quick start. Pass --backend-ca-file or use a CA-signed cert to enable verification."
      cat >> /etc/nginx/sites-available/ecube <<EOF_PROXY
        proxy_pass https://${_bh_url}:${API_PORT}/;
        proxy_ssl_verify off; # default; see --backend-ca-file to enable verification
EOF_PROXY
    else
      # Strict mode: verify using the system trust store.
      # proxy_ssl_trusted_certificate must be set explicitly — without it nginx
      # does not know which CA bundle to use and verification will not work as
      # intended (nginx -t may also fail on some versions).  The Debian/Ubuntu
      # system CA bundle is always at /etc/ssl/certs/ca-certificates.crt.
      # See CA-file branch above for explanation of proxy_ssl_server_name,
      # proxy_ssl_name, and proxy_ssl_verify_depth.
      cat >> /etc/nginx/sites-available/ecube <<EOF_PROXY
        proxy_pass https://${_bh_url}:${API_PORT}/;
        proxy_ssl_verify                on;
        proxy_ssl_trusted_certificate   /etc/ssl/certs/ca-certificates.crt;
        proxy_ssl_server_name           on;
        proxy_ssl_name                  ${_bh_bare};
        proxy_ssl_verify_depth          2;
EOF_PROXY
    fi
  fi
  cat >> /etc/nginx/sites-available/ecube <<EOF_PROXY2
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF_PROXY2
  else
    echo "[DRY-RUN] Would write /etc/nginx/sites-available/ecube (listen ${UI_PORT} → proxy to ${API_PORT})"
  fi

  # Enable site
  run ln -sf /etc/nginx/sites-available/ecube /etc/nginx/sites-enabled/ecube

  # 5. Remove default nginx site (avoid port conflict on 443)
  if [[ -L /etc/nginx/sites-enabled/default ]]; then
    info "Removing nginx default site symlink..."
    run rm /etc/nginx/sites-enabled/default
  fi

  # 6. Test and reload nginx
  if [[ "${DRY_RUN}" != true ]]; then
    nginx -t
  fi
  run systemctl enable nginx
  run systemctl reload nginx || run systemctl start nginx
  ok "nginx configured and running"
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

  if [[ "${INSTALL_FRONTEND}" == true ]]; then
    if _confirm "Allow TCP port ${UI_PORT} (UI) through ufw?"; then
      run ufw allow "${UI_PORT}/tcp"
      ok "ufw: allowed ${UI_PORT}/tcp"
    fi
    # Deny direct API access from external hosts when nginx fronts it
    if _confirm "Deny external access to API port ${API_PORT} (traffic should go through nginx)?"; then
      run ufw deny "${API_PORT}/tcp"
      ok "ufw: denied external access to ${API_PORT}/tcp"
    fi
  elif [[ "${INSTALL_BACKEND}" == true ]]; then
    local cidr=""
    if [[ "${YES}" == true ]]; then
      warn "Skipping ufw API port rule in --yes mode for backend-only install (use ufw manually if needed)."
    else
      while true; do
        read -r -p "$(echo -e "${C_YELLOW}Enter source CIDR to allow for API port ${API_PORT} (leave blank to skip):${C_RESET} ")" cidr
        if [[ -z "${cidr}" ]]; then
          break
        elif ! _is_valid_cidr "${cidr}"; then
          warn "Invalid CIDR '${cidr}' — expected n.n.n.n/prefix (IPv4) or hex::/prefix (IPv6). Leave blank to skip."
        else
          break
        fi
      done
      if [[ -n "${cidr}" ]]; then
        if run ufw allow from "${cidr}" to any port "${API_PORT}" proto tcp; then
          ok "ufw: allowed ${cidr} → port ${API_PORT}/tcp"
        else
          warn "ufw: failed to add rule for '${cidr}' — firewall not updated. Configure manually: sudo ufw allow from ${cidr} to any port ${API_PORT} proto tcp"
        fi
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

  # Stop and disable backend service
  if systemctl is-active --quiet ecube.service 2>/dev/null; then
    run systemctl stop ecube.service
  fi
  if systemctl is-enabled --quiet ecube.service 2>/dev/null; then
    run systemctl disable ecube.service
  fi
  if [[ -f /etc/systemd/system/ecube.service ]]; then
    run rm /etc/systemd/system/ecube.service
    run systemctl daemon-reload
    ok "ecube.service removed"
  fi

  # Remove nginx ecube site
  if [[ -f /etc/nginx/sites-available/ecube ]]; then
    run rm -f /etc/nginx/sites-enabled/ecube
    run rm -f /etc/nginx/sites-available/ecube
    if systemctl is-active --quiet nginx 2>/dev/null; then
      run systemctl reload nginx
    fi
    ok "nginx ecube site removed"
  fi

  # Remove install directory
  if [[ -d "${INSTALL_DIR}" ]]; then
    if _confirm "Remove ${INSTALL_DIR}?"; then
      run rm -rf "${INSTALL_DIR}"
      ok "${INSTALL_DIR} removed"
    fi
  fi

  # Remove /var/lib/ecube
  if [[ -d /var/lib/ecube ]]; then
    if _confirm "Remove /var/lib/ecube (runtime data)?"; then
      run rm -rf /var/lib/ecube
      ok "/var/lib/ecube removed"
    fi
  fi

  # Remove ecube system user
  if id -u ecube &>/dev/null; then
    if _confirm "Remove system user 'ecube'?"; then
      run userdel ecube
      ok "User 'ecube' removed"
    fi
  fi

  # Remove ecube group (if separate)
  if getent group ecube &>/dev/null; then
    if command -v groupdel &>/dev/null; then
      run groupdel ecube 2>/dev/null || true
    else
      warn "groupdel not found — group 'ecube' not removed; remove manually with: groupdel ecube"
    fi
  fi

  # Remove ecube-www bridge group (created by install_frontend to give www-data
  # traversal access to INSTALL_DIR without o+x).  Remove www-data from the
  # group first so groupdel succeeds, then delete the group.
  if getent group ecube-www &>/dev/null; then
    if id -nG www-data 2>/dev/null | grep -qw ecube-www; then
      if command -v gpasswd &>/dev/null; then
        run gpasswd -d www-data ecube-www 2>/dev/null || true
      else
        warn "gpasswd not found — www-data may still be a member of ecube-www; remove manually with: usermod -G ... www-data"
      fi
    fi
    if command -v groupdel &>/dev/null; then
      run groupdel ecube-www 2>/dev/null || true
      ok "Group 'ecube-www' removed"
    else
      warn "groupdel not found — group 'ecube-www' not removed; remove manually with: groupdel ecube-www"
    fi
  fi

  # Revoke ufw rules that configure_firewall may have added.
  # A frontend install creates: allow ${UI_PORT}/tcp + deny ${API_PORT}/tcp.
  # A backend-only install may have created a per-CIDR allow for ${API_PORT}/tcp;
  # the source CIDR is not persisted here, so we attempt best-effort deletion of
  # the two known rules and warn the operator if any rule for ${API_PORT} remains.
  if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    if _confirm "Remove ECUBE ufw rules (ports ${UI_PORT}/tcp and ${API_PORT}/tcp)?"; then
      ufw delete allow "${UI_PORT}/tcp" 2>/dev/null || true
      ufw delete deny  "${API_PORT}/tcp" 2>/dev/null || true
      ok "ufw: rules for ${UI_PORT}/tcp and ${API_PORT}/tcp removed (if present)"
      # A CIDR-scoped allow rule cannot be deleted without the original source
      # address; alert the operator if any rule for API_PORT is still active.
      if ufw status 2>/dev/null | grep -q "^${API_PORT}"; then
        warn "ufw: rule(s) for port ${API_PORT} may still be active — review with: sudo ufw status numbered"
      fi
    fi
  fi

  # Optionally remove the installer log file.
  if [[ -f "${LOG_FILE}" && "${LOG_FILE}" != "/dev/null" ]]; then
    if _confirm "Remove installer log ${LOG_FILE}?"; then
      run rm -f "${LOG_FILE}"
      ok "${LOG_FILE} removed"
    fi
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
    if _confirm "Remove the deadsnakes repository entry (detected in apt sources)?"; then
      if [[ "${ID:-}" == "ubuntu" ]]; then
        run add-apt-repository -y --remove ppa:deadsnakes/ppa
      else
        run rm -f /etc/apt/sources.list.d/deadsnakes*.list \
                  /etc/apt/trusted.gpg.d/deadsnakes*.gpg \
                  /etc/apt/keyrings/deadsnakes*.gpg
        run apt-get update -qq
      fi
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

  echo ""
  if [[ "${INSTALL_BACKEND}" == true && "${INSTALL_FRONTEND}" == true ]]; then
    echo -e "${C_BOLD}=======================================================${C_RESET}"
    echo -e "${C_GREEN}  ECUBE ${installed_version} installed successfully${C_RESET}"
    echo -e "${C_BOLD}=======================================================${C_RESET}"
    echo -e "  UI:           https://${HOST_URL}:${UI_PORT}"
    echo -e "  API:          https://${HOST_URL}:${UI_PORT}/api/"
    echo -e "  Setup wizard: https://${HOST_URL}:${UI_PORT}/setup"
    echo ""
    echo -e "  Complete initial configuration via the Setup Wizard."
    echo -e "  A PostgreSQL database must be reachable at that point."
    echo ""
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

  elif [[ "${INSTALL_BACKEND}" == true ]]; then
    echo -e "${C_BOLD}=======================================================${C_RESET}"
    echo -e "${C_GREEN}  ECUBE backend ${installed_version} installed successfully${C_RESET}"
    echo -e "${C_BOLD}=======================================================${C_RESET}"
    echo -e "  API:  https://${HOST_URL}:${API_PORT}"
    echo -e "  Docs: https://${HOST_URL}:${API_PORT}/docs"
    echo ""
    echo -e "  TIP – restrict API access if this host is network-exposed:"
    echo -e "    sudo ufw allow from <trusted-cidr> to any port ${API_PORT} proto tcp"
    echo -e "    sudo ufw deny ${API_PORT}/tcp"
    echo ""
    echo -e "  Service management:"
    echo -e "    sudo systemctl {start|stop|restart|status} ecube"
    echo ""
    echo -e "  Logs:"
    echo -e "    sudo journalctl -u ecube -f"
    echo ""
    echo -e "  Install log: ${LOG_FILE}"
    echo -e "${C_BOLD}=======================================================${C_RESET}"

  else
    echo -e "${C_BOLD}=======================================================${C_RESET}"
    echo -e "${C_GREEN}  ECUBE frontend installed successfully${C_RESET}"
    echo -e "${C_BOLD}=======================================================${C_RESET}"
    echo -e "  UI:  https://${HOST_URL}:${UI_PORT}"
    echo ""
    local _summary_bh
    _summary_bh=$(_url_host "${BACKEND_HOST}")
    if [[ "${BACKEND_HOST}" == "127.0.0.1" ]]; then
      # Same-host topology: the backend was reconfigured to serve plain HTTP on
      # loopback; nginx is the only TLS termination point and is the component
      # operators should interact with.  The loopback address is not directly
      # accessible and the scheme is HTTP, so avoid printing it as an https://
      # URL which would mislead operators into thinking it is externally reachable.
      echo -e "  nginx proxies /api/ → http://${_summary_bh}:${API_PORT}/ (loopback, not directly accessible)"
    else
      echo -e "  Ensure the backend API is reachable at:"
      echo -e "    https://${_summary_bh}:${API_PORT}"
    fi
    echo ""
    echo -e "  Service management:"
    echo -e "    sudo systemctl {start|stop|reload|status} nginx"
    echo -e "${C_BOLD}=======================================================${C_RESET}"
  fi
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

  if [[ "${INSTALL_BACKEND}" == false && "${INSTALL_FRONTEND}" == false ]]; then
    error "--backend-only and --frontend-only cannot both be specified."
    exit 1
  fi

  header "\n${C_BOLD}ECUBE Installer${C_RESET}"
  [[ "${DRY_RUN}" == true ]] && warn "DRY-RUN mode: no changes will be made."

  preflight
  _resolve_host

  [[ "${INSTALL_BACKEND}"  == true ]] && install_backend
  [[ "${INSTALL_FRONTEND}" == true ]] && install_frontend

  configure_firewall
  print_summary
}

main "$@"

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
UI_PORT="443"
HOSTNAME_OVERRIDE=""
CERT_VALIDITY="3650"
YES=false
UNINSTALL=false
DRY_RUN=false
VERSION_TAG=""

INSTALL_BACKEND=true
INSTALL_FRONTEND=true
BACKEND_HOST="127.0.0.1"
ALLOW_INSECURE_BACKEND=true
BACKEND_CA_FILE=""

# PostgreSQL connection — populated interactively or via CLI flags
DB_HOST=""
DB_PORT="5432"
DB_NAME="ecube"
DB_USER=""
DB_PASS=""
DATABASE_URL=""   # built by _collect_db_config

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
  --cert-validity DAYS   Self-signed cert validity    (default: 3650)
  --yes, -y              Non-interactive / unattended mode
  --version TAG          Install a specific release tag instead of latest
  --uninstall            Remove ECUBE from this host
  --dry-run              Print all actions without executing them
  -h, --help             Show this help message
EOF
}

# Validate that a hostname/IP argument contains only DNS- and IP-safe characters:
# alphanumerics, dots, hyphens, and brackets (for IPv6 literals).
# Rejects whitespace, newlines, slashes, semicolons, and any other character
# that could break an nginx config directive or an OpenSSL subject field.
_validate_host_arg() {
  local flag="$1"
  local val="$2"
  if [[ -z "${val}" ]]; then
    echo "ERROR: ${flag} value must not be empty." >&2
    exit 1
  fi
  if [[ "${val}" =~ [^a-zA-Z0-9.\:\-\[\]] ]]; then
    echo "ERROR: ${flag} value '${val}' contains invalid characters." >&2
    echo "       Allowed: alphanumerics, '.', '-', ':', '[', ']' (DNS names and IPv4/IPv6 addresses only)." >&2
    exit 1
  fi
}

# Pure predicate: returns 0 if val is a valid DNS name or IP address, 1 otherwise.
# No output and no exit — safe to use inside interactive prompt loops.
_is_valid_host() {
  local val="$1"
  [[ -n "${val}" && ! "${val}" =~ [^a-zA-Z0-9.\:\-\[\]] ]]
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
# (whitespace, newlines, semicolons, braces, quotes, backslashes, null bytes).
_validate_ca_file_arg() {
  local flag="$1" val="$2"
  if [[ "${val}" != /* ]]; then
    echo "ERROR: ${flag} must be an absolute path (starting with /)." >&2
    exit 1
  fi
  if [[ "${val}" =~ [[:space:]]|\'|\"|\\|\;|\{|\}|\| ]]; then
    echo "ERROR: ${flag} path contains characters not allowed in an nginx config directive (whitespace, ;, {}, quotes, or backslash)." >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-only)   INSTALL_FRONTEND=false; shift ;;
    --frontend-only)  INSTALL_BACKEND=false;  shift ;;
    --backend-host)
      _require_arg "$1" "${2-}"
      _validate_host_arg "--backend-host" "$2"
      BACKEND_HOST="$2"; shift 2 ;;
    --allow-insecure-backend)  ALLOW_INSECURE_BACKEND=true;  shift ;;
    --secure-backend)          ALLOW_INSECURE_BACKEND=false; shift ;;
    --backend-ca-file)
      _require_arg "$1" "${2-}"
      _validate_ca_file_arg "$1" "$2"
      BACKEND_CA_FILE="$2"; shift 2 ;;
    --db-host)
      _require_arg "$1" "${2-}"
      _validate_host_arg "--db-host" "$2"
      DB_HOST="$2"; shift 2 ;;
    --db-port)
      _require_arg "$1" "${2-}"
      [[ "$2" =~ ^[0-9]+$ ]] || { echo "ERROR: --db-port must be a positive integer." >&2; exit 1; }
      DB_PORT="$2"; shift 2 ;;
    --db-name)
      _require_arg "$1" "${2-}"
      if [[ "$2" =~ [^a-zA-Z0-9_] ]]; then
        echo "ERROR: --db-name must contain only alphanumerics and underscores." >&2; exit 1
      fi
      DB_NAME="$2"; shift 2 ;;
    --db-user)
      _require_arg "$1" "${2-}"
      if [[ "$2" =~ [[:space:]] ]]; then
        echo "ERROR: --db-user must not contain whitespace." >&2; exit 1
      fi
      DB_USER="$2"; shift 2 ;;
    --db-password)
      _require_arg "$1" "${2-}"
      if [[ "$2" =~ [[:space:]] ]]; then
        echo "ERROR: --db-password must not contain whitespace." >&2; exit 1
      fi
      DB_PASS="$2"; shift 2 ;;
    --install-dir)
      _require_arg "$1" "${2-}"
      # Reject values that are /, a known system root, contain whitespace
      # or newlines, or are not absolute paths.  Any of these could cause
      # accidental rm -rf of critical paths or break systemd unit parsing.
      _idir="$2"
      if [[ "${_idir}" != /* ]]; then
        echo "ERROR: --install-dir must be an absolute path (got '${_idir}')." >&2; exit 1
      fi
      if [[ "${_idir}" =~ [[:space:]] ]]; then
        echo "ERROR: --install-dir must not contain spaces or whitespace (got '${_idir}')." >&2; exit 1
      fi
      # Block /, single-depth paths like /tmp, and common system directories.
      _canonical="$(realpath -m "${_idir}" 2>/dev/null || echo "${_idir}")"
      _dangerous=("/" "/bin" "/boot" "/dev" "/etc" "/home" "/lib" "/lib64"
                  "/proc" "/root" "/run" "/sbin" "/srv" "/sys" "/tmp"
                  "/usr" "/var")
      for _d in "${_dangerous[@]}"; do
        if [[ "${_canonical}" == "${_d}" ]]; then
          echo "ERROR: --install-dir '${_idir}' is a protected system path." >&2; exit 1
        fi
      done
      INSTALL_DIR="${_idir}"; shift 2 ;;
    --api-port)
      _require_arg "$1" "${2-}"
      [[ "$2" =~ ^[0-9]+$ && "$2" -ge 1 && "$2" -le 65535 ]] || { echo "ERROR: --api-port must be a number between 1 and 65535." >&2; exit 1; }
      API_PORT="$2"; shift 2 ;;
    --ui-port)
      _require_arg "$1" "${2-}"
      [[ "$2" =~ ^[0-9]+$ && "$2" -ge 1 && "$2" -le 65535 ]] || { echo "ERROR: --ui-port must be a number between 1 and 65535." >&2; exit 1; }
      UI_PORT="$2"; shift 2 ;;
    --hostname)
      _require_arg "$1" "${2-}"
      _validate_host_arg "--hostname" "$2"
      HOSTNAME_OVERRIDE="$2"; shift 2 ;;
    --cert-validity)
      _require_arg "$1" "${2-}"
      CERT_VALIDITY="$2"; shift 2 ;;
    --yes|-y)         YES=true;  shift ;;
    --version)
      _require_arg "$1" "${2-}"
      VERSION_TAG="$2"; shift 2 ;;
    --uninstall)      UNINSTALL=true; shift ;;
    --dry-run)        DRY_RUN=true; shift ;;
    -h|--help)        usage; exit 0 ;;
    *) error "Unknown option: $1"; usage; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Dry-run wrapper
# ---------------------------------------------------------------------------
run() {
  if [[ "${DRY_RUN}" == true ]]; then
    echo -e "${C_YELLOW}[DRY-RUN]${C_RESET} $*"
  else
    "$@"
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
  local free_kb
  free_kb=$(df -k "${parent_dir}" | awk 'NR==2 {print $4}')
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
          if ! apt-cache show python3.11 &>/dev/null; then
            info "python3.11 not in ${codename} main; enabling ${codename}-backports ..."
            echo "deb https://deb.debian.org/debian ${codename}-backports main" \
              | tee /etc/apt/sources.list.d/"${codename}-backports.list" >/dev/null
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
  info "Hostname: ${HOST}  IP: ${HOST_IP}"
}

# ===========================================================================
# TLS CERTIFICATES
# ===========================================================================
_generate_certs() {
  local cert_dir="${INSTALL_DIR}/certs"
  if [[ -f "${cert_dir}/cert.pem" && -f "${cert_dir}/key.pem" ]]; then
    info "TLS certificates already exist — skipping generation."
    return
  fi
  info "Generating self-signed TLS certificate (CN=${HOST}, validity=${CERT_VALIDITY} days)..."
  run mkdir -p "${cert_dir}"
  run openssl req -x509 -nodes -days "${CERT_VALIDITY}" -newkey rsa:2048 \
    -keyout "${cert_dir}/key.pem" \
    -out    "${cert_dir}/cert.pem" \
    -subj   "/CN=${HOST}" \
    -addext "subjectAltName=IP:${HOST_IP},DNS:${HOST}" \
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

  info "Downloading ECUBE ${VERSION_TAG} from GitHub Releases..."
  run curl -fsSL -o "/tmp/${tarball_name}" "${base_url}/${tarball_name}"
  run curl -fsSL -o "/tmp/${checksum_name}" "${base_url}/${checksum_name}"

  info "Verifying checksum..."
  if [[ "${DRY_RUN}" != true ]]; then
    (cd /tmp && sha256sum -c "${checksum_name}")
    ok "Checksum verified"
  fi

  info "Extracting package to ${INSTALL_DIR}..."
  run mkdir -p "${INSTALL_DIR}"
  run tar -xzf "/tmp/${tarball_name}" -C "${INSTALL_DIR}" --strip-components=1
}

# ===========================================================================
# DATABASE CONFIGURATION
# ===========================================================================
_validate_db_str() {
  # Reject values containing whitespace, @, /, or characters that would break
  # a postgresql:// URL or a psql connection string.
  local flag="$1" val="$2"
  if [[ -z "${val}" ]]; then
    echo "ERROR: ${flag} must not be empty." >&2; exit 1
  fi
  if [[ "${val}" =~ [[:space:]/@] ]]; then
    echo "ERROR: ${flag} value contains invalid characters (whitespace, '/' or '@' not allowed)." >&2; exit 1
  fi
}

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
  while ! [[ "${DB_PORT}" =~ ^[0-9]+$ && "${DB_PORT}" -ge 1 && "${DB_PORT}" -le 65535 ]]; do
    if [[ "${YES}" == true ]]; then
      error "--db-port '${DB_PORT}' is not a valid port number."; exit 1
    fi
    read -r -p "$(echo -e "${C_YELLOW}PostgreSQL port [${DB_PORT}]:${C_RESET} ")" _in
    DB_PORT="${_in:-${DB_PORT}}"
  done

  # ── Database name ─────────────────────────────────────────────────────────
  while [[ -z "${DB_NAME}" || "${DB_NAME}" =~ [^a-zA-Z0-9_] ]]; do
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
      if [[ -z "${DB_USER}" || "${DB_USER}" =~ [[:space:]/@] ]]; then
        warn "Invalid username — must be non-empty and must not contain whitespace, '/' or '@'."
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
      elif [[ "${DB_PASS}" =~ [[:space:]] ]]; then
        warn "Password must not contain whitespace."
        DB_PASS=""
      else
        break
      fi
    done
  fi

  # ── TCP reachability check ─────────────────────────────────────────────────
  info "Checking TCP connectivity to ${DB_HOST}:${DB_PORT}..."
  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would check TCP ${DB_HOST}:${DB_PORT}"
  elif command -v nc &>/dev/null; then
    if ! nc -z -w5 "${DB_HOST}" "${DB_PORT}" 2>/dev/null; then
      error "Cannot reach PostgreSQL at ${DB_HOST}:${DB_PORT}. Check the host, port, and firewall rules."
      exit 1
    fi
    ok "TCP ${DB_HOST}:${DB_PORT} is reachable"
  elif command -v bash &>/dev/null && (echo '' > "/dev/tcp/${DB_HOST}/${DB_PORT}") 2>/dev/null; then
    ok "TCP ${DB_HOST}:${DB_PORT} is reachable (via /dev/tcp)"
  else
    warn "Neither 'nc' nor /dev/tcp is available — skipping TCP reachability check."
  fi

  # ── Credential check (psql) ────────────────────────────────────────────────
  if [[ "${DRY_RUN}" != true ]] && command -v psql &>/dev/null; then
    info "Verifying credentials with psql..."
    if PGPASSWORD="${DB_PASS}" psql \
        --host="${DB_HOST}" \
        --port="${DB_PORT}" \
        --username="${DB_USER}" \
        --dbname="${DB_NAME}" \
        --command='SELECT 1;' \
        &>/dev/null; then
      ok "PostgreSQL credentials verified"
    else
      error "psql could not connect to ${DB_NAME}@${DB_HOST}:${DB_PORT} as '${DB_USER}'."
      error "Check the username, password, and that the database exists."
      exit 1
    fi
  else
    [[ "${DRY_RUN}" == true ]] || warn "psql not found — skipping credential verification."
  fi

  # ── URL-encode the password (percent-encode @ : / space) ──────────────────
  # bash-only encoding — covers the characters that break a postgresql:// URL.
  local encoded_pass="${DB_PASS}"
  encoded_pass="${encoded_pass//'%'/'%25'}"
  encoded_pass="${encoded_pass//' '/'%20'}"
  encoded_pass="${encoded_pass//'@'/'%40'}"
  encoded_pass="${encoded_pass//':'/'%3A'}"
  encoded_pass="${encoded_pass//'/'/'%2F'}"

  DATABASE_URL="postgresql://${DB_USER}:${encoded_pass}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
  ok "DATABASE_URL configured (password redacted)"
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

  # 5. Python virtual environment
  local venv_dir="${INSTALL_DIR}/venv"
  if [[ ! -d "${venv_dir}" ]]; then
    info "Creating Python virtual environment..."
    run python3.11 -m venv "${venv_dir}"
  fi
  info "Installing Python dependencies..."
  run "${venv_dir}/bin/pip" install --quiet --upgrade pip setuptools wheel
  run "${venv_dir}/bin/pip" install --quiet -e "${INSTALL_DIR}"
  ok "Python environment ready at ${venv_dir}"

  # 6. TLS certificates
  _generate_certs

  # 7. Database configuration
  _collect_db_config

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

  # 1. Install nginx if absent
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

  # 3. TLS certificates (shared with backend if co-installed, or generate fresh)
  _generate_certs

  # 4. nginx site config
  info "Writing nginx site config /etc/nginx/sites-available/ecube..."
  if [[ "${DRY_RUN}" != true ]]; then
        cat > /etc/nginx/sites-available/ecube <<EOF_NGINX
server {
    listen ${UI_PORT} ssl;
    listen [::]:${UI_PORT} ssl;

    server_name ${HOST};

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
    location /api/ {
EOF_NGINX
  if [[ "${BACKEND_HOST}" == "127.0.0.1" ]]; then
    # Same-host: uvicorn serves plain HTTP on loopback; TLS is terminated here.
    cat >> /etc/nginx/sites-available/ecube <<EOF_PROXY
        proxy_pass http://${BACKEND_HOST}:${API_PORT}/;
EOF_PROXY
  else
    # Remote backend: proxy over HTTPS.
    if [[ -n "${BACKEND_CA_FILE}" ]]; then
      # Custom CA certificate supplied — verify against it.
      cat >> /etc/nginx/sites-available/ecube <<EOF_PROXY
        proxy_pass https://${BACKEND_HOST}:${API_PORT}/;
        proxy_ssl_verify on;
        proxy_ssl_trusted_certificate ${BACKEND_CA_FILE};
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
        proxy_pass https://${BACKEND_HOST}:${API_PORT}/;
        proxy_ssl_verify off; # default; see --backend-ca-file to enable verification
EOF_PROXY
    else
      # Strict mode: verify using the system trust store.
      cat >> /etc/nginx/sites-available/ecube <<EOF_PROXY
        proxy_pass https://${BACKEND_HOST}:${API_PORT}/;
        proxy_ssl_verify on;
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
      run ufw deny "${API_PORT}"
      ok "ufw: denied external access to ${API_PORT}"
    fi
  elif [[ "${INSTALL_BACKEND}" == true ]]; then
    local cidr=""
    if [[ "${YES}" == true ]]; then
      warn "Skipping ufw API port rule in --yes mode for backend-only install (use ufw manually if needed)."
    else
      read -r -p "$(echo -e "${C_YELLOW}Enter source CIDR to allow for API port ${API_PORT} (leave blank to skip):${C_RESET} ")" cidr
      if [[ -n "${cidr}" ]]; then
        run ufw allow from "${cidr}" to any port "${API_PORT}"
        ok "ufw: allowed ${cidr} → port ${API_PORT}"
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
    run groupdel ecube 2>/dev/null || true
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

  echo ""
  if [[ "${INSTALL_BACKEND}" == true && "${INSTALL_FRONTEND}" == true ]]; then
    echo -e "${C_BOLD}=======================================================${C_RESET}"
    echo -e "${C_GREEN}  ECUBE ${installed_version} installed successfully${C_RESET}"
    echo -e "${C_BOLD}=======================================================${C_RESET}"
    echo -e "  UI:           https://${HOST}:${UI_PORT}"
    echo -e "  API:          https://${HOST}:${UI_PORT}/api"
    echo -e "  Setup wizard: https://${HOST}:${UI_PORT}/setup"
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
    echo -e "  API:  https://${HOST}:${API_PORT}"
    echo -e "  Docs: https://${HOST}:${API_PORT}/docs"
    echo ""
    echo -e "  TIP – restrict API access if this host is network-exposed:"
    echo -e "    sudo ufw allow from <trusted-cidr> to any port ${API_PORT}"
    echo -e "    sudo ufw deny ${API_PORT}"
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
    echo -e "  UI:  https://${HOST}:${UI_PORT}"
    echo ""
    echo -e "  Ensure the backend API is reachable at:"
    echo -e "    https://${BACKEND_HOST}:${API_PORT}"
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

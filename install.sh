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
  --hostname HOST        Hostname/IP for TLS cert CN  (default: \$(hostname -f))
  --cert-validity DAYS   Self-signed cert validity    (default: 3650)
  --yes, -y              Non-interactive / unattended mode
  --version TAG          Install a specific release tag instead of latest
  --uninstall            Remove ECUBE from this host
  --dry-run              Print all actions without executing them
  -h, --help             Show this help message
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-only)   INSTALL_FRONTEND=false; shift ;;
    --frontend-only)  INSTALL_BACKEND=false;  shift ;;
    --backend-host)   BACKEND_HOST="$2"; shift 2 ;;
    --install-dir)    INSTALL_DIR="$2";  shift 2 ;;
    --api-port)       API_PORT="$2";     shift 2 ;;
    --ui-port)        UI_PORT="$2";      shift 2 ;;
    --hostname)       HOSTNAME_OVERRIDE="$2"; shift 2 ;;
    --cert-validity)  CERT_VALIDITY="$2"; shift 2 ;;
    --yes|-y)         YES=true;  shift ;;
    --version)        VERSION_TAG="$2"; shift 2 ;;
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

  # Python 3.11
  if ! command -v python3.11 &>/dev/null; then
    warn "python3.11 not found."
    if [[ "${ID}" == "ubuntu" ]]; then
      local prompt_msg="Install python3.11 via the deadsnakes PPA (ppa:deadsnakes/ppa)?"
    else
      local prompt_msg="Install python3.11 via the deadsnakes apt repository?"
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
  if command -v ss &>/dev/null; then
    if ss -tlnp 2>/dev/null | grep -qE ":${port}\b"; then
      error "Port ${port} (${label}) is already in use."
      exit 1
    fi
  fi
  ok "Port ${port} (${label}) is available"
}

# ===========================================================================
# RESOLVE HOSTNAME / IP
# ===========================================================================
_resolve_host() {
  HOST="${HOSTNAME_OVERRIDE:-$(hostname -f 2>/dev/null || hostname)}"
  # Primary non-loopback IPv4
  HOST_IP=$(ip -4 addr show scope global | awk '/inet/{print $2}' | cut -d/ -f1 | head -1 || true)
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
# BACKEND INSTALLATION
# ===========================================================================
install_backend() {
  header "\n── Backend installation ────────────────────────────────────────"

  # 1. System user, role groups, and USB device access
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

  # 7. .env file
  _write_env_file

  # 8. Systemd unit
  _write_systemd_unit

  # 9. Reload and start
  run systemctl daemon-reload
  run systemctl enable ecube.service
  run systemctl restart ecube.service
  ok "ecube.service started and enabled"

  # 10. Health check
  _wait_for_healthy
}

_write_env_file() {
  local env_file="${INSTALL_DIR}/.env"
  if [[ -f "${env_file}" ]]; then
    info ".env already exists — not overwriting (preserving operator secrets)."
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
DATABASE_URL=postgresql://ecube:CHANGE_ME@localhost/ecube

# Set to true if a reverse proxy (nginx) sits in front of uvicorn.
TRUST_PROXY_HEADERS=${trust_proxy}

# Mount prefix used by nginx to proxy /api/* to the backend.
# Affects Swagger UI and OpenAPI schema server URL.
API_ROOT_PATH=${api_root_path}
EOF
    chmod 600 "${env_file}"
    chown ecube:ecube "${env_file}"
  else
    echo "[DRY-RUN] Would write ${env_file} with SECRET_KEY, DATABASE_URL placeholder, TRUST_PROXY_HEADERS=${trust_proxy}, API_ROOT_PATH=${api_root_path}"
  fi
  ok ".env written (remember to update DATABASE_URL before starting the service)"
}

_write_systemd_unit() {
  info "Writing systemd unit /etc/systemd/system/ecube.service..."
  local bind_host="127.0.0.1"
  [[ "${INSTALL_FRONTEND}" == false ]] && bind_host="0.0.0.0"

  if [[ "${DRY_RUN}" != true ]]; then
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
    echo "[DRY-RUN] Would write /etc/systemd/system/ecube.service (bind=${bind_host}:${API_PORT})"
  fi
  ok "Systemd unit written"
}

_wait_for_healthy() {
  if [[ "${DRY_RUN}" == true ]]; then
    echo "[DRY-RUN] Would poll https://localhost:${API_PORT}/health for up to 30 s"
    return
  fi
  info "Waiting for service health check (up to 30 s)..."
  local i=0
  until curl -fsk "https://localhost:${API_PORT}/health" &>/dev/null; do
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
      if [[ "${DRY_RUN}" != true ]]; then
        # Update existing keys in-place, or append if absent.
        if grep -q "^TRUST_PROXY_HEADERS=" "${env_file}"; then
          sed -i 's|^TRUST_PROXY_HEADERS=.*|TRUST_PROXY_HEADERS=true|' "${env_file}"
        else
          echo "TRUST_PROXY_HEADERS=true" >> "${env_file}"
        fi
        if grep -q "^API_ROOT_PATH=" "${env_file}"; then
          sed -i 's|^API_ROOT_PATH=.*|API_ROOT_PATH=/api|' "${env_file}"
        else
          echo "API_ROOT_PATH=/api" >> "${env_file}"
        fi
        ok ".env updated (TRUST_PROXY_HEADERS=true, API_ROOT_PATH=/api)"
      else
        echo "[DRY-RUN] Would patch ${env_file}: TRUST_PROXY_HEADERS=true, API_ROOT_PATH=/api"
      fi
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
    cat > /etc/nginx/sites-available/ecube <<EOF
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
        proxy_pass https://${BACKEND_HOST}:${API_PORT}/;
        proxy_ssl_verify off;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
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

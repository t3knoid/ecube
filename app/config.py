import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.utils.callback_payload_contract import validate_callback_payload_contract

logger = logging.getLogger(__name__)


DEFAULT_READINESS_MOUNT_CHECK_TIMEOUT_SECONDS = 1.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", env_ignore_empty=True)

    # Empty by default on fresh installs. The setup wizard writes this once
    # database connectivity is configured.
    database_url: str = ""

    #: PostgreSQL superuser (or CREATEDB-privileged role) name used by the
    #: setup wizard to provision the application database.  Set via
    #: ``PG_SUPERUSER_NAME`` in ``.env``.  Cleared automatically after
    #: successful provisioning.
    pg_superuser_name: str = ""

    #: Password for :attr:`pg_superuser_name`.  Cleared automatically from
    #: ``.env`` after successful database provisioning.
    pg_superuser_pass: str = ""

    #: PostgreSQL container-level username (``POSTGRES_USER``).  Used as a
    #: fallback when ``PG_SUPERUSER_NAME`` is not set, so the setup wizard
    #: can suggest the correct admin username for database provisioning.
    postgres_user: str = ""

    #: PostgreSQL hostname suggested to the setup wizard when the application
    #: is detected to be running inside a Docker container.  In a standard
    #: Docker Compose deployment this matches the ``postgres`` service name.
    #: Override with ``SETUP_DOCKER_DB_HOST=<name>`` if your Compose service
    #: is named differently.
    setup_docker_db_host: str = "postgres"

    #: PostgreSQL admin username suggested to the setup wizard for the
    #: database provisioning step.  The installer persists this in ``.env``
    #: (``SETUP_DEFAULT_ADMIN_USERNAME=...``) to keep UI defaults aligned
    #: with the superuser it created.  Left empty by default so the wizard
    #: falls back through the cascade (PG_SUPERUSER_NAME → POSTGRES_USER).
    setup_default_admin_username: str = ""
    
    #: Target platform for infrastructure implementations.  Factory functions
    #: in ``app.infrastructure`` use this to select concrete Protocol
    #: implementations.  Currently only ``"linux"`` adapters are provided;
    #: ``"windows"`` is accepted by the schema but reserved for future use
    #: and will raise ``ValueError`` at runtime until adapters are registered.
    platform: Literal["linux", "windows"] = "linux"

    #: Shared signing key for JWT tokens **and** cookie-based sessions
    #: (when ``SESSION_BACKEND=cookie``).  Rotating this key invalidates
    #: all outstanding JWTs and active cookie sessions.
    secret_key: str = "change-me-in-production-please-rotate-32b"

    #: Optional dedicated key material for encrypting stored mount credentials.
    #: When omitted, ECUBE derives a stable encryption key from ``secret_key``
    #: so fresh installs can persist mount credentials securely without an
    #: additional required setting.
    mount_credentials_encryption_key: str = ""

    algorithm: str = "HS256"

    # ---------------------------------------------------------------------------
    # Role resolver configuration
    # ---------------------------------------------------------------------------

    #: Which role resolver provider to use.  ``"local"`` (default) maps local
    #: OS/application groups to ECUBE roles.  ``"ldap"`` maps LDAP group DNs.
    #: ``"oidc"`` maps OIDC provider group claims to ECUBE roles.
    role_resolver: Literal["local", "ldap", "oidc"] = "local"

    #: Mapping used by :class:`~app.auth_providers.LocalGroupRoleResolver`.
    #: Keys are local group names; values are lists of ECUBE role strings.
    #: Example: ``{"evidence-admins": ["admin"], "evidence-team": ["processor"]}``
    local_group_role_map: Dict[str, List[str]] = {}

    #: Mapping used by :class:`~app.auth_providers.LdapGroupRoleResolver`.
    #: Keys are LDAP group distinguished names; values are lists of ECUBE role
    #: strings.
    #: Example: ``{"CN=EvidenceAdmins,DC=corp,DC=example,DC=com": ["admin"]}``
    ldap_group_role_map: Dict[str, List[str]] = {}

    #: LDAP server URI for group lookups when ``role_resolver = "ldap"``.
    #: Example: ``ldap://ldap.example.com`` or ``ldaps://ldap.example.com:636``
    ldap_server: Optional[str] = None

    #: Distinguished name used to bind to the LDAP server.
    ldap_bind_dn: Optional[str] = None

    #: Password for the LDAP bind DN.
    ldap_bind_password: Optional[str] = None

    #: Base DN for LDAP search queries (e.g. ``DC=corp,DC=example,DC=com``).
    ldap_base_dn: Optional[str] = None

    # ---------------------------------------------------------------------------
    # TLS configuration
    # ---------------------------------------------------------------------------

    #: Path to the TLS certificate file used by the application / uvicorn.
    tls_certfile: str = "/opt/ecube/certs/cert.pem"

    #: Path to the TLS private key file.
    tls_keyfile: str = "/opt/ecube/certs/key.pem"

    # ---------------------------------------------------------------------------
    # Operational tuning
    # ---------------------------------------------------------------------------

    #: Number of days to retain audit log records. Records older than this are
    #: purged on application startup.  ``0`` disables automatic cleanup.
    audit_log_retention_days: int = 365

    #: Maximum elapsed seconds for an individual file copy/checksum attempt.
    #: ``0`` disables timeout enforcement.
    copy_job_timeout: int = 3600

    #: Default number of Job Detail file rows returned per page.
    #: This value is operator-configurable for the UI and bounded to prevent
    #: overly small or excessively large file page requests.
    job_detail_files_page_size: int = Field(default=40, ge=20, le=100)

    #: Interval in seconds between automatic USB discovery sweeps.
    #: ``0`` disables periodic discovery.
    usb_discovery_interval: int = 30

    #: Maximum number of bytes sampled during manual startup-analysis transfer
    #: benchmarking. The benchmark reads up to this many bytes from the source
    #: share and writes the same amount to the assigned target drive.
    startup_analysis_benchmark_bytes: int = 8_388_608

    #: Timeout in seconds for each mountpoint check during ``GET /health/ready``.
    #: Keep this low so readiness fails fast even when a mount check hangs.
    readiness_mount_check_timeout_seconds: float = DEFAULT_READINESS_MOUNT_CHECK_TIMEOUT_SECONDS

    #: Total timeout budget in seconds for all mount checks during
    #: ``GET /health/ready``. This keeps probe latency bounded as mount count
    #: grows.
    readiness_mount_checks_total_timeout_seconds: float = 1.0

    #: Cache window in seconds for successful USB discovery readiness probes.
    #: A positive value avoids repeated full sysfs walks on frequent
    #: ``GET /health/ready`` checks while preserving periodic re-validation.
    readiness_usb_discovery_cache_ttl_seconds: float = 5.0

    # ---------------------------------------------------------------------------
    # Logging configuration
    # ---------------------------------------------------------------------------

    #: Root log level.  One of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``.
    log_level: str = "INFO"

    #: Log output format.  ``"text"`` for human-readable, ``"json"`` for
    #: structured JSON (suitable for log aggregation / compliance tooling).
    log_format: Literal["text", "json"] = "text"

    #: Standard ECUBE application log path. When set, a
    #: :class:`~logging.handlers.RotatingFileHandler` is attached.
    log_file: Optional[str] = "/var/log/ecube/app.log"

    #: Maximum size (bytes) of a single log file before rotation.  Default 10 MB.
    log_file_max_bytes: int = 10_485_760

    #: Number of rotated backup log files to keep.
    log_file_backup_count: int = 5

    # ---------------------------------------------------------------------------
    # OIDC configuration (used when role_resolver = "oidc")
    # ---------------------------------------------------------------------------

    #: Full OIDC discovery URL (the ``/.well-known/openid-configuration``
    #: endpoint of your identity provider).
    #: Example: ``https://<YOUR_AUTH0_DOMAIN>/.well-known/openid-configuration``
    oidc_discovery_url: Optional[str] = None

    #: OIDC client ID registered with the identity provider.
    oidc_client_id: Optional[str] = None

    #: OIDC client secret (keep secret; not used for token validation itself).
    oidc_client_secret: Optional[str] = None

    #: Expected audience value for ``aud`` claim validation.  When set, tokens
    #: whose ``aud`` claim does not match are rejected.  Leave ``None`` to skip
    #: audience validation.
    oidc_audience: Optional[str] = None

    #: Name of the JWT claim that contains the user's group memberships.
    #: Defaults to ``"groups"``; some providers use ``"roles"`` or a custom name.
    oidc_group_claim_name: str = "groups"

    #: Mapping used by :class:`~app.auth_providers.OidcGroupRoleResolver`.
    #: Keys are OIDC group/claim values; values are lists of ECUBE role strings.
    #: Example: ``{"evidence-admins": ["admin"], "evidence-team": ["processor"]}``
    oidc_group_role_map: Dict[str, List[str]] = {}

    #: Allowed JWT algorithms for OIDC token validation.
    oidc_allowed_algorithms: List[str] = Field(
        default=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]
    )

    #: Timeout in seconds for fetching the OIDC discovery document.
    oidc_discovery_timeout_seconds: int = 10

    # ---------------------------------------------------------------------------
    # Token expiration
    # ---------------------------------------------------------------------------

    #: Number of minutes before a locally-issued JWT expires.
    token_expire_minutes: int = 60

    # ---------------------------------------------------------------------------
    # Demo deployment configuration
    # ---------------------------------------------------------------------------

    #: Enable the public demo experience on a standard ECUBE installation.
    #: When ``True``, the login screen may display demo-safe guidance and the
    #: backend may apply demo-specific policy restrictions.
    demo_mode: bool = False

    #: Optional public-safe guidance text shown on the login screen when demo
    #: mode is enabled. This must never include internal-only deployment data.
    demo_login_message: str = ""

    #: Optional shared demo password shown publicly on the login screen for
    #: disposable demo deployments. Only set this when the password is
    #: intentionally meant to be visible to evaluators.
    demo_shared_password: str = ""

    #: Demo account metadata for the login panel and bootstrap flow. Public-safe
    #: fields such as ``username``, ``label``, and ``description`` may be shown
    #: on the login screen. Internal-only keys such as ``roles`` or ``password``
    #: may also be supplied for the trusted demo bootstrap command and are never
    #: exposed by the public auth metadata endpoint.
    demo_accounts: List[Dict[str, Any]] = Field(default_factory=list)

    #: Disable password-change operations for shared demo accounts when demo mode
    #: is enabled.
    demo_disable_password_change: bool = True

    #: Dedicated demo-only root used by the bootstrap flow for staging
    #: sanitized sample content.
    demo_data_root: str = "./demo-data"

    # ---------------------------------------------------------------------------
    # Copy engine tuning
    # ---------------------------------------------------------------------------

    #: Batch size for startup-analysis discovery, persistence, and validation.
    #: The upper bound keeps operator tuning from reintroducing unbounded
    #: startup-analysis memory growth on large source trees.
    startup_analysis_batch_size: int = Field(default=500, ge=1, le=5000)

    #: Chunk size in bytes for file copy and checksum computation.
    copy_chunk_size_bytes: int = 1_048_576

    #: Minimum buffered byte count before the copy engine flushes
    #: ``copied_bytes`` progress to the database.
    copy_progress_flush_bytes: int = 8_388_608

    #: Default thread pool size when ``ExportJob.thread_count`` is ``None``.
    copy_default_thread_count: int = 4

    #: Default maximum file-level retries when ``ExportJob.max_file_retries``
    #: is ``None``.
    copy_default_max_retries: int = 3

    #: Default retry delay in seconds when ``ExportJob.retry_delay_seconds``
    #: is ``None``.
    copy_default_retry_delay_seconds: float = 1.0

    # ---------------------------------------------------------------------------
    # Subprocess / system binary paths
    # ---------------------------------------------------------------------------

    #: Timeout in seconds for subprocess calls (mount, umount, sync, etc.).
    subprocess_timeout_seconds: int = 30

    #: Timeout in seconds for drive formatting subprocesses. Large media can
    #: legitimately take much longer than the generic subprocess timeout.
    drive_format_timeout_seconds: int = 900

    #: Timeout in seconds for drive mount subprocesses. Large removable media,
    #: especially exFAT volumes on slower links, can legitimately exceed the
    #: generic subprocess timeout during mount.
    drive_mount_timeout_seconds: int = 120

    #: Default NFS client protocol version requested for network mounts.
    nfs_client_version: Literal["4.2", "4.1", "4.0", "3"] = "4.1"

    #: Path to the ``mount`` binary.
    mount_binary_path: str = "/bin/mount"

    #: Path to the ``sync`` binary.
    sync_binary_path: str = "/bin/sync"

    #: Path to the ``umount`` binary.
    umount_binary_path: str = "/bin/umount"

    #: Path to the ``mountpoint`` binary.
    mountpoint_binary_path: str = "/bin/mountpoint"

    #: Path to the ``blkid`` binary (filesystem detection).
    blkid_binary_path: str = "/sbin/blkid"

    #: Path to the ``lsblk`` binary (filesystem detection fallback).
    lsblk_binary_path: str = "/bin/lsblk"

    #: Path to the ``mkfs.ext4`` binary.
    mkfs_ext4_path: str = "/sbin/mkfs.ext4"

    #: Path to the ``mkfs.exfat`` binary.
    mkfs_exfat_path: str = "/sbin/mkfs.exfat"

    #: Cluster size passed to ``mkfs.exfat``.  ``4K`` is the default because it
    #: preserves capacity for the common case where evidence sets include at
    #: least some small files; larger sizes are better suited only for drives
    #: storing very large files without small-file slack concerns.
    mkfs_exfat_cluster_size: str = "4K"

    #: Path to the ``dumpe2fs`` binary used for best-effort ext4 free-space probing.
    dumpe2fs_path: str = "/sbin/dumpe2fs"

    #: Base directory for USB drive mount points.  Each drive is mounted at
    #: ``<usb_mount_base_path>/<drive_db_id>``, e.g. ``/mnt/ecube/7``.
    usb_mount_base_path: str = "/mnt/ecube"

    # ---------------------------------------------------------------------------
    # OS user/group management binary paths
    # ---------------------------------------------------------------------------

    #: Whether to prepend ``sudo`` to OS management commands.  Set to
    #: ``false`` when the process already runs as root (e.g. inside a
    #: Docker container).  Defaults to ``true`` for native deployments
    #: where the service runs as a non-root ``ecube`` account.
    use_sudo: bool = True

    #: Path to the ``useradd`` binary (must match sudoers whitelist).
    useradd_binary_path: str = "/usr/sbin/useradd"

    #: Path to the ``usermod`` binary (must match sudoers whitelist).
    usermod_binary_path: str = "/usr/sbin/usermod"

    #: Path to the ``userdel`` binary (must match sudoers whitelist).
    userdel_binary_path: str = "/usr/sbin/userdel"

    #: Path to the ``groupadd`` binary (must match sudoers whitelist).
    groupadd_binary_path: str = "/usr/sbin/groupadd"

    #: Path to the ``groupdel`` binary (must match sudoers whitelist).
    groupdel_binary_path: str = "/usr/sbin/groupdel"

    #: Path to the ``chpasswd`` binary (must match sudoers whitelist).
    chpasswd_binary_path: str = "/usr/sbin/chpasswd"

    #: Path to the ``chage`` binary (must match sudoers whitelist).
    chage_binary_path: str = "/usr/bin/chage"

    #: Path to the host ``pwquality.conf`` file.
    pwquality_conf_path: str = "/etc/security/pwquality.conf"

    #: Root-owned helper used for atomic ``pwquality.conf`` writes.
    password_policy_writer_path: str = "/usr/local/bin/ecube-write-pwquality-conf"

    #: PAM service name used for local credential validation (``/auth/token``)
    #: via python-pam. Defaults to ``ecube``, a dedicated PAM config installed
    #: by the ECUBE installer (``/etc/pam.d/ecube``) that handles both local
    #: users (via pam_unix) and domain users (via pam_sss when SSSD is present).
    #: Override with ``PAM_SERVICE_NAME=login`` or ``PAM_SERVICE_NAME=sudo`` if
    #: the dedicated config is not installed.
    pam_service_name: str = "ecube"

    #: Optional PAM fallback service names attempted in order after
    #: ``pam_service_name`` if authentication fails.  Empty by default when
    #: the dedicated ``ecube`` PAM config is used; set to ``["sudo"]`` as a
    #: workaround on hosts without ``/etc/pam.d/ecube``.
    pam_fallback_services: List[str] = Field(default=[])

    #: Path to ``/proc/mounts`` for reading active mount information.
    procfs_mounts_path: str = "/proc/mounts"

    #: Path to ``/proc/diskstats`` for reading block-device statistics.
    procfs_diskstats_path: str = "/proc/diskstats"

    #: Path to the sysfs USB devices directory.
    sysfs_usb_devices_path: str = "/sys/bus/usb/devices"

    #: Path to the sysfs block devices directory.
    sysfs_block_path: str = "/sys/block"

    # ---------------------------------------------------------------------------
    # Directory browse settings
    # ---------------------------------------------------------------------------

    #: Allowlist of filesystem path prefixes that are permitted as browse roots.
    #: Only paths whose realpath starts with one of these prefixes (after DB
    #: validation) are served.  Provides a secondary defence-in-depth layer on
    #: top of the database-backed mount root validation.
    #:
    #: The defaults cover common ECUBE layouts.  Operators should override this
    #: via the ``BROWSE_ALLOWED_PREFIXES`` environment variable (JSON array) to
    #: match the actual mount hierarchy on their deployment.
    browse_allowed_prefixes: List[str] = Field(
        default=["/mnt/ecube/", "/nfs/", "/smb/"]
    )

    #: Maximum number of entries a single directory may contain before the
    #: browse endpoint rejects the request with 400.  Prevents DoS from
    #: directories with hundreds of thousands of files.  Set to 0 to disable.
    browse_max_dir_entries: int = Field(default=50_000, ge=0)

    # ---------------------------------------------------------------------------
    # Audit log pagination
    # ---------------------------------------------------------------------------

    #: Default page size for audit log queries.
    audit_log_default_limit: int = 100

    #: Maximum allowed page size for audit log queries.
    audit_log_max_limit: int = 1000

    # ---------------------------------------------------------------------------
    # CORS configuration
    # ---------------------------------------------------------------------------

    #: Origins permitted for cross-origin requests.  Empty by default
    #: (CORS disabled).  In production, FastAPI serves the SPA on the
    #: same origin so CORS is not triggered.  For local development, set
    #: via the ``CORS_ALLOWED_ORIGINS`` env var as a JSON list, e.g.:
    #:
    #: .. code-block:: bash
    #:
    #:     CORS_ALLOWED_ORIGINS='["http://localhost:5173"]'
    cors_allowed_origins: List[str] = []

    # ---------------------------------------------------------------------------
    # Reverse proxy / client IP settings
    # ---------------------------------------------------------------------------

    #: When ``True``, use ``X-Forwarded-For`` / ``X-Real-IP`` headers to
    #: determine the client IP address.  When ``False`` (default), always use
    #: ``request.client.host`` to prevent header spoofing on direct connections.
    trust_proxy_headers: bool = False

    #: Path prefix this application is mounted at behind a reverse proxy.
    #: Set to ``"/api"`` when an external reverse proxy (e.g. nginx)
    #: strips the ``/api`` prefix before forwarding requests.  Leave
    #: empty for standard deployments (both native and Docker) and any
    #: deployment where no prefix is stripped.  Controls the ``servers``
    #: entry in the OpenAPI spec so that Swagger UI "Try it out" generates
    #: correct request paths.
    api_root_path: str = ""

    #: Absolute path to a directory containing the pre-built frontend
    #: (Vue/Vite ``dist/`` output).  When set and the directory exists,
    #: FastAPI serves these static files and provides SPA fallback.  Set
    #: automatically in Docker images.  Leave empty (default) only when
    #: an external reverse proxy serves the frontend.
    serve_frontend_path: str = ""

    # ---------------------------------------------------------------------------
    # Webhook callback settings
    # ---------------------------------------------------------------------------

    #: Timeout in seconds for each individual callback HTTP request.
    callback_timeout_seconds: int = 30

    #: Allow callbacks to private/reserved IP addresses.  Must remain
    #: ``False`` in production to prevent SSRF attacks.
    callback_allow_private_ips: bool = False

    #: Maximum number of concurrent callback delivery threads.
    #: Limits resource usage under high job throughput; additional
    #: deliveries queue until a worker becomes available.
    callback_max_workers: int = 4

    #: Maximum number of outstanding callback deliveries (queued +
    #: in-flight).  When this limit is reached, new deliveries are
    #: dropped and an audit record is written.  Provides real
    #: backpressure against slow or unreachable callback endpoints.
    callback_max_pending: int = 100

    #: Optional HTTPS URL used for terminal-state callbacks when a job
    #: does not define its own callback_url. Job-level callback_url
    #: takes precedence over this system-wide default.
    callback_default_url: str | None = None

    #: Optional shared secret used to generate the
    #: ``X-ECUBE-Signature: sha256=...`` HMAC header for callback payloads.
    #: This value is write-only in admin configuration surfaces.
    callback_hmac_secret: str | None = None

    #: Optional outbound forward-proxy URL used for callback delivery.
    #: Supports ``http://`` and ``https://`` proxies. Leave unset to
    #: connect directly.
    callback_proxy_url: str | None = None

    #: Optional source-field allowlist applied to outbound callback payloads.
    #: When unset, ECUBE sends the default payload shape.
    callback_payload_fields: List[str] | None = None

    #: Optional outbound field mapping applied after
    #: :attr:`callback_payload_fields`. Values reference allowlisted source
    #: fields directly or use constrained ``${field}`` templates.
    callback_payload_field_map: Dict[str, str] | None = None

    # ---------------------------------------------------------------------------
    # Database pool settings
    # ---------------------------------------------------------------------------

    #: Number of persistent connections in the SQLAlchemy connection pool.
    db_pool_size: int = 5

    #: Maximum overflow connections above ``db_pool_size``.
    db_pool_max_overflow: int = 10

    #: Seconds after which a connection is recycled.  ``-1`` disables recycling.
    db_pool_recycle_seconds: int = -1

    # ---------------------------------------------------------------------------
    # OpenAPI metadata
    # ---------------------------------------------------------------------------

    #: Contact name shown in the OpenAPI spec.
    api_contact_name: str = "ECUBE Support"

    #: Contact email shown in the OpenAPI spec.
    api_contact_email: str = "support@ecube.local"

    # ---------------------------------------------------------------------------
    # Session / cookie configuration
    # ---------------------------------------------------------------------------

    #: Session storage backend.  ``"cookie"`` uses signed browser cookies;
    #: ``"redis"`` stores session data in Redis (requires ``redis`` package).
    session_backend: Literal["cookie", "redis"] = "cookie"

    #: Name of the session cookie sent to browsers.
    session_cookie_name: str = "ecube_session"

    #: Session cookie lifetime in seconds.  Default: 3600 (1 hour).
    session_cookie_expiration_seconds: int = 3600

    #: Domain scope for the session cookie.  ``None`` lets the browser apply
    #: its default rules.
    session_cookie_domain: Optional[str] = None

    #: Send the cookie only over HTTPS.  Should be ``True`` in production.
    session_cookie_secure: bool = True

    #: SameSite attribute for the session cookie.
    #: .. note:: The ``HttpOnly`` flag is always set on session cookies and
    #:    cannot be disabled.  Both Starlette's ``SessionMiddleware`` and
    #:    ECUBE's ``RedisSessionMiddleware`` enforce this unconditionally.
    session_cookie_samesite: Literal["strict", "lax", "none"] = "lax"

    # ---------------------------------------------------------------------------
    # Redis configuration (used when session_backend = "redis")
    # ---------------------------------------------------------------------------

    #: Redis connection URL.  Only used when ``session_backend = "redis"``.
    #: Example: ``redis://localhost:6379/0``
    redis_url: Optional[str] = None

    #: Timeout in seconds for establishing a Redis connection.
    redis_connection_timeout: int = 5

    #: Enable TCP keepalive on the Redis socket to detect dead connections.
    redis_socket_keepalive: bool = True

    def _demo_metadata_path(self) -> Path:
        return Path(self.demo_data_root).expanduser().resolve() / "demo-metadata.json"

    def _load_demo_metadata_payload(self) -> Dict[str, Any]:
        """Load the raw demo metadata payload from the managed demo-data root."""
        metadata_path = self._demo_metadata_path()
        if not metadata_path.is_file():
            return {}

        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load demo metadata", {"error": str(exc), "path": str(metadata_path)})
            return {}

        if isinstance(payload, dict):
            return payload
        return {}

    def load_demo_metadata(self) -> Dict[str, Any]:
        """Load effective demo runtime metadata from the managed demo-data root."""
        payload = self._load_demo_metadata_payload()
        if not payload:
            return {}

        config = payload.get("demo_config")
        if isinstance(config, dict):
            return config
        return payload

    def is_demo_mode_enabled(self) -> bool:
        """Return the effective demo-mode state.

        Once the demo bootstrap has seeded a managed demo root, the deployment
        remains in demo mode until the managed root is reset or removed.
        """
        if bool(self.demo_mode):
            return True

        payload = self._load_demo_metadata_payload()
        if not payload:
            return False

        config = payload.get("demo_config") if isinstance(payload.get("demo_config"), dict) else payload
        if isinstance(config, dict) and "demo_mode" in config:
            return bool(config.get("demo_mode"))

        return payload.get("managed_by") == "ecube-demo-seed-v1"

    def get_demo_login_message(self) -> str:
        value = self.demo_login_message.strip()
        if value:
            return value
        metadata_value = self.load_demo_metadata().get("login_message")
        if isinstance(metadata_value, str):
            return metadata_value.strip()
        return ""

    def get_demo_shared_password(self) -> str:
        value = self.demo_shared_password.strip()
        if value:
            return value
        metadata_value = self.load_demo_metadata().get("shared_password")
        if isinstance(metadata_value, str):
            return metadata_value.strip()
        return ""

    def get_demo_accounts(self) -> List[Dict[str, Any]]:
        if self.demo_accounts:
            return list(self.demo_accounts)
        metadata = self.load_demo_metadata()
        accounts = metadata.get("accounts", metadata.get("demo_accounts", []))
        if isinstance(accounts, list):
            return [account for account in accounts if isinstance(account, dict)]
        return []

    def get_demo_disable_password_change(self) -> bool:
        metadata = self.load_demo_metadata()
        if "demo_disable_password_change" in getattr(self, "model_fields_set", set()) or os.getenv("DEMO_DISABLE_PASSWORD_CHANGE") is not None:
            return bool(self.demo_disable_password_change)
        if "demo_disable_password_change" in metadata:
            return bool(metadata["demo_disable_password_change"])
        if "password_change_allowed" in metadata:
            return not bool(metadata["password_change_allowed"])
        return bool(self.demo_disable_password_change)

    @field_validator("serve_frontend_path", mode="before")
    @classmethod
    def _normalise_serve_frontend_path(cls, v: str) -> str:  # noqa: N805
        """Ensure ``serve_frontend_path`` is empty or an absolute path.

        Rejects dangerous system roots (``/``, ``/etc``, …) so a
        misconfiguration fails fast at startup rather than silently
        exposing host files through the SPA fallback.
        """
        if not isinstance(v, str) or v.strip() == "":
            return ""
        import os
        v = v.strip()
        if not os.path.isabs(v):
            raise ValueError(
                f"SERVE_FRONTEND_PATH must be an absolute path, got: {v!r}"
            )
        normalised = os.path.normpath(v)
        # Reject well-known system roots — mirrors the installer's
        # _protected list so runtime and install-time share the same
        # safety boundary.
        _DANGEROUS_ROOTS = frozenset((
            "/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib",
            "/lib64", "/media", "/mnt", "/opt", "/proc", "/root",
            "/run", "/sbin", "/srv", "/sys", "/tmp", "/usr", "/var",
        ))
        if normalised in _DANGEROUS_ROOTS:
            raise ValueError(
                f"SERVE_FRONTEND_PATH must not be a system root directory, "
                f"got: {normalised!r}"
            )
        return normalised

    @field_validator(
        "ldap_server",
        "ldap_bind_dn",
        "ldap_bind_password",
        "ldap_base_dn",
        "oidc_discovery_url",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_audience",
        "redis_url",
        "session_cookie_domain",
        mode="before",
    )
    @classmethod
    def _normalise_optional_strings(cls, v: str | None) -> str | None:  # noqa: N805
        """Treat blank strings as unset so empty env values do not override defaults."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("log_file", mode="before")
    @classmethod
    def _normalise_log_file(cls, v: str | None) -> str | None:  # noqa: N805
        if isinstance(v, str) and v.strip() == "":
            return None
        if not isinstance(v, str):
            return v

        path = os.path.expanduser(v.strip())
        if not path:
            return None
        if not os.path.isabs(path):
            path = os.path.sep + path.lstrip(os.path.sep)
        return os.path.normpath(path)

    @field_validator("session_cookie_samesite", mode="before")
    @classmethod
    def _normalise_samesite(cls, v: str) -> str:  # noqa: N805
        return v.lower() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _samesite_none_requires_secure(self) -> "Settings":
        if self.session_cookie_samesite == "none" and not self.session_cookie_secure:
            raise ValueError(
                "SESSION_COOKIE_SECURE must be true when "
                "SESSION_COOKIE_SAMESITE is 'none' (browsers reject "
                "SameSite=None cookies without the Secure flag)"
            )
        validate_callback_payload_contract(
            self.callback_payload_fields,
            self.callback_payload_field_map,
        )
        return self


_ENV_FILE = os.getenv("ECUBE_ENV_FILE", ".env")
settings = Settings(_env_file=_ENV_FILE)  # type: ignore[call-arg]

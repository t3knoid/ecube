from typing import Dict, List, Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator, model_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql://ecube:ecube@localhost/ecube"
    
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

    #: Maximum elapsed seconds for a copy job before it is marked FAILED with
    #: a timeout reason.  ``0`` disables timeout enforcement.
    copy_job_timeout: int = 3600

    #: Interval in seconds between automatic USB discovery sweeps.
    #: ``0`` disables periodic discovery.
    usb_discovery_interval: int = 30

    # ---------------------------------------------------------------------------
    # Logging configuration
    # ---------------------------------------------------------------------------

    #: Root log level.  One of ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``.
    log_level: str = "INFO"

    #: Log output format.  ``"text"`` for human-readable, ``"json"`` for
    #: structured JSON (suitable for log aggregation / compliance tooling).
    log_format: Literal["text", "json"] = "text"

    #: Optional path to a log file.  When set, a
    #: :class:`~logging.handlers.RotatingFileHandler` is attached.
    log_file: Optional[str] = None

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
    # Copy engine tuning
    # ---------------------------------------------------------------------------

    #: Chunk size in bytes for file copy and checksum computation.
    copy_chunk_size_bytes: int = 1_048_576

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

    # ---------------------------------------------------------------------------
    # OS user/group management binary paths
    # ---------------------------------------------------------------------------

    #: Whether to prepend ``sudo`` to OS management commands.  Set to
    #: ``false`` when the process already runs as root (e.g. inside a
    #: Docker container).  Defaults to ``true`` for bare-metal deployments
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

    #: Path to ``/proc/mounts`` for reading active mount information.
    procfs_mounts_path: str = "/proc/mounts"

    #: Path to ``/proc/diskstats`` for reading block-device statistics.
    procfs_diskstats_path: str = "/proc/diskstats"

    #: Path to the sysfs USB devices directory.
    sysfs_usb_devices_path: str = "/sys/bus/usb/devices"

    #: Path to the sysfs block devices directory.
    sysfs_block_path: str = "/sys/block"

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

    #: Origins permitted for cross-origin requests.  Typically needed only
    #: during development (Vite dev server on a different port) or when
    #: Swagger UI is served from a different origin.  In production, nginx
    #: proxies everything on the same origin so CORS is not triggered.
    cors_allowed_origins: List[str] = ["https://localhost:8443"]

    # ---------------------------------------------------------------------------
    # Reverse proxy / client IP settings
    # ---------------------------------------------------------------------------

    #: When ``True``, use ``X-Forwarded-For`` / ``X-Real-IP`` headers to
    #: determine the client IP address.  When ``False`` (default), always use
    #: ``request.client.host`` to prevent header spoofing on direct connections.
    trust_proxy_headers: bool = False

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

    @field_validator("session_cookie_domain", mode="before")
    @classmethod
    def _normalise_domain(cls, v: str | None) -> str | None:  # noqa: N805
        """Treat blank strings as *unset* so ``SESSION_COOKIE_DOMAIN=``
        in the environment behaves the same as omitting the variable."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

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
        return self


settings = Settings()

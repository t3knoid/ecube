from typing import Dict, List, Literal, Optional, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql://ecube:ecube@localhost/ecube"
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

    #: Path to the ``sync`` binary.
    sync_binary_path: str = "/bin/sync"

    #: Path to the ``umount`` binary.
    umount_binary_path: str = "/bin/umount"

    #: Path to ``/proc/mounts`` for reading active mount information.
    procfs_mounts_path: str = "/proc/mounts"

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


settings = Settings()

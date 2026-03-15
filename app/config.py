from typing import Dict, List, Literal, Optional, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()

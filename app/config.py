from typing import Dict, List, Literal

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
    role_resolver: Literal["local", "ldap"] = "local"

    #: Mapping used by :class:`~app.auth_providers.LocalGroupRoleResolver`.
    #: Keys are local group names; values are lists of ECUBE role strings.
    #: Example: ``{"evidence-admins": ["admin"], "evidence-team": ["processor"]}``
    local_group_role_map: Dict[str, List[str]] = {}

    #: Mapping used by :class:`~app.auth_providers.LdapGroupRoleResolver`.
    #: Keys are LDAP group distinguished names; values are lists of ECUBE role
    #: strings.
    #: Example: ``{"CN=EvidenceAdmins,DC=corp,DC=example,DC=com": ["admin"]}``
    ldap_group_role_map: Dict[str, List[str]] = {}


settings = Settings()

"""Pluggable role resolver providers.

Role resolution is the process of converting a user's group memberships into
ECUBE roles (``admin``, ``manager``, ``processor``, ``auditor``).

Three built-in providers are supplied:

* :class:`LocalGroupRoleResolver` *(default)* — uses a static group-to-role
  mapping defined in application settings (``local_group_role_map``).
* :class:`LdapGroupRoleResolver` *(optional)* — uses a separate mapping
  (``ldap_group_role_map``) intended for LDAP-sourced group names.  Enabled
  by setting ``role_resolver = "ldap"`` in configuration.
* :class:`OidcGroupRoleResolver` *(optional)* — maps OIDC provider group
  claims to ECUBE roles using ``oidc_group_role_map``.  Enabled by setting
  ``role_resolver = "oidc"`` in configuration.

All providers apply **deny-by-default** semantics: a group not present in the
mapping contributes no roles, and a user whose groups are entirely unmapped
will receive an empty role list (which ``require_roles`` will reject with
HTTP 403).

Usage::

    from app.auth_providers import get_role_resolver

    resolver = get_role_resolver()
    roles = resolver.resolve(["evidence-team", "analysts"])
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Dict, List

from app.config import settings


class RoleResolver(ABC):
    """Abstract base class for role resolver providers.

    Concrete implementations must override :meth:`resolve`.
    """

    @abstractmethod
    def resolve(self, groups: List[str]) -> List[str]:
        """Resolve a list of group names into a deduplicated list of ECUBE roles.

        Groups that have no mapping are silently ignored (deny-by-default).

        Args:
            groups: Group names extracted from the user's token or identity
                    context.

        Returns:
            A deduplicated list of role strings (e.g. ``["admin", "manager"]``).
            Returns an empty list when no groups map to any role.
        """


class _MappedRoleResolver(RoleResolver):
    """Shared implementation for map-based role resolvers.

    Sub-classes only need to supply the group-to-role mapping dict; the
    deduplication and iteration logic lives here once.
    """

    def __init__(self, group_role_map: Dict[str, List[str]]) -> None:
        self._map = group_role_map

    def resolve(self, groups: List[str]) -> List[str]:
        seen: set[str] = set()
        roles: List[str] = []
        for group in groups:
            for role in self._map.get(group, []):
                if role not in seen:
                    seen.add(role)
                    roles.append(role)
        return roles


class LocalGroupRoleResolver(_MappedRoleResolver):
    """Role resolver that maps local OS/application groups to ECUBE roles.

    The mapping is read from :attr:`app.config.Settings.local_group_role_map`.
    Example configuration::

        local_group_role_map = '{"evidence-admins": ["admin"], "evidence-team": ["processor"]}'

    Groups absent from the mapping contribute no roles (deny-by-default).
    """


class LdapGroupRoleResolver(_MappedRoleResolver):
    """Role resolver that maps LDAP group distinguished names to ECUBE roles.

    The mapping is read from :attr:`app.config.Settings.ldap_group_role_map`.
    Example configuration::

        ldap_group_role_map = '{"CN=EvidenceAdmins,DC=corp,DC=example,DC=com": ["admin"]}'

    Groups absent from the mapping contribute no roles (deny-by-default).

    This provider is selected when ``role_resolver = "ldap"`` in settings.
    """


class OidcGroupRoleResolver(_MappedRoleResolver):
    """Role resolver that maps OIDC provider group claims to ECUBE roles.

    The mapping is read from :attr:`app.config.Settings.oidc_group_role_map`.
    The claim that supplies the group list is configured via
    :attr:`app.config.Settings.oidc_group_claim_name` (default: ``"groups"``).

    Example configuration::

        oidc_group_role_map = '{"evidence-admins": ["admin"], "evidence-team": ["processor"]}'

    Groups absent from the mapping contribute no roles (deny-by-default).

    This provider is selected when ``role_resolver = "oidc"`` in settings.
    """


@lru_cache(maxsize=1)
def get_role_resolver() -> RoleResolver:
    """Return the configured role resolver instance (cached after first call).

    The provider is selected by :attr:`app.config.Settings.role_resolver`:

    * ``"local"`` (default) — returns a :class:`LocalGroupRoleResolver` backed
      by ``settings.local_group_role_map``.
    * ``"ldap"`` — returns an :class:`LdapGroupRoleResolver` backed by
      ``settings.ldap_group_role_map``.
    * ``"oidc"`` — returns an :class:`OidcGroupRoleResolver` backed by
      ``settings.oidc_group_role_map``.

    The result is cached for the lifetime of the process so that configuration
    is read once and the resolver instance is reused across requests.

    Raises:
        ValueError: If ``settings.role_resolver`` is an unrecognised value.
    """
    if settings.role_resolver == "ldap":
        return LdapGroupRoleResolver(settings.ldap_group_role_map)
    if settings.role_resolver == "local":
        return LocalGroupRoleResolver(settings.local_group_role_map)
    if settings.role_resolver == "oidc":
        return OidcGroupRoleResolver(settings.oidc_group_role_map)
    raise ValueError(
        f"Unknown role_resolver setting: {settings.role_resolver!r}. "
        "Valid options are: 'local', 'ldap', 'oidc'."
    )

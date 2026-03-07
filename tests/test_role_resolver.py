"""Tests for the pluggable role resolver extension point (app/auth_providers.py).

Verifies that:
- LocalGroupRoleResolver maps configured groups to the correct ECUBE roles.
- LocalGroupRoleResolver denies (returns empty) for unmapped groups.
- LdapGroupRoleResolver maps configured groups to the correct ECUBE roles.
- LdapGroupRoleResolver denies (returns empty) for unmapped groups.
- OidcGroupRoleResolver maps OIDC group claims to the correct ECUBE roles.
- OidcGroupRoleResolver denies (returns empty) for unmapped groups.
- get_role_resolver() returns the provider selected by settings.role_resolver.
- Multiple groups are resolved with deduplication.
- get_current_user applies the resolver when the token has no roles claim.
"""

import time
from unittest.mock import patch

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
from app.auth_providers import (
    LdapGroupRoleResolver,
    LocalGroupRoleResolver,
    OidcGroupRoleResolver,
    RoleResolver,
    get_role_resolver,
)
from app.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = settings.secret_key
_ALGORITHM = settings.algorithm


def _make_token(payload: dict) -> str:
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def _valid_payload(**overrides) -> dict:
    base = {
        "sub": "user-resolver-test",
        "username": "resolver-tester",
        "exp": int(time.time()) + 3600,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------


class TestRoleResolverInterface:
    def test_base_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            RoleResolver()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_resolve(self):
        class BadResolver(RoleResolver):
            pass

        with pytest.raises(TypeError):
            BadResolver()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# LocalGroupRoleResolver
# ---------------------------------------------------------------------------


class TestLocalGroupRoleResolver:
    _MAP = {
        "evidence-admins": ["admin"],
        "evidence-managers": ["manager"],
        "evidence-team": ["processor"],
        "evidence-auditors": ["auditor"],
        "dual-role-group": ["admin", "manager"],
    }

    def _resolver(self):
        return LocalGroupRoleResolver(self._MAP)

    def test_known_group_returns_correct_role(self):
        assert self._resolver().resolve(["evidence-team"]) == ["processor"]

    def test_admin_group_returns_admin_role(self):
        assert self._resolver().resolve(["evidence-admins"]) == ["admin"]

    def test_manager_group_returns_manager_role(self):
        assert self._resolver().resolve(["evidence-managers"]) == ["manager"]

    def test_auditor_group_returns_auditor_role(self):
        assert self._resolver().resolve(["evidence-auditors"]) == ["auditor"]

    def test_unmapped_group_returns_empty_list(self):
        assert self._resolver().resolve(["unknown-group"]) == []

    def test_empty_groups_returns_empty_list(self):
        assert self._resolver().resolve([]) == []

    def test_multiple_groups_aggregates_roles(self):
        roles = self._resolver().resolve(["evidence-admins", "evidence-team"])
        assert set(roles) == {"admin", "processor"}
        assert len(roles) == 2  # no duplicates

    def test_duplicate_roles_are_deduplicated(self):
        # Both groups map to overlapping roles; admin must appear only once.
        roles = self._resolver().resolve(["dual-role-group", "evidence-admins"])
        assert roles.count("admin") == 1

    def test_group_with_multiple_roles(self):
        roles = self._resolver().resolve(["dual-role-group"])
        assert set(roles) == {"admin", "manager"}

    def test_mixed_mapped_and_unmapped_groups(self):
        roles = self._resolver().resolve(["unknown-group", "evidence-team"])
        assert roles == ["processor"]

    def test_empty_map_always_returns_empty(self):
        resolver = LocalGroupRoleResolver({})
        assert resolver.resolve(["evidence-admins"]) == []


# ---------------------------------------------------------------------------
# LdapGroupRoleResolver
# ---------------------------------------------------------------------------


class TestLdapGroupRoleResolver:
    _MAP = {
        "CN=EvidenceAdmins,DC=corp,DC=example,DC=com": ["admin"],
        "CN=EvidenceManagers,DC=corp,DC=example,DC=com": ["manager"],
        "CN=EvidenceProcessors,DC=corp,DC=example,DC=com": ["processor"],
        "CN=EvidenceAuditors,DC=corp,DC=example,DC=com": ["auditor"],
    }

    def _resolver(self):
        return LdapGroupRoleResolver(self._MAP)

    def test_known_ldap_group_returns_correct_role(self):
        assert self._resolver().resolve(
            ["CN=EvidenceAdmins,DC=corp,DC=example,DC=com"]
        ) == ["admin"]

    def test_unmapped_ldap_group_returns_empty(self):
        assert self._resolver().resolve(["CN=Unknown,DC=corp,DC=example,DC=com"]) == []

    def test_empty_groups_returns_empty(self):
        assert self._resolver().resolve([]) == []

    def test_multiple_ldap_groups_aggregates_roles(self):
        roles = self._resolver().resolve(
            [
                "CN=EvidenceAdmins,DC=corp,DC=example,DC=com",
                "CN=EvidenceProcessors,DC=corp,DC=example,DC=com",
            ]
        )
        assert set(roles) == {"admin", "processor"}

    def test_empty_map_always_returns_empty(self):
        resolver = LdapGroupRoleResolver({})
        assert resolver.resolve(["CN=EvidenceAdmins,DC=corp,DC=example,DC=com"]) == []


# ---------------------------------------------------------------------------
# OidcGroupRoleResolver
# ---------------------------------------------------------------------------


class TestOidcGroupRoleResolver:
    _MAP = {
        "evidence-admins": ["admin"],
        "evidence-managers": ["manager"],
        "evidence-team": ["processor"],
        "evidence-auditors": ["auditor"],
        "dual-role-group": ["admin", "manager"],
    }

    def _resolver(self):
        return OidcGroupRoleResolver(self._MAP)

    def test_known_group_returns_correct_role(self):
        assert self._resolver().resolve(["evidence-team"]) == ["processor"]

    def test_admin_group_returns_admin_role(self):
        assert self._resolver().resolve(["evidence-admins"]) == ["admin"]

    def test_unmapped_group_returns_empty_list(self):
        assert self._resolver().resolve(["unknown-group"]) == []

    def test_empty_groups_returns_empty_list(self):
        assert self._resolver().resolve([]) == []

    def test_multiple_groups_aggregates_roles(self):
        roles = self._resolver().resolve(["evidence-admins", "evidence-team"])
        assert set(roles) == {"admin", "processor"}
        assert len(roles) == 2

    def test_duplicate_roles_are_deduplicated(self):
        roles = self._resolver().resolve(["dual-role-group", "evidence-admins"])
        assert roles.count("admin") == 1

    def test_group_with_multiple_roles(self):
        roles = self._resolver().resolve(["dual-role-group"])
        assert set(roles) == {"admin", "manager"}

    def test_mixed_mapped_and_unmapped_groups(self):
        roles = self._resolver().resolve(["unknown-group", "evidence-team"])
        assert roles == ["processor"]

    def test_empty_map_always_returns_empty(self):
        resolver = OidcGroupRoleResolver({})
        assert resolver.resolve(["evidence-admins"]) == []

    def test_is_role_resolver_subclass(self):
        assert issubclass(OidcGroupRoleResolver, RoleResolver)

    def test_all_four_roles_resolved_from_four_groups(self):
        roles = self._resolver().resolve(
            ["evidence-admins", "evidence-managers", "evidence-team", "evidence-auditors"]
        )
        assert set(roles) == {"admin", "manager", "processor", "auditor"}


# ---------------------------------------------------------------------------
# get_role_resolver() factory
# ---------------------------------------------------------------------------


class TestGetRoleResolver:
    def setup_method(self):
        get_role_resolver.cache_clear()

    def teardown_method(self):
        get_role_resolver.cache_clear()

    def test_local_resolver_selected_by_default(self):
        with patch.object(settings, "role_resolver", "local"):
            resolver = get_role_resolver()
        assert isinstance(resolver, LocalGroupRoleResolver)

    def test_ldap_resolver_selected_when_configured(self):
        with patch.object(settings, "role_resolver", "ldap"):
            resolver = get_role_resolver()
        assert isinstance(resolver, LdapGroupRoleResolver)

    def test_unknown_resolver_raises_value_error(self):
        with patch.object(settings, "role_resolver", "unknown"):
            with pytest.raises(ValueError, match="Unknown role_resolver setting: 'unknown'"):
                get_role_resolver()

    def test_local_resolver_uses_local_group_role_map(self):
        local_map = {"my-group": ["admin"]}
        with patch.object(settings, "role_resolver", "local"):
            with patch.object(settings, "local_group_role_map", local_map):
                resolver = get_role_resolver()
        assert resolver.resolve(["my-group"]) == ["admin"]

    def test_ldap_resolver_uses_ldap_group_role_map(self):
        ldap_map = {"CN=Admins,DC=example,DC=com": ["admin"]}
        with patch.object(settings, "role_resolver", "ldap"):
            with patch.object(settings, "ldap_group_role_map", ldap_map):
                resolver = get_role_resolver()
        assert resolver.resolve(["CN=Admins,DC=example,DC=com"]) == ["admin"]

    def test_oidc_resolver_selected_when_configured(self):
        with patch.object(settings, "role_resolver", "oidc"):
            resolver = get_role_resolver()
        assert isinstance(resolver, OidcGroupRoleResolver)

    def test_oidc_resolver_uses_oidc_group_role_map(self):
        oidc_map = {"evidence-admins": ["admin"]}
        with patch.object(settings, "role_resolver", "oidc"):
            with patch.object(settings, "oidc_group_role_map", oidc_map):
                resolver = get_role_resolver()
        assert resolver.resolve(["evidence-admins"]) == ["admin"]

    def test_unknown_resolver_error_message_includes_oidc(self):
        with patch.object(settings, "role_resolver", "bad"):
            with pytest.raises(ValueError, match="'oidc'"):
                get_role_resolver()


# ---------------------------------------------------------------------------
# Integration: get_current_user applies resolver when roles claim is absent
# ---------------------------------------------------------------------------

_test_app = FastAPI()


@_test_app.get("/resolved-user")
def resolved_user_route(user: CurrentUser = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "groups": user.groups,
        "roles": user.roles,
    }


@pytest.fixture()
def resolver_client():
    with TestClient(_test_app) as c:
        yield c


class TestGetCurrentUserWithResolver:
    """get_current_user should resolve roles from groups when roles claim is absent."""

    _LOCAL_MAP = {"evidence-admins": ["admin"], "evidence-team": ["processor"]}

    def setup_method(self):
        get_role_resolver.cache_clear()

    def teardown_method(self):
        get_role_resolver.cache_clear()

    def test_roles_resolved_from_groups_when_no_roles_claim(self, resolver_client):
        payload = _valid_payload(groups=["evidence-team"])  # no "roles" key
        token = _make_token(payload)
        with patch.object(settings, "role_resolver", "local"):
            with patch.object(settings, "local_group_role_map", self._LOCAL_MAP):
                resp = resolver_client.get(
                    "/resolved-user",
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["roles"] == ["processor"]
        assert data["groups"] == ["evidence-team"]

    def test_roles_resolved_from_multiple_groups(self, resolver_client):
        payload = _valid_payload(groups=["evidence-admins", "evidence-team"])
        token = _make_token(payload)
        with patch.object(settings, "role_resolver", "local"):
            with patch.object(settings, "local_group_role_map", self._LOCAL_MAP):
                resp = resolver_client.get(
                    "/resolved-user",
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["roles"]) == {"admin", "processor"}

    def test_unmapped_group_yields_empty_roles(self, resolver_client):
        payload = _valid_payload(groups=["unknown-group"])
        token = _make_token(payload)
        with patch.object(settings, "role_resolver", "local"):
            with patch.object(settings, "local_group_role_map", self._LOCAL_MAP):
                resp = resolver_client.get(
                    "/resolved-user",
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200
        assert resp.json()["roles"] == []

    def test_explicit_roles_claim_takes_precedence_over_resolver(self, resolver_client):
        """If the token already carries roles, the resolver is NOT called."""
        payload = _valid_payload(groups=["evidence-admins"], roles=["auditor"])
        token = _make_token(payload)
        with patch.object(settings, "role_resolver", "local"):
            with patch.object(settings, "local_group_role_map", self._LOCAL_MAP):
                resp = resolver_client.get(
                    "/resolved-user",
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200
        # The token said "auditor", not "admin" — resolver should not override.
        assert resp.json()["roles"] == ["auditor"]

    def test_ldap_resolver_resolves_groups_in_token(self, resolver_client):
        ldap_map = {"CN=EvidenceAdmins,DC=corp,DC=example,DC=com": ["admin"]}
        payload = _valid_payload(groups=["CN=EvidenceAdmins,DC=corp,DC=example,DC=com"])
        token = _make_token(payload)
        with patch.object(settings, "role_resolver", "ldap"):
            with patch.object(settings, "ldap_group_role_map", ldap_map):
                resp = resolver_client.get(
                    "/resolved-user",
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200
        assert resp.json()["roles"] == ["admin"]

    def test_no_groups_and_no_roles_yields_empty_roles(self, resolver_client):
        payload = _valid_payload()  # no groups, no roles
        token = _make_token(payload)
        with patch.object(settings, "role_resolver", "local"):
            with patch.object(settings, "local_group_role_map", self._LOCAL_MAP):
                resp = resolver_client.get(
                    "/resolved-user",
                    headers={"Authorization": f"Bearer {token}"},
                )
        assert resp.status_code == 200
        assert resp.json()["roles"] == []


# ---------------------------------------------------------------------------
# Integration: get_current_user with OIDC resolver
# ---------------------------------------------------------------------------


class TestGetCurrentUserWithOidcResolver:
    """get_current_user should use OidcGroupRoleResolver when role_resolver='oidc'."""

    _OIDC_MAP = {"evidence-admins": ["admin"], "evidence-team": ["processor"]}

    def setup_method(self):
        get_role_resolver.cache_clear()

    def teardown_method(self):
        get_role_resolver.cache_clear()

    def _make_oidc_token_via_mock(self, groups, group_claim_name="groups"):
        """Produce a local HS256 token and mock the OIDC validation so that
        _get_current_user_oidc receives a realistic payload."""
        payload = {
            "sub": "oidc-sub-456",
            "preferred_username": "oidc.tester",
            group_claim_name: groups,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()) - 5,
        }
        return payload

    def test_oidc_token_with_groups_maps_to_roles(self, resolver_client):
        oidc_payload = self._make_oidc_token_via_mock(["evidence-admins"])
        with patch.object(settings, "role_resolver", "oidc"):
            with patch.object(settings, "oidc_group_role_map", self._OIDC_MAP):
                with patch.object(settings, "oidc_group_claim_name", "groups"):
                    with patch(
                        "app.services.oidc_service.validate_token",
                        return_value=oidc_payload,
                    ):
                        resp = resolver_client.get(
                            "/resolved-user",
                            headers={"Authorization": "Bearer mock.oidc.token"},
                        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["roles"] == ["admin"]
        assert data["groups"] == ["evidence-admins"]
        assert data["username"] == "oidc.tester"

    def test_oidc_token_without_groups_returns_empty_roles(self, resolver_client):
        oidc_payload = {
            "sub": "oidc-sub-789",
            "preferred_username": "oidc.user2",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()) - 5,
        }
        with patch.object(settings, "role_resolver", "oidc"):
            with patch.object(settings, "oidc_group_role_map", self._OIDC_MAP):
                with patch.object(settings, "oidc_group_claim_name", "groups"):
                    with patch("app.services.oidc_service.validate_token", return_value=oidc_payload):
                        resp = resolver_client.get(
                            "/resolved-user",
                            headers={"Authorization": "Bearer mock.oidc.token"},
                        )
        assert resp.status_code == 200
        assert resp.json()["roles"] == []

    def test_oidc_token_with_mixed_mapped_unmapped_groups(self, resolver_client):
        oidc_payload = self._make_oidc_token_via_mock(["evidence-admins", "unknown-group"])
        with patch.object(settings, "role_resolver", "oidc"):
            with patch.object(settings, "oidc_group_role_map", self._OIDC_MAP):
                with patch.object(settings, "oidc_group_claim_name", "groups"):
                    with patch("app.services.oidc_service.validate_token", return_value=oidc_payload):
                        resp = resolver_client.get(
                            "/resolved-user",
                            headers={"Authorization": "Bearer mock.oidc.token"},
                        )
        assert resp.status_code == 200
        assert resp.json()["roles"] == ["admin"]

    def test_oidc_token_with_multiple_groups_multiple_roles(self, resolver_client):
        oidc_payload = self._make_oidc_token_via_mock(["evidence-admins", "evidence-team"])
        with patch.object(settings, "role_resolver", "oidc"):
            with patch.object(settings, "oidc_group_role_map", self._OIDC_MAP):
                with patch.object(settings, "oidc_group_claim_name", "groups"):
                    with patch("app.services.oidc_service.validate_token", return_value=oidc_payload):
                        resp = resolver_client.get(
                            "/resolved-user",
                            headers={"Authorization": "Bearer mock.oidc.token"},
                        )
        assert resp.status_code == 200
        assert set(resp.json()["roles"]) == {"admin", "processor"}

    def test_oidc_validation_failure_returns_401(self, resolver_client):
        from app.services.oidc_service import OidcTokenError

        with patch.object(settings, "role_resolver", "oidc"):
            with patch("app.services.oidc_service.validate_token", side_effect=OidcTokenError("Token expired")):
                resp = resolver_client.get(
                    "/resolved-user",
                    headers={"Authorization": "Bearer bad.oidc.token"},
                )
        assert resp.status_code == 401

    def test_oidc_token_falls_back_to_sub_when_no_preferred_username(self, resolver_client):
        oidc_payload = {
            "sub": "oidc-sub-only",
            "groups": ["evidence-admins"],
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()) - 5,
        }
        with patch.object(settings, "role_resolver", "oidc"):
            with patch.object(settings, "oidc_group_role_map", self._OIDC_MAP):
                with patch.object(settings, "oidc_group_claim_name", "groups"):
                    with patch("app.services.oidc_service.validate_token", return_value=oidc_payload):
                        resp = resolver_client.get(
                            "/resolved-user",
                            headers={"Authorization": "Bearer mock.oidc.token"},
                        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "oidc-sub-only"

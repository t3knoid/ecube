"""Tests for app/services/oidc_service.py.

Tests cover:
- Valid token acceptance
- Expired token rejection
- Invalid signature rejection
- Audience mismatch rejection
- Missing required claims rejection
- JWKS cache behaviour
- Discovery document failures
- Group claim extraction
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.hazmat.backends import default_backend
from jwt import PyJWKClient

import jwt as pyjwt

from app.config import settings
from app.services.oidc_service import (
    OidcTokenError,
    clear_jwks_cache,
    get_jwks_client,
    validate_token,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_TEST_DISCOVERY_URL = "https://example.com/.well-known/openid-configuration"
_TEST_JWKS_URI = "https://example.com/.well-known/jwks.json"


# ---------------------------------------------------------------------------
# Helpers: RSA key pair for test tokens
# ---------------------------------------------------------------------------


def _generate_rsa_keypair():
    """Return (private_key, public_key) for RSA-256 test tokens."""
    private_key = generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    return private_key, private_key.public_key()


def _make_rsa_token(
    private_key,
    payload: Dict[str, Any],
    key_id: str = "test-key-id",
) -> str:
    """Encode a JWT signed with the given RSA private key."""
    return pyjwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def _valid_oidc_payload(**overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "sub": "oidc-user-123",
        "preferred_username": "oidc.user",
        "groups": ["evidence-admins"],
        "iat": int(time.time()) - 5,
        "exp": int(time.time()) + 3600,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the JWKS cache before and after every test."""
    clear_jwks_cache()
    yield
    clear_jwks_cache()


@pytest.fixture()
def rsa_keypair():
    return _generate_rsa_keypair()


@pytest.fixture()
def mock_jwks_client(rsa_keypair):
    """Return a mock PyJWKClient that resolves against the test RSA key pair."""
    private_key, public_key = rsa_keypair

    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key

    mock_client = MagicMock(spec=PyJWKClient)
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
    return mock_client, private_key


# ---------------------------------------------------------------------------
# OidcTokenError: basic
# ---------------------------------------------------------------------------


class TestOidcTokenError:
    def test_is_exception_subclass(self):
        assert issubclass(OidcTokenError, Exception)

    def test_message_preserved(self):
        err = OidcTokenError("something went wrong")
        assert str(err) == "something went wrong"


# ---------------------------------------------------------------------------
# get_jwks_client: discovery behaviour
# ---------------------------------------------------------------------------


class TestGetJwksClient:
    def test_raises_when_discovery_url_not_configured(self):
        with patch.object(settings, "oidc_discovery_url", None):
            with pytest.raises(OidcTokenError, match="oidc_discovery_url"):
                get_jwks_client()

    def test_raises_when_discovery_url_empty_string(self):
        with patch.object(settings, "oidc_discovery_url", ""):
            with pytest.raises(OidcTokenError, match="oidc_discovery_url"):
                get_jwks_client()

    def test_raises_on_network_failure(self):
        with patch.object(settings, "oidc_discovery_url", "https://invalid.example.test/.well-known/openid-configuration"):
            with patch("app.services.oidc_service.urlopen", side_effect=OSError("network error")):
                with pytest.raises(OidcTokenError, match="Failed to fetch OIDC discovery document"):
                    get_jwks_client()

    def test_raises_when_jwks_uri_missing_from_discovery(self):
        discovery_doc = {"issuer": "https://example.com"}  # no jwks_uri
        with patch.object(settings, "oidc_discovery_url", _TEST_DISCOVERY_URL):
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_response.read.return_value = json.dumps(discovery_doc).encode()
            with patch("app.services.oidc_service.urlopen", return_value=mock_response):
                with pytest.raises(OidcTokenError, match="jwks_uri"):
                    get_jwks_client()

    def test_returns_pyjwks_client_on_success(self):
        discovery_doc = {
            "issuer": "https://example.com",
            "jwks_uri": _TEST_JWKS_URI,
        }
        with patch.object(settings, "oidc_discovery_url", _TEST_DISCOVERY_URL):
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_response.read.return_value = json.dumps(discovery_doc).encode()
            with patch("app.services.oidc_service.urlopen", return_value=mock_response):
                with patch("app.services.oidc_service.PyJWKClient") as mock_cls:
                    mock_cls.return_value = MagicMock(spec=PyJWKClient)
                    result = get_jwks_client()
                    mock_cls.assert_called_once_with(_TEST_JWKS_URI)
                    assert result is mock_cls.return_value

    def test_result_is_cached_across_calls(self):
        discovery_doc = {
            "issuer": "https://example.com",
            "jwks_uri": _TEST_JWKS_URI,
        }
        with patch.object(settings, "oidc_discovery_url", _TEST_DISCOVERY_URL):
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_response.read.return_value = json.dumps(discovery_doc).encode()
            with patch("app.services.oidc_service.urlopen", return_value=mock_response) as mock_open:
                with patch("app.services.oidc_service.PyJWKClient", return_value=MagicMock(spec=PyJWKClient)):
                    c1 = get_jwks_client()
                    c2 = get_jwks_client()
                    # urlopen should have been called only once despite two get_jwks_client calls
                    assert mock_open.call_count == 1
                    assert c1 is c2

    def test_clear_cache_allows_refetch(self):
        discovery_doc = {
            "issuer": "https://example.com",
            "jwks_uri": _TEST_JWKS_URI,
        }
        with patch.object(settings, "oidc_discovery_url", _TEST_DISCOVERY_URL):
            mock_response = MagicMock()
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            mock_response.read.return_value = json.dumps(discovery_doc).encode()
            with patch("app.services.oidc_service.urlopen", return_value=mock_response) as mock_open:
                with patch("app.services.oidc_service.PyJWKClient", return_value=MagicMock(spec=PyJWKClient)):
                    get_jwks_client()
                    clear_jwks_cache()
                    get_jwks_client()
                    assert mock_open.call_count == 2


# ---------------------------------------------------------------------------
# validate_token
# ---------------------------------------------------------------------------


class TestValidateToken:
    def _patch_jwks_client(self, mock_client):
        return patch("app.services.oidc_service.get_jwks_client", return_value=mock_client)

    def test_valid_token_returns_payload(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        payload = _valid_oidc_payload()
        token = _make_rsa_token(private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", None):
                result = validate_token(token)

        assert result["sub"] == "oidc-user-123"
        assert result["preferred_username"] == "oidc.user"
        assert result["groups"] == ["evidence-admins"]

    def test_expired_token_raises_oidc_token_error(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        payload = _valid_oidc_payload(exp=int(time.time()) - 3600)
        token = _make_rsa_token(private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", None):
                with pytest.raises(OidcTokenError, match="expired"):
                    validate_token(token)

    def test_invalid_signature_raises_oidc_token_error(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        # Sign with a different key
        other_private_key, _ = _generate_rsa_keypair()
        payload = _valid_oidc_payload()
        token = _make_rsa_token(other_private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", None):
                with pytest.raises(OidcTokenError):
                    validate_token(token)

    def test_audience_mismatch_raises_oidc_token_error(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        payload = _valid_oidc_payload(aud="wrong-audience")
        token = _make_rsa_token(private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", "expected-audience"):
                with pytest.raises(OidcTokenError, match="audience"):
                    validate_token(token)

    def test_valid_audience_claim_accepted(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        payload = _valid_oidc_payload(aud="my-client-id")
        token = _make_rsa_token(private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", "my-client-id"):
                result = validate_token(token)
        assert result["sub"] == "oidc-user-123"

    def test_audience_validation_skipped_when_not_configured(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        # Token has no aud claim; should not raise when oidc_audience is None
        payload = _valid_oidc_payload()
        token = _make_rsa_token(private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", None):
                result = validate_token(token)
        assert result["sub"] == "oidc-user-123"

    def test_jwks_key_lookup_failure_raises_oidc_token_error(self):
        mock_client = MagicMock(spec=PyJWKClient)
        mock_client.get_signing_key_from_jwt.side_effect = Exception("key not found")

        with patch("app.services.oidc_service.get_jwks_client", return_value=mock_client):
            with pytest.raises(OidcTokenError, match="signing key"):
                validate_token("dummy.token.value")

    def test_get_jwks_client_oidc_error_propagated(self):
        with patch(
            "app.services.oidc_service.get_jwks_client",
            side_effect=OidcTokenError("discovery failed"),
        ):
            with pytest.raises(OidcTokenError, match="discovery failed"):
                validate_token("any.token.value")

    def test_token_without_groups_claim_returns_empty(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        payload = _valid_oidc_payload()
        del payload["groups"]
        token = _make_rsa_token(private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", None):
                result = validate_token(token)

        assert "groups" not in result

    def test_custom_group_claim_name_accessible_in_payload(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        payload = _valid_oidc_payload()
        payload["org_groups"] = ["evidence-admins"]
        token = _make_rsa_token(private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", None):
                with patch.object(settings, "oidc_group_claim_name", "org_groups"):
                    result = validate_token(token)

        assert result.get("org_groups") == ["evidence-admins"]

    def test_token_missing_exp_raises_oidc_token_error(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        payload = _valid_oidc_payload()
        del payload["exp"]
        token = _make_rsa_token(private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", None):
                with pytest.raises(OidcTokenError, match="missing required claim"):
                    validate_token(token)

    def test_token_missing_iat_raises_oidc_token_error(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        payload = _valid_oidc_payload()
        del payload["iat"]
        token = _make_rsa_token(private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", None):
                with pytest.raises(OidcTokenError, match="missing required claim"):
                    validate_token(token)

    def test_token_missing_sub_raises_oidc_token_error(self, mock_jwks_client, rsa_keypair):
        mock_client, private_key = mock_jwks_client
        payload = _valid_oidc_payload()
        del payload["sub"]
        token = _make_rsa_token(private_key, payload)

        with self._patch_jwks_client(mock_client):
            with patch.object(settings, "oidc_audience", None):
                with pytest.raises(OidcTokenError, match="missing required claim"):
                    validate_token(token)

"""OIDC token validation service.

Fetches OIDC provider metadata from the configured discovery URL, retrieves
the provider's JSON Web Key Set (JWKS), and validates ID tokens presented by
clients.

The :func:`get_jwks_client` helper is cached with :func:`functools.lru_cache`
so that the public-key discovery round-trip happens only once per process
lifetime (or until :func:`clear_jwks_cache` is called, e.g. in tests).

Typical usage::

    from app.services import oidc_service

    try:
        payload = oidc_service.validate_token(raw_token)
    except oidc_service.OidcTokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    groups = payload.get(settings.oidc_group_claim_name, [])
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Dict
from urllib.request import urlopen

import jwt
from jwt import PyJWKClient

from app.config import settings

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class OidcTokenError(Exception):
    """Raised when an OIDC ID token fails validation for any reason.

    Callers should translate this to HTTP 401.
    """


# ---------------------------------------------------------------------------
# JWKS client (cached)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_jwks_client() -> PyJWKClient:
    """Return a cached :class:`jwt.PyJWKClient` for the configured OIDC provider.

    Fetches the OIDC discovery document at :attr:`app.config.Settings.oidc_discovery_url`
    to obtain the ``jwks_uri``, then constructs and caches a
    :class:`~jwt.PyJWKClient` pointed at that URI.

    Returns:
        A :class:`jwt.PyJWKClient` instance.

    Raises:
        OidcTokenError: If ``oidc_discovery_url`` is not configured, the
                        discovery document cannot be fetched, or the document
                        is missing the ``jwks_uri`` field.
    """
    if not settings.oidc_discovery_url:
        raise OidcTokenError(
            "OIDC is enabled but 'oidc_discovery_url' is not configured."
        )

    discovery_url = settings.oidc_discovery_url
    try:
        with urlopen(discovery_url, timeout=10) as resp:  # noqa: S310 - URL is administrator-controlled config, not user input
            discovery: Dict[str, Any] = json.loads(resp.read().decode())
    except OidcTokenError:
        raise
    except Exception as exc:
        raise OidcTokenError(
            f"Failed to fetch OIDC discovery document from {discovery_url!r}: {exc}"
        ) from exc

    jwks_uri = discovery.get("jwks_uri")
    if not jwks_uri:
        raise OidcTokenError(
            "OIDC discovery document is missing the required 'jwks_uri' field."
        )

    return PyJWKClient(jwks_uri)


def clear_jwks_cache() -> None:
    """Clear the cached JWKS client (useful in tests or after config changes)."""
    get_jwks_client.cache_clear()


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------


def validate_token(token: str) -> Dict[str, Any]:
    """Validate an OIDC ID token and return its decoded claims.

    Validation steps:

    1. Retrieves the provider's signing key from the cached JWKS client.
    2. Verifies the JWT signature using RSA or EC algorithms.
    3. Validates standard claims:

       - ``exp`` — token must not be expired (strict; no grace period).
       - ``iat`` — issued-at must be present.
       - ``aud`` — validated against :attr:`~app.config.Settings.oidc_audience`
         when that setting is non-empty; skipped otherwise.

    Args:
        token: The raw JWT ID token string (the value from the ``Authorization:
               Bearer <token>`` header).

    Returns:
        The decoded token payload as a plain dictionary.  Callers should extract
        the groups claim via ``payload.get(settings.oidc_group_claim_name, [])``.

    Raises:
        OidcTokenError: For any validation failure — expired token, invalid
                        signature, missing required claims, audience mismatch,
                        or JWKS discovery failure.
    """
    try:
        client = get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
    except OidcTokenError:
        raise
    except Exception as exc:
        raise OidcTokenError(
            f"Failed to obtain signing key for OIDC token: {exc}"
        ) from exc

    decode_kwargs: Dict[str, Any] = {
        "algorithms": ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
        "options": {
            "require": ["exp", "iat", "sub"],
        },
    }

    if settings.oidc_audience:
        decode_kwargs["audience"] = settings.oidc_audience
    else:
        # No audience configured — skip audience validation.
        decode_kwargs["options"]["verify_aud"] = False

    try:
        payload: Dict[str, Any] = jwt.decode(
            token, signing_key.key, **decode_kwargs
        )
    except jwt.ExpiredSignatureError as exc:
        raise OidcTokenError("OIDC token has expired.") from exc
    except jwt.InvalidAudienceError as exc:
        raise OidcTokenError("OIDC token audience mismatch.") from exc
    except jwt.MissingRequiredClaimError as exc:
        raise OidcTokenError(f"OIDC token missing required claim: {exc}") from exc
    except jwt.InvalidTokenError as exc:
        raise OidcTokenError(f"OIDC token validation failed: {exc}") from exc

    return payload

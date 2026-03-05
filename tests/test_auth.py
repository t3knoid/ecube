"""Tests for bearer token authentication dependency (app/auth.py)."""

import time

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import CurrentUser, get_current_user
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
        "sub": "user-123",
        "username": "testuser",
        "groups": ["evidence-team"],
        "roles": ["processor"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Minimal test app that exposes a single protected endpoint
# ---------------------------------------------------------------------------

_test_app = FastAPI()


@_test_app.get("/protected")
def protected_route(user: CurrentUser = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "groups": user.groups,
        "roles": user.roles,
    }


@pytest.fixture
def auth_client():
    with TestClient(_test_app) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_valid_token_returns_user_context(auth_client):
    token = _make_token(_valid_payload())
    response = auth_client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "user-123"
    assert data["username"] == "testuser"
    assert data["groups"] == ["evidence-team"]
    assert data["roles"] == ["processor"]


def test_missing_token_returns_401(auth_client):
    response = auth_client.get("/protected")
    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()


def test_invalid_token_returns_401(auth_client):
    response = auth_client.get("/protected", headers={"Authorization": "Bearer not.a.valid.token"})
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


def test_expired_token_returns_401(auth_client):
    expired_payload = _valid_payload(exp=int(time.time()) - 60)
    token = _make_token(expired_payload)
    response = auth_client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


def test_token_signed_with_wrong_secret_returns_401(auth_client):
    token = jwt.encode(_valid_payload(), "wrong-secret", algorithm=_ALGORITHM)
    response = auth_client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_token_missing_sub_returns_401(auth_client):
    payload = _valid_payload()
    del payload["sub"]
    token = _make_token(payload)
    response = auth_client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "payload" in response.json()["detail"].lower()


def test_token_missing_username_returns_401(auth_client):
    payload = _valid_payload()
    del payload["username"]
    token = _make_token(payload)
    response = auth_client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "payload" in response.json()["detail"].lower()


def test_token_optional_claims_default_to_empty_lists(auth_client):
    payload = {"sub": "user-456", "username": "minimaluser"}
    token = _make_token(payload)
    response = auth_client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert data["groups"] == []
    assert data["roles"] == []


def test_www_authenticate_header_present_on_401(auth_client):
    response = auth_client.get("/protected")
    assert response.status_code == 401
    assert "www-authenticate" in {k.lower() for k in response.headers}

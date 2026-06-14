"""Unit tests for get_optional_user_lenient (public-endpoint token resolution).

A bad/expired/unverifiable token must degrade the caller to anonymous (None)
rather than raising 401/503 the way get_optional_user does. This is what lets
POST /api/feedback never block a submission on a stale session.
"""

import asyncio
from unittest.mock import patch

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from jwt import PyJWKClientError

from api.auth.dependencies import get_optional_user_lenient


def _creds(token: str = "tok") -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_no_credentials_returns_none():
    assert asyncio.run(get_optional_user_lenient(credentials=None)) is None


def test_valid_token_returns_claims():
    claims = {"sub": "auth0|x", "email": "x@example.com"}
    with patch("api.auth.dependencies.validate_token", return_value=claims):
        result = asyncio.run(get_optional_user_lenient(credentials=_creds()))
    assert result == claims


@pytest.mark.parametrize(
    "exc",
    [
        jwt.InvalidTokenError("malformed"),
        jwt.ExpiredSignatureError("expired"),
        PyJWKClientError("jwks unreachable"),
    ],
)
def test_unverifiable_token_degrades_to_anonymous(exc):
    with patch("api.auth.dependencies.validate_token", side_effect=exc):
        result = asyncio.run(get_optional_user_lenient(credentials=_creds("garbage")))
    assert result is None

"""Tests for JWT token validation."""

import time
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

# Generate test RSA keypair (module-level, reused across tests)
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_key = _private_key.public_key()

TEST_DOMAIN = "test.us.auth0.com"
TEST_AUDIENCE = "test-api"
TEST_ISSUER = f"https://{TEST_DOMAIN}/"


def _encode_token(payload: dict) -> str:
    """Encode a JWT with the test private key."""
    return pyjwt.encode(payload, _private_key, algorithm="RS256")


def _valid_payload(**overrides) -> dict:
    """Build a valid JWT payload with sensible defaults."""
    now = int(time.time())
    base = {
        "sub": "auth0|abc123",
        "iss": TEST_ISSUER,
        "aud": TEST_AUDIENCE,
        "iat": now,
        "exp": now + 3600,
        "email": "user@example.com",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _patch_settings():
    """Patch Auth0 settings for all tests."""
    with patch("api.auth.jwt.settings") as mock_settings:
        mock_settings.auth0_domain = TEST_DOMAIN
        mock_settings.auth0_audience = TEST_AUDIENCE
        yield mock_settings


@pytest.fixture(autouse=True)
def _reset_jwks_client():
    """Reset the singleton JWKS client between tests."""
    import api.auth.jwt as jwt_module

    jwt_module._jwks_client = None
    yield
    jwt_module._jwks_client = None


@pytest.fixture(autouse=True)
def _mock_jwks_client():
    """Mock the JWKS client to return our test public key."""
    mock_signing_key = MagicMock()
    mock_signing_key.key = _public_key

    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with patch("api.auth.jwt._get_jwks_client", return_value=mock_client):
        yield mock_client


class TestValidateToken:
    """Tests for the validate_token function."""

    def test_valid_token_returns_payload(self):
        """A correctly signed token with valid claims decodes successfully."""
        from api.auth.jwt import validate_token

        payload = _valid_payload()
        token = _encode_token(payload)

        result = validate_token(token)

        assert result["sub"] == "auth0|abc123"
        assert result["email"] == "user@example.com"
        assert result["iss"] == TEST_ISSUER
        assert result["aud"] == TEST_AUDIENCE

    def test_expired_token_raises(self):
        """An expired token raises ExpiredSignatureError."""
        from api.auth.jwt import validate_token

        payload = _valid_payload(exp=int(time.time()) - 3600)
        token = _encode_token(payload)

        with pytest.raises(pyjwt.ExpiredSignatureError):
            validate_token(token)

    def test_wrong_audience_raises(self):
        """A token with the wrong audience raises InvalidAudienceError."""
        from api.auth.jwt import validate_token

        payload = _valid_payload(aud="wrong-audience")
        token = _encode_token(payload)

        with pytest.raises(pyjwt.InvalidAudienceError):
            validate_token(token)

    def test_wrong_issuer_raises(self):
        """A token with the wrong issuer raises InvalidIssuerError."""
        from api.auth.jwt import validate_token

        payload = _valid_payload(iss="https://evil.example.com/")
        token = _encode_token(payload)

        with pytest.raises(pyjwt.InvalidIssuerError):
            validate_token(token)

    def test_malformed_token_raises(self):
        """A garbage string raises DecodeError."""
        from api.auth.jwt import validate_token

        with pytest.raises((pyjwt.InvalidTokenError, pyjwt.DecodeError)):
            validate_token("not.a.jwt")

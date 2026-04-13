"""Tests for JWT token validation (Auth0 and Google) and auth dependencies."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt import PyJWKClientError

# Generate test RSA keypair (module-level, reused across tests)
_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_public_key = _private_key.public_key()

TEST_DOMAIN = "test.us.auth0.com"
TEST_AUDIENCE = "test-api"
TEST_ISSUER = f"https://{TEST_DOMAIN}/"
TEST_GOOGLE_CLIENT_ID = "test-google-client-id.apps.googleusercontent.com"
TEST_GOOGLE_ISSUER = "https://accounts.google.com"


def _encode_token(payload: dict) -> str:
    """Encode a JWT with the test private key."""
    return pyjwt.encode(payload, _private_key, algorithm="RS256")


def _valid_payload(**overrides) -> dict:
    """Build a valid Auth0 JWT payload with sensible defaults."""
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


def _google_payload(**overrides) -> dict:
    """Build a valid Google ID token payload with sensible defaults."""
    now = int(time.time())
    base = {
        "sub": "google_user_12345",
        "iss": TEST_GOOGLE_ISSUER,
        "aud": TEST_GOOGLE_CLIENT_ID,
        "iat": now,
        "exp": now + 3600,
        "email": "user@gmail.com",
        "given_name": "Test",
        "family_name": "User",
        "picture": "https://lh3.googleusercontent.com/photo.jpg",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _patch_settings():
    """Patch Auth0 and Google settings for all tests."""
    with (
        patch("api.auth.jwt.settings") as mock_jwt_settings,
        patch("api.auth.google_jwt.settings") as mock_google_settings,
    ):
        for s in (mock_jwt_settings, mock_google_settings):
            s.auth0_domain = TEST_DOMAIN
            s.auth0_audience = TEST_AUDIENCE
            s.google_client_id = TEST_GOOGLE_CLIENT_ID
        yield mock_jwt_settings


@pytest.fixture(autouse=True)
def _reset_jwks_client():
    """Reset JWKS client singletons between tests."""
    import api.auth.jwt as jwt_module
    import api.auth.google_jwt as google_jwt_module

    jwt_module._jwks_client = None
    google_jwt_module._google_jwks_client = None
    yield
    jwt_module._jwks_client = None
    google_jwt_module._google_jwks_client = None


def _make_mock_jwks_client():
    """Create a mock JWKS client returning the test public key."""
    mock_signing_key = MagicMock()
    mock_signing_key.key = _public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
    return mock_client


@pytest.fixture(autouse=True)
def _mock_jwks_client():
    """Mock the Auth0 JWKS client to return our test public key."""
    mock_client = _make_mock_jwks_client()
    with patch("api.auth.jwt._get_jwks_client", return_value=mock_client):
        yield mock_client


@pytest.fixture(autouse=True)
def _mock_google_jwks_client():
    """Mock the Google JWKS client to return our test public key."""
    mock_client = _make_mock_jwks_client()
    with patch(
        "api.auth.google_jwt._get_google_jwks_client", return_value=mock_client
    ):
        yield mock_client


class TestValidateAuth0Token:
    """Tests for Auth0 token validation."""

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


class TestValidateGoogleToken:
    """Tests for Google One Tap token validation."""

    def test_valid_google_token_returns_payload(self):
        """A valid Google ID token decodes successfully."""
        from api.auth.google_jwt import validate_google_token

        payload = _google_payload()
        token = _encode_token(payload)
        result = validate_google_token(token)

        assert result["sub"] == "google_user_12345"
        assert result["email"] == "user@gmail.com"
        assert result["iss"] == TEST_GOOGLE_ISSUER

    def test_expired_google_token_raises(self):
        """An expired Google token raises ExpiredSignatureError."""
        from api.auth.google_jwt import validate_google_token

        payload = _google_payload(exp=int(time.time()) - 3600)
        token = _encode_token(payload)

        with pytest.raises(pyjwt.ExpiredSignatureError):
            validate_google_token(token)

    def test_wrong_audience_raises(self):
        """A Google token with wrong audience raises InvalidAudienceError."""
        from api.auth.google_jwt import validate_google_token

        payload = _google_payload(aud="wrong-client-id")
        token = _encode_token(payload)

        with pytest.raises(pyjwt.InvalidAudienceError):
            validate_google_token(token)

    def test_accepts_both_google_issuers(self):
        """Google tokens from either issuer format are accepted."""
        from api.auth.google_jwt import validate_google_token

        for issuer in ["https://accounts.google.com", "accounts.google.com"]:
            payload = _google_payload(iss=issuer)
            token = _encode_token(payload)
            result = validate_google_token(token)
            assert result["sub"] == "google_user_12345"


class TestTokenDispatch:
    """Tests for the validate_token issuer-based dispatcher."""

    def test_auth0_token_routes_to_auth0(self):
        """Token with Auth0 issuer uses Auth0 validation."""
        from api.auth.jwt import validate_token

        payload = _valid_payload()
        token = _encode_token(payload)
        result = validate_token(token)

        assert result["sub"] == "auth0|abc123"
        assert result["iss"] == TEST_ISSUER

    def test_google_token_routes_to_google(self):
        """Token with Google issuer uses Google validation."""
        from api.auth.jwt import validate_token

        payload = _google_payload()
        token = _encode_token(payload)
        result = validate_token(token)

        assert result["sub"] == "google_user_12345"
        assert result["iss"] == TEST_GOOGLE_ISSUER

    def test_google_accounts_issuer_routes_to_google(self):
        """Token with bare accounts.google.com issuer uses Google validation."""
        from api.auth.jwt import validate_token

        payload = _google_payload(iss="accounts.google.com")
        token = _encode_token(payload)
        result = validate_token(token)

        assert result["sub"] == "google_user_12345"

    def test_google_token_falls_back_to_auth0_when_google_not_configured(
        self, _patch_settings
    ):
        """Google-issued token falls back to Auth0 when google_client_id is unset."""
        _patch_settings.google_client_id = None
        from api.auth.jwt import validate_token

        payload = _google_payload()
        token = _encode_token(payload)

        # Should try Auth0 validation and fail on issuer mismatch
        with pytest.raises(pyjwt.InvalidIssuerError):
            validate_token(token)


class TestEnvVarGuards:
    """Tests for missing environment variable guards in JWKS client initialization."""

    @pytest.fixture(autouse=True)
    def _mock_jwks_client(self):
        """Override: don't mock _get_jwks_client so we can test the real function."""
        yield

    @pytest.fixture(autouse=True)
    def _mock_google_jwks_client(self):
        """Override: don't mock _get_google_jwks_client so we can test the real function."""
        yield

    def test_auth0_missing_domain_raises(self, _patch_settings):
        """_get_jwks_client raises RuntimeError when auth0_domain is unset."""
        _patch_settings.auth0_domain = None
        from api.auth.jwt import _get_jwks_client

        with pytest.raises(RuntimeError, match="AUTH0_DOMAIN"):
            _get_jwks_client()

    def test_auth0_missing_audience_raises(self, _patch_settings):
        """_get_jwks_client raises RuntimeError when auth0_audience is unset."""
        _patch_settings.auth0_audience = None
        from api.auth.jwt import _get_jwks_client

        with pytest.raises(RuntimeError, match="AUTH0_AUDIENCE"):
            _get_jwks_client()

    def test_google_missing_client_id_raises(self):
        """_get_google_jwks_client raises RuntimeError when google_client_id is unset."""
        import api.auth.google_jwt as google_jwt_module

        google_jwt_module.settings.google_client_id = None
        with pytest.raises(RuntimeError, match="GOOGLE_CLIENT_ID"):
            google_jwt_module._get_google_jwks_client()


class TestAuthDependencies:
    """Tests for get_optional_user and get_current_user FastAPI dependencies."""

    def _run(self, coro):
        """Run an async function synchronously."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_optional_user_returns_none_when_no_credentials(self):
        """get_optional_user returns None when no Bearer token is present."""
        from api.auth.dependencies import get_optional_user

        result = self._run(get_optional_user(None))
        assert result is None

    def test_optional_user_returns_claims_for_valid_token(self):
        """get_optional_user returns claims for a valid token."""
        from api.auth.dependencies import get_optional_user

        payload = _valid_payload()
        token = _encode_token(payload)
        creds = MagicMock()
        creds.credentials = token
        result = self._run(get_optional_user(creds))
        assert result["sub"] == "auth0|abc123"

    def test_optional_user_raises_401_on_expired_token(self):
        """get_optional_user raises 401 HTTPException for an expired token."""
        from api.auth.dependencies import get_optional_user

        payload = _valid_payload(exp=int(time.time()) - 3600)
        token = _encode_token(payload)
        creds = MagicMock()
        creds.credentials = token
        with pytest.raises(HTTPException) as exc_info:
            self._run(get_optional_user(creds))
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_optional_user_raises_401_on_invalid_token(self):
        """get_optional_user raises 401 HTTPException for an invalid token."""
        from api.auth.dependencies import get_optional_user

        creds = MagicMock()
        creds.credentials = "not.a.valid.jwt"
        with pytest.raises(HTTPException) as exc_info:
            self._run(get_optional_user(creds))
        assert exc_info.value.status_code == 401
        assert "invalid" in exc_info.value.detail.lower()

    def test_optional_user_raises_401_on_jwks_client_error(self):
        """get_optional_user raises 401 HTTPException on PyJWKClientError."""
        from api.auth.dependencies import get_optional_user

        creds = MagicMock()
        creds.credentials = _encode_token(_valid_payload())
        with patch(
            "api.auth.dependencies.validate_token",
            side_effect=PyJWKClientError("connection failed"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                self._run(get_optional_user(creds))
            assert exc_info.value.status_code == 401

    def test_current_user_raises_401_when_none(self):
        """get_current_user raises 401 when user is None (no auth)."""
        from api.auth.dependencies import get_current_user

        with pytest.raises(HTTPException) as exc_info:
            self._run(get_current_user(None))
        assert exc_info.value.status_code == 401
        assert "required" in exc_info.value.detail.lower()

    def test_current_user_returns_claims_when_present(self):
        """get_current_user returns claims when a valid user is provided."""
        from api.auth.dependencies import get_current_user

        claims = {"sub": "auth0|123", "email": "test@example.com"}
        result = self._run(get_current_user(claims))
        assert result == claims

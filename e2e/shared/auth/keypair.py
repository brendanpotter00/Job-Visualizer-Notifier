"""Generate/cache an RSA keypair for the e2e suite's fake Auth0 tenant.

PLAN.md §4: mint our own RS256 token and patch the ONE seam that decides which
public key `jwt.decode` checks a token against (`api.auth.jwt._get_jwks_client`).
This module owns the private half of that key; `mint.py` signs with it and
`e2e_app.py` serves the public half in place of a real JWKS fetch.

Cached under `e2e/add-companies/artifacts/keys/` (gitignored) so repeated runs
don't pay RSA keygen every time and so `mint.py` and `e2e_app.py` — two
different processes — agree on the same key without an env var round-trip.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

_KEY_DIR = Path(__file__).resolve().parents[2] / "add-companies" / "artifacts" / "keys"
_PRIVATE_KEY_PATH = _KEY_DIR / "e2e_rsa_private.pem"

#: Stable key id — not load-bearing for validation (our patched JWKS client
#: hands back a single fixed key regardless of the token's `kid`), but present
#: in the mock JWKS JSON handed back for shape-completeness.
KID = "e2e-add-companies"


def _generate_and_cache() -> RSAPrivateKey:
    _KEY_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    _PRIVATE_KEY_PATH.write_bytes(pem)
    _PRIVATE_KEY_PATH.chmod(0o600)
    return key


def load_or_create_private_key() -> RSAPrivateKey:
    """The e2e tenant's private key, generating and caching it on first use."""
    if _PRIVATE_KEY_PATH.exists():
        data = _PRIVATE_KEY_PATH.read_bytes()
        loaded = serialization.load_pem_private_key(data, password=None)
        if not isinstance(loaded, RSAPrivateKey):
            raise RuntimeError(f"{_PRIVATE_KEY_PATH} does not hold an RSA private key")
        return loaded
    return _generate_and_cache()


def public_key() -> RSAPublicKey:
    return load_or_create_private_key().public_key()

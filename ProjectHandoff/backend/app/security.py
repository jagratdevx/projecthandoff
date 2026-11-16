from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

_PBKDF2_ITERATIONS = 200_000


# ---------------------------------------------------------------------------
# Password hashing (PBKDF2-HMAC-SHA256)
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$", 2)
        if scheme != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS)
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, AttributeError):
        return False


def hash_token(token: str) -> str:
    """SHA-256 hex digest, used for invitation token storage (never store raw tokens)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Stateless signed session tokens (HMAC-SHA256, no third-party JWT dependency)
# ---------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_token(claims: dict, secret_key: str) -> str:
    body = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_token(token: str, secret_key: str) -> dict | None:
    """Return claims if the token is authentic and unexpired, else None."""
    try:
        body, signature = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(secret_key.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        claims = json.loads(_b64url_decode(body))
    except (ValueError, UnicodeDecodeError):
        return None
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp < time.time():
        return None
    return claims


# ---------------------------------------------------------------------------
# OAuth state parameter (CSRF protection for the Drive authorization flow)
# ---------------------------------------------------------------------------

def create_signed_state(nonce: str, secret_key: str) -> str:
    return create_token({"n": nonce, "exp": time.time() + 600}, secret_key)


def verify_signed_state(state: str, secret_key: str) -> bool:
    return read_signed_state(state, secret_key) is not None


def read_signed_state(state: str, secret_key: str) -> str | None:
    """Return the signed nonce if authentic and unexpired, else None."""
    claims = verify_token(state, secret_key)
    if claims and claims.get("n"):
        return str(claims["n"])
    return None

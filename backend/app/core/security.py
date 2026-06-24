"""
app/core/security.py
====================
JWT security utilities for TalentMatch AI.  (L-4: was previously an empty stub)

Centralises token creation so the signing algorithm, expiry window, and
secret key are defined in exactly one place.  The FastAPI dependency
``verify_admin_token`` intentionally lives in profiles.py to avoid circular
imports (it references the FastAPI router and must be co-located with the
login endpoint).
"""

import jwt
from datetime import datetime, timezone

from app.core.config import settings


def create_admin_token(expires_in_seconds: int = 86_400) -> str:
    """
    Creates and returns a signed JWT admin token.

    Args:
        expires_in_seconds: Token lifetime in seconds (default 24 hours).

    Returns:
        Signed JWT string, ready to be returned directly to the client.

    Note:
        ``exp`` is stored as an **integer** per RFC 7519 §4.1.4.
        Using a float would cause strict JWT verifiers (AWS Cognito, Okta,
        many mobile SDKs) to reject the token.
    """
    payload = {
        "sub": "admin",
        "role": "admin",
        "exp": int(datetime.now(timezone.utc).timestamp()) + expires_in_seconds,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decodes and verifies a signed JWT token, returning its payload dict.

    Raises:
        jwt.ExpiredSignatureError: if the token's ``exp`` claim has passed.
        jwt.InvalidTokenError:     if the signature or structure is invalid.
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
    )

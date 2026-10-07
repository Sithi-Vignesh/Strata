"""Opaque server-side session token primitives."""

import hashlib
import secrets


SESSION_LIFETIME_MS = 2_592_000_000


def generate_session_token() -> str:
    """Generate a cryptographically secure opaque session bearer token."""
    return secrets.token_urlsafe(32)


def session_token_digest(token: str) -> str:
    """Return the fixed-width SHA-256 hex digest persisted for a raw token."""
    if not isinstance(token, str) or not token:
        raise ValueError("session token must be a non-empty string.")
    try:
        encoded = token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("session token must contain only ASCII characters.") from exc
    return hashlib.sha256(encoded).hexdigest()

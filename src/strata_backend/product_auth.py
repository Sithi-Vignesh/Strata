"""HTTP cookie helpers for Strata's opaque server-side sessions."""

from starlette.responses import Response


SESSION_COOKIE_NAME = "strata_session"
SESSION_COOKIE_MAX_AGE_SECONDS = 2_592_000


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    """Attach the one authoritative browser session-cookie contract."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_COOKIE_MAX_AGE_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    """Clear the session cookie with the same scope and SameSite contract."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )

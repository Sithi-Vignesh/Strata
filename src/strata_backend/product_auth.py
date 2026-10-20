"""HTTP cookie helpers for Strata's opaque server-side sessions."""

from starlette.responses import Response
from starlette.requests import Request
from urllib.parse import urlsplit


SESSION_COOKIE_NAME = "strata_session"
SESSION_COOKIE_MAX_AGE_SECONDS = 2_592_000


def is_trusted_mutation_origin(request: Request, frontend_origin: str) -> bool:
    """Validate browser mutation origins, including same-site alternate ports.

    CORS controls reading responses, not delivery of simple POSTs such as logout.
    The same-origin Vite proxy preserves Host. Headerless non-browser clients
    remain supported; browsers supply Origin, Referer or Fetch Metadata.
    """
    trusted = {str(request.base_url).rstrip("/"), frontend_origin.rstrip("/")}
    origins = request.headers.getlist("origin")
    if origins:
        return len(origins) == 1 and origins[0] in trusted
    referers = request.headers.getlist("referer")
    if referers:
        if len(referers) != 1:
            return False
        try:
            parsed = urlsplit(referers[0])
        except ValueError:
            return False
        return f"{parsed.scheme}://{parsed.netloc}" in trusted
    return request.headers.get("sec-fetch-site", "none") in {"none", "same-origin"}


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

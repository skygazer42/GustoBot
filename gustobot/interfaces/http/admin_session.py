"""Single-administrator browser sessions for the knowledge management interface."""

import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from gustobot.config import settings

router = APIRouter(prefix="/admin", tags=["Administrator session"])
COOKIE_NAME = "gustobot_admin"
SESSION_SECONDS = 8 * 60 * 60
NO_STORE = {"Cache-Control": "no-store"}
AUDIENCE = "gustobot-admin"


class LoginRequest(BaseModel):
    """Administrator credentials accepted by the sign-in endpoint."""

    model_config = ConfigDict(extra="forbid")

    password: SecretStr = Field(min_length=1, max_length=256)


class SessionStatus(BaseModel):
    """Report whether administrator login is configured and active."""

    authenticated: bool
    configured: bool


def _session_key() -> bytes:
    """Derive a signing key from independently configured administrator secrets."""
    password = settings.GUSTOBOT_ADMIN_PASSWORD
    secret = settings.SECRET_KEY
    if password is None or not secret or len(secret.encode()) < 32:
        raise HTTPException(503, "Administrator login is not configured", headers=NO_STORE)
    password_bytes = password.get_secret_value().encode()
    if hmac.compare_digest(secret.encode(), password_bytes):
        raise HTTPException(503, "Administrator signing key must be independent", headers=NO_STORE)
    return hmac.digest(
        secret.encode(), b"gustobot-admin-session\0" + password_bytes, hashlib.sha256
    )


def _check_origin(request: Request) -> None:
    """Reject cross-origin browser requests before changing session state."""
    origin = request.headers.get("origin")
    if origin is not None and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Administrator requests must be same-origin", headers=NO_STORE)
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in {"same-origin", "none"}:
        raise HTTPException(403, "Administrator requests must be same-origin", headers=NO_STORE)


def _authenticated(request: Request, key: bytes) -> bool:
    """Validate the signed administrator cookie and its bounded lifetime."""
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        return False
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["HS256"],
            audience=AUDIENCE,
            issuer=AUDIENCE,
            options={"require_exp": True, "require_iat": True, "require_sub": True},
        )
        issued, expires = claims["iat"], claims["exp"]
        return (
            claims["sub"] == "administrator"
            and type(issued) is int
            and type(expires) is int
            and 0 < expires - issued <= SESSION_SECONDS
            and issued <= datetime.now(timezone.utc).timestamp()
        )
    except JWTError:
        return False


async def require_admin(request: Request, response: Response) -> None:
    """Enforce browser-session authentication when a password is configured."""
    if settings.GUSTOBOT_ADMIN_PASSWORD is None:
        return
    response.headers.update(NO_STORE)
    key = _session_key()
    _check_origin(request)
    if not _authenticated(request, key):
        raise HTTPException(401, "Administrator login is required", headers=NO_STORE)


@router.get("/session", response_model=SessionStatus)
async def read_session(request: Request, response: Response) -> SessionStatus:
    """Return the current login state without allowing caches to retain it."""
    response.headers.update(NO_STORE)
    configured = settings.GUSTOBOT_ADMIN_PASSWORD is not None
    if not configured:
        return SessionStatus(authenticated=False, configured=False)
    key = _session_key()
    _check_origin(request)
    return SessionStatus(authenticated=_authenticated(request, key), configured=True)


@router.post("/session", status_code=204)
async def sign_in(payload: LoginRequest, request: Request) -> Response:
    """Issue a strict, HTTP-only cookie after a constant-time password check."""
    key = _session_key()
    _check_origin(request)
    password = settings.GUSTOBOT_ADMIN_PASSWORD
    assert password is not None
    if not hmac.compare_digest(
        payload.password.get_secret_value().encode(), password.get_secret_value().encode()
    ):
        raise HTTPException(401, "Invalid administrator password", headers=NO_STORE)
    now = int(datetime.now(timezone.utc).timestamp())
    token = jwt.encode(
        {
            "sub": "administrator",
            "aud": AUDIENCE,
            "iss": AUDIENCE,
            "iat": now,
            "exp": now + SESSION_SECONDS,
        },
        key,
        algorithm="HS256",
    )
    response = Response(status_code=204, headers=NO_STORE)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path=settings.API_V1_PREFIX,
    )
    return response


@router.delete("/session", status_code=204)
async def sign_out(request: Request) -> Response:
    """Expire the administrator cookie after validating the request origin."""
    _check_origin(request)
    response = Response(status_code=204, headers=NO_STORE)
    response.delete_cookie(
        COOKIE_NAME,
        path=settings.API_V1_PREFIX,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
    )
    return response

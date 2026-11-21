from datetime import datetime, timedelta, timezone

from fastapi.security import OAuth2PasswordBearer
from jose import jwt

from gustobot.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


def create_access_token(data: dict, expires_delta: timedelta | None = None):
    """Sign a JWT payload with the configured key and optional expiry override."""
    if not settings.SECRET_KEY:
        raise ValueError("SECRET_KEY must be configured before signing access tokens")
    to_encode = data.copy()
    duration = timedelta(minutes=15) if expires_delta is None else expires_delta
    expire = datetime.now(timezone.utc) + duration
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

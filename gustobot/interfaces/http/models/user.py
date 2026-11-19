from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    """Shared fields for user payloads."""

    username: str
    email: EmailStr


class UserCreate(UserBase):
    """Payload for creating a new user."""

    password: str


class UserUpdate(BaseModel):
    """Payload for updating an existing user."""

    username: str | None = None
    email: EmailStr | None = None
    password: str | None = None
    status: str | None = None


class UserLogin(BaseModel):
    """Login request payload."""

    email: EmailStr
    password: str


class UserResponse(UserBase):
    """User model returned to clients."""

    id: int
    status: str
    created_at: datetime
    last_login: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    """Authentication token response."""

    access_token: str
    token_type: str = "bearer"

"""HTTP contracts for stored chat sessions, their messages, and snapshots."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatSessionBase(BaseModel):
    """Base schema for ChatSession."""

    title: str = Field(..., max_length=500, description="Session title")
    user_id: str | None = Field(
        None, max_length=255, description="User identifier (device ID, UUID, etc.)"
    )


class ChatSessionCreate(ChatSessionBase):
    """Schema for creating a new chat session."""

    id: str = Field(..., max_length=255, description="Session UUID")


class ChatSessionUpdate(BaseModel):
    """Schema for updating an existing chat session."""

    title: str | None = Field(None, max_length=500, description="Updated title")
    user_id: str | None = Field(None, max_length=255, description="Updated user ID")
    is_active: bool | None = Field(None, description="Active status")

    @field_validator("title", "is_active")
    @classmethod
    def _reject_null_stored_fields(cls, value):
        """Reject explicit nulls for fields that must remain stored values."""
        if value is None:
            raise ValueError("title and is_active cannot be null")
        return value


class SessionListQuery(BaseModel):
    """Filters and pagination bounds for a user's session list."""

    user_id: str | None = Field(default=None, max_length=255)
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1)
    active_only: bool = True


class ChatSessionResponse(ChatSessionBase):
    """Schema for chat session responses."""

    id: str
    created_at: datetime
    updated_at: datetime | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class ChatMessageBase(BaseModel):
    """Base schema for ChatMessage."""

    session_id: str = Field(..., max_length=255, description="Parent session UUID")
    message_type: str = Field(
        ...,
        max_length=50,
        description="Message type: user_query, agent_response, knowledge, error, etc.",
    )
    content: str = Field(..., description="Message content")
    message_metadata: dict[str, Any] | None = Field(None, description="Additional metadata")
    order_index: int = Field(..., description="Message order within session")


class ChatMessageCreate(ChatMessageBase):
    """Schema for creating a new chat message."""


class ChatMessageUpdate(BaseModel):
    """Schema for updating an existing chat message."""

    content: str | None = None
    message_metadata: dict[str, Any] | None = None


class ChatMessageResponse(ChatMessageBase):
    """Schema for chat message responses."""

    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionSnapshotBase(BaseModel):
    """Base schema for chat session snapshot."""

    session_id: str = Field(..., max_length=255, description="Parent session UUID")
    query: str = Field(..., description="Original user query")
    response_data: dict[str, Any] = Field(..., description="Complete response data")


class ChatSessionSnapshotCreate(ChatSessionSnapshotBase):
    """Schema for creating a new chat session snapshot."""


class ChatSessionSnapshotResponse(ChatSessionSnapshotBase):
    """Schema for chat session snapshot responses."""

    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserSessionCountResponse(BaseModel):
    """Number of stored sessions associated with one user identifier."""

    user_id: str
    session_count: int

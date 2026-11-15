"""
Pydantic schemas for chat session messages and snapshots.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChatMessageBase(BaseModel):
    """Base schema for ChatMessage."""

    session_id: str = Field(..., description="Parent session UUID")
    message_type: str = Field(
        ..., description="Message type: user_query, agent_response, knowledge, error, etc."
    )
    content: str = Field(..., description="Message content")
    message_metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    order_index: int = Field(..., description="Message order within session")


class ChatMessageCreate(ChatMessageBase):
    """Schema for creating a new chat message."""

    pass


class ChatMessageUpdate(BaseModel):
    """Schema for updating an existing chat message."""

    content: Optional[str] = None
    message_metadata: Optional[Dict[str, Any]] = None


class ChatMessageResponse(ChatMessageBase):
    """Schema for chat message responses."""

    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatSessionSnapshotBase(BaseModel):
    """Base schema for chat session snapshot."""

    session_id: str = Field(..., description="Parent session UUID")
    query: str = Field(..., description="Original user query")
    response_data: Dict[str, Any] = Field(..., description="Complete response data")


class ChatSessionSnapshotCreate(ChatSessionSnapshotBase):
    """Schema for creating a new chat session snapshot."""

    pass


class ChatSessionSnapshotResponse(ChatSessionSnapshotBase):
    """Schema for chat session snapshot responses."""

    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

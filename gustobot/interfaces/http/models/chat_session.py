"""
Pydantic schemas for ChatSession model.

Lightweight user ID system - no authentication required.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ChatSessionBase(BaseModel):
    """Base schema for ChatSession."""

    title: str = Field(..., description="Session title")
    user_id: Optional[str] = Field(None, description="User identifier (device ID, UUID, etc.)")


class ChatSessionCreate(ChatSessionBase):
    """Schema for creating a new chat session."""

    id: str = Field(..., description="Session UUID")


class ChatSessionUpdate(BaseModel):
    """Schema for updating an existing chat session."""

    title: Optional[str] = Field(None, description="Updated title")
    user_id: Optional[str] = Field(None, description="Updated user ID")
    is_active: Optional[bool] = Field(None, description="Active status")


class ChatSessionResponse(ChatSessionBase):
    """Schema for chat session responses."""

    id: str
    created_at: datetime
    updated_at: Optional[datetime]
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

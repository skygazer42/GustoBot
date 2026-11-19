"""
Pydantic schemas for chat history management.
Based on ChatDB implementation.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# Chat History Snapshot Schemas
class ConversationHistorySnapshotCreate(BaseModel):
    """Schema for creating a new conversation history snapshot."""

    conversation_id: int
    query: str
    response_data: dict[str, Any]


class ConversationHistorySnapshotResponse(BaseModel):
    """Schema for conversation history snapshot response."""

    id: int
    conversation_id: int
    query: str
    response_data: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Save Conversation History Request
class SaveConversationHistoryRequest(BaseModel):
    """Request payload for persisting conversation history."""

    conversation_id: int
    title: str
    query: str
    response: dict[str, Any]
    user_id: int | None = None


# Conversation History Response
class ConversationHistoryResponse(BaseModel):
    """Response containing a single conversation history entry."""

    id: int
    title: str
    timestamp: datetime
    query: str
    response: dict[str, Any]
    user_id: int | None = None

    model_config = ConfigDict(from_attributes=True)


# Conversation History List Response
class ConversationHistoryListResponse(BaseModel):
    """Response containing list of conversation histories."""

    sessions: list[ConversationHistoryResponse]
    total: int
    page: int
    page_size: int


# Restore Conversation History Response
class RestoreConversationHistoryResponse(BaseModel):
    """Response model for restoring conversation history."""

    conversation_id: int
    title: str
    query: str
    response: dict[str, Any]
    user_id: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

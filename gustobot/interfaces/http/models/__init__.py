"""
Pydantic request/response models used by the HTTP API layer.

This package consolidates what used to live under ``gustobot.schemas`` so that the
name makes their purpose (API-facing contracts) explicit.
"""

from .chat_history import (
    ConversationHistoryListResponse,
    ConversationHistoryResponse,
    ConversationHistorySnapshotCreate,
    ConversationHistorySnapshotResponse,
    RestoreConversationHistoryResponse,
    SaveConversationHistoryRequest,
)
from .session import (
    ChatMessageBase,
    ChatMessageCreate,
    ChatMessageResponse,
    ChatMessageUpdate,
    ChatSessionBase,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionSnapshotBase,
    ChatSessionSnapshotCreate,
    ChatSessionSnapshotResponse,
    ChatSessionUpdate,
)
from .user import Token, UserBase, UserCreate, UserLogin, UserResponse, UserUpdate

__all__ = [
    "ChatMessageBase",
    "ChatMessageCreate",
    "ChatMessageResponse",
    "ChatMessageUpdate",
    "ChatSessionBase",
    "ChatSessionCreate",
    "ChatSessionResponse",
    "ChatSessionSnapshotBase",
    "ChatSessionSnapshotCreate",
    "ChatSessionSnapshotResponse",
    "ChatSessionUpdate",
    "ConversationHistoryListResponse",
    "ConversationHistoryResponse",
    "ConversationHistorySnapshotCreate",
    "ConversationHistorySnapshotResponse",
    "RestoreConversationHistoryResponse",
    "SaveConversationHistoryRequest",
    "Token",
    "UserBase",
    "UserCreate",
    "UserLogin",
    "UserResponse",
    "UserUpdate",
]

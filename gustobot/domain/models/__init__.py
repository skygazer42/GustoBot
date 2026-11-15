"""
Legacy aggregate for application models.

This module now proxies to the new `gustobot.infrastructure.persistence.db.models` (SQLAlchemy) and
`gustobot.interfaces.http.models` (Pydantic) packages. Prefer importing from those packages
directly to make intent explicit.
"""

from warnings import warn

from gustobot.interfaces.http.models.chat import ChatRequest, ChatResponse
from gustobot.interfaces.http.models.chat_message import (
    ChatMessageBase,
    ChatMessageCreate,
    ChatMessageResponse,
    ChatMessageUpdate,
    ChatSessionSnapshotBase,
    ChatSessionSnapshotCreate,
    ChatSessionSnapshotResponse,
)
from gustobot.interfaces.http.models.chat_session import (
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionUpdate,
)
from gustobot.infrastructure.persistence.db.models import (
    ChatMessage,
    ChatSession,
    ChatSessionSnapshot,
    Conversation,
    ConversationHistorySnapshot,
    DialogueType,
    Message,
    User,
)

warn(
    "Importing from `gustobot.domain.models` is deprecated. "
    "Use `gustobot.infrastructure.persistence.db.models` for database entities and "
    "`gustobot.interfaces.http.models` for Pydantic schemas instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    # Pydantic schemas (legacy re-export)
    "ChatRequest",
    "ChatResponse",
    "ChatMessageBase",
    "ChatMessageCreate",
    "ChatMessageUpdate",
    "ChatMessageResponse",
    "ChatSessionSnapshotBase",
    "ChatSessionSnapshotCreate",
    "ChatSessionSnapshotResponse",
    "ChatSessionCreate",
    "ChatSessionUpdate",
    "ChatSessionResponse",
    # SQLAlchemy models
    "ChatMessage",
    "ChatSession",
    "ChatSessionSnapshot",
    "Conversation",
    "ConversationHistorySnapshot",
    "DialogueType",
    "Message",
    "User",
]

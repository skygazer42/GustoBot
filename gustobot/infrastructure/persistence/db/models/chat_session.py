"""
Chat session models for persistent conversation storage.

Lightweight user ID system - no authentication, just user identification.
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gustobot.infrastructure.core.database import Base

if TYPE_CHECKING:
    from .chat_message import ChatMessage, ChatSessionSnapshot


class ChatSession(Base):
    """
    Chat session model for persistent conversation storage.

    Uses lightweight user ID system:
    - user_id is a string (device ID, UUID, etc.) provided by frontend
    - No User table or authentication required
    - Allows grouping sessions by user without login
    """

    __tablename__ = "chat_sessions"

    # Primary key - using UUID string for session ID
    id: Mapped[str] = mapped_column(
        String(255), primary_key=True, index=True, comment="Session UUID"
    )

    # Lightweight user identification (no FK, just a string)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="User identifier (device ID, anonymous UUID, etc.) - no authentication",
    )

    # Session metadata
    title: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="Session title (usually derived from first query)"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Session creation timestamp",
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
        comment="Last update timestamp",
    )

    # Status flag for soft delete
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether the session is active (soft delete flag)",
    )

    # Relationships
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.order_index",
    )
    snapshots: Mapped[List["ChatSessionSnapshot"]] = relationship(
        "ChatSessionSnapshot",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatSessionSnapshot.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} user_id={self.user_id} title={self.title[:30]!r}>"

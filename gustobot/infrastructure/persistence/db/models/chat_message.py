"""
Chat message model for storing individual messages within a session.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gustobot.infrastructure.core.database import Base

if TYPE_CHECKING:
    from .chat_session import ChatSession


class ChatMessage(Base):
    """
    Chat message model for storing individual messages in a session.

    Stores structured message data including user queries, agent responses,
    SQL queries, visualizations, and other message types.
    """

    __tablename__ = "chat_messages"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Session relationship
    session_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent session ID",
    )

    # Message type classification
    message_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Message type: user_query, agent_response, knowledge, error, etc.",
    )

    # Message content
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Message content text")

    # Additional metadata (flexible JSON storage)
    message_metadata: Mapped[Optional[dict[str, object]]] = mapped_column(
        JSON, nullable=True, comment="Additional metadata: route info, confidence, sources, etc."
    )

    # Message ordering within session
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Message order within the session"
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Message creation timestamp",
    )

    # Relationships
    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} type={self.message_type} content={self.content[:50]!r}>"


class ChatSessionSnapshot(Base):
    """
    Session-level chat snapshot for quick restoration of conversation context.

    Stores a complete snapshot of a conversation turn (query + full response)
    for efficient retrieval and display in UI.
    """

    __tablename__ = "chat_history_snapshots"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Session relationship
    session_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent session ID",
    )

    # User query
    query: Mapped[str] = mapped_column(Text, nullable=False, comment="Original user query")

    # Complete response data
    response_data: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        comment="Complete response data including answer, metadata, sources, etc.",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Snapshot creation timestamp",
    )

    # Relationships
    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="snapshots")

    def __repr__(self) -> str:
        return f"<ChatSessionSnapshot id={self.id} query={self.query[:50]!r}>"

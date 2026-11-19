"""Persistent chat sessions, ordered messages, and restoration snapshots."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gustobot.infrastructure.core.database import Base


class ChatSession(Base):
    """A chat identified by a frontend UUID and an optional unauthenticated user ID."""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        String(255), primary_key=True, index=True, comment="Session UUID"
    )
    user_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="User identifier (device ID, anonymous UUID, etc.) - no authentication",
    )
    title: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="Session title (usually derived from first query)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Session creation timestamp",
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=True,
        comment="Last update timestamp",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether the session is active (soft delete flag)",
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.order_index",
    )
    snapshots: Mapped[list["ChatSessionSnapshot"]] = relationship(
        "ChatSessionSnapshot",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatSessionSnapshot.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} user_id={self.user_id} title={self.title[:30]!r}>"


class ChatMessage(Base):
    """An ordered message and its optional structured metadata within a chat session."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent session ID",
    )
    message_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Message type: user_query, agent_response, knowledge, error, etc.",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="Message content text")
    message_metadata: Mapped[dict[str, object] | None] = mapped_column(
        JSON, nullable=True, comment="Additional metadata: route info, confidence, sources, etc."
    )
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Message order within the session"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Message creation timestamp",
    )
    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} type={self.message_type} content={self.content[:50]!r}>"


class ChatSessionSnapshot(Base):
    """A query and complete response saved for restoring a chat session's context."""

    __tablename__ = "chat_history_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent session ID",
    )
    query: Mapped[str] = mapped_column(Text, nullable=False, comment="Original user query")
    response_data: Mapped[dict[str, object]] = mapped_column(
        JSON,
        nullable=False,
        comment="Complete response data including answer, metadata, sources, etc.",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Snapshot creation timestamp",
    )
    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="snapshots")

    def __repr__(self) -> str:
        return f"<ChatSessionSnapshot id={self.id} query={self.query[:50]!r}>"

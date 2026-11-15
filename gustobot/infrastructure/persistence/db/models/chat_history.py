"""
Chat history models - snapshot functionality for conversation persistence.
Based on ChatDB implementation with adaptations for GustoBot.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from gustobot.infrastructure.core.database import Base

if TYPE_CHECKING:
    from .conversation import Conversation


class ConversationHistorySnapshot(Base):
    """
    Chat history snapshot model for quick conversation restoration.

    Stores complete conversation state including query and full response data
    in JSON format for efficient retrieval and restoration.
    """

    __tablename__ = "conversation_history_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)  # User's original query
    response_data: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False
    )  # Complete response data
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, server_default=func.now()
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship("Conversation", backref="snapshots")

    def __repr__(self) -> str:
        return f"<ConversationHistorySnapshot id={self.id} conversation_id={self.conversation_id}>"

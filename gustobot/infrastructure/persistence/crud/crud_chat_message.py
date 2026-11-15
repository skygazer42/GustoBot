"""
CRUD operations for chat session messages and snapshots.
"""

from typing import List, NoReturn, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from gustobot.infrastructure.core.database import commit_session

from gustobot.infrastructure.persistence.crud.base import CRUDBase
from gustobot.infrastructure.persistence.db.models.chat_message import (
    ChatMessage,
    ChatSessionSnapshot,
)
from gustobot.interfaces.http.models.chat_message import (
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatSessionSnapshotCreate,
)


class CRUDChatMessage(CRUDBase[ChatMessage, ChatMessageCreate, ChatMessageUpdate]):
    """CRUD operations for ChatMessage model."""

    def get_by_session(
        self, db: Session, *, session_id: str, skip: int = 0, limit: int = 100
    ) -> List[ChatMessage]:
        """
        Get messages for a specific session, ordered by index.

        Args:
            db: Database session
            session_id: Parent session UUID
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List of messages ordered by order_index
        """
        return (
            db.query(self.model)
            .filter(self.model.session_id == session_id)
            .order_by(self.model.order_index)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_latest_by_session(self, db: Session, *, session_id: str) -> Optional[ChatMessage]:
        """
        Get the most recent message in a session.

        Args:
            db: Database session
            session_id: Parent session UUID

        Returns:
            Latest message or None
        """
        return (
            db.query(self.model)
            .filter(self.model.session_id == session_id)
            .order_by(desc(self.model.order_index))
            .first()
        )

    def create_batch(self, db: Session, *, messages: List[ChatMessageCreate]) -> List[ChatMessage]:
        """
        Create multiple messages in a single transaction.

        Args:
            db: Database session
            messages: List of message creation data

        Returns:
            List of created message instances
        """
        db_messages = []
        for message_data in messages:
            db_message = self.model(**message_data.model_dump())
            db.add(db_message)
            db_messages.append(db_message)

        commit_session(db)
        for db_message in db_messages:
            db.refresh(db_message)
        return db_messages

    def delete_by_session(self, db: Session, *, session_id: str) -> int:
        """
        Delete all messages for a specific session.

        Returns:
            Number of rows deleted.
        """
        deleted = (
            db.query(self.model)
            .filter(self.model.session_id == session_id)
            .delete(synchronize_session=False)
        )
        commit_session(db)
        return deleted


class CRUDChatSessionSnapshot(CRUDBase[ChatSessionSnapshot, ChatSessionSnapshotCreate, NoReturn]):
    """Snapshot operations; updates accept field mappings, with no update schema."""

    def get_by_session(self, db: Session, *, session_id: str) -> List[ChatSessionSnapshot]:
        """
        Get all snapshots for a session, ordered by creation time (newest first).

        Args:
            db: Database session
            session_id: Parent session UUID

        Returns:
            List of snapshots
        """
        return (
            db.query(self.model)
            .filter(self.model.session_id == session_id)
            .order_by(desc(self.model.created_at))
            .all()
        )

    def get_latest_by_session(
        self, db: Session, *, session_id: str
    ) -> Optional[ChatSessionSnapshot]:
        """
        Get the most recent snapshot for a session.

        Args:
            db: Database session
            session_id: Parent session UUID

        Returns:
            Latest snapshot or None
        """
        return (
            db.query(self.model)
            .filter(self.model.session_id == session_id)
            .order_by(desc(self.model.created_at))
            .first()
        )


# Create singleton instances
chat_message = CRUDChatMessage(ChatMessage)
chat_session_snapshot = CRUDChatSessionSnapshot(ChatSessionSnapshot)

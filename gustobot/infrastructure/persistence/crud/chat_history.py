"""
CRUD operations for conversation-level history snapshots.
"""

from sqlalchemy.orm import Session

from gustobot.infrastructure.core.database import commit_session
from gustobot.infrastructure.persistence.db.models.chat_history import (
    ConversationHistorySnapshot,
)
from gustobot.interfaces.http.models.chat_history import (
    ConversationHistorySnapshotCreate,
)


class ConversationHistoryCRUD:
    """CRUD operations for ConversationHistorySnapshot model."""

    def create(
        self,
        db: Session,
        *,
        obj_in: ConversationHistorySnapshotCreate,
    ) -> ConversationHistorySnapshot:
        """Create a new chat history snapshot."""
        snapshot = ConversationHistorySnapshot(
            conversation_id=obj_in.conversation_id,
            query=obj_in.query,
            response_data=obj_in.response_data,
        )
        db.add(snapshot)
        commit_session(db)
        db.refresh(snapshot)
        return snapshot

    def get(self, db: Session, *, id: int) -> ConversationHistorySnapshot | None:
        """Get a chat history snapshot by ID."""
        return (
            db.query(ConversationHistorySnapshot)
            .filter(ConversationHistorySnapshot.id == id)
            .first()
        )

    def get_by_conversation(
        self, db: Session, *, conversation_id: int, skip: int = 0, limit: int = 100
    ) -> list[ConversationHistorySnapshot]:
        """Get all snapshots for a conversation."""
        return (
            db.query(ConversationHistorySnapshot)
            .filter(ConversationHistorySnapshot.conversation_id == conversation_id)
            .order_by(ConversationHistorySnapshot.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_latest_by_conversation(
        self, db: Session, *, conversation_id: int
    ) -> ConversationHistorySnapshot | None:
        """Get the latest snapshot for a conversation."""
        return (
            db.query(ConversationHistorySnapshot)
            .filter(ConversationHistorySnapshot.conversation_id == conversation_id)
            .order_by(ConversationHistorySnapshot.created_at.desc())
            .first()
        )

    def delete(self, db: Session, *, id: int) -> ConversationHistorySnapshot | None:
        """Delete a chat history snapshot."""
        snapshot = self.get(db, id=id)
        if snapshot is None:
            return None
        db.delete(snapshot)
        commit_session(db)
        return snapshot


# Singleton instance
conversation_history_crud = ConversationHistoryCRUD()

"""Persistence operations for chat sessions, their messages, and snapshots."""

from datetime import datetime, timezone
from typing import NoReturn

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session, selectinload

from gustobot.infrastructure.core.database import commit_session
from gustobot.infrastructure.persistence.crud.base import CRUDBase
from gustobot.infrastructure.persistence.db.models.chat import (
    ChatMessage,
    ChatSession,
    ChatSessionSnapshot,
)
from gustobot.interfaces.http.models.session import (
    ChatMessageCreate,
    ChatMessageUpdate,
    ChatSessionCreate,
    ChatSessionSnapshotCreate,
    ChatSessionUpdate,
)


class CRUDChatSession(CRUDBase[ChatSession, ChatSessionCreate, ChatSessionUpdate]):
    """Read and update sessions with lightweight user identification."""

    def get_all(
        self, db: Session, *, skip: int = 0, limit: int = 100, active_only: bool = True
    ) -> list[ChatSession]:
        """List sessions across users, most recently updated first."""
        query = db.query(self.model)
        if active_only:
            query = query.filter(self.model.is_active.is_(True))
        return query.order_by(desc(self.model.updated_at)).offset(skip).limit(limit).all()

    def get_by_user(
        self,
        db: Session,
        *,
        user_id: str,
        skip: int = 0,
        limit: int = 100,
        active_only: bool = True,
    ) -> list[ChatSession]:
        """List a user's sessions, most recently updated first."""
        query = db.query(self.model).filter(self.model.user_id == user_id)
        if active_only:
            query = query.filter(self.model.is_active.is_(True))
        return query.order_by(desc(self.model.updated_at)).offset(skip).limit(limit).all()

    def get_with_messages(self, db: Session, *, session_id: str) -> ChatSession | None:
        """Load an active session and its messages before the database session closes."""
        return (
            db.query(self.model)
            .options(selectinload(self.model.messages))
            .filter(and_(self.model.id == session_id, self.model.is_active.is_(True)))
            .first()
        )

    def update_activity(self, db: Session, *, session_id: str) -> ChatSession | None:
        """Update the last activity timestamp, or return None when the session is missing."""
        session = db.query(self.model).filter(self.model.id == session_id).first()
        if session is None:
            return None
        session.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        commit_session(db)
        db.refresh(session)
        return session

    def soft_delete(self, db: Session, *, session_id: str) -> ChatSession | None:
        """Mark a session inactive, or return None when it is missing."""
        session = db.query(self.model).filter(self.model.id == session_id).first()
        if session is None:
            return None
        session.is_active = False
        commit_session(db)
        db.refresh(session)
        return session

    def restore(self, db: Session, *, session_id: str) -> ChatSession | None:
        """Reactivate a session, or return None when it is missing."""
        session = db.query(self.model).filter(self.model.id == session_id).first()
        if session is None:
            return None
        session.is_active = True
        commit_session(db)
        db.refresh(session)
        return session

    def count_by_user(self, db: Session, *, user_id: str) -> int:
        """Count a user's sessions, including inactive sessions."""
        return db.query(self.model).filter(self.model.user_id == user_id).count()


class CRUDChatMessage(CRUDBase[ChatMessage, ChatMessageCreate, ChatMessageUpdate]):
    """Read and write the ordered messages belonging to a chat session."""

    def get_by_session(
        self, db: Session, *, session_id: str, skip: int = 0, limit: int = 100
    ) -> list[ChatMessage]:
        """List a session's messages in ascending order_index."""
        return (
            db.query(self.model)
            .filter(self.model.session_id == session_id)
            .order_by(self.model.order_index)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_latest_by_session(self, db: Session, *, session_id: str) -> ChatMessage | None:
        """Return the session's message with the highest order_index, or None."""
        return (
            db.query(self.model)
            .filter(self.model.session_id == session_id)
            .order_by(desc(self.model.order_index))
            .first()
        )

    def create_batch(self, db: Session, *, messages: list[ChatMessageCreate]) -> list[ChatMessage]:
        """Create the messages in one transaction and return the refreshed records."""
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
        """Delete the session's messages and return the number of rows deleted."""
        deleted = (
            db.query(self.model)
            .filter(self.model.session_id == session_id)
            .delete(synchronize_session=False)
        )
        commit_session(db)
        return deleted


class CRUDChatSessionSnapshot(CRUDBase[ChatSessionSnapshot, ChatSessionSnapshotCreate, NoReturn]):
    """Snapshot operations; updates accept field mappings, with no update schema."""

    def get_by_session(self, db: Session, *, session_id: str) -> list[ChatSessionSnapshot]:
        """List the session's snapshots, newest first."""
        return (
            db.query(self.model)
            .filter(self.model.session_id == session_id)
            .order_by(desc(self.model.created_at))
            .all()
        )

    def get_latest_by_session(self, db: Session, *, session_id: str) -> ChatSessionSnapshot | None:
        """Return the session's newest snapshot, or None."""
        return (
            db.query(self.model)
            .filter(self.model.session_id == session_id)
            .order_by(desc(self.model.created_at))
            .first()
        )


chat_session = CRUDChatSession(ChatSession)
chat_message = CRUDChatMessage(ChatMessage)
chat_session_snapshot = CRUDChatSessionSnapshot(ChatSessionSnapshot)

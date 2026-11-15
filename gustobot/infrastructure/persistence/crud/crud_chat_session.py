"""
CRUD operations for ChatSession model.

Lightweight user ID system - group sessions by user_id without authentication.
"""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session, selectinload

from gustobot.infrastructure.core.database import commit_session

from gustobot.infrastructure.persistence.crud.base import CRUDBase
from gustobot.infrastructure.persistence.db.models.chat_session import ChatSession
from gustobot.interfaces.http.models.chat_session import ChatSessionCreate, ChatSessionUpdate


class CRUDChatSession(CRUDBase[ChatSession, ChatSessionCreate, ChatSessionUpdate]):
    """CRUD operations for ChatSession model."""

    def get_all(
        self, db: Session, *, skip: int = 0, limit: int = 100, active_only: bool = True
    ) -> List[ChatSession]:
        """
        Get all chat sessions (across all users).

        Args:
            db: Database session
            skip: Number of records to skip
            limit: Maximum number of records to return
            active_only: Only return active (non-deleted) sessions

        Returns:
            List of chat sessions
        """
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
    ) -> List[ChatSession]:
        """
        Get chat sessions for a specific user.

        Args:
            db: Database session
            user_id: User identifier (device ID, UUID, etc.)
            skip: Number of records to skip
            limit: Maximum number of records to return
            active_only: Only return active (non-deleted) sessions

        Returns:
            List of chat sessions for the user
        """
        query = db.query(self.model).filter(self.model.user_id == user_id)

        if active_only:
            query = query.filter(self.model.is_active.is_(True))

        return query.order_by(desc(self.model.updated_at)).offset(skip).limit(limit).all()

    def get_with_messages(self, db: Session, *, session_id: str) -> Optional[ChatSession]:
        """
        Get a chat session with its messages loaded.

        Args:
            db: Database session
            session_id: Session UUID

        Returns:
            ChatSession with messages relationship loaded, or None
        """
        return (
            db.query(self.model)
            .options(selectinload(self.model.messages))
            .filter(and_(self.model.id == session_id, self.model.is_active.is_(True)))
            .first()
        )

    def update_activity(self, db: Session, *, session_id: str) -> Optional[ChatSession]:
        """
        Update the session's last activity timestamp.

        Args:
            db: Database session
            session_id: Session UUID

        Returns:
            Updated session or None if not found
        """
        session = db.query(self.model).filter(self.model.id == session_id).first()
        if session is None:
            return None
        session.updated_at = datetime.utcnow()
        commit_session(db)
        db.refresh(session)
        return session

    def soft_delete(self, db: Session, *, session_id: str) -> Optional[ChatSession]:
        """
        Soft delete a session (mark as inactive).

        Args:
            db: Database session
            session_id: Session UUID

        Returns:
            Deleted session or None if not found
        """
        session = db.query(self.model).filter(self.model.id == session_id).first()
        if session is None:
            return None
        session.is_active = False
        commit_session(db)
        db.refresh(session)
        return session

    def restore(self, db: Session, *, session_id: str) -> Optional[ChatSession]:
        """
        Restore a soft-deleted session.

        Args:
            db: Database session
            session_id: Session UUID

        Returns:
            Restored session or None if not found
        """
        session = db.query(self.model).filter(self.model.id == session_id).first()
        if session is None:
            return None
        session.is_active = True
        commit_session(db)
        db.refresh(session)
        return session

    def count_by_user(self, db: Session, *, user_id: str) -> int:
        """
        Count total sessions for a user.

        Args:
            db: Database session
            user_id: User identifier

        Returns:
            Number of sessions
        """
        return db.query(self.model).filter(self.model.user_id == user_id).count()


# Create singleton instance
chat_session = CRUDChatSession(ChatSession)

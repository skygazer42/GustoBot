"""
CRUD operations for conversations.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from gustobot.infrastructure.core.database import commit_session
from gustobot.infrastructure.persistence.db.models.conversation import (
    Conversation,
    DialogueType,
)


class ConversationCRUD:
    """CRUD operations for Conversation model."""

    def create(
        self,
        db: Session,
        *,
        user_id: int,
        title: str,
        dialogue_type: DialogueType = DialogueType.RAG,
    ) -> Conversation:
        """Create a new conversation."""
        conversation = Conversation(
            user_id=user_id,
            title=title,
            dialogue_type=dialogue_type,
            status="ongoing",
        )
        db.add(conversation)
        commit_session(db)
        db.refresh(conversation)
        return conversation

    def get(self, db: Session, *, id: int) -> Conversation | None:
        """Get a conversation by ID."""
        return db.query(Conversation).filter(Conversation.id == id).first()

    def get_by_user(
        self, db: Session, *, user_id: int, skip: int = 0, limit: int = 100
    ) -> list[Conversation]:
        """Get all conversations for a user."""
        return (
            db.query(Conversation)
            .filter(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def update(self, db: Session, *, db_obj: Conversation, obj_in: dict) -> Conversation:
        """Update a conversation."""
        for field, value in obj_in.items():
            setattr(db_obj, field, value)
        db.add(db_obj)
        commit_session(db)
        db.refresh(db_obj)
        return db_obj

    def update_activity(self, db: Session, *, conversation_id: int) -> Conversation | None:
        """Update conversation activity timestamp."""
        conversation = self.get(db, id=conversation_id)
        if conversation is None:
            return None
        conversation.updated_at = func.now()
        commit_session(db)
        db.refresh(conversation)
        return conversation

    def delete(self, db: Session, *, id: int) -> Conversation | None:
        """Delete a conversation (soft delete by changing status)."""
        conversation = self.get(db, id=id)
        if conversation is None:
            return None
        conversation.status = "deleted"
        db.add(conversation)
        commit_session(db)
        db.refresh(conversation)
        return conversation


# Singleton instance
conversation_crud = ConversationCRUD()

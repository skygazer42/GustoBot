"""Read-only administrator inspection of persisted conversations and messages."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.orm import Session

from gustobot.infrastructure.core.database import get_db
from gustobot.infrastructure.persistence.db.models import ChatMessage, ChatSession
from gustobot.interfaces.http.admin_session import NO_STORE, require_admin
from gustobot.interfaces.http.models.session import ChatMessageResponse

router = APIRouter(
    prefix="/admin/conversations",
    tags=["Administrator conversations"],
    dependencies=[Depends(require_admin)],
)
DatabaseSession = Annotated[Session, Depends(get_db)]


class ConversationListQuery(BaseModel):
    """Literal search, activity state, and bounded session pagination."""

    q: str = Field(default="", max_length=200)
    state: Literal["all", "active", "deleted"] = "all"
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)


class MessageListQuery(BaseModel):
    """Bounds for reading a chronological page of one conversation."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)


class ConversationSummary(BaseModel):
    """Session identity and compact evidence needed to choose a conversation."""

    id: str
    title: str
    user_id: str | None
    created_at: datetime
    updated_at: datetime | None
    is_active: bool
    message_count: int
    last_message_preview: str | None


class ConversationPage(BaseModel):
    """A filtered session page with its matching total."""

    items: list[ConversationSummary]
    total: int
    offset: int
    limit: int


class ConversationMessages(BaseModel):
    """Full stored messages and the session to which they belong."""

    session: ConversationSummary
    items: list[ChatMessageResponse]
    total: int
    offset: int
    limit: int


def _summary_statement() -> Select:
    """Read counts and latest previews without loading every session's messages."""
    message_count = (
        select(func.count(ChatMessage.id))
        .where(ChatMessage.session_id == ChatSession.id)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    latest_preview = (
        select(func.substr(ChatMessage.content, 1, 160))
        .where(ChatMessage.session_id == ChatSession.id)
        .order_by(ChatMessage.order_index.desc(), ChatMessage.id.desc())
        .limit(1)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    return select(ChatSession, message_count, latest_preview)


def _summary(
    session: ChatSession, message_count: int, last_message_preview: str | None
) -> ConversationSummary:
    """Expose only the stored identity and bounded list evidence."""
    return ConversationSummary(
        id=session.id,
        title=session.title,
        user_id=session.user_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        is_active=session.is_active,
        message_count=message_count,
        last_message_preview=last_message_preview,
    )


@router.get("", response_model=ConversationPage)
def list_conversations(
    query: Annotated[ConversationListQuery, Depends()], response: Response, db: DatabaseSession
) -> ConversationPage:
    """Find conversations by their title, user identifier, or stored message text."""
    response.headers.update(NO_STORE)
    conditions: list[ColumnElement[bool]] = []
    if query.state != "all":
        conditions.append(ChatSession.is_active.is_(query.state == "active"))
    search = query.q.strip()
    if search:
        matching_message = (
            select(ChatMessage.id)
            .where(
                ChatMessage.session_id == ChatSession.id,
                ChatMessage.content.contains(search, autoescape=True),
            )
            .exists()
        )
        conditions.append(
            or_(
                ChatSession.title.contains(search, autoescape=True),
                ChatSession.user_id.contains(search, autoescape=True),
                matching_message,
            )
        )
    total = db.execute(
        select(func.count()).select_from(ChatSession).where(*conditions)
    ).scalar_one()
    statement = (
        _summary_statement()
        .where(*conditions)
        .order_by(
            func.coalesce(ChatSession.updated_at, ChatSession.created_at).desc(),
            ChatSession.id.desc(),
        )
        .offset(query.offset)
        .limit(query.limit)
    )
    items = [_summary(session, count, preview) for session, count, preview in db.execute(statement)]
    return ConversationPage(items=items, total=total, offset=query.offset, limit=query.limit)


@router.get("/{session_id}/messages", response_model=ConversationMessages)
def read_conversation_messages(
    session_id: str,
    query: Annotated[MessageListQuery, Depends()],
    response: Response,
    db: DatabaseSession,
) -> ConversationMessages:
    """Read full messages in a stable order without modifying the session."""
    response.headers.update(NO_STORE)
    row = db.execute(_summary_statement().where(ChatSession.id == session_id)).one_or_none()
    if row is None:
        raise HTTPException(404, "Conversation not found", headers=NO_STORE)
    summary = _summary(*row)
    messages = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.order_index, ChatMessage.id)
        .offset(query.offset)
        .limit(query.limit)
    )
    return ConversationMessages(
        session=summary,
        items=[ChatMessageResponse.model_validate(message) for message in messages],
        total=summary.message_count,
        offset=query.offset,
        limit=query.limit,
    )

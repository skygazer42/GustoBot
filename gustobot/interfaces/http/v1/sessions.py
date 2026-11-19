"""
Chat session management API endpoints.

Lightweight user ID system - group sessions by user_id without authentication.
"""

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from gustobot.infrastructure.core.database import get_db
from gustobot.infrastructure.persistence.crud.chat import (
    chat_message,
    chat_session,
    chat_session_snapshot,
)
from gustobot.interfaces.http.models.session import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionSnapshotCreate,
    ChatSessionSnapshotResponse,
    ChatSessionUpdate,
    SessionListQuery,
    UserSessionCountResponse,
)

DatabaseSession = Annotated[Session, Depends(get_db)]

router = APIRouter()


@router.get("/", response_model=list[ChatSessionResponse])
def get_sessions(
    query: Annotated[SessionListQuery, Depends()],
    *,
    db: DatabaseSession,
) -> Any:
    """
    Get list of chat sessions.

    - If user_id is provided: Get sessions for that specific user
    - If user_id is None: Get all sessions (across all users)

    No authentication required.
    """
    if query.user_id is not None:
        # Get sessions for specific user
        sessions = chat_session.get_by_user(
            db,
            user_id=query.user_id,
            skip=query.skip,
            limit=query.limit,
            active_only=query.active_only,
        )
    else:
        # Get all sessions
        sessions = chat_session.get_all(
            db, skip=query.skip, limit=query.limit, active_only=query.active_only
        )

    return sessions


@router.post("/", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    *,
    db: DatabaseSession,
    session_in: ChatSessionCreate,
) -> Any:
    """
    Create a new chat session.

    Frontend should provide:
    - id: Session UUID
    - user_id: User identifier (device ID, UUID, etc.) - optional
    - title: Session title
    """
    session = chat_session.create(db, obj_in=session_in)
    return session


@router.get("/{session_id}", response_model=ChatSessionResponse)
def get_session(
    *,
    db: DatabaseSession,
    session_id: str,
) -> Any:
    """
    Get a specific chat session by ID.
    """
    session = chat_session.get(db, id=session_id)

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    return session


@router.patch("/{session_id}", response_model=ChatSessionResponse)
def update_session(
    *,
    db: DatabaseSession,
    session_id: str,
    session_update: ChatSessionUpdate,
) -> Any:
    """
    Update a chat session.

    Can update: title, user_id, is_active
    """
    session = chat_session.get(db, id=session_id)

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    session = chat_session.update(db, db_obj=session, obj_in=session_update)
    return session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    *,
    db: DatabaseSession,
    session_id: str,
) -> None:
    """
    Soft delete a chat session.
    """
    session = chat_session.get(db, id=session_id)

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    chat_session.soft_delete(db, session_id=session_id)


@router.post(
    "/{session_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_message_to_session(
    *,
    db: DatabaseSession,
    session_id: str,
    message_in: ChatMessageCreate,
) -> Any:
    """
    Add a message to a chat session.
    """
    session = chat_session.get(db, id=session_id)

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Ensure session_id matches
    message_in.session_id = session_id

    session.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    message = chat_message.create(db, obj_in=message_in)
    return message


@router.post(
    "/{session_id}/snapshot",
    response_model=ChatSessionSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session_snapshot(
    *,
    db: DatabaseSession,
    session_id: str,
    snapshot_in: ChatSessionSnapshotCreate,
) -> Any:
    """
    Create a snapshot of a conversation turn for quick restoration.
    """
    session = chat_session.get(db, id=session_id)

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Ensure session_id matches
    snapshot_in.session_id = session_id

    # Create snapshot
    snapshot = chat_session_snapshot.create(db, obj_in=snapshot_in)

    return snapshot


@router.get("/user/{user_id}/count", response_model=UserSessionCountResponse)
def get_user_session_count(
    *,
    db: DatabaseSession,
    user_id: str,
) -> Any:
    """
    Get the total number of sessions for a user.

    Useful for analytics and user interface.
    """
    count = chat_session.count_by_user(db, user_id=user_id)

    return {"user_id": user_id, "session_count": count}

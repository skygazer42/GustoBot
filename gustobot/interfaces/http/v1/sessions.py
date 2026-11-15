"""
Chat session management API endpoints.

Lightweight user ID system - group sessions by user_id without authentication.
"""

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from gustobot.infrastructure.core.database import get_db
from gustobot.infrastructure.persistence.crud import (
    chat_message,
    chat_session,
    chat_session_snapshot,
)
from gustobot.interfaces.http.models.chat_message import (
    ChatMessageCreate,
    ChatMessageResponse,
    ChatSessionSnapshotCreate,
    ChatSessionSnapshotResponse,
)
from gustobot.interfaces.http.models.chat_session import (
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionUpdate,
)

router = APIRouter()


class UserSessionCountResponse(BaseModel):
    user_id: str
    session_count: int


@router.get("/", response_model=List[ChatSessionResponse])
def get_sessions(
    *,
    db: Session = Depends(get_db),
    user_id: Optional[str] = Query(None, description="Filter by user ID (device ID, UUID, etc.)"),
    skip: int = 0,
    limit: int = 50,
    active_only: bool = True,
) -> Any:
    """
    Get list of chat sessions.

    - If user_id is provided: Get sessions for that specific user
    - If user_id is None: Get all sessions (across all users)

    No authentication required.
    """
    if user_id is not None:
        # Get sessions for specific user
        sessions = chat_session.get_by_user(
            db, user_id=user_id, skip=skip, limit=limit, active_only=active_only
        )
    else:
        # Get all sessions
        sessions = chat_session.get_all(db, skip=skip, limit=limit, active_only=active_only)

    return sessions


@router.post("/", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    *,
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
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

    # Create message
    message = chat_message.create(db, obj_in=message_in)

    # Update session activity
    chat_session.update_activity(db, session_id=session_id)

    return message


@router.post(
    "/{session_id}/snapshot",
    response_model=ChatSessionSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session_snapshot(
    *,
    db: Session = Depends(get_db),
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
    db: Session = Depends(get_db),
    user_id: str,
) -> Any:
    """
    Get the total number of sessions for a user.

    Useful for analytics and user interface.
    """
    count = chat_session.count_by_user(db, user_id=user_id)

    return {"user_id": user_id, "session_count": count}

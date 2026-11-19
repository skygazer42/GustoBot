"""Database failures remain visible and leave sessions usable."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gustobot.infrastructure.core import database
from gustobot.infrastructure.persistence.crud.chat import (
    chat_session,
    chat_session_snapshot,
)
from gustobot.infrastructure.persistence.crud.conversation import conversation_crud
from gustobot.infrastructure.persistence.db.models import (
    ChatMessage,
    ChatSessionSnapshot,
    Conversation,
    DialogueType,
)
from gustobot.interfaces.http.models.session import (
    ChatSessionCreate,
    ChatSessionSnapshotCreate,
    ChatSessionUpdate,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://")
    try:
        database.Base.metadata.create_all(engine)
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


def test_failed_crud_commit_rolls_back_and_session_can_be_reused(db_session):
    first = ChatSessionCreate(id="same", title="first", user_id=None)
    chat_session.create(db_session, obj_in=first)

    with pytest.raises(IntegrityError):
        chat_session.create(db_session, obj_in=first)

    assert not db_session.in_transaction()
    second = chat_session.create(
        db_session, obj_in=ChatSessionCreate(id="second", title="second", user_id=None)
    )
    assert chat_session.get(db_session, "second") is second


def test_partial_updates_preserve_explicit_empty_values_and_unset_fields(db_session):
    session = chat_session.create(
        db_session, obj_in=ChatSessionCreate(id="updates", title="original", user_id="owner")
    )
    chat_session.update(
        db_session, db_obj=session, obj_in=ChatSessionUpdate(title="", is_active=False)
    )
    db_session.expire_all()
    assert session.title == ""
    assert session.is_active is False
    assert session.user_id == "owner"

    snapshot = chat_session_snapshot.create(
        db_session,
        obj_in=ChatSessionSnapshotCreate(
            session_id=session.id, query="original", response_data={"count": 1}
        ),
    )
    chat_session_snapshot.update(
        db_session,
        db_obj=snapshot,
        obj_in={"query": "", "response_data": {"count": 0, "sources": []}},
    )
    db_session.expire_all()
    assert snapshot.session_id == "updates"
    assert snapshot.query == ""
    assert snapshot.response_data == {"count": 0, "sources": []}


@pytest.mark.parametrize("as_mapping", [False, True])
def test_partial_updates_persist_when_the_orm_instance_is_expired(db_session, as_mapping):
    session = chat_session.create(
        db_session,
        obj_in=ChatSessionCreate(id="expired", title="original", user_id="owner"),
    )
    db_session.expire(session)
    update = ChatSessionUpdate(title="updated", is_active=False)
    updates = update.model_dump(exclude_unset=True) if as_mapping else update

    chat_session.update(db_session, db_obj=session, obj_in=updates)
    db_session.expire_all()

    assert session.title == "updated"
    assert session.is_active is False
    assert session.user_id == "owner"


@pytest.mark.parametrize("close_fails", [False, True])
def test_session_scope_preserves_original_error_when_rollback_fails(monkeypatch, close_fails):
    session = Session()
    original = RuntimeError("operation failed")
    cleanup = []

    def failing_rollback():
        cleanup.append("rollback")
        raise RuntimeError("rollback failed")

    def close():
        cleanup.append("close")
        if close_fails:
            raise RuntimeError("close failed")

    monkeypatch.setattr(database, "SessionLocal", lambda: session)
    monkeypatch.setattr(session, "rollback", failing_rollback)
    monkeypatch.setattr(session, "close", close)

    with (
        pytest.raises(RuntimeError, match="operation failed") as failure,
        database.session_scope(),
    ):
        raise original

    assert failure.value is original
    assert cleanup == ["rollback", "close"]


def test_session_relationships_and_json_values_round_trip(db_session):
    parent = chat_session.create(
        db_session, obj_in=ChatSessionCreate(id="roundtrip", title="recipe", user_id=None)
    )
    parent.messages.append(
        ChatMessage(message_type="user_query", content="", order_index=0, message_metadata=None)
    )
    parent.snapshots.append(
        ChatSessionSnapshot(query="", response_data={"answer": "", "sources": [], "count": 0})
    )
    db_session.commit()
    db_session.expire_all()

    loaded = chat_session.get(db_session, "roundtrip")
    assert loaded is not None
    assert loaded.user_id is None
    assert loaded.messages[0].content == ""
    assert loaded.messages[0].order_index == 0
    assert loaded.messages[0].message_metadata is None
    assert loaded.snapshots[0].response_data == {"answer": "", "sources": [], "count": 0}


def test_get_with_messages_loads_messages_before_the_database_session_closes(db_session):
    session = chat_session.create(
        db_session, obj_in=ChatSessionCreate(id="loaded", title="recipe", user_id=None)
    )
    session.messages.append(
        ChatMessage(message_type="user_query", content="recipe question", order_index=0)
    )
    db_session.commit()
    db_session.expunge_all()

    loaded = chat_session.get_with_messages(db_session, session_id="loaded")
    assert loaded is not None
    db_session.expunge_all()
    assert [message.content for message in loaded.messages] == ["recipe question"]


def test_conversation_activity_persists_a_new_timestamp(db_session):
    earlier = datetime(2000, 1, 1)
    conversation = Conversation(title="recipe", dialogue_type=DialogueType.RAG, updated_at=earlier)
    db_session.add(conversation)
    db_session.commit()

    updated = conversation_crud.update_activity(db_session, conversation_id=conversation.id)
    assert updated is not None
    db_session.expire_all()
    assert updated.updated_at is not None
    assert updated.updated_at > earlier

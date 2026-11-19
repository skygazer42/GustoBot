"""Publication switches are transactional, scoped and protected against stale writers."""

import importlib
import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, inspect, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gustobot.domain.linking import IndexScope
from gustobot.infrastructure.core.database import (
    Base,
    create_database_engine,
    migrate_database,
)
from gustobot.infrastructure.persistence.crud.semantic_index import (
    BuildLeaseConflict,
    PublicationConflict,
)
from gustobot.infrastructure.persistence.db.models.semantic_index import (
    SemanticIndexGeneration,
    SemanticIndexPublication,
)


def repository(session):
    name = "gustobot.infrastructure.persistence.crud.semantic_index"
    assert importlib.util.find_spec(name) is not None, "Semantic publication repository is missing"
    return importlib.import_module(name).SemanticIndexRepository(session)


def scope(kind="entity", **changes):
    return IndexScope(
        domain_id="recipes",
        ontology_version="v1",
        ontology_fingerprint="a" * 64,
        embedding_fingerprint="b" * 64,
        kind=kind,
        **changes,
    )


@pytest.fixture
def database(request):
    engine = create_engine("sqlite://")
    request.addfinalizer(engine.dispose)
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    with Session(engine) as session:
        repository(session)
    Base.metadata.create_all(engine)
    yield engine


def ready(repo, identifier, revision=1, *, selected_scope=None):
    repo.create_generation(
        scope() if selected_scope is None else selected_scope,
        generation_id=identifier,
        graph_revision=revision,
    )
    return repo.mark_ready(identifier, expected_count=0, written_count=0, checksum="c" * 64)


def test_generation_and_pointer_changes_remain_owned_by_caller_transaction(database):
    with Session(database) as session:
        repo = repository(session)
        ready(repo, "first")
        repo.publish("first", expected_active_generation=None)
        session.rollback()
        assert repo.get_generation("first") is None
        assert repo.publication_status(scope()).generation_id is None


def test_switch_retires_old_generation_and_failed_build_keeps_active(database):
    with Session(database) as session:
        repo = repository(session)
        ready(repo, "first")
        repo.publish("first", expected_active_generation=None)
        session.commit()
        repo.create_generation(scope(), generation_id="broken", graph_revision=2)
        repo.update_outcome("broken", status="failed", error="write failed")
        session.commit()
        assert repo.publication_status(scope()).generation_id == "first"
        ready(repo, "second", revision=2)
        repo.publish("second", expected_active_generation="first")
        assert repo.get_generation("first").status == "retired"
        session.rollback()
        assert repo.get_generation("first").status == "active"
        assert repo.publication_status(scope()).generation_id == "first"


def test_competing_publishers_compare_expected_pointer(database):
    with Session(database) as session:
        repo = repository(session)
        ready(repo, "winner", revision=2)
        ready(repo, "loser", revision=2)
        session.commit()
        repo.publish("winner", expected_active_generation=None)
        session.commit()
        with pytest.raises(RuntimeError, match="publication|Publication"):
            repo.publish("loser", expected_active_generation=None)
        assert repo.publication_status(scope()).generation_id == "winner"
        assert repo.get_generation("loser").status == "ready"


def test_old_revision_cannot_replace_newer_even_with_current_pointer(database):
    with Session(database) as session:
        repo = repository(session)
        ready(repo, "new", revision=4)
        ready(repo, "old", revision=3)
        repo.publish("new", expected_active_generation=None)
        with pytest.raises(RuntimeError, match="revision"):
            repo.publish("old", expected_active_generation="new")
        assert repo.publication_status(scope()).generation_id == "new"


def test_concepts_publish_independently_of_entity_revision_and_policy_is_scoped(database):
    with Session(database) as session:
        repo = repository(session)
        ready(repo, "entity", revision=7)
        ready(repo, "concept", revision=None, selected_scope=scope("concept"))
        repo.publish("entity", expected_active_generation=None)
        result = repo.publish(
            "concept",
            expected_active_generation=None,
            calibration_id="run-1",
            policy={"min_cosine": 0.8, "margin": 0.1, "dataset_hash": "d" * 64},
        )
        assert result.calibration_id == "run-1"
        assert result.policy["margin"] == 0.1
        assert result.graph_revision is None
        assert repo.publication_status(scope()).graph_revision == 7
        assert len(repo.list_generations()) == 2


@pytest.mark.parametrize(
    "calibration_id,policy",
    [
        (None, {"min_cosine": 0.8, "margin": 0.1, "dataset_hash": "d" * 64}),
        ("run-1", {}),
        ("run-1", {"apiKey": "credential-must-not-be-stored"}),
        ("run-1", {"min_cosine": 1.1, "margin": 0.1, "dataset_hash": "d" * 64}),
        ("run-1", {"min_cosine": 0.8, "margin": float("nan"), "dataset_hash": "d" * 64}),
        ("run-1", {"min_cosine": 0.8, "margin": 0.1, "dataset_hash": "unverified"}),
    ],
)
def test_uncalibrated_invalid_or_credential_policy_cannot_be_published(
    database, calibration_id, policy
):
    with Session(database) as session:
        repo = repository(session)
        ready(repo, "uncalibrated")
        with pytest.raises(ValueError):
            repo.publish(
                "uncalibrated",
                expected_active_generation=None,
                calibration_id=calibration_id,
                policy=policy,
            )
        assert repo.publication_status(scope()).generation_id is None


def test_generation_scope_revision_and_verified_data_are_immutable(database):
    with Session(database) as session:
        repo = repository(session)
        ready(repo, "immutable")
        with pytest.raises(ValueError, match="immutable|different"):
            repo.create_generation(scope("concept"), generation_id="immutable", graph_revision=None)
        with pytest.raises(ValueError, match="immutable|verified"):
            repo.mark_ready("immutable", expected_count=1, written_count=1, checksum="d" * 64)
        with pytest.raises(ValueError, match="revision"):
            repo.create_generation(scope("concept"), generation_id="invalid", graph_revision=1)


def test_lease_expiry_allows_resume_but_original_owner_cannot_finish(database):
    now = datetime(2026, 11, 16)
    with Session(database) as session:
        repo = repository(session)
        first = repo.claim_build(scope(), graph_revision=2, owner="one", now=now, lease_seconds=10)
        session.commit()
        with pytest.raises(RuntimeError, match="lease|Lease"):
            repo.claim_build(scope(), graph_revision=2, owner="two", now=now, lease_seconds=10)
        resumed = repo.claim_build(
            scope(),
            graph_revision=2,
            owner="two",
            now=now + timedelta(seconds=11),
            lease_seconds=10,
        )
        assert resumed.generation_id == first.generation_id
        with pytest.raises(RuntimeError, match="lease|Lease"):
            repo.renew_lease(
                first.generation_id, owner="one", now=now + timedelta(seconds=12), lease_seconds=10
            )
        assert repo.get_generation(first.generation_id).owner == "two"


def test_retire_protects_active_generation_and_rejects_unknown_ids(database):
    with Session(database) as session:
        repo = repository(session)
        ready(repo, "active")
        repo.publish("active", expected_active_generation=None)
        with pytest.raises(ValueError, match="active"):
            repo.retire("active")
        with pytest.raises(LookupError):
            repo.retire("unknown")


def test_calibration_attachment_is_transactional_and_uses_exact_active_generation(database):
    with Session(database) as session:
        repo = repository(session)
        ready(repo, "active", revision=7)
        repo.publish("active", expected_active_generation=None)
        session.commit()
        policy = {"min_cosine": 0.8, "margin": 0.1, "dataset_hash": "d" * 64}
        status = repo.attach_calibration(
            scope(),
            "active",
            expected_active_generation="active",
            graph_revision=7,
            calibration_id="e" * 64,
            policy=policy,
        )
        assert status.calibration_id == "e" * 64 and status.policy == policy
        session.rollback()
        assert repo.publication_status(scope()).calibration_id is None
        repo.attach_calibration(
            scope(),
            "active",
            expected_active_generation="active",
            graph_revision=7,
            calibration_id="e" * 64,
            policy=policy,
        )
        session.commit()
        with pytest.raises(PublicationConflict):
            repo.attach_calibration(
                scope(),
                "active",
                expected_active_generation="wrong",
                graph_revision=7,
                calibration_id="f" * 64,
                policy=policy,
            )
        assert repo.publication_status(scope()).calibration_id == "e" * 64


def test_calibration_provenance_is_immutable_and_stale_graph_cannot_change_it(database):
    with Session(database) as session:
        repo = repository(session)
        ready(repo, "active", revision=7)
        repo.publish("active", expected_active_generation=None)
        policy = {"min_cosine": 0.8, "margin": 0.1, "dataset_hash": "d" * 64}
        repo.attach_calibration(
            scope(),
            "active",
            expected_active_generation="active",
            graph_revision=7,
            calibration_id="e" * 64,
            policy=policy,
        )
        with pytest.raises(ValueError, match="immutable"):
            repo.attach_calibration(
                scope(),
                "active",
                expected_active_generation="active",
                graph_revision=7,
                calibration_id="e" * 64,
                policy=policy | {"margin": 0.2},
            )
        with pytest.raises(PublicationConflict):
            repo.attach_calibration(
                scope(),
                "active",
                expected_active_generation="active",
                graph_revision=8,
                calibration_id="f" * 64,
                policy=policy,
            )
        assert repo.publication_status(scope()).policy == policy


def test_semantic_migration_is_idempotent_and_publication_has_foreign_key(database):
    from migrations import migrate_database

    with database.begin() as connection:
        Base.metadata.drop_all(connection)
    applied = migrate_database(database)
    assert applied[-1] == "0003_semantic_index_publication"
    assert migrate_database(database) == []
    foreign_keys = inspect(database).get_foreign_keys("semantic_index_publications")
    assert any(item["referred_table"] == "semantic_index_generations" for item in foreign_keys)


@pytest.fixture
def mysql_storage(request):
    url = os.environ.get("GUSTOBOT_TEST_MYSQL_URL")
    if url is None:
        pytest.skip("An isolated MySQL URL must be explicitly supplied")
        return
    engine = create_database_engine(url)
    request.addfinalizer(engine.dispose)
    migrate_database(engine)
    token = uuid4().hex
    selected_scope = scope().model_copy(update={"domain_id": "semantic_publication_" + token})
    try:
        yield SimpleNamespace(engine=engine, scope=selected_scope, token=token)
    finally:
        with engine.begin() as connection:
            connection.execute(
                delete(SemanticIndexPublication).where(
                    SemanticIndexPublication.domain_id == selected_scope.domain_id
                )
            )
            connection.execute(
                delete(SemanticIndexGeneration).where(
                    SemanticIndexGeneration.scope_json["domain_id"].as_string()
                    == selected_scope.domain_id
                )
            )


def test_isolated_mysql_publication_switch_rolls_back_and_foreign_key_is_enforced(mysql_storage):
    storage = mysql_storage
    first, second = storage.token + "-first", storage.token + "-second"
    with Session(storage.engine) as session:
        repo = repository(session)
        ready(repo, first, revision=1, selected_scope=storage.scope)
        repo.publish(first, expected_active_generation=None)
        session.commit()
        ready(repo, second, revision=2, selected_scope=storage.scope)
        session.commit()
        repo.publish(second, expected_active_generation=first)
        assert repo.get_generation(first).status == "retired"
        session.rollback()
        assert repo.publication_status(storage.scope).generation_id == first
        assert repo.get_generation(first).status == "active"
        assert repo.get_generation(second).status == "ready"
        with pytest.raises(IntegrityError):
            session.execute(
                update(SemanticIndexPublication)
                .where(SemanticIndexPublication.domain_id == storage.scope.domain_id)
                .values(active_generation_id=storage.token + "-missing")
            )
        session.rollback()
        assert repo.publication_status(storage.scope).generation_id == first
    assert migrate_database(storage.engine) == []


def test_isolated_mysql_concurrent_publishers_have_exactly_one_cas_winner(mysql_storage):
    storage = mysql_storage
    identifiers = [storage.token + "-one", storage.token + "-two"]
    with Session(storage.engine) as session, session.begin():
        repo = repository(session)
        for identifier in identifiers:
            ready(repo, identifier, revision=3, selected_scope=storage.scope)
    barrier = Barrier(2)

    def publish(identifier):
        barrier.wait(timeout=10)
        try:
            with Session(storage.engine) as session, session.begin():
                repository(session).publish(identifier, expected_active_generation=None)
            return "published"
        except PublicationConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(publish, identifier) for identifier in identifiers]
        assert sorted(future.result(timeout=15) for future in futures) == ["conflict", "published"]
    with Session(storage.engine) as session:
        repo = repository(session)
        rows = repo.list_generations(storage.scope)
        assert sorted(row.status for row in rows) == ["active", "ready"]
        assert repo.publication_status(storage.scope).generation_id in identifiers


def test_isolated_mysql_concurrent_workers_share_one_live_scope_lease(mysql_storage):
    storage = mysql_storage
    barrier = Barrier(2)
    now = datetime(2026, 11, 17)

    def claim(owner):
        barrier.wait(timeout=10)
        try:
            with Session(storage.engine) as session, session.begin():
                generation = repository(session).claim_build(
                    storage.scope, graph_revision=2, owner=owner, now=now, lease_seconds=10
                )
            return generation
        except BuildLeaseConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(claim, owner) for owner in ("worker-a", "worker-b")]
        results = [future.result(timeout=15) for future in futures]
    claimed = [result for result in results if result is not None]
    assert len(claimed) == 1
    with Session(storage.engine) as session, session.begin():
        repo = repository(session)
        resumed = repo.claim_build(
            storage.scope,
            graph_revision=2,
            owner="resumed",
            now=now + timedelta(seconds=11),
            lease_seconds=10,
        )
        assert resumed.generation_id == claimed[0].generation_id
        with pytest.raises(BuildLeaseConflict):
            repo.renew_lease(
                resumed.generation_id,
                owner=claimed[0].owner,
                now=now + timedelta(seconds=12),
                lease_seconds=10,
            )
        repo.update_outcome(
            resumed.generation_id, status="failed", error="test cleanup", owner="resumed"
        )


def test_isolated_mysql_late_calibration_cannot_overwrite_replaced_pointer(mysql_storage):
    storage = mysql_storage
    old, new = storage.token + "-old", storage.token + "-new"
    policy = {"min_cosine": 0.8, "margin": 0.1, "dataset_hash": "d" * 64}
    with Session(storage.engine) as session, session.begin():
        repo = repository(session)
        ready(repo, old, revision=7, selected_scope=storage.scope)
        ready(repo, new, revision=8, selected_scope=storage.scope)
        repo.publish(old, expected_active_generation=None)
    # An evaluator has already observed old; a newer publisher commits first.
    with Session(storage.engine) as stale_session, Session(storage.engine) as publisher:
        stale = repository(stale_session)
        assert stale.publication_status(storage.scope).generation_id == old
        repository(publisher).publish(new, expected_active_generation=old)
        publisher.commit()
        with pytest.raises(PublicationConflict):
            stale.attach_calibration(
                storage.scope,
                old,
                expected_active_generation=old,
                graph_revision=7,
                calibration_id="e" * 64,
                policy=policy,
            )
        stale_session.rollback()
        current = repository(publisher).publication_status(storage.scope)
        assert current.generation_id == new and current.calibration_id is None
        attached = repository(publisher).attach_calibration(
            storage.scope,
            new,
            expected_active_generation=new,
            graph_revision=8,
            calibration_id="f" * 64,
            policy=policy,
        )
        assert attached.calibration_id == "f" * 64
        publisher.commit()

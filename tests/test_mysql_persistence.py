"""Application storage uses MySQL; metadata writes share the caller's transaction."""

import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import Table, create_engine, event, func, inspect, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from gustobot.infrastructure.core import database
from gustobot.infrastructure.persistence.db.models import (
    ChatMessage,
    ChatSession,
    ChatSessionSnapshot,
)


def knowledge_module():
    module_name = "gustobot.infrastructure.persistence.crud.knowledge"
    assert (
        importlib.util.find_spec(module_name) is not None
    ), "KnowledgeRepository is not implemented"
    return importlib.import_module(module_name)


def migrate(engine):
    runner = getattr(database, "migrate_database", None)
    assert callable(runner), "Explicit versioned database migration is not implemented"
    return runner(engine)


@pytest.fixture
def test_engine():
    """SQLite is an explicitly injected offline test engine, never runtime config."""
    knowledge_module()
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        migrate(engine)
        yield engine
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "url",
    ["sqlite:///ignored.db", "postgresql://user:secret@host/db", "mysql://user@host/db"],
)
def test_runtime_database_rejects_non_pymysql_connections_without_leaking_credentials(url):
    factory = getattr(database, "create_database_engine", None)
    assert callable(factory), "MySQL-only runtime engine factory is not implemented"
    with pytest.raises(ValueError, match="mysql\\+pymysql") as failure:
        factory(url)
    assert "secret" not in str(failure.value)


def test_runtime_mysql_engine_is_lazy_and_uses_utf8mb4():
    factory = getattr(database, "create_database_engine", None)
    assert callable(factory), "MySQL-only runtime engine factory is not implemented"
    engine = factory("mysql+pymysql://user:secret@127.0.0.1:1/gustobot")
    try:
        assert engine.dialect.name == "mysql"
        assert engine.dialect.driver == "pymysql"
        assert engine.dialect.create_connect_args(engine.url)[1].get("charset") == "utf8mb4"
    finally:
        engine.dispose()


def test_migration_initializes_once_and_preserves_chat_history():
    knowledge_module()
    engine = create_engine("sqlite://")
    try:
        assert migrate(engine) == [
            "0001_application_schema",
            "0002_exact_knowledge_identity",
            "0003_semantic_index_publication",
        ]
        with Session(engine) as session, session.begin():
            chat = ChatSession(id="migration-chat", title="佛跳墙", user_id=None)
            chat.messages.append(
                ChatMessage(
                    message_type="agent_response",
                    content="用量未知",
                    order_index=0,
                    message_metadata={"sources": [], "count": 0, "known": False},
                )
            )
            chat.snapshots.append(
                ChatSessionSnapshot(query="糖的用量", response_data={"answer": "用量未知"})
            )
            session.add(chat)

        assert migrate(engine) == []
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT version FROM schema_migrations")
            ).scalars().all() == [
                "0001_application_schema",
                "0002_exact_knowledge_identity",
                "0003_semantic_index_publication",
            ]
        with Session(engine) as session:
            loaded = session.get(ChatSession, "migration-chat")
            assert loaded is not None
            assert loaded.messages[0].message_metadata == {
                "sources": [],
                "count": 0,
                "known": False,
            }
            assert loaded.snapshots[0].response_data == {"answer": "用量未知"}
        assert set(inspect(engine).get_table_names()) >= {
            "chat_sessions",
            "chat_messages",
            "knowledge_sources",
            "ingestion_jobs",
            "uploaded_assets",
        }
    finally:
        engine.dispose()


def test_mysql_schema_uses_json_longtext_and_exact_source_foreign_keys():
    knowledge_module()
    models = importlib.import_module("gustobot.infrastructure.persistence.db.models.knowledge")
    source_ddl = str(CreateTable(models.KnowledgeSource.__table__).compile(dialect=mysql.dialect()))
    job_ddl = str(CreateTable(models.IngestionJob.__table__).compile(dialect=mysql.dialect()))
    message_table = ChatMessage.__table__
    assert isinstance(message_table, Table)
    message_ddl = str(CreateTable(message_table).compile(dialect=mysql.dialect()))
    assert "LONGTEXT" in source_ddl
    assert "JSON" in source_ddl
    assert "PRIMARY KEY (domain_id, source_id, version)" in source_ddl
    assert "FOREIGN KEY(domain_id, source_id, source_version)" in job_ddl
    assert "REFERENCES knowledge_sources (domain_id, source_id, version)" in job_ddl
    assert "JSON" in message_ddl
    assert "REFERENCES chat_sessions (id) ON DELETE CASCADE" in message_ddl


def test_asset_lookup_is_durable_and_idempotent(test_engine):
    repository_type = knowledge_module().KnowledgeRepository
    with Session(test_engine) as session, session.begin():
        repository = repository_type(session)
        asset = repository.register_asset(
            id="asset-1",
            original_name="配方.txt",
            path="uploads/managed/file.txt",
            file_type="txt",
            size=0,
        )
        assert (
            repository.register_asset(
                id="asset-1",
                original_name="配方.txt",
                path="uploads/managed/file.txt",
                file_type="txt",
                size=0,
            )
            is asset
        )
        with pytest.raises(ValueError, match="asset"):
            repository.register_asset(
                id="asset-1", original_name="other.txt", path="other", file_type="txt", size=1
            )
    with Session(test_engine) as session:
        repository = repository_type(session)
        loaded = repository.get_asset("asset-1")
        assert loaded is not None
        assert (loaded.original_name, loaded.path, loaded.size) == (
            "配方.txt",
            "uploads/managed/file.txt",
            0,
        )
        assert loaded.created_at is not None
        assert repository.get_asset("missing") is None


def test_source_identity_includes_domain_and_version_and_content_is_immutable(test_engine):
    repository_type = knowledge_module().KnowledgeRepository
    with Session(test_engine) as session, session.begin():
        repository = repository_type(session)
        source = repository.put_source(
            domain_id="recipe",
            source_id="same-name",
            version="v1",
            uri="asset:1",
            text="糖适量",
            ontology_version="recipe-1",
            metadata={"count": 0, "verified": False},
        )
        repository.set_source_status("recipe", "same-name", "v1", "ready")
        assert (
            repository.put_source(
                domain_id="recipe",
                source_id="same-name",
                version="v1",
                uri="asset:1",
                text="糖适量",
                ontology_version="recipe-1",
                metadata={"count": 0, "verified": False},
            )
            is source
        )
        assert source.status == "ready"
        for domain_id, version, content in [
            ("recipe", "v2", "糖 5 克"),
            ("equipment", "v1", "设备说明"),
        ]:
            repository.put_source(
                domain_id=domain_id,
                source_id="same-name",
                version=version,
                uri="asset:1",
                text=content,
                ontology_version="recipe-1",
            )
        with pytest.raises(ValueError, match="version|immutable"):
            repository.put_source(
                domain_id="recipe",
                source_id="same-name",
                version="v1",
                uri="asset:1",
                text="糖 0 克",
                ontology_version="recipe-1",
            )
    with Session(test_engine) as session:
        repository = repository_type(session)
        loaded = repository.get_source("recipe", "same-name", "v1")
        assert loaded is not None
        assert loaded.text == "糖适量"
        assert loaded.source_metadata == {"count": 0, "verified": False}
        assert repository.get_source("recipe", "same-name", "v2").text == "糖 5 克"
        assert repository.get_source("equipment", "same-name", "v1").text == "设备说明"
        assert repository.get_source("recipe", "missing", "v1") is None


def test_failed_jobs_keep_error_details_and_exact_source_version(test_engine):
    repository_type = knowledge_module().KnowledgeRepository
    with Session(test_engine) as session, session.begin():
        repository = repository_type(session)
        repository.put_source(
            domain_id="recipe",
            source_id="recipe-file",
            version="hash-1",
            uri="asset:1",
            text="配方",
            ontology_version="recipe-1",
        )
        job = repository.create_job(
            id="job-1",
            domain_id="recipe",
            source_id="recipe-file",
            source_version="hash-1",
            details={"graph": "ready", "documents": "pending"},
        )
        assert (
            repository.create_job(
                id="job-1", domain_id="recipe", source_id="recipe-file", source_version="hash-1"
            )
            is job
        )
        repository.update_job(
            "job-1",
            status="failed",
            error="Milvus unavailable",
            details={"graph": "ready", "documents": "failed", "indexed_chunks": 0},
        )
        repository.set_source_status("recipe", "recipe-file", "hash-1", "failed")
    with Session(test_engine) as session:
        repository = repository_type(session)
        job = repository.get_job("job-1", domain_id="recipe")
        assert job is not None
        assert (job.status, job.error, job.source_version) == (
            "failed",
            "Milvus unavailable",
            "hash-1",
        )
        assert job.details == {"graph": "ready", "documents": "failed", "indexed_chunks": 0}
        assert job.created_at is not None and job.updated_at is not None
        assert repository.get_job("job-1", domain_id="equipment") is None
        assert repository.get_source("recipe", "recipe-file", "hash-1").status == "failed"
        with pytest.raises(LookupError, match="job"):
            repository.update_job("missing", status="failed", error="missing")
        with pytest.raises(LookupError, match="source"):
            repository.set_source_status("recipe", "missing", "hash-1", "failed")


def test_published_versions_selects_latest_ready_version_in_the_requested_domain(test_engine):
    repository_type = knowledge_module().KnowledgeRepository
    with Session(test_engine) as session, session.begin():
        repository = repository_type(session)
        for domain_id, source_id, version, status in [
            ("recipe", "published", "older", "pending"),
            ("recipe", "published", "newer", "ready"),
            ("recipe", "published", "draft", "processing"),
            ("recipe", "failed-only", "v1", "failed"),
            ("equipment", "published", "other-domain", "ready"),
        ]:
            repository.put_source(
                domain_id=domain_id,
                source_id=source_id,
                version=version,
                uri="memory:test",
                text=version,
                ontology_version="ontology-1",
                status=status,
            )
        provider = getattr(repository, "published_versions", None)
        assert callable(provider), "Published source version selection is not implemented"
        assert provider("recipe") == {"published": "newer"}
        assert provider("equipment") == {"published": "other-domain"}
        assert provider("missing") == {}
        repository.set_source_status("recipe", "published", "older", "ready")
        assert provider("recipe") == {"published": "older"}


def test_ontology_reprocessing_is_explicit_and_published_versions_filter_processing_metadata(
    test_engine,
):
    repository_type = knowledge_module().KnowledgeRepository
    with Session(test_engine) as session, session.begin():
        repository = repository_type(session)
        source = repository.put_source(
            domain_id="recipe",
            source_id="ontology-reprocess",
            version="raw-hash",
            uri="memory:test",
            text="同一份原文",
            ontology_version="1",
            status="ready",
        )
        assert (
            repository.put_source(
                domain_id="recipe",
                source_id="ontology-reprocess",
                version="raw-hash",
                uri="memory:test",
                text="同一份原文",
                ontology_version="2",
                status="pending",
            )
            is source
        )
        assert (source.ontology_version, source.status) == ("1", "ready")
        assert repository.published_versions("recipe", ontology_version="1") == {
            "ontology-reprocess": "raw-hash"
        }
        assert repository.published_versions("recipe", ontology_version="2") == {}
        source.ontology_version = "2"
        source.status = "processing"
        session.flush()
        assert repository.published_versions("recipe", ontology_version="1") == {}
        assert repository.published_versions("recipe", ontology_version="2") == {}
        repository.set_source_status("recipe", "ontology-reprocess", "raw-hash", "ready")
        assert repository.published_versions("recipe", ontology_version="2") == {
            "ontology-reprocess": "raw-hash"
        }


def test_new_metadata_operations_never_commit_the_callers_transaction(test_engine):
    repository_type = knowledge_module().KnowledgeRepository
    with Session(test_engine) as session:
        with pytest.raises(RuntimeError, match="cancelled"), session.begin():
            repository = repository_type(session)
            repository.register_asset(
                id="rolled-back",
                original_name="data.txt",
                path="managed/data.txt",
                file_type="txt",
                size=5,
            )
            repository.put_source(
                domain_id="recipe",
                source_id="rolled-back",
                version="v1",
                uri="asset:1",
                text="source",
                ontology_version="recipe-1",
            )
            repository.create_job(
                id="rolled-back",
                domain_id="recipe",
                source_id="rolled-back",
                source_version="v1",
            )
            raise RuntimeError("cancelled")
        repository = repository_type(session)
        assert repository.get_asset("rolled-back") is None
        assert repository.get_source("recipe", "rolled-back", "v1") is None
        assert repository.get_job("rolled-back") is None


def test_jobs_reject_nonexistent_source_versions(test_engine):
    with Session(test_engine) as session:
        with pytest.raises(IntegrityError), session.begin():
            knowledge_module().KnowledgeRepository(session).create_job(
                id="orphan", domain_id="recipe", source_id="missing", source_version="v1"
            )
        assert knowledge_module().KnowledgeRepository(session).get_job("orphan") is None


def test_migration_cli_rejects_sqlite_before_creating_a_database(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "migrate_database.py"
    assert script.is_file(), "Explicit database migration CLI is not implemented"
    target = tmp_path / "must-not-exist.db"
    environment = dict(os.environ, DATABASE_URL=f"sqlite:///{target.as_posix()}")
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "mysql+pymysql" in result.stderr
    assert not target.exists()


@pytest.mark.skipif(
    not os.environ.get("GUSTOBOT_TEST_MYSQL_URL"), reason="isolated MySQL URL not supplied"
)
def test_isolated_mysql_migration_and_metadata_roundtrip():
    """Runs only against the controller-provided disposable MySQL schema."""
    engine = database.create_database_engine(os.environ["GUSTOBOT_TEST_MYSQL_URL"])
    knowledge_module()
    try:
        migrate(engine)
        assert migrate(engine) == []
        with Session(engine) as session, session.begin():
            repository = knowledge_module().KnowledgeRepository(session)
            source = repository.put_source(
                domain_id="recipe",
                source_id="mysql-persistence-test",
                version="v1",
                uri="memory:test",
                text="佛跳墙的糖用量未知。" + "配方" * 40000,
                ontology_version="recipe-1",
                metadata={"known": False, "count": 0},
            )
            repository.create_job(
                id="mysql-persistence-test",
                domain_id="recipe",
                source_id=source.source_id,
                source_version=source.version,
                details={"documents": "failed"},
            )
            repository.update_job(
                "mysql-persistence-test", status="failed", error="visible test failure"
            )
        with Session(engine) as session:
            repository = knowledge_module().KnowledgeRepository(session)
            assert repository.get_source(
                "recipe", "mysql-persistence-test", "v1"
            ).source_metadata == {"known": False, "count": 0}
            assert repository.get_job("mysql-persistence-test").error == "visible test failure"
            session_count = session.scalar(select(func.count()).select_from(ChatSession))
            assert session_count is not None and session_count >= 0
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("GUSTOBOT_TEST_MYSQL_URL"), reason="isolated MySQL URL not supplied"
)
def test_isolated_mysql_preserves_case_and_accent_in_source_asset_and_job_identity():
    engine = database.create_database_engine(os.environ["GUSTOBOT_TEST_MYSQL_URL"])
    repository_type = knowledge_module().KnowledgeRepository
    identities = [
        ("recipe", "Manual-A", "v1"),
        ("recipe", "manual-a", "v1"),
        ("Recipes", "manual", "v1"),
        ("recipes", "manual", "v1"),
        ("recipe", "café", "v1"),
        ("recipe", "cafe", "v1"),
        ("recipe", "manual", "V1"),
        ("recipe", "manual", "v1"),
    ]
    try:
        migrate(engine)
        with Session(engine) as session, session.begin():
            repository = repository_type(session)
            for domain_id, source_id, version in identities:
                source = repository.put_source(
                    domain_id=domain_id,
                    source_id=source_id,
                    version=version,
                    uri="memory:case-test",
                    text="Case identity sample",
                    ontology_version="case-1",
                )
                assert (source.domain_id, source.source_id, source.version) == (
                    domain_id,
                    source_id,
                    version,
                )
            for asset_id in ["Asset-A", "asset-a"]:
                asset = repository.register_asset(
                    id=asset_id,
                    original_name="case.txt",
                    path="managed/case.txt",
                    file_type="txt",
                    size=1,
                )
                assert asset.id == asset_id
            for job_id in ["Job-A", "job-a"]:
                job = repository.create_job(
                    id=job_id,
                    domain_id="recipe",
                    source_id="Manual-A",
                    source_version="v1",
                )
                assert job.id == job_id
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("GUSTOBOT_TEST_MYSQL_URL"), reason="isolated MySQL URL not supplied"
)
def test_isolated_mysql_chat_history_roundtrips_json_and_enforces_session_foreign_key():
    engine = database.create_database_engine(os.environ["GUSTOBOT_TEST_MYSQL_URL"])
    try:
        migrate(engine)
        with (
            Session(engine) as session,
            pytest.raises(IntegrityError),
            session.begin(),
        ):
            session.add(
                ChatMessage(
                    session_id="missing-mysql-chat",
                    message_type="user_query",
                    content="orphan",
                    order_index=0,
                )
            )
        with Session(engine) as session, session.begin():
            chat = session.get(ChatSession, "mysql-chat-invariants")
            if chat is None:
                chat = ChatSession(id="mysql-chat-invariants", title="佛跳墙", user_id=None)
                chat.messages.append(
                    ChatMessage(
                        message_type="agent_response",
                        content="糖用量未知",
                        order_index=0,
                        message_metadata={"sources": [], "count": 0, "known": False},
                    )
                )
                chat.snapshots.append(
                    ChatSessionSnapshot(
                        query="糖放多少",
                        response_data={"answer": "用量未知", "sources": []},
                    )
                )
                session.add(chat)
        assert migrate(engine) == []
        with Session(engine) as session:
            chat = session.get(ChatSession, "mysql-chat-invariants")
            assert chat is not None
            assert chat.title == "佛跳墙"
            assert chat.messages[0].message_metadata == {"sources": [], "count": 0, "known": False}
            assert chat.snapshots[0].response_data == {"answer": "用量未知", "sources": []}
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.environ.get("GUSTOBOT_TEST_MYSQL_URL"), reason="isolated MySQL URL not supplied"
)
def test_isolated_mysql_debug_logging_hides_source_parameter_values(caplog):
    engine = database.create_database_engine(os.environ["GUSTOBOT_TEST_MYSQL_URL"], echo=True)
    try:
        migrate(engine)
        caplog.clear()
        with caplog.at_level("INFO", logger="sqlalchemy.engine.Engine"), Session(engine) as session:
            knowledge_module().KnowledgeRepository(session).put_source(
                domain_id="recipe",
                source_id="log-redaction-test",
                version="temporary",
                uri="memory:log-test",
                text="task-only-sensitive-token",
                ontology_version="1",
            )
            session.rollback()
        assert any(
            "INSERT INTO knowledge_sources" in record.getMessage() for record in caplog.records
        )
        assert "task-only-sensitive-token" not in caplog.text
    finally:
        engine.dispose()


def test_schema_check_does_not_create_tables_or_apply_missing_revisions():
    from sqlalchemy import inspect

    from migrations import check_database_schema

    engine = create_engine("sqlite://")
    try:
        with pytest.raises(RuntimeError, match="migrate|版本|schema"):
            check_database_schema(engine)
        assert inspect(engine).get_table_names() == []
        migrate(engine)
        check_database_schema(engine)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM schema_migrations WHERE version = '0003_semantic_index_publication'"
                )
            )
        with pytest.raises(RuntimeError, match="migrate|版本|schema"):
            check_database_schema(engine)
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM schema_migrations")).scalar_one() == 2
            )
    finally:
        engine.dispose()

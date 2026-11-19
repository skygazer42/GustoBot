"""Opt-in physical MySQL/Neo4j restore exercise using only newly owned resources.

Run with the dotenv-disabled test entrypoint and explicit restore environment.
The controlled corpus and vector protocol fixtures do not prove vendor semantic
quality, production backup readiness or full-corpus migration.
"""

import asyncio
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
from contextlib import AsyncExitStack, ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any, Literal, cast
from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from gustobot.config.domain import get_domain_definition
from gustobot.domain.formal_ontology import load_formal_ontology
from gustobot.domain.knowledge import KnowledgeGraph
from gustobot.domain.linking import (
    BuildIndexRequest,
    IndexVerification,
    catalog_checksum,
    digest,
)
from gustobot.infrastructure.core.database import (
    Base,
    create_database_engine,
    migrate_database,
)
from gustobot.infrastructure.core.resources import close_on_exit
from gustobot.infrastructure.knowledge.graph_store import FactQuery, Neo4jGraphStore
from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts
from gustobot.infrastructure.knowledge.semantic_runtime import (
    SemanticRuntime,
    SemanticSelection,
)
from gustobot.infrastructure.persistence.crud.knowledge import KnowledgeRepository
from gustobot.infrastructure.persistence.crud.semantic_index import (
    SemanticIndexRepository,
)
from gustobot.infrastructure.persistence.db.models import (
    IngestionJob,
    KnowledgeSource,
    SemanticIndexGeneration,
    SemanticIndexPublication,
    UploadedAsset,
)
from scripts.verify_knowledge_snapshot import create_manifest, verify_manifest

ROOT = Path(__file__).resolve().parents[1]
RESTORE_ROOT = ROOT / ".superpowers/sdd/2026-11-16-knowledge-completion/restore"
ENABLED = os.environ.get("GUSTOBOT_RUN_RESTORE_EXERCISE") == "1"

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not ENABLED, reason="Explicit isolated restore exercise was not requested"),
]


def _json(path: Path, payload):
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _hash_file(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


class OwnedResources:
    """Only generated names carrying this run's unique Docker label can mutate."""

    def __init__(self):
        RESTORE_ROOT.resolve().relative_to(ROOT.resolve())
        RESTORE_ROOT.mkdir(parents=True, exist_ok=True)
        self.token = uuid4().hex[:16]
        self.name = "gustobot-restore-" + self.token
        self.volume = self.name + "-data"
        self.database = "gustobot_restore_" + self.token
        self.label = "org.gustobot.restore-exercise=" + self.token
        self.path = RESTORE_ROOT / self.token
        self.path.mkdir()
        self.bundle = self.path / "bundle"
        self.bundle.mkdir()
        self.password = secrets.token_urlsafe(24)
        self.created_container = self.created_volume = self.created_database = False
        self.engine = None
        self.admin_engine = None
        self.private: dict[str, Any] = {
            "token": self.token,
            "neo4j_container": self.name,
            "neo4j_volume": self.volume,
            "mysql_database": self.database,
        }
        self.evidence: dict[str, Any] = {
            "exercise": "controlled_real_database_dump_restore_v1",
            "run_id": self.token,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "provider_kind": "protocol",
            "shared_services_modified": False,
            "production_data_used": False,
            "database_restore_verified": False,
            "vector_vendor_restore_verified": False,
            "actual_provider_quality_verified": False,
            "cleanup": {},
            "steps": [],
        }

    def docker(self, args, *, name, stdin=None, stdout=None, timeout=90):
        result = subprocess.run(
            ["docker", *args],
            input=stdin,
            stdout=subprocess.PIPE if stdout is None else stdout,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            # Docker can include env arguments in its error. Keep only a sanitized
            # operation code in pytest/output, never command arguments or stderr.
            raise RuntimeError("Restore Docker operation failed: " + name)
        return b"" if result.stdout is None else result.stdout

    def assert_owned_container(self):
        actual = (
            self.docker(
                [
                    "inspect",
                    "--format",
                    '{{ index .Config.Labels "org.gustobot.restore-exercise" }}',
                    self.name,
                ],
                name="check ownership",
            )
            .decode()
            .strip()
        )
        if actual != self.token:
            raise RuntimeError("Refusing to mutate a Docker container without this run's label")

    def stop(self):
        self.assert_owned_container()
        self.docker(["stop", "--time", "30", self.name], name="stop owned Neo4j", timeout=45)

    def start(self):
        self.assert_owned_container()
        self.docker(["start", self.name], name="start owned Neo4j")
        port = (
            self.docker(["port", self.name, "7687/tcp"], name="refresh owned Neo4j port")
            .decode()
            .strip()
        )
        self.uri = "bolt://" + port
        self.private["neo4j"]["uri"] = self.uri
        _json(self.path / "private.json", self.private)

    async def wait_graph(self):
        deadline = monotonic() + 150
        while monotonic() < deadline:
            driver = AsyncGraphDatabase.driver(
                self.uri, auth=("neo4j", self.password), connection_timeout=2
            )
            try:
                await driver.verify_connectivity()
                return
            except Exception:  # noqa: BLE001 - Bounded startup polling against a new owned service.
                await asyncio.sleep(2)
            finally:
                await driver.close()
        raise TimeoutError("Owned Neo4j did not become ready")

    def prepare_mysql(self):
        config_path = Path(os.environ["GUSTOBOT_TEST_RESTORE_MYSQL_CONFIG"]).resolve(strict=True)
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        url = make_url(config["url"])
        if url.host != "127.0.0.1" or url.port != 56867 or url.username != "root":
            raise ValueError(
                "Restore exercise requires the explicitly authorized local task MySQL root"
            )
        if url.password is None:
            raise ValueError("Task MySQL password is missing")
        self.mysql_password = url.password
        self.mysql_container = config["container"]
        if self.mysql_container != "gustobot-ontology-verify-mysql":
            raise ValueError("Unexpected task MySQL container")
        self.admin_url = url
        self.admin_engine = create_engine(url, hide_parameters=True)
        if re.fullmatch(r"gustobot_restore_[0-9a-f]{16}", self.database) is None:
            raise ValueError("Unsafe generated restore database name")
        with self.admin_engine.begin() as connection:
            connection.execute(
                text(
                    f"CREATE DATABASE `{self.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin"
                )
            )
        self.created_database = True
        self.engine = create_database_engine(url.set(database=self.database))
        migrate_database(self.engine)
        self.private["mysql_url"] = self.engine.url.render_as_string(hide_password=False)

    async def prepare(self):
        self.prepare_mysql()
        self.docker(
            ["volume", "create", "--label", self.label, self.volume],
            name="create owned Neo4j volume",
        )
        self.created_volume = True
        self.docker(
            [
                "run",
                "--detach",
                "--name",
                self.name,
                "--label",
                self.label,
                "--publish",
                "127.0.0.1::7687",
                "--volume",
                self.volume + ":/data",
                "--env",
                "NEO4J_AUTH=neo4j/" + self.password,
                "--env",
                "NEO4J_server_memory_heap_initial__size=128m",
                "--env",
                "NEO4J_server_memory_heap_max__size=256m",
                "--env",
                "NEO4J_server_memory_pagecache_size=128m",
                "neo4j:5.26-community",
            ],
            name="create owned Neo4j service",
        )
        self.created_container = True
        port = (
            self.docker(["port", self.name, "7687/tcp"], name="read owned Neo4j port")
            .decode()
            .strip()
        )
        self.uri = "bolt://" + port
        self.private["neo4j"] = {
            "uri": self.uri,
            "user": "neo4j",
            "password": self.password,
            "database": "neo4j",
        }
        _json(self.path / "private.json", self.private)
        await self.wait_graph()

    def dump_mysql(self):
        with (self.bundle / "mysql.sql").open("wb") as output:
            self.docker(
                [
                    "exec",
                    "--env",
                    "MYSQL_PWD=" + self.mysql_password,
                    self.mysql_container,
                    "mysqldump",
                    "--user=root",
                    "--single-transaction",
                    "--routines",
                    "--triggers",
                    "--hex-blob",
                    "--set-gtid-purged=OFF",
                    "--no-tablespaces",
                    self.database,
                ],
                name="dump owned MySQL database",
                stdout=output,
            )

    def restore_mysql(self):
        self.docker(
            [
                "exec",
                "--interactive",
                "--env",
                "MYSQL_PWD=" + self.mysql_password,
                self.mysql_container,
                "mysql",
                "--user=root",
                self.database,
            ],
            name="restore owned MySQL database",
            stdin=(self.bundle / "mysql.sql").read_bytes(),
        )

    def admin_graph(self, operation):
        self.assert_owned_container()
        running = (
            self.docker(
                ["inspect", "--format", "{{.State.Running}}", self.name],
                name="check owned Neo4j stopped",
            )
            .decode()
            .strip()
        )
        if running != "false":
            raise RuntimeError(
                "Offline Neo4j backup/restore requires the owned service to be stopped"
            )
        helper = self.name + "-" + operation
        arguments = [
            "run",
            "--rm",
            "--name",
            helper,
            "--label",
            self.label,
            "--user",
            "neo4j",
            "--volumes-from",
            self.name,
            "--mount",
            "type=bind,source=" + str(self.bundle.resolve()) + ",target=/backups",
            "--entrypoint",
            "neo4j-admin",
            "neo4j:5.26-community",
            "database",
            operation,
            "neo4j",
        ]
        if operation == "dump":
            arguments.append("--to-path=/backups")
        elif operation == "load":
            arguments.extend(["--from-path=/backups", "--overwrite-destination=true"])
        else:
            raise ValueError("Unsupported restore exercise operation")
        self.docker(arguments, name="offline owned Neo4j " + operation, timeout=180)

    def cleanup(self):
        with ExitStack() as cleanup:
            cleanup.callback(self._record_cleanup)
            if self.created_volume:
                cleanup.callback(self._remove_volume)
            if self.created_container:
                cleanup.callback(self._remove_container)
            if self.admin_engine is not None:
                cleanup.callback(self.admin_engine.dispose)
            if self.created_database:
                cleanup.callback(self._drop_database)
            if self.engine is not None:
                cleanup.callback(self.engine.dispose)

    def _drop_database(self):
        assert self.admin_engine is not None
        with self.admin_engine.begin() as connection:
            connection.execute(text(f"DROP DATABASE `{self.database}`"))
        self.evidence["cleanup"]["mysql_database_removed"] = True

    def _remove_container(self):
        self.assert_owned_container()
        self.docker(["rm", "--force", self.name], name="remove owned Neo4j container")
        self.evidence["cleanup"]["neo4j_container_removed"] = True

    def _remove_volume(self):
        actual = (
            self.docker(
                [
                    "volume",
                    "inspect",
                    "--format",
                    '{{ index .Labels "org.gustobot.restore-exercise" }}',
                    self.volume,
                ],
                name="check owned volume label",
            )
            .decode()
            .strip()
        )
        if actual != self.token:
            raise RuntimeError("Refusing to remove a volume without this run's label")
        self.docker(["volume", "rm", self.volume], name="remove owned Neo4j volume")
        self.evidence["cleanup"]["neo4j_volume_removed"] = True

    def _record_cleanup(self):
        self.evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        _json(self.path / "evidence.json", self.evidence)


class ProtocolVectors:
    """Explicit protocol-only persistence, deliberately excluded from vendor backups."""

    embedding_fingerprint = "a" * 64

    def __init__(self):
        self.rows = {}

    def reusable_vectors(self, scope, hashes):
        return {
            record.text_hash: vector
            for rows in self.rows.values()
            for record, vector in rows.values()
            if record.text_hash in hashes
        }

    def upsert(self, generation_id, records, vectors):
        rows = self.rows.setdefault(generation_id, {})
        rows.update(
            {
                record.record_id: (record, vector)
                for record, vector in zip(records, vectors, strict=True)
            }
        )

    def verify_generation(self, generation_id, *, expected_count, expected_checksum):
        records = [record for record, _ in self.rows.get(generation_id, {}).values()]
        checksum = catalog_checksum(records)
        return IndexVerification(
            valid=len(records) == expected_count and checksum == expected_checksum,
            count=len(records),
            checksum=checksum,
            schema_fingerprint="b" * 64,
        )


class ProtocolEmbeddings:
    async def aembed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _mysql_snapshot(engine):
    result = {}
    with engine.connect() as connection:
        for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
            rows = [dict(row) for row in connection.execute(select(table)).mappings()]
            result[table.name] = sorted(
                rows, key=lambda row: json.dumps(row, sort_keys=True, default=str)
            )
        result["schema_migrations"] = [
            dict(row)
            for row in connection.execute(
                text("SELECT * FROM schema_migrations ORDER BY version")
            ).mappings()
        ]
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "counts": {name: len(rows) for name, rows in result.items()},
        "checksum": hashlib.sha256(encoded.encode()).hexdigest(),
        "rows": result,
    }


async def _graph_snapshot(store):
    async with store._driver.session(database=store.database) as session:
        nodes = await (
            await session.run("MATCH (n) RETURN labels(n) AS labels, properties(n) AS properties")
        ).data()
        relations = await (
            await session.run(
                "MATCH (a)-[r]->(b) RETURN a.id AS source_id, b.id AS target_id, type(r) AS type, properties(r) AS properties"
            )
        ).data()
    for row in nodes:
        row["labels"] = sorted(row["labels"])
    nodes.sort(key=lambda row: json.dumps(row, sort_keys=True))
    relations.sort(key=lambda row: json.dumps(row, sort_keys=True))
    return {
        "node_count": len(nodes),
        "relation_count": len(relations),
        "checksum": digest({"nodes": nodes, "relations": relations}),
        "nodes": nodes,
        "relations": relations,
    }


async def _answer(store, model, variant_id):
    from gustobot.domain.numeric import NumericSelection

    facts = await store.query(
        FactQuery(
            entity_type="RecipeVariant",
            anchor_ids=[variant_id],
            numeric_selections=[
                NumericSelection(
                    property="ingredientTotalAmount",
                    target_ref="糖类",
                    grain="recipe_total",
                    unit="g",
                )
            ],
        )
    )
    answer = SemanticRuntime(model).evaluate(
        KnowledgeGraph(entities=facts.entities, relations=facts.relations, sources=facts.sources),
        [
            SemanticSelection(
                property="ingredientTotalAmount", target="糖类", grain="recipe_total", unit="g"
            )
        ],
        anchor_ids=[variant_id],
        numeric_values=facts.numeric_values,
    )
    assert answer.status == "success" and "20g" in answer.message
    assert len(answer.sources) == 1
    return {
        "status": answer.status,
        "message": answer.message,
        "source_ids": sorted(item["document_id"] for item in answer.sources),
        "numeric_values": [item.model_dump() for item in facts.numeric_values],
    }


async def test_real_mysql_and_offline_neo4j_dump_restore_preserve_controlled_knowledge():
    from gustobot.application.services.semantic_indexing import SemanticIndexingService

    owned = OwnedResources()
    stores = []
    try:
        await owned.prepare()
        domain = get_domain_definition()
        model = domain.semantic_model
        assert model is not None and model.version == "2026-11-17.1"
        (owned.bundle / "model").mkdir()
        for filename in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
            shutil.copy2(
                ROOT / "gustobot/config/ontologies" / filename, owned.bundle / "model" / filename
            )
        saved_model = load_formal_ontology(
            owned.bundle / "model/recipes.ttl", owned.bundle / "model/recipes.shacl.ttl"
        )
        assert saved_model.fingerprint == model.fingerprint
        scope = {
            "domain_id": domain.id,
            "ontology_version": domain.version,
            "ontology_fingerprint": model.fingerprint,
        }
        graph = recipe_to_facts(
            "恢复验证佛跳墙",
            {
                "主料": [["猪肉", "500g"]],
                "辅料": [["白糖", "20g"]],
                "耗时": "30分钟",
                "做法": ["准备原料", "炖煮至熟"],
            },
            domain=domain,
        )
        source = graph.sources[0]
        version = hashlib.sha256(source.text.encode()).hexdigest()
        source_path = owned.bundle / "recipe-source.json"
        source_path.write_text(source.text, encoding="utf-8")
        asset_id = "restore-asset-" + owned.token
        job_id = "restore-job-" + owned.token
        variant_id = next(item.id for item in graph.entities if item.type == "RecipeVariant")
        store = Neo4jGraphStore(domain, uri=owned.uri, user="neo4j", password=owned.password)
        stores.append(store)
        await store.bootstrap_graph_scope(audit_only=False)
        await store.upsert(graph)
        audit = await store.bootstrap_graph_scope(audit_only=True)
        assert audit.invalid == 0 and audit.unknown_version == 0 and not audit.errors
        revision = await store.graph_revision()
        assert revision.state == "ready" and revision.revision == 1
        with Session(owned.engine) as session, session.begin():
            repo = KnowledgeRepository(session)
            repo.register_asset(
                id=asset_id,
                original_name="recipe-source.json",
                path=str(source_path),
                file_type="json",
                size=source_path.stat().st_size,
            )
            repo.put_source(
                domain_id=domain.id,
                source_id=source.id,
                version=version,
                uri="controlled:restore-exercise",
                text=source.text,
                ontology_version=domain.version,
                status="graph_ready",
                metadata={"kind": "recipe", "asset_id": asset_id},
            )
            repo.create_job(
                id=job_id,
                domain_id=domain.id,
                source_id=source.id,
                source_version=version,
                status="graph_ready",
                details={"controlled_restore_exercise": True},
            )

        @contextmanager
        def transaction():
            with Session(owned.engine) as session, session.begin():
                yield session

        vectors = ProtocolVectors()
        indexer = SemanticIndexingService(
            domain,
            graph_store=store,
            candidate_store=cast(Any, vectors),
            embedder=cast(Any, ProtocolEmbeddings()),
            session_factory=transaction,
        )
        kinds: tuple[Literal["concept", "entity"], ...] = ("concept", "entity")
        receipts = [
            await indexer.build(BuildIndexRequest(scope=indexer.scope(kind), publish=True))
            for kind in kinds
        ]
        assert all(item.status == "active" for item in receipts)
        before_answer = await _answer(store, model, variant_id)
        before_graph = await _graph_snapshot(store)
        before_mysql = _mysql_snapshot(owned.engine)
        _json(owned.path / "before-private.json", {"graph": before_graph, "mysql": before_mysql})
        capture = "restore-" + owned.token
        with transaction() as session:
            metadata = SemanticIndexRepository(session)
            publications = [
                metadata.publication_status(indexer.scope(kind)).model_dump(mode="json")
                for kind in kinds
            ]
            generations = [item.model_dump(mode="json") for item in metadata.list_generations()]
        _json(
            owned.bundle / "mysql-scope.json",
            {
                "capture_id": capture,
                "scope": scope,
                "graph_revision": revision.revision,
                "schema_revisions": [
                    row["version"] for row in before_mysql["rows"]["schema_migrations"]
                ],
                "asset_ids": [asset_id],
                "sources": [
                    {
                        "source_id": source.id,
                        "version": version,
                        "ontology_version": domain.version,
                        "status": "graph_ready",
                        "asset_id": asset_id,
                    }
                ],
            },
        )
        _json(
            owned.bundle / "graph-scope.json",
            {
                "capture_id": capture,
                "scope": scope,
                "graph_revision": revision.revision,
                "source_ids": [source.id],
                "sample_entity_ids": [variant_id],
                "numeric_projection_version": model.numeric_projection_version,
            },
        )
        _json(
            owned.bundle / "documents.json",
            {
                "capture_id": capture,
                "scope": scope,
                "collection": "protocol_no_document_vectors",
                "embedding_model": "protocol_fixed_vector",
                "dimension": 2,
                "publications": [],
            },
        )
        _json(
            owned.bundle / "candidates.json",
            {"capture_id": capture, "publications": publications, "generations": generations},
        )
        _json(
            owned.path / "protocol-vectors.json",
            {
                generation: {
                    key: {"record": record.model_dump(), "vector": vector}
                    for key, (record, vector) in rows.items()
                }
                for generation, rows in vectors.rows.items()
            },
        )
        _json(
            owned.bundle / "snapshot-input.json",
            {
                "snapshot_id": capture,
                "model": {
                    "ontology": "model/recipes.ttl",
                    "shapes": "model/recipes.shacl.ttl",
                    "resources": ["model/schema-recipe-subset.ttl"],
                },
                "mysql": {"dump": "mysql.sql", "metadata": "mysql-scope.json"},
                "neo4j": {"dump": "neo4j.dump", "metadata": "graph-scope.json"},
                "sources": [
                    {
                        "source_id": source.id,
                        "version": version,
                        "asset_id": asset_id,
                        "path": source_path.name,
                    }
                ],
                "documents": "documents.json",
                "candidates": "candidates.json",
                "vector_backups": {},
            },
        )
        owned.dump_mysql()
        await store.close()
        owned.stop()
        owned.admin_graph("dump")
        assert (owned.bundle / "neo4j.dump").stat().st_size > 0
        manifest = create_manifest(
            owned.bundle / "snapshot-input.json", owned.bundle / "manifest.json"
        )
        assert (
            manifest.valid
            and not manifest.candidate_compatible
            and "candidate_backup_missing" in manifest.rebuild_reasons
        )
        assert not manifest.database_restore_verified
        owned.evidence["steps"].append(
            "Actual MySQL mysqldump and stopped-volume neo4j-admin dump completed"
        )

        owned.start()
        await owned.wait_graph()
        changed = Neo4jGraphStore(domain, uri=owned.uri, user="neo4j", password=owned.password)
        stores.append(changed)
        async with changed._driver.session(database=changed.database) as graph_session:
            await (await graph_session.run("MATCH (n) DETACH DELETE n")).consume()
        assert (await _graph_snapshot(changed))["node_count"] == 0
        with transaction() as session:
            for model_type in (
                SemanticIndexPublication,
                SemanticIndexGeneration,
                IngestionJob,
                KnowledgeSource,
                UploadedAsset,
            ):
                session.execute(delete(model_type))
        assert _mysql_snapshot(owned.engine)["counts"]["knowledge_sources"] == 0
        vectors.rows.clear()
        await changed.close()
        owned.stop()
        owned.restore_mysql()
        owned.admin_graph("load")
        owned.start()
        await owned.wait_graph()
        restored_model = load_formal_ontology(
            owned.bundle / "model/recipes.ttl", owned.bundle / "model/recipes.shacl.ttl"
        )
        restored = Neo4jGraphStore(
            restored_model.domain_definition(), uri=owned.uri, user="neo4j", password=owned.password
        )
        stores.append(restored)
        after_mysql = _mysql_snapshot(owned.engine)
        after_graph = await _graph_snapshot(restored)
        restored_revision = await restored.graph_revision()
        after_answer = await _answer(restored, restored_model, variant_id)
        assert after_mysql == before_mysql
        assert after_graph == before_graph
        assert restored_revision == revision
        assert after_answer == before_answer
        verified = verify_manifest(owned.bundle / "manifest.json")
        assert verified.valid and not verified.candidate_compatible
        assert verified.restore_checklist[0].startswith("Set SEMANTIC_LINKING_MODE=off")
        owned.evidence.update(
            {
                "database_restore_verified": True,
                "actual_mysql_dump_restored": True,
                "actual_offline_neo4j_dump_restored": True,
                "model_scope": scope,
                "graph_revision": revision.revision,
                "source_versions": {source.id: version},
                "variant_id": variant_id,
                "before_mysql_checksum": before_mysql["checksum"],
                "after_mysql_checksum": after_mysql["checksum"],
                "mysql_counts": after_mysql["counts"],
                "before_graph_checksum": before_graph["checksum"],
                "after_graph_checksum": after_graph["checksum"],
                "graph_nodes": after_graph["node_count"],
                "graph_relationships": after_graph["relation_count"],
                "deterministic_answer": after_answer,
                "dump_hashes": {
                    "mysql": _hash_file(owned.bundle / "mysql.sql"),
                    "neo4j": _hash_file(owned.bundle / "neo4j.dump"),
                },
                "snapshot_manifest": verified.model_dump(),
                "candidate_restore_action": "off_and_rebuild; protocol vectors were not vendor backups",
            }
        )
        owned.evidence["steps"].append(
            "Owned datasets were erased, restored from real dumps, and matched on rows, IDs, source versions, counts, revision, checksums and 20g evidence-backed answer"
        )
    finally:
        try:
            async with AsyncExitStack() as cleanup:
                for store in stores:
                    await cleanup.enter_async_context(close_on_exit(store.close))
        finally:
            owned.cleanup()

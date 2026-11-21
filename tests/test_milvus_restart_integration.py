"""Opt-in restart persistence proof using one new Milvus container and volume.

The fixture vectors prove storage, scoping and numeric vector stability. They
do not measure a real embedding provider or the quality of semantic retrieval.
"""

import asyncio
import hashlib
import json
import math
import os
import struct
import subprocess
from contextlib import AsyncExitStack, ExitStack
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from time import monotonic
from typing import Any, Literal
from uuid import uuid4

import httpx
import pytest

from gustobot.domain.linking import (
    INDEX_SCHEMA_VERSION,
    CatalogRecord,
    IndexScope,
    catalog_checksum,
    digest,
)
from gustobot.infrastructure.core.resources import close_on_exit
from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore
from gustobot.infrastructure.knowledge.vector_store import DocumentChunk, VectorStore

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / ".superpowers/sdd/2026-11-16-knowledge-completion/milvus-restart"
ENABLED = os.environ.get("GUSTOBOT_RUN_MILVUS_RESTART") == "1"
# QueryCoord checks restored node sessions every 60s; HTTP health can recover earlier.
RECOVERY_TIMEOUT = 120

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not ENABLED, reason="Explicit isolated Milvus restart exercise was not requested"
    ),
]


def _json(path: Path, payload) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


class OwnedMilvus:
    def __init__(self) -> None:
        OUTPUT_ROOT.resolve().relative_to(ROOT.resolve())
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        self.token = uuid4().hex[:16]
        self.name = "gustobot-milvus-restart-" + self.token
        self.volume = self.name + "-data"
        self.label = "org.gustobot.milvus-restart=" + self.token
        self.folder = OUTPUT_ROOT / self.token
        self.folder.mkdir()
        self.container_created = self.volume_created = self.image_created = False
        self.evidence: dict[str, Any] = {
            "exercise": "isolated_milvus_real_restart_persistence_v1",
            "run_id": self.token,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "provider_kind": "fixed_numeric_vector_fixture",
            "image": self.name,
            "candidate_schema": INDEX_SCHEMA_VERSION,
            "actual_restart_verified": False,
            "semantic_quality_verified": False,
            "shared_services_modified": False,
            "cleanup": {},
            "timings_seconds": {},
        }

    def docker(self, arguments: list[str], *, operation: str, timeout: int = 60) -> bytes:
        result = subprocess.run(
            ["docker", *arguments], capture_output=True, check=False, timeout=timeout
        )
        if result.returncode:
            # No keys are used, but avoid dumping arbitrary daemon output into reports.
            raise RuntimeError("Owned Milvus Docker operation failed: " + operation)
        return result.stdout

    def assert_owned(self) -> None:
        label = (
            self.docker(
                [
                    "inspect",
                    "--format",
                    '{{ index .Config.Labels "org.gustobot.milvus-restart" }}',
                    self.name,
                ],
                operation="verify ownership",
            )
            .decode()
            .strip()
        )
        if label != self.token:
            raise RuntimeError("Refusing to mutate a container without this run's ownership label")

    def ports(self) -> None:
        def port(internal):
            value = (
                self.docker(["port", self.name, f"{internal}/tcp"], operation="read own port")
                .decode()
                .strip()
            )
            address, separator, number = value.rpartition(":")
            if separator != ":" or address != "127.0.0.1" or not number.isdigit():
                raise ValueError("Owned service must expose exactly one loopback port")
            return int(number)

        self.grpc_port, self.health_port = port(19530), port(9091)

    async def wait_ready(self, *, budget_seconds: float = 180) -> float:
        started = monotonic()
        async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
            while monotonic() - started < budget_seconds:
                try:
                    response = await client.get(f"http://127.0.0.1:{self.health_port}/healthz")
                    if response.status_code == 200:
                        return monotonic() - started
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
        raise TimeoutError("Owned Milvus did not become healthy within its bounded startup budget")

    async def start(self) -> None:
        started = monotonic()
        self.docker(
            [
                "build",
                "--file",
                str(ROOT / "Dockerfile"),
                "--target",
                "milvus",
                "--tag",
                self.name,
                "--label",
                self.label,
                str(ROOT),
            ],
            operation="build own image",
            timeout=300,
        )
        self.image_created = True
        self.docker(
            ["volume", "create", "--label", self.label, self.volume], operation="create own volume"
        )
        self.volume_created = True
        self.docker(
            [
                "run",
                "--detach",
                "--name",
                self.name,
                "--label",
                self.label,
                "--publish",
                "127.0.0.1::19530",
                "--publish",
                "127.0.0.1::9091",
                "--security-opt",
                "seccomp=unconfined",
                "--volume",
                self.volume + ":/var/lib/milvus",
                "--env",
                "ETCD_USE_EMBED=true",
                "--env",
                "ETCD_DATA_DIR=/var/lib/milvus/etcd",
                "--env",
                "ETCD_CONFIG_PATH=/milvus/configs/embedEtcd.yaml",
                "--env",
                "COMMON_STORAGETYPE=local",
                self.name,
                "milvus",
                "run",
                "standalone",
            ],
            operation="start own service",
        )
        self.container_created = True
        configuration = self.docker(
            ["exec", self.name, "cat", "/milvus/configs/embedEtcd.yaml"],
            operation="read own image configuration",
        )
        self.ports()
        self.evidence["initial_ports"] = {"grpc": self.grpc_port, "health": self.health_port}
        self.evidence["configuration_sha256"] = {
            "embedEtcd.yaml": hashlib.sha256(configuration).hexdigest()
        }
        await self.wait_ready()
        self.evidence["timings_seconds"]["initial_start_to_health"] = monotonic() - started

    async def restart(self) -> None:
        self.assert_owned()
        started = monotonic()
        await asyncio.to_thread(
            self.docker,
            ["restart", "--time", "30", self.name],
            operation="restart own service",
            timeout=45,
        )
        self.ports()
        self.evidence["after_restart_ports"] = {"grpc": self.grpc_port, "health": self.health_port}
        await self.wait_ready()
        self.evidence["timings_seconds"]["restart_to_health"] = monotonic() - started

    def cleanup(self) -> None:
        with ExitStack() as cleanup:
            cleanup.callback(self._record_cleanup)
            if self.image_created:
                cleanup.callback(self._remove_image)
            if self.volume_created:
                cleanup.callback(self._remove_volume)
            if self.container_created:
                cleanup.callback(self._remove_container)

    def _remove_container(self) -> None:
        self.assert_owned()
        self.docker(["rm", "--force", self.name], operation="remove own service")
        self.evidence["cleanup"]["container_removed"] = True

    def _remove_image(self) -> None:
        label = (
            self.docker(
                [
                    "image",
                    "inspect",
                    "--format",
                    '{{ index .Config.Labels "org.gustobot.milvus-restart" }}',
                    self.name,
                ],
                operation="verify own image",
            )
            .decode()
            .strip()
        )
        if label != self.token:
            raise RuntimeError("Refusing to remove an image without this run's ownership label")
        self.docker(["image", "rm", self.name], operation="remove own image")
        self.evidence["cleanup"]["image_removed"] = True

    def _remove_volume(self) -> None:
        label = (
            self.docker(
                [
                    "volume",
                    "inspect",
                    "--format",
                    '{{ index .Labels "org.gustobot.milvus-restart" }}',
                    self.volume,
                ],
                operation="verify own volume",
            )
            .decode()
            .strip()
        )
        if label != self.token:
            raise RuntimeError("Refusing to remove a volume without this run's ownership label")
        self.docker(["volume", "rm", self.volume], operation="remove own volume")
        self.evidence["cleanup"]["volume_removed"] = True

    def _record_cleanup(self) -> None:
        self.evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        _json(self.folder / "evidence.json", self.evidence)


def _unit_vector(dimension: int, seed: int) -> list[float]:
    raw = [
        math.sin((index + 1) * (seed + 0.37)) + math.cos((index + 1) * 0.13) / 3
        for index in range(dimension)
    ]
    norm = math.sqrt(sum(value * value for value in raw))
    return [struct.unpack("<f", struct.pack("<f", value / norm))[0] for value in raw]


def _vector_proof(vector) -> dict:
    values = list(vector)
    raw = struct.pack("<" + "f" * len(values), *values)
    return {
        "float32_sha256": hashlib.sha256(raw).hexdigest(),
        "dimensions": len(values),
        "first_8_float32_hex": [struct.pack("<f", value).hex() for value in values[:8]],
        "l2_norm": math.sqrt(sum(value * value for value in values)),
    }


def _catalog(
    identifier: str,
    *,
    domain_id: str,
    kind: Literal["concept", "entity"] = "entity",
    revision: int | None = 7,
):
    return CatalogRecord.create(
        domain_id=domain_id,
        ontology_version="fixture-v1",
        ontology_fingerprint="c" * 64,
        kind=kind,
        ref_kind="entity" if kind == "entity" else "class",
        ref_id=identifier,
        object_type="RecipeVariant",
        label=identifier,
        source_ids=["controlled-source-a"],
        graph_revision=revision,
    )


def _open_stores(owned: OwnedMilvus, dimension: int):
    fingerprint = digest(["restart-controlled", dimension, owned.token, INDEX_SCHEMA_VERSION])
    candidates = SemanticCandidateStore(
        collection_name=f"restart_candidates_{dimension}_{owned.token}",
        host="127.0.0.1",
        port=owned.grpc_port,
        dimension=dimension,
        embedding_model="restart-fixed-vector-fixture",
        embedding_fingerprint=fingerprint,
        timeout=RECOVERY_TIMEOUT,
        initialization_timeout=RECOVERY_TIMEOUT,
    )
    try:
        documents = VectorStore(
            collection_name=f"restart_documents_{dimension}_{owned.token}",
            host="127.0.0.1",
            port=owned.grpc_port,
            dimension=dimension,
            embedding_model="restart-fixed-vector-fixture",
            index_type="HNSW",
            metric_type="COSINE",
            timeout=RECOVERY_TIMEOUT,
        )
    except BaseException:
        candidates.close()
        raise
    return candidates, documents


def _write(stores, domain_id, dimension):
    candidates, documents = stores
    primary, second = _unit_vector(dimension, 2), _unit_vector(dimension, 5)
    records = [
        _catalog("recipe-primary", domain_id=domain_id),
        _catalog("recipe-second", domain_id=domain_id),
    ]
    other_domain = _catalog("other-domain", domain_id=domain_id + "-other")
    wrong_generation = _catalog("wrong-generation", domain_id=domain_id)
    concept = _catalog("class-recipe", domain_id=domain_id, kind="concept", revision=None)
    candidates.upsert("entity_current", records, [primary, second])
    candidates.upsert("entity_other_domain", [other_domain], [primary])
    candidates.upsert("entity_wrong_generation", [wrong_generation], [primary])
    candidates.upsert("concept_current", [concept], [second])
    chunks = [
        DocumentChunk(
            id=hashlib.sha256(f"chunk-{index}".encode()).hexdigest(),
            domain_id=domain_id if index < 2 else domain_id + "-other",
            source_id="controlled-source-a",
            source_version="source-version-a",
            ontology_version="fixture-v1",
            embedding_model=documents.embedding_model,
            chunk_index=index,
            content=f"Controlled document fixture {index}",
            uri="controlled:restart",
            entity_ids=["recipe-primary"],
        )
        for index in range(3)
    ]
    documents.upsert(chunks, [primary, second, primary])
    # Flush before a graceful process restart: this gate proves actual persistent
    # segments/index metadata and embedded-etcd recovery, not acknowledged WAL crash safety.
    candidates.collection.flush(timeout=30)
    documents.collection.flush(timeout=30)
    return records, chunks, primary


def _rows(store):
    fields = [field.name for field in store.collection.schema.fields]
    rows = store.collection.query(
        expr='id != ""',
        output_fields=fields,
        limit=100,
        consistency_level="Strong",
        timeout=RECOVERY_TIMEOUT,
    )
    return sorted(rows, key=lambda row: row["id"])


def _snapshot(stores, domain_id, dimension, records, chunks, query):
    candidates, documents = stores
    scope = IndexScope(
        domain_id=domain_id,
        ontology_version="fixture-v1",
        ontology_fingerprint="c" * 64,
        embedding_fingerprint=candidates.embedding_fingerprint,
        kind="entity",
    )
    checksum = catalog_checksum(records)
    verification = candidates.verify_generation(
        "entity_current", expected_count=2, expected_checksum=checksum
    )
    assert verification.valid and verification.count == 2
    hits = candidates.search(
        query,
        scope=scope,
        generation_id="entity_current",
        expected_types=["RecipeVariant"],
        top_k=10,
    )
    assert [item.ref_id for item in hits] == ["recipe-primary", "recipe-second"]
    assert hits[0].vector_score == pytest.approx(1.0, abs=2e-6)
    docs = documents.search(
        query,
        domain_id=domain_id,
        ontology_version="fixture-v1",
        source_versions={"controlled-source-a": "source-version-a"},
        entity_ids=["recipe-primary"],
        top_k=10,
    )
    assert [item["chunk"].id for item in docs] == [chunks[0].id, chunks[1].id]
    assert docs[0]["score"] == pytest.approx(1.0, abs=2e-6)
    assert (
        documents.search(
            query,
            domain_id=domain_id,
            ontology_version="fixture-v1",
            source_versions={"controlled-source-a": "different-version"},
            top_k=10,
        )
        == []
    )
    assert documents.existing_ids([chunk.id for chunk in chunks]) == {chunk.id for chunk in chunks}
    reusable = candidates.reusable_vectors(scope, [record.text_hash for record in records])
    assert len(reusable) == 2
    candidate_rows, document_rows = _rows(candidates), _rows(documents)
    assert len(candidate_rows) == 5 and len(document_rows) == 3
    # Convert protobuf float arrays into ordinary floats for a stable JSON proof.
    vector_bits = {
        kind: {row["id"]: _vector_proof(row["embedding"]) for row in rows}
        for kind, rows in (("candidates", candidate_rows), ("documents", document_rows))
    }
    for row in [*candidate_rows, *document_rows]:
        row["embedding"] = [float(value) for value in row["embedding"]]
    return {
        "dimension": dimension,
        "scope": scope.model_dump(),
        "generation_id": "entity_current",
        "verification": verification.model_dump(),
        "candidate_count": len(candidate_rows),
        "document_count": len(document_rows),
        "candidate_rows_checksum": digest(candidate_rows),
        "document_rows_checksum": digest(document_rows),
        "vector_bits": vector_bits,
        "candidate_query": [
            {
                "ref_id": hit.ref_id,
                "generation_id": hit.generation_id,
                "scope": hit.scope.model_dump(),
                "cosine": hit.vector_score,
            }
            for hit in hits
        ],
        "document_query": [
            {
                "id": item["chunk"].id,
                "source_id": item["chunk"].source_id,
                "source_version": item["chunk"].source_version,
                "entity_ids": item["chunk"].entity_ids,
                "cosine": item["score"],
            }
            for item in docs
        ],
        "reusable_float32": {key: _vector_proof(value) for key, value in reusable.items()},
    }


async def test_actual_milvus_restart_preserves_candidate_and_document_vectors():
    owned = OwnedMilvus()
    clients = []
    try:
        await owned.start()
        domain_id = "restart-fixture-" + owned.token
        written = {}
        before = []
        started = monotonic()
        for dimension in (3, 1536):
            stores = await asyncio.to_thread(_open_stores, owned, dimension)
            clients.extend(stores)
            records, chunks, query = await asyncio.to_thread(_write, stores, domain_id, dimension)
            written[dimension] = records, chunks, query
            before.append(
                await asyncio.to_thread(
                    _snapshot, stores, domain_id, dimension, records, chunks, query
                )
            )
        owned.evidence["timings_seconds"]["initial_write_and_verify"] = monotonic() - started
        _json(owned.folder / "before.json", before)
        for client in clients:
            await asyncio.to_thread(client.close)
        clients.clear()
        await owned.restart()
        after = []
        started = monotonic()
        for dimension in (3, 1536):
            stores = await asyncio.to_thread(_open_stores, owned, dimension)
            clients.extend(stores)
            records, chunks, query = written[dimension]
            after.append(
                await asyncio.to_thread(
                    _snapshot, stores, domain_id, dimension, records, chunks, query
                )
            )
        owned.evidence["timings_seconds"]["reopen_and_verify"] = monotonic() - started
        _json(owned.folder / "after.json", after)
        assert before == after
        owned.evidence.update(
            {
                "actual_restart_verified": True,
                "persisted_candidate_rows": sum(row["candidate_count"] for row in after),
                "persisted_document_rows": sum(row["document_count"] for row in after),
                "dimensions": [3, 1536],
                "before_sha256": digest(before),
                "after_sha256": digest(after),
                "vector_bits_identical": True,
                "scope_and_source_filters_preserved": True,
                "generation_checksums_preserved": True,
                "candidate_cosine_verified": True,
                "document_cosine_verified": True,
                "restart_kind": "graceful_process_restart_after_flush",
            }
        )
    finally:
        try:
            async with AsyncExitStack() as cleanup:
                for client in clients:
                    await cleanup.enter_async_context(
                        close_on_exit(partial(asyncio.to_thread, client.close))
                    )
        finally:
            owned.cleanup()

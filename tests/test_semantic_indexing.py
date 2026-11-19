"""Build snapshots reuse vectors and never publish partial or unstable catalogs."""

import asyncio
import hashlib
import importlib
import importlib.util
import json
import os
from contextlib import contextmanager, suppress
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Literal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from gustobot.domain.linking import (
    BuildIndexRequest,
    CatalogPage,
    CatalogRecord,
    GraphRevision,
    IndexVerification,
    catalog_checksum,
)
from gustobot.infrastructure.core.database import (
    Base,
    create_database_engine,
    migrate_database,
)
from gustobot.infrastructure.persistence.crud.semantic_index import (
    SemanticIndexRepository,
)
from gustobot.infrastructure.persistence.db.models.semantic_index import (
    SemanticIndexGeneration,
    SemanticIndexPublication,
)


def api():
    name = "gustobot.application.services.semantic_indexing"
    assert importlib.util.find_spec(name) is not None, "Semantic index builder is missing"
    return importlib.import_module(name)


def record(identifier="a", label="佛跳墙", *, revision=1, source="source-a", kind="entity"):
    return CatalogRecord.create(
        domain_id="recipes",
        ontology_version="v1",
        ontology_fingerprint="a" * 64,
        kind=kind,
        ref_kind="entity" if kind == "entity" else "class",
        ref_id=identifier,
        object_type="RecipeVariant",
        label=label,
        source_ids=[source],
        graph_revision=revision if kind == "entity" else None,
    )


class Graph:
    def __init__(self, records=()):
        self.records = list(records)
        self.revision = 1
        self.state: Literal["uninitialized", "initializing", "ready"] = "ready"
        self.mutate_during_export = False

    async def graph_revision(self):
        return GraphRevision(
            domain_id="recipes",
            ontology_version="v1",
            ontology_fingerprint="a" * 64,
            revision=self.revision if self.state == "ready" else None,
            state=self.state,
        )

    async def export_linking_records(self, *, after_id, limit):
        records = [item for item in self.records if after_id is None or item.ref_id > after_id][
            :limit
        ]
        if self.mutate_during_export:
            self.revision += 1
        return CatalogPage(
            records=records,
            observed_revision=self.revision,
            next_after_id=records[-1].ref_id if len(records) == limit else None,
        )


class Candidates:
    embedding_fingerprint = "b" * 64

    def __init__(self):
        self.rows = {}
        self.write_failure = False
        self.bad_verification = False

    def reusable_vectors(self, scope, text_hashes):
        wanted = set(text_hashes)
        return {
            item.text_hash: vector
            for rows in self.rows.values()
            for item, vector in rows.values()
            if item.text_hash in wanted
        }

    def upsert(self, generation_id, records, vectors):
        rows = self.rows.setdefault(generation_id, {})
        for item, vector in zip(records, vectors):
            rows[item.record_id] = (item, vector)
        if self.write_failure:
            raise OSError("candidate write interrupted")

    def verify_generation(self, generation_id, *, expected_count, expected_checksum):
        rows = self.rows.get(generation_id, {})
        checksum = catalog_checksum([item for item, _ in rows.values()])
        return IndexVerification(
            valid=not self.bad_verification
            and len(rows) == expected_count
            and checksum == expected_checksum,
            count=len(rows),
            checksum=checksum,
            schema_fingerprint="c" * 64,
        )

    def delete_generation(self, generation_id):
        self.rows.pop(generation_id, None)


class Embedder:
    def __init__(self):
        self.texts = []
        self.cancel = False

    async def aembed_documents(self, texts):
        self.texts.extend(texts)
        if self.cancel:
            raise asyncio.CancelledError
        return [[1.0, float(len(text))] for text in texts]


@pytest.fixture(params=["sqlite", "mysql"])
def setup(request):
    if request.param == "mysql":
        url = os.environ.get("GUSTOBOT_TEST_MYSQL_URL")
        if url is None:
            pytest.skip("An isolated MySQL URL must be explicitly supplied")
            return
        engine = create_database_engine(url)
        request.addfinalizer(engine.dispose)
        migrate_database(engine)
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        request.addfinalizer(engine.dispose)
        Base.metadata.create_all(engine)
    active = []

    @contextmanager
    def transaction():
        with Session(engine, expire_on_commit=False) as session, session.begin():
            active.append(session)
            try:
                yield session
            finally:
                active.remove(session)

    graph, candidates, embedder = (
        Graph([record(), record("b", "红烧肉")]),
        Candidates(),
        Embedder(),
    )
    if request.param == "mysql":
        candidates.embedding_fingerprint = uuid4().hex * 2
    domain = SimpleNamespace(
        id="recipes",
        version="v1",
        semantic_model=SimpleNamespace(
            fingerprint="a" * 64,
            linking_records=lambda: (record("class-1", kind="concept"),),
        ),
    )
    result = SimpleNamespace(
        engine=engine,
        transaction=transaction,
        active=active,
        graph=graph,
        candidates=candidates,
        embedder=embedder,
        domain=domain,
    )
    try:
        yield result
    finally:
        if request.param == "mysql":
            with engine.begin() as connection:
                connection.execute(
                    delete(SemanticIndexPublication).where(
                        SemanticIndexPublication.embedding_fingerprint
                        == candidates.embedding_fingerprint
                    )
                )
                connection.execute(
                    delete(SemanticIndexGeneration).where(
                        SemanticIndexGeneration.scope_json["embedding_fingerprint"].as_string()
                        == candidates.embedding_fingerprint
                    )
                )


def service(setup, **options):
    return api().SemanticIndexingService(
        setup.domain,
        graph_store=setup.graph,
        candidate_store=setup.candidates,
        embedder=setup.embedder,
        session_factory=setup.transaction,
        **options,
    )


def generation(setup, identifier):
    with setup.transaction() as session:
        return SemanticIndexRepository(session).get_generation(identifier)


@pytest.mark.asyncio
async def test_same_scope_and_revision_repeats_without_embedding_or_rewriting(setup):
    builder = service(setup)
    request = BuildIndexRequest(scope=builder.scope("entity"), batch_size=1, publish=True)
    first = await builder.build(request)
    repeated = await builder.build(request)
    assert first.status == repeated.status == "active"
    assert first.generation_id == repeated.generation_id
    assert len(setup.embedder.texts) == 2
    assert first.exported == 2 and first.embedded == 2


@pytest.mark.asyncio
async def test_text_changes_embed_only_new_text_and_metadata_changes_reuse(setup):
    builder = service(setup)
    scope = builder.scope("entity")
    first = await builder.build(BuildIndexRequest(scope=scope, publish=True))
    setup.graph.revision = 2
    setup.graph.records = [
        record(label="家庭佛跳墙", revision=2),
        record("b", "红烧肉", revision=2, source="different"),
    ]
    second = await builder.build(
        BuildIndexRequest(scope=scope, publish=True, expected_active_generation=first.generation_id)
    )
    assert second.status == "active" and second.embedded == 1 and second.reused == 1
    assert len(setup.embedder.texts) == 3
    assert generation(setup, first.generation_id).status == "retired"


@pytest.mark.asyncio
async def test_duplicate_text_is_embedded_once_but_each_real_id_is_stored(setup):
    setup.graph.records = [record("a"), record("b")]
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), batch_size=1))
    assert receipt.status == "ready" and receipt.exported == 2 and receipt.embedded == 1
    assert len(setup.embedder.texts) == 1
    assert len(setup.candidates.rows[receipt.generation_id]) == 2
    assert (await builder.status(builder.scope("entity"))).generation_id is None


@pytest.mark.asyncio
async def test_empty_catalog_requires_attested_ready_graph_and_publishes_zero(setup):
    builder = service(setup)
    setup.graph.records = []
    setup.graph.state = "uninitialized"
    with pytest.raises(RuntimeError, match="ready|initialized"):
        await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    setup.graph.state, setup.graph.revision = "ready", 0
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    assert receipt.status == "active" and receipt.exported == receipt.embedded == 0
    assert receipt.graph_revision == 0


@pytest.mark.asyncio
async def test_graph_write_during_export_supersedes_incomplete_generation(setup):
    setup.graph.mutate_during_export = True
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    assert receipt.status == "superseded"
    assert generation(setup, receipt.generation_id).error
    assert (await builder.status(builder.scope("entity"))).generation_id is None


@pytest.mark.asyncio
async def test_interrupted_write_resumes_same_generation_and_reuses_completed_vectors(
    setup,
):
    builder = service(setup)
    request = BuildIndexRequest(scope=builder.scope("entity"), publish=True)
    setup.candidates.write_failure = True
    failed = await builder.build(request)
    assert failed.status == "failed"
    assert generation(setup, failed.generation_id).status == "failed"
    assert failed.embedded == 2 and failed.error == "candidate write: OSError"
    setup.candidates.write_failure = False
    retry = await builder.build(request)
    assert retry.status == "active" and retry.generation_id == failed.generation_id
    assert retry.embedded == 2 and retry.reused == 2
    assert len(setup.embedder.texts) == 2


@pytest.mark.asyncio
async def test_actual_row_checksum_mismatch_never_becomes_ready(setup):
    setup.candidates.bad_verification = True
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    assert receipt.status == "failed"
    assert (await builder.status(builder.scope("entity"))).generation_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("vectors", [[], [[], []], [[float("nan")], [1.0]]])
async def test_invalid_embedding_response_fails_before_writing_candidates(setup, vectors):
    async def invalid_embeddings(texts):
        return vectors

    setup.embedder.aembed_documents = invalid_embeddings
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    assert receipt.status == "failed" and receipt.error == "embedding: ValueError"
    assert receipt.embedded == 0 and setup.candidates.rows == {}
    assert (await builder.status(builder.scope("entity"))).generation_id is None


@pytest.mark.asyncio
async def test_cancellation_is_durable_and_propagates_to_caller(setup):
    setup.embedder.cancel = True
    builder = service(setup)
    with pytest.raises(asyncio.CancelledError):
        await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    with setup.transaction() as session:
        rows = SemanticIndexRepository(session).list_generations(builder.scope("entity"))
        assert len(rows) == 1 and rows[0].status == "failed" and rows[0].error == "cancelled"


@pytest.mark.asyncio
async def test_expired_lease_fails_build_and_network_calls_hold_no_database_transaction(
    setup,
):
    now = datetime(2026, 11, 16)

    class SlowEmbedder(Embedder):
        async def aembed_documents(self, texts):
            nonlocal now
            assert setup.active == []
            now += timedelta(seconds=11)
            return await super().aembed_documents(texts)

    setup.embedder = SlowEmbedder()
    builder = service(setup, lease_seconds=10, clock=lambda: now)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    assert receipt.status == "failed" and "lease" in receipt.error.casefold()


@pytest.mark.asyncio
async def test_cas_conflict_is_superseded_and_current_active_is_preserved(setup):
    builder = service(setup)
    first = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    setup.graph.revision = 2
    setup.graph.records = [record(revision=2)]
    conflict = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    assert conflict.status == "superseded"
    assert (await builder.status(builder.scope("entity"))).generation_id == first.generation_id


@pytest.mark.asyncio
async def test_concepts_do_not_read_graph_and_active_retirement_is_rejected(setup):
    setup.graph.state = "uninitialized"
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("concept"), publish=True))
    assert receipt.status == "active" and receipt.graph_revision is None
    with pytest.raises(ValueError, match="active"):
        await builder.retire(receipt.generation_id)


@pytest.mark.asyncio
async def test_graph_write_after_vectors_are_written_supersedes_before_publication(
    setup,
):
    original = setup.candidates.upsert

    def write(*args):
        original(*args)
        setup.graph.revision += 1

    setup.candidates.upsert = write
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    assert receipt.status == "superseded"
    assert setup.candidates.rows[receipt.generation_id]
    assert (await builder.status(builder.scope("entity"))).generation_id is None


@pytest.mark.asyncio
async def test_second_worker_cannot_duplicate_embedding_while_first_lease_is_live(
    setup,
):
    from gustobot.infrastructure.persistence.crud.semantic_index import (
        BuildLeaseConflict,
    )

    entered, release = asyncio.Event(), asyncio.Event()

    class BlockingEmbedder(Embedder):
        async def aembed_documents(self, texts):
            entered.set()
            await release.wait()
            return await super().aembed_documents(texts)

    setup.embedder = BlockingEmbedder()
    first, second = service(setup, owner="worker-a"), service(setup, owner="worker-b")
    request = BuildIndexRequest(scope=first.scope("entity"), publish=True)
    task = asyncio.create_task(first.build(request))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        with pytest.raises(BuildLeaseConflict):
            await second.build(request)
    finally:
        release.set()
        receipt = await task
    assert receipt.status == "active" and len(setup.embedder.texts) == 2


@pytest.mark.asyncio
async def test_publication_commit_response_loss_is_recovered_from_authoritative_pointer(
    setup,
):
    lost = False

    @contextmanager
    def response_loss():
        nonlocal lost
        disconnect = False
        with setup.transaction() as session:
            yield session
            if not lost and any(
                row.status == "active"
                for row in SemanticIndexRepository(session).list_generations(
                    builder.scope("entity")
                )
            ):
                lost = disconnect = True
        if disconnect:
            raise OSError("publication commit response lost")

    builder = api().SemanticIndexingService(
        setup.domain,
        graph_store=setup.graph,
        candidate_store=setup.candidates,
        embedder=setup.embedder,
        session_factory=response_loss,
    )
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    assert lost and receipt.status == "active"
    assert generation(setup, receipt.generation_id).status == "active"


def cli_api():
    name = "scripts.build_semantic_index"
    assert importlib.util.find_spec(name) is not None, "Semantic index CLI is missing"
    return importlib.import_module(name)


@pytest.mark.asyncio
async def test_cli_audits_by_default_and_always_closes_runtime(monkeypatch):
    cli = cli_api()
    calls = []

    class Builder:
        async def bootstrap(self, *, audit_only):
            calls.append(audit_only)
            return SimpleNamespace(
                invalid=0,
                unknown_version=0,
                errors=[],
                model_dump_json=lambda: '{"validated":0}',
            )

    async def close():
        calls.append("closed")

    monkeypatch.setattr(cli, "create_service", lambda: Builder())
    monkeypatch.setattr(cli, "close_resources", close)
    assert await cli.execute(cli.parser().parse_args(["bootstrap"])) == 0
    assert calls == [True, "closed"]
    assert await cli.execute(cli.parser().parse_args(["bootstrap", "--apply-scope"])) == 0
    assert calls[-2:] == [False, "closed"]


@pytest.mark.asyncio
async def test_cli_returns_nonzero_for_superseded_build_and_cleans_up(setup, monkeypatch):
    cli = cli_api()
    setup.graph.mutate_during_export = True
    builder = service(setup)
    closed = []

    async def close():
        closed.append(True)

    monkeypatch.setattr(cli, "create_service", lambda: builder)
    monkeypatch.setattr(cli, "close_resources", close)
    assert (
        await cli.execute(cli.parser().parse_args(["build", "--kind", "entity", "--publish"])) == 1
    )
    assert closed == [True]


@pytest.mark.asyncio
async def test_watch_waits_for_quiet_revision_and_uses_normal_build(setup):
    cli = cli_api()
    builder = service(setup)
    time = 0.0
    iterations = 0

    async def sleep(seconds):
        nonlocal time, iterations
        time += seconds
        iterations += 1
        if iterations == 1:
            setup.graph.revision = 2
            setup.graph.records = [record(revision=2)]
        if iterations == 4:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await cli.watch(
            builder,
            kinds=("entity",),
            poll_seconds=5,
            quiet_seconds=5,
            sleep=sleep,
            clock=lambda: time,
        )
    assert len(setup.embedder.texts) == 1
    current = await builder.status(builder.scope("entity"))
    assert current.status == "ready" and current.graph_revision == 2


@pytest.mark.asyncio
async def test_lazy_bootstrap_and_status_do_not_initialize_vectors_or_provider(setup):
    calls = []

    async def bootstrap(*, audit_only):
        assert audit_only
        return "audit report"

    setup.graph.bootstrap_graph_scope = bootstrap

    def graph():
        calls.append("graph")
        return setup.graph

    def candidates():
        raise AssertionError("status and audit must not initialize Milvus")

    def embedder():
        raise AssertionError("status and audit must not initialize the provider")

    builder = api().SemanticIndexingService(
        setup.domain,
        graph_store=graph,
        candidate_store=candidates,
        embedder=embedder,
        session_factory=setup.transaction,
        embedding_fingerprint=setup.candidates.embedding_fingerprint,
    )
    assert calls == []
    assert await builder.bootstrap() == "audit report"
    assert (await builder.status(builder.scope("concept"))).status == "missing"
    assert (await builder.status(builder.scope("entity"))).status == "missing"
    assert calls == ["graph"]


@pytest.mark.asyncio
async def test_lazy_concept_build_never_initializes_graph_and_resolves_other_clients_once(
    setup,
):
    calls = []

    def graph():
        raise AssertionError("Concepts have no graph revision dependency")

    def candidates():
        calls.append("candidates")
        return setup.candidates

    def embedder():
        calls.append("embedder")
        return setup.embedder

    builder = api().SemanticIndexingService(
        setup.domain,
        graph_store=graph,
        candidate_store=candidates,
        embedder=embedder,
        session_factory=setup.transaction,
        embedding_fingerprint=setup.candidates.embedding_fingerprint,
    )
    request = BuildIndexRequest(scope=builder.scope("concept"), publish=True)
    assert (await builder.build(request)).status == "active"
    assert (await builder.build(request)).status == "active"
    assert calls == ["candidates", "embedder"]


@pytest.mark.asyncio
async def test_all_external_build_io_runs_outside_metadata_transactions(setup):
    stages = set()

    def check_sync(name, operation):
        def checked(*args, **kwargs):
            assert setup.active == []
            stages.add(name)
            return operation(*args, **kwargs)

        return checked

    def check_async(name, operation):
        async def checked(*args, **kwargs):
            assert setup.active == []
            stages.add(name)
            return await operation(*args, **kwargs)

        return checked

    for name in ("graph_revision", "export_linking_records"):
        setattr(setup.graph, name, check_async(name, getattr(setup.graph, name)))
    for name in ("reusable_vectors", "upsert", "verify_generation"):
        setattr(setup.candidates, name, check_sync(name, getattr(setup.candidates, name)))
    setup.embedder.aembed_documents = check_async("embedding", setup.embedder.aembed_documents)
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    assert receipt.status == "active"
    assert stages == {
        "graph_revision",
        "export_linking_records",
        "reusable_vectors",
        "upsert",
        "verify_generation",
        "embedding",
    }


@pytest.mark.asyncio
async def test_watch_limits_retries_after_failed_verification(setup, capsys):
    cli = cli_api()
    setup.candidates.bad_verification = True
    builder = service(setup)
    time, polls = 0.0, 0

    async def sleep(seconds):
        nonlocal time, polls
        time += seconds
        polls += 1
        if polls == 4:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await cli.watch(
            builder,
            kinds=("entity",),
            poll_seconds=5,
            quiet_seconds=5,
            sleep=sleep,
            clock=lambda: time,
        )
    assert capsys.readouterr().out.count('"status":"failed"') == 1
    with setup.transaction() as session:
        rows = SemanticIndexRepository(session).list_generations(builder.scope("entity"))
        assert len(rows) == 1 and rows[0].status == "failed"


@pytest.mark.asyncio
async def test_graph_change_after_ready_before_pointer_switch_is_superseded(setup):
    reads = 0
    original = setup.graph.graph_revision

    async def revision():
        nonlocal reads
        reads += 1
        if reads == 3:
            setup.graph.revision = 2
        return await original()

    setup.graph.graph_revision = revision
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    assert receipt.status == "superseded" and reads == 3


@pytest.mark.asyncio
async def test_cancelled_old_worker_preserves_resumed_owner_and_still_propagates_cancellation(
    setup,
):
    entered = asyncio.Event()
    now = datetime(2026, 11, 17)

    class WaitingEmbedder(Embedder):
        async def aembed_documents(self, texts):
            entered.set()
            await asyncio.Event().wait()

    setup.embedder = WaitingEmbedder()
    builder = service(setup, owner="old-owner", lease_seconds=10, clock=lambda: now)
    scope = builder.scope("entity")
    task = asyncio.create_task(builder.build(BuildIndexRequest(scope=scope, publish=True)))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        with setup.transaction() as session:
            resumed = SemanticIndexRepository(session).claim_build(
                scope,
                graph_revision=1,
                owner="new-owner",
                now=now + timedelta(seconds=11),
                lease_seconds=10,
            )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    current = generation(setup, resumed.generation_id)
    assert current.owner == "new-owner" and current.status == "building"
    assert (await builder.status(builder.scope("entity"))).generation_id is None


@pytest.mark.asyncio
async def test_calibration_reads_validated_report_before_transaction_and_preserves_active_vectors(
    setup, tmp_path, monkeypatch
):
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    counts = (len(setup.embedder.texts), len(setup.candidates.rows))
    payload = {
        "scope": builder.scope("entity").model_dump(),
        "generation_id": receipt.generation_id,
        "graph_revision": 1,
        "calibration": {
            "dataset_hash": "d" * 64,
            "policy": {"min_cosine": 0.8, "margin": 0.1},
        },
    }
    path = tmp_path / "approved-calibration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    evaluator = importlib.import_module("scripts.evaluate_knowledge")
    validated = []

    def verify(report):
        assert setup.active == []
        validated.append(report)
        return report

    monkeypatch.setattr(evaluator, "validate_approved_calibration_report", verify, raising=False)
    status = await builder.calibrate(receipt.generation_id, path)
    assert status.calibration_id == hashlib.sha256(path.read_bytes()).hexdigest()
    assert status.policy == {"min_cosine": 0.8, "margin": 0.1, "dataset_hash": "d" * 64}
    assert counts == (len(setup.embedder.texts), len(setup.candidates.rows)) and len(validated) == 1
    setup.graph.revision = 2
    with pytest.raises(RuntimeError, match="revision"):
        await builder.calibrate(receipt.generation_id, path)
    assert (await builder.status(builder.scope("entity"))).calibration_id == status.calibration_id


@pytest.mark.asyncio
async def test_calibration_rejects_protocol_invalid_and_wrong_generation_reports_without_writes(
    setup, tmp_path, monkeypatch
):
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("concept"), publish=True))
    path = tmp_path / "untrusted.json"
    path.write_text('{"provider_kind":"protocol","publication_ready":true}', encoding="utf-8")
    evaluator = importlib.import_module("scripts.evaluate_knowledge")

    def reject(report):
        raise ValueError("unapproved report")

    monkeypatch.setattr(evaluator, "validate_approved_calibration_report", reject, raising=False)
    with pytest.raises(ValueError, match="unapproved"):
        await builder.calibrate(receipt.generation_id, path)
    assert (await builder.status(builder.scope("concept"))).calibration_id is None


@pytest.mark.asyncio
async def test_cli_calibrate_passes_exact_generation_and_report_and_always_closes_runtime(
    setup, tmp_path, monkeypatch
):
    cli = cli_api()
    calls: list[object] = []
    selected_scope = service(setup).scope("entity")
    from gustobot.domain.linking import IndexPublicationStatus

    class Builder:
        async def calibrate(self, identifier, report_path, *, expected_active_generation):
            calls.append((identifier, report_path, expected_active_generation))
            return IndexPublicationStatus(
                scope=selected_scope, generation_id=identifier, status="ready"
            )

    async def close():
        calls.append("closed")

    path = tmp_path / "report.json"
    monkeypatch.setattr(cli, "create_service", lambda: Builder())
    monkeypatch.setattr(cli, "close_resources", close)
    args = cli.parser().parse_args(
        [
            "calibrate",
            "--generation",
            "active",
            "--report",
            str(path),
            "--expected-active-generation",
            "active",
        ]
    )
    assert await cli.execute(args) == 0
    assert calls == [("active", path, "active"), "closed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("generation_id", "other"), ("graph_revision", 99)])
async def test_calibration_report_binding_is_checked_against_current_generation(
    setup, tmp_path, monkeypatch, field, value
):
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    payload = {
        "scope": builder.scope("entity").model_dump(),
        "generation_id": receipt.generation_id,
        "graph_revision": 1,
        "calibration": {
            "dataset_hash": "d" * 64,
            "policy": {"min_cosine": 0.8, "margin": 0.1},
        },
    }
    payload[field] = value
    path = tmp_path / "wrong-binding.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    evaluator = importlib.import_module("scripts.evaluate_knowledge")
    monkeypatch.setattr(evaluator, "validate_approved_calibration_report", lambda report: report)
    with pytest.raises(ValueError):
        await builder.calibrate(receipt.generation_id, path)
    assert (await builder.status(builder.scope("entity"))).calibration_id is None


@pytest.mark.asyncio
async def test_actual_evaluator_rejects_protocol_publication_flag_before_metadata_changes(
    setup, tmp_path
):
    builder = service(setup)
    receipt = await builder.build(BuildIndexRequest(scope=builder.scope("entity"), publish=True))
    path = tmp_path / "protocol.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "knowledge-approved-calibration-v1",
                "publication_ready": True,
                "provider_kind": "protocol",
                "scope": builder.scope("entity").model_dump(),
                "generation_id": receipt.generation_id,
                "evidence": {
                    "calibration_report": {"provider_kind": "protocol"},
                    "heldout_report": {"provider_kind": "protocol"},
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        await builder.calibrate(receipt.generation_id, path)
    assert (await builder.status(builder.scope("entity"))).calibration_id is None

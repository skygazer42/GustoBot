"""Actual three-store index publication and identity binding, with protocol embeddings."""

import json
import os
from contextlib import AsyncExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pymilvus import connections, utility
from sqlalchemy import delete
from sqlalchemy.orm import Session

from gustobot.application.services.entity_linking import EntityLinkingService
from gustobot.application.services.knowledge_query import KnowledgeQueryService
from gustobot.application.services.semantic_indexing import SemanticIndexingService
from gustobot.domain.linking import (
    BuildIndexRequest,
    CandidateKind,
    embedding_fingerprint,
)
from gustobot.infrastructure.core.database import (
    create_database_engine,
    migrate_database,
)
from gustobot.infrastructure.knowledge.embeddings import OpenAICompatibleEmbeddings
from gustobot.infrastructure.knowledge.semantic_index import SemanticCandidateStore
from gustobot.infrastructure.persistence.crud.semantic_index import (
    SemanticIndexRepository,
)
from gustobot.infrastructure.persistence.db.models.semantic_index import (
    SemanticIndexGeneration,
    SemanticIndexPublication,
)
from tests.test_linking_catalog import (
    formal_model as formal_model,  # noqa: PLC0414 - pytest fixture
)
from tests.test_linking_catalog import (
    linking_graph as linking_graph,  # noqa: PLC0414 - pytest fixture
)

CANDIDATE_KINDS: tuple[CandidateKind, CandidateKind] = ("concept", "entity")


@pytest.mark.asyncio
async def test_three_store_build_publish_link_query_update_and_rebuild(linking_graph):
    mysql_url = os.environ.get("GUSTOBOT_TEST_MYSQL_URL")
    milvus_path = os.environ.get("GUSTOBOT_MILVUS_TEST_CONFIG")
    if mysql_url is None or milvus_path is None:
        pytest.skip("Explicit isolated MySQL and Milvus configuration required")
    assert mysql_url is not None and milvus_path is not None
    scope = linking_graph
    await scope.store.upsert(scope.quick)
    token = uuid4().hex
    model = replace(scope.domain.semantic_model, id=scope.domain.id)
    domain = scope.domain.model_copy()
    domain._semantic_model = model
    async with AsyncExitStack() as cleanup:
        engine = create_database_engine(mysql_url)
        cleanup.callback(engine.dispose)
        migrate_database(engine)

        @contextmanager
        def sessions():
            with Session(engine) as session, session.begin():
                yield session

        def publication(index_scope):
            with sessions() as session:
                return SemanticIndexRepository(session).publication_status(index_scope)

        def response(request):
            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": index, "embedding": [1.0, 0.0]}
                        for index, _ in enumerate(payload["input"])
                    ]
                },
            )

        fingerprint = embedding_fingerprint(
            provider="protocol",
            base_url="https://fixture.invalid/v1",
            model="fixture",
            revision=token,
            dimension=2,
        )
        http_client = httpx.Client(transport=httpx.MockTransport(response))
        cleanup.callback(http_client.close)
        embedder = OpenAICompatibleEmbeddings(
            model="fixture",
            api_key="fixture",
            dimension=2,
            purpose="build",
            http_client=http_client,
        )
        cleanup.callback(embedder.close)
        config = json.loads(Path(milvus_path).read_text(encoding="utf-8"))
        name = "three_store_candidates_" + token
        candidates = SemanticCandidateStore(
            collection_name=name,
            host=config["host"],
            port=config["port"],
            dimension=2,
            embedding_model="fixture",
            embedding_fingerprint=fingerprint,
        )
        cleanup.callback(candidates.close)

        def remove_candidate_collection():
            alias = "cleanup_" + token
            try:
                connections.connect(
                    alias=alias, host=config["host"], port=config["port"], timeout=30
                )
                utility.drop_collection(name, using=alias, timeout=30)
            finally:
                connections.disconnect(alias)

        cleanup.callback(remove_candidate_collection)
        builder = SemanticIndexingService(
            domain,
            graph_store=scope.store,
            candidate_store=candidates,
            embedder=embedder,
            session_factory=sessions,
            embedding_fingerprint=fingerprint,
        )
        generations = []

        def remove_metadata():
            with sessions() as session:
                session.execute(
                    delete(SemanticIndexPublication).where(
                        SemanticIndexPublication.domain_id == domain.id
                    )
                )
                session.execute(
                    delete(SemanticIndexGeneration).where(
                        SemanticIndexGeneration.scope_key.in_(
                            [builder.scope(kind).key for kind in CANDIDATE_KINDS]
                        )
                    )
                )

        cleanup.callback(remove_metadata)
        for kind in CANDIDATE_KINDS:
            receipt = await builder.build(
                BuildIndexRequest(scope=builder.scope(kind), publish=True)
            )
            generations.append(receipt.generation_id)
            assert receipt.status == "active" and receipt.exported > 0
            with sessions() as session:
                row = SemanticIndexRepository(session).get_generation(receipt.generation_id)
                assert row is not None
                assert candidates.verify_generation(
                    row.generation_id,
                    expected_count=row.expected_count,
                    expected_checksum=row.checksum,
                ).valid
                # Protocol policy only enables controlled integration behavior; not a release calibration.
                pointer = SemanticIndexRepository(session).get_publication(builder.scope(kind))
                assert pointer is not None
                pointer.calibration_id = "protocol-integration-only"
                pointer.policy_json = {
                    "min_cosine": 0.5,
                    "margin": 0.01,
                    "dataset_hash": "a" * 64,
                }

        class Planner:
            def __init__(self):
                self.calls = 0

            def with_structured_output(self, *args, **kwargs):
                return self

            async def ainvoke(self, messages):
                self.calls += 1
                return {
                    "facts": True,
                    "entity_type": "RecipeVariant",
                    "entity_mentions": ["佛挑墙"],
                    "requests": [{"property": "ingredientQuantity", "target": "鸡肉"}],
                }

        planner = Planner()
        linker = EntityLinkingService(
            domain,
            graph_store=scope.store,
            candidate_store=candidates,
            embedder=embedder,
            scopes={kind: builder.scope(kind) for kind in CANDIDATE_KINDS},
            publication_provider=publication,
            mode="on",
            retrieval_deadline=10,
        )
        service = KnowledgeQueryService(
            domain,
            graph_store=scope.store,
            documents=None,
            model=planner,
            linker=linker,
        )
        answer = await service.answer("想知道佛挑墙中鸡肉的用量")
        assert "100" in answer.message and planner.calls == 1
        assert answer.metadata["linking"]["generation"]["entity"] == generations[-1]
        old = generations[-1]
        await scope.store.upsert(scope.slow)
        stale = await linker.prepare("佛挑墙", history=[], expected_types=["RecipeVariant"])
        assert stale.status in {"stale", "degraded", "unavailable"}
        rebuilt = await builder.build(
            BuildIndexRequest(
                scope=builder.scope("entity"),
                publish=True,
                expected_active_generation=old,
            )
        )
        generations.append(rebuilt.generation_id)
        assert rebuilt.status == "active" and rebuilt.generation_id != old
        with sessions() as session:
            previous = SemanticIndexRepository(session).get_generation(old)
            assert previous is not None and previous.status == "retired"
        # Name/alias path uses current facts even while the new generation awaits calibration.
        exact = await service.answer("佛跳墙加多少鸡肉？")
        assert exact.metadata["status"] == "needs_clarification"
        assert len(exact.metadata["choices"]) == 2

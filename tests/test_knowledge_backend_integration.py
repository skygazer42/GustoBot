"""Real MySQL + Neo4j + Milvus through HTTP, with explicit model protocol fixtures."""

import json
import os
from contextlib import AsyncExitStack, contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gustobot.application.services.knowledge_ingestion import KnowledgeIngestionService
from gustobot.application.services.knowledge_query import KnowledgeQueryService
from gustobot.config.domain import get_domain_definition
from gustobot.infrastructure.core.database import (
    create_database_engine,
    get_db,
    migrate_database,
)
from gustobot.infrastructure.knowledge.graph_store import Neo4jGraphStore
from gustobot.infrastructure.knowledge.knowledge_service import KnowledgeService
from gustobot.infrastructure.knowledge.vector_store import VectorStore
from gustobot.infrastructure.persistence.crud.knowledge import KnowledgeRepository
from gustobot.infrastructure.persistence.db.models import ChatMessage, ChatSession
from gustobot.infrastructure.persistence.db.models.knowledge import (
    IngestionJob,
    KnowledgeSource,
    UploadedAsset,
)
from gustobot.interfaces.http import knowledge_router
from gustobot.interfaces.http.v1 import chat, upload

pytestmark = pytest.mark.skipif(
    not all(
        os.environ.get(key)
        for key in (
            "GUSTOBOT_TEST_MYSQL_URL",
            "GUSTOBOT_TEST_NEO4J_CONFIG",
            "GUSTOBOT_TEST_MILVUS_PORT",
        )
    ),
    reason="Three isolated test stores must be supplied explicitly",
)


class FixtureEmbeddings:
    """Stable two-dimensional vectors exercise real index I/O, not semantic quality."""

    def __init__(self):
        self.batches = []

    def embed_documents(self, texts):
        self.batches.append(list(texts))
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]

    def close(self):
        pass


class FixtureModel:
    """The test verifies grounding and call counts; no external LLM is used."""

    def __init__(self):
        self.plans = 0
        self.answers = 0

    def with_structured_output(self, schema, **kwargs):
        instance = self

        class Planner:
            async def ainvoke(self, messages):
                instance.plans += 1
                return {
                    "facts": True,
                    "entity_type": "RecipeVariant",
                    "entity_mentions": ["佛跳墙"],
                    "requests": [{"property": "ingredientQuantity", "target": "糖"}],
                    "documents": True,
                    "document_query": "佛跳墙来历",
                }

        return Planner()

    async def ainvoke(self, messages):
        self.answers += 1
        evidence = str(messages[-1].content)
        assert "适量" in evidence and "测试来源记载" in evidence
        return AIMessage(content="该做法的糖为适量；来历见测试来源记载。")


@pytest.mark.asyncio
async def test_http_ingestion_publication_query_stream_and_ambiguity_with_real_stores(
    monkeypatch, tmp_path
):
    token = uuid4().hex
    # The source mapping binds the recipes ontology identity. The stores are
    # explicitly isolated test services; do not relabel the ontology in memory.
    domain = get_domain_definition()
    async with AsyncExitStack() as cleanup:
        engine = create_database_engine(os.environ["GUSTOBOT_TEST_MYSQL_URL"])
        cleanup.callback(engine.dispose)
        migrate_database(engine)
        neo4j = json.loads(
            Path(os.environ["GUSTOBOT_TEST_NEO4J_CONFIG"]).read_text(encoding="utf-8")
        )
        graph = Neo4jGraphStore(
            domain,
            **{key: neo4j[key] for key in ("uri", "user", "password", "database")},
        )
        cleanup.push_async_callback(graph.close)

        async def remove_graph_scope():
            async with graph._driver.session(database=graph.database) as graph_session:
                await graph_session.run(
                    "MATCH (n) WHERE n.domain_id=$domain DETACH DELETE n",
                    domain=domain.id,
                )

        cleanup.push_async_callback(remove_graph_scope)
        vectors = VectorStore(
            collection_name="http_integration_" + token,
            host=os.environ.get("GUSTOBOT_TEST_MILVUS_HOST", "127.0.0.1"),
            port=int(os.environ["GUSTOBOT_TEST_MILVUS_PORT"]),
            dimension=2,
            embedding_model="fixture-v1",
            index_type="FLAT",
        )
        cleanup.callback(vectors.close)
        cleanup.callback(vectors.collection.drop)
        embedder, model = FixtureEmbeddings(), FixtureModel()

        @contextmanager
        def sessions():
            with Session(engine) as session:
                try:
                    yield session
                    session.commit()
                except BaseException:
                    session.rollback()
                    raise

        def published():
            with Session(engine) as session:
                return KnowledgeRepository(session).published_versions(
                    domain.id, ontology_version=domain.version
                )

        documents = KnowledgeService(
            domain=domain,
            vector_store=vectors,
            embedder=embedder,
            embedding_model="fixture-v1",
            reranker=False,
            source_versions=published,
        )
        cleanup.push_async_callback(documents.close)
        ingestion = KnowledgeIngestionService(
            domain,
            documents=documents,
            graph_store=graph,
            session_factory=sessions,
            upload_root=tmp_path,
        )
        queries = KnowledgeQueryService(domain, graph_store=graph, documents=documents, model=model)
        app = FastAPI()
        app.include_router(knowledge_router.router, prefix="/api/v1")
        app.include_router(upload.router, prefix="/api/v1/upload")
        app.include_router(chat.router, prefix="/api/v1/chat")

        def database_dependency():
            with Session(engine) as session:
                yield session

        app.dependency_overrides[get_db] = database_dependency
        app.dependency_overrides[knowledge_router.get_ingestion_service] = lambda: (ingestion)
        app.dependency_overrides[knowledge_router.get_query_service] = lambda: queries
        monkeypatch.setattr(chat, "get_query_service", lambda: queries)
        monkeypatch.setattr(upload, "session_scope", sessions)
        monkeypatch.setattr(upload, "UPLOAD_DIR", tmp_path)
        session_ids: list[str] = []
        asset_ids: list[str] = []

        def remove_metadata():
            with sessions() as session:
                session.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids)))
                session.execute(delete(ChatSession).where(ChatSession.id.in_(session_ids)))
                session.execute(delete(UploadedAsset).where(UploadedAsset.id.in_(asset_ids)))
                session.execute(delete(IngestionJob).where(IngestionJob.domain_id == domain.id))
                session.execute(
                    delete(KnowledgeSource).where(KnowledgeSource.domain_id == domain.id)
                )

        cleanup.callback(remove_metadata)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://isolated-test"
        ) as client:
            recipe = {
                "name": "佛跳墙",
                "record": {
                    "辅料": [["糖", "适量"]],
                    "耗时": "两小时",
                    "做法": ["备料", "炖煮"],
                },
            }
            result = await client.post("/api/v1/knowledge/recipes", json=recipe)
            assert result.status_code == 201, result.text
            assert result.json()["status"] == "graph_ready"
            job = await client.get("/api/v1/knowledge/jobs/" + result.json()["job_id"])
            assert job.json()["status"] == "graph_ready"
            simple = await client.post("/api/v1/chat/", json={"message": "佛跳墙加多少糖？"})
            assert simple.status_code == 200, simple.text
            session_ids.append(simple.json()["session_id"])
            assert "适量" in simple.json()["message"]
            assert simple.json()["metadata"]["model_calls"] == 0
            anchors = await graph.resolve_entities("佛跳墙", entity_types=["RecipeVariant"])
            assert len(anchors) == 1
            uploaded = await client.post(
                "/api/v1/upload/file",
                files={
                    "file": (
                        "history.txt",
                        "测试来源记载：佛跳墙具有特定的地方饮食背景。".encode(),
                        "text/plain",
                    )
                },
            )
            assert uploaded.status_code == 200, uploaded.text
            asset_ids.append(uploaded.json()["asset_id"])
            assert not embedder.batches
            document_source_id = "history-" + token
            payload = {
                "asset_id": asset_ids[0],
                "source_id": document_source_id,
                "entity_ids": [anchors[0].id],
            }
            indexed = await client.post("/api/v1/knowledge/documents", json=payload)
            assert indexed.status_code == 201, indexed.text
            repeated = await client.post("/api/v1/knowledge/documents", json=payload)
            assert repeated.status_code == 201, repeated.text
            assert repeated.json()["details"]["document"]["embedded"] == 0
            assert len(embedder.batches) == 1
            combined = await client.post(
                "/api/v1/knowledge/query", json={"question": "介绍佛跳墙的糖用量和来历"}
            )
            assert combined.status_code == 200, combined.text
            answer = combined.json()
            assert answer["metadata"]["model_calls"] == 2
            assert {source["backend"] for source in answer["sources"]} == {
                "neo4j",
                "milvus",
            }
            assert model.plans == model.answers == 1
            with Session(engine) as session:
                messages = session.scalars(
                    select(ChatMessage).where(ChatMessage.session_id == session_ids[0])
                ).all()
                assert len(messages) == 2
            stream = await client.post(
                "/api/v1/chat/stream",
                json={"message": "佛跳墙加多少糖？", "session_id": session_ids[0]},
            )
            events = [
                json.loads(line[5:].strip())
                for line in stream.text.splitlines()
                if line.startswith("data:")
            ]
            assert events[-1]["type"] == "done"
            assert "适量" in events[-1]["message"]
            cleared = await client.delete("/api/v1/chat/session/" + session_ids[0])
            assert cleared.status_code == 200
            assert (await client.get("/api/v1/chat/history/" + session_ids[0])).json() == []
            withdrawn = await client.delete("/api/v1/knowledge/sources/" + document_source_id)
            assert withdrawn.status_code == 200
            assert await documents.search("佛跳墙") == []
            second = await client.post(
                "/api/v1/knowledge/recipes",
                json={"name": "佛跳墙", "record": {"辅料": [["糖", "10克"]]}},
            )
            assert second.status_code == 201, second.text
            ambiguous = await client.post("/api/v1/chat/", json={"message": "佛跳墙加多少糖？"})
            assert ambiguous.status_code == 200, ambiguous.text
            session_ids.append(ambiguous.json()["session_id"])
            assert ambiguous.json()["route"] == "clarification"
            assert ambiguous.json()["metadata"]["model_calls"] == 0
            choices = ambiguous.json()["metadata"]["choices"]
            chosen = await client.post(
                "/api/v1/chat/",
                json={"message": "第2份", "session_id": session_ids[-1]},
            )
            assert chosen.status_code == 200, chosen.text
            assert chosen.json()["route"] == "knowledge-query"
            assert chosen.json()["metadata"]["plan"]["anchor_ids"] == [choices[1]["id"]]
            assert chosen.json()["metadata"]["model_calls"] == 0

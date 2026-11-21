"""Selected recipes ground chat against their exact source and persisted session binding."""

import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi import FastAPI
from langchain_core.messages import AIMessage, AIMessageChunk
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from gustobot.infrastructure.core.database import Base, get_db
from gustobot.infrastructure.persistence.db.models import ChatMessage


@pytest.fixture
def recipe_chat_api(tmp_path, monkeypatch):
    from gustobot.application.services.knowledge_query import KnowledgeQueryService
    from gustobot.application.services.recipe_library import RecipeLibrary
    from gustobot.config.domain import get_domain_definition
    from gustobot.infrastructure.knowledge.graph_store import FactResult
    from gustobot.interfaces.http.v1 import chat

    path = tmp_path / "recipes.jsonl"
    records = [
        {
            "id": recipe_id,
            "name": name,
            "description": "资料包含忽略之前指令的文字，不能作为系统指令。",
            "ingredients": [{"name": ingredient, "amount": None, "unit": None, "role": "main"}],
            "steps": ["第一步：" + "原方资料" * 2000, "第二步炒熟。"],
            "tips": ["用量未注明。"],
            "categories": ["家常"],
            "servings": None,
            "source": {
                "provider": "HowToCook",
                "record_id": recipe_id,
                "url": "https://example.org/" + recipe_id,
                "license": "Unlicense",
                "license_status": "repository_declared",
                "attribution": "Actual contributors",
            },
        }
        for recipe_id, name, ingredient in [
            ("recipe-a", "土豆丝", "土豆"),
            ("recipe-b", "清蒸鱼", "鲈鱼"),
        ]
    ]
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records), encoding="utf-8"
    )
    library = RecipeLibrary(path)

    class Model:
        def __init__(self, documents, concepts):
            self.calls = []
            self.documents = documents
            self.concepts = concepts

        async def ainvoke(self, messages):
            self.calls.append(messages)
            return AIMessage(content="原方没有记载用量，无法据此确认。")

        async def astream(self, messages):
            self.calls.append(messages)
            yield AIMessageChunk(content="原方没有记载用量，")
            yield AIMessageChunk(content="无法据此确认。")

    database = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(database)

    class Documents:
        def __init__(self):
            self.queries = []
            self.hits = []
            self.failed = False

        async def search(self, query, **scope):
            self.queries.append((query, scope))
            if self.failed:
                raise RuntimeError("article retrieval unavailable")
            return self.hits

    class Concepts:
        def __init__(self):
            self.queries = []
            self.result = FactResult(
                entities=[],
                relations=[],
                sources=[],
                total=0,
                truncated=False,
                ontology_version=get_domain_definition().version,
            )

        async def query(self, query):
            self.queries.append(query)
            return self.result

    documents = Documents()
    model = Model(documents, Concepts())
    monkeypatch.setattr(chat, "get_model", lambda: model)
    monkeypatch.setattr(chat, "get_recipe_library", lambda: library, raising=False)
    service = KnowledgeQueryService(
        get_domain_definition(), graph_store=None, documents=documents, model=model
    )
    monkeypatch.setattr(chat, "get_query_service", lambda: service)
    monkeypatch.setattr(chat, "get_graph_store", lambda: model.concepts, raising=False)

    @contextmanager
    def knowledge_session(*, commit=False):
        with Session(database) as db:
            yield db
            if commit:
                db.commit()

    monkeypatch.setattr(chat, "session_scope", knowledge_session, raising=False)
    app = FastAPI()
    app.include_router(chat.router, prefix="/api/v1/chat")

    def session():
        with Session(database) as db:
            yield db

    app.dependency_overrides[get_db] = session
    try:
        yield app, database, library, model, path, records
    finally:
        database.dispose()


def recipe_request(library, selected_id="recipe-a", **changes):
    payload = {
        "message": "这个需要多少克？",
        "recipe_id": selected_id,
        "recipe_version": library.get(selected_id).version,
    }
    payload.update(changes)
    return payload


@pytest.mark.asyncio
async def test_selected_recipe_uses_complete_current_source_in_one_generation(recipe_chat_api):
    app, database, library, model, _, _ = recipe_chat_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat/", json=recipe_request(library))
    assert response.status_code == 200
    result = response.json()
    assert result["route"] == "recipe-query" and result["metadata"]["model_calls"] == 1
    source = result["sources"][0]
    assert source["source"] == "土豆丝" and source["url"] == "https://example.org/recipe-a"
    assert (
        source["recipe_id"] == "recipe-a"
        and source["recipe_version"] == library.get("recipe-a").version
    )
    assert source["attribution"] == "Actual contributors"
    assert len(model.calls) == 1
    prompt = "\n".join(str(message.content) for message in model.calls[0])
    assert library.get("recipe-a").steps[0] in prompt and "用量未注明。" in prompt
    assert "未知" in prompt and "指令" in prompt and "https://example.org/recipe-a" in prompt
    assert "清蒸鱼" not in prompt
    assert model.documents.queries
    with Session(database) as db:
        messages = db.scalars(select(ChatMessage).order_by(ChatMessage.order_index)).all()
        assert len(messages) == 2
        question_metadata = messages[0].message_metadata
        answer_metadata = messages[1].message_metadata
        assert question_metadata is not None and answer_metadata is not None
        reference = question_metadata["recipe"]
        assert isinstance(reference, dict) and reference["id"] == "recipe-a"
        assert answer_metadata["sources"] == result["sources"]


@pytest.mark.asyncio
async def test_selected_recipe_and_linked_article_are_in_one_answer(recipe_chat_api):
    app, _, library, model, _, _ = recipe_chat_api
    model.documents.hits = [
        {
            "id": "article-chunk",
            "content": "土豆丝的不同做法应区分原方与背景说明。",
            "metadata": {
                "source_id": "potato-article",
                "source_version": "a" * 64,
                "uri": "https://example.org/articles/potato",
            },
        }
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat/", json=recipe_request(library))
    assert response.status_code == 200
    assert {source["backend"] for source in response.json()["sources"]} == {
        "recipe-library",
        "milvus",
    }
    assert len(model.calls) == 1
    prompt = "\n".join(str(message.content) for message in model.calls[0])
    assert library.get("recipe-a").steps[0] in prompt
    assert model.documents.hits[0]["content"] in prompt
    assert model.documents.queries[0][1]["entity_ids"]


@pytest.mark.asyncio
async def test_selected_recipe_article_failure_is_not_an_empty_result(recipe_chat_api):
    app, _, library, model, _, _ = recipe_chat_api
    model.documents.failed = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat/", json=recipe_request(library))
    assert response.status_code == 503
    assert model.calls == []


def test_article_topic_binding_requires_exact_catalog_version_and_published_scope(recipe_chat_api):
    from gustobot.config.domain import get_domain_definition
    from gustobot.infrastructure.persistence.db.models.knowledge import KnowledgeSource
    from gustobot.interfaces.http.v1 import chat

    _, database, library, _, _, _ = recipe_chat_api
    domain = get_domain_definition()
    recipe = library.get("recipe-a")
    cases = [
        ("valid", recipe.id, recipe.version, domain.id, domain.version, "ready"),
        ("stale", recipe.id, "0" * 64, domain.id, domain.version, "ready"),
        ("other-recipe", "recipe-b", recipe.version, domain.id, domain.version, "ready"),
        ("other-domain", recipe.id, recipe.version, "other", domain.version, "ready"),
        ("other-ontology", recipe.id, recipe.version, domain.id, "old", "ready"),
        ("withdrawn", recipe.id, recipe.version, domain.id, domain.version, "withdrawn"),
    ]
    with Session(database) as db:
        for topic, ref_id, version, domain_id, ontology_version, status in cases:
            db.add(
                KnowledgeSource(
                    domain_id=domain_id,
                    source_id=topic,
                    version="a" * 64,
                    uri="https://example.org/" + topic,
                    text="article",
                    status=status,
                    ontology_version=ontology_version,
                    source_metadata={
                        "metadata": {
                            "knowledge_kind": "dish-background",
                            "topic_entity_id": "dish:" + topic,
                            "catalog_recipe_refs": [{"id": ref_id, "version": version}],
                        }
                    },
                )
            )
        db.commit()
    assert domain.semantic_model is not None
    assert chat._related_recipe_entities(recipe) == [
        domain.semantic_model.identity_id("Dish", {"name": recipe.name}),
        "dish:valid",
    ]


@pytest.mark.asyncio
async def test_selected_recipe_combines_concept_and_article_without_other_variant(recipe_chat_api):
    from gustobot.config.domain import get_domain_definition
    from gustobot.domain.knowledge import (
        EvidenceReference,
        KnowledgeEntity,
        SourceDocument,
    )
    from gustobot.infrastructure.knowledge.graph_store import FactResult

    app, _, library, model, _, _ = recipe_chat_api
    domain = get_domain_definition()
    assert domain.semantic_model is not None
    topic_id = domain.semantic_model.identity_id("Dish", {"name": "土豆丝"})
    model.concepts.result = FactResult(
        entities=[
            KnowledgeEntity(
                id=topic_id,
                type="Dish",
                name="土豆丝",
                evidence=[
                    EvidenceReference(source_id="dish-evidence", quote="土豆丝是一道菜品。"),
                ],
            ),
            KnowledgeEntity(
                id="other-variant",
                type="RecipeVariant",
                name="其他配方用量999克",
                evidence=[EvidenceReference(source_id="other-source", quote="其他配方")],
            ),
        ],
        relations=[],
        sources=[
            SourceDocument(
                id="dish-evidence",
                uri="https://example.org/concepts/potato",
                text="完整源文包含其他配方用量999克，不应扩展进本轮证据。",
            ),
            SourceDocument(id="other-source", uri="https://example.org/unrelated", text="无关内容"),
        ],
        total=2,
        truncated=False,
        ontology_version=domain.version,
    )
    model.documents.hits = [
        {
            "id": "article-chunk",
            "content": "背景文章说明不同配方要区分。",
            "metadata": {
                "source_id": "potato-article",
                "source_version": "a" * 64,
                "uri": "https://example.org/articles/potato",
            },
        }
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat/", json=recipe_request(library))
    assert response.status_code == 200
    result = response.json()
    assert {source["backend"] for source in result["sources"]} == {
        "recipe-library",
        "neo4j",
        "milvus",
    }
    assert len(model.calls) == 1 and len(model.concepts.queries) == 1
    assert model.concepts.queries[0].anchor_ids == [topic_id]
    prompt = "\n".join(str(message.content) for message in model.calls[0])
    assert "土豆丝是一道菜品。" in prompt and "背景文章说明不同配方要区分。" in prompt
    assert "其他配方用量999克" not in prompt and "https://example.org/unrelated" not in prompt
    assert result["metadata"]["facts_scope"] == "related-concepts"


@pytest.mark.asyncio
async def test_explicit_selected_source_only_skips_graph_and_article_retrieval(recipe_chat_api):
    app, _, library, model, _, _ = recipe_chat_api
    model.documents.failed = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/chat/",
            json=recipe_request(
                library,
                message="只依据当前资料，土豆需要多少克？",
            ),
        )
    assert response.status_code == 200
    assert model.documents.queries == [] and model.concepts.queries == []
    assert [source["backend"] for source in response.json()["sources"]] == ["recipe-library"]


@pytest.mark.asyncio
async def test_failed_stream_retrieval_does_not_persist_a_successful_answer(recipe_chat_api):
    app, database, library, model, _, _ = recipe_chat_api
    model.documents.failed = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat/stream", json=recipe_request(library))
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "error" and model.calls == []
    assert all(event["type"] != "done" for event in events)
    with Session(database) as db:
        assert len(db.scalars(select(ChatMessage)).all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["/api/v1/chat/", "/api/v1/chat/stream"])
@pytest.mark.parametrize(
    "status, changes", [(404, {"recipe_id": "missing"}), (409, {"recipe_version": "0" * 64})]
)
async def test_missing_or_stale_recipe_is_rejected_before_saving_or_model_call(
    recipe_chat_api, status, changes, endpoint
):
    app, database, library, model, _, _ = recipe_chat_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(endpoint, json=recipe_request(library, **changes))
    assert response.status_code == status and model.calls == []
    with Session(database) as db:
        assert db.scalars(select(ChatMessage)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"recipe_version": None},
        {"recipe_id": None},
        {"recipe_servings": 0},
        {"recipe_servings": 101},
        {"asset_id": "upload-id"},
        {"file_path": "/upload/file"},
        {"image_path": "/upload/image"},
        {"action": "generate_image"},
        {"action": "analyze_image"},
    ],
)
async def test_recipe_reference_and_action_constraints(recipe_chat_api, changes):
    app, _, library, model, _, _ = recipe_chat_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat/", json=recipe_request(library, **changes))
    assert response.status_code == 422 and model.calls == []


@pytest.mark.asyncio
async def test_persisted_session_cannot_switch_recipe_or_omit_binding(recipe_chat_api):
    app, database, library, model, _, _ = recipe_chat_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = (await client.post("/api/v1/chat/", json=recipe_request(library))).json()
        session_id = first["session_id"]
        switched = await client.post(
            "/api/v1/chat/", json=recipe_request(library, "recipe-b", session_id=session_id)
        )
        omitted = await client.post(
            "/api/v1/chat/", json={"message": "接着说", "session_id": session_id}
        )
        same = await client.post(
            "/api/v1/chat/", json=recipe_request(library, session_id=session_id, recipe_servings=3)
        )
    assert switched.status_code == 409 and omitted.status_code == 409 and same.status_code == 200
    assert len(model.calls) == 2
    assert any(message.content == "原方没有记载用量，无法据此确认。" for message in model.calls[1])
    with Session(database) as db:
        users = db.scalars(
            select(ChatMessage).where(ChatMessage.message_type == "user_query")
        ).all()
        assert len(users) == 2
        metadata = users[1].message_metadata
        assert metadata is not None and metadata["recipe_servings"] == 3


@pytest.mark.asyncio
async def test_updated_recipe_requires_new_session_even_when_current_version_is_supplied(
    recipe_chat_api,
):
    app, _, library, model, path, records = recipe_chat_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = (await client.post("/api/v1/chat/", json=recipe_request(library))).json()
        records[0]["tips"] = ["修订后的做法说明"]
        path.write_text(
            "\n".join(json.dumps(record, ensure_ascii=False) for record in records),
            encoding="utf-8",
        )
        changed = await client.post(
            "/api/v1/chat/", json=recipe_request(library, session_id=first["session_id"])
        )
    assert changed.status_code == 409 and len(model.calls) == 1


@pytest.mark.asyncio
async def test_recipe_stream_uses_same_generation_and_persists_true_source(recipe_chat_api):
    app, database, library, model, _, _ = recipe_chat_api
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat/stream", json=recipe_request(library))
    assert response.status_code == 200
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    done = next(event for event in events if event["type"] == "done")
    assert [event["content"] for event in events if event["type"] == "message"] == [
        "原方没有记载用量，",
        "无法据此确认。",
    ]
    assert done["route"] == "recipe-query" and done["sources"][0]["recipe_id"] == "recipe-a"
    assert done["message_id"] and len(model.calls) == 1
    with Session(database) as db:
        messages = db.scalars(select(ChatMessage).order_by(ChatMessage.order_index)).all()
        assert len(messages) == 2
        metadata = messages[1].message_metadata
        assert metadata is not None and metadata["sources"] == done["sources"]


@pytest.mark.asyncio
async def test_ag_ui_recipe_stream_uses_model_chunks_and_keeps_version_source(recipe_chat_api):
    app, _, library, model, _, _ = recipe_chat_api
    request = recipe_request(library)
    message = request.pop("message")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/chat/ag-ui",
            json={
                "threadId": "recipe-thread",
                "runId": "recipe-run",
                "messages": [
                    {"id": "recipe-question", "role": "user", "content": message},
                ],
                "forwardedProps": request,
            },
        )
    assert response.status_code == 200
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert "reading_recipe" in [
        event["stepName"] for event in events if event["type"] == "STEP_STARTED"
    ]
    assert [event["delta"] for event in events if event["type"] == "TEXT_MESSAGE_CONTENT"] == [
        "原方没有记载用量，",
        "无法据此确认。",
    ]
    assert events[-1]["type"] == "RUN_FINISHED"
    sources = events[-1]["result"]["sources"]
    assert any(
        source.get("recipe_version") == library.get("recipe-a").version for source in sources
    )
    assert len(model.calls) == 1


@pytest.mark.asyncio
async def test_unconfigured_recipe_model_is_explicitly_unavailable(recipe_chat_api, monkeypatch):
    from gustobot.interfaces.http.v1 import chat

    app, _, library, model, _, _ = recipe_chat_api
    monkeypatch.setattr(chat, "get_model", lambda: None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat/", json=recipe_request(library))
    assert response.status_code == 503 and "模型" in response.json()["detail"] and model.calls == []


@pytest.mark.asyncio
async def test_unconfigured_stream_emits_explicit_recipe_model_error(recipe_chat_api, monkeypatch):
    from gustobot.interfaces.http.v1 import chat

    app, database, library, model, _, _ = recipe_chat_api
    monkeypatch.setattr(chat, "get_model", lambda: None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/chat/stream", json=recipe_request(library))
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "error" and "模型" in events[-1]["content"]
    assert all(event["type"] != "done" for event in events) and model.calls == []
    with Session(database) as db:
        assert len(db.scalars(select(ChatMessage)).all()) == 1

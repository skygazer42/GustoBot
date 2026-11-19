"""Offline LangChain wire and terminal contracts for the unified service."""

import asyncio
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from gustobot.application.services.ontology_service import OntologyService
from gustobot.domain.knowledge import DomainDefinition, SourceDocument


@pytest.mark.asyncio
async def test_fact_extraction_keeps_single_tool_calling_request_and_source_text():
    requests = []
    source = SourceDocument(id="manual", text='泵 A。原文 {"count": 0}。')
    domain = DomainDefinition.model_validate(
        {
            "id": "wire-contract",
            "name": "Equipment",
            "description": "Equipment records",
            "entity_types": {"Asset": {"description": "Equipment", "properties": {}}},
            "relation_types": {},
            "document_scope": "Equipment documents",
        }
    )
    payload = {
        "entities": [
            {
                "id": "pump-a",
                "type": "Asset",
                "name": "泵 A",
                "evidence": [{"source_id": "manual", "quote": "泵 A"}],
            }
        ],
        "relations": [],
    }

    def complete(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "id": "completion-contract",
                "object": "chat.completion",
                "created": 0,
                "model": "offline-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-contract",
                                    "type": "function",
                                    "function": {
                                        "name": body["tools"][0]["function"]["name"],
                                        "arguments": json.dumps(payload),
                                    },
                                }
                            ],
                        },
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(complete)) as client:
        async with httpx.AsyncClient(transport=httpx.MockTransport(complete)) as async_client:
            model = ChatOpenAI(
                model="offline-model",
                api_key="offline-test",
                base_url="https://model.test/v1",
                http_client=client,
                http_async_client=async_client,
                max_retries=0,
            )
            graph = await OntologyService(domain, model=model).extract([source])
    assert graph.entities[0].id == "pump-a"
    assert graph.sources == [source]
    assert len(requests) == 1
    body = requests[0]
    assert "response_format" not in body
    assert body["tool_choice"]["function"]["name"] == body["tools"][0]["function"]["name"]
    assert json.loads(body["messages"][1]["content"]) == source.model_dump()


@pytest.mark.asyncio
async def test_terminal_uses_shared_service_history_and_releases_runtime(monkeypatch, capsys):
    from gustobot.application.services.knowledge_query import KnowledgeAnswer

    module = importlib.import_module("gustobot.application.agents.main")
    calls = []
    metadata = {
        "choices": [{"id": "selected-recipe", "name": "佛跳墙"}],
        "plan": {"documents": True},
    }

    async def answer(question, *, history):
        calls.append((question, list(history)))
        return KnowledgeAnswer(message=f"answer to {question}", metadata=metadata)

    questions = iter(["first", "second", "quit"])
    cleanup = AsyncMock()
    monkeypatch.setattr(module, "get_query_service", lambda: SimpleNamespace(answer=answer))
    monkeypatch.setattr(module, "cleanup_runtime", cleanup)
    monkeypatch.setattr("builtins.input", lambda _: next(questions))
    await module.main()
    assert calls == [
        ("first", []),
        (
            "second",
            [
                HumanMessage(content="first"),
                AIMessage(
                    content="answer to first",
                    additional_kwargs={
                        "knowledge_choices": metadata["choices"],
                        "knowledge_plan": metadata["plan"],
                    },
                ),
            ],
        ),
    ]
    assert capsys.readouterr().out == "answer to first\nanswer to second\n"
    cleanup.assert_awaited_once()


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
@pytest.mark.asyncio
async def test_terminal_failure_and_cancellation_release_runtime(monkeypatch, error_type):
    module = importlib.import_module("gustobot.application.agents.main")
    failure = error_type("query interrupted")
    cleanup = AsyncMock()
    service = SimpleNamespace(answer=AsyncMock(side_effect=failure))
    monkeypatch.setattr(module, "get_query_service", lambda: service)
    monkeypatch.setattr(module, "cleanup_runtime", cleanup)
    monkeypatch.setattr("builtins.input", lambda _: "question")
    with pytest.raises(error_type) as raised:
        await module.main()
    assert raised.value is failure
    cleanup.assert_awaited_once()

"""Offline contracts for the LangChain 1.x migration."""

import importlib
import json
from types import SimpleNamespace
from typing import Any

import httpx
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_openai import ChatOpenAI
import pytest


COMPONENTS = "gustobot.application.agents.text2sql.components"


@pytest.mark.asyncio
@pytest.mark.parametrize("component", ["router", "guardrails", "query_analysis"])
async def test_structured_nodes_keep_tool_calling_wire_protocol(monkeypatch, component):
    requests = []
    payloads = {
        "router": {"type": "general-query", "logic": "general", "question": "hello"},
        "guardrails": {"decision": "end"},
        "query_analysis": {
            "query_intent": "count recipes",
            "required_tables": ["recipes"],
            "required_columns": ["id"],
        },
    }
    payload = payloads[component]

    def complete(request):
        body = json.loads(request.content)
        requests.append(body)
        message: dict[str, Any] = {"role": "assistant", "content": json.dumps(payload)}
        if "tools" in body:
            message.update(
                content=None,
                tool_calls=[
                    {
                        "id": "call_contract",
                        "type": "function",
                        "function": {
                            "name": body["tools"][0]["function"]["name"],
                            "arguments": json.dumps(payload),
                        },
                    }
                ],
            )
        return httpx.Response(
            200,
            json={
                "id": "completion_contract",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-4o-mini",
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(complete)) as client:
        async with httpx.AsyncClient(transport=httpx.MockTransport(complete)) as async_client:
            llm = ChatOpenAI(
                model="gpt-4o-mini",
                api_key="offline-test",
                base_url="https://model.test/v1",
                http_client=client,
                http_async_client=async_client,
                max_retries=0,
            )
            if component == "router":
                module = importlib.import_module("gustobot.application.agents.lg_builder")
                monkeypatch.setattr(module, "ChatOpenAI", lambda **_: llm)
                monkeypatch.setattr(
                    module,
                    "settings",
                    SimpleNamespace(
                        OPENAI_API_KEY="offline-test",
                        OPENAI_MODEL="gpt-4o-mini",
                        OPENAI_API_BASE="https://model.test/v1",
                        SQL_DATABASE_URL=None,
                    ),
                )
                state = module.AgentState(messages=[HumanMessage(content="hello")])
                result = await module.analyze_and_route_query(state, config={})
                assert result["router"].type == "general-query"
            elif component == "guardrails":
                module = importlib.import_module("gustobot.application.agents.lg_builder")
                monkeypatch.setattr(module, "ChatOpenAI", lambda **_: llm)
                state = module.AgentState(messages=[HumanMessage(content="unrelated request")])
                result = await module.get_additional_info(state, config={})
                assert "当前服务范围" in result["messages"][0].content
            else:
                module = importlib.import_module(f"{COMPONENTS}.query_analysis.node")
                result = await module.create_query_analysis_node(llm)(
                    {"question": "count recipes", "schema_context": {"tables": []}}
                )
                assert result["analysis"]["required_tables"] == ["recipes"]

    assert len(requests) == 1
    request_body = requests[0]
    assert "response_format" not in request_body
    assert request_body["tool_choice"]["function"]["name"] == (
        request_body["tools"][0]["function"]["name"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_calls",
    [[{"function": {"arguments": "RAW_TOOL_JSON"}}], [{"index": 0}]],
)
async def test_resumed_chat_prints_only_message_text(monkeypatch, capsys, tool_calls):
    module = importlib.import_module("gustobot.application.agents.main")
    calls = []

    class Graph:
        def get_state(self, config):
            return SimpleNamespace(
                values={"messages": []}, tasks=[SimpleNamespace(interrupts=[object()])]
            )

        async def astream(self, input, *, stream_mode, config):
            calls.append(input)
            if len(calls) == 1:
                yield AIMessageChunk(content="first "), {}
            else:
                yield AIMessageChunk(content="private plan"), {"tags": ["research_plan"]}
                yield AIMessageChunk(content="", additional_kwargs={"tool_calls": tool_calls}), {}
                yield AIMessageChunk(
                    content=[
                        {"type": "reasoning", "summary": []},
                        {"type": "text", "text": "resumed answer"},
                    ]
                ), {}

    monkeypatch.setattr(module, "graph", Graph())
    monkeypatch.setattr("builtins.input", lambda _: "y")
    await module.process_query("hello")
    assert len(calls) == 2
    assert calls[1].resume == "y"
    assert capsys.readouterr().out == "first resumed answer"


@pytest.mark.asyncio
@pytest.mark.parametrize("router_kind", ["model", "dict", "missing"])
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("answer", "answer"),
        (
            [
                {"type": "reasoning", "reasoning": "hidden"},
                {"type": "text", "text": "answer"},
            ],
            "answer",
        ),
        ([], ""),
    ],
)
async def test_http_chat_reads_router_and_message_contracts(
    monkeypatch, router_kind, content, expected
):
    module = importlib.import_module("gustobot.interfaces.http.v1.chat")
    states = importlib.import_module("gustobot.application.agents.lg_states")
    result: dict[str, Any] = {"messages": [AIMessage(content=content)]}
    if router_kind != "missing":
        route = states.Router(type="general-query", logic="mock")
        result["router"] = route if router_kind == "model" else route.model_dump()

    class Graph:
        async def ainvoke(self, input, *, config):
            assert isinstance(input, states.InputState)
            assert input.messages[0] == HumanMessage(content="hello")
            return result

    monkeypatch.setattr(module, "graph", Graph())
    monkeypatch.setattr(module, "settings", SimpleNamespace(INGEST_INCREMENTAL_DEFAULT=False))
    response = await module.process_agent_query("hello", "offline-session")

    assert response["message"] == expected
    assert response["route"] == (None if router_kind == "missing" else "general-query")
    assert response["route_logic"] == (None if router_kind == "missing" else "mock")
    assert response["metadata"]["session_id"] == "offline-session"


@pytest.mark.asyncio
async def test_routing_script_uses_graph_state_and_response_contracts(monkeypatch):
    monkeypatch.setenv("GUSTOBOT_RUN_INTEGRATION_TESTS", "1")
    module = importlib.import_module("tests.test_agent_routing")
    builder = importlib.import_module("gustobot.application.agents.lg_builder")
    states = importlib.import_module("gustobot.application.agents.lg_states")

    class Graph:
        async def ainvoke(self, input, *, config):
            assert isinstance(input, states.InputState)
            assert input.messages[0] == HumanMessage(content="hello")
            return {
                "router": states.Router(type="general-query", logic="mock"),
                "messages": [AIMessage(content=[{"type": "text", "text": "answer"}])],
            }

    monkeypatch.setattr(builder, "graph", Graph())
    case = module.RoutingTestCase("hello", "general-query", "general", "offline routing")
    result = await module.test_routing(case)
    assert result["status"] == "PASS"
    assert result["logic"] == "mock"
    assert result["response"] == "answer"

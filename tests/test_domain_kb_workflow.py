"""Domain-neutral KB prompts and fallback answers using real graph execution."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


@pytest.fixture
def kb_module(monkeypatch):
    module = importlib.import_module("gustobot.application.agents.kb_tools.workflow")
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            KB_TOP_K=2,
            KB_SIMILARITY_THRESHOLD=0.0,
            KB_ENABLE_EXTERNAL_SEARCH=False,
            INGEST_SERVICE_URL=None,
            KB_EXTERNAL_SEARCH_URL=None,
            KB_EXTERNAL_SEARCH_TIMEOUT=5,
        ),
    )
    return module


def _build_workflow(module, *, scope=None, decision="proceed", documents=(), answer="设备资料"):
    prompts = {}

    class Model:
        def with_structured_output(self, schema, *, method):
            def invoke(prompt):
                prompts[schema.__name__] = prompt.to_messages()[0].content
                if schema is module.KBGuardrailsDecision:
                    return schema(decision=decision)
                return schema(route="local", rationale="设备资料查询", tools=["milvus"])

            return RunnableLambda(invoke)

        async def ainvoke(self, messages):
            prompts["final"] = messages[0].content
            return AIMessage(content=answer)

    service = SimpleNamespace(
        reranker=SimpleNamespace(enabled=False),
        search=AsyncMock(return_value=list(documents)),
    )
    workflow = module.create_kb_multi_tool_workflow(Model(), service, scope_description=scope)
    return workflow, service, prompts


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [None, '设备手册与维护信息 {"source": "manual"}'])
async def test_kb_scope_reaches_each_prompt_without_recipe_restrictions(kb_module, scope):
    workflow, service, prompts = _build_workflow(
        kb_module,
        scope=scope,
        documents=[{"content": "泵含阀门", "source": "manual.pdf"}],
    )
    result = await workflow.ainvoke({"question": "泵含哪些部件？", "history": []})

    assert result["answer"] == "设备资料"
    assert result["sources"][0]["source"] == "manual.pdf"
    assert set(prompts) == {"KBGuardrailsDecision", "KBRouteDecision", "final"}
    for prompt in prompts.values():
        assert "菜谱" not in prompt
        assert "川菜" not in prompt
        if scope is not None:
            assert scope in prompt
    service.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_kb_rejection_is_neutral_and_does_not_search(kb_module):
    workflow, service, _ = _build_workflow(kb_module, decision="end", scope="设备手册")
    result = await workflow.ainvoke({"question": "不相关问题", "history": []})
    assert "支持范围" in result["answer"]
    assert "菜谱" not in result["answer"]
    assert result["sources"] == []
    service.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_kb_no_results_answer_is_domain_neutral(kb_module):
    workflow, _, prompts = _build_workflow(kb_module)
    result = await workflow.ainvoke({"question": "泵含哪些部件？", "history": []})
    assert "未找到" in result["answer"]
    assert "菜谱" not in result["answer"]
    assert result["sources"] == []
    assert "final" not in prompts


@pytest.mark.asyncio
async def test_kb_empty_generation_answer_is_domain_neutral(kb_module):
    workflow, _, _ = _build_workflow(
        kb_module, documents=[{"content": "泵含阀门", "source": "manual.pdf"}], answer=""
    )
    result = await workflow.ainvoke({"question": "泵含哪些部件？", "history": []})
    assert "无法生成可靠" in result["answer"]
    assert "菜谱" not in result["answer"]
    assert result["sources"][0]["source"] == "manual.pdf"

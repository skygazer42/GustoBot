"""Business plans retain exact numeric grain through the actual fact store."""

import re

import pytest

from gustobot.application.services.knowledge_query import KnowledgeQueryService
from tests.test_quantity_predicates import (
    formal_model as formal_model,  # noqa: PLC0414 - pytest fixture
)
from tests.test_quantity_predicates import (
    linking_graph as linking_graph,  # noqa: PLC0414 - pytest fixture
)
from tests.test_quantity_predicates import numeric_recipe
from tests.test_quantity_predicates import (
    numeric_recipes as numeric_recipes,  # noqa: PLC0414 - pytest fixture
)


class Planner:
    def __init__(self, plan):
        self.plan = plan
        self.calls = 0

    def with_structured_output(self, *args, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return self.plan


class NoDocuments:
    async def search(self, *args, **kwargs):
        return []


@pytest.mark.asyncio
async def test_total_request_renders_one_aggregate_with_evidence(linking_graph):
    scope = linking_graph
    await scope.store.upsert(
        numeric_recipe(scope, "两次投糖", {"辅料": [["白糖", "10g"], ["红糖", "15g"]]})
    )
    planner = Planner(
        {
            "facts": True,
            "entity_mentions": ["两次投糖"],
            "requests": [
                {
                    "property": "ingredientTotalAmount",
                    "target": "糖类",
                    "unit": "g",
                    "grain": "recipe_total",
                }
            ],
        }
    )
    answer = await KnowledgeQueryService(
        scope.domain, graph_store=scope.store, documents=NoDocuments(), model=planner
    ).answer("两次投糖的糖类总用量是多少克")
    assert re.search(r"25\s*g", answer.message)
    assert not re.search(r"(?:10|15)\s*g", answer.message)
    assert answer.metadata["plan"]["requests"][0]["grain"] == "recipe_total"
    assert answer.metadata["model_calls"] == 1
    assert answer.sources


@pytest.mark.asyncio
async def test_full_scope_numeric_filter_shows_unknown_coverage(numeric_recipes):
    scope = numeric_recipes.scope
    planner = Planner(
        {
            "facts": True,
            "selection": "all",
            "requests": [
                {
                    "property": "ingredientTotalAmount",
                    "target": "糖类",
                    "grain": "recipe_total",
                    "unit": "g",
                }
            ],
            "numeric_conditions": [
                {
                    "property": "ingredientTotalAmount",
                    "target_ref": "糖类",
                    "grain": "recipe_total",
                    "op": "lte",
                    "value": "12",
                    "unit": "g",
                }
            ],
        }
    )
    answer = await KnowledgeQueryService(
        scope.domain, graph_store=scope.store, documents=NoDocuments(), model=planner
    ).answer("列出所有糖类总用量不超过12克的做法及其糖类总用量")
    assert "精确少量" in answer.message
    assert re.search(r"5\s*g", answer.message)
    assert "未知" in answer.message or "未记录" in answer.message
    coverage = answer.metadata["numeric_coverage"][0]
    assert coverage["total"] == 8 and coverage["matched"] == 1
    assert coverage["unknown"] == 3


@pytest.mark.asyncio
async def test_unspecified_source_time_cannot_answer_actual_cooking_duration(linking_graph):
    scope = linking_graph
    await scope.store.upsert(numeric_recipe(scope, "仅记笼统耗时", {"耗时": "半小时"}))
    planner = Planner(
        {
            "facts": True,
            "entity_mentions": ["仅记笼统耗时"],
            "requests": [{"property": "reportedDuration", "grain": "cook", "unit": "minute"}],
        }
    )
    answer = await KnowledgeQueryService(
        scope.domain, graph_store=scope.store, documents=NoDocuments(), model=planner
    ).answer("仅记笼统耗时这个做法真正烹饪耗时是多少分钟")
    assert "未记录" in answer.message or "未知" in answer.message
    assert "30" not in answer.message

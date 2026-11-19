"""Reported duration parsing keeps unknown text and its stated grain."""

import importlib

import pytest

from gustobot.domain.knowledge import KnowledgeGraph
from gustobot.infrastructure.knowledge.graph_store import FactQuery
from gustobot.infrastructure.knowledge.semantic_runtime import (
    SemanticRuntime,
    SemanticSelection,
)
from tests.test_linking_catalog import (
    formal_model as formal_model,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.test_linking_catalog import (
    linking_graph as linking_graph,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.test_quantity_predicates import numeric_recipe


@pytest.mark.parametrize(
    "raw,ticks",
    [
        ("半小时", 1800000),
        ("一小时二十五分钟", 5100000),
        ("1小时30分钟", 5400000),
        ("二十分钟", 1200000),
        ("PT1H30M", 5400000),
        ("P1DT2H", 93600000),
        ("PT0.5S", 500),
        ("0分钟", 0),
        ("数天", None),
        ("一会儿", None),
        ("P1M", None),
        ("P1DT", None),
        ("二十十分钟", None),
        ("一二分钟", None),
    ],
)
def test_duration_projection_parses_only_explicit_source_durations(raw, ticks, formal_model):
    runtime = SemanticRuntime(formal_model)
    value = runtime.project_duration(raw)
    assert value.minimum == ticks and value.maximum == ticks
    assert value.status == ("unknown" if ticks is None else "comparable")


def test_reported_unspecified_cannot_be_substituted_for_cook_or_total():
    api = importlib.import_module("gustobot.domain.numeric")
    condition = api.NumericCondition(
        property="reportedDuration",
        grain="reported_unspecified",
        op="lte",
        value=30,
        unit="minute",
    )
    assert condition.grain == "reported_unspecified"
    with pytest.raises(ValueError):
        api.NumericCondition(
            property="reportedDuration",
            grain="usage",
            op="lte",
            value=30,
            unit="minute",
        )


@pytest.mark.asyncio
async def test_duration_filter_keeps_source_grain_and_orders_full_scope(linking_graph):
    scope = linking_graph
    api = importlib.import_module("gustobot.domain.numeric")
    for name, record in [
        ("未分口径", {"耗时": "半小时"}),
        ("明确烹饪", {"烹饪时长": "二十分钟"}),
        ("未知耗时", {"耗时": "数天"}),
        ("较慢", {"耗时": "一小时二十五分钟"}),
    ]:
        await scope.store.upsert(numeric_recipe(scope, name, record))
    unspecified = api.NumericCondition(
        property="reportedDuration",
        grain="reported_unspecified",
        op="lte",
        value=30,
        unit="minute",
    )
    result = await scope.store.query(
        FactQuery(entity_type="RecipeVariant", numeric_conditions=[unspecified], limit=1)
    )
    assert result.total == 1 and result.entities[0].name == "未分口径"
    assert result.numeric_coverage[0].unknown == 2
    cooking = api.NumericCondition(
        property="reportedDuration", grain="cook", op="lte", value=30, unit="minute"
    )
    result = await scope.store.query(
        FactQuery(entity_type="RecipeVariant", numeric_conditions=[cooking], limit=1)
    )
    assert result.total == 1 and result.entities[0].name == "明确烹饪"
    assert result.numeric_coverage[0].unknown == 3
    ordered = await scope.store.query(
        FactQuery(
            entity_type="RecipeVariant",
            order=[
                api.OrderSpec(
                    property="reportedDuration",
                    grain="reported_unspecified",
                    direction="asc",
                )
            ],
            limit=2,
        )
    )
    assert [entity.name for entity in ordered.entities] == ["未分口径", "较慢"]


@pytest.mark.asyncio
async def test_requested_duration_renders_only_the_selected_grain(linking_graph):
    scope = linking_graph
    await scope.store.upsert(
        numeric_recipe(
            scope,
            "口径展示",
            {"耗时": "半小时", "烹饪时长": "二十分钟", "总时长": "两小时"},
        )
    )
    api = importlib.import_module("gustobot.domain.numeric")
    result = await scope.store.query(
        FactQuery(
            numeric_selections=[
                api.NumericSelection(property="reportedDuration", grain="cook", unit="minute")
            ]
        )
    )
    answer = SemanticRuntime(scope.domain.semantic_model).evaluate(
        KnowledgeGraph(
            entities=result.entities, relations=result.relations, sources=result.sources
        ),
        [SemanticSelection(property="reportedDuration", grain="cook", unit="minute")],
        anchor_ids=[result.entities[0].id],
        numeric_values=result.numeric_values,
    )
    assert answer.status == "success" and "20minute" in answer.message
    assert "30minute" not in answer.message and "120minute" not in answer.message
    assert len(answer.sources) == 1

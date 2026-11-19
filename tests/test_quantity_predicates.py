"""Exact numeric contracts, projections and complete Neo4j predicate scope."""

import importlib
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from rdflib import Graph, Literal, Namespace

from gustobot.config.domain import get_domain_definition
from gustobot.domain.formal_ontology import load_formal_ontology
from gustobot.domain.knowledge import KnowledgeGraph
from gustobot.infrastructure.knowledge.graph_store import FactProjection, FactQuery
from gustobot.infrastructure.knowledge.recipe_facts import (
    load_recipe_mapping,
    recipe_to_facts,
)
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
from tests.test_linking_catalog import run_native


def numeric_api():
    return importlib.import_module("gustobot.domain.numeric")


@pytest.mark.parametrize("value", [0.1, True, float("inf"), "NaN", "Infinity", "-1"])
def test_numeric_condition_requires_finite_nonnegative_exact_inputs(value):
    with pytest.raises(ValueError):
        numeric_api().NumericCondition(
            property="ingredientUsageAmount",
            target_ref="糖类",
            grain="usage",
            op="lte",
            value=value,
            unit="g",
        )


def test_numeric_condition_preserves_grain_target_and_interval():
    condition = numeric_api().NumericCondition(
        property="ingredientTotalAmount",
        target_ref="糖类",
        grain="recipe_total",
        op="between",
        minimum="1.25",
        maximum=20,
        unit="g",
    )
    assert condition.minimum == "1.25" and condition.maximum == 20
    with pytest.raises(ValueError):
        numeric_api().NumericCondition(
            property="ingredientTotalAmount",
            target_ref="糖类",
            grain="usage",
            op="lte",
            value=20,
            unit="g",
        )


@pytest.mark.parametrize(
    "raw,unit,status,minimum,maximum",
    [
        ("0g", None, "comparable", 0, 0),
        ("1.25g", None, "comparable", 1250000, 1250000),
        ("1000mg", None, "comparable", 1000000, 1000000),
        ("10-20克", None, "comparable", 10000000, 20000000),
        ("0.0000001g", None, "non_comparable", None, None),
        ("9223372036854775808ug", None, "non_comparable", None, None),
        ("适量", None, "unknown", None, None),
        (None, None, "unknown", None, None),
        ("20", None, "non_comparable", None, None),
        ("20勺", None, "non_comparable", None, None),
    ],
)
def test_quantity_projection_uses_formal_exact_tick_units(
    raw, unit, status, minimum, maximum, formal_model
):
    projection = SemanticRuntime(formal_model).project_quantity(raw, unit)
    assert (projection.status, projection.minimum, projection.maximum) == (
        status,
        minimum,
        maximum,
    )
    assert projection.projection_version == "exact_numeric_v1"


def test_numeric_projection_definitions_are_formal_and_versioned():
    model = get_domain_definition().semantic_model
    assert model is not None
    assert model.version == "2026-11-17.1"
    assert model.numeric_projections["mass"].tick_unit == "ug"
    assert model.numeric_projections["time"].tick_unit == "ms"
    assert {
        "ingredientUsageAmount",
        "ingredientTotalAmount",
        "reportedDuration",
    } <= model.property_bindings.keys()


def numeric_recipe(scope, name, record):
    mapping = load_recipe_mapping().model_copy(update={"ontology_id": scope.domain.id})
    return recipe_to_facts(name, record, domain=scope.domain, mapping=mapping)


@pytest_asyncio.fixture
async def numeric_recipes(linking_graph):
    scope = linking_graph
    records = {
        "两次投糖": [["白糖", "10g"], ["红糖", "15g"]],
        "区间": [["白糖", "10-20g"]],
        "定性": [["白糖", "适量"]],
        "异量纲": [["白糖", "20ml"]],
        "不可整除": [["白糖", "0.0000001g"]],
        "精确少量": [["白糖", "5g"]],
        "部分未知": [["白糖", "5g"], ["红糖", "适量"]],
        "未记录糖": [["盐", "1g"]],
    }
    graphs = {}
    for name, ingredients in records.items():
        graph = numeric_recipe(scope, name, {"辅料": ingredients})
        await scope.store.upsert(graph)
        graphs[name] = graph
    return SimpleNamespace(scope=scope, graphs=graphs)


@pytest.mark.asyncio
async def test_usage_and_recipe_total_have_distinct_complete_scope_coverage(
    numeric_recipes,
):
    scope = numeric_recipes.scope
    api = numeric_api()
    usage = api.NumericCondition(
        property="ingredientUsageAmount",
        target_ref="糖类",
        grain="usage",
        op="lte",
        value=12,
        unit="g",
    )
    result = await scope.store.query(
        FactQuery(entity_type="RecipeVariant", numeric_conditions=[usage], limit=1)
    )
    assert result.total == 3 and result.truncated
    coverage = result.numeric_coverage[0]
    assert (
        coverage.total,
        coverage.matched,
        coverage.not_matched,
        coverage.unknown,
        coverage.uncertain,
        coverage.non_comparable,
    ) == (8, 3, 0, 2, 1, 2)
    total = api.NumericCondition(
        property="ingredientTotalAmount",
        target_ref="SugarIngredient",
        grain="recipe_total",
        op="lte",
        value=12,
        unit="g",
    )
    result = await scope.store.query(
        FactQuery(entity_type="RecipeVariant", numeric_conditions=[total], limit=1)
    )
    assert result.total == 1
    assert [entity.name for entity in result.entities if entity.type == "RecipeVariant"] == [
        "精确少量"
    ]
    coverage = result.numeric_coverage[0]
    assert (
        coverage.total,
        coverage.matched,
        coverage.not_matched,
        coverage.unknown,
        coverage.uncertain,
        coverage.non_comparable,
    ) == (8, 1, 1, 3, 1, 2)


@pytest.mark.asyncio
async def test_numeric_filter_finds_match_after_display_limit_and_orders_in_database(
    linking_graph,
):
    scope = linking_graph
    for index in range(25):
        await scope.store.upsert(
            numeric_recipe(scope, f"高用量{index}", {"辅料": [["白糖", "100g"]]})
        )
    small = numeric_recipe(scope, "低用量", {"辅料": [["白糖", "1g"]]})
    await scope.store.upsert(small)
    condition = numeric_api().NumericCondition(
        property="ingredientTotalAmount",
        target_ref="白糖",
        grain="recipe_total",
        op="lte",
        value=20,
        unit="g",
    )
    result = await scope.store.query(
        FactQuery(entity_type="RecipeVariant", numeric_conditions=[condition], limit=1)
    )
    assert result.total == 1 and result.entities[0].name == "低用量"
    ordered = await scope.store.query(
        FactQuery(
            entity_type="RecipeVariant",
            order=[
                numeric_api().OrderSpec(
                    property="ingredientTotalAmount",
                    target_ref="白糖",
                    grain="recipe_total",
                    direction="asc",
                )
            ],
            limit=1,
        )
    )
    assert ordered.total == 26 and ordered.entities[0].name == "低用量"


@pytest.mark.parametrize(
    "op,value,status",
    [
        ("lte", 20, "matched"),
        ("lte", 15, "uncertain"),
        ("gt", 20, "not_matched"),
        ("eq", 15, "uncertain"),
        ("ne", 15, "uncertain"),
        ("ne", 5, "matched"),
    ],
)
@pytest.mark.asyncio
async def test_interval_predicate_requires_whole_interval(linking_graph, op, value, status):
    scope = linking_graph
    await scope.store.upsert(numeric_recipe(scope, "区间", {"辅料": [["白糖", "10-20g"]]}))
    condition = numeric_api().NumericCondition(
        property="ingredientTotalAmount",
        target_ref="白糖",
        grain="recipe_total",
        op=op,
        value=value,
        unit="g",
    )
    result = await scope.store.query(
        FactQuery(entity_type="RecipeVariant", numeric_conditions=[condition])
    )
    assert getattr(result.numeric_coverage[0], status) == 1
    assert result.total == (1 if status == "matched" else 0)


@pytest.mark.asyncio
async def test_recipe_total_overflow_fails_without_partial_success(linking_graph):
    scope = linking_graph
    await scope.store.upsert(
        numeric_recipe(
            scope,
            "合计溢出",
            {"辅料": [["白糖", "9223372036854775807ug"], ["白糖", "1ug"]]},
        )
    )
    condition = numeric_api().NumericCondition(
        property="ingredientTotalAmount",
        target_ref="白糖",
        grain="recipe_total",
        op="gte",
        value=0,
        unit="ug",
    )
    with pytest.raises(ValueError, match="overflow|int64"):
        await scope.store.query(
            FactQuery(entity_type="RecipeVariant", numeric_conditions=[condition])
        )


@pytest.mark.asyncio
async def test_old_projection_is_visible_as_non_comparable(linking_graph):
    scope = linking_graph
    await scope.store.upsert(numeric_recipe(scope, "旧投影", {"辅料": [["白糖", "1g"]]}))
    await run_native(
        scope,
        "MATCH ()-[edge:GUSTO_FACT {domain_id: $domain_id}]->() WHERE edge.relation_type = 'HAS_AUX_INGREDIENT' SET edge.n__amount_version = 'obsolete'",
    )
    condition = numeric_api().NumericCondition(
        property="ingredientTotalAmount",
        target_ref="白糖",
        grain="recipe_total",
        op="lte",
        value=20,
        unit="g",
    )
    result = await scope.store.query(
        FactQuery(entity_type="RecipeVariant", numeric_conditions=[condition])
    )
    assert result.total == 0 and result.numeric_coverage[0].non_comparable == 1


@pytest.mark.asyncio
async def test_requested_total_is_one_complete_database_measurement_with_evidence(
    linking_graph,
):
    scope = linking_graph
    await scope.store.upsert(
        numeric_recipe(scope, "合计展示", {"辅料": [["白糖", "10g"], ["红糖", "15g"]]})
    )
    selection = numeric_api().NumericSelection(
        property="ingredientTotalAmount",
        target_ref="糖类",
        grain="recipe_total",
        unit="g",
    )
    result = await scope.store.query(
        FactQuery(entity_type="RecipeVariant", numeric_selections=[selection], limit=1)
    )
    assert len(result.numeric_values) == 1 and result.numeric_values[0].minimum == 25000000
    assert len(result.numeric_values[0].relation_ids) == 2
    runtime = SemanticRuntime(scope.domain.semantic_model)
    answer = runtime.evaluate(
        KnowledgeGraph(
            entities=result.entities, relations=result.relations, sources=result.sources
        ),
        [
            SemanticSelection(
                property="ingredientTotalAmount",
                target="糖类",
                grain="recipe_total",
                unit="g",
            )
        ],
        anchor_ids=[result.entities[0].id],
        numeric_values=result.numeric_values,
    )
    assert answer.status == "success" and "25g" in answer.message
    assert "10g" not in answer.message and "15g" not in answer.message
    assert len(answer.sources) == 1


@pytest.mark.asyncio
async def test_explicit_numeric_rebuild_is_readonly_until_publish_and_advances_revision(
    linking_graph,
):
    scope = linking_graph
    await scope.store.upsert(
        numeric_recipe(scope, "投影重建", {"辅料": [["白糖", "1000mg"]], "耗时": "半小时"})
    )
    await run_native(
        scope,
        "MATCH ()-[edge:GUSTO_FACT {domain_id: $domain_id}]->() WHERE edge.relation_type = 'HAS_AUX_INGREDIENT' SET edge.n__amount_minimum = 999, edge.n__amount_version = 'obsolete'",
    )
    original = await run_native(
        scope,
        "MATCH ()-[edge:GUSTO_FACT {domain_id: $domain_id}]->() WHERE edge.relation_type = 'HAS_AUX_INGREDIENT' RETURN properties(edge) AS values",
    )
    dry = await scope.store.rebuild_numeric_projection(dry_run=True)
    assert dry.applied is False and dry.revision == 1
    assert dry.comparable >= 2
    assert (
        await run_native(
            scope,
            "MATCH ()-[edge:GUSTO_FACT {domain_id: $domain_id}]->() WHERE edge.relation_type = 'HAS_AUX_INGREDIENT' RETURN properties(edge) AS values",
        )
        == original
    )
    applied = await scope.store.rebuild_numeric_projection(dry_run=False)
    assert applied.applied is True and applied.revision == 2
    values = await run_native(
        scope,
        "MATCH ()-[edge:GUSTO_FACT {domain_id: $domain_id}]->() WHERE edge.relation_type = 'HAS_AUX_INGREDIENT' RETURN edge.n__amount_minimum AS minimum, edge.p__amount_text AS raw",
    )
    assert values == [{"minimum": 1000000, "raw": "1000mg"}]


@pytest.mark.asyncio
async def test_numeric_rebuild_never_retags_old_ontology_data(linking_graph):
    scope = linking_graph
    await run_native(
        scope,
        "CREATE (:GustoSource {domain_id: $domain_id, id: 'old-source', ontology_version: '2026-11-16.3', text: 'old'})",
    )
    with pytest.raises(RuntimeError, match="uninitialized|scope"):
        await scope.store.rebuild_numeric_projection(dry_run=False)
    assert await run_native(
        scope,
        "MATCH (node:GustoSource {domain_id: $domain_id, id: 'old-source'}) RETURN node.ontology_version AS version",
    ) == [{"version": "2026-11-16.3"}]


@pytest.mark.asyncio
async def test_order_compares_only_the_complete_filtered_dimension_scope(linking_graph):
    scope = linking_graph
    for name, amount in [("少", "1g"), ("多", "5g"), ("异量纲", "1ml")]:
        await scope.store.upsert(numeric_recipe(scope, name, {"辅料": [["白糖", amount]]}))
    condition = numeric_api().NumericCondition(
        property="ingredientTotalAmount",
        target_ref="白糖",
        grain="recipe_total",
        op="lte",
        value=20,
        unit="g",
    )
    for direction, expected in [("asc", "少"), ("desc", "多")]:
        result = await scope.store.query(
            FactQuery(
                entity_type="RecipeVariant",
                numeric_conditions=[condition],
                order=[
                    numeric_api().OrderSpec(
                        property="ingredientTotalAmount",
                        target_ref="白糖",
                        grain="recipe_total",
                        direction=direction,
                    )
                ],
                limit=1,
            )
        )
        assert result.entities[0].name == expected and result.total == 2


@pytest.mark.asyncio
async def test_actual_ingredient_id_preserves_specific_scope_and_exact_thresholds(
    numeric_recipes,
):
    scope = numeric_recipes.scope
    graph = numeric_recipes.graphs["两次投糖"]
    white = next(
        entity.id
        for entity in graph.entities
        if entity.type == "Ingredient" and entity.name == "白糖"
    )
    anchor = next(entity.id for entity in graph.entities if entity.type == "RecipeVariant")
    condition = numeric_api().NumericCondition(
        property="ingredientTotalAmount",
        target_ref=white,
        grain="recipe_total",
        op="lte",
        value=12,
        unit="g",
    )
    result = await scope.store.query(FactQuery(anchor_ids=[anchor], numeric_conditions=[condition]))
    assert result.total == 1
    too_precise = numeric_api().NumericCondition(
        property="ingredientUsageAmount",
        target_ref=white,
        grain="usage",
        op="lte",
        value="0.0000001",
        unit="g",
    )
    with pytest.raises(ValueError, match="exact"):
        await scope.store.query(FactQuery(numeric_conditions=[too_precise]))


def test_numeric_projection_changes_with_declared_tick_unit(tmp_path):
    directory = Path(__file__).resolve().parents[1] / "gustobot/config/ontologies"
    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / name).write_bytes((directory / name).read_bytes())
    graph = Graph().parse(tmp_path / "recipes.ttl", format="turtle")
    binding = Namespace("https://gustobot.org/ontology/binding#")
    node = next(graph.subjects(binding.dimension, Literal("mass")))
    graph.set((node, binding.tickUnit, Literal("mg")))
    graph.serialize(tmp_path / "recipes.ttl", format="turtle")
    model = load_formal_ontology(tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl")
    assert SemanticRuntime(model).project_quantity("1.25g").minimum == 1250
    graph.set((node, binding.minimum, Literal(Decimal("0.5"))))
    graph.serialize(tmp_path / "recipes.ttl", format="turtle")
    with pytest.raises(ValueError):
        load_formal_ontology(tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl")


@pytest.mark.asyncio
async def test_rebuild_cli_dry_run_and_publish_use_the_same_scoped_operation(
    linking_graph, monkeypatch, capsys
):
    import json

    from gustobot.application.services import knowledge_runtime
    from scripts import rebuild_numeric_projection as cli

    scope = linking_graph
    await scope.store.upsert(numeric_recipe(scope, "命令行重建", {"辅料": [["糖", "1g"]]}))
    monkeypatch.setattr(knowledge_runtime, "get_graph_store", lambda: scope.store)
    await cli.rebuild(cli.parser().parse_args(["--dry-run"]))
    report = json.loads(capsys.readouterr().out)
    assert report["applied"] is False and report["revision"] == 1
    await cli.rebuild(cli.parser().parse_args(["--publish", "--batch-size", "1"]))
    report = json.loads(capsys.readouterr().out)
    assert report["applied"] is True and report["revision"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single", "alternatives", "empty"])
async def test_numeric_evidence_projections_filter_before_path_count_and_limit(linking_graph, mode):
    scope = linking_graph
    graph = numeric_recipe(
        scope,
        "混合投影",
        {"辅料": [["盐", "1g"], ["白糖", "2g"], ["鸡肉", "3g"]], "耗时": "半小时"},
    )
    await scope.store.upsert(graph)
    uses = sorted(
        (edge for edge in graph.relations if edge.type == "HAS_AUX_INGREDIENT"),
        key=lambda edge: edge.id,
    )
    by_id = {entity.id: entity for entity in graph.entities}
    requested = by_id[uses[-1].target_id]
    projection = FactProjection(
        relation_types=["HAS_AUX_INGREDIENT"], target_names=[requested.name]
    )
    projections = [] if mode == "empty" else [projection]
    if mode == "alternatives":
        projections.insert(
            0,
            FactProjection(relation_types=["HAS_AUX_INGREDIENT"], target_names=["未记录食材"]),
        )
    result = await scope.store.query(
        FactQuery(
            entity_type="RecipeVariant",
            relation_types=["HAS_AUX_INGREDIENT"],
            include_anchors=True,
            projections=projections,
            numeric_selections=[
                numeric_api().NumericSelection(
                    property="reportedDuration",
                    grain="reported_unspecified",
                    unit="minute",
                )
            ],
            limit=1,
        )
    )
    assert [(edge.type, edge.target_id) for edge in result.relations] == (
        [] if mode == "empty" else [("HAS_AUX_INGREDIENT", requested.id)]
    )
    assert result.total == 1 and not result.truncated
    assert len(result.numeric_values) == 1


@pytest.mark.parametrize(
    "amounts,expected_status",
    [
        (["5g", "25g"], "not_matched"),
        (["15g"], "matched"),
        (["5-25g"], "uncertain"),
        (["5-9g", "21-25g"], "not_matched"),
        (["5-15g", "15-25g"], "uncertain"),
    ],
)
@pytest.mark.asyncio
async def test_conjunctive_usage_bounds_bind_one_item_and_match_between(
    linking_graph, amounts, expected_status
):
    scope = linking_graph
    await scope.store.upsert(
        numeric_recipe(scope, "同项条件", {"辅料": [["白糖", amount] for amount in amounts]})
    )
    common = {
        "property": "ingredientUsageAmount",
        "target_ref": "白糖",
        "grain": "usage",
        "unit": "g",
    }
    interval = await scope.store.query(
        FactQuery(
            numeric_conditions=[
                numeric_api().NumericCondition(**common, op="between", minimum=10, maximum=20)
            ]
        )
    )
    bounds = await scope.store.query(
        FactQuery(
            numeric_conditions=[
                numeric_api().NumericCondition(**common, op="gte", value=10),
                numeric_api().NumericCondition(**common, op="lte", value=20),
            ]
        )
    )
    assert interval.total == bounds.total == (1 if expected_status == "matched" else 0)
    assert getattr(interval.numeric_coverage[0], expected_status) == 1
    assert all(getattr(coverage, expected_status) == 1 for coverage in bounds.numeric_coverage)


@pytest.mark.asyncio
async def test_missing_usage_selection_returns_explicit_unknown_without_violation(
    linking_graph,
):
    scope = linking_graph
    await scope.store.upsert(numeric_recipe(scope, "仅有盐", {"辅料": [["盐", "1g"]]}))
    result = await scope.store.query(
        FactQuery(
            numeric_selections=[
                numeric_api().NumericSelection(
                    property="ingredientUsageAmount",
                    target_ref="糖类",
                    grain="usage",
                    unit="g",
                )
            ]
        )
    )
    assert result.numeric_coverage[0].unknown == 1
    assert len(result.numeric_values) == 1
    value = result.numeric_values[0]
    assert value.status == "unknown" and value.minimum is value.maximum is None
    assert value.relation_ids == []
    answer = SemanticRuntime(scope.domain.semantic_model).evaluate(
        KnowledgeGraph(
            entities=result.entities, relations=result.relations, sources=result.sources
        ),
        [
            SemanticSelection(
                property="ingredientUsageAmount", target="糖类", grain="usage", unit="g"
            )
        ],
        anchor_ids=[result.entities[0].id],
        numeric_values=result.numeric_values,
    )
    assert answer.status == "no_results" and not answer.diagnostics
    assert "未记录" in answer.message


@pytest.mark.parametrize(
    "amount,operations,status",
    [
        ("5-25g", [("gte", 20), ("lte", 10)], "not_matched"),
        ("15g", [("eq", 15), ("ne", 15)], "not_matched"),
        ("10-20g", [("gte", 10), ("lte", 20), ("ne", 15)], "uncertain"),
        ("20g", [("gte", 10), ("lte", 20), ("ne", 15)], "matched"),
        ("适量", [("gte", 10), ("lte", 20)], "unknown"),
        ("20ml", [("gte", 10), ("lte", 20)], "non_comparable"),
    ],
)
@pytest.mark.asyncio
async def test_conjunctive_usage_preserves_empty_ranges_exclusions_and_missing_states(
    linking_graph, amount, operations, status
):
    scope = linking_graph
    await scope.store.upsert(numeric_recipe(scope, "合取边界", {"辅料": [["白糖", amount]]}))
    conditions = [
        numeric_api().NumericCondition(
            property="ingredientUsageAmount",
            target_ref="白糖",
            grain="usage",
            op=operator,
            value=value,
            unit="g",
        )
        for operator, value in operations
    ]
    result = await scope.store.query(FactQuery(numeric_conditions=conditions))
    assert result.total == (1 if status == "matched" else 0)
    assert all(getattr(coverage, status) == 1 for coverage in result.numeric_coverage)


@pytest.mark.asyncio
async def test_conjunctive_usage_strict_int64_boundary_does_not_overflow(linking_graph):
    scope = linking_graph
    await scope.store.upsert(
        numeric_recipe(scope, "最大整数", {"辅料": [["白糖", "9223372036854775807ug"]]})
    )
    conditions = [
        numeric_api().NumericCondition(
            property="ingredientUsageAmount",
            target_ref="白糖",
            grain="usage",
            op=operator,
            value=9223372036854775807,
            unit="ug",
        )
        for operator in ("gte", "gt")
    ]
    result = await scope.store.query(FactQuery(numeric_conditions=conditions))
    assert result.total == 0 and all(
        coverage.not_matched == 1 for coverage in result.numeric_coverage
    )

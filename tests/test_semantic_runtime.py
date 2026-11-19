"""Formal rules must change real validation, inference and quantity answers."""

import importlib
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from rdflib import RDF, RDFS, Graph, Literal
from rdflib.namespace import SH

from gustobot.domain.knowledge import KnowledgeGraph

ONTOLOGIES = Path(__file__).resolve().parents[1] / "gustobot/config/ontologies"


def runtime(model=None):
    assert (
        importlib.util.find_spec("gustobot.infrastructure.knowledge.semantic_runtime") is not None
    ), "Formal definitions need a real semantic runtime"
    from gustobot.domain.formal_ontology import load_formal_ontology

    module = importlib.import_module("gustobot.infrastructure.knowledge.semantic_runtime")
    if model is None:
        model = load_formal_ontology(ONTOLOGIES / "recipes.ttl", ONTOLOGIES / "recipes.shacl.ttl")
    return module.SemanticRuntime(model)


def facts(amount="1000 mg", *, name="红糖", second=False):
    text = "糖水甲使用红糖1000 mg。糖水乙使用红糖2 g。两份做法记录耗时半小时。"
    ev = [{"source_id": "recipe-source", "quote": text}]
    entities = [
        {"id": "dish", "type": "Dish", "name": "糖水", "evidence": ev},
        {
            "id": "r-a",
            "type": "RecipeVariant",
            "name": "糖水甲",
            "properties": {"cook_time": "半小时"},
            "evidence": ev,
        },
        {"id": "sugar", "type": "Ingredient", "name": name, "evidence": ev},
    ]
    relations = [
        {
            "id": "variant-a",
            "source_id": "r-a",
            "target_id": "dish",
            "type": "VARIANT_OF",
            "evidence": ev,
        },
        {
            "id": "use-a",
            "source_id": "r-a",
            "target_id": "sugar",
            "type": "HAS_AUX_INGREDIENT",
            "properties": {} if amount is None else {"amount_text": amount},
            "evidence": ev,
        },
    ]
    if second:
        entities.append({"id": "r-b", "type": "RecipeVariant", "name": "糖水乙", "evidence": ev})
        relations.extend(
            [
                {
                    "id": "variant-b",
                    "source_id": "r-b",
                    "target_id": "dish",
                    "type": "VARIANT_OF",
                    "evidence": ev,
                },
                {
                    "id": "use-b",
                    "source_id": "r-b",
                    "target_id": "sugar",
                    "type": "HAS_AUX_INGREDIENT",
                    "properties": {"amount_text": "2 g"},
                    "evidence": ev,
                },
            ]
        )
    return KnowledgeGraph.model_validate(
        {
            "entities": entities,
            "relations": relations,
            "sources": [{"id": "recipe-source", "text": text, "uri": "complete-source.txt"}],
        }
    )


def selection(property="ingredientQuantity", target="糖类", unit=None):
    module = importlib.import_module("gustobot.infrastructure.knowledge.semantic_runtime")
    return module.SemanticSelection(property=property, target=target, unit=unit)


def test_quantity_conversion_and_class_inference_execute_without_a_language_model():
    engine = runtime()
    result = engine.evaluate(facts(), [selection(unit="g")], anchor_ids=["r-a"])
    assert result.status == "success"
    assert "1 g" in result.message and "红糖" in result.message
    assert result.sources[0]["source"] == "complete-source.txt"
    assert {item["kind"] for item in result.derivations} >= {"inferred", "converted"}
    assert all(item["rule"] and item["premises"] for item in result.derivations)
    assert result.model_version == engine.model.version
    assert result.assertions[0]["kind"] == "asserted"
    assert result.assertions[0]["properties"]["amount_text"] == "1000 mg"


def test_separate_usage_records_keep_their_own_recipe_amounts():
    engine = runtime()
    graph = facts(second=True)
    first = engine.evaluate(graph, [selection(unit="g")], anchor_ids=["r-a"])
    second = engine.evaluate(graph, [selection(unit="g")], anchor_ids=["r-b"])
    assert "1 g" in first.message and "糖水乙" not in first.message
    assert "2 g" in second.message and "糖水甲" not in second.message


def test_defining_a_new_superclass_changes_selection_without_prompt_edits(tmp_path):
    engine = runtime()
    namespace = engine.model.uri
    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / name).write_bytes((ONTOLOGIES / name).read_bytes())
    graph = Graph().parse(tmp_path / "recipes.ttl", format="turtle")
    graph.remove((namespace("BrownSugarIngredient"), RDFS.subClassOf, namespace("SugarIngredient")))
    graph.add((namespace("BrownSugarIngredient"), RDFS.subClassOf, namespace("Ingredient")))
    graph.serialize(tmp_path / "recipes.ttl", format="turtle")
    from gustobot.domain.formal_ontology import load_formal_ontology

    changed = runtime(
        load_formal_ontology(tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl")
    )
    assert engine.evaluate(facts(), [selection()], anchor_ids=["r-a"]).status == "success"
    assert changed.evaluate(facts(), [selection()], anchor_ids=["r-a"]).status == "no_results"


def test_raw_input_and_answer_shapes_have_different_completeness_requirements():
    engine = runtime()
    assert engine.validate_input(facts(amount=None)).conforms
    assert (
        engine.evaluate(facts(amount=None), [selection()], anchor_ids=["r-a"]).status
        == "no_results"
    )
    projection = facts()
    projection.relations = [
        relation for relation in projection.relations if relation.type != "VARIANT_OF"
    ]
    assert engine.evaluate(projection, [selection()], anchor_ids=["r-a"]).status == "success"
    module = importlib.import_module("gustobot.infrastructure.knowledge.semantic_runtime")
    with pytest.raises(module.SemanticValidationError) as raised:
        engine.validate_input(projection)
    assert raised.value.report.issues
    assert any("VARIANT_OF" in (issue.path or "") for issue in raised.value.report.issues)


@pytest.mark.parametrize(
    ("amount", "unit", "status"),
    [
        ("适量", None, "success"),
        ("适量", "g", "insufficient_evidence"),
        ("1 碗", "g", "insufficient_evidence"),
        ("2 ml", "g", "insufficient_evidence"),
        ("2-4 g", "mg", "success"),
    ],
)
def test_quantity_kinds_and_dimensions_control_what_can_be_computed(amount, unit, status):
    engine = runtime()
    result = engine.evaluate(facts(amount), [selection(unit=unit)], anchor_ids=["r-a"])
    assert result.status == status
    if amount == "2-4 g":
        assert "2000" in result.message and "4000" in result.message
    if status == "insufficient_evidence":
        assert result.diagnostics
        assert not any(item.get("kind") == "converted" for item in result.derivations)


def test_shape_violation_is_reported_before_owl_domain_inference_can_mask_it():
    engine = runtime()
    graph = facts()
    graph.entities[1].type = "Ingredient"
    module = importlib.import_module("gustobot.infrastructure.knowledge.semantic_runtime")
    with pytest.raises(module.SemanticValidationError) as raised:
        engine.validate_input(graph)
    assert raised.value.report.conforms is False
    assert raised.value.report.issues[0].message


def test_decimal_conversion_uses_ontology_unit_values_and_retains_original_expression():
    engine = runtime()
    result = engine.evaluate(facts("0.1 g"), [selection(unit="mg")], anchor_ids=["r-a"])
    assert "100 mg" in result.message
    conversion = next(item for item in result.derivations if item["kind"] == "converted")
    assert conversion["original"] == "0.1 g"
    assert Decimal(conversion["value"]) == Decimal(100)


def test_binding_uses_declared_identity_keys_and_is_idempotent():
    engine = runtime()
    bound = engine.bind_graph(facts(second=True))
    assert engine.bind_graph(bound) == bound
    assert len({entity.id for entity in bound.entities if entity.type == "RecipeVariant"}) == 2
    ingredient = next(entity for entity in bound.entities if entity.type == "Ingredient")
    assert ingredient.id == engine.model.identity_id("Ingredient", {"name": "红糖"})
    assert engine.validate_input(bound).conforms


def test_missing_selected_property_is_partial_when_another_selected_property_is_present():
    engine = runtime()
    result = engine.evaluate(
        facts(amount=None), [selection(), selection("reportedTime", None)], anchor_ids=["r-a"]
    )
    assert result.status == "partial"
    assert "半小时" in result.message
    assert "未记录" in result.message


def test_two_recipe_owners_on_one_use_produce_a_real_shacl_path_violation():
    engine = runtime()
    data = engine.project(facts(second=True))
    use = next(data.subjects(RDF.type, engine.model.uri("IngredientUse")))
    owners = list(data.subjects(RDF.type, engine.model.uri("RecipeVariant")))
    for owner in owners:
        data.add((use, engine.model.uri("inRecipe"), owner))
    report = engine.validate_rdf(data)
    assert not report.conforms
    assert any(
        issue.path == str(engine.model.uri("inRecipe"))
        and issue.constraint == str(SH.MaxCountConstraintComponent)
        for issue in report.issues
    )


def test_model_unit_scale_changes_real_computation_without_changing_executor(tmp_path):
    engine = runtime()
    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / name).write_bytes((ONTOLOGIES / name).read_bytes())
    graph = Graph().parse(tmp_path / "recipes.ttl", format="turtle")
    unit = engine.model.unit_spec("mg")
    graph.set((unit.uri, engine.model.uri("scale"), Literal(Decimal("0.002"))))
    graph.serialize(tmp_path / "recipes.ttl", format="turtle")
    from gustobot.domain.formal_ontology import load_formal_ontology

    changed = runtime(
        load_formal_ontology(tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl")
    )
    answer = changed.evaluate(facts(), [selection(unit="g")], anchor_ids=["r-a"])
    assert answer.status == "success" and "2 g" in answer.message


def test_negative_and_reversed_numeric_quantities_fail_shape_validation():
    engine = runtime()
    module = importlib.import_module("gustobot.infrastructure.knowledge.semantic_runtime")
    for raw in ["-1 g", "4-2 g"]:
        with pytest.raises(module.SemanticValidationError) as raised:
            engine.validate_input(facts(raw))
        assert any(
            issue.constraint
            in {
                str(SH.MinInclusiveConstraintComponent),
                str(SH.LessThanOrEqualsConstraintComponent),
            }
            for issue in raised.value.report.issues
        )


def test_answer_shape_executes_referenced_quantity_shapes_and_blocks_negative_values():
    engine = runtime()
    result = engine.evaluate(facts("-1 g"), [selection()], anchor_ids=["r-a"])
    assert result.status == "insufficient_evidence"
    assert result.diagnostics
    assert not result.sources


def test_comparing_anchors_reports_a_missing_property_on_the_other_anchor():
    engine = runtime()
    graph = facts(second=True)
    graph.relations[-1].properties = {}
    answer = engine.evaluate(graph, [selection()], anchor_ids=["r-a", "r-b"])
    assert answer.status == "partial"
    assert "糖水甲" in answer.message and "糖水乙" in answer.message
    assert "未记录" in answer.message


def test_a_unit_on_a_nonquantity_property_is_not_silently_discarded():
    engine = runtime()
    answer = engine.evaluate(facts(), [selection("reportedTime", None, "g")], anchor_ids=["r-a"])
    assert answer.status == "insufficient_evidence"
    assert answer.diagnostics
    assert "半小时" not in answer.message


def test_scalar_property_rejects_an_ingredient_target_instead_of_answering_recipe_time():
    engine = runtime()
    result = engine.evaluate(facts(), [selection("reportedTime", "红糖")], anchor_ids=["r-a"])
    assert result.status == "insufficient_evidence"
    assert result.diagnostics and "半小时" not in result.message


def test_canonical_target_identity_is_used_for_case_spacing_and_unicode_variants():
    engine = runtime()
    graph = facts("1 g", name="Brown Sugar")
    for name in ["brown sugar", "  brown   sugar ", "Ｂｒｏｗｎ Ｓｕｇａｒ"]:
        answer = engine.evaluate(graph, [selection(target=name)], anchor_ids=["r-a"])
        assert answer.status == "success", name
        assert "1 g" in answer.message


def test_range_answers_preserve_a_separately_recorded_unit():
    engine = runtime()
    graph = facts("2-4")
    graph.relations[-1].properties["unit"] = "g"
    answer = engine.evaluate(graph, [selection()], anchor_ids=["r-a"])
    assert answer.status == "success" and "2-4 g" in answer.message


def test_quantity_answer_does_not_cite_another_recipe_via_shared_ingredient():
    from gustobot.domain.knowledge import EvidenceReference, SourceDocument

    engine = runtime()
    graph = facts()
    graph.entities[-1].evidence.append(
        EvidenceReference(source_id="other-source", quote="另一份糖水使用红糖。")
    )
    graph.sources.append(
        SourceDocument(id="other-source", text="另一份糖水使用红糖。", uri="other-recipe.txt")
    )
    answer = engine.evaluate(graph, [selection()], anchor_ids=["r-a"])
    assert answer.status == "success"
    assert {source["source"] for source in answer.sources} == {"complete-source.txt"}


def test_formal_steps_follow_declared_order_even_when_storage_returns_hash_order():
    from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts

    engine = runtime()
    graph = engine.bind_graph(
        recipe_to_facts(
            "步骤排序", {"steps": ["第一道动作", "第二道动作", "第三道动作"]}, domain=engine.domain
        )
    )
    # Preserve the reversed iteration that a storage projection is free to return.
    graph.relations = sorted(
        graph.relations, key=lambda edge: edge.properties.get("order", 0), reverse=True
    )
    anchor = next(item.id for item in graph.entities if item.type == "RecipeVariant")
    answer = engine.evaluate(graph, [selection("steps", None)], anchor_ids=[anchor])
    assert answer.status == "success"
    assert (
        answer.message.index("第一道动作")
        < answer.message.index("第二道动作")
        < answer.message.index("第三道动作")
    )


def test_logical_subproperty_binding_controls_relation_selection_and_records_derivation(tmp_path):
    from gustobot.domain.formal_ontology import B, load_formal_ontology

    engine = runtime()
    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / name).write_bytes((ONTOLOGIES / name).read_bytes())
    model_graph = Graph().parse(tmp_path / "recipes.ttl", format="turtle")
    model_graph.add(
        (
            engine.model.uri("HAS_MAIN_INGREDIENT"),
            RDFS.subPropertyOf,
            engine.model.uri("HAS_AUX_INGREDIENT"),
        )
    )
    model_graph.set(
        (
            engine.model.uri("IngredientQuantityProperty"),
            B.relation,
            engine.model.uri("HAS_AUX_INGREDIENT"),
        )
    )
    model_graph.serialize(tmp_path / "recipes.ttl", format="turtle")
    changed = runtime(
        load_formal_ontology(tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl")
    )
    graph = facts("1 g")
    graph.relations[-1].type = "HAS_MAIN_INGREDIENT"
    answer = changed.evaluate(graph, [selection()], anchor_ids=["r-a"])
    assert answer.status == "success"
    assert any(
        item["rule"] == "owl-rl:prp-spo1"
        and str(engine.model.uri("HAS_AUX_INGREDIENT")) in item["premises"]
        for item in answer.derivations
    )


def test_declared_edge_string_constraint_changes_input_and_answer_validation(tmp_path):
    from gustobot.domain.formal_ontology import B, load_formal_ontology

    for name in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / name).write_bytes((ONTOLOGIES / name).read_bytes())
    shapes = Graph().parse(tmp_path / "recipes.shacl.ttl", format="turtle")
    field = next(shapes.subjects(B.nativeField, Literal("unit")))
    shapes.add((field, SH.minLength, Literal(3)))
    shapes.serialize(tmp_path / "recipes.shacl.ttl", format="turtle")
    changed = runtime(
        load_formal_ontology(tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl")
    )
    graph = facts("1")
    graph.relations[-1].properties["unit"] = "g"
    module = importlib.import_module("gustobot.infrastructure.knowledge.semantic_runtime")
    with pytest.raises(module.SemanticValidationError):
        changed.validate_input(graph)
    answer = changed.evaluate(graph, [selection()], anchor_ids=["r-a"])
    assert answer.status == "insufficient_evidence"
    assert any(
        issue["constraint"] == str(SH.MinLengthConstraintComponent) for issue in answer.diagnostics
    )


def test_mapped_role_is_one_rdf_value_and_conflicting_role_is_rejected():
    from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts

    engine = runtime()
    graph = recipe_to_facts("糖水", {"辅料": [["糖", "1 g"]]}, domain=engine.domain)
    assert engine.validate_input(graph).conforms
    edge = next(item for item in graph.relations if item.type == "HAS_AUX_INGREDIENT")
    edge.properties["role"] = "main"
    module = importlib.import_module("gustobot.infrastructure.knowledge.semantic_runtime")
    with pytest.raises(module.SemanticValidationError):
        engine.validate_input(graph)


def test_inference_cache_keeps_independent_graphs_and_invalidates_changed_assertions(monkeypatch):
    from rdflib import URIRef

    from gustobot.infrastructure.knowledge import semantic_runtime as module

    engine = runtime()
    calls = []
    original = module.DeductiveClosure.expand

    def counted(closure, graph):
        calls.append(len(graph))
        return original(closure, graph)

    monkeypatch.setattr(module.DeductiveClosure, "expand", counted)
    raw = Graph()
    entity = URIRef("urn:cache:ingredient")
    ingredient_type = engine.model.classify_name("红糖", "Ingredient")
    assert ingredient_type is not None
    raw.add((entity, RDF.type, ingredient_type))
    first = engine._inferred(raw)
    assert (entity, RDF.type, engine.model.uri("SugarIngredient")) in first
    first.remove((entity, RDF.type, engine.model.uri("SugarIngredient")))
    second = engine._inferred(raw)
    assert (entity, RDF.type, engine.model.uri("SugarIngredient")) in second
    assert len(calls) == 1
    raw.add((entity, RDFS.label, Literal("新来源断言")))
    changed = engine._inferred(raw)
    assert (entity, RDFS.label, Literal("新来源断言")) in changed
    assert len(calls) == 2

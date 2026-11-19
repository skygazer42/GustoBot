"""Structured recipes retain distinct instances and exact source evidence."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from gustobot.config import domain as domain_config
from gustobot.domain.knowledge import DomainDefinition, validate_graph
from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts


@pytest.fixture
def recipe_domain(monkeypatch):
    monkeypatch.setattr(
        domain_config,
        "settings",
        SimpleNamespace(KNOWLEDGE_DOMAIN_FILE="gustobot/config/domains/recipes.yaml"),
    )
    return domain_config.get_domain_definition()


def test_mapping_retains_amount_units_unknown_time_and_original_record(recipe_domain):
    record = {
        "主食材": [["鲍鱼", "2只"], ["海参", "适量"]],
        "辅料": [["糖", None], ["盐", 0], {"name": "酒", "amount": "2", "unit": "汤匙"}],
        "耗时": "数天",
        "做法": "1:准备食材。2:炖煮。",
        "类型": "宴客菜",
        "来源备注": {"原始单位": "只", "未确定": None, "literal": "{原文}"},
    }

    graph = recipe_to_facts("佛跳墙", record)

    validate_graph(recipe_domain, graph)
    variants = [entity for entity in graph.entities if entity.type == "RecipeVariant"]
    assert len(variants) == 1
    assert variants[0].properties["cook_time"] == "数天"
    assert variants[0].properties["instructions"] == record["做法"]
    assert json.loads(graph.sources[0].text) == {"name": "佛跳墙", "record": record}
    ingredients = {
        entity.id: entity.name for entity in graph.entities if entity.type == "Ingredient"
    }
    amounts = {
        ingredients[relation.target_id]: relation.properties
        for relation in graph.relations
        if relation.type in {"HAS_MAIN_INGREDIENT", "HAS_AUX_INGREDIENT"}
    }
    assert amounts["鲍鱼"]["amount_text"] == "2只"
    assert amounts["海参"]["amount_text"] == "适量"
    assert "amount_text" not in amounts["糖"]
    assert amounts["盐"]["amount_text"] == "0"
    assert amounts["酒"]["amount_text"] == "2汤匙"
    assert amounts["酒"]["unit"] == "汤匙"


def test_same_display_name_keeps_distinct_recipe_variants_and_sources():
    quick = recipe_to_facts("佛跳墙", {"耗时": "半小时", "主食材": [["鸡肉", "100克"]]})
    slow = recipe_to_facts("佛跳墙", {"耗时": "数天", "主食材": [["鲍鱼", "2只"]]})

    first = next(entity for entity in quick.entities if entity.type == "RecipeVariant")
    second = next(entity for entity in slow.entities if entity.type == "RecipeVariant")
    assert first.name == second.name == "佛跳墙"
    assert first.id != second.id
    assert quick.sources[0].id != slow.sources[0].id
    assert any(relation.type == "VARIANT_OF" for relation in quick.relations)


def test_repeated_import_is_stable_even_when_record_key_order_changes():
    first = recipe_to_facts("糖水", {"主食材": [["水", "一碗"]], "耗时": "十分钟"})
    reordered = recipe_to_facts("糖水", {"耗时": "十分钟", "主食材": [["水", "一碗"]]})

    assert first == reordered
    assert len({relation.id for relation in first.relations}) == len(first.relations)


def test_display_prefix_alias_does_not_collapse_variant_identity():
    first = recipe_to_facts("#传统名菜#佛跳墙", {"耗时": "半小时"})
    second = recipe_to_facts("#家常菜#佛跳墙", {"耗时": "半小时"})
    first_variant = next(entity for entity in first.entities if entity.type == "RecipeVariant")
    second_variant = next(entity for entity in second.entities if entity.type == "RecipeVariant")

    assert "佛跳墙" in first_variant.aliases
    assert "佛跳墙" in second_variant.aliases
    assert first_variant.id != second_variant.id
    assert first_variant.name == "#传统名菜#佛跳墙"


def test_missing_ingredients_and_time_do_not_become_zero_or_negative_facts(recipe_domain):
    graph = recipe_to_facts("清蒸鱼", {"主食材": [["鱼", "一条"]], "耗时": None})

    validate_graph(recipe_domain, graph)
    variant = next(entity for entity in graph.entities if entity.type == "RecipeVariant")
    assert "cook_time" not in variant.properties
    assert all(entity.name != "糖" for entity in graph.entities)
    assert not any("absent" in relation.type.lower() for relation in graph.relations)


def test_repeated_same_ingredient_occurrences_keep_their_own_amounts(recipe_domain):
    graph = recipe_to_facts("红烧肉", {"辅料": [["糖", "10克"], ["糖", "适量"]]})

    validate_graph(recipe_domain, graph)
    amounts = [
        relation.properties["amount_text"]
        for relation in graph.relations
        if relation.type == "HAS_AUX_INGREDIENT"
    ]
    assert amounts == ["10克", "适量"]
    assert len({relation.id for relation in graph.relations}) == len(graph.relations)


def test_two_digit_step_numbers_do_not_create_extra_steps():
    graph = recipe_to_facts("十步菜", {"做法": "".join(f"{i}:步骤{i}。" for i in range(1, 11))})
    steps = [entity for entity in graph.entities if entity.type == "CookingStep"]

    assert len(steps) == 10
    assert steps[-1].properties == {"order": 10, "instruction": "10:步骤10。"}


def test_recorded_amount_text_does_not_repeat_its_separate_unit():
    graph = recipe_to_facts(
        "糖水", {"辅料": [{"name": "糖", "amount_text": "两汤匙", "unit": "汤匙"}]}
    )
    relation = next(item for item in graph.relations if item.type == "HAS_AUX_INGREDIENT")

    assert relation.properties["amount_text"] == "两汤匙"
    assert relation.properties["unit"] == "汤匙"


@pytest.mark.parametrize(
    "ingredient",
    [
        {"name": "糖", "amount": "20g", "unit": "g"},
        ["糖", "20g", "g"],
    ],
)
def test_amount_with_recorded_unit_is_not_appended_again(ingredient):
    graph = recipe_to_facts("糖水", {"辅料": [ingredient]})
    relation = next(item for item in graph.relations if item.type == "HAS_AUX_INGREDIENT")

    assert relation.properties["amount_text"] == "20g"
    assert relation.properties["unit"] == "g"


def test_source_field_binding_changes_without_changing_ontology_or_mapper(recipe_domain):
    from gustobot.infrastructure.knowledge.recipe_facts import (
        load_recipe_mapping,
    )
    from gustobot.infrastructure.knowledge.recipe_facts import (
        recipe_to_facts as map_record,
    )

    mapping = load_recipe_mapping()
    mapping.record_fields["instructions"] = ["制作说明"]
    mapping.ingredients[1].source_fields = ["调味记录"]
    graph = map_record(
        "糖水", {"制作说明": ["加水", "煮开"], "调味记录": [["糖", "少许"]]}, mapping=mapping
    )
    validate_graph(recipe_domain, graph)
    assert len([item for item in graph.entities if item.type == "CookingStep"]) == 2
    assert (
        next(item for item in graph.relations if item.type == "HAS_AUX_INGREDIENT").properties[
            "amount_text"
        ]
        == "少许"
    )
    assert "制作说明" not in load_recipe_mapping().record_fields["instructions"]


def test_explicit_model_controls_entity_identity_and_step_parent():
    from gustobot.infrastructure.knowledge.recipe_facts import (
        recipe_to_facts as map_record,
    )

    class DeclaredIdentity:
        def identity_id(self, entity_type, values):
            keys = ("parent_id", "order") if entity_type == "CookingStep" else ("source_id", "name")
            return "declared:" + entity_type + ":" + ":".join(str(values[key]) for key in keys)

    domain = cast(
        DomainDefinition, SimpleNamespace(id="recipes", semantic_model=DeclaredIdentity())
    )
    record = {
        "主食材": [["水", None]],
        "辅料": [["糖", 0, "g"]],
        "口味": "甜味",
        "工艺": "煮",
        "类型": "甜品",
        "菜系": "家常菜",
        "做法": ["煮开"],
    }

    graph = map_record("糖水", record, domain=domain)

    source_id = graph.sources[0].id
    variant_id = f"declared:RecipeVariant:{source_id}:糖水"
    assert {entity.type for entity in graph.entities} == {
        "Dish",
        "RecipeVariant",
        "Ingredient",
        "Flavor",
        "CookingMethod",
        "DishType",
        "CuisineStyle",
        "CookingStep",
    }
    assert all(entity.id.startswith(f"declared:{entity.type}:") for entity in graph.entities)
    assert next(entity.id for entity in graph.entities if entity.type == "CookingStep") == (
        f"declared:CookingStep:{variant_id}:1"
    )
    assert json.loads(graph.sources[0].text) == {"name": "糖水", "record": record}
    assert all(
        reference.source_id == source_id
        for references in (
            [entity.evidence for entity in graph.entities]
            + [edge.evidence for edge in graph.relations]
        )
        for reference in references
    )


def test_explicit_legacy_domain_keeps_record_identity_without_loading_global_domain(monkeypatch):
    from gustobot.infrastructure.knowledge import recipe_facts

    domain = cast(DomainDefinition, SimpleNamespace(id="recipes", semantic_model=None))
    monkeypatch.setattr(
        recipe_facts,
        "get_domain_definition",
        lambda: pytest.fail("Explicit domain must not load global configuration"),
        raising=False,
    )
    first = recipe_facts.recipe_to_facts("糖水", {"辅料": [["糖", None]]}, domain=domain)
    repeated = recipe_facts.recipe_to_facts("糖水", {"辅料": [["糖", None]]}, domain=domain)

    assert first == repeated
    assert next(entity.id for entity in first.entities if entity.type == "Ingredient").startswith(
        "recipe-ingredient:"
    )


def test_formal_canonical_names_share_concepts_without_merging_source_variants(recipe_domain):
    from gustobot.infrastructure.knowledge.recipe_facts import (
        recipe_to_facts as map_record,
    )

    first = map_record("糖水", {"辅料": [["Brown Sugar", "1g"]]}, domain=recipe_domain)
    second = map_record("糖水", {"辅料": [["  brown   sugar ", None]]}, domain=recipe_domain)

    first_ingredient = next(entity for entity in first.entities if entity.type == "Ingredient")
    second_ingredient = next(entity for entity in second.entities if entity.type == "Ingredient")
    assert first_ingredient.id == second_ingredient.id
    assert first.sources[0].id != second.sources[0].id
    assert next(entity.id for entity in first.entities if entity.type == "RecipeVariant") != next(
        entity.id for entity in second.entities if entity.type == "RecipeVariant"
    )
    assert second_ingredient.name == "  brown   sugar "
    assert "amount_text" not in next(
        edge.properties for edge in second.relations if edge.type == "HAS_AUX_INGREDIENT"
    )


def test_formal_identity_declaration_change_alters_mapper_and_relation_endpoint(tmp_path):
    from rdflib import Graph, Literal, Namespace

    from gustobot.domain.formal_ontology import load_formal_ontology
    from gustobot.infrastructure.knowledge.recipe_facts import (
        recipe_to_facts as map_record,
    )

    directory = Path(__file__).resolve().parents[1] / "gustobot/config/ontologies"
    for filename in ("recipes.ttl", "recipes.shacl.ttl", "schema-recipe-subset.ttl"):
        (tmp_path / filename).write_bytes((directory / filename).read_bytes())
    ontology = Graph().parse(tmp_path / "recipes.ttl", format="turtle")
    recipe = Namespace("https://gustobot.org/ontology/recipes#")
    binding = Namespace("https://gustobot.org/ontology/binding#")
    rule = ontology.value(recipe.Ingredient, binding.identity)
    assert rule is not None
    ontology.set((rule, binding.prefix, Literal("declared-ingredient:")))
    ontology.serialize(tmp_path / "recipes.ttl", format="turtle")
    changed = load_formal_ontology(
        tmp_path / "recipes.ttl", tmp_path / "recipes.shacl.ttl"
    ).domain_definition()

    graph = map_record("糖水", {"辅料": [["糖", "适量"]]}, domain=changed)

    ingredient = next(entity for entity in graph.entities if entity.type == "Ingredient")
    assert ingredient.id.startswith("declared-ingredient:")
    assert next(
        edge.target_id for edge in graph.relations if edge.type == "HAS_AUX_INGREDIENT"
    ) == (ingredient.id)

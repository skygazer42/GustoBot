"""The ontology is an executable semantic contract, separate from query routing."""

from types import SimpleNamespace

import pytest
import yaml

from gustobot.config import domain as domain_config
from gustobot.domain.knowledge import KnowledgeGraph, validate_graph


def definition_payload():
    return {
        "id": "equipment",
        "version": "2026-11-16",
        "name": "设备维护",
        "description": "设备领域",
        "document_scope": "设备手册",
        "classes": {
            "Equipment": {
                "label": "设备",
                "description": "可定位设备",
                "identity": "source_assigned",
                "grain": "一条记录对应一台设备",
                "properties": {},
            },
            "Component": {
                "label": "部件",
                "description": "部件",
                "identity": "source_assigned",
                "grain": "一个设备上的一个部件",
                "properties": {},
            },
        },
        "allowed_edges": {
            "HAS_COMPONENT": {
                "domain": ["Equipment"],
                "range": ["Component"],
                "description": "设备包含部件",
                "cardinality": {"min": 0},
                "properties": {"slot": {"type": "integer", "minimum": 1}},
            }
        },
        "lexicon": [{"terms": ["组成", "部件"], "refs": ["HAS_COMPONENT", "Component"]}],
    }


def configure_yaml(monkeypatch, tmp_path, payload):
    path = tmp_path / "equipment.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(domain_config, "settings", SimpleNamespace(KNOWLEDGE_DOMAIN_FILE=str(path)))
    return path


def test_yaml_semantics_are_loaded_and_caller_mutation_is_isolated(monkeypatch, tmp_path):
    payload = definition_payload()
    payload["description"] = '保留原文 {serial} 和 JSON {"count": 0}'
    configure_yaml(monkeypatch, tmp_path, payload)
    monkeypatch.chdir(tmp_path.parent)
    first = domain_config.get_domain_definition()
    first.lexicon[0].terms.append("modified")
    first.entity_types.clear()
    second = domain_config.get_domain_definition()
    assert second.description == payload["description"]
    assert second.lexicon[0].terms == ["组成", "部件"]
    assert second.entity_types["Equipment"].grain == "一条记录对应一台设备"
    assert second.relation_types["HAS_COMPONENT"].source_types == ["Equipment"]


@pytest.mark.parametrize("ref", ["Unknown", "Equipment.secret", "HAS_COMPONENT.secret"])
def test_lexicon_cannot_invent_types_edges_or_properties(monkeypatch, tmp_path, ref):
    payload = definition_payload()
    payload["lexicon"][0]["refs"] = [ref]
    configure_yaml(monkeypatch, tmp_path, payload)
    with pytest.raises(ValueError, match="Unknown ontology reference"):
        domain_config.get_domain_definition()


def test_yaml_rejects_relations_with_unknown_endpoints(monkeypatch, tmp_path):
    payload = definition_payload()
    payload["allowed_edges"]["HAS_COMPONENT"]["range"] = ["Unknown"]
    configure_yaml(monkeypatch, tmp_path, payload)
    with pytest.raises(ValueError, match="Unknown entity type"):
        domain_config.get_domain_definition()


@pytest.mark.parametrize("invalid", ["id: [", "id: equipment\nid: duplicate\n", "[]"])
def test_invalid_yaml_is_visible(monkeypatch, tmp_path, invalid):
    path = configure_yaml(monkeypatch, tmp_path, definition_payload())
    path.write_text(invalid, encoding="utf-8")
    with pytest.raises(ValueError):
        domain_config.get_domain_definition()


@pytest.mark.parametrize("profile", ["recipes", "equipment", "generic"])
def test_profiles_declare_semantics_without_query_classifications(monkeypatch, tmp_path, profile):
    profile_path = domain_config.REPOSITORY_ROOT / f"gustobot/config/domains/{profile}.yaml"
    payload = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    assert "query_capabilities" not in payload
    if profile == "recipes":
        assert set(payload) == {"format", "ontology", "shapes"}
        assert payload["format"] == "rdf"
    else:
        assert "classes" in payload and "allowed_edges" in payload
        assert all(value["identity"] and value["grain"] for value in payload["classes"].values())
    monkeypatch.setattr(
        domain_config, "settings", SimpleNamespace(KNOWLEDGE_DOMAIN_FILE=str(profile_path))
    )
    monkeypatch.chdir(tmp_path)
    domain = domain_config.get_domain_definition()
    assert domain.id == profile
    assert all(value.identity and value.grain for value in domain.entity_types.values())
    assert (domain.semantic_model is not None) == (profile == "recipes")
    validate_graph(domain, KnowledgeGraph(entities=[], relations=[], sources=[]))


def recipe_graph():
    from gustobot.infrastructure.knowledge.recipe_facts import recipe_to_facts

    return recipe_to_facts("糖水", {"辅料": [["糖", "适量"]], "做法": ["加水", "煮开"]})


def test_step_order_constraint_is_executed():
    domain = domain_config.get_domain_definition()
    graph = recipe_graph()
    step = next(entity for entity in graph.entities if entity.type == "CookingStep")
    step.properties["order"] = 0
    with pytest.raises(ValueError, match="minimum"):
        validate_graph(domain, graph)


def test_variant_shape_requires_its_dish_anchor():
    domain = domain_config.get_domain_definition()
    graph = recipe_graph()
    graph.relations = [edge for edge in graph.relations if edge.type != "VARIANT_OF"]
    with pytest.raises(ValueError, match="VARIANT_OF"):
        validate_graph(domain, graph)


def test_step_order_must_be_unique_within_one_variant():
    domain = domain_config.get_domain_definition()
    graph = recipe_graph()
    edges = [edge for edge in graph.relations if edge.type == "HAS_STEP"]
    edges[1].properties["order"] = edges[0].properties["order"]
    with pytest.raises(ValueError, match="unique"):
        validate_graph(domain, graph)


def test_quantity_is_not_a_global_ingredient_property():
    domain = domain_config.get_domain_definition()
    graph = recipe_graph()
    ingredient = next(entity for entity in graph.entities if entity.type == "Ingredient")
    ingredient.properties["amount_text"] = "20克"
    with pytest.raises(ValueError, match="Unknown property amount_text"):
        validate_graph(domain, graph)


def test_original_unknown_amount_and_unit_survive_validation():
    domain = domain_config.get_domain_definition()
    graph = recipe_graph()
    validate_graph(domain, graph)
    assert (
        next(edge for edge in graph.relations if edge.type == "HAS_AUX_INGREDIENT").properties[
            "amount_text"
        ]
        == "适量"
    )


def referenced_definition():
    payload = definition_payload()
    payload["vocabularies"] = {
        "schema": {
            "namespace": "https://schema.org/",
            "version": "30.1",
            "definition_url": "https://example.org/schema.jsonld",
            "sha256": "a" * 64,
            "terms": ["Thing", "identifier"],
        },
        "unused": {
            "namespace": "https://example.org/unused/",
            "version": "1",
            "definition_url": "https://example.org/unused.ttl",
            "sha256": "b" * 64,
            "terms": ["Unused"],
        },
    }
    payload["classes"]["Equipment"]["external_refs"] = [
        {"source": "schema", "uri": "https://schema.org/Thing", "kind": "local_profile"}
    ]
    payload["classes"]["Equipment"]["properties"]["serial"] = {
        "type": "string",
        "external_refs": [
            {"source": "schema", "uri": "https://schema.org/identifier", "kind": "value_projection"}
        ],
    }
    return payload


def test_vocabulary_definitions_load_and_catalog_exposes_only_used_source_summaries(
    monkeypatch, tmp_path
):
    configure_yaml(monkeypatch, tmp_path, referenced_definition())
    domain = domain_config.get_domain_definition()
    assert domain.vocabularies["schema"].version == "30.1"
    catalog = domain.semantic_catalog("部件")
    assert catalog["vocabularies"] == {
        "schema": {"namespace": "https://schema.org/", "version": "30.1"}
    }
    assert catalog["classes"]["Equipment"]["external_refs"][0]["uri"] == "https://schema.org/Thing"
    assert set(catalog["classes"]) == {"Equipment", "Component"}
    assert "definition_url" not in str(catalog)
    assert "sha256" not in str(catalog)
    domain.vocabularies["schema"].terms.clear()
    assert domain_config.get_domain_definition().vocabularies["schema"].terms == [
        "Thing",
        "identifier",
    ]


@pytest.mark.parametrize(
    ("owner", "source", "uri"),
    [
        ("class", "missing", "https://schema.org/Thing"),
        ("class", "schema", "https://other.org/Thing"),
        ("property", "schema", "https://schema.org/MadeUp"),
        ("relation", "schema", "https://schema.org/MadeUp"),
    ],
)
def test_external_references_reject_unknown_sources_namespaces_and_terms(
    monkeypatch, tmp_path, owner, source, uri
):
    payload = referenced_definition()
    if owner == "class":
        location = payload["classes"]["Equipment"]
    elif owner == "property":
        location = payload["classes"]["Equipment"]["properties"]["serial"]
    else:
        location = payload["allowed_edges"]["HAS_COMPONENT"]
    location["external_refs"] = [{"source": source, "uri": uri, "kind": "local_profile"}]
    configure_yaml(monkeypatch, tmp_path, payload)
    with pytest.raises(ValueError, match="vocabulary|Vocabulary"):
        domain_config.get_domain_definition()


def test_recipes_adopt_verified_terms_without_resolving_ambiguous_meanings():
    domain = domain_config.get_domain_definition()
    assert domain.vocabularies["schema"].version == "30.1"
    assert domain.entity_types["RecipeVariant"].external_refs[0].uri == "https://schema.org/Recipe"
    assert domain.entity_types["CookingStep"].external_refs[0].uri == "https://schema.org/HowToStep"
    assert domain.entity_types["RecipeVariant"].properties["cook_time"].external_refs == []
    assert domain.relation_types["HAS_FLAVOR"].external_refs == []
    assert "foodon" not in domain.vocabularies
    ref = domain.relation_types["HAS_AUX_INGREDIENT"].properties["amount_text"].external_refs[0]
    assert ref.uri == "https://schema.org/requiredQuantity"
    assert ref.kind == "relationship_reification"
    validate_graph(domain, recipe_graph())


def test_external_reference_does_not_expand_allowed_graph_types(monkeypatch, tmp_path):
    configure_yaml(monkeypatch, tmp_path, referenced_definition())
    domain = domain_config.get_domain_definition()
    graph = KnowledgeGraph.model_validate(
        {
            "entities": [
                {
                    "id": "outside",
                    "type": "https://schema.org/Thing",
                    "name": "设备 A",
                    "evidence": [{"source_id": "source", "quote": "设备 A"}],
                }
            ],
            "relations": [],
            "sources": [{"id": "source", "text": "设备 A"}],
        }
    )
    with pytest.raises(ValueError, match="Unknown entity type"):
        validate_graph(domain, graph)


def test_runtime_recipe_references_match_the_approved_research_subset():
    domain = domain_config.get_domain_definition()
    path = domain_config.REPOSITORY_ROOT / "docs/ontology/recipe-reference-alignment.yaml"
    research = yaml.safe_load(path.read_text(encoding="utf-8"))
    expected = {
        (local_ref, item["external_uri"], item["mapping"])
        for item in research["alignments"]
        if not item["mapping"].startswith("unresolved_")
        for local_ref in item.get("local_refs", [item.get("local_ref")])
    }
    actual: set[tuple[str, str, str]] = set()
    for owner, definition in (domain.entity_types | domain.relation_types).items():
        actual.update((owner, ref.uri, ref.kind) for ref in definition.external_refs)
        for prop, value in definition.properties.items():
            actual.update((f"{owner}.{prop}", ref.uri, ref.kind) for ref in value.external_refs)
    assert actual == expected
    for key in ("schema", "wtm"):
        assert domain.vocabularies[key].sha256 == research["sources"][key]["sha256"]


@pytest.mark.parametrize("location", ["class", "property"])
def test_shared_class_and_relation_names_cannot_hide_invalid_vocabulary_refs(
    monkeypatch, tmp_path, location
):
    payload = referenced_definition()
    payload["allowed_edges"]["Equipment"] = payload["allowed_edges"].pop("HAS_COMPONENT")
    payload["lexicon"][0]["refs"] = ["Equipment", "Component"]
    target = payload["classes"]["Equipment"]
    if location == "property":
        target = target["properties"]["serial"]
    target["external_refs"][0]["source"] = "undeclared"
    configure_yaml(monkeypatch, tmp_path, payload)
    with pytest.raises(ValueError, match="Unknown vocabulary source"):
        domain_config.get_domain_definition()

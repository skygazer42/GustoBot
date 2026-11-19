"""Deterministic domain definitions and source-backed fact validation."""

import importlib
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest
import yaml


def _api():
    return importlib.import_module("gustobot.domain.knowledge")


def _definition_payload() -> dict[str, Any]:
    return {
        "id": "equipment",
        "name": "Equipment maintenance",
        "description": "Equipment, components and faults.",
        "entity_types": {
            "Equipment": {
                "description": "Maintained equipment",
                "properties": {
                    "serial": {"type": "string", "required": True},
                    "enabled": {"type": "boolean"},
                    "count": {"type": "integer"},
                    "weight": {"type": "number"},
                },
            },
            "Component": {"description": "Equipment component", "properties": {}},
            "Fault": {"description": "Observed fault", "properties": {}},
        },
        "relation_types": {
            "HAS_COMPONENT": {
                "source_types": ["Equipment"],
                "target_types": ["Component"],
                "description": "Equipment contains a component",
                "properties": {"slot": {"type": "integer", "required": True}},
            },
            "HAS_FAULT": {
                "source_types": ["Component"],
                "target_types": ["Fault"],
                "description": "A component exhibits a fault",
                "properties": {"confidence": {"type": "number"}},
            },
            "CAUSES": {
                "source_types": ["Fault"],
                "target_types": ["Fault"],
                "description": "One fault causes another fault",
            },
        },
        "document_scope": "Equipment maintenance records and manuals.",
    }


def _graph_payload() -> dict[str, Any]:
    return {
        "sources": [
            {"id": "doc-1", "text": "Pump A has valve.", "uri": "manual://pump"},
            {"id": "doc-2", "text": "The valve has Leak."},
            {"id": "doc-3", "text": "Leak causes Overheat. Overheat causes Leak."},
            {"id": "doc-unused", "text": "Pump B is unrelated."},
        ],
        "entities": [
            {
                "id": "pump",
                "type": "Equipment",
                "name": "Pump A",
                "properties": {"serial": "SN-1", "enabled": False, "count": 0, "weight": 1.5},
                "evidence": [{"source_id": "doc-1", "quote": "Pump A"}],
            },
            {
                "id": "valve",
                "type": "Component",
                "name": "valve",
                "evidence": [{"source_id": "doc-1", "quote": "valve"}],
            },
            {
                "id": "leak",
                "type": "Fault",
                "name": "Leak",
                "evidence": [{"source_id": "doc-2", "quote": "Leak"}],
            },
            {
                "id": "overheat",
                "type": "Fault",
                "name": "Overheat",
                "evidence": [{"source_id": "doc-3", "quote": "Overheat"}],
            },
        ],
        "relations": [
            {
                "id": "contains",
                "source_id": "pump",
                "target_id": "valve",
                "type": "HAS_COMPONENT",
                "properties": {"slot": 1},
                "evidence": [{"source_id": "doc-1", "quote": "Pump A has valve"}],
            },
            {
                "id": "fault",
                "source_id": "valve",
                "target_id": "leak",
                "type": "HAS_FAULT",
                "properties": {"confidence": 0.8},
                "evidence": [{"source_id": "doc-2", "quote": "valve has Leak"}],
            },
            {
                "id": "cause",
                "source_id": "leak",
                "target_id": "overheat",
                "type": "CAUSES",
                "evidence": [{"source_id": "doc-3", "quote": "Leak causes Overheat"}],
            },
            {
                "id": "cycle",
                "source_id": "overheat",
                "target_id": "leak",
                "type": "CAUSES",
                "evidence": [{"source_id": "doc-3", "quote": "Overheat causes Leak"}],
            },
        ],
    }


def test_valid_equipment_graph_preserves_scalar_values():
    api = _api()
    domain = api.DomainDefinition.model_validate(_definition_payload())
    graph = api.KnowledgeGraph.model_validate(_graph_payload())

    assert api.validate_graph(domain, graph) is None
    assert graph.entities[0].properties["enabled"] is False
    assert type(graph.entities[0].properties["count"]) is int
    assert graph.entities[0].properties["count"] == 0


@pytest.mark.parametrize(
    "value",
    ["", "..", "../other", "nested/../other", "/outside", "C:/outside", "C:outside", "\\outside"],
)
def test_domain_ids_stay_relative_to_the_index_root(value):
    api = _api()
    payload = _definition_payload()
    payload["id"] = value
    with pytest.raises(ValueError):
        api.DomainDefinition.model_validate(payload)


def test_domain_id_cannot_select_the_shared_index_root():
    api = _api()
    payload = _definition_payload()
    payload["id"] = "."
    with pytest.raises(ValueError):
        api.DomainDefinition.model_validate(payload)


@pytest.mark.parametrize(
    ("properties", "error"),
    [
        ({"serial": "SN-1", "unknown": "value"}, "Unknown property"),
        ({"count": 1}, "Required property"),
        ({"serial": 123}, "string"),
        ({"serial": "SN-1", "count": True}, "integer"),
        ({"serial": "SN-1", "count": 1.5}, "integer"),
        ({"serial": "SN-1", "enabled": 1}, "boolean"),
        ({"serial": "SN-1", "weight": False}, "number"),
    ],
)
def test_entity_properties_follow_the_domain_without_coercion(properties, error):
    api = _api()
    payload = _graph_payload()
    payload["entities"][0]["properties"] = properties
    with pytest.raises(ValueError, match=error):
        api.validate_graph(
            api.DomainDefinition.model_validate(_definition_payload()),
            api.KnowledgeGraph.model_validate(payload),
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("type", "COOKED_WITH", "Unknown relation type"),
        ("source_id", "leak", "source type"),
        ("target_id", "leak", "target type"),
        ("source_id", "missing", "Unknown source entity"),
        ("target_id", "missing", "Unknown target entity"),
        ("properties", {"slot": True}, "integer"),
        ("properties", {}, "Required property"),
        ("properties", {"slot": 1, "secret": "value"}, "Unknown property"),
    ],
)
def test_relations_require_declared_endpoints_and_properties(field, value, error):
    api = _api()
    payload = _graph_payload()
    payload["relations"][0][field] = value
    with pytest.raises(ValueError, match=error):
        api.validate_graph(
            api.DomainDefinition.model_validate(_definition_payload()),
            api.KnowledgeGraph.model_validate(payload),
        )


@pytest.mark.parametrize("collection", ["entities", "relations", "sources"])
def test_graph_ids_are_unique_within_each_collection(collection):
    api = _api()
    payload = _graph_payload()
    payload[collection].append(deepcopy(payload[collection][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        api.validate_graph(
            api.DomainDefinition.model_validate(_definition_payload()),
            api.KnowledgeGraph.model_validate(payload),
        )


@pytest.mark.parametrize("collection", ["entities", "relations"])
@pytest.mark.parametrize(
    "evidence",
    [
        [],
        [{"source_id": "doc-missing", "quote": "Pump A"}],
        [{"source_id": "doc-1", "quote": "invented claim"}],
        [{"source_id": "doc-1", "quote": ""}],
        [{"source_id": "doc-1", "quote": " "}],
    ],
)
def test_all_entity_and_relation_evidence_must_quote_a_known_source(collection, evidence):
    api = _api()
    payload = _graph_payload()
    payload[collection][0]["evidence"] = evidence
    with pytest.raises(ValueError):
        api.validate_graph(
            api.DomainDefinition.model_validate(_definition_payload()),
            api.KnowledgeGraph.model_validate(payload),
        )


@pytest.mark.parametrize("endpoint", ["source_types", "target_types"])
def test_domain_relation_definitions_cannot_reference_unknown_entity_types(endpoint):
    api = _api()
    payload = _definition_payload()
    payload["relation_types"]["HAS_COMPONENT"][endpoint] = ["Dish"]
    with pytest.raises(ValueError, match="Unknown entity type"):
        api.validate_graph(
            api.DomainDefinition.model_validate(payload),
            api.KnowledgeGraph(entities=[], relations=[], sources=[]),
        )


def test_extracted_knowledge_has_separate_entity_and_relation_contracts():
    api = _api()
    payload = _graph_payload()
    extracted = api.ExtractedKnowledge.model_validate(
        {"entities": payload["entities"], "relations": payload["relations"]}
    )
    assert extracted.entities[0].type == "Equipment"
    assert extracted.relations[0].source_id == "pump"


@pytest.mark.parametrize("profile", ["recipes", "equipment", "generic"])
def test_domain_profiles_load_relative_to_repository_from_any_cwd(monkeypatch, tmp_path, profile):
    module = importlib.import_module("gustobot.config.domain")
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(KNOWLEDGE_DOMAIN_FILE=f"gustobot/config/domains/{profile}.yaml"),
    )
    monkeypatch.chdir(tmp_path)
    domain = module.get_domain_definition()
    assert domain.id == profile
    api = _api()
    api.validate_graph(domain, api.KnowledgeGraph(entities=[], relations=[], sources=[]))
    assert domain.version
    assert domain.entity_types
    if profile != "recipes":
        assert not any(word in domain.model_dump_json() for word in ["菜谱", "食材", "烹饪"])


def test_equipment_profile_accepts_equipment_graph_and_recipes_rejects_it(monkeypatch):
    module = importlib.import_module("gustobot.config.domain")
    configured = SimpleNamespace(KNOWLEDGE_DOMAIN_FILE="gustobot/config/domains/equipment.yaml")
    monkeypatch.setattr(module, "settings", configured)
    api = _api()
    graph = api.KnowledgeGraph.model_validate(_graph_payload())
    api.validate_graph(module.get_domain_definition(), graph)
    configured.KNOWLEDGE_DOMAIN_FILE = "gustobot/config/domains/recipes.yaml"
    with pytest.raises(ValueError, match="Unknown entity type"):
        api.validate_graph(module.get_domain_definition(), graph)


def test_domain_cache_uses_resolved_path_and_does_not_share_mutable_models(monkeypatch, tmp_path):
    module = importlib.import_module("gustobot.config.domain")
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text(yaml.safe_dump(_definition_payload()), encoding="utf-8")
    second.write_text(yaml.safe_dump({**_definition_payload(), "id": "other"}), encoding="utf-8")
    configured = SimpleNamespace(KNOWLEDGE_DOMAIN_FILE=str(first))
    monkeypatch.setattr(module, "settings", configured)
    loaded = module.get_domain_definition()
    loaded.entity_types.clear()
    assert "Equipment" in module.get_domain_definition().entity_types
    configured.KNOWLEDGE_DOMAIN_FILE = str(second)
    assert module.get_domain_definition().id == "other"


@pytest.mark.parametrize("invalid", ["classes: [unterminated", "id: incomplete"])
def test_invalid_domain_configuration_is_visible(monkeypatch, tmp_path, invalid):
    module = importlib.import_module("gustobot.config.domain")
    path = tmp_path / "invalid.yaml"
    path.write_text(invalid, encoding="utf-8")
    monkeypatch.setattr(module, "settings", SimpleNamespace(KNOWLEDGE_DOMAIN_FILE=str(path)))
    with pytest.raises(ValueError):
        module.get_domain_definition()


def test_missing_domain_configuration_is_visible(monkeypatch, tmp_path):
    module = importlib.import_module("gustobot.config.domain")
    path = tmp_path / "missing.yaml"
    monkeypatch.setattr(module, "settings", SimpleNamespace(KNOWLEDGE_DOMAIN_FILE=str(path)))
    with pytest.raises(FileNotFoundError):
        module.get_domain_definition()


def test_loaded_domain_rejects_unknown_definition_references(monkeypatch, tmp_path):
    module = importlib.import_module("gustobot.config.domain")
    payload = _definition_payload()
    payload["relation_types"]["HAS_COMPONENT"]["target_types"] = ["Unknown"]
    path = tmp_path / "unknown-type.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    monkeypatch.setattr(module, "settings", SimpleNamespace(KNOWLEDGE_DOMAIN_FILE=str(path)))
    with pytest.raises(ValueError, match="Unknown entity type"):
        module.get_domain_definition()

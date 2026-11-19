"""Map recorded recipe fields to facts without asking a model to recreate them."""

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from gustobot.config.domain import UniqueKeyLoader, get_domain_definition
from gustobot.domain.knowledge import (
    DomainDefinition,
    EvidenceReference,
    KnowledgeEntity,
    KnowledgeGraph,
    KnowledgeRelation,
    ScalarValue,
    SourceDocument,
)


class _Binding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class IngredientBinding(_Binding):
    source_fields: list[str]
    relation: str
    role: str


class ClassificationBinding(_Binding):
    source_fields: list[str]
    entity_type: str
    relation: str


class RecipeSourceMapping(_Binding):
    ontology_id: str
    record_fields: dict[str, list[str]]
    ingredient_fields: dict[str, list[str]]
    ingredients: list[IngredientBinding]
    classifications: list[ClassificationBinding]


@lru_cache(maxsize=1)
def _recipe_mapping() -> RecipeSourceMapping:
    path = Path(__file__).resolve().parents[2] / "config/mappings/recipes.yaml"
    mapping = RecipeSourceMapping.model_validate(
        yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    )
    if mapping.ontology_id != "recipes":
        raise ValueError("Recipe mapping must bind the recipes ontology")
    return mapping


def load_recipe_mapping() -> RecipeSourceMapping:
    return _recipe_mapping().model_copy(deep=True)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _identifier(kind: str, *parts: Any) -> str:
    digest = hashlib.sha256(_json(parts).encode("utf-8")).hexdigest()
    return f"recipe-{kind}:{digest}"


def _first_present(record: dict, *fields: str) -> Any:
    for field in fields:
        if field in record:
            return record[field]
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if type(value) in (int, float):
        return str(value)
    raise ValueError("Recipe text and amount fields must be strings or numbers")


def _aliases(name: str) -> list[str]:
    alias = re.sub(r"^(?:(?:#[^#]+#|【[^】]+】|\[[^\]]+\]|\d+[、.．:：])\s*)+", "", name).strip()
    return [alias] if alias and alias != name else []


def _ingredient(item: Any, fields: dict[str, list[str]]) -> tuple[str, dict[str, ScalarValue]]:
    amount = None
    unit = None
    amount_is_text = False
    if isinstance(item, str):
        name = item
    elif isinstance(item, (list, tuple)) and item:
        name = item[0]
        if len(item) > 1:
            amount = _text(item[1])
        if len(item) > 2:
            unit = _text(item[2])
    elif isinstance(item, dict):
        name = _first_present(item, *fields["name"])
        if "amount_text" in item:
            amount = _text(item["amount_text"])
            amount_is_text = True
        else:
            amount = _text(_first_present(item, *fields["amount"]))
        unit = _text(_first_present(item, *fields["unit"]))
    else:
        raise ValueError("Each ingredient must have a recorded name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Each ingredient must have a nonempty recorded name")
    properties: dict[str, ScalarValue] = {}
    if amount is not None:
        bare_number = re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", amount.strip())
        properties["amount_text"] = (
            amount + unit if unit is not None and not amount_is_text and bare_number else amount
        )
    if unit is not None:
        properties["unit"] = unit
    return name, properties


def _items(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    raise ValueError("Recipe ingredient fields must be lists")


def _labels(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        if any(not isinstance(item, str) for item in value):
            raise ValueError("Recipe classifications must contain strings")
        return [item for item in value if item.strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[、/,，；;]+", value) if part.strip()]
    raise ValueError("Recipe classifications must be strings or lists")


def _steps(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        if any(not isinstance(item, str) for item in value):
            raise ValueError("Recipe steps must contain strings")
        return [item for item in value if item.strip()]
    if not isinstance(value, str):
        raise TypeError("Recipe instructions must be strings or lists")
    # Keep the text of each recorded step, including its original numbering.
    parts = re.split(r"(?<!\d)(?=\d+[:：])", value)
    return [part for part in parts if part.strip()]


def recipe_to_facts(
    name: str,
    record: dict,
    *,
    mapping: RecipeSourceMapping | None = None,
    domain: DomainDefinition | None = None,
) -> KnowledgeGraph:
    """Preserve source records, version identities, units and unknown amounts.

    A content change creates a different source and recipe instance. Names and
    display aliases never select which instance an import overwrites. Concepts
    such as ingredients can be shared; relations remain source assertions.
    """
    if not name.strip():
        raise ValueError("Recipe name must not be empty")
    domain = get_domain_definition() if domain is None else domain
    mapping = load_recipe_mapping() if mapping is None else mapping
    if mapping.ontology_id != domain.id:
        raise ValueError("Recipe mapping does not bind the selected ontology")
    semantic_model = domain.semantic_model
    source_text = _json({"name": name, "record": record})
    source_id = _identifier("source", name, record)
    source_uri = _first_present(record, *mapping.record_fields["source_uri"])
    if source_uri is not None and not isinstance(source_uri, str):
        raise ValueError("Recipe source URI must be a string")
    source = SourceDocument(id=source_id, text=source_text, uri=source_uri)

    def evidence(value: Any) -> list[EvidenceReference]:
        return [EvidenceReference(source_id=source_id, quote=_json(value))]

    def entity_id(entity_type: str, legacy_kind: str, *parts: Any, **values: ScalarValue) -> str:
        if semantic_model is None:
            return _identifier(legacy_kind, *parts)
        return semantic_model.identity_id(entity_type, {"source_id": source_id, **values})

    dish_id = entity_id("Dish", "dish", name, name=name)
    variant_id = entity_id("RecipeVariant", "variant", name, record, name=name)
    aliases = _aliases(name)
    instructions = _first_present(record, *mapping.record_fields["instructions"])
    cook_time = _text(_first_present(record, *mapping.record_fields["cook_time"]))
    properties: dict[str, ScalarValue] = {}
    if cook_time is not None:
        properties["cook_time"] = cook_time
    for field in ("prep_duration", "cook_duration", "total_duration"):
        if field in mapping.record_fields:
            duration = _text(_first_present(record, *mapping.record_fields[field]))
            if duration is not None:
                properties[field] = duration
    if instructions is not None:
        properties["instructions"] = (
            instructions if isinstance(instructions, str) else "\n".join(_steps(instructions))
        )
    record_id = _text(_first_present(record, *mapping.record_fields["source_record_id"]))
    if record_id is not None:
        properties["source_record_id"] = record_id
    entities = {
        dish_id: KnowledgeEntity(
            id=dish_id, type="Dish", name=name, aliases=aliases, evidence=evidence(name)
        ),
        variant_id: KnowledgeEntity(
            id=variant_id,
            type="RecipeVariant",
            name=name,
            aliases=aliases,
            properties=properties,
            evidence=evidence(record),
        ),
    }
    relations = [
        KnowledgeRelation(
            id=_identifier("relation", variant_id, "VARIANT_OF", dish_id),
            source_id=variant_id,
            target_id=dish_id,
            type="VARIANT_OF",
            evidence=evidence(name),
        )
    ]

    for binding in mapping.ingredients:
        role, relation_type = binding.role, binding.relation
        for index, item in enumerate(_items(_first_present(record, *binding.source_fields))):
            ingredient_name, amount = _ingredient(item, mapping.ingredient_fields)
            ingredient_id = entity_id(
                "Ingredient", "ingredient", ingredient_name, name=ingredient_name
            )
            reference = evidence(item)
            if ingredient_id not in entities:
                entities[ingredient_id] = KnowledgeEntity(
                    id=ingredient_id,
                    type="Ingredient",
                    name=ingredient_name,
                    evidence=reference,
                )
            relations.append(
                KnowledgeRelation(
                    id=_identifier("relation", variant_id, relation_type, index, ingredient_id),
                    source_id=variant_id,
                    target_id=ingredient_id,
                    type=relation_type,
                    properties={**amount, "role": role},
                    evidence=reference,
                )
            )

    for classification in mapping.classifications:
        entity_type, relation_type = classification.entity_type, classification.relation
        value = _first_present(record, *classification.source_fields)
        for index, label in enumerate(_labels(value)):
            identifier = entity_id(entity_type, entity_type, label, name=label)
            entities[identifier] = KnowledgeEntity(
                id=identifier, type=entity_type, name=label, evidence=evidence(value)
            )
            relations.append(
                KnowledgeRelation(
                    id=_identifier("relation", variant_id, relation_type, index, identifier),
                    source_id=variant_id,
                    target_id=identifier,
                    type=relation_type,
                    evidence=evidence(value),
                )
            )

    for order, instruction in enumerate(_steps(instructions), start=1):
        step_name = f"{name} - Step {order}"
        step_id = entity_id(
            "CookingStep",
            "step",
            variant_id,
            order,
            name=step_name,
            parent_id=variant_id,
            order=order,
        )
        reference = evidence(instructions)
        entities[step_id] = KnowledgeEntity(
            id=step_id,
            type="CookingStep",
            name=step_name,
            properties={"order": order, "instruction": instruction},
            evidence=reference,
        )
        relations.append(
            KnowledgeRelation(
                id=_identifier("relation", variant_id, "HAS_STEP", order),
                source_id=variant_id,
                target_id=step_id,
                type="HAS_STEP",
                properties={"order": order},
                evidence=reference,
            )
        )
    return KnowledgeGraph(entities=list(entities.values()), relations=relations, sources=[source])

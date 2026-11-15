"""Domain contracts and deterministic validation for evidence-backed knowledge."""

from pathlib import PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


ScalarValue = str | int | float | bool


class _KnowledgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class PropertyDefinition(_KnowledgeModel):
    type: Literal["string", "integer", "number", "boolean"]
    required: bool = False


class EntityTypeDefinition(_KnowledgeModel):
    description: str
    properties: dict[str, PropertyDefinition]


class RelationTypeDefinition(_KnowledgeModel):
    source_types: list[str]
    target_types: list[str]
    description: str
    properties: dict[str, PropertyDefinition] = Field(default_factory=dict)


class DomainDefinition(_KnowledgeModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str
    entity_types: dict[str, EntityTypeDefinition]
    relation_types: dict[str, RelationTypeDefinition]
    document_scope: str
    graph_keywords: list[str]
    sql_keywords: list[str]
    document_keywords: list[str]
    document_backend: Literal["lightrag", "legacy_kb"] = "lightrag"
    document_index_namespace: str | None = None
    sql_enabled: bool = False
    sql_db_type: str = "MySQL"
    http_router_modules: list[str] = Field(default_factory=list)
    assistant_instructions: str = ""

    @field_validator("id", "document_index_namespace")
    @classmethod
    def _check_index_path(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return value
        path = PureWindowsPath(value)
        if (
            not value.strip()
            or path.drive
            or path.root
            or ".." in path.parts
            or (info.field_name == "id" and not path.parts)
        ):
            raise ValueError("Domain index paths must stay relative to the index root")
        return value


class SourceDocument(_KnowledgeModel):
    id: str = Field(min_length=1)
    text: str
    uri: str | None = None


class EvidenceReference(_KnowledgeModel):
    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class KnowledgeEntity(_KnowledgeModel):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    properties: dict[str, ScalarValue] = Field(default_factory=dict)
    evidence: list[EvidenceReference] = Field(min_length=1)


class KnowledgeRelation(_KnowledgeModel):
    id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    properties: dict[str, ScalarValue] = Field(default_factory=dict)
    evidence: list[EvidenceReference] = Field(min_length=1)


class ExtractedKnowledge(_KnowledgeModel):
    entities: list[KnowledgeEntity]
    relations: list[KnowledgeRelation]


class KnowledgeGraph(ExtractedKnowledge):
    sources: list[SourceDocument]


def _validate_definition(domain: DomainDefinition) -> None:
    for relation_type, definition in domain.relation_types.items():
        if not definition.source_types or not definition.target_types:
            raise ValueError(f"Relation {relation_type} must declare source and target types")
        for entity_type in [*definition.source_types, *definition.target_types]:
            if entity_type not in domain.entity_types:
                raise ValueError(
                    f"Unknown entity type {entity_type} in relation definition {relation_type}"
                )


def _check_unique_ids(ids: list[str], kind: str) -> None:
    seen = set()
    for identifier in ids:
        if identifier in seen:
            raise ValueError(f"Duplicate {kind} ID: {identifier}")
        seen.add(identifier)


def _validate_properties(
    properties: dict[str, ScalarValue],
    definitions: dict[str, PropertyDefinition],
    owner: str,
) -> None:
    for name in properties:
        if name not in definitions:
            raise ValueError(f"Unknown property {name} on {owner}")
    for name, definition in definitions.items():
        if name not in properties:
            if definition.required:
                raise ValueError(f"Required property {name} missing on {owner}")
            continue
        value = properties[name]
        if definition.type == "string":
            valid = type(value) is str
        elif definition.type == "integer":
            valid = type(value) is int
        elif definition.type == "number":
            valid = type(value) in (int, float)
        else:
            valid = type(value) is bool
        if not valid:
            raise ValueError(f"Property {name} on {owner} must have type {definition.type}")


def _validate_evidence(
    evidence: list[EvidenceReference], sources: dict[str, SourceDocument], owner: str
) -> None:
    if not evidence:
        raise ValueError(f"Evidence is required for {owner}")
    for reference in evidence:
        source = sources.get(reference.source_id)
        if source is None:
            raise ValueError(f"Unknown evidence source {reference.source_id} on {owner}")
        if not reference.quote.strip() or reference.quote not in source.text:
            raise ValueError(f"Evidence quote on {owner} is not present in source {source.id}")


def validate_graph(domain: DomainDefinition, graph: KnowledgeGraph) -> None:
    """Reject undeclared structure, invalid property values and unsupported evidence."""
    _validate_definition(domain)
    _check_unique_ids([source.id for source in graph.sources], "source")
    _check_unique_ids([entity.id for entity in graph.entities], "entity")
    _check_unique_ids([relation.id for relation in graph.relations], "relation")
    sources = {source.id: source for source in graph.sources}
    entities = {entity.id: entity for entity in graph.entities}

    for entity in graph.entities:
        definition = domain.entity_types.get(entity.type)
        if definition is None:
            raise ValueError(f"Unknown entity type {entity.type} on entity {entity.id}")
        _validate_properties(entity.properties, definition.properties, f"entity {entity.id}")
        _validate_evidence(entity.evidence, sources, f"entity {entity.id}")

    for relation in graph.relations:
        relation_definition = domain.relation_types.get(relation.type)
        if relation_definition is None:
            raise ValueError(f"Unknown relation type {relation.type} on relation {relation.id}")
        source_entity = entities.get(relation.source_id)
        target_entity = entities.get(relation.target_id)
        if source_entity is None:
            raise ValueError(
                f"Unknown source entity {relation.source_id} on relation {relation.id}"
            )
        if target_entity is None:
            raise ValueError(
                f"Unknown target entity {relation.target_id} on relation {relation.id}"
            )
        if source_entity.type not in relation_definition.source_types:
            raise ValueError(f"Invalid source type {source_entity.type} on relation {relation.id}")
        if target_entity.type not in relation_definition.target_types:
            raise ValueError(f"Invalid target type {target_entity.type} on relation {relation.id}")
        _validate_properties(
            relation.properties, relation_definition.properties, f"relation {relation.id}"
        )
        _validate_evidence(relation.evidence, sources, f"relation {relation.id}")

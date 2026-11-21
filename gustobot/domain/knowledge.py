"""Domain contracts and deterministic validation for evidence-backed knowledge."""

from collections import defaultdict
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
)

if TYPE_CHECKING:
    from gustobot.domain.formal_ontology import FormalOntology

ScalarValue = str | int | float | bool


class _KnowledgeModel(BaseModel):
    """Base contract for strict, assignment-validated knowledge records."""

    model_config = ConfigDict(
        extra="forbid", strict=True, validate_assignment=True, populate_by_name=True
    )


class VocabularySource(_KnowledgeModel):
    """Pinned external vocabulary metadata and the terms used by this domain."""

    namespace: str = Field(pattern=r"^https?://\S+$")
    version: str = Field(min_length=1)
    definition_url: str = Field(pattern=r"^https?://\S+$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    terms: list[str] = Field(min_length=1)


class ExternalReference(_KnowledgeModel):
    """A provenance link from a local schema element to an external term."""

    source: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    kind: Literal[
        "local_profile",
        "restricted_value",
        "value_projection",
        "text_projection",
        "ordered_steps_projection",
        "related_relation",
        "relationship_reification",
        "target_name_projection",
        "related_concept",
    ]
    note: str = ""


class PropertyDefinition(_KnowledgeModel):
    """Value type, bounds, requiredness, and provenance for one schema property."""

    type: Literal["string", "integer", "number", "boolean"]
    required: bool = False
    description: str = ""
    minimum: int | float | None = None
    maximum: int | float | None = None
    missing: Literal["unknown"] = "unknown"
    external_refs: list[ExternalReference] = Field(default_factory=list)


class EntityTypeDefinition(_KnowledgeModel):
    """Local entity type definition, including identity and property contracts."""

    label: str = ""
    description: str
    identity: Literal[
        "source_assigned", "canonical_name", "source_record_content", "source_and_position"
    ] = "source_assigned"
    grain: str = ""
    external_refs: list[ExternalReference] = Field(default_factory=list)
    properties: dict[str, PropertyDefinition]


class Cardinality(_KnowledgeModel):
    """Minimum and optional maximum count for an outgoing relation type."""

    minimum: int = Field(default=0, alias="min", ge=0)
    maximum: int | None = Field(default=None, alias="max", ge=0)


class RelationTypeDefinition(_KnowledgeModel):
    """Allowed source and target types plus property and cardinality constraints."""

    source_types: list[str] = Field(alias="domain")
    target_types: list[str] = Field(alias="range")
    description: str
    cardinality: Cardinality = Field(default_factory=Cardinality)
    external_refs: list[ExternalReference] = Field(default_factory=list)
    properties: dict[str, PropertyDefinition] = Field(default_factory=dict)


class LexiconEntry(_KnowledgeModel):
    """Terms that map user wording to local ontology references."""

    terms: list[str] = Field(min_length=1)
    refs: list[str] = Field(min_length=1)


class UnitDefinition(_KnowledgeModel):
    """A measurement dimension and its accepted unit aliases."""

    dimension: Literal["mass", "volume", "time", "count"]
    aliases: list[str]


class SubgraphShape(_KnowledgeModel):
    """Relation types required for a complete entity subgraph."""

    required_edges: list[str] = Field(default_factory=list)


class OntologyRule(_KnowledgeModel):
    """A domain integrity rule for a relation property."""

    id: str = Field(min_length=1)
    kind: Literal["unique_relation_property"]
    relation: str
    property: str


class DomainDefinition(_KnowledgeModel):
    """Versioned ontology, vocabulary, and validation policy for one domain."""

    _semantic_model: "FormalOntology | None" = PrivateAttr(default=None)
    id: str = Field(min_length=1)
    version: str = Field(default="1", min_length=1)
    name: str = Field(min_length=1)
    description: str
    entity_types: dict[str, EntityTypeDefinition] = Field(alias="classes")
    relation_types: dict[str, RelationTypeDefinition] = Field(alias="allowed_edges")
    lexicon: list[LexiconEntry] = Field(default_factory=list)
    units: dict[str, UnitDefinition] = Field(default_factory=dict)
    subgraph_shapes: dict[str, SubgraphShape] = Field(default_factory=dict)
    rules: list[OntologyRule] = Field(default_factory=list)
    document_scope: str
    interpretation_notes: list[str] = Field(default_factory=list)
    vocabularies: dict[str, VocabularySource] = Field(default_factory=dict)

    @property
    def semantic_model(self) -> "FormalOntology | None":
        """Compiled executable model; excluded from public JSON and API schemas."""
        return self._semantic_model

    @field_validator("id")
    @classmethod
    def _check_index_path(cls, value: str) -> str:
        path = PureWindowsPath(value)
        if not value.strip() or path.drive or path.root or ".." in path.parts or not path.parts:
            raise ValueError("Domain index paths must stay relative to the index root")
        return value

    def concept_refs(self, text: str) -> set[str]:
        """Resolve approved vocabulary; these references are not query templates."""
        return {
            ref
            for entry in self.lexicon
            if any(term in text for term in entry.terms)
            for ref in entry.refs
        }

    def semantic_catalog(self, text: str) -> dict:
        """Expose matching concepts and their local schema without runtime settings."""
        refs = self.concept_refs(text)
        types = {ref.split(".")[0] for ref in refs if ref.split(".")[0] in self.entity_types}
        edges = {ref.split(".")[0] for ref in refs if ref.split(".")[0] in self.relation_types}
        # With no lexical match, the small class/edge catalogue allows the model
        # to map unfamiliar wording; known terms narrow the schema beforehand.
        if not refs:
            types.update(self.entity_types)
            edges.update(self.relation_types)
        else:
            edges.update(
                key
                for key, value in self.relation_types.items()
                if types.intersection(value.source_types)
            )
        for edge in edges:
            types.update(self.relation_types[edge].source_types)
            types.update(self.relation_types[edge].target_types)
        selected_definitions = [self.entity_types[key] for key in types] + [
            self.relation_types[key] for key in edges
        ]
        vocabulary_ids = {
            reference.source
            for definition in selected_definitions
            for reference in [
                *definition.external_refs,
                *(ref for prop in definition.properties.values() for ref in prop.external_refs),
            ]
        }
        return {
            "id": self.id,
            "version": self.version,
            "vocabularies": {
                key: {"namespace": source.namespace, "version": source.version}
                for key, source in self.vocabularies.items()
                if key in vocabulary_ids
            },
            "classes": {
                key: value.model_dump() for key, value in self.entity_types.items() if key in types
            },
            "allowed_edges": {
                key: value.model_dump(by_alias=True)
                for key, value in self.relation_types.items()
                if key in edges
            },
            "matched_refs": sorted(refs),
            "units": {key: value.model_dump() for key, value in self.units.items()},
            "subgraph_shapes": {
                key: value.model_dump()
                for key, value in self.subgraph_shapes.items()
                if key in types
            },
            "rules": [rule.model_dump() for rule in self.rules if rule.relation in edges],
            "document_scope": self.document_scope,
            "interpretation_notes": self.interpretation_notes,
        }


class SourceDocument(_KnowledgeModel):
    """Authoritative source text against which extracted evidence is checked."""

    id: str = Field(min_length=1)
    text: str
    uri: str | None = None


class EvidenceReference(_KnowledgeModel):
    """Verbatim source quote supporting one extracted assertion."""

    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class KnowledgeEntity(_KnowledgeModel):
    """Typed domain entity with properties, aliases, and source evidence."""

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    properties: dict[str, ScalarValue] = Field(default_factory=dict)
    evidence: list[EvidenceReference] = Field(min_length=1)


class KnowledgeRelation(_KnowledgeModel):
    """Directed, typed edge between entities with properties and evidence."""

    id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    properties: dict[str, ScalarValue] = Field(default_factory=dict)
    evidence: list[EvidenceReference] = Field(min_length=1)


class ExtractedKnowledge(_KnowledgeModel):
    """Entities and relations returned by a knowledge extraction pass."""

    entities: list[KnowledgeEntity]
    relations: list[KnowledgeRelation]


class KnowledgeGraph(ExtractedKnowledge):
    """Extracted knowledge together with the source records it depends on."""

    sources: list[SourceDocument]


def _validate_definition(domain: DomainDefinition) -> None:
    """Check cross-references and consistency across the domain schema."""
    for key, vocabulary in domain.vocabularies.items():
        if (
            not key.strip()
            or not vocabulary.version.strip()
            or any(not term.strip() or term != term.strip() for term in vocabulary.terms)
        ):
            raise ValueError(f"Invalid vocabulary definition {key}")
        _check_unique_ids(vocabulary.terms, f"vocabulary term in {key}")
    for relation_type, definition in domain.relation_types.items():
        if not definition.source_types or not definition.target_types:
            raise ValueError(f"Relation {relation_type} must declare source and target types")
        for entity_type in [*definition.source_types, *definition.target_types]:
            if entity_type not in domain.entity_types:
                raise ValueError(
                    f"Unknown entity type {entity_type} in relation definition {relation_type}"
                )
        cardinality = definition.cardinality
        if cardinality.maximum is not None and cardinality.minimum > cardinality.maximum:
            raise ValueError(f"Invalid cardinality on {relation_type}")
    owners = dict(domain.entity_types) | dict(domain.relation_types)
    definitions: list[tuple[str, EntityTypeDefinition | RelationTypeDefinition]] = [
        *domain.entity_types.items(),
        *domain.relation_types.items(),
    ]
    for owner, owner_definition in definitions:
        references = list(owner_definition.external_refs)
        for referenced_property in owner_definition.properties.values():
            references.extend(referenced_property.external_refs)
        for reference in references:
            source = domain.vocabularies.get(reference.source)
            if source is None:
                raise ValueError(f"Unknown vocabulary source {reference.source} on {owner}")
            if (
                not reference.uri.startswith(source.namespace)
                or reference.uri[len(source.namespace) :] not in source.terms
            ):
                raise ValueError(f"Unknown vocabulary term {reference.uri} on {owner}")
        for name, property_definition in owner_definition.properties.items():
            if (
                property_definition.minimum is not None or property_definition.maximum is not None
            ) and property_definition.type not in {"integer", "number"}:
                raise ValueError(f"Numeric bounds on nonnumeric property {owner}.{name}")
            if (
                property_definition.minimum is not None
                and property_definition.maximum is not None
                and property_definition.minimum > property_definition.maximum
            ):
                raise ValueError(f"Invalid property range {owner}.{name}")
    for entry in domain.lexicon:
        if any(not term.strip() for term in entry.terms):
            raise ValueError("Ontology vocabulary cannot contain a blank term")
        for ref in entry.refs:
            owner, separator, prop = ref.partition(".")
            if owner not in owners or (separator and prop not in owners[owner].properties):
                raise ValueError(f"Unknown ontology reference {ref}")
    for entity_type, shape in domain.subgraph_shapes.items():
        if entity_type not in domain.entity_types:
            raise ValueError(f"Unknown entity type {entity_type} in subgraph shape")
        for edge in shape.required_edges:
            if (
                edge not in domain.relation_types
                or entity_type not in domain.relation_types[edge].source_types
            ):
                raise ValueError(f"Invalid required edge {edge} for {entity_type}")
    _check_unique_ids([rule.id for rule in domain.rules], "rule")
    for rule in domain.rules:
        if (
            rule.relation not in domain.relation_types
            or rule.property not in domain.relation_types[rule.relation].properties
        ):
            raise ValueError(f"Invalid rule property {rule.relation}.{rule.property}")


def _check_unique_ids(ids: list[str], kind: str) -> None:
    """Reject duplicate identifiers within one graph component collection."""
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
    """Validate property names, required values, exact types, and numeric bounds."""
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
        if (
            isinstance(value, (int, float))
            and definition.minimum is not None
            and value < definition.minimum
        ):
            raise ValueError(f"Property {name} on {owner} is below minimum {definition.minimum}")
        if (
            isinstance(value, (int, float))
            and definition.maximum is not None
            and value > definition.maximum
        ):
            raise ValueError(f"Property {name} on {owner} exceeds maximum {definition.maximum}")


def _validate_evidence(
    evidence: list[EvidenceReference], sources: dict[str, SourceDocument], owner: str
) -> None:
    """Require every assertion quote to occur verbatim in a declared source."""
    if not evidence:
        raise ValueError(f"Evidence is required for {owner}")
    for reference in evidence:
        source = sources.get(reference.source_id)
        if source is None:
            raise ValueError(f"Unknown evidence source {reference.source_id} on {owner}")
        if not reference.quote.strip() or reference.quote not in source.text:
            raise ValueError(f"Evidence quote on {owner} is not present in source {source.id}")


def validate_graph(
    domain: DomainDefinition, graph: KnowledgeGraph, *, complete: bool = True
) -> None:
    """Validate assertions; projected reads do not claim a complete object shape."""
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

    outgoing: dict[tuple[str, str], list[KnowledgeRelation]] = defaultdict(list)
    for relation in graph.relations:
        outgoing[relation.source_id, relation.type].append(relation)
    for entity in graph.entities:
        for edge, edge_definition in domain.relation_types.items():
            if entity.type not in edge_definition.source_types:
                continue
            count = len({item.target_id for item in outgoing[entity.id, edge]})
            bounds = edge_definition.cardinality
            if (complete and count < bounds.minimum) or (
                bounds.maximum is not None and count > bounds.maximum
            ):
                raise ValueError(f"Cardinality violated for {entity.id}.{edge}")
        shape = domain.subgraph_shapes.get(entity.type)
        if complete and shape is not None:
            for edge in shape.required_edges:
                if not outgoing[entity.id, edge]:
                    raise ValueError(f"Required edge {edge} missing on {entity.id}")
    for rule in domain.rules:
        for (source_id, edge), relations in outgoing.items():
            if edge != rule.relation:
                continue
            values = [
                item.properties[rule.property]
                for item in relations
                if rule.property in item.properties
            ]
            if len(values) != len(set(values)):
                raise ValueError(
                    f"Rule {rule.id}: {source_id}.{edge}.{rule.property} must be unique"
                )

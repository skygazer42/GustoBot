"""Domain-scoped, evidence-backed Neo4j facts and a bounded typed query compiler.

Counts use distinct anchors. A lookup total counts distinct anchors for property
queries and distinct directed paths for traversals, before the display limit.
Target groups are conjunctive requirements on an anchor, with alternative names
within each group. Count results contain an anchor sample. With include_anchors,
lookup totals count anchors and paths are a separately bounded evidence sample.
"""

import asyncio
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from neo4j import AsyncDriver, AsyncGraphDatabase, AsyncManagedTransaction
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from gustobot.domain.knowledge import (
    DomainDefinition,
    EvidenceReference,
    KnowledgeEntity,
    KnowledgeGraph,
    KnowledgeRelation,
    PropertyDefinition,
    ScalarValue,
    SourceDocument,
    validate_graph,
)
from gustobot.domain.linking import (
    ENTITY_CATALOG_TYPES,
    CatalogPage,
    CatalogRecord,
    GraphRevision,
    LinkedCandidate,
    NameFamilyResult,
    ScopeAuditReport,
    digest,
)
from gustobot.domain.numeric import (
    DURATION_FIELDS,
    NumericCondition,
    NumericCoverage,
    NumericMeasurement,
    NumericRebuildReport,
    NumericSelection,
    OrderSpec,
)


class _GraphModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class EntityCandidate(_GraphModel):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    source_uris: list[str] = Field(default_factory=list)
    summary: dict[str, ScalarValue] = Field(default_factory=dict)


class FactFilter(_GraphModel):
    property: str = Field(min_length=1)
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "in"]
    value: ScalarValue | list[ScalarValue]

    @model_validator(mode="after")
    def _check_operand(self) -> "FactFilter":
        if (self.op == "in") != isinstance(self.value, list):
            raise ValueError("The in operator requires a list; other operators require a scalar")
        return self


class FactProjection(_GraphModel):
    """An optional evidence path, separate from conditions on the anchor set."""

    relation_types: list[str] = Field(min_length=1)
    target_names: list[str] = Field(default_factory=list)

    @field_validator("relation_types", "target_names")
    @classmethod
    def _check_nonblank_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Projection relations and names must not be blank")
        return values


class FactQuery(_GraphModel):
    expected_graph_revision: int | None = Field(default=None, ge=0)
    numeric_conditions: list[NumericCondition] = Field(default_factory=list, max_length=10)
    order: list[OrderSpec] = Field(default_factory=list, max_length=5)
    numeric_selections: list[NumericSelection] = Field(default_factory=list, max_length=10)
    anchor_ids: list[str] = Field(default_factory=list)
    anchor_names: list[str] = Field(default_factory=list, max_length=10)
    entity_type: str | None = None
    relation_types: list[str] = Field(default_factory=list)
    target_names: list[str] = Field(default_factory=list)
    target_name_groups: list[list[str]] = Field(default_factory=list)
    target_group_relation_types: list[list[str]] = Field(default_factory=list)
    include_anchors: bool = False
    projections: list[FactProjection] | None = None
    filters: list[FactFilter] = Field(default_factory=list)
    max_hops: int = Field(default=1, ge=1, le=3)
    limit: int = Field(default=20, ge=1, le=100)
    operation: Literal["lookup", "count"] = "lookup"

    @field_validator("anchor_ids", "anchor_names", "relation_types", "target_names")
    @classmethod
    def _check_nonblank_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Query names and IDs must not be blank")
        return values

    @field_validator("target_name_groups")
    @classmethod
    def _check_target_groups(cls, groups: list[list[str]]) -> list[list[str]]:
        if any(not group or any(not name.strip() for name in group) for group in groups):
            raise ValueError("Target groups require at least one nonblank alternative")
        return groups

    @model_validator(mode="after")
    def _check_group_relations(self) -> "FactQuery":
        if self.target_group_relation_types:
            if len(self.target_group_relation_types) != len(self.target_name_groups):
                raise ValueError("Each relation restriction must bind one target name group")
            if any(
                not group or any(not edge.strip() for edge in group)
                for group in self.target_group_relation_types
            ):
                raise ValueError("Target relation groups must not be empty or blank")
        return self


class FactResult(_GraphModel):
    entities: list[KnowledgeEntity]
    relations: list[KnowledgeRelation]
    sources: list[SourceDocument]
    total: int = Field(ge=0)
    truncated: bool
    ontology_version: str
    numeric_coverage: list[NumericCoverage] = Field(default_factory=list)
    numeric_values: list[NumericMeasurement] = Field(default_factory=list)


class GraphWriteResult(_GraphModel):
    entities: int = Field(ge=0)
    relations: int = Field(ge=0)
    sources: int = Field(ge=0)


class GraphRevisionConflict(RuntimeError):
    """The fact snapshot changed after entity linking selected its objects."""


_PROPERTY_PREFIX = "p__"
_OPERATORS = {
    "eq": "=",
    "ne": "<>",
    "lt": "<",
    "lte": "<=",
    "gt": ">",
    "gte": ">=",
    "in": "IN",
}
_CONSTRAINTS = (
    (
        "CREATE CONSTRAINT gustobot_entity_identity IF NOT EXISTS "
        "FOR (n:GustoEntity) REQUIRE (n.domain_id, n.id) IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT gustobot_source_identity IF NOT EXISTS "
        "FOR (n:GustoSource) REQUIRE (n.domain_id, n.id) IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT gustobot_evidence_identity IF NOT EXISTS "
        "FOR (n:GustoEvidence) REQUIRE (n.domain_id, n.id) IS UNIQUE"
    ),
    (
        "CREATE INDEX gustobot_evidence_owner IF NOT EXISTS FOR (n:GustoEvidence) "
        "ON (n.domain_id, n.owner_kind, n.owner_id)"
    ),
    "CALL db.awaitIndex('gustobot_evidence_owner', 30)",
    (
        "CREATE CONSTRAINT gustobot_relation_identity IF NOT EXISTS "
        "FOR ()-[r:GUSTO_FACT]-() REQUIRE (r.domain_id, r.id) IS UNIQUE"
    ),
    (
        "CREATE CONSTRAINT gustobot_graph_scope_identity IF NOT EXISTS "
        "FOR (n:GustoGraphScope) REQUIRE "
        "(n.domain_id, n.ontology_version, n.ontology_fingerprint) IS UNIQUE"
    ),
    (
        "CREATE INDEX gustobot_entity_name IF NOT EXISTS FOR (n:GustoEntity) "
        "ON (n.domain_id, n.ontology_version, n.name_key)"
    ),
    (
        "CREATE INDEX gustobot_entity_aliases IF NOT EXISTS FOR (n:GustoEntity) "
        "ON (n.domain_id, n.ontology_version, n.alias_keys)"
    ),
    (
        "CREATE FULLTEXT INDEX gustobot_linking_entity_names IF NOT EXISTS "
        "FOR (n:GustoEntity) ON EACH [n.name, n.aliases] "
        "OPTIONS {indexConfig: {`fulltext.analyzer`: 'standard-no-stop-words'}}"
    ),
)

_NUMERIC_INDEXES = (
    (
        "CREATE INDEX gustobot_numeric_amount IF NOT EXISTS FOR ()-[r:GUSTO_FACT]-() "
        "ON (r.domain_id, r.ontology_version, r.n__amount_minimum)"
    ),
    *(
        f"CREATE INDEX gustobot_duration_{grain} IF NOT EXISTS FOR (n:GustoEntity) "
        f"ON (n.domain_id, n.ontology_version, n.n__duration_{grain}_minimum)"
        for grain in DURATION_FIELDS
    ),
)

_CATALOG_SCOPE = """
MATCH (entity:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})
WHERE entity.entity_type IN $entity_types
  AND (NOT $strict_scope OR entity.ontology_fingerprint = $ontology_fingerprint)
"""
_CATALOG_PROJECTION = """
CALL (entity) {
    MATCH (evidence:GustoEvidence {domain_id: $domain_id, owner_kind: 'entity', owner_id: entity.id})
          -[:GUSTO_FROM_SOURCE]->(source:GustoSource {domain_id: $domain_id, ontology_version: $ontology_version})
    WHERE evidence.source_id = source.id
      AND (NOT $strict_scope OR source.ontology_fingerprint = $ontology_fingerprint)
    RETURN collect(DISTINCT source.id) AS source_ids,
           collect(DISTINCT source.uri) AS source_labels
}
CALL (entity) {
    MATCH (entity)-[relation:GUSTO_FACT {domain_id: $domain_id, ontology_version: $ontology_version}]->
          (target:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})
    WHERE (NOT $strict_scope OR (relation.ontology_fingerprint = $ontology_fingerprint
                               AND target.ontology_fingerprint = $ontology_fingerprint))
    RETURN collect(DISTINCT CASE WHEN relation.relation_type = 'BELONGS_TO_CUISINE'
                                AND target.entity_type = 'CuisineStyle' THEN target.name END) AS cuisines,
           collect(DISTINCT CASE WHEN relation.relation_type = 'USES_METHOD'
                                AND target.entity_type = 'CookingMethod' THEN target.name END) AS methods
}
RETURN properties(entity) AS entity, source_ids, source_labels, cuisines, methods
ORDER BY entity.id
"""


def _name_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _escape_lucene(value: str) -> str:
    return re.sub(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)', r"\\\1", value)


def _property_values(properties: Mapping[str, ScalarValue]) -> dict[str, ScalarValue]:
    return {f"{_PROPERTY_PREFIX}{name}": value for name, value in properties.items()}


def _decode_properties(record: Mapping[str, Any]) -> dict[str, ScalarValue]:
    return {
        key[len(_PROPERTY_PREFIX) :]: value
        for key, value in record.items()
        if key.startswith(_PROPERTY_PREFIX)
    }


def validate_filter_value(value: ScalarValue, definition: PropertyDefinition) -> None:
    expected = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
    }
    if type(value) not in expected[definition.type]:
        raise ValueError(f"Filter value must have type {definition.type}")


class Neo4jGraphStore:
    """Own a Neo4j driver, or borrow an injected driver without closing it.

    Explicit fact IDs are unique within a domain, independently of display names.
    A source ID is immutable: changed text or URI requires a different source ID.
    Reimports replace fact properties but retain approved aliases and all evidence.
    """

    def __init__(
        self,
        domain: DomainDefinition,
        *,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        driver: AsyncDriver | None = None,
    ) -> None:
        validate_graph(domain, KnowledgeGraph(entities=[], relations=[], sources=[]))
        self.domain = domain.model_copy(deep=True)
        self.database = database
        self._owns_driver = driver is None
        self._driver = (
            driver if driver is not None else AsyncGraphDatabase.driver(uri, auth=(user, password))
        )
        self._closed = False
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("The graph store is closed")

    async def close(self) -> None:
        if self._closed:
            return
        if self._owns_driver:
            await self._driver.close()
        self._closed = True

    async def _ensure_schema(self) -> None:
        async with self._schema_lock:
            if self._schema_ready:
                return
            async with self._driver.session(database=self.database) as session:
                for statement in (*_CONSTRAINTS, *_NUMERIC_INDEXES):
                    await (await session.run(statement)).consume()
                await (
                    await session.run("CALL db.awaitIndex('gustobot_linking_entity_names', 30)")
                ).consume()
            self._schema_ready = True

    def _linking_scope(self) -> dict[str, str]:
        model = self.domain.semantic_model
        if model is None:
            raise ValueError("Linking catalogs require a compiled formal ontology")
        if model.version != self.domain.version:
            raise ValueError("Declared ontology version differs from the compiled formal model")
        return {
            "domain_id": self.domain.id,
            "ontology_version": self.domain.version,
            "ontology_fingerprint": model.fingerprint,
        }

    async def _read_revision(self, transaction: AsyncManagedTransaction) -> GraphRevision:
        scope = self._linking_scope()
        rows = await (
            await transaction.run(
                "MATCH (scope:GustoGraphScope {domain_id: $domain_id, ontology_version: $ontology_version, "
                "ontology_fingerprint: $ontology_fingerprint}) RETURN scope.state AS state, scope.revision AS revision",
                scope,
            )
        ).data()
        if not rows:
            return GraphRevision(**scope, state="uninitialized", revision=None)
        return GraphRevision(**scope, state=rows[0]["state"], revision=rows[0]["revision"])

    async def graph_revision(self) -> GraphRevision:
        self._check_open()
        async with self._driver.session(database=self.database) as session:
            return await session.execute_read(self._read_revision)

    async def _lock_scope(self, transaction: AsyncManagedTransaction) -> GraphRevision:
        scope = self._linking_scope()
        rows = await (
            await transaction.run(
                "MERGE (scope:GustoGraphScope {domain_id: $domain_id, ontology_version: $ontology_version, "
                "ontology_fingerprint: $ontology_fingerprint}) "
                "ON CREATE SET scope.state = 'uninitialized' "
                "SET scope.write_lock = coalesce(scope.write_lock, 0) + 1 "
                "RETURN scope.state AS state, scope.revision AS revision",
                scope,
            )
        ).data()
        return GraphRevision(**scope, state=rows[0]["state"], revision=rows[0]["revision"])

    @staticmethod
    def _catalog_limit(limit: int) -> None:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Catalog limit must be between 1 and 1000")

    def _catalog_record(self, row: Mapping[str, Any], revision: GraphRevision) -> CatalogRecord:
        entity = row["entity"]
        qualifiers = {}
        if entity.get("p__cook_time") is not None:
            qualifiers["cook_time"] = entity["p__cook_time"]
        for key, values in (("cuisine", row["cuisines"]), ("method", row["methods"])):
            if values:
                qualifiers[key] = "、".join(sorted(set(values)))
        return CatalogRecord.create(
            **self._linking_scope(),
            kind="entity",
            ref_kind="entity",
            ref_id=entity["id"],
            object_type=entity["entity_type"],
            label=entity["name"],
            aliases=entity["aliases"],
            source_ids=row["source_ids"],
            source_labels=row["source_labels"],
            qualifiers=qualifiers,
            graph_revision=revision.revision,
        )

    async def _catalog_records(
        self,
        transaction: AsyncManagedTransaction,
        selection: str,
        parameters: Mapping[str, Any],
        revision: GraphRevision,
    ) -> list[CatalogRecord]:
        rows = await (
            await transaction.run(selection + _CATALOG_PROJECTION, dict(parameters))
        ).data()
        records = []
        for row in rows:
            entity = row["entity"]
            if entity["ontology_version"] != self.domain.version:
                continue
            if (
                revision.state == "ready"
                and entity.get("ontology_fingerprint") != revision.ontology_fingerprint
            ):
                continue
            records.append(self._catalog_record(row, revision))
        return records

    async def export_linking_records(
        self, *, after_id: str | None = None, limit: int
    ) -> CatalogPage:
        self._check_open()
        self._catalog_limit(limit)
        if after_id is not None and (not isinstance(after_id, str) or not after_id):
            raise ValueError("The catalog cursor must be a nonempty entity ID")

        async def export(transaction: AsyncManagedTransaction) -> CatalogPage:
            revision = await self._read_revision(transaction)
            if revision.revision is None:
                raise RuntimeError(
                    f"Graph scope is {revision.state}; explicit bootstrap is required"
                )
            records = await self._catalog_records(
                transaction,
                _CATALOG_SCOPE + "AND ($after_id IS NULL OR entity.id > $after_id) "
                "WITH entity ORDER BY entity.id LIMIT $limit\n",
                self._linking_scope()
                | {
                    "strict_scope": True,
                    "entity_types": list(ENTITY_CATALOG_TYPES),
                    "after_id": after_id,
                    "limit": limit + 1,
                },
                revision,
            )
            return CatalogPage(
                records=records[:limit],
                observed_revision=revision.revision,
                next_after_id=records[limit - 1].ref_id if len(records) > limit else None,
            )

        async with self._driver.session(database=self.database) as session:
            return await session.execute_read(export)

    async def hydrate_candidates(self, ids: Sequence[str]) -> list[LinkedCandidate]:
        self._check_open()
        if not ids:
            return []

        async def hydrate(
            transaction: AsyncManagedTransaction,
        ) -> list[LinkedCandidate]:
            revision = await self._read_revision(transaction)
            if revision.state != "ready":
                raise RuntimeError(
                    f"Graph scope is {revision.state}; explicit bootstrap is required"
                )
            records = await self._catalog_records(
                transaction,
                _CATALOG_SCOPE + "AND entity.id IN $ids\nWITH entity\n",
                self._linking_scope()
                | {
                    "strict_scope": True,
                    "entity_types": list(ENTITY_CATALOG_TYPES),
                    "ids": list(dict.fromkeys(ids)),
                },
                revision,
            )
            return [LinkedCandidate(record=record) for record in records]

        async with self._driver.session(database=self.database) as session:
            return await session.execute_read(hydrate)

    async def lookup_name_family(
        self, candidate_ids: Sequence[str], limit: int = 40
    ) -> NameFamilyResult:
        self._check_open()
        self._catalog_limit(limit)
        if not candidate_ids:
            return NameFamilyResult(items=[])

        async def family(transaction: AsyncManagedTransaction) -> NameFamilyResult:
            revision = await self._read_revision(transaction)
            records = await self._catalog_records(
                transaction,
                """
MATCH (seed:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})
WHERE seed.id IN $ids AND seed.entity_type IN $entity_types
  AND (NOT $strict_scope OR seed.ontology_fingerprint = $ontology_fingerprint)
MATCH (entity:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})
WHERE entity.entity_type = seed.entity_type
  AND (NOT $strict_scope OR entity.ontology_fingerprint = $ontology_fingerprint)
  AND any(name IN [seed.name_key] + seed.alias_keys WHERE name = entity.name_key OR name IN entity.alias_keys)
WITH DISTINCT entity ORDER BY entity.id LIMIT $limit
""",
                self._linking_scope()
                | {
                    "strict_scope": revision.state == "ready",
                    "entity_types": list(ENTITY_CATALOG_TYPES),
                    "ids": list(dict.fromkeys(candidate_ids)),
                    "limit": limit + 1,
                },
                revision,
            )
            return NameFamilyResult(
                items=[
                    LinkedCandidate(record=record, match_sources=["family"])
                    for record in records[:limit]
                ],
                has_more=len(records) > limit,
            )

        async with self._driver.session(database=self.database) as session:
            return await session.execute_read(family)

    async def lexical_candidates(
        self, question: str, *, expected_types: Sequence[str] = (), limit: int = 40
    ) -> list[LinkedCandidate]:
        self._check_open()
        self._catalog_limit(limit)
        if not isinstance(question, str) or not _name_key(question):
            raise ValueError("An entity mention must not be blank")
        if set(expected_types) - set(ENTITY_CATALOG_TYPES):
            raise ValueError("Unknown linking entity types")
        await self._ensure_schema()
        identifier_mentions = list(
            dict.fromkeys(
                [
                    question.strip(),
                    *re.findall(r"[A-Za-z0-9_][A-Za-z0-9_:/-]*(?:\.[A-Za-z0-9_:/-]+)*", question),
                ]
            )
        )
        parameters = self._linking_scope() | {
            "entity_types": list(expected_types or ENTITY_CATALOG_TYPES),
            "name": _name_key(question),
            "ids": identifier_mentions,
            "limit": limit,
        }

        async def lexical(
            transaction: AsyncManagedTransaction,
        ) -> list[LinkedCandidate]:
            revision = await self._read_revision(transaction)
            parameters["strict_scope"] = revision.state == "ready"
            rows = await (
                await transaction.run(
                    _CATALOG_SCOPE
                    + """
AND (entity.id IN $ids OR any(name IN [entity.name_key] + entity.alias_keys
    WHERE name CONTAINS $name OR $name CONTAINS name))
RETURN entity.id AS id, CASE WHEN entity.id IN $ids THEN 'exactid'
    WHEN entity.name_key = $name OR $name IN entity.alias_keys THEN 'exact'
    ELSE 'substring' END AS source
ORDER BY CASE source WHEN 'exactid' THEN 0 WHEN 'exact' THEN 1 ELSE 2 END, id
LIMIT $limit
""",
                    parameters,
                )
            ).data()
            matches = {row["id"]: row["source"] for row in rows}
            if any(source == "exactid" for source in matches.values()):
                matches = {
                    identifier: source
                    for identifier, source in matches.items()
                    if source == "exactid"
                }
            elif len(matches) < limit:
                tokens = re.findall(r"[^\W_]+", question, flags=re.UNICODE)
                if tokens:
                    lucene_query = " OR ".join(
                        '"' + _escape_lucene(token) + '"' for token in tokens
                    )
                    fulltext = await (
                        await transaction.run(
                            "CALL db.index.fulltext.queryNodes('gustobot_linking_entity_names', $lucene_query) YIELD node AS entity, score "
                            "WHERE entity.domain_id = $domain_id AND entity.ontology_version = $ontology_version "
                            "AND entity.entity_type IN $entity_types "
                            "AND (NOT $strict_scope OR entity.ontology_fingerprint = $ontology_fingerprint) "
                            "RETURN entity.id AS id ORDER BY score DESC, id LIMIT $limit",
                            parameters | {"lucene_query": lucene_query},
                        )
                    ).data()
                    for row in fulltext:
                        if len(matches) >= limit:
                            break
                        matches.setdefault(row["id"], "fulltext")
            if not matches:
                return []
            records = await self._catalog_records(
                transaction,
                _CATALOG_SCOPE + "AND entity.id IN $ids\nWITH entity\n",
                parameters | {"ids": list(matches)},
                revision,
            )
            by_id = {record.ref_id: record for record in records}
            return [
                LinkedCandidate(record=by_id[identifier], match_sources=[source])
                for identifier, source in matches.items()
                if identifier in by_id
            ]

        async with self._driver.session(database=self.database) as session:
            return await session.execute_read(lexical)

    async def _scope_snapshot(self, transaction: AsyncManagedTransaction) -> dict[str, Any]:
        """Read every native fact and its actual endpoints; no display/sample limit."""
        nodes = await (
            await transaction.run(
                """
MATCH (node {domain_id: $domain_id})
WHERE node:GustoEntity OR node:GustoSource OR node:GustoEvidence
OPTIONAL MATCH (node)-[:GUSTO_FROM_SOURCE]->(source)
RETURN properties(node) AS values, labels(node) AS labels,
       collect(source {.id, .domain_id}) AS sources
ORDER BY values.id
""",
                {"domain_id": self.domain.id},
            )
        ).data()
        relations = await (
            await transaction.run(
                """
MATCH (source)-[edge:GUSTO_FACT]->(target)
WHERE edge.domain_id = $domain_id OR source.domain_id = $domain_id OR target.domain_id = $domain_id
RETURN properties(edge) AS values, source.id AS source_id, target.id AS target_id,
       source.domain_id AS source_domain, target.domain_id AS target_domain
ORDER BY edge.id
""",
                {"domain_id": self.domain.id},
            )
        ).data()
        return {"nodes": nodes, "relations": relations}

    def _validate_scope_graph(self, graph: KnowledgeGraph) -> None:
        from gustobot.infrastructure.knowledge.semantic_runtime import SemanticRuntime

        model = self.domain.semantic_model
        if model is None:
            raise ValueError("Graph scope audit requires a compiled formal ontology")
        runtime = SemanticRuntime(model)
        runtime.validate_input(graph)
        bound = runtime.bind_graph(graph)

        def identities(entities: Sequence[KnowledgeEntity]) -> dict[str, Any]:
            return {
                entity.id: (
                    entity.type,
                    entity.name,
                    entity.properties,
                    frozenset(entity.aliases),
                    frozenset((item.source_id, item.quote) for item in entity.evidence),
                )
                for entity in entities
            }

        if identities(bound.entities) != identities(graph.entities):
            raise ValueError(
                "Stored fact identities disagree with the formal native identity rules"
            )

    def _audit_snapshot(
        self, snapshot: dict[str, Any], revision: GraphRevision
    ) -> ScopeAuditReport:
        report = ScopeAuditReport(
            scope=revision, existing=len(snapshot["nodes"]) + len(snapshot["relations"])
        )
        entities, relations, sources, evidence_nodes = {}, {}, {}, []
        for row in snapshot["nodes"]:
            value = row["values"]
            if "GustoEntity" in row["labels"]:
                entities[value["id"]] = value
            elif "GustoSource" in row["labels"]:
                sources[value["id"]] = value
            else:
                evidence_nodes.append(row)
            legacy_evidence = "GustoEvidence" in row["labels"] and "ontology_version" not in value
            if (
                not legacy_evidence and value.get("ontology_version") != self.domain.version
            ) or value.get("ontology_fingerprint") not in (
                None,
                revision.ontology_fingerprint,
            ):
                report.unknown_version += 1
        for row in snapshot["relations"]:
            value = row["values"]
            relations[value["id"]] = value
            if value.get("ontology_version") != self.domain.version or value.get(
                "ontology_fingerprint"
            ) not in (None, revision.ontology_fingerprint):
                report.unknown_version += 1
        if report.unknown_version:
            report.errors.append(
                "Facts from an unknown ontology version or fingerprint require explicit migration"
            )
            return report
        try:
            evidence: dict[tuple[str, str], list[EvidenceReference]] = {}
            for row in evidence_nodes:
                value = row["values"]
                owner_kind, owner_id = value["owner_kind"], value["owner_id"]
                owners = (
                    entities
                    if owner_kind == "entity"
                    else relations if owner_kind == "relation" else {}
                )
                expected_id = hashlib.sha256(
                    json.dumps(
                        [owner_kind, owner_id, value["source_id"], value["quote"]],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                if owner_id not in owners or value["id"] != expected_id:
                    raise ValueError(f"Invalid native evidence identity: {value['id']}")
                if (
                    row["sources"] != [{"id": value["source_id"], "domain_id": self.domain.id}]
                    or value["source_id"] not in sources
                ):
                    raise ValueError(f"Evidence source endpoint mismatch: {value['id']}")
                evidence.setdefault((owner_kind, owner_id), []).append(
                    EvidenceReference(source_id=value["source_id"], quote=value["quote"])
                )
            for row in snapshot["relations"]:
                value = row["values"]
                if (
                    row["source_domain"],
                    row["target_domain"],
                    value.get("domain_id"),
                ) != (
                    self.domain.id,
                ) * 3 or (row["source_id"], row["target_id"]) != (
                    value["source_id"],
                    value["target_id"],
                ):
                    raise ValueError(f"Native relationship endpoint mismatch: {value['id']}")
            graph = KnowledgeGraph(
                entities=[
                    KnowledgeEntity(
                        id=value["id"],
                        type=value["entity_type"],
                        name=value["name"],
                        aliases=value["aliases"],
                        properties=_decode_properties(value),
                        evidence=evidence.get(("entity", value["id"]), []),
                    )
                    for value in entities.values()
                ],
                relations=[
                    KnowledgeRelation(
                        id=value["id"],
                        source_id=value["source_id"],
                        target_id=value["target_id"],
                        type=value["relation_type"],
                        properties=_decode_properties(value),
                        evidence=evidence.get(("relation", value["id"]), []),
                    )
                    for value in relations.values()
                ],
                sources=[
                    SourceDocument(id=value["id"], text=value["text"], uri=value.get("uri"))
                    for value in sources.values()
                ],
            )
            self._validate_scope_graph(graph)
        except (KeyError, ValueError) as error:
            report.invalid = report.existing
            report.errors.append(str(error))
            return report
        report.validated = report.existing
        return report

    async def bootstrap_graph_scope(self, *, audit_only: bool) -> ScopeAuditReport:
        self._check_open()
        self._linking_scope()
        if type(audit_only) is not bool:
            raise ValueError("audit_only must be a boolean")

        async def audit(transaction: AsyncManagedTransaction) -> ScopeAuditReport:
            revision = (
                await self._read_revision(transaction)
                if audit_only
                else await self._lock_scope(transaction)
            )
            snapshot = await self._scope_snapshot(transaction)
            report = self._audit_snapshot(snapshot, revision)
            if report.errors:
                return report
            observed = await self._read_revision(transaction)
            if observed != revision or digest(await self._scope_snapshot(transaction)) != digest(
                snapshot
            ):
                report.invalid = report.existing
                report.validated = 0
                report.errors.append(
                    "Graph changed during the scope audit; stop writers before applying"
                )
                return report
            if audit_only:
                return report
            entity_keys = []
            repaired_keys = set()
            for row in snapshot["nodes"]:
                if "GustoEntity" not in row["labels"]:
                    continue
                value = row["values"]
                name_key = _name_key(value["name"])
                alias_keys = list(dict.fromkeys(_name_key(alias) for alias in value["aliases"]))
                entity_keys.append(
                    {"id": value["id"], "name_key": name_key, "alias_keys": alias_keys}
                )
                if value.get("name_key") != name_key or value.get("alias_keys") != alias_keys:
                    repaired_keys.add(value["id"])
            missing = sum(
                row["values"].get("ontology_fingerprint") != revision.ontology_fingerprint
                or ("GustoEntity" in row.get("labels", []) and row["values"]["id"] in repaired_keys)
                for row in [*snapshot["nodes"], *snapshot["relations"]]
            )
            next_revision = revision.revision
            if next_revision is None:
                next_revision = 1 if report.existing else 0
            elif missing:
                next_revision += 1
            await (
                await transaction.run(
                    "UNWIND $entity_keys AS row MATCH (entity:GustoEntity {domain_id: $domain_id, id: row.id}) "
                    "SET entity.name_key = row.name_key, entity.alias_keys = row.alias_keys",
                    {"domain_id": self.domain.id, "entity_keys": entity_keys},
                )
            ).consume()
            await (
                await transaction.run(
                    "MATCH (node {domain_id: $domain_id}) WHERE node:GustoEntity OR node:GustoSource OR node:GustoEvidence "
                    "SET node.ontology_fingerprint = $ontology_fingerprint, node.ontology_version = $ontology_version",
                    self._linking_scope(),
                )
            ).consume()
            await (
                await transaction.run(
                    "MATCH ()-[edge:GUSTO_FACT {domain_id: $domain_id}]->() SET edge.ontology_fingerprint = $ontology_fingerprint",
                    self._linking_scope(),
                )
            ).consume()
            await (
                await transaction.run(
                    "MATCH (scope:GustoGraphScope {domain_id: $domain_id, ontology_version: $ontology_version, ontology_fingerprint: $ontology_fingerprint}) "
                    "SET scope.state = 'ready', scope.revision = $revision",
                    self._linking_scope() | {"revision": next_revision},
                )
            ).consume()
            report.scope = GraphRevision(
                **self._linking_scope(), state="ready", revision=next_revision
            )
            report.backfilled = missing
            return report

        if not audit_only:
            await self._ensure_schema()
        async with self._driver.session(database=self.database) as session:
            operation = session.execute_read if audit_only else session.execute_write
            return await operation(audit)

    async def rebuild_numeric_projection(
        self, *, dry_run: bool = True, batch_size: int = 100
    ) -> NumericRebuildReport:
        """Rebuild derived values only inside an already attested current model scope."""
        from gustobot.infrastructure.knowledge.semantic_runtime import SemanticRuntime

        self._check_open()
        self._catalog_limit(batch_size)
        if type(dry_run) is not bool:
            raise ValueError("dry_run must be a boolean")
        model = self.domain.semantic_model
        if model is None or not model.numeric_projections:
            raise ValueError("Numeric rebuild requires formally declared projections")
        runtime = SemanticRuntime(model)

        async def rebuild(transaction: AsyncManagedTransaction) -> NumericRebuildReport:
            revision = (
                await self._read_revision(transaction)
                if dry_run
                else await self._lock_scope(transaction)
            )
            if revision.state != "ready" or revision.revision is None:
                raise RuntimeError(
                    "Numeric rebuild requires an initialized current ontology scope; old data is not retagged"
                )
            snapshot = await self._scope_snapshot(transaction)
            audit = self._audit_snapshot(snapshot, revision)
            if audit.errors:
                raise ValueError("Numeric rebuild scope audit failed: " + "; ".join(audit.errors))
            entities, relations = [], []
            counts = {"comparable": 0, "unknown": 0, "non_comparable": 0}
            for row in snapshot["nodes"]:
                if "GustoEntity" not in row["labels"]:
                    continue
                value = row["values"]
                projection = runtime.native_numeric_projection(
                    value["entity_type"], _decode_properties(value)
                )
                if projection:
                    entities.append({"id": value["id"], "values": projection})
                    for key, status in projection.items():
                        if key.endswith("_status"):
                            counts[status] += 1
            for row in snapshot["relations"]:
                value = row["values"]
                projection = runtime.native_numeric_projection(
                    value["relation_type"], _decode_properties(value)
                )
                if projection:
                    relations.append({"id": value["id"], "values": projection})
                    counts[projection["n__amount_status"]] += 1
            if await self._read_revision(transaction) != revision or digest(
                await self._scope_snapshot(transaction)
            ) != digest(snapshot):
                raise GraphRevisionConflict("The graph changed during numeric projection rebuild")
            next_revision = revision.revision
            if not dry_run and (entities or relations):
                for collection, match in (
                    (
                        entities,
                        "MATCH (owner:GustoEntity {domain_id: $domain_id, id: row.id})",
                    ),
                    (
                        relations,
                        "MATCH ()-[owner:GUSTO_FACT {domain_id: $domain_id, id: row.id}]->()",
                    ),
                ):
                    for offset in range(0, len(collection), batch_size):
                        await (
                            await transaction.run(
                                "UNWIND $rows AS row " + match + " SET owner += row.values",
                                {
                                    "domain_id": self.domain.id,
                                    "rows": collection[offset : offset + batch_size],
                                },
                            )
                        ).consume()
                next_revision += 1
                await (
                    await transaction.run(
                        "MATCH (scope:GustoGraphScope {domain_id: $domain_id, ontology_version: $ontology_version, ontology_fingerprint: $ontology_fingerprint}) SET scope.revision = $revision",
                        self._linking_scope() | {"revision": next_revision},
                    )
                ).consume()
            return NumericRebuildReport(
                domain_id=self.domain.id,
                ontology_version=self.domain.version,
                ontology_fingerprint=model.fingerprint,
                projection_version=model.numeric_projection_version,
                revision=next_revision,
                applied=not dry_run,
                entities=len(entities),
                relations=len(relations),
                comparable=counts["comparable"],
                unknown=counts["unknown"],
                non_comparable=counts["non_comparable"],
            )

        async with self._driver.session(database=self.database) as session:
            return await (session.execute_read if dry_run else session.execute_write)(rebuild)

    async def resolve_entities(
        self, name: str, entity_types: list[str] | None = None, limit: int = 10
    ) -> list[EntityCandidate]:
        self._check_open()
        if not isinstance(name, str) or not _name_key(name):
            raise ValueError("An entity mention must not be blank")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Candidate limit must be between 1 and 100")
        if entity_types is not None:
            unknown = set(entity_types) - self.domain.entity_types.keys()
            if unknown:
                raise ValueError(f"Unknown entity types: {sorted(unknown)}")
        statement = """
MATCH (entity:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})
WHERE ($entity_types IS NULL OR entity.entity_type IN $entity_types)
  AND (entity.id IN $id_mentions OR (
       NOT EXISTS {
           MATCH (selected:GustoEntity {domain_id: $domain_id})
           WHERE selected.id IN $id_mentions
       }
       AND (entity.name_key CONTAINS $name OR $name CONTAINS entity.name_key
            OR any(alias IN entity.alias_keys WHERE alias CONTAINS $name OR $name CONTAINS alias))))
WITH entity, CASE WHEN entity.id IN $id_mentions THEN 0
                 WHEN entity.name_key = $name THEN 1
                 WHEN $name IN entity.alias_keys THEN 2 ELSE 3 END AS rank,
     reduce(longest = 0, mention IN [entity.name_key] + entity.alias_keys |
         CASE WHEN $name CONTAINS mention AND size(mention) > longest
              THEN size(mention) ELSE longest END) AS mention_length
ORDER BY rank, mention_length DESC, entity.id
LIMIT $limit
CALL (entity) {
    MATCH (evidence:GustoEvidence {domain_id: $domain_id, owner_kind: 'entity', owner_id: entity.id})
          -[:GUSTO_FROM_SOURCE]->(source:GustoSource {domain_id: $domain_id})
    WHERE evidence.source_id = source.id
    WITH DISTINCT source ORDER BY source.id
    RETURN collect(source.id) AS source_ids,
           [item IN collect(source) WHERE item.uri IS NOT NULL | item.uri] AS source_uris
}
RETURN entity.id AS id, entity.entity_type AS type, entity.name AS name,
       entity.aliases AS aliases, source_ids, source_uris,
       {cook_time: entity[$cook_time_property], source_record_id: entity[$record_id_property]} AS summary
ORDER BY rank, mention_length DESC, entity.id
"""
        identifier_mentions = [
            name.strip(),
            *re.findall(r"[A-Za-z0-9_][A-Za-z0-9_:/-]*(?:\.[A-Za-z0-9_:/-]+)*", name),
        ]
        parameters = {
            "domain_id": self.domain.id,
            "ontology_version": self.domain.version,
            "name": _name_key(name),
            "id_mentions": list(dict.fromkeys(identifier_mentions)),
            "cook_time_property": f"{_PROPERTY_PREFIX}cook_time",
            "record_id_property": f"{_PROPERTY_PREFIX}source_record_id",
            "entity_types": entity_types,
            "limit": limit,
        }

        async def resolve(
            transaction: AsyncManagedTransaction,
        ) -> list[EntityCandidate]:
            rows = await (await transaction.run(statement, parameters)).data()
            candidates = []
            for row in rows:
                declared_properties = self.domain.entity_types[row["type"]].properties
                summary = {
                    key: value
                    for key, value in row["summary"].items()
                    if value is not None and key in declared_properties
                }
                candidates.append(
                    EntityCandidate.model_validate(
                        row
                        | {
                            "summary": summary,
                            "source_ids": sorted(set(row["source_ids"])),
                            "source_uris": sorted(set(row["source_uris"])),
                        }
                    )
                )
            return candidates

        async with self._driver.session(database=self.database) as session:
            return await session.execute_read(resolve)

    def _validate_query(self, request: FactQuery) -> None:
        if request.entity_type is not None and request.entity_type not in self.domain.entity_types:
            raise ValueError(f"Unknown entity type: {request.entity_type}")
        unknown_relations = set(request.relation_types) - self.domain.relation_types.keys()
        if unknown_relations:
            raise ValueError(f"Unknown relation types: {sorted(unknown_relations)}")
        if request.projections is not None:
            if not request.include_anchors or request.operation != "lookup":
                raise ValueError("Optional projections require an anchor-preserving lookup")
            if any(
                not set(projection.relation_types) <= set(request.relation_types)
                for projection in request.projections
            ):
                raise ValueError("Projection paths must use the declared query relations")
        if any(
            not set(group) <= set(request.relation_types)
            for group in request.target_group_relation_types
        ):
            raise ValueError("Target relation restrictions must use the declared query relations")
        if not request.relation_types and (
            request.target_names or request.target_name_groups or request.max_hops != 1
        ):
            raise ValueError("Target names and traversal depth require declared relation types")
        if request.entity_type is None:
            if request.filters:
                raise ValueError("Property filters require an explicit anchor entity type")
            return
        for clause in request.filters:
            definition = self.domain.entity_types[request.entity_type].properties.get(
                clause.property
            )
            if definition is None:
                raise ValueError(f"Unknown property {clause.property} on {request.entity_type}")
            if clause.op in ("lt", "lte", "gt", "gte") and definition.type not in (
                "integer",
                "number",
            ):
                raise ValueError("Ordered comparisons require a numeric ontology property")
            values = clause.value if isinstance(clause.value, list) else [clause.value]
            for value in values:
                validate_filter_value(value, definition)

    @staticmethod
    def _path_scope(path: str, relation_parameter: str = "relation_types") -> str:
        return (
            f"all(node IN nodes({path}) WHERE node.domain_id = $domain_id "
            "AND node.ontology_version = $ontology_version) "
            f"AND all(edge IN relationships({path}) WHERE edge.domain_id = $domain_id "
            "AND edge.ontology_version = $ontology_version "
            f"AND edge.relation_type IN ${relation_parameter})"
        )

    def _compile(self, request: FactQuery) -> tuple[str, dict[str, Any]]:
        parameters: dict[str, Any] = {
            "domain_id": self.domain.id,
            "ontology_version": self.domain.version,
            "limit": request.limit,
        }
        predicates = []
        if request.anchor_ids:
            parameters["anchor_ids"] = request.anchor_ids
            predicates.append("anchor.id IN $anchor_ids")
        if request.anchor_names:
            parameters["anchor_names"] = list(
                dict.fromkeys(_name_key(name) for name in request.anchor_names)
            )
            predicates.append(
                "(anchor.name_key IN $anchor_names "
                "OR any(alias IN anchor.alias_keys WHERE alias IN $anchor_names))"
            )
        if request.entity_type is not None:
            parameters["entity_type"] = request.entity_type
            predicates.append("anchor.entity_type = $entity_type")
        for index, clause in enumerate(request.filters):
            parameters[f"property_{index}"] = f"{_PROPERTY_PREFIX}{clause.property}"
            parameters[f"value_{index}"] = clause.value
            predicates.append(f"anchor[$property_{index}] {_OPERATORS[clause.op]} $value_{index}")
        if request.relation_types:
            parameters["relation_types"] = request.relation_types
            groups = [[name] for name in request.target_names] + request.target_name_groups
            groups = [list(dict.fromkeys(_name_key(name) for name in group)) for group in groups]
            parameters["target_names"] = list(
                dict.fromkeys(name for group in groups for name in group)
            )
            for index, group in enumerate(groups):
                parameters[f"target_group_{index}"] = group
                relations_parameter = "relation_types"
                restricted_index = index - len(request.target_names)
                if restricted_index >= 0 and request.target_group_relation_types:
                    relations_parameter = f"target_relations_{index}"
                    parameters[relations_parameter] = request.target_group_relation_types[
                        restricted_index
                    ]
                path = f"required_path_{index}"
                target = f"required_target_{index}"
                predicates.append(
                    "EXISTS { MATCH "
                    f"{path} = (anchor)-[:GUSTO_FACT*1..{request.max_hops}]->({target}:GustoEntity) "
                    f"WHERE {self._path_scope(path, relations_parameter)} AND "
                    f"({target}.name_key IN $target_group_{index} OR "
                    f"any(alias IN {target}.alias_keys WHERE alias IN $target_group_{index})) }}"
                )
            if request.operation == "count" and not groups:
                predicates.append(
                    "EXISTS { MATCH "
                    f"required_path = (anchor)-[:GUSTO_FACT*1..{request.max_hops}]->(:GustoEntity) "
                    f"WHERE {self._path_scope('required_path')} }}"
                )
        anchor_match = "MATCH (anchor:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})"
        if predicates:
            anchor_match += "\nWHERE " + " AND ".join(predicates)
        if request.numeric_conditions or request.order or request.numeric_selections:
            return self._compile_numeric(request, anchor_match, parameters)
        if not request.relation_types or request.operation == "count" or request.projections == []:
            statement = (
                f"CALL {{ {anchor_match} RETURN count(DISTINCT anchor) AS total }}\n"
                f"CALL {{ {anchor_match} WITH DISTINCT anchor ORDER BY anchor.id LIMIT $limit "
                "RETURN collect(properties(anchor)) AS nodes }\n"
                "RETURN total, nodes, [] AS relations"
            )
        elif request.include_anchors:
            sample_paths = (
                "WITH anchors UNWIND anchors AS anchor "
                f"MATCH path = (anchor)-[:GUSTO_FACT*1..{request.max_hops}]->(target:GustoEntity) "
                f"WHERE {self._path_scope('path')}"
            )
            if request.projections is not None:
                parameters["projections"] = [
                    {
                        "relation_types": projection.relation_types,
                        "target_names": list(
                            dict.fromkeys(_name_key(name) for name in projection.target_names)
                        ),
                    }
                    for projection in request.projections
                ]
                sample_paths += (
                    " AND any(projection IN $projections WHERE "
                    "all(edge IN relationships(path) WHERE edge.relation_type IN projection.relation_types) "
                    "AND (size(projection.target_names) = 0 OR target.name_key IN projection.target_names "
                    "OR any(alias IN target.alias_keys WHERE alias IN projection.target_names)))"
                )
            statement = (
                f"CALL {{ {anchor_match} RETURN count(DISTINCT anchor) AS total }}\n"
                f"CALL {{ {anchor_match} WITH DISTINCT anchor ORDER BY anchor.id LIMIT $limit "
                "RETURN collect(anchor) AS anchors }\n"
                f"CALL {{ {sample_paths} RETURN count(DISTINCT path) AS path_total }}\n"
                f"CALL {{ {sample_paths} WITH DISTINCT path, anchor.id AS anchor_id, "
                "[edge IN relationships(path) | edge.id] AS path_ids "
                "ORDER BY anchor_id, path_ids LIMIT $limit RETURN collect(path) AS paths }\n"
                "RETURN total, path_total, [node IN anchors | properties(node)] + "
                "[node IN reduce(items = [], path IN paths | items + nodes(path)) | properties(node)] AS nodes, "
                "[edge IN reduce(items = [], path IN paths | items + relationships(path)) | properties(edge)] AS relations"
            )
        else:
            path_match = (
                f"{anchor_match}\nMATCH path = (anchor)-[:GUSTO_FACT*1..{request.max_hops}]->(target:GustoEntity)\n"
                f"WHERE {self._path_scope('path')}"
            )
            if request.target_names or request.target_name_groups:
                path_match += " AND (target.name_key IN $target_names OR any(alias IN target.alias_keys WHERE alias IN $target_names))"
            statement = (
                f"CALL {{ {path_match} RETURN count(DISTINCT path) AS total }}\n"
                f"CALL {{ {path_match} WITH DISTINCT path, anchor.id AS anchor_id, "
                "[edge IN relationships(path) | edge.id] AS path_ids "
                "ORDER BY anchor_id, path_ids LIMIT $limit RETURN collect(path) AS paths }\n"
                "RETURN total, [node IN reduce(items = [], path IN paths | items + nodes(path)) | properties(node)] AS nodes, "
                "[edge IN reduce(items = [], path IN paths | items + relationships(path)) | properties(edge)] AS relations"
            )
        return statement, parameters

    def _numeric_measure(
        self,
        reference: NumericCondition | OrderSpec | NumericSelection,
        name: str,
        parameters: dict[str, Any],
    ) -> str:
        model = self.domain.semantic_model
        assert model is not None
        if reference.property == "reportedDuration":
            prefix = f"n__duration_{reference.grain}_"
            return (
                "CALL (anchor) { RETURN {overflow: false, items: [{"
                f"status: CASE WHEN anchor.{prefix}version = $numeric_version THEN anchor.{prefix}status ELSE 'non_comparable' END, "
                f"lo: anchor.{prefix}minimum, hi: anchor.{prefix}maximum, dimension: anchor.{prefix}dimension, relation_ids: []"
                f"}}]}} AS {name} }}\n"
            )
        binding = model.property_binding(reference.property)
        target_type = binding.target_type
        assert target_type is not None and reference.target_ref is not None
        parameters[f"{name}_relations"] = list(binding.relation_types)
        parameters[f"{name}_target"] = reference.target_ref
        parameters[f"{name}_names"] = [
            _name_key(value) for value in model.expand_names(reference.target_ref, target_type)
        ]
        parameters[f"{name}_all"] = reference.target_ref in {
            target_type,
            str(model.native_classes[target_type]),
            self.domain.entity_types[target_type].label,
        }
        clause = f"""
CALL (anchor) {{
    OPTIONAL MATCH (anchor)-[use:GUSTO_FACT {{domain_id: $domain_id, ontology_version: $ontology_version, ontology_fingerprint: $ontology_fingerprint}}]->
          (ingredient:GustoEntity {{domain_id: $domain_id, ontology_version: $ontology_version, ontology_fingerprint: $ontology_fingerprint}})
    WHERE use.relation_type IN ${name}_relations
      AND (${name}_all OR ingredient.id = ${name}_target OR ingredient.name_key IN ${name}_names
           OR any(alias IN ingredient.alias_keys WHERE alias IN ${name}_names))
    WITH collect(DISTINCT use {{status: CASE WHEN use.n__amount_version = $numeric_version THEN use.n__amount_status ELSE 'non_comparable' END,
          lo: use.n__amount_minimum, hi: use.n__amount_maximum, dimension: use.n__amount_dimension, relation_ids: [use.id]}}) AS items
"""
        if reference.property == "ingredientUsageAmount":
            return (
                clause + f"RETURN {{overflow: false, items: CASE WHEN size(items) = 0 THEN "
                "[{status: 'unknown', lo: null, hi: null, dimension: null, relation_ids: []}] "
                f"ELSE items END}} AS {name} }}\n"
            )
        return (
            clause
            + f"""
    WITH items, reduce(dimensions = [], item IN items |
        CASE WHEN item.dimension IS NOT NULL AND NOT item.dimension IN dimensions THEN dimensions + [item.dimension] ELSE dimensions END) AS dimensions
    WITH items, dimensions,
         CASE WHEN size(items) = 0 OR any(item IN items WHERE item.status = 'unknown') THEN 'unknown'
              WHEN size(dimensions) <> 1 OR any(item IN items WHERE item.status <> 'comparable' OR item.lo IS NULL OR item.hi IS NULL) THEN 'non_comparable'
              ELSE 'comparable' END AS status
    WITH items, dimensions, status,
         reduce(total = {{lo: 0, hi: 0, overflow: false}}, item IN CASE WHEN status = 'comparable' THEN items ELSE [] END |
             CASE WHEN total.overflow OR item.hi > $numeric_maximums[item.dimension] - total.hi
                  OR item.lo > $numeric_maximums[item.dimension] - total.lo THEN total {{.*, overflow: true}}
                  ELSE {{lo: total.lo + item.lo, hi: total.hi + item.hi, overflow: false}} END) AS total
    RETURN {{overflow: total.overflow, items: [{{status: status, lo: CASE WHEN status = 'comparable' THEN total.lo END,
        hi: CASE WHEN status = 'comparable' THEN total.hi END, dimension: head(dimensions),
        relation_ids: reduce(ids = [], item IN items | ids + item.relation_ids)}}]}} AS {name}
}}\n"""
        )

    def _conjunctive_usage_states(
        self,
        conditions: Sequence[NumericCondition],
        indices: list[int],
        parameters: dict[str, Any],
    ) -> str:
        """Intersect exact predicate ranges before testing any one usage interval."""
        name = f"measure_{indices[0]}"
        dimensions = {parameters[f"measure_{index}_dimension"] for index in indices}
        if len(dimensions) != 1:
            return f"[item IN {name}.items | CASE WHEN item.status = 'unknown' THEN 'unknown' ELSE 'non_comparable' END]"
        model = self.domain.semantic_model
        assert model is not None
        spec = model.numeric_projections[next(iter(dimensions))]
        allowed = [(spec.minimum, spec.maximum)]
        for index in indices:
            condition = conditions[index]
            low, high = (
                parameters[f"measure_{index}_low"],
                parameters[f"measure_{index}_high"],
            )
            if condition.op == "ne":
                allowed = [
                    (start, end)
                    for first, last in allowed
                    for start, end in (
                        (first, min(last, low - 1)),
                        (max(first, low + 1), last),
                    )
                    if start <= end
                ]
            else:
                first = (
                    low + (condition.op == "gt")
                    if condition.op in {"eq", "between", "gte", "gt"}
                    else spec.minimum
                )
                last = (
                    high - (condition.op == "lt")
                    if condition.op in {"eq", "between", "lte", "lt"}
                    else spec.maximum
                )
                allowed = [
                    (max(start, first), min(end, last))
                    for start, end in allowed
                    if max(start, first) <= min(end, last)
                ]
        parameters[f"{name}_allowed"] = [
            {"minimum": first, "maximum": last} for first, last in allowed
        ]
        return (
            f"[item IN {name}.items | CASE WHEN item.status = 'unknown' THEN 'unknown' "
            f"WHEN item.status <> 'comparable' OR item.dimension <> ${name}_dimension OR item.lo IS NULL OR item.hi IS NULL THEN 'non_comparable' "
            f"WHEN any(interval IN ${name}_allowed WHERE item.lo >= interval.minimum AND item.hi <= interval.maximum) THEN 'matched' "
            f"WHEN none(interval IN ${name}_allowed WHERE item.hi >= interval.minimum AND item.lo <= interval.maximum) THEN 'not_matched' "
            "ELSE 'uncertain' END]"
        )

    def _compile_numeric(
        self, request: FactQuery, anchor_match: str, parameters: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        from gustobot.infrastructure.knowledge.semantic_runtime import SemanticRuntime

        model = self.domain.semantic_model
        if model is None or not model.numeric_projections:
            raise ValueError("Numeric predicates require formal numeric projections")
        references: list[NumericCondition | OrderSpec | NumericSelection] = [
            *request.numeric_conditions,
            *request.order,
            *request.numeric_selections,
        ]
        anchor_types = {
            model.property_binding(reference.property).anchor_type for reference in references
        }
        if (
            len(anchor_types) != 1
            or request.entity_type is not None
            and request.entity_type not in anchor_types
        ):
            raise ValueError("Numeric properties require a single compatible anchor type")
        parameters.update(
            self._linking_scope()
            | {
                "numeric_anchor_type": next(iter(anchor_types)),
                "numeric_version": model.numeric_projection_version,
                "numeric_maximums": {
                    key: spec.maximum for key, spec in model.numeric_projections.items()
                },
            }
        )
        anchor_match += (
            (" AND " if "\nWHERE " in anchor_match else "\nWHERE ")
            + "anchor.entity_type = $numeric_anchor_type AND anchor.ontology_fingerprint = $ontology_fingerprint"
        )
        runtime = SemanticRuntime(model)
        clauses, states, order_values, descriptors = [], [], [], []
        count_conditions, count_orders = (
            len(request.numeric_conditions),
            len(request.order),
        )
        for index, reference in enumerate(references):
            name = f"measure_{index}"
            clauses.append(self._numeric_measure(reference, name, parameters))
            role = (
                "condition"
                if index < count_conditions
                else "order" if index < count_conditions + count_orders else "selection"
            )
            descriptors.append(
                {
                    "index": index,
                    "property": reference.property,
                    "target_ref": reference.target_ref,
                    "grain": reference.grain,
                    "role": role,
                }
            )
            if role == "condition":
                condition = request.numeric_conditions[index]
                low_value = condition.minimum if condition.op == "between" else condition.value
                assert low_value is not None
                low, dimension = runtime.request_ticks(low_value, condition.unit)
                high = (
                    runtime.request_ticks(condition.maximum, condition.unit)[0]
                    if condition.maximum is not None
                    else low
                )
                if condition.property == "reportedDuration" and dimension != "time":
                    raise ValueError("Duration conditions require a declared time unit")
                (
                    parameters[f"{name}_low"],
                    parameters[f"{name}_high"],
                    parameters[f"{name}_dimension"],
                ) = (
                    low,
                    high,
                    dimension,
                )
                lo, hi = f"${name}_low", f"${name}_high"
                true_false = {
                    "lte": (f"item.hi <= {lo}", f"item.lo > {lo}"),
                    "lt": (f"item.hi < {lo}", f"item.lo >= {lo}"),
                    "gte": (f"item.lo >= {lo}", f"item.hi < {lo}"),
                    "gt": (f"item.lo > {lo}", f"item.hi <= {lo}"),
                    "eq": (
                        f"item.lo = {lo} AND item.hi = {lo}",
                        f"item.hi < {lo} OR item.lo > {lo}",
                    ),
                    "ne": (
                        f"item.hi < {lo} OR item.lo > {lo}",
                        f"item.lo = {lo} AND item.hi = {lo}",
                    ),
                    "between": (
                        f"item.lo >= {lo} AND item.hi <= {hi}",
                        f"item.hi < {lo} OR item.lo > {hi}",
                    ),
                }
                true, false = true_false[condition.op]
                status = f"CASE WHEN item.status = 'unknown' THEN 'unknown' WHEN item.status <> 'comparable' OR item.dimension <> ${name}_dimension OR item.lo IS NULL OR item.hi IS NULL THEN 'non_comparable' WHEN {true} THEN 'matched' WHEN {false} THEN 'not_matched' ELSE 'uncertain' END"
                states.append(f"[item IN {name}.items | {status}]")
            else:
                states.append(
                    f"[item IN {name}.items | CASE WHEN item.status = 'comparable' THEN 'matched' ELSE item.status END]"
                )
            if role == "order":
                states[-1] = (
                    f"CASE WHEN any(item IN {name}.items WHERE item.status = 'unknown') OR size({name}.items) = 0 THEN ['unknown'] WHEN any(item IN {name}.items WHERE item.status <> 'comparable' OR item.lo IS NULL OR item.hi IS NULL) THEN ['non_comparable'] WHEN any(item IN {name}.items WHERE item.lo <> item.hi OR item.lo <> head({name}.items).lo OR item.dimension <> head({name}.items).dimension) THEN ['uncertain'] ELSE ['matched'] END"
                )
                order_values.append(f"head({name}.items).lo")
        usage_groups: dict[tuple[str, str | None, str], list[int]] = {}
        for index, condition in enumerate(request.numeric_conditions):
            if condition.property == "ingredientUsageAmount":
                usage_groups.setdefault(
                    (condition.property, condition.target_ref, condition.grain), []
                ).append(index)
        for indices in usage_groups.values():
            if len(indices) > 1:
                combined = self._conjunctive_usage_states(
                    request.numeric_conditions, indices, parameters
                )
                for index in indices:
                    states[index] = combined
        parameters["numeric_descriptors"] = descriptors
        parameters["numeric_selections"] = [
            item for item in descriptors if item["role"] == "selection"
        ]
        measures = ", ".join(f"measure_{index}" for index in range(len(references)))
        classifications = ", ".join(
            f"CASE WHEN 'matched' IN states_{index} THEN 'matched' WHEN size(states_{index}) = 0 OR 'unknown' IN states_{index} THEN 'unknown' WHEN 'uncertain' IN states_{index} THEN 'uncertain' WHEN 'non_comparable' IN states_{index} THEN 'non_comparable' ELSE 'not_matched' END"
            for index in range(len(references))
        )
        statement = "CALL () { " + anchor_match + "\n" + "".join(clauses)
        statement += (
            "WITH anchor, "
            + measures
            + ", "
            + ", ".join(f"{state} AS states_{index}" for index, state in enumerate(states))
            + "\n"
        )
        statement += f"RETURN collect({{anchor: anchor, measures: [{measures}], states: [{classifications}], order_values: [{', '.join(order_values)}]}}) AS evaluated }}\n"
        if count_orders:
            condition_match = (
                " AND ".join(
                    f"row.states[{index}] = 'matched'" for index in range(count_conditions)
                )
                or "true"
            )
            dimensions = ", ".join(
                f"reduce(dimensions = [], row IN evaluated | CASE WHEN ({condition_match}) AND row.states[{count_conditions + index}] = 'matched' AND NOT head(row.measures[{count_conditions + index}].items).dimension IN dimensions THEN dimensions + [head(row.measures[{count_conditions + index}].items).dimension] ELSE dimensions END)"
                for index in range(count_orders)
            )
            statement += f"WITH evaluated, [{dimensions}] AS dimensions\n"
            all_states = []
            for index in range(len(references)):
                if count_conditions <= index < count_conditions + count_orders:
                    all_states.append(
                        f"CASE WHEN row.states[{index}] = 'matched' AND (size(dimensions[{index - count_conditions}]) <> 1 OR NOT head(row.measures[{index}].items).dimension IN dimensions[{index - count_conditions}]) THEN 'non_comparable' ELSE row.states[{index}] END"
                    )
                else:
                    all_states.append(f"row.states[{index}]")
            statement += (
                "WITH [row IN evaluated | row {.*, states: ["
                + ", ".join(all_states)
                + "]}] AS evaluated\n"
            )
        match_expression = (
            " AND ".join(f"row.states[{index}] = 'matched'" for index in range(count_conditions))
            or "true"
        )
        statement += f"WITH evaluated, [row IN evaluated WHERE {match_expression}] AS matched\n"
        ordering: list[str] = []
        for index, order in enumerate(request.order):
            ordering.extend(
                (
                    f"CASE WHEN row.states[{count_conditions + index}] = 'matched' THEN 0 ELSE 1 END ASC",
                    f"CASE WHEN row.states[{count_conditions + index}] = 'matched' THEN row.order_values[{index}] END {order.direction.upper()}",
                )
            )
        ordering.append("row.anchor.id ASC")
        statement += (
            "CALL (matched) { UNWIND matched AS row WITH row ORDER BY "
            + ", ".join(ordering)
            + " LIMIT $limit RETURN collect(row) AS selected_rows }\n"
        )
        statement += """
CALL (evaluated) {
    UNWIND $numeric_descriptors AS descriptor
    RETURN collect({property: descriptor.property, target_ref: descriptor.target_ref, grain: descriptor.grain,
        projection_version: $numeric_version, total: size(evaluated),
        matched: size([row IN evaluated WHERE row.states[descriptor.index] = 'matched']),
        not_matched: size([row IN evaluated WHERE row.states[descriptor.index] = 'not_matched']),
        unknown: size([row IN evaluated WHERE row.states[descriptor.index] = 'unknown']),
        uncertain: size([row IN evaluated WHERE row.states[descriptor.index] = 'uncertain']),
        non_comparable: size([row IN evaluated WHERE row.states[descriptor.index] = 'non_comparable'])}) AS numeric_coverage
}
CALL (selected_rows) {
    UNWIND selected_rows AS row UNWIND $numeric_selections AS descriptor
    UNWIND row.measures[descriptor.index].items AS item
    RETURN collect({anchor_id: row.anchor.id, property: descriptor.property, target_ref: descriptor.target_ref,
        grain: descriptor.grain, status: item.status, minimum: item.lo, maximum: item.hi, dimension: item.dimension,
        projection_version: $numeric_version, relation_ids: item.relation_ids}) AS numeric_values
}
WITH *, [row IN selected_rows | row.anchor] AS anchors
"""
        if request.relation_types and request.projections != [] and request.operation != "count":
            path_match = f"UNWIND anchors AS anchor MATCH path = (anchor)-[:GUSTO_FACT*1..{request.max_hops}]->(target:GustoEntity) WHERE {self._path_scope('path')}"
            if request.projections is not None:
                parameters["projections"] = [
                    {
                        "relation_types": projection.relation_types,
                        "target_names": list(
                            dict.fromkeys(_name_key(name) for name in projection.target_names)
                        ),
                    }
                    for projection in request.projections
                ]
                path_match += (
                    " AND any(projection IN $projections WHERE "
                    "all(edge IN relationships(path) WHERE edge.relation_type IN projection.relation_types) "
                    "AND (size(projection.target_names) = 0 OR target.name_key IN projection.target_names "
                    "OR any(alias IN target.alias_keys WHERE alias IN projection.target_names)))"
                )
            statement += (
                f"CALL (anchors) {{ {path_match} RETURN count(DISTINCT path) AS path_total }}\n"
            )
            statement += f"CALL (anchors) {{ {path_match} WITH DISTINCT path, anchor.id AS anchor_id, [edge IN relationships(path) | edge.id] AS ids ORDER BY anchor_id, ids LIMIT $limit RETURN collect(path) AS paths }}\n"
        else:
            statement += "WITH *, [] AS paths, 0 AS path_total\n"
        statement += """
RETURN size(matched) AS total, path_total, numeric_coverage, numeric_values,
       any(row IN evaluated WHERE any(measure IN row.measures WHERE measure.overflow)) AS numeric_overflow,
       [node IN anchors | properties(node)] + [node IN reduce(items = [], path IN paths | items + nodes(path)) | properties(node)] AS nodes,
       [edge IN reduce(items = [], path IN paths | items + relationships(path)) | properties(edge)] AS relations
"""
        return statement, parameters

    async def query(self, request: FactQuery) -> FactResult:
        self._check_open()
        # Revalidate nested mutable models, including in-place list edits.
        request = FactQuery.model_validate(request.model_dump())
        self._validate_query(request)
        statement, parameters = self._compile(request)
        numeric = bool(request.numeric_conditions or request.order or request.numeric_selections)

        async def read(transaction: AsyncManagedTransaction) -> FactResult:
            expected_revision = request.expected_graph_revision
            if expected_revision is not None or numeric:
                revision = await self._read_revision(transaction)
                if (
                    revision.state != "ready"
                    or expected_revision is not None
                    and revision.revision != expected_revision
                ):
                    raise GraphRevisionConflict("The graph changed after the linking snapshot")
                expected_revision = revision.revision
            rows = await (await transaction.run(statement, parameters)).data()
            row = rows[0]
            if numeric and row["numeric_overflow"]:
                raise ValueError("Numeric recipe total exceeds the declared int64 range (overflow)")
            numeric_values = [
                NumericMeasurement.model_validate(value)
                for value in (row["numeric_values"] if numeric else [])
            ]
            nodes = {item["id"]: item for item in row["nodes"]}
            edges = {item["id"]: item for item in row["relations"]}
            evidence: dict[tuple[str, str], list[EvidenceReference]] = {}
            sources: dict[str, SourceDocument] = {}
            if nodes or edges:
                records = await (
                    await transaction.run(
                        """
MATCH (e:GustoEvidence {domain_id: $domain_id})-[:GUSTO_FROM_SOURCE]->(source:GustoSource {domain_id: $domain_id})
WHERE (e.owner_kind = 'entity' AND e.owner_id IN $entity_ids)
   OR (e.owner_kind = 'relation' AND e.owner_id IN $relation_ids)
RETURN e.owner_kind AS owner_kind, e.owner_id AS owner_id,
       e.source_id AS source_id, e.quote AS quote,
       source.id AS id, source.text AS text, source.uri AS uri
ORDER BY owner_kind, owner_id, source_id, quote
""",
                        {
                            "domain_id": self.domain.id,
                            "entity_ids": list(nodes),
                            "relation_ids": sorted(
                                set(edges)
                                | {
                                    identifier
                                    for value in numeric_values
                                    for identifier in value.relation_ids
                                }
                            ),
                        },
                    )
                ).data()
                for record in records:
                    key = (record["owner_kind"], record["owner_id"])
                    evidence.setdefault(key, []).append(
                        EvidenceReference(source_id=record["source_id"], quote=record["quote"])
                    )
                    source = SourceDocument(id=record["id"], text=record["text"], uri=record["uri"])
                    sources[source.id] = source
            numeric_values = [
                value.model_copy(
                    update={
                        "source_ids": sorted(
                            {
                                reference.source_id
                                for identifier in value.relation_ids
                                for reference in evidence.get(("relation", identifier), [])
                            }
                            | {
                                reference.source_id
                                for reference in evidence.get(("entity", value.anchor_id), [])
                            }
                        )
                    }
                )
                for value in numeric_values
            ]
            graph = KnowledgeGraph(
                entities=[
                    KnowledgeEntity(
                        id=item["id"],
                        type=item["entity_type"],
                        name=item["name"],
                        aliases=item["aliases"],
                        properties=_decode_properties(item),
                        evidence=evidence.get(("entity", item["id"]), []),
                    )
                    for item in (
                        nodes.values()
                        if numeric
                        else sorted(nodes.values(), key=lambda item: item["id"])
                    )
                ],
                relations=[
                    KnowledgeRelation(
                        id=item["id"],
                        source_id=item["source_id"],
                        target_id=item["target_id"],
                        type=item["relation_type"],
                        properties=_decode_properties(item),
                        evidence=evidence.get(("relation", item["id"]), []),
                    )
                    for item in sorted(edges.values(), key=lambda item: item["id"])
                ],
                sources=sorted(sources.values(), key=lambda source: source.id),
            )
            validate_graph(self.domain, graph, complete=False)
            if expected_revision is not None:
                revision = await self._read_revision(transaction)
                if revision.state != "ready" or revision.revision != expected_revision:
                    raise GraphRevisionConflict("The graph changed during the fact read")
            return FactResult(
                entities=graph.entities,
                relations=graph.relations,
                sources=graph.sources,
                total=row["total"],
                truncated=row["total"] > request.limit or row.get("path_total", 0) > request.limit,
                ontology_version=self.domain.version,
                numeric_coverage=[
                    NumericCoverage.model_validate(value)
                    for value in (row["numeric_coverage"] if numeric else [])
                ],
                numeric_values=numeric_values,
            )

        async with self._driver.session(database=self.database) as session:
            return await session.execute_read(read)

    async def source_facts(
        self, source: SourceDocument, *, version: str, limit: int = 50
    ) -> FactResult:
        """Read a bounded sample of facts supported by this exact stored content."""
        self._check_open()
        if not 1 <= limit <= 100:
            raise ValueError("Source fact limit must be between 1 and 100")
        if hashlib.sha256(source.text.encode("utf-8")).hexdigest() != version:
            raise ValueError("Source version does not match its canonical content")
        parameters = {
            "domain_id": self.domain.id,
            "ontology_version": self.domain.version,
            "ontology_fingerprint": (
                self.domain.semantic_model.fingerprint
                if self.domain.semantic_model is not None
                else None
            ),
            "source_id": source.id,
            "source_text": source.text,
            "source_uri": source.uri,
            "limit": limit,
        }
        source_scope = """
MATCH (source:GustoSource {domain_id: $domain_id, id: $source_id, ontology_version: $ontology_version})
WHERE source.text = $source_text
  AND (source.uri = $source_uri OR source.uri IS NULL AND $source_uri IS NULL)
  AND ($ontology_fingerprint IS NULL OR source.ontology_fingerprint = $ontology_fingerprint)
"""
        # Every returned endpoint must also have evidence from the selected source.
        selection = """
MATCH (entity:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})
WHERE ($ontology_fingerprint IS NULL OR entity.ontology_fingerprint = $ontology_fingerprint)
  AND EXISTS {
    MATCH (e:GustoEvidence {domain_id: $domain_id, ontology_version: $ontology_version,
           owner_kind: 'entity', owner_id: entity.id, source_id: $source_id})-[:GUSTO_FROM_SOURCE]->(source)
    WHERE $ontology_fingerprint IS NULL OR e.ontology_fingerprint = $ontology_fingerprint
  }
RETURN 'entity' AS kind, properties(entity) AS item, null AS origin, null AS target
UNION ALL
MATCH (origin:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})
      -[edge:GUSTO_FACT {domain_id: $domain_id, ontology_version: $ontology_version}]->
      (target:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})
WHERE ($ontology_fingerprint IS NULL OR
       all(fact IN [origin, edge, target] WHERE fact.ontology_fingerprint = $ontology_fingerprint))
  AND EXISTS {
    MATCH (e:GustoEvidence {domain_id: $domain_id, ontology_version: $ontology_version,
           owner_kind: 'relation', owner_id: edge.id, source_id: $source_id})-[:GUSTO_FROM_SOURCE]->(source)
    WHERE $ontology_fingerprint IS NULL OR e.ontology_fingerprint = $ontology_fingerprint
  }
  AND all(endpoint IN [origin, target] WHERE EXISTS {
    MATCH (e:GustoEvidence {domain_id: $domain_id, ontology_version: $ontology_version,
           owner_kind: 'entity', owner_id: endpoint.id, source_id: $source_id})-[:GUSTO_FROM_SOURCE]->(source)
    WHERE $ontology_fingerprint IS NULL OR e.ontology_fingerprint = $ontology_fingerprint
  })
RETURN 'relation' AS kind, properties(edge) AS item, properties(origin) AS origin, properties(target) AS target
"""

        async def read(transaction: AsyncManagedTransaction) -> FactResult:
            rows = await (
                await transaction.run(
                    source_scope + "CALL (source) {" + selection + "} RETURN count(*) AS total",
                    parameters,
                )
            ).data()
            total = rows[0]["total"]
            selected = await (
                await transaction.run(
                    source_scope
                    + "CALL (source) {"
                    + selection
                    + "} RETURN kind, item, origin, target ORDER BY kind DESC, item.id LIMIT $limit",
                    parameters,
                )
            ).data()
            nodes, edges = {}, {}
            for row in selected:
                if row["kind"] == "entity":
                    nodes[row["item"]["id"]] = row["item"]
                else:
                    edges[row["item"]["id"]] = row["item"]
                    for endpoint in (row["origin"], row["target"]):
                        nodes[endpoint["id"]] = endpoint
            evidence: dict[tuple[str, str], list[EvidenceReference]] = {}
            truncated = total > limit
            if nodes or edges:
                records = await (
                    await transaction.run(
                        """
UNWIND $owners AS owner
CALL (owner) {
    MATCH (e:GustoEvidence {domain_id: $domain_id, ontology_version: $ontology_version,
           owner_kind: owner.kind, owner_id: owner.id, source_id: $source_id})
          -[:GUSTO_FROM_SOURCE]->(source:GustoSource {domain_id: $domain_id,
            id: $source_id, ontology_version: $ontology_version})
    WHERE source.text = $source_text
      AND (source.uri = $source_uri OR source.uri IS NULL AND $source_uri IS NULL)
      AND ($ontology_fingerprint IS NULL OR
           e.ontology_fingerprint = $ontology_fingerprint AND source.ontology_fingerprint = $ontology_fingerprint)
    WITH DISTINCT e.source_id AS source_id, e.quote AS quote ORDER BY quote LIMIT 11
    RETURN collect({source_id: source_id, quote: quote}) AS references
}
RETURN owner.kind AS owner_kind, owner.id AS owner_id, references
""",
                        parameters
                        | {
                            "owners": [
                                {"kind": kind, "id": identifier}
                                for kind, collection in (("entity", nodes), ("relation", edges))
                                for identifier in sorted(collection)
                            ]
                        },
                    )
                ).data()
                for row in records:
                    truncated = truncated or len(row["references"]) > 10
                    evidence[(row["owner_kind"], row["owner_id"])] = [
                        EvidenceReference.model_validate(reference)
                        for reference in row["references"][:10]
                    ]
            graph = KnowledgeGraph(
                entities=[
                    KnowledgeEntity(
                        id=item["id"],
                        type=item["entity_type"],
                        name=item["name"],
                        aliases=item["aliases"],
                        properties=_decode_properties(item),
                        evidence=evidence[("entity", item["id"])],
                    )
                    for item in sorted(nodes.values(), key=lambda item: item["id"])
                ],
                relations=[
                    KnowledgeRelation(
                        id=item["id"],
                        source_id=item["source_id"],
                        target_id=item["target_id"],
                        type=item["relation_type"],
                        properties=_decode_properties(item),
                        evidence=evidence[("relation", item["id"])],
                    )
                    for item in sorted(edges.values(), key=lambda item: item["id"])
                ],
                sources=[source] if nodes or edges else [],
            )
            validate_graph(self.domain, graph, complete=False)
            return FactResult(
                **graph.model_dump(),
                total=total,
                truncated=truncated,
                ontology_version=self.domain.version,
            )

        async with self._driver.session(database=self.database) as session:
            return await session.execute_read(read)

    def _write_rows(
        self, graph: KnowledgeGraph
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        entities = []
        relations = []
        evidence = []
        semantic = None
        model = self.domain.semantic_model
        if model is not None and model.numeric_projections:
            from gustobot.infrastructure.knowledge.semantic_runtime import (
                SemanticRuntime,
            )

            semantic = SemanticRuntime(model)
        for kind, collection in (
            ("entity", graph.entities),
            ("relation", graph.relations),
        ):
            for fact in collection:
                for reference in fact.evidence:
                    identity = json.dumps(
                        [kind, fact.id, reference.source_id, reference.quote],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    evidence.append(
                        {
                            "id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
                            "owner_kind": kind,
                            "owner_id": fact.id,
                            "source_id": reference.source_id,
                            "quote": reference.quote,
                        }
                    )
        for entity in graph.entities:
            if not _name_key(entity.name) or any(not _name_key(alias) for alias in entity.aliases):
                raise ValueError("Entity names and aliases must not be blank")
            values = {
                "domain_id": self.domain.id,
                "id": entity.id,
                "entity_type": entity.type,
                "name": entity.name,
                "name_key": _name_key(entity.name),
                "aliases": list(dict.fromkeys(entity.aliases)),
                "alias_keys": list(dict.fromkeys(_name_key(alias) for alias in entity.aliases)),
                "ontology_version": self.domain.version,
                **(
                    {"ontology_fingerprint": self.domain.semantic_model.fingerprint}
                    if self.domain.semantic_model is not None
                    else {}
                ),
                **_property_values(entity.properties),
            }
            if semantic is not None:
                values.update(semantic.native_numeric_projection(entity.type, entity.properties))
            entities.append({"id": entity.id, "values": values})
        for relation in graph.relations:
            values = {
                "domain_id": self.domain.id,
                "id": relation.id,
                "source_id": relation.source_id,
                "target_id": relation.target_id,
                "relation_type": relation.type,
                "ontology_version": self.domain.version,
                **(
                    {"ontology_fingerprint": self.domain.semantic_model.fingerprint}
                    if self.domain.semantic_model is not None
                    else {}
                ),
                **_property_values(relation.properties),
            }
            if semantic is not None:
                values.update(
                    semantic.native_numeric_projection(relation.type, relation.properties)
                )
            relations.append(
                {
                    "id": relation.id,
                    "source_id": relation.source_id,
                    "target_id": relation.target_id,
                    "values": values,
                }
            )
        return entities, relations, evidence

    async def _validate_merged_constraints(
        self, transaction: AsyncManagedTransaction, anchor_ids: list[str]
    ) -> None:
        """Validate the current stored union while the write transaction holds locks."""
        match = """
MATCH (anchor:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})
WHERE anchor.id IN $anchor_ids AND anchor.entity_type IN $source_types
MATCH (anchor)-[relation:GUSTO_FACT {domain_id: $domain_id, ontology_version: $ontology_version}]->
      (target:GustoEntity {domain_id: $domain_id, ontology_version: $ontology_version})
WHERE relation.relation_type = $relation_type
"""
        scope: dict[str, Any] = {
            "domain_id": self.domain.id,
            "ontology_version": self.domain.version,
            "anchor_ids": anchor_ids,
        }
        for edge, definition in self.domain.relation_types.items():
            maximum = definition.cardinality.maximum
            if maximum is None:
                continue
            violations = await (
                await transaction.run(
                    match + "WITH anchor.id AS anchor_id, count(DISTINCT target.id) AS total "
                    "WHERE total > $maximum RETURN anchor_id LIMIT 1",
                    scope
                    | {
                        "source_types": definition.source_types,
                        "relation_type": edge,
                        "maximum": maximum,
                    },
                )
            ).data()
            if violations:
                raise ValueError(f"Cardinality violated for {violations[0]['anchor_id']}.{edge}")
        for rule in self.domain.rules:
            definition = self.domain.relation_types[rule.relation]
            violations = await (
                await transaction.run(
                    match + "WITH anchor.id AS anchor_id, relation[$property] AS value, "
                    "count(DISTINCT relation.id) AS total "
                    "WHERE value IS NOT NULL AND total > 1 RETURN anchor_id LIMIT 1",
                    scope
                    | {
                        "source_types": definition.source_types,
                        "relation_type": rule.relation,
                        "property": f"{_PROPERTY_PREFIX}{rule.property}",
                    },
                )
            ).data()
            if violations:
                raise ValueError(
                    f"Rule {rule.id}: {violations[0]['anchor_id']}."
                    f"{rule.relation}.{rule.property} must be unique"
                )

    def _assert_write_scope(self, stored: Mapping[str, Any]) -> None:
        if self.domain.semantic_model is not None and (
            stored["ontology_version"] != self.domain.version
            or stored["ontology_fingerprint"] != self.domain.semantic_model.fingerprint
        ):
            raise ValueError(
                f"Stored identity belongs to a different ontology scope: {stored['id']}"
            )

    async def upsert(self, graph: KnowledgeGraph) -> GraphWriteResult:
        self._check_open()
        graph = KnowledgeGraph.model_validate(graph.model_dump())
        validate_graph(self.domain, graph)
        if not graph.entities and not graph.relations and not graph.sources:
            return GraphWriteResult(entities=0, relations=0, sources=0)
        entities, relations, evidence = self._write_rows(graph)
        await self._ensure_schema()

        async def write(transaction: AsyncManagedTransaction) -> GraphWriteResult:
            scope_revision = None
            if self.domain.semantic_model is not None:
                scope_revision = await self._lock_scope(transaction)
                if scope_revision.state != "ready":
                    rows = await (
                        await transaction.run(
                            "MATCH (node {domain_id: $domain_id}) "
                            "WHERE node:GustoEntity OR node:GustoSource OR node:GustoEvidence "
                            "RETURN count(node) AS existing",
                            {"domain_id": self.domain.id},
                        )
                    ).data()
                    if rows[0]["existing"]:
                        raise RuntimeError(
                            "Existing graph facts require explicit bootstrap audit before writing"
                        )
                    scope_revision = GraphRevision(
                        **self._linking_scope(), state="ready", revision=0
                    )
                if scope_revision.revision == 0:
                    self._validate_scope_graph(graph)
            entity_by_id = {entity.id: entity for entity in graph.entities}
            relation_by_id = {relation.id: relation for relation in graph.relations}
            existing_entities = await (
                await transaction.run(
                    "MATCH (entity:GustoEntity {domain_id: $domain_id}) WHERE entity.id IN $ids "
                    "RETURN entity.id AS id, entity.entity_type AS type, "
                    "entity.ontology_version AS ontology_version, entity.ontology_fingerprint AS ontology_fingerprint",
                    {"domain_id": self.domain.id, "ids": list(entity_by_id)},
                )
            ).data()
            for existing in existing_entities:
                self._assert_write_scope(existing)
                if existing["type"] != entity_by_id[existing["id"]].type:
                    raise ValueError(
                        f"Entity identity conflicts with existing type: {existing['id']}"
                    )
            existing_relations = await (
                await transaction.run(
                    "MATCH ()-[relation:GUSTO_FACT {domain_id: $domain_id}]->() WHERE relation.id IN $ids "
                    "RETURN relation.id AS id, relation.source_id AS source_id, relation.target_id AS target_id, relation.relation_type AS type, "
                    "relation.ontology_version AS ontology_version, relation.ontology_fingerprint AS ontology_fingerprint",
                    {"domain_id": self.domain.id, "ids": list(relation_by_id)},
                )
            ).data()
            for existing in existing_relations:
                self._assert_write_scope(existing)
                fact = relation_by_id[existing["id"]]
                if (existing["source_id"], existing["target_id"], existing["type"]) != (
                    fact.source_id,
                    fact.target_id,
                    fact.type,
                ):
                    raise ValueError(
                        f"Relation identity conflicts with existing endpoints or type: {fact.id}"
                    )
            sources = {source.id: source for source in graph.sources}
            stored_sources = await (
                await transaction.run(
                    """
UNWIND $sources AS row
MERGE (source:GustoSource {domain_id: $domain_id, id: row.id})
ON CREATE SET source.text = row.text, source.uri = row.uri, source.ontology_version = $ontology_version,
              source.ontology_fingerprint = $ontology_fingerprint
RETURN source.id AS id, source.text AS text, source.uri AS uri,
       source.ontology_version AS ontology_version, source.ontology_fingerprint AS ontology_fingerprint
""",
                    {
                        "domain_id": self.domain.id,
                        "ontology_version": self.domain.version,
                        "ontology_fingerprint": (
                            self.domain.semantic_model.fingerprint
                            if self.domain.semantic_model is not None
                            else None
                        ),
                        "sources": [source.model_dump() for source in graph.sources],
                    },
                )
            ).data()
            for stored in stored_sources:
                self._assert_write_scope(stored)
                if (
                    SourceDocument.model_validate(
                        {key: stored[key] for key in ("id", "text", "uri")}
                    )
                    != sources[stored["id"]]
                ):
                    raise ValueError(
                        f"Source identity is immutable; use a new source ID: {stored['id']}"
                    )
            stored_entities = await (
                await transaction.run(
                    """
UNWIND $entities AS row
MERGE (entity:GustoEntity {domain_id: $domain_id, id: row.id})
ON CREATE SET entity.entity_type = row.values.entity_type,
              entity.ontology_version = row.values.ontology_version, entity.ontology_fingerprint = row.values.ontology_fingerprint
WITH entity, row, entity.entity_type AS original_type,
     entity.ontology_version AS original_version, entity.ontology_fingerprint AS original_fingerprint,
     coalesce(entity.aliases, []) AS aliases, coalesce(entity.alias_keys, []) AS alias_keys
SET entity = row.values
SET entity.aliases = reduce(items = [], alias IN aliases + row.values.aliases | CASE WHEN alias IN items THEN items ELSE items + [alias] END),
    entity.alias_keys = reduce(items = [], alias IN alias_keys + row.values.alias_keys | CASE WHEN alias IN items THEN items ELSE items + [alias] END)
RETURN entity.id AS id, original_type AS type,
       original_version AS ontology_version, original_fingerprint AS ontology_fingerprint
""",
                    {"domain_id": self.domain.id, "entities": entities},
                )
            ).data()
            for stored in stored_entities:
                self._assert_write_scope(stored)
                if stored["type"] != entity_by_id[stored["id"]].type:
                    raise ValueError(
                        f"Entity identity conflicts with existing type: {stored['id']}"
                    )
            stored_relations = await (
                await transaction.run(
                    """
UNWIND $relations AS row
MATCH (source:GustoEntity {domain_id: $domain_id, id: row.source_id}),
      (target:GustoEntity {domain_id: $domain_id, id: row.target_id})
MERGE (source)-[relation:GUSTO_FACT {domain_id: $domain_id, id: row.id}]->(target)
ON CREATE SET relation.relation_type = row.values.relation_type,
              relation.ontology_version = row.values.ontology_version, relation.ontology_fingerprint = row.values.ontology_fingerprint
WITH relation, row, relation.relation_type AS original_type,
     relation.ontology_version AS original_version, relation.ontology_fingerprint AS original_fingerprint
SET relation = row.values
RETURN relation.id AS id, original_type AS type,
       original_version AS ontology_version, original_fingerprint AS ontology_fingerprint
""",
                    {"domain_id": self.domain.id, "relations": relations},
                )
            ).data()
            for stored in stored_relations:
                self._assert_write_scope(stored)
                if stored["type"] != relation_by_id[stored["id"]].type:
                    raise ValueError(
                        f"Relation identity conflicts with existing type: {stored['id']}"
                    )
            await self._validate_merged_constraints(transaction, list(entity_by_id))
            await (
                await transaction.run(
                    """
UNWIND $evidence AS row
MATCH (source:GustoSource {domain_id: $domain_id, id: row.source_id})
MERGE (evidence:GustoEvidence {domain_id: $domain_id, id: row.id})
ON CREATE SET evidence.owner_kind = row.owner_kind, evidence.owner_id = row.owner_id,
              evidence.source_id = row.source_id, evidence.quote = row.quote
SET evidence.ontology_version = $ontology_version, evidence.ontology_fingerprint = $ontology_fingerprint
MERGE (evidence)-[:GUSTO_FROM_SOURCE]->(source)
""",
                    {
                        "domain_id": self.domain.id,
                        "ontology_version": self.domain.version,
                        "ontology_fingerprint": (
                            self.domain.semantic_model.fingerprint
                            if self.domain.semantic_model is not None
                            else None
                        ),
                        "evidence": evidence,
                    },
                )
            ).consume()
            if scope_revision is not None:
                assert scope_revision.revision is not None
                await (
                    await transaction.run(
                        "MATCH (scope:GustoGraphScope {domain_id: $domain_id, ontology_version: $ontology_version, ontology_fingerprint: $ontology_fingerprint}) "
                        "SET scope.state = 'ready', scope.revision = $revision",
                        self._linking_scope() | {"revision": scope_revision.revision + 1},
                    )
                ).consume()
            return GraphWriteResult(
                entities=len(graph.entities),
                relations=len(graph.relations),
                sources=len(graph.sources),
            )

        async with self._driver.session(database=self.database) as session:
            return await session.execute_write(write)

"""Execute the compiled ontology on assertion graphs and answer evidence.

The property graph stays the persistence projection. Stable fact identities
become RDF resources; each ingredient edge becomes an IngredientUse, with a
separate quantity and evidence. Raw assertions are validated before inference.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict, defaultdict
from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction
from threading import RLock
from typing import Any, cast
from urllib.parse import quote

from owlrl import DeductiveClosure, OWLRL_Semantics
from pydantic import BaseModel, ConfigDict, Field
from pyshacl import validate as validate_shapes
from rdflib import RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import SH, XSD

from gustobot.domain.formal_ontology import FormalOntology
from gustobot.domain.knowledge import (
    DomainDefinition,
    EvidenceReference,
    KnowledgeEntity,
    KnowledgeGraph,
    KnowledgeRelation,
    ScalarValue,
    validate_graph,
)
from gustobot.domain.numeric import (
    DEFAULT_NUMERIC_GRAINS,
    DURATION_FIELDS,
    NumericGrain,
    NumericMeasurement,
    NumericValue,
    duration_components,
    exact_number,
)


class SemanticSelection(BaseModel):
    """Requested business property and optional target, unit, and grain."""

    model_config = ConfigDict(extra="forbid")
    property: str = Field(min_length=1)
    target: str | None = None
    unit: str | None = None
    grain: NumericGrain | None = None


class SemanticIssue(BaseModel):
    """One native or SHACL validation issue with its affected focus and path."""

    focus_node: str | None = None
    path: str | None = None
    source_shape: str | None = None
    constraint: str | None = None
    message: str
    severity: str = str(SH.Violation)


class SemanticValidationReport(BaseModel):
    """Conformance result tied to the exact ontology version and fingerprint."""

    conforms: bool
    ontology_version: str
    ontology_fingerprint: str
    issues: list[SemanticIssue] = Field(default_factory=list)


class SemanticValidationError(ValueError):
    """Validation exception that retains the structured issue report."""

    def __init__(self, report: SemanticValidationReport):
        self.report = report
        super().__init__("; ".join(issue.message for issue in report.issues))


class SemanticEvaluation(BaseModel):
    """Evidence-backed answer and derivation diagnostics from semantic evaluation."""

    message: str
    status: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    assertions: list[dict[str, Any]] = Field(default_factory=list)
    derivations: list[dict[str, Any]] = Field(default_factory=list)
    model_version: str


class _Quantity(BaseModel):
    """Parsed quantity range retaining its original text and unit."""

    kind: str
    original: str
    unit_text: str | None = None
    value: Decimal | None = None
    maximum: Decimal | None = None


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_RANGE = re.compile(rf"^\s*({_NUMBER})\s*(?:-|~|～|至|—)\s*({_NUMBER})\s*([^\d]*)$")
_MEASURE = re.compile(rf"^\s*({_NUMBER})\s*([^\d]*)$")


def _resource(kind: str, identifier: str) -> URIRef:
    return URIRef(f"urn:gustobot:{kind}:{quote(identifier, safe='')}")


def _literal(value: ScalarValue) -> Literal:
    return Literal(value, datatype=XSD.string) if isinstance(value, str) else Literal(value)


def _digest(kind: str, value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return f"semantic-{kind}:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _deduplicate_evidence(values: list[EvidenceReference]) -> list[EvidenceReference]:
    return [
        EvidenceReference(source_id=source_id, quote=text)
        for source_id, text in sorted({(value.source_id, value.quote) for value in values})
    ]


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _exact_decimal(value: Fraction) -> Decimal:
    denominator, twos, fives = value.denominator, 0, 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        raise ValueError("单位比例无法表示为有限精确小数")
    places = max(twos, fives)
    integer = value.numerator * 2 ** (places - twos) * 5 ** (places - fives)
    return Decimal(
        (
            1 if integer < 0 else 0,
            tuple(int(char) for char in str(abs(integer))),
            -places,
        )
    )


class SemanticRuntime:
    """Bind graph assertions, validate ontology constraints, and derive answers."""

    def __init__(self, model: FormalOntology):
        self.model = model
        self.domain = model.domain_definition()
        self._inference_lock = RLock()
        self._inference_cache: OrderedDict[tuple, tuple] = OrderedDict()

    def _report(self, issues: list[SemanticIssue]) -> SemanticValidationReport:
        return SemanticValidationReport(
            conforms=not issues,
            ontology_version=self.model.version,
            ontology_fingerprint=self.model.fingerprint,
            issues=issues,
        )

    def _native_validation(self, graph: KnowledgeGraph, *, complete: bool) -> None:
        try:
            validate_graph(self.domain, graph, complete=complete)
        except ValueError as error:
            raise SemanticValidationError(
                self._report([SemanticIssue(message=str(error), constraint="native_assertion")])
            ) from error

    def bind_graph(self, graph: KnowledgeGraph) -> KnowledgeGraph:
        """Apply declared identity strategies and re-key assertions deterministically."""
        self._native_validation(graph, complete=False)
        by_id = {entity.id: entity for entity in graph.entities}
        resolved: dict[str, str] = {}
        visiting: set[str] = set()

        def identity(identifier: str) -> str:
            """Resolve owning entity identities recursively and detect cycles."""
            if identifier in resolved:
                return resolved[identifier]
            if identifier in visiting:
                raise ValueError("Cyclic owning identities cannot be bound")
            visiting.add(identifier)
            entity = by_id[identifier]
            keys = self.model.identity_keys(entity.type)
            values: dict[str, ScalarValue] = {"name": entity.name}
            if "source_id" in keys:
                source_ids = {reference.source_id for reference in entity.evidence}
                if len(source_ids) != 1:
                    raise ValueError(
                        f"Identity of {entity.type} requires one unambiguous source_id"
                    )
                values["source_id"] = next(iter(source_ids))
            if "parent_id" in keys:
                parents = {
                    edge.source_id
                    for edge in graph.relations
                    if edge.target_id == identifier
                    and self.model.native_relations[edge.type].owns_target
                }
                if len(parents) != 1:
                    raise ValueError(f"Identity of {entity.type} requires one owning parent_id")
                values["parent_id"] = identity(next(iter(parents)))
            if "order" in keys:
                if "order" not in entity.properties:
                    raise ValueError(f"Identity of {entity.type} requires order")
                values["order"] = entity.properties["order"]
            resolved[identifier] = self.model.identity_id(entity.type, values)
            visiting.remove(identifier)
            return resolved[identifier]

        entities: dict[str, KnowledgeEntity] = {}
        for entity in graph.entities:
            canonical_id = identity(entity.id)
            bound = entity.model_copy(update={"id": canonical_id}, deep=True)
            previous = entities.get(canonical_id)
            if previous is not None:
                for name, value in bound.properties.items():
                    if name in previous.properties and previous.properties[name] != value:
                        raise ValueError(f"Conflicting identity values on {canonical_id}.{name}")
                previous.properties.update(bound.properties)
                previous.aliases = sorted(
                    {*previous.aliases, *bound.aliases, bound.name} - {previous.name}
                )
                previous.evidence = _deduplicate_evidence([*previous.evidence, *bound.evidence])
            else:
                entities[canonical_id] = bound
        relations = []
        occurrences: dict[str, int] = defaultdict(int)
        for edge in sorted(graph.relations, key=lambda item: item.id):
            evidence = _deduplicate_evidence(edge.evidence)
            assertion = {
                "type": edge.type,
                "source_id": resolved[edge.source_id],
                "target_id": resolved[edge.target_id],
                "properties": edge.properties,
                "evidence": [item.model_dump() for item in evidence],
            }
            signature = _digest("relation", assertion)
            index = occurrences[signature]
            occurrences[signature] += 1
            relations.append(
                edge.model_copy(
                    update={
                        "id": _digest("relation", [assertion, index]),
                        "source_id": assertion["source_id"],
                        "target_id": assertion["target_id"],
                        "evidence": evidence,
                    },
                    deep=True,
                )
            )
        return KnowledgeGraph(
            entities=sorted(entities.values(), key=lambda item: item.id),
            relations=sorted(relations, key=lambda item: item.id),
            sources=[source.model_copy(deep=True) for source in graph.sources],
        )

    def _quantity(self, raw: str, separate_unit: str | None) -> _Quantity:
        """Parse exact scalar or ranged amounts while retaining source unit text."""
        match = _RANGE.fullmatch(raw)
        if match is not None:
            start, end, suffix = match.groups()
            value, maximum = Decimal(start), Decimal(end)
            kind = "range"
        else:
            match = _MEASURE.fullmatch(raw)
            if match is None:
                return _Quantity(kind="qualitative", original=raw, unit_text=separate_unit)
            start, suffix = match.groups()
            value, maximum, kind = Decimal(start), None, "numeric"
        suffix = suffix.strip()
        if suffix and separate_unit:
            left, right = (
                self.model.unit_spec(suffix),
                self.model.unit_spec(separate_unit),
            )
            if (
                (left is not None and right is not None and left != right)
                or (left is None or right is None)
                and suffix != separate_unit
            ):
                raise ValueError(f"Conflicting quantity units {suffix} and {separate_unit}")
        return _Quantity(
            kind=kind,
            original=raw,
            unit_text=suffix if suffix else separate_unit,
            value=value,
            maximum=maximum,
        )

    def _numeric_projection(
        self, minimum: Fraction, maximum: Fraction, dimension: str
    ) -> NumericValue:
        """Project an exact range to ticks or mark it outside the declared bounds."""
        spec = self.model.numeric_projections[dimension]
        tick = self.model.unit_spec(spec.tick_unit)
        assert tick is not None
        low, high = minimum / Fraction(tick.scale), maximum / Fraction(tick.scale)
        if (
            low.denominator != 1
            or high.denominator != 1
            or not spec.minimum <= low <= high <= spec.maximum
        ):
            return NumericValue(
                status="non_comparable",
                dimension=dimension,
                projection_version=spec.projection_version,
            )
        return NumericValue(
            status="comparable",
            minimum=low.numerator,
            maximum=high.numerator,
            dimension=dimension,
            projection_version=spec.projection_version,
        )

    def project_quantity(self, raw: str | None, separate_unit: str | None = None) -> NumericValue:
        """Convert a source amount to its declared exact fixed-point projection."""
        version = self.model.numeric_projection_version
        if raw is None:
            return NumericValue(status="unknown", projection_version=version)
        amount = self._quantity(raw, separate_unit)
        if amount.value is None:
            return NumericValue(status="unknown", projection_version=version)
        unit = None if amount.unit_text is None else self.model.unit_spec(amount.unit_text)
        if unit is None or unit.dimension not in self.model.numeric_projections:
            return NumericValue(status="non_comparable", projection_version=version)
        high = amount.value if amount.maximum is None else amount.maximum
        return self._numeric_projection(
            Fraction(amount.value) * Fraction(unit.scale),
            Fraction(high) * Fraction(unit.scale),
            unit.dimension,
        )

    def project_duration(self, raw: str | None) -> NumericValue:
        """Project a supported duration expression or mark it as unknown."""
        components = duration_components(raw)
        if components is None:
            return NumericValue(
                status="unknown",
                dimension="time",
                projection_version=self.model.numeric_projection_version,
            )
        total = Fraction(0)
        for value, name in components:
            unit = self.model.unit_spec(name)
            if unit is None or unit.dimension != "time":
                raise ValueError(f"The formal model lacks the duration unit {name}")
            total += Fraction(value) * Fraction(unit.scale)
        return self._numeric_projection(total, total, "time")

    def request_ticks(self, value: str | int, unit_name: str) -> tuple[int, str]:
        """Convert an exact query value to integer ticks and its dimension."""
        unit = self.model.unit_spec(unit_name)
        if unit is None or unit.dimension not in self.model.numeric_projections:
            raise ValueError(f"No declared numeric projection for unit {unit_name}")
        base = Fraction(exact_number(value)) * Fraction(unit.scale)
        projection = self._numeric_projection(base, base, unit.dimension)
        if projection.status != "comparable" or projection.minimum is None:
            raise ValueError("The numeric threshold cannot be represented by exact allowed ticks")
        return projection.minimum, unit.dimension

    def native_numeric_projection(
        self, owner: str, properties: dict[str, ScalarValue]
    ) -> dict[str, Any]:
        """Derive numeric storage fields for one entity or relation property map."""
        projections = {}
        if owner == self.model.property_binding("reportedDuration").anchor_type:
            projections = {
                f"n__duration_{grain}_": self.project_duration(
                    cast(str | None, properties.get(field))
                )
                for grain, field in DURATION_FIELDS.items()
            }
        elif owner in self.model.native_relations and self.model.native_relations[
            owner
        ].reification_class == self.model.uri("IngredientUse"):
            projections = {
                "n__amount_": self.project_quantity(
                    cast(str | None, properties.get("amount_text")),
                    cast(str | None, properties.get("unit")),
                )
            }
        return {
            prefix + ("version" if key == "projection_version" else key): value
            for prefix, projection in projections.items()
            for key, value in projection.model_dump().items()
        }

    def _add_evidence(self, rdf: Graph, owner: URIRef, references: list[EvidenceReference]) -> None:
        for reference in references:
            node = _resource("evidence", _digest("evidence", reference.model_dump()))
            rdf.add((owner, self.model.uri("evidence"), node))
            rdf.add((node, RDF.type, self.model.uri("Evidence")))
            rdf.add(
                (
                    node,
                    self.model.uri("sourceId"),
                    Literal(reference.source_id, datatype=XSD.string),
                )
            )
            rdf.add(
                (
                    node,
                    self.model.uri("quote"),
                    Literal(reference.quote, datatype=XSD.string),
                )
            )

    def project(self, graph: KnowledgeGraph) -> Graph:
        """Build a fresh assertion graph; this does not invoke inference."""
        rdf = Graph()
        for entity in graph.entities:
            node = _resource("entity", entity.id)
            rdf.add((node, RDF.type, self.model.native_classes[entity.type]))
            classified = self.model.classify_name(entity.name, entity.type)
            if classified is not None:
                rdf.add((node, RDF.type, classified))
            rdf.add((node, RDFS.label, Literal(entity.name)))
            for key, value in entity.properties.items():
                rdf.add((node, self.model.field_uri(entity.type, key), _literal(value)))
            self._add_evidence(rdf, node, entity.evidence)
        for edge in graph.relations:
            source, target = (
                _resource("entity", edge.source_id),
                _resource("entity", edge.target_id),
            )
            binding = self.model.native_relations[edge.type]
            rdf.add((source, binding.uri, target))
            node = _resource("assertion", edge.id)
            self._add_evidence(rdf, node, edge.evidence)
            for key, value in edge.properties.items():
                rdf.add((node, self.model.field_uri(edge.type, key), _literal(value)))
            if binding.reification_class is not None:
                rdf.add((node, RDF.type, binding.reification_class))
            if binding.reification_class == self.model.uri("IngredientUse"):
                rdf.add((source, self.model.uri("hasIngredientUse"), node))
                rdf.add((node, self.model.uri("inRecipe"), source))
                rdf.add((node, self.model.uri("ingredient"), target))
                if binding.role is not None:
                    rdf.add(
                        (
                            node,
                            self.model.uri("role"),
                            Literal(binding.role, datatype=XSD.string),
                        )
                    )
                raw = edge.properties.get("amount_text")
                if raw is not None:
                    amount = self._quantity(
                        cast(str, raw),
                        cast(str, edge.properties["unit"]) if "unit" in edge.properties else None,
                    )
                    quantity = _resource("quantity", edge.id)
                    rdf.add((node, self.model.uri("quantity"), quantity))
                    rdf.add((quantity, RDF.type, self.model.uri("Quantity")))
                    kinds = {
                        "numeric": "NumericQuantity",
                        "range": "RangeQuantity",
                        "qualitative": "QualitativeQuantity",
                    }
                    rdf.add((quantity, RDF.type, self.model.uri(kinds[amount.kind])))
                    rdf.add(
                        (
                            quantity,
                            self.model.uri("rawText"),
                            Literal(amount.original, datatype=XSD.string),
                        )
                    )
                    if self.model.numeric_projections:
                        comparison = self.project_quantity(
                            cast(str, raw),
                            (
                                cast(str, edge.properties["unit"])
                                if "unit" in edge.properties
                                else None
                            ),
                        )
                        rdf.add(
                            (
                                quantity,
                                self.model.uri("comparisonStatus"),
                                Literal(comparison.status, datatype=XSD.string),
                            )
                        )
                        rdf.add(
                            (
                                quantity,
                                self.model.uri("projectionVersion"),
                                Literal(comparison.projection_version, datatype=XSD.string),
                            )
                        )
                        if comparison.minimum is not None:
                            rdf.add(
                                (
                                    quantity,
                                    self.model.uri("comparisonMinTick"),
                                    Literal(comparison.minimum, datatype=XSD.long),
                                )
                            )
                            rdf.add(
                                (
                                    quantity,
                                    self.model.uri("comparisonMaxTick"),
                                    Literal(comparison.maximum, datatype=XSD.long),
                                )
                            )
                    if amount.value is not None:
                        rdf.add(
                            (
                                quantity,
                                self.model.uri("minValue" if amount.kind == "range" else "value"),
                                Literal(amount.value, datatype=XSD.decimal),
                            )
                        )
                    if amount.maximum is not None:
                        rdf.add(
                            (
                                quantity,
                                self.model.uri("maxValue"),
                                Literal(amount.maximum, datatype=XSD.decimal),
                            )
                        )
                    if amount.unit_text is not None:
                        rdf.add(
                            (
                                quantity,
                                self.model.uri("unitText"),
                                Literal(amount.unit_text, datatype=XSD.string),
                            )
                        )
                        unit = self.model.unit_spec(amount.unit_text)
                        if unit is not None:
                            unit_node = unit.uri
                            rdf.add((quantity, self.model.uri("unit"), unit_node))
                            rdf.add((unit_node, RDF.type, self.model.uri("Unit")))
                    self._add_evidence(rdf, quantity, edge.evidence)
        return rdf

    def _validate(
        self, data: Graph, *, shape: URIRef | None = None, focus: URIRef | None = None
    ) -> SemanticValidationReport:
        """Run SHACL validation and normalize violations into a stable report."""
        shapes = self.model.shapes_graph()
        if shape is not None:
            if (shape, RDF.type, SH.NodeShape) not in shapes:
                raise ValueError(f"Unknown answer shape {shape}")
            if focus is None:
                raise ValueError("Answer shape validation requires a focus node")
            for predicate in (
                SH.targetClass,
                SH.targetNode,
                SH.targetSubjectsOf,
                SH.targetObjectsOf,
            ):
                shapes.remove((None, predicate, None))
            shapes.add((shape, SH.targetNode, focus))
        conforms, report_graph, _ = validate_shapes(
            data,
            shacl_graph=shapes,
            inference="none",
            advanced=False,
            do_owl_imports=False,
        )
        if not isinstance(report_graph, Graph):
            raise RuntimeError(  # noqa: TRY004 - invalid SHACL processor response
                f"SHACL processor could not execute the shape: {report_graph}"
            )
        issues = []
        for result in report_graph.subjects(RDF.type, SH.ValidationResult):

            def value(predicate, result=result):
                """Read an optional SHACL result term as text for the report."""
                item = report_graph.value(result, predicate)
                return None if item is None else str(item)

            issues.append(
                SemanticIssue(
                    focus_node=value(SH.focusNode),
                    path=value(SH.resultPath),
                    source_shape=value(SH.sourceShape),
                    constraint=value(SH.sourceConstraintComponent),
                    message=value(SH.resultMessage) or "SHACL shape violation",
                    severity=value(SH.resultSeverity) or str(SH.Violation),
                )
            )
        if not conforms and not issues:
            raise RuntimeError("SHACL returned nonconformance without a violation report")
        return self._report(issues)

    def validate_input(self, graph: KnowledgeGraph) -> SemanticValidationReport:
        """Validate native facts and formal shapes without claiming completeness."""
        # 先校验原始断言，不能先靠 OWL 推理补齐类型，再掩盖来源本身缺失的信息。
        self._native_validation(graph, complete=False)
        try:
            raw = self.project(graph)
        except ValueError as error:
            raise SemanticValidationError(
                self._report([SemanticIssue(message=str(error), constraint="quantity_expression")])
            ) from error
        report = self._validate(raw)
        if not report.conforms:
            raise SemanticValidationError(report)
        self._native_validation(graph, complete=True)
        return report

    def validate_rdf(self, data: Graph) -> SemanticValidationReport:
        """Validate original semantic assertions without adding domain/range types."""
        return self._validate(data)

    def _inferred(self, raw: Graph) -> Graph:
        """Apply cached OWL-RL closure to an isolated graph of raw assertions."""
        # 推理只作用于独立副本，原始事实仍保留，回答时才能区分记载与推导。
        key = self.model.fingerprint, frozenset(raw)
        with self._inference_lock:
            triples = self._inference_cache.get(key)
            if triples is None:
                result = self.model.ontology_graph()
                for triple in raw:
                    result.add(triple)
                DeductiveClosure(
                    OWLRL_Semantics, axiomatic_triples=False, datatype_axioms=False
                ).expand(result)
                triples = tuple(result)
                self._inference_cache[key] = triples
                if len(self._inference_cache) > 64:
                    self._inference_cache.popitem(last=False)
            else:
                self._inference_cache.move_to_end(key)
        result = Graph()
        for triple in triples:
            result.add(triple)
        return result

    def _validate_selected_assertion(
        self, raw: Graph, edge: KnowledgeRelation
    ) -> SemanticValidationReport:
        reification = self.model.native_relations[edge.type].reification_class
        if reification is None:
            return self._report([])
        shape_graph = self.model.shapes_graph()
        issues = []
        for shape in shape_graph.subjects(SH.targetClass, reification):
            if not isinstance(shape, URIRef):
                raise ValueError(  # noqa: TRY004 - an invalid formal contract is a value error.
                    "Selected assertion shapes must have named identities"
                )
            issues.extend(
                self._validate(raw, shape=shape, focus=_resource("assertion", edge.id)).issues
            )
        return self._report(issues)

    def _hierarchy_trace(
        self, graph: Graph, node: URIRef, target: str, edge: KnowledgeRelation
    ) -> dict[str, Any] | None:
        """Explain an inferred target through the declared hierarchy relations."""
        target_type = self.model.classify_name(target, "Ingredient")
        if target_type is None:
            return None
        asserted = self.model.classify_name(
            next(str(label) for label in graph.objects(node, RDFS.label)), "Ingredient"
        )
        if asserted is None or asserted == target_type:
            return None
        frontier = [(asserted, [str(asserted)])]
        seen = set()
        assertions = self.model.asserted_ontology_graph()
        while frontier:
            kind, path = frontier.pop(0)
            if kind == target_type:
                return {
                    "kind": "inferred",
                    "rule": "owl-rl:cax-sco",
                    "premises": [edge.id, *path],
                    "type_path": path,
                    "ontology_version": self.model.version,
                    "ontology_fingerprint": self.model.fingerprint,
                }
            if kind in seen:
                continue
            seen.add(kind)
            for parent in assertions.objects(kind, RDFS.subClassOf):
                if isinstance(parent, URIRef) and parent != kind:
                    frontier.append((parent, [*path, str(parent)]))
        return None

    def _amount_text(
        self, edge: KnowledgeRelation, target_unit: str | None
    ) -> tuple[str, dict[str, Any] | None]:
        """Convert a source amount to the requested declared unit with evidence."""
        raw = cast(str, edge.properties["amount_text"])
        original_unit = cast(str, edge.properties["unit"]) if "unit" in edge.properties else None
        parsed = self._quantity(raw, original_unit)
        if target_unit is None:
            bare = _RANGE.fullmatch(raw) if parsed.kind == "range" else _MEASURE.fullmatch(raw)
            if (
                parsed.kind in {"numeric", "range"}
                and parsed.unit_text is not None
                and bare is not None
                and not bare.group(3 if parsed.kind == "range" else 2).strip()
            ):
                return raw + " " + parsed.unit_text, None
            return raw, None
        destination = self.model.unit_spec(target_unit)
        source = self.model.unit_spec(parsed.unit_text) if parsed.unit_text is not None else None
        if parsed.kind == "qualitative" or source is None or destination is None:
            raise ValueError("该用量或单位无法进行精确换算")
        if source.dimension != destination.dimension:
            raise ValueError("单位量纲不同，不能换算")
        assert parsed.value is not None
        ratio = Fraction(source.scale) / Fraction(destination.scale)
        converted = _exact_decimal(Fraction(parsed.value) * ratio)
        upper = None if parsed.maximum is None else _exact_decimal(Fraction(parsed.maximum) * ratio)
        value_text = _decimal_text(converted)
        text = value_text if upper is None else value_text + "–" + _decimal_text(upper)
        detail = {
            "kind": "converted",
            "rule": "quantity:same-dimension-scale",
            "premises": [edge.id, str(source.uri), str(destination.uri)],
            "original": raw,
            "value": value_text,
            "unit": destination.symbol,
            "ontology_version": self.model.version,
            "ontology_fingerprint": self.model.fingerprint,
        }
        if upper is not None:
            detail["max_value"] = _decimal_text(upper)
        return text + " " + destination.symbol, detail

    def _relation_trace(self, edge: KnowledgeRelation, logical: URIRef) -> dict[str, Any] | None:
        """Trace one logical relation to its authoritative stored assertion."""
        native = self.model.native_relations[edge.type].uri
        if native == logical:
            return None
        assertions = self.model.asserted_ontology_graph()
        queue = [(native, [str(native)])]
        seen = set()
        while queue:
            predicate, path = queue.pop(0)
            if predicate == logical:
                return {
                    "kind": "inferred",
                    "rule": "owl-rl:prp-spo1",
                    "premises": [edge.id, *path],
                    "property_path": path,
                    "ontology_version": self.model.version,
                    "ontology_fingerprint": self.model.fingerprint,
                }
            if predicate in seen:
                continue
            seen.add(predicate)
            for parent in assertions.objects(predicate, RDFS.subPropertyOf):
                if isinstance(parent, URIRef) and parent != predicate:
                    queue.append((parent, [*path, str(parent)]))
        return None

    def _numeric_measurement_text(self, value: NumericMeasurement, unit_name: str | None) -> str:
        """Format a projected amount with its requested display unit and precision."""
        if (
            value.dimension is None
            or value.projection_version != self.model.numeric_projection_version
            or value.dimension not in self.model.numeric_projections
        ):
            raise ValueError("数值投影版本或量纲不兼容")
        spec = self.model.numeric_projections[value.dimension]
        if (
            value.minimum is None
            or value.maximum is None
            or not spec.minimum <= value.minimum <= value.maximum <= spec.maximum
        ):
            raise ValueError("数值投影没有完整的精确范围")
        tick_unit = self.model.unit_spec(spec.tick_unit)
        output = self.model.unit_spec(spec.tick_unit if unit_name is None else unit_name)
        if tick_unit is None or output is None or output.dimension != value.dimension:
            raise ValueError("请求单位与数值量纲不兼容")
        ratio = Fraction(tick_unit.scale) / Fraction(output.scale)
        low = _decimal_text(_exact_decimal(Fraction(value.minimum) * ratio))
        high = _decimal_text(_exact_decimal(Fraction(value.maximum) * ratio))
        return (low if low == high else f"{low}–{high}") + output.symbol

    def evaluate(
        self,
        graph: KnowledgeGraph,
        selections: list[SemanticSelection],
        *,
        anchor_ids: list[str],
        truncated: bool = False,
        numeric_values: Sequence[NumericMeasurement] = (),
    ) -> SemanticEvaluation:
        """Answer property selections from a graph with traceable evidence."""
        # 先执行本体绑定和确定性求值，模型只负责后续表达，不负责裁定用量等事实。
        result = SemanticEvaluation(message="", status="success", model_version=self.model.version)
        try:
            self._native_validation(graph, complete=False)
            raw = self.project(graph)
        except (ValueError, SemanticValidationError) as error:
            issues = (
                error.report.issues
                if isinstance(error, SemanticValidationError)
                else [SemanticIssue(message=str(error))]
            )
            result.status = "insufficient_evidence"
            result.message = "事实证据未通过语义校验。"
            result.diagnostics = [issue.model_dump() for issue in issues]
            return result
        inferred = self._inferred(raw)
        entities = {entity.id: entity for entity in graph.entities}
        anchors = [entities[identifier] for identifier in anchor_ids if identifier in entities]
        lines: list[str] = []
        missing: list[str] = []
        invalid: list[dict[str, Any]] = []
        source_ids: set[str] = set()
        for selected in selections:
            binding = self.model.property_binding(selected.property)
            successful_anchors: set[str] = set()
            if selected.property in {
                "ingredientUsageAmount",
                "ingredientTotalAmount",
                "reportedDuration",
            }:
                grain = selected.grain
                if grain is None:
                    grain = DEFAULT_NUMERIC_GRAINS[selected.property]
                numeric_target = (
                    selected.target if selected.target is not None else binding.target_type
                )
                for anchor in anchors:
                    values = [
                        value
                        for value in numeric_values
                        if value.anchor_id == anchor.id
                        and value.property == selected.property
                        and value.grain == grain
                        and value.target_ref == numeric_target
                    ]
                    if not values:
                        invalid.append(
                            SemanticIssue(
                                message="缺少完整数据库范围的数值投影",
                                constraint="missing_numeric_projection",
                            ).model_dump()
                        )
                        continue
                    for value in values:
                        if value.status != "comparable":
                            missing.append(
                                f"{anchor.name} · {binding.label}（{grain}，{value.status}）"
                            )
                            continue
                        try:
                            detail = self._numeric_measurement_text(value, selected.unit)
                        except ValueError as error:
                            invalid.append(
                                SemanticIssue(
                                    message=str(error), constraint="numeric_projection"
                                ).model_dump()
                            )
                            continue
                        grain_label = {
                            "usage": "单次使用",
                            "recipe_total": "每份做法合计",
                            "reported_unspecified": "来源未分口径",
                            "prep": "准备",
                            "cook": "烹饪",
                            "total": "总时长",
                        }[grain]
                        lines.append(
                            f"{anchor.name} · {binding.label}（{grain_label}）"
                            + (f" · {selected.target}" if selected.target else "")
                            + f"：{detail}"
                        )
                        source_ids.update(value.source_ids)
                        result.assertions.append(
                            {
                                "kind": "derived",
                                "anchor_id": anchor.id,
                                "property": selected.property,
                                "grain": grain,
                                "numeric_value": value.model_dump(),
                                "basis": value.relation_ids,
                            }
                        )
                continue
            if selected.target is not None and (
                binding.target_type is None or not binding.relation_types
            ):
                invalid.append(
                    SemanticIssue(
                        message="该业务属性不支持指定目标对象",
                        constraint="unsupported_target_request",
                    ).model_dump()
                )
                continue
            if selected.unit is not None and not any(
                self.model.native_relations[edge].reification_class
                == self.model.uri("IngredientUse")
                for edge in binding.relation_types
            ):
                invalid.append(
                    SemanticIssue(
                        message="该业务属性不支持数量单位换算",
                        constraint="unsupported_unit_request",
                    ).model_dump()
                )
                continue
            for anchor in anchors:
                if anchor.type != binding.anchor_type:
                    continue
                if not binding.relation_types:
                    for field in binding.fields:
                        owner, key = field.split(".", 1)
                        if owner == anchor.type and key in anchor.properties:
                            report = self._validate(
                                raw,
                                shape=binding.answer_shape,
                                focus=_resource("entity", anchor.id),
                            )
                            if report.conforms:
                                lines.append(
                                    f"{anchor.name} · {binding.label}：{anchor.properties[key]}"
                                )
                                source_ids.update(ref.source_id for ref in anchor.evidence)
                                result.assertions.append(
                                    {
                                        "kind": "asserted",
                                        "fact_id": anchor.id,
                                        "anchor_id": anchor.id,
                                        "property": selected.property,
                                        "field": field,
                                        "value": anchor.properties[key],
                                        "source_ids": sorted(
                                            {ref.source_id for ref in anchor.evidence}
                                        ),
                                    }
                                )
                                successful_anchors.add(anchor.id)
                            else:
                                invalid.extend(issue.model_dump() for issue in report.issues)
                    continue
                ordering = [
                    (owner, key)
                    for field in binding.fields
                    for owner, _, key in [field.partition(".")]
                    if self.model.field_uri(owner, key) == self.model.uri("order")
                ]

                def edge_order(edge, ordering=ordering):
                    """Sort projected relation edges by their mapped order field."""
                    target = entities[edge.target_id]
                    values = [
                        target.properties[key] if owner == target.type else edge.properties[key]
                        for owner, key in ordering
                        if (owner == target.type and key in target.properties)
                        or (owner == edge.type and key in edge.properties)
                    ]
                    return values[0] if values else 0

                for edge in sorted(graph.relations, key=edge_order):
                    if edge.source_id != anchor.id or edge.type not in binding.relation_types:
                        continue
                    target = entities[edge.target_id]
                    logical_relations = [
                        predicate
                        for predicate in binding.semantic_relations
                        if (
                            _resource("entity", anchor.id),
                            predicate,
                            _resource("entity", target.id),
                        )
                        in inferred
                    ]
                    if binding.semantic_relations and not logical_relations:
                        continue
                    if selected.target is not None:
                        assert binding.target_type is not None
                        target_type = self.model.classify_name(selected.target, binding.target_type)
                        type_match = (
                            target_type is not None
                            and (_resource("entity", target.id), RDF.type, target_type) in inferred
                        )
                        names = [target.name, *target.aliases]
                        if self.model.identity_spec(target.type).strategy == "CanonicalName":
                            selected_identity = self.model.identity_id(
                                target.type, {"name": selected.target}
                            )
                            exact_match = any(
                                self.model.identity_id(target.type, {"name": name})
                                == selected_identity
                                for name in names
                            )
                        else:
                            exact_match = selected.target in names
                        if not type_match and not exact_match:
                            continue
                    relation_binding = self.model.native_relations[edge.type]
                    usage = relation_binding.reification_class == self.model.uri("IngredientUse")
                    if usage and "amount_text" not in edge.properties:
                        missing.append(f"{anchor.name} · {target.name} · {binding.label}")
                        continue
                    assertion_report = self._validate_selected_assertion(raw, edge)
                    if not assertion_report.conforms:
                        invalid.extend(issue.model_dump() for issue in assertion_report.issues)
                        continue
                    focus = (
                        _resource("assertion", edge.id) if usage else _resource("entity", target.id)
                    )
                    report = self._validate(raw, shape=binding.answer_shape, focus=focus)
                    if not report.conforms:
                        invalid.extend(issue.model_dump() for issue in report.issues)
                        continue
                    try:
                        if usage:
                            detail, conversion = self._amount_text(edge, selected.unit)
                            if conversion is not None:
                                result.derivations.append(conversion)
                            if selected.target is not None:
                                trace = self._hierarchy_trace(
                                    inferred,
                                    _resource("entity", target.id),
                                    selected.target,
                                    edge,
                                )
                                if trace is not None:
                                    result.derivations.append(trace)
                        else:
                            detail = "；".join(
                                str(target.properties[key])
                                for field in binding.fields
                                for owner, _, key in [field.partition(".")]
                                if owner == target.type and key in target.properties
                            )
                            if not detail:
                                detail = target.name
                        lines.append(f"{anchor.name} · {target.name}：{detail}")
                        for logical in logical_relations:
                            trace = self._relation_trace(edge, logical)
                            if trace is not None:
                                result.derivations.append(trace)
                        references = (
                            [*anchor.evidence, *edge.evidence]
                            if usage
                            else [*anchor.evidence, *edge.evidence, *target.evidence]
                        )
                        source_ids.update(ref.source_id for ref in references)
                        result.assertions.append(
                            {
                                "kind": "asserted",
                                "fact_id": edge.id,
                                "anchor_id": anchor.id,
                                "target_id": target.id,
                                "property": selected.property,
                                "properties": (
                                    dict(edge.properties) if usage else dict(target.properties)
                                ),
                                "source_ids": sorted({ref.source_id for ref in references}),
                            }
                        )
                        successful_anchors.add(anchor.id)
                    except ValueError as error:
                        invalid.append(
                            SemanticIssue(
                                focus_node=str(focus),
                                path=str(self.model.uri("quantity")),
                                message=str(error),
                                constraint="quantity_conversion",
                            ).model_dump()
                        )
            absent = [
                anchor
                for anchor in anchors
                if anchor.type == binding.anchor_type and anchor.id not in successful_anchors
            ]
            for anchor in absent:
                missing.append(
                    anchor.name
                    + " · "
                    + binding.label
                    + (f"（{selected.target}）" if selected.target else "")
                )
            if not anchors:
                missing.append(
                    binding.label + (f"（{selected.target}）" if selected.target else "")
                )
        if invalid:
            result.diagnostics.extend(invalid)
            lines.append("部分事实证据未通过语义校验。")
        if missing:
            lines.append("未记录或无法确认：" + "、".join(missing))
        if truncated:
            lines.append("展示的证据已截断，不能视为完整结果。")
        has_facts = bool(source_ids)
        result.status = (
            "partial"
            if has_facts and (invalid or missing or truncated)
            else "success" if has_facts else "insufficient_evidence" if invalid else "no_results"
        )
        result.message = "\n".join(lines) if lines else "未记录所请求的事实。"
        result.sources = [
            {
                "backend": "neo4j",
                "document_id": source.id,
                "source": source.uri or source.id,
            }
            for source in graph.sources
            if source.id in source_ids
        ]
        return result


def get_semantic_runtime(domain: DomainDefinition) -> SemanticRuntime | None:
    """Create a runtime only when the domain includes a compiled formal ontology."""
    model = domain.semantic_model
    return None if model is None else SemanticRuntime(model)

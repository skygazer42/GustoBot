"""Frozen, deterministic knowledge evaluation; provider quality is never inferred from fixtures."""

import argparse
import asyncio
import hashlib
import importlib
import inspect
import json
import math
import re
import sys
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class ExpectedOutcome(BaseModel):
    """Expected answer properties and evidence rules used to grade a case."""

    model_config = ConfigDict(extra="forbid", strict=True)
    concept_ids: list[str] = Field(default_factory=list)
    object_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(min_length=1)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    numbers: list[dict[str, str]] = Field(default_factory=list)
    numeric_unknown: bool = False
    choice_ids: list[str] = Field(default_factory=list)
    forbidden_ids: list[str] = Field(default_factory=list)
    answer_contains: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    expected_predicate: (
        Literal["matched", "not_matched", "unknown", "uncertain", "non_comparable"] | None
    ) = None


class EvaluationCase(BaseModel):
    """One question, fixture, and expected outcome in the evaluation set."""

    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1)
    split: Literal["holdout", "calibration"]
    truth: Literal["controlled", "human_verified", "manual_unverified"]
    category: str = Field(min_length=1)
    question: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    history: list[dict[str, str]] = Field(default_factory=list)
    fault: str | None = None
    expected: ExpectedOutcome


@dataclass
class EvaluationDataset:
    """Validated cases and source identity used to reproduce an evaluation run."""

    cases: list[EvaluationCase]
    fixtures: dict[str, Any]
    manifest: dict[str, Any]
    checksum: str


@dataclass
class EvaluationRuntime:
    """Evaluation-only services and deployment metadata with owned resources."""

    query_service: Any
    scope: dict[str, Any]
    deployment: dict[str, Any]
    provider_kind: Literal["protocol", "real"]
    linker: Any = None
    telemetry_snapshot: Callable | None = None
    cleanup: Callable | None = None
    case_context: Callable | None = None


def _reject_constant(value):
    raise ValueError(f"Non-finite JSON value: {value}")


def _json(value: str):
    return json.loads(value, parse_constant=_reject_constant)


def _checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def load_dataset(path: str | Path) -> EvaluationDataset:
    """Load and verify an evaluation dataset and its content identity."""
    path = Path(path)
    raw = path.read_bytes()
    manifest_path = path.with_name("manifest.json")
    manifest = _json(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if manifest and manifest["files"][path.name] != _checksum(raw):
        raise ValueError(f"Frozen dataset checksum mismatch: {path.name}")
    cases = [
        EvaluationCase.model_validate(_json(line))
        for line in raw.decode("utf-8").splitlines()
        if line.strip()
    ]
    if not cases:
        raise ValueError("Evaluation dataset cannot be empty")
    questions = [
        " ".join(unicodedata.normalize("NFKC", case.question).casefold().split()) for case in cases
    ]
    if len({case.id for case in cases}) != len(cases) or len(set(questions)) != len(cases):
        raise ValueError("Duplicate evaluation identity or normalized question")
    fixtures: dict[str, list[dict[str, Any]]] = {
        "sources": [],
        "entities": [],
        "relations": [],
    }
    fixture_names = manifest.get("fixture_files", ["controlled_sources.json"])
    for name in fixture_names:
        if Path(name).name != name or not name.endswith(".json"):
            raise ValueError("Fixture filenames must stay inside the dataset directory")
        fixture_path = path.with_name(name)
        if not fixture_path.exists() and not manifest:
            continue
        fixture_raw = fixture_path.read_bytes()
        if manifest and manifest["files"][name] != _checksum(fixture_raw):
            raise ValueError("Frozen source fixture checksum mismatch")
        part = _json(fixture_raw.decode("utf-8"))
        for key, values in fixtures.items():
            values.extend(part[key])
    sources = {item["id"]: item for item in fixtures["sources"]}
    objects = {item["id"] for item in fixtures["entities"]}
    for item in [*fixtures["entities"], *fixtures["relations"]]:
        for reference in item["evidence"]:
            if (
                reference["source_id"] not in sources
                or reference["quote"] not in sources[reference["source_id"]]["text"]
            ):
                raise ValueError("Controlled fixture has ungrounded evidence")
    for case in cases:
        if (
            case.truth == "controlled"
            and fixtures["sources"]
            and (
                set(case.expected.source_ids) - sources.keys()
                or set(case.expected.object_ids + case.expected.choice_ids) - objects
            )
        ):
            raise ValueError(f"Controlled gold references unknown source/object: {case.id}")
    return EvaluationDataset(cases, fixtures, manifest, _checksum(raw))


def materialize_dataset(path: Path, output: Path, *, model=None):
    """Bind authored logical IDs using the production identity compiler, without database writes."""
    from gustobot.domain.formal_ontology import load_formal_ontology
    from gustobot.domain.knowledge import KnowledgeGraph
    from gustobot.infrastructure.knowledge.semantic_runtime import SemanticRuntime

    dataset = load_dataset(path)
    if model is None:
        ontology = PROJECT_ROOT / "gustobot/config/ontologies"
        model = load_formal_ontology(ontology / "recipes.ttl", ontology / "recipes.shacl.ttl")
    required = dataset.manifest.get("required_ontology_version")
    if required is not None and required != model.version:
        raise ValueError(f"Fixture requires ontology {required}; actual model is {model.version}")
    graph = KnowledgeGraph.model_validate(dataset.fixtures)
    engine = SemanticRuntime(model)
    bound = engine.bind_graph(graph)
    report = engine.validate_input(bound)
    if not report.conforms:
        raise ValueError("Controlled complete source fixture failed formal validation")
    identity_map = {}
    for original in graph.entities:
        sources = {reference.source_id for reference in original.evidence}
        matches = [
            entity.id
            for entity in bound.entities
            if entity.type == original.type
            and original.name in [entity.name, *entity.aliases]
            and sources <= {reference.source_id for reference in entity.evidence}
        ]
        if len(matches) != 1:
            raise ValueError(f"Fixture identity cannot be bound unambiguously: {original.id}")
        identity_map[original.id] = matches[0]
    for original_edge in graph.relations:
        matches = [
            edge.id
            for edge in bound.relations
            if edge.source_id == identity_map[original_edge.source_id]
            and edge.target_id == identity_map[original_edge.target_id]
            and edge.type == original_edge.type
            and edge.properties == original_edge.properties
            and edge.evidence == original_edge.evidence
        ]
        if len(matches) != 1:
            raise ValueError(f"Fixture assertion cannot be bound unambiguously: {original_edge.id}")
        identity_map[original_edge.id] = matches[0]

    def bind(value):
        """Recursively replace fixture identities with their bound graph IDs."""
        if isinstance(value, str):
            return identity_map.get(value, value)
        if isinstance(value, list):
            return [bind(item) for item in value]
        if isinstance(value, dict):
            return {key: bind(item) for key, item in value.items()}
        return value

    if output.resolve() == path.parent.resolve():
        raise ValueError("Materialization output must preserve the original frozen input directory")
    output.mkdir(parents=True, exist_ok=True)
    names = [path.name]
    for sibling in ("questions.jsonl", "calibration.jsonl"):
        if sibling != path.name and path.with_name(sibling).exists():
            names.append(sibling)
    concepts = {record.ref_id for record in model.linking_records()}
    parent_hashes = {}
    for name in names:
        split = load_dataset(path.with_name(name))
        payloads = []
        for case in split.cases:
            payload = bind(case.model_dump())
            resolved_concepts = [
                identifier if identifier in concepts else "property:" + identifier
                for identifier in case.expected.concept_ids
            ]
            if set(resolved_concepts) - concepts:
                raise ValueError(f"Gold concepts are absent from materialized model: {case.id}")
            payload["expected"]["concept_ids"] = resolved_concepts
            payloads.append(payload)
        parent_hashes[name] = split.checksum
        (output / name).write_text(
            "".join(_canonical(payload) + "\n" for payload in payloads),
            encoding="utf-8",
        )
    fixture_name = "controlled_sources.json"
    (output / fixture_name).write_text(_canonical(bound.model_dump()) + "\n", encoding="utf-8")
    manifest = dataset.manifest | {
        "schema_version": "knowledge-eval-fixtures-v1",
        "required_ontology_version": model.version,
        "materialized_scope": {
            "domain_id": model.id,
            "ontology_version": model.version,
            "ontology_fingerprint": model.fingerprint,
        },
        "identity_status": "bound_by_actual_formal_model",
        "parent_dataset_hashes": parent_hashes,
        "files": {name: _checksum((output / name).read_bytes()) for name in [*names, fixture_name]},
        "fixture_files": [fixture_name],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "identity_map.json").write_text(
        json.dumps(identity_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


_UNITS = {
    "克": "g",
    "毫克": "mg",
    "千克": "kg",
    "毫升": "ml",
    "mL": "ml",
    "升": "L",
    "分钟": "分钟",
    "分": "分钟",
    "小时": "小时",
    "秒": "秒",
    "minute": "分钟",
    "min": "分钟",
    "second": "秒",
    "s": "秒",
    "millisecond": "ms",
    "微克": "ug",
    "μg": "ug",
    "微升": "ul",
    "μl": "ul",
    "piece": "个",
    "只": "个",
    "hour": "小时",
    "h": "小时",
    "l": "L",
}
_QUANTITY_UNIT = r"(?:millisecond|minute|second|piece|hour|mg|kg|ug|μg|ml|mL|ul|μl|ms|min|g|L|l|h|s|毫克|千克|微克|毫升|微升|毫秒|分钟|小时|克|升|秒|勺|份|个|只)(?![A-Za-z])"
_EXACT_NUMBER = r"[+-]?\d+(?:\.\d+)?(?:/\d+)?"
_NUMBER = re.compile(rf"({_EXACT_NUMBER})\s*({_QUANTITY_UNIT})")
_RANGE_NUMBER = re.compile(
    rf"({_EXACT_NUMBER})\s*(?:–|-|~|至|到)\s*({_EXACT_NUMBER})\s*({_QUANTITY_UNIT})"
)


def _number(value, unit, semantic_engine=None):
    """Parse a numeric expectation and normalize its value into the target unit."""
    canonical = _UNITS.get(unit, unit)
    amount = Fraction(str(value))
    if semantic_engine is not None:
        spec = semantic_engine.model.unit_spec(unit)
        if spec is not None:
            base = {"mass": "g", "volume": "ml", "time": "minute", "count": "piece"}[spec.dimension]
            base_spec = semantic_engine.model.unit_spec(base)
            return str(amount * Fraction(spec.scale) / Fraction(base_spec.scale)), _UNITS.get(
                base, base
            )
    conversions = {
        "mg": ("g", Fraction(1, 1000)),
        "ug": ("g", Fraction(1, 1_000_000)),
        "kg": ("g", Fraction(1000)),
        "ul": ("ml", Fraction(1, 1000)),
        "L": ("ml", Fraction(1000)),
        "秒": ("分钟", Fraction(1, 60)),
        "ms": ("分钟", Fraction(1, 60_000)),
        "小时": ("分钟", Fraction(60)),
    }
    base, scale = conversions.get(canonical, (canonical, Fraction(1)))
    return str(amount * scale), base


def _numbers(text, semantic_engine=None):
    result = set()
    for match in _RANGE_NUMBER.finditer(text):
        low, high, unit = match.groups()
        result.update([_number(low, unit, semantic_engine), _number(high, unit, semantic_engine)])
    text = _RANGE_NUMBER.sub(" ", text)
    return result | {_number(value, unit, semantic_engine) for value, unit in _NUMBER.findall(text)}


def _condition(condition, target_names=None):
    values = {key: value for key, value in condition.items() if value is not None}
    if "target_ref" in values and target_names is not None:
        values["target_ref"] = target_names.get(values["target_ref"], values["target_ref"])
    for key in ("value", "minimum", "maximum"):
        if key in values and values[key] is not None:
            values[key] = str(Fraction(str(values[key])))
    return _canonical(values)


def _source_id(source):
    return source["source_id"] if "source_id" in source else source["document_id"]


def _derived_evidence(assertion, facts, expected, engine):
    """Resolve expected evidence through source facts and semantic derivation traces."""
    from rdflib import RDFS

    from gustobot.domain.numeric import DURATION_FIELDS, NumericMeasurement

    if engine is None:
        return False
    value = NumericMeasurement.model_validate(assertion["numeric_value"])
    if (
        value.status != "comparable"
        or value.projection_version != engine.model.numeric_projection_version
    ):
        return False
    if any(assertion[key] != getattr(value, key) for key in ("anchor_id", "property", "grain")):
        return False
    anchor = facts.get(value.anchor_id)
    if (
        anchor is None
        or set(assertion["basis"]) != set(value.relation_ids)
        or len(value.relation_ids) != len(set(value.relation_ids))
    ):
        return False
    if value.property == "reportedDuration":
        if value.relation_ids:
            return False
        projected = [
            engine.project_duration(anchor["properties"].get(DURATION_FIELDS[value.grain]))
        ]
        references = anchor["evidence"]
    else:
        targets = []
        requested_class = engine.model.classify_name(value.target_ref)
        hierarchy = engine.model.ontology_graph()
        for fact in facts.values():
            if (
                fact.get("type") not in {"HAS_MAIN_INGREDIENT", "HAS_AUX_INGREDIENT"}
                or fact["source_id"] != value.anchor_id
            ):
                continue
            target = facts[fact["target_id"]]
            target_class = engine.model.classify_name(target["name"])
            if (
                value.target_ref in {target["id"], target["name"]}
                or requested_class is not None
                and target_class is not None
                and (
                    requested_class == target_class
                    or (target_class, RDFS.subClassOf, requested_class) in hierarchy
                )
            ):
                targets.append(fact)
        if value.grain == "recipe_total":
            if set(value.relation_ids) != {item["id"] for item in targets}:
                return False
        elif len(value.relation_ids) != 1 or not set(value.relation_ids) <= {
            item["id"] for item in targets
        }:
            return False
        selected = [facts[identifier] for identifier in value.relation_ids]
        if not selected:
            return False
        projected = [
            engine.project_quantity(
                item["properties"].get("amount_text"), item["properties"].get("unit")
            )
            for item in selected
        ]
        references = [reference for item in selected for reference in item["evidence"]]
    if not all(
        item.status == "comparable" and item.dimension == value.dimension for item in projected
    ):
        return False
    if value.minimum != sum(item.minimum for item in projected) or value.maximum != sum(
        item.maximum for item in projected
    ):
        return False
    source_ids = {item["source_id"] for item in references}
    return bool(source_ids) and source_ids <= set(value.source_ids) <= set(expected.source_ids)


def grade_case(
    case: EvaluationCase,
    observation: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    *,
    target_names=None,
    semantic_engine=None,
) -> dict[str, Any]:
    """Compare one observed answer with expected facts, scope, and source evidence."""
    expected = case.expected
    status_ok = observation["status"] in expected.statuses
    selected = set(observation["selected_ids"])
    ambiguous = "clarification" in expected.statuses and bool(expected.choice_ids)
    choices = {item["id"] for item in observation["choices"]}
    binding = (
        selected == set(expected.object_ids) if expected.object_ids and not ambiguous else None
    )
    target_names = {item["id"]: item["name"] for item in fixtures["entities"]} | (
        {} if target_names is None else target_names
    )
    conditions = {
        _condition(item, target_names)
        for item in [
            *observation["plan"].get("conditions", []),
            *observation["plan"].get("numeric_conditions", []),
        ]
    }
    expected_conditions = {_condition(item, target_names) for item in expected.conditions}
    sources = {item["id"]: item for item in fixtures["sources"]}
    facts = {item["id"]: item for item in [*fixtures["entities"], *fixtures["relations"]]}
    citations = {_source_id(item) for item in observation["sources"]}
    evidence_ok = citations <= set(expected.source_ids)
    assertions = observation["assertions"]
    for assertion in assertions:
        if assertion.get("kind") == "derived":
            evidence_ok &= _derived_evidence(assertion, facts, expected, semantic_engine)
            continue
        fact = facts.get(assertion["fact_id"])
        if fact is None:
            evidence_ok = False
            continue
        fact_sources = {item["source_id"] for item in fact["evidence"]}
        evidence_ok &= bool(assertion["source_ids"]) and set(
            assertion["source_ids"]
        ) <= fact_sources & set(expected.source_ids)
        evidence_ok &= all(
            fact["properties"].get(key) == value
            for key, value in assertion.get("properties", {}).items()
        )
        if "value" in assertion:
            evidence_ok &= (
                fact["properties"].get(assertion["field"].split(".")[-1]) == assertion["value"]
            )
    if expected.source_ids and status_ok and not ambiguous:
        evidence_ok &= bool(citations) and bool(
            assertions or case.category in {"documents", "combined"}
        )
    expected_numbers = {
        _number(item["value"], item["unit"], semantic_engine) for item in expected.numbers
    }
    actual_numbers = _numbers(observation["message"], semantic_engine)
    allowed_numbers = set(expected_numbers)
    anchors = observation["plan"].get("anchor_ids", []) or expected.object_ids
    totals = {
        "total",
        "matched",
        "not_matched",
        "unknown",
        "uncertain",
        "non_comparable",
    }
    for coverage in observation.get("numeric_coverage", []):
        expected_total = len(set(anchors))
        wanted = expected.expected_predicate or (
            "unknown" if expected.numeric_unknown else "matched"
        )
        counts = {name: coverage.get(name, 0) for name in totals}
        if coverage.get("grain") == "usage":
            expected_total = sum(
                fact.get("type") in {"HAS_MAIN_INGREDIENT", "HAS_AUX_INGREDIENT"}
                and fact.get("source_id") in anchors
                and target_names.get(
                    fact.get("target_id"),
                    facts.get(fact.get("target_id"), {}).get("name"),
                )
                == target_names.get(coverage.get("target_ref"), coverage.get("target_ref"))
                for fact in fixtures["relations"]
            )
        if (
            counts["total"] == expected_total
            and counts[wanted] == expected_total
            and all(counts[name] == 0 for name in totals - {"total", wanted})
        ):
            allowed_numbers.update(
                _number(count, "份", semantic_engine) for count in counts.values()
            )
    for identifier in expected.source_ids:
        if identifier in sources:
            allowed_numbers.update(_numbers(sources[identifier]["text"], semantic_engine))
    unsupported = sorted(f"{value} {unit}" for value, unit in actual_numbers - allowed_numbers)
    numeric = expected_numbers <= actual_numbers and not unsupported if expected.numbers else None
    if expected.numeric_unknown:
        numeric = status_ok and not actual_numbers
    if expected.expected_predicate is not None:
        coverage = observation.get("numeric_coverage", [])

        def matches_coverage(item, condition):
            """Match one measured coverage row to a requested numeric condition."""
            if not all(item.get(key) == condition.get(key) for key in ("property", "grain")):
                return False
            target = target_names.get(item.get("target_ref"), item.get("target_ref"))
            expected_target = target_names.get(
                condition.get("target_ref"), condition.get("target_ref")
            )
            return target == expected_target and item.get(expected.expected_predicate, 0) > 0

        numeric = (
            bool(expected.conditions)
            and all(
                any(matches_coverage(item, condition) for item in coverage)
                for condition in expected.conditions
            )
            and not unsupported
        )
    shape_case = "shape" in case.tags
    return {
        "status": status_ok,
        "binding": binding,
        "ambiguity": (
            (status_ok and not selected and set(expected.choice_ids) <= choices)
            if ambiguous
            else None
        ),
        "scope": bool(observation["scope_valid"])
        and not selected.intersection(expected.forbidden_ids)
        and (not fixtures["entities"] or selected <= {item["id"] for item in fixtures["entities"]}),
        "conditions": conditions == expected_conditions if expected.conditions else None,
        "evidence": bool(evidence_ok) if expected.source_ids else not assertions and not citations,
        "numeric": numeric,
        "unsupported_numeric_claims": unsupported,
        "shape_blocked": status_ok and not assertions if shape_case else None,
        "answer_contains": all(
            value in observation["message"] for value in expected.answer_contains
        ),
        "exact_preserved": (
            (status_ok and binding is not False)
            if {"exact", "approved_alias"}.intersection(case.tags)
            else None
        ),
        "exact_embedding_free": (
            (observation["calls"]["candidate"]["http_attempts"] == 0)
            if {"exact", "approved_alias"}.intersection(case.tags)
            and observation["calls"].get("candidate", {}).get("http_attempts") is not None
            else None
        ),
    }


def _metric(values: Sequence[bool]) -> dict[str, Any]:
    """Summarize passed checks with a stable numerator, denominator, and rate."""
    total = len(values)
    if not total:
        return {"value": None, "passed": 0, "total": 0, "wilson_95": None}
    passed = sum(values)
    proportion = passed / total
    z = 1.959963984540054
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    half = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return {
        "value": proportion,
        "passed": passed,
        "total": total,
        "wilson_95": [max(0, center - half), min(1, center + half)],
    }


def _percentiles(values):
    if not values:
        return {"samples": 0, "p50_ms": None, "p95_ms": None, "p99_ms": None}
    ordered = sorted(values)
    return {
        "samples": len(values),
        **{
            f"p{percentile}_ms": ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]
            for percentile in (50, 95, 99)
        },
    }


def _case_checks(rows, name):
    grouped: dict[str, list[bool]] = {}
    for row in rows:
        value = row["checks"].get(name)
        if value is not None:
            grouped.setdefault(row["id"], []).append(value)
    return [all(values) for values in grouped.values()]


def _delta(before, after):
    output: dict[str, dict[str, int | float]] = {}
    for purpose, counters in after.items():
        output[purpose] = {}
        for key, value in counters.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                previous = before.get(purpose, {}).get(key, 0)
                difference = value - previous
                if not math.isfinite(difference) or difference < 0:
                    raise ValueError("Telemetry counters must be finite and monotonic")
                output[purpose][key] = difference
    return output


def _candidate(item, scope=None):
    """Normalize one recalled candidate for scoring and calibration reports."""
    if scope is not None:
        return {
            "id": item["ref_id"],
            "kind": scope["kind"],
            "object_type": item["object_type"],
            "domain_id": scope["domain_id"],
            "ontology_version": scope["ontology_version"],
            "ontology_fingerprint": item["ontology_fingerprint"],
            "match_sources": item["match_sources"],
            "vector_score": item["vector_score"],
            "rank_score": item["rank_score"],
            "generation_id": item["generation_id"],
        }
    record = item["record"]
    return {
        "id": record["ref_id"],
        "kind": record["kind"],
        "object_type": record["object_type"],
        "domain_id": record["domain_id"],
        "ontology_version": record["ontology_version"],
        "ontology_fingerprint": record["ontology_fingerprint"],
        "match_sources": item["match_sources"],
        "vector_score": item["vector_score"],
        "rank_score": item["rank_score"],
        "generation_id": item["generation_id"],
    }


def _scope_valid(runtime, metadata, candidates):
    for key in ("domain_id", "ontology_version"):
        if metadata.get(key) != runtime.scope[key]:
            return False
    return all(
        all(
            item[key] == runtime.scope[key]
            for key in ("domain_id", "ontology_version", "ontology_fingerprint")
        )
        for item in candidates
    )


@asynccontextmanager
async def _no_fault():
    yield


async def _observe(case, runtime, mode, serial):
    """Run one evaluation case and capture answer, candidates, timing, and provider use."""
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

    history: list[BaseMessage] = [
        (HumanMessage if item["role"] == "human" else AIMessage)(content=item["content"])
        for item in case.history
    ]
    if case.fault and runtime.case_context is None:
        raise ValueError("Fault injection was requested but no runtime case_context was provided")
    context = runtime.case_context(case.fault) if runtime.case_context is not None else _no_fault()
    before = (
        runtime.telemetry_snapshot() if serial and runtime.telemetry_snapshot is not None else {}
    )
    started = time.perf_counter()
    concepts: list[dict[str, Any]] | None
    entities: list[dict[str, Any]] | None
    async with context:
        if mode == "retrieval":
            if runtime.linker is None:
                raise ValueError("Retrieval evaluation requires an actual linker")
            linked = await runtime.linker.prepare(case.question, history=history)
            concepts = [_candidate(item.model_dump()) for item in linked.concepts]
            entities = [_candidate(item.model_dump()) for item in linked.entities]
            metadata = {
                "domain_id": runtime.scope["domain_id"],
                "ontology_version": runtime.scope["ontology_version"],
            }
            result = {
                "status": linked.status,
                "selected_ids": [],
                "plan": {},
                "sources": [],
                "assertions": [],
                "derivations": [],
                "message": "",
                "choices": [],
                "diagnostics": linked.diagnostics,
                "concept_candidates": concepts,
                "entity_candidates": entities,
                "timings": linked.timings,
                "generation": linked.generations,
                "graph_revision": (
                    linked.graph_revision.model_dump()
                    if linked.graph_revision is not None
                    else None
                ),
                "analysis_calls": 0,
                "generation_calls": 0,
            }
        else:
            from gustobot.application.services.knowledge_query import (
                KnowledgeQueryService,
            )

            if not isinstance(runtime.query_service, KnowledgeQueryService):
                raise TypeError("QA/protocol/latency must call KnowledgeQueryService.answer")
            answer = await runtime.query_service.answer(case.question, history=history)
            metadata = answer.metadata
            linking = metadata.get("linking") or {}
            semantic = metadata.get("semantic_evaluation") or {}
            concepts = (
                [_candidate(item, linking["scopes"]["concept"]) for item in linking["concepts"]]
                if "concepts" in linking
                else None
            )
            entities = (
                [_candidate(item, linking["scopes"]["entity"]) for item in linking["entities"]]
                if "entities" in linking
                else None
            )
            result = {
                "status": metadata["status"],
                "selected_ids": metadata["plan"].get("anchor_ids", []),
                "plan": metadata["plan"],
                "sources": answer.sources,
                "assertions": semantic.get("assertions", []),
                "derivations": semantic.get("derivations", []),
                "message": answer.message,
                "choices": metadata["choices"],
                "diagnostics": semantic.get("diagnostics", []) + linking.get("diagnostics", []),
                "concept_candidates": concepts,
                "entity_candidates": entities,
                "timings": linking.get("timings", {}),
                "generation": linking.get("generation", {}),
                "graph_revision": linking.get("graph_revision"),
                "analysis_calls": metadata["analysis_calls"],
                "generation_calls": metadata["generation_calls"],
            }
    result["raw_status"] = result["status"]
    if result["status"] == "needs_clarification":
        result["status"] = "clarification"
    result["numeric_coverage"] = metadata.get("numeric_coverage", [])
    after = (
        runtime.telemetry_snapshot() if serial and runtime.telemetry_snapshot is not None else {}
    )
    result["calls"] = _delta(before, after)
    for purpose, counters in metadata.get("provider_calls", {}).items():
        measured = result["calls"].setdefault(purpose, {})
        for name, value in counters.items():
            if name not in measured:
                measured[name] = value
    result["calls"].setdefault("analysis", {"logical_calls": result["analysis_calls"]})
    result["calls"].setdefault("generation", {"logical_calls": result["generation_calls"]})
    result["scope_valid"] = _scope_valid(runtime, metadata, [*(concepts or []), *(entities or [])])
    result["elapsed_ms"] = (time.perf_counter() - started) * 1000
    return result


def _release_gate(metrics, provider_kind, cases, mode):
    """Apply evaluation thresholds and provider-evidence requirements for release."""
    limits = {
        "concept_recall_at_5": 0.98,
        "entity_recall_at_10": 0.95,
        "correct_binding": 1.0,
        "ambiguity_clarification": 1.0,
        "scope_preservation": 1.0,
        "conditions_preservation_controlled": 1.0,
        "conditions_preservation_real": 0.98,
        "evidence_alignment": 0.95,
        "evidence_alignment_real": 0.95,
        "numeric_correctness": 1.0,
        "shape_violation_blocking": 1.0,
        "exact_preservation": 1.0,
        "exact_embedding_free": 1.0,
        "expected_status": 1.0,
    }
    pending = []
    failed = []
    if provider_kind != "real":
        pending.append("real_provider")
    if not any(case.truth == "human_verified" for case in cases):
        pending.append("approved_real_truth")
    if any(case.truth == "manual_unverified" for case in cases):
        pending.append("manual_source_verification")
    for name, minimum in limits.items():
        metric = metrics.get(name)
        if metric is None or metric["value"] is None:
            pending.append(name)
        elif metric["value"] < minimum:
            failed.append(name)
        if metric is not None and metric.get("unobserved_cases"):
            pending.append(name + "_incomplete")
    if metrics.get("unsupported_numeric_claim_count", 0):
        failed.append("unsupported_numeric_claims")
    pending.extend(["baseline_shadow_on_comparison", "human_prose_review"])
    if mode == "retrieval":
        pending.append("qa")
    return {
        "accepted": not pending and not failed,
        "pending": sorted(set(pending)),
        "failed": sorted(set(failed)),
        "scope": "code/protocol observations; business acceptance additionally requires real providers and human truth",
    }


async def run_evaluation(
    cases,
    *,
    runtime: EvaluationRuntime,
    mode: str,
    linking_mode: str,
    fixtures,
    dataset_hash: str,
    concurrency: int = 1,
    repeats: int = 1,
):
    """Evaluate cases with bounded concurrency and collect outcomes and telemetry."""
    from gustobot.domain.linking import INDEX_SCHEMA_VERSION

    runtime.scope.setdefault("index_schema_version", INDEX_SCHEMA_VERSION)
    if concurrency not in {1, 5, 20} or repeats < 1:
        raise ValueError("Concurrency must be 1/5/20 and repeats must be positive")
    if runtime.provider_kind not in {"protocol", "real"}:
        raise ValueError("Runtime must explicitly distinguish protocol and real providers")
    if mode not in {"protocol", "retrieval", "qa", "latency"}:
        raise ValueError("Unknown evaluation mode")
    if runtime.query_service is not None:
        domain = runtime.query_service.domain
        if (
            runtime.scope["domain_id"] != domain.id
            or runtime.scope["ontology_version"] != domain.version
            or runtime.scope["ontology_fingerprint"] != domain.semantic_model.fingerprint
        ):
            raise ValueError("Evaluation runtime scope differs from actual query model")
    before = runtime.telemetry_snapshot() if runtime.telemetry_snapshot is not None else {}
    target_names = {}
    if runtime.query_service is not None:
        for item in runtime.query_service.domain.semantic_model.linking_records():
            if item.ref_kind == "class":
                for term in [item.ref_id, item.label, *item.aliases]:
                    target_names[term] = item.label
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case, repetition):
        """Run and grade one case repetition while capturing timing and failure."""
        async with semaphore:
            started = time.perf_counter()
            try:
                observation = await _observe(case, runtime, mode, concurrency == 1)
                checks = (
                    grade_case(
                        case,
                        observation,
                        fixtures,
                        target_names=target_names,
                        semantic_engine=(
                            runtime.query_service.runtime
                            if runtime.query_service is not None
                            else None
                        ),
                    )
                    if mode != "retrieval"
                    else {"scope": observation["scope_valid"]}
                )
                return {
                    "id": case.id,
                    "repetition": repetition,
                    "category": case.category,
                    "truth": case.truth,
                    "observation": observation,
                    "checks": checks,
                    "elapsed_ms": observation["elapsed_ms"],
                    "error": None,
                }
            # Report this diagnostic while preserving the remaining cases.
            except Exception as error:  # noqa: BLE001
                return {
                    "id": case.id,
                    "repetition": repetition,
                    "category": case.category,
                    "truth": case.truth,
                    "observation": None,
                    "checks": {},
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                    "error": {
                        "type": type(error).__name__,
                        "message": "Runtime invocation failed; no answer was graded.",
                        "expected_service_error": bool(
                            case.fault and type(error).__name__ in case.expected.errors
                        ),
                    },
                }

    rows = await asyncio.gather(
        *(one(case, repetition) for repetition in range(repeats) for case in cases)
    )
    after = runtime.telemetry_snapshot() if runtime.telemetry_snapshot is not None else {}
    scored_rows = [row for row in rows if row["truth"] != "manual_unverified"]
    metrics: dict[str, Any] = {}
    check_names = {
        "binding": "correct_binding",
        "ambiguity": "ambiguity_clarification",
        "scope": "scope_preservation",
        "evidence": "evidence_alignment",
        "numeric": "numeric_correctness",
        "shape_blocked": "shape_violation_blocking",
        "exact_preserved": "exact_preservation",
        "exact_embedding_free": "exact_embedding_free",
        "status": "expected_status",
    }
    for name, metric_name in check_names.items():
        metrics[metric_name] = _metric(_case_checks(scored_rows, name))
    for truth_group, truths in (
        ("controlled", {"controlled"}),
        ("real", {"human_verified"}),
    ):
        metrics[f"conditions_preservation_{truth_group}"] = _metric(
            _case_checks([row for row in rows if row["truth"] in truths], "conditions")
        )
        metrics[f"evidence_alignment_{truth_group}"] = _metric(
            _case_checks([row for row in rows if row["truth"] in truths], "evidence")
        )
    by_id = {case.id: case for case in cases}
    for row in rows:
        row["outcome_class"] = classify_outcome(by_id[row["id"]], row)
    for kind, maximum in (("concept", 5), ("entity", 10)):
        hits: list[bool] = []
        unobserved = []
        for identifier in dict.fromkeys(row["id"] for row in scored_rows):
            expected = getattr(
                by_id[identifier].expected,
                "concept_ids" if kind == "concept" else "object_ids",
            )
            if not expected:
                continue
            observations = [row["observation"] for row in scored_rows if row["id"] == identifier]
            if any(
                observed is None or observed[kind + "_candidates"] is None
                for observed in observations
            ):
                unobserved.append(identifier)
                continue
            returned = [
                set(
                    list(dict.fromkeys(item["id"] for item in observed[kind + "_candidates"]))[
                        :maximum
                    ]
                )
                for observed in observations
            ]
            hits.extend(all(item in group for group in returned) for item in expected)
        metrics[f"{kind}_recall_at_{maximum}"] = _metric(hits) | {
            "unobserved_cases": sorted(set(unobserved)),
            "unit": "relevant_gold_id",
        }
    metrics["unsupported_numeric_claim_count"] = sum(
        len(row["checks"].get("unsupported_numeric_claims", [])) for row in scored_rows
    )
    metrics["case_errors"] = sum(row["error"] is not None for row in rows)
    metrics["unexpected_case_errors"] = sum(
        row["error"] is not None and not row["error"]["expected_service_error"] for row in rows
    )
    metrics["service_failure_handling"] = _metric(
        [
            (
                row["error"]["expected_service_error"]
                if row["error"] is not None
                else row["observation"]["status"] in by_id[row["id"]].expected.statuses
            )
            for row in rows
            if by_id[row["id"]].fault
        ]
    )
    metrics.update(_approval_metrics(cases, rows))
    timings = [row["elapsed_ms"] for row in rows]
    stages: dict[str, list[float]] = {}
    for row in rows:
        if row["observation"] is not None:
            for name, seconds in row["observation"]["timings"].items():
                if name.endswith("_ms"):
                    stages.setdefault(name, []).append(seconds)
                elif name.endswith("_seconds"):
                    stages.setdefault(name, []).append(seconds * 1000)
    calls = _delta(before, after)
    successful = [row["observation"] for row in rows if row["observation"] is not None]
    for purpose in {name for observation in successful for name in observation["calls"]}:
        aggregate = calls.setdefault(purpose, {})
        for counter in {
            name for observation in successful for name in observation["calls"].get(purpose, {})
        }:
            values = [
                observation["calls"].get(purpose, {}).get(counter) for observation in successful
            ]
            if (
                counter not in aggregate
                and len(successful) == len(rows)
                and all(value is not None for value in values)
            ):
                aggregate[counter] = sum(values)
    for purpose in ("analysis", "generation"):
        calls.setdefault(
            purpose,
            {
                "logical_calls": (
                    sum(observation[purpose + "_calls"] for observation in successful)
                    if len(successful) == len(rows)
                    else None
                )
            },
        )
    for purpose in (
        "analysis",
        "generation",
        "candidate",
        "document",
        "build",
        "rerank",
    ):
        counters = calls.setdefault(purpose, {})
        for name in (
            "logical_calls",
            "provider_batches",
            "http_attempts",
            "input_tokens",
            "output_tokens",
            "input_characters",
        ):
            counters.setdefault(name, None)
    report = {
        "schema_version": "knowledge-evaluation-v1",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "status": "evaluated",
        "mode": mode,
        "linking_mode": linking_mode,
        "provider_kind": runtime.provider_kind,
        "scope": runtime.scope,
        "deployment": runtime.deployment,
        "dataset_hash": dataset_hash,
        "case_count": len(cases),
        "repeats": repeats,
        "truth_counts": dict(Counter(case.truth for case in cases)),
        "metrics": metrics,
        "calls": calls,
        "timings": {
            "all_requests": _percentiles(timings),
            "first_request_ms": timings[0] if timings else None,
            "steady_state": _percentiles(timings[1:]),
            "stages": {name: _percentiles(values) for name, values in stages.items()},
        },
        "concurrency": concurrency,
        "http_attribution": "per_case" if concurrency == 1 else "aggregate_only",
        "cases": rows,
        "cost": {"usd": None, "status": "pricing_or_token_usage_not_supplied"},
        "release_gate": _release_gate(metrics, runtime.provider_kind, cases, mode),
    }
    report["timings"]["steady_state"] = _percentiles(timings[concurrency:])
    report["timings"]["failed_requests"] = _percentiles(
        [row["elapsed_ms"] for row in rows if row["error"] is not None]
    )
    report["timings"]["by_category"] = {
        category: _percentiles([row["elapsed_ms"] for row in rows if row["category"] == category])
        for category in sorted({row["category"] for row in rows})
    }
    report["outcome_classes"] = dict(Counter(row["outcome_class"] for row in rows))
    report["classification_basis"] = (
        "Deterministic triage from trace and frozen truth; failure diagnosis requires human review."
    )
    if metrics["unexpected_case_errors"]:
        report["release_gate"]["failed"].append("case_errors")
    return report


def classify_outcome(case, row):
    """Assign one stable outcome category from the case and its graded observation."""
    if row["error"] is not None:
        return "service_unavailable" if case.fault else "functional_defect"
    if case.truth == "manual_unverified":
        return "source_incomplete"
    checks = row["checks"]
    if (
        checks.get("scope") is False
        or checks.get("shape_blocked") is False
        or checks.get("unsupported_numeric_claims")
    ):
        return "functional_defect"
    if checks.get("conditions") is False:
        return "model_understanding_error"
    if checks.get("binding") is False:
        candidates = row["observation"]["entity_candidates"]
        returned = (
            {candidate["id"] for candidate in candidates} if candidates is not None else set()
        )
        return (
            "retrieval_defect"
            if not set(case.expected.object_ids) <= returned
            else "model_understanding_error"
        )
    if case.category == "no_results" and checks.get("status"):
        return "data_not_recorded"
    if any(value is False for value in checks.values()):
        return "functional_defect"
    return "no_detected_defect"


def calibrate_policy(cases, observations, *, embedding_fingerprint, scope=None, kind="entity"):
    """Select candidate thresholds from held-out observations for one embedding scope."""
    if not cases or any(case.split != "calibration" for case in cases):
        raise ValueError("Calibration requires a separate calibration split; holdout is forbidden")
    if any(case.truth == "manual_unverified" for case in cases):
        raise ValueError("Calibration labels must have controlled or human-verified truth")
    by_id = {case.id: case for case in cases}
    points = []
    for row in observations:
        observed = row["observation"]
        if observed is None or not observed[kind + "_candidates"]:
            continue
        candidates = observed[kind + "_candidates"]
        if candidates[0]["vector_score"] is None:
            continue
        score = candidates[0]["vector_score"]
        second = (
            candidates[1]["vector_score"]
            if len(candidates) > 1 and candidates[1]["vector_score"] is not None
            else -1.0
        )
        expected = by_id[row["id"]].expected
        gold = expected.object_ids if kind == "entity" else expected.concept_ids
        correct = (
            len(gold) == 1
            and candidates[0]["id"] in gold
            and (kind == "concept" or not expected.choice_ids)
        )
        points.append((score, score - second, correct))
    policies = []
    for minimum in sorted({point[0] for point in points}):
        for margin in sorted({0.0, *(point[1] for point in points)}):
            accepted = [point for point in points if point[0] >= minimum and point[1] >= margin]
            if accepted and all(point[2] for point in accepted):
                policies.append(
                    (
                        len(accepted),
                        -minimum,
                        -margin,
                        {"min_cosine": minimum, "margin": margin},
                    )
                )
    policy = max(policies, key=lambda item: item[:3])[3] if policies else None
    identity = {
        "embedding_fingerprint": embedding_fingerprint,
        "scope": scope,
        "kind": kind,
        "cases": [case.model_dump() for case in sorted(cases, key=lambda case: case.id)],
        "observations": points,
        "policy": policy,
    }
    return {
        "calibration_id": _checksum(_canonical(identity).encode()),
        "embedding_fingerprint": embedding_fingerprint,
        "scope": scope,
        "kind": kind,
        "policy": policy,
        "observed_cases": len(points),
        "status": (
            "candidate_policy_requires_heldout_validation"
            if policy is not None
            else "insufficient_separable_calibration_evidence"
        ),
        "publication_ready": False,
    }


def compare_reports(baseline, current):
    """Compare two reports by outcome, quality gate, and resource usage changes."""
    if baseline["provider_kind"] != current["provider_kind"]:
        raise ValueError("Protocol and real-provider reports require separate baselines")
    semantic_keys = ("domain_id", "ontology_version", "ontology_fingerprint")
    if baseline["dataset_hash"] != current["dataset_hash"] or any(
        baseline["scope"].get(key) != current["scope"].get(key) for key in semantic_keys
    ):
        raise ValueError("Baseline comparison requires the same frozen dataset and scope")
    old_embedding, new_embedding = (
        baseline["scope"].get("embedding_fingerprint"),
        current["scope"].get("embedding_fingerprint"),
    )
    if old_embedding is not None and new_embedding is not None and old_embedding != new_embedding:
        raise ValueError("Baseline comparison cannot mix embedding spaces")
    if {(row["id"], row["repetition"]) for row in baseline["cases"]} != {
        (row["id"], row["repetition"]) for row in current["cases"]
    }:
        raise ValueError("Baseline comparison requires matching cases and repetitions")
    original = {(row["id"], row["repetition"]): row for row in baseline["cases"]}
    changes = []
    for row in current["cases"]:
        old = original[row["id"], row["repetition"]]["observation"]
        new = row["observation"]
        if (
            old is None
            or new is None
            or any(old[key] != new[key] for key in ("status", "selected_ids", "plan"))
        ):
            changes.append(row["id"])
    old_p95 = baseline["timings"]["all_requests"]["p95_ms"]
    new_p95 = current["timings"]["all_requests"]["p95_ms"]
    return {
        "baseline_mode": baseline["linking_mode"],
        "current_mode": current["linking_mode"],
        "structural_changes": sorted(set(changes)),
        "p95_ratio": new_p95 / old_p95 if old_p95 and new_p95 is not None else None,
        "metric_deltas": {
            name: metric["value"] - baseline["metrics"][name]["value"]
            for name, metric in current["metrics"].items()
            if isinstance(metric, dict)
            and metric["value"] is not None
            and baseline["metrics"].get(name, {}).get("value") is not None
        },
    }


def _report_dataset(report):
    """Read the frozen dataset identity embedded in an evaluation report."""
    frozen = report["frozen_dataset"]
    raw = frozen["questions_jsonl"].encode("utf-8")
    if _checksum(raw) != report["dataset_hash"]:
        raise ValueError("Evaluation frozen dataset hash mismatch")
    manifest = frozen["manifest"]
    filename = frozen["filename"]
    if manifest["files"][filename] != report["dataset_hash"]:
        raise ValueError("Dataset is not in its frozen manifest")
    fixtures = frozen["fixtures"]
    if _checksum(_canonical(fixtures).encode()) != frozen["fixtures_hash"]:
        raise ValueError("Evaluation frozen fixture hash mismatch")
    if manifest.get("materialized_scope") is None or any(
        report["scope"].get(key) != value for key, value in manifest["materialized_scope"].items()
    ):
        raise ValueError("Evaluation dataset formal model scope mismatch")
    cases = [
        EvaluationCase.model_validate(_json(line))
        for line in raw.decode("utf-8").splitlines()
        if line.strip()
    ]
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("Evaluation dataset cases must be nonempty and unique")
    return cases, fixtures


def _approval_metrics(cases, rows):
    """Calculate calibration acceptance metrics from graded cases and observations."""
    scored = [row for row in rows if row["truth"] != "manual_unverified"]
    names = {
        "correct_binding": "binding",
        "ambiguity_clarification": "ambiguity",
        "scope_preservation": "scope",
        "numeric_correctness": "numeric",
        "shape_violation_blocking": "shape_blocked",
        "exact_preservation": "exact_preserved",
        "exact_embedding_free": "exact_embedding_free",
        "evidence_alignment": "evidence",
        "expected_status": "status",
    }
    metrics: dict[str, Any] = {
        name: _metric(_case_checks(scored, key)) for name, key in names.items()
    }
    metrics["exact_embedding_free"]["unobserved_cases"] = sorted(
        {
            case.id
            for case in cases
            if {"exact", "approved_alias"}.intersection(case.tags)
            and any(
                row["checks"].get("exact_embedding_free") is None
                for row in rows
                if row["id"] == case.id
            )
        }
    )
    for truth, label in (("controlled", "controlled"), ("human_verified", "real")):
        selected = [row for row in scored if row["truth"] == truth]
        metrics["conditions_preservation_" + label] = _metric(_case_checks(selected, "conditions"))
        metrics["evidence_alignment_" + label] = _metric(_case_checks(selected, "evidence"))
    for kind, k in (("concept", 5), ("entity", 10)):
        outcomes: list[bool] = []
        missing = []
        for case in cases:
            if case.truth == "manual_unverified":
                continue
            gold = case.expected.concept_ids if kind == "concept" else case.expected.object_ids
            if not gold:
                continue
            observations = [row["observation"] for row in scored if row["id"] == case.id]
            if not observations or any(
                item is None or item[kind + "_candidates"] is None for item in observations
            ):
                missing.append(case.id)
                continue
            retrieved = [
                set(
                    list(
                        dict.fromkeys(candidate["id"] for candidate in item[kind + "_candidates"])
                    )[:k]
                )
                for item in observations
            ]
            outcomes.extend(all(identifier in ids for ids in retrieved) for identifier in gold)
        metrics[f"{kind}_recall_at_{k}"] = _metric(outcomes) | {
            "unobserved_cases": sorted(missing),
            "unit": "relevant_gold_id",
        }
    metrics["unsupported_numeric_claim_count"] = sum(
        len(row["checks"].get("unsupported_numeric_claims", [])) for row in scored
    )
    return metrics


def _assert_real_report(report, scope, generation_id):
    """Reject calibration inputs lacking real-provider, scope, or generation evidence."""
    from gustobot.domain.linking import GraphRevision

    if report.get("provider_kind") != "real":
        raise ValueError(
            "Calibration publication requires actual real-provider reports; protocol reports are rejected"
        )
    if (
        report.get("status") != "evaluated"
        or report.get("schema_version") != "knowledge-evaluation-v1"
    ):
        raise ValueError("Calibration requires a completed evaluation report")
    if not report["deployment"].get("embedding_revision") or not report["deployment"].get(
        "embedding_model"
    ):
        raise ValueError("Real-provider embedding deployment and explicit revision are required")
    attempts = report["calls"].get("candidate", {}).get("http_attempts")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts <= 0:
        raise ValueError("Real-provider calibration needs observed embedding HTTP attempts")
    for key, value in scope.items():
        if key != "kind" and report["scope"].get(key) != value:
            raise ValueError("Calibration report scope or embedding space mismatch")
    kinds = set()
    revisions = set()
    for row in report["cases"]:
        observation = row["observation"]
        if observation is None:
            continue
        for candidate_kind in ("concept", "entity"):
            for candidate in observation.get(candidate_kind + "_candidates") or []:
                if candidate["kind"] != candidate_kind or any(
                    candidate[key] != report["scope"][key]
                    for key in ("domain_id", "ontology_version", "ontology_fingerprint")
                ):
                    raise ValueError("Candidate trace belongs to another scope or model version")
                if candidate["generation_id"] is not None and candidate[
                    "generation_id"
                ] != observation["generation"].get(candidate_kind):
                    raise ValueError(
                        "Candidate trace generation differs from the observed generation"
                    )
        observed = observation["generation"].get(scope["kind"])
        if observed is not None:
            kinds.add(observed)
        revision = observation["graph_revision"]
        if revision is not None:
            typed_revision = GraphRevision.model_validate(revision)
            if typed_revision.state != "ready":
                raise ValueError("Calibration evidence graph revision must be ready")
            if any(
                getattr(typed_revision, key) != report["scope"][key]
                for key in ("domain_id", "ontology_version", "ontology_fingerprint")
            ):
                raise ValueError("Calibration graph revision scope differs from its formal model")
            revisions.add(typed_revision.revision)
        elif observation["generation"].get("entity") is not None:
            raise ValueError(
                "Entity generation evidence requires its complete ready graph revision"
            )
    if kinds != {generation_id}:
        raise ValueError("Calibration evidence does not identify one exact current generation")
    if scope["kind"] == "entity" and (len(revisions) != 1 or None in revisions):
        raise ValueError("Calibration evidence does not identify one ready graph revision")
    return next(iter(revisions)) if scope["kind"] == "entity" else None


def candidate_policy_from_report(report):
    """Validate a real calibration fit for an isolated, temporary heldout overlay."""
    from gustobot.domain.linking import INDEX_SCHEMA_VERSION, IndexScope

    if report.get("provider_kind") != "real":
        raise ValueError("Candidate calibration overlay requires an actual real-provider report")
    calibration = report["calibration"]
    scope = IndexScope.model_validate(
        report["scope"]
        | {"kind": calibration["kind"], "index_schema_version": INDEX_SCHEMA_VERSION}
    ).model_dump()
    generations = {
        row["observation"]["generation"].get(scope["kind"])
        for row in report["cases"]
        if row["observation"] is not None
    }
    generations.discard(None)
    if len(generations) != 1:
        raise ValueError("Candidate calibration must identify exactly one indexed generation")
    generation_id = next(iter(generations))
    revision = _assert_real_report(report, scope, generation_id)
    cases, _ = _report_dataset(report)
    fitted = calibrate_policy(
        cases,
        report["cases"],
        embedding_fingerprint=scope["embedding_fingerprint"],
        scope=report["scope"],
        kind=scope["kind"],
    )
    if fitted["policy"] is None or any(
        fitted[key] != calibration[key]
        for key in (
            "calibration_id",
            "policy",
            "kind",
            "scope",
            "embedding_fingerprint",
        )
    ):
        raise ValueError("Candidate calibration fit does not match its measured report")
    return {
        "scope": scope,
        "generation_id": generation_id,
        "graph_revision": revision,
        "calibration_id": fitted["calibration_id"],
        "policy": fitted["policy"],
        "report_hash": _checksum(_canonical(report).encode()),
        "publication_ready": False,
    }


def build_approved_calibration_report(calibration_report, heldout_report, *, scope, generation_id):
    """Make a publication artifact only from disjoint actual runs and independent heldout evidence."""
    from gustobot.domain.linking import IndexScope

    scope = IndexScope.model_validate(scope).model_dump()
    calibration_revision = _assert_real_report(calibration_report, scope, generation_id)
    heldout_revision = _assert_real_report(heldout_report, scope, generation_id)
    if calibration_revision != heldout_revision:
        raise ValueError("Calibration and heldout graph revision differ")
    calibration_cases, _ = _report_dataset(calibration_report)
    cases, fixtures = _report_dataset(heldout_report)
    if any(case.split != "calibration" for case in calibration_cases) or any(
        case.split != "holdout" for case in cases
    ):
        raise ValueError("Calibration and heldout splits must remain separate")
    if (
        calibration_report["dataset_hash"] == heldout_report["dataset_hash"]
        or {case.id for case in cases} & {case.id for case in calibration_cases}
        or {normalize_question(case.question) for case in cases}
        & {normalize_question(case.question) for case in calibration_cases}
    ):
        raise ValueError("Calibration and heldout datasets overlap")
    if (
        len(cases) < 200
        or not any(case.truth == "human_verified" for case in cases)
        or any(case.truth == "manual_unverified" for case in cases)
    ):
        raise ValueError(
            "Publication requires at least 200 heldout cases with approved real-source truth"
        )
    calibration = calibration_report["calibration"]
    if calibration.get("kind") != scope["kind"]:
        raise ValueError("Calibration candidate kind differs from publication scope")
    recomputed = calibrate_policy(
        calibration_cases,
        calibration_report["cases"],
        embedding_fingerprint=scope["embedding_fingerprint"],
        scope=calibration_report["scope"],
        kind=scope["kind"],
    )
    if (
        any(
            calibration[key] != recomputed[key]
            for key in ("calibration_id", "policy", "embedding_fingerprint", "scope")
        )
        or calibration["policy"] is None
    ):
        raise ValueError("Calibration policy or hash differs from measured calibration cases")
    if heldout_report["deployment"].get("calibration_id") != calibration["calibration_id"]:
        raise ValueError("Heldout run did not actually apply the candidate calibration policy")
    by_id = {case.id: case for case in cases}
    if {(row["id"], row["repetition"]) for row in heldout_report["cases"]} != {
        (case.id, repetition) for case in cases for repetition in range(heldout_report["repeats"])
    }:
        raise ValueError("Heldout case observations are incomplete")
    if any(row["error"] is not None for row in heldout_report["cases"]):
        raise ValueError("Heldout report has ungraded execution failures")
    semantic_engine = None
    if any(
        assertion.get("kind") == "derived"
        for row in heldout_report["cases"]
        if row["observation"] is not None
        for assertion in row["observation"]["assertions"]
    ):
        from gustobot.domain.formal_ontology import load_formal_ontology
        from gustobot.infrastructure.knowledge.semantic_runtime import SemanticRuntime

        ontology = PROJECT_ROOT / "gustobot/config/ontologies"
        model = load_formal_ontology(ontology / "recipes.ttl", ontology / "recipes.shacl.ttl")
        if model.fingerprint != heldout_report["scope"]["ontology_fingerprint"]:
            raise ValueError("Derived evidence model differs from the approved report scope")
        semantic_engine = SemanticRuntime(model)
    for row in heldout_report["cases"]:
        if row["truth"] != by_id[row["id"]].truth:
            raise ValueError("Heldout observation truth label differs from its frozen case")
        checks = grade_case(
            by_id[row["id"]],
            row["observation"],
            fixtures,
            semantic_engine=semantic_engine,
        )
        if checks != row["checks"]:
            raise ValueError("Heldout stored checks do not match frozen truth")
    metrics = _approval_metrics(cases, heldout_report["cases"])
    if any(heldout_report["metrics"].get(key) != value for key, value in metrics.items()):
        raise ValueError("Heldout aggregate metrics differ from independently graded traces")
    gate = _release_gate(metrics, "real", cases, "qa")
    pending = set(gate["pending"]) - {
        "baseline_shadow_on_comparison",
        "human_prose_review",
    }
    if gate["failed"] or pending:
        raise ValueError("Heldout release metrics are failed or unobserved")
    verification = heldout_report.get("human_verification")
    if (
        not isinstance(verification, dict)
        or verification.get("dataset_hash") != heldout_report["dataset_hash"]
        or verification.get("fixtures_hash") != heldout_report["frozen_dataset"]["fixtures_hash"]
        or not verification.get("reviewer")
        or not verification.get("reviewed_at")
        or verification.get("prose_and_quantitative_claims_approved") is not True
    ):
        raise ValueError(
            "Heldout source/prose verification is missing or belongs to another dataset"
        )
    if heldout_report.get("linking_mode") != "on":
        raise ValueError("Heldout quality must be measured with the calibrated on policy")
    comparison = heldout_report.get("comparison")
    if (
        comparison is None
        or comparison["baseline_mode"] != "shadow"
        or comparison["current_mode"] != "on"
    ):
        raise ValueError("Heldout report requires the baseline/shadow/on comparison chain")
    baseline = heldout_report.get("comparison_evidence")
    if (
        baseline is None
        or baseline.get("provider_kind") != "real"
        or baseline.get("comparison", {}).get("baseline_mode") != "off"
        or baseline["comparison"].get("structural_changes")
    ):
        raise ValueError("Actual off/shadow comparison evidence is missing or changed answers")
    if compare_reports(baseline, heldout_report) != comparison:
        raise ValueError("Heldout comparison evidence was modified")
    previous = baseline.get("comparison_evidence")
    if (
        previous is None
        or previous.get("provider_kind") != "real"
        or compare_reports(previous, baseline) != baseline["comparison"]
    ):
        raise ValueError("Actual lexical baseline evidence is missing or modified")
    values = {
        name: metric["value"]
        for name, metric in heldout_report["metrics"].items()
        if isinstance(metric, dict) and "value" in metric
    }
    values["unsupported_numeric_claim_count"] = heldout_report["metrics"][
        "unsupported_numeric_claim_count"
    ]
    bundle = {
        "schema_version": "knowledge-approved-calibration-v1",
        "provider_kind": "real",
        "publication_ready": True,
        "scope": scope,
        "generation_id": generation_id,
        "graph_revision": heldout_revision,
        "calibration": {
            "calibration_id": calibration["calibration_id"],
            "dataset_hash": calibration_report["dataset_hash"],
            "report_hash": _checksum(_canonical(calibration_report).encode()),
            "policy": calibration["policy"],
        },
        "heldout": {
            "dataset_hash": heldout_report["dataset_hash"],
            "report_hash": _checksum(_canonical(heldout_report).encode()),
            "split": "holdout",
            "gate_passed": True,
            "case_count": len(cases),
            "truth_counts": dict(Counter(case.truth for case in cases)),
            "metric_values": values,
        },
        "evidence": {
            "calibration_report": calibration_report,
            "heldout_report": heldout_report,
        },
    }
    bundle["report_hash"] = _checksum(_canonical(bundle).encode())
    return bundle


def normalize_question(question):
    """Normalize whitespace and Unicode for stable evaluation question identity."""
    return " ".join(unicodedata.normalize("NFKC", question).casefold().split())


def validate_approved_calibration_report(payload):
    """Validate report provenance and real-provider evidence before policy use."""
    if payload.get("schema_version") != "knowledge-approved-calibration-v1":
        raise ValueError("Unsupported approved-calibration report schema")
    try:
        expected = build_approved_calibration_report(
            payload["evidence"]["calibration_report"],
            payload["evidence"]["heldout_report"],
            scope=payload["scope"],
            generation_id=payload["generation_id"],
        )
    except KeyError as error:
        raise ValueError("Approved calibration report is incomplete") from error
    if _canonical(payload) != _canonical(expected):
        raise ValueError("Approved calibration report hash or derived summary was modified")
    return payload


def calculate_cost(calls, prices):
    """Estimate only declared rates applied to observed usage; missing usage remains unknown."""
    rates = {
        "input_usd_per_million": ("input_tokens", 1_000_000),
        "output_usd_per_million": ("output_tokens", 1_000_000),
        "http_attempt_usd": ("http_attempts", 1),
    }
    total = Fraction(0)
    components = []
    unknown = []

    def decimal_text(value):
        """Format a rational cost exactly without scientific notation."""
        with localcontext() as context:
            context.prec = 50
            text = format(Decimal(value.numerator) / Decimal(value.denominator), "f")
            return text.rstrip("0").rstrip(".") if "." in text else text

    for purpose, counters in calls.items():
        if counters.get("http_attempts") == 0:
            components.append(
                {"purpose": purpose, "usd": "0", "basis": "zero_observed_http_attempts"}
            )
            continue
        if purpose not in prices or not prices[purpose]:
            unknown.append(purpose + ".price")
            continue
        for rate, price in prices[purpose].items():
            counter, scale = rates[rate]
            value = counters.get(counter)
            if value is None:
                unknown.append(purpose + "." + counter)
                continue
            usage, declared_price = Fraction(str(value)), Fraction(str(price))
            if usage < 0 or declared_price < 0:
                raise ValueError("Usage and declared prices must be nonnegative")
            amount = usage * declared_price / scale
            total += amount
            components.append(
                {
                    "purpose": purpose,
                    "counter": counter,
                    "observed_usage": value,
                    "declared_rate": str(price),
                    "usd": decimal_text(amount),
                }
            )
    known = decimal_text(total) if components else None
    return {
        "usd": known if not unknown else None,
        "usd_known": known,
        "components": components,
        "unknown": sorted(set(unknown)),
        "basis": "declared_prices_and_observed_usage; estimate_not_provider_invoice",
    }


def _attach_build_cost(report, args):
    """Attach observed index-build resource totals and configured prices."""
    if args.build_telemetry is None:
        return
    source = _json(args.build_telemetry.read_text(encoding="utf-8"))
    scope = source["scope"]
    if scope["domain_id"] != args.scope:
        raise ValueError("Build telemetry domain differs from requested scope")
    runtime_scope = report["scope"] if isinstance(report["scope"], dict) else None
    if runtime_scope is not None and any(
        scope[key] != runtime_scope[key]
        for key in ("domain_id", "ontology_version", "ontology_fingerprint")
    ):
        raise ValueError("Build telemetry belongs to a different formal model scope")
    prices = _json(args.prices.read_text(encoding="utf-8")) if args.prices else {}
    report["build_cost"] = {
        "scope": scope,
        "provenance": "imported_telemetry",
        "verified_against_runtime": runtime_scope is not None,
    }
    for operation in ("full_build", "single_update"):
        report["build_cost"][operation] = (
            calculate_cost(source[operation]["calls"], prices)
            if operation in source
            else {"usd": None, "status": "not_measured"}
        )


def create_runtime(*, scope, linking_mode):
    """Create isolated evaluation clients for the requested domain and link mode."""
    from gustobot.application.services import knowledge_runtime
    from gustobot.config import settings

    if settings.SEMANTIC_LINKING_MODE != linking_mode:
        raise ValueError("Requested linking mode must match explicitly configured runtime settings")
    service = knowledge_runtime.get_query_service()
    if service.domain.id != scope:
        raise ValueError("Requested evaluation domain differs from runtime")
    linker = knowledge_runtime.get_entity_linker()
    embedding_fingerprint = (
        linker.scopes["entity"].embedding_fingerprint if linker is not None else None
    )
    return EvaluationRuntime(
        query_service=service,
        linker=linker,
        scope={
            "domain_id": service.domain.id,
            "ontology_version": service.domain.version,
            "ontology_fingerprint": service.domain.semantic_model.fingerprint,
            "embedding_fingerprint": embedding_fingerprint,
        },
        deployment={
            "generation_model": settings.LLM_MODEL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "embedding_revision": settings.SEMANTIC_EMBEDDING_REVISION,
            "transport_instrumentation": "provide_runtime_factory_for_client_attempt_snapshots",
        },
        provider_kind="real",
        cleanup=knowledge_runtime.cleanup_runtime,
    )


def _write_report(report, output):
    """Write the report, case rows, and failed rows as JSON files."""
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    rows = report.get("cases", [])
    (output / "cases.jsonl").write_text(
        "".join(_canonical(row) + "\n" for row in rows), encoding="utf-8"
    )
    failed = [
        row
        for row in rows
        if row["error"] is not None
        or any(value is False for value in row["checks"].values())
        or row["checks"].get("unsupported_numeric_claims")
    ]
    (output / "failures.jsonl").write_text(
        "".join(_canonical(row) + "\n" for row in failed), encoding="utf-8"
    )


async def execute(args, *, runtime_factory=None):
    """Load, run, and report an evaluation while closing all acquired resources."""
    if args.approve_calibration:
        if not args.heldout_report or not args.generation or not args.kind:
            raise ValueError(
                "Approved calibration export requires --heldout-report, --generation, and --kind"
            )
        calibration_report = _json(args.approve_calibration.read_text(encoding="utf-8"))
        heldout_report = _json(args.heldout_report.read_text(encoding="utf-8"))
        from gustobot.domain.linking import INDEX_SCHEMA_VERSION

        scope = heldout_report["scope"] | {
            "kind": args.kind,
            "index_schema_version": INDEX_SCHEMA_VERSION,
        }
        if scope["domain_id"] != args.scope:
            raise ValueError("Approved calibration domain differs from requested scope")
        bundle = build_approved_calibration_report(
            calibration_report,
            heldout_report,
            scope=scope,
            generation_id=args.generation,
        )
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "approved-calibration.json").write_text(
            json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        return 0
    dataset = load_dataset(args.dataset)
    if args.materialize:
        materialize_dataset(args.dataset, args.output)
        return 0
    if args.calibrate and any(case.split != "calibration" for case in dataset.cases):
        raise ValueError("Cannot calibrate on the holdout dataset")
    if args.dry_run:
        report = {
            "status": "dry_run",
            "mode": args.mode,
            "scope": args.scope,
            "dataset_hash": dataset.checksum,
            "case_count": len(dataset.cases),
            "categories": dict(Counter(case.category for case in dataset.cases)),
            "truth_counts": dict(Counter(case.truth for case in dataset.cases)),
            "metrics": {},
            "materialized_scope": dataset.manifest.get("materialized_scope"),
            "release_gate": {
                "accepted": False,
                "pending": [
                    "real_provider",
                    "approved_real_truth",
                    "actual_runtime_measurement",
                ],
                "failed": [],
            },
        }
        _attach_build_cost(report, args)
        _write_report(report, args.output)
        return 0
    if runtime_factory is None:
        if args.runtime_factory:
            module, name = args.runtime_factory.rsplit(":", 1)
            runtime_factory = getattr(importlib.import_module(module), name)
        else:
            runtime_factory = create_runtime
    started = time.perf_counter()
    factory_arguments = {"scope": args.scope, "linking_mode": args.linking_mode}
    candidate_calibration = None
    if args.candidate_calibration_report:
        if runtime_factory is create_runtime:
            raise ValueError(
                "Candidate policy overlay requires an explicit isolated runtime factory"
            )
        candidate_calibration = candidate_policy_from_report(
            _json(args.candidate_calibration_report.read_text(encoding="utf-8"))
        )
        factory_arguments["candidate_calibration"] = candidate_calibration
    runtime = runtime_factory(**factory_arguments)
    if inspect.isawaitable(runtime):
        runtime = await runtime
    try:
        if candidate_calibration is not None and (
            runtime.deployment.get("calibration_id") != candidate_calibration["calibration_id"]
            or runtime.deployment.get("candidate_policy") != candidate_calibration["policy"]
        ):
            raise ValueError(
                "Evaluation runtime did not apply the exact candidate calibration overlay"
            )
        binding = dataset.manifest.get("materialized_scope")
        if dataset.manifest and binding is None:
            raise ValueError(
                "Frozen fixture must be materialized to actual formal IDs and scope before provider evaluation"
            )
        if binding is not None and any(
            runtime.scope[key] != value for key, value in binding.items()
        ):
            raise ValueError("Materialized dataset scope differs from runtime")
        factory_ms = (time.perf_counter() - started) * 1000
        report = await run_evaluation(
            dataset.cases,
            runtime=runtime,
            mode=args.mode,
            linking_mode=args.linking_mode,
            fixtures=dataset.fixtures,
            dataset_hash=dataset.checksum,
            concurrency=args.concurrency,
            repeats=args.repeats,
        )
        report["timings"]["runtime_initialization_ms"] = factory_ms
        report["frozen_dataset"] = {
            "filename": args.dataset.name,
            "questions_jsonl": args.dataset.read_bytes().decode("utf-8"),
            "fixtures": dataset.fixtures,
            "fixtures_hash": _checksum(_canonical(dataset.fixtures).encode()),
            "manifest": dataset.manifest,
        }
        if args.calibrate:
            report["calibration"] = calibrate_policy(
                dataset.cases,
                report["cases"],
                embedding_fingerprint=runtime.scope["embedding_fingerprint"],
                scope=runtime.scope,
                kind=args.calibration_kind,
            )
            report["calibration"]["provider_kind"] = runtime.provider_kind
        if args.compare_baseline:
            baseline_report = _json(args.compare_baseline.read_text(encoding="utf-8"))
            report["comparison"] = compare_reports(baseline_report, report)
            report["comparison_evidence"] = baseline_report
            if args.linking_mode == "shadow" and report["comparison"]["structural_changes"]:
                report["release_gate"]["failed"].append("shadow_changed_baseline")
        if args.prices:
            report["cost"] = calculate_cost(
                report["calls"], _json(args.prices.read_text(encoding="utf-8"))
            )
        _attach_build_cost(report, args)
        if args.human_verification:
            report["human_verification"] = _json(
                args.human_verification.read_text(encoding="utf-8")
            )
        _write_report(report, args.output)
        return (
            1
            if report["metrics"]["unexpected_case_errors"] or report["release_gate"]["failed"]
            else 0
        )
    finally:
        if runtime.cleanup is not None:
            closed = runtime.cleanup()
            if inspect.isawaitable(closed):
                await closed


def main(argv=None, *, runtime_factory=None):
    """Parse evaluation options and return an exit status from release gates."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("protocol", "retrieval", "qa", "latency"), required=True)
    parser.add_argument(
        "--dataset", type=Path, default=PROJECT_ROOT / "eval/knowledge/questions.jsonl"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scope",
        required=True,
        help="Explicit domain ID; full model scope comes from materialization/runtime",
    )
    parser.add_argument("--linking-mode", choices=("off", "shadow", "on"), default="off")
    parser.add_argument(
        "--runtime-factory", help="module:callable accepting scope and linking_mode"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--materialize",
        action="store_true",
        help="Create a separately hashed fixture bound to actual formal model IDs; no database writes",
    )
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--calibration-kind", choices=("concept", "entity"), default="entity")
    parser.add_argument("--concurrency", type=int, choices=(1, 5, 20), default=1)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--compare-baseline", type=Path)
    parser.add_argument(
        "--prices",
        type=Path,
        help="Declared per-purpose USD rates; unknown token usage is never estimated",
    )
    parser.add_argument(
        "--build-telemetry",
        type=Path,
        help="Import scoped full_build/single_update measured counters for the cost report",
    )
    parser.add_argument(
        "--approve-calibration",
        type=Path,
        help="Export a guarded publication bundle from this actual calibration report",
    )
    parser.add_argument("--heldout-report", type=Path)
    parser.add_argument("--generation")
    parser.add_argument("--kind", choices=("concept", "entity"))
    parser.add_argument(
        "--human-verification",
        type=Path,
        help="Human review tied to exact dataset/fixtures hashes",
    )
    parser.add_argument(
        "--candidate-calibration-report",
        type=Path,
        help="Use a validated candidate policy through an explicit isolated runtime factory; never publishes policy",
    )
    return asyncio.run(execute(parser.parse_args(argv), runtime_factory=runtime_factory))


if __name__ == "__main__":
    raise SystemExit(main())

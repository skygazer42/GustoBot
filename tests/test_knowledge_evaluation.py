"""Evaluation gates use frozen truth, actual public answers, and measured counters."""

import importlib
import json
from pathlib import Path

import pytest

from gustobot.domain.linking import INDEX_SCHEMA_VERSION, CandidateKind

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "eval/knowledge/questions.jsonl"
CANDIDATE_KINDS: tuple[CandidateKind, CandidateKind] = ("concept", "entity")


def evaluator():
    return importlib.import_module("scripts.evaluate_knowledge")


def test_frozen_holdout_has_meaningful_cases_and_disjoint_calibration():
    module = evaluator()
    holdout = module.load_dataset(DATASET)
    calibration = module.load_dataset(DATASET.with_name("calibration.jsonl"))
    assert len(holdout.cases) >= 200
    assert len({case.question for case in holdout.cases}) == len(holdout.cases)
    assert {case.split for case in holdout.cases} == {"holdout"}
    assert {case.split for case in calibration.cases} == {"calibration"}
    assert not {case.question for case in holdout.cases}.intersection(
        case.question for case in calibration.cases
    )
    assert {case.category for case in holdout.cases} >= {
        "exact",
        "alias",
        "paraphrase",
        "typo",
        "ambiguous",
        "numeric",
        "duration",
        "documents",
        "combined",
        "scope",
        "service_failure",
        "no_results",
        "out_of_domain",
    }
    assert all(case.truth == "controlled" for case in holdout.cases)
    assert holdout.manifest["real_source_truth"]["status"] == "pending_human_verification"
    assert len(holdout.fixtures["sources"]) >= 20
    assert all(
        case.expected.source_ids
        or case.category in {"out_of_domain", "no_results", "service_failure", "scope"}
        for case in holdout.cases
    )


def test_dry_run_never_constructs_runtime_and_does_not_claim_quality(tmp_path):
    module = evaluator()

    def prohibited(**kwargs):
        raise AssertionError("dry run accessed providers")

    assert (
        module.main(
            [
                "--mode",
                "qa",
                "--dataset",
                str(DATASET),
                "--output",
                str(tmp_path),
                "--scope",
                "recipes",
                "--dry-run",
            ],
            runtime_factory=prohibited,
        )
        == 0
    )
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "dry_run"
    assert report["metrics"] == {}
    assert report["release_gate"]["accepted"] is False
    assert "real_provider" in report["release_gate"]["pending"]


def test_holdout_tampering_and_duplicate_questions_fail_visibly(tmp_path):
    module = evaluator()
    copied = tmp_path / "questions.jsonl"
    copied.write_text(DATASET.read_text(encoding="utf-8"), encoding="utf-8")
    copied.with_name("manifest.json").write_text(
        DATASET.with_name("manifest.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with copied.open("a", encoding="utf-8") as output:
        output.write(copied.read_text(encoding="utf-8").splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="hash|checksum|Duplicate|duplicate"):
        module.load_dataset(copied)


def test_dry_run_can_report_declared_build_and_update_cost_without_providers(tmp_path):
    module = evaluator()
    telemetry = tmp_path / "build-telemetry.json"
    prices = tmp_path / "prices.json"
    telemetry.write_text(
        json.dumps(
            {
                "scope": {
                    "domain_id": "recipes",
                    "ontology_version": "2026-11-17.1",
                    "ontology_fingerprint": "a" * 64,
                },
                "full_build": {"calls": {"build": {"input_tokens": 1000, "http_attempts": 2}}},
                "single_update": {"calls": {"build": {"input_tokens": 10, "http_attempts": 1}}},
            }
        ),
        encoding="utf-8",
    )
    prices.write_text(json.dumps({"build": {"input_usd_per_million": "0.1"}}), encoding="utf-8")
    assert (
        module.main(
            [
                "--mode",
                "protocol",
                "--dataset",
                str(DATASET),
                "--scope",
                "recipes",
                "--output",
                str(tmp_path / "report"),
                "--dry-run",
                "--build-telemetry",
                str(telemetry),
                "--prices",
                str(prices),
            ],
            runtime_factory=lambda **kwargs: pytest.fail("dry run constructed runtime"),
        )
        == 0
    )
    report = json.loads((tmp_path / "report/report.json").read_text(encoding="utf-8"))
    assert report["metrics"] == {}
    assert report["build_cost"]["full_build"]["usd"] == "0.0001"
    assert report["build_cost"]["single_update"]["usd"] == "0.000001"
    assert report["build_cost"]["provenance"] == "imported_telemetry"


def test_metrics_reject_wrong_binding_dropped_conditions_and_unsupported_numbers():
    module = evaluator()
    case = module.EvaluationCase.model_validate(
        {
            "id": "adversarial",
            "split": "holdout",
            "truth": "controlled",
            "category": "numeric",
            "question": "糖水红糖不超过20g的做法有哪些？",
            "tags": [],
            "expected": {
                "concept_ids": ["ingredientTotalAmount"],
                "object_ids": ["r-a"],
                "statuses": ["success"],
                "conditions": [
                    {
                        "property": "ingredientTotalAmount",
                        "op": "lte",
                        "value": "20",
                        "unit": "g",
                        "grain": "recipe",
                    }
                ],
                "source_ids": ["source-a"],
                "numbers": [{"value": "10", "unit": "g"}],
            },
        }
    )
    observed = {
        "status": "success",
        "selected_ids": ["foreign"],
        "concept_candidates": [],
        "entity_candidates": [],
        "plan": {"conditions": []},
        "sources": [{"document_id": "forged"}],
        "assertions": [],
        "derivations": [],
        "message": "红糖为999g。",
        "choices": [],
        "calls": {},
        "scope_valid": False,
        "diagnostics": [],
    }
    checks = module.grade_case(case, observed, {"sources": [], "entities": [], "relations": []})
    assert checks["binding"] is False
    assert checks["conditions"] is False
    assert checks["scope"] is False
    assert checks["evidence"] is False
    assert checks["numeric"] is False
    assert checks["unsupported_numeric_claims"] == ["999 g"]


def test_calibration_refuses_holdout_and_binds_policy_to_embedding_space():
    module = evaluator()
    dataset = module.load_dataset(DATASET)
    with pytest.raises(ValueError, match="calibration|holdout"):
        module.calibrate_policy(dataset.cases[:1], [], embedding_fingerprint="b" * 64)


@pytest.mark.parametrize(
    "predicate", ["matched", "not_matched", "uncertain", "unknown", "non_comparable"]
)
def test_numeric_grading_uses_exact_public_coverage_and_keeps_numeric_conditions(
    predicate,
):
    module = evaluator()
    condition = {
        "property": "ingredientTotalAmount",
        "target_ref": "sugar",
        "grain": "recipe_total",
        "op": "lte",
        "value": "20",
        "unit": "g",
    }
    case = module.EvaluationCase.model_validate(
        {
            "id": "numeric-coverage",
            "split": "holdout",
            "truth": "controlled",
            "category": "numeric",
            "question": "合计是否不超过20g？",
            "expected": {
                "statuses": ["success"],
                "conditions": [condition],
                "expected_predicate": predicate,
            },
        }
    )
    coverage: dict[str, str | int] = {
        "property": "ingredientTotalAmount",
        "target_ref": "sugar",
        "grain": "recipe_total",
        "total": 1,
        predicate: 1,
    }
    observed = {
        "status": "success",
        "selected_ids": [],
        "plan": {
            "conditions": [],
            "numeric_conditions": [condition | {"value": 20, "minimum": None, "maximum": None}],
        },
        "sources": [],
        "assertions": [],
        "derivations": [],
        "message": "比较结果见覆盖信息。",
        "choices": [],
        "scope_valid": True,
        "calls": {},
        "numeric_coverage": [coverage],
    }
    checks = module.grade_case(case, observed, {"sources": [], "entities": [], "relations": []})
    assert checks["conditions"] is True
    assert checks["numeric"] is True
    coverage["target_ref"] = "another-ingredient"
    assert (
        module.grade_case(case, observed, {"sources": [], "entities": [], "relations": []})[
            "numeric"
        ]
        is False
    )


def test_numeric_range_reports_both_endpoints_without_invented_zero():
    module = evaluator()
    assert module._numbers("已记录区间10–20g，不能当成0g。") == {
        ("10", "g"),
        ("20", "g"),
        ("0", "g"),
    }


def test_unknown_duration_without_filter_does_not_need_coverage_or_default_zero():
    module = evaluator()
    case = module.EvaluationCase.model_validate(
        {
            "id": "unknown-duration",
            "split": "holdout",
            "truth": "controlled",
            "category": "duration",
            "question": "没有明确记录的时长是多少？",
            "expected": {
                "statuses": ["insufficient_evidence"],
                "numeric_unknown": True,
            },
        }
    )
    observation = {
        "status": "insufficient_evidence",
        "selected_ids": [],
        "plan": {},
        "sources": [],
        "assertions": [],
        "derivations": [],
        "message": "来源只写数天，无法确定分钟数。",
        "choices": [],
        "scope_valid": True,
        "calls": {},
    }
    fixtures: dict[str, list[dict[str, object]]] = {"sources": [], "entities": [], "relations": []}
    assert module.grade_case(case, observation, fixtures)["numeric"] is True
    observation["message"] = "来源没有时间，默认0分钟。"
    assert module.grade_case(case, observation, fixtures)["numeric"] is False


@pytest.mark.parametrize(
    "text,number,unit",
    [
        ("20minute", "20", "分钟"),
        ("1500000ms", "25", "分钟"),
        ("25000000ug", "25", "g"),
    ],
)
def test_numeric_grader_recognizes_canonical_projection_units(text, number, unit):
    assert evaluator()._numbers(text) == {(number, unit)}


def test_derived_numeric_assertions_validate_complete_basis_and_projection():
    module = evaluator()
    from gustobot.domain.formal_ontology import load_formal_ontology
    from gustobot.infrastructure.knowledge.semantic_runtime import SemanticRuntime

    model = load_formal_ontology(
        ROOT / "gustobot/config/ontologies/recipes.ttl",
        ROOT / "gustobot/config/ontologies/recipes.shacl.ttl",
    )
    engine = SemanticRuntime(model)
    evidence = [{"source_id": "s", "quote": "白糖10g，红糖15g。"}]
    fixtures = {
        "sources": [{"id": "s", "text": "白糖10g，红糖15g。"}],
        "entities": [
            {
                "id": "r",
                "type": "RecipeVariant",
                "name": "糖水",
                "properties": {},
                "evidence": evidence,
            },
            {
                "id": "white",
                "type": "Ingredient",
                "name": "白糖",
                "properties": {},
                "evidence": evidence,
            },
            {
                "id": "red",
                "type": "Ingredient",
                "name": "红糖",
                "properties": {},
                "evidence": evidence,
            },
        ],
        "relations": [
            {
                "id": "u1",
                "type": "HAS_AUX_INGREDIENT",
                "source_id": "r",
                "target_id": "white",
                "properties": {"amount_text": "10g"},
                "evidence": evidence,
            },
            {
                "id": "u2",
                "type": "HAS_AUX_INGREDIENT",
                "source_id": "r",
                "target_id": "red",
                "properties": {"amount_text": "15g"},
                "evidence": evidence,
            },
        ],
    }
    case = module.EvaluationCase.model_validate(
        {
            "id": "derived",
            "split": "holdout",
            "truth": "controlled",
            "category": "numeric",
            "question": "糖类合计多少克？",
            "expected": {
                "statuses": ["success"],
                "object_ids": ["r"],
                "source_ids": ["s"],
                "numbers": [{"value": "25", "unit": "g"}],
            },
        }
    )
    numeric = engine.project_quantity("25g").model_dump() | {
        "property": "ingredientTotalAmount",
        "target_ref": "糖类",
        "grain": "recipe_total",
        "anchor_id": "r",
        "relation_ids": ["u1", "u2"],
        "source_ids": ["s"],
    }
    assertion = {
        "kind": "derived",
        "anchor_id": "r",
        "property": "ingredientTotalAmount",
        "grain": "recipe_total",
        "basis": ["u1", "u2"],
        "numeric_value": numeric,
    }
    observed = {
        "status": "success",
        "selected_ids": ["r"],
        "plan": {},
        "sources": [{"document_id": "s"}],
        "assertions": [assertion],
        "derivations": [],
        "message": "糖类合计25g。",
        "choices": [],
        "scope_valid": True,
        "calls": {},
    }
    assert module.grade_case(case, observed, fixtures, semantic_engine=engine)["evidence"] is True
    assertion["basis"] = ["u1"]
    assert module.grade_case(case, observed, fixtures, semantic_engine=engine)["evidence"] is False
    assertion["basis"] = ["u1", "u2"]
    numeric["projection_version"] = "stale"
    assert module.grade_case(case, observed, fixtures, semantic_engine=engine)["evidence"] is False


def test_cost_uses_only_declared_prices_and_observed_usage():
    module = evaluator()
    report = module.calculate_cost(
        {
            "analysis": {"input_tokens": 1000, "output_tokens": 20, "http_attempts": 1},
            "candidate": {"input_tokens": None, "http_attempts": 1},
        },
        {
            "analysis": {"input_usd_per_million": "2", "output_usd_per_million": "8"},
            "candidate": {"input_usd_per_million": "1"},
        },
    )
    assert report["usd_known"] == "0.00216"
    assert report["usd"] is None
    assert "candidate.input_tokens" in report["unknown"]


def test_calibration_publication_rejects_protocol_flags_and_tampered_report():
    module = evaluator()
    from gustobot.domain.linking import IndexScope

    scope = IndexScope(
        domain_id="recipes",
        ontology_version="2026-11-17.1",
        ontology_fingerprint="a" * 64,
        embedding_fingerprint="b" * 64,
        kind="entity",
    ).model_dump()
    protocol = {"provider_kind": "protocol", "publication_ready": True}
    with pytest.raises(ValueError, match="real.provider|protocol"):
        module.build_approved_calibration_report(
            protocol, protocol, scope=scope, generation_id="active"
        )
    malformed = {
        "schema_version": "knowledge-approved-calibration-v1",
        "provider_kind": "real",
        "publication_ready": True,
        "scope": scope,
        "generation_id": "active",
        "graph_revision": 1,
        "evidence": {"calibration_report": protocol, "heldout_report": protocol},
    }
    with pytest.raises(ValueError, match="real.provider|protocol|hash|calibration"):
        module.validate_approved_calibration_report(malformed)


def test_approved_calibration_bundle_roundtrips_only_when_all_embedded_evidence_matches():
    """Synthetic reports exercise artifact validation; they are never provider-quality evidence."""
    import copy
    import hashlib

    module = evaluator()
    scope = {
        "domain_id": "recipes",
        "ontology_version": "2026-11-17.1",
        "ontology_fingerprint": "a" * 64,
        "embedding_fingerprint": "b" * 64,
        "index_schema_version": INDEX_SCHEMA_VERSION,
    }
    fixtures = {
        "sources": [{"id": "s", "text": "红糖10g", "uri": "controlled:s"}],
        "entities": [
            {"id": "r-a", "name": "合同测试对象", "properties": {}},
            {"id": "r-b", "name": "合同测试同名对象", "properties": {}},
        ],
        "relations": [
            {
                "id": "use-a",
                "properties": {"amount_text": "10g"},
                "evidence": [{"source_id": "s", "quote": "红糖10g"}],
            }
        ],
    }
    condition = {
        "property": "ingredientUsageAmount",
        "target_ref": "红糖",
        "grain": "usage",
        "op": "lte",
        "value": "20",
        "unit": "g",
    }

    def candidate(identifier, kind, score):
        return {
            "id": identifier,
            "kind": kind,
            "object_type": "RecipeVariant" if kind == "entity" else "SemanticProperty",
            "domain_id": scope["domain_id"],
            "ontology_version": scope["ontology_version"],
            "ontology_fingerprint": scope["ontology_fingerprint"],
            "match_sources": ["vector"],
            "vector_score": score,
            "rank_score": score,
            "generation_id": "g",
        }

    def observation():
        return {
            "status": "success",
            "selected_ids": ["r-a"],
            "concept_candidates": [candidate("property:ingredientQuantity", "concept", 0.9)],
            "entity_candidates": [
                candidate("r-a", "entity", 0.9),
                candidate("r-b", "entity", 0.1),
            ],
            "plan": {"anchor_ids": ["r-a"], "numeric_conditions": [condition]},
            "sources": [{"document_id": "s"}],
            "assertions": [
                {
                    "fact_id": "use-a",
                    "source_ids": ["s"],
                    "properties": {"amount_text": "10g"},
                }
            ],
            "derivations": [],
            "message": "红糖10g",
            "choices": [],
            "scope_valid": True,
            "calls": {"candidate": {"http_attempts": 0}},
            "generation": {"entity": "g", "concept": "g"},
            "graph_revision": {
                "domain_id": scope["domain_id"],
                "ontology_version": scope["ontology_version"],
                "ontology_fingerprint": scope["ontology_fingerprint"],
                "state": "ready",
                "revision": 1,
            },
            "numeric_coverage": [],
            "diagnostics": [],
        }

    def case(index, split="holdout"):
        return module.EvaluationCase.model_validate(
            {
                "id": f"{split}-{index}",
                "split": split,
                "truth": "human_verified" if index == 197 else "controlled",
                "category": "numeric",
                "question": f"合成报告契约输入{split}{index}",
                "tags": ["exact"],
                "expected": {
                    "statuses": ["success"],
                    "object_ids": ["r-a"],
                    "concept_ids": ["property:ingredientQuantity"],
                    "source_ids": ["s"],
                    "conditions": [condition],
                    "numbers": [{"value": "10", "unit": "g"}],
                },
            }
        )

    def report(cases, rows):
        raw = "".join(item.model_dump_json() + "\n" for item in cases)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return {
            "schema_version": "knowledge-evaluation-v1",
            "provider_kind": "real",
            "status": "evaluated",
            "scope": scope,
            "deployment": {
                "embedding_model": "test-contract-only",
                "embedding_revision": "synthetic-no-provider-call",
            },
            "calls": {"candidate": {"http_attempts": 1}},
            "dataset_hash": digest,
            "case_count": len(cases),
            "repeats": 1,
            "cases": rows,
            "linking_mode": "on",
            "frozen_dataset": {
                "filename": "questions.jsonl",
                "questions_jsonl": raw,
                "fixtures": fixtures,
                "fixtures_hash": hashlib.sha256(module._canonical(fixtures).encode()).hexdigest(),
                "manifest": {
                    "files": {"questions.jsonl": digest},
                    "materialized_scope": {
                        key: scope[key]
                        for key in (
                            "domain_id",
                            "ontology_version",
                            "ontology_fingerprint",
                        )
                    },
                },
            },
            "metrics": {},
            "timings": {"all_requests": {"p95_ms": 10}},
        }

    calibration_cases = [case(0, "calibration")]
    calibration = report(
        calibration_cases,
        [
            {
                "id": calibration_cases[0].id,
                "repetition": 0,
                "observation": observation(),
                "error": None,
            }
        ],
    )
    calibration["calibration"] = module.calibrate_policy(
        calibration_cases,
        calibration["cases"],
        embedding_fingerprint=scope["embedding_fingerprint"],
        scope=scope,
    )
    cases = [case(index) for index in range(200)]
    rows = []
    for index, item in enumerate(cases):
        observed = observation()
        if index == 198:
            item.expected.choice_ids = ["r-a", "r-b"]
            item.expected.object_ids = ["r-a", "r-b"]
            item.expected.statuses = ["clarification"]
            item.expected.conditions = []
            item.expected.numbers = []
            item.expected.source_ids = []
            item.tags = []
            observed.update(
                status="clarification",
                selected_ids=[],
                plan={},
                sources=[],
                assertions=[],
                message="请选择",
                choices=[{"id": "r-a"}, {"id": "r-b"}],
            )
        elif index == 199:
            item.expected.object_ids = []
            item.expected.concept_ids = []
            item.expected.statuses = ["insufficient_evidence"]
            item.expected.conditions = []
            item.expected.numbers = []
            item.expected.source_ids = []
            item.tags = ["shape"]
            observed.update(
                status="insufficient_evidence",
                selected_ids=[],
                plan={},
                sources=[],
                assertions=[],
                message="无效事实已拦截",
            )
        rows.append(
            {
                "id": item.id,
                "repetition": 0,
                "truth": item.truth,
                "observation": observed,
                "checks": module.grade_case(item, observed, fixtures),
                "error": None,
            }
        )
    heldout = report(cases, rows)
    heldout["metrics"] = module._approval_metrics(cases, rows)
    heldout["deployment"]["calibration_id"] = calibration["calibration"]["calibration_id"]
    heldout["human_verification"] = {
        "dataset_hash": heldout["dataset_hash"],
        "fixtures_hash": heldout["frozen_dataset"]["fixtures_hash"],
        "reviewer": "synthetic-contract-test",
        "reviewed_at": "2026-11-17",
        "prose_and_quantitative_claims_approved": True,
    }
    lexical = copy.deepcopy(heldout)
    lexical["linking_mode"] = "off"
    shadow = copy.deepcopy(heldout)
    shadow["linking_mode"] = "shadow"
    shadow["comparison"] = module.compare_reports(lexical, shadow)
    shadow["comparison_evidence"] = lexical
    heldout["comparison"] = module.compare_reports(shadow, heldout)
    heldout["comparison_evidence"] = shadow
    bundle = module.build_approved_calibration_report(
        calibration, heldout, scope=scope | {"kind": "entity"}, generation_id="g"
    )
    assert module.validate_approved_calibration_report(bundle) == bundle
    for change in (
        {"state": "uninitialized"},
        {"domain_id": "another-domain"},
        {"ontology_version": "old"},
        {"ontology_fingerprint": "c" * 64},
    ):
        modified = copy.deepcopy(bundle)
        modified["evidence"]["heldout_report"]["cases"][0]["observation"]["graph_revision"].update(
            change
        )
        with pytest.raises(ValueError, match="revision|scope|ready"):
            module.validate_approved_calibration_report(modified)
    for field, value in (
        ("ontology_fingerprint", "c" * 64),
        ("generation_id", "wrong-generation"),
    ):
        modified = copy.deepcopy(bundle)
        modified["evidence"]["heldout_report"]["cases"][0]["observation"]["entity_candidates"][0][
            field
        ] = value
        with pytest.raises(ValueError, match="scope|generation"):
            module.validate_approved_calibration_report(modified)
    modified = copy.deepcopy(heldout)
    modified["cases"][0]["observation"]["calls"]["candidate"]["http_attempts"] = None
    modified["cases"][0]["checks"] = module.grade_case(
        cases[0], modified["cases"][0]["observation"], fixtures
    )
    modified["metrics"] = module._approval_metrics(cases, modified["cases"])
    with pytest.raises(ValueError, match="unobserved"):
        module.build_approved_calibration_report(
            calibration, modified, scope=scope | {"kind": "entity"}, generation_id="g"
        )
    wrong_status_metrics = copy.deepcopy(heldout["metrics"])
    wrong_status_metrics["expected_status"] = module._metric([False])
    assert (
        "expected_status"
        in module._release_gate(wrong_status_metrics, "real", cases, "qa")["failed"]
    )
    bundle["calibration"]["policy"]["margin"] = 0.5
    with pytest.raises(ValueError, match="hash|modified|policy"):
        module.validate_approved_calibration_report(bundle)


def test_candidate_policy_overlay_clones_runtime_and_rejects_stale_generation(
    monkeypatch,
):
    module = evaluator()
    factory = importlib.import_module("eval.knowledge.runtime_factory")
    from gustobot.application.services.entity_linking import EntityLinkingService
    from gustobot.application.services.knowledge_query import KnowledgeQueryService
    from gustobot.config.domain import get_domain_definition
    from gustobot.domain.linking import IndexPublicationStatus, IndexScope

    domain = get_domain_definition()
    model = domain.semantic_model
    assert model is not None
    scopes: dict[str, IndexScope] = {
        kind: IndexScope(
            domain_id=domain.id,
            ontology_version=domain.version,
            ontology_fingerprint=model.fingerprint,
            embedding_fingerprint="b" * 64,
            kind=kind,
        )
        for kind in CANDIDATE_KINDS
    }
    active = {"generation_id": "g"}

    def publication(scope):
        return IndexPublicationStatus(
            scope=scope,
            generation_id=active["generation_id"],
            graph_revision=1 if scope.kind == "entity" else None,
            status="ready",
        )

    original_linker = EntityLinkingService(
        domain,
        graph_store=object(),
        candidate_store=object(),
        embedder=object(),
        scopes=scopes,
        publication_provider=publication,
        mode="on",
    )
    original_query = KnowledgeQueryService(
        domain,
        graph_store=object(),
        documents=object(),
        model=None,
        linker=original_linker,
        telemetry_instrumented=True,
    )
    runtime = module.EvaluationRuntime(
        query_service=original_query,
        linker=original_linker,
        provider_kind="protocol",
        scope=scopes["entity"].model_dump(),
        deployment={"label": "isolated-contract-test"},
    )
    monkeypatch.setattr(module, "create_runtime", lambda **kwargs: runtime)
    candidate = {
        "scope": scopes["entity"].model_dump(),
        "generation_id": "g",
        "graph_revision": 1,
        "calibration_id": "candidate-fit",
        "policy": {"min_cosine": 0.8, "margin": 0.05},
    }
    cloned = factory.create_runtime(
        scope=domain.id, linking_mode="on", candidate_calibration=candidate
    )
    assert cloned.query_service is not original_query and cloned.linker is not original_linker
    assert original_query.linker is original_linker
    assert cloned.query_service.telemetry_instrumented is True
    assert original_linker.publication_provider(scopes["entity"]).calibration_id is None
    assert cloned.linker.publication_provider(scopes["entity"]).calibration_id == "candidate-fit"
    assert cloned.linker.publication_provider(scopes["concept"]).calibration_id is None
    active["generation_id"] = "new-g"
    with pytest.raises(ValueError, match="stale"):
        cloned.linker.publication_provider(scopes["entity"])


def test_baseline_comparison_rejects_protocol_as_real_provider_baseline():
    module = evaluator()
    base = {
        "dataset_hash": "f" * 64,
        "scope": {
            "domain_id": "recipes",
            "ontology_version": "test",
            "ontology_fingerprint": "a" * 64,
        },
        "provider_kind": "protocol",
        "linking_mode": "off",
        "cases": [],
        "timings": {"all_requests": {"p95_ms": 10}},
        "metrics": {},
    }
    with pytest.raises(ValueError, match="provider|protocol"):
        module.compare_reports(base, base | {"provider_kind": "real", "linking_mode": "on"})


def test_materialization_binds_ids_and_scope_without_changing_frozen_input(tmp_path):
    module = evaluator()
    from gustobot.domain.formal_ontology import load_formal_ontology

    model = load_formal_ontology(
        ROOT / "gustobot/config/ontologies/recipes.ttl",
        ROOT / "gustobot/config/ontologies/recipes.shacl.ttl",
    )
    original = module.load_dataset(DATASET)
    case = original.cases[0]
    source_id = case.expected.source_ids[0]
    selected = tmp_path / "original"
    selected.mkdir()
    question_path = selected / "questions.jsonl"
    question_path.write_text(case.model_dump_json() + "\n", encoding="utf-8")
    graph = {
        "sources": [item for item in original.fixtures["sources"] if item["id"] == source_id],
        "entities": [
            item
            for item in original.fixtures["entities"]
            if any(ref["source_id"] == source_id for ref in item["evidence"])
        ],
        "relations": [
            item
            for item in original.fixtures["relations"]
            if any(ref["source_id"] == source_id for ref in item["evidence"])
        ],
    }
    (selected / "controlled_sources.json").write_text(
        json.dumps(graph, ensure_ascii=False), encoding="utf-8"
    )
    before = question_path.read_bytes()
    output = tmp_path / "materialized"
    module.materialize_dataset(question_path, output, model=model)
    bound = module.load_dataset(output / "questions.jsonl")
    assert question_path.read_bytes() == before
    assert bound.manifest["materialized_scope"]["ontology_fingerprint"] == model.fingerprint
    assert bound.manifest["materialized_scope"]["ontology_version"] == model.version
    assert bound.cases[0].expected.object_ids != case.expected.object_ids
    assert set(bound.cases[0].expected.object_ids) <= {
        item["id"] for item in bound.fixtures["entities"]
    }
    assert bound.cases[0].question == case.question


def test_full_fixture_cli_materialization_requires_no_providers(tmp_path):
    module = evaluator()

    def prohibited(**kwargs):
        raise AssertionError("materialization initialized a provider runtime")

    assert (
        module.main(
            [
                "--mode",
                "protocol",
                "--dataset",
                str(DATASET),
                "--output",
                str(tmp_path),
                "--scope",
                "recipes",
                "--materialize",
            ],
            runtime_factory=prohibited,
        )
        == 0
    )
    bound = module.load_dataset(tmp_path / "questions.jsonl")
    assert len(bound.cases) >= 276
    assert len(bound.fixtures["sources"]) == 56
    assert bound.manifest["materialized_scope"]["ontology_version"] == "2026-11-17.1"
    assert len(bound.manifest["materialized_scope"]["ontology_fingerprint"]) == 64


@pytest.mark.asyncio
async def test_retrieval_metrics_exclude_unverified_truth_and_unknown_attempts_stay_unknown():
    module = evaluator()
    from gustobot.domain.linking import CatalogRecord, LinkedCandidate, LinkingContext

    def candidate(kind, reference):
        return LinkedCandidate(
            record=CatalogRecord.create(
                domain_id="recipes",
                ontology_version="test",
                ontology_fingerprint="a" * 64,
                kind=kind,
                ref_kind="entity" if kind == "entity" else "property",
                ref_id=reference,
                object_type="RecipeVariant" if kind == "entity" else "SemanticProperty",
                label=reference,
                graph_revision=1 if kind == "entity" else None,
            ),
            match_sources=["vector"],
            vector_score=0.9,
            rank_score=1.0,
            generation_id="generation",
        )

    invocations = []

    class Linker:
        async def prepare(self, question, **kwargs):
            invocations.append(question)
            return LinkingContext(
                question=question,
                mode="shadow",
                concepts=[candidate("concept", "property:ingredientQuantity")],
                entities=[candidate("entity", "r-a")],
                timings={"total_ms": 20.0, "shadow_entity_candidates": 3.0},
            )

    runtime = module.EvaluationRuntime(
        query_service=None,
        linker=Linker(),
        provider_kind="protocol",
        deployment={"label": "protocol-linker-boundary"},
        scope={
            "domain_id": "recipes",
            "ontology_version": "test",
            "ontology_fingerprint": "a" * 64,
            "embedding_fingerprint": "b" * 64,
        },
    )
    base = {
        "split": "holdout",
        "category": "paraphrase",
        "tags": [],
        "expected": {
            "statuses": ["ready"],
            "concept_ids": ["property:ingredientQuantity"],
            "object_ids": ["r-a"],
        },
    }
    cases = [
        module.EvaluationCase.model_validate(
            base | {"id": "verified", "truth": "controlled", "question": "受控用量"}
        ),
        module.EvaluationCase.model_validate(
            base
            | {
                "id": "unverified",
                "truth": "manual_unverified",
                "question": "真实来源未核验",
            }
        ),
    ]
    report = await module.run_evaluation(
        cases,
        runtime=runtime,
        mode="retrieval",
        linking_mode="shadow",
        fixtures={"sources": [], "entities": [], "relations": []},
        dataset_hash="f" * 64,
        repeats=2,
    )
    assert len(invocations) == 4
    assert report["metrics"]["concept_recall_at_5"]["total"] == 1
    assert report["metrics"]["entity_recall_at_10"]["value"] == 1.0
    assert report["calls"]["document"]["http_attempts"] is None
    assert report["timings"]["stages"]["total_ms"]["p95_ms"] == 20.0
    assert "shadow_entity_candidates" not in report["timings"]["stages"]
    calibration_cases = [case.model_copy(update={"split": "calibration"}) for case in cases[:1]]
    policy = module.calibrate_policy(
        calibration_cases, report["cases"][:1], embedding_fingerprint="b" * 64
    )
    assert policy["policy"]["min_cosine"] == 0.9
    assert policy["embedding_fingerprint"] == "b" * 64
    assert len(policy["calibration_id"]) == 64


def test_report_comparison_matches_each_repetition():
    module = evaluator()
    cases = [
        {
            "id": "same-case",
            "repetition": index,
            "observation": {
                "status": "success",
                "selected_ids": [f"r-{index}"],
                "plan": {},
            },
        }
        for index in range(2)
    ]
    baseline = {
        "provider_kind": "protocol",
        "dataset_hash": "b" * 64,
        "scope": {
            "domain_id": "recipes",
            "ontology_version": "test",
            "ontology_fingerprint": "a" * 64,
        },
        "cases": cases,
        "linking_mode": "off",
        "timings": {"all_requests": {"p95_ms": 10}},
        "metrics": {},
    }
    current = baseline | {"linking_mode": "shadow"}
    assert module.compare_reports(baseline, current)["structural_changes"] == []


@pytest.mark.asyncio
async def test_expected_backend_failure_is_recorded_with_latency_and_failure_kind():
    module = evaluator()
    import httpx
    from openai import APITimeoutError

    class FailedLinker:
        async def prepare(self, *args, **kwargs):
            raise APITimeoutError(
                request=httpx.Request("POST", "https://provider.invalid/embeddings")
            )

    runtime = module.EvaluationRuntime(
        query_service=None,
        linker=FailedLinker(),
        provider_kind="protocol",
        deployment={"label": "timeout-protocol"},
        scope={
            "domain_id": "recipes",
            "ontology_version": "test",
            "ontology_fingerprint": "a" * 64,
            "embedding_fingerprint": "b" * 64,
        },
        case_context=lambda fault: module._no_fault(),
    )
    case = module.EvaluationCase.model_validate(
        {
            "id": "timeout",
            "split": "holdout",
            "truth": "controlled",
            "category": "service_failure",
            "question": "服务不可用时应明确失败",
            "fault": "embedding_timeout",
            "expected": {"statuses": ["unavailable"], "errors": ["APITimeoutError"]},
        }
    )
    report = await module.run_evaluation(
        [case],
        runtime=runtime,
        mode="retrieval",
        linking_mode="shadow",
        fixtures={"sources": [], "entities": [], "relations": []},
        dataset_hash="f" * 64,
    )
    assert report["cases"][0]["error"]["type"] == "APITimeoutError"
    assert report["cases"][0]["outcome_class"] == "service_unavailable"
    assert report["cases"][0]["elapsed_ms"] >= 0
    assert report["metrics"]["service_failure_handling"]["value"] == 1.0
    assert report["metrics"]["unexpected_case_errors"] == 0
    assert report["timings"]["all_requests"]["samples"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,concurrency", [("protocol", 1), ("qa", 1), ("latency", 5), ("latency", 20)]
)
async def test_protocol_run_drives_actual_query_service_and_marks_real_gates_pending(
    tmp_path,
    mode,
    concurrency,
):
    module = evaluator()
    from gustobot.application.services.knowledge_query import KnowledgeQueryService
    from gustobot.config.domain import get_domain_definition
    from gustobot.domain.knowledge import KnowledgeGraph
    from gustobot.infrastructure.knowledge.graph_store import (
        EntityCandidate,
        FactResult,
    )

    text = "评测糖水使用红糖10g，耗时10分钟。"
    evidence = [{"source_id": "source-a", "quote": text}]
    graph = KnowledgeGraph.model_validate(
        {
            "sources": [{"id": "source-a", "text": text, "uri": "controlled:source-a"}],
            "entities": [
                {
                    "id": "r-a",
                    "type": "RecipeVariant",
                    "name": "评测糖水",
                    "properties": {
                        "cook_time": "10分钟",
                        "source_record_id": "controlled-a",
                    },
                    "evidence": evidence,
                },
                {
                    "id": "sugar",
                    "type": "Ingredient",
                    "name": "红糖",
                    "evidence": evidence,
                },
            ],
            "relations": [
                {
                    "id": "use-a",
                    "source_id": "r-a",
                    "target_id": "sugar",
                    "type": "HAS_AUX_INGREDIENT",
                    "properties": {"amount_text": "10g"},
                    "evidence": evidence,
                }
            ],
        }
    )
    domain = get_domain_definition()
    model = domain.semantic_model
    assert model is not None

    class ControlledGraph:
        async def resolve_entities(self, name, entity_types=None, limit=10):
            return [EntityCandidate(id="r-a", type="RecipeVariant", name="评测糖水")]

        async def query(self, request):
            return FactResult(
                **graph.model_dump(),
                total=1,
                truncated=False,
                ontology_version=domain.version,
            )

    class Documents:
        async def search(self, *args, **kwargs):
            return []

    service = KnowledgeQueryService(
        domain, graph_store=ControlledGraph(), documents=Documents(), model=None
    )
    runtime = module.EvaluationRuntime(
        query_service=service,
        provider_kind="protocol",
        scope={
            "domain_id": domain.id,
            "ontology_version": domain.version,
            "ontology_fingerprint": model.fingerprint,
            "embedding_fingerprint": "b" * 64,
        },
        deployment={"label": "injected-controlled-protocol"},
        telemetry_snapshot=lambda: {"candidate": {"http_attempts": 0}},
    )
    case = module.EvaluationCase.model_validate(
        {
            "id": "protocol-public-answer",
            "split": "holdout",
            "truth": "controlled",
            "category": "exact",
            "question": "评测糖水用多少红糖？",
            "tags": ["exact"],
            "expected": {
                "concept_ids": [],
                "object_ids": ["r-a"],
                "source_ids": ["source-a"],
                "statuses": ["success"],
                "numbers": [{"value": "10", "unit": "g"}],
            },
        }
    )
    report = await module.run_evaluation(
        [case],
        runtime=runtime,
        mode=mode,
        linking_mode="off",
        fixtures=graph.model_dump(),
        dataset_hash="f" * 64,
        concurrency=concurrency,
        repeats=2 if concurrency > 1 else 1,
    )
    assert report["cases"][0]["error"] is None, report["cases"][0]["error"]
    assert report["cases"][0]["observation"]["message"]
    assert report["metrics"]["correct_binding"]["value"] == 1.0
    assert report["metrics"]["numeric_correctness"]["value"] == 1.0
    assert report["metrics"]["correct_binding"]["total"] == 1
    assert report["timings"]["all_requests"]["samples"] == (2 if concurrency > 1 else 1)
    assert report["http_attribution"] == ("per_case" if concurrency == 1 else "aggregate_only")
    assert report["calls"]["candidate"]["http_attempts"] == 0
    assert report["release_gate"]["accepted"] is False
    assert "real_provider" in report["release_gate"]["pending"]
    custom = tmp_path / "protocol.jsonl"
    custom.write_text(case.model_dump_json() + "\n", encoding="utf-8")
    (tmp_path / "controlled_sources.json").write_text(graph.model_dump_json(), encoding="utf-8")
    closed = []
    runtime.cleanup = lambda: closed.append("runtime")
    from argparse import Namespace

    args = Namespace(
        dataset=custom,
        mode="protocol",
        output=tmp_path / "report",
        scope="recipes",
        linking_mode="off",
        dry_run=False,
        materialize=False,
        calibrate=False,
        runtime_factory=None,
        concurrency=1,
        repeats=1,
        compare_baseline=None,
        prices=None,
        build_telemetry=None,
        approve_calibration=None,
        human_verification=None,
        candidate_calibration_report=None,
    )
    assert await module.execute(args, runtime_factory=lambda **kwargs: runtime) == 0
    assert closed == ["runtime"]
    persisted = json.loads((args.output / "report.json").read_text(encoding="utf-8"))
    assert persisted["provider_kind"] == "protocol" and persisted["cases"][0]["error"] is None

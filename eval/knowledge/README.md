# Knowledge evaluation

This is an executable evaluation harness and a frozen **controlled** dataset. It
does not contain approved real-source business truth. No real-provider quality,
latency, or business acceptance is claimed by the committed fixtures or their
protocol tests.

`questions.jsonl` contains 276 distinct holdout questions. `calibration.jsonl`
contains 28 separate questions, including four negative cases. The two source
files contain 56 complete, authored snapshots with native graph facts and exact
source quotations. Cases cover names, approved aliases, paraphrases, typos,
same-name variants, ingredient scope, amounts, ranges, repeated use, unknown and
incompatible units, duration grain, documents, combined evidence, scope attacks,
service failures, missing facts, and invalid-fact leakage. The fixtures describe
test assertions, not recommended recipes. Their IDs initially refer to logical
fixture objects; they must be materialized before evaluating a database runtime.

The manifest pins file SHA-256 hashes. Changes to the frozen questions, expected
outcomes, sources, or manifest create a new dataset revision. Do not tune a policy
or prompt against the holdout answers. Calibration refuses holdout input.

## Provider-free checks

These commands do not initialize application clients or load `.env`:

```powershell
.venv\Scripts\python.exe scripts/evaluate_knowledge.py --mode protocol --scope recipes --dataset eval/knowledge/questions.jsonl --output .superpowers/sdd/2026-11-16-knowledge-completion/task8-dryrun --dry-run
.venv\Scripts\python.exe scripts/evaluate_knowledge.py --mode protocol --scope recipes --dataset eval/knowledge/questions.jsonl --output .superpowers/sdd/2026-11-16-knowledge-completion/task8-materialized --materialize
```

Materialization loads the local formal model, checks the required model version,
uses the production identity compiler, and runs the complete SHACL input checks.
It writes a separate bundle with native entity/relation IDs, actual concept IDs,
the actual model fingerprint, a fresh manifest, and an identity map. It preserves
the original source and question files and performs no database writes. A runtime
whose model fingerprint differs from the materialized bundle is rejected.

The ordinary test command uses the repository's safe `.env`-disabling runner:

```powershell
.venv\Scripts\python.exe -X utf8 scripts/run_backend_tests.py tests/test_knowledge_evaluation.py -q --tb=short
```

The tests exercise the actual public `KnowledgeQueryService.answer` method with
injected graph/provider boundaries, retrieval traces, deterministic grading,
materialization, cost calculations, and calibration artifacts. Contract tests
that synthesize reports exercise validator behavior; they are not actual provider
measurements.

## Runtime modes

All modes require `--mode`, `--scope`, `--dataset`, and `--output`.

| Mode | Execution |
| --- | --- |
| `protocol` | Calls the public query service using the supplied runtime. Reports the runtime's actual provider kind; choosing this mode never promotes fixtures to real-provider evidence. |
| `retrieval` | Calls the actual linker's `prepare` once and records ranked concepts/entities, generation, revision, scores, provenance, calls, and timings. |
| `qa` | Calls `KnowledgeQueryService.answer` once and grades the selected objects, plan, conditions, numeric coverage, evidence, and answer. It consumes answer candidate metadata without another linker/model call. |
| `latency` | Uses the same public-answer path with `--concurrency 1`, `5`, or `20` and `--repeats N`. It includes failures in elapsed-time samples. |

The default factory uses application runtime accessors and verifies that
`--linking-mode off|shadow|on` matches explicitly configured runtime settings.
Only actual non-dry runs initialize application clients. Configure an isolated
test environment explicitly; the harness does not upload fixtures or point a
database at the controlled data on the operator's behalf. Database fixture import
and generation publication use their existing, separately authorized tooling.

To inject a provider/runtime, pass `--runtime-factory package.module:callable`.
The callable receives `scope` (domain ID) and `linking_mode`, and returns
`scripts.evaluate_knowledge.EvaluationRuntime`. Its fields are:

- `query_service`: an actual `KnowledgeQueryService`, required for QA/protocol/latency.
- `linker`: the linker used for retrieval evaluation.
- `scope`: domain, model version/fingerprint, embedding fingerprint, and schema version.
- `deployment`: explicit provider/deployment/model/revision information without keys.
- `provider_kind`: `protocol` or `real`; keep protocol and real baselines separate.
- `telemetry_snapshot`: optional monotonic counters by analysis, generation,
  candidate, document, build, and rerank purpose. Missing counts stay `null`.
- `cleanup`: optional owned-runtime cleanup, called even after failed runs.
- `case_context`: optional asynchronous context manager accepting a fault name.
  Fault cases fail visibly when the factory has no injection capability.

Faults are `embedding_timeout`, `milvus_unavailable`, `graph_unavailable`,
`revision_changed`, `missing_calibration`, `graph_uninitialized`,
`unpublished_source`, `invalid_negative_quantity`, and
`invalid_two_recipe_owners`. Fault injection is restricted to an isolated runtime.
It must not modify production data or active publication pointers.

## Metrics and evidence

Every completed run writes `report.json`, `cases.jsonl`, and `failures.jsonl`.
Reports contain per-case ranked candidates, actual plan/object IDs, evidence and
derivations, generation/revision, diagnostics, timing, known calls, failures, and
dataset/model/deployment provenance. They include the frozen evaluation inputs
for artifact verification; use approved, nonsensitive local inputs and do not
commit reports containing private source material.

Metrics include concept Recall@5, entity Recall@10, binding, ambiguity,
scope/version preservation, exact-path preservation, condition retention,
evidence alignment, invalid-shape blocking, and exact numeric results. Missing
candidate telemetry produces unobserved recall cases, not successful recall.
Human-unverified cases appear in diagnostics but do not count as correct gold.
Wilson 95% intervals are descriptive; repetitions are grouped by question so
rerunning the same question does not inflate the sample size. Latency samples
still include every repetition. Reports distinguish initial, steady, failed, and
per-category samples, with p50/p95/p99. These are measured wall times, not a
guarantee of the performance targets.

The grader checks structured assertions against fixture facts and source IDs,
required exact numbers, numeric coverage, conditions, and forbidden identities.
It normalizes native IDs to names when comparing numeric targets and preserves
property/grain distinctions. It cannot establish that every free-form prose
claim is entailed. Real-source prose and quantitative-claim review requires an
explicit human record; an answer-model judge is never the sole proof.

Failure classification is deterministic triage: functional defect, retrieval
defect, model-understanding error, data not recorded, source incomplete, or
service unavailable. The trace remains available for human root-cause review.

Optional `--prices prices.json` computes exact USD estimates from declared rates
and observed usage. Supported rates per purpose are `input_usd_per_million`,
`output_usd_per_million`, and `http_attempt_usd`. Unknown tokens or prices remain
unknown. No current provider prices are bundled. `--build-telemetry file.json`
adds separately measured `full_build` and `single_update` costs; it never starts
a build. The JSON contains `scope` plus each operation's `calls` mapping. Cache
hits, input size, and actual attempts can be included in the counter snapshots.

## Calibration and baseline comparison

Run the old lexical baseline with `--linking-mode off`, then shadow with
`--compare-baseline <off/report.json>`, and finally on against the shadow report.
Each comparison requires matching frozen cases/repetitions and formal scope.
An off report may lack an embedding fingerprint; two declared embedding spaces
must match. Protocol runs cannot stand in for real-provider baselines.

Fit a policy using a materialized **calibration** file:

```powershell
.venv\Scripts\python.exe scripts/evaluate_knowledge.py --mode retrieval --scope recipes --linking-mode shadow --dataset <materialized>/calibration.jsonl --output <calibration-run> --calibrate --calibration-kind entity
```

The fit uses measured correct/incorrect top candidates and cosine/margin values,
records the dataset and embedding space, and emits a content-derived calibration
ID. Its status always says that heldout validation is required; it is not a
publishable artifact. Fit concepts separately with `--calibration-kind concept`.

To test that candidate policy before publishing it, use the provided read-only
runtime overlay **in an explicitly isolated evaluation environment**:

```powershell
.venv\Scripts\python.exe scripts/evaluate_knowledge.py --mode qa --scope recipes --linking-mode on --dataset <materialized>/questions.jsonl --output <heldout-run> --runtime-factory eval.knowledge.runtime_factory:create_runtime --candidate-calibration-report <calibration-run>/report.json --compare-baseline <shadow-run>/report.json --human-verification <human-review.json>
```

This factory clones the linker/query service and wraps publication reads with the
candidate policy for its exact scope/generation/revision. It leaves persisted
publication metadata unchanged and rejects stale generations. The run records
the applied candidate calibration ID. This avoids requiring a production policy
change in order to validate the policy.

The human-review JSON names the reviewer/date, exact `dataset_hash` and
`fixtures_hash`, and sets `prose_and_quantitative_claims_approved: true` only
after that review happened. Add approved real-source cases in a separate frozen
dataset revision with `truth: human_verified`; retain source snapshots, exact
gold IDs/numbers/conditions, and review provenance. Keep unverified material
marked `manual_unverified`. The shipped manifest explicitly records that no
approved real-source cases have yet been supplied.

After actual heldout gates, provenance, human review, and the real off/shadow/on
comparison pass, export a publication artifact without opening a provider:

```powershell
.venv\Scripts\python.exe scripts/evaluate_knowledge.py --mode qa --scope recipes --output <approval-output> --approve-calibration <calibration-run>/report.json --heldout-report <heldout-run>/report.json --kind entity --generation <exact-generation-id>
```

The exporter rechecks frozen input hashes, model/embedding scope, generation and
revision, separate calibration/holdout splits, independently derived checks and
aggregate metrics, actual provider attempts, applied policy, and human evidence.
It requires at least 200 heldout questions including approved real-source truth.
It embeds the source reports and writes `approved-calibration.json`. The builder's
`calibrate` operation validates that bundle again and uses its exact file SHA-256
as the attached calibration ID, with CAS protection of the active generation.
Changing a flag or copying a calibration score cannot create an accepted bundle.

The shipped controlled corpus alone cannot produce an approved artifact. Real
provider credentials, approved real-source truth, actual retrieval/QA runs,
performance measurements, and human business acceptance remain external gates.

A separate [real-source review draft](../real-source-review/README.md) provides
240 pending questions from 48 existing recipe records, with original excerpts,
native IDs and draft expectations. Every case remains `manual_unverified` until
a person checks the source and publishes a new reviewed dataset revision.

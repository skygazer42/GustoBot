# Python guidelines audit and correction plan

## Scope and constraints

- Review all 304 project Python files discovered with `rg --files --hidden --no-ignore`, including scripts, tests, package initializers and the existing untracked test. Exclude Git internals, installed dependencies, virtual environments, bytecode caches and generated operational helpers under `.omx` belonging to other tasks.
- Apply `C:/Users/luke/.codex/skills/python-coding-guidelines/SKILL.md` and its relevant rule chapters. Read each assigned file completely and inspect actual callers before changing contracts.
- Preserve existing uncommitted work, business capabilities, public API behavior, supported Python version and existing framework choices. Do not add dependencies, commit, deploy or run database migrations.
- Per the user's latest instruction, use two native subagents with disjoint file ownership. One owns API/persistence, knowledge/ingestion and scripts/tests; the other owns orchestration and RAG components/workflows. Retain the six original inventory groups for exact coverage tracking.

## Execution and cleanup order

1. Record the full inventory, initial file hashes and Git status; allocate every file to exactly one lane.
2. Run existing safe tests and available static checks to establish the baseline. Each lane documents its concrete cleanup plan before edits, and establishes regression coverage before changing behavior-sensitive code.
3. Review every file for applicable mandatory rules, readability, actual data contracts, async/resource lifecycle, exception visibility, persistence boundaries, imports and test quality.
4. Remove proven dead or duplicate code first, then simplify unnecessary wrappers and fix naming, None/zero handling, exception/resource and boundary issues. Preserve real framework protocols and public exports. Do not force module mergers or formatting-only changes.
5. Apply minimal fixes within each lane's ownership. Add targeted behavioral regression tests for uncovered, meaningful risks; record necessary exceptions to recommendations.
6. Run targeted tests after fixes. Reconcile cross-lane concerns and independently inspect the combined diff.
7. Verify syntax for every Python file, relevant lint/type/static checks supported by installed tools, and the safe automated test suite. Distinguish pre-existing failures and infrastructure-dependent checks from regressions.
8. Reconcile audit reports against the complete inventory, including any new Python files. Deliver an exact coverage count, changed-file list, verified results and concrete remaining limitations.

## Review evidence

Inventory and lane assignments live under `.omx/state/python-guidelines-audit/`. Each lane writes a per-file report under `docs/audits/python/2026-11-15/`, with path, review outcome, relevant rule findings, fixes or reasons to retain the implementation, and validation results. The lead produces the coverage summary only after every inventory entry has a completed review record.

## Lead integration fixes

- Own `gustobot/application/agents/kg_sub_graph/agentic_rag_agents/agent.py` while the RAG agent continues its other files. Its Studio workflow import names an absent external package, and its vector retriever is never imported. Trace both objects to their existing in-repository definition modules, establish an offline entrypoint assembly regression first, then correct the imports and the missing URI configuration fallback. Preserve the Studio `graph` export and the existing visualization-capable workflow; do not contact live Neo4j or model services.
- After both agents finish, reconcile Python 3.9 annotation compatibility using existing `typing` forms, without changing overloaded LangChain pipeline operators or adding future-annotation imports. Include these final changes and any new regression files in the audit evidence and full validation.

## Verification boundaries

Inspect tests before execution. Do not invoke CLI entrypoints that ingest data or contact production services as a substitute for tests. Mock external services for new unit coverage; do not hide functional failures with blanket skips or weakened assertions. Run existing documented tooling without adding a new toolchain or requiring unrelated style changes.

## Python 3.9 dataclass compatibility follow-up

- Remove unsupported slots optimization on simple dataclasses without changing frozen/data fields. For five keyword-only state classes, retain dataclass field metadata and keyword-only required arguments using explicit constructors with init=False, preserving defaults and fresh mutable values. Establish import/constructor regression coverage against the Python 3.9 decorator keyword boundary before edits, then exercise state construction and LangGraph assembly. This does not substitute for an unavailable actual Python 3.9 interpreter run.

- Final resource review found that KnowledgeService allocates its embedding client before a fallible vector-store constructor. Add a failing construction regression, initialize pure reranker configuration before resource allocation, and close the owned embedder on store-construction failure while preserving the original exception. Check remaining Loguru calls using printf-style arguments and correct only confirmed framework mismatches.

## Completed review and validation

- Reviewed all 304 original project Python files using two subagents, with parent integration review; corrected 131 originals and retained 173 unchanged. Eight added regression modules were also reviewed, giving 312 final records.
- Safe offline suite: 100 passed, 2 skipped. Compilation/Python 3.9 grammar and Ruff F/E9 pass for all 312 files; Black passes for all 139 changed/new files.
- Whole-repository Black/Flake8 and Mypy remain non-passing; no claim of a clean typecheck or actual Python 3.9 runtime execution. Standard Mypy is blocked at 23 errors; the supplemental skipped-import run reports 174 errors in 53 files. Eight medium/high Bandit findings retain documented operational/trusted-SQL boundaries.
- Complete per-file reports, changed-file list, current fingerprints, coverage reconciliation and actual validation limits are delivered under `docs/audits/python/2026-11-15/`. No dependencies installed, production-service writes, migrations, commits or pushes.

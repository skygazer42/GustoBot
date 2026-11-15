# Frontend guidelines audit and correction plan

## Scope and baseline

- Request: individually inspect every first-party frontend file and correct actual violations using `frontend-coding-guidelines` 1.6.0.
- Root: `web/`; Vue 3 with TypeScript, Vite 5, Axios, scoped SCSS and one global SCSS file. Keep the existing two-space, double-quote, semicolon style (FMT-001).
- No dependency additions, formatter migrations, automatic commits, deployment, or unrelated backend/data changes.
- Preserve existing user changes. `node_modules`, `dist`, logs, caches and private local environment values are not authored frontend source.
- Initial `npm run lint` (the existing vue-tsc typecheck) passed on 2026-11-15.

## Complete review inventory

1. `web/src/components/ChatWidget.vue`
2. `web/src/components/LandingPage.vue`
3. `web/src/App.vue`
4. `web/src/main.ts`
5. `web/src/styles/global.scss`
6. `web/index.html`
7. `web/vite.config.ts`
8. `web/tsconfig.json`
9. `web/tsconfig.node.json`
10. `web/package.json`
11. `web/package-lock.json` (generated dependency metadata: inspect consistency, do not hand-edit)
12. `web/src/components/system-report.txt` (non-executable text: inspect references and applicability)

## Execution and ownership

The latest user instruction requests one agent. All delegated agents stopped before editing (their launches returned rate-limit failures). The primary agent owns all inspection, corrections, evidence and verification.

1. Each owner reads the applicable skill rules and pinned original excerpts before recommending or changing patterns.
2. Establish relevant existing behavior with tests before substantive behavioral corrections; low-impact semantic/style corrections use the existing compile checks and targeted interaction checks.
3. Audit each assigned file in full, including script, template and scoped styles where present. Record both corrected and unchanged files with reasons. No mechanical rewrite merely to create a diff.
4. Prioritize real input, state, request, resource-lifecycle, type and HTML contracts. Reuse existing patterns and delete unnecessary work before adding abstractions.
5. Record findings with rule, level, location, impact and minimal fix. Maintain per-identifier naming records for introduced/renamed declarations.
6. After final edits, bind schemaVersion 2 writing evidence to final line ranges and SHA-256 hashes; verify using the skill's registry and identifier tools.
7. Run the existing frontend typecheck and production build, targeted regression tests, configuration/static checks, and available browser interactions. Distinguish mocked API coverage from live backend verification.

## Completion criteria

Every inventory item has an explicit review result; justified corrections are integrated; relevant tests and available existing checks pass; evidence and remaining verification limits are recorded in a final audit report under this task's `.omx` directory.

## Expanded writing pass after the whole-web request

The user explicitly includes all of `web/`, with one owner. Review every authored
file again for writing and maintainability, beyond the initial correctness fixes.
The existing 15 chat regressions pass before these edits.

1. ChatWidget: give the state object an explicit interface; remove its one-use
   factory, empty-array assertion and six pass-through computed aliases. Bind the
   template to the actual owner, derive only shared busy state and placeholder,
   and name upload/chat response values and template loop variables by purpose.
   Preserve all request identity, draft, upload and focus behavior.
2. LandingPage: remove the event-forwarding wrapper, keep the typed existing
   event, use heading elements for section titles and code elements for literal
   API paths. Preserve layout, content and event names.
3. App/global styles: remove the layout-only root wrapper and move the shared
   viewport minimum to body; inherit typography in native form controls.
4. HTML: align the document title with the actual Chinese application.
5. Vite: load only the VITE_ variables used by the config and share the existing
   proxy target; retain port, host and both proxy routes.
6. Type/package configs: persist the already-passing unused/fallthrough checks,
   check Vite config with the existing compiler, and require typecheck before
   production builds. Remove unneeded composite emission metadata; no package
   or dependency-tree changes. Regenerate the lockfile with npm only as needed.
7. Review the sample report against actual endpoints and describe its fixture
   purpose. Keep the already-minimal main.ts bootstrap unless a real issue is
   found; source coverage does not require a cosmetic rewrite of valid lines.
8. Re-run regressions, package checks/build, real keyboard/layout checks where
   affected, and regenerate identifier, rule, file and hash evidence.

The removed computed aliases were legal Vue, not duplicate writable state or
framework violations. Their removal is a project simplification under FUN-001
and STA-001. All configuration choices remain project adaptations, not invented
universal requirements.

## Strict follow-up after the user's conformance request

Continue solo. Recheck all 137 indexed rules for applicability to all 12 authored
frontend files, including the template, script and style blocks. Record concrete
reasons for inapplicable rules and justified project choices instead of treating
React, Redux, classes or Tailwind as required additions to this Vue/SCSS app.

1. Run the existing 15 behavior regressions before editing. Add a regression for
   unknown backend labels that collide with Object.prototype keys, observe its
   failure, then restrict the label lookup to owned mapping entries (OBJ-003).
2. Apply the selected recommendations consistently in ChatWidget: name the
   per-instance API configuration apiBaseUrl (NAM-006), use braced control blocks
   (JS-003), and express string emptiness and source counts explicitly (JS-002).
   These readability edits preserve behavior; existing single-line guards are
   not claimed to be a runtime defect or banned by upstream Airbnb guidance.
3. Finish a rule-by-rule disposition matrix, refresh identifier reviews and final
   code/hash evidence, then rerun regressions, type/lint/build and project checks.
   The current follow-up does not change layout or focus/keyboard interactions;
   prior browser evidence remains identified as prior verification.

A final boundary review also reproduced a rendering failure for legal JSON with
a non-scalar source field containing an own toString=null property. Before
editing, the new 17th regression fails with TypeError. Restrict source display
conversion to string/number/boolean values through one local pure helper shared
by label and URL formatting; retain valid fallback text and document ID 0. Do
not reject arbitrary extra source metadata or introduce a generic sanitizer.
Refresh scalar-field evidence, declaration meanings and all final checks.

## Goal completion audit

Treat the conformance claim as unproven until the current tree is checked again.
The prior inventory compared Git-tracked files only. Enumerate the physical web
tree as well, skipping dependency/build directories and generated logs/metadata;
fail verification if an authored file is missing from the reviewed inventory.
Record the existing ignored .env.local separately as local configuration, read
it only through the established Vite environment loader, and verify the values
actually consumed by the application without printing or copying private values.
Recheck 137-rule coverage and retained-choice reasons against the current source,
run final behavior/type/build/evidence checks, and save requirement-by-requirement
completion evidence. No additional product rewrite is planned without a concrete
applicable guideline violation.

## Writing-first pass after the clarified objective

The user prioritizes standard frontend writing, with only small defensive checks.
Keep one owner and the existing stack/style. Stop additional boundary-test or
browser expansion; the existing 17 regressions protect behavior during this pass.

1. Recheck every authored file by naming, declarations/types, function contracts,
   component/state ownership, template/HTML structure and SCSS scope/format.
2. ChatWidget: move existing API response checks and result mapping into two
   local, explicitly typed parse functions, so upload/chat commands show their
   business steps directly. Do not add validation policies, packages or layers.
3. Name the returned upload and chat results and message text/link parts by their
   actual contracts. Declare command return types consistently. Rename the
   source URL reader and window key handler to describe result/target clearly.
4. Move the fixed source-label dictionary beside the component's static values
   and make its intended read-only use explicit; avoid recreating it per label.
5. Apply the selected Vue template attribute/line layout consistently. Keep valid
   HTML, scoped SCSS, state and package/config conventions; unchanged valid files
   stay reviewed without cosmetic diff requirements.
6. Document writing improvements separately from historical bug fixes. Refresh
   code/name evidence and all-file coverage, run the existing regression, type,
   build and evidence checks, then audit the clarified objective to completion.

### Final writing-pass result

Completed all six steps with one owner. The physical tree and Git inventory both
match the 12 reviewed authored files; 11 are corrected and the minimal main.ts
bootstrap is retained. Local env consumption is separately verified without
recording private values. No dependency or defensive-policy expansion was added.

After the final source edit, 17/17 compiled-component regressions, lint/typecheck,
production build, installed dependency inspection, source/code evidence,
declaration review, project contracts and diff checks passed. Evidence now covers
20 writing patterns, 58 final code ranges and 162 declarations. All 137 rules have
an applicability decision: 81 conform, 13 retain a documented permitted choice,
43 are inapplicable, and none has an unresolved applicable violation.

Requirement-by-requirement results and exact final command outputs are recorded
in .omx/audits/frontend-2026-11-15/writing-pass-verification.json. The report and
final verification records point to the final code snapshots. Real backend/model
integration remains untested; the existing Sass legacy API warning remains.

## Continued review: shared font inheritance

Re-read both complete component styles, templates, rule adoption boundaries and
the final inventory. Keep this follow-up limited to deleting two declarations
already supplied by global.scss: the brand button's font shorthand and the chat
textarea's font-family. Preserve local font-size/font-weight and every layout,
event, state and API contract. This is a small reuse improvement under the
existing CSS-001 scope choice, not a claim that duplicate CSS is a language error.

Existing 17 component regressions protect the established behavior; no new tests
or dependencies are needed for this deletion. Refresh current file/code hashes
and declaration snapshots, then rerun the existing type/build/regression and
evidence checks before updating the final report.

Follow-up complete: both duplicate declarations were removed, component-local
font sizes and weights retained, and all eight final checks passed, including
17/17 existing regressions and production build. Current hashes and outputs are
recorded in font-followup-verification.json and the refreshed final records.

## Continued review: environment variable type contract

The TypeScript compiler confirms a missed TYP-001 issue: Vite's default custom
environment index signature makes both VITE_API_BASE_URL and apiBaseUrl any.
Use the existing Vite 5.4.21 contract, verified at commit
adce3c22c64cc9d44cc8f45cc92b543e3e4bf385 in docs/guide/env-and-mode.md.

Add src/vite-env.d.ts with an ImportMetaEnv declaration merge for the one client
environment field actually consumed: readonly VITE_API_BASE_URL?: string. Keep
it a declaration script without imports; tsconfig already includes vite/client
and src/**/*.d.ts, so no duplicate ImportMeta declaration or runtime layer is
needed. Optionality preserves the existing absent-variable empty-string fallback.

Verify compiler inference changes from any to string|undefined for the field and
string for apiBaseUrl. Refresh naming/source evidence and the all-file inventory
to include the new first-party declaration file; keep tracked and physical scope
checks meaningful for a newly added, untracked source. Run existing regression,
type/build and evidence checks. No runtime validation or dependency is added.

Environment follow-up complete: using the actual parsed tsconfig, a compiler
comparison including/excluding only the declaration confirms any/any before and
string|undefined/string after. All nine final checks passed, including 17/17
component regressions. The inventory now includes 13 application/configuration
files (11 original files corrected, one declaration added, main.ts retained),
with 164 declaration reviews and 60 code ranges bound to fixed evidence.

The concurrently appearing design-lab index.html is an identifiable generated
style-explorer comparison viewer with embedded screenshots. It and its retention
.gitignore are inspected and listed separately as generated artifacts. Final
scope checks keep physical-source coverage and recorded exclusions explicit.
Outputs and the compiler comparison are in env-followup-verification.json.

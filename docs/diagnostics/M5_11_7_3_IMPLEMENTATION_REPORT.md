# M5-11.7.3 Public Reporting Qualification

**Technical status:** COMPLETE_LOCAL_REGISTERED_REPORTING_SCOPE, 2026-10-19 UTC.
**Scientific status:** DESCRIPTIVE_ONLY / REANALYZED_EXISTING_EVIDENCE.
This closes [the approved phase](../../upgrade/implement.md#mode5-m5-11-7-3)
and the registered M5-11.7 reporting scope, not package/remote/release gates.
Guide authorities are [16.4](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md#mlr-r4)
and [Mode 5 product gates](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#79-acceptance-matrix-theo-sản-phẩm-không-chỉ-phase).

## Delivered

- Additive `endpoint.research_report(...)`, ordinary legacy/V2/event/score
  `result.research_report(...)` and `ResearchDecisionReport.from_result(...)`.
  All use one cold reader and explicit access/source rights, with no attached
  mutable cache or automatic metadata retention.
- Generic Mode 4 causal metadata and recognized prepared W3 direct metadata
  keep their original typed observations and account scopes. W3 carry markers
  or continuous-account attachments are rejected; no backend code changes.
- Diagnostics-first Mode 5 delegates to the existing scientific reader and
  requires actual selected params plus an explicit full-development witness.
  No prefix/cohort override, backdating or guessed dictionary is allowed.
- Final [coverage/field/acceptance/handoff matrix](REPORTING_COVERAGE_AND_HANDOFF.md),
  [API](FOLD_DECISION_REPORTS.md), official methodology and Mode 4/5 links,
  [synthetic endpoint/result example](../../examples/completed_research_reporting.py)
  and source-only release handoff. Legacy pre-search disclosure defaults remain
  unchanged: use `public=True` on `AlphaDiagnosticReport`; the new decision
  report defaults are redacted.

The public API is opt-in; `full_report()`, `show_metrics()`, plots, strategy,
sampler, model, fees, fills, account state and RNG remain unchanged. AST checks
prove all pre-existing endpoint/result nodes, fields and signatures identical
to `1633809` after removing only the six new accessor methods. Inherited helper
availability is not new options/meta/WFO capability. Nested Mode 1 retains its
own runtime/measurement contract; this Mode 4 reader does not certify its
inner-validation comparison. No Rust/ML/optimizer bridge was added.

## Reporting Optimizations

Two measured cold-path redundancies were removed, without changing exported
numbers, masks, units or public bytes:

1. JSON export uses the existing canonical owner directly instead of creating
   and validating another temporary `Record` for the detached export.
2. Public Mode 5 rendering uses the original owner's public projection of the
   immutable snapshot already verified by `ResearchDecisionReport`. Full
   validation remains mandatory at assembly and private reload, including
   original decision/params/evidence and permissions. Rendering does not rerun
   that validation for each output format.

An explicit before/after control fails on the original repeated-validation
path and passes after the change. Existing invalid/tampered/private/source tests
continue to pass; there is no trusted flag permitting unvalidated input.
The benchmark invokes the pinned original pure renderer and original export
wrapping from `1633809` for same-process matched comparisons. It never executes
historical financial code or drops requested fields to improve timing.

## Source And Evidence Qualification

Final regression: **416 PASS**, 72.76 seconds. Additional synthetic privacy
archive controls: **6 PASS**, 0.39 seconds; these are canary archives, not built
candidate distributions. Earlier 415-test and 111-test receipts retain their
original scopes and are not added again as distinct tests.

Coverage includes numeric/null/mask cases, active/shadow/applied identity,
original continuous-account scope, future/narrowed permissions, no hidden
execution/search/fit, global RNG stability, source-unchanged AST, detached
exports, immutable copy/pickle/JSON, legacy diagnostics, environment rights,
event facade, WFO schedules and prepared-performance correctness. Existing toy
engine fixtures exercise their original synthetic engines; **new financial
research runs, optimizer proposals and model fits are all zero**.

Final-source readback passes all **nine** retained views: seven Mode 4 families
with **370 origin slots**, two Mode 5 decision snapshots, and their eight
qualified original continuous accounts. Identity, entire private summary and
public JSON bytes are exact, not just rounded R/Q. Readback takes 10.89 seconds,
peak 308.64 MiB; no economic study, fit or bootstrap is repeated.

The prior compact storage contract keeps full original payloads and current
scalar projections separately. The reader explicitly reassembles those pinned
parts and validates the current immutable report; it does not treat the older
pre-projection summary as current. Correct rejection of that older snapshot and
the initial fixture/import failures remain retained. No failed receipt is
rewritten as PASS. The five discovery dossiers, 18 permitted-prefix diagnostic
views, 228 original search pins, three formal RSI results and separate quarterly
variants remain under [11.7.1 inventory](M5_11_7_1_IMPLEMENTATION_REPORT.md).
They are not newly rerun studies or a matched seven-alpha macro experiment.

There are **259 byte-pinned protected inputs**, four pinned prior receipts and
three explicitly accessor-only files verified structurally. Financial,
optimization, metric, backend/Rust, private alpha and detailed guide owners
remain unchanged. Frozen Ridge V1 still verifies 42 sources / five receipts.
No private alpha/local evidence is tracked or admitted to package manifests.

## Measured Cost

Five serial fresh workers, one numeric thread, one first call followed by five
stateless render samples. Medians below are descriptive host samples, **not a
release p95, whole-WFO speedup or universal performance promise**. Inputs and
outputs are matched; optional full detail has its own cost.

| Ledger | Load / Assembly | Public Summary | Public Markdown | Public JSON | Private Full JSON | Worker Peak |
|---|---:|---:|---:|---:|---:|---:|
| Synthetic 2 folds | 0.386 s | 6.43 ms | 7.41 ms | 11.23 ms | 9.58 ms | 221.51 MiB |
| Synthetic 57 folds | 0.982 s | 19.45 ms | 21.32 ms | 28.65 ms | 34.31 ms | 230.17 MiB |
| Original HMA 57 folds | 0.642 s | 25.20 ms | 38.61 ms | 33.64 ms | 66.40 ms | 243.04 MiB |
| Original Mode 5 floor/TPE | 2.364 s | 113.28 ms | 102.93 ms | 124.14 ms | 149.19 ms | 316.08 MiB |
| Original Mode 5 floor/CMA | 2.618 s | 122.91 ms | 107.65 ms | 133.95 ms | 154.46 ms | 316.59 MiB |

Fresh import spans and first-call samples are separately retained in JSON;
load/assembly is not renderer latency. Mode 4 public JSON sizes are
253,131 / 465,415 / 425,719 bytes, respectively. Mode 5 public JSON is
1,160,407 / 1,161,222 bytes; private full JSON is approximately 5.16/5.21 MB.
JSON and original-reader views carry the full retained Mode 5 detail; the shared
public Mode 5 Markdown remains compact. The original `DecisionReport` can render
its detailed trials/components Markdown without inventing another reducer.

Matched original/current JSON ratios across Mode 4 disclosure/detail cells are
**1.48--2.03x**. Mode 5 public JSON is **6.31x / 5.93x**, and private full JSON
**1.99x / 2.14x**. Original/current bytes are identical in all 20 matched cells.
Do not apply these renderer ratios to execution, optimizer, training or WFO.
The complete five-worker cost plus nine-view readback lane took 87.28 seconds.
Earlier pre-optimization Mode 5 samples, including slower/noisy public cells,
remain retained, not hidden or relabelled as current-source wins.

## Exit And Boundaries

All registered M45R-01..10 reporting gates have mapped source/test evidence;
there is no remaining blocking implementation debt in this reporting scope.
Optional unretained return/DD/campaign/cost/factor/probe inputs stay unavailable,
not guessed. Optional R06 financial probes remain deferred; no economic gate,
threshold, history, scientific conclusion or source outcome was changed.

M5-12 is ready for owner entry review, **not started**. Installed artifacts,
current-source remote Linux/Python matrix and public-index proofs remain later
gates. No build/dependency/environment, CI, push, merge, tag or publication ran.
All original positive/negative/insufficient findings are preserved; this work
does not newly establish or deny economic edge for any strategy/domain.

The [cleanup receipt](../maintenance/M5_11_7_3_CLEANUP.md) removes only registered
inactive fixtures, with 3.66 MiB observed recovery. Retained phase evidence is
under 128 MiB and the parent stays under 256 MiB; disk reserve remains >=5 GiB.
Private append-only directory:
`upgrade/private/mode5_upgrade_v1/m5-11-7-3/attempt-01/` contains
`report.json`, `report.md`, `terminal-qualification.json`, source/test/cost pins,
`final-source-tests.xml`, `privacy-tests.xml`, `final-workers.json`,
`readback-03.json`, `operational-failures.json` and `cleanup.json`.

Reproduction uses the registered source, original witnesses and exact inputs:

```bash
.venv/bin/python -B -m examples.completed_research_reporting
.venv/bin/python -B -m tools.benchmark_decision_reporting --folds 57 --output /tmp/new-report-cost.json
```

The benchmark is a checkout research tool requiring its pinned Git baseline,
not an installed-package consumer. Full installed proof belongs to M5-12.

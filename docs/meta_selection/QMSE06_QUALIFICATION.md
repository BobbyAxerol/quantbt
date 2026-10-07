# QMS-E06 Intrabar Intent/Session Qualification

## Registration

Owner approved local E06 on 2026-10-07 UTC after PRE-E06-06. Entry source is
`c0dfcc5fc0e9830630c0c81a4cec847581b4eebf`, branch
`feat/meta-selection-samplers`. Core/native pair stays **1.1.2 / 0.4.3**.
This document registers work before test or benchmark outcomes.

Required reading: [unified E06](../../upgrade/implement.md#qms-e06),
[owner amendment](../../upgrade/implement.md#qms-required-execution-routes),
[guide routes](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s3),
[causality](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[fold flow](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7),
[ownership](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
[economic interpretation](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14),
[intrabar contract](../fast_intrabar.md), [usage](EXECUTION_WFO.md),
[PRE06 source/artifact proof](PRE_E06_06_REPORT.md) and
[cleanup rules](../BUILD_TEST_CLEANUP.md).

## Accepted Scope

- Existing typed `WfoExecutionWindow("intrabar", ..., intent=..., session=...)`.
  The original financial endpoint owns next-open execution, protection, sizing,
  fees, slippage, funding, margin, liquidation and ambiguity policy.
- Mode 4 / `per_fold_causal`, with off/shadow/active meta. No Mode 1 execution-
  domain activation, Mode 2 bootstrap, new numerical dispatch or new estimator.
- Raw IS/forward measurements use original reset-flat diagnostic accounts.
  Final chronological intents run once on one continuous original account.
  No concatenated fold equity, effective-position proxy or execution replay.
- Globally stable session IDs are sliced, not recomputed relative to each fold.
  Quotas and positions do not reset at fold boundaries in the final account.
  Existing entry-bound SL/TP are retained. Explicit per-bar dynamic trailing
  intents keep their existing update semantics; they are not immutable stops.
- Public synthetic strategies only. Private notebooks/data are not accessed.
  Source qualification is independent of positive economic outcomes. No promise
  that meta reduces decay, no default promotion and no synthetic-to-live claim.

## Test And Measurement Contract

| Gate | Required checks |
|---|---|
| T01 | Exact typed calendars, past warmup, no future data, stable sliced session IDs, unsupported-route rejection |
| T02 | Long/short, gap SL/TP, collision policies, explicit dynamic trailing, quota/force-flat/session changes |
| T03 | Independent fill/fee/slippage/funding OPEN/CLOSE, quantity/tick, margin and liquidation expectations |
| T04 | Python oracle/Numba/Rust, direct/prepared, minimal/audit account and fill parity |
| T05 | Carried protections, pending next-open action across folds, actual selected params, independent continuous-account rebuild |
| T06 | Synthetic paired raw IS/FWD decomposition/status only; original real-market empirical study remains NOT_ASSESSED |
| T07 | Matched complete public WFO cost, CPU/RSS, separate financial kernel/facade evidence and exact installed wheel/sdist consumers |

Reuse existing independently expected-value suites, supplemented with focused
fold/session tests. Actual meta checks require at least **12 mature origins**,
fit artifacts, predictions and an applied `META_MODEL_PROPOSAL`; cold fallback
or metadata flags alone are insufficient. Future OHLCV/funding, unavailable
labels, late corrections, history order and pool order must not alter an earlier
decision. Original statuses and raw sample rules are preserved.

Freeze the existing PRE02 public daily synthetic intrabar tape, window range
`(3, 9, 2)`, 90D IS, monthly split, **8 trials**, **seed 731**, Ridge lambda **10**,
one current May 2022 fold with cutoff **2022-04-30**, and sealed PRE05 intrabar
history. This is a compact matched software workload, not the guide's >=128-
trial/12-evaluation-fold economic experiment. Longer chronological multi-fold
account/no-leakage tests are reported separately from this latency fixture.

Cost matrix: off/shadow/active x prepared-witness enabled/disabled, each in
**three fresh processes**, one untimed warmup and one measured complete public
WFO call per process. Reclone history for each call. Measure wall/CPU inside
the call; record process peak RSS separately from WFO-only wall. Includes search,
selection, observer and final account/report work; no observer removal in active
or shadow arms. Preserve pool, RNG, labels, accounting and retained audit work.
All repeats must have the same logical digest per arm and witness parity.
Three samples are descriptive, not a statistical latency or speedup gate.

Use the existing Phase 69 2,000-bar financial benchmark with three repeats and
its unchanged fixture/options. Report kernel and facade separately; these
numbers do not constitute a whole-WFO Rust acceleration claim.

Report paired R as IS contribution + forward-Q using original outcomes and
statuses. Undefined/no-variance results remain typed, not manufactured zeros.
Same independently chosen winner is valid zero effect. One synthetic fold
cannot establish persistent economic gain or a meaningful uncertainty interval.

## Artifact And Source Gate

No runtime change is planned. Verify all 322 runtime/build files against the
PRE06 source seal and all 260 canonical package files in each retained artifact.
Reusing exact byte-identical artifacts is allowed only while those checks pass.
If a defect requires a runtime edit, stop artifact reuse and build/requalify the
changed source separately; no stale artifact may certify new code.

Fresh isolated wheel and sdist consumers must load quantbt/native from installed
site-packages, verify all package files and the extension hash, then run all six
matched full-work cells. Only public test fixtures/tools may come from checkout;
the runtime must not. Check selected params, original raw metrics, account
rebuild, mature fit/rank, unchanged shadow and witness on/off parity. Linux local
CPython 3.12 is not the remote six-cell Ubuntu/Python certification.

## Resources And Cleanup

Initial observed free bytes: **26,411,614,208**; free inodes: **5,598,781**.
New lane: `.maturin/qms08/e06-qualification-v1`. Maximum incremental budget:
**512 MiB** test/benchmark evidence plus **1.5 GiB** for two independent consumers,
with at least **5 GiB** safety headroom. Sequential runs, one-thread BLAS/OMP,
retained G01 tooling and UV offline dependency cache; no new native build.

Retain source, Git, exact wheel/sdist/native artifacts, all passing/failing logs,
raw receipts, frozen history and protected predecessor receipts. Only these new,
ignored, inactive reproducible scratch roots are cleanup candidates:

- `.maturin/qms08/e06-qualification-v1/wheel-consumer`
- `.maturin/qms08/e06-qualification-v1/sdist-consumer`

Hash protected inputs and all new evidence before/after cleanup. Check paths,
ignore status, symlinks and inactivity; keep G01 tooling and offline dependencies.
Report actual filesystem free-space delta, not apparent directory size.
Freshly removed consumers require reinstall before any rerun.

## Exit And Boundaries

Local technical gates must pass without unexpected skip, changed scientific
math, weakened tolerance or rejected evidence deletion. Publish only reviewed
aggregate/hash receipts, not strategy-like raw parameter/descriptor traces.
Commit each coherent verified chunk locally. No push, CI, merge, tag, upload,
economic/default promotion, E07 or E08 execution is authorized by this phase.

Final report separates implementation, software, cost, empirical, artifact,
cleanup and owner promotion states. Existing E03/E04/E05 evidence and remaining
capability exclusions stay intact; E06 does not close unrelated debts by name.

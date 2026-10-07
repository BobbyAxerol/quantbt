# QMS-E07 Event Route Qualification

## Registration

Owner authorized local E07 on 2026-10-07 UTC, after E06. Entry source is
`1a0f892`, branch `feat/meta-selection-samplers`. Pair remains **1.1.2 / 0.4.3**.
No push, CI dispatch, merge, tag, release or economic promotion is authorized.

Read [E07](../../upgrade/implement.md#qms-e07), the
[execution amendment](../../upgrade/implement.md#qms-required-execution-routes),
guide [selection](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7),
[causality](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[W3 ownership](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
[reporting](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s12),
[cost](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10),
[transport](W3_TRANSPORT_AND_ACCOUNT_CONTRACTS.md),
[sampler/schedule limits](W3_SAMPLER_SCHEDULES.md), [E06](QMSE06_REPORT.md),
[workspace rules](../../AGENTS.md) and [cleanup](../BUILD_TEST_CLEANUP.md).

## Accepted Scope And Output Addition

Qualify generic callback and command-tape windows on their existing Python/Rust
financial owners, and sequential single-symbol numeric W3 on its existing Rust
reset-flat runner. Mode 4 / `per_fold_causal` only; meta remains off by default.
Do not translate arbitrary callbacks to numeric strategies or activate carry,
multi-symbol, bootstrap or public meta batching.

Generic final accounts preserve pending orders and account state across alpha
factory switches. W3 exposes separate reset-flat fold accounts, not a continuous
equity. Independent IS/forward counterfactual accounts remain reset-flat.

The owner additionally requires enough endpoint output to evaluate the run.
Existing metadata exposes tasks, models, snapshots, proposals and selected params,
but observed forward outcomes are only accessible through the caller's history.
Add `meta_selection.observed_revisions`: immutable current-run sealed revisions,
including panel, raw observations, typed statuses, publication times and labels.
Retain references to the original records, not all archive history, extra financial
paths or a replay. It is opt-in output only; selection and observer order stay
unchanged. This narrow shared-runtime change invalidates reuse of old core
artifacts: rebuild core wheel/sdist, keep the byte-identical native wheel.
Historical source-bound receipts remain historical; do not rewrite their seals.

## Tests And Fixtures

| Gate | Required evidence |
|---|---|
| T01 | Stable facades, typed payloads, fresh candidate/window factories and IDs; wrong protocols fail closed |
| T02 | Independent next-open/fill-feedback, pending cross-fold orders, cancel/amend/replace/OCO, partial fills and rejection; declared OHLCV assumptions only |
| T03 | Original numeric/reference/process witnesses, cancellation/deadline failure cleanup, task-local RNG and no partial label publication |
| T04 | At least 12 actual mature origins, full-pool fit/rank, applied active params, off/shadow search/account parity and future/history mutation controls |
| T05 | Original IS/forward sample/activity/status contract, independent final account rebuild; raw R = IS contribution + forward Q, no economic guarantee |
| T06 | Complete public workloads, wall/CPU/RSS/PSS, callback/FFI ownership, source-exact installed wheel/sdist, privacy and cleanup |

Reuse PRE02/PRE05 synthetic daily tapes, 90D rolling IS, monthly forward,
range `window=(3,9,2)`, 8 trials, seed 731, lambda 10 and default minimum 12
mature origins. The matched current fold is May 2022, cutoff April 30.
Use own compatible history for every financial backend. Existing history bytes
and failed/scientific evidence are protected. Add a public basic numeric grid
fixture whose exits depend on actual fill feedback; no private alpha/data access.
Real-alpha economic promotion remains NOT_ASSESSED, not a required positive
result to manufacture from these software fixtures.

Before measuring, freeze five protocol/backend cases: callback Python/Rust,
commands Python/Rust, numeric W3 Rust. Each has off/shadow/active and two variants:
prepared witness on/off for callback/commands; reference/required Rust meta math
for W3. These are **30 cells**. Record three fresh-process repeats, one untimed
warmup and one measured complete WFO call per cell; fresh history each call.
No observer removal or changed audit work. Three repeats are descriptive, not
a significance or speedup acceptance threshold. Process peak RSS includes imports;
record resident/PSS at the end of the measured call separately.

Run all 30 cells once in each isolated exact wheel/sdist consumer. Check all
canonical package hashes and loaded runtime origins before/after. Legacy logical
digests stay comparable: the new additive revision sidecar is tested separately.
Rerun affected shared-meta, event lifecycle, W3 transport and E06 conformance;
do not rerun unrelated real-market optimization or old source-seal receipts as
though they certified new bytes.

## Resource Plan And Exit

Lane: `.maturin/qms08/e07-qualification-v1`. Initial free disk about 25 GiB.
Budget 512 MiB retained evidence/artifacts plus 2 GiB temporary core build/two
consumers; minimum 5 GiB safety headroom. One-thread BLAS/OMP, sequential workers,
reuse current G01 tooling and offline dependency cache. No Rust rebuild.

Only these new ignored, inactive reproducible scratch paths may be removed:
`build-env`, `wheel-consumer`, `sdist-consumer`, `stage/build` inside this lane.
Retain exact wheel/sdist/native, staged source, frozen histories, registration,
all pass/fail logs, receipts and predecessor hashes. Verify protected hashes and
source before/after cleanup; report actual free-space change. No broad cache prune.

Exit: applicable tests and installed cells PASS, no unexpected skips, unchanged
scientific math/search/accounting, transparent output and scope, cleanup receipt
and local scoped commits. Distinguish software, cost, economic, remote and public
states. E08 remains separately authorized; no default/economic promotion here.

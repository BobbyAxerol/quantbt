# QMS-01 Source And Seam Map

This page preserves the QMS-01 discovery snapshot below. QMS-02/03/04/05 are
subsequent approved changes, not claims that current bytes still equal that
snapshot. The current public hook is in `WalkForwardEngine._run_per_fold_schedule`
after native selection and before `params_by_fold`/OOS. Focused
`meta_selection/config.py` and `runtime.py` own policy, history binding and observer;
the endpoint/engine add thin hooks only. Read [current integration](INTEGRATION.md)
and [QMS-05 source-pinned evidence](QMS05_REPORT.md) for the implemented version.

## Identity And Scope

Baseline tag `v1.1.1` resolves to
`2c811a7faaed3c274e93c60650e16207949f0a59`. Phase entry is `e2abce9` on
`feat/meta-selection-samplers`, based on `origin/dev` at `24f55c7`.
The entry worktree was clean. Runtime `src/`, Rust, core metadata and lockfile
have no diff from the release. The manifest records 271 protected file hashes,
per-symbol line ranges/body hashes, isolated import paths, native binary hashes,
dependency versions, installed exports and descriptors. Those machine records
are authoritative when a line number differs from a historical guide excerpt.

An isolated `python -I` from `/tmp` imports the editable `src/quantbt` package,
not a retired root mirror. Installed core/native are `1.1.1`/`0.4.2`, Optuna is
`4.8.0`, native API is `0.4`, core ABI is `0.5`. The product descriptor identifies
the same release pair. No environment installation, native rebuild, distribution
upload, tag movement or financial-source edit was performed. This is an installed
host proof, not a fresh CPython wheel matrix or a newly downloaded wheel proof.

References: [guide source contract](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s0),
[machine manifest](../../benchmarks/optimization/meta_selection/legacy_baseline_manifest.json),
[test implementation](../../tests/meta_selection/test_qms01_baseline.py),
[discovery tool](../../tools/qms01_baseline.py).

## Verified Callers

| Stage | Actual source/symbol | Observed ownership |
|---|---|---|
| Public configuration | [endpoint.py](../../src/quantbt/endpoint.py), `walk_forward` 1931-2187; `EndpointConfig` | Builds WFO config/retention/scorer policy, preserves account and one-way fee. |
| Public execution | `backtest` 2240-2442 -> `_run_walk_forward` 3689-3955 | Builds scorer and engine, then executes one final stitched account. |
| Prepared lifetime | [walkforward.py](../../src/quantbt/walkforward.py), `run` 985-1127 | Owns immutable preparation, lifecycle and cleanup; do not evaluate with a released scorer after return. |
| Per-fold schedule | `_run_per_fold_schedule` 1455-1640 | One study per fold, seeds 731/1000734 in this fixture; commits fold params before outer realization. |
| Search | `optimize_params` 1674-1844 | Direct legacy `TPESampler(seed=fold_seed)`, objective on IS, duplicate pruning, no meta observations. |
| Raw IS metrics | `evaluate_params_is` 1854-1966 | Full IS plus shards. Fold metrics retain raw Sharpe, report trade count and penalty. |
| Full pool | `_select_is_candidate_records` 4318-4341 input `records` | All attempted records exist here; eligible means not pruned and finite objective. |
| Native anchor | `select_is_only_robust_record` 4062-4242 | Top IS fraction, temporal/plateau policy, medoid/fallback/centroid. Not `max(raw_IS)`. |
| Retention | `_capture_research_records` 1642-1672 -> `_compact_trial_records` 1846-1852 | Full ledger is optional and observation-only; compaction drops fold metrics. |
| Outer OOS | `_run_per_fold_schedule` post-selection scoring | Exactly one outer realization per Mode 4 causal fold; not used to select its params. |
| Endpoint scorer | `endpoint.py::_WalkForwardEndpointScorer` 4839-5392 | Prepared NumPy/Numba or ordinary endpoint reference; target route stays declared. |
| Prepared Rust scorer | [native_wfo_public.py](../../src/quantbt/backends/native_wfo_public.py) | Batch fresh accounts, same-close target contract; does not select or own the final stitched account. |
| Sampler factory | [samplers.py](../../src/quantbt/optimization/samplers.py), `build_sampler` 12-80 | Generic optimizer only today; QMS-02 must bridge this factory, not duplicate it. |
| Baseline floor | [optimizer.py](../../src/quantbt/optimization/optimizer.py), `_apply_baseline_floor` 310-361 | Called by generic `OptunaOptimizer.optimize`, not by public WFO or reactive WFO. No invented WFO floor. |
| Reactive selection | [reactive_wfo.py](../../src/quantbt/backends/reactive_wfo.py), `_select` 630-762 | Separate loop, shared selection formulas, reset-flat diagnostics; needs its own QMS-06 qualification. |

Full functions and relevant branches were read, including the prepared scorer's
guards, default/explicit retention, proxy path, OOS scoring and cleanup. AST
body hashes include decorators; grep matches alone are not source evidence.

## Selection Hook And Pool

QMS-05 integration point: inside `_run_per_fold_schedule`, after exact native
selection and its metadata tagging, **before** assigning `params_by_fold` at
line 1564 and before strategy/OOS execution. No raw-IS floor may overwrite a
future meta winner after this point. The generic baseline floor is not on this
call path. The full pool must come from search records before compaction, not
from `fold_candidates` or a public filtered table.

The actual public fixture has six attempts, five eligible candidates per study.
The filtered candidate list has four entries including the anchor duplicated
among three top records; unique filtered membership is three, not five.
For fold 0, native anchor is trial 4 (`window=11`, adjusted IS 9.30293425756).
Raw/objective-best is trial 2 (`window=9`, 9.92895871318). Fold 1 chooses trial 5,
`window=7`. A separate plateau fixture selects `x=3` instead of an isolated
raw-IS spike at `x=9`; fallback and centroid variants are also exercised.

`research_retention="full_trial_ledger"` preserves original raw records before
compaction. It is not the source of selection and cannot become an implicit
default allocation. QMS-03/05 will retain only required compact numeric fields
on opt-in routes; disabled paths keep existing retention and RNG behavior.
The discovery spies delegate original calls and are restored on exit. A plain
no-ledger run has exact matching trials, params, positions and equity.

### Centroid Disposition

Stock centroid returns trial ID -1, `requires_evaluation=True`, no fold metrics
and cluster-average IS metrics. Its causal return path does not evaluate those
new params on IS. These averages are **not labels for the centroid**.

The probe invokes the existing `evaluate_params_is` for those exact params
after native selection, before the live fold/scorer lifetime ends. Its score
differs from the cluster average. It never replaces the stock selection, tells
Optuna a new objective or changes final params. This extra work is diagnostic,
not included in the uninstrumented performance baseline.

QMS-03/05 must capture a same-IS authoritative evaluation here, with evaluator
lineage and separately charged physical work. If a route cannot provide it,
centroid meta opt-in must fail; medoid native behavior remains untouched.
The first test attempt incorrectly tried replay after cleanup and failed. The
probe was moved to the owned lifetime, not fixed by extending account lifetime
or modifying the runtime.

## Metric Validity And Activity

| Evidence | Authoritative meaning | Future label disposition |
|---|---|---|
| `fold_metrics.is_sharpe_raw` | Existing evaluator Sharpe before trade penalty | Retain separately from objective. |
| `mean_is_sharpe` | Mean penalty-adjusted IS | Not a raw model target. |
| IS shard/temporal/plateau scores | Native policy diagnostics | Preserve descriptor profile; do not substitute them for raw Sharpe. |
| `mean_oos_sharpe=0` on IS records | OOS not evaluated | Missing label, not observed zero. |
| `volatility=0` in endpoint/native WFO adapters | Placeholder | Never certifies zero or positive variance. |
| Native status 0 | Execution succeeded | Does not alone prove the Sharpe sample is defined. |
| `trade_count`/`turnover` scorer fields | Public report position-transition count | Not fill count or quote turnover; even the initial diff is counted. |
| Accepted positions/equity and original metric result | Sample/activity support under that same economic route | Source of validity; never reconstruct a different account. |

Existing [performance metrics](../../src/quantbt/metrics/performance.py) prefer
finite daily returns, use sample standard deviation (`ddof=1`) and 365-period
annualization by default. Daily equity is last daily mark, forward-filled by
the existing result contract; returns are its percentage changes. A short run
with no daily sample falls back to finite bar returns and existing intraday
annualization. These conventions must be versioned, not silently compressed
or replaced when creating historical labels.

Unit probes distinguish a valid zero-mean/positive-variance Sharpe zero from a
flat sample that also publicly reports zero, and from an absent sample.
Undefined/flat/failed/censored support cannot be converted to label zero.
Liquidation and activity disposition require explicit account/metric policy.

`BacktestScalarScoreResult` discards paths after its authoritative reduction.
`NativePreparedScoreColumnsV1` retains neither sample count nor variance;
the fuller native prepared row has a sample count but still no variance field.
The underlying Rust metric snapshot contains both, but matching its metric
contract to the public daily reducer must be proved, not inferred by name.
QMS-03/06 must qualify a thin original-result/support adapter or fail the
affected meta label lane. Financial scoring itself is already usable; scalar
Sharpe alone is not blanket meta-label certification.

## Data Clock Versus Completion Clock

| Field/frontier | Actual owner now | Meta ownership planned |
|---|---|---|
| Current selection frontier | `fold.train_end` / `selection_data_end`; lifecycle cutoff for IS invocation | Frozen `information_as_of`/`data_cutoff`, QMS-03. |
| `WalkForwardFold.cutoff_timestamp` | Fold output/execution range endpoint; may be outer test end | **Not** a substitute for current IS frontier. |
| Strategy/scorer visible data | Causal per-invocation prefix and prepared positional window | Never expose current OOS outcomes to selection. |
| Search completion | Measured wall timestamp in discovery trace; no stock decision field | Runtime completion clock, QMS-05. |
| Label/revision availability | No sealed meta task archive in baseline | Explicit observer/history versions, QMS-03. |
| Seal / readiness | No stock meta decision fields | QMS-03/05/06; separate from data cutoff. |
| Economic effect | Existing intent/fold-account execution, not a model timestamp | Reference existing route; no new controller. |

In this historical fixture, selection inputs end in 2020/2021, while actual
computation occurs in 2026. Saved `wall_search_*` timestamps are **not** simulated
past forecasts or past live effects. No seal/effective timestamp is fabricated.
Future-suffix mutation changes realized equity but not the first fold's
proposals, raw IS records or selected params. Later folds may legitimately use
that now-past data. Future archive mutations belong to QMS-03/05 when an archive
actually exists. Equality-at-cutoff needs source event-order evidence.

## Route And Capability Dispositions

| Route | Baseline status | Meta disposition before activation |
|---|---|---|
| W0 scalar Series, Mode 4 causal | Actual public trace, prefix mutation and oracle/Rust parity pass | Mandatory; QMS-03/05/06 must qualify raw metric support. |
| Prepared scalar Rust target scorer | Installed exports and actual batches pass | Same-close only; retain one-symbol/365/runtime/fee/slippage/contiguous guards. |
| W1/W2 prepared strategy | Existing protocol/capability inspected; affected prepared tests pass | Require declared causal parameter-independent cache; no arbitrary callback purity inference. |
| `%_equity` prepared Rust | Existing explicit require, runtime and legacy fee/slippage guards inspected | Separate economic-family identity; no inferred equivalence to notional. |
| Global modes 1-5 | Actual baseline runs saved | Legacy stays available; active/shadow meta V1 must reject global. |
| Mode 1 per-fold decay/nested causal | Actual runs saved | Preserve decay/nested math; no meta activation. |
| Mode 2 SBB | Actual proxy/path baseline saved | Preserve bootstrap/path and RNG; not scalar Rust meta. |
| W3 reactive/reset-flat | Different selection/account semantics inspected | Not certified for meta by scalar tests; QMS-06 adapter or explicit reviewed unsupported disposition. |
| Portfolio/package/intrabar/options | Outside this module's mandatory scalar proof | No new engine or accounting portability claim. |

Prepared guard tests exercise unsupported target, 252-day annualization,
noncontiguous window and Mode 2 proxy + require. Require raises before search;
auto reports fallback reason. Installed Rust scores 42 rows / 3,781 score-bars in
12 native boundaries for the matched Mode 4 fixture, with zero fallback rows.
Metric values, report trade counts, selected params, positions and final equity
match the ordinary prepared oracle under the registered tolerance.

## Frozen Extension Boundaries

- Public endpoint names and existing default invocation stay unchanged.
- Future static config: `optimization_config.sampler_config` uses the shared
  `SamplerConfig`/factory; `optimization_config.meta_selection` is typed and
  versioned. These are proposals, not APIs implemented in QMS-01.
- Future history binding: additive keyword-only caller-owned `meta_history`
  at existing `backtest`/engine-run boundaries, outside serialized config. No
  hidden database URI, callable or global provider. Tests come with QMS-03/05.
- Existing tuples/lists/ranges/scalars keep their distribution semantics.
  Conditional descriptors require caller schema, never inferred alpha flags.
  Generic log/conditional sampling is currently unsupported; QMS-02 must use a
  minimal normalized extension or explicit capability error, not silently turn
  a numeric list into continuous space or discard inactive dimensions.
- Sampler roster is fixed to legacy TPE, multivariate/group TPE, CMA-ES and Sobol
  recipes on pinned Optuna 4.8.x. Preserve generic random/grid/NSGA-II. CMA-ES
  optional dependency and Sobol factory bridge belong to QMS-02; no dependency
  added now, no adaptive batching rewrite or learned auto-sampler.
- Identity schemas will separate task/revision, compatibility family and
  exact training snapshot. Metrics, parameters, roles, basis/weights, sampler,
  seed, route/economics and clocks must be versioned. No mutable anchor flag.
- `full eligible pool` is not a label panel. Registered panel cap 16 means
  anchor + five top + five diversity + five controls, union actual winners;
  extras are charged, not clipped. Selection membership stays full.
- Rust-first numeric additions: one batched descriptor transform, weighted
  Gram/b accumulation, and score/guard/winner reduction through the existing
  native crate. Python owns sampler/orchestration; independent NumPy/Numba
  references/fallbacks must declare reason and preserve full inputs.
- Keep float64, no fast math, lambda 10 with origin-sum weights, minimum 12
  mature origins, Q floor -0.10 and two-pass tie tolerance 1e-6. Near-boundary
  uncertainty uses qualified reference scope; do not loosen decision parity.

### Patch Allowlist And Owners

QMS-01 actual changes: `tools/qms01_baseline.py`, `tests/meta_selection/`,
`benchmarks/optimization/meta_selection/`, `docs/meta_selection.md`,
`docs/meta_selection/`, `handoff/WFO_META_CURRENT.md`, `upgrade/implement.md`.
All runtime/source/package files and the guide are read-only in this phase.

Later, individually approved phases may add one cohesive
`src/quantbt/optimization/meta_selection/` package and minimal adapters in
`endpoint.py`, `walkforward.py`, optimization config/space/samplers, prepared
WFO/evaluation and, only after qualification, reactive WFO. Pure numeric Rust
code belongs in a focused module under the existing `quantbt-batch` crate and
a thin `rust/native_event` binding. Rust Cargo/package versions change only
under the corresponding dependency/ABI/release approval. Account, matching,
funding, sizing and market collection code are not in the meta allowlist.

| Requirement / guide rules | Verified/discovered here | Owning completion phase |
|---|---|---|
| Q1-T01 / source / R23,26,27 | Actual import/tag/descriptors/hashes, mismatch negatives | QMS-01; later versioned source maps must record approved diffs. |
| Q1-T02 / frontier / R08-10,30 | Actual current-OOS mutation, distinct data/wall clocks | QMS-01 lock; archive/revision clocks QMS-03, decisions QMS-05/06. |
| Q1-T03 / anchor / R06-07,12 | Public robust != raw-best; medoid/fallback/centroid exact replay | QMS-03/05 integration, no stock financial correction needed. |
| Q1-T04 / pool / R01,11,16 | Original pool and compaction loss; no-ledger parity | QMS-03/05 compact opt-in retention, QMS-07 information parity. |
| Q1-T05 / raw support / R13-15,20 | Placeholders, route guards, installed native parity | QMS-03/06 required validity adapter; unsupported lanes fail closed. |
| Q1-T06 / legacy modes / R02-05,18-19,21 | Eight valid combinations and unsupported baseline behavior | QMS-02 sampler-only bridge; QMS-05 meta preflight; QMS-08 regression. |
| Q1-T07 / protection / R23,26-27 | 271 hashes, clean entry, no core/native diff | All phases preserve their reviewed financial boundaries. |
| Q1-T08 / budget / R20,22,24-25,28-30 | Actual output/resources, zero existing meta origins, no advancement | QMS-04 numeric reference; QMS-07 performance; QMS-08 empirical/package. |
| G1-OWNER / R25 | PENDING, no fabricated approval | Bobby accepts boundaries before QMS-02. |
| R17 / corrupt vs cold start | History does not exist yet; not a fallback success claim | QMS-03/04 typed errors/support and QMS-05 integration. |

## Measurement And Acceptance

Registered before measurement in [the phase plan](../../upgrade/implement.md#qms-01):
547 daily bars, six attempts/study, seed 731, two quarterly outer folds, three IS
shards, eight SBB samples, one native worker and thread pools capped to one.
No early stopping; execution reuse off; full scientific trial records retained
for discovery, normal no-ledger output used for warm timing. A warm-up is saved
separately from three uninstrumented timing repetitions.

The baseline is about 0.18 seconds per tiny Mode 4 public run on this host.
RSS/PSS are saved per repetition and peak RSS is process-wide including earlier
lanes, imports and JIT, not isolated WFO incremental memory. Three repeats
cannot qualify a 3%/5% disabled-overhead gate or a memory plateau. No speedup is
claimed: implementation behavior has not changed. Future overhead comparisons
must keep candidate/search/account/output work and use the registered repeated
aggregate method when this tiny fixture is too noisy.

There are two smoke origins but **zero sealed matured meta origins**. Candidate
rows or multiple seeds cannot manufacture 12 origins. The primary real-market
study is NOT_RUN_BUDGET; it still needs authorized data/history and >=128
attempts/cutoff, >=12 matured origins and >=12 locked paired folds. The SMA
example is a representative existing strategy, not the primary real-alpha cell.

Technical source/boundary/baseline/scope gates can pass independently of
economic benefit. Owner acceptance remains pending; no phase advancement,
publication or live authorization follows automatically.

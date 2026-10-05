# Real-Alpha Correctness And Cost Review

This is the preserved **pre-debt-closure** report. Its original metrics and
receipts remain historical; the current owner-approved local follow-up is
tracked under [QMS Local Debt Closure](../../upgrade/implement.md#qms-local-debt-closure---owner-authorization-2026-10-04).
Read [the completed current comparison](LOCAL_DEBT_CLOSURE_REPORT.md) for
post-patch time, unchanged witnesses/accounts and explicit native/meta decay.

## Status And Scope

Local owner-approved follow-up to QMS-08, 2026-10-04, on
`feat/meta-selection-samplers`. The selected alpha is **Gradient RSI / ETHUSDT
1h**, not the guide's primary BTC scientific cell. No core, alpha notebook,
data-loader, financial policy, published version or default was changed.
No push, release, deployment or PyPI operation is authorized or performed.

Private installed pair: **core 1.1.1+qms08 / native 0.4.3.dev4**, CPython 3.12,
NumPy 2.2.6, Numba 0.65.1, Optuna 4.8.0. Real runs use site-packages, not a
checkout source shadow. The ordinary published/research pair stays 1.1.1/0.4.2.
QMS numeric transform/Gram-solve/rank actually execute compiled Rust. All
financial arms explicitly use Numba so their comparison isolates meta costs.
This is not an all-Rust financial WFO benchmark.

**Completed locally:** four full-study arms, four three-repeat sampler lanes,
independent fixed replay, saved-output verifier and separate profiler. Technical
lineage/accounting parity passes. Economic evidence is descriptive research;
the original-result hourly meta path has material performance debt. Owner review
and all public/remote decisions remain pending.

Read the [sanitized verified evidence](../../benchmarks/optimization/meta_selection/qms_real_review_evidence.json).
Full alpha/data/trial params/witnesses remain private and ignored. The public
receipt contains counts, hashes, aggregate metrics, all 28 calendar fold metric
pairs and measured profiler owners, not alpha code or selected params.

## Protocol And Provenance

The protocol was written into the [unified plan](../../upgrade/implement.md#qms-post-08-real-alpha-cost-and-correctness-review)
before outcomes. It follows the detailed guide's
[empirical scope](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14),
[numeric/chronological policy](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
and [cost rules](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10).

- Real loader: `CryptoBinance1m.load_resampled("ETHUSDT", timeframe="1h")`.
- 37,968 hourly bars, 2020-01-01 00:00 through 2024-04-30 23:00 UTC;
  zero missing hours, unique monotone calendar, coherent finite OHLCV.
- Loader/export took 1.685 s. No synthetic quotes or gap filling.
- Market SHA256:
  `4726433bced6b83a935e5c5c38ec25299cec20df08ff03fdf0700b44b166f42b`.
- Export only the existing trusted function cell and its eight numeric ranges;
  never execute notebook optimization/display cells or modify its thesis.
- Main lane: 28 monthly folds, January 2022 through April 2024, rolling 365D IS,
  Mode 4 / `per_fold_causal`, 128 attempts/fold, seed 731, no early stopping or
  warm-start. One financial worker, independent sampler/history per run.
- Native selector: current-IS robust medoid, top 10%, one IS subperiod,
  original 100 trades/year penalty with factor 0.5.
- Preserve notebook economics: capital 20,000; leverage 1; allocation 0.5;
  maintenance 0.005; contract size 1; legacy fee 0.0005, canonical one-way
  0.00025; slippage 0.0001; funding 0.0001; no pyramiding.
- Funding is the baseline's configured constant, not newly obtained historical
  venue funding. This is target-position replay, not exchange-certified fills.
- Meta keeps default 12 matured origins, lambda 10, Q floor -0.10 and full
  registered panels; no information budget is reduced for speed.
- Sampler cost lane: first two monthly folds, 32 attempts each, one warmup plus
  three independent measured runs per fresh process. Four engineering recipes,
  not four economic policies selected after seeing forward returns.
  Each recipe owns one fresh process; its three measured studies run sequentially
  inside that process with fresh endpoint/sampler state, not three cold imports.

Main studies are single warm observations, not medians or a portable speed
certificate. Normal host services remain running; small timing differences
between arms cannot establish Rust superiority. Cold warmup and private export
are separate from the measured public execution span. RSS includes imports/JIT
and retained results through execution; it does not certify the peak of later
JSON evidence serialization. Do not call qualification disk usage runtime RSS.
The recorded first-public-call warmup is two folds/32 trials after imports and
the alpha prefix probe, not first installation/import or a cold full study.

## Domain And Guide Alignment

The eight implementation phases are not eight demonstrations of economic edge.
The sealed [QMS-08 report](QMS08_REPORT.md) records **567 passed**, zero
failures/errors/skips, including 429 QMS and 138 adjacent checks. All 64 guide
requirement IDs have coverage/dispositions, not 64 independent market samples.
This follow-up executes **27 additional checks** (15 runner + 12 saved-receipt
negatives) and actual real-market executions, without
rewriting prior phase receipts into retroactive real-alpha certificates.

| Contract | What is verified |
|---|---|
| Shared sampler bridge | Existing Optuna factory, exact bounds/steps/effective identities, conditional/categorical guards, warm-start provenance and omitted-config compatibility |
| Full IS pool/native anchor | All eligible original-result candidates, exact stock selector anchor, actual raw IS metrics, not a proxy or manually supplied anchor |
| Chronology | Snapshot frozen before search; terminal revisions available only after forward end/lag; current outer OOS is not a fit/rank input |
| Ridge mathematics | Origin-sum weights, historical scaler/basis, lambda, relative-decay target, Q/tie guards; float64, no inverse/fast-math or NxN weight matrix |
| Active/shadow behavior | Actual selected params feed the OOS signal; shadow leaves the native winner/account intact |
| Financial domain | Original pct-equity fee/funding/sizing and continuous account; reset counterfactual metrics are not stitched fold equity |
| Prepared/portable artifacts | Prior QMS-06/08 qualified witness and export/restore tests; this real lane uses original results, not a new prepared/Rust-financial certification |
| Unsupported routes | Meta remains Mode 4 causal scalar-only; other modes/schedules/W3 are not silently coerced |

For each historical origin, candidate labels use the native anchor:

\[
y_{g,j}=(I_{g,j}-F_{g,j})-(I_{g,a}-F_{g,a}),\qquad
w_{g,j}=\frac{1}{m_g}.
\]

The learner fits weighted Ridge on compatible **past matured** observations.
The proposed current candidate must pass the predicted forward-difference guard:

\[
\widehat{Q}_j=I_j-I_a-\widehat{y}_j\geq -0.10.
\]

That prediction is not an actual OOS safeguard or a guarantee of future gains.
The native stage stays current-IS-only; a learned active final decision uses
past-forward-adaptive information and must not be labeled pure IS-only.

## Real Correctness Results

- Real-alpha future-suffix price/volume mutation leaves the prior 7,000-bar
  signal prefix exactly unchanged. This proves this alpha probe, not arbitrary
  strategies or exchange/live clock availability.
- Each main arm has 3,584 attempts, 3,531 COMPLETE and 53 duplicate PRUNED;
  no trial FAIL. Attempts, unique candidates and completion are different counts.
- Each enabled arm executes 459 panel evaluations with zero observer failures.
  Full eligible pools and selected/native panel membership are preserved.
- First 13 folds have insufficient history and use native fallback. The first
  learned fold is February 2023, with exactly 12 matured origins; April 2024
  has 26. An outcome published just after its last bar is not available at that
  same last-bar cutoff, even in historical replay.
- Off/shadow have identical proposals/objectives, params and accounts;
  positions, equity and returns have maximum absolute difference **0**.
- Independent fixed-parameter regeneration of all 28 OOS signal segments,
  without optimization or meta fitting, reproduces both off and active/Rust
  positions, equity and returns with maximum absolute difference **0**.
  This checks actual parameter application, not only metadata.
- Active Rust/reference have identical proposal/objective trajectories, final
  params, support/fallback reasons and original raw paired metrics; positions,
  equity and returns have maximum absolute difference **0**. Float tolerances
  remain declared even where the actual financial buffers are bit-identical.
- The independent saved-output verifier checks original tasks, terminal
  revisions, snapshot availability at the cutoff, current pool/native anchor,
  actual params application, panel membership, original-result provenance,
  terminal counters and financial buffer hashes. It makes zero financial calls.
  Negative tests cover current-OOS permission, late labels, readiness, panel,
  proxy evidence, changed objective/account/params and cumulative counter misuse.

Numeric tolerances stay `rtol=1e-9, atol=1e-10`; account tolerance stays
`rtol=atol=1e-10`. Logical params, support, panel/role membership and dispositions
are exact comparisons. Timed publication/artifact IDs need not match.

## Measured Costs

### Main Public Studies

| Arm | Public wall | Fit/select | Observer | Execution peak RSS |
|---|---:|---:|---:|---:|
| Off | 391.024 s | Not run | Not run | 342.934 MiB |
| Shadow/Rust meta | 1,023.177 s | 1.125 s | 18.557 s | 356.793 MiB |
| Active/Rust meta | 1,086.556 s | 1.342 s | 19.308 s | 357.871 MiB |
| Active/reference meta | 1,032.585 s | 1.211 s | 18.191 s | 355.625 MiB |

Active/Rust is **2.779x the off latency**, an extra **695.533 s / 177.9%**;
execution peak RSS rises **14.938 MiB / 4.36%**. Fit/select is only **0.12%**
of total active execution; observer is **1.78%**. Thus a fast Rust Ridge solve
does not make this original-result hourly WFO path cheap. Most incremental
work lies in the IS scoring/witness path; the separate profile below identifies
the measured owner rather than attributing the residual to Rust.

Off takes **6.52 min**; shadow **17.05 min** (+161.7%); active Rust **18.11 min**
(+177.9%); active reference **17.21 min** (+164.1%). Rust active is 5.23% slower
than reference in these single observations, despite exact decision/account
parity. This is not a repeated matched numeric-kernel comparison and does not
prove a stable 5.23% language effect. No new whole-study Rust speed claim passes.

| Arm | CPU | Sampler methods | Before RSS/PSS | After RSS/PSS | First public warmup |
|---|---:|---:|---:|---:|---:|
| Off | 385.463 s | 85.157 s | 315.742 / 308.290 MiB | 343.129 / 336.033 MiB | 7.148 s |
| Shadow | 1,020.919 s | 75.632 s | 318.730 / 310.123 MiB | 357.020 / 348.412 MiB | 19.806 s |
| Active Rust | 1,085.675 s | 79.390 s | 319.563 / 313.180 MiB | 358.074 / 350.923 MiB | 20.992 s |
| Active reference | 1,032.020 s | 77.610 s | 317.402 / 308.807 MiB | 355.750 / 347.154 MiB | 19.847 s |

Fit/select, observer and sampler spans are contained in public wall time, not
extra time to add to it. The observer timer covers post-seal forward work, not
all IS witness generation. Full-run physical evaluator/bar/callback counts were
not instrumented in this follow-up; do not invent them from attempted trials.

There are 60 native numeric calls plus three qualification probes, 1,174,823
owned input-copy bytes, zero exact-cache hits and 30 misses. Changing-fold
inputs legitimately miss the exact cache; last retained cache size is 3,008
bytes. These are the **latest run-cumulative counters**, not a sum of per-decision
snapshots. Parameter encoding/scaler/diagnostics remain Python/NumPy as declared;
the financial scorer and alpha use Numba. No fictitious all-Rust or zero-copy
claim is made.

### Samplers

| Recipe | Warm wall median | Sampler-method median | Wall versus legacy | Execution peak RSS |
|---|---:|---:|---:|---:|
| TPE legacy | 5.543 s | 0.909 s | Baseline | 318.320 MiB |
| TPE multivariate/group | 4.732 s | 0.488 s | -14.64% | 318.887 MiB |
| CMA-ES | 4.407 s | 0.092 s | -20.50% | 317.152 MiB |
| Sobol | 4.278 s | 0.084 s | -22.83% | 318.066 MiB |

Every measured run has 64 attempts/64 COMPLETE, no FAIL or PRUNED. Three repeats
within each recipe reproduce params, objective trace and financial buffer hashes.
The recipes naturally propose different pools; their winners are not a
cross-recipe parity assertion or evidence of one sampler's superior edge.
Execution RSS spread is less than 2 MiB here and is not an allocation-level
proof that one recipe is more memory-efficient.

Resolved recipes use the existing Optuna factory. Both TPE recipes have startup
10 per study; grouped TPE has 22 relative proposal trials after 10 independent
trials on this 32-trial fixture. CMA-ES and Sobol have one independent startup
then 31 relative proposals per study. Thus the two-fold Sobol lane has **62 QMC
points plus two independent starts**, not 64 pure Sobol points. Numeric-only
alpha geometry does not exercise categorical/conditional behavior; those remain
covered by the sealed QMS-02/08 mixed-schema fixtures. Group decomposition and
CMA generations are recorded as not exposed, not fabricated as measured values.

The four warm sample sets are fully retained in the public receipt. First-public
two-fold warmups are 7.298 / 5.875 / 5.611 / 5.549 s respectively. These small
engineering lanes do not estimate a 600-trial economic tournament's cost.

### Witness Diagnostic

Separate `cProfile` execution takes 30.631 s on the registered first two
folds/64 attempts and preserves the original native params. Its latency is not
inserted into the ordinary timing table. Measured owners:

| Owner | Calls | Inclusive profiled time |
|---|---:|---:|
| `ResultMetricAdapter.observe` | 162 | 19.673 s (64.23% of profiled wall) |
| Canonical `digest` | 1,391 | 7.295 s |
| Canonical recursive `wire` | 1,168,856 total | 6.996 s |
| UTC conversion | 1,147,431 | 4.674 s |
| `market_signature` | 162 | 0.849 s |
| Existing financial `full_report` | 162 | 0.528 s |

These inclusive spans are **nested and must not be summed**. The 162 original
observations contain IS and 32 forward-panel evaluations; the 1.709 s forward
observer timer does not cover the heavy per-IS timestamp/hash work. The source
rebuilds the UTC/ISO calendar witness for each original result, recursively
canonicalizes it, and hashes market input again. This is a confirmed practical
bottleneck in this diagnostic, not a financial-kernel error or a slow Ridge fit.
It is not valid to extrapolate profiled seconds into exact 28-fold savings.

Proposed next optimization, awaiting approval: reuse immutable exact calendar/
market witness material per compatible fold through the existing prepared WFO
context. Preserve canonical witness bytes, full eligible pools/forward labels,
RNG, metric provenance and financial outcomes; do not drop audit information or
reduce the study budget to make the benchmark look faster. No such core patch
is included in this review.

### What Earlier Phase Speedups Mean

QMS-07's matched optimization of the previous **enabled meta implementation**
remains valid: reference-meta p50 2.743 -> 1.916 s (-30.2%); prepared/meta Rust
2.329 -> 1.425 s (-38.8%). It never meant meta adds no cost to a disabled run.
That synthetic daily engineering fixture uses six folds/six trials and an
explicit one-origin support override, unlike this real hourly/default-support
review. Comparing its seconds directly with the table above is invalid.

The sealed QMS-02 small sampler fixture has TPE/MTPE/CMA/Sobol totals
360.952 / 353.233 / 374.030 / 359.537 ms; CMA then costs 3.62% more than legacy.
The real numeric fixture shows a different ordering. Both are scoped results;
neither justifies universal best-sampler routing. Existing high-dimensional
Rust fits can lose to BLAS; language alone is not a promotion gate.

## Economics And Interpretation

| Continuous OOS account | Native/off | Active meta/Rust |
|---|---:|---:|
| Final equity | 29,600.73 | 34,812.73 |
| Total return | 48.00% | 74.06% |
| Sharpe | 0.889 | 1.191 |
| Max drawdown | 19.29% | 14.27% |
| Trade metric | 368 | 358 |

These are actual original-account results, not mean fold Sharpe. The learned
selector changes params in 15 supported folds. Do not infer universal edge,
pristine holdout evidence or live certification from this historically exposed
alpha/sample. There is no recipe/model retuning or budget increase after outcomes.

Saved independent-reset paired fold metrics are analyzed separately:

\[
R_k=D_{a,k}-D_{m,k}=(I_{a,k}-I_{m,k})+Q_k,
\qquad Q_k=F_{m,k}-F_{a,k}.
\]

All 28 calendar folds have paired-valid original metrics, no omitted undefined
months. First 13 decisions are native fallback and have R=Q=0. The 15 consecutive
supported learned decisions run from February 2023 to April 2024:

| Paired estimand | Observed mean | Descriptive 95% block interval |
|---|---:|---:|
| Decay reduction R | 3.132 | [1.865, 4.773] |
| Actual forward-Sharpe difference Q | 1.001 | [-0.155, 2.516] |
| Native-minus-meta IS Sharpe | 2.130 | Decomposition only |

The preregistered moving-block bootstrap uses three-month blocks, 4,096
resamples and seed 731. Across all 28 months, means are R=1.678 and Q=0.536;
do not substitute these diluted means for the 15 learned-fold estimand.
Supported R is positive in 13/15 folds but Q in only 9/15. Worst observed Q is
-4.100: the predicted Q floor is not a guarantee about realized OOS.

R=3.132 includes 2.130 from accepting lower IS Sharpe and 1.001 from higher
forward Sharpe. Consequently lower decay alone is not proof of better OOS.
The Q interval includes zero. Actual continuous equity improves in this sample,
but **robust future superiority is not certified**. Monthly Sharpe can be noisy;
the intervals are descriptive research uncertainty, not independent folds,
a pristine locked sample, actual live evidence or removal of prior exposure.

## Debt And Next Decision

| Item | Current disposition |
|---|---|
| Real ETH parameter application/continuous account | Verified; fixed replay maximum difference zero |
| Real ETH shadow compatibility | Verified; full proposal/params/account equality |
| Real ETH Rust/reference sequence | Verified; decision/raw-metric/account parity, max account difference zero |
| Original-result hourly meta scoring/witness cost | Confirmed material overhead; per-IS UTC/canonical witness reuse requires an approved lossless patch |
| Primary BTC empirical/live certification | Not supplied by this ETH review; no universal gain claim |
| W3 reactive/reset-flat meta | Still explicitly unsupported; future owner-approved integration |
| Public candidate activation/version/platform matrix | Owner/remote decisions remain pending; no release action |
| Configured/observed thread telemetry and high-d Rust/BLAS dispatch | Inherited QMS-07 debt remains; a faster small kernel is not full-workload closure |

The real ETH run closes the previously unexecuted functional lineage check
for this chosen cell, exercises default support/guard/fallbacks and quantifies
cost on a genuine hourly strategy. It does **not** close the guide's primary
BTC scientific acceptance, live-clock/fill certification, optional W3 or remote
platform/public-version decisions. The sealed QMS-08 NOT_RUN status is retained
as historical; this supplement is a new scoped receipt, not a rewritten gate.

Generated `exit_price` is not passed to the pct-equity target-series endpoint.
Accordingly this review does not certify intrabar stop fills or venue funding,
queue, margin or live data-readiness semantics. Historical replay clock fields
are not proof of observed-live readiness. These scope distinctions preserve
the existing alpha/account baseline instead of silently changing its economics.

## Reproduce Privately

Use the existing pool-alpha environment for the approved hot loader, then the
QMS-08 installed private pair. Full alpha/data/params/witnesses stay under the
existing ignored `data/local/qms-real-review/` directory.

```bash
/root/bobby/pool_alpha/.venv/bin/python tools/qms_real_review.py prepare
.maturin/qms08/qualified/cp312/pair/bin/python tools/qms_real_review.py worker --kind meta --arm off
.maturin/qms08/qualified/cp312/pair/bin/python tools/qms_real_review.py worker --kind meta --arm active_rust
.maturin/qms08/qualified/cp312/pair/bin/python tools/qms_real_run_remaining.py
.maturin/qms08/qualified/cp312/pair/bin/python tools/qms_real_fixed_replay.py
.venv/bin/python tools/qms_real_evidence.py --check
.venv/bin/python -m pytest -q tests/test_qms_real_review.py tests/test_qms_real_evidence.py
.venv/bin/python -m tools.qms08_gate --check
```

The queue preserves already-completed same-registration lanes; failures stop
advancement. An interrupted process is checked for actual liveness before any
restart. Do not overwrite completed evidence, broaden data/recipes after
outcomes, or reinterpret profiling/repeated runs as additional market origins.

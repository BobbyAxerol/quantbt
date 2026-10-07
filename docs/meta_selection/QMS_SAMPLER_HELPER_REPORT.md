# Optional Sampler Helper: Implementation And Diagnostic

Date: 2026-10-07. Scope: **COMPLETE_LOCAL**, opt-in API, no push or release.
Plan: [QMS-SH01](../../upgrade/implement.md#qms-sh01).
Usage: [Sampler-Space Helper](SAMPLER_SPACE_HELPER.md).
Machine-readable evidence: [sealed summary](../../benchmarks/optimization/meta_selection/qms_sampler_helper_evidence.json).

## What Changed

`quantbt.optimization.prepare_sampler_space` reuses the existing schema and
sampler factory. It reports static numeric, conditional, categorical and fixed
parameters; prepares reusable config; and supports explicit schema, condition,
fixed-value and sampler overrides. The caller remains responsible for whether
numeric distance is meaningful for the strategy.

Default behavior preserves ranges. Explicit declarations convert regular
integer enumerations to **exactly the same supported values**, without expanding
the domain. String/boolean modes are never converted to ordinal numbers;
irregular integer support is rejected. Float enum conversion requires a
deliberate caller schema override. Incompatible requests raise, unless the
caller explicitly requests a compatible TPE recommendation. Explicit sampler
overrides are never silently replaced.

The helper is not called automatically by WFO/meta. It does not inspect an
alpha, execute a strategy, read market data, consume RNG or fit a model. It
cannot infer objective smoothness, structural flags or expected future returns.
Existing endpoints, objective/selection mathematics, financial kernels, native
capabilities and meta activation remain unchanged. No Rust rebuild was needed.

## Test Results

- **25 helper cases PASS:** exact support/types, no ordinal coding or mutation,
  fixed/log/conditional overrides, factory recipes, no global RNG changes,
  actual helper/manual proposals and public meta off/shadow/active parity.
- **184 affected cases PASS:** helper plus existing QMS-02 sampler, QMS-05 public
  integration and PRE04 conditional-Sobol public tests. Experimental Optuna
  warnings remain visible; no tolerance or estimator was relaxed.
- **21 diagnostic studies, 10,752 attempted trials:** no failed trials. TPE
  duplicate pruning remains enabled; retained counts include those attempts.
- **Six helper/manual comparisons EXACT:** proposals, objective values,
  selected params, per-fold raw measurements, positions, returns and equity.
- **21 independent stitched-account replays EXACT:** no artificial fresh-account
  resets at forward fold boundaries.
- **Wheel and sdist installed consumers PASS:** all 261 Python/typing members
  match current canonical source. Each isolated CPython 3.12 consumer runs 128
  public pct-equity trial attempts, compares helper/manual accounting and
  verifies original parameter types and optional meta configuration.

Unit fixtures freeze only instrumentation/availability clocks and warm loaded
math libraries before exact provenance comparison; financial scorer/history/
learner/selection execute normally. Early failing tests and the first consumer
failure are retained. The consumer failure was an overly broad origin check
that incorrectly rejected installed site-packages under the repository, not
a package import or financial error. The corrected proof uses a fresh lane.

## Registered Comparison

Before outcomes: unchanged private Delta RSI on sealed ETHUSDT 1h history,
2020-2022; four quarterly 2022 forward windows; rolling 365-day IS; seeds
731/732/733; 128 attempts per fold; no early stopping, warm start or retune.
Public Mode 4/per_fold_causal selects on IS only; **meta is off** throughout.
The second alpha is the [public MA example](../../examples/wfo_sampler_space.py)
on a fixed 1,096-bar daily synthetic tape, with the same schedule and budget.

Raw metrics below come from selected candidates re-evaluated using the original
`pct_equity` account and original annualization. Decay here is the descriptive
raw IS Sharpe minus raw forward Sharpe, not a replacement of the WFO objective
or QMS label estimator. Unsupported/flat measurements are retained as undefined,
not coerced into zero. Paired comparisons use only common valid observations.

## Delta RSI Results

The existing private strategy already exposes eight genuine numeric dimensions.
Therefore the helper makes the intended CMA setup easier/safer; it does not
change correctly written numeric CMA configuration.

| Arm | Median Final Equity | Mean Raw IS Sharpe | Mean Raw Forward Sharpe | Mean Raw Decay | Median Study Time |
|---|---:|---:|---:|---:|---:|
| Manual numeric CMA | $30,252.77 | 2.6841 | 1.7624 | 0.9217 | 38.290 s |
| Helper numeric CMA | $30,252.77 | 2.6841 | 1.7624 | 0.9217 | 39.366 s |
| Numeric legacy TPE | $21,937.51 | 2.8423 | 0.9509 | 1.8913 | 48.638 s |

All 12 seed/fold observations are valid, but they cover only **four distinct
market forward windows**, not 12 independent origins. CMA decay is about 51.3%
lower in this bounded comparison. That is evidence about **different search
algorithms in this registered experiment**, not a helper-created return uplift.

| Seed | CMA Helper/Manual Equity | TPE Equity |
|---|---:|---:|
| 731 | $31,661.32 | $21,937.51 |
| 732 | $25,863.58 | $21,907.93 |
| 733 | $30,252.77 | $24,338.19 |

The original private account remains sealed, including its legacy-fee
compatibility mapping. Costs were not changed to obtain these results. No
private source, data, ranges or winning parameters are published in the report.

## Additional Public Alpha

MA windows originally supplied as categorical integer enumerations can be
explicitly declared numeric while preserving support. This enables joint CMA
geometry across both windows and both continuous thresholds. Direct mixed CMA
keeps the two windows independently sampled under its explicit policy.

| Arm | Median Final Equity | Independent Sample Calls Per 512-Attempt Run | Median Study Time |
|---|---:|---:|---:|
| Manual numeric CMA | $22,781.70 | 16 | 12.119 s |
| Helper numeric CMA | $22,781.70 | 16 | 12.089 s |
| Numeric TPE | $21,874.23 | 2,048 | 16.354 s |
| Explicit mixed CMA | $22,957.20 | 1,032 | 12.519 s |

The helper avoids **1,016 extra independent calls** relative to mixed CMA in
this example; 16 numeric startup calls remain. Mixed CMA still has 508 relative
proposal trials for its continuous subspace, so it is not purely random search.
The warnings and independent/relative telemetry are not hidden.

Mixed CMA has slightly higher median equity and wins in two of three seeds;
the helper is **not uniformly economically superior**. On the six common valid
observations, helper forward Sharpe averages 2.9379 versus mixed CMA 2.3395,
with decay -0.7014 versus -0.0979. On seven common helper/TPE observations,
forward Sharpe is 2.7097 versus 3.1288 and decay -0.5165 versus -0.5587. These
small, partly flat-window samples do not justify a general superiority claim.
All missing/undefined cells and per-seed outcomes remain in the sealed receipts.

## Cost, RSS And Package Scope

Helper configuration costs **1.2-2.6 ms once per study run**, not per trial or
fold. It performs no extra financial evaluation or Python/Rust call. Full-study
times above are observational, with cold/warm order and host effects; they are
not an isolated repeated latency gate or proof of a kernel speedup. Comparing
different proposal sequences cannot certify same-work execution speed.

Same-process absolute peak RSS rises from 320.39 to 399.11 MiB during the real
alpha studies and stays at 399.11 MiB throughout the subsequent public studies.
This is an allocator/JIT/cache high-water measurement, **not isolated per-arm
RSS**. It does not establish a helper memory advantage or attribute all retained
memory to the helper.

Local artifacts use the prepared 1.1.2/0.4.3 pair and unchanged sealed native
extension. This focused helper proof does not replace a final E08 integrated
qualification, Ubuntu/CPython matrix or public consumer proof. Older E08
receipts remain historical, not certificates of the later helper addition.

## Cleanup And Conclusion

Only reviewed inactive helper build/consumer scratch is removed; exact
wheel/sdist/native artifacts, source stages, private inputs, raw trial/array
receipts and every failed/successful test/build log remain protected. See the
[cleanup receipt](../maintenance/QMS_SAMPLER_HELPER_CLEANUP.md).

The initial 1 GiB scratch estimate was exceeded: UV could not hardlink from
the cache and copied dependencies; the two lanes showed about 1.70 GiB total
filesystem increase. This operational variance is recorded, not retroactively
edited into the original registration. Future helper-package budget is 2 GiB
plus 5 GiB headroom; completed environments are reclaimed now.

**Conclusion:** the optional helper is software-qualified locally. Its proven
benefit is reliable declaration, compatibility diagnostics, customization and
use of intended CMA numeric geometry without fake ordinal categories. Correct
manual configuration is identical. The bounded Delta RSI comparison favors
CMA over TPE; neither that finding nor the helper guarantees future edge or
meta decay improvement. No new scientific methodology or release was approved.

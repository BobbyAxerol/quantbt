# E04 Real Portfolio Meta On/Off Diagnostic

## Frozen Scope

Unchanged private Gradient/Delta RSI, ETHUSDT/BTCUSDT 1h, 37,968 aligned bars
per symbol (2020-01 through 2024-04); no missing-hour repair. Each strategy
uses its own causal price history and shared params. Original native portfolio
longshort `%_equity` account, 20,000 capital, 0.25 allocation per symbol,
leverage one, one-way fee 0.00025, one-bps slippage and original funding policy.
Mode 4 / per_fold_causal, rolling 365D, 28 monthly forward folds from 2022-01,
128 attempts per fold, seed 731, unchanged TPE recipe and no early stopping.
Financial execution stays the original Numba portfolio authority; Rust-required
QMS numerics do not turn this into an all-Rust portfolio benchmark.

The owner requested real evaluation; the additional universe/protocol does not
have separate formal economic approval. This is research-exposed diagnostic
data, not locked holdout or the guide's complete development/evaluation split.
No results were used to retune alpha, learner, costs, RNG or thresholds.

## Correctness

Same full IS search pool/objectives and native anchor params between arms.
Active uses only past matured outcomes; selected params are actually executed.
IS/forward labels come from original aggregate shared-account results, never
symbol-average Sharpe. Final positions are stitched into one continuous account,
not compounded fold equities. Accepted positions, costs, funding, margin,
turnover, diagnostics and equity match an independent original-account call
exactly; its conformance cost is charged separately, not used for learning.
An additional verifier rebuilds every fold's signal from saved params and the
unchanged alpha, without optimization or fitting. All seven original-account
buffers again match exactly (maximum absolute difference zero). Its cost is
separate and the original primary studies/evidence remain unchanged.

## Observed Effect

| Original OOS continuous account | Meta off | Meta active |
|---|---:|---:|
| Final equity | 17284.6054 | 19670.1242 |
| Return (%) | -13.5770 | -1.6494 |
| OOS account Sharpe | -0.4726 | 0.0049 |
| Max drawdown (%) | 19.7607 | 19.7607 |

28/28 paired-valid folds;
15 valid origins with twelve matured tasks;
15 changed selected evaluations.
Supported mean native decay: 2.621583349631323.
Supported mean meta decay: -0.45332859717005897.
R (native decay minus meta decay): 3.0749119468013815.
Forward Q (meta minus native Sharpe): 0.00945392466469949.
IS contribution: 3.0654580221366823.
Intervals are paired moving-block bootstrap, three months, 4,096 resamples,
95%, seed 731. Forward-Q interval: **[-2.0571, 1.9639]**.
Read exact bounds in the [sanitized receipt](../../benchmarks/optimization/meta_selection/qms_e04_real_diagnostic_v2.json).
Diagnostic R > 0 / lower-Q >= 0 threshold: **False**.
Lower IS alone is not better forward performance. Undefined windows are not zero.
IS contribution / point-mean R: **99.69%** (arithmetic decomposition,
not causal effect attribution). Read it together with the forward-Q interval.
A different continuous-account outcome is not statistical certification of
better future Sharpe or a profitable alpha.

## Cost And Decision

Off: 786.289 s, peak RSS 428.7 MiB.
Active: 885.919 s, peak RSS 432.4 MiB.
Measured added latency: 12.67%; added peak RSS:
3.74 MiB. These are observations,
not a guaranteed overhead bound for other alphas/domains.
One cold public call per arm on a shared VPS, single worker/numeric thread;
after imports and causal-alpha probes, with no financial endpoint warmup;
not repeated medians or a kernel benchmark. Observer attempts:
459. Evaluation and learner timings stay separate
in the receipt. Costs include the original post-seal labels, not free inference.
The original portfolio `num_trades` metric counts quantity changes (and its
initial-column convention), not completed alpha round trips. Equity sizing can
resize units without a direction change. No metric definition was replaced.

**NOT PROMOTED.** Diagnostic success or failure does not replace owner approval
and locked evaluation. E03-G01 remains open without scientific repair approval.
Real quarterly basis has separate expiry/roll/data coverage requirements.
Current-source remote matrix and public index are not certified here.
Read [software/artifact scope](QMSE04_REPORT.md), [the plan](../../upgrade/implement.md#qms-e04)
and [cleanup](../BUILD_TEST_CLEANUP.md). Private alpha, params, data and raw
witnesses remain ignored. No push, merge, tag or upload was performed.

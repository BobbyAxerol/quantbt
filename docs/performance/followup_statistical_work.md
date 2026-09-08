# Shared Statistical Work Follow-Up

This is an implementation optimization, not a new WFO methodology. Public
endpoints, financial execution, split schedules and selection policies remain
unchanged. Future mathematical methods remain open research decisions; the
[architecture rules](../../AGENTS.md) require efficient shared ownership and
explicit contract extensions, not a prescribed model family or objective.

## Changes

- `ReportMetricObjective` reads one report per invocation, reusing that snapshot
  for display metrics and required objective values. Missing required metrics
  still raise. Aliases, margin/rejection diagnostics, constraints, metadata,
  `scope` and `trading_days` retain their existing behavior. No result is cached
  across invocations, so a later changed result cannot reuse stale metrics.
- With `use_numba=True`, stationary bootstrap index construction now compiles
  the existing scalar loop. Both paths use NumPy's `default_rng(seed)` Generator,
  including interleaved restart draws. No new RNG, parallel draws, fewer
  replicates, iid substitution, or altered return/Sharpe reducer is introduced.
- The statistical loop lives in a focused optimization module, outside the
  financial engines and Rust bridge. No cross-language transfer per random draw
  is needed. `use_numba=False` and unavailable-Numba fallback remain supported.

Stationary and stress simulation use this index path. Regime-conditioned and
GARCH generation are unchanged. This does not add a scalar Rust substitute for
Mode 2's required path-based evaluation or enable unsupported reactive Mode 2.

## Matched Measurements

Baseline implementation: `ac69e76`. CPython 3.12, Linux x86_64, seven alternating
before/after pairs, a fresh child process per lane, one compute thread. The
report baseline is loaded from the pinned Git source; the bootstrap baseline
uses the same reference loop with compilation disabled only for indices.
Both lanes keep the compiled Sharpe reducer enabled. Each public Mode 2 run
creates a new study; no completed candidate result is reused.

| Work | Before | After | Interpretation |
| --- | ---: | ---: | --- |
| Stationary bootstrap: 2,000 observations x 200 replicates | 376.686 ms | 10.310 ms | Warm index construction plus unchanged Sharpe reduction |
| Report objective: 2,000-hourly-bar account, five evaluations | 7.304 ms/evaluation | 2.104 ms/evaluation | Same required/display metrics and values |
| Mode 2 global: 2,000 daily bars, four trials, 32 replicates | 1.147 s | 0.657 s | Fresh public study, same selected params/account |
| Child-process peak RSS across these operations | 223.613 MiB | 224.137 MiB | No memory-reduction claim |

Ratios of the displayed medians are approximately 36.5x, 3.5x and 1.74x,
respectively. The first number is **not** whole-WFO throughput. Seven pairs are
local performance evidence, not a general guarantee or a multi-platform release
certificate. Compilation/cache loading occurs before warm measurements; each
child's first bootstrap call is retained separately in the raw artifact. Input
size, sample count, requested reports and account calculations are identical.

The final measurements use clean source `0e8776d` and the unchanged certified
native extension `dbe336b9...de7de` on both lanes. Full source/build identities
are in the [raw paired artifact](../../benchmarks/native_event/results/followup_statistical_work.json).
The default report-objective fixture reduced full-report invocations from five
to one; this count, not a dropped metric or a result cache, explains the gain.

## Callback And Native Review

Existing generic callback optimizations were retained and regression-tested,
not counted as new work or speedups. Python strategy decisions remain Python
unless the strategy uses a supported native/numeric protocol.

A rebuilt Rust wheel experiment hoisted the immutable risk-free division and
inlined `OnlineMetricReducerV2.observe`. Seven alternating wheel pairs on the
20,000-bar direct-target fixture passed accounting parity but measured prepared
score medians of 1.836 ms before and 2.014 ms after. The experiment was rejected;
both native source and the original installed wheel were restored. It is not
part of the delivered package. The [wheel experiment artifact](../../benchmarks/native_event/results/followup_native_metrics_experiment.json)
records wheel hashes and native module identities. Direct-target Rust score
still trails the narrower Numba kernel; no claim of complete optimization is made.

## Verification And Reproduction

Independent tests compare full index matrices across seeds, block lengths and
edge sizes, then compare Generator state after the run. Public compiled Sharpe
outputs match bit-for-bit when only the index implementation changes. Report
tests verify single extraction, alias handling, missing metrics, constraints,
empty display lists, and fresh extraction after result mutation. The benchmark
requires exact bootstrap and selection/accounting hashes for every pair.

```bash
.venv/bin/python -m pytest -q tests/test_followup_statistical_work.py
.venv/bin/python benchmarks/native_event/benchmark_followup_statistical_work.py \
  --pairs 7 --output /tmp/quantbt-followup-statistical.json
```

The script records raw per-process times, peak RSS, selected parameters, source
hashes and exact output hashes. It does not change a notebook, strategy, seed,
optimizer schedule or installed package. The ordinary callback and native
direct-target review are tracked separately in the implementation plan; these
statistical results are not evidence of callback or Rust-kernel speedups.

Final local release regression: **1,384 passed, 25 skipped across 24 isolated
shards**. Optional-environment skips and the release profile's exclusions for
private alpha/real-data suites are not claimed as passes. Clean wheel/sdist and
editable consumer checks passed on CPython 3.12, including direct-target and
public callback/WFO smokes. The exact rebuilt core artifacts are bound in
[`next03_product_qualification.json`](../../contracts/next03_product_qualification.json).
The inventory tool also now classifies new canonical modules using the frozen
retirement ledger, without requiring new root mirrors. Public API and execution
contracts are unchanged. Remote version-matrix certification and publishing
remain separate, unperformed release actions.

# MET-03 Owner Recheck

This is the preserved correctness recheck. The latest
[copy/cost closure](MET03_COPY_COST_REPORT.md) follows the historical
[reporting performance pass](MET03_PERFORMANCE_REPORT.md). These recheck
receipts remain unchanged and certify only their recorded source.

**COMPLETE_LOCAL.** Owner requested an additional audit on 2026-10-07.
Source fixes commit `3e6ae7d`, starting parent `ffdda97`; no financial/scientific
changes, private alpha/data, native rebuild, push, CI, merge, tag or publication.
The [phase registration](../../upgrade/implement.md#metrics-met-03) and G01..G05
govern the pass. Previous receipts are historical and unchanged, not rewritten.

## Findings And Corrections

The preregistered independent repro produced **20 failures / five passes**.
These were real reporting defects despite the previous 598-test PASS:

| Defect | Before | Corrected behavior |
|---|---|---|
| Timestamp resolution | `DatetimeIndex.asi8` assumed ns even for s/ms/us indices; valid paths failed scope filtering | Normalize UTC to ns explicitly; completed index stays unchanged |
| Missing clocks | Integer NaT sentinel could enter typed snapshots | Reject missing clocks before scope filtering and in all timestamp snapshots |
| Partially closed action | Open-action realized PnL counted only still-open legs, omitted closed legs/shared cost | Sum recorded realized net across all members of the unfinished action plus its shared adjustment once |
| Missing valuation witness | Closed-looking ledger could imply open PnL zero at an unobserved report end | Open PnL and open count require exact scope-end valuation; absent/mismatched witness is N/A |
| Holding-bar display | Mean 1.5 bars formatted as integer 2 | Retain fractional bars and unit; only actual counts are integer-formatted |

Action fixture: closed ETH leg +10, open BTC leg -1 realized and +3 unrealized,
recorded shared cost -2. Correct open-action realized PnL is **+7**, unrealized
**+3**, open action count **1**, closed action count **0**. The independent
trade population still reports +10 closed-trade PnL and -1 open-trade realized
PnL. Trade/action populations are alternative units, never additive controls.
Missing gross/cost allocations produce metric-specific N/A without erasing
valid closed counts or unrealized observations. Matched empty coverage is zero;
an unmatched empty-looking population is not certified zero.

The live dictionary also now lists actual `reporting.period.*`,
`reporting.closed_trade.*` and `reporting.closed_action.*` IDs rather than
proposal-style aliases. This corrects documentation, not the accepted formulas.

## Regression And Artifact Proof

- New targeted cases: **69 PASS**, including 12 resolution/timezone combinations,
  open-action/cost/valuation cases, NaT validation, fractional formatting and
  40 independent randomized drawdown cases with negative equity, unequal clocks
  and explicit recovery tolerance. Python/Numba metrics and episodes agree.
- Complete metrics/oracle/QuantStats/scope/schedule/event/native-result suite:
  **667 PASS, zero failures/skips**, 89.55 seconds. Financial arrays/trace/raw
  metadata, legacy dictionaries, scientific objective/selection and RNG
  sentinels remain exact; no financial replay occurs.
- All 325 original source guards pass: 321 exact byte hashes and four exact
  legacy AST/cold-surface comparisons. Only reporting modules changed.
- New wheel and sdist consumers PASS outside checkout, dependency checks PASS,
  all **275 package modules** byte-equal to final source. Installed consumers
  additionally exercise s/ms/us/ns indices and unfinished-action PnL.
- Unchanged native 0.4.3 identity is reused, not rebuilt. Local CPython 3.12 only.
  The primary tooling environment remains untouched.
- Original successful/failed receipts, their referenced evidence and original
  wheel/sdist are hash-verified unchanged by the new closure.

Exact new core artifacts are retained under
`.maturin/met03/run-20261007T204118067245Z/dist/`:

| Artifact | SHA256 |
|---|---|
| `quantbt_engine-1.1.2-py3-none-any.whl` | `4d6fbf2a3df50e7bcbf339296ea6483c36bd828d0f5dcd409dfefefa3c8534f5` |
| `quantbt_engine-1.1.2.tar.gz` | `a756cc38190ada14c45d7664c2bf2538c6f86dcf626f6198c24790a5ae47b52f` |

## Reporting Cost Recheck

Twelve fresh matched cost cells, one thread, one warmup/five repetitions, same
sizes/outputs as MET-03. These are report costs, not backtest/WFO speedups.
The host is not exclusive; independent stage measurements are not additive.

| Observations | Python p50 / p95 | Numba p50 / p95 | Python / Numba peak RSS |
|---:|---:|---:|---:|
| 2,000 | 11.162 / 12.441 ms | 2.647 / 3.198 ms | 200.70 / 304.49 MiB |
| 100,000 | 348.405 / 532.890 ms | 38.844 / 42.307 ms | 173.73 / 270.63 MiB |
| 1,000,000 | 3.662 / 3.915 s | 440.632 / 481.093 ms | 339.62 / 426.18 MiB |

The 1M Numba public median is higher than the prior 326.657 ms receipt; retain
this observation rather than claim a speedup. Its snapshot stage was
281.486 -> 289.567 ms, warm reducer 26.758 -> 27.649 ms, and cache public call
301.391 -> 309.678 ms. Full call timings include adaptation/serialization and
vary with host scheduling; these measurements alone do not assign the entire
difference to a code change. No repeats, tolerance or outputs were changed.
All workers remain under the registered 2 GiB RSS cap. Timing acceptance is
owner review, not a new numeric gate invented after the run.

## Cleanup And Handoff

Owned `/tmp/quantbt-met03-b85co6gr`, `/tmp/quantbt-met03-ovyrob6y` source/build
consumers and `/tmp/quantbt-met03-review-repro` are removed. Keep old/new exact
artifacts, logs, XML, source, private data, primary environment and offline cache.
The installed lane peak was 14,886 concurrent files / 694,093,140 apparent bytes,
below 20k / 3 GiB. Its final cleanup recovered **13,033,472 actual bytes**;
1,373,271,846 apparent lifetime bytes are not a claim of freed disk space.

No additional reproduced in-scope calculation, compatibility or raw-mutation
blocker remains after the recheck. This is not proof that every possible bug
or every repository debt has disappeared. Known boundaries remain explicit:

- Missing complete raw ledger/action identity/valuation cannot produce guessed
  closed-action statistics; automatic execution-ledger attribution is separate.
- Rust Reporting V1, flow-adjusted returns and new financial-domain semantics
  are not implemented by this metrics program; native scientific V2 is unchanged.
- Reporting timing/optimization headroom remains measured, not universally solved.
- Owner acceptance, remote CPython/Ubuntu matrix and public release qualification
  still require separate approval. No new methodology or trading-edge claim.

Evidence: [failed repro](evidence/met03/review-repro-20261007.xml),
[focused PASS](evidence/met03/review-focused-20261007.xml),
[full source/benchmark receipt](evidence/met03/run-20261007T203616400281Z/receipt.json),
[installed receipt](evidence/met03/run-20261007T204118067245Z/receipt.json),
[new immutable closure](evidence/met03/review-closure.json).

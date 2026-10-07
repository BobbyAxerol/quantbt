# QMS-E06 Intrabar Intent/Session Qualification Report

## Conclusion

**COMPLETE_LOCAL_SOFTWARE_QUALIFIED_OPT_IN**, 2026-10-07 UTC.
Bounded single-symbol intent/session WFO with optional meta is locally qualified
under the [owner-approved scope](QMSE06_QUALIFICATION.md), through the existing
endpoint and adapter. No financial kernel, estimator, Ridge mathematics,
sampler trajectory, endpoint signature, native wheel or default was changed.

Read the [source-bound receipt](../../benchmarks/optimization/meta_selection/qms_e06_closure.json),
[usage](EXECUTION_WFO.md) and [unified E06 plan](../../upgrade/implement.md#qms-e06).
The original [execution receipt](EXECUTION_WFO_REPORT.md) stays historical.
E06 is not a new optimizer or another account simulation engine.

| Dimension | Result |
|---|---|
| Software | PASS_LOCAL; 124 distinct source tests, zero unexpected skip |
| Actual mature meta | PASS; fit artifacts/predictions/applied selection, not cold fallback |
| Financial owners | Python oracle/Numba/Rust parity; mature WFO intent-only/session on explicit Numba and Rust |
| Installed artifacts | PASS_LOCAL; two independent consumers, 12 full-work cells, 32 rerun tests |
| Runtime/build source | All 322 files unchanged; all 260 canonical installed package files checked |
| Cost | Registered descriptive measurement; no latency waiver or universal speedup claim |
| Empirical | Public synthetic point result only; real-market study NOT_ASSESSED, NOT_PROMOTED |
| Default/publication | Meta remains opt-in; no push, CI, merge, tag or publication |
| Cleanup | PASS; two new inactive consumers removed, evidence/artifacts retained |

## What Was Completed

The bounded adapter already existed. This phase completes its accepted-scope
qualification, rather than rewriting execution:

- Stable `QuantBTEndpoint.walk_forward(execution_endpoint=financial,
  target_mode="intrabar", ...)` and typed `WfoExecutionWindow` are unchanged.
- Entry/intent/session calendars and indicator warmup retain original causality.
  IS and forward diagnostics use separate reset-flat original accounts.
- Final chronological intents execute on one continuous account. Neither fold
  equity concatenation nor a precomputed effective-position proxy is used.
- Long and short entry-bound SL/TP survive fold changes. Pending next-open
  entry survives the boundary. Session IDs remain globally stable; session
  quotas are not reset just because another fold starts.
- Explicit dynamic per-bar trailing retains its existing update contract.
  Changing fold params alone is not an implicit order amendment; an emitted
  trailing update is an actual intent, not a claim of immutable trailing.
- Direct/prepared and minimal/audit preserve equity, returns, positions, fees,
  funding and margin. Repeated prepared runs start independent accounts.
- Active meta executes the actual selected params. Shadow preserves the
  complete original search table, params, RNG and account buffers.

No blanket arbitrary grid/DCA, shared cross-margin, multi-symbol intrabar,
tick/L2 realism, nested execution-domain Mode 1 or Mode 2 bootstrap is certified.
Caller-owned alpha/feature causality remains the caller's responsibility; these
tests do not prove that every arbitrary user strategy has no leakage.

## Tests And Measurement

| Suite | PASS | Coverage |
|---|---:|---|
| Financial/window contract | 71 | Phase 69 oracle/Numba/Rust, Phase 31 timing, typed windows, original account/witness checks, 22 new fold/session cases |
| Mature intrabar no-leakage | 23 | Actual active decisions at three cutoffs, unavailable labels/artifacts, late corrections, physical history/pool order, raw measurements and continuous account |
| Four mature financial families | 16 | Intent-only/session x Numba/Rust, own-family history, active params, off/shadow RNG/search, cached/uncached witnesses, future OHLCV/funding mutations |
| Fail-closed qualification harness | 14 | Missing/failed/skipped work, insufficient history, wrong digest/account/params, observer failures, unsafe cleanup roots |

**124 distinct source PASS.** The initial 22-case smoke is already inside the
71-case suite and is not counted again. The two installed 16-case runs are
reruns, not 32 additional distinct source tests. Three scalar-prepared intrabar
cells are not applicable and were explicitly deselected: this execution account
is not the same-close scalar scorer. Other routes are outside this phase, not
silently certified by these counts.

The mature financial-family histories use the registered public synthetic tape,
90D IS, monthly splits, eight attempted trials, seed 731 and lambda 10.
The matched May 2022 workload has **24 mature origins**, above the unchanged
minimum 12; all four own-family tests independently require at least 12.
Each financial backend/session family builds its own history; no incompatible
history is transferred merely because two numerical results look similar.

Future OHLCV/funding mutations leave the earlier candidate pool, snapshot,
fit, rank and selected params unchanged, while original forward input witnesses
change. Late/future labels do not enter the frozen fit. A permitted historical
correction changes the fit as a positive control, replacing rather than doubling
an origin. Observer labels stay after forward completion plus reporting lag.

Every retained candidate's raw IS/forward Sharpe, activity, sample count,
sample standard deviation and outcome status is checked against the original
full report/return reducer. Original fee/funding/margin buffers remain bound.
No undefined/no-variance/liquidated observation is rewritten into a valid zero.
Final execution rebuilt independently from actual stitched intent has **diff 0**.

## Matched Public WFO Cost

Complete public call on the registered May 2022 synthetic fold: 90D IS,
31-day forward, eight attempted trials, same sealed history and pool. Three
fresh processes per cell, one untimed warmup then one timed WFO call. Wall and
CPU include search, meta/observer work, final continuous account and reports;
endpoint construction, history loading and imports are outside the timed call.
Peak RSS is the whole process, including imports, warmup and later verification.

| Meta | Witness reuse | Median Wall | Median CPU | Process Peak RSS |
|---|---|---:|---:|---:|
| off | off | 191.64 ms | 191.34 ms | 285.53 MiB |
| shadow | off | 365.80 ms | 365.70 ms | 291.76 MiB |
| active | off | 369.00 ms | 368.58 ms | 291.54 MiB |
| off | on | 212.43 ms | 212.43 ms | 284.77 MiB |
| shadow | on | 392.22 ms | 390.89 ms | 291.23 MiB |
| active | on | 348.53 ms | 347.99 ms | 291.05 MiB |

With witness reuse enabled, active costs about **64.06%** more wall than off
and **6.28 MiB** more process peak RSS. Shadow also fits/ranks and collects
forward labels, so it is not a no-work arm. All 18 runs match sealed PRE05 logical
digests, including search/RNG, raw measures, model decisions and accounting.
Witness on/off has exact logical parity. Three samples are descriptive; these
small cells do not establish a systematic cache speedup, a latency quantile
gate, or a whole multi-year WFO estimate.

## Financial Kernel Versus Adapter

Unchanged Phase 69 fixture, **2,000 hourly bars**, three warm repeats, original
financial options and terminal/path parity checked:

| Surface | Median Time | Bars/s |
|---|---:|---:|
| Numba kernel/result, standard | 2.490 ms | 803,097 |
| Rust score, scalar output | 0.145 ms | 13,800,815 |
| Rust compact kernel, typed paths | 0.229 ms | 8,736,869 |
| Rust Python kernel-result adapter, compact | 3.887 ms | 514,590 |
| Rust cold prepare + scalar score | 1.207 ms | 1,656,401 |

Output profiles differ: scalar Rust score is not comparable to Numba's retained
standard result as an apples-to-apples public speedup. The Rust adapter is
about **1.56x slower** than the Numba kernel/result in this fixture. This is a
remaining cold-path cost observation, not a regression introduced by E06 (runtime
bytes did not change). These are financial kernel/adapter timings, not the
public WFO timing table or the full endpoint/report construction time.

## Synthetic Effect, Not Real-Market Promotion

One independently selected active synthetic fold changes the applied winner:

- Decay reduction R: **+2.167831**.
- IS contribution: **+1.314751**.
- Actual forward-Q: **+0.853080**.
- Identity holds: R = IS contribution + Q, using original VALID outcomes.
- Final account equity: off/shadow **19,998.777879**, active **19,998.899352**.
- Shadow retains the native winner and therefore has valid zero applied effect.

This is evidence that the adapter can carry a real selection change into the
actual financial account and measure its effect faithfully. One synthetic fold
is not a persistent decay/forward improvement certificate. Its uncertainty is
**NOT_ESTIMABLE_ONE_SYNTHETIC_FOLD**; no favorable interval is manufactured.
The guide's full registered real-market study remains NOT_ASSESSED here. E04's
negative evidence and E03's inconclusive forward intervals remain unchanged.

## Exact Installed Artifacts

Reused only after exact source/allowlist checks: core wheel and sdist from PRE06,
native 0.4.3 unchanged default/locked release build. Fresh isolated consumers
load runtime only from installed site-packages, check all 260 package files and
the extension SHA, and reject checkout runtime substitution. Both rerun six
full-work cells plus all 16 mature intent/session x Numba/Rust tests.

Local Linux **CPython 3.12.13** proof is not Ubuntu 22.04/24.04 x CPython
3.11-3.13 remote qualification or a public PyPI consumer certificate. The first
installed Numba run compiles its fresh caches; its cold timing is not compared
to the source warm table. No needless native rebuild or package bump occurred.

## Cleanup And Next Steps

[Cleanup receipt](../maintenance/QMS_E06_CLEANUP.md): only two new inactive
consumer environments removed, **1,135.17 MiB** observed free-space improvement,
93 protected artifact/evidence hashes unchanged. Runtime/build source and guide
remain exact. Logs, raw/private receipts, source stage, frozen history, exact
artifacts, G01 tooling and offline cache remain. Removed consumers need fresh
installation before rerun.

E06 has no open correctness/installed-source gap in its accepted local scope.
E07 route-specific qualification and E08 integrated remote/release handoff
still require owner approval. Economic promotion, delivery cash settlement and
previously unadmitted capabilities are separate decisions, not closed by this
software receipt. Public endpoints/defaults remain unchanged.

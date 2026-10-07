# MET-02 Additive Reducers

Status: COMPLETE_ADDITIVE_LOCAL; MET02-T01..T10 PASS, 567 tests, no skips. No public endpoint,
optimizer objective, accounting kernel or existing report default changes.
MET-03 remains separately approved work.

## Contract And Inputs

Follow [V1 definitions](REPORTING_CONTRACT_V1.md) and
[the unified phase](../../upgrade/implement.md#metrics-met-02).
Immutable bytes-backed account/return snapshots carry explicit scope-entry
valuation, UTC clock, observed frequency and a partial-period witness. Missing
days are not filled. Account return/Sharpe, execution counters, closed trade and
closed action are separate namespaces and populations.

The cold adapters read completed account paths or already-attributed Trade
outcomes with explicit matching/net-cost/completeness witnesses. Empty default
`result.trades` does not prove zero closed trades. No fill matching, execution
replay, simulated liquidation/expiry or position-to-trade inference is added.
In particular, testing a recorded settlement outcome does not certify a new
settlement engine. Native V2 counters/costs may be read exactly, independently of
truncated audit details; V2 scientific ratios are never substituted for V1.

## Admitted Reducers

- Account: explicit baseline total return, elapsed/period-count CAGR, declared
  frequency/RF/MAR/DDOF Sharpe, Sortino, Omega, observed-period PF/win/loss,
  arithmetic/geometric mean, Calmar and Ulcer Index.
- Drawdown: deepest versus longest, fractional elapsed durations, recovered
  versus open/censored episodes, observed marks/days and inclusive underwater
  calendar span, explicit ties and recovery tolerance. Details are on demand.
- Closed outcomes: net PnL/counts/PF/payoff/expectancy, win/loss/breakeven, average/
  median/largest, streaks and profit concentration. Action net is reduced across
  all authoritative roster obligations; asynchronous partial closures stay open.
  Separate shared net adjustments are included once. Cost/risk/holding/excursion
  statistics require recorded allocation, synchronized marks and denominators.
- Execution: exact matched-scope counters/turnover/costs, recorded auxiliary
  cost/exposure/margin paths; mean means equally weighted observed marks, not TWAP.

Incomplete ledger, missing IDs/rosters/FX, scoped attribution without boundary
marks, missing risk/excursion or omitted score paths produce explicit N/A/reason,
not zero, timestamp grouping or a rerun. Lifetime closed-in-scope net does not
equal account return for a carried/open population without exact controls.

## Ownership And Performance

Python and lazy Numba (no fastmath or persistent compilation cache) implement
the same reporting V1 kernels. A Rust reporting V1 reducer is NOT implemented;
legacy Rust MetricContractV2 is a different contract. No new Rust build is needed.
NumPy handles vector aggregates; ledger grouping stays a bounded cold-path Python
operation over recorded outcomes. This is not a Rust-only reporting claim.

`ReportingCache` has explicit lifetime, entry and accounted-byte limits, content/
contract/scope/coverage/output/backend keys, oversize bypass, eviction and release.
It retains only report outputs, never market/account/strategy/RNG/trial state.
No new reports are constructed in optimization trials. Public rendering/integration
is deferred deliberately to MET-03, not represented as already complete.

## Qualification

Registered: independent MET-01 oracle/hand fixtures, same-contract Python/Numba
parity, raw/no-mutation and source hashes, seeded public WFO proposals/objectives/
selection/account before/after reporting, missing/truncated/cost/action tests.
Matched 2k/100k/1M mark measurements disclose preparation, first-call compilation,
p50/p95, observations/s, fresh-worker RSS and cache hits separately. They do not
measure execution speedup or change the WFO measurement contract.

Final [source-bound receipt](evidence/met02/run-20261007T192855863510Z/receipt.json),
[JUnit](evidence/met02/run-20261007T192855863510Z/pytest.xml) and
[benchmark](evidence/met02/run-20261007T192855863510Z/benchmark.json).
Protected **325 files** (322 prior production/packaging sources, frozen V1 schema,
independent oracle and hand fixtures) remain SHA256-identical. The local native
extension hash also remains `0aa2c376f106606baa9009853de883cb67927dd24263318c0b72953226adadec`.
Three implementation/test commits: `1171991`, `55b27ba`, `0f005f6`.

| Gate | Covered Behavior | Result |
| --- | --- | --- |
| T01 | Independent account/period/episode/trade/action oracle, hand outcomes and estimator sample counts | PASS |
| T02 | Scope entry, first cost, observed daily/bar, partial/empty, insolvency, cashflow fail-closed, integer time limits, independent scopes | PASS |
| T03 | Deepest/longest/current/recovered, gaps, repeated peaks, censored averages, reporting-only tolerance | PASS |
| T04 | Recorded long/short/scaled/partial/reversal outcome semantics, net costs once, credit funding, risk/holding/excursion coverage | PASS |
| T05 | Authoritative roster, opposite legs, asynchronous closure, shared costs, currency and reconciliation controls | PASS |
| T06 | Recorded liquidation/forced-close/pre-expiry/roll/hedge/settlement outcomes remain reporting inputs, not expanded engine support | PASS |
| T07 | Missing/empty/truncated, no phantom trades, exact execution counters independent of capped audit | PASS |
| T08 | Python/Numba V1 parity, immutable snapshots, bounded cache identity/scope/profile/release | PASS |
| T09 | Legacy/native scientific identity and seeded public WFO proposal/objective/selection/account preservation | PASS |
| T10 | Raw preservation, no replay/hot consumer/import, optional-dependency absence, privacy and cleanup | PASS |

These groups overlap; the total is **567 distinct tests**, including the 322
original source-hash parametrizations. The mature off/shadow/active sentinel uses
the existing public QMS synthetic fixture and real fitted predictions; it is not
economic evidence or a retune of a private alpha. Mode 1/per-fold decay and Mode
4/per-fold causal also compare exact nonzero-objective, traded account runs.
Legacy pct-equity outputs do not retain separate fee/funding series: this absence
is asserted, not patched with fabricated cost rows. Net equity/return/positions,
trial/candidate tables, params and existing reports remain exact.

Intermediate receipts are retained: one ledger FAIL had two fixture-construction
errors; one full FAIL had legacy fixture column names, absent legacy cost fields
and an incorrect expectation that historical imports did not require Numba.
All were fixed in the test setup without relaxing accounting/math tolerances.
Earlier PASS measurements certify their earlier bytes only. The final receipt
includes module/tool/test hashes; no previous receipt is overwritten.

## Measured Cost

Fresh worker per cell, one thread, one warmup and five measured repeats. Scalar
outputs only in **both** backends; episode/population details are optional and
their correctness is covered separately. Times below exclude snapshot preparation
and first-call compilation, which remain disclosed in the JSON.

| Population | Python p50/p95 (ms) | Numba p50/p95 (ms) | Numba Observations/s |
| --- | ---: | ---: | ---: |
| 2,000 account marks | 10.420 / 12.662 | 0.842 / 0.884 | 2,375,610 |
| 100,000 account marks | 353.802 / 426.571 | 3.685 / 4.127 | 27,136,770 |
| 1,000,000 account marks | 4,440.317 / 4,799.177 | 26.456 / 27.056 | 37,798,606 |
| 32 closed outcomes, sparse | 0.882 / 1.661 | 1.071 / 1.581 | 29,886 |
| 2,000 closed outcomes, churn | 10.288 / 15.108 | 8.083 / 10.939 | 247,419 |
| 2,000 mixed-side legs / 1,000 actions | 13.182 / 13.234 | 11.602 / 13.071 | 172,388 legs/s |

Numba is not uniformly better: sparse ledger p50 is slower, and grouping/
attribution remains Python/NumPy in both ledger backends. No automatic backend
selection or latency threshold was introduced. The new reducer is additive work,
not an apples-to-apples speedup of the unchanged legacy report.

Snapshot preparation in the final cells costs approximately 1-393 ms, depending
on size/type. Account Numba first-call compilation plus first report costs
**6.4-7.6 s**, versus warm costs above; cold ledger compilation/report costs about
0.84-1.05 s. This matters for one-off small reports. Cache-hit p50 is roughly
**0.04-0.15 ms**, with approximately **13 KiB** accounted payload per scalar entry;
no input/market tape is retained by the cache.

Primary-worker peak RSS (before invoking the other backend for parity):

| Account Marks | Python Peak (MiB) | Numba Peak (MiB) |
| --- | ---: | ---: |
| 2,000 | 156.4 | 253.4 |
| 100,000 | 166.1 | 256.9 |
| 1,000,000 | 257.4 | 298.9 |

The existing package import floor is about 155-156 MiB in these workers; compiler
memory and immutable snapshot preparation are included in the peak, not claimed
as reducer-only allocations. The JSON separates primary measurement RSS from
the later second-backend parity/cache RSS. No RSS reduction, execution speedup,
universal 1-10 ms claim or whole-package Rust reporting certification is implied.

## Remaining Boundaries

No required unfinished reducer or failing gate remains inside MET-02's admitted
V1 input contracts. Financial raw-data capabilities are still explicit limits:
no guessed matching/action IDs/FX, no scoped attribution without boundary marks,
no multi-leg extrema from separately observed leg maxima, no inferred initial
risk and no missing cashflow valuation adjustment. A producer without these
witnesses receives unavailable fields; expanding engine ledgers needs separate
approval. Existing engine settlement/calendar/portfolio support is unchanged.

MET-03 will connect these optional results to public reports, formatting/charts,
official endpoint/methodology docs and exact wheel/sdist consumers. That phase
has not started. No push, CI workflow, merge, version, tag or publication here.

## Cleanup

[Cleanup inventory and receipt](../maintenance/MET02_CLEANUP.md).
Every qualification scratch directory was automatically removed, including the
reviewed empty exploratory path. Final run retains about 379 KiB of logs/JUnit/
receipt/benchmark (excluding the receipt itself from that measured subtotal).
Source, failed receipts, native artifact, environments and historical caches
remain preserved. Runbook and budget limits are unchanged.

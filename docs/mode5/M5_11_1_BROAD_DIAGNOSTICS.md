# M5-11.1 Broad Diagnostics

Status: **IN_PROGRESS**, owner-approved recovery, 2026-10-10. This report is not
a completed broad landscape, selector/search or economic promotion receipt.

Authority: [unified phase](../../upgrade/implement.md#mode5-m5-11-1),
[effective domain](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#453-diagnostic-domain-không-bị-ép-nhỏ-chỉ-để-rẻ),
[six matrices](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#43-sáu-ma-trận-derived-bắt-buộc-trong-dossier),
[resource contract](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#73-resource-plan-và-tốc-độ-không-làm-hỏng-methodology)
and [scope correction](M5_11_RESEARCH_SCOPE_REVIEW.md).

## Frozen Inputs

- Five unchanged alpha bindings, source and account witnesses protected. Four
  supplied alphas use BTCUSDT; Gradient/Delta RSI uses its original ETHUSDT route.
- Each symbol has 52,608 complete hourly observations for 2020-2025, with no
  missing or duplicate hours and finite OHLCV. The provider is read-only local
  canonical data; ETH reuses the exact retained snapshot. No new download.
- Feature preload begins in 2020. Development is one chronological account path
  from 2021-01-01 inclusive to 2024-01-01 exclusive: 1,095 days / 26,280 bars.
  Annual views do not reset that path. Forward 2024-2025 remains outside the
  diagnostics worker's development file.
- Seed 731. The initial route pilots used one financial worker, one numeric
  thread and a 1,800-second / 2-GiB RSS cap. The owner subsequently authorized
  more runtime and delegated execution: an append-only amendment allows three
  independent financial workers, one numeric thread each, and six hours per
  native pilot. Original capped attempts remain preserved. Economics is the
  priority; these caps are host-safety controls, not a resource-optimization
  gate or permission to shorten the research data.
- Disk was about 25 GiB free with 5.59 million free inodes before work. Scratch
  cap is 1 GiB, retained cap 4 GiB, minimum reserve 5 GiB. Exact scratch is
  `.maturin/mode5-m5111/attempt-01`; inputs/evidence/artifacts are retained.

## Outcome-Independent Proposal Coverage

| Alpha | Effective configurations prepared | Variable axes in registered schema | Explicit branches |
|---|---:|---:|---:|
| A-RSI | 128 | 8 | 1 |
| A-SC | 128 | 4 | 2 |
| A-HMA | 128 | 12 | 4 |
| A-HASH | 128 | 10 | 1 |
| A-VWAP | 128 | 12 | 8 |

These are **prepared configurations**, not 640 executed backtests. Branch-balanced
scrambled Sobol proposals have finite preregistered raw caps. Structural invalid
points, effective collisions and unused proposals remain in the private ledger.
Admission never reads profit, exposure, support or a forward outcome. Fixed and
source-ignored axes are not misrepresented as searched dimensions. This design
does not constitute an exact Sobol-index estimator or whole-space coverage proof.

## Execution And Next Gates

Complete original-account route pilots precede the bulk time/RSS/retention
estimate. HMA/VWAP/HASH use the existing actual-fill feedback compiler and
full Python/Rust accounting/lifecycle parity, not a substituted signal backtest.
All compiler passes must be billed; one nominal configuration can execute many
account passes. Failed/capped pilots remain incomplete, not zero-return samples.
When a workstream completes, its slot may be reused for another independent
native pilot under the retained allocation amendment. The limit remains three
financial workers, never parallel slices of the same chronological account.

The extended original HMA/HASH pilots are now complete. Each is still only the
first registered candidate; its actual paths, lifecycle traces, Python numeric/
fill/selected-event parity and independent fill-account reconciliation are
retained. Terminal active-order parity is being independently supplemented;
the original parity helper did not test that terminal state.

| Original native pilot | HMA | HASH |
|---|---:|---:|
| Financial-driver seconds | 3,014.992 | 2,106.138 |
| Actual account passes, including Python parity | 648 | 539 |
| Actual account-bars | 17,029,440 | 14,164,920 |
| Actual fills | 645 | 758 |
| Closed / boundary-open campaigns | 322 / 1 | 267 / 1 |
| Net account return | +6.88% | +3.12% |
| Daily Sharpe, annualized 365 | 0.445 | 0.377 |
| Maximum drawdown | 8.07% | 6.41% |
| Registered net economic utility | -0.018 | -0.037 |
| Independent accounting difference | 0 | 0 |
| Financial-process peak RSS, MiB | 555.23 | 612.23 |

Both positive returns coexist with negative registered risk/tail utility. That
does not establish absence of alpha edge or a selector failure. Partial rung
fills in HASH are not independent campaigns. The expensive stage is the existing
offline actual-feedback compiler: 3,001.853 / 2,086.002 seconds, not a claim that
one native kernel pass takes 50/35 minutes.

One-point scaling suggests roughly 107/75 serial hours for 128 HMA/HASH points,
but is **not a distribution, bound or reliable ETA**. After this measurement the
owner chose a **small tranche**, not a multi-day full-panel launch: original
indices 1, 2 and 3 per native alpha, separately from retained pilot index 0.
New registrations seal exact requests, one worker per alpha, one numeric thread,
six-hour safety caps, required evidence retention and the unchanged data/account
contracts. The final target remains 128 per alpha. Reporting four points as a
completed broad native panel would be incorrect.

Completed initial pilots on the entire development horizon: A-RSI took 7.498 s
inside the financial driver (two actual account passes, exact array parity);
A-SC took 33.299 s (one callback account run, 140 fills, 70 closed campaigns,
independent accounting difference zero). These are the first frozen discovery
points, not selected winners or sampler experiments. HMA's initial pilot reached
the 1,800-second cap without a final certificate; HASH also reached its initial
1,800-second cap. Both are retained as incomplete execution,
not evidence that its economics are negative. Broad alpha-level results require
all registered points and the additional matrices/probes, not these pilots.

## Verified RSI Development Tranche

All **128/128** registered effective RSI configurations completed and passed
source/request/calendar/array/metric validation on the original ETHUSDT route:
127 new cells plus one identity-verified original pilot reuse. There were no
execution failures, missing cells or zero-exposure paths. Negative outcomes are
retained: 108 positive and 20 negative account returns.

| Whole continuous development metric | Minimum | Median | Maximum |
|---|---:|---:|---:|
| Net account return | -41.50% | +29.37% | +189.62% |
| Daily-frequency Sharpe, annualized 365 | -0.737 | 0.560 | 1.708 |
| Maximum drawdown | 9.91% | 21.42% | 58.96% |
| Registered net economic utility | -0.942 | 0.078 | 1.685 |

These are finite-panel **development observations**, not calibrated forward
results or a method-superiority test. They cover 256 original endpoint/direct
owner account passes and 6,727,680 actual account-bars. The bulk supervisor took
112.127 s; the account-cell elapsed sum including reused pilot was 80.006 s.
Peak financial RSS was 345.93 MiB. This is a work bill, not a benchmark speedup.
Accepted-fill/campaign and fee/funding/turnover ledgers were not retained by this
legacy route: support is **unavailable**, not zero or inferred from signal changes.

The separately registered neighborhood tranche executed **155** complete
development paths at two centers: 76 selection probes and 79 validation probes,
covering all eight active axes, integer-adjacent and three coupled groups, plus
supported covariance proposals for one center. All 155 account returns were
positive; four role-specific rows had negative utility because drawdown/tail
penalties can outweigh positive return. Both centers retain `FRAGILE_CENTER`
under the registered all-probe quality policy, not an "alpha has no edge" label.

Of the 79 validation points, 42 overlap selection effective points. Only **37**
are genuinely new held coordinates (10 and 27 per center); all 37 had positive
return and utility. Reexecuting overlapped adverse points validates repeatability,
not independent confirmation of the adverse basin. Held probes remain on the
same development market, not temporal OOS. One center has schema-only covariance
support; the other has regularized proposal directions, not a measured Hessian.

Private immutable details: `rsi_panel_summary.json`, `rsi_panel_validation.json`,
`rsi_probes_summary.json` and `rsi_probes_held_review.json` in the registered lane.
Annual attribution uses actual prior close marks, not fresh yearly accounts.
Primary utility keeps the existing scope-entry drawdown convention; carried
global-watermark drawdown is a separately named diagnostic, not a formula change.

## Verified SC Development Tranche

SC completed **128/128** registered configurations on the original BTCUSDT Python
callback route: 127 new account runs and one identity-verified pilot. All 26,280
hourly bars / 1,095 development days per configuration remain intact. There are
122 positive, four negative and two zero-return/no-trade paths; the two no-trade
Sharpes remain undefined rather than favorable numerical sentinels.

The retained actual ledgers contain 11,224 fills, 5,571 closed and 82 censored
open campaigns across the candidate runs. Those sums are a computation/support
bill, **not independent trades across experiments**. Independent equity
reconciliation has maximum difference zero; summed campaign/account PnL differs
by at most 3.217e-10 currency units under the unchanged 1e-8 absolute tolerance.
Net returns range -4.85% to +18.21%; defined Sharpes range -0.427 to 1.142.
These are within-alpha development observations, not a cross-alpha ranking.

Supervisor elapsed was 2,402.081 s (about 40 minutes), with 128 original account
passes / 3,363,840 account-bars including reused pilot. Peak financial RSS was
611.83 MiB. No time/economic-quality stop filtered the panel. SC stress, actual
sampler/search contrasts and transfer remain separate work.
Private summary and validation: `sc_panel_summary.json`, `sc_panel_summary.md`
and retained original shard receipts.

SC's registered multi-center neighborhood work now completes **58/58** actual
paths, covering all four active axes and supported same-branch covariance
proposals. Both centers retain `FRAGILE_CENTER`: tested quality survival is
78.57% at the first center and 86.67% on validation at the second. All probe
account returns are positive (+0.87% to +19.99%), but minimum utility is -0.0862.
Positive return is not equivalent to a risk-qualified basin.

Selection and validation have effective-coordinate overlaps. Each center has
eight genuinely distinct held coordinates; repeated paths are dependent
repeatability checks, not independent confirmations or temporal OOS. No
undeclared coupled group or covariance/Hessian interpretation was invented.
The tranche bills 58 account passes / 1,524,240 account-bars, 1,045.753 s of
financial-cell elapsed and 1,105.048 s of supervisor elapsed. All workers are
reaped. Ledgers retain 3,928 actual fills, 1,936 closures and 56 open campaigns;
these sum alternative candidate runs, not independent financial observations.

VWAP's first extended pilot failed before accounting because its original alpha
requires an explicit input even when that dimension is structurally inactive.
The effective search representation had omitted it. This is an input-binding
failure, not no-trade/negative economics. Recovery must retain the original
proposal, restore only a source-bound registered raw input, prove the effective
identity unchanged and create a new lane; no module default or favorable
replacement candidate is permitted.
The owner has approved restoring the required constructor input from the original
sealed economic config **only when the time-stop dimension is inactive**. A separately
registered recovery must prove strict constructor coverage, unchanged effective
IDs and behavior, and full financial parity. The failed attempt remains retained;
this approval alone is not a passing recovered account run.

## Cold Measurement Verification

`tools/mode5_research/panels.py` ingests original caller-sealed paths/requests,
source and data witnesses; it does not execute/replay an account or reconstruct
an opaque execution key. The 128 real RSI paths yield 512 verified whole/annual
rows. Annual monetary PnL sums reconcile exactly; wealth-product residual is at
most 4.4409e-16. All 857 original/current-knowledge identities were checked.

The primary scope-entry and diagnostic carried-watermark drawdowns differ in
145 annual rows. Both have explicit valuation/contract identities. Preserving
this distinction avoids changing the scientific utility while adding a risk
view. The development data cutoff is 2024-01-01; artifact/current-knowledge
cutoffs are in 2026. This is retrospective attribution, not a 2024-vintage seal.
Missing legacy ledgers remain null. No financial rerun occurred during ingest.

SC also ingests all 128 original paths into 512 whole/annual rows. Monetary
reconciliation is exact; wealth-product residual is at most 2.2205e-16 and
campaign/account residual at most 3.2174e-10. Actual campaign closures and
boundary-censored holdings remain distinct from annual marked account PnL.

The registered endogenous volatility partition reuses the qualified provider:
fit BTC/ETH on **2020 only**, then label each UTC development day from information
available at midnight, including only the preceding completed hourly bar.
All 256 RSI/SC account paths yield 4,096 full/annual state-contribution rows;
marked monetary PnL reconciles with difference zero, and exposure, costs and
day counts conserve. Unknown availability is retained as unknown. These are
contributions from the same continuous accounts, not artificial equity curves
formed by joining disjoint state days. State annualized Sharpe/drawdown/utility
and campaign attribution are not claimed.

Twelve focused chronology/conservation tests PASS, including future-suffix
mutation, later intraday marks, late/missing features and frozen provider
identity. The fit algorithm is causal, but this attribution was reconstructed
at current knowledge in 2026: it is not a historical 2020 deployment seal or
clean independent OOS. Trend/activity partitions and complete five-battery
qualification remain `NOT_RUN`.

Retrospective same-panel diagnostics, with separately registered preferences,
show RSI annual utility-rank Spearman correlations of -0.025, +0.106 and -0.086;
the three annual near-optimal sets have pairwise Jaccard zero. Floor/Chebyshev
and pooled **utility** selection agree on this finite panel; lower-tail selects
a different compromise. This is not the forthcoming raw-Sharpe adaptive-search
comparison. SC has no candidate passing the day-supported quality/risk gate in
all three annual views, so selectors return `NO_SELECTION`, preserving losses
and no-trade states. With three equal-weight years, a lower-tail mass of .25
reduces to the minimum; it is not evidence for a separate nonredundant tail test.
These descriptions do not establish an economic promotion or independent
transfer result. Held LORO scores and gates are excluded from selection.

The distinction matters in the measured results: all six RSI kept-gate
floor/lower-tail LORO held annual utilities are negative (-0.126 to -0.306),
despite the all-years floor choice having positive utility in every registered
annual view. LORO here is retrospective omission, not a chronological forecast.
The actual same-panel raw-Sharpe control differs from the pooled-utility choice.
None of these fixed-panel results replace separate matched adaptive studies.

For SC's weak 2022 environment, 119 candidates lose marked PnL and nine have
no trades. All 119 active paths remain negative **before recorded fees** under
fixed-fill accounting; there are no fee-only sign flips. Median net marked PnL
is -862.15 USDT. Pre-fee arithmetic holds actual execution prices/fills fixed:
it is not an independently rerun frictionless strategy or a complete causal
market/execution decomposition. SC's empty admissible Pareto front means the
compromise comparison is `NOT_RUN`, not agreement between two null choices.

## Actual RSI Execution-Cost Stress

The separately registered 2x-fee scenario reexecutes all **128/128** original
RSI configurations on the same full development path, using both original
endpoint and direct owner. No posthoc fee subtraction, source/parameter change,
funding/slippage/allocation change or economic filtering is used. Base cells are
verified reuse, not repeated new base executions.

All paired Sharpes and utilities decrease. Median **paired changes** are -0.0684
Sharpe, -4.2352 percentage points net return and -0.05187 utility; median paired
drawdown increases 0.7036 percentage points. Signals and close-mark exposure are
unchanged. Utility rank changes for 108/128 candidates. This demonstrates cost
sensitivity on a finite development panel, not independent selector superiority.
Accepted-fill/campaign/payment ledgers remain unavailable on the legacy route.

The new scenario bills 256 actual account passes / 6,727,680 account-bars.
Financial-cell elapsed sum is 74.617 s and supervisor elapsed 125.090 s, including
isolated worker/import/verification overhead. All workers are reaped and exact
original sources remain unchanged. Protected paths, failed prior attempts and
paired daily account contributions remain private. The latest independent cold
analytics suite has 36 PASS; this count includes its earlier overlapping suites
and is separate from the 61 ingestion/design controls.

Independent focused verification: **61 PASS in 9.30 s**, with protected files
and helper sources unchanged. Tests cover all original seals, altered/future
suffix rejection, leap days, previous-close valuation, bankruptcy, losses,
no-trade/undefined states, censored ledgers, immutable buffers, numerical backend
parity and explicitly separated valuation/cutoff provenance. Prior failed and
earlier successful verification receipts remain retained.

After pilot measurement: freeze bulk work/resource registration, execute
checkpointed candidates, then actual multi-center schema/conditional/joint and
supported covariance probes. Keep held directions separate. Populate all six
matrices and five batteries, then issue new evidence-backed dossiers. M5-11.2
search remains unstarted until its entry conditions are satisfied or the owner
approves an explicitly labeled partial disposition. No public release is implied.

## Technical Controls

An independent 19-case source/fake-process audit found **qualification gaps,
not observed account corruption**: some supervisors can omit a fault receipt,
some per-tranche source lists omit financial dependencies, terminal active
orders are absent from the original Python parity check, and HMA's cache check
does not itself anchor the cell to its original pilot receipt. Independent
cold inspection verifies the current pilot bytes and calendars, but cannot
retroactively create a missing historical seal.

Append-only source/cache custody, terminal-owner oracle checks and failure
receipts are being added without changing active sealed workers or financial
source. Completed cells retain exact pass bills. A capped/failed worker lacking
a durable final pass ledger has an **unknown exact count**, with any observed
count only a lower bound; it must not be billed as zero or certified as complete.
No full-phase or fault/cancellation qualification is implied by the original
successful path/fill comparisons.

Focused tests cover strict protocol budgets and chronology, deterministic branch
quotas, conditional inactivity, effective deduplication, retained infeasibility,
finite-domain shortfall and design identity including the admission budget.
The initial twelve tests passed before registration. The expanded sixteen-test
suite passed after adding strict seed/count validation and budget-sensitive
design identity. These are orchestration controls, not broad economic evidence.

The first data-import attempt failed because the isolated tooling path omitted
the already-installed `pyarrow`. The preserved failed harness and a new recovery
receipt record addition of the existing pool environment's site-packages. No
dependency install, data filling, schema reduction or financial execution was
used to resolve this operational issue. Old Mode5 receipts remain untouched.

Private registration/designs/data: `upgrade/private/mode5_upgrade_v1/m5-11-1/attempt-01`.
Private harness: `upgrade/local/mode5_upgrade_v1/m5-11-1/attempt-01`.
Both are Git-ignored and excluded from the public package. Reports must distinguish
software PASS, performed measurements, open work and economic conclusions.

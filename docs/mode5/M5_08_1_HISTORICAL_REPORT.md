# M5-08.1 Historical Diagnostic Report

## Scope And Status

**COMPLETE_LOCAL_REGISTERED_HISTORICAL_DIAGNOSTICS / DESCRIPTIVE_ONLY.**
All 53 registered requests have qualified actual-account results. Current-source
regression, independent metric/accounting checks, source protection and exact
scratch cleanup pass. No production endpoint, alpha, financial engine, objective
mandate or packaging metadata changed.

The [unified extension](../../upgrade/implement.md#mode5-m5-08-1),
[detailed guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-08--five-empirical-batteries-và-targeted-verification-bốn-alpha)
and [historical contract](HISTORICAL_DIAGNOSTIC_CONTRACT_V1.md) govern this work.
The [original M5-08 report](M5_08_BATTERY_REPORT.md) and its 20 `NO_SELECTION`
decisions remain historical evidence, not overwritten results.

## Data And Registered Work

The read-only ETHUSDT 1h snapshot contains 59,280 finite, contiguous hourly rows,
2020-01-01 through 2026-10-05. Three incomplete provider-day rows are excluded;
there are no retained gaps, duplicates or nonfinite bars. Each request retains
365 days of prior history where required, without scoring preload.

| Work | Frozen Scope |
| --- | --- |
| Five actual admitted alpha routes | Complete annual reset accounts in 2021 and 2025 |
| Selection panel | Source-selected anchor and outcome-independent first-feasible neutral point per alpha |
| Local probes | Positive joint primary probe; distinct negative held direction, excluded from selection |
| Two anchor routes | Additional annual resets in 2022-2024 and separately partial 2026 |
| Two continuous accounts | Actual 2021-2026 carry, with calendar views using the preceding actual equity mark |
| Prior sampler choices | Eight frozen 2025 replays; no new study or Optuna observation |

There are 28 candidate records / 28 unique effective points and 40 registered
neutral raw proposals. This is a targeted tranche, not a 128-point standard
landscape, full-schema local basin qualification or full-history execution for
every command alpha. Those unexecuted scopes remain explicit.

2024 has 366 days; partial 2026 has 278 scored days and is not pooled into the
complete-year selector panel. Continuous versus reset comparisons also differ
in preload initialization. They are not isolated experiments on inventory carry.
Reviewed/unknown-history years and post-selected source anchors are not clean OOS.

## Metric And Selection Contract

Primary utility remains **period net return - hourly maximum drawdown - daily
ES95**, with positive quality, drawdown at most 0.5 and at least 91 daily
observations. Annualized-growth sensitivity is descriptive; it cannot rescue
primary eligibility. Sharpe annualization uses 365 daily periods; classical PSR
uses the same original-frequency daily series and moments.

Four canonical formula requests use the identical anchor/neutral panel:
floor/mean, lower-tail, active local downside and Pareto Chebyshev. They are not
four distinct selector families; the adaptive dossier slot belongs to M5-09.
Two equal-weight years with tail mass 0.25 make the lower-tail mean equal to
the minimum, so agreement does not establish distinct tail-shape advantages.

Held probes, partial 2026 and frozen sampler replays never enter this panel.
Leave-out rebuilds eligibility using kept environments only; held gate
information is excluded. Retrospective leave-out is not historical deployment.

## Diagnostic Findings

The extended panel produces **6 `SELECTED` and 14 `NO_SELECTION` decisions**.
Three formula requests select a candidate for each of two alpha panels;
all five active-local requests remain unqualified because full active-schema
neighborhood coverage is absent. These correlated choices are not six
independent confirmations or proof of end-to-end recipe superiority.

The longer accounts now distinguish profitable-but-ineligible, eligible,
losing and no-trade candidates. Neither the original short negative panel nor
this longer panel establishes that an alpha has, or lacks, universal edge.
Different calendar regimes and horizons both changed; this is not a controlled
test of duration alone.

Important observed mechanisms and support limits:

- One selected neutral candidate has only six closed campaigns in each annual
  account. Calendar coverage passes the declared formula gate, but that does
  not supply broad independent campaign support for an economic claim.
- A ladder candidate retains tiny residual inventory. Nonzero-position bars
  greatly overstate quote exposure and do not imply many independent campaigns.
  Source re-entry behavior is retained, not corrected into a better alpha.
- Actual adaptive-length clamps vary by context. A zero local effect does not
  justify pruning an axis or declaring it structurally inactive.
- The HTF route has complete scored readiness and retained amendments; its
  neutral point emits no orders. This is not missing preload or fabricated fills.
- The legacy scalar route has exact endpoint/direct-owner path parity but no
  accepted-fill/campaign ledger. Those unavailable fields remain null.

Nine evaluable paired fixed-path forward-Sharpe intervals contain zero; the
remaining no-trade contrast is insufficient. All nine decay-change intervals
also contain zero. Smaller IS performance alone is not a transfer gain.
Seven-day circular blocks, 256 draws and a fixed seed describe fixed paths;
one early/late origin does not certify the selection procedure's uncertainty.

Detailed per-alpha returns, gates, campaign/exposure/clamp tables, all 53 cells,
paired intervals and continuous/reset views remain in the ignored private
Appendix D report. No strategy code or parameter vector is exported here.

## Technical Certification

- **1,191 related tests PASS**, no failures or skips; six existing Optuna
  experimental warnings. Included: 19 calendar/view tests, 19 private
  analysis/transport guards and seven empty-account/dispatch checks.
- Four additive reporting/readiness tests PASS, independently of that pack.
- Independent retained-path oracles cover all **53** cells: return,
  baseline-inclusive drawdown, daily marks, fractional-atom ES95, Sharpe,
  original-frequency PSR, utility, actual accepted fees and closed/open PnL.
- Maximum accounting difference is **0**; maximum metric-oracle difference is
  **4.884981308350689e-15**. Original financial tolerances were not relaxed.
- All **2,803 protected hashes** remain unchanged. Required clocks,
  held/partial exclusion and kept-only gate behavior have regression guards.

Three research-harness gaps are closed, with all failures retained:
inactive mandatory constructor-carrier transport; zero-row Python reference
schema/unbound adapter dispatch; and non-scalar margin slicing in calendar
analysis. Recovery preserves the same effective point, commands, feedback,
account paths and source. No event/fill row or financial buffer is invented.

## Actual Resource Bill

| Measurement | Observed |
| --- | ---: |
| Qualified requests / execution attempts | 53 / 59 |
| Successful account passes / visited scored bars | 10,243 / 89,847,696 |
| Two-worker batch elapsed wall | 11,684.60 s |
| Same-point recovery elapsed wall, all attempts | 57.38 s |
| Successful command wall, summed across workers | 23,356.34 s |
| Failed original / failed retry command wall | 6.62 s / 27.56 s |
| Additional pilot successful / failed wall | 98.72 s / 299.00 s |
| Offline actual-feedback compiler, summed stage wall | 22,709.52 s |
| Analysis before serialization / process peak RSS | 19.14 s / 320.27 MiB |
| Maximum individual fresh account-worker peak RSS | 748.17 MiB |

Batch plus recovery is about 3.26 hours, inside the original 21,600-second wall
budget. Summed worker time is not elapsed time. Pilot work is billed separately;
unknown failed account-pass counters and simultaneous system-wide peak RSS
remain null. Preload/indicator work is additional to scored account-bars.

The dominant cost is research admission's repeated actual-feedback convergence,
not one production backtest, public WFO or Rust/kernel throughput. No speedup or
regression claim for those products follows from these timings.

## Cleanup And Handoff

[Cleanup](../maintenance/M5_08_1_CLEANUP.md) removed only the registered inactive
scratch after host process/FD review. All protected and 635 retained hashes
passed; observed immediate free-space improvement is 8.26 MiB. All science,
original failures, private source, current tooling and exact artifacts remain.

The [aggregate seal](evidence/m5-08-1.json) binds the private report and current
source receipts. There is no remaining in-scope implementation blocker.
Sparse geometry, reviewed history, limited campaign support/origins, unavailable
full historical trials and legacy fill coverage remain disclosed evidence limits.

M5-09 can consume this evidence for a dossier, including `NO_CLEAR_WINNER`, but
still requires separate approval. Broad economic confirmation belongs to a
separately registered M5-11 study. M5-09 onward, public activation, installed
artifact certification, rebuild, CI, push, merge, tag and release have not run.

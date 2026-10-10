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
611.83 MiB. No time/economic-quality stop filtered the panel. SC neighborhoods,
stress, actual sampler/search contrasts and transfer remain separate work.
Private summary and validation: `sc_panel_summary.json`, `sc_panel_summary.md`
and retained original shard receipts.

VWAP's first extended pilot failed before accounting because its original alpha
requires an explicit input even when that dimension is structurally inactive.
The effective search representation had omitted it. This is an input-binding
failure, not no-trade/negative economics. Recovery must retain the original
proposal, restore only a source-bound registered raw input, prove the effective
identity unchanged and create a new lane; no module default or favorable
replacement candidate is permitted.

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

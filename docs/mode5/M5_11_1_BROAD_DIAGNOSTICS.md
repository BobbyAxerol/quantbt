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
- Seed 731, one financial worker, one numeric thread. Each route's measured
  complete-horizon pilot has a registered 1,800-second / 2-GiB RSS cap. The cap
  concerns the pilot, not permission to shorten research data.
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

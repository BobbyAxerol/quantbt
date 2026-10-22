# M4-ML-09 Technical Closeout

## Scope And Result

Local technical qualification PASS on 2026-10-18 UTC. This closes
[ML-09.C](../../upgrade/implement.md#m4-ml-09-closeout), following
[guide 16.1](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md#mlr-r1).
There is no new optimizer, learner/default change, automatic reporting phase,
installed-package certificate, CI run or release activation.

The two private source-faithful alpha routes remain anonymous here. N1 uses
original close-fill orders; N2 uses next-open actual feedback with four
reduce-only targets. Account settings are matched, but original sizing and
clock differences remain explicit. Neither is replaced with a signal proxy.

The completed study uses ETHUSDT 1h, rolling 730D IS, 57 monthly origins per
alpha from January 2022 through September 2026, 128 attempted legacy-TPE
proposals per pool and seed 731. The original Mode 4 causal/native selector
and frozen Ridge V1 remain unchanged. Only base-16 plus original Ridge-winner
acquisition enters subsequent training; alternative-policy labels do not.

## Verified Gates

| Gate | Fresh verification |
|---|---|
| Custody | 114 primary origins and six group-TPE screen pools; 120 pools, each 128 attempts; 15,360 existing qualified slots, zero new proposals |
| Measurement | All 1,954 saved primary forward observations independently reduced from daily return samples; all five policies' D/R/Q and exact valid/undefined masks rechecked across 114 origins |
| Mature decisions | N1 folds 13/40/56 and N2 folds 14/40/56; full numerical fit, scaler, Gram/RHS, row references, predictions, ranking, guard, ties, IDs and applied params match saved results exactly |
| Availability | Current/future labels, reversed physical record order and late corrections leave earlier snapshots and actual fit/rank unchanged |
| Positive control | Permitted-past synthetic corrections change coefficients, without increasing origins or duplicating their training weight; never written into real training history |
| Market causality | 12 original fixed accounts plus their 12 future-market mutations; IS and forward at all six checkpoints; all 24 observation hashes match original evidence |
| Raw accounting | Independent actual-fill MTM, positions, fees, funding, margin and campaign PnL; no hypothetical fills or alternative execution engine |
| Regression | 116 focused tests PASS, including seven closeout reducer/mutation checks and 109 existing history/Ridge/target/measurement checks |
| Identity/privacy | Exact original study source, current native binary, old failed lane and 42-source/5-receipt Ridge freeze preserved; private source/params remain ignored and excluded from package manifests |

N1 has 44 actually model-ready origins and 13 support fallbacks. N2 has 43 and
14 respectively. Checkpoint matured-origin support is N1 12/39/55 and N2
12/35/47. Their actual model rows are 180/609/858 and 155/490/660; availability
is not replaced by an assumed calendar count.

Across the 24 fixed executions, independent maximum path errors are:

- Equity, positions, fees and funding: zero.
- Initial margin: `2.2737367544323206e-13`.
- Maintenance margin: `7.105427357601002e-15`.
- Campaign-versus-account money reconciliation: `1.9917933968827128e-10`.

These satisfy the existing absolute `1e-8` accounting tolerance; it was not
relaxed. All N2 controls finish flat. N1 can retain its source-defined terminal
position; open campaigns are marked and reconciled, not silently flattened.
The older source-bound Python/Numba/Rust acceptance and oracle witnesses are
reused under [their exact artifact contract](../maintenance/M4_ML_09_CORE_ACCEPTANCE.md),
not rebuilt or reinterpreted as a new installed-wheel proof.

Future mutation multiplies only later OHLC/volume. For the terminal September
window, a later synthetic bar is appended because no real suffix exists in the
snapshot. The past index/data and financial account interval stay unchanged.
This verifies execution-prefix isolation, not a rerun of the adaptive search
under future market changes.

## Economic Readback

These are the original registered 32 evaluation months, February 2024 through
September 2026, not newly searched outcomes. R is native signed decay minus
selected signed decay; Q is selected minus native forward Sharpe. Therefore
`R = (native IS - selected IS) + Q`. Q need not be positive for R to improve,
and OOS need not exceed IS.

| Descriptive statistic | N1 | N2 |
|---|---|---|
| Valid Sharpe pairs | 32/32 | 24/32 |
| R mean; decay wins | +3.06795; 26/32 | +1.78324; 17/24 |
| Q mean; help/harm/tie | +1.15896; 22/10/0 | -0.00697; 13/10/1 |
| Positive OOS Sharpe, native to Ridge | 10 to 17/32 | 14 to 15/24 |
| Mean monthly return, native to Ridge | -1.01880% to +0.48006% | +0.05406% to +0.04185% |
| Positive monthly returns | 10 to 16/32 | 14 to 18/32 |
| Worst-20% monthly return mean | -8.06735% to -4.99027% | -2.28685% to -5.23890% |
| Mean within-fold max DD | 6.18691% to 4.76888% | 1.66846% to 3.17397% |
| Actual fills, native to Ridge | 723 to 537 | 173 to 469 |

Return/DD rows retain all 32 months, including flat accounts. A legacy display
Sharpe of zero with `NO_VARIANCE` is not a valid regression label or R/Q operand.
All 43 model-ready N2 origins have 32 valid Sharpe pairs and mean Q -0.62604;
the late-period table does not erase that adverse finding. N1's 2025 mean Q is
-0.69288 despite its favorable aggregate result. No universal improvement or
fresh family-confidence claim is made, and no outcome is retuned.

All fold metrics are reset-account diagnostics. Neither mean fold Sharpe nor
pooled daily returns is advertised as a stitched continuous-account metric.
The model/target/ranking and three-cutoff sampler controls remain bounded
research, not an automatic replacement policy.

## Work, Retention And Handoff

New financial work is exactly 24 registered saved-param executions, totaling
46.54 seconds of account execution on this host. Zero optimizer proposals or
new economic candidate-query arms were run. Successful mature-control work is
30 Ridge plus 30 direct-Q fits; retained failed-harness attempts add 37 of each,
for 67 of each in the actual work ledger. This is a qualification workload,
not a before/after performance benchmark.

Initial harness failures and source versions remain retained: parent-revision
ordering, legacy flat-display/invalid-origin handling, terminal suffix support
and calendar metadata. The fixes affect qualification code only, not alpha,
production math, financial results, thresholds or original study receipts.
Eleven completed account controls were reused exactly when the terminal-suffix
harness was repaired; they were not financially rerun.

Machine evidence is local and ignored under
`upgrade/private/meta_model_research_v1/ml09/closeout-01/`: `registration.json`,
`protected.json.gz`, per-alpha measurement/chronology, 24 account receipts,
`tests-final.xml`, `cleanup.json` and `closure.json`. The original `attempt-01`
failures and `attempt-02` financial evidence remain immutable. Budget is the
existing 192 MiB study ceiling plus 32 MiB proof/32 MiB scratch, at least 5 GiB
free disk, 24 account executions and 30 minutes qualification wall.

[Terminal cleanup](../maintenance/M4_ML_09_TERMINAL_CLEANUP.md) checks all 18,076
protected references before and after owned scratch removal. Only three owned
harness files have explicit versioned amendments; their old bytes are retained.
Original scientific/source/artifact references remain unchanged.

Next is [M5-11.7.1 shared diagnostics/reporting](../../upgrade/implement.md#mode5-m5-11-7-1)
after owner review. No M5-11.7 implementation, M5-12, remote qualification,
push, tag, build or publication is included in this closeout.

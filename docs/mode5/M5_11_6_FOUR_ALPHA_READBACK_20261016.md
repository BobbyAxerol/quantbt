# M5-11.6 Four-Alpha Readback And Qualification Gaps

## Scope And Disposition

Read-only inspection at **2026-10-16T17:07:52.778817+07:00**. All four alphas have 57 saved
completed search journals, but the phase is **not complete**. Three alphas have
certified final account replay; HMA has a newly confirmed observer failure and
a stopped final account. No financial run, optimizer, label repair, recipe
change, CI or release was launched for this report.

This corrects the preliminary statement that all four alphas had complete valid
labels. A fold completion marker alone did not certify HMA's auxiliary observer.

The [approved rolling protocol](M5_11_6_LONG_ROLLING_QUEUE.md) and
[unified scope](../../upgrade/implement.md#mode5-m5-11-6) remain unchanged:
ETHUSDT 1h, preload from 2020, rolling 730D IS, monthly OOS January 2022 through
September 2026, 128 attempted proposals/fold, legacy TPE, seed 731, no warm start
or early stopping. Native selection uses the unchanged IS-only robust selector;
active meta uses Ridge origin-sum, lambda 10, minimum 12 matured origins and
predicted-Q floor -0.10. Arms share each original IS search pool, not two
independent optimizers. This is Mode 4 evidence, not new Mode 5 calibration.

## Search, Labels And Execution

| Alpha | COMPLETE / PRUNED trials | Fit/rank decisions | First fit | Native medoid / fallback | Failed observer labels | Final account/replay |
|---|---:|---:|---|---:|---:|---|
| SC | 7296 / 0 | 42 | 2023-04 | 57 / 0 | 0 | PASS exact original-engine replay |
| HMA | 7151 / 145 | 44 | 2023-02 | 36 / 21 | 466 | NOT COMPLETE |
| HASH | 7028 / 268 | 44 | 2023-02 | 18 / 39 | 0 | PASS exact original-engine replay |
| VWAP | 7290 / 6 | 39 | 2023-07 | 48 / 9 | 0 | PASS exact original-engine replay |

Totals: **29,184 attempted slots, 28,765 COMPLETE, 419 PRUNED, zero optimizer
FAIL**. These are not counts of independent market observations or all physical
executions. Zero optimizer failures does not mean zero observer failures.

| Alpha | Retained observer rows | VALID | NO_VARIANCE | OUTCOME_FAILED | Matching selected-forward/outer observations |
|---|---:|---:|---:|---:|---:|
| SC | 941 | 621 | 320 | 0 | 57/57 |
| HMA | 942 | 468 | 8 | 466 | 29/57 |
| HASH | 948 | 948 | 0 | 0 | 57/57 |
| VWAP | 943 | 409 | 534 | 0 | 57/57 |

NO_VARIANCE is a legitimate undefined metric status, not an execution error.
HMA's OUTCOME_FAILED rows are different: they cannot be used as valid labels
or replaced by zero. Fit-count metadata on HMA does not certify that its later
history acquired the required new observations.

## Primary Evaluation Economics

Definitions follow [guide section 14.3](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14):
D = raw IS Sharpe - raw forward Sharpe;
R = D_native - D_meta;
Q = forward_meta - forward_native;
R = (IS_native - IS_meta) + Q.

The locked evaluation calendar is February 2024 through September 2026.
Means below use the same paired-valid months within each alpha; missing slots
remain in the calendar. These are unweighted mean fold diagnostic Sharpe
contrasts, not continuous-account Sharpe and not independent daily-return CIs.

| Alpha | Valid evaluation pairs / calendar | Paired calendar days | Native / meta mean IS | Native / meta mean forward | Native / meta mean D | Mean R | Mean Q |
|---|---:|---:|---:|---:|---:|---:|---:|
| SC | 20/32 | 609 | 1.330 / 0.734 | -0.646 / -0.278 | 1.976 / 1.012 | +0.964 | +0.368 |
| HASH | 32/32 | 973 | 1.342 / -0.342 | 0.048 / 0.293 | 1.294 / -0.635 | +1.928 | +0.245 |
| VWAP | 11/32 | 336 | 1.444 / -0.303 | 0.045 / -0.055 | 1.399 / -0.248 | +1.648 | -0.100 |
| HMA | 4/32 valid; 28 failed | 121 | NOT FULL-SCOPE QUALIFIED | NOT FULL-SCOPE QUALIFIED | NOT FULL-SCOPE QUALIFIED | NOT REPORTED AS FULL STUDY | NOT REPORTED AS FULL STUDY |

HMA's four valid February-May 2024 evaluation pairs have descriptive R=+0.676
and Q=-1.104. They do not represent 2025-2026,
a completed long-horizon study or evidence about the repaired methodology.
The failed June 2024 onward labels also prevent calling later history/decisions
equivalent to the intended adaptive study.

### Decomposition And Robustness

| Alpha | IS contribution to R | Actual forward contribution Q | Median R | Median Q | Q positive / negative / zero months |
|---|---:|---:|---:|---:|---:|
| SC | +0.596 (61.8%) | +0.368 (38.2%) | +0.851 | +0.389 | 12 / 8 / 0 |
| HASH | +1.684 (87.3%) | +0.245 (12.7%) | +1.015 | +0.000 | 14 / 14 / 4 |
| VWAP | +1.747 (106.1%) | -0.100 (-6.1%) | +1.381 | +0.000 | 5 / 5 / 1 |

- SC: both lower IS and improved forward contribute; mean forward remains
  negative in both arms. This is less-negative forward, not a guaranteed
  profitable or consistently superior policy.
- HASH: forward mean improves, but most decay reduction comes from lower IS.
  Median Q is zero, and positive/negative forward contrasts are balanced.
- VWAP: lower IS more than explains positive R; forward offsets that gain.
  Participation and paired support are limited. This is not forward improvement.
- Negative signed D means forward exceeds IS; it does not mean negative risk,
  a perfect predictor or more-than-perfect retention.

### Calendar Stability

Each cell is **mean R / mean Q (paired months)**. These are descriptive year
slices, not inferred market-regime labels. 2024 starts February; 2026 ends
September; excluded months are not imputed.

| Alpha | 2024 evaluation | 2025 | 2026 evaluation |
|---|---|---|---|
| SC | +1.543 / +1.016 (9) | +0.491 / -0.155 (7) | +0.490 / -0.173 (4) |
| HASH | +2.938 / +0.923 (11) | +1.066 / -0.502 (12) | +1.844 / +0.412 (9) |
| VWAP | +4.580 / +2.854 (2) | +1.152 / -0.531 (5) | +0.801 / -1.038 (4) |

All three completed comparisons have negative Q means in 2025. SC/VWAP also
have negative Q means on their valid 2026 subsets. Positive all-evaluation
means must not be reported as stability through every period.

### Support And Uncertainty

SC has 20 paired evaluation months / 609 calendar days; HASH 32 / 973.
VWAP has only 11 / 336, below the registered 12-month/365-day support minimum.
HMA currently has only four / 121 with valid forward labels.

The existing family reducer returns **INCONCLUSIVE**, with no certified
intervals. It requires a complete supported 32-month by eight-coordinate
matrix, which SC/HMA/VWAP currently do not supply. The frozen design is
three-month moving blocks, 16,384 draws, seed 731, family confidence 95% with
eight fixed R/Q coordinates. No months were compressed, zero-filled or
discarded to manufacture a confidence bound. Finishing HMA accounting alone
would not close this missing-data inference limitation. Changing the estimator
or gate requires a separate prospective decision, not a silent report change.

## Continuous Account Crosscheck

These accounts retain original carry, fills, fees and margin. They are not
concatenated reset diagnostic equities and are secondary to fold R/Q for the
methodology comparison. Legacy full-calendar Sharpe includes the flat pre-OOS
prefix and is not a mean fold Sharpe.

| Alpha/arm | Final equity | Return % | Legacy full-calendar Sharpe | Max DD % | Fees USD | OOS time in market % | Actual fills |
|---|---:|---:|---:|---:|---:|---:|---:|
| SC/native | 24160.99 | 20.80 | 0.662 | 5.73 | 125.48 | 52.38 | 155 |
| SC/active | 21110.12 | 5.55 | 0.221 | 8.25 | 446.99 | 49.62 | 558 |
| HASH/native | 20067.18 | 0.34 | 0.032 | 9.62 | 509.95 | 88.48 | 910 |
| HASH/active | 17707.96 | -11.46 | -0.682 | 17.03 | 604.17 | 87.68 | 1034 |
| VWAP/native | 19723.74 | -1.38 | -0.254 | 2.45 | 73.71 | 3.09 | 92 |
| VWAP/active | 19484.16 | -2.58 | -0.374 | 3.62 | 364.62 | 3.62 | 456 |

No completed arm liquidated; funding is off in this protocol. Fills are not
closed campaigns. A final closed-campaign/activity-support qualification is not
replaced by the fill counts above. HMA has no saved final financial-complete
marker, so no final account values are fabricated.

## HMA Technical Findings

Two independent issues are retained:

1. **Observer wrapper defect:** all 466 failed labels occur in folds 29--56,
   June 2024 through September 2026. The private RAM continuation checks the
   main engine identity before permitting a live auxiliary observer call.
   A read-only reproduction invokes the actual helper with an auxiliary engine
   and gets both `unexpected peer strategy owner/fold` and
   `unexpected RAM scorer engine`, with zero optimizer/financial calls.
   Correct early prefix folds 0--28 remain distinct from the failed suffix.
2. **Final memory guard:** HMA stopped at 2026-10-16 11:23 Asia/Saigon after
   crossing its unchanged 900-MiB worker allowance (recorded peak 909.39 MiB).
   A full-history command compilation was recorded, but no final financial
   paths/replay receipt exists. This is not an OOM/accounting-parity conclusion.

The 28 failed selected-forward observations disagree with their actual outer
account observations on raw Sharpe/sample count/std/initial mark/status. Thus a
whole HMA measurement gate cannot pass merely because all searches completed.

A proposed correction reuses all 57 original pools and exact native anchors,
restores the clean 29-fold prefix, repairs later labels and reruns chronological
selection with correct maturity. Later active decisions may change as repaired
history becomes available. This needs no new optimizer search, but it does need
the missing original-engine observer/accounts, followed by both final accounts
and exact replay under a separately admitted final-memory budget. Preserve all
old failed histories and receipts. No such repair was launched in this readback.

## Gates, Cost And Next Decision

- Software/measurement/accounting: final replay and selected-forward/outer
  checks pass for SC/HASH/VWAP. Their 171 reduced rows reproduce saved R/Q
  statistics. HMA has a confirmed wrapper/measurement failure, not an alpha
  economic verdict.
- Chronology: saved current-OOS access flags are false and canonical revision/
  task/panel hashes are checked. This is not a substitute for the still-open
  mature off/shadow/future-mutation M4X-03/05 closeout.
- Economic status: descriptive R/Q gain for SC/HASH, limited/non-improving
  forward evidence for VWAP; no qualified full HMA result and no family
  directional certificate. No retuning or automatic promotion.
- Performance: historical/resumed lane timers are not a fresh full-study
  benchmark. HMA's failed final lane elapsed 36,274.46 seconds including its
  continuation work; SC's 263.72-second finalization is not a new optimizer
  timing. Observer failures with millisecond timers are not speedups.
- Cleanup: HMA supervisor reaped its worker and removed nine inactive JIT
  files, preserving 2,509 protected hashes. SC/HASH cleanup receipts also pass.
  No environment, source, alpha or evidence was deleted by this readback.
- Owner review: **PENDING / CHANGES TO DISCUSS**. First correct HMA's technical
  evidence; then review IS horizon, participation, native cluster fallback,
  predicted-Q guard and regime stability without treating old evaluation data
  as a newly untouched holdout. Do not automatically copy RSI's 100-trades/year
  requirement into unrelated order strategies.

M5-11.7, M5-12, CI, merge, tags and publication remain unactivated.

## Source Receipts

All paths below are retained beneath
`upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01/`:

| Alpha | Original retained financial/journal root |
|---|---|
| SC | `sc57-finalization-v3-02/A-SC/run/A-SC` |
| HASH | `hash54-continuation-v3/A-HASH/run/A-HASH` |
| VWAP | `long-rolling-monthly-v1/A-VWAP` |
| HMA | `ram-resume-hma-v2/A-HMA/run/A-HMA` |

HMA's `folds/29/revision.json.gz` and `folds/56/revision.json.gz` retain the
failed-label boundaries. Its lane-level `queue-result.json` and `cleanup.json`
retain the memory stop and protected cleanup. Private alpha code and parameter
dictionaries remain ignored; no such content is included in this report.


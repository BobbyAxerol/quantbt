# M5-11.6 Four-Alpha History, Accounting And Economic Closeout

## Scope And Status

Local closeout of the owner's approved remaining work in
[M5-11.6](../../upgrade/implement.md#mode5-m5-11-6), dated 2026-10-16.
The approved history/financial recovery, source-bound local checkpoint
qualification, terminal readback and exact scratch cleanup are complete.
Local correctness/accounting PASS; registered economic family inference is
INCONCLUSIVE, not promoted or declared zero effect.

The owner plans another experiment inside this phase. M5-11.6 therefore remains
IN_PROGRESS for that owner decision; M5-11.7, M5-12, CI, push, merge, version/tag
and publication are not activated. No estimator, alpha, endpoint or accounting
engine was changed by this repair/closeout. Private alpha source, parameter
dictionaries, market data and detailed journals remain ignored, not published.

Authorities: [rolling registration](M5_11_6_LONG_ROLLING_QUEUE.md),
[HMA repair](M5_11_6_HMA_OBSERVER_CLOSEOUT.md),
[checkpoint contract](M5_11_6_CHECKPOINT_CLOSEOUT_PLAN.md), and QMS guide
[math](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[availability](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[causal flow](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7),
[parity](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
[work accounting](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10),
[reporting](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s12)
and [economics](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14).

## Frozen Method

ETHUSDT 1h, existing verified snapshot and original per-alpha feasible ranges.
Preload starts 2020-01-01. Rolling IS is exactly 730D, not two calendar years;
the first IS starts 2020-01-02. Monthly OOS is January 2022--September 2026:
57 folds and 1,734 days. Partial October is excluded.

- Mode 4 / `per_fold_causal`; legacy TPE, 128 attempted slots/fold, seed 731
  with the existing fold derivation, no warm-start or early stopping.
- Native means the existing IS selector/anchor, not Python versus Rust.
  `is_only_robust`, top 10%, medoid, epsilon 0.15, minimum cluster size 3,
  `is_subperiods=1`; original temporal/plateau weights 0.65/0.35.
- Active uses the same complete eligible IS pool and native anchor, then
  origin-sum Ridge, lambda 10, at least 12 matured compatible origins,
  predicted-Q floor -0.10 and the original ranking/tie rules.
- Label acquisition retains 16 base candidates plus the deduplicated union of
  compared winners, sealed before forward. No labels or trials are cut for cost.
- Capital 20,000, leverage 1, one-way fee 0.0004, zero slippage/funding and the
  original fixed-notional sizing/constraints. These are registered research
  conventions, not certification of live ETH venue constraints.
- SC uses the original callback via `event_driven`; HMA/HASH/VWAP use original
  actual-feedback native command tapes. No vectorized proxy replaces feedback.
- Diagnostic IS/forward accounts reset flat. Each final arm instead runs one
  continuous original account across fold transitions, including carry state;
  diagnostic equities are never concatenated.

One IS subperiod means this study does not add a within-IS multi-period stress
panel. Native medoid metadata can contain cluster-level summaries of members'
temporal scores; those fields are not the selected candidate's raw IS Sharpe.
The comparisons below use the latter's original observation, not a renamed
objective or cluster statistic.

There is one optimizer pool per fold, not two nominally identical optimizers.
Active ranks that exact pool; observer/final/replay work is additional physical
execution, not additional search information. Prior RSI evidence is retained,
not rerun or claimed to use the same protocol/account configuration.

## HMA Correction And Custody

The private RAM continuation incorrectly rejected auxiliary observer engines.
Its 57 searches remained valid, but folds 29--56 contained 466 failed labels.
The old failed evidence remains immutable and is excluded from repaired history.

The new harness delegates auxiliary calls to the original implementation before
the main-engine guard. It restores the clean first 29 folds/revision IDs exactly,
reuses all 57 original pools, and recomputes the 28 suffix decisions, panels and
forward outcomes chronologically. No completed optimizer is rerun. All 57 saved
search dictionaries remain canonically identical; later winners can change the
deduplicated winner union without changing the base-16 acquisition policy.

The corrected run saved both accounts, then exceeded its 2,304-MiB final-stage
allowance during the last independent replay (2,336.81-MiB peak). That receipt
stays FAIL_RETAINED. A separately registered lane reused saved financial bytes
and ran two fresh serial original-engine replays. Equity, returns, positions,
fees, funding, margin and every fill match exactly. Active/native replay took
17.521/16.270 s, with 804.64/809.52 MiB process peaks. This is replay cost, not
whole WFO or meta overhead. See [HMA financial status](M5_11_6_HMA_FINALIZATION_STATUS.md).

## Search, Labels And Actual Learning

Every alpha has 57 complete ordered 128-attempt journals. Infrastructure failures
remain separately retained; there are zero optimizer FAIL states in these pools.

| Alpha | COMPLETE / PRUNED | Labels: VALID / NO_VARIANCE | Actual Fitted Folds | First Fit | Changed Winner Folds | Native Medoid / Fallback |
|---|---:|---:|---:|---|---:|---:|
| SC | 7,296 / 0 | 621 / 320 | 42 | 2023-04 | 42 | 57 / 0 |
| HMA | 7,151 / 145 | 930 / 15 | 44 | 2023-02 | 44 | 36 / 21 |
| HASH | 7,028 / 268 | 948 / 0 | 44 | 2023-02 | 39 | 18 / 39 |
| VWAP | 7,290 / 6 | 409 / 534 | 39 | 2023-07 | 39 | 48 / 9 |

Total: 29,184 attempted slots, 28,765 COMPLETE, 419 PRUNED; 3,777 observer labels
comprise 2,908 VALID and 869 NO_VARIANCE, with zero failed/pending corrected
labels. No-variance observations are explicit unsupported metrics, never zero
Sharpe labels. Later first-fit dates reflect actual compatible valid history,
not a forced twelfth-month activation. A fitted model need not change the winner.
Cold verification of all 169 fitted decisions confirms predictions cover the
entire recorded eligible pool, model origin count equals recorded matured
support (at least 12), the canonical anchor has exact zero Yhat/Qhat, and the
actual selected prediction passes the unchanged Qhat floor. This retained-data
check is separate from fresh public fit/rank checkpoint execution.

## Primary Fold Economics

Frozen roles: 13 acquisition folds, 12 development folds, then 32 evaluation
folds from February 2024 through September 2026 (973 days). Below are arithmetic
means over each alpha's paired-valid evaluation months, not whole-account
Sharpe or day-weighted return. Undefined months remain in the calendar/mask.

`D = IS_raw_Sharpe - FWD_raw_Sharpe`; `R = D_native - D_meta`;
`Q = FWD_meta - FWD_native`; exactly `R = (IS_native - IS_meta) + Q`.

| Alpha | Paired Months / Days | Native D | Active D | R | IS Contribution | Q | Median R / Q | Q Positive / Negative / Zero |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SC | 20/32 / 609 | 1.97619 | 1.01190 | +0.96428 | +0.59588 | +0.36840 | +0.85113 / +0.38867 | 12 / 8 / 0 |
| HMA | 32/32 / 973 | 2.19427 | 0.98674 | +1.20754 | +1.81502 | -0.60748 | +1.40658 / -0.53408 | 13 / 19 / 0 |
| HASH | 32/32 / 973 | 1.29365 | -0.63474 | +1.92839 | +1.68351 | +0.24488 | +1.01522 / 0.00000 | 14 / 14 / 4 |
| VWAP | 11/32 / 336 | 1.39922 | -0.24838 | +1.64761 | +1.74741 | -0.09980 | +1.38057 / 0.00000 | 5 / 5 / 1 |

Raw levels make the mechanism visible:

| Alpha | Native / Active IS Sharpe | Native / Active Forward Sharpe |
|---|---:|---:|
| SC | 1.33011 / 0.73422 | -0.64608 / -0.27768 |
| HMA | 1.33193 / -0.48309 | -0.86235 / -1.46983 |
| HASH | 1.34159 / -0.34192 | 0.04795 / 0.29282 |
| VWAP | 1.44429 / -0.30312 | 0.04507 / -0.05473 |

R is positive for all four descriptive means. This is not evidence of four
forward improvements: lower IS explains 61.8% of SC R and 87.3% of HASH R;
for HMA/VWAP it more than explains R and is offset by worse forward Q. Negative
decay can arise from low/negative IS, not necessarily profitable forward.
Paired-valid conditioning can itself be selection-dependent; missing Sharpe
months must not be assumed randomly missing or silently averaged as zero.

The policy predicts relative decay Y, then constrains predicted Q; it does not
optimize realized forward Sharpe directly. Its -0.10 predicted-Q floor is not
an actual-outcome noninferiority guarantee. Lower-IS selections with positive
R but negative realized Q are therefore an empirical prediction/selection
limitation to investigate, not by themselves evidence of leakage or an account
bug. The present evidence does not isolate which descriptor, model vintage or
policy constraint caused the error; no post-outcome causal attribution or
threshold retuning is claimed.

## Stability By Year

Each cell is mean R / mean Q on that year's paired-valid evaluation months.
2024 begins in February and 2026 ends in September; neither is a full year here.

| Alpha | 2024 | 2025 | 2026 | Valid Pairs By Year |
|---|---:|---:|---:|---:|
| SC | +1.54329 / +1.01613 | +0.49114 / -0.15505 | +0.48951 / -0.17297 | 9 / 7 / 4 |
| HMA | -0.07802 / -1.88700 | +0.62183 / -1.02767 | +3.55972 / +1.51662 | 11 / 12 / 9 |
| HASH | +2.93803 / +0.92305 | +1.06637 / -0.50241 | +1.84373 / +0.41238 | 11 / 12 / 9 |
| VWAP | +4.57973 / +2.85380 | +1.15175 / -0.53106 | +0.80136 / -1.03753 | 2 / 5 / 4 |

SC/HASH have positive aggregate Q but not stable gains every year. All four
have negative 2025 Q; HMA's favorable 2026 does not erase its 2024/2025 weakness.
VWAP's few supported months and low participation limit interpretation.

## Uncertainty Disposition

The registered family remains eight R/Q coordinates, shared chronological
three-month blocks, 16,384 bootstrap draws, seed 731, family confidence 95% via
Bonferroni. The existing estimator requires the supported complete calendar
pattern across this family. SC has missing paired months; VWAP additionally
has only 11 mature valid months/336 days, below 12/365 support requirements.

Result: **family INCONCLUSIVE; no numerical family confidence intervals and no
joint directional claim certified.** Do not fill missing months, compress time,
drop coordinates, substitute an unregistered per-alpha CI or change estimator.
The missing-pattern admission stops before numerical bootstrap; 16,384 is the
registered draw budget, not a claim that an unsupported family was resampled.
This is not a test proving zero effect, nor evidence that meta has no edge.
HMA/HASH meet the registered paired-calendar support; that alone does not close
the unsupported family inference. Campaign-based activity support remains
unavailable where original ledgers lack campaign IDs/closure rosters.

These are retrospective, reviewed/exploratory results from one seed and four
specific strategy/route/config cells. Technical no-leakage does not turn earlier
researcher exposure into untouched OOS or establish full-pipeline uncertainty.
Prior positive RSI evidence is not invalidated by heterogeneous new cells.

## Continuous Account Cross-Check

Original final accounts cover the complete OOS sequence, including acquisition
and development folds; they are not restricted to the primary 32-fold subset.
Retained legacy whole-path metrics include the earlier flat preload calendar.
They are not mean monthly Sharpe and are not reinterpreted as closed-action
metrics. All eight accounts avoid liquidation and have zero funding cashflow.

| Alpha | Arm | Final Equity | Return | Max DD | Fees | Time In Market | Actual Fills |
|---|---|---:|---:|---:|---:|---:|---:|
| SC | Native | 24,160.99 | +20.80% | 5.73% | 125.48 | 52.38% | 155 |
| SC | Active | 21,110.12 | +5.55% | 8.25% | 446.99 | 49.62% | 558 |
| HMA | Native | 19,563.29 | -2.18% | 10.30% | 1,659.95 | 54.19% | 2,075 |
| HMA | Active | 17,204.90 | -13.98% | 18.19% | 1,450.86 | 59.01% | 1,813 |
| HASH | Native | 20,067.18 | +0.34% | 9.62% | 509.95 | 88.48% | 910 |
| HASH | Active | 17,707.96 | -11.46% | 17.03% | 604.17 | 87.68% | 1,034 |
| VWAP | Native | 19,723.74 | -1.38% | 2.45% | 73.71 | 3.09% | 92 |
| VWAP | Active | 19,484.16 | -2.58% | 3.62% | 364.62 | 3.62% | 456 |

Time in market is the fraction of 41,616 original OOS hourly bars with nonzero
position. Fills are original ledger records, not closed trades/campaigns or
independent observations. Legacy `num_trades` is retained separately. Closed/open
campaign counts are UNAVAILABLE; they are not invented from fill or regime
counts. Lower active equity and higher DD are disclosed, but neither replaces
the registered fold-decay comparison; the two scopes answer different questions.

## Qualification And Cost Ledger

The [prospective checkpoint contract](M5_11_6_CHECKPOINT_CLOSEOUT_PLAN.md)
completed **100/100 passing bounded cells** over all four actual bindings:
early, first mature fit and final fold; off/shadow/active; separate future-market,
future-label, anchor, physical-order and late-arrival mutations; allowed past-label
positive controls and unavailable-model rejection. All current and unavailable
future records are physically present, so the rights checks are non-vacuous.
Each bounded cell deliberately stops before full final-account assembly after
its decision/control checks. Its scoped checkpoint receipt is the authority;
the interrupted original long-run wrapper is not relabeled a complete financial
PASS. The separately retained eight final accounts supply that accounting proof.

Every alpha uses fold 0, its first actually fitted fold and fold 56. The fresh
active fit/rank checkpoints confirm the following; unavailable/late mutations
preserve these decisions, while permitted past-label controls change fitted
coefficients without changing the number of origins.

| Alpha | First Fitted Checkpoint | Origins First / Final | Predictions / Full Pool First | Predictions / Full Pool Final |
|---|---|---:|---:|---:|
| SC | Fold 15, 2023-04 | 12 / 40 | 128 / 128 | 128 / 128 |
| HMA | Fold 13, 2023-02 | 12 / 55 | 124 / 124 | 128 / 128 |
| HASH | Fold 13, 2023-02 | 12 / 55 | 123 / 123 | 126 / 126 |
| VWAP | Fold 18, 2023-07 | 12 / 27 | 128 / 128 | 128 / 128 |

Off/shadow preserve actual native params and exact original OOS paths/fills.
Future-market controls preserve original native-anchor IS objective, raw
observation and six financial paths/fills. All 228 selected-forward/outer
measurements agree; all 228 snapshots rebuild under actual as-of rights, and all
456 saved native/active dictionaries match the original applied schedules.

Earlier source-compatible full-search/RNG/lifecycle/financial controls remain
separate retained proofs. Saved-pool qualification is not a fresh 128-ask/tell
search at every mature checkpoint. No same-seed-only claim substitutes for exact
pool, anchor, original journal, snapshot and applied-schedule identity.
The earlier [404-case performance qualification](M5_11_6_PERFORMANCE_CLOSURE.md#correctness-and-remaining-work)
and [native transaction controls](M5_11_6_NATIVE_TRANSACTION_CLOSURE.md) are
reused only for their unchanged source/contract scope; they are not counted as
new four-alpha mature checkpoints or new economic observations.

Focused new tests: 20 HMA handoff tests plus 52 readback/history tests passed;
overlapping earlier reruns are not added to these counts. Checkpoint cells are
separate from unit tests and are not independent economic replications.

The current work adds zero optimizer trials. Corrected HMA observer accounts,
final accounts and independent replays are actual additional work; readback and
uncertainty rendering reuse retained observations. Failed/partial attempts and
interruptions remain in the work ledger, not silently folded into an invented
uninterrupted runtime. Completed-search sums exclude observer/recovery/final work
and are not total study elapsed time or an off-versus-active benchmark.

| Alpha | Sum Of 57 Completed Search Timers | Median / Maximum Search Per Fold | Median Sampler Timer Per Study |
|---|---:|---:|---:|
| SC | 17,725.12 s | 303.27 / 410.79 s | 1.15 s |
| HMA | 76,651.73 s | 1,307.85 / 1,930.10 s | 3.66 s |
| HASH | 50,272.88 s | 790.02 / 2,055.92 s | 3.14 s |
| VWAP | 29,796.55 s | 517.03 / 740.74 s | 3.03 s |

These original retained per-fold clocks span interrupted execution vintages and
shared-host load; they are not a new matched hardware benchmark or a before/after
speedup. No within-fold duplicate attempts were recorded; this does not imply
no repeated effective dictionary across different folds. The HMA finalization
receipt is derived custody, so it has no invented full-run elapsed/RSS value;
the two measured fresh serial replay clocks above remain its explicit cost.

Private checkpoint guarding inventories output/disk at frequent safe points;
its measured runtime includes that operational proof overhead. It is not a
production QuantBT/meta speed benchmark. The complete serial 100-cell controller
took 5,178.04 s; that is not a 128-trial study, meta-fit overhead or a production
latency regression measurement. Existing tooling/native artifacts were
reused, with one numeric thread and no build or dependency download. Retained
source/binary pins, private source archives, exact receipts and cleanup bind the
actual executed scope; installed-wheel/manylinux/public qualification is not
claimed by these local proofs.

## Receipt, Privacy And Cleanup

The final cold readback is 793,960 bytes and verifies 2,763 unique input pins.
Its financial summaries, repaired history and uncertainty disposition exactly
match the separately saved pre-qualification readback. Rendering did not run
an account or optimizer. The [public aggregate JSON](M5_11_6_FOUR_ALPHA_SUMMARY.json)
is an explicit whitelist: no parameter dictionaries, candidate/evaluation IDs,
coefficients, private paths, source alpha or raw ledger rows.

Private authority under `upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01`:

- `hma-observer-repair-v3`: corrected 57 folds and retained final memory failure.
- `hma-accounts-finalization-v4`: byte-exact financial custody and two new
  successful serial original-engine replay proofs.
- `four-alpha-closeout-v1/attempt-01/result.json`: all 100 actual checkpoint
  receipts, source/artifact registration and scoped comparison checks.
- `four-alpha-closeout-v1/readback.json`: canonical four-alpha reduction,
  family disposition, exact HMA repair references and protected inputs.
- `four-alpha-closeout-v1/final-closeout.json`: derived local terminal scope,
  tests, schedules, full-pool checks, public outputs and cleanup references.

Original per-alpha financial markers and stopped runs retain their historical
statuses; the new scoped qualification receipt does not rewrite them.
Source archives, test XML/logs, all failed attempts, old/new financial evidence,
private alpha/data, exact native artifacts and current environments remain.

[Cleanup receipt](../maintenance/M5_11_6_FOUR_ALPHA_CLOSEOUT_CLEANUP.md): six
inactive fixture/JIT roots, 324 ordinary files removed after 75 host processes
were reviewed; 11,884 protected files reverified unchanged. Observed filesystem
free-space increase is 2,736,128 bytes (2.61 MiB), separate from apparent file
size and host activity. No scientific evidence, artifact, environment, notebook
or unrelated service was deleted/stopped. At cleanup exit, free bytes were
6,814,134,272, still above the 5-GiB reserve.

## Research Handoff

Private compact readback retains all 57 fold rows and role/status masks per
alpha, raw IS/FWD observations, R/Q decomposition, year slices, exact params and
model/history provenance, ordered search journals, current winner schedules,
cost/activity paths, missing-field reasons and original financial replay refs.
M5-11.7 reporting can consume these without another optimizer or account run.

Potential next questions are owner decisions, not automatic experiments: why
the Q predictor selects low-IS candidates in these cells, sensitivity of its
predicted-Q constraint, regime-dependent errors and defensive/inactivity behavior.
Do not fit a new policy on these evaluation outcomes and label it independent
validation. The current repair did not retune lambda, thresholds, descriptors,
sampler, trial counts, calendar or account conventions.

# M5-11.6.1 Quarterly Mode 4 Decision Report

## Status And Scope

**COMPLETE_LOCAL_REGISTERED_RESEARCH.** All admitted financial studies and
local verification are terminal. Supported accounting, measurement and causal
checks pass. The registered economic family is **INCONCLUSIVE**, not an
implementation failure and not a general upgrade recommendation.

Read the [unified plan](../../upgrade/implement.md#mode5-m5-11-6-1),
[variant contract](M5_11_6_1_FAST_VARIANT_DESIGN.md),
[implementation/admission](M5_11_6_1_IMPLEMENTATION_REPORT.md) and
[sanitized numeric summary](M5_11_6_1_QUARTERLY_SUMMARY.json).
The authoritative QMS guide governs [selection](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[availability](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6)
and [economic interpretation](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14).
Mode 5's [battery separation](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử)
is retained; this experiment does not copy its annual utility objective into Mode 4.

No original alpha, public endpoint, production default, version or release is
changed. M5-11.7 and M5-12 require separate owner approval. The original
[monthly/730D study](M5_11_6_FOUR_ALPHA_CLOSEOUT.md) and earlier RSI evidence
remain valid within their own scopes; these new variants do not overwrite them.

## Actual Work And Method

| Item | Executed contract |
|---|---|
| Market | Existing verified ETHUSDT 1h snapshot; preload from 2020 |
| IS | Rolling 365D, full permitted indicator prefix |
| OOS | 2022Q1 through 2026Q3: 19 quarters, 1,734 days |
| Search | Mode 4/per_fold_causal, 128 attempts/fold, seed 731/fold derivation |
| Arms | Legacy TPE and multivariate/group TPE for SC/HMA/HASH/VWAP; legacy RSI reference |
| Trials | 171 studies; 21,888 attempted slots, 21,792 COMPLETE and 96 PRUNED |
| Selectors | Existing is_only_robust anchor and registered IS-segment floor/mean |
| Meta | Original Ridge origin-sum, lambda 10, min 12 matured origins, Qhat floor -0.10 |
| Account | 20,000 capital; 2,000 fixed-notional campaign; leverage 1; one-way fee 0.0004; no funding/slippage |
| Extra evaluations | 266 prefix probes, 3,080 sealed observer queries, 146 targeted account/isolation checks |
| Final accounts | 34 continuous accounts, each independently rebuilt/replayed: 68 final executions |

Both samplers retain the original IS search objective. They do not optimize
the challenger floor score. The two selectors share each financial IS account;
meta OFF/active share its captured pool. Eight primary policy combinations
therefore require two optimizers, not eight. No early stopping or warm-start.
Sampler telemetry records 2,242 relative proposals per group-TPE stream;
attempt uniqueness is not the same as feasible/VALID candidate support.

The challenger attributes one continuous 365D IS account into 91/91/91/92-day
segments. Its score is minimum segment daily Sharpe plus 0.25 times the
day-weighted mean. Every segment needs 60 valid days and positive variance.
This is **raw-Sharpe attribution**, not Mode 5's annual risk-penalized utility,
four reset accounts, an all-years-positive requirement or a new search objective.
Canonical IS/FWD raw Sharpe uses the existing daily-preferred sample, first
daily observation excluded, ddof=1 and 365 annual periods. Inclusive first-day
returns used for floor attribution are separately identified.

Here **native means the existing selector/anchor, not a Python backend**.
All financial runs use the prepared public Rust intrabar authority. Exact
Numba/NumPy features, Python Optuna/orchestration, Rust accounting/Ridge/ranking
and cold Python reporting remain distinct responsibilities.

## Primary Recipe Results

Primary comparison: **group TPE + floor, meta OFF**, against legacy TPE +
existing selector, meta OFF. All numbers below are paired-quarter raw-Sharpe
units, not return percentages or whole-account Sharpe.

`D = IS - FWD`, `R = D_reference - D_policy`,
`Q = FWD_policy - FWD_reference`, `R = IS_effect + Q`.

| Alpha | Valid pairs / 19 | R | IS effect | Q |
|---|---:|---:|---:|---:|
| SC | 18 | +0.0350 | +0.2788 | -0.2438 |
| HMA | 18 | +0.5098 | +0.3483 | +0.1615 |
| HASH | 19 | -0.3477 | -0.1566 | -0.1911 |
| VWAP | 13 | +1.3992 | +0.5023 | +0.8969 |

SC's small positive R does not mean better forward quality: lower IS more than
offsets worse FWD. HMA/VWAP have encouraging point improvements in both R/Q;
HASH deteriorates. These are not grounds to replace Mode 4 globally.

Every study and account exists. Unusable analysis slots arise from retained
NO_VARIANCE observations, not missing optimizer runs. The private readback's
masked MISSING slots retain their underlying measurement reasons; the public
summary exposes those exclusions. No flat Sharpe is imputed as a valid zero.

The registered estimand requires the entire 19-by-eight R/Q matrix. SC/HMA/
VWAP leave undefined coordinates, so the **joint family is INCONCLUSIVE**.
The predeclared two-quarter moving-block/16,384-draw/95%-family procedure is
not executed on an incomplete matrix. No CI is invented, HASH-only family
substituted, gap compressed or available-case mean promoted to that estimand.

## Sampler And Selector Mechanisms

Each row reports its own paired support. Different rows need not have the same
quarters and must not be added together as if they did.

| Alpha | Sampler-only n / R / Q | Floor-only on legacy n / R / Q | Floor-only on group n / R / Q |
|---|---|---|---|
| SC | 17 / +0.1448 / +0.0935 | 18 / +0.1287 / -0.1750 | 17 / +0.0697 / -0.1603 |
| HMA | 16 / +0.2845 / +0.5485 | 18 / +0.0195 / -0.2390 | 17 / +0.2826 / -0.1987 |
| HASH | 19 / -0.0891 / -0.1023 | 19 / +0.3061 / +0.2920 | 19 / -0.2586 / -0.0888 |
| VWAP | 8 / -0.7450 / -0.6153 | 12 / +0.4757 / -0.0626 | 11 / +1.0638 / +0.3247 |

Group TPE is promising for HMA candidate generation, but not uniformly better.
The floor selector often reduces IS more than it improves FWD; on HASH it
helps the legacy pool but hurts the group pool. VWAP's sparse support prevents
interpreting its large point differences as a general sampler recommendation.
Compatibility is not evidence that one kernel wins every alpha.

## Incremental Meta Results

The following contrasts use each sampler's **own existing-selector anchor**.
They are restricted to paired-valid quarters with an actual learned model,
not the early fallback quarters. This is a descriptive mechanism view.

| Alpha | Legacy learned n / R / Q | Group learned n / R / Q |
|---|---|---|
| SC | 5 / -0.4955 / -1.1544 | 4 / +1.7215 / +0.9814 |
| HMA | 5 / +0.9928 / +0.0747 | 4 / +1.7624 / +0.9148 |
| HASH | 6 / +1.2379 / +0.8046 | 6 / +0.5553 / -0.1341 |
| VWAP | 1 / +0.3151 / +0.3095 | 0 / NA / NA |
| Matched RSI | 6 / +4.7910 / +1.9516 | Not registered |

HASH/legacy and the matched RSI reference improve forward quality as well as
decay. SC/group and HMA/group are encouraging, but only four valid learned
quarters support each mean. HASH/group's positive R accompanies worse FWD;
this distinction is essential. Results depend on candidate generation and
anchor family, not solely on turning meta on.

The floor-anchor meta contrasts are also fully retained. Learned-quarter Q is
SC legacy/group +0.0909/+0.5459, HMA -0.5315/-0.2571,
HASH -0.6123/-0.6101, VWAP -0.0211/-1.2907. Positive R alongside those negative
Q values must not be marketed as improved forward retention.

First actual native-family fit is 2025Q2 for SC/HASH/RSI, 2025Q3 and 2025Q4
for HMA legacy/group, 2026Q2 for VWAP legacy, and absent for VWAP/group.
Floor families generally fit in 2025Q2, except VWAP/legacy in 2025Q4.
Actual sealed decisions and paired-valid analysis counts are separate in the
JSON: e.g. VWAP legacy fits twice but only one learned pair has defined Sharpe.
An evaluation-ID change is separately distinguished from a change of effective
parameter dictionary.

Fresh quarterly history plus the one-second publication lag permits at most
six learned decisions. No monthly history, relaxed minimum or re-used model
manufactures twelve learned evaluation quarters. The new matched RSI result
supports the existing positive evidence; it does not replace its original
protocol or become a new broad economic-promotion certificate.

## Diagnostics And Researcher Interpretation

Five first-IS worksheets reuse the actual 128-attempt baseline pool and add
two-center selection/held-local probes before opening current forward data.

| Alpha | VALID prefix records | Numeric dimensions | Additional physical probes |
|---|---:|---:|---:|
| SC | 125 | 3 | 23 |
| HMA | 126 | 10 | 73 |
| HASH | 128 | 5 | 43 |
| VWAP | 97 | 8 | 68 |
| RSI | 128 | 8 | 59 |

Held local worst raw-Sharpe deltas reach about -0.918/-0.319 for SC's two
centers, -0.595/-0.061 for HMA, -0.726/-2.202 for HASH,
-0.442/-1.541 for VWAP and -2.571/-0.246 for RSI. These identify uneven local
fragility and activity support, not global sensitivity indices or proof that
a dimension count selects a sampler. The adaptive TPE design is explicitly
not a neutral Sobol experiment. Local validation probes are not recycled as
optimizer/meta training input or used to select a favorable challenger later.

## Accounting, Measurement And Causality

- All 34 saved schedules map exact effective dictionaries, evaluation IDs and
  windows to sealed decisions. Continuous accounts preserve native pending
  orders/protection across quarters; no diagnostic-equity concatenation.
- Each final account is independently recompiled from its saved schedule and
  executed again. Equity, returns, positions, fees, funding, margin, protection,
  event flags, fills and liquidation agree exactly.
- Early, **each family's first fit**, and late checkpoints exercise 146 actual
  selected-account/isolation runs. Saved forward witnesses match, independent
  NumPy daily Sharpe agrees, and nonempty future-market mutations preserve
  past paths/fills. Last checkpoints without a future suffix make no mutation claim.
- Actual pool readback covers off/shadow/active, own-family labels, maturity,
  full-pool ranking, model/scaler parity, future/late-label exclusion and a
  permitted-past correction positive control. Eight cells have full actual
  qualification, including two exact-source receipt reuses. VWAP/group has
  qualified floor-family fit but no mature native-family model; its cell status
  stays INCONCLUSIVE_NO_MATURE_MODEL for that missing evidence, not falsely PASS.
- Three verifier gaps found by independent review were fixed before final
  qualification: consumed-file hashes, complete policy sets, and per-family
  first-fit account checkpoints. Fifteen focused tests pass. A serialization
  mistake in the first hardening test run remains as failed XML; no study used it.
- Seven ordered-prefix recovery tests pass; 54 focused schedule/sampler/shard
  default regressions pass. Earlier source-bound accounting, feature, policy,
  analysis and qualification tests remain retained without a blanket rerun.

The data is research-exposed. These information-flow checks do not restore a
pristine unseen OOS. Original/research bridge controls retain explicit HMA,
HASH and VWAP lifecycle ablations; neither return equality nor global original-
alpha equivalence is claimed. All strategy code/ranges/data remain ignored.

## Accounts And Cost

Full risk/cost/fill/exposure scalars for every policy are in the JSON. Examples
below are corroboration, **not the primary decay statistic**:

| Own native family | Final equity OFF -> active | Fees OFF -> active |
|---|---:|---:|
| RSI/legacy | 20,444.19 -> 22,414.59 | 427.87 -> 479.33 |
| HASH/legacy | 20,037.61 -> 20,209.81 | 1,323.44 -> 1,153.78 |
| SC/legacy | 23,080.56 -> 21,093.80 | 154.89 -> 214.92 |
| HMA/group | 19,151.80 -> 19,677.41 | 3,205.26 -> 3,206.80 |

Whole-account returns/Sharpe are distinct from mean reset-segment metrics.
Fills are not the legacy activity/position-regime counter used by descriptors.

## Performance, Failures And Recovery

Main financial queue time, including failed lanes, is **3,127.72 s / 52.13 min**.
Serial source/measurement/account qualification adds **1,104.64 s / 18.41 min**;
their sum is **70.54 min**, below the prospective 90-minute target. This is
measured queue/verifier work, not total interactive development time or a
matched production meta-on/off latency comparison.

The first export failure retained completed IS journals. The next queue stopped
at the host available-RAM floor, not accounting corruption; every owned child
was reaped. The successor uses at most three workers. Peak worker-sum RSS is
about 1,151 MiB; verifier-parent peak is 331 MiB. These are different measurements,
not a fabricated single system-wide peak. Numeric pools remain configured to
one thread; unrelated kernels/services were not signalled.

Completed folds are content-checked/hardlinked. Their histories are independently
rebuilt from original IS and standalone forward witnesses before continuation.
Partial folds replay fresh deterministic ask/tell with **every** recorded
proposal/score/daily path checked; only missing or invalid-observation work is
executed. This is not persisted exact Optuna/full-WFO checkpoint recovery or
seed-only resumption. Interrupted uncommitted work remains UNKNOWN, not zero.

Exact feature optimizations pass their original-array/control tests. Fast
variant execution also changes lifecycle intentionally: its speed is **not an
unchanged-original-alpha benchmark**. Recorded fit/seal replay timestamps are
availability clocks, not wall computation timers. Sampler time and retained
fold-search time remain separately exposed; observer work is not free.

See the [terminal cleanup receipt](../maintenance/M5_11_6_1_TERMINAL_CLEANUP.md).
No rebuild, environment duplication, CI, push, merge or publication occurred.

## Mode 4 Decision And Handoff

| Component | Recommendation | Basis |
|---|---|---|
| Global Mode 4 defaults | KEEP_CURRENT_MODE4 | No complete joint economic promotion; effects vary by alpha/pool |
| Shared prefix diagnostics/coverage/causal witnesses | STANDARDIZE_SHARED_DIAGNOSTICS_ONLY | Useful measured fragility/support and reusable qualified owners |
| Group TPE for HMA/SC | INCONCLUSIVE_KEEP_DEFAULT | Encouraging candidate-generation points; keep existing explicit sampler option |
| Group TPE for HASH/VWAP | KEEP_CURRENT_MODE4 | No uniform benefit; sparse VWAP support and negative HASH points |
| IS-segment floor as universal selector | KEEP_CURRENT_MODE4 | Frequent lower-IS-only effects; real sampler-selector interaction |
| Incremental meta | INCONCLUSIVE_KEEP_DEFAULT | Positive HASH/legacy and RSI evidence retained; six learned quarters maximum |

This recommendation does not disable existing sampler/meta opt-ins or assert
absence of edge. It rejects an automatic global replacement from these cells.
The owner may review the component matrix before authorizing a versioned
research opt-in or M5-11.7 reporting integration; none is activated here.

Private receipts, actual dictionaries, models, full rankings, all 19-quarter
R/Q rows, negative results and failure history remain under
`upgrade/private/mode5_upgrade_v1/m5-11-6-1/fast-v1`. Final-source installed
wheel/sdist/package qualification remains M5-12, not this research certificate.

# M4-ML-06 - Decision Value And Prefix Diagnostics

**Local technical gate: PASS, bounded registered scope.** Economics are exploratory,
heterogeneous and do not activate a production policy. Frozen Ridge V1 remains available.

## What Was Compared

Original ETHUSDT 1h SC/HMA/HASH/VWAP; rolling730D; 128 attempts/origin already executed.
All 228 native/Ridge decisions are retained. Primary evaluation is 32 monthly origins/alpha,
February2024--September2026. Existing 13 acquisition and12 development origins stay separate.

N=native anchor; R=Ridge V1; X=frozen X2 with the same history and guard;
G=Ridge with Qhat>=0; F=Ridge ranked by maximum Qhat under the old guard.
G/F are component ablations. Constant Yhat=0 is an incumbent/tie control, not random search.

## Decision Value Against Native

| Alpha | Policy | Changed/32 | Observed/32 | Help/Harm/Tie | Mean R | IS contribution | Mean Q |
|---|---|---:|---:|---|---:|---:|---:|
| A-HASH | R | 28 | 32 | 14/14/4 | +1.9284 | +1.6835 | +0.2449 |
| A-HASH | X | 32 | 32 | 14/18/0 | +1.4937 | +2.0808 | -0.5871 |
| A-HASH | G | 27 | 32 | 12/15/5 | +1.7080 | +1.5856 | +0.1225 |
| A-HASH | F | 28 | 26 | 7/15/4 | +0.0532 | +0.6535 | -0.6004 |
| A-HMA | R | 32 | 32 | 13/19/0 | +1.2075 | +1.8150 | -0.6075 |
| A-HMA | X | 31 | 32 | 17/14/1 | +1.7981 | +1.5646 | +0.2335 |
| A-HMA | G | 32 | 32 | 14/18/0 | +1.5321 | +1.7658 | -0.2337 |
| A-HMA | F | 32 | 26 | 14/12/0 | +1.6900 | +1.0377 | +0.6523 |
| A-SC | R | 32 | 20 | 12/8/0 | +0.9643 | +0.5959 | +0.3684 |
| A-SC | X | 32 | 17 | 6/11/0 | +0.2811 | +1.0997 | -0.8186 |
| A-SC | G | 31 | 20 | 11/8/1 | +1.1318 | +0.5047 | +0.6271 |
| A-SC | F | 31 | 20 | 10/9/1 | +0.2040 | +0.2769 | -0.0729 |
| A-VWAP | R | 32 | 11 | 5/5/1 | +1.6476 | +1.7474 | -0.0998 |
| A-VWAP | X | 32 | 10 | 4/5/1 | +3.2678 | +2.2165 | +1.0512 |
| A-VWAP | G | 31 | 11 | 3/7/1 | +0.9730 | +1.6451 | -0.6721 |
| A-VWAP | F | 32 | 5 | 1/2/2 | +0.1428 | +0.1663 | -0.0235 |

Raw-Sharpe differences from reset diagnostic accounts; the count conditions each mean.
Unknown/undefined months are not zero. Different masks must not be compared as identical cohorts.
R=(IS_anchor-IS_selected)+Q. Positive R alone does not establish improved forward quality.

## Matched Incremental Decisions

| Alpha | Contrast | Valid/32 | Changed/32 | Help/Harm/Tie | Delta R | Delta Q |
|---|---|---:|---:|---|---:|---:|
| A-HASH | F-R | 26 | 25 | 8/11/7 | -2.0552 | -1.1708 |
| A-HASH | G-R | 32 | 7 | 3/4/25 | -0.2203 | -0.1224 |
| A-HASH | R-N | 32 | 28 | 14/14/4 | +1.9284 | +0.2449 |
| A-HASH | X-R | 32 | 27 | 9/18/5 | -0.4347 | -0.8320 |
| A-HMA | F-R | 26 | 20 | 10/4/12 | +0.2142 | +0.8736 |
| A-HMA | G-R | 32 | 2 | 2/0/30 | +0.3246 | +0.3738 |
| A-HMA | R-N | 32 | 32 | 13/19/0 | +1.2075 | -0.6075 |
| A-HMA | X-R | 32 | 24 | 15/9/8 | +0.5906 | +0.8410 |
| A-SC | F-R | 19 | 18 | 4/8/7 | -0.5606 | -0.2522 |
| A-SC | G-R | 20 | 6 | 4/2/14 | +0.1675 | +0.2587 |
| A-SC | R-N | 20 | 32 | 12/8/0 | +0.9643 | +0.3684 |
| A-SC | X-R | 16 | 29 | 5/11/0 | -0.2864 | -0.7224 |
| A-VWAP | F-R | 5 | 25 | 1/3/1 | -2.8524 | -1.5641 |
| A-VWAP | G-R | 11 | 7 | 0/2/9 | -0.6746 | -0.5723 |
| A-VWAP | R-N | 11 | 32 | 5/5/1 | +1.6476 | -0.0998 |
| A-VWAP | X-R | 9 | 27 | 5/2/2 | +1.5437 | +1.4089 |

## Prediction Versus Decision Error

| Alpha | Model | Acquired-origin MSE | Origins | Changed-winner MSE | Winner observations |
|---|---|---:|---:|---:|---:|
| A-HASH | R | +18.6641 | 32 | +19.1213 | 28 |
| A-HASH | X | +18.4345 | 32 | +18.4185 | 32 |
| A-HMA | R | +17.3597 | 32 | +18.3601 | 32 |
| A-HMA | X | +17.0132 | 32 | +25.5042 | 31 |
| A-SC | R | +3.3478 | 21 | +10.0043 | 20 |
| A-SC | X | +3.5245 | 21 | +4.9181 | 17 |
| A-VWAP | R | +14.5699 | 12 | +11.3823 | 11 |
| A-VWAP | X | +15.1652 | 12 | +20.4503 | 10 |

The acquired and winner masks differ; these columns diagnose selection concentration,
not two independent tests or a fair winner-versus-randomized-sample experiment.

## Existing Acquisition Sensitivity

| Reviewed development panel | Zero MSE | Ridge MSE | X2 MSE |
|---|---:|---:|---:|
| base | +10.7124 | +9.7506 | +9.4976 |
| union | +10.9520 | +10.3381 | +9.8963 |

These are reused development results, not new evaluation losses. Base and union are related
acquisition panels; the old policy's winner union can alter training support. Primary ML06
decision comparisons all use the same logged union, keeping model effects matched.

## Witnessed Candidate Opportunity

| Alpha | Policy | Supported/32 | Better base candidate | Mean positive headroom | Best excluded by guard | Ranking misses within guard |
|---|---|---:|---:|---:|---:|---:|
| A-HASH | F | 26 | 25 | +5.0943 | 22 | 17 |
| A-HASH | G | 32 | 29 | +4.4232 | 24 | 19 |
| A-HASH | R | 32 | 29 | +4.3008 | 24 | 19 |
| A-HASH | X | 32 | 30 | +5.0700 | 16 | 29 |
| A-HMA | F | 26 | 24 | +4.7980 | 18 | 19 |
| A-HMA | G | 32 | 30 | +5.9144 | 23 | 24 |
| A-HMA | R | 32 | 31 | +6.2744 | 24 | 25 |
| A-HMA | X | 32 | 29 | +5.4755 | 24 | 17 |
| A-SC | F | 20 | 16 | +2.1867 | 6 | 14 |
| A-SC | G | 20 | 13 | +1.7721 | 6 | 11 |
| A-SC | R | 20 | 14 | +1.9612 | 4 | 14 |
| A-SC | X | 17 | 17 | +2.6057 | 5 | 16 |
| A-VWAP | F | 5 | 4 | +3.3353 | 3 | 3 |
| A-VWAP | G | 11 | 10 | +4.8929 | 9 | 8 |
| A-VWAP | R | 11 | 9 | +4.3206 | 6 | 8 |
| A-VWAP | X | 10 | 8 | +3.4045 | 5 | 8 |

Opportunity uses only the preexisting base panel plus anchor. New winner queries are excluded
from that benchmark. Feature-dependent acquisition and missing labels prevent full-pool or
global-parameter-space regret claims. Guard and ranking misses need not be disjoint.

## Downside And Guard Reliability

| Alpha | Policy | Observed predictions | Q<0 | Q<-0.10 | Qhat-Q bias | Worst Q | Mean worst20% Q |
|---|---|---:|---:|---:|---:|---:|---:|
| A-HASH | R | 32 | 14 | 14 | +0.0012 | -6.7623 | -5.2892 |
| A-HASH | X | 32 | 18 | 18 | +1.5999 | -6.4041 | -5.2290 |
| A-HASH | G | 32 | 15 | 15 | +0.1879 | -6.7623 | -5.2892 |
| A-HASH | F | 26 | 15 | 15 | +1.1903 | -5.9953 | -4.7810 |
| A-HMA | R | 32 | 19 | 18 | +1.1519 | -11.3083 | -6.9969 |
| A-HMA | X | 32 | 14 | 14 | +0.5148 | -10.5142 | -6.8089 |
| A-HMA | G | 32 | 18 | 17 | +0.8056 | -11.3083 | -6.7777 |
| A-HMA | F | 26 | 12 | 12 | +0.1902 | -4.9197 | -2.8813 |
| A-SC | R | 20 | 8 | 8 | -0.0028 | -8.0926 | -3.7504 |
| A-SC | X | 17 | 11 | 11 | +1.8841 | -2.7666 | -2.5330 |
| A-SC | G | 20 | 8 | 8 | -0.2174 | -8.0926 | -3.2850 |
| A-SC | F | 20 | 9 | 9 | +0.6057 | -5.6482 | -3.3747 |
| A-VWAP | R | 11 | 5 | 5 | +0.3079 | -7.9877 | -5.0598 |
| A-VWAP | X | 10 | 5 | 4 | -0.5909 | -5.8480 | -4.3314 |
| A-VWAP | G | 11 | 7 | 7 | +0.9186 | -7.9877 | -5.1197 |
| A-VWAP | F | 5 | 2 | 2 | +0.4084 | -1.5757 | N/A |

A stricter predicted guard is not a realized outcome guarantee. Worst20% uses fractional
empirical mass and requires ten observed folds; these are Sharpe-difference units, not money.

## Prefix Diagnostics And Next Actions

| Alpha | Native selectors, all57 | Median absolute IS feature share | Leading next action |
|---|---|---:|---|
| A-HASH | {'fallback_best_is_temporal': 39, 'medoid': 18} | +0.4147 | KEEP_RIDGE_RESEARCH |
| A-HMA | {'fallback_best_is_temporal': 21, 'medoid': 36} | +0.2525 | ANCHOR_RETENTION_OR_GUARD_STUDY |
| A-SC | {'medoid': 57} | +0.2211 | KEEP_RIDGE_RESEARCH |
| A-VWAP | {'fallback_best_is_temporal': 9, 'medoid': 48} | +0.3748 | INCONCLUSIVE_WITH_EXACT_GAP |

IS feature contribution is exact served standardized arithmetic, not causal importance.
Adaptive TPE coverage is not neutral-design sensitivity. Missing local probes and environment
paths remain explicit. Compatibility, measured sampler response and original-alpha proof differ.

## Uncertainty

Exploratory R-N and X-R intervals reserve16 coordinates, use shared3-month moving blocks,
16,384 draws/seed731/family95%. Each numerical coordinate requires the complete32-month
metric calendar; unsupported coordinates get no interval. G/F remain descriptive.

| Coordinate | Status | R interval | Q interval |
|---|---|---|---|
| A-HASH/R-N | DEFINED_EXPLORATORY | [-0.1693, +4.0806] | [-1.7861, +2.1588] |
| A-HASH/X-R | DEFINED_EXPLORATORY | [-2.4044, +1.6325] | [-2.5892, +1.0722] |
| A-HMA/R-N | DEFINED_EXPLORATORY | [-0.5805, +3.5471] | [-2.4416, +1.7203] |
| A-HMA/X-R | DEFINED_EXPLORATORY | [-1.0976, +2.2704] | [-0.8847, +2.5897] |
| A-SC/R-N | INCONCLUSIVE_INCOMPLETE_CALENDAR | N/A | N/A |
| A-SC/X-R | INCONCLUSIVE_INCOMPLETE_CALENDAR | N/A | N/A |
| A-VWAP/R-N | INCONCLUSIVE_INCOMPLETE_CALENDAR | N/A | N/A |
| A-VWAP/X-R | INCONCLUSIVE_INCOMPLETE_CALENDAR | N/A | N/A |

These conditional intervals do not restore independent OOS or include uncertainty from
choosing models after reviewed development. Earlier family receipts are not rewritten.

## Existing Quarterly Sampler And Selector Evidence

| Alpha | Contrast | Valid/19 | R | Q |
|---|---|---:|---:|---:|
| A-HASH | interaction | 19 | -0.5647 | -0.3807 |
| A-HASH | primary | 19 | -0.3477 | -0.1911 |
| A-HASH | sampler_only | 19 | -0.0891 | -0.1023 |
| A-HASH | selector_only/tpe_legacy | 19 | +0.3061 | +0.2920 |
| A-HASH | selector_only/tpe_multivariate_group | 19 | -0.2586 | -0.0888 |
| A-HMA | interaction | 16 | +0.0766 | -0.1726 |
| A-HMA | primary | 18 | +0.5098 | +0.1615 |
| A-HMA | sampler_only | 16 | +0.2845 | +0.5485 |
| A-HMA | selector_only/tpe_legacy | 18 | +0.0195 | -0.2390 |
| A-HMA | selector_only/tpe_multivariate_group | 17 | +0.2826 | -0.1987 |
| A-SC | interaction | 17 | -0.0780 | +0.0070 |
| A-SC | primary | 18 | +0.0350 | -0.2438 |
| A-SC | sampler_only | 17 | +0.1448 | +0.0935 |
| A-SC | selector_only/tpe_legacy | 18 | +0.1287 | -0.1750 |
| A-SC | selector_only/tpe_multivariate_group | 17 | +0.0697 | -0.1603 |
| A-VWAP | interaction | 7 | +1.2685 | +1.5462 |
| A-VWAP | primary | 13 | +1.3992 | +0.8969 |
| A-VWAP | sampler_only | 8 | -0.7450 | -0.6153 |
| A-VWAP | selector_only/tpe_legacy | 12 | +0.4757 | -0.0626 |
| A-VWAP | selector_only/tpe_multivariate_group | 11 | +1.0638 | +0.3247 |

Quarterly/365D fast variants remain a separate experiment; no new optimizer was run.
Prefix input eligibility does not prove advice was sealed before each study. No automatic
sampler/selector router or universal winner is certified.

## Work, Safety And Handoff

New learner fits: 145; numeric/reference/qualification charges: 153.
Financial calls: 132; measured stage CPU 662.59s, wall 665.76s.
Cold measured CPU 180.92s; query process peak 696.09MiB.
Queries outside the fixed budget: 26 {'F': 26}.
First native-path setup error was not timed; source-binary correction precedes all finance. Measured work excludes this failed startup.

All four original-route controls match complete metric/account witnesses exactly.
Fresh causal controls, permitted-past positives and unchanged source-bound earlier market
proofs are recorded separately. Queried labels never enter the fitted histories.
The historical union was acquired by the old policy; alternative decisions condition on
that logged history and do not constitute a replacement-policy acquisition rollout.

Keep V1 available; prioritize selection/guard and prefix support explanations before a larger model search.

Per-alpha cards, coverage, exact contrasts, tails and source hashes are in
[the machine summary](../../benchmarks/optimization/meta_selection/model_research_v1/ml06_summary.json).
M5-11.7/M5-12, public activation, CI, builds, push and release await separate approval.

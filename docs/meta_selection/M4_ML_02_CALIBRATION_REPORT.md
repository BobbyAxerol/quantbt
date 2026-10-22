# M4-ML-02 - Common Calibration Versus Frozen Ridge

## Decision And Scope

**COMPLETE_LOCAL_REGISTERED_RESEARCH / technical PASS / empirical INCONCLUSIVE.**
Decision: **KEEP_FROZEN_V1**. No default, public endpoint, financial engine,
sampler, target, Q guard, alpha or account changes. ML-03..05 and older
M5-11.7/M5-12 still require separate approval; no push/CI/release occurred.

The [research guide](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md),
[admission](M4_ML_01_ADMISSION_REPORT.md) and
[phase plan](../../upgrade/implement.md#m4-ml-02) are authoritative.
The [sanitized measured comparison](../../benchmarks/optimization/meta_selection/model_research_v1/ml02_results.json)
contains the full metrics/null masks. Tables below are generated from it.

## Method And Rights

Reuse the original four ETHUSDT 1h/730D/monthly groups, 57 origins and original
128-attempt pools; **zero new optimization proposals and financial executions**.
No quarterly proxy replaces original callback/feedback economics. Acquiring
13 origins, then 12 development and 32 evaluation months is unchanged.

- P0: origin-sum lambda=10; effective mean strength 10/K.
- P1: fixed mean alpha=10/12; sum lambda=K*10/12. Same solution as P0 at K=12.
- P2: common six-point calibration, excluding the held-out alpha group;
  coefficients may fit compatible own past. It is not an alpha-name lambda table.

Calibration freezes at the actual first evaluation cutoff,
2024-01-31 23:00 UTC. January outcomes published seconds later are unavailable.
Each inner scaler/model uses its own permitted historical snapshot, never a
full-corpus scaler. Future target records physically present in storage confer
no fit/rank rights. Existing reviewed outcomes remain **exploratory**, not a new
untouched external OOS or prospective live forecast.

Base-only acquisition is primary; original winner-union is sensitivity and V1
reproduction. Both are feature/policy-dependent finite panels, not full-pool
outcome oracles. Every policy ranks the full current valid IS pool. Missing new
winner outcomes remain null; selection is never restricted to labeled candidates.

## Served Prediction Loss

Y is signed relative decay in Sharpe points. MSE has squared-Sharpe-point units,
with equal origin weight followed by equal alpha-group weight. Each group uses
its explicitly supported months; this is a conditional descriptive macro mean.
Matched Y/Q errors have opposite signs and identical MSE/MAE, not two separate
confirmations. RMSE, MAE, bias, calibration slope, pair accuracy and rank support
are retained in the measured JSON/private origin ledgers.

| Group | Valid loss origins | P0 MSE | P1 MSE | MSE reduction |
|---|---:|---:|---:|---:|
| A-SC | 21/32 | 2.916571 | 2.953607 | -1.270% |
| A-HMA | 32/32 | 17.170406 | 17.135438 | +0.204% |
| A-HASH | 32/32 | 18.596717 | 18.049886 | +2.940% |
| A-VWAP | 12/32 | 14.690847 | 14.943797 | -1.722% |

Macro MSE: **13.343636 -> 13.270682, reduction 0.547%**, below the
registered 2% shortlist hurdle. More shrinkage lowers effective degrees of
freedom in every group, but does not produce uniform predictive improvement.
HASH's lower loss is not by itself a better selected-candidate outcome.

Original union sensitivity, not another independent replication:

| Group | P0 MSE | P1 MSE | MSE reduction |
|---|---:|---:|---:|
| A-SC | 3.347823 | 3.375231 | -0.819% |
| A-HMA | 17.359704 | 17.280555 | +0.456% |
| A-HASH | 18.664096 | 18.165518 | +2.671% |
| A-VWAP | 14.569858 | 14.883784 | -2.155% |

The [initial complexity/stability/cost curves](../../benchmarks/optimization/meta_selection/model_research_v1/ml02_curves.json)
retain all six development settings, degrees of freedom and neighboring-alpha
coefficient stability in the same origin/basis. No per-alpha winner is promoted.
Pilot cost points span first-mature/middle/final K; per-alpha-grid latency was
not separately timed and is not invented from total replay time.

## Decisions And Economic Limits

Below, delta is P1 minus P0 on origins where both selected forward witnesses
exist and Sharpe is defined. Delta-R = delta-IS-contribution + delta-Q.
These are **not** continuous-account Sharpe, final equity or a full-WFO rerun.

| Group | Paired observed origins | Delta R | Delta IS contribution | Delta Q | Changed winners |
|---|---:|---:|---:|---:|---:|
| A-SC | 15/32 | -0.12628 | -0.02243 | -0.10385 | 6/32 |
| A-HMA | 21/32 | +0.14208 | -0.22409 | +0.36617 | 16/32 |
| A-HASH | 18/32 | -0.79985 | -0.26626 | -0.53359 | 18/32 |
| A-VWAP | 2/32 | -2.37035 | -0.31285 | -2.05750 | 15/32 |

HMA's conditional Q improves, while HASH's conditional Q worsens despite better
panel MSE. This shows why loss, guard calibration and served decisions must be
checked together; it does not establish a universal causal explanation. VWAP's
two primary paired points cannot support a broad economic conclusion. Missing
new-winner labels are not assumed random; even the direction can be conditional.
No novel-policy continuous equity, DD, fees or campaigns are fabricated.

The registered six-coordinate family uses shared three-month calendar blocks,
16,384 draws/seed 731 and family 95%. Missing calendar slots remain in place.
**Numerical family bootstrap is not executed:** complete-calendar support fails.
No coordinate is dropped, compressed, imputed or retuned. Point summaries do not
certify the Q/R noninferiority margins. This is not proof of no economic edge.

## P2 Support And Explicit Abstention

Usable pre-cutoff inner origins are SC/HMA/HASH/VWAP=7/11/11/2. Training groups
containing VWAP fail the three-origin rule. With VWAP held out, the three other
groups still lack three complete calendar blocks with every group/month valid.
The owner [confirmed](../../benchmarks/optimization/meta_selection/model_research_v1/ml02_owner_block_clarification.json)
**three months per group per block**, not one valid row somewhere in a quarter.
This clarification followed audit/review; it is not a new untouched registration.
Therefore all four P2 recipes explicitly fallback P0.
P2's displayed losses equal P0 by fallback, **not** a successful calibration.
It remains scientifically unresolved whether supported common calibration helps.

The finite six-point inner replay still executed and is retained; none of those
alpha-group curves is converted into a hand-tuned per-alpha lambda. There is no
online hyperparameter controller, Q-floor adjustment or new model family here.

## Technical Qualification And Actual Work

- All **228 unique union P0 decisions** match retained V1;
  full-pool scores/guards/ties match and maximum coefficient difference is
  **0.0**. Alias calls are not extra origins.
- The cold audit verifies all **1168 policy/panel/calendar rows**,
  456 original revision/selection pins and 24 raw account/fill/report files.
  Raw accounting is unchanged; its prior original-engine proofs are reused.
- Actual-history HMA control: K=24, full pool
  122 candidates, P0/P1/fixed-grid learner.
  Unavailable future corrections preserve all predictions/winners; permitted past
  correction changes coefficients without inflating origins. Mutations are
  explicitly synthetic in-memory controls, never admitted as economic labels.
- Independent weighted augmented-least-squares/scaler/guard/normalization oracles,
  restore/cache/resource controls and grouped/calibration/future-label tests pass.
  See [final tests](../../benchmarks/optimization/meta_selection/model_research_v1/ml02_final_tests.xml)
  and [closure](../../benchmarks/optimization/meta_selection/model_research_v1/ml02_closure.json).

One initial wrapper failed at a portable filename collision after useful work;
it remains **FAIL_RETAINED**. Independent review also caught partial blocks
misnamed intact, missing null/status telemetry and a missing prospective pilot
admission calculation. All are repaired with tests and explicit source-bound
[erratum](../../benchmarks/optimization/meta_selection/model_research_v1/ml02_registration_v3.json).
Completed fixed-policy groups and both inner grids were recovered without model
refits; invalid old P2 decisions were excluded. This is pure-model evidence
recovery, **not** exact Optuna/full-WFO checkpoint recovery. No old FAIL becomes PASS.

Corrected replay: wall **248.049 s**, CPU
**247.029 s**, peak process RSS **462.50 MiB**.
Including failed work, counted historical regression work is
**2489 fits** and **677.228 CPU s**;
actual-history controls add 14 regression/qualification fits.
Failed-run wall time was not recorded; it is not manufactured from CPU time.
Numeric/reference parity solves are counted; proposal/restore certification
solves and software-test oracles are separately identified verification work.

Historical replay plus these actual-history controls count
**2503 regression/qualification fits**, below the 4,000 ceiling.
Software-test fits and repeated same-model certification solves are not novel
historical fits; they are verification work, not additional outcome evidence.

Corrected replay Rust boundary: 1604 numeric calls,
46,595,095 input-owned bytes, one observed
numeric thread. Historical scaler/report work remains NumPy/Python; no all-Rust
or whole-public-WFO latency claim. Timers are fit/rank/report only for newly
executed parts; cold ingestion, custody/recovery and retention are real additional
cost, not secretly attributed to ML kernels. No new environment, dependency,
native build, market download or duplicated optimizer is used.

## Handoff

Retain the frozen V1 baseline. P1 does not meet the registered gain/generality
requirements; P2 is correctly abstaining, not disproven. More flexible models
must justify their capacity/cost with permitted origin support and actual Q/R,
not only a lower training loss. ML-03..05 remain separately approved research.
Exact inactive test scratch is cleaned; all failed/passing evidence, private
alpha/data and the reused native environment remain. Cleanup and final measured
bill are in the closure receipt, not a claim that all future optimization is done.

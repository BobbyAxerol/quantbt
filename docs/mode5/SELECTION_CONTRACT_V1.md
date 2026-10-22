# M5-07 Selection Contract V1

## Scope And Ownership

This is the research-only implementation of [guide M5-07](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-07--canonical-objectives-four-selectors-và-formula-migration).
It does not activate public endpoint selectors, perform calibration, simulate
orders, fetch data or authorize deployment. M5-08 owns registered empirical
batteries; M5-09 owns dossier/calibration sealing; M5-10 owns public integration.

`tools/mode5_selection` consumes qualified inputs from the existing statistics,
geometry and diagnostic permission layers. There is no new account engine,
prepared cache, sampler, market owner or Python/Rust bridge. A producer must
retain actual execution, metric, environment, qualification and generation
evidence. Supplying a string reference does not certify that its underlying
backtest or search actually ran.

## Typed Inputs

- `Channel`: economic utility in decimal account-return units, PSR/evidence
  probability, or explicitly named legacy Sharpe utility. The metric contract
  is part of the channel identity: classical PSR and HAC are not interchangeable.
- `Panel`: exact environment roster, strictly positive declared weights,
  immutable candidate metrics and actual analysis/access witnesses, generation
  provenance and a shared alpha/economics/schema/scope context identity.
- `Candidate`: actual parameter digest and evaluated-representative status;
  feasibility, risk, economic quality and support gates reference their producer
  evidence. Activity penalties explicitly have the same channel unit. Financial
  gates are not inferred from a numerical rank or overwritten by a selector.
- `SelectionPlan`: frozen formula/preferences, stage, reference, local scale or
  Pareto reference, access-policy identity, exact tie policy and incumbent margin. No implicit defaults
  for mathematical coefficients or hidden reference fitting.
- `LocalEvidence`: one complete or explicitly failed/missing record for every
  expected unique effective probe; same weighted-environment-mean aggregate for
  center and probes; qualified schema coverage, optional covariance and local
  validation reference. `geometry.from_geometry` preserves the M5-06 ledger.
- `ParetoPreference`: frozen ideal/worst values, maximize/minimize directions,
  positive weights, zero-range and extrapolation policies.
- `AdvisoryDossier`: versioned, context-matched, mature development evidence
  and a measured recipe shortlist. V1 is advisory, not automatic routing.

No holdout/independent-validation policy can construct a selection panel.
Every candidate, probe and dossier access is checked for role, manifest and
readiness at the permitted cutoff, independently of cache identity. Missing
environment results stay null and make that candidate ineligible. Failed local
probes or inadequate geometry make local/unified evidence incomplete, not a
smaller favorable neighborhood. Valid losses and risk failures stay in reports.

Snapshots use frozen dataclasses and immutable tuples; output JSON is canonical
and callers receive fresh decoded dictionaries. Pickle/deepcopy cannot make
underlying score arrays writable because policy snapshots contain no mutable
array ownership. Nested mutable metric components are rejected. Fingerprints
are computed once per immutable DTO; replacement creates a fresh identity and
every probe/dossier access remains checked. Cached/uncached reducers must return
byte-identical decision JSON and hashes under the same contract.

## Formula Registry

`registry.formula_registry()` is the machine-readable inventory. Formula,
channel, coefficients, reference, plan, probes, Pareto preferences and dossier
audit contribute to selection identity. Component tables have separate hashes.

| Version | Meaning |
|---|---|
| `environment_floor_mean_v1` | Environment minimum + declared weighted mean coefficient - activity penalty |
| `legacy_floor_mean_regret_v1` | Minimum - coefficient times weighted average regret; equals floor + mean - a frozen constant, not minimax |
| `legacy_spec_1_1_quantile` | Explicit guide PSR prototype: floor + linear quantile - unweighted midpoint-median MAD; equal weights required; not CVaR |
| `environment_lower_tail_v2` | Floor + exact lower probability-mass mean - weighted MAD; fractional boundary atoms |
| `finite_panel_minimax_regret_v1` | Negative maximum environment regret from a frozen economic-utility benchmark; finite panel, not global optimum |
| `local_downside_v1` | Same aggregate at center minus gamma times worst observed downside |
| `unified_same_channel_v1` | Declared weighted floor/mean/population weighted SD/local downside combination |
| `pareto_chebyshev_v1` | Direction-aware finite Pareto front, then fixed weighted Chebyshev compromise with augmentation |

Weighted median/MAD use the shared M5-03 **lower half-mass tie** convention.
Legacy quantile replay deliberately retains NumPy linear interpolation and
midpoint median/MAD; these differences are versioned, not a compatibility fix.
Alpha one in the tail means weighted mean. A tail confined to the minimum atom
is reported as floor/tail redundancy; quantile replay is not given that badge.

Economic utility is `net_return - dd_weight*MDD - tail_weight*daily_loss_ES`,
with positive-magnitude MDD and explicit preferences. Costs already reside in
net account returns and are not deducted twice. Its input producer must qualify
matched horizons or an explicit time-rate convention. Different episode Sharpe
values are never relabelled aggregate account Sharpe. Evidence-channel selection
still needs independent economic/risk/support gates.

Local downside is owned by `mode5_statistics.tails.local_downside`; M5-06
geometry and M5-07 selection call that same reducer. Gamma one and zero extra
penalty equal the minimum of the center aggregate and all evaluated probes.
Downside normalization uses a frozen positive scale, never the center's absolute
value. A finite tested neighborhood is not a global robust ball or a SAM theorem.

## Four Slots

| Slot | Required policy |
|---|---|
| `full_dro_cvar` | Explicit environment or unified version; name does not turn a quantile or regret into CVaR |
| `full_sam_basin` | Qualified schema plus optional covariance probes, evaluated representative and explicit local version |
| `full_pareto_chebyshev` | Exact environment/direction/preference reference; admissible front and component gaps retained |
| `full_alpha_adaptive_invariant` | Matching advisory dossier plus explicit researcher recipe choice/reason, frozen formula and all resolved-slot requirements |

Without a researcher decision the adaptive slot returns
`NO_SELECTION / RESEARCHER_DECISION_REQUIRED`. It does not inspect alpha names,
skew labels, radar maxima or validation outcomes. Overrides of first advice are
recorded; recipes outside the qualified shortlist require a new dossier/plan.
There is no silent algorithm fallback or auto deployment.

Pareto zero-width dimensions are explicitly non-discriminative both in ranking
and dominance. Extrapolation is either `allow_and_report_v1` (no clipping) or
`reject_v1`; both are frozen. Duplicate front values use the declared candidate
ID tie break. Adding an outlier cannot refit existing preference scales.
Generation metadata remains QMC/TPE/CMA/actual NSGA-II as supplied by its
producer; Pareto post-selection is not NSGA-II generation. No hypervolume or
selected-point performance is invented by the selector.

An incumbent receives the same panel, probes, gates and score. The decision
reports pre/post incumbent candidates and the declared improvement margin.
An ineligible incumbent cannot overrule a valid challenger. No supported
configuration yields typed `NO_SELECTION`, not a forced best-of-bad. All
decisions carry `edge_claim=NOT_ASSESSED` and `deployment_authorized=false`.

## Migration And Reproduction

Existing public Mode 5 `full_robust`, `full_plateau_robust`,
`full_temporal_robust` and `full_best` are unchanged. The guide replay version
above is **not** a claim that T2 used actual PSR or that these new slots existed
in the published package. T1/T2 original records, labels and bytes remain intact.
Winner-only summaries cannot reconstruct an unavailable complete candidate
panel; they cannot fabricate new PSR, local-probe or Pareto evidence.

`StageLedger` is a research guard over immutable completed objective observations,
not a replacement Optuna study or checkpoint service. It binds both the plan
and each component row to one formula/reference identity. A changed benchmark
must create a registered revision and rescore every comparable completed
candidate via `rescore_revision`; old observations remain untouched. Reanalysis
generates a new `SelectionDecision`, never overwrites a historical decision or
mixes old/new trial values. Numerical oracle tolerance is `1e-12` on registered
finite scalar cases; historical core tolerances are unchanged.

## Verification

[M5-07 report](M5_07_SELECTION_REPORT.md) maps M5T-061..070 to commands and
receipts. Public test fixtures contain synthetic values only; private alpha,
parameters, paths and retained evidence are excluded from Git/package outputs.
Use the approved tooling environment with `PYTHONPATH=src:.` and one numeric
thread. The pure scalar oracle does not import the tested implementation.

No Rust extension was rebuilt or numerically promoted in M5-07. NumPy handles
finite-panel vectors/fronts; shared statistics own tails/medians/downside;
bounded 32-row front blocks avoid a full N*N*E temporary. Full policy timings
include gates, hashes/components and output serialization and are reported
separately from lightweight mathematical-reference timings.

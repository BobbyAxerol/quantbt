# Effective Geometry And Active Local Probes V1

## Scope

`tools/mode5_geometry` is an opt-in research layer. It does not modify alpha
sources, execution, Mode 1..4, legacy Mode 5, sampling/search defaults, objective
values or deployment. Read the [phase plan](../../upgrade/implement.md#mode5-m5-06)
and [detailed geometry guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#45-trục-2--parameter-geometry-và-landscape).

## Schema And Effective Identity

`EffectiveGeometry.from_ranges` reuses the existing `NormalizedSearchSpace` and
`ParameterSpec` parser/validator. Numeric bounds, linear/log transforms, integer
steps, categorical choices, conditional parents, positive axis weights and
source-proven inactive policies are registered before outcomes. No sampled
min/max or sample covariance changes the distance units.

`ResolvedPoint` records immutable raw and effective JSON, active axes and cast/
branch changes. Only explicit `truncate_integer_v1` source casts apply; other
grid violations fail. Inactive values do not create effective candidates.
Adding a fixed/inactive field cannot inflate active distance denominators.
Ordered coupled constraints reject invalid values, never silently sort them.
Any alternative latent prior/repair policy needs a new registered version.

Distance is schema-weighted Gower-like: numeric normalized differences,
categorical mismatch one, and union-axis penalty one for active-branch mismatch.
Categories are not label-encoded Euclidean coordinates or inputs to PCA.
Log units are distances after the declared log transform. Repeated source casts,
quantization or conditional omissions must retain their original proposal rows.

## Coverage And Proposal Roles

`ProposalLedger` preserves raw rows, feasible points, collision references and
infeasibility reasons. A reserved neighborhood center uses collision reference
`-1`; clipping back onto that center is not a newly evaluated neighbor.

`neutral_coverage` uses explicit power-of-two branch quotas and scrambled SciPy
Sobol cubes with a fixed seed. Numeric coordinates use the registered linear/log
mapping and nearest feasible grid decoding; categorical slots are discrete
choice bins, not geometric coordinates. This design is not a clone sampler
registry and does not route public WFO. Invalid coupled rows remain in place;
they are not silently resampled to improve apparent coverage.

Separate roles are `exploration`, `geometry_fit`, `selection_probe` and
`local_validation`. Report raw, unique-effective, failed and duplicated work.
128 proposals do not certify 128 distinct configs, all corners or a complete
high-dimensional landscape. An unexecuted coverage design is not market evidence.

## Schema Plus Covariance Neighborhoods

`active_neighbors` always creates independent signed schema moves, adjacent
integer/grid moves, categorical flips and explicitly requested joint moves.
Boundary clipping, invalid coupled points, center clones and effective
duplicates remain visible. Per-axis/group effective radii and minimum distinct
support gate the resulting evidence.

A same-branch basin-local cloud may add covariance proposals. It never replaces
schema directions. Sparse/singular clouds explicitly fall back to schema-only.
Supported clouds use `(1-rho) covariance + rho diagonal + tau^2 I`; rho, tau,
cloud radius and support are frozen development policies. The cloud is not a
Hessian, a plateau volume estimate or a proof of unseen generalization.

Validation uses a separate registered seed/design. `held_support` reports
overlapping versus distinct effective proposals; different seed labels alone
do not imply independent economic observations. These are held development
directions, not chronological OOS.

## Screening And Structured Sensitivity

`paired_screen` retains utility, risk/tail, cost, turnover, opportunities and
holding effects with explicit units and missing/failed cells. A flat utility
response cannot automatically remove a parameter that changes another channel.
No confidence interval is invented from one paired market path. Screening is
labelled `paired_local_multi_metric_v1`, not global Sobol sensitivity.

`saltelli_layout` counts `N(D+2)` first/total-order input rows or `N(2D+2)` with
second order, separately multiplying execution scenarios. Design admission
checks full A/B/cross matrices and every output row. Plain QMC/TPE panels,
conditional/coupled inputs without an explicit independent latent design,
missing rows or nonfinite outputs fail closed. Constant output is undefined,
not a vector of zero sensitivity indices. A separately registered structured
SALib/Morris extension is required for global indices and uncertainty; M5-06
does not launch a market Saltelli sweep.

The design contracts follow [SALib's structured sensitivity requirements](https://salib.readthedocs.io/en/latest/api/SALib.analyze.html#module-SALib.analyze.sobol)
and [SciPy's Sobol power-of-two guidance](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.Sobol.html).

## Basin Evidence And Representatives

`local_summary` requires one status/value per distinct feasible probe, including
runtime failures. It reports center utility, empirical downside, survival,
observed minimum and frozen-reference normalized roughness. The minimum is not
mislabelled CVaR. Units must match center/neighbors; adding a utility constant
does not change absolute downside or fixed-reference roughness.

Flat-negative controls fail center quality. A good center with poor neighbors
is fragile. Missing results or insufficient effective directions remain
incomplete, not filtered into a successful basin certificate.

`basin_catalog` builds separately named schema-radius connected components, not
clusters inferred to be profitable. `representative` distinguishes a finite
evaluated medoid from a new schema-quantized centroid. Categorical/conditional
arithmetic means are rejected. Any new representative requires actual financial
evaluation and sufficient local quality/support before a later selector may use it.

## Ownership, Privacy And Rollback

M5-04 execution/analysis keys and every-access authorization remain authoritative.
Geometry/schema, probe design, membership, units and reference policies belong
in analysis/selection identities; changing them never overwrites old outcomes.
Fresh mutable alpha/account state is required for each executed candidate.

Private alpha schemas, params, traces, helpers and market paths stay in ignored
research lanes, outside Git and the core package. Public tests use synthetic
math/market controls. Roll back by disabling these views and retaining the full
original schema or qualified schema-only probes. No parameter is automatically
pruned, and no live switch or new selector is activated by this contract.

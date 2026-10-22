# Diagnostic Dossier And Calibration Governance V1

## Scope And Authority

Research-only implementation of [guide M5-09](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-09--dossier-advisory-và-calibrationplan-trước-tuning),
[schemas](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#74-core-evidence-schemas)
and [M5T-081..090](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#m5-09--dossier-và-advisory-governance).
`tools/mode5_dossier` does not simulate, fetch market data, run Optuna, activate
an endpoint, authorize orders or certify an installed distribution. Financial,
metric and canonical selector authorities remain unchanged.

M5-10 owns public integration. This phase approval is not a researcher choice
of a formal recipe, economic preferences or a new study budget.

## Evidence And Six Matrices

`EvidenceCatalog` checks actual parsed bytes against the registered SHA/size,
then snapshots them for one assembly lifetime. Returned values are copies.
Explicit diagnostic roles, source manifests and availability cutoffs are checked
with the existing `AccessPolicy`/`AccessWitness`. A matching hash does not grant
selection or validation rights. Sources are rehashed before a seal/search entry.
This verifies declared producer provenance, not authenticity of an arbitrary
researcher's invented witness or a digitally signed trust chain.

`Matrix` is an exact roster of source-bound records, which may retain nested
tables. Matrix-record count is not unique financial executions or statistical N.
An independently frozen inventory prevents omissions, substitutions and extra
rows. Every row keeps its source, JSON pointer and content hash:

| Kind | Evidence |
|---|---|
| `parameter_representation` | Full schema, active/fixed/cast/constraint mappings and paired effects |
| `candidate_environment` | All actual cells and bindings, reset/continuous namespaces and support |
| `center_neighbor_environment` | Requested/effective designs, observed and unexecuted probe records |
| `environment_environment` | Rank/overlap, leave-out and paired transfer with interval/support |
| `recipe_split_seed` | All formula decisions, sampler studies and complete trial ledgers |
| `execution_stress` | Registered cost/risk controls, mechanics and explicit unexecuted scopes |

No interpolation, omission of negative trials, liquidation/fee reinterpretation
or conversion of missing observations into zero. Short, annual, partial-year
and continuous-account views are not pooled into a common utility horizon.

## Five Axes And Radar

The dossier keeps mechanics/economics, geometry, environments, transfer and
distributions/tails separate. Technical reconciliation, observed support,
economic eligibility and independent validation are different fields.

Radar points have raw values, units, directions, support, uncertainty and a
source-bound frozen definition. A justified scale may be explicitly supplied;
it cannot change with later candidates. Without one, rendering is `RAW_ONLY`
and normalized values are null. Missing raw values remain null with a reason.
There is no neutral score of 50, composite winner or inferred alpha taxonomy.
The actual dossier uses predeclared representative diagnostics, not five
comparable standardized scores or a summary of every regime.

## Advisory And Recipe Choice

Readiness ordering uses measured eligibility/coverage and versioned recipe IDs
as a deterministic tie-break, not an economic preference inferred from names.
Each item retains effects, source decisions, limitations and reasons. Current
whole-procedure status is `NO_CLEAR_WINNER`; no automatic router is qualified.
Low rank correlation does not disqualify a stable best candidate. Sparse,
no-trade, all-negative or wide-interval results are not technical invalidity.

A finite-panel candidate may be considered without claiming independent
recipe superiority. Insufficient full-schema local probes cannot be rescued
by sampler density. The two DRO formulas are not independent confirmations.
The existing [canonical advisory layer](SELECTION_CONTRACT_V1.md#four-slots)
continues to own actual selector resolution; this phase does not replace it.

## Plan And Chronology

`CalibrationPlan` has two explicit states:

- `DEFER_CALIBRATION`: source/context/dossier sealed, zero search budget;
  unchosen recipe fields are null with reasons. Search entry is denied.
- `RESEARCHER_CHOICE`: explicit canonical formula/channel/coefficients,
  selector/tie-break, sampler/fallback/seeds/schedule, domain, probe budget,
  constraints/support, retention/reuse, incumbent, failure and validation
  contracts are frozen. A recipe outside the eligible dossier needs a new
  diagnostic revision, not an override of technical validity.

`GovernanceLog` writes exclusive, hash-linked events with actual seal times.
Dossier precedes plan; a current matching plan and fresh declared selection
rights precede a formal-search entry. Revisions/override reasons remain
auditable. `require_formal_chronology` rejects a formal trial timestamp preceding
the seals; old diagnostic trials cannot be backfilled as pre-sealed calibration.
The journal detects modified/missing-middle/reordered events. It is not an
authenticated filesystem or protection against an actor deleting/replacing an
entire history; retained receipt hashes are the external audit references.

These are metadata guards, not an implemented search runner or economic
permission bypass. Validation child results cannot change the parent label
`none_full_sample_calibration`. No state grants deployment authority.

## Reuse And Invalidation

Alpha, data, economics, effective schema, roles, metric contract, references and
scope are dependencies. Any change invalidates affected dossier/plan seals.
Metric/reference changes can retain execution, but analysis must be revised.
Rights-only changes require fresh authorization even when numeric analysis is
reusable. Report/display changes do not require financial reruns when scientific
dependencies are identical. A new identity never edits a historical receipt.

Immutable canonical records survive JSON, deepcopy and pickle; public decoded
metadata cannot alter a snapshot or leave a stale hash behind.

## Qualification

See the [M5-09 report](M5_09_DOSSIER_REPORT.md),
[public summary](evidence/m5-09.json) and
[unified phase](../../upgrade/implement.md#mode5-m5-09).
All actual alpha dossiers, parameters, matrix contents and complete manifests
stay in ignored private lanes, outside Git/package artifacts. Only synthetic
governance fixtures are public. Independent economics/whole-procedure routing
remain M5-11; endpoint/wheel/release qualification are not claimed here.

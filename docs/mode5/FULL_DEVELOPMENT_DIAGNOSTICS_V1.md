# Full-Development Diagnostic Reports

## Purpose

Diagnostics describe a declared development sample before a researcher chooses
an objective, sampler and parameter selector. They do not automatically choose
a recipe, certify an alpha's edge or change strategy/accounting behavior.
Mode 5 still aims for one externally fixed parameter dictionary. Internal
strategy adaptation remains part of the original strategy.

The [detailed guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#chapter-4)
and [approved phase](../../upgrade/implement.md#mode5-m5-11-4) define the scientific
scope. A readable report is not a certificate that every requested experiment
has run. Missing, censored, adverse and no-trade observations stay visible.

## Scope And Reuse

`DevelopmentCalendar` records requested/provider/scored bounds, common readiness,
missing hours and partial years. An unavailable prefix is a data limitation,
not an arbitrary full-year warmup. Candidates within one alpha share the same
scored calendar. Complete UTC days are actual observations; partial 2026 is not
rounded up to a year.

For the current M5-11.4 study, the owner approved scoring from January 1, 2020
with original strategy warmup kept flat and reported separately. The readiness
inventory remains a source witness, not a reason to silently drop that prefix
or to disable original strategy gates. All candidates share the January-start
account calendar; their actual warmup durations may differ. No unavailable
pre-2020 prices are invented. An account previously started at common readiness
is retained as older-convention evidence, not relabeled as January-start data.

Changing scored start, source, market, financial initial state, fee or terminal
policy can invalidate financial reuse. Never concatenate older equity paths
onto a new starting account. `WorkQuestion` and `work_manifest` bind each reuse
decision to matching identities and its incremental work. Re-rendering existing
evidence executes no finance, search, model fitting or RNG draws.

Annual and state views attribute one continuous account. Yearly return uses
actual entering equity. State PnL is the sum of actual marked PnL on those dates;
positions crossing a boundary are not silently closed/reopened. Different state
families overlap and their contributions must not be added together.

## Six Views

| View | Questions Answered |
|---|---|
| Scope/test behavior | What dates, sources, roles and methods were actually used? What was reused, executed or missing? |
| Parameter profile | What does each input control? Is it active, conditional, ignored, cast or coupled? Which measured outcomes vary? |
| Parameter regions | Which points/neighbors were evaluated? Where are risk, fragility, collisions and coverage gaps? |
| Environment profile | Which years/states contribute PnL, costs and tails? Do candidate ranks, good sets or leave-out choices change? |
| Stress profile | What exact assumption changed? Does an actual matched rerun differ, including strategy feedback? |
| Decision worksheet | Which compatible recipe experiments answer the remaining question, and what is their cost and counter-evidence? |

Each finding distinguishes **measured evidence**, **source facts** and
**hypotheses**. It carries value/unit, support, uncertainty, source pointer,
interpretation, rival explanation, decision implication and next test.

An alpha quality/risk profile is separate from recipe suitability. A weak
annual result does not automatically mean no edge. Conversely, good past equity
does not establish out-of-sample transfer or a superior optimizer.

## Method Limits

- Branch-local finite-panel rank associations are screening, not causal effects
  or Sobol indices. Candidate-resampling intervals are conditional on that
  roster, not market-return confidence intervals. Degenerate replications are
  retained and can suppress an interval.
- Signed local effects use matched paths and effective distances. Integer
  collisions, clipping, newly active children and infeasible coupled moves are
  disclosed. Small effects on Sharpe can coexist with large effects on risk.
- Global S1/ST requires the complete registered independent A/B/cross design,
  declared marginals/representation and measured outputs. No failed rows may be
  discarded to make that design valid. Estimates are not clipped to hide
  finite-sample uncertainty; prefix diagnostics do not guarantee convergence.
- Full-set fitted state thresholds are descriptive. Decision-vintage labels
  require a historical fit/availability cutoff and separate namespace. The
  latter's future-mutation test does not certify a full calibration procedure.
- Conditional state moments are not annualized account Sharpe. Sparse/unknown
  states and nonpositive-equity return limitations remain explicit.
- Doubling fees requires an actual engine/strategy rerun when behavior depends
  on the account; subtracting a fee estimate from old returns is not that test.

## Cold Reader

The canonical reporting API consumes the existing dossier and evidence catalog:

```python
from quantbt.mode5.dossier.researcher_report import ResearcherReport

# dossier and catalog are existing source-bound Dossier/EvidenceCatalog owners.
report = ResearcherReport.read(dossier, catalog)
private_json = report.to_json()
private_markdown = report.to_markdown()

# Add typed ReportView/Finding annotations when researcher interpretation exists.
# Verify a retained report against the current evidence bytes/access policy.
restored = ResearcherReport.from_json(private_json)
restored.verify(catalog)

# Only the structural, redacted view is suitable for public examples.
public_json = restored.to_json(public=True)
public_markdown = restored.to_markdown(public=True)
```

`ResearcherReport.read(..., views=...)` accepts typed annotations. Measured
findings must point to the exact immutable source value; they cannot introduce
different numbers by editing prose. A report without annotations preserves the
original dossier, matrices and masks, but does not invent researcher conclusions.

Private alpha source, names/values, market data, prose and provenance are not
included in the public export. Detailed actual research reports stay in the
ignored private evidence lane. This phase does not change public backtest/WFO
endpoints or activate the subsequent formal calibration phase.

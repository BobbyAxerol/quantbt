# Fold Consistency And Decision Reports

## Scope

`quantbt.diagnostics.ResearchDecisionReport` is an additive cold reader/reducer.
It reads original typed observations and decisions, not strategies or market
data. It does not fit, predict, optimize, replay accounts, change params or draw
bootstrap/optimizer RNG. See [M5-11.7.2](../../upgrade/implement.md#mode5-m5-11-7-2),
[guide 16.3](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md#mlr-r3)
and [local qualification](M5_11_7_2_IMPLEMENTATION_REPORT.md).

It complements [pre-search diagnostics](PRESEARCH_RESEARCHER_REPORT.md), rather
than using a post-WFO outcome as earlier pre-search evidence. Normal endpoint
signatures, metrics, report defaults, financial ownership and Ridge V1 are
unchanged. This is feature-branch source functionality, not a published-wheel
or expanded meta-capability claim.

## Endpoint And Result Access

On a completed public WFO run the same reader is available without extracting
metadata manually:

```python
report = endpoint.research_report(access=access, source_ref="my-original-run")
# Or the same completed legacy/V2/event/score result:
report = result.research_report(access=access, source_ref="my-original-run")
# Works with a result-like object too, including prepared numeric W3:
report = ResearchDecisionReport.from_result(
    result, access=access, source_ref="my-original-run",
)
print(report.to_markdown())
public_json = report.to_json()
private_snapshot = report.to_json(private=True, detail=True)
```

`access` must be an explicit existing reporting policy as below, not a permission
inferred from the result or final clock. The accessor returns a report object,
does not print, store an attached cache, enable an observer or run a strategy.
`full_report()`, `show_metrics()`, plots and all constructor defaults are unchanged.
Merely having the accessor on an inherited options/event result does not make
options, every WFO mode or a standalone backtest eligible for meta reporting.

Prepared W3 uses its explicit root metadata schema, not the generic nested
`walk_forward` key. Its declared reset-flat/segmented/no-continuous-equity
markers must agree; supplying a continuous-account report is rejected. Its
result-like interface is `ResearchDecisionReport.from_result(...)`, not a new
method added to the reactive engine/result owner.

For diagnostics-first Mode 5 use the same call with its original witness:

```python
report = endpoint.research_report(
    access=full_development_access,
    source_ref="my-original-calibration",
    witness=full_development_witness,
    role=full_development_witness.role,
    max_report_bytes=16 * 1024**2,  # explicit budget for a large retained ledger
)
```

The selected dictionary comes from the original `best_trial.params` and must
match the runtime decision. No missing dictionary, observation or full-data
witness is guessed. Mode 5 does not accept causal prefix/cohort overrides.
Native/meta-off runs without observer labels retain their old reports; this
new comparison accessor explicitly reports missing evidence rather than
backtesting counterfactuals. Typed original records may still be supplied to
`mode4(..., decision=None)` for the disabled-policy view.

See [coverage, unavailable fields and M5-12 handoff](REPORTING_COVERAGE_AND_HANDOFF.md).

## Read A Completed Mode 4 Run

```python
from quantbt.diagnostics import AccessPolicy, ResearchDecisionReport

wf = result.metadata["walk_forward"]
meta = wf["meta_selection"]
revisions = meta["observed_revisions"]

# Explicit rights for this reviewed diagnostic, not selection/deployment rights.
access = AccessPolicy(
    policy_id="my-reviewed-report",
    roles=("diagnostic_development",),
    manifests=tuple(sorted({t.corpus_id for t in meta["tasks"]})),
    cutoff_ns=max(int(r.revision_available_at.value) for r in revisions),
    purpose="diagnostic",
)
report = ResearchDecisionReport.from_walk_forward(
    wf,
    access=access,
    source_ref="my-original-completed-result",
    role="diagnostic_development",
)
print(report.to_markdown())        # public, private identifiers/params redacted
summary = report.to_dict()
private = report.to_dict(private=True, detail=True)
```

The normal-metadata reader currently requires Mode 4 / `per_fold_causal`,
original active/shadow sidecars and typed observed revisions. It joins revisions
by task identity, not snapshot order. Applied params must match the original
selected candidate and activation; shadow proposals are not applied params.
Serialized histories need the existing witnessed persistence decoder, not a
trusted JSON verification flag.

When no observer revisions were retained, this reader fails explicitly: it
cannot derive counterfactual R/Q from the final equity. It never enables the
observer or reruns finance to fill that gap. Some missing revisions in an
otherwise qualified roster remain explicit missing fold records.

For retained records or a native/meta-off comparator use the same reducer:

```python
from quantbt.diagnostics import (
    FoldDecisionEvidence, FoldSlot, ReportCohort, ResearchDecisionReport,
)

# Each item binds an original SealedTaskRevision, decision (or None for off),
# exact source witness and source ref. These are not reconstructed fake labels.
report = ResearchDecisionReport.mode4(
    evidence,
    roster=slots,   # ordered FoldSlot IDs and half-open forward mark windows
    access=access,
    cohorts=(ReportCohort("evaluation", evaluation_ids, "frozen-protocol"),),
)
```

`mode4` requires one compatible family: schema, route, instrument, timeframe,
window, raw metric, economics, sampler, anchor and account policy. Original
monthly/730D, RSI/365D and quarterly research variants are not pooled. A missing
calendar slot stays in the denominator. Cohort IDs must be distinct, ordered
and inside the roster; an empty cohort is empty, never an all-calendar fallback.

## Quantities And Masks

For candidate `s` and native anchor `a`, all Sharpe values use the original raw
metric contract, not a clustering or trade-penalized objective:

```text
D_a = I_a - O_a                     D_s = I_s - O_s
R   = D_a - D_s                     Q   = O_s - O_a
IS contribution = I_a - I_s         R = IS contribution + Q
```

Positive R can coexist with negative Q. The report does not demand positive
every fold or OOS greater than IS. Help/harm/tie means realized Q sign; R sign
is separately counted. Unknown or undefined Sharpe is not a zero or a loss.

Each quantity has its own ordered mask. Q needs both forward observations;
R and the matched decomposition require all four valid raw operands. The report
shows own-metric masks and a separate common-mask decomposition. Do not subtract
means from different populations or add their components as if matched.

Built-in cohorts are all-calendar, model-ready, native fallback, meta-disabled,
applied-changed and proposed-changed. Registered evaluation masks are additional.
Same-ID/effective decisions remain in whole-policy statistics. Same parameters
do not manufacture zero differences if source observations differ; undefined
same-anchor Sharpe also remains undefined.

| View | Returned Information |
|---|---|
| Fold trace | IS/forward windows, cutoff/seal/action/availability clocks, original pool/budget provenance, native/proposed/applied vectors, IDs and model/snapshot references |
| Decision state | Model support, ready/fallback, exact original prediction/guard/tie/rank, applied versus proposed change and available execution-comparison witness |
| Consistency | Help/harm/tie and magnitudes, mean/median/sample dispersion, extrema/linear quantiles, time/state populations and adjacent parameter turnover |
| Downside | Worst Q, negative-Q mean/magnitude, fractional empirical worst20% when at least ten observed folds |
| Forward quality | Positive raw OOS Sharpe separate from positive net account return, each with its own support |
| Activity and costs | Original metric-contract activity counts, available return/DD/exposure/fee/funding/fill/action/campaign observations in named units |
| Predictions | Selected Q MSE/MAE/bias, Y MSE and guard failures; Y/Q errors are algebraically related, not independent tests |
| Acquired-label loss | Existing qualified training-row witnesses, equal observed labels within origin then equal origins; anchor exclusion follows the original training-row owner |
| Controls | Permitted `Yhat=0` and `Yhat=deltaIS`/`Qhat=0` errors on the same witnessed mask, not randomized choices or executed replacement policies |
| Opportunity | Original fixed acquired base panel plus anchor only; coverage and observed headroom are not a full-pool oracle |

State labels have their own source, witness and purpose. Future labels are denied;
full-development/descriptive labels cannot advise a prefix. State families can
overlap and time groups are dependent views, not independent regimes. Mark-span
days and exact windows are disclosed; there is no invented full-year coverage,
annualization or horizon weighting. The first/last groups may be partial.

## Original Metrics And Accounts

`MetricSupplement` binds retained scalar metrics and explicit units to the exact
forward-observation digest. Copy original endpoint/MET values; do not synthesize
return/DD/costs from raw Sharpe. Actual zero is distinct from null. Source activity
counts are not fills, and fills are not closed actions/campaigns.

`RetainedAccountReport` accepts an original qualified continuous account with
its result/contract identity, exact start/stop, witness, units and policy. Its
default scope must match the reported window. The explicit
`contains_reported_window` option retains the actual larger full-calendar scope,
including a legacy flat pre/post-OOS period; it does not reslice or recompute
metrics. Such metrics stay separately labelled, not mean fold metrics. Reset
diagnostic equity is never joined into a purported carried account.

Many old minimal label archives retain raw Sharpe/activity but not per-candidate
net return, DD or fees. Those fields are explicitly unavailable even when a
different continuous account exists. Supplying that continuous account does
not silently populate independently reset fold diagnostics.

## Mode 5

```python
from quantbt.mode5 import DecisionReport
from quantbt.diagnostics import ResearchDecisionReport

original = DecisionReport.read(
    wf["mode5_diagnostics_first"],
    selected_params=wf["best_trial"]["params"],
)
report = ResearchDecisionReport.mode5(
    original, access=full_development_access,
    witness=full_development_witness, source_ref="original-calibration",
)
```

This delegates validation to the existing Mode 5 reader and preserves the fixed
dict, selector/formula/components, incumbent disposition, actual whole/annual
observations, support/risk/quality exclusions, replay and sampler telemetry.
`NO_SELECTION` stays no selection. Independent reset windows are not relabelled
continuous. Full-scope selection is NOT_BACKDATABLE, not causal WFO or independent
OOS. Missing older scope fields remain explicitly partial. A known first-trial
timestamp cannot come after the source's claimed readiness.

## Intervals, Reload And Cost

`RetainedInterval` copies an existing registered coordinate, mask, estimate,
bounds, policy/source ref and witness. The exact comparison, ordered observed
mask and mean must agree. Absent/unsupported intervals stay nonnumeric; no new
bootstrap, family adjustment or estimator runs. Existing intervals remain
conditional on their original reviewed recipe/history and dependence policy.

Private complete snapshots are explicit:

```python
saved = report.to_json(private=True, detail=True)
restored = ResearchDecisionReport.from_json(saved)
restored.authorize(access)
```

Public/compact views are not reloadable scientific snapshots. Immutable Records
survive copy/pickle/JSON; altered summaries, observations, masks, application or
witnesses fail. Changed access needs reassembly, not cache relabelling. Source
declarations are not authentication against a malicious producer.

Budgets fail without truncation: default 2,048 folds, 250,000 input candidates,
64 named cohorts, 384 retained interval coordinates, four continuous account
reports and 4 MiB assembled private JSON. Explicit larger report caps are allowed;
real retained Mode 5 snapshots use 16 MiB in local qualification. Reporting is
cold Python/NumPy with shared numeric owners, not new Rust execution or an
all-workload speedup claim. Cold endpoint/result accessors are qualified in
[M5-11.7.3](M5_11_7_3_IMPLEMENTATION_REPORT.md); installed qualification remains
M5-12, not inherited from source tests.

Run [the synthetic example](../../examples/shared_decision_reporting.py):

```bash
PYTHONPATH=src:. .venv/bin/python -m examples.shared_decision_reporting
PYTHONPATH=src:. .venv/bin/python -m examples.completed_research_reporting
```

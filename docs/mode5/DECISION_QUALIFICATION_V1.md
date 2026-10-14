# Mode 5 Decision Qualification

`DecisionReport` is an additive cold reader for diagnostics-first Mode 5.
It does not change an endpoint, objective, sampler, account engine or selected
dictionary. Reading/rendering it executes no financial query, no reduction and
no RNG draw. It does not grant current evidence rights or deployment permission.

## Read The Actual Decision

```python
from quantbt.mode5 import DecisionReport

wf = result.metadata["walk_forward"]
report = DecisionReport.read(
    wf["mode5_diagnostics_first"],
    selected_params=wf["best_trial"]["params"],
)
private = report.to_dict(private=True)
print(report.to_markdown(private=True))
```

The dictionary must be the actual selected vector. A different vector, altered
objective/component, inconsistent sampler state or mismatched replay is rejected.
The report retains:

- Frozen selector, formula, channel, coefficients and reference identities.
- Actual sampler class/settings/startup/relative-versus-independent telemetry.
- Complete/pruned/failed states and duplicate evaluation references.
- Objective scores separately from raw account-return Sharpe.
- Selected dictionary, incumbent outcome, alternative scores and gate exclusions.
- Annual/environment observations and selected original-endpoint replay.
- Continuous-account versus independently reset-window semantics and compute bill.

The readable view has separate trial, candidate-component and environment tables.
The JSON view retains more detailed immutable provenance, not just a winner.

## No Selection

```python
from quantbt.mode5.runtime import Mode5NoSelectionError

try:
    result = endpoint.backtest(data=development, param_ranges=param_ranges)
except Mode5NoSelectionError as error:
    report = DecisionReport.read(error.mode5_metadata)
    print(report.to_markdown(private=True))
```

`NO_SELECTION` retains exclusions and null/adverse observations. The reader
does not substitute an arbitrary best trial or create a selected audit/vector.
It also recognizes a source-qualified no-candidate failure before any decision
was sealed, with that distinction explicitly shown.

## Privacy And Reload

`to_dict()`, `to_json()` and `to_markdown()` default to public redaction: parameter
names/values, recipe knobs, private IDs/strings and source context remain masked.
Numerical performance, states and allowlisted formulas remain descriptive.
`private=True` deliberately exposes actual dictionaries and detailed provenance;
keep that export outside public repositories/package resources.

```python
stored = report.to_json(private=True)
reloaded = DecisionReport.from_json(stored)
```

A redacted public view is not a reloadable scientific snapshot. Immutable
records remain internally consistent across copy/pickle/reload. The reader
serializes actual sampler timestamps without guessing their timezone and uses
the existing finite portable codec for other scalars. Invalid payloads fail.

## Runnable Synthetic Example

```bash
python examples/mode5_synthetic_decision.py --workdir /tmp/mode5-demo-new --private
```

The new directory retains eight actually executed diagnostic accounts and the
dossier/plan journal before a six-proposal public study. `--private` exposes only
the example's synthetic dictionary; omit it for a redacted report. Reusing the
same directory rejects instead of overwriting evidence. This intentionally small
32-day, one-environment example teaches the complete workflow, not economics.
Unrun geometry/stress/transfer/sampler batteries are explicit, and the formula
is a researcher preference, not an inferred winner. The full-development
continuous provider is a distinct binding; this demo does not relabel reset-flat
observations as continuous annual attribution.

## Scientific Interpretation

### Whole-Account Quality Mandate

For an explicitly approved continuous calibration, freeze the optional policy:

```python
from quantbt.mode5.continuous_eligibility import WholeAccountEligibility

binding = continuous_calibration_binding(
    eligibility_policy=WholeAccountEligibility(),
    **frozen_binding_inputs,
)
```

This versioned policy requires original whole-account quality and finite whole
Sharpe, plus whole/annual risk and annual support. Negative annual utility is
retained for floor/tail ranking, not automatically disqualified. Its presence
changes the binding/context identity and must precede a newly sealed plan.
Omitting it preserves the previous all-environment quality contract and binding
bytes. It never changes returns, equity, costs, drawdown or an estimator.

The separate raw research control can seal the same policy. Both controls retain
measured numeric feedback and enforce the declared eligibility at final selection;
gate-excluded complete observations are not relabelled as execution failures or
erased from the work bill. Compare selector-only on the same eligible panel,
sampler-only under the same objective/policy, and combined recipes separately.

Diagnostics precede a prospectively sealed `CalibrationPlan`. Selector-only
comparisons use the same qualified pool; sampler-only studies freeze objective,
selector, domain, budget and data; end-to-end recipes require separately declared
procedure/validation rights. A missing hard-eligible cohort remains unsupported.
Quality/support thresholds are mandate preferences, not an excuse to alter an
estimator or rescue an adverse study after seeing its outcome.

The continuous provider runs one original account per effective query. Annual
views are dependent attribution, not account resets or independent observations.
The earlier reset-flat provider keeps its own contract; the report does not
relabel it. Full-development scores and shorter decay are not independent
forward quality or a universal edge guarantee.

See [public calibration](PUBLIC_CALIBRATION_V1.md),
[full-development diagnostics](FULL_DEVELOPMENT_DIAGNOSTICS_V1.md),
[M5-11.5 plan](../../upgrade/implement.md#mode5-m5-11-5) and
[guide comparison levels](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử).

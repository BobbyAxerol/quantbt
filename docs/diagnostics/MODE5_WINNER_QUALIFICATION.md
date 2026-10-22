# Mode 5 Winner Qualification And Optional Archive Donors

Source-branch, researcher-controlled support. The supplement does not change
Mode 4/5 defaults, scientific estimators, account engines, Ridge, sampler RNG or
selection policy. Source tests are not installed-package or release certification.

## Completed-Run Entry

The existing endpoint and result `research_report` methods accept one optional
typed request. Omitting it preserves the original `ResearchDecisionReport` path.
The new request returns one `WinnerQualificationReport`, also available through
`pack.winner_report`. It never runs missing probes, stress scenarios or search.

```python
from quantbt.diagnostics import WinnerQualificationRequest

request = WinnerQualificationRequest(
    include_account=True,        # original selected final account, no replay
    state_views=(),               # optional source-bound daily state families
    evidence=(),                  # optional exact-winner probe/stress refs
)
qualification = endpoint.research_report(
    access=diagnostic_access, witness=full_development_witness,
    role=full_development_witness.role,
    source_ref=original_completed_result_ref,
    qualification=request,
)
readable = qualification.to_markdown(private=True)
data = qualification.to_dict(private=True)
```

Use the **original full-development diagnostic** access/witness, not fabricated
historical selection rights. The result must contain the actual diagnostics-first
Mode 5 continuous-account metadata and selected dictionary. Old reset-environment
Mode 5 remains readable through the original default report, not this continuous
qualification option. Other modes fail explicitly. Existing
Mode 4 fold/meta reporting remains available through its unchanged path.

## Reading The Report

| Section | Recorded Data | Interpretation / Missingness |
|---|---|---|
| Original decision | Actual dict/effective ID, formula/coefficients/reference, eligible/excluded rows, incumbent guard, tie-break, attempts and actual sampler telemetry | Report does not rerank the winner |
| Whole and annual | Original utility, raw quality, returns, DD, daily loss ES, support and risk/quality gates | Annuals partition the same account; they are not independent market regimes |
| Calendar consistency | Supported/undefined counts, positive counts and observed ranges for each original measure | No new confidence interval or annual-positivity requirement |
| Activity and costs | Exact original equity/position/fee/funding/margin hashes, calendar, close-mark exposure and actual costs | Fills/campaigns need authoritative ledger/counters, never position transitions |
| States/regimes | Separate authorized daily label families, monetary attribution, observed activity and nonannualized conditional Sharpe | Labels require their own source/vintage/readiness; unknown state `-1` stays unknown; families overlap |
| Exact-winner checks | Explicit local/held role, expected/observed probes, requested/observed radius; scenario/execution ref and measurements for stress | Another diagnostic center cannot certify this winner; finite neighbors alone are not a basin certificate |
| Numerical explanation | Winner minus recorded score runner-up and same-pool eligible raw-Sharpe-best; original components and per-environment values | Same-pool raw-best is not an old legacy plateau run or a fresh baseline study |
| Registered baseline | Exact original baseline decision/pack, financial/measurement match, objective compatibility, budget/initialization and selected-path differences | One pair does not identify universal sampler superiority or a causal risk-allocation effect |
| Coverage | Status, support, unavailable inputs and limits per section | Missing evidence is not PASS, zero, no edge or an automatic rejection |

`U` remains the registered utility, with its own original metric definition and
risk coefficients. It is not an alias for return or Sharpe. Numeric descriptions
of return/exposure/risk trade-offs do not, by themselves, isolate their causes.

## States, Probes And Stress

`WinnerStateView(name, labels, witness, source_ref, label_names, purpose)` takes
an immutable `FrozenBuffer` containing one integer per observed UTC day.
Labels retain their own `AccessWitness`; `purpose` is `decision_vintage` or
`asof_calibration_descriptive`. This API does not fit a regime classifier or
infer transitions. State metrics are conditional descriptions, not independent
sample replications or hypothetical flat-reset accounts.

`WinnerEvidence.at(catalog.ref(...))` references a document with schema
`quantbt.mode5.winner_evidence.v1`, exact `winner_subject(decision)`, kind
`local_probes` or `execution_stress`, measurements, support, design and
limitations. Every measure includes metric, unit, value, sample_count and an
undefined reason. The design names the exact center candidate; local probes
retain selection-versus-held role and radius support. Stress names its actual
scenario and execution ref. Source bytes and current rights are checked again
when building/verifying the report. Referencing an old research receipt alone
does not automatically transform it into this current typed schema.

## Baseline And Saved Snapshots

Provide `WinnerBaseline(decision, pack, dossier, catalog, access, source_ref, ...)`
for both `request.current` and `request.baseline`. Packs are verified against
their actual sources. Alpha, market, economics, geometry, account clocks,
measurement and attribution windows must match. Different objective/reference
semantics are not subtracted as though scores were comparable. Optional
`baseline.result` supplies original marks for measured activity comparisons.
No account path is serialized into the report.

Private JSON reload requires an independently retained expected identity:

```python
from quantbt.diagnostics import WinnerQualificationReport

loaded = WinnerQualificationReport.from_json(
    saved_private_json, expected_identity=retained_identity,
)
```

This checks a retained snapshot, not renewed source access. `report.verify`
rebuilds from current original inputs and source catalogs; it does not inherit
an old approval or cached evidence. Public JSON/Markdown redact identifiers,
parameters and arbitrary private prose. `private=True` is an explicit disclosure
decision, not a flag to publish a strategy.

## Optional Cross-Mode Execution

The opt-in is **usable**, but not mandatory and not automatically recommended.
An archive review and a donor plan are different objects: score/path reuse may
be forbidden by reset/window differences while a coordinate can lawfully be
evaluated afresh under the current Mode 5 contract.

1. Assemble a complete, source-bound `ArchiveReview`. Keep source, candidate,
   outcome and revision dependency clocks, data roles and actual execution refs.
2. Derive the actual destination with `continuous_donor_target(dossier, binding,
   seed=...)`. Current continuous producers hash instrument/constraints, costs
   and funding together: this exact composite witness is required, not a
   hand-written assertion that symbol or fees are equivalent.
3. Explicitly choose and order `evidence_id -> catalog.ref(effective_params)`.
   `ArchiveDonorPlan.create` requires COMPLETE records, current selection rights,
   exact effective coordinates, compatible target/geometry and declared budget.
4. Call `donors.warm_start_records(...)`; put those exact records in the current
   binding. Rebuild its context/dossier and recipe **before** plan seal. Pass
   `donors=donors` to `CalibrationRecipe.continuous`. All starts consume the
   current budget. No prior score, model state or account path is imported.
5. Compile/prepare the existing `Mode5RunPack`. Current sources and donor binding
   are rechecked at execution preflight. The existing Mode 5 runtime evaluates
   current observations, selects and verifies replay/final accounting normally.
6. Compare to a declared unassisted baseline; inspect donor application, quality,
   risk/activity, support and cost. Keep the baseline if the evidence does not
   warrant a researcher change. Defaults are not promoted by this mechanism.

No learned/automatic donor ranking or 57-anchor/refill rule is activated.
Full-development archives cannot be backdated into a Mode 4 prefix by slicing
rows. Future/immature labels, unknown clocks, disallowed purposes, stale bytes,
different schema/economics/backend and duplicates fail before search.

See [the prior executable handoff](MODE5_EXECUTABLE_HANDOFF.md),
[the original decision contract](../mode5/DECISION_QUALIFICATION_V1.md), and
[the supplement plan](../../upgrade/implement.md#mode5-m5-11-15).
M5-12, remote qualification, merge/tag and publication remain separately approved.
See the [local qualification report](M5_11_15_IMPLEMENTATION_REPORT.md) for exact
tests, original-owner work counts, retained real readback, costs and limitations.

## Runnable Mechanics Example

[mode5_cross_mode_qualification.py](../../examples/mode5_cross_mode_qualification.py)
contains public synthetic data/strategy only. Dry run writes the exact protocol
and unmeasured diagnostic controls, not a fabricated complete archive:

```bash
python -m examples.mode5_cross_mode_qualification --workdir /tmp/cross-mode-dry
```

Explicit execution (new directory) runs two weekly Mode 4 studies with two
attempts each, retains the actual selected COMPLETE trials, then seals two
four-attempt Mode 5 plans before opening their outcomes:

```bash
python -m examples.mode5_cross_mode_qualification \
  --workdir /tmp/cross-mode-run --run --donor-fold 0
```

It uses one researcher-named donor, no automatic ranking, 12 total proposals
and at most 23 financial owner invocations. Both Mode 5 arms share the synthetic
account, source, metric, objective, selector, seed and attempt budget; only
initialization changes. All donor coordinates are rescored under current Mode 5
observations. The fixture's incomplete/partial calendar is mechanics support,
not evidence of economic superiority or independent validation. Current global
Mode 5 permits post-window coordinates under its sealed selection-policy clock;
that authority never changes a Mode 4 historical-prefix cutoff.

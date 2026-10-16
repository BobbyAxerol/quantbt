# Shared Alpha Diagnostics

## Scope

`quantbt.diagnostics` is an opt-in pre-search module, independent of WFO mode,
schedule, financial route and meta activation. It analyzes retained candidate
observations and existing source-bound analyses. It does not fetch data, call
a strategy, optimize, fit Ridge, choose an executed parameter dictionary or
change the account engine. This is feature-branch source functionality, not a
claim that an already published wheel contains it.

The owner-approved [scope](../../upgrade/implement.md#shared-alpha-diagnostics)
reuses Mode 5 geometry/statistics and QMS sampler/access contracts. Existing
`tools.mode5_geometry` and `tools.mode5_diagnostics` imports retain compatibility;
they reference the same packaged owners, not copied mathematical implementations.
The historical `mode5` names on source/access/metric owners do not impose Mode 5
on callers. This change does not expand the public meta capability matrix.

## Workflow

1. Define the effective parameter schema, alpha/market/economics/route identity,
   metric names/units/direction, generation method and activity definition.
2. Declare a permitted development manifest, exact cutoff and evidence readiness.
3. Use the existing financial endpoint/evaluator to produce observations. Missing
   values are null; failed/pruned observations are not sentinel bad performance.
4. Analyze existing observations once, reusing the shared geometry reducers.
5. Inspect coverage, branch-local associations, activity, optional local/regime/
   factor evidence and sampler compatibility. Supply a traceable recipe shortlist
   with rationale, hypothesis/comparison status and explicitly missing evidence.
6. Record a researcher choice with a reason, then separately freeze/apply the
   corresponding optimization config. A report choice does not start a run.

Run the [synthetic example](../../examples/shared_alpha_diagnostics.py):

```bash
PYTHONPATH=src .venv/bin/python -m examples.shared_alpha_diagnostics
```

```python
from quantbt import AlphaDiagnostics, DiagnosticContext, DiagnosticObservation
from quantbt.diagnostics import AccessPolicy, AccessWitness, DiagnosticNeeds, compile_plan

# Context, access and rows come from the declared pre-search evidence contract.
diagnostics = AlphaDiagnostics(param_ranges, context=context, access=access)
report = diagnostics.analyze(rows, advice=recipe_options)
payload = report.to_dict()
text = report.to_markdown()

# Optional label; this only declares retention, not engine or meta support.
plan = compile_plan(DiagnosticNeeds(objective=("return",), audit=("fill_audit",)),
    route_id="intrabar", backend="rust", optimization_mode="mode_4_is_only_robust",
    optimization_schedule="per_fold_causal")
```

The same API works before any WFO mode is selected. It also accepts caller
labels for Modes 1-5 or a future method without altering their methodology.
Mode 4 evidence must be prefix-authorized at each decision; Mode 5 may analyze
its explicitly declared full development scope. Full-development reports cannot
be used as inputs to earlier chronological decisions.

## Output And Interpretation

| Section | Returned evidence | What it does not imply |
|---|---|---|
| Geometry | Shared schema ID, variable/conditional/source-inactive axes, observed values and constraints | Effective dimension theorem or permission to remove a parameter |
| Coverage | All dispositions, effective duplicates, defined/undefined primary metrics | Complete exploration of the parameter domain |
| Activity | Producer-defined count, missing and zero counts, observed range | Fills equal closed trades, or low activity automatically invalid |
| Associations | Existing branch-local multi-metric Spearman and finite-panel bootstrap | Causal factor effects, neutral design from adaptive TPE or global Sobol indices |
| Optional analyses | Hash-bound fragility/environment/factor results from the existing catalog | Recomputed or independently certified source methodology |
| Compatibility | Existing factory geometry preflight for four sampler recipes | Dependency availability, fastest sampler or best economic recipe |
| Advice | Explicit source refs, rationale, basis, missing proof and researcher choice | Automatic routing, execution or economic superiority |

Finite-panel associations require an explicitly outcome-blind roster. Adaptive
or reviewed search rosters keep coverage/activity but return association status
`NOT_ESTIMATED_ADAPTIVE_OR_REVIEWED_ROSTER`. A caller's design declaration is
not independent design certification. Categorical values are branches, never
ordinal numbers; conditional parent order and activity masks remain intact.
Repeated effective candidates stay in the coverage ledger but do not produce
association intervals by masquerading as distinct supported points.
Structured sensitivity/probes remain available under
`quantbt.diagnostics.geometry` through the unchanged registered design contracts.

Optional `DiagnosticAnalysis` entries require the existing `EvidenceCatalog`.
The selected source object must bind `context_id` in its hash-verified bytes.
Current policy rechecks role, manifest and readiness even if the catalog was
created under a later policy. Source files are reverified; no absent local/
regime/factor analysis is invented. A filename, source ref or report hash alone
is not permission or scientific certification.

`DiagnosticAdvice` is researcher-supplied, not an alpha-name classifier. Its
references must exist; `OBSERVED_COMPARISON` additionally needs a verified source
analysis. This checks provenance, not the scientific adequacy of that comparison.
No combined score, automatic ranking or universal kernel recommendation is added.
`report.with_choice(access=..., sampler_id=..., selector_id=..., reason=...)`
records only a choice from the explicit shortlist; incompatible samplers fail.
Unknown/conditional/mixed-space overrides continue through the existing
[sampler-space helper](../meta_selection/SAMPLER_SPACE_HELPER.md), not hidden
category-to-integer conversion in diagnostics.

## Ownership And Safety

Frozen contexts/observations and canonical `Record` reports survive deepcopy/
pickle without writable-buffer/hash drift. Dictionary exports are fresh copies.
Context/schema, every observation's metrics/content, witnesses and cutoff are
bound into the report identity. Reports are metadata, not authenticated proof
against a malicious producer. Reuse the existing `DiagnosticReuse` and bounded
prepared cache when retaining financial evidence; there is no new global cache.
`report.authorize(new_policy)` rechecks retained witnesses and requires exact
policy identity; changed rights/cutoffs require reassembly, not cache relabeling.

Observation/report budgets fail explicitly; rows or metrics are never dropped
to fit. Numeric bootstrap uses its own generator and does not consume global
NumPy/Python or Optuna RNG. Report assembly is cold NumPy/SciPy/Python, reusing
existing reducers; no extra Rust bridge, native build, model or dependency is
introduced. It is not advertised as an all-Rust runtime.

Metrics/accounting, existing selectors/samplers/defaults, history permissions
and all Ridge/loss/hyperparameter versions remain unchanged. Diagnostics does
not require meta to be enabled. Private strategy/data/ranges remain caller-owned;
reports may contain sensitive observations/analysis, so only synthetic fixtures
and sanitized evidence should be published.

Installed-wheel/source-final packaging and M5-11.7 broader Mode 4/5 reporting
remain separate gates. See the [local implementation report](SHARED_ALPHA_DIAGNOSTICS_REPORT.md).

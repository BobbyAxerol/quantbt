# Pre-Search Researcher Reports

## Contract

This opt-in extension of `quantbt.diagnostics` describes retained search space,
participation, environment contributions and recipe suitability. It is common
to any declared strategy/route/mode; it does not broaden WFO/meta financial
capabilities or select a deployed dictionary. See
[M5-11.7.1](../../upgrade/implement.md#mode5-m5-11-7-1) and
[guide 16.2](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md#mlr-r2).

`AlphaDiagnostics.analyze(rows)` keeps the existing version-1 JSON identity and
Markdown behavior. Supply `research=DiagnosticResearch(...)` to add the versioned
`researcher_diagnostics` view. There is no new account engine, optimizer,
estimator, result cache or automatic recipe router.

```python
from quantbt.diagnostics import DiagnosticResearch, DiagnosticTrial

# diagnostics, rows, witness and optional catalog come from the existing
# declared schema, original financial observations and access policy.
request = DiagnosticResearch(
    context_id=diagnostics.context.identity,
    witness=witness,
    source_ref="registered-study-ledger",
    view="prefix",
    trials=tuple(DiagnosticTrial(
        trial_id=str(i), ordinal=i, status="COMPLETE",
        evaluation_id=row.evaluation_id,
    ) for i, row in enumerate(rows)),
    requested_trials=128,
)
report = diagnostics.analyze(rows, research=request)
data = report.to_dict()["researcher_diagnostics"]
text = report.to_markdown()
public_json = report.to_json(public=True)
```

Only create COMPLETE attempt records when they really represent complete
attempts. Imported candidate rosters without the actual attempt ledger must
leave `trials=()`: attempted/failed/pruned counts then remain NOT_SUPPLIED, not
an inferred 128/128 success. PRUNED/FAILED/INFEASIBLE/CANCELLED attempts retain
their reason and cannot carry sentinel financial scores. `ordinal` is ordered
and contiguous; `elapsed_seconds=None` is unavailable time, not zero cost.

The [synthetic example](../../examples/shared_presearch_researcher.py) includes
an original-mark account fixture and source-provided labels, with zero finance:

```bash
PYTHONPATH=src:. .venv/bin/python -m examples.shared_presearch_researcher
```

## Output

| Section | What Is Measured Or Preserved |
|---|---|
| Provenance | Context/schema/route/economics, metric names and units, exact witnesses, source references, cutoff and view rights |
| Search | Actual attempts/dispositions/reasons, missing durations, observed effective points/duplicates, ordered budget-response curve |
| Parameter support | Conditional/category branches, inactive/fixed/cast policies, observed values, boundary hits and coupled constraints |
| Accounts | Actual marked PnL, fees/funding when supplied, close-mark exposure, observed/zero/undefined days, source-labelled monetary contributions |
| Analyses | Existing sensitivity/local probe, native selection/components/fallback, sampler-comparison and actual execution-stress fields |
| Six matrices | Schema/point support or exact original Dossier/Matrix reconciliation; explicit missing status where no such matrix exists |
| Findings/cards | Value/unit/support source, interpretation, competing explanation, missing proof, bounded next action and non-executing override |

Observed coordinate variation is not an intrinsic-dimension theorem. An adaptive
TPE roster still cannot generate neutral-design sensitivity intervals or basin
volume. Fixed/conditional/constraint support is not permission to remove axes.
Structured/local reducers retain their original registered design requirements.

The four sampler cards use the existing factory's geometry policy. They
distinguish compatibility from response evidence and scientific superiority;
default CMA-ES/Sobol restrictions are not bypassed by ordinal category codes.
Joint-search compatibility alone does not establish an interaction or economic
benefit. No selector is invented when its implementation/probes/metric contract
is absent. Explicit `DiagnosticAdvice` remains the researcher shortlist, and
`with_choice(...)` records a reason without applying configuration.

Bull concentration can arise from the data, directional exposure, objective,
sampler or selector. The report shows the actual available contributions and
alternative explanations. It cannot isolate a sampler's causal effect without
a matched study. All recipe options are advisory, not alpha-name heuristics.

## Account Views

`DiagnosticAccount` binds an immutable `ExecutionEvidence` to the exact
`digest(asdict(observation))`, initial equity and monetary unit. Market marks,
positions and optional costs must come from the original result. The existing
Mode 5 monetary partition/calendar attribution functions are the canonical
owners under `quantbt.diagnostics.environments`; legacy tool imports are aliases.
Their mathematical bodies are unchanged.

Daily state labels require their own witness, source reference and declared
purpose. `prefix` rejects full-development fitted labels. `full_development`
and `retrospective` are NOT_BACKDATABLE; neither can supply earlier decisions.
No regime model or threshold fit runs in this report.

Attribution uses actual chronological marks: positions crossing a state boundary
are not closed/reopened, and daily PnL includes actual existing costs/MTM.
Positive-day PnL and negative-day loss have separately named masses. State shares
divide by positive/loss/absolute daily money, never near-zero signed total profit.
A zero denominator produces null, not a favorable or huge concentration number.
State families remain dependent views; no new uncertainty sample count is made.

Close-mark exposure is not fills, entry opportunities, rejected orders or closed
actions. Multi-symbol long/short mark counts can overlap. Intrabar trading can
occur on a close-flat day. These limits are explicit. Sparse activity is not
automatically defensive degeneracy, and no new activity gate is applied.
Undefined returns after a nonpositive base remain counted separately; zero
returns are counted only on valid return days. Reset episodes are never relabelled
as one carried account or used to produce a spliced continuous Sharpe.

## Existing Dossiers

Pass an existing typed `Dossier` in `DiagnosticResearch.dossier` and its original
`EvidenceCatalog` to `analyze`. Current access rechecks every source even if the
catalog was created with later rights. Dossier/Matrix owners verify rosters,
values and original source manifest. The shared view retains matrix IDs/counts,
not another copy of all matrix values; the original dossier remains authoritative.

Some older dossiers use composite dependency IDs instead of a direct geometry
hash. They require `dossier_geometry_ref=Record.of(catalog.ref(...))` pointing
to the original full geometry metadata. The metadata must exactly equal the
current geometry, and alpha/data/economics dependencies must still match. No
old schema ID or receipt is rewritten to make the join succeed. The source
catalog's original policy identity remains unchanged while current access is
checked separately.

Optional producer analyses remain hash/context-bound through `DiagnosticAnalysis`
and the existing catalog. Wrong geometry, cutoff, candidate IDs or local center
identity/role fail. Missing components are named; raw Sharpe does not become
an annual floor, fragility measurement or execution stress. Source reconciliation
is not a new scientific certificate for the producer's method.

## Safety And Limits

Report Records and byte-backed evidence remain immutable through deepcopy,
pickle and JSON round trips. Full account buffers are content-hashed, not placed
inside JSON or copied into each finding. Observation/attempt/account budgets fail
explicitly without truncation. Default limits are 10,000 observations/attempts,
4 MiB report JSON and 32 MiB retained account inputs; caller overrides are explicit.

Default exports are private. `to_dict/to_json/to_markdown(public=True)` export
only allowlisted counts/fixed states, not arbitrary prose, parameters, alpha/data
identities, state names or source paths. Context/metric statements remain producer
claims, not authentication against a malicious input producer.

There are no hidden strategy, financial, optimizer or model-fit calls, no global
NumPy/Python/Optuna RNG consumption and no hot-path/accounting changes. Existing
outcome-blind association analysis retains its isolated bootstrap generator and
seed contract; this extension adds no sampling or inference. Source/local
qualification is not a wheel/public release proof. Mode 4/5 fold/meta-statistic
views and final public integration remain M5-11.7.2 and M5-11.7.3.

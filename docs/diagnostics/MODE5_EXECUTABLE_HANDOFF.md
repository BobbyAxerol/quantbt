# Mode 5 Executable Handoff

Availability: opt-in source-branch API. Local source qualification is not an
installed-wheel, remote-platform or published-package certificate; M5-12 and
release retain their separate approval gates.

This is a synthetic public API mechanics example, not an economic study,
evidence-based recipe recommendation, validation result or deployment approval.
The implementation is [mode5_diagnostic_handoff.py](../../examples/mode5_diagnostic_handoff.py).
It imports no test modules and needs no archived study or 57-fold research run.

## Entry Points

The later [winner qualification and complete-archive donor supplement](MODE5_WINNER_QUALIFICATION.md)
adds an explicit optional request on the same result/endpoint interface and
verified coordinate-only warm starts. The MISSING archive example below remains
an absence control; it is not retroactively relabelled as the positive proof.

The shared `calibration_handoff_capabilities()` describes executable annual
continuous attribution versus descriptive-only temporal views. It adds no
financial route or automatic recipe registry. For a completed run,
`pack.to_json(report=report, private=True)` and
`pack.to_markdown(report=report, private=True)` provide the five linked views.
Default exports redact private fields. `pack.export` writes executable recipe
metadata, whereas `pack.to_json` renders the linked report, not a reloadable
run-pack configuration.

```python
build_inputs(workdir, *, optional_archive=False, trials=4)
run_demo(workdir, *, optional_archive=False)
```

`workdir` must be a new disposable directory. `build_inputs` returns a dictionary
containing the original `data`, `strategy`, `param_ranges`, `dossier`, `catalog`,
unchosen `worksheet`, selection `access`, and `account_kwargs`. Additional keys
are `archive`, `archive_access` and `workdir`.

Importing the example executes no strategy, optimizer, financial account or
diagnostic battery. `build_inputs` constructs configurations, hashes original
inputs, writes `synthetic-evidence.json`, and verifies the catalog, six matrices
and dossier. It performs **zero financial executions**, creates no journal seal,
and makes no worksheet choice. It permits one to four formal attempts, not an
unbounded study. Literal fixture scalars are marked `SYNTHETIC_CONTROL`, with
dimensionless, non-return units. They are not utility observations or scores.
All five unmeasured diagnostic axes have null values and explicit reasons.

`run_demo` builds fresh inputs with four attempts, explicitly calls
`worksheet.choose`, then calls `Mode5RunPack.compile`, private `export`, identity-
checked `read`, `prepare`, `endpoint.backtest`, and `pack.reconcile`, in that order.
It returns a dictionary with `endpoint`, `result`, `report`, `pack` and `inputs`.
The original unchosen worksheet remains in `inputs`; the chosen revision is
retained inside the pack. No automatic recipe router is involved.

There are at most four formal attempts, one selected replay and one final
account execution per demo: at most six accounts, zero local probes and zero
diagnostic accounts. There are no retries, hidden warm starts, incumbent queries
or extra search seeds. A `Mode5NoSelectionError` is retained as `result` and
reconciled without another search; other errors propagate. Two successful demo
runs, with and without the archive control, therefore use at most twelve
financial executions. Execution verification belongs to the parent lane.

## CLI

From the repository root, using the environment where `quantbt` is installed:

```bash
python3 examples/mode5_diagnostic_handoff.py --workdir /tmp/m5-handoff-inspect
python3 examples/mode5_diagnostic_handoff.py --workdir /tmp/m5-handoff-inspect-archive --optional-archive --private
```

These are dry runs that write fixture evidence and print the worksheet. They do
not call `backtest`. `--private` reveals the synthetic recipe fields, reasons and
archive disposition; the default display is redacted. Use a different new
directory for each invocation. Only an explicit `--run` performs backtests:

```bash
python3 examples/mode5_diagnostic_handoff.py --workdir /tmp/m5-handoff-run --run
python3 examples/mode5_diagnostic_handoff.py --workdir /tmp/m5-handoff-run-archive --optional-archive --run
```

`--run` also explicitly opts into writing the private pack. There is no implicit
execution on import, dry run, worksheet rendering or archive review.

## Frozen Preferences

The synthetic market contains 768 hourly UTC bars from 2020-12-16 through
2021-01-16. The original legacy `pct_equity` account uses capital 20,000, leverage
1, allocation 0.5, configured `fee=0.0005`, slippage 0.0001, funding disabled and
symbol `DEMO`. These are original endpoint settings, not a reinterpretation of
the engine's fee convention. `producer_records` uses the resolved original
`pct_equity` scoring config and exact strategy. `calibration_context` binds the
same data, strategy, account economics and parameter ranges later supplied to
`prepare` and `backtest`.

`continuous_calibration_binding` registers one continuous account with carried
positions, no annual resets and no preload. Calendar-year IDs `2020` and `2021`
each describe 16 observed complete UTC days. These partial years are allowed
explicitly for this mechanics control: minimum two daily returns per view,
minimum zero closed engine records, maximum drawdown 1 and minimum utility -10,
with a greater-or-equal quality comparison. These permissive gates are not
investability criteria. No absent full-year data is filled, extrapolated or
treated as independent support. Missing or invalid metrics retain their original
status; they are not replaced by zero.

The utility channel is `ECONOMIC_UTILITY_V1` / `mode5.utility.net_v1`, in decimal
returns. Utility is net account return minus drawdown minus daily-loss expected
shortfall at confidence 0.95. Both penalty weights are explicitly 1; costs are
already in net return. The declared annualization factor 365 applies to daily
statistics, not extrapolation of the partial-year net return into a yearly gain.
Both reference utilities are frozen at zero with equal environment weights.

`CalibrationRecipe.continuous` mechanically resolves identifiers without choosing
numeric preferences. This example explicitly chooses `full_dro_cvar` with
`environment_floor_mean_v1` and mean coefficient 0.5: environment floor plus
half the weighted mean, with no extra activity penalty. This is not a claim of
CVaR estimation across independent years. The sampler is `tpe_legacy`, seed 731,
two startup trials, sequential exact schedule and batch size 1. The domain is
`period=(6, 24, 1)`. Failure policy is `raise`; no early stopping, warm starts,
incumbent, Pareto preferences or local offsets are registered. Independent
validation is explicitly not performed, and automatic deployment is disabled.

## Archive And Choices

The default path has `archive=None` and requires no archive history. An explicit
researcher choice can still compile and preflight; absence of an archive does
not select a recipe or start an optimizer.

The optional path adds an `ArchiveEvidence` with `status="MISSING"` and the known
reason that no original account execution or measurements were retained. Its
candidate and execution identifiers are absence-control labels, not real runs.
Its dependency DAG and availability clocks are synthetic contract fixtures, not
historical receipts or a backdated research history. It retains no account
marks, scores, candidate coordinates or derived readbacks.

The exact `asdict(evidence)` is stored at `/archive` in the **same source catalog
and dossier** as the diagnostic controls. `ArchiveReview.assess` receives a tuple
of `(evidence, intended_reuse, catalog.ref(...))`, the digest of the dossier
context, current selection access and that catalog. Source and DAG witnesses
agree with the binding. The resulting disposition is
`TARGETED_EXECUTION_REQUIRED`, with the original missing-measurement reason.
This is an eligibility statement, not execution authority: the example neither
imports archive scores into TPE nor executes any archive follow-up request.

Quarterly and regime options are explicit `RESEARCH_ONLY` cards with missing
contracts and `NOT_EXECUTABLE` readiness. Current continuous selector windows
support calendar-year attribution only. Quarter and regime views can be
descriptive where separately supported; neither view authorizes a new public
ranking binding or supplies independent OOS evidence. This example does not fit
a regime model or produce quarterly research measurements.

Manual overrides use immutable `worksheet.choose(option_id, researcher=...,
reason=...)` revisions that preserve the parent and previous choice. A choice
does not mutate evidence, apply configuration or run finance. Choosing a
research-only card records intent but compilation fails `NOT_EXECUTABLE`.
Changing numeric preferences, data, source, geometry, sampler or account settings
requires the corresponding revised binding/context, dossier and worksheet, then
an explicit new choice and seal. Do not edit compiled pack JSON to override it.
The compiled plan reason binds the worksheet identity, researcher and choice
reason. Choosing the same numeric recipe again cannot inherit an old choice's
plan seal. Optional shared-diagnostic attachments require their exact original
report reference in the verified catalog and recheck dependencies for selection.
Pack-created calibrations repeat these cold checks at execution-time preflight;
the endpoint receiving a second `data` argument cannot bypass the pack's
clock/attribute/source restrictions after `prepare` has returned.

## Disclosure And Reuse

Public worksheet and run-report views redact private identifiers, parameter
dictionaries, recipe rationale and source details. Private views require
`private=True` or CLI `--private`; public views are not reloadable private packs.
Archive disclosure uses `public=True`, a different keyword from worksheet and
run-report disclosure. Neither redaction nor a content hash establishes economic
truth or renewed evidence permission.

`pack.export(..., private=True)` creates `run-pack/run_pack.json`, `manifest.json`
and a fixed `run_mode5.py` caller stub. The pack contains private recipe,
worksheet and binding metadata. It does **not** export a Dossier object, evidence
files, source paths, market data arrays, strategy/callback implementations or an
executable alpha. Treat the files as private configuration even though evidence
paths and financial arrays are excluded. `journal/` records the new seals and
actual search lifecycle when the explicit run is prepared and started.

The caller supplies the original verified dossier, catalog, access, strategy,
market, ranges, account settings and a fresh `GovernanceLog`. Retain the expected
pack identity independently; `read` compares against it. `prepare` rechecks
sources, rights, context and actual producer configuration before sealing or
returning an endpoint. Reading a pack is not permission to execute it, and an
already-started journal cannot be silently resumed or resealed.

This is not arbitrary-path portability. The original catalog and dossier bind
source paths and access witnesses. Relocating or revising that catalog requires
a newly verified catalog, dossier, worksheet/pack and seal, even when source
bytes are unchanged. Changed provider or strategy code also requires fresh
registration. A moved pack alone still needs all original verified external
objects and current authority. Symlinked pack paths are rejected.

Reconciliation reads original decision metadata and reduces retained final
marks without another financial replay. `RECONCILED_RETAINED_RUN` means bounded
consistency of the actual retained run, not independent accounting certification,
out-of-sample performance, or economic promotion. Inspect `NO_SELECTION`,
`MISMATCH` and `FAILED_UNVERIFIED` without hiding missing evidence. Static utility
or regret is not prefix-forward decay. Every path remains non-promoting.
Matching includes the sealed scored calendar and stream alignment, available
support/terminal fields, resolved sampler settings and initialization, complete
reference, selection-plan identity, eligibility policy and incumbent margin.
This is not independent validation of every accepted-fill/trade-ledger field.
`prepare` requires an explicitly timezone-aware market index, not an inferred
naive-to-UTC clock. It currently rejects nonempty `DataFrame.attrs`: the existing
market context hash does not seal those attributes, which can carry instrument
constraints. A separately specified manifest extension is required before this
new helper can certify them. Do not strip financial attributes to bypass this
gate. Original backtest/calibration entry points are unchanged; this is a
fail-closed limit of the optional run-pack helper, not a claim that all QuantBT
data must lack attributes. Synthetic missing-archive examples do not certify an
archive-seeded optimizer or any benefit from that policy.

## Current API Constraints

`CalibrationPlan.search` currently requires a `CONSIDER_FINITE_PANEL` assessment,
including for a synthetic handoff. The example labels that entry explicitly as
`SYNTHETIC_CONTROL` contract permission, records zero measured decisions and
leaves every diagnostic axis null. Do not reinterpret it as measured eligibility
or use this control dossier for real research admission.

Binding the exact original financial configuration currently uses the internal
`_walkforward_scoring_config` resolver, as do the existing public examples. No
replacement financial engine or source qualification is implemented here.

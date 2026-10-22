# M5-12 Bounded Report Reproduction

This sidecar implements a small reproducibility harness and an operations-test
inventory. It is **not** the terminal M5-12 receipt, an installed artifact proof,
a new economic experiment, or a rebuild of all twelve phase reports. Main owns
serial test execution, exact-current-source artifact qualification and cleanup.
Implementation is provided here; no test/build/install execution is claimed by
this document. Current package provenance uses the main verifier's
`qualified_source_count=466`, not a source count inferred by this sidecar.

Authoritative requirements: [M512.03/M512.04](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-12--qualification-docs-reproducibility-và-handoff),
[7.8 reporting and 7.9 product gates](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#chapter-7),
[8.2 completion](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#chapter-8),
[Appendix D](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#appendix-d)
and [Appendix E](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#appendix-e).
The [unified plan](../../upgrade/implement.md#mode5-m5-12) remains the phase owner.

## Question And Scope

Can a new process reproduce exact report values, identities, JSON and Markdown
from retained synthetic inputs, using the same report owners and no notebook
state, financial execution, optimizer calls or model fitting?

The answer must come from execution of the new tests/CLI, not from this text.
The only supported evidence class is `SYNTHETIC_CONTROL` with explicitly
reviewed public-safe inputs and synthetic diagnostic rights. Public-safe is a
caller-reviewed declaration, **not** an automatic privacy classifier or proof
against a malicious evidence producer. Never pass private alpha dictionaries,
market snapshots or original private research reports to this sample exporter.
Synthetic fixtures may contain adversarial privacy-marker strings; those are
not private strategies. Nothing is fetched, compiled, installed or simulated.

## Existing Owners Used

| Output | Retained Input | Existing Owner And Actual Check |
|---|---|---|
| `diagnostics.json` / `.md` | Ordered portable ranges, diagnostic context, observations, witnesses and advice | `AlphaDiagnostics.analyze` reconstructs coverage, effective geometry support, activity, availability and explanation. Reviewed-roster association status stays unestimated; no new bootstrap |
| `mode4.json` / `.md` | Complete `ResearchDecisionReport` snapshot with original fold observations, policies, calendar and masks | Existing `from_json` validation recomputes effects and descriptive reducers, checks observation identities and proposed/applied semantics, and reauthorizes current access |
| `mode5.json` / `.md` | Original `DecisionReport` snapshot | Existing reader reconciles trials, sampler telemetry, selected dictionary/audit, formula, components and raw-versus-objective semantics. It never reruns selection or search |
| `winner.json` / `.md` | Exact decision-only `WinnerQualificationReport` and the same Mode 5 decision | Existing winner reader and `verify` rebuild explanation, annual summary and coverage against the original decision. External account/catalog/stress attachments are deliberately unsupported in this bounded sample |

No new reducer, estimator, engine, sampler, accounting model or execution
endpoint is introduced. At least one retained observation and at most 128
diagnostic rows, 16 axes and 16 fold slots are admitted. Missing regime,
continuous account, probe, stress and registered-baseline evidence remains
`NOT_SUPPLIED`; annual observations do not become independent regime evidence.

The synthetic Mode 4 control intentionally has positive decay improvement R
and negative forward-Q on two folds: means approximately `R=0.815`, `Q=-0.185`,
with IS contribution `1.0`. This exercises the meaningful distinction rather
than equating decay reduction with forward improvement. These are constructed
records with saved illustrative predictions, **not** an actual Ridge fit or
new empirical performance. The Mode 5 winner control exercises floor/mean
objective components and a `0.35` runner-up objective difference, with a minimum
retained annual utility of `0.05`; utility keeps its declared channel and is
not renamed raw return or Sharpe.

## Sealing And Fresh-Process Command

The main driver provides four already-built synthetic report objects and their
original diagnostic input rows to
[`seal_synthetic`](../../tools/m5_12_reproduction.py). It supplies literal
expected values/units/support through `expected_values`, and explicit
diagnostic, Mode 4 and winner `AccessPolicy` objects. The existing examples
[`shared_presearch_researcher`](../../examples/shared_presearch_researcher.py)
and [`shared_decision_reporting`](../../examples/shared_decision_reporting.py),
plus the retained synthetic winner fixtures used by the
[sidecar tests](../../tests/test_m5_12_reproduction.py), supply the sample.
The test fixture's finance-free preparation is an example of this call:

```python
pin = seal_synthetic(
    new_input_directory,
    diagnostic_inputs=retained_diagnostic_input,
    reports={"diagnostics": diagnostic, "mode4": fold_report,
             "mode5": decision, "winner": winner},
    access={"diagnostics": diagnostic_access, "mode4": fold_access,
            "winner": winner_access},
    expected_values=registered_value_assertions,
)
# Retain pin["sha256"] outside the bundle before starting the fresh process.
```

The input directory and output directory must be new; their parents must
already exist. The main driver records the command, exit status, stdout/stderr
and source/artifact identity in its own append-only attempt lane. Example:

```bash
"$CONSUMER/bin/python" -I -B /absolute/path/tools/m5_12_reproduction.py \
  --manifest "$INPUT/manifest.json" \
  --expected-sha256 "$EXTERNALLY_RETAINED_SHA256" \
  --output "$NEW_OUTPUT_DIRECTORY"
```

For this phase, main's private receipt root is
`upgrade/private/mode5_upgrade_v1/m5-12/attempt-01`. Use distinct children for
each consumer/attempt; do not overwrite earlier failed or partial output. No
default command scans or exports private historical evidence. The tool itself
adds no import path or environment override. Main's installed qualification
must verify import origins and artifact hashes independently. The source-only
subprocess test uses a visible `src` bootstrap solely to exercise fresh-process
behavior; it is explicitly **not** an installed package test.

The terminal `reproduction.json` must have `fresh_process=true`, a different PID
from the producer, expected report IDs, eight exact output file hashes, and the
checked numeric/unit/support assertions. A direct in-process unit call can
verify the logic but records `fresh_process=false`; it cannot satisfy M5T-113.
The receipt always leaves `installed_artifact_qualified=false`,
`independent_validation=false` and `publish_or_live_authorized=false`. Main may
link it to an independently verified installed-artifact receipt, not rewrite it.

## Integrity And Negative Controls

The manifest's externally retained SHA pins the complete four-entry roster,
current renderer/reducer owner hashes, access policies, expected report IDs,
input hashes/sizes, expected full-precision values and expected MD/JSON hashes.
All inputs are verified before any output directory is created; source/input
hashes are checked again before the terminal receipt is written. JSON duplicate
keys and nonfinite constants, symlinks, path escape, missing reports and silent
truncation are rejected. Only fixed relative input filenames are read.

The tests register actual negative controls, not JSON-parse checks alone:

- A valid rewritten JSON file with a stale hash must fail.
- Rehashed diagnostic activity changes must not match the original report ID.
- Mutating a Mode 4 forward observation with stale effects/source identity,
  or merely changing its summary, must fail existing semantic reducers.
- Substituting raw Sharpe for the Mode 5 selector objective must fail.
- A winner snapshot for another candidate must not certify the retained choice.
- Wrong expected values/units/support and Markdown hashes must fail even when
  JSON is well formed and its input hash has been updated.
- Narrowed current cutoffs must be rechecked; readable data is not permission.
- Changed owner bytes, inflated all-twelve scope, non-synthetic input, duplicate
  keys, nonfinite values and exceeded bounds must not emit a terminal receipt.
- Interrupted output writes retain partial files without a completion marker;
  repeat invocations never overwrite that lane. Mutation during rendering also
  prevents a terminal receipt. RNG state and protected input bytes stay intact.

Public finance/WFO entry points, Optuna study creation/asks and Ridge fit have
process-local tripwires. They are an accidental-call detector, not a security
sandbox against arbitrary malicious Python. The tool imports no alpha module.
Source pins cover named report owners; they do **not** replace main's exact
466-file source guard, whole-artifact member inventory or dependency qualification.
The expected output hash is a replay reference, not an independent scientific
oracle. Tests add simple externally understood arithmetic/identity controls.

## Operations Inventory For Main

The machine-readable `OPERATIONS_TARGETS` constant lists exact existing pytest
nodes. The new unit test checks that the targets exist by AST, not by importing
or running their runtime owners. Main records actual execution separately.

| Area | Existing Targets / Coverage | Boundary |
|---|---|---|
| Cancel/crash/slow audit sink | `test_diagnostic_audit.py`: durable flush, slow-sink backpressure, canceled/crashed artifacts, failed fsync. `test_public_boundaries.py`: failed batch retains unevaluated asks and releases context | Partial/canceled work cannot become completed; no timeout is relabelled an economic score |
| Stale handles/owned worker death | `test_phase71_runtime_productization.py`; prepared-cache generation/pin control; `test_phase76_reactive_wfo.py`; `test_c02_transport.py` stale/corrupt/deadline replies | Reset/recovery preserves owner generations and kills only owned work; native tests need the current qualified extension |
| Narrow rights/reload | Diagnostic planner earlier-cutoff denial, archive review narrower-access reload, donor prefix/cutoff denial | Same hash or old catalog policy cannot renew data access or backdate full-development information |
| Recipe failure/missing prerequisites | Required recipe fields, missing governance seal, plus main's installed import/resource/pair controls | No silent fallback or fake ready state; this sidecar never deletes packages to simulate a missing environment |
| Exact continuation | C04 fresh-process restore without an evaluator, terminal states/batch ordering, seed-only rejection; conditional-policy fresh-process continuation | Exact sampler continuation is contract-specific. It is not automatic full-WFO/account/order/model recovery |

These nodes are candidate targets, **not** PASS receipts. Main should select
affected existing shards once, reuse current valid execution receipts where
identities still match, and avoid running financial/optimizer tests twice just
because this inventory references them. Parameterized nodes require all
registered variants, not one favorable case. The operations inventory does not
claim a newly executed endpoint/backend/sampler Cartesian product.

## History And All-Twelve Boundary

The [accepted parent research ledger](M5_11_RESEARCH_COVERAGE_DISPOSITION.md)
retains the real seven-alpha, diagnostic/search/winner and cross-mode scopes.
Its completed studies and positive, adverse and inconclusive findings remain
under their original source/data/economic contracts. HMA's unqualified formal
cohort, finite-probe radius limits, reviewed-data roles and deferred broad
whole-procedure claims are not repaired or promoted by this synthetic sample.
Earlier financial corrections must not be back-applied to old economics while
pretending the old receipts described the new source.

This sidecar verifies four representative report views and their table data;
it does **not** rebuild every historical M5-01..12 Markdown/JSON file, chart
image, private campaign/trace view, original EvidenceCatalog or 120-requirement
mapping. It does not certify independent OOS or a universal best recipe.
`twelve_phase_reports_rebuilt=false` and `historical_research_recomputed=false`
are mandatory schema fields. Full historical report reconstruction/disposition,
all-120 traceability and Appendix D handoff remain main's explicit M512.03/06
work, under the actual accepted coverage. Missing historical inputs must be
listed with an honest disposition, not replaced with these synthetic reports.

## Execution, Resource And Handoff

Main's next source check is the following, after registering its test resource
budget and exact scratch paths:

```bash
.venv/bin/python -B -m pytest -q tests/test_m5_12_reproduction.py
```

This command is provided, **not executed in the sidecar implementation task**.
Input cap is 2 MiB/file, 8 MiB/bundle; total rendered MD/JSON cap is 8 MiB. Main
must budget the interpreter/import peak and the test's one fresh child, in
addition to fixture files; this is not permission to launch parallel consumers.
Keep numeric pools single-threaded as in the main qualification protocol.
No large historical archive, finance replay, optimizer study, build or install
is necessary. Sidecar has no cleanup command. Main preserves receipts, logs,
exact input/output pins and artifacts, reviews inactive disposable fixture
scratch, then records cleanup under the [runbook](../BUILD_TEST_CLEANUP.md).

Handoff must attach actual test/CLI exit codes and hashes, fresh process/import
provenance, all reported coverage exclusions and the independent artifact/source
receipt. Reproduction failure blocks this sample's claim; it does not justify
changing historical evidence, tolerances, scientific methodology or financial
code. Rollback is to omit this optional qualification tool; no public endpoint,
raw accounting or sampler behavior changes.

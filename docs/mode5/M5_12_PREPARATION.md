# M5-12 Package Preparation

Date: 2026-10-22 UTC. This retains the technical preflight and links the
owner-approved local qualification results; it is not a blanket M5-12 PASS receipt
or publication authorization. Candidate pair:
**quantbt-engine 1.1.2 / quantbt-native 0.4.3**, unchanged by this preparation.
No live PyPI index query is represented here.

The [unified phase](../../upgrade/implement.md#mode5-m5-12) is now
**TECHNICALLY_VALID** within the registered local scope: local final-artifact
gates are recorded and the owner accepts all four reconciled operational
exceptions, preserving failed receipts and waiving no technical gate.
Parent research acceptance and ACC-01 local closure retain their own scope.
The [current summary](M5_12_LOCAL_QUALIFICATION_SUMMARY.md),
[canonical report](M5_12_REPORT_R3.md) and [cleanup](../maintenance/M5_12_CLEANUP.md)
record actual wheel and sdist consumers. Do not push, dispatch CI, merge, tag or upload
from this checklist without the corresponding approval.

Current qualified runtime source is `bf3f919`. The earlier `b4c4f93`
[accepted-position/activity repair](M5_12_PCT_ACTIVITY_REPAIR.md) records a fresh
native build and **61 focused source/native tests PASS**. It corrects pct public
positions/activity and versions the affected compatibility identities without
changing the statistical metric formulas. An older same-version native wheel
cannot satisfy the new pct capability by version alone. Final wheel/sdist
consumers, regression reconciliation and integrated handoff are recorded under the
[existing phase plan](../../upgrade/implement.md#mode5-m5-12).
The alias followup `45fd6ec` and
[continuous snapshot repair](M5_12_SNAPSHOT_REPAIR.md) are separately sealed
Python amendments. V5 successes predate the latter; final local qualification
uses V6 core artifacts and their own passing installed consumers, not relabeled
historical receipts. Local CPython 3.12 proof does not certify the remote matrix.

## Endpoint Compatibility

The static audit reads Python AST, not an installed package. Reproduce it:

```bash
.venv/bin/python tools/check_endpoint_compatibility.py \
  --baseline v1.1.1 --baseline 8f7df9d
.venv/bin/python tools/generate_public_api_inventory.py --check
```

| Comparison | Observed API Delta | Interpretation |
|---|---|---|
| Pre-ACC `8f7df9d` to current endpoint | All 48 public method signatures identical | Account/configuration repairs change behavior, not these signatures |
| `v1.1.1` to current endpoint | New `research_report`; optional `execution_endpoint` on `walk_forward`; keyword-only `meta_history` on `backtest`; optional keyword-only `reporting` on `full_report`, `show_metrics`, `quick_plot` | Additive inputs; no public method removed or previous argument/default changed |
| Stale generated root inventory to current `__all__` | 516 to 527 exports, 11 additions, zero removals | Inventory refresh, not 11 new endpoint factories |

The 11 previously omitted names are `AlphaDiagnosticReport`, `AlphaDiagnostics`,
`DiagnosticAdvice`, `DiagnosticAnalysis`, `DiagnosticBudget`, `DiagnosticContext`,
`DiagnosticObservation`, `ReportingCache`, `ReportingContractV1`,
`ReportingCoverageV1`, and `ReportingRequest`. The complete machine inventory
is [generated from the canonical root module](../../contracts/generated_public_api_inventory.json).
The audit's full export delta against the release tag is separate from this
stale-inventory delta. Static compatibility does not establish behavioral,
all-export signature, installed or platform parity.

### Intentional Behavior Changes

The [ACC-01 migration matrix](../portfolio_review/ACC01_CONFIGURATION_AND_MIGRATION.md)
is authoritative for applied settings, inactive defaults and explicit errors.
Corrected clocks, funding, sizing, risk-reducing admission, constraints,
attribution, option wallet/fees and metric edge cases can change outputs.
Unsupported hedging/isolated or other non-default requests no longer silently
appear supported. Generic linear accounts remain gross-cross/netting with
the documented OHLC liquidation convention, not a venue-exact margin model.

The [ACC-01 report](../portfolio_review/ACC01_REPORT.md) qualifies financial
runtime `70fe9f7` and its local exact native binding. Historical unchanged-
financial claims must not be copied into the new release notes. The generated
API metadata refresh has its own exact-byte amendment in
`tools/public_inventory_source_amendment.py`; it does not rewrite historical
receipts, normalize arbitrary drift or qualify a native artifact.

The later approved cold extraction is committed as `77af917`: options validation
and portfolio reporting move to focused helper modules while all retained engine
AST, moved function bodies and endpoint signatures remain unchanged. That
extraction's source qualification covered 466 files through
`.venv/bin/python -m tools.m5_12_source_guard --check` from the repo root and a
[separate immutable amendment](../maintenance/evidence/pre-m512-source-amendment.json).
This describes equivalence to the repaired ACC-01 source, not unchanged finance
relative to old QMS. Native source/ABI was not changed by that extraction;
the later approved pct repair has its own source/native evidence and does not
inherit the extraction's artifact or invariance claims.

## Researcher Reading Path

1. Choose the domain's [endpoint and account contract](../endpoint.md); an
   inherited result helper does not certify a new WFO financial adapter.
2. Read [shared diagnostics](../diagnostics/SHARED_ALPHA_DIAGNOSTICS.md) and
   [pre-search explanation](../diagnostics/PRESEARCH_RESEARCHER_REPORT.md).
   Geometry, coverage, activity, regimes and probes describe supplied evidence;
   compatibility does not choose the universally best sampler or selector.
3. For Mode 4, use [fold/meta-decision reporting](../diagnostics/FOLD_DECISION_REPORTS.md)
   and its [coverage matrix](../diagnostics/REPORTING_COVERAGE_AND_HANDOFF.md).
   Distinguish R, Q, IS contributions, matched masks, changed/unchanged candidate
   decisions and realized outcomes. Keep Ridge V1 and its registered controls
   distinct from experimental models. Sampler choice does not require meta on.
4. For Mode 5, seal the [diagnostics-first recipe](PUBLIC_CALIBRATION_V1.md)
   and [executable handoff](../diagnostics/MODE5_EXECUTABLE_HANDOFF.md) before
   calibration. Inspect the [winner qualification](../diagnostics/MODE5_WINNER_QUALIFICATION.md):
   exact selected ID/dict, objective/components, runner-up/baseline trade-offs,
   whole/annual/state risk and activity, probe/stress support and unavailable
   sections. One fixed dict is evaluated across dependent calendar/regime views;
   annual positivity is not silently substituted for the registered objective.
5. Optional archive donors are explicitly chosen, source/rights checked and
   rescored under the destination contract. No old score/account/model is
   imported. A full-development dossier cannot be backdated into Mode 4.

Economic findings retain their registered support and observed improvements
or trade-offs. Missing endpoint-specific economics are not proof of no edge;
an observed improvement is not a universal promise. This preparation opens no
new optimizer, financial study, model tournament or independent OOS claim.

## Distribution And Privacy

The sole package source remains `src/quantbt`; core/native identity is checked
against the product registry. The core's direct native dependency applies on
Linux x86_64 CPython 3.11-3.13. Its marker cannot detect libc: Alpine/musl may
fail resolution, not fall back automatically. Certified release wheels target
glibc/manylinux; [installation](../native/install.md) lists the limits.
Missing/incompatible native capability fails for explicit native-required
contracts; only eligible portable routes retain their documented fallback.

Git ignores owner alpha sources, private/local research and the exact
superseded owner draft, while keeping public plans/tests/docs trackable.
`MANIFEST.in` separately excludes those inputs from the sdist. Neither Git
ignore nor a path-only scan proves an artifact private: the final inspection
must use member/content allowlists and private-payload hashes, including
renamed copies. Use the [artifact checker](../../tools/check_release_artifacts.py)
on actual final archives, never copy research directories into package staging.
Only synthetic strategies belong in public runnable examples.

## Qualification Work And Boundaries

The table defines required scope, not unexecuted work. Current execution and
reuse dispositions are in the summary and canonical report linked above.

| Work Package | Required Execution At M5-12 | Boundary |
|---|---|---|
| M512.01 regression | Affected shared contracts, old/new Mode 5, Mode 1..4, samplers/meta, current ACC accounting/configuration and reporting | Reuse immutable scientific evidence; do not rerun completed optimizers just to count tests |
| M512.02 artifacts | Exact-source core wheel + sdist, matching native features/pair, source/member hashes and isolated installed consumers outside checkout | Local CPython 3.12 ACC wheel is not a new core artifact or the six-cell platform proof |
| M512.03 reproduction | Regenerate reports from sealed data, compare values/identities, redacted scope and schema | Corrected source does not silently recompute historical economics or rewrite their receipts |
| M512.04 operations | Cancel/failure/partial output, stale handles, permission narrowing and declared resume behavior | A saved pool or seed is not exact full-WFO recovery |
| M512.05 docs/examples/cost | Execute supported public synthetic examples from installed artifacts; verify effective options and complete requested output | Keep historical benchmark tables labelled; no unmeasured universal speed/RSS promise |
| M512.06 final handoff | Final source/pair/claim/120-requirement mapping, dependency dispositions, privacy and cleanup | Distinguish local software, economic support, platform, publication and live authority |

### CI And Consumer Wiring Before Remote Admission

The initial architecture failure remains in its original receipt. The approved
extraction resolves it: `native_option.py` is 956 lines and
`native_portfolio.py` is 811. The 1,000-line trigger, registry exceptions and
import-boundary rules are unchanged; the architecture command now passes.

- Candidate workflow filters now include the current feature branch, canonical
  source, shared diagnostics/reporting, Mode 5 examples, ACC and verifier changes.
  No push or workflow execution is authorized by the current local qualification.
- A maintained [installed consumer roster](M5_12_CONSUMER_MATRIX.md) supplements
  existing W3/scalar/portfolio/package/intrabar/event proofs with Mode 5,
  winner/donor, reporting and ACC controls. Source unit/mutation verification
  of the wiring is not installed PASS; the actual final-source artifact runs
  are now recorded for wheel and sdist. CI must later execute them, not just collect/parse
  their metadata; local results do not certify the six remote rows.
- `qms08_package --release-pair` is an available artifact builder, not by itself
  a complete M5-12 verifier. Its older private-pair/native-reuse recipes and
  source reconciliations retain historical meaning. Qualify the final staging,
  consumers and current-source gates together; never bypass a stale-source
  failure or present old consumer receipts as freshly run proof.
  Preparation reconciles the approved diagnostics root exports by exact
  commit/hash and passes mutation negatives. The broader historical
  `qms08_gate.validate` still forbids changed financial source from its old
  entry; it remains a historical gate, not the ordinary `verify_pair` entry
  called by candidate package consumers. The new installed preflight calls the
  exact current-source guard before and after execution instead of treating
  that old financial-invariance check as current certification.
- Remote scope remains Ubuntu 22.04/24.04 x CPython 3.11/3.12/3.13, with the
  approved manylinux native release matrix. Source-only static gates and one
  local interpreter cannot replace it.

### Publication Order After Separate Approval

After local M5-12 and remote certification: review/commit release metadata,
merge the reviewed branch through dev then main, verify the exact main ref,
tag the approved pair, certify/publish native wheels first, then publish core
through the protected GitHub release workflow. Finally run public consumer
proof against the actual public pair. Follow the
[channel checklist](../testpypi_release_checklist.md) and
[release handoff](../meta_selection/RELEASE_HANDOFF.md), not historical tag
examples. No tag is moved or artifact overwritten by this preparation.

## Local Preflight Receipt

The [preparation receipt](../maintenance/M5_12_PREPARATION.md) records actual
commands, results, source/metadata boundaries and exact scratch cleanup. These
focused static checks are preparation, not M512.01..06 PASS. No environment
replacement, native rebuild, package install, financial run or remote action
is implied by the original audit. Later technical preflight has its own
resource/cleanup [receipt](../maintenance/PRE_M512_TECHNICAL_PREFLIGHT.md);
it is not a full M5-12 launch or artifact certificate. Local qualification was
approved later; its current status and the focused pct repair evidence are
recorded above, without rewriting those earlier receipts.

For local serial qualification, run `tools/m5_12_resources.py --check` again at
admission. The registered incremental budget is 896 MiB **plus** the 5 GiB disk
reserve and separate RAM guard. It permits one installed consumer environment
at a time and conditional exact retained-native reuse. Its original no-native-
build restriction was superseded only by the owner-approved narrow pct rebuild;
the older wheel cannot substitute for that repaired native artifact. This does
not approve arbitrary rebuilds, parallel environments or the legacy four-retained-
consumer schedule. The repair report records the observed build growth and
reserve, not a measured peak. Recheck resource admission and exact artifact
eligibility before any new consumer execution; larger fixtures or different
retention schedules still require a new forecast. The registered consumers are
now terminal and retired after hash/process review. Their retained receipts
describe actual past executions; reruns require fresh exact-artifact installation.
The initial fixture forecast and two cleanup-control exceptions remain visible
in the cleanup report, not retroactively passing resource receipts.

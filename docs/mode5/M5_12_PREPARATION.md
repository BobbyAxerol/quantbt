# M5-12 Package Preparation

Date: 2026-10-22 UTC. This is a source/documentation/privacy preflight, not
the M5-12 execution receipt or publication authorization. Candidate pair:
**quantbt-engine 1.1.2 / quantbt-native 0.4.3**, unchanged by this preparation.
No live PyPI index query is represented here.

The [unified phase](../../upgrade/implement.md#mode5-m5-12) remains
APPROVED_CONDITIONAL / NOT_STARTED. Parent research acceptance and ACC-01 local
closure satisfy their own entry dependencies; separate launch/resource
admission is still required. Do not push, dispatch CI, merge, tag or upload
from this checklist without the corresponding approval.

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

## Qualification Work Remaining

| Work Package | Required Execution At M5-12 | Boundary |
|---|---|---|
| M512.01 regression | Affected shared contracts, old/new Mode 5, Mode 1..4, samplers/meta, current ACC accounting/configuration and reporting | Reuse immutable scientific evidence; do not rerun completed optimizers just to count tests |
| M512.02 artifacts | Exact-source core wheel + sdist, matching native features/pair, source/member hashes and isolated installed consumers outside checkout | Local CPython 3.12 ACC wheel is not a new core artifact or the six-cell platform proof |
| M512.03 reproduction | Regenerate reports from sealed data, compare values/identities, redacted scope and schema | Corrected source does not silently recompute historical economics or rewrite their receipts |
| M512.04 operations | Cancel/failure/partial output, stale handles, permission narrowing and declared resume behavior | A saved pool or seed is not exact full-WFO recovery |
| M512.05 docs/examples/cost | Execute supported public synthetic examples from installed artifacts; verify effective options and complete requested output | Keep historical benchmark tables labelled; no unmeasured universal speed/RSS promise |
| M512.06 final handoff | Final source/pair/claim/120-requirement mapping, dependency dispositions, privacy and cleanup | Distinguish local software, economic support, platform, publication and live authority |

### CI And Consumer Wiring Before Remote Admission

The following architecture failure is locally reproduced by the same static
command used in CI; no remote workflow has been run:

- `tools/check_module_architecture.py` currently FAILS: ACC-01 leaves
  `native_option.py` at 1,040 lines and `native_portfolio.py` at 1,006, above the
  1,000-line review trigger without listed exceptions. Do not merge this as
  CI-ready or raise the global threshold. M5-12 must make a small cohesive,
  parity-checked extraction or obtain an explicit documented ownership review;
  rerun this gate and exact-source/artifact qualification after the resolution.
  This is a real architecture/pre-CI gap, not an observed new accounting defect.

The remaining items are wiring inspection findings, not remote run failures:

- `qms-candidate.yml` push trigger names `feat/meta-selection-samplers`, not the
  current `feat/mode5-diagnostics-first`. Its PR paths cover earlier QMS and
  execution changes but do not fully enumerate shared diagnostics/reporting,
  current Mode 5 examples and ACC option/metric paths. Review these at M5-12;
  do not assume a branch push runs the intended matrix.
- The installed QMS matrix covers W3, scalar, portfolio, bounded packages,
  liquidation, intrabar and event contracts. It has no final-source installed
  Mode 5 winner/donor/shared-reporting or ACC-specific consumer step yet.
  Add these before claiming the matrix certifies the candidate's whole scope.
- `qms08_package --release-pair` is an available artifact builder, not by itself
  a complete M5-12 verifier. Its older private-pair/native-reuse recipes and
  source reconciliations retain historical meaning. Qualify the final staging,
  consumers and current-source gates together; never bypass a stale-source
  failure or present old consumer receipts as freshly run proof.
  Preparation reconciles the approved diagnostics root exports by exact
  commit/hash and passes mutation negatives. The broader historical
  `qms08_gate.validate` still forbids changed financial source from its old
  entry; it is not the final ACC-01/M5-12 source certificate.
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
is part of this audit. Final package execution needs its own forecast and
admission; do not reuse this small docs/test lane's resource budget. At this
cleanup only about 5.22 GiB is free, just 0.22 GiB above the required 5 GiB reserve;
do not launch another environment/build from nominal free-space alone.

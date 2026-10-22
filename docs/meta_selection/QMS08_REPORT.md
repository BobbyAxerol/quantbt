# QMS Phase Report - QMS-08

## Scope And Decision

2026-10-04, `feat/meta-selection-samplers`, entry `559b4d1`.
Owner authorized local QMS-08 implementation/qualification, not publication.
Followed the [unified plan](../../upgrade/implement.md#qms-08) and
[detailed guide](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#qms-08--regression-bounded-economic-study-tài-liệu-và-đóng-gói),
including sections 8/12/13/14/15 and repository architecture rules.

**Software candidate qualification complete locally. Empirical validation not
run. Remote platform matrix and final owner acceptance pending.** This is not
completion of the guide's scientific acceptance study or live certification.
The published/source/installed baseline remains **1.1.1 / 0.4.2**. No push,
merge, tag, release, deployment, public version change or PyPI operation occurs.

The build-only pair **1.1.1+qms08 / 0.4.3.dev4** qualifies existing opt-in
candidate features; it is not a proposed public version. No financial code,
methodology, endpoint, objective, RNG protocol or default is rewritten here.

## Delivered

- Full affected regression of QMS-01..08, legacy optimizer/search-space behavior,
  five modes and their supported schedules, fixed/TTS/account controls, native
  WFO and packaging/release-source tests. Explicit off and omitted meta agree.
- Complete runnable off, sampler-only, reviewed local-history and unsupported
  examples; existing shadow/active and portable host examples remain available.
- Independent required-64-ID registry and six gates, actual JUnit/log/artifact
  verification, historical byte preservation and strict completion flags.
  Q8-T03's real-alpha disposition cannot become PASS from synthetic tests.
- Pure saved-output paired analysis with signed decay/forward decomposition,
  genuine zero, typed undefined outcomes, original calendar and denominator.
  Regeneration neither executes an account nor fits/predicts a model.
- Three actual CPython interpreter builds, exact source wheel/sdist inventories,
  retained artifact/log hashes and four isolated installed lanes per interpreter.
  Native numerics/prepared execution run a compiled Rust extension, not a mock.
- Shared private-fixture action for CI/core-publish/native-release regressions;
  a separate read-only Ubuntu 22.04/24.04 x CPython 3.11/3.12/3.13 candidate
  matrix. Workflows are prepared/tested structurally, not dispatched.
- Usage, endpoint, sampler, causal-WFO, methodology, capability, examples and
  README navigation documentation. Existing public endpoint signatures survive.

Implementation/initial qualification commit: `2269dc1`. The subsequent scoped
CI/docs and final receipt commits are recorded in branch history.

## Test And Gate Evidence

Final affected regression: **567 passed**, zero failures/errors/skips,
**145.66 s**, including **56 QMS-08 checks**. This comprises 429 QMS checks
and 138 adjacent optimizer/WFO/account/packaging checks. The initial 561-test
run also passed before adding installed missing-Optuna and verifier/CI guards;
it is not added again to inflate the final count. Actual cases are retained in
[executed JUnit](../../benchmarks/optimization/meta_selection/qms08_tests.xml)
and the independently derived [gate receipt](../../benchmarks/optimization/meta_selection/qms08_gate_receipt.json).

Q1..Q8 requirement-group case counts: **38 / 96 / 83 / 41 / 38 / 46 / 31 / 56**.
Q8-T01..08 case counts: **9 / 4 / 1 / 11 / 8 / 17 / 5 / 1**.

Q1-T01..Q8-T08 are **64 requirement IDs**, not 64 independent market samples.
Their actual pytest memberships are in the receipt. The software assertion
under Q8-T03 verifies NOT_RUN; it does not execute the required real alpha.
Expected Optuna experimental-feature warnings are not failures or missing tests.

| Gate | Actual disposition |
|---|---|
| G8-REGRESSION | PASS: actual affected legacy/QMS/account/result tests |
| G8-END_TO_END | PASS: public synthetic lineage, source-exact installed prepared/native/reference parity |
| G8-EMPIRICAL_SCOPE | NOT_RUN_BUDGET: no approved real-alpha/data/calendar/economic registration |
| G8-DOCS | PASS: executable cases; logged source/registry/API/architecture/benchmark/docs checks |
| G8-PACKAGE | PASS_LOCAL_3_INTERPRETERS_REMOTE_PENDING |
| G8-OWNER | PENDING: no final acceptance or release decision invented |

The gate checks exact entry/source manifests, the independently known required
gates/IDs, historical evidence membership and bytes, consumer output scalars
against actual command logs, artifact hashes, stage-only identity changes and
strict booleans. Negative tests cover altered source/model/payload/scalar/gates,
missing or failed/skipped cases, false completion and fabricated market counts.
Earlier model/artifact tamper tests remain part of the full regression.

## Installed Artifact Matrix

All proof runs execute `python -I` outside checkout source imports and assert
`site-packages` origins. Installed research environments remain unchanged.

| Interpreter | Core wheel/sdist + native build | Installed lanes |
|---|---:|---|
| CPython 3.11.17 | 52.26 s | off, core-only optimization, exact pair, core-sdist pair: PASS |
| CPython 3.12.13 | 50.14 s | off, core-only optimization, exact pair, core-sdist pair: PASS |
| CPython 3.13.16 | 56.11 s | off, core-only optimization, exact pair, core-sdist pair: PASS |

Times are tool-observed build spans, including build-environment/dependency
setup, core build and native compilation; they are **not backtest performance**.
Each exact pair/sdist lane exercises six public synthetic causal meta folds,
all four sampler recipes, product handshake, actual Rust Gram/solve and
reference/prepared params/equity/position parity. Numerical tolerances are
`rtol=atol=1e-10` for account/positions and `rtol=1e-9, atol=1e-10` for Gram/solve.
Logical selected params and information-scope flags match exactly.

Core-only lanes explicitly omit native for negative qualification. Off does not
load Optuna/CMA-ES; requesting optimization without Optuna produces its existing
informative ImportError. With optimization dependencies but no native, auto
records the qualified fallback and require fails. Pair/sdist lanes resolve the
exact private dependency and pass `uv pip check`.

Core wheel is 976,971 bytes, sdist about 876 kB, native wheel about 1.18 MB;
each exact SHA256/size and consumer dependency version is retained in evidence.
Native files on this host are CPython-specific `manylinux_2_34_x86_64` wheels.
This proves local Linux installation, **not portable manylinux2014 or success
on both remote Ubuntu images**. Six remote jobs remain NOT_RUN.

Build staging changes only six declared version/descriptor files; Cargo also
updates its copied lockfile's own native-package identity. Structured lock
comparison forbids any dependency change. Canonical Python modules match wheel
and sdist byte for byte after those declared identity adaptations. Artifact
allowlist/secret scans pass. Private alphas, market datasets, caches, `.venv`,
mirrors and evidence bundles are not shipped or committed into distributions.
The final README/prose can evolve after the immutable private build; no staged
financial source drift is permitted. Artifact hashes preserve that build's bytes.

Retained local build/consumer environments occupy approximately **2.1 GiB**, with
213 MiB for the additional interpreters; these are ignored qualification tooling,
not process RSS, runtime allocation or shipped wheel sizes. No cleanup deletes
the evidence required for rechecking this gate.

## Financial And Information Scope

Actual active params feed the existing causal OOS signal and one final account.
Diagnostic reset-fold equity is not stitched into a new account. Fees, slippage,
funding, sizing, leverage, position carry and metric conventions remain unchanged.
Fixed calls and explicit-off controls retain their existing schedule guards;
per-fold schedules still require `param_ranges`, not one fixed params dictionary.

Off is the old path. Shadow preserves the native winner/account. Active can use
compatible **past matured forward** labels; it is not falsely called stock
IS-only, including a learned same-anchor choice. Current outer OOS is never a
fit/rank input. Snapshot/completion/seal/readiness/effect clocks, terminal
revision replacement, late-label/future-suffix and resume parity are covered.
Portable exports do not imply trusted permissions, activation or live trading.

## Economic And Performance Disposition

No approved real alpha/BTC cell, dataset, calendar or market-study resource budget
was supplied. Assessed market trials/origins/development/locked-valid folds are
all **zero**; market gain and dependent-time uncertainty are **not estimated**.
Q8-T03 real-alpha lineage remains NOT_RUN_REAL_ALPHA. Synthetic support-one
fixtures do not satisfy the default twelve-origin scientific support threshold.

Saved reporting preserves

\[
R_k=D_{\mathrm{native},k}-D_{\mathrm{meta},k}
   =I_{\mathrm{native},k}-I_{\mathrm{meta},k}+Q_k,
\qquad Q_k=F_{\mathrm{meta},k}-F_{\mathrm{native},k}.
\]

Lower IS alone can improve R with Q=0; it is not demonstrated forward gain.
Negative/no-gain, no-trade/zero-variance/failed windows retain typed status and
original dates. Mean paired-valid fold statistics are not continuous-account
Sharpe. The helper never manufactures confidence intervals or an edge label.

No new execution optimization or speedup is claimed in QMS-08. Reuse the sealed
[QMS-07 matched report](QMS07_REPORT.md): reference meta p50 **2.743 -> 1.916 s**
(-30.2%) and prepared/meta Rust **2.329 -> 1.425 s** (-38.8%) on its exact
synthetic public workload. Its full decision parity and fixed RSS/PSS plateau
were checked; those numbers are not universal live speed or market improvement.
No redundant financial benchmark rerun is required by these docs/package edits.

## Remaining Decisions And Debt Ledger

| Item | Disposition after QMS-08 | Next scoped action |
|---|---|---|
| Mandatory scalar QMS software/docs/local artifact proof | Complete locally | Owner review of this receipt |
| Real-alpha lineage and empirical acceptance | Not run, not certified | Approve data/calendar and >=128 attempted trials/cutoff, >=12 matured origins and >=12 paired-valid locked folds; reserve >=12 dev folds if selecting recipes |
| Public core/native version and feature activation | Unchanged; owner decision pending | Approve new exact pair and candidate feature activation; build fresh release artifacts |
| Remote installed-platform matrix | Workflow ready, not run | Separately approve push; collect all six actual job receipts |
| W3 reactive/reset-flat meta seam | Explicit unsupported optional scope | Separate approved integration phase, no silent fallback to another financial contract |
| Configured BLAS=4 versus observed OpenBLAS=1 telemetry | Inherited performance-reporting debt | Align configured/observed resource metadata without changing execution math |
| Mixed/high-dimensional Rust slower than BLAS | Qualified fallback retained, no universal speed claim | Optional measured geometry-aware numeric dispatch/parity phase |
| Disabled p50/p95 performance budget | Local proposed budget met; owner acceptance pending | Review QMS-07's +2.63%/-0.82% matched record |

No mandatory scoped software failure is deferred to disguise completion. These
remaining scientific, optional-scope, performance and release decisions are
kept visible for the user's planned post-QMS review/subphases.

## Recheck And Handoff

Start with [usage](USAGE.md), [qualification/reproduction](QUALIFICATION.md),
[portable handoff](HANDOFF.md) and [current handoff](../../handoff/WFO_META_CURRENT.md).
Read [verified evidence](../../benchmarks/optimization/meta_selection/qms08_qualification_evidence.json)
and [gate receipt](../../benchmarks/optimization/meta_selection/qms08_gate_receipt.json);
earlier sealed QMS artifacts stay unchanged.

```bash
.venv/bin/python -m tools.qms08_gate --check
.venv/bin/python -m tools.qms08_gate --report /tmp/qms08-summary.md
```

Both revalidate stored outputs without engine execution or model inference.
For a later owner-approved release, review the registered pair/features, push
the scoped branch, pass candidate/core/native CI, merge dev then main, build
fresh exact release artifacts, publish native before core dependency resolution,
and run Public Native Consumer Proof. **None is authorized or run here.**
Rollback is opt-in removal/off or qualified reference policy; do not revert
unrelated account/WFO upgrades or rewrite historical records into PASS.

# QMS Qualification And Release Boundary

## Scope

The feature branch implements eight approved QMS phases. New behavior is opt-in
and remains separate from published core/native `1.1.1/0.4.2`. Historical QMS-08 exercises
private build-only `1.1.1+qms08/0.4.3.dev4`, with QMS numeric and original-pass
prepared witness feature flags enabled only in those builds.

The owner approved preparation of **1.1.2 / 0.4.3**, including default compiled
QMS exports. Meta selection remains opt-in; native ABI/financial policies are
unchanged. No merge, tag or upload is authorized. The fresh release builder
uses unchanged canonical identities and ordinary Cargo default features;
private PASS cannot certify that new pair. See the [release handoff](RELEASE_HANDOFF.md)
for exact artifacts, installed-W3, remote and pending public-index gates.

Start with [usage](USAGE.md), [integration](INTEGRATION.md),
[mathematical model](MODEL.md), [samplers](SAMPLERS.md) and
[portable handoff](HANDOFF.md). See the [QMS-08 actual report/debt ledger](QMS08_REPORT.md).
For current source, read [local debt closure and real meta effectiveness](LOCAL_DEBT_CLOSURE_REPORT.md);
the older QMS08 receipts below retain their historical source and scope.
Detailed requirements remain the
[approved guide](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#qms-08--regression-bounded-economic-study-tài-liệu-và-đóng-gói).

## Additional Methodology Review

QMS-C01 is approved for specification and tests only; additional meta activation
requires a separate owner decision. The [amendment](ADDITIONAL_METHODS_REVIEW.md)
and [phase report](QMSC01_REPORT.md) classify actual native anchors, data roles,
full pools and decision frontiers for eight existing native combinations.
They preserve the original guide, Ridge, financial sources and supported meta
matrix. Synthetic native/off parity is not new-mode installed-wheel or economic
certification. C01-D01, the default Mode 2 final-OOS-selection metadata discrepancy,
is recorded explicitly and is not silently marked fixed.

## C02 Transport Qualification

[C02 transport/account contracts](W3_TRANSPORT_AND_ACCOUNT_CONTRACTS.md) extend
only the existing Mode 4/per_fold_causal/reset-flat W3 lane: inprocess or safe
Linux fork/COW process, original-pass detached witnesses and native cooperative
deadlines. The R3B original-result witness primitive is qualified separately;
public meta batches and carry/multi-symbol runtimes are not activated.
The additive atomic-token getter fixes an actual active-batch cancellation
borrow failure; financial Rust source remains exact after removing that getter.
`tools/qms_c02_source_guard.py` verifies the exact reviewed Python adapters and
native getter, while older phase gates retain their historical source/artifacts.
No scientific guide/Ridge/objective/sampler or release identity is exempted.
Fresh C02 core wheel/sdist plus the rebuilt local native wheel must pass isolated
`python -I tools/qms_local_consumer.py --witness-transport` in a cold directory.
Old remote 6/6 or private PASS receipts do not certify these new artifact bytes.
Final local qualification is **618 QMS/affected checks + 36 native checks PASS**,
including 50 C02 checks, fresh wheel/sdist installed process consumers and the
runnable example. The [C02 report](QMSC02_REPORT.md) records exact artifacts,
source boundaries, matched transport cost and pending remote/public gates.

## Software Gates

The independent `tools/qms08_gate.py` registry contains all **64** Q1-T01..Q8-T08
IDs and six QMS-08 gates. It reads actual JUnit cases/failures/errors/skips,
checks source/guide and immutable earlier evidence, artifact bytes and retained
command logs. Removing required gates, tampering scalar values/completion flags,
or changing artifact bytes cannot manufacture a PASS receipt.

Financial sources stay byte-locked against QMS-08 entry; an exact separate
packaging allowlist validates the owner-approved identity/default-feature change.
Legacy eight supported mode/schedule combinations span all five modes; four
sampler recipes, fixed params, one train/test holdout and stitched accounting
are exercised. New-feature tests cover cold/shadow/active/same-anchor, exact
full pool, real lower-IS software switches, conditional geometry, future mutation,
late revisions, checkpoint restore, origin weights, clocks and native boundaries.

The original software switch fixtures are synthetic/engineered. They prove actual
candidate lineage, not **Q8-T03 real-alpha market** lineage. That scientific
expectation remains explicitly NOT_RUN until registered market execution.

## Historical Private Artifact Qualification

The builder copies only tracked canonical source and allowlisted packaging
files. It performs six exact identity adaptations in the build copy: project
version/dependency, import version, native Cargo/project version and generated
Python/Rust product descriptor. Registry rendering reuses the existing generator;
financial semantics and checkout files are not edited.
Cargo also updates the copied lockfile's own native-package version; independent
structured comparison verifies no dependency or other lock entry changed.

Core wheel and sdist Python members match the staged canonical source byte for
byte; only declared identity adaptations differ from checkout. All artifacts
pass repository allowlist/secret scanning. Retained build/log/artifact refs
remain under ignored `.maturin/qms08`; datasets, private alpha, `.venv`, source
mirror and benchmark bundles do not enter distributions.

Each interpreter uses fresh environments outside canonical source imports:

| Lane | Expected proof |
|---|---|
| Core-only/off | Fixed-account result; no optional optimization dependency loaded |
| Core-only/optimization | Off/shadow parity; native-missing auto reason and require failure |
| Exact private wheel pair | Product handshake, all four samplers, actual prepared/meta Rust and reference account/selection parity |
| Install from core sdist + private native | Same installed feature/account tests, dependency resolution and `pip check` |

Supported interpreter target is Linux x86_64 CPython 3.11-3.13. Local execution
on this host does **not** certify manylinux portability or both Ubuntu runner
images. `.github/workflows/qms-candidate.yml` prepares non-publishing installed
qualification on Ubuntu 22.04/24.04 x CPython 3.11-3.13. For the approved release
pair, remote qualification now passes all six rows on `0970d55` in
[run 37225926548](https://github.com/BobbyAxerol/quantbt/actions/runs/37225926548).
Read the [current release-gap report](RELEASE_GAP_REPORT.md), not the historical
private artifact seals, for that exact source and scope. Default-feature release
builds use zero staged identity rewrites. Public-index and manylinux2014 release
qualification are still separate later gates.

## Reproduce Locally

For the original private identities (not public release evidence):

```bash
.venv/bin/python -m tools.qms08_package --output "$PWD/.maturin/qms08/qualified"
# Repeat with --python /path/to/python3.11 and /path/to/python3.13.
# A sealed lane is immutable; choose a fresh output for a changed candidate.
```

The actual artifact consumer runs via `python -I` from a build directory and
asserts `site-packages` origin. It neither loads repo `src` through PYTHONPATH
nor substitutes a mock Rust extension. Build tools/dependencies live in their
own venvs; installed research environments are unchanged.

After the recorded regression and artifact matrix:

```bash
.venv/bin/python -m tools.qms08_gate --gather-checks
# On a new candidate, seal once after tests: python -m tools.qms08_gate
.venv/bin/python -m tools.qms08_gate --check
.venv/bin/python -m tools.qms08_gate --report /tmp/qms08-summary.md
```

The report command revalidates stored evidence and renders it without account
execution or model inference. Old sealed receipts remain historical, not silently
updated when new test files are added. New qualification records bind the current
source and all required test coverage instead.

## Sealed QMS-08 Economic Disposition

No approved real-alpha/BTC data/calendar/resource registration was supplied for
the original QMS-08 seal. That historical market disposition remains
**EMPIRICAL_VALIDATION_NOT_RUN**: zero
assessed market trials/origins/development/evaluation folds and no estimated
market edge. Reduced-support synthetic demos are never counted toward >=12
independent valid origins or >=12 paired-valid locked market folds.

Before a market study, register alpha/version/data digest and permissions,
calendar/IS/FWD lengths, original execution economics, allowed history/cohorts,
support, native pool/panel policy, <=2 sampler recipes, >=128 attempted trials
per cutoff, >=12 matured origins and >=12 paired-valid locked folds. If choosing
recipes/model settings, reserve >=12 development folds separately. Do not
reselect budgets/settings after locked outcomes. The separately owner-approved
[ETH real-alpha review](REAL_ALPHA_REVIEW.md) is descriptive research, not
retroactive pristine BTC certification of this historical seal.

Saved-output reporting preserves signed decay and
`R = D_native - D_meta = I_native - I_meta + Q`, where `Q` is actual forward
Sharpe difference. It preserves genuine zero and typed no-trade/zero-variance/
failed outcomes, their calendar and denominator. Mean paired fold Sharpe is
not continuous-account Sharpe. Uncertainty needs registered time-dependent
inference; these engineering checks do not invent confidence intervals.

## Review And Rollback

Owner review, remote packaging matrix, public release version/capability
activation and real market acceptance remain separate decisions. The owner-approved
local follow-up implements exact prepared witnesses, a bounded sequential W3
adapter, measured Rust/BLAS fit dispatch and observed thread telemetry. Its
new receipts are separate from sealed QMS-08; see the
[integration contract](INTEGRATION.md#w3-sequential-meta). C02 process transport
has a separate local gate; public meta batch and current-source remote/public
qualification are not inferred from an older local adapter receipt.

To disable QMS, omit/remove its optional config/runtime binding. Qualified
reference execution remains available when native numerics are slower or missing.
Do not revert unrelated WFO/account upgrades. A future release must build and
certify its own exact core/native pair, publish native before core resolution,
then run the existing Public Native Consumer Proof; this phase does none of
those actions automatically.

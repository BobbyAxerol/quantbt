# QMS-E02: Shared Domain Evaluation And Admission

## Scope And Decision

**COMPLETE_LOCAL_APPROVED_SCOPE**, 2026-10-05. Owner approved E02 only on
`feat/meta-selection-samplers`, entry `82c1421`. Pair stays **1.1.2 / 0.4.3**.
No release, push, merge, tag, alpha study, new method or domain activation.
Read the [phase plan](../../upgrade/implement.md#qms-e02),
[versioned adapter amendment](DOMAIN_ADAPTER_CONTRACT.md) and original guide's
[architecture](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s2),
[history](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[selection](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7),
[ownership](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8)
and [measurement](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10).

The [independent receipt](../../benchmarks/optimization/meta_selection/qms_e02_final_gate_receipt.json)
verifies all six groups, actual before/after execution, exact reviewed source,
installed artifacts/logs and matched resources. Local software evidence is not
remote, manylinux2014, public-index or economic certification.

## Architecture And Actual Work

Six focused `optimization/meta_selection/domains/` modules separate typed
contracts, registry, lifecycle, scalar and reactive adapters. Domain tags are
explicit; no guessing from Series/matrix shapes. Contracts cover input kinds,
stages, effective params, exact calendars/cutoffs/seals, original-result evidence,
ordered universe, costs/metrics, instrument/funding/timing and account policies.
Existing qualified family IDs remain unchanged. Future domain families require
the versioned compatibility namespace, not scalar history reuse.

The scalar adapter contains former signal/frame-only assumptions. The W3
adapter delegates to the existing native reset-flat observer/witness. Each calls
its financial owner once per observer evaluation, uses the existing reducer on
that original output and adds cold-path telemetry. IS scoring, pool capture,
native selection and final OOS accounting remain with their current owners;
E02 does not replace them with a generic execution engine.

Adapters own no market arrays, account, strategy, RNG, persistent candidate cache
or PyO3 bridge. The existing prepared witness/context supplies exact market
identity once per run; actual funding/volume/constraints affect the binding.
Reset/cancel/clear respects existing owners, retains no financial result and
leaves caller history untouched. W3 runtime/process cleanup is preserved.

`walkforward_support_matrix` keeps its signature and nine old rows. Additive
columns distinguish domain, input ABI, method/schedule, software/empirical
status and gate owner. Conformance checks actual endpoint dispatch against the
registry and discovery; new unregistered/undiscovered dispatch fails. Registration
cannot open active or shadow execution.

## Correctness And Gates

**E02-T01 through T06 PASS**. Full QMS regression: **1,104 PASS**, **393.29 s**,
zero failures/errors/skips; 207 existing Optuna experimental warnings. Ten gate
negatives and four final docs checks bring the union to **1,118 distinct passing
tests**; repeated runs are not summed. There are 72 E02 contract/parity/lifecycle/
admission/proof cases plus four documentation cases in this union.

- Eight native routes preserve omitted/explicit-off search, objectives, pool,
  native anchor, params, account and Python/NumPy RNG identities exactly.
- Four scalar lanes preserve scientific/account signatures and actual decisions:
  off, shadow, shadow with observer, active with observer.
- Three W3 lanes preserve objectives, pool observations, panel/selection identities
  and original equity/returns/positions/fee/funding/margin buffers. W3 remains
  segmented reset-flat, never gains continuous equity by concatenation.
- W0/W1/W2 original/prepared full-pool, exact-anchor and account parity pass.
- Actual future-market mutation, unavailable/future labels, incompatible family/
  universe/costs, wrong domain/ABI/input/index/seal and lifecycle failure cases
  preserve earlier decisions or fail closed as specified.

Measured scalar observer completion/publication clocks vary across wall-time runs.
Their revision-ID byte strings are not claimed identical; ordered support counts
and other compared selection/financial fields are checked. Actual availability,
permission and maturity guards are separately tested on the public runner.
No clock is backdated to manufacture parity. The audit harness normalizes JSON
tuple/list representations to avoid a false report mismatch, not an engine fix.

Exact source guards admit only eleven reviewed adapter/discovery/lifecycle files.
Rust, Ridge/search/objective/reducers, protected guide, release identities and
pre-existing sealed receipt bytes remain unchanged. Architecture, canonical
source, product/API inventory, benchmark governance and secret guards PASS.

## Installed Artifacts

Fresh canonical core wheel/sdist pass source equality and artifact/secret
allowlists. Each runs four mandatory consumers: scalar/prepared/four recipes,
W3 original process witnesses, C03 schedulers and C04 fresh-process continuation:
**eight isolated runs PASS**. Two additional `python -I` consumers verify actual
typed execution, off/shadow account parity, closed lifecycle, unchanged discovery
and pending-domain rejection: **ten installed consumer runs in total**.

| Artifact | SHA-256 |
|---|---|
| Core wheel | `aad7c98c04d31af059245a1331f58c3f953c17c50bfb8ceb2281e809d7572f8c` |
| Core sdist | `ced15ecffcd6d0072659f82e06763b209d0b5b0e96ed1f48eb4b481c13d17698` |
| Unchanged native wheel | `20a9a5116470ad0f385bdfe4ec902ea43ba580a6cdb208920caffda4b8d4ba7a` |

Native reuse requires exact tracked Rust/source/artifact hashes against C04;
actual loaded binary hashes are validated. This CPython 3.12/manylinux_2_34
proof is not a fresh native build or portability certificate. The reused builder
retains its E01 inner proof schema; E02's outer gate separately binds current
source/artifacts and actual adapter consumers.

## Matched Resources

Three alternated baseline/current pairs per lane: **18 fresh processes**, same
thread budget/native dependency, public synthetic SMA/W3 fixtures and unchanged
trials, outputs and observer work. Wall/CPU excludes identical prior import/JIT
warm-up; peak RSS covers the whole process including warm-up. These are medians.

| Workload | Baseline Seconds | E02 Seconds | Delta | Baseline Peak RSS MiB | E02 Peak RSS MiB |
|---|---:|---:|---:|---:|---:|
| Scalar off, 36 trials | 0.897 | 0.944 | +5.23% | 286.02 | 285.22 |
| Scalar active, 36 trials / 32 observer calls | 2.012 | 2.057 | +2.25% | 289.78 | 289.25 |
| W3 active, 32 trials / 8 observer calls | 1.186 | 1.200 | +1.22% | 296.62 | 296.03 |

Meta off instantiates no adapter. Enabled adapters add **zero market array
copies, owned market bytes, financial replays or PyO3 crossings**. Counts are
adapter-scoped; actual financial FFI remains in its owner's telemetry, not a
fabricated total of zero. One delegate/original observation per observer call
is verified, without per-bar model callbacks.

These short measurements show modest overhead, not speed improvement or proven
RSS savings. Disabled +5.23% is not reported as meeting the guide's proposed
+3% p50/+5% p95 budget; three samples do not qualify that statistical gate.
E02 is architecture/correctness, not performance promotion. Stable larger timing/
retention qualification remains E08.

## Reproduce And Proceed

With QuantBT tooling and its qualified local native artifact available:

```bash
export PYTHONPATH=src:.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
PY=.maturin/qms08/release-regression-v1/bin/python
"$PY" -m pytest -q tests/meta_selection --junitxml=/tmp/qms-e02.xml
"$PY" -m tools.qms_e02_audit --output .maturin/qms08/e02-review/after-fresh.json \
  --baseline .maturin/qms08/e02-review/before-v2.json
"$PY" -m tools.qms_e02_measure --output .maturin/qms08/e02-measure-fresh --repeats 3
```

Historical candidate-required QMS-04 tests also need their previously built
`QMS04_NATIVE_EXTENSION`; that is not substituted for the actual 0.4.3 installed
proof. Fresh artifact/log/baseline paths must not overwrite seals. Retained gate
inputs identify exact executed lanes and hashes.

Commits: contracts `6a2f2d5`, migration `6220a62`, proof/resource tooling `ebef9f5`.
E-G06's shared architectural gap is closed locally. Domain evaluators and paired
real-alpha decay studies remain **E03-E07**, not discarded work. Use the
[pre-outcome registration template](DOMAIN_EMPIRICAL_REGISTRATION.md); no scalar
study is reused as intrabar/grid/portfolio evidence. C01/C05 activation, W3
carry/multi-symbol/public meta batching and scientific replacement remain
unapproved. Final remote matrix, manylinux/public artifacts and owner release
review remain **E08/PENDING**, with no remote operation performed.

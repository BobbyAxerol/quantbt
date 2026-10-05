# QMS-C02: Witness Transport And Account Contract Review

## Disposition

Date: 2026-10-05 (Asia/Saigon). Branch: `feat/meta-selection-samplers`.
Owner approval: **transport plus carry/multi-symbol specification and tests**.
Status: **COMPLETE_LOCAL_APPROVED_SCOPE**. Remote/public certification pending.

Read the [C02 plan](../../upgrade/implement.md#qms-c02---w3-process-batch-deadline-carry-and-multi-symbol-contracts),
[transport/account contracts](W3_TRANSPORT_AND_ACCOUNT_CONTRACTS.md) and original
guide [section 8.4](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8).
Entry source: `0bb77b5`; reviewed implementation: `2b9f05a`.
Plan, original-pass transport and batch/cancellation changes are separate commits
`ac84404`, `70c7b22`, `2b9f05a`; final evidence/source-gate changes follow them.

Prepared identities remain **quantbt-engine 1.1.2 / quantbt-native 0.4.3**.
This phase does not push, merge, tag, publish or replace a scientific study.
The alpha notebooks and original mathematical guide were not edited. There is
no new economic study or claim that meta improved future Sharpe/decay in C02.

## Delivered Capability

| Surface | Final local disposition |
|---|---|
| Mode 4 / per_fold_causal / sequential / reset-flat / single symbol | Original-result meta witnesses supported |
| Inprocess and safe Linux fork/COW process | Exact original-pass detached witnesses; existing worker reused |
| Native deadline and active cancellation | Existing cooperative safe points; aborted work cannot publish partial labels/revisions |
| Existing R3B shared-market batch witness | Qualified private primitive; unchanged streaming scalar scores |
| Public meta batch/global | Still rejected; not enabled or called sequential TPE |
| Cross-fold account/order/strategy carry | Versioned proposal, independent expected values, negative preflight tests only |
| Shared-account multi-symbol/asynchronous W3 | Versioned proposal, independent expected values, negative preflight tests only |

The public endpoint and supported methodology names are unchanged. Process
transport is opt-in through the existing runtime config, not a new financial
engine. Arbitrary user strategy callbacks remain Python-owned. Fork/COW requires
a Linux parent with one kernel thread before fork; threaded services/notebooks
must use inprocess or start a dedicated constrained process.

## Correctness And Ownership

`ReactiveWitnessBindingV1` identifies the full task, effective params, candidate,
fold/stage/window/history bounds, seed, market, exact calendar, economics and
metric. `DetachedReactiveWitnessV1` carries unchanged native scalar objectives
and an authoritative `MetricObservation` reduced from the **original native
account result**, not reconstructed from summary Sharpe and not replayed.

Original witness status, support, raw Sharpe/std, first mark, output reference
and hashes remain exact. Worker generation and request ID are checked before
capture. Missing, duplicate, stale, wrong-binding or corrupt packets fail closed.
The seal detects trusted-local transport corruption, not hostile authentication.
No market arrays, financial paths, strategy, account or history/model objects
are serialized per task. Native mutable strategy/account state stays candidate-
local; forward observation isolates RNG within the worker as well as the parent.
Unseeded arbitrary callbacks are not promised cross-process reproducibility:
CPython reseeds global `random` on fork; user `reset(seed, task)` remains required.

Actual tests compare full pools, objective values, anchors, candidate observations
and selected parameters. They exercise an active meta winner that genuinely
changes the applied candidate, not only active metadata. Original financial
paths reconcile exactly across batch/single execution: equity, accepted units,
fees, funding, turnover, initial and maintenance margin. Future-only mutations
cannot alter earlier permitted decisions or witness families.

Observer cancel/deadline now propagates an abort instead of publishing an
incomplete outcome panel. Worker death, poison and invalid responses dispose of
the child/channels; explicit retry gets a new generation. Close/reset are tested
for independent state and idempotent cleanup; no child survives the consumer.
Earlier completed history revisions are retained, never rewritten.

### Actual Cancellation Bug

An active R3B cancellation test exposed `RuntimeError: Already mutably borrowed`:
the wrapper tried calling an active PyO3 runner under its mutable execution
borrow. The narrow correction exports the **existing independent atomic tokens**
and acquires them before execution. Cancel/clear operates on those tokens without
borrowing the active runner. Existing reset semantics preserve the same atomic.

Only this additive getter changed Rust source. After removing it, that module
is byte-identical to C02 entry; no fee/funding/margin/lifecycle/matching arithmetic
changed. The native wheel was rebuilt because the binding changed, not because
a Python transport phase warrants financial-engine redevelopment. An older
extension missing the getter explicitly rejects private batch witness retention.

Deadlines are cooperative: checks use existing completed-account-bar safe points
(interval 64 plus terminal checks). They cannot hard-preempt a blocking Python
callback or roll back arbitrary external side effects. Candidate-local batch
errors have no valid witness; whole-call aborts clear every detached witness from
that call, including earlier completed chunks.

## Test And Source Gates

Final broad regression: **618 PASS**, zero failures/errors/skips, **185.72 s**.
It includes all `tests/meta_selection`, Phase 76 W3 and optimization-sampler
tests. Its 50 C02 cases comprise 21 transport, 6 batch, 12 account-contract and
11 exact-source tests. A separate affected native regression has **36 PASS**,
zero failures/errors/skips, **2.10 s**, covering R1, sparse wake/block commands,
scalar retention and existing full-tape/sparse Rust execution. Counts do not sum
earlier staged runs. Declared Optuna experimental warnings are not skipped gates.

| Gate | Actual evidence | Status |
|---|---|---|
| C02-T01 | Strict packet/binding/schema/metric/calendar/generation; corrupt/stale replies | PASS |
| C02-T02 | Inprocess/process off/shadow/active original pools/accounts; actual candidate switch | PASS |
| C02-T03 | Worker observer RNG continuation, isolated state, future mutation/family parity | PASS |
| C02-T04 | Actual native deadline/cancel, observer atomic abort, worker death/recovery/cleanup | PASS |
| C02-T05 | Original R3B paths/scalars/raw witness; local error and whole-call abort | PASS |
| C02-T06 | Global/public batch meta, carry/multi-symbol preflight failures before execution | PASS |
| C02-T07 | Independent carry/shared-account expected values; inactive proposal identifiers | PASS: spec only |
| C02-T08 | Exact source, fresh installed wheel/sdist/example, matched cost and hygiene | PASS: local |

`tools/qms_c02_source_guard.py` requires exact reviewed Python adapter bytes,
not a blanket file allowlist. Negative tests prove that even an extra arithmetic
or comment change in an allowed module fails. Rust permits exactly the token
getter, nothing else. Original guide SHA-256 remains:
`adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d`.
Dependencies, product contracts, release identities, Ridge and samplers are
unchanged. Historical financial source gates normalize only these exact reviewed
adapters; old artifact receipts still verify against their sealed source. A
fresh supplied receipt must match current source. Historical PASS is not reused
as proof for new bytes.

Canonical layout, public API inventory, module architecture, generated native/
product contracts, documentation links, benchmark governance, Ruff, whitespace
and tracked-secret checks PASS.

## Local Installed Artifact Proof

Fresh canonical core wheel/sdist members match `src/quantbt` byte for byte and
pass artifact allowlists. A new consumer environment installs cached dependency
wheels **offline**, then runs `python -I` from a separate directory with verified
`site-packages` origins, not source imports. Both core-wheel and core-sdist lanes
exercise exact off/shadow/active process/inprocess objectives, candidate witnesses
and selected financial account results. The installed runnable process example
also passes. Supplemental scalar consumer proof passes all four sampler recipes
and actual Rust transform/Gram-solve/rank with original prepared witness parity.

Local native scope is **CPython 3.12, Linux x86_64, manylinux_2_34 build tag**.
This is not Ubuntu 22.04/24.04 x CPython 3.11-3.13 or manylinux2014/public-index
certification. Research/pool-alpha environments were not replaced.

| Receipt/artifact | SHA-256 |
|---|---|
| `.maturin/qms08/c02-review/regression-v3.xml` | `62331d48df312ea251d2f7f872b5dcbc42bf0654d499f17310b27bb5d8a4c346` |
| `.maturin/qms08/c02-review/native-regression.xml` | `96b1bba8c3f26507f47f9b66d88d61b88e8de2aa429e571f42643b8c70c52479` |
| `.maturin/qms08/c02-package-v3/proof.json` | `b80350b2053e03fe6af06bb316a9ceccd1d24891851fd7e6d2d86e329aed09a9` |
| Core wheel `1.1.2` | `130f5cb4fff07469c71861f9e4d162af35c1d7e7170820265036b72ecc88dc3a` |
| Core sdist `1.1.2` | `25ff01c48b28a40f9db3f89959df3dbdc94df572f538d3f6990e918c1983a539` |
| Native wheel `0.4.3` | `20a9a5116470ad0f385bdfe4ec902ea43ba580a6cdb208920caffda4b8d4ba7a` |

Builds/logs/receipts remain under ignored `.maturin/qms08`; no alpha/data or
environment enters distributions. Core/native version strings alone do not
certify source equality.

## Matched Transport Cost

The [structured receipt](../../benchmarks/optimization/meta_selection/qms_c02_transport.json)
binds source `2b9f05a` and the tested native extension hash. This is a small
**synthetic transport fixture**, not a representative alpha speed/decay study:
180 daily bars, 4 folds, 8 attempted trials/fold, 2 IS subperiods, two directions,
shadow meta, reset-flat account, reference meta numerics. Native financial
execution is real. Three paired warm repeats exclude startup/JIT warm-up.

| Lane | Median whole-call time | Verified packets | Market IPC / task | Financial replays |
|---|---:|---:|---:|---:|
| Inprocess | 0.934988 s | 40 | 0 bytes | 0 |
| Safe process | 1.444536 s | 40 | 0 bytes | 0 |

Same complete objective/account/witness fingerprint in every run. Each has
1,260 score-bar visits and 8 observer attempts with zero observer failures.
Process is **54.50% slower** on this small workload; it buys isolation/control,
not acceleration. It remains opt-in. This is not a before/after claim for the
prior inprocess implementation, or proof of acceleration on large strategies.

Maximum witness packet is **1,594 UTF-8 JSON bytes**; this deliberately excludes
the actual pipe envelope. Original result paths are temporarily retained within
the native window for reduction, then released; zero financial-path IPC is not
a scalar-only/no-allocation claim. Batch scratch is bounded per native chunk
(1..64 candidates), then reduced to detached observations.

Parent same-process high-water RSS is **250.37 MiB**, not fresh-process memory.
Last worker snapshot: RSS **164.68 MiB**, PSS **89.86 MiB**, private **18.89 MiB**.
Across three repeats, worker private snapshots span **16.76..67.08 MiB** and
PSS **87.98..113.93 MiB**. These are sampled values, not lifetime peaks, leak
plateau or a promised RSS improvement. COW/shared RSS must not be summed as
unique physical memory. No general memory-speed marketing claim follows.

## Reproduce

Use constrained threads and a fresh output directory; do not overwrite sealed
evidence. The original numeric-test extension remains a historical fixture;
actual W3 financial execution uses the newly installed native wheel.

```bash
export PYTHONPATH=src:.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export MPLCONFIGDIR=/tmp UV_CACHE_DIR=/tmp/quantbt-uv-cache
export QMS04_NATIVE_EXTENSION="$PWD/.maturin/qms04/_quantbt_native.cpython-312-x86_64-linux-gnu.so"
PY=.maturin/qms08/release-regression-v1/bin/python
"$PY" -m pytest -q tests/meta_selection tests/test_phase76_reactive_wfo.py \
  tests/test_optimization_samplers.py
"$PY" -m tools.qms_c02_evidence --output /tmp/qms-c02-cost-fresh.json
"$PY" -m tools.qms_c02_package --output "$PWD/.maturin/qms08/c02-package-fresh" \
  --build-python "$PWD/.maturin/qms08/release-1.1.2-v2/cp312/build-env/bin/python" --python "$PY" \
  --native-wheel "$PWD/.maturin/qms08/c02-native-dist/quantbt_native-0.4.3-cp312-cp312-manylinux_2_34_x86_64.whl"
```

## Remaining Ledger

**No approved local C02 transport gate remains open.** These are explicit next
scope/qualification decisions, not activated capabilities:

- Current-source six-row remote qualification must include the new installed
  `--witness-transport` consumer. Old remote `0970d55` PASS predates C02 and cannot
  qualify the new binding/adapter bytes. No remote push occurred in this phase.
- Public native-first release of the approved pair and public consumer proof
  remain pending owner approval. Local cached installs are not public resolver proof.
- Carry/multi-symbol require approved snapshots, parameter-transition and shared
  financial authority plus uninterrupted-run accounting parity before activation.
- Public meta batches require methodology/scheduler approval and C03 recipe
  qualification. Private witness parity does not enable a per-fold batch optimizer.
- C01 additional-mode activation and **C01-D01** Mode 2 final-selection metadata
  correction are still separate decisions; C02 changes neither.
- C03 four-recipe scheduler qualification, C04 persisted exact Optuna continuation,
  C05 conditional Sobol/admissible centroid remain planning-only.
- Deadline hard preemption, hostile worker authentication and unseeded arbitrary
  callback equivalence are not promised by the cooperative local protocol.

The previous Delta/Gradient RSI effectiveness study remains unchanged. Transport
parity does not improve labels, authorize retuning or show economic superiority.

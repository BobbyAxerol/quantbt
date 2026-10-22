# QMS Phase Report - QMS-05

## Scope And Status

2026-10-04, branch `feat/meta-selection-samplers`, entry `0be25c7`.
Only the approved [QMS-05 plan](../../upgrade/implement.md#qms-05) and linked
[detailed guide](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#qms-05--gắn-vào-actual-mode-4-per_fold_causal)
were implemented. Canonical source stays `src/quantbt`; financial kernels,
metric formulas, sampler factory, published versions and user alphas are unchanged.
Installed core/native remain `1.1.1` / `0.4.2`.

Functional implementation COMPLETE; five technical gates PASS; empirical
NOT_ASSESSED; performance MEASURED_COST_ONLY; owner acceptance PENDING.
No push, merge, publication or QMS-06 advancement is authorized by this receipt.

Local coherent commits: `ec73f43` public hook, `980cec6` causal/native/account
locks, `b6e8bfd` actual policy lineage and executable consumer/evidence tooling.
The final documentation/evidence commit is separately visible in branch history.

## Delivered

- Strict versioned static config and keyword-only runtime `meta_history` binding
  at the existing public backtest/engine boundary. Runtime handles do not enter
  serialized configs. Off/omitted does no archive, auxiliary or extra RNG work.
- Preflight Mode-4/per-fold-causal, scalar endpoint original-result witnesses,
  exact aware calendar, isolated lifecycle and carry-position accounting.
  Unsupported modes/routes/prepared requests fail before Optuna/evaluation.
- Freeze compatible authorized history before search. Capture the full eligible
  current IS pool before compaction, including an exact evaluated centroid
  anchor where needed. No current OOS candidate evaluation is used for selection.
- Fit the existing QMS-04 learner and guard the entire pool. Active winner
  really feeds `params_by_fold`, OOS strategy and the original account. A lower-IS
  learned winner is not overwritten by a later native floor. Shadow executes
  the exact native choice and keeps native objectives/financial results.
- Distinct raw-best/native/proposed/actual identities, params, scores, snapshot,
  models and clocks. Active learned same-anchor still reports past-forward usage;
  cold/invalid-metric fallback does not. Native raw trial/candidate tables remain
  native; inference predictions belong to the research sidecar. Active fold
  selection/best-trial metadata separates native and actual information claims.
- Post-seal frozen-panel observer reuses isolated strategies and fresh original
  endpoint accounts. Global NumPy/Python RNG state is restored for both observer
  and centroid acquisition. Terminal failures/no variance are not fake labels.
  Immutable complete revisions enter only later available as-of snapshots.
- Measured historical-replay completion and separate wall generation, explicit
  clock fixture, readiness fail without backdating/target shifts. No observed-live
  or broker-order claim. Final authority remains one continuous stitched target
  account, not concatenated counterfactual reset equities.
- Executable public SMA example, full integration/methodology/endpoint docs,
  discovery map and source/JUnit/native-candidate-pinned evidence.

See [INTEGRATION.md](INTEGRATION.md) for exact calls, config defaults and errors.

## Tests And Gates

[Executed JUnit](../../benchmarks/optimization/meta_selection/qms05_tests.xml):
**392 passed, zero failures/errors/skips**, 104.77 s, including **40 Q5 checks** and 352
prior/affected checks. Native cases execute the actual compiled QMS-04 candidate,
not a fake module or a missing-capability skip. Optuna's 69 warnings are exposed
experimental-feature notices, not hidden failures.

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
QMS04_NATIVE_EXTENSION="$PWD/.maturin/qms04/_quantbt_native.cpython-312-x86_64-linux-gnu.so" \
.venv/bin/python -m pytest -q tests/meta_selection \
  tests/test_optimization_core.py tests/test_optimization_samplers.py \
  tests/test_optimization_integration.py tests/test_optimization_phase33b.py \
  tests/test_phase49a_walkforward_schedules.py \
  tests/test_phase50_nested_mode1_causal.py \
  tests/test_phase74_public_wfo_native.py tests/test_perf_06_research_audit.py \
  --junitxml=benchmarks/optimization/meta_selection/qms05_tests.xml
```

| Gate | Executed proof | Result |
|---|---|---|
| G5-ENDPOINT | Actual existing endpoint, strict config/history, all Q5 groups, result consumer and runnable example | PASS |
| G5-MODE4_CAUSAL | Actual strategy-frontier spy, future-data/late-label mutations, 00:00/00:08/00:09/00:15 replay fixture, truthful active/same-anchor/fallback scopes | PASS |
| G5-LEGACY | Off/shadow raw search/params/RNG/account parity, centroid acquisition isolation, conditional sampler bridge and affected modes/schedules | PASS |
| G5-ACTUAL_SELECTION | Actual fitted lower-IS switch goes into final params/OOS/account, full pool, no native overwrite, raw/native/meta/actual lineage | PASS |
| G5-OBSERVATION | Original financial outcomes, isolated reset accounts, immutable publication, unavailable revisions excluded, no-variance disposition and actual later support | PASS |
| G5-OWNER | No acceptance decision invented | PENDING |

Q5-T01..08 counts are **1 / 4 / 1 / 1 / 20 / 5 / 2 / 6**.
The [receipt](../../benchmarks/optimization/meta_selection/qms05_gate_receipt.json)
pins [public evidence](../../benchmarks/optimization/meta_selection/qms05_public_evidence.json),
source hashes, JUnit and actual candidate binary. Older QMS-01..04 receipts remain
immutable historical snapshots, not regenerated against QMS-05 source.

Focused lint, canonical-source, module ownership/import, docs-link and benchmark
governance gates are separate. No full-repository suite, fresh installed wheel,
remote CI matrix or real-market economic superiority claim is made here.

## Actual Public Evidence

Existing public SMA rule, synthetic 850 daily bars, six quarterly folds,
six attempted trials per study, seed 731, one worker, same economic contract.
Support minimum one is an explicit engineering override; real default stays 12.
One warm-up precedes five single full-public timing samples. These are added-work
measurements, not statistical performance acceptance or kernel timing.

Off/shadow/shadow-observer produce exactly the same search/selected params,
equity, returns and positions. The 32 observer evaluations finish without failure
in each observer-enabled run. Four original-history models and four learned
decisions execute in active; this particular market fixture keeps the native
anchor. It is not falsely described as an improved or switched market result.
Independent reviewed synthetic fixtures Q5-T03/T04 prove actual switching with
fitted Ridge, without patching model coefficients or pretending to prove edge.

Whole-public native/reference active runs have identical search, fold params and
account signatures. Rust transform/Gram-solve/rank is genuinely called through
the private candidate, and complete reference decision verification is charged.
The same installed 0.4.2 financial baseline remains untouched; no rebuild was
needed in QMS-05, no numeric-only candidate was advertised as a public release.

Exact total/snapshot/fit/observer costs and cumulative RSS are retained in the
evidence. Added meta acquisition, fitting and observer work makes these small
public runs more expensive than off. No whole-WFO speedup or isolated RSS saving
is claimed. Prepared scorer qualification and measured numeric optimization
remain the separately registered QMS-06 and QMS-07 work.

| Full public workload | Total | Fit/select work | Observer work |
|---|---:|---:|---:|
| Off | 0.783 s | 0 | 0 |
| Shadow, no label acquisition | 1.296 s | 0.014 s | 0 |
| Shadow with observer | 2.794 s | 0.953 s | 0.502 s |
| Active reference with observer | 2.916 s | 0.982 s | 0.538 s |
| Active Rust candidate with observer | 2.724 s | 0.889 s | 0.494 s |

Totals also include native search, original-result witnesses and final account.
One sample per workload cannot establish a Rust performance gain; the workloads
with an observer deliberately perform more work. Same-process peak RSS is
**294.25 MiB**, cumulative imports/JIT/runs, not isolated retained memory savings.

Reproduce after building the QMS-04 private candidate:

```bash
env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python -m tools.qms05_public \
  --extension .maturin/qms04/_quantbt_native.cpython-312-x86_64-linux-gnu.so \
  --junit benchmarks/optimization/meta_selection/qms05_tests.xml
# Verify the captured source/JUnit/candidate without rerunning studies:
.venv/bin/python -m tools.qms05_public \
  --extension .maturin/qms04/_quantbt_native.cpython-312-x86_64-linux-gnu.so \
  --junit benchmarks/optimization/meta_selection/qms05_tests.xml --check
```

## Remaining Scope

No missing functional block remains in this registered QMS-05 route. QMS-06
prepared/reference/reactive qualification and portable host handoff, QMS-07
numeric resource optimization and QMS-08 economic/installed-package qualification
are explicit future phases, not functionality silently delivered here.
Strategy feature causality, arbitrary hidden callback state and genuine live
readiness remain caller/protocol responsibilities, not guarantees inferred
from the meta-enabled flag.

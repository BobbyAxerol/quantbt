# Native Measurement Contract V1

The Phase 72 measurement contract makes native-performance evidence
reproducible and route-specific. It does not change execution, fills, account
state, selection mathematics, or public endpoint semantics.

The machine-readable source is
[`phase72_measurement_contract_v1.json`](../../benchmarks/native_event/manifests/phase72_measurement_contract_v1.json).
It inventories each public route, its planner, its native entry point, result
adapter, current authority, owner phase, fixture, and source-code anchors.
This prevents a helper or an explicit companion runtime from being described as
Rust authority for a broader public endpoint.

## Work Denominator

For candidate/fold/scenario workloads, the execution denominator is:

```text
actual candidate-test-bar visits
```

not supplied tape bars multiplied by every candidate and fold. Training bars
may be present for causal feature preparation, but they are not simulated by a
fresh OOS account unless the runtime actually visits them. The counter record
therefore reports separately:

- supplied market bars and warmup visits;
- each half-open executor test window;
- planned/executed/skipped/early-terminated candidate-fold-scenario tasks;
- actual bar and symbol-bar visits; and
- logical full-tape input volume, explicitly labelled as non-execution work.

Early termination or pruning requires an observed executor counter; the helper
will not fabricate a full-window denominator. Score, compact, and audit are
compared only against the same retention profile and accounting/metric
contract.

## Identity And Evidence

Every current measurement records commit, dirty-tree fingerprint, canonical
source tree hash, product/lifecycle registry hashes, wheel/module hash,
protocol/API identity, Python/OS/CPU/thread settings, warmup declaration, and
typed data/intent hashes. A current evidence record must also show matching
parity, comparator profile, timing contract, RSS policy, and measured limits.

Automatic routing additionally requires a clean candidate tree, an immutable
benchmark-artifact hash, a compiled native-module hash, and matching Python /
Rust values for timing scope, result contract, metric contract, annualization,
fee contract, and account contract. The runtime repeats a compact structural
check before routing; CI verifies the complete artifact-level contract. A
hand-edited `pass` flag therefore cannot promote a route.

Historical manifests remain immutable. Their original duration and logical
input-volume metric are preserved, but they carry
`historical_scope_only` status and can never enable automatic Rust routing.
Only `current_candidate_verified` evidence can enable a promotion rule.

## Corrected Historical Interpretation

The Phase 65 fixture has 64 candidates and four OOS windows totaling 3,414
test bars on a 4,096-bar tape. Its preserved 232.514 ms raw duration therefore
corresponds to approximately **0.94M actual candidate-test-bar visits/s**;
the former 4.51M number is retained only as logical full-tape input-volume/s.

The Phase 71 warm soak has 32 candidates over the same 3,414 test bars. Its
preserved 13.325 ms duration corresponds to approximately **8.20M actual
candidate-test-bar visits/s**; the former 39.35M number is logical
input-volume/s. Neither number is a generic `walk_forward(...)` throughput
claim.

## Reproduce

```bash
PYTHONPATH=src .venv/bin/python tools/check_benchmark_governance.py
PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_phase65_native_wfo.py \
  --bars 4096 --candidates 64 --folds 4 --workers 2 --repeats 3
PYTHONPATH=src .venv/bin/python benchmarks/native_event/benchmark_phase71_runtime_soak.py \
  --bars 4096 --candidates 32 --repeats 30 --workers 2
```

Use a temporary output path for exploratory runs. Do not overwrite committed
historical JSON merely to attach a newer source fingerprint. Phase 77 owns a
fresh complete matrix and any future automatic-promotion decision.

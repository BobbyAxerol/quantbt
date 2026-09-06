# PERF-07 Performance Closure

## Purpose

PERF-07 is the pre-Phase-78 release handoff for the V1.1 performance work. It
does not publish a wheel, blanket-enable Rust, or replace the independent
Python/Numba oracle. It binds one clean source candidate to immutable evidence
for the combined public workload, affected-domain regression, portable build
decision, clean installed core/native pair, and route-specific rollback.

The validated handoff is
[`perf_07_performance_closure.json`](../../benchmarks/native_event/results/perf_07_performance_closure.json).
It uses `quantbt.performance_closure.v1` and fails closed when an evidence
checksum, canonical source fingerprint, native extension, wheel pair, AP/AC
disposition, or route declaration changes.

## Qualified Candidate

The standard qualification ran on clean source commit `2701193` and recorded a
separate clean closure identity at `73a262f`. The latter contains committed
evidence artifacts only; the canonical Python/Rust source fingerprint is the
same for both. The source identity records CPython 3.12.13, Linux x86_64,
`quantbt-engine==1.1.0`, and `quantbt-native==0.4.1` with native API `0.4`.

The combined matrix took `87.516 s` wall time. That is a test-suite duration,
not a backtest throughput claim. It deliberately keeps each constituent route's
work denominator, result retention, timing, and RSS scope separate.

| Check | Result |
|---|---|
| Observer economics | exact public parity |
| Session reset/reuse | completed owned Rust corpus |
| Reactive Python/Rust boundary | six isolated boundary cases completed |
| Lifecycle matcher | score/audit terminal parity |
| Five WFO modes, execution reuse | exact public parity |
| Five WFO modes, research sidecar | exact public parity |
| Typed direct target | exact accounting parity |
| Reactive cross-domain controls | all declared controls pass |
| Aggregate speedup claim | intentionally prohibited |

The same-process combined process rose from `158.262 MiB` to `305.062 MiB`.
That is a suite-level peak while multiple runtimes coexist, not a Rust RSS
claim or a steady-state limit. Use the route-specific artifacts for those
measurements.

## WFO And Audit Behavior

The standard fixture exercises all five WFO modes with the same public
contracts. Exact terminal-score reuse activated for Modes 1, 3, and 4, then
released its bounded cache at teardown. It remained intentionally disabled for
Mode 2 because its deterministic bootstrap path has its own retained return
contract, and for Mode 5 because it has no exact post-study replay to reuse.
No adaptive Optuna trial reads from the cache.

Full research retention was measured as a transparency cost, not called a
speedup. The full-ledger overhead was `+31.22%` for Mode 1, `+8.24%` for Mode
2, `+16.01%` for Mode 3, `+48.72%` for Mode 4, and `+38.95%` for Mode 5. All
five retained their public positions, equity, selected parameters, and tables.
See [PERF-05 WFO reuse](perf_05_wfo_evaluation_reuse.md) and
[PERF-06 research audit](perf_06_research_audit.md) for the retention and
Optuna-safety contracts.

## Regression, Build, And Wheel Evidence

The affected-domain matrix ran 195 tests across execution clock, accounting,
funding, lifecycle, target, portfolio, bounded package, intrabar, reactive
WFO, options containment, and arbitrage containment. Two pre-existing fixture
warnings explicitly state that missing high/low input falls back to close and
does not certify intrabar risk; they are not suppressed or treated as a pass
for that uncertified input shape.

The portable release profile remains `opt-level=3`, thin LTO, one codegen unit,
and no `target-cpu=native`, fast math, panic/safety relaxation, or changed
financial capability. `llvm-profdata` was unavailable on the qualification
host, so the explicit PGO disposition is `NOT_BENEFICIAL`: no reproducible
profile merge or host-specific PGO wheel was selected. This is a deliberate
portable release policy, not a claim that PGO was measured faster or slower.

The candidate wheel proof built a core wheel, sdist, and manylinux native wheel
from the pinned source, then used clean environments outside the checkout. It
verified source hashes, the exact `1.1.0` / `0.4.1` pair, source-tree import
blocking, and a public direct-target Rust smoke after wheel installation.

## Certified Route Matrix

| Route | State | Boundary |
|---|---|---|
| Static orders and bounded Native Strategy IR | explicit support | typed static request |
| Prepared static/IR WFO and `%_equity` transition WFO | explicit support | declared prepared scalar scorer |
| Typed direct targets | explicit support | same-close V2 target contract |
| Bounded shared-account portfolio | explicit support | declared target/admission policy |
| Bounded package scenario execution | explicit support | same-account package policy |
| One-symbol Rust intrabar | explicit support | typed bracket contract |
| Arbitrary Python WFO callback | safe baseline | Python decision/orchestration remains authority |
| Arbitrary reactive Python strategy | safe baseline | explicit R1/R2/R3/W3 schedule only |
| Options | safe baseline | Python options engine |
| Cross-venue, multi-currency, inverse/quanto package | rejected | no nearest-specialization fallback |

`explicit support` means the listed bounded contract can be selected explicitly;
it does not mean `backend="auto"` has changed or that a nearby endpoint inherits
native authority. Phase 78 must preserve this matrix or regenerate the closure.

## Reproduction And Rollback

From a clean checkout with the native build toolchain:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=src .venv/bin/python \
  benchmarks/native_event/benchmark_perf07_combined_qualification.py \
  --profile standard

MPLCONFIGDIR=/tmp PYTHONPATH=src .venv/bin/python \
  tools/run_perf07_cross_domain_regression.py

MPLCONFIGDIR=/tmp PYTHONPATH=src .venv/bin/python \
  tools/run_perf07_pgo_experiment.py

MPLCONFIGDIR=/tmp PYTHONPATH=src .venv/bin/python \
  tools/build_perf07_candidate_wheel.py

MPLCONFIGDIR=/tmp PYTHONPATH=src .venv/bin/python \
  tools/generate_perf07_closure.py
```

If a certified explicit route regresses, disable that explicit selection and
rerun the same contract-compatible Python/Numba baseline. Never recreate an
audit from reconstructed positions, equity, or costs. A stale closure is not
valid evidence after a source, wheel, ABI, contract, or route-matrix change.

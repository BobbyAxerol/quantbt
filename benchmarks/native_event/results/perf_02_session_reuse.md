# PERF-02 Session Reuse Evidence

This evidence measures the native `NativeExecutionRunnerV1` reset path with a
four-bar, one-symbol command-tape fixture. It is deliberately separate from a
public endpoint, reactive strategy, Optuna, or WFO benchmark.

## Fixture

- Release build of `quantbt-execution`.
- One small deterministic market-order tape.
- `100,000`-order predecessor cases.
- Five release samples in the committed initial measurement.

The fixture separates two semantically different high-water cases:

1. A terminal market-order predecessor has no live arena slots at reset, so the
   arena may clear without scanning inactive historical slots.
2. A passive limit-order predecessor has `100,000` live orders. Reset must
   visit and cancel them; an O(1) clear here would leak lifecycle state.

## Committed Result

Source: [`perf_02_session_reuse.json`](perf_02_session_reuse.json).

| Measurement | Median |
| --- | ---: |
| Fresh small run | 23.142 us |
| Reused small run | 23.788 us |
| Reset after normal small run | 0.202 us |
| Reset after terminal 100k-order predecessor | 1.688 us |
| Reset after live 100k-order predecessor | 5.094 ms |

The process RSS rose from `21.004 MiB` to `66.884 MiB` while deliberately
holding a `100,000` live-order arena. This is a bounded live-order allocation
fact, not a generic steady-state RSS claim. The example records this distinction
in its result contract and does not market the terminal fast path as an
optimization for active orders.

## Reproduction

```bash
cargo run --manifest-path rust/Cargo.toml -p quantbt-execution --release \
  --example perf02_session_reuse -- \
  --outlier-orders 100000 --repeats 5 \
  --output benchmarks/native_event/results/perf_02_session_reuse.json
```

For promotion-grade evidence, increase the repeat count, capture host/toolchain
metadata beside the artifact, and retain the fresh/reuse output parity corpus.

# Benchmarking Governance

Run a benchmark only after the corresponding parity gate is green. The release
question is not “which implementation is faster?” but “which implementation
produces the same declared accounting and trace under a declared workload?”.

## Current Release Evidence

The governed pair is `quantbt-engine==1.1.0` and
`quantbt-native==0.4.1`. The current committed evidence reports:

| Workload | Rust median | Throughput | Python oracle | Parity gate |
|---|---:|---:|---:|---|
| Native Strategy IR score, 2,000 bars | 0.741 ms | 2.70M bars/s | 31.565 ms | exact trace/accounting |
| Native Strategy IR batch, 64 x 2,000 bars | 11.379 ms | 11.25M bars/s | n/a | exact serial/batch |
| Native Strategy IR causal fold, 64,000 bars | 7.386 ms | 8.67M bars/s | n/a | exact fold isolation |
| Portfolio target-units score, 2,000 bars x 8 symbols | 3.594 ms | 556,551 bars/s | 33.493 ms | exact at `1e-12` |
| Atomic package score, 2,000 bars x 8 symbols | 3.512 ms | 569,514 bars/s | 19.735 ms | exact at `1e-12` |

The IR score is 42.6x faster than its Python oracle on this fixture. The
bounded portfolio and package score paths are 9.3x and 5.6x faster. These
ratios are derived from same-fixture medians; they are not comparisons with
external frameworks or guarantees for a full report facade.

Primary evidence:

- [`phase54b2/public_routes.json`](../../benchmarks/native_event/results/phase54b2/public_routes.json)
- [`phase54b2/public_routes.md`](../../benchmarks/native_event/results/phase54b2/public_routes.md)
- [`phase54b3/portfolio_package.json`](../../benchmarks/native_event/results/phase54b3/portfolio_package.json)

Static public compact and audit routes are reported even when Rust is not
faster. Their shared Python preparation/report work can dominate sparse command
tapes. This is why backend promotion is a capability and correctness decision,
not a blanket speed promise.

## Required controls

1. Use the same deterministic fixture for compared routes.
2. Record event-clock contract, profile, warm/cold separation, and worker count.
3. Require exact accounting/trace parity before comparing throughput.
4. Record median and robust spread, not only a best sample.
5. Capture peak/incremental RSS using a documented method.
6. Version the baseline with its source commit, lockfile, Python/Rust toolchain,
   CPU/OS metadata, and fixture fingerprint.

## Commands

```bash
make bench-smoke
make bench-native
make bench-facade
```

The committed E0/E3/E6 evidence is historical and workload-scoped. It does not
authorize backend promotion. Promotion requires clean staged wheels, compatible
native package evidence, a threshold owned by the workload manifest, and an
emergency Python rollback route.

The scheduled `Native Nightly Regression Evidence` workflow regenerates E0,
E3, E6, and prepared-score RSS artifacts on one declared CI host. It is an
observability tier, not a hardware-normalized release threshold: its artifacts
can detect a material regression, but they cannot promote `backend="auto"`.

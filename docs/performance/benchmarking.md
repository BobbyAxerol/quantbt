# Benchmarking Governance

Run a benchmark only after the corresponding parity gate is green. The release
question is not “which implementation is faster?” but “which implementation
produces the same declared accounting and trace under a declared workload?”.

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

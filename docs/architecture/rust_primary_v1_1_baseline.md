# Rust-Primary V1.1 Baseline

Phase 56 freezes the factual starting point for the Rust-primary V1.1 program.
It changes no endpoint behavior, timing contract, accounting calculation, or
backend auto-routing decision. Its purpose is to make every later promotion
testable against a reproducible source and installed-wheel baseline.

## Read The Baseline

- [Endpoint and capability inventory](../generated/v1_1_endpoint_inventory.md):
  current authority per public endpoint and governed native workload.
- [Baseline corpus](../generated/v1_1_corpus_manifest.md): representative
  fixtures, historical evidence hashes, trace availability, and known limits.
- [Measurement contract](../generated/v1_1_measurement_contract.md): common
  timing, boundary, copy, allocation, and RSS field definitions.
- [ADR index](../adr/README.md): Rust authority, strategy boundary, correctness,
  runtime-class, and WFO schedule decisions.

The JSON artifacts are the machine-readable authority. Generated Markdown is a
reader for those artifacts. `null` in a historical measurement means that the
older artifact did not record a field; it never means a measured zero.

`v1_1_installed_wheel_baseline.json` is immutable evidence for the released
1.1.0 core/native pair. Its source hashes are intentionally pinned to that
historical revision; later V1.1 development must not rewrite the record merely
to match the working tree. A later release gate creates a separate fresh-wheel
certificate and verifies current source/artifact parity in a clean environment.

## Regenerate And Check

Run from the repository root:

```bash
poetry run python tools/generate_v1_1_baseline.py
poetry run python tools/generate_v1_1_baseline.py --check
```

The generator uses AST coverage of every `QuantBTEndpoint` classmethod,
governed product/lifecycle registries, current package versions, and hash-pinned
evidence. It fails if a public factory has no V1.1 row or a listed evidence
artifact is absent.

## Installed-Wheel Evidence

The clean-wheel record is intentionally separate because it depends on the
staged artifacts and the local Python/platform pair:

```bash
poetry run python tools/capture_v1_1_installed_wheel_baseline.py \
  --dist dist/staged \
  --output benchmarks/baselines/v1_1_installed_wheel_baseline.json
```

It delegates to the existing release certifier, which creates fresh virtual
environments with repository `PYTHONPATH` and active Poetry/Conda variables
removed. The proof records both core-only Python fallback and the exact
core/native pair, including site-packages import paths and capability routing.

## Promotion Discipline

This baseline does not make every endpoint Rust-first. A route becomes eligible
only after the later specification, oracle, canonical-trace, differential,
installed-wheel, RSS, and performance gates documented in the V1.1 guide. An
explicit `backend="rust"` request must fail closed outside a certified contract;
`backend="auto"` must retain an observable Python fallback reason.

## Phase 57 Correctness Foundation

Phase 57 adds the first V1.1 promotion prerequisite without changing a
production route:

- [Execution clock contract](../contracts/v1_1_execution_clock.md) freezes
  first-bar, effective-time, V2/V3, gap, ambiguity, and funding-boundary
  language.
- [Linear accounting contract](../contracts/v1_1_linear_accounting.md)
  defines scale, reduce, reverse, fee, funding, margin preview, and the scope
  boundary for the linear quote-settled model.
- [Canonical Trace V2](../contracts/v1_1_canonical_trace_v2.md) defines the
  typed trace, field-specific comparator, stable serializer, and terminal
  fingerprint needed for later route-by-route promotion.

The machine-readable source is
[`contracts/v1_1_correctness_contract.json`](../../contracts/v1_1_correctness_contract.json).
The independent reference implementations stay under `reference/python`; that
tree is standard-library-only and excluded from the production wheel. Existing
`canonical-execution-trace-v1` output remains unchanged. Its V2 adapter is
explicitly lossy and is evidence for bounded fixtures, not a claim that every
runtime already emits a complete V2 trace.

Run the foundation gate with:

```bash
poetry run make v1_1-phase57-check \
  PYTHON=/root/bobby/pool_alpha/quantbt/.venv/bin/python
```

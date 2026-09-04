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

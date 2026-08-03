# Changelog

All notable changes to `quantbt-engine` are documented here.

## [1.0.7] - Unreleased

This is the first independently installable core package release line.

### Release candidate

- `1.0.7rc1` was blocked before publication because its lockfile version was stale.
- `1.0.7rc2` prepared for TestPyPI on 2026-08-03 with immutable lock validation.
- Python 3.11-3.13 package validation is required before final publication.
- `backend="auto"` remains Python.
- `backend="rust"` remains explicit and experimental.
- `quantbt-native` is not included in this core release.
- Native crate and Python metadata remain aligned to API version `0.4.0`.

### Added

- Stable `from quantbt import QuantBTEndpoint` import contract.
- NumPy/Numba native vectorized, event-driven, portfolio, arbitrage, options,
  intrabar, and walk-forward research routes.
- Optional extras for optimization, reports, visualization, and NautilusTrader
  validation.
- Prepared service contexts and report levels for repeated research workloads.
- Explicit Python/Rust native-event selector contract with Python as the
  release default and Rust as a capability-gated experimental backend.
- Wheel, sdist, clean-install, source-sync, parity, and RSS release gates.

### Release policy

- The core `quantbt-engine` distribution is the release candidate for PyPI.
- `quantbt-native` is not part of this core release and is not exposed through
  a non-empty `native` extra until its wheel matrix and incremental RSS gates
  pass.
- `native_backend="auto"` remains Python; explicit Rust requests never
  silently fall back to Python.

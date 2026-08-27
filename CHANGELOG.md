# Changelog

All notable changes to `quantbt-engine` are documented here.

## [1.0.10] - Unreleased

### Changed

- Prepared the public `quantbt-native==0.4.1` companion contract for the
  next Linux x86_64 release line. The core declares an exact, platform-marked
  dependency for CPython 3.11-3.13; unsupported platforms keep Python/Numba.
- Added a wheel-only manylinux artifact gate. Public publishing remains blocked
  until the Phase 55B TestPyPI/PyPI consumer-install proof completes.

### Compatibility

- No endpoint signature, execution policy, promotion threshold, or domain
  accounting behavior changes in this packaging-only phase.

## [1.0.9] - 2026-08-21

### Added

- Direct PyPI discovery and installation guidance in the repository README.
- Release-preparation guidance for the governed Rust-first routes, exact
  installed-wheel certification, and the matching core/native compatibility
  contract.

### Changed

- Promoted the bounded Rust-first public policy for certified static command
  tapes, Native Strategy IR, batch, and causal-fold workloads while preserving
  Python authority for callbacks, reactive strategies, generic portfolio,
  basket, arbitrage, and options routes.
- Updated the core product registry to the `1.0.9` release line. The staged
  `quantbt-native` companion remains unpublished and capability-gated.

### Verification

- Source-mirror, generated-product-contract, documentation-link, build, and
  installed-wheel release checks are required from the final tagged commit.

## [1.0.8] - 2026-08-12

### Changed

- Added strict nested causal retraining for
  `mode_1_decay + optimization_schedule="per_fold_causal"`. Mode 1 decay now
  uses inner IS-only folds while each outer OOS segment remains untouched until
  its parameters are frozen.
- Added explicit chronological validation metadata so consumers can distinguish
  retrospective global calibration, selection-adjusted OOS, and strict outer
  OOS evaluation without breaking legacy result fields.
- Added a bounded-RSS release test runner that executes deterministic pytest
  shards in fresh processes; CI and publish workflows use the same selection.

### Verification

- Root/source mirror, prepared/reference WFO parity, nested-fold causality,
  and the full non-real-data release suite passed before this version bump.

## [1.0.7] - 2026-08-04

This is the first independently installable core package release line.

### Release candidate

- `1.0.7rc1` was blocked before publication because its lockfile version was stale.
- `1.0.7rc2` prepared for TestPyPI on 2026-08-03 with immutable lock validation.
- `1.0.7rc2` passed clean TestPyPI installation and functional endpoint smoke.
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

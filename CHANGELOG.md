# Changelog

All notable changes to `quantbt-engine` are documented here.

## [Unreleased]

### Prepared 1.2.0 / Native 0.4.3

- Retargeted the unreleased core candidate from1.1.2to1.2.0 to reflect the
  diagnostics, Mode4/Mode5, sampler/meta, reporting and account upgrade below.
  Historical1.1.2receipts retain their original scope; they are not renamed
  release evidence. Native version remains0.4.3; generated product metadata
  follows the new pair, requiring fresh matching native artifacts.
- Reduced full Reporting V1 Python scalar-dispatch and metadata overhead;
  closed-ledger reason counting uses one pass instead of one scan per reason.
  Exact before/after output, snapshot/identity and undefined-policy parity are
  tested. Reporting formulas, financial kernels and WFO selection are unchanged;
  timing gains are workload-specific and do not imply a universal speedup.

- Added opt-in `reporting=ReportingRequest(...)` on completed endpoint/result
  reports and quick plots. Account-period, execution, closed-trade/action and
  drawdown episode output has explicit baseline, frequency, currency, coverage
  and unavailable policies. This opt-in does not alter execution or WFO/meta
  objectives; separate account repairs below intentionally correct financial
  edge cases. Read [Reporting V1](docs/metrics/PUBLIC_REPORTING.md).
- Reduced optional reporting copies and duplicate hashing using immutable
  bytes-owned snapshots, a prepared boolean mask and one report/plot snapshot.
  Cache hits still rehash mutable completed input; formulas, exact identities,
  requested episode detail, legacy reports and financial/WFO metrics are unchanged.
- Fixed immutable reporting snapshot reconstruction after copy/deepcopy and
  pickle, including nested execution paths and drawdown episodes. Constructors
  revalidate storage and recompute hashes; changed observations cannot reuse a
  saved identity. Python reporting scans use zero-copy native scalar access
  with preserved numerical overflow policies and exact differential coverage.

- Added opt-in Mode 4 / per-fold causal meta selection and a shared sampler
  bridge for legacy TPE, grouped multivariate TPE, CMA-ES and fixed-space Sobol.
- Qualified causal history, ridge artifacts, reference/prepared selection
  parity, exact reusable calendar/market witnesses, observed thread telemetry
  and bounded sequential W3 meta on the original native accounting pass.
- Enabled the already-qualified QMS native exports in default Cargo builds;
  Linux core dependency is exactly `quantbt-native==0.4.3`. The ABI remains
  versioned; later ACC-01 changes affect both Python and Rust financial source
  and require fresh compatible artifacts. Meta remains disabled unless requested.
- Earlier QMS wheel/sdist, installed-W3 and six-row Ubuntu receipts retain
  their historical source scope. They do not certify the later Mode 5,
  reporting and account repairs. Final M5-12 artifacts, remote qualification
  and public consumers remain separate gates.
- Added diagnostics-first opt-in Mode 5 calibration with versioned objectives,
  selectors, diagnostic evidence/rights, frozen plans, explanation and winner
  qualification. Shared diagnostics/reporting include Mode 4 fold consistency,
  R/Q, decision coverage and explicit cross-mode researcher handoff. No automatic
  sampler/selector router or universal economic improvement is claimed.
- Extended the stable endpoint API additively: optional `execution_endpoint`
  on `walk_forward`, keyword-only `meta_history` on `backtest`, optional
  `reporting` on completed reports/plots, and `research_report(...)`.
- Corrected current-capability account/configuration behavior: financial clocks,
  funding interval coverage, contract multipliers, risk-reducing admission,
  constraints, invalid inputs, actual attribution and reporting horizon/time
  handling. Unsupported non-default options fail explicitly; gross-cross/netting
  is not hedge inventory or isolated liquidation. See
  [ACC-01 migration](docs/portfolio_review/ACC01_CONFIGURATION_AND_MIGRATION.md).
- Refreshed the generated root API inventory to 527 exports (11 additions to
  the stale generated list, no removals), with an exact metadata-only amendment
  that preserves the separate financial source qualification and historical receipts.
- Extracted cold option validation and portfolio report helpers, preserving
  endpoint/private aliases, moved function bodies and retained engine code.
  Exact source qualification is separate from historical financial-invariance
  receipts and still does not certify installed artifacts.
- Added maintained installed-consumer/CI wiring for the prepared Mode 5,
  winner/donor, reporting and account changes. Execution on final wheel/sdist
  artifacts and remote/public qualification remain separate gates.
- Preparation only: no tag, upload, merge or scientific acceptance is implied.
  See [QMS release handoff](docs/meta_selection/RELEASE_HANDOFF.md).

## [1.1.1]

### Changed

- Released the completed statistical WFO follow-up: stationary-bootstrap index
  construction now preserves the existing RNG draw sequence while avoiding
  repeated Python work, and report-metric objectives share one report snapshot
  per evaluation.
- Updated the governed wheel-only companion contract to
  `quantbt-native==0.4.2`; `quantbt-engine==1.1.1` keeps the exact
  platform-marked dependency for supported Linux x86_64 CPython 3.11-3.13
  consumers.

### Compatibility And Verification

- No public endpoint, methodology, selection, accounting, trace, or backend
  promotion policy changed. The release remains native-first: publish the
  complete native wheel matrix before publishing the matching core package.

### Changed

- NEXT-01 reduces generic every-bar and declared sparse callback overhead while
  retaining full financial/audit output and dynamic callback compatibility.
- NEXT-02 reuses immutable WFO market/window preparation and native score
  requests while preserving candidate ordering, selection and fresh accounts.
- NEXT-03 makes `src/quantbt` the sole Python package source; the reviewed
  duplicate root modules are retired. Local developers should use an editable
  install rather than a parent-directory import-path override.
- Research audit exposes objective components and eight record-family links
  while preserving existing public trial/candidate tables and legacy exports.

### Compatibility And Qualification

- Endpoint factory signatures are unchanged across NEXT-01 through NEXT-03.
  Reactive WFO adds optional `preparation_policy="prepared"`; numeric reactive
  minimal output omits diagnostic tables while retaining financial paths.
- Local release shards and isolated wheel/sdist/editable consumer checks pass.
  Publication requires new compatible core/native versions and remote matrix
  certification. Performance claims remain limited to the measured workloads.
- CI and release test checkouts retain Git history for qualification ancestry
  verification; the validator continues to reject unverified source ancestry.

## [1.1.0]

### Changed

- Renamed the governed public release line to `1.1.0` and synchronized package
  metadata, runtime version, generated core/native contracts, lockfile, and
  release documentation.
- Prepared the governed public `quantbt-native==0.4.1` companion contract for
  Linux x86_64 / CPython 3.11-3.13. The core declares an exact,
  platform-marked dependency; unsupported platforms keep Python/Numba.
- Added a native-first, wheel-only manylinux OIDC release workflow and a six-row
  Ubuntu 22.04/24.04 Poetry consumer proof. The core release preflights the
  matching public native artifact before it can publish.
- Kept public release certification self-contained by excluding private,
  out-of-tree Grid integration fixtures from its test shard profile.
- Updated release, install, capability, troubleshooting, and handoff docs to
  state that supported users receive a pre-built wheel rather than compiling
  Rust locally.

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

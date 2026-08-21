# P1 Planning, Preparation, And Backend SPI

## Certified Checkpoint

Phase 52A introduces the first P1 execution boundary for static native-event
lifecycle tapes. Public endpoint signatures and P0 accounting semantics remain
unchanged.

The certified control flow is:

```text
QuantBTEndpoint / BacktestEngineV2
  -> BacktestRequest
  -> immutable ExecutionPlan
  -> one NativeEventPreparation pass
  -> prepared lifecycle execution
  -> P0-compatible BacktestResultV2 adaptation
```

The planning layer resolves report aliases, event clock, workload, strategy
mode, output projection, backend policy, capabilities, numeric policy, and
fingerprints once. `auto` remains Python under the release policy and does not
import `_quantbt_native`. Explicit Rust probes the native semantic descriptor
and fails before market preparation when the wheel is absent or incompatible.

## Immutable Contracts

`BacktestRequest` records user intent. `ExecutionPlan` records only resolved
decisions; no ambiguous `auto` value reaches a prepared engine session. Both
are frozen, slot-based, JSON serializable, and SHA-256 fingerprinted.

`PreparedRun` contains read-only contiguous arrays for timestamps, OHLCV,
funding, instrument constraints, account values, and the compiled lifecycle
command tape. Market, instrument, account, command, plan, and combined
fingerprints make cache identity explicit. Pandas objects are retained only by
the outer compatibility adapter, never by the engine SPI.

`EngineRunRequest` and `RawEngineResult` form the equal Python/Rust contract.
The result uses struct-of-arrays buffers and contains no pandas or report
objects. Python and Rust sessions support `run`, `reset`, and `close` through
the same protocol and consume the same `ExecutionPlan` and `PreparedRun`.

## Output Projection

`OutputRequirements` compiles once per run:

- Internal `score`: scalar counters only; no dense paths, fill rows, event rows,
  command states, or pandas objects.
- Public `score`: preserves the historical `BacktestResultV2` path surface but
  does not retain fill/event detail rows.
- `minimal`: public accounting paths and compact terminal command state.
- `standard`: public paths, fills, compact events, and compact command state.
- `audit`: full lifecycle detail, accounting audit, and canonical trace.

Fill and event counts are accumulated by the engine even when row buffers are
not retained.

## Dependency Rules

- `planning` cannot import endpoint, reporting, pandas, or the native module.
- `engine_spi` cannot import endpoint, reporting, or pandas.
- raw `results` cannot import endpoint, backends, or pandas.
- backend execution cannot construct public reports through the SPI.
- native capability loading is lazy.

These boundaries are enforced by AST and isolated-process import tests.

## Compatibility Scope

Phase 52A routes static `OrderCommand` lifecycle runs through immutable
planning and one-pass preparation. The final public materialization still uses
the P0 report adapter so historical DataFrames, compact ledgers, accounting
audit, and canonical trace stay parity-locked.

Reactive Python callbacks, basket generation, event v1, context projection,
command-writer reuse, Rust authoritative callback state, streaming audit, and
prepared-session cache ownership remain Phase 52B scope. No Phase 52A claim is
made for those paths.

## Evidence

Run the focused source gate:

```bash
poetry run pytest -q tests/native_event/contract
```

Run the installed-wheel gate:

```bash
python tools/certify_phase52a_wheel.py --expected-site /path/to/site-packages
```

The machine-readable evidence is archived in
`docs/contracts/phase52a_certification.json`.

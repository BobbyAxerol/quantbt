# Native Event Dual Backend: Phase 46E

Phase 46E closes the Python/Rust selection and reporting boundary for the
single-symbol explicit-order scope. It does not claim that Rust replaces the
full Python reactive engine.

## Contract

`NativeEventConfig.native_backend` accepts:

| Selector | Contract |
| --- | --- |
| `python` | Full reactive Python implementation. This is the canonical and compatibility backend. |
| `rust` | Explicit, fail-fast Rust batched tape path. Only certified single-symbol static tapes are accepted. |
| `auto` | Python for the current release policy. It does not silently enable an experimental wheel. |
| `replay_certified` | Deterministic audit/replay oracle used for candidate certification. |

The endpoint also accepts `native_backend=...` and passes it through
`BacktestEngineV2` without changing existing endpoint names or defaults.

Example:

```python
bt = QuantBTEndpoint.orders(
    backend="native_event",
    native_backend="rust",
    initial_capital=10_000,
    leverage=5,
    maintenance_ratio=0.0,
    use_funding=False,
    fee_rate=0.0002,
)
result = bt.backtest(data=bars, order_commands=commands, symbols=["BTC"])
```

Rust requests fail before execution when the tape requires unsupported
funding, liquidation, multiple symbols, or quantity constraints. There is no
silent downgrade to Python for an explicit `rust` request.

## Common reporting boundary

`RustBatchedAuditResult.to_backtest_result(...)` converts Rust SoA arrays once
into the common `BacktestResultV2` surface. It provides:

- equity, returns, position, fee, funding and margin paths;
- `fills_report` and `order_report` metadata tables;
- `Fill` objects for report/export compatibility;
- `show_metrics()`, `full_report()`, `quick_plot()` and `tearsheet()` through
  the normal `BacktestResultV2` helpers.

The adapter is intentionally outside the score hot path. Score runs keep
typed scalar fields only; audit runs retain SoA buffers and materialize report
objects only when requested.

## Python hot state

Scalar Python score runs keep the existing public command and context contract.
When a strategy explicitly disables fills, events, active-order snapshots,
positions, margin, ledgers and terminal orders, pending score state drops
non-execution strategy metadata. Parent/OCO/group/tag fields remain because
they affect lifecycle matching. Full audit/default runs retain the complete
metadata and object behavior.

## Release evidence

The reproducible gate is:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=. poetry run python \
  benchmarks/native_event/benchmark_phase46e_release_gate.py
```

Evidence is saved in
[`../benchmarks/native_event/phase46e_release_gate.json`](../benchmarks/native_event/phase46e_release_gate.json).
The current run passed lifecycle/scalar parity, 100-run RSS plateau,
absolute RSS budget, and speed thresholds. The 40% incremental prepared-RSS
reduction gate did not pass: Rust ownership is compact and execution is much
faster, but the prepared native object is not yet 40% smaller than the Python
prepared baseline in this process. Therefore the release policy remains:

```text
Rust: explicit experimental/capability-gated batched backend
auto: Python
native PyPI extra: not released
```

This is a gate result, not a correctness failure or a claim that total process
RSS should fall by 40%; interpreter and package imports dominate that metric.

# Rust Batched Native Event

> Phase 47B adds the API `0.4` `RustFullRunner` contract. Read
> [`native_event_rust_full_contract.md`](native_event_rust_full_contract.md)
> for the current explicit `native_backend="rust"` path. This document
> describes the earlier `RustBatchedRunner` compatibility surface below; it
> remains intentionally single-symbol and fail-fast.

QuantBT includes an explicit, experimental Rust/PyO3 full-tape runner for a
precomputed single-symbol `OrderCommand` tape. It is designed for a static
command sequence produced outside the execution kernel, not for compiling an
arbitrary Python strategy.

## Usage

```python
from quantbt import NativeEventBackend, NativeEventConfig, AccountConfig

backend = NativeEventBackend(
    NativeEventConfig(
        account=AccountConfig(
            initial_capital=10_000,
            leverage=5,
            maintenance_ratio=0.0,
        ),
        fee_rate=0.0002,
        use_funding=False,
    )
)

market = backend.prepare_market_arrays(
    datetime_index=index,
    closes={"BTC": frame["close"]},
    highs={"BTC": frame["high"]},
    lows={"BTC": frame["low"]},
    symbols=["BTC"],
)
compiled = backend.compile_order_commands(index, commands, symbols=["BTC"])
runner = backend.prepare_rust_batched_runner(
    index,
    {"BTC": frame["close"]},
    {"BTC": frame["high"]},
    {"BTC": frame["low"]},
    symbols=["BTC"],
)

score = runner.run_tape_score(compiled)
audit = runner.run_tape_audit(compiled)

# Stateful sparse continuation: no dense equity/position path per chunk.
session = runner.open_sparse_session(compiled)
first = session.run_until(3)
second = session.run_until(len(index) - 1)
```

`score` returns scalars only. `audit` returns contiguous struct-of-arrays
buffers such as `fill_bar`, `fill_price`, `event_kind`, `equity`, and
`positions`. The market preparation is reusable, while each call creates a
fresh mutable session so trials cannot leak order state into one another.

`RustBatchedSession.run_until(stop_bar)` keeps the same Rust order/account
state across consecutive chunks. Each chunk returns scalar accounting plus
contiguous sparse `fill_*`, `event_*`, and `wake_*` arrays. `wake_kind` uses
`0=fill`, `1=order event`, and `2=end of chunk`. No dense bar path is created;
run `run_tape_audit` separately when a full audit ledger is required. The
current sparse contract is still the same certified single-symbol slice as
the full-tape runner: immediate GTC market/limit/stop, cancel/amend/replace,
reduce-only, fee and slippage, without funding, liquidation, quantity rules,
package orders, non-GTC TIF, or multi-symbol state.

## Certified scope

The current Rust slice supports one symbol, immediate GTC market/limit/stop
orders, cancel/amend/replace, reduce-only, fee and slippage. The command tape
must follow the native-event v2 effective-bar contract. Unsupported funding,
liquidation, quantity constraints, OCO/parent packages, expiry, IOC/FOK/GTD,
and multi-symbol input raise explicitly. Use the Python/replay-certified
backend for those semantics.

`auto` never selects this runner, and no public endpoint default changes. The
replay-certified Python/Numba engine remains the domain oracle. Rust can only be
promoted after the isolated benchmark, RSS and installed-wheel gates in
`upgrade/implement.md` Phase 45F pass.

## Phase45F certification evidence

`benchmarks/native_event/benchmark_phase45f_release_gate.py` runs each backend
in a fresh child process, with five measured runs after warm-up. Exact
final-equity/fill-count parity passed. The warmed score-path speedups were
`5.09x` for low churn and `79.06x` for high churn, with repeated RSS plateau
in both backends. Peak RSS reduction was only `18.3%` at the lower scenario,
below the required
`40%` release threshold; the remaining overhead is consistent with Python
prepared arrays coexisting with the Rust-owned prepared market. Rust
therefore remains explicit experimental and `auto` remains Python.

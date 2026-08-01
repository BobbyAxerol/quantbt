# Rust Batched Native Event

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
```

`score` returns scalars only. `audit` returns contiguous struct-of-arrays
buffers such as `fill_bar`, `fill_price`, `event_kind`, `equity`, and
`positions`. The market preparation is reusable, while each call creates a
fresh mutable session so trials cannot leak order state into one another.

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

# Margin And Leverage

QuantBT follows Binance-style futures accounting for notional buying power.

```python
buying_power = current_equity * leverage
initial_margin_required = abs(order_notional) / leverage
maintenance_margin = abs(position_notional) * maintenance_ratio
```

Important rule:

`leverage` does not multiply `alloc_per_trade`.

If the account has `initial_capital=10_000` and `leverage=10`, the initial
buying power is about `100_000`. A strategy can still choose to allocate
`50_000`; leverage only controls required margin and rejection/liquidation
thresholds.

```python
bt = BacktestEngine(
    Datetime=dt,
    Position=signal,
    Close=close,
    initial_capital=10_000,
    leverage=10,
    alloc_per_trade=50_000,
    hedge_type="signal_notional",
)
```

## Fees And Slippage

Legacy `BacktestEngine` expects `fee` as round-trip and halves it internally to
one-way. V2 backends expect `fee_rate` as one-way.

Legacy `slippage` is a fraction:

```python
slippage=0.0001  # 1 bp
```

V2 `ExecutionConfig.slippage_bps` is in basis points:

```python
ExecutionConfig(slippage_bps=1.0)
```

## Liquidation

Intrabar liquidation uses high/low worst-case prices:

- long positions are checked against `Low`;
- short positions are checked against `High`;
- if `High` and `Low` are not provided, close is used as fallback.

For robust crypto intraday backtests, always pass `High` and `Low`.

## Quantity Constraints

Crypto fractional trading is controlled by exchange quantity filters, not by
`contract_size`.

Use:

```python
QuantBTEndpoint.signal_notional(
    contract_size=1.0,   # PnL/notional multiplier for linear USDT contracts
    qty_step=0.001,      # venue lot increment
    min_qty=0.001,
    min_notional=10.0,
)
```

`qty_step`, `lot_size`, and the compatibility alias `slot_size` describe the
same venue quantity increment. QuantBT rounds target/order quantity down before
execution and zeroes orders below `min_qty` or `min_notional`. The same shared
constraint layer is used by legacy single-symbol, native vectorized, native
event/orders, native portfolio, and Nautilus validation routes.

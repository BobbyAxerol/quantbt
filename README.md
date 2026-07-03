# QuantBT

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Numba](https://img.shields.io/badge/core-numba-00A86B)
![Backtesting](https://img.shields.io/badge/backtesting-vectorized%20%7C%20event--driven-black)
![Nautilus](https://img.shields.io/badge/nautilus-optional-6f42c1)

Fast, research-friendly backtesting for crypto and portfolio alphas.

QuantBT gives notebooks and services one stable endpoint over multiple engines:
Numba vectorized simulation for sweeps, event-driven order simulation for fills,
legacy-compatible portfolio modes, and optional NautilusTrader validation.

## Highlights

- Single-symbol signal backtests with margin, leverage, fees, slippage, funding,
  and liquidation checks.
- Structural DCA/grid ladders with high/low limit-touch simulation.
- Native event-driven orders, fills, baskets, and pair trades.
- Multi-symbol portfolio modes: `longshort`, `market_neutral`, `directional`,
  and `equal_weight`.
- Optional Nautilus validation for Binance perpetuals:
  BTC, ETH, BNB, SOL, DOGE, ARB, and LINK.
- Stable result contract with `show_metrics()`, `full_report()`, plots, reports,
  and export helpers.

## Install

```bash
pip install numpy pandas numba matplotlib seaborn
```

Optional Nautilus validation:

```bash
poetry add nautilus-trader
```

## Quick Start

```python
from quantbt import QuantBTEndpoint

bt = QuantBTEndpoint.signal_notional(
    backend="native_vectorized",
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    fee_rate=0.0002,
    slippage_bps=1.0,
    use_funding=False,
)

result = bt.backtest(
    data=df,                    # OHLCV DataFrame
    signal_col="pos_weight",    # 1.0 / -1.0 / 0.0 style signal
    symbols=["ETHUSDT"],
)

result.show_metrics()
bt.quick_plot()
```

## Endpoint Modes

```python
QuantBTEndpoint.pct_equity(...)          # legacy % equity sizing
QuantBTEndpoint.signal_notional(...)     # fixed units between signal changes
QuantBTEndpoint.dca_ladder(...)          # DCA/grid structural levels
QuantBTEndpoint.orders(...)              # explicit OrderIntent simulation
QuantBTEndpoint.basket(...)              # pair/basket event simulation
QuantBTEndpoint.portfolio(...)           # multi-symbol portfolio matrix
QuantBTEndpoint.nautilus_validation(...) # optional Nautilus validation
```

## Nautilus Example

```python
from quantbt import QuantBTEndpoint
from quantbt.adapters.nautilus import NautilusBackendConfig

bt = QuantBTEndpoint.nautilus_validation(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=10_000,
    use_funding=False,
    nautilus_config=NautilusBackendConfig(timeframe="1h"),
)

result = bt.simulate(
    data=df,
    signal_col="pos_weight",
    symbols=["SOLUSDT-PERP.BINANCE"],
)

result.show_metrics()
fills = bt.fills_report
```

Supported Nautilus validation instruments:

`BTCUSDT-PERP.BINANCE`, `ETHUSDT-PERP.BINANCE`, `BNBUSDT-PERP.BINANCE`,
`SOLUSDT-PERP.BINANCE`, `DOGEUSDT-PERP.BINANCE`, `ARBUSDT-PERP.BINANCE`,
`LINKUSDT-PERP.BINANCE`.

## Result Helpers

```python
result.show_metrics()
result.full_report()
result.quick_plot()
result.tearsheet()

bt.order_report
bt.fills_report
bt.export_orders("orders.csv")
bt.export_fills("fills.csv")
```

## Documentation

- [Endpoint contract](docs/endpoint.md)
- [Backend selection](docs/backend_selection.md)
- [Vectorized vs event-driven](docs/vectorized_vs_event_driven.md)
- [Margin and leverage](docs/margin_leverage.md)
- [Order fill policies](docs/order_fill_policies.md)
- [DCA/grid ladder](examples/dca_grid_ladder.py)
- [Nautilus backend](docs/nautilus_backend.md)

## Design Goal

QuantBT is built for the workflow most alpha research needs: fast iteration
first, then stricter execution validation where it matters. Use native
vectorized mode for broad sweeps, native event mode for order/fill behavior, and
Nautilus for small high-fidelity checks.

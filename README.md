# quantbt

Vectorised Binance-Futures backtest SDK with Numba-compiled simulation kernels.

## Package layout

```
quantbt/
├── __init__.py              public API
├── backtester.py            BacktestEngine
├── portfolio.py             MultiSymbolPortfolio
├── core/
│   ├── engine.py            Numba JIT kernels
│   ├── types.py             BacktestResult dataclass
│   └── preprocessor.py     data alignment, funding mask, array assembly
├── sizing/
│   └── modes.py             notional · unit · signal_notional · %_equity
├── metrics/
│   └── performance.py       sharpe · sortino · calmar · omega · mdd · hitrate …
└── viz/
    ├── themes.py             dark / light palette + rcParams
    └── plots.py              quick_plot · tearsheet
```

---

## Installation

```bash
pip install numpy pandas numba matplotlib seaborn
# then put the quantbt/ folder on your Python path
```

---

## Single-symbol backtest

```python
from quantbt import BacktestEngine

bt = BacktestEngine(
    Datetime        = df["Datetime"],
    Position        = signal,           # pd.Series: weights e.g. 1.0 / -0.5 / 0.0
    Close           = df["Close"],
    High            = df["High"],       # optional, enables intrabar liq check
    Low             = df["Low"],
    fee             = 0.0004,           # round-trip; halved internally to one-way
    use_pyramiding  = True,
    initial_capital = 20_000,
    leverage        = 10,
    maintenance_ratio = 0.005,
    contract_size   = 1.0,
    use_funding_rate = True,
    funding_rate    = 0.0001,
    alloc_per_trade = 100_000,
    hedge_type      = "signal_notional",
    slippage        = 0.0001,
)

bt.analyze()                 # text metrics + cumret/dd chart
result = bt.result           # BacktestResult
bt.tearsheet()               # full dashboard (optional)
bt.export_trade_log("log.csv")
```

---

## `hedge_type` — position sizing modes

| mode | description | use case |
|---|---|---|
| `"signal_notional"` | units frozen at signal-change price; no phantom rebalancing | systematic strategies — **recommended** |
| `"notional"` | constant notional every bar; recomputes units each bar | mark-to-market books, EOD data |
| `"unit"` | fixed unit count from first-bar price; notional drifts | delta-one exposure |
| `"%_equity"` | target = equity × alloc% × weight; dynamic sizing | volatility-targeted sizing |

### `signal_notional` in detail

When the signal changes from 0 → 1, units are computed as `alloc / close[change_bar]` and held constant
until the next signal transition.  This eliminates the O(n) micro-trades that `"notional"` generates on
high-frequency data when price drifts, and better reflects how systematic desks enter and size positions.

---

## Multi-symbol portfolio

```python
from quantbt import MultiSymbolPortfolio

msp = MultiSymbolPortfolio(
    positions  = {
        "BTCUSDT": pos_btc,
        "ETHUSDT": pos_eth,
        "SOLUSDT": pos_sol,
    },
    closes     = {
        "BTCUSDT": close_btc,
        "ETHUSDT": close_eth,
        "SOLUSDT": close_sol,
    },
    datetime_index  = common_dt,
    mode            = "market_neutral",   # 'longshort' | 'market_neutral' | 'directional' | 'equal_weight'
    asset_type      = "crypto",           # 'crypto' | 'stock'
    initial_capital = 100_000,
    leverage        = {"BTCUSDT": 5, "ETHUSDT": 3, "SOLUSDT": 2},
    alloc_per_trade = {"BTCUSDT": 60_000, "ETHUSDT": 30_000, "SOLUSDT": 10_000},
    funding_rate    = {"BTCUSDT": 0.00012, "ETHUSDT": 0.00008, "SOLUSDT": 0.00010},
)

msp.analyze()
msp.tearsheet()
msp.export_log("portfolio.csv")
hr = msp.hitrate_per_symbol()
```

### Allocation modes

| mode | description |
|---|---|
| `"longshort"` | raw positions, no adjustment |
| `"market_neutral"` | gross long notional == gross short notional each bar |
| `"directional"` | keep only the dominant side (highest abs notional) |
| `"equal_weight"` | equal weight across all active symbols |

---

## Standalone metrics

```python
from quantbt.metrics import full_report, sharpe, max_drawdown_pct, rolling_sharpe

rpt  = full_report(result)               # dict of all metrics
sr   = sharpe(result, trading_days=365)
mdd  = max_drawdown_pct(result)
rs   = rolling_sharpe(result, window=30)  # pd.Series
```

Available metrics: `total_return`, `cagr`, `sharpe`, `sortino`, `calmar`, `omega`,
`max_drawdown`, `avg_drawdown`, `drawdown_duration`, `profit_factor`, `hitrate`,
`avg_win_loss`, `expectancy`, `number_of_trades`, `rolling_sharpe`, `rolling_drawdown`.

---

## Standalone plots

```python
from quantbt.viz import quick_plot, tearsheet, apply_theme

quick_plot(result, theme="dark")          # cumret + drawdown only
tearsheet(result, theme="dark",           # full 6-panel dashboard
          benchmark=bm_series)
```

Themes: `"dark"` (screen / notebook) · `"light"` (print / report).

---

## BacktestResult

```python
result.equity           # pd.Series  equity curve
result.returns          # pd.Series  bar-frequency net returns
result.positions        # pd.DataFrame  Position_<sym> per symbol
result.closes           # pd.DataFrame  Close_<sym> per symbol
result.drawdown         # pd.Series  fraction from peak (property)
result.daily_equity     # pd.Series  resampled to 1D
result.daily_returns    # pd.Series  1D pct_change
result.liquidated       # bool
result.liquidation_bar  # int  (-1 = no liquidation)
result.metadata         # dict  run parameters snapshot
```

---

## Simulation contract

| item | implementation |
|---|---|
| MTM | close-to-close every bar; equity updated first |
| Liquidation | intrabar worst-case: Low for longs, High for shorts |
| Maintenance margin | `abs(pos) × price × contract_size × mm_rate`  (Binance notional formula) |
| Funding | fires once per 8h window (first bar entering 00:00 / 08:00 / 16:00 UTC) |
| Fee | one-way; round-trip fee is halved before passing to kernel |
| Slippage | fraction applied at execution; always a cost regardless of direction |
| Margin check | additional IM checked per order; rejected if insufficient |

---

## Known limitations

- `"notional"` mode generates O(n) trades on sub-daily data; prefer `"signal_notional"`.
- Partial fills are not modelled; orders are either fully executed or fully rejected.
- Cross-margin netting across symbols is not implemented.

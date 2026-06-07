# quantbt

Vectorised backtest SDK with Numba-compiled simulation kernels.

## Package layout

```
quantbt/
├── __init__.py              public API
├── backtester.py            BacktestEngine
├── portfolio.py             MultiSymbolPortfolio wrapper + allocation modes
├── core/
│   ├── engine.py            Numba JIT kernels incl. single, DCA, portfolio
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
    alloc_per_trade = 100_000,          # target notional per full signal unit
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
| `"dca_ladder"` | signed structural grid level; safety orders fill from High/Low at trigger prices | DCA/grid, ladder averaging |
| `"notional"` | constant notional every bar; recomputes units each bar | mark-to-market books, EOD data |
| `"unit"` | fixed unit count from first-bar price; notional drifts | delta-one exposure |
| `"%_equity"` | target = equity × alloc% × weight; dynamic sizing | volatility-targeted sizing |

### Leverage and buying power

Binance-style futures sizing separates collateral from notional exposure:

```python
buying_power = current_equity * leverage
initial_margin_required = order_notional / leverage
```

`alloc_per_trade` is the order notional.  Leverage does not
multiply the order size; it only controls how much initial margin is required and
whether the account still has enough buying power.

```python
# 20,000 equity, 10x leverage -> up to about 200,000 notional buying power
bt = BacktestEngine(
    Datetime=dt,
    Position=signal,
    Close=close,
    initial_capital=20_000,
    leverage=10,
    alloc_per_trade=50_000,     # order notional
)
```

### `signal_notional` in detail

When the signal changes from 0 → 1, units are computed as `alloc / close[change_bar]` and held constant
until the next signal transition.  This eliminates the O(n) micro-trades that `"notional"` generates on
high-frequency data when price drifts, and better reflects how systematic desks enter and size positions.

### `dca_ladder` in detail

`dca_ladder` separates the structural grid state from the actual filled position.
`Position` is a signed structural level cap:

| value | meaning |
|---|---|
| `0` | flat / no active ladder |
| `+1` | long base order only |
| `+2` | long base + AO1 allowed |
| `+6` | long base + AO1..AO5 allowed |
| `-1` | short base order only |
| `-6` | short base + AO1..AO5 allowed |

The engine keeps actual filled units internally.  Base orders execute at close
when a cycle starts.  Safety orders are simulated as limit orders:

- long AO fills when `Low <= trigger_price`
- short AO fills when `High >= trigger_price`
- multiple AO levels can fill in the same bar, each at its own trigger price
- a new base opened at close does not back-fill safety orders from that same bar's earlier High/Low
- old legs are not repriced when new levels fill
- `result.positions` contains actual filled units, not structural levels
- `result.metadata["dca_actual_level"]` contains the filled structural level over time

```python
bt = BacktestEngine(
    Datetime=dt,
    Position=grid_level,          # e.g. 0, 6, 6, 6, 0 for one long cycle
    Close=close,
    High=high,                    # required
    Low=low,                      # required
    hedge_type="dca_ladder",
    initial_capital=100_000,
    leverage=10,
    alloc_per_trade=20_000,       # default base/safety leg notional
    dca_step_pct=0.01,            # AO1 at 1% adverse from base
    dca_step_scale=1.2,           # next distance increments expand
    dca_volume_scale=1.5,         # next safety order notionals grow
    dca_max_safety_orders=5,
    dca_take_profit_pct=0.006,    # TP from weighted average entry; 0 disables
)
```

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

For crypto portfolios, `funding_rate` is interpreted as the per-event funding
rate applied on each 8h funding timestamp.

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
| DCA Ladder | base/flat transitions are market-at-close; safety orders and TP are limit fills from High/Low triggers |

---

## Known limitations

- `"notional"` mode generates O(n) trades on sub-daily data; prefer `"signal_notional"`.
- Partial fills are not modelled; orders are either fully executed or fully rejected.
- Cross-margin netting across symbols is not implemented.

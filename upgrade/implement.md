# QuantBT Upgrade Implementation Plan

Mục tiêu: nâng cấp `quantbt` thành hệ backtest hai lớp:

1. **Native fast path**: core riêng của quantbt, dùng Numba trước tiên, sau đó Cython/C++ nếu benchmark chứng minh cần.
2. **High-fidelity backend**: adapter NautilusTrader để tận dụng Rust core cho order lifecycle, matching, portfolio/risk semantics và làm reference/oracle cho các case event-driven khó.

Nguyên tắc chính:

- Không trộn alpha logic, sizing logic, execution logic và accounting logic.
- Vectorized engine phải nhanh, batch-friendly, dùng ndarray và Numba.
- Event-driven engine phải đúng order domain, có order/fill/trade lifecycle rõ ràng.
- Hai engine phải trả cùng một result schema để metrics/viz/optimizer dùng chung.
- Mỗi phase phải có golden tests trước hoặc cùng lúc với implementation.
- Sau mỗi thay đổi coherent, commit ngay trên `dev`.

---

## Architecture Decision

Không chọn một trong hai kiểu "tự code hết" hoặc "dùng Nautilus hết".

Chúng ta sẽ làm **dual-backend architecture**:

```text
Alpha / Signals
      |
      v
Signal Adapter / Sizing
      |
      v
OrderIntent / TargetPosition / BasketIntent
      |
      +--> NativeVectorizedBackend   -> BacktestResultV2
      |
      +--> NativeEventBackend        -> BacktestResultV2
      |
      +--> NautilusBackend Adapter   -> BacktestResultV2
```

Lý do:

- Native vectorized backend là bắt buộc cho optimizer, multi-symbol research, grid search và daily/intraday batch runs.
- Native event backend là cần để mô phỏng order/fill domain mà không phụ thuộc vào strategy callback overhead.
- Nautilus backend vẫn rất giá trị cho high-fidelity validation, order lifecycle, instrument precision, netting/hedging semantics và các case cần gần production.
- Không nên đặt Nautilus làm default core duy nhất vì chi phí object conversion, dependency nặng, strategy callback model, report conversion và tốc độ optimizer có thể không phù hợp với workflow alpha research.

---

## Phase 0 - Baseline And Golden Tests

Deliverables:

- Tạo `tests/` cho quantbt nếu chưa có.
- Thêm golden scenarios nhỏ, deterministic:
  - single market long/flat;
  - long to short reversal;
  - fee one-way/round-trip;
  - leverage buying power and margin rejection;
  - funding event once per 8h window;
  - intrabar liquidation using high/low;
  - limit fill touched by low/high;
  - DCA ladder level fill;
  - multi-symbol portfolio rebalance;
  - pair basket entry/exit with frozen hedge ratio.

Acceptance:

- Tests chạy được cục bộ.
- Current behavior được snapshot để tránh regression vô thức.
- Các known-differences được ghi rõ, không giấu trong metric drift.

Commit boundary:

- Commit chỉ gồm tests/baseline fixtures/docs liên quan Phase 0.

---

## Phase 1 - Shared Domain Schema

Deliverables:

- Thêm module schema, ví dụ:
  - `core/schema.py`
  - `core/orders.py`
  - `core/results.py`

Core dataclasses/enums:

- `InstrumentSpec`
  - symbol, asset_type, contract_size, tick_size, lot_size, min_qty, min_notional, price_precision, qty_precision.
- `AccountConfig`
  - initial_capital, base_currency, margin_mode, leverage, maintenance_ratio, liquidation_policy.
- `ExecutionConfig`
  - fill_model, slippage_model, fee_model, order_price_policy, allow_partial_fill, reject_on_insufficient_margin.
- `OrderIntent`
  - timestamp, symbol, side, order_type, qty, price, trigger_price, tif, reduce_only, tag.
- `Fill`
  - timestamp, symbol, side, qty, price, fee, liquidity, order_id, trade_id.
- `Trade`
  - open/close timestamps, qty, avg entry/exit, realized pnl, fees, metadata.
- `BacktestResultV2`
  - equity, returns, positions, closes, orders, fills, trades, fees, funding, margin, diagnostics, metadata.

Compatibility:

- Existing `BacktestResult` remains supported.
- Add conversion helpers:
  - `BacktestResultV2.to_legacy()`
  - `BacktestResultV2.from_legacy()`

Acceptance:

- Existing public imports keep working.
- Metrics can still consume legacy result.
- New result can store fills/trades without breaking old charts.

---

## Phase 2 - Native Vectorized Backend V2

Purpose:

Fast path for position/target-unit style backtests.

Deliverables:

- Move current kernels behind a backend API:
  - `backends/native_vectorized.py`
  - `core/engine.py` remains kernel home or becomes kernel registry.
- Support target modes:
  - `notional`
  - `unit`
  - `signal_notional`
  - `pct_equity`
  - `dca_ladder`
  - future: `basket_frozen`
- Kernel returns richer diagnostics:
  - accepted positions;
  - fees per bar;
  - turnover per bar;
  - funding per bar;
  - initial margin;
  - maintenance margin;
  - rejected order count/reason code;
  - liquidation bar and reason code.

Important domain rule:

- `alloc_per_trade` is order notional.
- `buying_power = equity * leverage`.
- Initial margin required = notional / leverage.
- Leverage must not multiply `alloc_per_trade`.

Acceptance:

- Existing `BacktestEngine` and `MultiSymbolPortfolio` match or intentionally improve current behavior.
- No pandas in kernel path.
- Benchmarks added for `N bars x M symbols`.

---

## Phase 3 - Native Event-Driven Backend

Purpose:

Order lifecycle simulation without Nautilus dependency, optimized for research speed.

Deliverables:

- Add backend:
  - `backends/native_event.py`
  - `core/matching.py`
  - `core/accounting.py`
- Event loop:
  - iterate bars/ticks by timestamp;
  - apply funding/mark price updates;
  - process order queue;
  - update positions/account;
  - emit fills/trades.
- Supported order types:
  - market;
  - limit;
  - stop-market;
  - stop-limit later;
  - reduce-only later.
- Supported TIF:
  - GTC;
  - IOC;
  - FOK basic.
- OHLC fill policy:
  - buy limit fills if `low <= limit_price`;
  - sell limit fills if `high >= limit_price`;
  - fill at trigger/limit price, not close;
  - configurable same-bar ordering policy for ambiguous bars.

Acceptance:

- Limit/DCA/grid behavior matches golden tests.
- Event result has complete order/fill/trade logs.
- Performance is good enough for medium-size parameter sweeps.

---

## Phase 4 - Basket, Pair Trading, Arbitrage

Purpose:

Support pair/multi-leg strategies as first-class domain objects.

Deliverables:

- Add `BasketIntent`:
  - basket_id;
  - legs;
  - target gross notional or alloc pct;
  - hedge ratios;
  - atomic execution policy.
- Add sizing:
  - `basket_frozen`
  - `pair_beta`
  - `market_neutral_basket`
- Hedge freezing:
  - compute units at entry;
  - hold units constant while signal unchanged;
  - close all legs together at exit;
  - optional rebalance threshold for beta drift.
- Margin model:
  - gross margin default;
  - optional `hedged_margin_offset`;
  - portfolio-margin style diagnostics.

Acceptance:

- Pair entry opens all legs same timestamp.
- Exit closes exact frozen units.
- No price-drift micro-rebalancing unless explicitly configured.
- Basket failures are visible: all-or-none reject, partial fill, or best-effort depending config.

---

## Phase 5 - Nautilus Backend Adapter

Purpose:

Use Nautilus Rust/Cython engine as high-fidelity backend and validation oracle.

Deliverables:

- Add optional module:
  - `adapters/nautilus/__init__.py`
  - `adapters/nautilus/backend.py`
  - `adapters/nautilus/instruments.py`
  - `adapters/nautilus/reports.py`
- Convert quantbt schema to Nautilus:
  - `InstrumentSpec` -> Nautilus instrument;
  - `OrderIntent` -> Nautilus order factory;
  - `ExecutionConfig` -> venue/fill/fee model;
  - OHLCV DataFrame -> v1 `BarDataWrangler` bars.
- Convert Nautilus reports back:
  - account report -> equity;
  - orders report -> orders;
  - fills report -> fills;
  - positions report + snapshots -> trades.

Rules:

- Nautilus dependency must be optional.
- Importing `quantbt` should not require Nautilus installed.
- If Nautilus is missing, adapter raises clear install error.
- Use v1 wranglers with `BacktestEngine.add_data()`.
- Use EXTERNAL bar types for external OHLCV data.

Acceptance:

- Single-symbol market strategy runs through Nautilus backend.
- Result converts to `BacktestResultV2`.
- At least 3 golden tests compare NativeEvent vs Nautilus on simple cases.

Current status:

- Implemented single-symbol Nautilus validation for signal-series strategies.
- Supported single-symbol sizing modes:
  - `signal_notional`;
  - `notional`;
  - `unit`;
  - `%_equity`.
- Supported Binance USDT perpetual validation instruments:
  - BTC, ETH, BNB, SOL, DOGE, ARB, LINK.
- Nautilus report conversion now reconstructs full bar-by-bar equity and
  positions from fills plus OHLCV close, while preserving raw account reports for
  audit.

Planned Nautilus upgrades, not implemented yet:

- **Explicit order replay**
  - Convert `OrderIntent` into Nautilus market/limit/stop orders.
  - Preserve TIF, reduce-only, order tags, and reject/cancel diagnostics.
  - Compare native event order reports vs Nautilus order/fill reports.
- **DCA/grid ladder validation**
  - Convert structural ladder levels into Nautilus limit safety orders.
  - Model base order, safety order activation, take-profit, same-bar ambiguity,
    and high/low trigger behavior explicitly.
  - Add parity tests against native DCA golden cases.
- **Pair/basket validation**
  - Convert `BasketSpec` / `BasketIntent` into multi-leg Nautilus orders.
  - Support frozen hedge-ratio entry, exact-unit exit, all-or-none or
    best-effort execution policy.
  - Add spread/accounting diagnostics per leg and per basket.
- **Multi-symbol portfolio validation**
  - Run multiple instruments in one Nautilus venue/account.
  - Convert position matrix signals into per-symbol target orders.
  - Reconcile cross-symbol margin, netting, funding, fees, and equity reports.
- **Institutional parity audit**
  - Add a reusable native-vs-Nautilus comparison report:
    - transition timestamp;
    - target quantity;
    - fill price;
    - fee;
    - position;
    - reconstructed equity;
    - account report equity;
    - native equity diff.
  - Promote any known intentional differences into documented test fixtures.

---

## Phase 5.2 - Nautilus Explicit Order Replay

Purpose:

Promote Nautilus from signal-target validation into an execution trustee backend
that can replay explicit QuantBT `OrderIntent` objects. This is the foundation
for DCA/grid validation, SL/TP/OCO workflows, order-package arbitrage, and later
multi-leg portfolio validation.

Branch:

```text
feat/nautilus-explicit-orders
```

Design scope:

- Keep alpha/signal generation outside Nautilus.
- QuantBT creates normalized `OrderIntent` objects.
- Nautilus receives those explicit orders and simulates order lifecycle,
  execution, fills, positions, account reports, and venue semantics.
- The first implementation is deliberately single-symbol Binance USDT perpetual
  replay; multi-symbol and basket package replay come after the single-symbol
  path is trustworthy.

Common order families to support over time:

- Basic orders:
  - market;
  - limit;
  - stop-market;
  - stop-limit.
- Common venue controls:
  - GTC;
  - IOC;
  - FOK where supported;
  - post-only later if Nautilus route is clean;
  - reduce-only;
  - client tags/order ids.
- Conditional structures:
  - stop loss;
  - take profit;
  - trailing stop later;
  - OCO / bracket groups once base order replay is stable.
- Package orders:
  - DCA/grid safety-order packages;
  - pair/basket package orders;
  - arbitrage multi-leg package orders with atomic/best-effort policies.

### Phase 5.2A - Single-Symbol Explicit Order Adapter

Deliverables:

- Add a Nautilus explicit-order route that accepts QuantBT `OrderIntent`
  sequences.
- Public endpoint route:

```python
QuantBTEndpoint.orders(backend="nautilus", ...)
bt.simulate(data=df, orders=[OrderIntent(...), ...])
```

- Convert supported QuantBT fields:
  - timestamp;
  - symbol;
  - side;
  - order type;
  - quantity;
  - price / trigger price;
  - TIF;
  - reduce-only;
  - tag / client order id where Nautilus exposes it cleanly.
- Return `BacktestResultV2` with:
  - raw `account_report`;
  - raw `orders_report`;
  - raw `fills_report`;
  - raw `positions_report`;
  - reconstructed equity/positions;
  - metadata declaring `input_mode="explicit_orders"`.

Initial support matrix:

| QuantBT order | Phase 5.2A target |
|---|---|
| `MARKET` | supported |
| `LIMIT` | supported |
| `STOP_MARKET` | supported if Nautilus factory route is stable |
| `STOP_LIMIT` | map only if factory route is stable, otherwise explicit `NotImplementedError` |
| `GTC` | supported |
| `IOC` | supported if Nautilus route is stable |
| `FOK` | explicit support or documented reject |
| `reduce_only` | pass through if supported, otherwise documented metadata warning |

Acceptance tests:

- Market buy then market sell produces expected Nautilus reports.
- Buy limit fills only when the bar range touches the limit.
- Sell limit fills only when the bar range touches the limit.
- GTC order can wait across bars before filling.
- Unsupported order types fail clearly instead of silently degrading.
- Missing Nautilus dependency still raises a clear optional-install error.
- Existing signal-based `nautilus_validation(...)` remains unchanged.

### Phase 5.2B - Parity And Audit Hardening

Deliverables:

- Native-event vs Nautilus parity helper/report:
  - timestamp;
  - symbol;
  - side;
  - requested quantity;
  - requested price;
  - fill price;
  - fee;
  - position after fill;
  - native equity;
  - Nautilus equity;
  - diff.
- Extend `export_nautilus_report_bundle(...)` manifest for explicit-order runs:
  - `input_mode`;
  - `order_count_input`;
  - `orders_count`;
  - `fills_count`;
  - `cancelled/rejected count` when available.
- Add example:

```text
examples/nautilus_explicit_orders.py
```

- Update docs:
  - `docs/endpoint.md`;
  - `docs/nautilus_backend.md`;
  - README if the route is user-facing enough.

Acceptance tests:

- Simple native-event and Nautilus market replay agree in direction, order
  count, fill count and broad equity accounting.
- Report bundle works for explicit orders.
- Known intentional differences are documented instead of hidden.

Non-goals for 5.2:

- Full DCA/grid Nautilus validation.
- Full basket/multi-symbol Nautilus validation.
- Full OCO/bracket engine.
- Exchange-specific latency/queue-position modeling.
- Replacing native event engine as the fast research path.

Current status:

- Phase 5.2A implemented on `feat/nautilus-explicit-orders`:
  - `QuantBTEndpoint.orders(backend="nautilus", ...)`;
  - explicit single-symbol `OrderIntent` replay through Nautilus;
  - market, limit, stop-market, and stop-limit order factory mapping;
  - TIF, reduce-only, tags, trigger/limit prices preserved in payload/report
    tables where Nautilus supports them.
- Phase 5.2B implemented:
  - `build_native_nautilus_parity_report(...)`;
  - explicit-order fields in report bundle manifest/summary;
  - example `examples/nautilus_explicit_orders.py`;
  - docs updated for endpoint and Nautilus backend usage.
- Tested:
  - native event explicit order route remains unchanged;
  - Nautilus explicit order route works for market and GTC limit replay;
  - native-vs-Nautilus market replay parity smoke;
  - report bundle explicit-order manifest fields;
  - full internal tests excluding real-data scripts.

### Phase 5.2C - Nautilus Structured Orders And Strategy Packages

Purpose:

Upgrade single-symbol explicit replay into structured order workflows while
still keeping the strategy/research layer outside Nautilus.

Scope:

- DCA/grid validation through generated explicit order packages:
  - base market order;
  - safety limit orders;
  - take-profit / stop-loss exits;
  - high/low touch behavior delegated to Nautilus bar execution;
  - same-bar ambiguity documented as a policy.
- OCO/bracket order support:
  - entry order + stop-loss + take-profit group;
  - explicit group id / parent tag;
  - cancel sibling exit when one leg fills;
  - preserve tags in Nautilus reports.
- Stop-loss / take-profit package workflow:
  - deterministic generation from `OrderIntent`/package spec;
  - no hidden alpha logic inside Nautilus strategy;
  - all generated orders available in `package_order_map`.

Endpoint targets:

```python
QuantBTEndpoint.nautilus_dca_grid(...)
QuantBTEndpoint.nautilus_bracket_orders(...)
QuantBTEndpoint.orders(backend="nautilus", orders=[...])
```

The first two endpoint names are planned public convenience routes. They should
compile into explicit `OrderIntent` packages, then reuse the already-supported
Nautilus explicit-order replay path.

Acceptance tests:

- DCA base order submits at the expected timestamp.
- Safety limit fills only when bar high/low touches the grid price.
- TP/SL exit closes the position and prevents double-close.
- OCO/bracket sibling cancellation is visible in report metadata.
- Native DCA/grid golden scenario and Nautilus validation agree on order
  direction, intended trigger price, fill count, and position lifecycle where
  the same bar policy is unambiguous.

Non-goals:

- Exchange queue priority.
- Tick-level latency modeling.
- Hidden strategy generation inside Nautilus.

### Phase 5.2D - Nautilus Multi-Leg, Portfolio, And Institutional Audit

Purpose:

Promote Nautilus validation from single-symbol order replay into multi-leg and
portfolio execution trustee workflows.

Scope:

- Basket/pair validation:
  - convert `BasketSpec` / pair signals into multi-leg explicit order packages;
  - frozen hedge-ratio entry;
  - exact-unit exit;
  - package id, leg id, and execution policy in metadata;
  - support best-effort first, then all-or-none when domain tests are ready.
- Multi-symbol portfolio validation:
  - convert position matrix transitions into per-symbol target delta orders;
  - run multiple instruments in one Nautilus venue/account;
  - reconcile cross-symbol equity, netting, margin, fees, and funding;
  - expose per-symbol order/fill/position reports.
- Institutional parity audit:
  - compare native vs Nautilus at transition/order/fill/equity level;
  - summarize max fill-price diff, fee diff, position diff, equity diff;
  - classify differences as expected policy differences or regression risks;
  - produce CSV/JSON audit artifacts suitable for stakeholder review.

Endpoint targets:

```python
QuantBTEndpoint.basket(backend="nautilus", ...)
QuantBTEndpoint.portfolio(backend="nautilus", ...)
QuantBTEndpoint.arbitrage(..., backend="nautilus")
build_native_nautilus_parity_report(...)
```

Acceptance tests:

- Pair basket opens all intended legs and closes exact units.
- Multi-symbol portfolio transition generates expected per-symbol orders.
- Nautilus reports preserve package id / leg id / symbol ids.
- Parity report catches intentionally injected fill-price and fee differences.
- Existing single-symbol, native event, and report bundle endpoints remain
  unchanged.

Non-goals:

- Cross-exchange latency arb.
- Options Greeks / vol surface execution.
- Full portfolio-margin replication beyond diagnostics.

---

## Phase 5.1 - Nautilus Trustee Report Bundle

Purpose:

Build a professional report/export service around the existing Nautilus backend
so QuantBT can be used when third-party cloud platforms cannot run long,
high-resolution backtests such as multi-year 15m data.

This phase is **not** a new backtest engine.

It is a reporting and evidence layer on top of:

```text
QuantBTEndpoint.nautilus_validation(...)
  -> NautilusTrader BacktestEngine
  -> raw Nautilus account/order/fill/position reports
  -> QuantBT BacktestResultV2
  -> report bundle folder
```

Design position:

- The strategy/signal timeline is passed into `QuantBTEndpoint` before the
  backend simulation. This is the correct boundary.
- Backtest engines should not be responsible for strategy feature generation or
  look-ahead validation. That responsibility belongs to the strategy/research
  layer.
- Nautilus should receive the signal timeline, convert signal transitions into
  orders, simulate event-driven execution, and calculate account/fill/position
  results.
- Do **not** add a second strategy abstraction inside the report service.
- Do **not** make the report text claim that "signals are externally generated"
  as a caveat. In this architecture, signal input is the normal endpoint
  contract, similar to vectorbt/backtrader-style signal or target-position
  APIs.
- The report should instead emphasize the factual backend:
  - backend: `nautilus`;
  - engine: `NautilusTrader BacktestEngine`;
  - execution model: event-driven bar execution;
  - sizing mode;
  - account settings;
  - instrument/timeframe;
  - order/fill/position counts.

Deliverables:

- Add a service/exporter module, for example:
  - `quantbt/reporting/nautilus_bundle.py`; or
  - `quantbt/services/nautilus_report.py`.
- Public function or class:

```python
export_nautilus_report_bundle(
    result,
    output_dir,
    strategy_id,
    config=None,
    benchmark_returns=None,
    make_quantstats=True,
    quantstats_frequency="1D",
    quantstats_periods_per_year=365,
    print_fills=True,
    fill_log_limit=500,
    fill_log_mode="fills_only",
)
```

- Input is a completed `BacktestResultV2` returned by:

```python
bt = QuantBTEndpoint.nautilus_validation(...)
result = bt.simulate(...)
```

- The service reads from:
  - `result.equity`;
  - `result.returns`;
  - `result.positions`;
  - `result.metadata["account_report"]`;
  - `result.metadata["orders_report"]`;
  - `result.metadata["fills_report"]`;
  - `result.metadata["positions_report"]`;
  - `result.metadata` for run/config diagnostics.

Report folder layout:

```text
report_{strategy_id}_{timestamp}/
  quantstats_daily.html
  equity_curve.csv
  returns.csv
  account_report.csv
  orders_report.csv
  fills_report.csv
  positions_report.csv
  trade_log.csv
  fill_log.txt
  metrics_summary.json
  run_manifest.json
  config.json
```

Required artifacts:

- `account_report.csv`
  - raw Nautilus account report;
  - required for account-balance audit.
- `orders_report.csv`
  - raw Nautilus order lifecycle report.
- `fills_report.csv`
  - raw Nautilus fill report when available;
  - fallback to orders report only when Nautilus does not expose fills.
- `positions_report.csv`
  - raw Nautilus positions report.
- `trade_log.csv`
  - normalized closed-trade view built from `positions_report` and/or fills.
- `equity_curve.csv`
  - timestamp, equity, drawdown, returns.
- `returns.csv`
  - returns used by QuantStats.
- `quantstats_daily.html`
  - primary visual performance report.
- `metrics_summary.json`
  - compact metrics for dashboards/services.
- `run_manifest.json`
  - evidence file proving which backend, config, data span and report inputs
    were used.
- `config.json`
  - endpoint/backend configuration used for the run;
  - auto-filled from `result.metadata["run_config"]` when the caller does not
    pass explicit config;
  - must include capital, leverage, maintenance, fee, slippage, sizing,
    funding, instrument, and timeframe when available.
- `fill_log.txt`
  - human-readable execution trace for review.

QuantStats policy:

- Use `quantstats.reports.html(...)` as the default HTML performance report.
- For long 15m or intraday data, primary QuantStats report should normally use
  daily resampled returns:

```python
daily_equity = equity.resample("1D").last().dropna()
daily_returns = daily_equity.pct_change().dropna()
```

- Keep raw intraday `equity_curve.csv` and `returns.csv` for audit.
- Pass `periods_per_year=365` to QuantStats by default for crypto; expose
  `quantstats_periods_per_year` so stocks/futures can override this.
- Optional intraday QuantStats output may be allowed, but must be clearly named
  experimental because annualization assumptions can be misleading on raw 15m
  returns.

Trade log schema:

```text
strategy_id
symbol
exchange
instrument_id
position_type
open_datetime
close_datetime
entry_price
exit_price
quantity
realized_pnl
fees
duration_seconds
return_pct
order_ids
```

Run manifest schema:

```text
strategy_id
run_id
created_at
backend
engine
instrument_id
timeframe
data_start
data_end
bar_count
signal_count
signal_changes
initial_capital
leverage
alloc_per_trade
sizing_mode
fee_rate
use_funding
orders_count
fills_count
positions_count
account_final_equity
reconstructed_final_equity
account_reconstructed_diff
quantbt_git_commit
nautilus_version
python_version
data_hash
signal_hash
```

Fill/event logging:

- Add a bounded human-readable execution log, similar in spirit to
  `alphas_storage/simulation_alpha/services.py`, but more controlled.
- Default should print only on fills/order events, not every bar.
- Optional modes:
  - `print_fills=True`: print fill rows to stdout while exporting;
  - `fill_log_limit=500`: cap console/log text for large multi-year runs;
  - `fill_log_mode="fills_only"`: choose fills/order/position-change detail;
  - `include_no_fill_bars=False`: avoid printing every no-op bar by default.
- The log should make it obvious this is event-driven:

```text
2021-01-01 12:00:00 BUY 0.125 BTCUSDT-PERP.BINANCE @ 32000.5 fee=...
2021-01-04 08:15:00 SELL 0.125 BTCUSDT-PERP.BINANCE @ 33510.0 fee=...
```

- If full per-bar trace is needed, expose an explicit debug mode:

```python
fill_log_mode="fills_only"  # fills_only | order_events | bars_debug
```

- `bars_debug` must use `fill_log_limit` as a hard cap to avoid giant logs.

Endpoint usage target:

```python
from quantbt import QuantBTEndpoint
from quantbt.adapters.nautilus import NautilusBackendConfig
from quantbt.reporting import export_nautilus_report_bundle

bt = QuantBTEndpoint.nautilus_validation(
    initial_capital=20_000,
    leverage=5,
    alloc_per_trade=0.5,
    hedge_type="%_equity",
    fee_rate=0.0005,
    use_funding=False,
    nautilus_config=NautilusBackendConfig(
        timeframe="1h",
        starting_balance=20_000,
        trade_notional=0.5,
        close_positions_on_stop=False,
    ),
)

result = bt.simulate(
    data=df_result,
    signal_col="pos_weight",
    symbols=["BTCUSDT-PERP.BINANCE"],
)

export_nautilus_report_bundle(
    result=result,
    output_dir="/root/bobby/pool_alpha/alphas_storage/simulation_alpha/reports",
    strategy_id="my_alpha_001",
    config={"note": "nautilus trustee validation"},
    make_quantstats=True,
    print_fills=True,
    fill_log_limit=300,
    fill_log_mode="fills_only",
)
```

Implementation rules:

- Keep this phase outside core engine accounting.
- Do not change native vectorized/event behavior.
- Do not add alpha feature computation to Nautilus adapter.
- Do not make report export mandatory for every backtest run.
- Report export must be an explicit call after endpoint simulation.
- QuantStats should be optional; if missing, exporter should still dump CSV/JSON
  and warn clearly.
- Avoid huge console output by default.
- Never mutate `result.metadata` reports in-place; copy before normalization.
- Preserve raw Nautilus reports exactly as CSV.

Testing plan:

- Unit tests:
  - exporter creates expected folder/files from a synthetic `BacktestResultV2`;
  - empty orders/fills/positions reports still create valid manifest;
  - trade log parser handles Nautilus money strings and missing close times;
  - daily QuantStats input is resampled from intraday equity correctly;
  - fill log respects `fill_log_limit` and selected mode.
- Integration smoke:
  - run a small `QuantBTEndpoint.nautilus_validation(...)` backtest;
  - export report bundle;
  - assert raw reports exist and row counts match `result.metadata`;
  - assert `quantstats_daily.html` exists when `quantstats` is installed.
- Regression checks:
  - `orders_count`, `fills_count`, `positions_count` in manifest match metadata;
  - `account_reconstructed_diff` is saved and visible;
  - `trade_log.csv` has stable column order;
  - fill log contains timestamps, side, qty, instrument and price.
- Performance sanity:
  - exporter should stream/write CSVs directly;
  - no expensive plots required by default;
  - QuantStats daily resampling should handle multi-year 15m equity without
    exploding output size.

Acceptance:

- User can run Nautilus endpoint on long 15m data and then call one exporter
  function to produce a professional report folder.
- Report folder contains QuantStats HTML plus raw account/order/fill/position
  evidence.
- Console and `fill_log.txt` show executed fills in a bounded, readable way.
- No new strategy execution abstraction is introduced.
- Nautilus remains the event-driven third-party execution/accounting backend.

---

## Phase 6 - Public API And Migration

Deliverables:

- Keep old APIs:
  - `BacktestEngine`
  - `MultiSymbolPortfolio`
- Add new APIs:
  - `BacktestEngineV2`
  - `PortfolioBacktestEngine`
  - `EventDrivenBacktestEngine`
  - `NautilusBacktestEngine` optional.
- Add clear backend selector:

```python
engine = BacktestEngineV2(
    data=data,
    signals=signals,
    backend="native_vectorized",  # native_vectorized | native_event | nautilus
    execution=ExecutionConfig(...),
    account=AccountConfig(...),
)
```

Acceptance:

- Old notebooks continue to work.
- New examples cover:
  - single order;
  - DCA/grid;
  - multi-symbol portfolio;
  - pair basket;
  - Nautilus validation run.

---

## Phase 7 - Benchmark And Optimization

Deliverables:

- Benchmark suite:
  - bars x symbols;
  - order count;
  - event count;
  - memory usage;
  - compile time vs run time.
- Compare:
  - native vectorized;
  - native event;
  - Nautilus.
- Identify if Cython/C++ is needed.

Escalation rule:

- Stay with Numba unless benchmark proves bottleneck.
- Move only hot loops to Cython/C++.
- Keep Python API stable.

Acceptance:

- Benchmark report saved in repo.
- Performance thresholds documented.

---

## Phase 8 - Documentation And Examples

Deliverables:

- Update README.
- Add docs:
  - vectorized vs event-driven;
  - margin/leverage semantics;
  - order fill policies;
  - pair/basket guide;
  - Nautilus backend guide.
- Add sample files under `examples/`.

Acceptance:

- User can choose correct backend from docs.
- Each major strategy type has a minimal runnable example.

---

## Backend Selection Guide

Use `native_vectorized` when:

- signal already represents target position/weight;
- research speed matters most;
- fills can be approximated by close/open or deterministic high/low rules;
- optimizer needs many runs.

Use `native_event` when:

- order lifecycle matters;
- limit/stop/grid/DCA behavior matters;
- order rejection, partial fill, reduce-only, or TIF matters;
- still need faster-than-Nautilus research workflow.

Use `nautilus` when:

- validating native engine behavior;
- needing production-like order/portfolio semantics;
- testing instrument precision, netting/hedging, and exchange-like reports;
- running fewer, higher-fidelity simulations.

---

## Commit Discipline

For every phase:

1. Check branch is `dev`.
2. Check `git status`.
3. Stage only files related to current phase.
4. Run available tests/compile checks.
5. Commit immediately after a coherent change.
6. Do not include unrelated dirty files.

Main branch is protected by local pre-commit hook.

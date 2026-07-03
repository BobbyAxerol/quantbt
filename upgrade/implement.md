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

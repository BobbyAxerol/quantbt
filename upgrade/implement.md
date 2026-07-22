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

Completed in later Nautilus phases:

- Explicit order replay is implemented in Phase 5.2A/5.2B:
  - `OrderIntent` market/limit/stop routes;
  - TIF/reduce-only/tag preservation where Nautilus exposes it;
  - native-vs-Nautilus parity helper/report.
- DCA/grid and bracket/OCO package validation are implemented at experimental
  structured-package level in Phase 5.2C and depth-preflight level in Phase 5.4.
- Pair/basket and multi-symbol portfolio Nautilus package validation are
  implemented at experimental level in Phase 5.2D/5.4.
- Institutional parity artifacts exist for explicit orders and depth-preflight
  package diagnostics.

Remaining Nautilus debt:

- Dynamic in-Nautilus DCA/grid state machine, not just generated/preflighted
  package orders.
- Exchange-native OCO/bracket order-list semantics beyond package-strategy
  sibling cancellation.
- True queue priority, latency, partial-fill, and L2 order-book simulation.
- Deeper real-strategy portfolio/arbitrage parity bundles before production
  certification.
- Venue-specific portfolio-margin replication only if a production requirement
  appears.

---

## Phase 5.2 - Nautilus Explicit Order Replay

Purpose:

Promote Nautilus from signal-target validation into an execution trustee backend
that can replay explicit QuantBT `OrderIntent` objects. This is the foundation
for DCA/grid validation, SL/TP/OCO workflows, order-package arbitrage, and later
multi-leg portfolio validation.

Historical branch:

```text
feat/nautilus-explicit-orders
```

This branch has since been merged into `dev`; keep the section as design
history, not current branch guidance.

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

- Dynamic in-Nautilus alpha/state generation for DCA/grid.
- Full advanced basket/multi-symbol Nautilus validation with all-or-none
  package semantics and portfolio-margin replication.
- Exchange-native contingent order-list semantics beyond package-strategy OCO
  sibling cancellation.
- Exchange-specific latency/queue-position modeling.
- Replacing native event engine as the fast research path.

Current status:

- Phase 5.2A implemented from the historical `feat/nautilus-explicit-orders`
  work:
  - `QuantBTEndpoint.orders(backend="nautilus", ...)`;
  - explicit single-symbol `OrderIntent` replay through Nautilus;
  - market, limit, stop-market, and stop-limit order factory mapping;
  - TIF, reduce-only, tags, trigger/limit prices preserved in payload/report
    tables where Nautilus supports them.
- Phase 5.2B implemented:
  - `build_native_nautilus_parity_report(...)`;
  - `summarize_native_nautilus_parity_report(...)`;
  - explicit-order fields in report bundle manifest/summary;
  - example `examples/nautilus_explicit_orders.py`;
  - docs updated for endpoint and Nautilus backend usage.
- Phase 5.2C implemented at experimental structured-package level:
  - `DcaGridSpec`, `BracketOrderSpec`, and `StructuredOrderPlan`;
  - `QuantBTEndpoint.nautilus_dca_grid(...)`;
  - `QuantBTEndpoint.nautilus_bracket_orders(...)`;
  - DCA base market orders, safety GTC limits, and optional reduce-only TP/SL
    exits compile into explicit `OrderIntent` packages;
  - bracket/OCO entry plus TP/SL exits compile into explicit `OrderIntent`
    packages;
  - Nautilus package strategy cancels sibling TP/SL exit orders after the first
    exit fill and exposes `oco_cancellations` in metadata.
- Phase 5.2D implemented at experimental package-validation level:
  - `QuantBTEndpoint.basket(backend="nautilus", ...)`;
  - `QuantBTEndpoint.portfolio(backend="nautilus", ...)`;
  - basket/pair signals compile to frozen multi-leg `OrderIntent` packages;
  - portfolio position matrices compile to per-symbol market delta packages;
  - package metadata exposes target units, input mode, order count and engine.
- Tested:
  - native event explicit order route remains unchanged;
  - Nautilus explicit order route works for market and GTC limit replay;
  - native-vs-Nautilus market replay parity smoke;
  - Nautilus DCA/grid structured package smoke;
  - Nautilus bracket/OCO sibling cancellation smoke;
  - Nautilus basket package smoke;
  - Nautilus portfolio matrix package smoke;
  - report bundle explicit-order manifest fields;
  - full internal tests excluding real-data scripts.

Future directions / do not treat as completed:

- Nautilus adapter depth:
  - dynamic in-Nautilus DCA/grid state management;
  - exchange-native OCO/bracket order-list semantics beyond current
    package-strategy sibling cancellation;
  - exchange queue priority, latency, partial-fill and order-book simulation;
  - all-or-none basket package semantics;
  - deeper portfolio-margin replication beyond diagnostics.
- Arbitrage and portfolio engine depth:
  - continue native ArbitrageBacktestEngine validation and Nautilus adapter
    compatibility;
  - expand multi-leg package testing on realistic basis/stat-arb/basket data;
  - promote experimental basket/portfolio Nautilus package routes only after
    real-strategy parity audits.

Branch note:

- The `feat/nautilus-explicit-orders` work has been merged into `dev`.
- New unrelated upgrades should branch from or be committed on `dev` according
  to the current task scope.
- Do not resurrect old feature-branch assumptions when reading the Phase 5.2
  design notes.

## Phase 5.3 - Native Arbitrage And Portfolio Engine Depth

Purpose:

Harden the native arbitrage / portfolio domain layer before adding deeper
Nautilus execution simulation. Native engines must first be trusted as the
transparent research/accounting source of truth.

### Phase 5.3A - Native Arbitrage Domain Audit And Golden Invariants

Scope:

- Add reusable audit helpers for arbitrage results:
  - package PnL residual vs equity delta;
  - leg PnL sum vs package PnL;
  - leg fee sum vs result fee series;
  - target-unit symbols and final flattening;
  - rejection-report presence and package execution policy visibility.
- Add native event vs native vectorized comparison helper:
  - equity max diff;
  - position max diff;
  - package target-unit max diff;
  - package PnL residual max diff;
  - pass/fail status with tolerances.
- Add mock domain tests for representative executable specs:
  - basis;
  - calendar spread;
  - funding arbitrage;
  - index basket package.
- Keep endpoint behavior unchanged.

Acceptance:

- Audit helpers pass on known-good native event/vectorized mock arbitrage runs.
- Audit helpers fail loudly on intentionally corrupted package PnL residuals.
- Existing arbitrage endpoints and Nautilus package validation remain unchanged.
- Full internal tests pass excluding real-data scripts.

### Phase 5.3B - Portfolio And Real-Strategy Stabilization

Scope:

- Audit `PortfolioBacktestEngine` modes:
  - `longshort`;
  - `market_neutral`;
  - `directional`;
  - `equal_weight`.
- Add portfolio diagnostics for:
  - target-unit matrix vs accepted positions;
  - gross/net exposure;
  - margin usage;
  - per-symbol fee/funding contribution;
  - liquidation / rejection visibility.
- Run realistic mock and real-strategy validation for:
  - basis/stat-arb;
  - basket/pair;
  - multi-symbol portfolio.
- Promote support matrix statuses only after parity/audit evidence is present.

Implemented:

- Added portfolio-level diagnostic reports to `MultiSymbolPortfolio` metadata:
  - target units;
  - accepted units;
  - target notional;
  - accepted notional;
  - exposure / margin usage;
  - per-symbol mark/funding/fee PnL attribution;
  - rebalance rejection / mismatch report;
  - fee and turnover series / totals.
- Added `build_portfolio_domain_audit(result)`:
  - accepted-position PnL vs equity delta reconciliation;
  - per-symbol fee vs portfolio fee-series reconciliation;
  - accepted notional vs units × close × contract-size reconciliation;
  - long/short/gross/net exposure identity checks;
  - rebalance mismatch count and notional visibility.
- Added domain tests for:
  - `longshort` accounting reconciliation;
  - `market_neutral` long/short notional balancing;
  - `directional` dominant-leg selection;
  - `equal_weight` active-notional equalization;
  - margin-gate rejection visibility;
  - intentional corrupted PnL report failure.
- Added an executable institutional simulation matrix for:
  - multi-symbol portfolio accounting and exposure audit;
  - native explicit limit/market order fill prices and flattening;
  - Nautilus bracket/OCO package fill plus sibling cancellation;
  - basis arbitrage native event vs native vectorized parity and audit.
- Vectorized the heaviest diagnostics assembly paths:
  - per-symbol PnL report construction avoids per-bar Python row appends;
  - rebalance mismatch report uses masked stack extraction.
- Exported the portfolio audit helper through `quantbt.reporting` and the
  public `quantbt` namespace.

Validation:

- `quantbt/tests/test_phase5_3_portfolio_audit.py` passes.
- `quantbt/tests/test_phase5_3_institutional_simulations.py` passes.
- Full internal test suite passes excluding real-data scripts.
- Real scripts `test_real.py` and `test_real_endpoints.py` execute successfully
  as scripts; they do not expose pytest test functions.

Current conclusion:

- Phase 5.3 native portfolio / arbitrage audit layer is usable for controlled
  research validation:
  - mock multi-symbol portfolio, explicit order, Nautilus bracket/OCO, and
    basis-arbitrage simulations now pass deterministic domain checks;
  - native portfolio accounting exposes enough diagnostics to explain accepted
    positions, rejected target deltas, fees, notional exposure, and margin usage;
  - native arbitrage event/vectorized parity is covered by audit helpers and
    mock package tests.
- Do **not** mark this as final production certification for all strategy
  families yet:
  - real multi-symbol alpha notebooks still need archived audit bundles;
  - Nautilus portfolio/arbitrage parity is still experimental for package
    workflows;
  - exchange queue, partial-fill, portfolio-margin, and order-book depth are
    intentionally out of scope for 5.3.

Remaining debt before promoting portfolio support beyond native research use:

- Run real multi-symbol portfolio notebooks / service strategies and archive
  audit bundles for representative basket, pair, and multi-symbol alpha cases.
- Add Nautilus parity/audit for portfolio package replay once deeper
  multi-symbol Nautilus validation is scheduled.
- Add exchange-native portfolio-margin replication only if a venue-specific
  production requirement appears; current logic remains transparent cross-margin
  buying-power gating, not Binance portfolio-margin clone.
- Add explicit liquidation attribution rows if liquidated portfolio audit needs
  strict per-symbol reconciliation through the liquidation bar.

Non-goals for 5.3:

- Deep Nautilus queue/latency/order-book modeling.
- Exchange-native portfolio-margin replication.
- New schema-only arbitrage engines for cross-exchange, triangular, or options
  vol arbitrage.

## Phase 5.4 - Nautilus Adapter Depth

Purpose:

Move Nautilus validation from simple package replay toward institutional
execution semantics without breaking existing endpoint behavior.

This work must stay opt-in and auditable. Existing signal, explicit-order,
DCA/grid, bracket/OCO, basket, portfolio, and arbitrage endpoints must continue
to behave as they do today unless a new depth policy is explicitly passed.

### Phase 5.4A - Execution-Depth Preflight And Package Semantics

Scope:

- Add a deterministic preflight layer for `OrderIntent` packages before deeper
  Nautilus execution:
  - high/low touch checks for limit/stop orders;
  - latency-bar shifting;
  - simple queue-ahead and volume participation cap;
  - optional partial-fill simulation;
  - reduce-only capping to current simulated position;
  - exchange-like OCO sibling cancellation after the first exit fill;
  - all-or-none package rejection for basket/arbitrage package groups.
- Keep the layer dependency-free from Nautilus so it can be tested quickly and
  reused by native audits.
- Export the config/result helpers publicly, but do not enable them by default
  in existing endpoints.

Acceptance:

- Mock package tests prove:
  - all-or-none basket rejects every leg when one leg cannot fill;
  - best-effort package can keep valid fills;
  - partial-fill quantity respects volume participation and queue-ahead;
  - reduce-only exit cannot over-close the simulated position;
  - OCO sibling is canceled after TP/SL fill;
  - latency shifts effective execution bars.
- Full internal tests pass.

Status:

- Implemented `NautilusExecutionDepthConfig`,
  `PackageDepthPreflightResult`, and
  `simulate_nautilus_order_package_depth(...)`.
- Added deterministic domain tests for all acceptance bullets above.
- Documented opt-in usage in `docs/nautilus_backend.md` and
  `docs/endpoint.md`.
- Existing endpoints are unchanged by default.
- Validation:
  - `test_phase5_4_nautilus_depth.py` passes;
  - targeted endpoint/Nautilus regression passes;
  - full internal tests pass excluding real-data scripts;
  - `test_real.py` and `test_real_endpoints.py` execute successfully as
    scripts.

### Phase 5.4B - Deep Nautilus Adapter Integration And Parity Artifacts

Scope:

- Wire Phase 5.4A preflight into Nautilus package endpoints as an optional
  parameter / config path:
  - reject all-or-none package groups before Nautilus submission;
  - annotate package reports with preflight accepted/rejected/canceled/partial
    diagnostics;
  - preserve raw Nautilus reports separately from preflight diagnostics.
- Upgrade dynamic DCA/grid validation:
  - activate safety/exit orders from package state rather than submitting every
    possible order blindly at package start;
  - cap reduce-only TP/SL exits to filled ladder quantity;
  - document same-bar ambiguity policy.
- Upgrade parity artifacts:
  - portfolio package native-vs-Nautilus order/fill/equity comparison;
  - arbitrage package native-vs-Nautilus comparison;
  - known policy-difference classifier.

Non-goals for Phase 5.4:

- True order-book queue modeling from tick-level L2 data.
- Cross-exchange latency arbitrage.
- Portfolio-margin exact clone of any venue.
- Replacing native vectorized/event backends for optimizer workloads.

Status:

- Implemented optional endpoint wiring for `nautilus_depth_config`:
  - `QuantBTEndpoint.nautilus_dca_grid(...)`;
  - `QuantBTEndpoint.nautilus_bracket_orders(...)`;
  - `QuantBTEndpoint.basket(backend="nautilus", ...)`;
  - `QuantBTEndpoint.portfolio(backend="nautilus", ...)`;
  - `QuantBTEndpoint.arbitrage(..., backend="nautilus")`.
- Existing endpoints remain unchanged when `nautilus_depth_config=None`.
- Added preflight metadata to Nautilus package results:
  - `nautilus_depth_enabled`;
  - `nautilus_depth_order_report`;
  - `nautilus_depth_package_report`;
  - `nautilus_depth_metadata`;
  - `order_count_before_depth`;
  - `order_count_after_depth`.
- Added empty flat result path for packages fully rejected by preflight before
  Nautilus submission.
- Added `build_nautilus_depth_parity_summary(result)` for package-level
  preflight-vs-Nautilus count audit.
- Added endpoint integration tests for:
  - structured DCA all-or-none reject before Nautilus;
  - bracket/OCO preflight filtering and sibling cancellation before Nautilus;
  - basket package all-or-none metadata annotation and depth reports.
- Added debt-domain validation tests for:
  - DCA/grid lifecycle state: base fill, safety fill, untouched safety reject,
    reduce-only TP cap to filled ladder quantity, OCO SL cancellation;
  - queue/depth behavior: explicit `depth_model="ohlcv_volume_cap"` and
    volume participation minus queue-ahead sizing;
  - package fill-price / quantity parity artifact pass and intentional failure.
- Added `build_nautilus_depth_execution_report(result)` for row-level
  depth-preflight vs Nautilus package fill-price/quantity comparison.
- Validation:
  - `test_phase5_4_endpoint_depth.py` and `test_phase5_4_nautilus_depth.py`
    pass;
  - `test_phase5_4_debt_domain_validation.py` passes;
  - endpoint/Nautilus targeted regression passes;
  - full internal tests pass excluding real-data scripts;
  - `test_real.py` and `test_real_endpoints.py` execute successfully as
    scripts.

Remaining debt:

- Dynamic DCA/grid is still preflight-mediated, not a full Nautilus in-strategy
  state machine with progressive order activation.
- Queue/latency/depth is deterministic OHLCV-level approximation, not true L2
  order-book simulation. This is now explicitly visible as
  `depth_model="ohlcv_volume_cap"` in metadata and covered by tests.
- Portfolio/arbitrage package parity now has row-level fill-price/quantity
  artifacts, but real package runs and saved stakeholder bundles are still
  required before calling it production-certified.

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

The first two endpoint names are now experimental public convenience routes.
They compile into explicit `OrderIntent` packages, then reuse the
already-supported Nautilus explicit-order replay path.

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

Status:

- Implemented `export_nautilus_report_bundle(...)` in the public reporting
  namespace.
- Export bundle supports:
  - `equity_curve.csv`;
  - `returns.csv`;
  - raw account/order/fill/position CSV reports where present;
  - normalized `trade_log.csv`;
  - bounded `fill_log.txt`;
  - `metrics_summary.json`;
  - `run_manifest.json`;
  - clean `config.json`;
  - optional `quantstats_daily.html`.
- Config/export behavior now records applied account, leverage, sizing, fee,
  slippage, funding, instrument, and timeframe fields without confusing
  duplicate fee/sizing keys.
- QuantStats policy supports daily resampling and configurable
  `quantstats_periods_per_year`, with crypto default 365.
- Fill/order logs are opt-in and bounded through endpoint/report parameters.
- This phase remains a reporting/evidence layer only; it does not add alpha
  logic inside Nautilus and does not alter native engine accounting.

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

Status:

- Implemented `benchmarks/run_phase7.py` stdlib CLI.
- Profiles:
  - `smoke`;
  - `standard`;
  - `large`.
- Backends measured:
  - `native_vectorized`;
  - `native_event`;
  - `portfolio_legacy`;
  - optional `nautilus` with `--include-nautilus`.
- Captures:
  - bars x symbols;
  - generated signal transitions;
  - explicit order count;
  - event count;
  - warmup / first-run time;
  - repeated runtime;
  - `tracemalloc` peak memory;
  - RSS delta where available;
  - throughput and threshold pass/fail.
- Added `benchmarks/phase7_thresholds.json`.
- Added committed benchmark summary at `benchmarks/phase7_report.md`.
- Latest local run:
  - smoke profile passes native thresholds;
  - standard profile: `portfolio_legacy` passes, while `native_vectorized` and
    `native_event` exceed current threshold guardrails on this machine.

Conclusion:

- Do not jump to Cython/C++ yet.
- Profiling follow-up implemented:
  - `benchmarks/profile_phase7.py`;
  - committed summary at `benchmarks/phase7_profile_report.md`;
  - local JSON/Markdown artifacts under `benchmarks/out/`.
- Standard profile decomposition:
  - `native_vectorized`:
    - target sizing is the largest bucket;
    - data normalization and pandas-to-ndarray packing are secondary;
    - pure `_engine_units_v2` Numba kernel is about 1.3% of measured backend
      layer runtime.
  - `native_event`:
    - order-array construction is the largest bucket;
    - data normalization and market ndarray packing are secondary;
    - pure `_engine_event_v1` Numba kernel is about 1.3% of measured backend
      layer runtime.
- Optimization priority:
  - cache aligned market arrays for repeated optimizer/WFO runs;
  - move `signal_notional` sizing to ndarray/Numba or reusable array caches;
  - pre-map/order-cache explicit order arrays when orders are unchanged;
  - separate runtime thresholds from `tracemalloc` memory instrumentation.
- Cython/C++ escalation is **not justified** yet because the pure kernels are
  not the bottleneck.

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

Status:

- Added `docs/README.md` as the documentation map.
- README now points users to the correct doc by task:
  - endpoint contract;
  - backend selection;
  - vectorized vs event-driven;
  - margin/leverage;
  - order fill policies;
  - Nautilus validation;
  - pair/basket;
  - walk-forward methodology;
  - examples index.
- Added `examples/README.md` as the runnable example map.
- Added minimal examples for:
  - single explicit order;
  - DCA/grid ladder;
  - multi-symbol portfolio;
  - pair/basket package;
  - basis arbitrage;
  - walk-forward train/test split;
  - Nautilus validation;
  - Nautilus explicit order parity.
- Polished pair/basket guide to match current package preflight and Nautilus
  validation status.

---

## Phase 9 - Safe Performance Optimization After Profiling

Purpose:

Optimize the measured Phase 7 bottlenecks without changing domain logic,
accounting, fill policy, or public endpoint behavior.

Profiling evidence:

- `native_vectorized` bottleneck:
  - target sizing for `signal_notional`;
  - data normalization / pandas packing.
- `native_event` bottleneck:
  - `OrderIntent` -> kernel order-array construction.
- Pure Numba simulation kernels are not the bottleneck yet.

### Phase 9A - Fast `signal_notional` Target Sizing

Scope:

- Add ndarray/Numba sizing path for `signal_notional`.
- Keep existing Series-based `compute_target_units(...)` public behavior.
- Use the fast path only inside native vectorized backend when the mode is
  exactly `signal_notional` / `signal`.
- Preserve `use_pyramiding=False` semantics by snapping signal to sign.

Domain invariant:

```text
On signal transition: units = signal * alloc / close_at_transition
Between transitions: units are frozen
Flat signal: units = 0
```

Acceptance:

- Fast target-unit matrix equals legacy Series sizing for:
  - long/flat;
  - short/flat;
  - fractional pyramiding;
  - `use_pyramiding=False`;
  - multiple symbols with per-symbol alloc.
- Full `BacktestEngineV2(native_vectorized)` equity/positions are unchanged
  before vs after fast path.

### Phase 9B - Native Event Order Array Compiler

Scope:

- Add an internal order compiler that converts `OrderIntent` sequences into
  contiguous kernel arrays.
- Replace repeated per-order timestamp conversion with vectorized nanosecond
  `searchsorted`.
- Preserve original order index, stable ordering, enum mapping, TIF mapping,
  and unsupported-order behavior.
- Do not change `_engine_event_v1`.

Domain invariant:

```text
Same input orders + same bars -> same order_report, fills, positions, equity
```

Acceptance:

- Compiled arrays equal the previous Python construction for market and limit
  orders.
- Full `BacktestEngineV2(native_event)` equity, fills, and order_report are
  unchanged.
- Invalid symbols, timestamps after data, unsupported order types, and TIF
  behavior still fail the same way.

### Cache Safety Rules

- No process-wide mutable result cache.
- Numba function cache is allowed only for pure ndarray kernels.
- Any reusable prepared arrays must be local to an engine/run or keyed by a
  clear signature:
  - length;
  - first/last timestamp;
  - dtype;
  - shape;
  - symbols tuple;
  - optional content hash for safe/debug mode.
- Never cache by mutable pandas object identity alone.
- Mutating input data between runs must not reuse stale arrays.

### Phase 9C - Parity Script

Add a script that runs legacy-vs-fast comparison on deterministic mock data:

- target-unit max diff;
- vectorized equity max diff;
- vectorized position max diff;
- order-array max diff;
- event order_report diff;
- event equity max diff;
- event fill count and fill-price diff.

The script must print and write a small JSON/Markdown report so future agents
can verify that speed changes did not alter strategy meaning.

Status:

- Phase 9A implemented:
  - added `sizing/fast.py`;
  - native vectorized `signal_notional` uses ndarray/Numba target sizing;
  - public Series sizing APIs remain unchanged.
- Phase 9B implemented:
  - added `core/order_compiler.py`;
  - native event backend uses compiled order arrays with vectorized timestamp
    mapping;
  - `_engine_event_v1` is unchanged.
- Phase 9C implemented:
  - added `benchmarks/compare_phase9_parity.py`;
  - added `PreparedMarketArrays` and explicit market-data signatures;
  - native event accepts optional prepared market arrays and compiled orders
    with signature validation;
  - `run_phase7.py` supports `--no-tracemalloc` to separate runtime from memory
    tracing;
  - committed parity report at `benchmarks/phase9_parity_report.md`;
  - committed optimization report at `benchmarks/phase9_optimization_report.md`.
- Parity result:
  - target units diff: 0.0;
  - vectorized equity/position diff: 0.0;
  - order-array diff: 0.0;
  - event equity/order_report/fill diff: 0.0.
  - prepared event reuse equity/order_report/fill diff: 0.0.
- Standard runtime benchmark after Phase 9C:
  - `native_vectorized` runtime 0.306991s and passes threshold;
  - `native_event` runtime 0.793388s and improves but still fails the strict
    order-count threshold;
  - `portfolio_legacy` runtime 0.688006s and passes threshold.
- Remaining safe optimization targets:
  - reduce remaining pandas normalization overhead.

---

## Phase 10 - Native Event Prepared Replay And Portfolio Engine Direction

Purpose:

- Convert Phase 9 prepared arrays from an internal optimization into a clear
  higher-level replay pattern for WFO/service loops.
- Clarify that `legacy_portfolio` is a compatibility baseline, not the final
  portfolio architecture.

### Phase 10A - Native Event Prepared Replay

Scope:

- Expose `NativeEventBackend.prepare_market_arrays(...)`.
- Expose `NativeEventBackend.compile_orders(...)`.
- Add `native_event_prepared` to the Phase 7 benchmark suite.
- Keep `_engine_event_v1` unchanged.
- Keep normal `BacktestEngineV2(native_event)` behavior unchanged.

Domain invariant:

```text
Same market tape + same explicit orders -> same equity, positions, fills,
and order_report whether arrays are prepared internally or supplied by caller.
```

Status:

- Implemented helper preparation APIs with datetime/symbol signature guards.
- Added parity tests for helper-prepared arrays and compiled orders.
- Added `native_event_prepared` benchmark route.
- Latest standard benchmark:
  - `native_event` cold path: 0.879406s, still fails strict cold threshold;
  - `native_event_prepared`: 0.346367s, 72k+ orders/s, passes prepared replay
    threshold;
  - parity tests remain exact.

Usage guidance:

- Use cold `native_event` for one-off explicit-order simulation.
- Use prepared replay when a WFO/optimizer/service replays many order packages
  over the same market tape.
- Do not use mutable global caches. Prepared arrays must be passed explicitly
  and validated by signature.

### Phase 10B - Native Portfolio Engine Direction

Historical decision before Phase 11E:

- `legacy_portfolio` remained the default compatibility route while the native
  portfolio engine was still under construction.
- We do **not** have to reuse it forever.
- A new `NativePortfolioEngine` is the right long-term direction, but it must be
  delivered as a separate domain phase with golden tests before becoming the
  default. Phase 11E completed this default switch for supported portfolio
  modes/sizing.

Why not replace immediately:

- Current `MultiSymbolPortfolio` carries established behavior for:
  - `longshort`;
  - `market_neutral`;
  - `directional`;
  - `equal_weight`;
  - Binance-style netting options;
  - portfolio-level diagnostics;
  - funding, margin, and liquidation reporting expected by existing alpha
    notebooks.
- Rewriting this path without a golden parity suite risks changing strategy
  meaning silently.

Recommended next portfolio phase:

- Build `NativePortfolioEngine` as array-first, explicit-schema code.
- Keep `legacy_portfolio` as the oracle during development.
- Golden tests must cover:
  - per-symbol target units;
  - portfolio gross/net exposure;
  - rebalance timing;
  - no bar-by-bar unwanted resizing when strategy expects frozen units;
  - fees, funding, leverage, margin, liquidation;
  - all current portfolio modes;
  - real alpha parity reports.
- Only switch endpoint defaults after parity is understood and documented.

---

## Phase 11 - Portfolio Engine V3 Institutional Upgrade

Goal:

Build a fund-grade portfolio engine that is mathematically explicit,
domain-correct, fast, and auditable.  `legacy_portfolio` remains the
compatibility oracle until the native engine has passed golden parity and real
strategy validation.

### Phase 11A - Domain Spec, Capability Matrix, And Golden Parity

Scope:

- Define a portfolio domain contract independent of `MultiSymbolPortfolio`.
- Freeze the behavior of existing modes before writing the new engine:
  - `longshort`;
  - `market_neutral`;
  - `directional`;
  - `equal_weight`.
- Declare current legacy sizing support:
  - `signal_notional`;
  - `signal`;
  - `notional`;
  - `unit`.
- Declare native portfolio roadmap sizing support:
  - `signal_notional`;
  - `signal`;
  - `notional`;
  - `unit`;
  - `%_equity`;
  - `target_weight`;
  - `target_notional`;
  - `target_units`;
  - `fixed_notional`;
  - `gross_exposure`;
  - `net_exposure`;
  - `dca_ladder`.
- Add contract validation on completed portfolio results:
  - accounting audit must pass;
  - metadata mode/sizing must match spec;
  - target/accepted unit reports must exist;
  - symbol PnL must reconcile to equity;
  - exposure identities must reconcile;
  - margin columns must exist;
  - mode-specific invariants must hold.

Mode-specific invariants:

- `market_neutral`: active bars must have balanced long and short notional.
- `directional`: at most one symbol can be active per bar after directional
  selection.
- `equal_weight`: active symbols must carry equal absolute notional.
- `longshort`: raw signed target matrix is preserved except for margin gates.

Status:

- Implemented `core/portfolio.py`:
  - `PortfolioDomainSpec`;
  - `PortfolioMode`;
  - `PortfolioSizingMode`;
  - `PortfolioRebalancePolicy`;
  - `portfolio_capability_matrix()`;
  - `validate_portfolio_result_contract(...)`.
- Exported the domain contract through `quantbt`.
- Added `tests/test_phase11_portfolio_engine_spec.py`.
- Phase 11A tests pass.

### Phase 11B - NativePortfolioEngine Core

Scope:

- Add `backend="native_portfolio"` without changing the default endpoint.
- Keep `legacy_portfolio` as the oracle.
- Implement array-first core:
  - input alignment to ndarray once;
  - signal/position matrix -> target exposure;
  - target exposure -> target units;
  - target units -> trade deltas;
  - fees/slippage/funding;
  - per-symbol PnL;
  - gross/net exposure;
  - initial margin / maintenance margin;
  - liquidation scan;
  - attribution reports.
- Use NumPy/Numba in hot paths only after behavior is locked.
- No mutable global cache. Prepared arrays must be explicit and signature
  guarded.

Acceptance:

- Native result matches legacy for all Phase 11A legacy-compatible modes and
  sizing modes within documented tolerances.
- New sizing modes have direct mathematical tests, not just smoke tests.
- Existing endpoints remain unchanged unless `backend="native_portfolio"` is
  explicitly requested.

Status:

- Implemented `backends/native_portfolio.py`:
  - explicit `NativePortfolioBackend`;
  - `NativePortfolioConfig`;
  - array-first market/signal packing;
  - NumPy portfolio-mode transforms;
  - `_engine_portfolio` kernel execution for exact legacy parity;
  - V2 result construction with exposure, symbol PnL, margin, turnover, fee,
    target/accepted units, and contract validation reports.
- Wired `PortfolioBacktestEngine(backend="native_portfolio")`.
- Default backend remains `legacy_portfolio`.
- Added `tests/test_phase11_native_portfolio_backend.py`.
- Phase 11B supports legacy-compatible sizing modes:
  - `signal_notional`;
  - `signal`;
  - `notional`;
  - `unit`.
- Roadmap sizing modes such as `%_equity`, `target_weight`, `target_notional`,
  `target_units`, `gross_exposure`, `net_exposure`, and `dca_ladder` remain
  explicit Phase 11C+ work and raise instead of silently approximating behavior.
- Added Phase 7 benchmark route `native_portfolio`.
- Standard benchmark after Phase 11B:
  - `portfolio_legacy`: 0.675597s, 1.351193 sec/million bar-symbols, pass;
  - `native_portfolio`: 0.819805s, 1.639610 sec/million bar-symbols, pass.
- Interpretation: native portfolio is not intended to beat legacy in Phase 11B;
  it pays extra report/contract validation overhead to become an auditable
  backend. Speed optimization comes after Phase 11C validates all new sizing
  modes and real strategies.

### Phase 11C - Institutional Validation And Default Readiness

Scope:

- Run mock-domain tests:
  - flat;
  - long-only;
  - short-only;
  - long/short;
  - market-neutral rebalance;
  - equal-weight rebalance;
  - price drift without signal change;
  - missing data;
  - fee/funding;
  - leverage and buying power;
  - margin rejection;
  - liquidation.
- Run real-strategy smoke/parity notebooks where available.
- Benchmark:
  - bars x symbols;
  - rebalance count;
  - memory;
  - compile time vs runtime;
  - legacy vs native speed.
- Document migration rules from `legacy_portfolio` to `native_portfolio`.

Acceptance:

- No endpoint default change until real alpha parity is reviewed.
- If native improves legacy behavior intentionally, the improvement must be
  named and tested.

Status:

- Implemented additional exact native portfolio sizing modes:
  - `target_units`: input matrix is explicit target contracts/units;
  - `target_notional`: input matrix is signed notional and respects
    `contract_size`;
  - `fixed_notional`: signal multiplied by `alloc_per_trade`, then converted to
    units with `close * contract_size`.
- Kept equity-dependent sizing modes unsupported until an equity-aware
  portfolio kernel exists:
  - `%_equity`;
  - `target_weight`;
  - `gross_exposure`;
  - `net_exposure`.
- Kept `dca_ladder` out of portfolio target-matrix sizing because it requires
  intrabar high/low trigger-price fills.
- Added `NATIVE_PORTFOLIO_SUPPORTED_SIZING_MODES` and `native_supported` to
  `portfolio_capability_matrix()`.
- Fixed native portfolio symbol PnL fee allocation so force-flat liquidation
  does not create a fake trade fee when the kernel did not charge one.
- Added `tests/test_phase11_portfolio_institutional_scenarios.py` covering:
  - flat book;
  - long-only;
  - short-only;
  - long/short;
  - missing data;
  - fee/funding reconciliation;
  - leverage buying-power gate;
  - margin rejection;
  - liquidation audit.
- Added formula tests for `target_units`, `target_notional`, and
  `fixed_notional`.
- Standard benchmark after Phase 11C:
  - `portfolio_legacy`: 0.636433s, 1.272866 sec/million bar-symbols, pass;
  - `native_portfolio`: 0.776710s, 1.553421 sec/million bar-symbols, pass.

### Phase 11D - Nautilus Portfolio Validation

Scope:

- Use Nautilus as third-party event-driven execution trustee for portfolio
  packages.
- Compile native portfolio rebalance deltas into explicit order packages.
- Validate:
  - order count;
  - fill count;
  - fill price policy;
  - fee convention;
  - gross/net exposure path;
  - final equity;
  - drawdown and account timeline.
- Cover:
  - single-symbol portfolio subset;
  - multi-symbol longshort;
  - market-neutral package;
  - basket-like target units;
  - all-or-none package semantics where possible.

Non-goals:

- Exact venue-specific portfolio margin clone unless a production venue
  requires it.
- L2 queue/depth perfect simulation inside portfolio V3. That belongs to the
  Nautilus/depth roadmap.

Acceptance:

- Native-vs-Nautilus validation bundle is generated for representative
  portfolio scenarios.
- Nautilus remains validation/oracle backend, not the optimizer hot path.

Status:

- Implemented `reporting/portfolio_nautilus.py`:
  - `build_portfolio_nautilus_position_report(...)`;
  - `build_portfolio_nautilus_validation_report(...)`.
- Exported helpers through `quantbt.reporting` and top-level `quantbt`.
- Updated `QuantBTEndpoint.portfolio(backend="nautilus", ...)`:
  - first runs `backend="native_portfolio"` as the native reference;
  - compiles Nautilus package orders from native `target_units_report`;
  - applies portfolio transforms (`market_neutral`, `directional`,
    `equal_weight`) before Nautilus validation;
  - attaches `portfolio_nautilus_validation_report` to result metadata.
- Added Phase 11D validation tests:
  - matching native-vs-Nautilus package summary passes;
  - position mismatch is detected;
  - endpoint Nautilus portfolio route submits market-neutral transformed target
    units, not raw signals.

Remaining Phase 11D validation work:

- Run real Nautilus portfolio packages with installed `nautilus-trader` and
  archive report bundles.
- Add deeper fill-price/equity tolerance profiles for exchange-like fee/slippage
  settings.
- Add all-or-none basket package parity once venue/package semantics are needed
  for production portfolio workflows.

### Phase 11E - Native Portfolio Default And Full Surface Completion

Scope:

- Complete native portfolio support for the previously missing fund-grade
  sizing/mode surface:
  - `%_equity`;
  - `target_weight`;
  - `gross_exposure`;
  - `net_exposure`;
  - `risk_parity`;
  - `beta_neutral`.
- Keep `dca_ladder` out of portfolio native sizing because it requires intrabar
  high/low trigger-price fills and belongs to the DCA/grid engine.
- Switch portfolio defaults only after parity and domain tests pass.

Status:

- Added native equity-aware portfolio kernel:
  - `%_equity`: `signal * alloc_per_trade * live_equity`;
  - `target_weight`: `signal * live_equity`;
  - `gross_exposure`: signed signal normalized to
    `live_equity * alloc_per_trade` gross exposure;
  - `net_exposure`: signed signal normalized to
    `live_equity * alloc_per_trade` net exposure.
- Added native-only portfolio modes:
  - `risk_parity`: inverse rolling volatility allocation from close returns,
    controlled by `risk_lookback` (default `60`);
  - `beta_neutral`: beta-weighted neutralization using optional
    `betas={symbol: beta}`, default `1.0`.
- Changed defaults:
  - `QuantBTEndpoint.portfolio(...)` defaults to `backend="native_portfolio"`;
  - `PortfolioBacktestEngine(...)` defaults to `backend="native_portfolio"`;
  - `backend="legacy_portfolio"` remains available for reproduction.
- Added `tests/test_phase11_native_portfolio_full_surface.py`.
- Updated `benchmarks/run_portfolio_real_parity.py` and
  `benchmarks/portfolio_real_parity_report.md`.

Validation:

- Legacy-compatible parity:
  - 16/16 cases pass;
  - max equity diff = 0;
  - max position diff = 0;
  - max target units diff = 0;
  - max accepted notional diff = 0.
- Native-only domain checks:
  - `target_units`;
  - `target_notional`;
  - `fixed_notional`;
  - `%_equity`;
  - `target_weight`;
  - `gross_exposure`;
  - `net_exposure`;
  - `risk_parity`;
  - `beta_neutral`.
- `dca_ladder` is explicitly rejected for native portfolio.

---

## Phase 12 - Production Certification, Benchmark Follow-Up, And Real Validation

Goal:

Close the remaining production-certification gaps across arbitrage, benchmark
optimization evidence, and Nautilus portfolio validation. This phase is split
into two implementation phases only.

### Phase 12A - Arbitrage Production Certification

Status: completed in `benchmarks/run_phase12_arbitrage_cert.py`.

Validation artifacts:

- `benchmarks/phase12_arbitrage_cert.json`
- `benchmarks/phase12_arbitrage_cert.md`
- `tests/test_phase12_arbitrage_certification.py`

Latest certification summary:

- Native basis perp/quarterly event vs vectorized parity: pass.
- Basis package domain audit: pass.
- Stat-arb pair accounting parity: pass for equity/positions/target units.
- Index basket package smoke: pass.
- Cross-exchange, triangular, and options-vol guardrails: pass as explicit
  specialized-engine `NotImplemented` paths.
- Nautilus package smoke: pass with supported Binance test instruments. This
  validates adapter package replay, not a real quarterly venue model.

Remaining debt:

- Stat-arb pair should eventually emit the same `package_pnl_report` residual
  artifact as basis/index-basket routes.
- Real exchange quarterly/perpetual basis parity requires a Nautilus instrument
  provider or adapter extension for delivery futures.
- Cross-exchange, triangular, and options-vol arbitrage remain schema-safe,
  specialized-engine future work.

Scope:

- Use `/root/bobby/pool_alpha/Arbops/binance_basis_arb` only as a read-only
  reference alpha.
- Copy a local sandbox into
  `.local_arbitrage_sandboxes/binance_basis_arb/` and keep it git-ignored.
- Do not commit the copied alpha source, data, ML artifacts, or private reports.
- Add realistic basis/stat-arb/basket package simulations for QuantBT:
  - perp vs quarterly basis with unit-equal sizing;
  - funding on the perpetual leg and zero funding on the quarterly leg;
  - synthetic spread convergence and adverse divergence;
  - basket/index package smoke;
  - native event vs native vectorized parity;
  - optional Nautilus package parity when `nautilus-trader` is installed.
- Keep cross-exchange, triangular, and options-vol arbitrage schema-safe but
  non-executable unless specialized engines are explicitly implemented.

Acceptance:

- A production-certification script writes JSON/Markdown artifacts:
  - native event/vectorized final equity diff;
  - max equity diff;
  - fill/order count;
  - funding/fee totals;
  - audit pass/fail;
  - schema-only spec rejection status.
- Tests cover realistic package behavior without depending on private Arbops
  internals.
- Optional Nautilus execution is skipped cleanly when the dependency or venue
  support is unavailable.

### Phase 12B - Benchmark Follow-Up And Nautilus Portfolio Certification

Status: completed in `benchmarks/run_phase12_benchmark_nautilus_cert.py`.

Validation artifacts:

- `benchmarks/phase12_benchmark_nautilus_cert.json`
- `benchmarks/phase12_benchmark_nautilus_cert.md`
- `tests/test_phase12_benchmark_nautilus_cert.py`

Latest certification and optimization summary:

- Native portfolio benchmark separates full facade, array preparation, pure
  Numba kernel, and report-construction residual.
- `NativePortfolioBackend.prepare_market_arrays(...)` and
  `prepare_signal_matrix(...)` now provide explicit prepared-cache APIs for
  WFO/service loops. Reuse is guarded by datetime/symbol signatures, not pandas
  object identity.
- `NativePortfolioBackend.run_signals(...)` accepts `market_arrays` and
  `raw_signal_matrix` so repeated portfolio runs can skip pandas market
  normalization while preserving the same accounting kernel.
- Native portfolio `notional` and `unit` sizing now use ndarray vector paths
  instead of per-symbol pandas sizing dispatch. Legacy parity tests still pass.
- Native portfolio report construction was tightened by building common
  DataFrames directly from ndarray blocks and by generating `symbol_pnl_report`
  in one vectorized construction rather than per-symbol concat.
- Pure Numba kernel share remains about 0.2% in the current Phase 12B profile;
  Cython/C++ is not justified until cached preparation/reporting are optimized.
- Current benchmark artifact reports prepared-cache reuse speedup for the small
  Phase 12B profile. Larger WFO/service loops should benefit more because the
  same market arrays are reused across many strategy parameter trials.
- Real Nautilus portfolio package replay ran and passed the tolerance profile:
  equity tolerance `1.0`, position tolerance `0.005` for venue lot-size
  rounding.
- All-or-none basket package preflight parity passes using the current
  OHLCV-volume-cap depth model.

Remaining debt:

- Thread prepared portfolio market arrays through higher-level WFO endpoint
  loops where the market tape is invariant across parameter trials.
- Continue optimizing native portfolio report construction, which remains the
  measured largest residual bucket after the first vectorized report pass.
- Replace OHLCV queue/depth approximation with true L2/order-book simulation
  only when a production venue data feed is available.

Scope:

- Add a benchmark follow-up script that separates:
  - pure Numba kernel runtime;
  - pandas/data normalization;
  - report construction;
  - full facade runtime.
- Use this to decide whether speed debt is in Numba kernels or Python/reporting
  layers before considering Cython/C++.
- Add real/representative Nautilus portfolio package validation:
  - native portfolio reference;
  - Nautilus package replay;
  - fill-price/equity tolerance profile;
  - all-or-none basket/package preflight parity;
  - saved JSON/Markdown summary.

Acceptance:

- Benchmark report explains remaining optimization targets and whether Cython/C++
  is justified.
- Nautilus portfolio certification report exists and skips gracefully when
  Nautilus is unavailable.
- Existing endpoint defaults and public API remain stable.

---

## Phase 13 - WFO Cache, Portfolio Report, And Arbitrage Certification Cleanup

Goal:

Close the remaining non-Nautilus-depth technical debt before starting another
large high-fidelity Nautilus phase. This phase intentionally avoids true L2
queue simulation, dynamic in-Nautilus DCA/grid state machines, exchange-native
OCO lists, and venue-specific portfolio-margin cloning.

### Phase 13A - WFO Prepared Market Cache Integration

Purpose:

Use the prepared market-array APIs added in Phase 9/10/12 inside higher-level
walk-forward / service loops. When Optuna/WFO evaluates many parameter trials
over the same market tape, QuantBT should not repeatedly normalize pandas data
and pack identical close/high/low arrays.

Scope:

- Audit `_run_walk_forward`, endpoint scoring, native event, and native
  portfolio scoring paths.
- Add a run-local prepared context for one `.backtest(...)` call:
  - prepare market arrays once for invariant `data`, `symbols`, and
    `datetime_index`;
  - pass prepared arrays into endpoint scoring when the backend supports it;
  - validate reuse by datetime/symbol signature, never by mutable pandas object
    identity alone.
- Reuse `NativeEventBackend.prepare_market_arrays(...)` when event/order scoring
  is used.
- Reuse `NativePortfolioBackend.prepare_market_arrays(...)` when portfolio WFO
  scoring is used.
- Reuse `NativePortfolioBackend.prepare_signal_matrix(...)` only when a signal
  matrix is truly invariant; normally only market arrays are invariant across
  trials.
- Keep all caches local to the WFO run. No process-wide mutable result cache.
- Preserve accounting, fill policy, sizing, fees, funding, margin, and
  liquidation semantics exactly.

Acceptance:

- WFO endpoint scoring with and without prepared market arrays produces identical
  metrics and final backtest outputs.
- Portfolio WFO/native portfolio scoring can reuse market arrays across trials
  without stale-data risk.
- Signature mismatch rejects reuse with a clear error.
- Benchmark/mock WFO report shows prepared-cache reuse, parity, and timing so
  future optimization work can separate cache benefit from report/Optuna
  overhead.
- Existing endpoint behavior remains unchanged when prepared arrays are not
  applicable.

Status:

- Implemented run-local WFO prepared scoring cache for
  `target_mode="portfolio"` with endpoint scoring and `native_portfolio`.
- Added `optimization_config["use_prepared_scoring_cache"]`, default `True`,
  stored in `WalkForwardConfig.metadata` for debug/parity runs.
- Cache is scoped to one WFO `.backtest(...)` call and keyed by symbol tuple,
  index length, first timestamp, and last timestamp. Backend signature checks
  still guard prepared reuse.
- Existing non-portfolio endpoint scoring keeps the previous fallback path.
- Added `prepared_scoring_cache` metadata to `result.metadata["walk_forward"]`.
- Added deterministic parity test proving cached and uncached portfolio WFO
  endpoint scoring select the same params, objective, and final equity.
- Added `benchmarks/run_phase13_wfo_cache.py` plus committed JSON/Markdown
  artifacts:
  - `benchmarks/phase13_wfo_cache.json`;
  - `benchmarks/phase13_wfo_cache.md`.
- Current mock report is a parity/reuse guard, not a universal speed claim:
  cache hits occur, but full WFO runtime on the small fixture is still dominated
  by Optuna/report construction. This reinforces Phase 13B as the next
  optimization target.

### Phase 13B - Native Portfolio Report Construction Optimization

Purpose:

Reduce the measured residual report-construction cost after the native portfolio
kernel without changing portfolio domain logic.

Scope:

- Profile and optimize construction of:
  - equity/returns series;
  - position matrix;
  - exposure matrix;
  - target-units and accepted-notional reports;
  - symbol PnL reports;
  - diagnostics metadata.
- Prefer ndarray block construction over per-symbol pandas concat.
- Keep default reports backward-compatible for existing notebooks.
- Add optional report-level controls only if they do not break current endpoint
  behavior.

Acceptance:

- Native portfolio equity, positions, exposure, target units, accepted notional,
  and symbol PnL totals match pre-optimization output exactly or within documented
  floating tolerance.
- Tests cover multi-symbol mock data, missing data, `%_equity`, `target_weight`,
  `gross_exposure`, `risk_parity`, and `beta_neutral`.
- Benchmark report separates kernel runtime from report construction.

Status:

- Optimized native portfolio report construction without changing kernel or
  accounting semantics:
  - funding series now uses ndarray calculations instead of grouping the long
    symbol PnL report;
  - diagnostics rejected-rebalance flags use ndarray diffs directly;
  - returns are built from ndarray equity changes instead of pandas pct-change;
  - exposure report computes leverage/exposure columns array-first;
  - rebalance report uses `np.nonzero` over target-vs-accepted unit diffs
    instead of repeated pandas stack/reindex operations.
- Strengthened prepared-vs-normal native portfolio parity tests for:
  - target units;
  - accepted units;
  - target notional;
  - accepted notional;
  - exposure report;
  - funding series;
  - rebalance report.
- Added old-formula report parity regression in
  `tests/test_phase13_portfolio_report_parity.py`, comparing the optimized
  report surface against the previous pandas formulas for:
  - returns;
  - funding;
  - rejected-rebalance diagnostics;
  - exposure report;
  - rebalance report.
- Re-ran targeted portfolio/report tests and the full internal regression suite
  before Phase 13C; no production report formulas changed after the parity lock.
- Added Phase 13B benchmark artifacts:
  - `benchmarks/run_phase13_portfolio_report.py`;
  - `benchmarks/phase13_portfolio_report.json`;
  - `benchmarks/phase13_portfolio_report.md`.
- Latest benchmark on the standard Phase 13B fixture:
  - full facade: `0.058681s`;
  - prepared reuse: `0.047904s`;
  - pure Numba kernel: `0.000200s`;
  - report construction residual: `0.047671s`;
  - prepared reuse speedup: `1.225x`.
- Conclusion: report construction improved, but remains the dominant residual
  bucket. Cython/C++ is still not justified because pure Numba kernel share is
  only about `0.34%`; further gains should come from optional/lazy heavy reports
  or more compact report-level controls.

### Phase 13C - Arbitrage Production Certification Cleanup

Purpose:

Move native arbitrage from controlled research usability toward clearer
production-certification artifacts without pretending unsupported arbitrage
families are complete.

Scope:

- Add `package_pnl_report` / residual artifact for `StatArbPairSpec`, matching
  the basis/index-basket reporting style:
  - leg PnL;
  - hedge PnL;
  - spread/residual PnL;
  - fees;
  - funding where relevant.
- Preserve native event/vectorized parity for basis, stat-arb, and index-basket
  packages.
- Keep real perp/quarterly Nautilus parity explicitly dependent on a delivery
  futures instrument provider or adapter extension.
- Keep `CrossExchangeArbSpec`, `TriangularArbSpec`, and `OptionsVolArbSpec`
  schema-safe with actionable `NotImplemented` messages until specialized
  engines are built.

Acceptance:

- Stat-arb package PnL reconciles:
  - leg PnL + fees + funding = package PnL;
  - residual/spread PnL sign is correct;
  - dynamic hedge ratios do not break accounting.
- Event vs vectorized parity remains within tolerance.
- Schema-only specs reject clearly.
- Optional Nautilus smoke skips or passes cleanly depending on installed
  dependency and instrument support.

Status:

- Added native-event `StatArbPairSpec` package reporting to match the
  vectorized/package-style arbitrage surface:
  - `leg_pnl_report`;
  - `package_pnl_report`;
  - `spread_report`;
  - diagnostics `package_pnl` and `package_pnl_residual`.
- Tightened native-vectorized stat-arb reporting with the same detailed package
  columns:
  - `price_pnl`;
  - `fill_pnl`;
  - `fees`;
  - `funding_pnl`;
  - `leg_pnl`;
  - `hedge_pnl`;
  - `spread_pnl`;
  - `package_pnl`;
  - `equity_delta`;
  - `pnl_residual`.
- Stat-arb funding now follows the same arbitrage package policy as
  basis/funding/carry routes: only legs with `funding_enabled=True` receive
  funding rates.
- Schema-only arbitrage specs now reject with actionable messages pointing to
  `QuantBTEndpoint.arbitrage_support_matrix()`.
- Added Phase 13C regression coverage in
  `tests/test_phase13_arbitrage_certification_cleanup.py`:
  - dynamic hedge-ratio stat-arb package PnL reconciliation;
  - event vs vectorized stat-arb package report parity;
  - funding-enabled leg filtering;
  - schema-only spec guardrails.
- Upgraded the arbitrage certification runner and artifacts:
  - `benchmarks/run_phase12_arbitrage_cert.py`;
  - `benchmarks/phase12_arbitrage_cert.json`;
  - `benchmarks/phase12_arbitrage_cert.md`.
- Latest certification smoke with `--rows 240`:
  - status: `pass`;
  - basis event/vectorized parity: `pass`;
  - stat-pair audit: `pass`;
  - stat-pair max package residual: `1.8891554987021664e-11`;
  - index-basket smoke: `pass`;
  - schema-only guardrails: `pass`;
  - Nautilus package parity: `skipped` unless explicitly requested.

### Explicit Non-Goals For Phase 13

- Dynamic in-Nautilus DCA/grid state machine.
- True L2 order-book queue/latency simulation.
- Exchange-native OCO order-list semantics.
- Venue-specific portfolio-margin clone.

Those belong to a later dedicated Nautilus Depth phase.

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

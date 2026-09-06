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

Debt ledger after Phase 13:

- Completed by Phase 13C: `StatArbPairSpec` now emits `leg_pnl_report`,
  `package_pnl_report`, `spread_report`, and residual accounting artifacts
  matching the basis/index-basket report style.
- Remaining: real exchange quarterly/perpetual basis parity requires a Nautilus
  instrument provider or adapter extension for delivery futures.
- Remaining: cross-exchange, triangular, and options-vol arbitrage remain
  schema-safe specialized-engine future work.

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

Debt ledger after Phase 13:

- Completed by Phase 13A: prepared portfolio market arrays are threaded through
  the higher-level WFO endpoint scoring loop for `target_mode="portfolio"` and
  `backend="native_portfolio"`.
- Completed by Phase 13B: native portfolio report construction has been
  optimized and parity-locked against the previous pandas formulas.
- Completed by Phase 14C: prepared-array reuse now covers single-symbol
  `signal_notional` WFO scoring, native-event order-package replay, and
  supported arbitrage package replays.
- Completed by Phase 14C: native portfolio has opt-in `report_level` controls
  while `full` remains the default stakeholder/audit surface.
- Remaining: pandas normalization overhead still exists in facade layers.
- Remaining: true L2/order-book replay requires venue depth data. Until then,
  QuantBT can only provide OHLCV approximation and synthetic-book simulation for
  domain testing, not production L2 accuracy claims.

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

## Phase 14 - Performance Debt And Plan Hygiene

Goal:

Close the remaining performance/accounting bookkeeping debt without weakening
the current priority order:

```text
domain correctness > accounting transparency > report quality > speed
```

Do not move to Cython/C++ in this phase. The current profiling evidence still
shows Python/report construction and data normalization as the larger buckets,
while pure Numba kernels remain a small share of full facade runtime.

### Phase 14A - Plan Hygiene, Debt Ledger, And Certification Matrix

Purpose:

Make `upgrade/implement.md` accurate after Phase 13 so future agents do not
mistake historical debt for unfinished current scope.

Scope:

- Mark stale Phase 12 debt as completed where Phase 13 already closed it:
  - stat-arb `package_pnl_report` completed by Phase 13C;
  - WFO prepared portfolio arrays completed by Phase 13A;
  - native portfolio report optimization completed by Phase 13B.
- Preserve remaining debt with sharper wording:
  - prepared cache beyond portfolio WFO was completed later in Phase 14C;
  - optional report levels were completed later in Phase 14C;
  - facade-level pandas normalization remains measurable;
  - true L2 replay needs venue order-book data.
- Add a certification matrix covering current production/readiness state by
  backend and strategy family.
- Add the 5-phase roadmap for the next implementation wave.
- Do not modify engine behavior in this phase.

Certification matrix after Phase 13:

| Area | Current status | Certification level | Remaining gate |
|---|---|---|---|
| Single-symbol native vectorized | supported | research/production usable for target-position backtests | real-strategy regression bundles as needed |
| Single-symbol native event | supported | research/production usable for explicit order OHLC backtests | deeper stop/conditional edge cases when needed |
| Native portfolio | default for supported modes | production-ready for supported sizing/modes with parity tests | more real alpha bundles and full-report presentation polish |
| Native arbitrage basis/stat/calendar/funding/carry/index | supported | controlled research usable with audit artifacts | more real data packages and venue-specific cases |
| Cross-exchange arbitrage | schema-only | not executable | specialized multi-venue engine |
| Triangular arbitrage | schema-only | not executable | sequenced path engine |
| Options vol arbitrage | schema-only | not executable | option/Greeks/IV engine |
| Nautilus signal validation | supported | trustee validation for supported single-symbol instruments | tolerance bundles per venue profile |
| Nautilus explicit orders | supported | trustee validation for explicit order replay | real report bundles |
| Nautilus DCA/grid/bracket | experimental structured package | validation/stress-test usable | in-strategy state machine and native OCO semantics |
| Nautilus basket/portfolio/arbitrage packages | experimental validation | smoke/parity artifact usable | real package bundles and deeper tolerance profiles |
| OHLCV depth preflight | supported opt-in | deterministic stress model | not a true L2 claim |
| Synthetic book simulation | planned Phase 15B | domain-test model only | not production-certified without real L2 data |
| Real L2 replay | future | requires venue data | order-book snapshots/incremental updates/trades/latency |

Status:

- Phase 14A completed as documentation/plan hygiene only.
- Stale Phase 12 debt entries have been updated into explicit completed vs
  remaining debt ledgers.
- The certification matrix above is now the source of truth for what is
  supported, experimental, schema-only, and future.
- No production code or engine behavior changed in Phase 14A.

### Phase 14B - Real WFO And Service-Loop Benchmark

Purpose:

Measure the real remaining performance bottlenecks before any further
optimization. This benchmark must reflect how QuantBT is used in notebooks,
services, WFO, Optuna sweeps, explicit order replays, portfolio runs, and
arbitrage package loops.

Scope:

- Add a benchmark script and committed JSON/Markdown report for:
  - single-symbol WFO;
  - native-event explicit-order replay loops;
  - native-portfolio WFO;
  - arbitrage package sweeps;
  - report-heavy vs report-light execution.
- Decompose runtime into:
  - pandas normalization;
  - ndarray packing;
  - strategy callback / signal generation;
  - target sizing;
  - order-array construction;
  - pure Numba kernel;
  - result/report construction;
  - metrics/report export.
- Track:
  - bars;
  - symbols;
  - folds;
  - trials;
  - order count;
  - event count;
  - memory;
  - compile/warmup vs repeated runtime.

Acceptance:

- Benchmark output separates pure kernel runtime from facade/report runtime.
- Benchmark includes parity guards proving benchmark variants do not alter core
  equity, positions, fees, funding, margin, liquidation, or package PnL.
- Report explicitly states whether Cython/C++ is justified. Default expectation
  remains "not yet" unless pure kernels become the bottleneck.

Status:

- Implemented `benchmarks/run_phase14_service_loop.py`.
- Added committed benchmark artifacts:
  - `benchmarks/phase14_service_loop.json`;
  - `benchmarks/phase14_service_loop.md`.
- Added regression coverage in `tests/test_phase14_service_loop_benchmark.py`.
- Current benchmark command:

```bash
python benchmarks/run_phase14_service_loop.py \
  --rows 360 \
  --symbols 4 \
  --trials 4 \
  --order-count 120 \
  --repeats 2
```

- Latest benchmark status: `pass`.
- Parity guards all pass:
  - single-symbol WFO;
  - portfolio WFO cached vs uncached;
  - native-event cold vs prepared replay;
  - arbitrage package event vs vectorized sweep;
  - heavy metrics report vs light core summary.
- Latest measured bottlenecks:
  - native vectorized: `data_normalization` at about `54.04%`;
  - native event: `data_normalization` at about `38.32%`;
  - native portfolio: `report_construction_estimate` at about `79.55%`;
  - pure Numba kernel share remains below `1%` across the measured native
    vectorized/event/portfolio paths.
- Service-loop report now includes `tracemalloc` peak-memory measurements per
  workload so runtime and allocation pressure can be interpreted together.
- Conclusion: Cython/C++ is not justified yet. Phase 14C should prioritize
  prepared-array reuse in single-symbol/event/arbitrage loops and optional lazy
  heavy reports while preserving full report defaults.

### Phase 14C - Prepared Cache And Lazy Heavy Reports

Purpose:

Reduce repeated Python/pandas overhead in service and WFO loops while keeping
full stakeholder-grade reporting available and unchanged by default.

Scope:

- Extend prepared-array reuse beyond portfolio WFO:
  - single-symbol WFO endpoint scoring where market tape is invariant;
  - native-event explicit-order package loops;
  - arbitrage package repeated runs.
- Add optional report controls without changing defaults:
  - `report_level="full"` keeps current behavior;
  - `report_level="standard"` keeps key audit metrics but avoids selected heavy
    expansions;
  - `report_level="minimal"` keeps equity/returns/positions/core diagnostics for
    optimizer/service loops.
- Prepared caches must remain run-local or explicitly caller-owned, with
  datetime/symbol signatures and no mutable global result cache.

Acceptance:

- Full/standard/minimal report levels have identical core accounting:
  - equity;
  - returns;
  - positions;
  - fees;
  - funding;
  - margin;
  - liquidation;
  - package PnL where applicable.
- Signature mismatch rejects prepared reuse clearly.
- Prepared arrays are explicit copied snapshots; source data mutation requires
  rebuilding the prepared object, while stale index/symbol layouts are rejected.
- Existing endpoint calls remain backward compatible because `full` is default.

Status:

- Implemented `NativeVectorizedBackend.prepare_market_arrays(...)` and optional
  prepared-market replay for `run_signals(..., hedge_type="signal_notional")`.
- Extended WFO endpoint scoring cache beyond portfolio:
  - single-symbol `target_mode="signal_notional"` with `backend="native_vectorized"`;
  - portfolio `target_mode="portfolio"` with `backend="native_portfolio"` remains
    supported;
  - cache metadata is attached at
    `result.metadata["walk_forward"]["prepared_scoring_cache"]`.
- Added `prepared_scoring_report_level`, default `minimal`, so portfolio WFO
  objective scoring avoids heavy stakeholder reports per trial while the final
  stitched backtest still uses endpoint `report_level` default `full`.
- Added `report_level` to native portfolio:
  - `full`: default, unchanged audit surface;
  - `standard`: keeps exposure, accepted/target notional, funding rates, and
    symbol PnL but omits selected expansions;
  - `minimal`: keeps accounting-critical result surfaces for optimizer/service
    loops and marks contract validation as skipped.
- Extended native-event package routes to accept caller-owned prepared market
  arrays for basket, basis arbitrage, stat-arb pair, and generic supported
  package arbitrage replay.
- Updated Phase 14 benchmark artifact to measure:
  - single-symbol WFO cached vs uncached;
  - portfolio WFO cached vs uncached;
  - native-event explicit-order prepared replay;
  - arbitrage package cold vs prepared event replay;
  - native-portfolio `full` vs `minimal` report construction.
- Added regression coverage:
  - `tests/test_phase14c_prepared_report_levels.py`;
  - updated `tests/test_phase14_service_loop_benchmark.py`.
- Documentation updated:
  - `docs/endpoint.md`;
  - `docs/portfolio_engine_v3.md`.

Safety notes:

- Existing endpoint behavior is unchanged unless `report_level` or prepared
  APIs are explicitly used.
- Prepared arrays are copied snapshots with datetime/symbol signature guards,
  not mutable global caches. If OHLC/funding values are changed intentionally,
  rebuild the prepared arrays before replaying.
- Phase 14C does not implement true L2/order-book simulation and does not alter
  margin, fill, sizing, funding, or PnL kernels.

## Phase 15 - Nautilus Certification And Depth

Goal:

Promote Nautilus from a strong validation backend into a cleaner institutional
evidence layer, while being honest about what can and cannot be claimed without
real venue data.

### Phase 15A - Nautilus Real Certification Bundles

Purpose:

Produce stakeholder-ready Nautilus report bundles for representative real or
realistic workflows.

Scope:

- Run and archive report bundles for:
  - single-symbol `%_equity`;
  - explicit orders;
  - basket package;
  - portfolio package;
  - basis/stat-arb package where supported instruments exist.
- Export:
  - config;
  - account timeline;
  - orders;
  - fills;
  - positions;
  - native-vs-Nautilus parity;
  - tolerance profile;
  - known differences.
- Add tolerance profiles for:
  - fill price;
  - fee;
  - slippage;
  - equity;
  - quantity rounding.

Acceptance:

- Skips cleanly if `nautilus-trader` or required instrument support is missing.
- Passes and writes JSON/Markdown/CSV bundles when dependencies are available.
- Injected mismatch tests prove parity reports catch fill-price/equity/quantity
  differences.

Status:

- Implemented `reporting/nautilus_certification.py`:
  - `NautilusToleranceProfile`;
  - `build_nautilus_certification_profile(...)`;
  - `write_nautilus_certification_artifacts(...)`.
- Added public exports through `quantbt.reporting` and top-level `quantbt`.
- Implemented `benchmarks/run_phase15a_nautilus_certification.py`.
- Supported certification workflow matrix:
  - `pct_equity_signal`;
  - `explicit_orders`;
  - `basket_package`;
  - `portfolio_package`;
  - `basis_arbitrage_package`.
- Successful workflows export the normal Nautilus bundle plus:
  - `native_vs_nautilus_parity.csv`;
  - `tolerance_profile.json`;
  - `known_differences.md`;
  - `certification_summary.json`.
- Default runner behavior is dependency-safe:
  - without `--include-nautilus`, all workflows are marked `skipped`;
  - with `--include-nautilus`, missing `nautilus-trader` or unsupported
    instrument routes skip cleanly instead of pretending to pass.
- Added `tests/test_phase15a_nautilus_certification.py`:
  - clean skip behavior;
  - markdown readability;
  - identical synthetic results pass tolerance;
  - injected fill-price, fee, equity, and quantity mismatches fail tolerance.
- Updated documentation:
  - `docs/nautilus_backend.md`;
  - `README.md`.

Latest local artifact:

- `benchmarks/phase15a_nautilus_certification.json`;
- `benchmarks/phase15a_nautilus_certification.md`.

Current local run status without optional Nautilus execution:

- status: `pass`;
- workflows skipped: `5`;
- failed workflows: `0`.

Safety notes:

- Phase 15A is an evidence/reporting layer. It does not change native or
  Nautilus execution, sizing, fee, margin, liquidation, or funding logic.
- A skipped workflow is not a pass claim. It only records that optional
  dependency/instrument execution was not requested or available.

### Phase 15B - Nautilus Depth, Synthetic Book, And Specialized Arbitrage Plan

Status: completed for Level-2 synthetic depth stress and documentation
guardrails. Real venue L2 replay, exchange-native OCO lists, in-strategy
dynamic DCA state machines, and specialized cross-exchange / triangular /
options-vol engines remain future production work.

Purpose:

Define and implement the next depth layer carefully, without claiming exchange
fidelity beyond the available data.

L2 / book simulation levels:

- Level 1: OHLCV approximation. Already available via depth preflight:
  volume cap, queue-ahead approximation, latency-bar shifting, partial-fill
  approximation, and deterministic package rejection.
- Level 2: synthetic order-book simulation. This can be implemented without
  real L2 data by generating a book from assumptions such as spread, depth
  slope, volatility, volume participation, and queue-ahead. It is useful for
  domain tests and conservative stress scenarios, but must not be described as
  venue-realistic execution.
- Level 3: real L2 replay. This requires venue order-book snapshots, incremental
  depth updates, trade prints, timestamps, and latency assumptions. Only this
  level can support true queue-priority and order-book execution claims.

Nautilus depth scope:

- Dynamic DCA/grid state machine inside Nautilus strategy:
  - submit base;
  - activate safety orders only after base fill;
  - update TP/SL quantity as ladder fills;
  - prevent blind submission of all future orders.
- OCO/bracket semantics:
  - map to exchange-native order-list semantics if Nautilus route is stable;
  - otherwise keep package-strategy cancellation and document the difference.
- Depth model abstraction:
  - `OHLCVDepthModel` maps to `depth_model="ohlcv_volume_cap"` and remains the
    default;
  - `SyntheticBookDepthModel` maps to `depth_model="synthetic_book"` and now
    supports deterministic spread, level spacing, level depth, depth slope,
    participation cap, queue-ahead, partial-fill, and limit-price filtering;
  - `L2ReplayDepthModel` maps to `depth_model="l2_replay"` and intentionally
    refuses to run without real venue depth provider data.

Specialized arbitrage scope:

- Keep supported native arbitrage routes as-is:
  - basis;
  - stat-arb pair;
  - calendar spread;
  - funding arbitrage;
  - spot-perp cash carry;
  - index basket.
- Add explicit future engine plans:
  - `CrossExchangeArbEngine`: multi-venue account, latency, transfer/borrow
    constraints, venue-specific fees and settlement.
  - `TriangularArbEngine`: sequenced path execution, path slippage, partial-fill
    propagation, and inventory drift.
  - `OptionsVolArbEngine`: option instruments, IV surface, Greeks, expiry,
    assignment/exercise, and delta hedge behavior.

Acceptance:

- Synthetic-book tests prove depth model invariants without requiring private
  venue data: `tests/test_phase15b_synthetic_depth.py`.
- Endpoint package routing accepts the synthetic depth config:
  `tests/test_phase5_4_endpoint_depth.py::test_phase15b_endpoint_depth_accepts_synthetic_book_model`.
- Real L2 tests skip clearly when no L2 provider is configured via
  `l2_replay_available(...)`.
- Schema-only arbitrage specs remain rejected until their specialized engine has
  accounting audit, parity tests, and docs.

Latest local artifacts:

- `benchmarks/phase15b_synthetic_depth.json`;
- `benchmarks/phase15b_synthetic_depth.md`;
- `benchmarks/run_phase15b_synthetic_depth.py`.

Safety notes:

- Phase 15B does not change default endpoint behavior because
  `depth_model="ohlcv_volume_cap"` remains the default.
- Synthetic depth is an execution stress model, not an exchange L2 replay.
- `l2_replay` raises explicitly until venue snapshots, incremental updates,
  trade prints, and timestamp/latency assumptions are provided.

## Phase 16 - Performance Debt Closure

Goal:

Close the remaining non-Cython performance debt that was still open after
Phase 13/14:

- repeated pandas normalization in facade/service loops;
- native portfolio report-construction residual cost;
- larger WFO/service-loop benchmark before any Cython/C++ decision.

Scope:

- Add an opt-in prepared service context on the public endpoint:
  `endpoint.prepare_service_context(...)`.
- Support only routes with existing prepared-array parity locks:
  - `QuantBTEndpoint.signal_notional(..., backend="native_vectorized")`;
  - `QuantBTEndpoint.portfolio(..., backend="native_portfolio")`.
- Keep normal `.backtest(...)` unchanged and defensive.
- Reuse copied prepared market arrays and backend signature validation.
- Convert repeated signal/position inputs to raw ndarray matrices when index and
  columns already match, with safe pandas alignment fallback otherwise.
- Add a larger benchmark artifact that compares:
  - repeated normal endpoint replays;
  - prepared service-context replays;
  - full vs minimal native portfolio reports;
  - larger Phase 14 WFO/service-loop profile.

Acceptance:

- Prepared service context has identical core accounting versus normal endpoint:
  equity, returns, positions, fees, funding, margin.
- Unsupported legacy/event/Nautilus routes raise clearly instead of silently
  changing semantics.
- Benchmark artifact records speed, parity, memory, and Cython/C++ decision.
- Cython/C++ remains deferred unless pure kernels become the measured bottleneck.

Status:

- Implemented `QuantBTPreparedContext` and
  `QuantBTEndpoint.prepare_service_context(...)`.
- Exported `QuantBTPreparedContext` through top-level `quantbt`.
- Added tests in `tests/test_phase16_prepared_service_context.py`:
  - single-symbol `signal_notional` prepared context parity;
  - native portfolio prepared context core-accounting parity;
  - unsupported legacy `%_equity` rejection.
- Added benchmark runner and artifacts:
  - `benchmarks/run_phase16_performance_debt.py`;
  - `benchmarks/phase16_performance_debt.json`;
  - `benchmarks/phase16_performance_debt.md`.
- Latest Phase 16 benchmark status: `pass`.
- Latest measured prepared-context speedups:
  - single-symbol signal-notional service replays: `1.821x`;
  - native portfolio service replays: `4.483x`;
  - native portfolio full vs minimal report construction: `1.917x`.
- Larger WFO/service-loop parity remains `pass`.
- Current Cython/C++ decision: not justified yet; measured bottlenecks remain
  facade/report/preparation layers rather than pure Numba kernels.

Safety notes:

- This phase does not alter margin, sizing, fill, funding, liquidation, or PnL
  kernels.
- Prepared service contexts are caller-owned and run-local; there is no mutable
  global cache.
- If OHLC/funding data changes, rebuild the context.
- For final stakeholder reports, rerun the selected signal/portfolio with
  normal `.backtest(...)` or `report_level="full"`.

---

## Phase 17 - Options Backtest Engine

Planning source:

- `upgrade/option_backtest_plan/quantbt_options_engine_verified_design.md`
- `upgrade/option_backtest_plan/quantbt_options_engine_execution_plan.md`

Branch:

- Requested branch `dev/option-engine` is not valid while branch `dev` exists,
  because Git cannot store both `refs/heads/dev` and
  `refs/heads/dev/option-engine`.
- Active implementation branch: `feat/option-engine`.

Goal:

Add an institutional-grade options backtest stack while keeping existing
QuantBT behavior stable:

- option instrument conventions first;
- ledger-based PnL and expiry accounting;
- ragged option tape, not dense fixed-universe matrices;
- bid/ask execution;
- no lookahead in selector/tape usage;
- optional Nautilus validation, never an import-time dependency.

### Phase 17.0 - Baseline Protection

Status: completed.

Artifacts:

- `upgrade/option_backtest_plan/phase0_baseline_snapshot.json`;
- `upgrade/option_backtest_plan/phase0_baseline_snapshot.md`.

Latest result:

- full non-real regression: `286 passed, 1 skipped, 3 warnings`.
- `import quantbt` did not import `nautilus_trader`.
- existing endpoint support matrices were snapshotted.

### Phase 17.1 - Domain Schema And Conventions

Status: completed.

Implemented:

- Added `AssetType.OPTION`.
- Added `quantbt.options` bounded context:
  - schema;
  - venue conventions;
  - canonical option-chain data validation.
- Added option enums, `OptionInstrumentSpec`, instrument registry signatures,
  and versioned Deribit/Binance convention descriptors.
- Exported Phase 1 schema helpers from top-level `quantbt`.
- Added tests for additive import behavior, inverse/linear convention guards,
  registry signatures, option chain normalization, quote guards, expiry guards,
  and duplicate snapshot rejection.

Latest tests:

- Phase 1 option tests: `12 passed`.
- import smoke: `phase1_import_smoke=pass`.
- full non-real regression: `298 passed, 1 skipped, 3 warnings`.

Technical debt after Phase 17.1:

- `OptionInstrumentSpec.multiplier` currently mirrors
  `InstrumentSpec.contract_size`; later phases should choose one canonical
  reporting multiplier or keep both with stronger docs.
- `OptionInstrumentSpec.qty_step` mirrors `InstrumentSpec.lot_size`; later
  endpoint docs should settle on one user-facing term for quantity increment.
- One-sided or zero-bid option quotes are not accepted yet; Phase 3 may add
  explicit quote-status support.
- Venue convention descriptors do not yet include historical venue fee/margin
  schedule snapshots.
- Binance option convention is metadata-safe only, not exact venue margin
  certification.
- Pricing, IV, Greeks, tape compilation, package execution, ledger, expiry,
  endpoint, and Nautilus validation remain future phases by design.

### Phase 17.2 - Pricing, IV, Greeks

Status: completed.

Implemented:

- Added deterministic scalar option analytics primitives:
  - linear Black-76 call/put pricing;
  - linear intrinsic and put-call parity;
  - inverse base-currency forward pricing;
  - inverse intrinsic and base-currency parity;
  - linear quote Greeks;
  - inverse native base Greeks;
  - inverse quote-reporting Greeks;
  - static reporting-currency Greek scaling;
  - bisection IV solvers with explicit status enum;
  - minimal total variance surface and diagnostics.
- Exported Phase 2 analytics helpers from top-level `quantbt`.
- Added tests for:
  - linear parity;
  - inverse parity;
  - IV recovery;
  - invalid IV status;
  - finite-difference delta/gamma/vega;
  - no-future-timestamp surface calibration;
  - basic calendar total variance diagnostics.

Latest tests:

- options tests: `31 passed`.
- fastmath scan: no matches in `options` or `tests/options`.
- import smoke: `phase2_import_smoke=pass`.
- full non-real regression: `317 passed, 1 skipped, 3 warnings`.

Technical debt after Phase 17.2:

- Pricing/Greeks are scalar primitives; vectorized or Numba kernels should be
  added only after Phase 3/4 tape and execution array shapes are stable.
- Inverse pricing uses the Phase 2 forward convention: linear quote price
  divided by forward. Venue-exact Deribit/Binance option accounting needs later
  sample parity.
- Theta assumes fixed forward and discount.
- Surface diagnostics are minimal; butterfly convexity and full no-arb fitting
  are not production-certified yet.
- IV uses deterministic bisection for auditability; faster solvers are deferred.
- Options still have no tape compiler, selector, execution engine, ledger,
  expiry lifecycle, endpoint route, or Nautilus validation.

### Phase 17.3 - Data Tape And Selectors

Status: completed.

Implemented:

- Added a ragged/CSR option tape:
  - `PreparedOptionTape`;
  - `OptionTapeSignature`;
  - `prepare_option_tape(...)`;
  - snapshot timestamps;
  - row pointers;
  - per-row instrument codes and market fields.
- Added no-lookahead option selectors:
  - ATM;
  - target delta;
  - target DTE;
  - target moneyness;
  - available rows with liquidity/spread/OI filters.
- Added registry, convention, and timestamp signature validation.
- Added guards for:
  - unknown/unlisted instruments;
  - registry static-field mismatch;
  - crossed quotes;
  - stale source latency;
  - stale decision-time quote age;
  - expired contracts at decision time.
- Exported Phase 3 APIs from top-level `quantbt`.

Latest tests:

- options tests: `43 passed`.
- import smoke: `phase3_import_smoke=pass`.
- dense/fastmath scan: no dense matrix construction and no `fastmath`.
- full non-real regression: `329 passed, 1 skipped, 3 warnings`.

Technical debt after Phase 17.3:

- Selector scans are Python/NumPy. Numba kernels should wait until option
  execution/package shapes are stable.
- Delta/IV selectors use observable chain columns only. Model-derived fallback
  selection must be explicit in later phases.
- Stale checks are snapshot-level guards, not L2/order-book replay.
- Tie-break policies are first-minimum after canonical sort; richer secondary
  policies are future work.
- Options still have no package compiler, execution engine, ledger, expiry
  lifecycle, endpoint route, or Nautilus validation.

### Phase 17.4 - Package Compiler And Options Execution

Status: completed.

Implemented:

- Added option package domain objects:
  - `OptionPackageLeg`;
  - `OptionPackageIntent`;
  - `OptionPackageExecutionPolicy`.
- Added `compile_option_package_orders(...)` to compile option package legs into
  existing QuantBT `OrderIntent` leaves with package metadata.
- Added snapshot-level option package execution:
  - `OptionExecutionConfig`;
  - `OptionLimitFidelity`;
  - `OptionDepthFidelity`;
  - `OptionPackageExecutionResult`;
  - `execute_option_package(...)`.
- Supported policies:
  - `ATOMIC_ALL_OR_NONE`;
  - `BEST_EFFORT`;
  - `SEQUENTIAL`;
  - `HEDGE_AFTER_PRIMARY`;
  - `REBALANCE_ONLY`.
- Locked Phase 4 fill rules:
  - market buy at ask;
  - market sell at bid;
  - no mark/mid default execution;
  - FOK/IOC/GTC behavior where feasible on top-of-book snapshots;
  - package debit/credit guard;
  - explicit simulated atomicity/fidelity labels.
- Exported Phase 4 APIs from top-level `quantbt`.

Latest tests:

- options tests: `54 passed`.
- import smoke: `phase4_import_smoke=pass`.
- full non-real regression: `340 passed, 1 skipped, 3 warnings`.

Technical debt after Phase 17.4:

- Execution remains snapshot/top-of-book, not L2 replay or venue-native combo
  matching.
- `MAKER_TOUCH` is an explicit approximation, not real maker queue priority.
- Margin report is a placeholder until the multi-currency ledger phase.
- Stop/conditional option lifecycle is rejected until lifecycle semantics exist.
- Package debit/credit guard works in package premium units; full currency
  conversion is deferred.
- Options still have no endpoint route, full ledger, expiry lifecycle, or
  Nautilus adapter.

### Phase 17.5 - Multi-Currency Ledger, Fees, Lifecycle

Status: completed.

Implemented:

- Added `OptionFeeSchedule`, `OptionFeeResult`, and deterministic per-leg fee
  calculation.
- Added Deribit-like fee schedules:
  - inverse base-currency capped fee;
  - linear USDC capped fee.
- Added `OptionLedger` and `OptionPosition`:
  - multi-currency cash;
  - position quantity;
  - average entry;
  - realized PnL;
  - fees;
  - settlement cashflows;
  - margin-locked bucket;
  - event audit rows;
  - reporting-currency equity identity.
- Added lifecycle helpers:
  - `option_expiry_payoff_per_unit(...)`;
  - `settle_option_expiry(...)`;
  - `OptionSettlementRepresentation`;
  - `OptionSettlementResult`.
- Locked Phase 5 accounting rules:
  - long pays premium;
  - short receives premium;
  - fee is recorded separately;
  - round trip with no price move equals spread plus fees;
  - inverse BTC premium reconciles to USD reporting equity via conversion rate;
  - OTM expiry closes at zero payoff;
  - ITM linear payoff settles in quote/settlement currency;
  - ITM inverse payoff settles in base currency;
  - settlement closes exactly once.
- Exported Phase 5 APIs from top-level `quantbt`.

Latest tests:

- options tests: `63 passed`.
- import smoke: `phase5_import_smoke=pass`.
- full non-real regression: `349 passed, 1 skipped, 3 warnings`.

Technical debt after Phase 17.5:

- Ledger is not wired into a full option backend or endpoint yet.
- Margin models and liquidation sequencing remain Phase 6.
- Fee schedules are deterministic Deribit-like approximations, not venue-exact
  certified schedules.
- `future_then_cash` is currently an audit representation with equivalent
  economic cashflow.
- Quanto lifecycle payoff is not implemented.
- Reporting conversion uses caller-supplied rates only.

### Phase 17.6 - Hedging And Margin

Status: completed.

Implemented:

- Added option hedge-policy primitives:
  - fixed threshold;
  - hysteresis band;
  - time-based;
  - realized-vol scaled band.
- Added hedge path accounting where hedge PnL for the prior price move uses the
  previous hedge position before current-bar rebalance.
- Added option margin primitives:
  - long-premium-only;
  - standard venue approximation;
  - scenario PM approximation;
  - no-margin research;
  - external validator interface.
- Added liquidation audit:
  - maintenance breach check;
  - adverse bid/ask liquidation;
  - fee report;
  - final cash;
  - final positions.
- Exported Phase 6 APIs from top-level `quantbt`.

Latest tests:

- options tests: `71 passed`.
- import smoke: `phase6_import_smoke=pass`.
- full non-real regression: `357 passed, 1 skipped, 3 warnings`.

Technical debt after Phase 17.6:

- Hedge/margin are primitives, not a full option backend loop yet.
- Whalley-Wilmott remains intentionally excluded.
- Standard/scenario PM models are approximations; scenario PM reports
  `venue_exact=false`.
- External margin validator has an interface only.
- Liquidation closes all positions with adverse BBO prices, not exchange-native
  queue/partial liquidation logic.
- Underlying hedge instrument execution and Nautilus option validation remain
  future work.

---

## Phase 30 - Native Event Lifecycle Upgrade

Status: active on branch `feat/30-native-event-lifecycle`.

Urgent goal:

- Upgrade `native_event` from a static market/limit replay kernel into a
  deterministic OHLC order-lifecycle engine.
- Preserve strategy separation: alpha/research code still emits signals or
  order commands; the backend owns order state, fills, PnL, fees, margin,
  liquidation, and audit reports.
- Keep old endpoint behavior stable while adding a v2 lifecycle path.

Scope:

- `quantbt.core.orders`;
- `quantbt.core.order_compiler`;
- `quantbt.core.event`;
- `quantbt.backends.native_event`;
- `quantbt.adapters.nautilus`;
- endpoint/docs/tests only where needed to expose the new contract.

Non-goals for Phase 30:

- Do not move alpha/feature logic into the backend.
- Do not silently change `OrderIntent` v1 market/limit replay semantics.
- Do not claim exchange-native OCO/L2 queue behavior until parity tests exist.

### Phase 30A - Command Contract And Compiler V2

Status: completed.

Plan:

- Add canonical lifecycle command objects:
  - `OrderAction.PLACE`;
  - `OrderAction.CANCEL`;
  - `OrderAction.REPLACE`;
  - `OrderAction.AMEND`;
  - `OrderAction.CANCEL_ALL`.
- Keep `OrderIntent` as the backwards-compatible shorthand for immediate
  `PLACE`.
- Add lifecycle fields required by v2:
  - `order_id`;
  - `target_order_id`;
  - `parent_order_id`;
  - `group_id`;
  - `oco_group_id`;
  - `activation_policy`;
  - `expires_at`;
  - `reduce_only`;
  - `trigger_price`.
- Add `compile_order_commands(...)` to pack lifecycle commands into contiguous
  NumPy arrays without running execution logic.
- Preserve `compile_order_intents(...)` and `_engine_event_v1` unchanged for
  old endpoint parity.
- Add focused tests for validation, stable sorting, ID mapping, stop fields,
  reduce-only flags, parent/OCO metadata, and backend helper exposure.

Exit criteria:

- New command contract imports from `quantbt`.
- Compiler v2 supports market, limit, stop-market, stop-limit command payloads.
- Old native-event market/limit tests still pass unchanged.
- No endpoint default behavior changes.

Implemented:

- Added `OrderAction`, `OrderActivationPolicy`, and `OrderCommand`.
- Preserved `OrderIntent` as the compatibility shorthand for immediate place
  commands.
- Added `order_intents_to_commands(...)` and `compile_order_commands(...)`.
- Added `CompiledOrderCommandArrays` with packed fields for:
  - action;
  - symbol;
  - side;
  - order type;
  - quantity;
  - limit price;
  - trigger price;
  - TIF;
  - reduce-only;
  - order/target/parent/group/OCO IDs;
  - activation policy;
  - expiry bar;
  - original command index.
- Exposed `NativeEventBackend.compile_order_commands(...)`.
- Exported the new command contract from `quantbt` and `quantbt.core`.
- Documented the distinction between v1 `OrderIntent` execution and v2 command
  tape compilation.

Latest tests:

- Phase 30A command contract tests: `4 passed`.
- Native-event v1 parity/performance tests: `11 passed`.
- Full non-real regression: `399 passed, 1 skipped, 3 warnings`.

Technical debt after Phase 30A:

- `OrderCommand` tapes are compiled but not yet executed by a lifecycle kernel.
- Stop-market/stop-limit payloads are packed for v2, while v1 still executes
  only market/limit orders.
- OCO, parent-child activation, cancel/replace/amend, GTD expiry, and
  reduce-only clipping are contract-ready but require Phase 30B execution
  tests before production use.

### Phase 30B - Native Event Lifecycle Kernel V2

Status: completed.

Plan:

- Add an active-order registry in a v2 Numba kernel.
- Implement deterministic lifecycle transitions:
  - place;
  - cancel;
  - replace;
  - amend;
  - cancel-all;
  - GTD expiry;
  - reduce-only clipping;
  - stop-market and stop-limit trigger activation;
  - OCO sibling cancellation;
  - parent-child activation on first/full fill.
- Emit lifecycle audit artifacts:
  - order event log;
  - final active-order snapshot;
  - status/reject/cancel/fill report;
  - engine version metadata.
- Keep v1 as compatibility route until v2 parity is explicitly accepted.

Exit criteria:

- Domain tests cover bracket/OCO, DCA/grid entry/exit, cancel/replace/amend,
  reduce-only, stop triggers, GTD expiry, parent-child activation, and margin
  rejection.
- v1 compatibility tests still pass.
- v2 metadata makes lifecycle behavior transparent enough for Nautilus parity.

Implemented:

- Added `_engine_event_v2(...)` as an opt-in Numba lifecycle kernel.
- Added active-order registry arrays and dense ID lookup.
- Implemented deterministic lifecycle commands:
  - place;
  - cancel;
  - replace;
  - amend;
  - cancel-all.
- Implemented order-state behavior:
  - parent-child activation;
  - OCO sibling cancellation;
  - reduce-only no-op cancellation and quantity clipping;
  - stop-market trigger fills;
  - stop-limit trigger plus limit-touch fills;
  - GTD expiry before matching;
  - IOC/FOK cancellation when not touched;
  - margin rejection using the same account model as v1.
- Added `NativeEventBackend.run_order_commands(...)`.
- Added lifecycle audit metadata:
  - `command_report`;
  - `order_report`;
  - `order_events`;
  - `active_orders`;
  - `id_values`;
  - quantity preflight.
- Preserved `run_orders(...)` on event v1 for existing endpoint parity.

Latest tests:

- Phase 30A/30B lifecycle tests: `18 passed`.
- Native-event v1 parity/performance tests: `11 passed`.
- Simple market/limit v1-v2 parity test: passed inside Phase 30B suite.
- Full non-real regression: `413 passed, 1 skipped, 3 warnings`.

Additional locked domain cases:

- cancel prevents later GTC fill;
- replace cancels old slot and fills replacement;
- amend updates working limit before matching;
- stop-market trigger fill;
- stop-limit trigger plus limit-touch fill;
- cancel-all cancels active and parent-waiting orders;
- parent-child bracket activation with OCO sibling cancel;
- reduce-only no-op cancel without opposite position;
- reduce-only clipping to existing position size;
- margin rejection above buying power;
- DCA/grid-style base plus safety limit fills at grid prices;
- GTD expiry before later touch;
- unfilled GTC active snapshot;
- v1-v2 market/limit parity.

Technical debt after Phase 30B:

- Endpoint route still defaults to v1 `OrderIntent`; Phase 30C will expose
  lifecycle v2 through endpoint/backends more ergonomically.
- Structured DCA/grid, bracket, basket, and arbitrage packages are not yet
  automatically compiled into `OrderCommand` tapes.
- Partial fills, queue priority, latency, and L2 depth remain outside this
  kernel; current v2 behavior is deterministic OHLC lifecycle simulation.
- Nautilus parity for command tapes remains Phase 30C.

### Phase 30C - Endpoint, Nautilus Adapter, And Structured Package Parity

Status: completed.

Plan:

- Expose an opt-in native-event v2 route through endpoint/backends without
  breaking existing calls.
- Compile structured bracket, DCA/grid, basket, and arbitrage packages into
  lifecycle commands where order state matters.
- Align Nautilus adapter inputs around the same canonical command contract.
- Add parity tests between:
  - native-event v2 and old v1 for simple market/limit cases;
  - native-event v2 and Nautilus for single-symbol explicit order packages;
  - structured package preflight and lifecycle execution reports.

Exit criteria:

- Endpoint docs show how to pass `OrderIntent` vs `OrderCommand`.
- Legacy endpoints remain stable.
- Package-level reports include fills, cancels, rejects, and linked-order
  status for stakeholder audit.

Implemented:

- Added endpoint-level lifecycle route:
  - `QuantBTEndpoint.native_event_lifecycle(...)`;
  - `QuantBTEndpoint.orders(event_engine_version="v2", ...)`;
  - `simulate(..., order_commands=[OrderCommand(...), ...])`.
- Added `BacktestEngineV2` support for:
  - `order_commands`;
  - `event_engine_version`;
  - native-event v2 lifecycle execution;
  - legacy `OrderIntent` to lifecycle `PLACE` conversion when v2 is requested.
- Added structured native-event v2 endpoints:
  - `QuantBTEndpoint.native_event_dca_grid(...)`;
  - `QuantBTEndpoint.native_event_bracket_orders(...)`.
- Added canonical metadata converter:
  - `order_intents_to_lifecycle_commands(...)`;
  - lifts parent/OCO/package metadata into explicit command fields;
  - limits OCO linkage to reduce-only/exit legs so base/safety orders are not
    accidentally canceled.
- Aligned Nautilus adapter payloads:
  - `QuantBTEndpoint.orders(backend="nautilus")` accepts `order_commands`;
  - executable `PLACE` and `REPLACE` commands are converted into Nautilus
    package `OrderIntent` payloads;
  - legacy Nautilus `orders=[OrderIntent(...)]` params remain unchanged.
- Updated endpoint/order-fill docs and Nautilus support matrix.

Latest tests:

- Phase 30A/30B/30C lifecycle suites: `23 passed`.
- Endpoint/Nautilus compatibility subsets: `50 passed`.
- Native-event v1 parity/performance subset: `11 passed`.
- Full non-real regression: `418 passed, 1 skipped, 3 warnings`.

Final Phase 30 conclusion:

- Native-event v2 is usable for deterministic OHLC lifecycle research and
  package audit through opt-in endpoint/backend routes.
- Existing v1 `OrderIntent` endpoint behavior remains stable and default.
- Structured DCA/grid and bracket/OCO packages can now run through native-event
  v2 with command reports and event logs.
- Nautilus adapter is command-payload aligned for executable package orders,
  but exchange-native cancel/amend command parity remains future work.

Remaining out-of-scope debt:

- Partial fills, queue priority, latency, and L2 depth are still handled by
  separate depth/preflight approximations, not the v2 OHLC kernel.
- Nautilus parity for true cancel/replace/amend lifecycle requires a dedicated
  Nautilus strategy upgrade and real Nautilus package runs.
- Portfolio/arbitrage package command conversion can be deepened later where
  linked lifecycle state materially changes the strategy behavior.

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


## Aditional update to awesome-native event command reactive
### Feature Request: Reactive Native-Event Strategy Runner

### Phase 30D - Reactive Runner MVP

Status: completed.

Goal:

- Add a safe opt-in reactive strategy runner above native-event v2.
- Preserve the static command-tape route and all Phase 30A-C behavior.
- Let strategy callbacks observe engine-generated fills, events, positions,
  equity, margin, and active orders after each bar.
- Enforce causal timing: commands emitted after close `t` become effective from
  bar `t+1`.
- Capture the emitted command tape and prove that static replay of this tape
  has 100% accounting parity with the reactive run.

Implementation scope:

- Add read-only reactive records:
  - `NativeStrategyContext`;
  - `NativeFillEvent`;
  - `NativeOrderEvent`;
  - `NativeActiveOrderSnapshot`;
  - `NativeEventStrategyError`.
- Add `NativeEventBackend.run_strategy(...)`.
- Add endpoint route:
  - `QuantBTEndpoint.native_event_strategy(...)`;
  - `simulate(..., strategy=...)`.
- Add `context.size_order(...)` using the same quantity constraints as the
  backend.
- Preserve metadata round-trip for `campaign_id`, `cycle_id`, `level_id`,
  `order_id`, `tag`, `parent_order_id`, and `oco_group_id`.

MVP note:

- Phase 30D may use a replay-backed context builder that calls the already
  certified event-v2 command engine. This keeps lifecycle semantics identical
  and makes parity exact. Phase 30E is reserved for the true incremental
  session with preallocated buffers and large workload benchmarks.

Acceptance tests:

- `on_bar_close` is called exactly once after each bar.
- Commands emitted at close `t` cannot fill inside bar `t`.
- Commands become active/fillable from `t+1`.
- Context fills/positions match final result state.
- Rejected commands are visible in the next callback.
- Liquidation prevents further command ingestion.
- Captured `emitted_command_tape` static replay matches equity, positions,
  fills, and command report.

Implemented:

- Added read-only reactive records:
  - `NativeStrategyContext`;
  - `NativeFillEvent`;
  - `NativeOrderEvent`;
  - `NativeActiveOrderSnapshot`;
  - `NativeEventStrategyError`;
  - `NativeEventStrategyProtocol`.
- Added `NativeEventBackend.run_strategy(...)`.
- Added endpoint route:
  - `QuantBTEndpoint.native_event_strategy(...)`;
  - `simulate(..., strategy=...)`.
- Added `context.size_order(...)` using backend quantity constraints.
- Added metadata round-trip into command report, order events, fills, and
  reactive context for:
  - `campaign_id`;
  - `cycle_id`;
  - `level_id`;
  - `order_id`;
  - `tag`;
  - `parent_order_id`;
  - `oco_group_id`.
- Added captured command tape:
  - `result.metadata["emitted_command_tape"]`;
  - `emitted_command_count`;
  - `strategy_callback_count`;
  - `reactive_context_builder`.
- Added clear callback failure errors with bar index and timestamp.

Latest tests:

- Phase 30D reactive runner tests: `6 passed`.
- Phase 30A/30B/30C/30D lifecycle suites: `29 passed`.
- Endpoint/Nautilus compatibility subsets: `50 passed`.
- Full non-real regression: `424 passed, 1 skipped, 3 warnings`.

Technical debt after Phase 30D:

- The MVP context builder is replay-backed through the certified event-v2
  command engine. It preserves exact semantics and replay parity, but it is not
  the final high-throughput incremental session.
- Scoped `CANCEL_ALL` filters and large dynamic-grid benchmarks remain Phase
  30E.
- Nautilus exchange-native cancel/amend parity remains future work.

### Phase 30E - Incremental Reactive Session And Dynamic Grid Certification

Status: completed.

Goal:

- Replace the Phase 30D replay-backed context builder with an incremental
  session that appends per-bar commands without recompiling command history.
- Add scoped `CANCEL_ALL` filters:
  - symbol;
  - side;
  - order type;
  - tag;
  - tag prefix;
  - parent order id;
  - OCO group id;
  - campaign/group ids.
- Add dynamic grid fixture and benchmark:
  - 25,000 bars;
  - 15-30 active grid orders;
  - 1-5 commands per bar;
  - static tape vs reactive FAST vs reactive AUDIT;
  - full accounting parity between FAST and AUDIT.

Non-goals retained:

- No tick matching.
- No L2 book/queue priority.
- No exchange-native Nautilus cancel/amend parity.
- No async/live broker runtime.

Implementation notes:

- `NativeEventBackend.run_strategy(...)` now uses an incremental reactive
  session for callback context instead of replaying/recompiling command history
  on every bar.
- Final accounting, fills, positions, fees, margin, liquidation, and reports
  still come from one static `event_v2` replay of the emitted command tape.
- `reactive_execution_mode="fast"` and `"audit"` keep the same public API.
  Audit mode stores `reactive_audit` final equity/position diffs.
- Reactive strategy metadata now reports:
  - `reactive_context_builder="incremental_session_v1"`;
  - `reactive_incremental_compile_replays=0`;
  - `emitted_command_tape`;
  - `emitted_command_count`.
- Kernel `CANCEL_ALL` now supports scoped numeric filters:
  - symbol;
  - side;
  - order type;
  - parent order id;
  - group id;
  - OCO group id.
- Reactive string-scoped `CANCEL_ALL` supports:
  - exact tag;
  - tag prefix;
  - campaign id;
  - cycle id;
  - level id.
  These commands are expanded into explicit target `CANCEL` commands before
  final static replay so final accounting remains replayable by the Numba
  kernel.
- Active-order snapshots now include `group_id`.
- Core path optimization:
  - incremental session tracks only active/waiting pending orders;
  - filled/canceled/rejected historical orders are no longer scanned every bar;
  - pandas/report construction is kept out of the callback loop.

Validation:

- Phase 30A/30B/30C/30D/30E lifecycle suites: `33 passed`.
- Full quantbt unit regression: pending for final phase closeout.
- 25,000-bar dynamic grid benchmark:
  - 20 active grid levels;
  - 10,438 emitted commands;
  - 10,438 fills;
  - reactive context runtime: `3.5069s`;
  - final static replay runtime: `1.6560s`;
  - total runtime: `5.1629s`;
  - max equity diff vs static replay: `0.0`;
  - max position diff vs static replay: `0.0`.

Final Phase 30E conclusion:

- The urgent native-event lifecycle stack is now usable for dynamic DCA/grid,
  recurring order management, reactive re-arm, scoped cancellation, and audit
  replay workflows on OHLC bars.
- The trusted accounting source remains the Numba event-v2 kernel.
- Remaining future work is intentionally outside Phase 30:
  - tick/L2 book simulation;
  - exchange-native Nautilus cancel/amend/OCO order-list parity;
  - async broker runtime;
  - portfolio-margin venue clones.

Technical debt after Phase 30E:

- Add dedicated event-specific human loggers for:
  - native event v1;
  - native event v2 lifecycle;
  - reactive native-event strategy runner;
  - Nautilus validation adapter.
- Current `simulate(show_order_logs=True)` is a bounded generic helper and is
  useful for quick fill/order visibility, but it is not a full execution trace.
- Future logger should support bounded output modes such as:
  - `fills_only`;
  - `order_events`;
  - `bar_state`;
  - `margin_debug`;
  - `full_execution_trace`.
- Expected per-line fields:
  - timestamp/bar;
  - order id / command id / event type;
  - symbol, side, order type, qty, fill price;
  - intended price, trigger price, realized slippage;
  - fee, turnover;
  - realized/unrealized PnL when available;
  - equity before/after;
  - initial margin, maintenance margin, free/available equity;
  - reject/cancel/expire reason;
  - active/waiting order count.
- This should be implemented as a reporting layer over existing artifacts
  (`fills`, `command_report`, `order_events`, `diagnostics`, `margin`) instead
  of changing matching/accounting kernels.
- Priority is lower than core kernel/domain upgrades, portfolio/arbitrage
  engine depth, and Nautilus execution parity.

## 1. Mục tiêu

Bổ sung một **reactive lifecycle runner** lên `native_event v2` hiện tại để strategy có thể:

1. Nhận trạng thái execution thực tế sau mỗi bar.
2. Đọc fills, position và active orders do QuantBT tạo.
3. Phát `OrderCommand[]` cho bar tiếp theo.
4. Không phải tự kiểm tra `high/low` hoặc tự mô phỏng fill trong strategy.

Đây không phải full exchange OMS và không thay đổi matching/accounting kernel hiện tại.

Mục tiêu chính là hỗ trợ đúng domain cho:

* Dynamic grid.
* Recurring DCA.
* Re-arm order sau khi exit.
* Cancel/amend level theo indicator mới.
* Regime switch.
* Parent-child nhiều chu kỳ.
* Stateful scale-in/scale-out strategies.

---

## 2. Vấn đề hiện tại

`native_event v2` đã hỗ trợ:

```text
PLACE
CANCEL
REPLACE
AMEND
CANCEL_ALL
MARKET / LIMIT / STOP
parent-child
OCO
reduce-only
GTD
```

Nhưng public backend hiện vẫn chạy theo mô hình:

```python
run_order_commands(
    commands: Sequence[OrderCommand],
    market_arrays=...,
)
```

Tức là toàn bộ command tape phải được tạo trước simulation.

Mô hình này không đủ cho recurring dynamic grid:

```text
entry fill
→ strategy cần biết fill thực tế
→ tạo exit cho đúng filled quantity
→ exit fill
→ re-arm entry
→ amend grid theo level mới
```

Strategy không thể biết trước các event này nếu không tự mô phỏng fills, dẫn đến duplicate execution logic và nguy cơ sai parity.

---

## 3. Public API đề xuất

### Phương án chính

```python
endpoint = QuantBTEndpoint.native_event_strategy(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0005,
    slippage_bps=1.0,
    report_level="minimal",
)

result = endpoint.simulate(
    data=df,
    strategy=DynamicGridStrategy(params),
    symbols=["ETHUSDT"],
)
```

Hoặc giữ endpoint hiện tại:

```python
endpoint = QuantBTEndpoint.native_event_lifecycle(...)

result = endpoint.simulate_strategy(
    data=df,
    strategy=DynamicGridStrategy(params),
)
```

Không thay đổi API hiện có:

```python
simulate(order_commands=[...])
```

Static command tape và reactive strategy runner phải cùng dùng một kernel lifecycle.

---

## 4. Strategy protocol

```python
class NativeEventStrategyProtocol:
    def initialize(
        self,
        context: "NativeStrategyContext",
    ) -> list[OrderCommand]:
        ...

    def on_bar_close(
        self,
        context: "NativeStrategyContext",
    ) -> list[OrderCommand]:
        ...

    def finalize(
        self,
        context: "NativeStrategyContext",
    ) -> list[OrderCommand]:
        ...
```

MVP chỉ cần:

```text
initialize
on_bar_close
finalize
```

Chưa cần tick callback, order-book callback hoặc intrabar strategy callback.

---

## 5. Read-only strategy context

```python
@dataclass(frozen=True)
class NativeStrategyContext:
    bar_index: int
    timestamp: pd.Timestamp

    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    equity: float
    available_equity: float
    initial_margin: float
    maintenance_margin: float

    positions: Mapping[str, float]

    fills_this_bar: Sequence[FillEvent]
    order_events_this_bar: Sequence[OrderEvent]
    active_orders: Sequence[ActiveOrderSnapshot]

    liquidated: bool
```

`active_orders` cần chứa tối thiểu:

```text
order_id
symbol
side
order_type
status
remaining_qty
price
trigger_price
reduce_only
parent_order_id
oco_group_id
tag
```

Context chỉ đọc. Strategy không được sửa trực tiếp engine state.

---

## 6. Timeline causal bắt buộc

Tại bar `t`:

```text
1. Activate commands đã được submit từ trước.
2. Xử lý trigger và fills bằng OHLC[t].
3. Áp dụng fee, funding, margin và liquidation.
4. Cập nhật positions/equity.
5. Emit fill/order events của bar t.
6. Gọi strategy.on_bar_close(context_t).
7. Commands trả về chỉ active từ bar t+1.
```

Default phải là:

```python
command_effective_phase = "next_bar"
```

Như vậy strategy dùng indicator tại close `t` nhưng không thể retroactively đặt order trong high/low của chính bar `t`.

Không cho callback sửa kết quả bar đã xử lý.

---

## 7. Không mô phỏng fill trong strategy

Strategy chỉ được:

```text
tính indicator
xác định regime
xác định desired grid levels
PLACE / CANCEL / AMEND orders
quản lý campaign_id và level_id
phản ứng với fill events thật
```

QuantBT tiếp tục là nguồn duy nhất cho:

```text
limit touch
fill price
slippage
fee
position
average entry
margin
funding
liquidation
reduce-only clipping
OCO
parent activation
order status
```

---

## 8. Dynamic command ingestion

Kernel/session cần cho phép append commands sau mỗi bar mà không compile lại toàn bộ lịch sử.

Đề xuất internal structure:

```text
prepared market arrays
active-order registry
per-bar command buffer
preallocated command/event arrays
free-slot stack
```

API nội bộ:

```python
session.submit_commands(
    commands,
    effective_bar=current_bar + 1,
)
```

Không nối lại toàn bộ `Sequence[OrderCommand]` rồi chạy lại simulation từ đầu.

---

## 9. Scoped `CANCEL_ALL`

Dynamic grid cần hủy đúng campaign hoặc đúng side, không được luôn hủy toàn bộ account.

Mở rộng `CANCEL_ALL` với filter tùy chọn:

```python
OrderCommand(
    action=OrderAction.CANCEL_ALL,
    symbol="ETHUSDT",
    side=OrderSide.BUY,
    tag_prefix="GRID-C12-LONG-ENTRY",
)
```

Các scope cần thiết:

```text
symbol
side
order_type
tag
tag_prefix
parent_order_id
oco_group_id
```

Nếu chưa muốn đưa string filter vào Numba, compiler map tag/campaign/group thành integer code.

---

## 10. Metadata round-trip

Các trường sau phải được giữ xuyên suốt:

```text
order command
→ active order
→ order event
→ fill
→ result reports
```

Fields:

```text
order_id
tag
campaign_id
cycle_id
level_id
parent_order_id
oco_group_id
```

Có thể lưu các domain ID dưới dạng integer code trong kernel và decode khi tạo pandas reports.

Điều này cần thiết để strategy biết:

```text
fill này thuộc level nào
exit nào vừa đóng
entry nào cần re-arm
campaign nào cần cancel
```

---

## 11. Quantity semantics

MVP tiếp tục dùng `qty`, nhưng nên thêm shared sizing helper ngoài strategy:

```python
qty = context.size_order(
    symbol="ETHUSDT",
    notional=cash_per_entry,
    price=limit_price,
)
```

Helper phải dùng cùng venue constraints với backend:

```text
contract_size
qty_step
lot_size
min_qty
min_notional
```

Strategy không nên tự lặp lại rounding logic.

Không nhất thiết phải thêm `notional` vào kernel command trong phase này.

---

## 12. Performance

### Hai mode

```python
execution_mode="fast"
execution_mode="audit"
```

`fast`:

* Reuse prepared market arrays.
* Chỉ tạo context tối thiểu.
* Không dựng DataFrame trong bar loop.
* Fills/events dùng lightweight views hoặc arrays.
* Không lưu full active-order snapshots mỗi bar.
* `report_level="minimal"`.
* Dùng cho Optuna và WFO.

`audit`:

* Full `order_events`.
* Full active-order diagnostics.
* Command tape export.
* Dùng cho candidate cuối.

### Không gọi pandas trong hot loop

Alpha indicators nên được tính trước thành NumPy arrays:

```python
strategy.prepare(data) -> PreparedStrategyArrays
```

`on_bar_close()` chỉ đọc array tại `bar_index`.

### Không copy toàn bộ registry

Context chỉ expose:

```text
position vector
fills/events vừa phát sinh
active-order view cần thiết
```

Không copy tất cả historical events mỗi bar.

### Benchmark bắt buộc

Thêm benchmark:

```text
25,000 bars
15–30 concurrent grid orders
1–5 commands/bar
multiple fill/re-arm cycles
```

So sánh:

```text
static command tape
reactive FAST
reactive AUDIT
```

Reactive FAST không nên chậm hơn Python event loop ngây thơ và phải đủ dùng cho Optuna trên dữ liệu 1h.

---

## 13. Determinism

Cùng:

```text
market data
strategy parameters
initial state
random seed
```

phải tạo chính xác cùng:

```text
command tape
fills
positions
equity
reports
```

Command ordering:

```text
bar_index
callback_sequence
command_sequence
```

Commands strategy trả về phải giữ nguyên stable list order.

---

## 14. Failure handling

Nếu strategy callback raise exception:

```text
stop simulation
return bar_index/timestamp gây lỗi
không trả partial metrics như một backtest hợp lệ
```

Nếu command bị reject:

* Event phải xuất hiện trong `order_events`.
* Strategy nhận event đó ở callback tiếp theo.
* Không tự động retry trừ khi strategy yêu cầu.

Nếu liquidation xảy ra:

* Cancel toàn bộ active orders.
* Context đánh dấu `liquidated=True`.
* Không tiếp tục submit order mới mặc định.

---

## 15. Captured command tape

Reactive runner phải lưu toàn bộ commands mà strategy đã phát:

```python
result.metadata["emitted_command_tape"]
```

Hoặc:

```python
result.command_tape
```

Dùng cho:

* Audit.
* Reproduction.
* Replay static.
* So sánh strategy-state với engine-state.
* Nautilus validation.

Một reactive run phải có thể replay bằng:

```python
endpoint.simulate(
    data=df,
    order_commands=result.command_tape,
)
```

và cho kết quả native-event giống hệt.

Đây là acceptance criterion quan trọng nhất.

---

## 16. Nautilus validation follow-up

Support matrix hiện ghi native lifecycle đã hỗ trợ đầy đủ phía native, nhưng Nautilus command path mới payload-aligned; cancel/amend chưa có exchange-native parity đầy đủ.

Sau MVP reactive runner, bổ sung adapter:

```python
replay_lifecycle_tape_with_nautilus(
    data,
    command_tape,
)
```

Mapping:

```text
PLACE   → submit_order
CANCEL  → cancel_order
REPLACE → cancel + submit hoặc modify đúng Nautilus API
AMEND   → modify_order
```

Validation report:

```text
order lifecycle status
fill count
fill qty
position by bar
fees
realized PnL
final equity
```

Nautilus không cần nằm trong optimization loop; chỉ validate candidate cuối.

---

## 17. Acceptance tests bắt buộc

### Core runner

1. Callback được gọi đúng một lần sau mỗi bar.
2. Command sinh tại close `t` không thể fill trong bar `t`.
3. Command bắt đầu active tại `t+1`.
4. Position/fills trong context khớp result cuối.
5. Rejected command được trả về callback.
6. Liquidation khóa strategy đúng cách.
7. Static replay của captured command tape cho parity 100%.

### Dynamic grid fixture

1. Place 3 buy limits.
2. Một entry fill.
3. Chỉ child exit của đúng level được tạo.
4. Exit fill ở bar sau.
5. Entry level được re-arm.
6. Grid level thay đổi thì pending order được amend.
7. Regime switch cancel đúng pending side.
8. Reduce-only market command đóng inventory.
9. Không tồn tại stale hoặc duplicate order.
10. Không có same-bar entry/exit nếu strategy không chủ động yêu cầu.

### Performance

* Prepared market arrays được reuse.
* Không compile lại toàn bộ command history mỗi bar.
* FAST và AUDIT có accounting parity.
* Memory không tăng tuyến tính theo `bars × active_orders snapshots`.

---

## 18. Non-goals

Không cần bổ sung:

```text
tick matching
L2 order book
queue position
exchange latency
market impact model
distributed event bus
live broker connectivity
async strategy runtime
full exchange OMS
```

Runner chỉ là cầu nối reactive giữa:

```text
strategy state
↔ native-event lifecycle kernel
```

---

## 19. Những phần cần hoàn thành trước khi viết lại grid alpha

### Blocker bắt buộc

* Reactive `on_bar_close` runner.
* Context có positions, fills và active orders.
* Commands effective từ next bar.
* Scoped `CANCEL_ALL`.
* Metadata/tag/level ID round-trip.
* Captured command tape.
* Static replay parity test.

### Nên có ngay

* Shared notional-to-qty sizing helper.
* `report_level="minimal"` cho Optuna.
* Prepared strategy/market arrays.
* Dynamic grid integration fixture.
* Clear error khi duplicate `order_id`.

### Có thể làm sau alpha MVP

* Nautilus exchange-native cancel/amend adapter.
* Partial fills.
* Volume-capped fills.
* Intrabar callback.
* Same-close callback phase.
* Numba-compiled strategy callback protocol.

---

## 20. Deliverable cuối

Sau nâng cấp, grid alpha phải được viết theo dạng:

```python
class DynamicGridStrategy:
    def prepare(self, data, params):
        # Tính trước MA, ATR, regime và grid levels.
        ...

    def on_bar_close(self, context):
        # Đọc fills/active orders thật.
        # Sinh PLACE/CANCEL/AMEND cho bar tiếp theo.
        # Không kiểm tra high/low để tự quyết định fill.
        return commands
```

Backtest:

```python
endpoint = QuantBTEndpoint.native_event_strategy(
    initial_capital=20_000,
    leverage=5,
    fee_rate=0.0005,
    report_level="minimal",
)

result = endpoint.simulate(
    data=data_eth,
    strategy=DynamicGridStrategy(params),
)
```

Sau khi runner này hoàn thành, có thể viết lại `grid_long_only` và `grid_combine` thành một unified alpha mà không cần bất kỳ fill simulator nào bên trong strategy.

---

## Phase 31 - Execution Correctness And Fast Intrabar Upgrade

Status: complete for the current single-symbol OHLC intrabar scope. Phase 31A,
Phase 31B, Phase 31C, and Phase 31D implemented on
`feat/31-execution-correctness-intrabar`.

Source design document:

- [`upgrade/quantbt_phase17_execution_correctness_fast_intrabar_upgrade.md`](./quantbt_phase17_execution_correctness_fast_intrabar_upgrade.md)

Why this is tracked as Phase 31 here:

- The source document is named "Phase 17" because it describes the conceptual
  execution-correctness upgrade.
- `upgrade/implement.md` already uses Phase 17 for the Options Backtest Engine
  history, so the implementation roadmap is tracked as Phase 31 to avoid
  confusing future agents.

Branch recommendation:

- Do not continue this large upgrade on `feat/30-native-event-lifecycle`.
- First finish/push/merge the Phase 30 native-event lifecycle branch into
  `dev` if accepted.
- Then create a clean branch from updated `dev`, recommended:

```bash
git switch dev
git pull --ff-only origin dev
git switch -c feat/31-execution-correctness-intrabar
```

Reason:

- This upgrade changes execution contracts, market tape validation, vectorized
  semantics, endpoint routing, fill replay, and benchmark/certification docs.
- Keeping it separate from Phase 30 avoids coupling reactive native-event
  lifecycle work with a broader vectorized/intrabar correctness migration.

Implementation should be compressed from the source document's Phase 17A-J into
four practical phases:

### Phase 31A - Semantic Freeze, P0 Safety, And Contract Manifest

Scope:

- Preserve existing close-target behavior but label it explicitly as
  `close_target_v2`.
- Add mandatory result metadata:
  - `engine_id`;
  - `backend_alias`;
  - `execution_contract`;
  - `signal_phase`;
  - `fill_phase`;
  - `intrabar_exit_model`;
  - `kernel_version`;
  - `data_signature` when available.
- Add P0 safety checks without changing intentional close-target PnL:
  - no silent fake funding fallback;
  - no unsupported execution config silently passing through;
  - no high/low fallback when intrabar liquidation is required;
  - explicit first-bar target policy;
  - open/volume plumbing for routes that need it.
- Add warnings/errors for likely intrabar misuse on close-target endpoints,
  especially columns such as `exit_price`, `exit_type`, `stop_loss`,
  `take_profit`, `trailing`.

Tests:

- Golden close-target parity before/after.
- Metadata contract tests.
- Strict unsupported-config tests.
- Funding missing-symbol tests.
- High/low missing under liquidation tests.

Acceptance:

- Existing valid close-target alpha results remain reproducible.
- Silent execution ambiguity becomes explicit metadata, warning, or error.
- No intrabar engine implementation yet.

Implementation notes after Phase 31A:

- `native_vectorized` now declares the close-target execution contract via
  metadata:
  - `engine="close_target_v2"`;
  - `engine_id="close_target_v2"`;
  - `backend_alias="native_vectorized"`;
  - `kernel_version="units_v2"`;
  - `signal_phase="bar_close"`;
  - `fill_phase="same_close"`;
  - `intrabar_exit_model="none"`;
  - `first_bar_target_policy`;
  - `data_signature`.
- `NativeVectorizedConfig` fails fast on unsupported execution config for the
  close-target contract:
  - non-close fill price policy;
  - non-conservative same-bar policy;
  - partial fills;
  - min order notional;
  - disabling insufficient-margin rejection.
- Funding dictionaries no longer synthesize `0.0001` for missing symbols; the
  caller must pass the symbol explicitly, pass scalar funding, or disable
  funding.
- Missing high/low on native-vectorized close-target runs is now marked with
  `high_low_source="close_fallback_uncertified_intrabar_risk"` and emits a
  bounded warning. Phase 31B will replace this compatibility fallback with
  strict prepared-tape certification.
- Reactive native-event facade now passes `open` and `volume` from the input
  frame into strategy context.
- Close-target endpoint warns and marks runs as
  `uncertified_intrabar_columns_on_close_target` if the input dataframe
  contains likely intrabar artifacts such as `exit_price`, `stop_loss`,
  `take_profit`, or `trailing`.

Validation after Phase 31A:

- `tests/test_phase31a_execution_correctness_contract.py`: `6 passed`.
- Targeted regression:
  `tests/test_phase2_native_vectorized.py`,
  `tests/test_endpoint.py`,
  `tests/test_phase30d_native_event_reactive_runner.py`,
  `tests/test_phase30e_native_event_incremental_runner.py`,
  `tests/test_phase9_performance_parity.py`: `42 passed`.

### Phase 31B - Strict Prepared Market Tape And Python Intrabar Oracle

Scope:

- Add execution contract schema and registry:
  - `close_target_v2`;
  - `next_open_v1`;
  - `intrabar_bracket_v1`;
  - `fill_replay_v1`;
  - `event_lifecycle_v2`.
- Add strict `PreparedMarketTape` with validation certificate:
  - monotonic timestamps;
  - duplicate rejection;
  - finite OHLCV;
  - OHLC invariant;
  - explicit funding policy;
  - no ffill/bfill OHLC in strict mode.
- Add Python reference oracle for single-symbol linear intrabar execution:
  - signal at close;
  - entry at next open;
  - gap-aware SL;
  - TP limit policy;
  - same-bar ambiguity;
  - trailing update effective next bar;
  - technical exit;
  - reversal as two fee/slippage legs;
  - close-on-last-bar policy.

Tests:

- Golden scenario matrix from the source document.
- No-lookahead timeline tests.
- Same-bar SL/TP ambiguity tests.
- Gap stop tests.
- Long/short symmetry tests.
- Strict tape validation tests.

Acceptance:

- Oracle is readable and becomes the internal truth model.
- Prepared and non-prepared market inputs produce identical canonical arrays.
- No Numba intrabar kernel is promoted until oracle tests are stable.

Implementation notes after Phase 31B:

- Added `core/execution_contract.py` with the execution contract registry:
  `close_target_v2`, `next_open_v1`, `intrabar_bracket_v1`,
  `fill_replay_v1`, and `event_lifecycle_v2`.
- Added `core/market_tape.py` with strict immutable `PreparedMarketTape` and
  `MarketValidationCertificate`.
  - It rejects unsorted or duplicate timestamps.
  - It rejects missing OHLC, NaN/inf, invalid OHLC invariants, non-positive
    prices, and negative volume.
  - It does not sort, deduplicate, forward-fill, back-fill, or synthesize
    high/low from close.
  - Funding dicts must explicitly cover every symbol.
- Added `core/intrabar_reference.py` as the readable single-symbol truth model
  for `intrabar_bracket_v1`.
  - Signal at close becomes executable at next open.
  - Stops are gap-aware.
  - Take-profit is limit-conservative by default.
  - Same-bar SL/TP ambiguity is flagged and conservatively resolved.
  - Trailing updates are effective from the next bar, not the same bar.
  - Reversal pays two explicit legs: exit old position and enter new position.
  - Optional final close is controlled by the execution contract.
- Added public exports from `quantbt` and `quantbt.core`.
- Added `QuantBTEndpoint.intrabar_bracket_reference(...)`.
  - The endpoint accepts a compact signed `signal` / `signal_col` where sign is
    side and absolute value is entry quantity.
  - Optional SL/TP/trailing/technical-exit columns are mapped through
    `intent_cols` instead of requiring a wide fixed strategy schema.
  - The endpoint returns `BacktestResultV2`, normalized `fills_report`,
    diagnostics, validation certificate, and normal `show_metrics()` /
    `full_report()` compatibility.

Validation after Phase 31B:

- `tests/test_phase31b_market_tape_intrabar_oracle.py`: strict tape,
  execution-contract registry, funding dict strictness, same-bar ambiguity,
  next-bar trailing, reversal double-fee accounting, and public endpoint smoke.

Remaining for Phase 31C:

- Promote the oracle semantics into a Numba fast intrabar kernel.
- Add sparse audit ledger / second-pass fill replay.
- Add parity tests between oracle, native event, and the new Numba kernel.
- Add benchmark gates for `minimal`, `standard`, and `audit` report levels.

### Phase 31C - Numba Fast Intrabar Kernel, Audit Ledger, And Fill Replay

Scope:

- Add fast Numba intrabar kernels:
  - `next_open_v1`;
  - `intrabar_bracket_v1` fixed SL/TP;
  - trailing-enabled variant when safe;
  - compact event flags.
- Add `report_level`:
  - `minimal` for optimizer/WFO;
  - `standard` for normal endpoint reports;
  - `audit` for sparse fills/trades.
- Implement two-pass audit ledger:
  - pass 1 computes accounting and exact fill count;
  - pass 2 writes sparse fill/trade arrays only in audit mode;
  - minimal/audit core equity parity must hold.
- Add `fill_replay_v1` migration backend for old alphas that already emit
  explicit fills.

Tests:

- Python oracle vs Numba parity.
- Minimal vs audit parity.
- Fill replay accounting identity.
- Reversal two-leg fee/turnover tests.
- Liquidation/funding tests.
- Endpoint compatibility tests.

Benchmarks:

- Kernel-only warm JIT ratios versus `close_target_v2`.
- Prepared endpoint ratios.
- Native-event comparison for single-position bracket cases.
- Memory profile for minimal vs audit.

Acceptance:

- Intrabar kernel is materially faster than native-event for single-position
  bracket workloads.
- No Python objects are created in hot loops.
- Audit mode is deterministic and preserves exact fill sequence.

Implementation notes after Phase 31C:

- Added `core/intrabar_kernel.py`:
  - `_engine_intrabar_bracket_v1` is a Numba single-symbol linear intrabar
    kernel for `intrabar_bracket_v1`;
  - `run_intrabar_kernel(...)` wraps the kernel and returns
    `NativeIntrabarKernelResult`;
  - `report_level="minimal"` and `standard` avoid sparse fill materialization;
  - `report_level="audit"` runs deterministic pass 2, allocates exact-size
    sparse fill arrays, materializes fills/report, and asserts pass-1 parity;
  - `FillReplayTape` and `run_fill_replay_kernel(...)` provide
    `fill_replay_v1` accounting migration.
- Corrected the Python oracle accounting for entry slippage:
  - PnL after entry now marks from actual fill price, not raw bar open;
  - this makes fee/slippage legs explicit and gives the Numba kernel a correct
    parity target.
- Added simple single-symbol margin/risk semantics to oracle and kernel:
  - initial margin rejection with account leverage and margin buffer;
  - conservative intrabar maintenance breach liquidation for unprotected paths;
  - full venue mark-price liquidation remains future certification work.
- Added public endpoints:
  - `QuantBTEndpoint.intrabar_bracket(...)` for the fast Numba route;
  - `QuantBTEndpoint.fill_replay(...)` for explicit-fill accounting replay.
- Added public exports from `quantbt` and `quantbt.core`:
  `run_intrabar_kernel`, `NativeIntrabarKernelResult`, `FillReplayTape`,
  `run_fill_replay_kernel`, and `NativeFillReplayResult`.

Validation after Phase 31C:

- `tests/test_phase31c_intrabar_kernel.py` covers oracle parity, audit second
  pass, slippage accounting, trailing/reversal behavior, insufficient-margin
  rejection, single-symbol liquidation, fill replay accounting, endpoint
  standard/audit routes, fill replay endpoint, and warm-kernel speed smoke.

### Phase 31D - Certification, Alpha Audit Tooling, And Docs

Scope:

- Add alpha inventory scanner and registry template.
- Classify alphas into:
  - pure close target;
  - next-open only;
  - intrabar bracket;
  - fill replay migration;
  - event lifecycle/grid/DCA;
  - deferred cross-margin intrabar.
- Add certification levels:
  - Level 0 legacy;
  - Level 1 accounting replay;
  - Level 2 engine-causal;
  - Level 3 cross-backend;
  - Level 4 external validation.
- Add native-event parity scenarios for known intrabar cases.
- Add docs:
  - execution contracts;
  - fast intrabar endpoint;
  - fill replay migration;
  - alpha certification guide;
  - benchmark report.

Tests:

- Scanner smoke tests.
- Migration report fixtures.
- Native intrabar vs native-event known-case parity.
- Public endpoint examples.

Acceptance:

- No old intrabar alpha is silently treated as production-certified.
- Users know which backend to use for each strategy type.
- Production claim requires at least Level 2, and execution-sensitive alphas
  should target Level 3 or Level 4.

Design assessment:

- The direction is correct and materially more institutional than the current
  "one backend name fits all" model.
- It reaches fund-grade methodology once Phase 31A-B are in place because
  semantics, data validation, causality, and oracle truth are explicit.
- It reaches practical production-grade for single-symbol SL/TP/trailing
  intrabar research after Phase 31C parity and benchmark gates pass.
- It should not claim full institutional execution across venues until Phase
  31D plus lower-timeframe/Nautilus parity artifacts exist.

Explicit non-goals for Phase 31:

- No tick/L2 queue simulation.
- No exact shared cross-margin intrabar path claim from OHLC-only data.
- No generic multi-order grid engine inside the intrabar kernel.
- No options Greeks/portfolio option execution in this kernel.
- No Cython/C++ until prepared tape, lazy result, and Numba kernels are profiled.

Implementation notes after Phase 31D:

- Added `core/certification.py`:
  - `CertificationLevel` with Level 0-4 labels;
  - `classify_alpha_source(...)` for conservative source classification;
  - `scan_alpha_directory(...)` for `.py`, `.ipynb`, and `.md` alpha inventory;
  - `build_alpha_certification_report(...)` and `alpha_report_markdown(...)`;
  - `certify_result_metadata(...)` to summarize result metadata into a
    stakeholder-readable certification label.
- Added `tools/audit_alpha_execution_contracts.py`:
  - writes JSON and Markdown alpha execution-contract audit reports;
  - intentionally treats source scanning as a migration hint, not proof of
    causality or absence of look-ahead bias.
- Added Phase 31 benchmark harness:
  - `benchmarks/run_phase31_intrabar.py`;
  - committed `phase31_intrabar_benchmark.json` and
    `phase31_intrabar_benchmark.md` after running the standard 25k-bar profile.
- Added docs:
  - `docs/execution_contracts.md`;
  - `docs/fast_intrabar.md`;
  - `docs/alpha_certification.md`;
  - endpoint and benchmark documentation links.
- Public exports now include certification helpers from `quantbt` and
  `quantbt.core`.

Validation after Phase 31D:

- `tests/test_phase31d_certification.py` covers source classification, metadata
  certification levels, directory scan/report generation, CLI artifact writes,
  and benchmark smoke parity.
- Phase 31A/B/C/D targeted tests pass together with endpoint smoke tests.
- Full unit regression excluding real-data tests passes.
- Benchmark standard profile compares:
  - close-target pure kernel;
  - fast intrabar minimal;
  - fast intrabar audit;
  - Python intrabar oracle;
  - fill replay kernel;
  - native-event explicit-order facade.

Phase 31 certification conclusion:

- Completed:
  - semantic freeze and contract manifest;
  - strict market tape validation;
  - close-target misuse metadata;
  - Python intrabar oracle;
  - Numba fast intrabar bracket kernel;
  - audit ledger second pass;
  - fill replay accounting kernel;
  - public endpoint routes;
  - source scanner and certification docs;
  - reproducible benchmark report.
- Production readiness:
  - practical Level 2 for single-symbol linear next-open SL/TP/trailing
    intrabar research when the alpha emits compact intent columns and benchmark
    parity passes;
  - Level 1 for old explicit-fill alphas using `fill_replay`;
  - Level 3/4 still requires native-event/Nautilus/lower-timeframe parity
    artifacts for each concrete strategy and venue.
- Coverage of
  `quantbt_phase17_execution_correctness_fast_intrabar_upgrade.md` is roughly
  80 percent of the requested institutional methodology: the core semantic,
  oracle, kernel, audit, docs, and scanner work is done. Deferred pieces are
  intentionally outside the current single-symbol OHLC bracket kernel:
  standalone `next_open_v1` facade, broad native-event/Nautilus parity bundles,
  lower-timeframe/tick validation, shared cross-margin intrabar semantics,
  venue-specific liquidation/funding event ordering, and generic DCA/grid
  state machines.


# Upgrade after Phase 31;
## QuantBT Execution Correctness — Các sửa đổi bắt buộc trước khi merge

Status: implemented as two compact follow-up phases on
`feat/31-execution-correctness-intrabar`.

### Phase 31G - Final Merge Blockers From Sol Review

Status: implemented.

Final blockers reviewed:

1. Funding timing semantics.
   - Decision: keep `FundingPhase.POSITION_AT_EVENT` only for funding events
     whose timestamp matches an exact market bar timestamp.
   - Mid-bar funding events now raise and require a smaller timeframe.
   - Added explicit `bar_timestamp_semantics`:
     - `close` default: OHLC timestamp is the bar close, funding applies after
       intrabar execution on the remaining close position;
     - `open`: OHLC timestamp is the bar open, funding applies after open-gap
       marking and before pending exit/entry orders at `open[t]`.
   - `bar_timestamp_semantics` is part of the strict market tape signature, so
     prepared caches cannot be reused across open/close timestamp contracts.
   - Kernel/reference metadata records
     `funding_timing_certified=true` and
     `funding_event_alignment="exact_bar_timestamp"`.
2. Execution contract propagation.
   - Added `ExecutionContract.from_metadata(...)`.
   - `QuantBTEndpoint.intrabar_bracket(...)` and
     `.intrabar_bracket_reference(...)` accept `execution_contract=contract`.
   - Endpoint and `PreparedIntrabarRunner` restore the full contract from
     metadata rather than reconstructing only `close_on_last_bar`.
   - Unsupported fields still raise `NotImplementedError`.
3. Data signature completeness.
   - Strict market tape signature now includes:
     - timestamps;
     - symbols;
     - open/high/low/close;
     - volume;
     - funding rates;
     - funding event mask;
     - bar timestamp semantics.
   - Prepared intrabar runner also freezes a `prepared_signature` containing
     market signature plus account/execution/sizing/constraint profile metadata.

Technical debt handled in the same pass:

- `exit + same-side entry` now emits `ENTRY_SUPPRESSED` instead of counting as
  a rejected order.
- Dynamic trailing has explicit Python-oracle vs Numba parity coverage.
- Added optional `tick_size` conservative price quantization for entry, SL, TP,
  and trailing levels.
- Docs now state the current certified scope as fast, deterministic, audited
  **single-symbol intrabar** execution only.
- Added tests for:
  - funding position phase;
  - open-vs-close bar timestamp funding semantics;
  - execution-contract propagation;
  - signature changes from volume/funding;
  - signature changes from bar timestamp semantics;
  - prepared runner vs normal endpoint parity;
  - minimal/audit parity through the existing audit tests;
  - tick-size price quantization.

Merge gate after Phase 31G:

```bash
pytest -q tests/test_phase31*.py
pytest -q
python3 benchmarks/run_phase31_intrabar.py --rows 25000 --repeats 3
```

Validation after Phase 31G:

- `tests/test_phase31*.py`: 42 passed.
- Full `pytest -q`: 470 passed, 1 skipped.
- Phase31 benchmark: fast intrabar minimal 25k bars in 0.0118s, about 2.11M
  bars/s and 23.32x faster than the Python oracle.

Merge certification scope:

> Fast, deterministic, and audited single-symbol intrabar execution kernel.

### Phase 31H - Session-Aware Intrabar Reference Contract

Status: implemented on `feat/31-execution-correctness-intrabar`.

Source:

- Supplemental section `# PHẦN UPDATE BỔ SUNG:` in
  `upgrade/quantbt_phase17_execution_correctness_fast_intrabar_upgrade.md`.
- This phase is the user's requested new "Phase 31E"; it is tracked as 31H
  here because historical Phase 31E/F entries already exist below for earlier
  merge-blocker work.

Scope:

- Add session execution schemas:
  - `EntryPositionPolicy`;
  - `SessionCounterBasis`;
  - `ProtectiveExitReentryPolicy`;
  - `SessionExecutionPolicy`;
  - `IntrabarSessionTape`.
- Keep `ExecutionContract` unchanged; session policy owns only session mutable
  execution state.
- Extend intrabar endpoint and prepared runner with optional:
  - `session_policy`;
  - `session_tape`.
- Preserve backward compatibility:
  - `session_policy=None` means existing intrabar reference/kernel behavior is
    unchanged;
  - session feature requires both policy and tape;
  - fast kernel raises for session mode until Phase 31I.
- Implement session semantics in the Python reference oracle:
  - session reset;
  - entry time window;
  - force-flat at open;
  - flat-only/no-reversal;
  - per-session long/short entry quota;
  - stale pending signal cancellation across session boundaries;
  - protective-exit re-entry suppression.
- Add audit flags and metadata counts:
  - `SESSION_RESET`;
  - `SESSION_FORCED_EXIT`;
  - `ENTRY_WINDOW_BLOCKED`;
  - `ENTRY_QUOTA_BLOCKED`;
  - `FLAT_ONLY_BLOCKED`;
  - `STALE_SESSION_SIGNAL`;
  - `PROTECTIVE_REENTRY_BLOCKED`.

Tests:

- No-session reference output parity.
- Session boundary resets counters.
- Last-bar session signal does not fill in the new session.
- Flat-only blocks reversal and does not close old position implicitly.
- Entry quota blocks the next entry without counting rejects.
- Margin/quantity reject does not increment quota.
- Entry fill then same-bar SL still increments quota.
- Force-flat bar closes position and blocks new entry when configured.
- Protective exit at bar `t` suppresses signal from bar `t` at open `t+1`.

### Phase 31I - Fast Prepared Session Kernel

Status: implemented on `feat/31-execution-correctness-intrabar`.

Scope:

- Compile `SessionExecutionPolicy` into integer policy codes.
- Add a separate `run_intrabar_session_kernel(...)`; do not add a
  `session_enabled` branch to the existing fast kernel hot loop.
- Dispatch once before execution:
  - no session -> existing fast kernel;
  - session enabled -> session-specific kernel.
- Include session policy and session tape signature in prepared-context cache
  signatures.
- Differential-test session fast kernel against Phase 31H reference oracle.
- Benchmark:
  - existing fast kernel unchanged;
  - session kernel overhead isolated;
  - prepared/non-prepared parity preserved.

Acceptance:

- Existing intrabar workloads remain bit-for-bit stable when no session policy
  is supplied.
- Session-aware intrabar alphas get reference-correct behavior, audit metadata,
  and later Numba parity without becoming a generic mutable state-machine
  engine.

Implementation notes after Phase 31I:

- Added `run_intrabar_session_kernel(...)`.
  - Uses a separate `_engine_intrabar_session_bracket_v1` Numba kernel.
  - Does not add a `session_enabled` branch to the existing
    `_engine_intrabar_bracket_v1` hot loop.
  - Supports `minimal`, `standard`, and `audit` report levels.
  - Audit mode uses the same two-pass sparse fill ledger pattern as the
    original intrabar kernel.
- Endpoint dispatch:
  - `intrabar_bracket(...)` runs the old fast kernel when no session policy is
    configured;
  - `intrabar_bracket(..., session_policy=...)` runs the session kernel when
    `backtest(..., session_tape=...)` is supplied.
- Prepared runner dispatch:
  - no session -> old prepared fast kernel;
  - session -> session prepared fast kernel.
  - prepared profile metadata includes `session_policy` and
    `session_tape_signature`.
- Added public exports:
  - `run_intrabar_session_kernel` from `quantbt`;
  - `run_intrabar_session_kernel` from `quantbt.core`.
- Extended Phase 31 benchmark report with:
  - `intrabar_session_bracket_v1_minimal`;
  - `intrabar_session_bracket_v1_audit`.

Validation after Phase 31H:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests/test_phase31h_intrabar_session_reference.py
# 12 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests/test_phase31*.py
# 56 passed
```

Validation after Phase 31I:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests/test_phase31h_intrabar_session_reference.py
# 14 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests/test_phase31*.py
# 58 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python quantbt/benchmarks/run_phase31_intrabar.py --rows 25000 --repeats 3
```

Benchmark after Phase 31I:

- `intrabar_bracket_v1_minimal`: `0.011815s`, about `2.12M bars/s`.
- `intrabar_session_bracket_v1_minimal`: `0.011652s`, about `2.15M bars/s`.
- `intrabar_session_bracket_v1_audit`: `0.049885s`, about `501k bars/s`.
- Session audit parity: `pass`.
- Session minimal speedup vs Python oracle: about `20.55x`.

### Phase 31E - Merge Blocker Execution Correctness

Implemented:

- `slippage_bps` is the source of truth for intrabar endpoints:
  - fast/reference intrabar routes now pass `config.execution.slippage_rate`;
  - legacy `slippage` on intrabar factories is converted once with a
    deprecation warning;
  - passing both `slippage` and `slippage_bps` raises;
  - intrabar run config records `legacy_slippage_rate=None`.
- Funding is event-causal in strict market tape:
  - scalar funding is rejected in strict mode;
  - zero funding requires `use_funding=False` or
    `missing_funding_policy="zero"`;
  - `funding_event_timestamps` and `funding_event_rates` are supported;
  - events must match an exact market bar timestamp;
  - `bar_timestamp_semantics="close"` applies funding after intrabar execution
    on the close position;
  - `bar_timestamp_semantics="open"` applies funding before pending open
    orders at `open[t]`.
- Strict timezone:
  - naive market data is rejected unless `source_timezone` is provided;
  - source timezone is localized first, then converted to UTC;
  - data signatures are created after UTC normalization.
- Dynamic trailing now uses `trailing_value[t]` at close `t`; the new trailing
  level only affects later bars.
- Intrabar intent supports side-specific `exit_long` and `exit_short`;
  legacy `technical_exit` remains a compatibility alias for both sides.
- Same-side `exit + entry` conflict is `exit only`; opposite entry remains a
  two-leg reversal.
- Intrabar sizing compiler added:
  - `units`;
  - `fixed_notional`;
  - `pct_equity`;
  - `risk_per_trade`.
- Shared quantity constraints are applied to intrabar entry quantity:
  - `qty_step` / `lot_size` / `slot_size`;
  - `min_qty`;
  - `min_notional`.
- Unsupported `ExecutionContract` fields are rejected with
  `NotImplementedError` instead of being silently ignored.
- Fill replay certification metadata is granular:
  - price and fee accounting are certified;
  - funding, margin, liquidation, generation, and causality are explicitly not
    certified by the current fill replay implementation.

### Phase 31F - Prepared Intrabar Runner, Docs, And Regression Lock

Implemented:

- Added `PreparedIntrabarRunner`:
  - `runner = bt.prepare_intrabar(data=df, symbols=[...])`;
  - `runner.run(intent, report_level="minimal")`;
  - `runner.run(intent, report_level="audit")`;
  - caches strict OHLCV arrays, funding arrays, validation certificate, data
    signature, quantity constraints, and frozen profile metadata.
- Added endpoint support for event funding inputs:
  - `funding_event_timestamps`;
  - `funding_event_rates`.
- Added docs for:
  - `slippage_bps`;
  - funding events;
  - side-specific exits;
  - intrabar sizing;
  - prepared runner usage.
- Added `tests/test_phase31_merge_blockers.py` covering the Sol blocker list
  implemented in this compact follow-up.

Validation:

- `tests/test_phase31_merge_blockers.py`: 11 passed.
- Phase31 A/B/C/D/E/F targeted suite: 39 passed.
- Endpoint/native smoke suite: 41 passed.

Remaining outside this compact follow-up:

- A full `QuantBTProfile` / profile registry façade for every strategy family.
- Output contract classes for portfolio, grid, DCA, arbitrage, and options.
- Broad automatic output routing across all execution families.
- L2/tick/lower-timeframe validation and Nautilus Level 4 bundles for each
  concrete alpha.

## 1. Các lỗi phải sửa trước

### 1.1 `slippage_bps` là nguồn cấu hình duy nhất

Intrabar kernel phải lấy slippage từ:

```python
slippage_rate = execution.slippage_bps / 10_000.0
```

Không được đồng thời duy trì hai nguồn:

```python
slippage
slippage_bps
```

Nếu legacy API truyền `slippage`, chỉ convert tại compatibility adapter và phát cảnh báo deprecation. Nếu cả hai cùng được truyền, phải raise error.

---

### 1.2 Funding phải dựa trên event thực tế

Không broadcast một scalar funding rate lên mọi bar.

Intrabar backend chỉ nhận:

```python
funding_event_timestamps
funding_event_rates
```

hoặc một series đã có:

```text
rate != 0 chỉ tại funding event
```

Funding được áp khi event timestamp khớp chính xác một market bar timestamp:

```text
funding_event_timestamp == market_bar_timestamp
```

Nếu OHLC timestamp là bar close, dùng `bar_timestamp_semantics="close"` để
funding áp sau intrabar path trên position còn lại tại close. Nếu OHLC timestamp
là bar open, dùng `bar_timestamp_semantics="open"` để funding áp trước pending
orders tại `open[t]`.

Thiếu funding của symbol phải raise trong strict mode. Chỉ dùng zero khi:

```python
use_funding=False
```

hoặc người dùng khai báo rõ:

```python
missing_funding_policy="zero"
```

---

### 1.3 Dynamic trailing phải dùng giá trị tại `t`

Tại `close[t]`, trailing mới phải được tính từ:

```python
trailing_value[t]
```

không phải:

```python
trailing_value[t - 1]
```

Trailing stop vừa cập nhật chỉ có hiệu lực từ bar `t+1`. Không được dùng stop mới để kiểm tra lại `high[t]` hoặc `low[t]`.

---

### 1.4 Thêm sizing compiler và quantity constraints

Alpha không nên trả direct quantity trừ khi khai báo rõ:

```python
sizing_mode="units"
```

Phải hỗ trợ tối thiểu:

```text
UNITS
FIXED_NOTIONAL
PCT_EQUITY
RISK_PER_TRADE
```

Ví dụ fixed notional:

$$
q =
\frac{
Notional \times SizeWeight
}{
FillPrice \times ContractSize
}
$$

Ví dụ risk per trade:

$$
q =
\frac{
Equity \times RiskFraction \times SizeWeight
}{
StopDistance \times ContractSize
}
$$

Sau khi tính raw quantity, engine phải áp:

```text
qty_step
min_qty
min_notional
max_qty
available_margin
```

Việc quantize quantity phải dùng cùng một hàm cho reference oracle, Numba kernel và event backend.

---

### 1.5 Tách `exit_long` và `exit_short`

Không dùng một boolean chung:

```python
technical_exit
```

Thay bằng:

```python
exit_long
exit_short
```

Quy tắc:

```text
exit_long  chỉ tác động khi đang long
exit_short chỉ tác động khi đang short
```

Phải định nghĩa conflict policy khi cùng bar có exit và entry:

```text
EXIT_ONLY
EXIT_THEN_REENTER
REVERSAL
REJECT_CONFLICT
```

Default khuyến nghị:

```text
opposite entry  -> reversal
same-side entry -> bỏ qua
exit + same-side entry -> exit only
```

Mọi reversal phải được account thành hai fill legs riêng biệt.

---

### 1.6 Strict timezone

Không được tự hiểu naive datetime là UTC.

Strict mode:

```python
if index.tz is None and source_timezone is None:
    raise MarketDataError(...)
```

Nếu có:

```python
source_timezone="Asia/Ho_Chi_Minh"
```

thì localize trước, sau đó mới convert UTC.

Data signature phải được tạo sau khi timezone đã chuẩn hóa.

---

### 1.7 Enforce hoặc reject mọi execution contract field

Mọi field public trong `ExecutionContract` phải thuộc một trong hai trạng thái:

```text
được backend thực thi đầy đủ
hoặc bị reject bằng NotImplementedError
```

Không được âm thầm bỏ qua các field như:

```text
stop_gap_policy
take_profit_gap_policy
same_bar_policy
trailing_update_phase
funding_phase
liquidation_priority
ambiguity_policy
fill_price_policy
```

Mỗi backend nên khai báo capability:

```python
BackendCapabilities(
    supported_fill_phases=...,
    supports_intrabar_stop=True,
    supports_trailing=True,
    supports_partial_fill=False,
    supports_cross_margin=False,
)
```

Endpoint validate contract trước khi chạy kernel.

---

### 1.8 Sửa certification của fill replay

`fill_replay` chỉ được chứng nhận cho những domain mà implementation thực sự xử lý.

Metadata nên tách riêng:

```json
{
  "price_accounting_certified": true,
  "fee_accounting_certified": true,
  "funding_certified": false,
  "margin_certified": false,
  "liquidation_certified": false,
  "execution_generation_certified": false,
  "causality_certified": false
}
```

Chỉ nâng certification sau khi bổ sung implementation và parity tests tương ứng.

---

### 1.9 Thêm `PreparedIntrabarRunner`

Data preparation, validation và profile compilation chỉ chạy một lần:

```python
runner = QuantBT.intrabar(
    profile=profile,
).prepare(
    data=df,
    symbol="ETHUSDT",
    funding=funding_events,
)
```

Mỗi trial chỉ cần:

```python
intent = alpha.generate(runner.market, params)

result = runner.run(
    intent,
    report_level="minimal",
)
```

Best candidate mới chạy:

```python
audit = runner.run(
    intent,
    report_level="audit",
)
```

Prepared runner phải cache:

```text
OHLCV contiguous arrays
timestamps
funding event arrays
instrument constraints
compiled execution codes
validation certificate
data signature
reusable buffers
```

Không được build lại DataFrame, funding mask hoặc instrument arrays trong mỗi Optuna trial.

---

## 2. Kiến trúc dùng chung cho mọi alpha

Không nên biến `IntrabarAlphaOutput` thành output duy nhất cho mọi chiến lược.

Intrabar, target-position, grid, DCA, arbitrage và portfolio có execution semantics khác nhau. Ép tất cả vào một schema sẽ lặp lại lỗi thiết kế cũ của `pos_weight`.

Nên dùng một façade chung nhưng nhiều output contract chuyên biệt.

```text
QuantBT
  ├── SharedProfile
  ├── PreparedRunner
  ├── AlphaOutput protocol
  └── Backend/kernel registry
```

### 2.1 Profile dùng chung dạng composition

```python
@dataclass(frozen=True)
class QuantBTProfile:
    market: MarketProfile
    account: AccountProfile
    execution: ExecutionProfile
    sizing: SizingProfile
    portfolio: PortfolioProfile | None = None
    reporting: ReportingProfile = ReportingProfile()
```

Profile được khai báo một lần cho từng môi trường/thị trường:

```python
VN30F_PROFILE
BINANCE_PERP_PROFILE
VN_STOCK_PROFILE
DERIBIT_OPTION_PROFILE
```

Mọi alpha dùng cùng thị trường chỉ tham chiếu profile đó, không khai báo lại fee, leverage, slippage, contract size hoặc quantity constraints.

### 2.2 Output contract theo họ chiến lược

```python
class AlphaOutput(Protocol):
    execution_family: str
```

Các output cụ thể:

```text
TargetPositionOutput
NextOpenSignalOutput
IntrabarAlphaOutput
PortfolioTargetOutput
OrderIntentOutput
GridPlanOutput
DCAPlanOutput
ArbitrageOutput
OptionStrategyOutput
```

#### `IntrabarAlphaOutput`

Dùng cho single-position hoặc simple multi-symbol SL/TP/trailing:

```python
@dataclass(frozen=True)
class IntrabarAlphaOutput:
    entry_side: np.ndarray
    size_weight: np.ndarray

    stop_value: np.ndarray | None
    take_profit_value: np.ndarray | None
    trailing_value: np.ndarray | None

    exit_long: np.ndarray | None
    exit_short: np.ndarray | None

    level_mode: LevelMode
    signal_mode: SignalMode = SignalMode.PULSE
```

#### `PortfolioTargetOutput`

Dùng cho cross-sectional allocation:

```python
@dataclass(frozen=True)
class PortfolioTargetOutput:
    target_weights: np.ndarray
    rebalance_mask: np.ndarray
```

#### `OrderIntentOutput`

Dùng cho generic order lifecycle:

```python
@dataclass(frozen=True)
class OrderIntentOutput:
    commands: CompactOrderCommandTape
```

#### Grid và DCA

Không nên ép grid/DCA thành một `entry_side`.

Chúng cần output riêng:

```python
@dataclass(frozen=True)
class GridPlanOutput:
    level_prices: np.ndarray
    level_sizes: np.ndarray
    side: np.ndarray
    cancel_replace_mask: np.ndarray
```

```python
@dataclass(frozen=True)
class DCAPlanOutput:
    trigger_prices: np.ndarray
    order_sizes: np.ndarray
    take_profit_rules: np.ndarray
    stop_rules: np.ndarray
```

#### Arbitrage

Arbitrage phải biểu diễn một basket atomic hoặc coordinated legs:

```python
@dataclass(frozen=True)
class ArbitrageOutput:
    basket_entry: np.ndarray
    basket_exit: np.ndarray
    leg_weights: np.ndarray
    hedge_ratios: np.ndarray
    execution_policy: BasketExecutionPolicy
```

Không được chạy từng leg độc lập rồi gọi đó là arbitrage backtest chuẩn.

---

## 3. Không nên tạo endpoint ngầm bằng global state khi import

Không nên làm:

```python
import quantbt
```

rồi package âm thầm giữ một global profile hoặc global endpoint.

Global mutable state sẽ gây vấn đề:

```text
khó tái lập kết quả
không thread-safe
khó chạy nhiều thị trường trong một process
Optuna trials có thể dùng nhầm profile
tests ảnh hưởng lẫn nhau
khó biết result dùng config nào
```

Nên dùng explicit façade nhưng khai báo rất ngắn:

```python
qbt = QuantBT(profile=BINANCE_PERP_PROFILE)
runner = qbt.prepare(data=df, symbol="ETHUSDT")
```

Sau đó dùng lại `runner` cho mọi alpha:

```python
result_a = runner.run(alpha_a.generate(runner.market, params_a))
result_b = runner.run(alpha_b.generate(runner.market, params_b))
result_c = runner.run(alpha_c.generate(runner.market, params_c))
```

Có thể thêm profile registry:

```python
qbt = QuantBT.from_profile("binance_perp_default")
```

hoặc YAML:

```yaml
profile: binance_perp_default
```

Nhưng profile cuối cùng phải được đóng băng vào result metadata để bảo đảm reproducibility.

---

## 4. Routing tự động nhưng không được mơ hồ

Runner có thể tự route theo kiểu output:

```python
result = runner.run(alpha_output)
```

Ví dụ:

```text
IntrabarAlphaOutput   -> intrabar_bracket_v1
TargetPositionOutput  -> close_target_v2
PortfolioTargetOutput -> native_portfolio_v3
GridPlanOutput        -> grid kernel/event backend
DCAPlanOutput         -> DCA kernel
ArbitrageOutput       -> basket/arbitrage backend
OrderIntentOutput     -> event_lifecycle_v2
```

Nếu profile và output không tương thích:

```python
raise ExecutionContractError(...)
```

Không được fallback âm thầm sang backend khác.

---

## 5. API sử dụng cuối cùng

Khai báo profile một lần:

```python
profile = QuantBTProfile(
    market=BinancePerpetualMarketProfile(
        symbol="ETHUSDT",
        contract_size=1.0,
        qty_step=0.001,
        min_qty=0.001,
        min_notional=5.0,
    ),
    account=AccountProfile(
        initial_capital=100_000.0,
        leverage=3.0,
        maintenance_ratio=0.005,
    ),
    execution=IntrabarExecutionProfile(
        signal_phase="close",
        fill_phase="next_open",
        fee_rate=0.0004,
        slippage_bps=2.0,
        same_bar_policy="conservative",
        close_on_last_bar=True,
    ),
    sizing=FixedNotionalSizing(
        notional_per_trade=10_000.0,
    ),
)
```

Prepare một lần:

```python
runner = QuantBT(profile).prepare(
    data=df,
    funding=funding_events,
)
```

Mỗi alpha chỉ còn:

```python
intent = alpha.generate(
    market=runner.market,
    params=params,
)

result = runner.run(
    intent,
    report_level="minimal",
)
```

Audit:

```python
audit = runner.run(
    intent,
    report_level="audit",
)
```

Đây nên là API chính. Các low-level endpoint vẫn được giữ cho advanced use cases và backward compatibility.

---

## 6. Regression tests phải bổ sung

```text
test_intrabar_uses_slippage_bps_as_source_of_truth
test_legacy_slippage_conflict_raises
test_scalar_funding_rejected
test_funding_applied_only_at_event
test_funding_crosses_missing_exact_hour
test_dynamic_trailing_uses_value_at_t
test_new_trailing_not_applied_to_same_bar
test_fixed_notional_sizing
test_pct_equity_sizing
test_risk_per_trade_sizing
test_qty_step_rounding
test_min_qty_rejection
test_min_notional_rejection
test_exit_long_only_affects_long
test_exit_short_only_affects_short
test_exit_entry_conflict_policy
test_reversal_has_two_fill_legs
test_naive_timezone_rejected
test_source_timezone_localized_then_converted
test_unsupported_contract_field_raises
test_fill_replay_certification_is_granular
test_prepared_intrabar_matches_normal_endpoint
test_minimal_and_audit_equity_parity
test_profile_metadata_is_frozen_in_result
test_output_type_routes_to_expected_backend
test_incompatible_profile_output_raises
```

---

## 7. Cách chạy test

### Chạy toàn bộ test suite

```bash
pytest -q
```

### Dừng ngay tại lỗi đầu tiên

```bash
pytest -q -x
```

### Chạy các test Phase 31 hiện tại

```bash
pytest -q tests/test_phase31*.py
```

### Chạy riêng intrabar kernel và oracle

```bash
pytest -q \
  tests/test_phase31_intrabar_reference.py \
  tests/test_phase31c_intrabar_kernel.py
```

Nếu tên file thực tế khác, kiểm tra bằng:

```bash
find tests -maxdepth 1 -type f | sort | grep -E "phase31|intrabar|fill_replay"
```

### Chạy các regression tests mới

Khuyến nghị đặt trong:

```text
tests/test_phase31_merge_blockers.py
tests/test_phase31_profiles_and_runner.py
```

Sau đó chạy:

```bash
pytest -q \
  tests/test_phase31_merge_blockers.py \
  tests/test_phase31_profiles_and_runner.py
```

### Chạy test với output đầy đủ

```bash
pytest -vv -s tests/test_phase31_merge_blockers.py
```

### Chạy một test cụ thể

```bash
pytest -q \
  tests/test_phase31_merge_blockers.py::test_dynamic_trailing_uses_value_at_t
```

### Chạy tests liên quan funding

```bash
pytest -q -k "funding"
```

### Chạy tests liên quan sizing

```bash
pytest -q -k "sizing or quantity or min_notional or qty_step"
```

### Chạy tests liên quan intrabar

```bash
pytest -q -k "intrabar or trailing or same_bar or reversal"
```

### Chạy coverage

```bash
pytest \
  --cov=quantbt \
  --cov-report=term-missing \
  --cov-report=html
```

Nếu package import trực tiếp từ repository root:

```bash
PYTHONPATH=. pytest -q
```

### Chạy benchmark sau khi tests pass

```bash
python benchmarks/run_phase17_intrabar.py
```

Hoặc benchmark hiện có trên nhánh:

```bash
find benchmarks -maxdepth 1 -type f | sort | grep -E "phase17|phase31|intrabar"
```

Rồi chạy file tìm được:

```bash
python benchmarks/<intrabar_benchmark_file>.py
```

Benchmark phải chạy hai lần:

```text
cold JIT compile
warm execution
```

Chỉ dùng warm execution cho performance gate.

---

## 8. Merge gate

Chỉ merge vào `dev` khi:

* [ ] Tất cả lỗi P0 phía trên đã sửa.
* [ ] Mọi execution contract field được enforce hoặc reject.
* [ ] Python oracle và Numba kernel parity.
* [ ] Minimal và audit mode cho cùng equity/accounting.
* [ ] Prepared và non-prepared endpoint parity.
* [ ] Sizing và quantity constraints có regression tests.
* [ ] Funding chỉ áp tại event.
* [ ] Dynamic trailing dùng `t`.
* [ ] Strict timezone hoạt động.
* [ ] Fill replay certification không overclaim.
* [ ] Full test suite pass.
* [ ] Benchmark không vượt performance threshold đã đặt.
* [ ] Result metadata lưu profile, execution contract, kernel version và data signature.

Kiến trúc nên chốt theo nguyên tắc:

> **Một façade và một profile dùng lại cho nhiều alpha, nhưng mỗi họ chiến lược phải có output contract và backend phù hợp riêng. Không dùng một schema duy nhất để ép target-position, intrabar, portfolio, grid, DCA và arbitrage vào cùng semantics.**

---

# Phase 32 - Domain-Agnostic Optimization Framework

Status: planned, pending approval.

Primary design guide:

- [`upgrade/quantbt_domain_agnostic_optimization_upgrade.md`](./quantbt_domain_agnostic_optimization_upgrade.md)

This section is only the implementation tracking layer. The detailed domain
rules, module layout, evaluator contracts, sampler compatibility, constraints,
tests, and merge gates must follow the primary design guide above.

## Why This Phase Exists

Current QuantBT optimization is strongest inside `walkforward.py`, but the
Optuna plumbing is too tightly coupled to walk-forward semantics:

- search-space parsing lives inside WFO;
- sampler creation is mostly WFO-specific;
- duplicate pruning and callbacks are WFO-specific;
- robust candidate selection is useful beyond WFO but not exposed as a generic
  optimizer layer;
- prepared market contexts already exist for native vectorized, native
  portfolio, and intrabar, but there is no domain-agnostic evaluator contract
  that lets Optuna reuse those contexts across trials.

The upgrade should create a reusable optimization core while preserving the
important domain separation already built into QuantBT:

```text
optimizer core knows params/objectives/constraints only
domain evaluator knows signal/intrabar/portfolio/arbitrage/grid/options output
backtest backend keeps its own execution and accounting semantics
```

Do not build an `IntrabarOptimizer`. Build:

```text
optimization/
  config.py
  result.py
  space.py
  callbacks.py
  samplers.py
  constraints.py
  evaluator.py
  evaluators/
  candidate_selection.py
  optimizer.py
```

Public API should eventually expose:

```python
OptimizationConfig
SamplerConfig
ObjectiveResult
OptimizationResult
TrialEvaluator
OptunaOptimizer
GenericEndpointEvaluator
PreparedSignalEvaluator
PreparedIntrabarEvaluator
PreparedPortfolioEvaluator
```

## Branch Plan

Create a new branch from current `dev` after this plan is approved:

```bash
git switch dev
git pull --ff-only origin dev
git switch -c feat/domain-agnostic-optimization
```

All implementation commits for this phase should stay on that feature branch
until tests and benchmarks pass. Do not merge into `dev` until the merge gates
below are satisfied.

## Condensed Phase Plan

The source guide lists Phase A through Phase G. To keep the work practical, we
will implement it as three larger phases without dropping any required checks.

### Phase 32A - Optimization Core Extraction And Compatibility Lock

Status: implemented on `feat/domain-agnostic-optimization`.

Goal: create the generic optimization package and move shared Optuna utilities
out of WFO without changing current WFO behavior.

Implementation scope:

- Created `optimization/` package with:
  - `OptimizationConfig`;
  - `SamplerConfig`;
  - `ObjectiveResult`;
  - `OptimizationResult`;
  - `TrialEvaluator` protocol;
  - search-space helpers compatible with existing `param_ranges`;
  - fixed-param override semantics;
  - process-local duplicate detection;
  - JSONL logger;
  - single-objective early stopping callback;
  - constraint user-attr helper.
- Implemented sampler factory for Phase 1 samplers:
  - `tpe`;
  - `random`;
  - `grid`;
  - `cmaes`;
  - `nsgaii`.
- Validated sampler compatibility:
  - CMA-ES rejects categorical/mixed spaces;
  - Grid rejects dynamic/infinite spaces and warns/rejects huge Cartesian grids;
  - multi-objective does not use single-objective `study.best_value`;
  - constraints are passed through Optuna user attrs when supported.
- Kept `walkforward.py` behavior unchanged:
  - add compatibility imports first;
  - do not remove existing WFO utilities until parity tests are written;
  - no scoring/objective behavior drift.

Implemented files:

```text
optimization/__init__.py
optimization/config.py
optimization/result.py
optimization/space.py
optimization/callbacks.py
optimization/samplers.py
optimization/constraints.py
optimization/evaluator.py
optimization/optimizer.py
optimization/evaluators/__init__.py
tests/test_optimization_core.py
tests/test_optimization_samplers.py
```

Important correctness note:

- Bool choice detection requires actual `bool` values. Numeric specs such as
  `(0.0, 1.0)` must not be misclassified as `[False, True]`, because Python
  equality makes `0.0 == False` and `1.0 == True`.
- Unsupported formal-constraint samplers reject `constraints_func` in the
  factory, while `OptunaOptimizer` only passes the constraint callback to
  samplers that support it in Phase 32A (`tpe`, `nsgaii`).
- `cmaes` factory compatibility exists, but the environment currently does not
  include the optional external `cmaes` package; Phase 32A tests therefore
  validate construction/rejection semantics rather than running a CMA-ES study.

Tests:

- `test_single_objective_result`;
- `test_multi_objective_result`;
- `test_constraint_storage`;
- `test_fixed_params_override`;
- `test_search_space_specs`;
- `test_duplicate_pruning`;
- `test_nonfinite_objective_pruned`;
- `test_exception_policy_raise`;
- `test_tpe_factory`;
- `test_random_factory`;
- `test_grid_factory`;
- `test_cmaes_rejects_categorical`;
- `test_nsgaii_multiobjective`;
- `test_constraints_func_propagation`;
- `test_sampler_seed_reproducibility`;
- `test_single_objective_early_stopping`;
- `test_pruned_trials_do_not_consume_patience`;
- `test_multiobjective_rejects_single_best_callback`;
- `test_jsonl_logger`.

Validation gate:

```bash
pytest -q tests/test_optimization_core.py tests/test_optimization_samplers.py
pytest -q tests/test_walkforward_phase1.py
```

Validation after implementation:

```text
tests/test_optimization_core.py tests/test_optimization_samplers.py: 17 passed
tests/test_walkforward_phase1.py: 51 passed
tests/test_endpoint.py: 22 passed
pytest -q: 489 passed, 1 skipped
```

### Phase 32B - Domain Evaluators, Constraints, And Prepared Context Parity

Goal: make the optimizer useful across QuantBT domains without forcing every
domain into one output schema.

Implementation scope:

- Add `GenericEndpointEvaluator` as mandatory fallback.
- Add prepared evaluators:
  - `PreparedSignalEvaluator` for single-symbol close-target/vectorized routes;
  - `PreparedIntrabarEvaluator` using `QuantBTEndpoint.prepare_intrabar(...)`;
  - `PreparedPortfolioEvaluator` using native portfolio prepared market arrays.
- Add initial adapter contracts for:
  - arbitrage generic fallback;
  - grid/DCA generic fallback;
  - options generic fallback.
- Keep domain-specific imports inside evaluator adapters only.
- Add objective builder helpers for common metrics:
  - Sharpe;
  - max drawdown;
  - trade count;
  - turnover;
  - margin utilization;
  - rejection rate.
- Add official constraint semantics:
  - feasible when value `<= 0`;
  - infeasible when value `> 0`;
  - do not convert constraints into arbitrary penalty scores when formal
    constraints are possible.
- Add candidate selector interface:
  - Optuna best trial is not automatically production params;
  - feasibility filter precedes robust selection;
  - single-objective returns best params;
  - multi-objective returns Pareto trials unless a selector policy is passed.

Tests:

- `test_prepared_signal_evaluator`;
- `test_prepared_intrabar_evaluator`;
- `test_prepared_portfolio_evaluator`;
- `test_generic_endpoint_evaluator`;
- `test_arbitrage_adapter`;
- `test_grid_dca_adapter`;
- `test_option_adapter_contract`;
- `normal endpoint == prepared evaluator`;
- `minimal == audit core accounting` where the backend supports audit;
- constrained optimization smoke;
- multi-objective Pareto smoke;
- custom objective override smoke;
- persistent SQLite resume smoke.

Validation gate:

```bash
pytest -q tests/test_optimization_evaluators.py
pytest -q tests/test_optimization_integration.py
pytest -q tests/test_phase31*.py
pytest -q tests/test_phase11_native_portfolio_backend.py
```

Status: completed in Phase 32B.

Implemented:

- Added public evaluator adapters:
  - `GenericEndpointEvaluator`;
  - `PreparedSignalEvaluator`;
  - `PreparedIntrabarEvaluator`;
  - `PreparedPortfolioEvaluator`;
  - `ArbitrageGenericEvaluator`;
  - `GridDCAGenericEvaluator`;
  - `OptionPackageGenericEvaluator`.
- Added initial domain output contracts:
  - `ArbitrageTrialOutput`;
  - `GridDCATrialOutput`;
  - `OptionTrialOutput`.
- Added common objective helpers:
  - `ReportMetricObjective`;
  - `SharpeObjective`;
  - `metric_from_result(...)`;
  - `metrics_from_result(...)`;
  - formal constraint helpers for minimum trades, max drawdown, turnover,
    margin utilization, and rejection rate.
- Added candidate selector layer:
  - `CandidateSelector`;
  - `SelectedCandidate`;
  - `constraints_feasible(...)`.
- Added `IntrabarIntentTape.from_frame(...)` as an adapter helper for compact
  alpha DataFrames. This does not change the intrabar execution kernel.
- Fixed optimizer result bookkeeping so `fixed_params` are preserved in
  `best_params`, `selected_params`, and trial records via `quantbt_full_params`.

Tests added:

- `tests/test_optimization_evaluators.py`;
- `tests/test_optimization_integration.py`.

Validation:

```bash
PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_optimization_evaluators.py tests/test_optimization_integration.py
# 12 passed

PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_phase31*.py tests/test_phase11_native_portfolio_backend.py tests/test_optimization_core.py tests/test_optimization_samplers.py
# 82 passed

PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q
# 501 passed, 1 skipped
```

Scope note:

- Arbitrage, grid/DCA, and options are intentionally available through generic
  endpoint fallback contracts in Phase 32B. Specialized prepared evaluators for
  these domains are future extensions and should not be claimed as done.
- Candidate selection is conservative: single-objective can select best or
  feasible-best; multi-objective keeps Pareto unless an explicit selector is
  supplied.

### Phase 32C - Walk-Forward Consolidation, Docs, And Performance Benchmark

Goal: reuse the generic optimizer in WFO without breaking anti-leakage logic or
the five existing WFO optimization modes.

Implementation scope:

- Replace duplicated WFO utilities with imports from `optimization/`:
  - search-space suggestion;
  - fixed-param merging;
  - sampler factory;
  - duplicate handling;
  - JSONL logging where applicable;
  - early stopping where applicable.
- Keep WFO-only logic in `walkforward.py`:
  - fold generation;
  - anti-leakage train/test isolation;
  - mode 1/2/3/4/5 scoring semantics;
  - temporal/plateau/full-sample robust selection metadata;
  - OOS stitching.
- Add backward compatibility tests:
  - old WFO sampling equals new search-space sampling;
  - existing robust candidate selection metadata preserved;
  - train-test split remains OOS-isolated;
  - `mode_4_is_only_robust` still does not use OOS for selection;
  - `mode_5_full_robust` remains explicitly full-sample, not WFO anti-leakage.
- Add docs:
  - `docs/optimization.md`;
  - update `docs/endpoint.md`;
  - README pointer to optimization docs;
  - example snippets for signal, intrabar, portfolio, and generic endpoint.
- Add benchmark:
  - optimizer overhead separate from backtest runtime;
  - prepared evaluator vs normal endpoint in repeated trials;
  - cold vs warm Numba where applicable;
  - JSON artifact under `benchmarks/results/`.

Validation gate:

```bash
pytest -q tests/test_walkforward_phase1.py
pytest -q tests/test_optimization*.py
pytest -q tests/test_endpoint.py
pytest -q tests/test_phase31*.py
pytest -q
python benchmarks/run_optimization_overhead.py
```

Status: completed in Phase 32C.

Implemented:

- Consolidated safe WFO utilities onto the domain-agnostic optimization layer:
  - `_sample_params(...)` now delegates to `optimization.suggest_params(...)`;
  - WFO duplicate keys use `optimization.stable_params_key(...)`;
  - public `EarlyStoppingCallback` now reuses
    `optimization.SingleObjectiveEarlyStopping`.
- Kept WFO-only anti-leakage logic in `walkforward.py`:
  - fold generation;
  - IS/OOS isolation;
  - mode 1/2/3/4/5 objective semantics;
  - robust candidate selection metadata;
  - OOS stitching.
- Added documentation:
  - `docs/optimization.md`;
  - updated `docs/endpoint.md`;
  - updated `docs/README.md`;
  - updated `examples/README.md`;
  - updated README performance/feature pointers.
- Added runnable example:
  - `examples/optimization_workflow.py`.
- Added benchmark:
  - `benchmarks/run_optimization_overhead.py`;
  - `benchmarks/results/optimization_overhead.json`;
  - `benchmarks/results/optimization_overhead.md`.

Benchmark result on the committed smoke workload:

```text
status: pass
optimizer overhead: 0.017357s for 24 trials
optimizer overhead per trial: 0.000723s
normal signal replays: 0.165146s
prepared signal replays: 0.081492s
prepared signal speedup: 2.027x
intrabar first run: 0.017772s
intrabar warm run: 0.004809s
intrabar first/warm ratio: 3.695x
signal final equity diff: 0.0
intrabar final equity diff: 0.0
```

Validation:

```bash
PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_optimization_integration.py tests/test_optimization_evaluators.py tests/test_optimization_core.py tests/test_optimization_samplers.py
# 30 passed

PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_walkforward_phase1.py
# 51 passed

PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_endpoint.py tests/test_phase31*.py
# 66 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python benchmarks/run_optimization_overhead.py --rows 360 --trials 24 --loops 24
# status: pass

PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q
# 502 passed, 1 skipped
```

Scope note:

- Phase 32C intentionally did not rewrite WFO around `OptunaOptimizer`; WFO has
  anti-leakage/fold semantics that remain domain-specific and are locked by
  regression tests.
- Specialized prepared evaluators for arbitrage, grid/DCA, and options remain
  future work. They can be added without changing optimizer core.

### Phase 32 Final Merge Blockers - Sol Feedback

Status: completed after Phase 32C.

Assessment:

- Feedback was correct. The optimizer should fail fast when an objective or
  formal-constraint metric is missing, should not use raw infeasible Optuna
  best params as selected production params, and should not claim parallel
  optimization safety while evaluator adapters keep mutable `last_result` /
  `last_intent` state.

Implemented:

- Added `MissingOptimizationMetricError`.
- Objective/constraint metrics are strict:
  - missing Sharpe / MaxDD / turnover / margin / rejection rate now raises when
    used by objective values or formal constraints;
  - `turnover` no longer falls back to `num_trades`.
- Candidate selection is constraint-safe:
  - unconstrained single-objective studies still auto-populate
    `selected_params`;
  - constrained studies without an explicit selector now keep
    `selected_params=None`;
  - `CandidateSelector("feasible_best")` selects the best feasible trial;
  - `CandidateSelector("pareto_first")` filters infeasible Pareto trials.
- Added `SamplerConfig.constraint_mode`:
  - default: `"sampler"`;
  - unsupported constrained samplers such as random/grid/CMA-ES require
    `constraint_mode="post_filter"`;
  - otherwise they raise instead of silently ignoring constraints.
- Reproducibility safety:
  - `n_jobs != 1` raises `NotImplementedError`;
  - `_seen_params` is reset at the start of every study;
  - persistent studies preload previous `quantbt_params_key` /
    `quantbt_full_params` so resume duplicate detection works;
  - JSONL logs now write full params including fixed params.

Tests added:

- `test_missing_objective_metric_raises`;
- `test_missing_constraint_metric_raises`;
- `test_turnover_does_not_fallback_to_trade_count`;
- `test_infeasible_highest_score_not_selected`;
- `test_pareto_selector_filters_infeasible_trials`;
- `test_unsupported_constraint_sampler_requires_post_filter`;
- `test_no_feasible_trial_returns_no_selected_params`;
- `test_parallel_mode_rejected_until_thread_safe`;
- `test_duplicate_detection_after_sqlite_resume`;
- `test_repeated_optimize_does_not_reuse_stale_seen_set`;
- `test_jsonl_contains_fixed_and_search_params`.

Validation:

```bash
PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_optimization_core.py tests/test_optimization_samplers.py tests/test_optimization_evaluators.py tests/test_optimization_integration.py
# 41 passed

PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_walkforward_phase1.py tests/test_endpoint.py tests/test_phase31*.py
# 117 passed

PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q
# 513 passed, 1 skipped
```

### Phase 33 - Optimization Search Quality And Robust Selection

Guide:

- Detailed source plan:
  `upgrade/quantbt_optimization_search_quality_upgrade.md`.
- Scope is intentionally split into 2 phases:
  - Phase 33A: Search Assurance Core.
  - Phase 33B: Multi-seed search and robust plateau candidate selection.

Reason:

- A single TPE trajectory over mixed/conditional alpha spaces can miss known
  good regions such as historical Delta-RSI champions.
- Search quality should guarantee that known baselines are evaluated by the
  current evaluator and cannot be silently replaced by a worse sampled trial.
- This does not claim global optimality; it raises the optimizer from
  best-trial hunting to baseline-aware, diagnostic, reproducible research.

### Phase 33A - Search Assurance Core

Status: implemented on `feat/domain-agnostic-optimization`.

Implemented:

- Added `initial_trials` to `OptunaOptimizer.optimize(...)`.
  - Historical champions are enqueued with `study.enqueue_trial(...)`.
  - Warm-start trials are tagged as `quantbt_source="warm_start"`.
  - Fixed params are merged before enqueue validation.
  - Missing active search params in a warm-start raise instead of silently
    sampling a partial baseline.
- Added baseline floor for single-objective studies.
  - `result.baseline_trials` records completed warm-start trials.
  - If the selected candidate is worse than the best feasible warm-start,
    QuantBT resets `selected_params` to that warm-start and sets
    `search_regression=True`.
- Added `effective_params_builder`.
  - Duplicate detection can use semantic/effective params rather than raw
    noisy params.
  - This is designed for alpha spaces where toggles make params inactive.
- Added `early_stopping_min_trials`.
  - Early stopping cannot stop before the configured completed-trial floor.
- Added `OptimizationConfig(seed=None)`.
  - This restores true Optuna unseeded behavior for legacy-style exploratory
    searches while keeping integer seeds for audit runs.
- Added search diagnostics:
  - nominal variable dimension;
  - estimated grid size;
  - param kind counts;
  - source counts;
  - effective duplicate count;
  - per-param coverage;
  - top-decile parameter distributions;
  - baseline rank.
- Added docs in `docs/optimization.md`.

Validation:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests/test_optimization_core.py quantbt/tests/test_optimization_samplers.py
# 23 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests/test_optimization_core.py quantbt/tests/test_optimization_samplers.py quantbt/tests/test_optimization_evaluators.py quantbt/tests/test_optimization_integration.py
# 47 passed
```

Phase 33A merge gates:

- Warm-start trials are evaluated before sampled trials.
- Best feasible warm-start baseline cannot be silently lost.
- Effective duplicate detection prunes semantic duplicates.
- Early stopping respects `early_stopping_min_trials`.
- `seed=None` runs Optuna's unseeded sampler path.
- Search diagnostics persist baseline/source/coverage metadata.

### Phase 33B - Multi-Seed Robust Plateau Candidate Selection

Status: implemented on `feat/domain-agnostic-optimization`.

Implemented:

- Added `RobustSelectionConfig`.
  - Controls top objective quantile, metric feasibility filters, parameter
    neighborhood radius, minimum neighbor count, seed consensus, instability
    penalty, worst-neighbor weight, drawdown penalty, and size bonus.
- Added `CandidateSelector(mode="robust_plateau", config=...)`.
  - Filters failed/pruned/infeasible trials.
  - Applies optional `min_trades` and `max_drawdown_pct` filters.
  - Takes a top objective quantile instead of only the best trial.
  - Scores local parameter neighborhoods by median objective, worst-neighbor
    objective, objective dispersion, drawdown penalty, plateau size, and seed
    consistency.
  - Selects the medoid record from the best plateau rather than an isolated
    spike.
  - Writes ranked `result.robust_candidates` metadata.
- Added `MultiSeedOptimization`.
  - Runs the same evaluator across several sampler seeds.
  - Aggregates trial records with `quantbt_seed` and original trial metadata.
  - Stores `result.seed_results` and seed-level diagnostics.
  - Applies a robust selector over the aggregate search surface.
  - Keeps the Phase 33A warm-start baseline floor, so a worse new candidate
    cannot silently replace a better feasible historical baseline.
- Exported the new API from both `quantbt.optimization` and top-level
  `quantbt`.
- Updated `docs/optimization.md` with robust selector and multi-seed examples.

Validation:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests/test_optimization_phase33b.py quantbt/tests/test_optimization_core.py quantbt/tests/test_optimization_samplers.py quantbt/tests/test_optimization_evaluators.py quantbt/tests/test_optimization_integration.py
# 52 passed
```

Phase 33B merge gates:

- Robust plateau selector does not choose an isolated spike in deterministic
  mock data.
- Feasibility constraints and metric filters are respected before selection.
- Multi-seed aggregation records seed metadata and selects from a consensus
  plateau.
- Historical warm-start baseline floor remains active after robust selection.
- Validation/stress gate is available through selector metadata and baseline
  floor, but real alpha WFO/stress bundle validation remains a strategy-level
  certification step, not a generic optimizer-core guarantee.

## Merge Gates

Do not merge unless all are true:

- Existing walk-forward tests pass.
- Existing endpoint tests pass.
- Single-objective and multi-objective studies pass.
- Constraint semantics pass.
- TPE, Random, Grid, CMA-ES, and NSGA-II factory tests pass.
- CMA-ES rejects incompatible mixed spaces.
- Prepared signal/intrabar/portfolio parity passes.
- Generic evaluator can run arbitrage/options/grid-DCA fallback without adding
  optimizer-core imports from those domains.
- No generic exception is silently converted to score `0`.
- Multi-objective code never calls `study.best_value`.
- JSONL logs are deterministic and parseable.
- SQLite resume test passes.
- Optimizer overhead benchmark is recorded.
- Documentation and examples are updated.

## Scope Certification Target

Target after Phase 32C:

> Domain-agnostic Optuna orchestration with prepared evaluators for signal,
> intrabar, and portfolio; generic fallback for arbitrage, grid/DCA, and
> options; single/multi-objective studies, formal constraints, robust candidate
> selection hooks, and WFO utility consolidation without anti-leakage regression.

Do not claim every strategy family has the same prepared performance path.
Arbitrage, grid/DCA, and options can begin through `GenericEndpointEvaluator`
and receive specialized prepared evaluators later without changing optimizer
core.

## Phase 34 - Native Event Memory And Performance Optimization

Guide:

- Detailed source plan:
  `upgrade/optimized_native_event_kernel_v2.md`.
- Note: the source guide names this work "Phase 33A -> 33C", but the master
  implementation plan already uses Phase 33 for optimization search quality.
  This master plan tracks the same native-event work as Phase 34A -> 34C to
  avoid phase-number ambiguity.

Goal:

- Reduce native-event RSS and peak RAM for WFO, optimization, dynamic grid,
  DCA, bracket, and command-heavy strategies.
- Reduce report construction and pandas materialization overhead.
- Preserve public endpoint usage, `BacktestResultV2`, strategy callback API,
  lifecycle semantics, accounting formulas, fill policy, fee/funding/margin,
  liquidation, parent-child/OCO behavior, and same-bar command sequencing.
- Keep exactly one accounting source of truth. Score/minimal/standard/audit
  must be different artifact policies over the same accounting arrays, not
  different engines or metric implementations.

### Phase 34A - Native Event Artifact And Memory Contract

Status: implemented on `feat/30-native-event-lifecycle`.

Scope:

- Wire `report_level` through native-event endpoints, configs, backend, kernel
  artifact planning, and result materialization.
- Add an internal `NativeEventArtifactPlan` that controls whether equity,
  positions, fees, funding, margin, fill ledger, command terminal state, event
  ledger, command tape, pandas objects, and Python objects are retained.
- Introduce compact struct-of-arrays ledgers for fills, command terminal state,
  and lifecycle events.
- Dictionary-encode repeated strings such as order IDs, tags, campaign IDs,
  level IDs, OCO IDs, and parent IDs once.
- Make heavy public artifacts lazy where possible while keeping public
  `BacktestResultV2` compatibility.
- Remove duplicate storage such as separate canonical `order_report` and
  `command_report`; keep one canonical ledger/report with backward-compatible
  aliases.
- Add `audit_sink="none" | "memory" | "parquet" | "jsonl"` for long audit
  runs.

Required tests:

- Same command tape across current full path, minimal, standard, and audit.
- Exact equality for equity, returns, positions, fees, funding, margin,
  liquidation bar/reason, fill count, rejected count, canceled count, expired
  count, and terminal command status.
- Backward-compatible accessors for existing endpoint/report users.
- Benchmark dynamic-grid workload for peak RSS and report construction.

Acceptance:

- `report_level` changes only artifact retention, never accounting.
- Minimal path reduces peak RSS materially without changing results.
- Audit can retain full trace through memory or chunked disk sink.
- Public `.simulate()` remains source-compatible.

Implemented:

- Added `NativeEventConfig.report_level`, `audit_sink`, and `audit_sink_path`.
- Added `NativeEventArtifactPlan` with explicit artifact-retention flags.
- Added compact struct-of-arrays ledgers:
  - `CompactFillLedger`;
  - `CompactCommandLedger`;
  - `CompactOrderEventLedger`.
- Wired report policy through:
  - `QuantBTEndpoint`;
  - `BacktestEngineV2`;
  - native-event lifecycle v2 backend;
  - reactive native-event strategy replay.
- `full` normalizes to `audit`; existing default behavior remains
  audit-compatible.
- `minimal` keeps accounting paths and compact ledgers but omits heavy Python
  fills/orders and command/event DataFrames.
- `standard` keeps command terminal report and Python fills but omits full
  lifecycle event DataFrame.
- `audit` keeps full command report, order events, active-order report, Python
  fills/orders, compact ledgers, and optional disk sink artifacts.
- Reactive minimal mode records `emitted_command_count` but does not retain the
  full `emitted_command_tape`.
- Added `audit_sink="jsonl"` and `audit_sink="parquet"` support with explicit
  `audit_sink_path`; no silent project-folder writes.
- Updated endpoint docs for native-event report levels and audit sinks.

Validation:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_phase34a_native_event_artifacts.py
# 3 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_phase30a_native_event_lifecycle_contract.py tests/test_phase30b_native_event_lifecycle_kernel.py tests/test_phase30c_native_event_endpoint_lifecycle.py tests/test_phase30d_native_event_reactive_runner.py tests/test_phase30e_native_event_incremental_runner.py
# 33 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_endpoint.py tests/test_phase14c_prepared_report_levels.py
# 26 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python benchmarks/run_phase34a_native_event_memory.py --rows 3000 --levels 10 --cycle 40
# artifact retention benchmark recorded in benchmarks/phase34a_native_event_memory.md
```

Benchmark interpretation:

- `minimal` produced zero command-report rows, zero event-report rows, zero
  materialized Python fills, and zero materialized Python orders for the test
  workload while preserving final equity and lifecycle counters.
- The small subprocess RSS numbers include Python import, pandas, and
  Numba/cache overhead, so they are not used as a strict memory delta claim.
  Larger Phase 34B/34C optimization-batch benchmarks are still required before
  claiming stable RSS reduction percentages.

### Phase 34B - Prepared Native Event Score Path

Status: implemented on `feat/30-native-event-lifecycle`.

Scope:

- Add prepared native-event strategy runner:
  `prepare_native_event_strategy(data=..., symbols=...)`.
- Reuse datetime signatures, OHLCV/funding arrays, symbol maps, instrument
  constraints, contract sizes, leverage, fees, quantity constraints, and data
  signatures across many optimization trials.
- Add `NativeAccountingArrays` as the canonical post-kernel accounting object.
- Add lightweight internal `NativeEventScoreResult` for optimization scoring.
- Refactor performance metrics into shared pure array functions so
  `BacktestResultV2.full_report()` and `NativeEventScoreResult.full_report()`
  call the same metric implementation.
- Add prepared evaluator such as `PreparedNativeEventStrategyEvaluator` that
  plugs into the existing Optuna optimizer/objective contracts.

Required tests:

- `prepared.score(strategy)` vs `prepared.run(strategy, report_level="audit")`
  on identical data/params/seed/config.
- Exact metric equality for Sharpe, max drawdown, profit factor, number of
  trades, turnover, margin utilization, rejection rate, final equity, and
  liquidation status.
- 50-trial and 500-trial prepared optimization memory tests proving market
  arrays are prepared once and completed trials do not retain full artifacts.

Acceptance:

- Score path has no separate accounting or metric implementation.
- Score/full metric diff is exactly `0.0` for supported metrics.
- Prepared score is materially faster and more memory-lean than public audit.
- Optimizers can use the prepared score path without changing public endpoint
  behavior.

Implemented:

- Added `NativeAccountingArrays` as the canonical ndarray accounting payload
  extracted from native-event public results.
- Added `NativeEventScoreResult`:
  - ndarray equity/returns/positions/fees/funding/margin views;
  - lifecycle counters;
  - scalar metrics;
  - no public fills/orders artifact bundle.
- Added shared array-first performance metric function:
  `metrics.performance.compute_performance_metrics(...)`.
- `BacktestResultV2.full_report()` and `NativeEventScoreResult.full_report()`
  now use the same metric implementation through `metrics.performance`.
- Added `QuantBTEndpoint.prepare_native_event_strategy(...)`.
- Added `PreparedNativeEventStrategyRunner`:
  - prepares market arrays once;
  - reuses OHLC/funding/open/volume arrays;
  - `.score(strategy)` returns `NativeEventScoreResult` and does not store
    `endpoint.result`;
  - `.run(strategy, report_level=...)` returns public `BacktestResultV2`.
- Added `PreparedNativeEventStrategyEvaluator` for the optimization framework.
- Exported the new score/result/evaluator APIs from top-level/core/optimization
  namespaces.
- Updated endpoint docs with prepared native-event scoring examples.

Validation:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/test_phase34b_native_event_prepared_score.py
# 3 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python benchmarks/run_phase34b_native_event_prepared_score.py --rows 600 --trials 12
# metric_parity: true
# public_audit_seconds: 1.763319
# prepared_score_seconds: 0.634422
# speedup: 2.779x
# prepared_endpoint_result_retained: false

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q
# 544 passed, 1 skipped
```

Scope note:

- Phase 34B still uses the existing reactive session plus static replay kernel
  as the accounting source of truth. It prunes artifacts and reuses prepared
  market arrays, but it is not yet the single-pass stateful kernel.
- Fully eliminating transient pandas public-result construction from score
  execution belongs to Phase 34C, where the stateful kernel can emit
  `NativeAccountingArrays` directly.

### Phase 34C - Single-Pass Stateful Native Event Kernel

Scope:

- Replace the current reactive two-pass architecture for fast/score modes:
  Python reactive callback session -> capture command tape -> static replay.
- Add a stateful native-event kernel API:
  initialize state, apply commands for bar, match active orders, apply funding,
  apply margin/liquidation, finalize bar.
- Add active-order indexing:
  active slots, active slots by symbol, free slot stack, order ID to slot,
  expiry buckets, parent-child adjacency, and OCO group membership.
- Keep old replay-certified path as oracle/debug mode via
  `reactive_kernel_mode="replay_certified" | "single_pass"`.
- Make audit replay optional certification, not a requirement for every run.

Required tests:

- Lifecycle parity fixtures: market entry/exit, GTC limit, cancel before fill,
  replace, amend, stop-market, stop-limit, GTD expiry, reduce-only clipping,
  parent first/full-fill activation, OCO sibling cancellation, same timestamp
  sequencing, close-and-reverse, insufficient margin, funding, intrabar and
  post-funding liquidation, dynamic grid amend, grid entry/exit/re-arm, regime
  switch cancel/flatten, and multi-symbol commands.
- Compare replay-certified audit, minimal, standard, audit, score, single-pass
  score, single-pass audit, and static replay.
- Optimizer parity for fixed seeds/trial params/objective values/constraint
  values/feasible classification/selected candidate.
- Benchmarks in fresh subprocesses for real dynamic grid, one-minute stress,
  multi-symbol workloads, and optimization batches.

Acceptance:

- Public API remains stable.
- Single-pass path reaches exact accounting and lifecycle parity with replay
  oracle.
- Fast/score paths no longer need to retain full command tape or replay result.
- Audit can still produce full trace and optional replay certification.
- 500-trial prepared run does not grow RAM with completed-trial history.

Implemented:

- Added `NativeEventConfig.reactive_kernel_mode` with
  `replay_certified` and `single_pass`.
- Kept public compatibility default at `replay_certified`.
- Added single-pass result materialization from `_NativeEventReactiveSession`
  state:
  - equity path;
  - returns;
  - position matrix;
  - fee/funding arrays;
  - turnover, rejection, cancellation diagnostics;
  - margin paths;
  - liquidation flags;
  - compact fill ledger with real bar indices.
- `single_pass` skips the final static replay for `report_level="minimal"` and
  score runs.
- `single_pass` still runs replay oracle for `standard`, `audit`, and
  `reactive_execution_mode="audit"`, then asserts exact accounting parity.
- Added metadata:
  - `reactive_kernel_mode`;
  - `static_replay_available`;
  - `reactive_static_replay_count`;
  - `single_pass_accounting_source`;
  - `single_pass_replay_certified`.
- Updated `PreparedNativeEventStrategyRunner.score(...)` to use
  `reactive_kernel_mode="single_pass"` automatically.
- Threaded `reactive_kernel_mode` through endpoint, prepared runner, and
  `BacktestEngineV2`.
- Preserved legacy `reactive_incremental_compile_replays == 0` semantics:
  this field counts replay/compile inside callback construction, not the final
  optional certification replay.

Validation:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests/test_phase34c_native_event_single_pass.py
# 3 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q \
  quantbt/tests/test_phase30d_native_event_reactive_runner.py \
  quantbt/tests/test_phase30e_native_event_incremental_runner.py \
  quantbt/tests/test_phase34a_native_event_artifacts.py \
  quantbt/tests/test_phase34b_native_event_prepared_score.py \
  quantbt/tests/test_phase34c_native_event_single_pass.py
# 19 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 \
  benchmarks/run_phase34c_native_event_single_pass.py --rows 600 --trials 12
# accounting_parity: true
# replay_certified_seconds: 1.431315
# single_pass_seconds: 0.750957
# speedup: 1.906x
# replay_certified_static_replays: 12
# single_pass_static_replays: 0
```

Scope note:

- Phase 34C completes the practical single-pass optimization contract for
  reactive strategy minimal/score loops.
- The implementation intentionally keeps the Python reactive session as the
  state source and uses the existing event-v2 replay kernel as the oracle for
  audit/certification.
- A deeper future rewrite could move active-order state into a true low-level
  Numba step kernel, but that is no longer required for current prepared
  WFO/Optuna memory and replay-reduction goals.

### Phase 34 Final Merge Gate

- Public endpoints stay source-compatible.
- Public standard/audit still return `BacktestResultV2`.
- Strategy callback contract stays unchanged.
- No second accounting engine or metric implementation is introduced.
- Minimal/score artifact policies cannot change equity, positions, fees,
  funding, margin, liquidation, lifecycle state, or metrics.
- Dynamic grid, DCA, bracket, structured orders, and multi-symbol lifecycle
  semantics remain unchanged.
- Benchmark report records wall time, CPU time, peak RSS, Python heap peak,
  NumPy allocated bytes, object count, ledger bytes, command count, fill count,
  report construction time, and stage timings.

Merge regression fix on `dev`:

- Cherry-picked Phase 34A, 34B, and 34C onto `dev` after detecting that the
  native-event public endpoint integration was missing from the research
  branch.
- Restored public exports and endpoint contracts:
  - `PreparedNativeEventStrategyRunner`;
  - `QuantBTEndpoint.prepare_native_event_strategy(...)`;
  - `EndpointConfig.reactive_kernel_mode`;
  - `EndpointConfig.audit_sink`;
  - `EndpointConfig.audit_sink_path`.
- Added `scope="auto"` compatibility to
  `NativeEventScoreResult.full_report(...)`, matching the public result
  contract expected by `ReportMetricObjective`.
- Added `quantbt_phase34_merge_gate.py` so future merges can verify public
  Phase 34 integration directly.
- Added regression tests covering:
  - public `quantbt` imports;
  - endpoint Phase 34 fields;
  - prepared native-event runner availability;
  - `prepared.score(...)`;
  - `PreparedNativeEventStrategyEvaluator`;
  - `ReportMetricObjective(score_result)`.

Validation on `dev`:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 quantbt_phase34_merge_gate.py
# PHASE 34 MERGE GATE: PASSED

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q \
  quantbt/tests/test_phase34a_native_event_artifacts.py \
  quantbt/tests/test_phase34b_native_event_prepared_score.py \
  quantbt/tests/test_phase34c_native_event_single_pass.py
# 11 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests
# 549 passed, 1 skipped
```

## Phase 41 - Portfolio Correctness And Performance V2

Source guide:

- `upgrade/quantbt_portfolio_correctness_performance_plan_v2.md`

Issue/commit scope:

- `bug: Portfolio engine with long short mode and risk parity mode bug #41`

### Phase 41A - Correctness Blockers

Scope:

- Keep the existing portfolio endpoint and backend names stable.
- Keep portfolio as vectorized close-to-close; no intrabar portfolio claim.
- Do not auto-shift alpha signals; strategy/research layer owns causal target
  timing.
- Fix portfolio accounting blockers:
  - reversal turnover must use canonical traded delta;
  - slippage must affect execution cost and equity;
  - buying-power gate must include post-fee/post-slippage equity even when
    gross exposure is unchanged;
  - fee, slippage, turnover, and reports must come from the same accepted
    `delta_qty`.

Implemented:

- Updated `_engine_portfolio` and `_engine_portfolio_equity_sizing`.
- Added canonical per-symbol `delta_qty = target_qty - current_qty`.
- Turnover now uses traded notional from `abs(delta_qty)`, so `+1 -> -1`
  records `2 units` of turnover.
- Added slippage accounting through `ExecutionConfig.slippage_bps`:
  - buy delta uses adverse buy execution price;
  - sell delta uses adverse sell execution price;
  - slippage cost is recorded separately and subtracted from equity.
- Buying-power gate now checks:
  - `post_trade_equity >= target_initial_margin`;
  - `post_trade_equity >= target_maintenance_margin`;
  - non-tradable/invalid target rejection.
- Legacy `MultiSymbolPortfolio` keeps `slippage_rate=0.0` to preserve old
  compatibility behavior.

### Phase 41B - Risk Parity, Tradability, Audit, And Regression

Scope:

- Remove risk-parity warm-up look-ahead.
- Add leading/stale missing-price tradability guard.
- Standardize market-neutral missing-side semantics.
- Expose slippage/turnover diagnostics without changing public endpoint
  signatures.

Implemented:

- Risk parity volatility no longer uses `bfill()`.
- Warm-up bars without enough rolling observations produce zero risk-parity
  target exposure.
- `market_neutral` with only one side now zeros target exposure instead of
  silently creating directional exposure.
- Native portfolio builds a `tradable_mask` from original close observations:
  - leading missing price is not tradable;
  - rebalance on non-tradable symbols is rejected atomically;
  - held positions can still mark to last valid price.
- Added metadata/report fields:
  - `slippage_series`;
  - `slippage_total`;
  - `slippage_bps`;
  - `canonical_one_way_fee_rate`;
  - slippage columns in `symbol_pnl_report`.
- Finalized the fee contract:
  - `fee_rate` is canonical one-way across native backends;
  - legacy `fee` remains round-trip and is converted at compatibility
    boundaries;
  - explicit `fee_rate` has priority over `fee`;
  - legacy `MultiSymbolPortfolio` is bridged with round-trip fee only when used
    through its optional `fee` alias; explicit `fee_rate` is now one-way there
    too.
- Added detailed portfolio audit outputs:
  - structured rebalance reasons: `NON_TRADABLE`, `STALE_PRICE`,
    `POST_COST_MARGIN`, `INVALID_TARGET`, `MIN_QTY`, `MIN_NOTIONAL`;
  - `portfolio_reconciliation_report` for fee, slippage, symbol PnL, turnover,
    and accepted-position reconciliation.
- Added regression tests for:
  - `0 -> +1`;
  - `+1 -> 0`;
  - `+1 -> -1`;
  - explicit one-way `fee_rate` vs legacy round-trip `fee`;
  - fixed-target and `%_equity` accounting invariants;
  - long/short reversal post-cost margin gate;
  - slippage on long entry/exit and short entry/cover;
  - market-neutral missing one side;
  - risk-parity warm-up;
  - leading missing/non-tradable price;
  - stale/asynchronous calendar rejection;
  - symbol-vs-portfolio reconciliation.

Validation:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q \
  quantbt/tests/test_phase11_portfolio_institutional_scenarios.py
# 18 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q \
  quantbt/tests/test_phase11_native_portfolio_backend.py \
  quantbt/tests/test_phase11_native_portfolio_full_surface.py \
  quantbt/tests/test_phase11_portfolio_engine_spec.py \
  quantbt/tests/test_phase13_portfolio_report_parity.py \
  quantbt/tests/test_phase14c_prepared_report_levels.py \
  quantbt/tests/test_phase16_prepared_service_context.py \
  quantbt/tests/test_walkforward_phase1.py::test_walkforward_portfolio_endpoint_scoring_reuses_prepared_market_arrays_without_metric_drift
# 47 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q \
  quantbt/tests/test_phase11_portfolio_institutional_scenarios.py \
  quantbt/tests/test_endpoint.py \
  quantbt/tests/test_phase2_native_vectorized.py \
  quantbt/tests/test_phase3_native_event.py \
  quantbt/tests/test_phase34c_native_event_single_pass.py
# 52 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q \
  quantbt/tests/test_phase12_benchmark_nautilus_cert.py \
  quantbt/tests/test_phase14_service_loop_benchmark.py
# 5 passed

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests
# 561 passed, 1 skipped

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 \
  quantbt/benchmarks/run_portfolio_real_parity.py
# pass: legacy-compatible parity 16/16, native-only contract true,
# max equity diff 5.82076609135e-11
```

Remaining debt:

- Full L2/intrabar portfolio simulation remains out of scope.
- Prepared portfolio cache can later store the tradable/stale mask directly to
  avoid recomputation in larger WFO/service loops.

## Phase 42-44 - QuantBT Engine Packaging, Native Event, And PyO3 Roadmap

Status:

- Planned only. No code/package-layout/native-event implementation has started
  for this roadmap yet.

Source guide:

- `upgrade/quantbt_engine_packaging_pypi_pyo3_final_plan_v2_expanded.md`

Hard rules from the guide:

- Do not change public imports:
  - `from quantbt import QuantBTEndpoint`
- Do not rename existing endpoints.
- Do not force old alphas to migrate.
- Do not change domain semantics for speed.
- Do not merge an optimization if parity fails.
- Keep Python/Numba as fallback and accounting oracle.
- Rust/PyO3 is optional acceleration only; users should not import
  `_quantbt_native` directly.
- Do not force-push `main`; avoid rewriting remote history on `dev`.
- Prefer follow-up commits over amend once a commit has reached a shared
  remote branch.

Distribution targets:

- PyPI distribution: `quantbt-engine`
- Python import: `quantbt`
- Optional native distribution: `quantbt-native`
- Optional native module: `_quantbt_native`
- Extra install target: `pip install "quantbt-engine[native]"`

### Phase 42A - Packaging Baseline And Implementation Link

Branch:

- Start from `dev`.
- Create branch: `feat/quantbt-engine-packaging`.

Scope:

- Link this roadmap to the source guide in `upgrade/implement.md`.
- Create rollback/reference tag before migration:
  - `pre-quantbt-engine-packaging-20260731`
- Capture baseline:
  - commit SHA;
  - Python version;
  - NumPy/Pandas/Numba versions;
  - full test result;
  - current Native Event benchmark/RSS baseline if available.
- Run baseline tests using the current environment before any package layout
  changes.

Non-goals:

- No source move yet unless Phase 42A baseline has passed.
- No Native Event optimization.
- No Rust/PyO3.
- No PyPI publish.

Validation target:

```bash
git status
python --version
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests
```

### Phase 42B - Python Package Layout And Wheel Install

Branch:

- Continue on `feat/quantbt-engine-packaging`.

Scope:

- Add package metadata for `quantbt-engine`.
- Add `pyproject.toml` using PEP 621 / uv-compatible build metadata.
- Add `src/quantbt/` package layout.
- Copy current package source into `src/quantbt` safely.
- Add `src/quantbt/py.typed`.
- Keep existing public API/import behavior unchanged.
- Keep the root source during migration until wheel install/parity pass.
- Build and install the package in a clean environment.
- Run public import smoke outside the repository root.

Non-goals:

- Do not optimize Native Event in this branch.
- Do not introduce Rust.
- Do not delete root source until the clean wheel import path and pool_alpha
  compatibility are proven.

Merge gate:

- Public imports pass from clean wheel install.
- Full tests pass.
- Wheel build/install pass.
- Backtest fingerprints unchanged.
- Pool Alpha smoke can import `quantbt` without `PYTHONPATH` hacks.

Validation target:

```bash
uv sync --all-extras --dev
uv run pytest
uv build
python -m pip install dist/quantbt_engine-*.whl
python -c "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
```

### Phase 42C - CI, Pool Alpha Compatibility, And PyPI Preparation

Branch:

- Continue on `feat/quantbt-engine-packaging`, then PR/merge to `dev` only
  after gates pass.

Scope:

- Add CI for:
  - Python 3.11;
  - Python 3.12;
  - Python 3.13;
  - lint/type smoke where safe;
  - full pytest;
  - wheel build;
  - clean wheel install;
  - public import smoke;
  - pool_alpha compatibility smoke.
- Add release workflow skeleton for `quantbt-engine`.
- Prefer PyPI Trusted Publishing/OIDC.
- Keep API token only as manual/emergency fallback.
- Document release procedure:
  - feature branch -> `dev`;
  - release branch -> `main`;
  - tag from `main`;
  - GitHub Release triggers publish.

Non-goals:

- Do not publish to real PyPI without explicit approval.
- Do not tag from `dev`.
- Do not use `main` for package migration experiments.

Merge gate:

- CI-equivalent local commands pass.
- Clean install smoke pass.
- No `PYTHONPATH` dependency in package smoke.
- `main` remains stable/releasable.

Release policy:

- `quantbt-engine 0.1.x`: packaging, Python behavior unchanged.
- `quantbt-engine 0.2.x`: Python Native Event performance improvements.
- `quantbt-native 0.3.x`: optional experimental Rust accelerator.

### Phase 43A - Native Event Behavior Freeze And Baseline Benchmarks

Branch:

- Only create after Phase 42 is merged into `dev`.
- Create branch: `perf/native-event-python-hotpath`.

Scope:

- Tests first; no implementation changes before behavior is frozen.
- Add Native Event callback timing tests:
  - initialize at bar 0;
  - commands effective next bar;
  - same effective bar sequence order;
  - finalize commands beyond end of tape.
- Add lifecycle parity tests for:
  - PLACE;
  - AMEND;
  - REPLACE;
  - CANCEL;
  - CANCEL_ALL;
  - market;
  - limit;
  - stop-market;
  - stop-limit;
  - GTC;
  - GTD;
  - IOC;
  - FOK;
  - reduce-only;
  - parent first-fill/full-fill;
  - OCO;
  - quantity constraints;
  - insufficient margin;
  - funding;
  - intrabar / after-funding / after-order liquidation;
  - multi-symbol.
- Add compact deterministic fingerprints instead of DataFrame string hashes.
- Add baseline benchmark scenarios:
  - 25k bars / low order count;
  - 25k bars / high order churn;
  - 100k bars / low order count;
  - 100k bars / high order churn;
  - parent/OCO-heavy;
  - GTD-heavy;
  - multi-symbol;
  - 100 repeated prepared scores.

Reference/oracle:

- `replay_certified` is the canonical domain/accounting oracle.
- Python single-pass must pass before any Rust work.

Validation target:

```bash
pytest -q tests/native_event
python benchmarks/native_event/benchmark_reactive_session.py
```

Implementation note, 2026-08-01:

- Status: **completed as behavior-freeze and baseline phase**.
- Branch deviation: the detailed guide suggests `perf/native-event-python-hotpath`
  after Phase 42 is merged into `dev`; Phase 42A-C are still on
  `feat/quantbt-engine-packaging`, so Phase 43A was implemented on the same
  rollout branch to preserve package-layout/CI context.
- Runtime implementation changed: **none**. This phase only added tests,
  deterministic fingerprint helpers, and benchmark artifacts.
- Added files:
  - `tests/native_event/test_reactive_callback_contract.py`;
  - `tests/native_event/test_reactive_lifecycle_parity.py`;
  - `tests/native_event/test_reactive_accounting_parity.py`;
  - `tests/native_event/test_reactive_memory_lifetime.py`;
  - `tests/native_event/test_reactive_backend_matrix.py`;
  - `benchmarks/native_event/benchmark_reactive_session.py`;
  - `benchmarks/native_event/reactive_session_baseline.json`;
  - `benchmarks/native_event/reactive_session_baseline.md`.
- Validation:
  - `UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp /root/bobby/pool_alpha/.venv/bin/uv run pytest -q tests/native_event`
    -> `20 passed, 2 skipped, 2 xfailed`.
  - `UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp /root/bobby/pool_alpha/.venv/bin/uv run python benchmarks/native_event/benchmark_reactive_session.py`
    -> completed and wrote baseline artifacts.
- Baseline benchmark summary:
  - 25k low orders: `1.4672s` wall, `329.11 MB` peak RSS, 26 fills.
  - 25k high churn: `1.3999s` wall, `336.55 MB` peak RSS, 1,250 fills.
  - 100k low orders: `4.4641s` wall, `387.48 MB` peak RSS, 26 fills.
  - 100k high churn: `5.2720s` wall, `388.85 MB` peak RSS, 1,000 fills.
  - parent/OCO-heavy: `1.3920s` wall, `388.85 MB` peak RSS, 626 fills.
  - GTD-heavy: `1.3772s` wall, `388.85 MB` peak RSS, 418 fills.
  - multi-symbol lifecycle: `6.0748s` wall, `388.85 MB` peak RSS, 400 fills.
  - prepared 100 scores: `25.2063s` wall, `388.85 MB` peak RSS.
- Known debts surfaced by freeze tests:
  - `xfail`: finalize commands whose effective bar is beyond the market tape
    are currently discarded instead of retained as outside-tape audit records.
  - `xfail`: reactive `single_pass` replay parity currently fails after
    quantity preflight/rounding, with the replay oracle differing in equity.
  - `skip`: Rust/native extension parity and version-mismatch fallback remain
    Phase 44 work because no native wheel is routed yet.
  - Reactive strategy facade is still single-frame oriented; multi-symbol
    lifecycle is tested through `NativeEventBackend.run_order_commands(...)`
    directly.

### Phase 43B - Native Event Python Hot Path, RSS, And Prepared Score

Branch:

- Continue on `perf/native-event-python-hotpath`.

Scope:

- Score retention and result path:
  - add internal score requirements;
  - avoid pandas materialization in score path;
  - keep public `BacktestResultV2` path unchanged.
- Queue/object lifetime:
  - pop consumed scheduled commands;
  - release fill/event callback payload after callback;
  - separate active order state from terminal history;
  - score mode should not retain terminal order objects.
- Context allocation:
  - cache immutable helpers;
  - use read-only OHLCV row views;
  - keep positions as snapshots;
  - avoid active-order snapshots when no active orders.
- Lifecycle indexes where clearly beneficial:
  - active by ID;
  - children by parent;
  - OCO membership;
  - expiry bucket by bar;
  - keep `CANCEL_ALL` simple unless benchmark proves it is a hotspot.
- Margin/accounting cache:
  - refresh close margin once per bar;
  - mark dirty after fill;
  - do not change formulas.
- Prepared runner/evaluator:
  - immutable market arrays reused;
  - mutable session reset per trial;
  - evaluator does not retain prior strategy/result/session;
  - selected candidate reruns replay-certified audit.

Performance rules:

- No `fastmath`.
- No formula simplification.
- No public endpoint/result change.
- No merge if lifecycle/accounting parity fails.

Merge gate:

- Lifecycle parity: 100%.
- Accounting parity: 100%.
- RSS repeated-run plateau.
- Score throughput improves or at least no material regression.
- Audit path remains compatible.

Validation target:

```bash
pytest -q tests/native_event
pytest -q tests/test_phase34*.py
python benchmarks/native_event/benchmark_reactive_session.py
pytest -q quantbt/tests
```

Implementation note, 2026-08-01:

- Status: **completed as Python hot-path/RSS/prepared-score optimization
  phase**.
- Runtime implementation changed:
  - `_ReactiveOrderState` now uses `slots=True`.
  - Reactive session caches immutable context helpers:
    `symbols_tuple`, `size_helper`, empty payload tuples, and active-order
    snapshots.
  - Prepared market arrays, reactive `opens_arr`, and `volumes_arr` are marked
    read-only; context OHLCV now returns row views instead of per-bar copies.
  - Scheduled command queues are popped per bar after execution.
  - Callback payload dictionaries are released after the callback; full
    fills/events are kept in separate compact lifecycle ledgers for reporting.
  - Terminal state cleanup is centralized through `_terminalize_state(...)`.
  - `id_to_order` is kept active/waiting only; score mode does not retain
    terminal order history.
  - Parent children, OCO membership, and GTD expiry buckets are indexed without
    changing insertion-order priority.
  - Close-margin calculation is cached per bar and dirtied after fills or
    liquidation; formulas and liquidation priority are unchanged.
- Public API changed: **none**.
- Source mirrored in both packaging paths:
  - `src/quantbt/backends/native_event.py`;
  - `backends/native_event.py`;
  - `src/quantbt/core/preprocessor.py`;
  - `core/preprocessor.py`.
- Validation:
  - `UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp /root/bobby/pool_alpha/.venv/bin/uv run pytest -q tests/native_event`
    -> `20 passed, 2 skipped, 2 xfailed`.
  - `UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp /root/bobby/pool_alpha/.venv/bin/uv run pytest -q tests/native_event tests/test_phase30d_native_event_reactive_runner.py tests/test_phase34b_native_event_prepared_score.py tests/test_phase34c_native_event_single_pass.py`
    -> `34 passed, 2 skipped, 2 xfailed`.
  - `UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp /root/bobby/pool_alpha/.venv/bin/uv run python benchmarks/native_event/benchmark_reactive_session.py`
    -> completed and refreshed `benchmarks/native_event/reactive_session_baseline.*`.
- Benchmark change versus Phase 43A warm baseline:
  - 25k low orders: `1.4672s -> 1.2510s` (`~14.7%` faster).
  - 25k high churn: `1.3999s -> 1.3620s` (`~2.7%` faster).
  - 100k low orders: `4.4641s -> 3.5485s` (`~20.5%` faster).
  - 100k high churn: `5.2720s -> 3.8159s` (`~27.6%` faster).
  - parent/OCO-heavy: `1.3920s -> 1.1372s` (`~18.3%` faster).
  - GTD-heavy: `1.3772s -> 1.0886s` (`~21.0%` faster).
  - prepared 100 scores: `25.2063s -> 21.6358s` (`~14.2%` faster).
  - Multi-symbol benchmark path changed from reactive facade fallback to direct
    lifecycle package path after Phase 43A documented the facade limitation; it
    is not compared as a like-for-like speedup.
- Known debts still open:
  - The two Phase 43A `xfail` items remain open intentionally: finalize
    outside-tape audit retention and quantity-preflight replay parity.
  - Prepared score still materializes enough accounting arrays to preserve the
    existing score result contract; deeper requirements-driven scalar-only
    metrics can be a later phase only after metric parity is locked.
  - RSS peak is mostly bounded by pandas/result/report artifacts and Numba
    compiled code residency; callback payload retention is now cleaned per bar.

### Phase 44A - PyO3 R0 Scaffold And Backend Fallback

Branch:

- Only create after Phase 43B is merged into `dev`.
- Create branch: `feat/native-event-pyo3`.

Scope:

- Add `rust/native_event`.
- Add Rust/PyO3 package `quantbt-native`.
- Expose `_quantbt_native` version/capabilities only.
- Add thin Python adapter:
  - `quantbt/backends/_native_event_rust.py`.
- Add backend selection internals:
  - `auto`;
  - `python`;
  - `rust`;
  - `replay_certified`.
- Initial rollout:
  - `auto -> python`;
  - `rust` requires explicit opt-in and raises clearly if extension is absent
    or version-incompatible.

Non-goals:

- No production route through Rust yet.
- No domain logic in the adapter.

Validation target:

```bash
cargo fmt --check
cargo clippy -- -D warnings
cargo test
maturin build --release
python -c "import _quantbt_native"
pytest -q tests/native_event
```

Status: completed on `feat/quantbt-engine-packaging` (the planned
`feat/native-event-pyo3` split is deferred until the packaging branch is
integrated into `dev`).

Implemented:

- `rust/native_event` now contains the isolated `quantbt-native 0.3.0` PyO3
  R0 crate. `_quantbt_native` exports only `version`, `api_version`, and a
  capability map; it has no matching, accounting, or execution implementation.
- `src/quantbt/backends/_native_event_rust.py` is the sole optional-import and
  compatibility boundary. It validates API `0.3`, never silently enables an
  incompatible extension, and contains no domain logic.
- `QUANTBT_NATIVE_BACKEND=auto|python|rust|replay_certified` is internal-only:
  `auto` and `python` resolve to the existing Python path, `replay_certified`
  forces the canonical replay route, and explicit `rust` fails clearly until a
  later Rust slice exposes `reactive_session` capability.
- `NativeEventBackend` now records the selected backend and native capability
  state in reactive-result metadata. No endpoint signature or default routing
  changed.
- Main package `native` extra intentionally remains empty until a native wheel
  is published. Maturin remains isolated to the Rust subpackage and its native
  CI workflow, so normal core Python installs and the locked core environment
  do not need an unpublished package or a Rust toolchain.

### Phase 44B - PyO3 R1 Single-Symbol POC

Branch:

- Continue on `feat/native-event-pyo3`.

Scope:

- Rust POC supports:
  - single symbol;
  - PLACE;
  - CANCEL;
  - market;
  - limit;
  - GTC;
  - fee;
  - slippage;
  - position/equity accounting.
- Python adapter compiles command batches into contiguous numeric buffers.
- Rust returns compact fill/event/state arrays.
- Python materializes callback/audit objects only at boundaries.
- `QUANTBT_NATIVE_BACKEND=rust` explicit opt-in only.
- `auto` remains Python.

Parity gate:

- Same command timing.
- Same lifecycle states.
- Same fills.
- Same positions.
- Same fees/slippage.
- Same final equity.

Benchmark gate:

- Median end-to-end speedup >= 1.20x.
- High-churn speedup >= 1.50x.
- Peak RSS reduction >= 30%.
- Repeated-run RSS plateau.

Stop condition:

- If Rust boundary conversion dominates, parity needs loose tolerance, or RSS
  does not improve, keep Rust experimental and do not expand.

### Phase 44C - PyO3 Feature Expansion And Native Release Gate

Branch:

- Continue on `feat/native-event-pyo3`.

Scope:

 
- Expand only after Phase 44B gate passes.
- Feature slices in order:
  - stop orders;
  - amend/replace;
  - reduce-only;
  - quantity constraints;
  - parent-child;
  - OCO;
  - GTD;
  - IOC/FOK;
  - funding;
  - margin/liquidation;
  - multi-symbol.
- Each slice gets differential tests against Python/replay oracle.
- Add native wheel CI for Linux x86-64 first.
- Add combined core+native wheel install test.

Non-goals:

- Do not enable Rust as default `auto` until full parity, randomized
  certification, production soak, wheel coverage, fallback test, and RSS/runtime
  gates all pass.
- Do not publish `quantbt-native` unless the matching `quantbt-engine` version
  exists and combined parity passes.

Release gate:

- Build core wheel.
- Build native wheel.
- Install both in clean environment.
- Run native-event parity suite.
- Run RSS benchmark smoke.
- Publish only from GitHub Release / protected environment.

Status: R2 implementation and CI gate added; release certification remains
blocked on an actual Rust toolchain/combined-wheel run.

Implemented R2 slice:

- Explicit `QUANTBT_NATIVE_BACKEND=rust` now supports, within the existing
  single-symbol/no-funding/no-liquidation/GTC boundary:
  - `STOP_MARKET` and `STOP_LIMIT` touch rules matching the Python reactive
    session;
  - `AMEND` and `REPLACE`, including a replacement alias so a later command
    that targets the original ID reaches the active replacement;
  - reduce-only quantity clipping/cancellation semantics;
  - dynamic `qty_step`, `min_qty`, and `min_notional` filtering through the
    shared canonical `quantize_signed_quantity` helper.
- The Python/Rust boundary remains fixed-width contiguous primitive arrays;
  R2 reuses the R1 buffer layout instead of allocating richer Python objects
  in the bar loop.
- `Native PyO3 Gate` CI now builds the core wheel and native wheel from the
  same ref, clean-installs both, then runs the explicit Rust parity suite and
  Rust RSS benchmark smoke.
- Python-side feature-gate/buffer tests pass locally. Installed-wheel R1/R2
  differential tests are present but skipped locally because this machine has
  no `cargo`, `rustc`, or `maturin`.

Remaining Phase 44C slices and release debt:

- R3: parent-child, OCO, GTD, IOC/FOK, CANCEL_ALL.
- R4: funding, margin acceptance, intrabar/after-funding/after-order
  liquidation.
- R5: deterministic multi-symbol lifecycle ordering.
- Rust format/clippy/test/build, exact differential parity, randomized parity,
  and end-to-end speed/RSS gates must pass in the combined native CI before
  R2 is called certified or `quantbt-native` is published.

### Phase 45 - Packaging And Native Event Branch Audit Closure

Detailed source of truth:

- `upgrade/quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md`
  (especially sections `45` to `57`).

Execution rule:

- Read the detailed v3 audit before every Phase 45 subphase. It overrides this
  summary if a conflict is discovered.
- Do not leave known P0 parity, source-tree, wheel-install, or certification
  debt behind merely to claim a phase complete.
- `src/quantbt` is the canonical implementation during migration; root source
  is a verified compatibility mirror until it can be removed safely.
- Rust remains explicit/experimental and `auto` remains Python until every
  advertised capability has real installed-wheel parity and RSS evidence.

#### Phase 45A - Branch Certification And P0 Correctness Lock

Read first:

- V3 sections `45.1` to `45.4`, `46.1` to `46.7`, `47.1`, and `55` steps 1-3.

Scope:

- Record branch certification evidence through a Draft PR or manual native CI;
  never alter publish triggers for a feature branch.
- Remove required native-event `xfail`s by fixing domain logic, including:
  - reactive quantity preflight parity;
  - finalize commands retained in the immutable audit tape even when their
    effective bar lies beyond executable market data.
- Add complete quantity constraint parity cases: `qty_step`, `lot_size`,
  `min_qty`, `min_notional`, below-minimum post-quantization, reduce-only
  clipping, and floating-point boundary values.
- Make Rust installed-wheel tests use `assert_native_event_full_parity` plus
  explicit raw-session fill/event checks.
- Add a root/src SHA256 synchronization guard and CI coverage so neither tree
  can silently drift before the migration cleanup phase.

Exit criteria:

- No `xfail` in the required native-event domain suite.
- Exact lifecycle/accounting parity with the replay-certified oracle.
- Root and `src` Python trees pass the synchronization guard.
- Core wheel/sdist and native CI commands are ready to run on the feature ref;
  remote CI evidence is archived rather than assumed.

Implementation status (local, 2026-08-01):

- Complete locally: the two required reactive P0 cases no longer use `xfail`.
  Reactive scheduling now applies the same quantity preflight as the static
  replay oracle, while preserving the original requested command in the audit
  tape and reporting canonical rounding/drop diagnostics from replay.
- Complete locally: callback commands with no executable next bar are retained
  as `outside_executable_tape=True` audit intent. They are never scheduled,
  replayed, or allowed to create a synthetic final-bar fill.
- Complete locally: quantity/reduce-only boundary tests, root/src SHA256
  mirror guard, full installed-wheel Rust parity assertions, and raw Rust
  session fill/event comparison checks are present.
- Local evidence: focused native/PyO3/source-sync suite passed `30 passed,
  2 skipped`; broader native, packaging, and lifecycle suite passed
  `90 passed, 4 skipped`. Core wheel and sdist both clean-installed and
  imported successfully from isolated environments.
- Required external evidence before branch certification: run the native CI on
  this feature ref (or a Draft PR) to execute `cargo fmt`, `clippy`, Rust
  tests, built-wheel differential parity, and RSS smoke. This workstation has
  no Rust toolchain, so skipped installed-extension tests are not treated as
  certification. `twine check` remains Phase 45C release validation.

#### Phase 45B - Score Memory And PyO3 Boundary Certification

Read first:

- V3 sections `47.3` to `47.4`, `51`, `52.3` to `52.7`, and `55` steps 4-5.

Scope:

- Make prepared score execution scalar/array-first with conditional path
  allocation, online metrics, and no pandas/result materialization per trial.
- Add isolated process RSS benchmarks, warm-up discipline, threshold checks,
  and parity locks for score versus audit reruns.
- Replace per-trial Rust market copies with a safe shared immutable
  `PreparedMarketCore`; add reusable command/result buffers and compact typed
  boundary payloads before any R3+ lifecycle feature expansion.

Exit criteria:

- Score path retains no unnecessary audit history or DataFrames.
- Python/Rust/replay parity is exact for each advertised R1/R2 capability.
- RSS plateaus across repeated runs and benchmark gates have recorded evidence.
- If the Rust boundary fails the speed/RSS gate, freeze it as experimental and
  do not start R3-R5.

Implementation status (local, 2026-08-01):

- Prepared `.score(...)` now calls the internal direct score route. It builds
  `NativeAccountingArrays` from the completed reactive session and computes
  metrics through the existing array-first performance contract; it does not
  build `BacktestResultV2`, pandas Series, or DataFrames first.
- `NativeEventScoreRequirements` controls session path retention internally.
  The compatible public score contract retains accounting arrays needed for
  exact audit metrics, while fill/event/terminal-order ledgers and endpoint
  result retention are disabled by default. Evaluators also stop retaining the
  last strategy/result unless `retain_last=True` is explicitly requested.
- Added a capacity-managed Rust command buffer and a `PreparedMarketCore`
  PyO3 design. A prepared runner caches that immutable core by exact prepared
  array identity, so a capable native wheel copies market arrays once instead
  of once per score trial. Older R2 wheels retain their explicit compatible
  fallback path; `auto` remains Python.
- Added fresh-process RSS benchmark `run_phase45b_native_event_score_rss.py`
  and a CI gate requiring score/audit final-equity parity, score throughput
  improvement, and score RSS no higher than audit. Local 1,000-bar/100-run
  evidence: score `7.3839s`, `285.23 MB`; audit `10.0324s`, `335.11 MB`;
  final-equity parity exact to `1e-12`.
- Local native/lifecycle/PyO3/source-sync regression remains green. Rust code
  is intentionally not certified locally because this workstation has no
  `cargo`, `rustc`, or `maturin`; the feature-ref CI must compile the new
  `PreparedMarketCore`, run installed-wheel parity, and collect native RSS
  evidence before the PyO3 boundary can be certified or R3-R5 can begin.

##### Phase 45B.1 - Native Evidence Gate For This Linux VPS

Status: **completed: correctness evidence passes; performance gate rejects
Rust default rollout**.

Purpose:

- Close the local evidence gap before Phase 45C. This is certification for the
  current Linux x86_64 / CPython 3.12 VPS only, not a manylinux release claim.

Required procedure:

1. Install a minimal stable Rust toolchain with `rustfmt` and `clippy` outside
   either Python virtual environment; pin the repository with
   `rust-toolchain.toml`.
2. Install `maturin` only into the QuantBT/Pool Alpha Python tool environment,
   never by copying packages between virtual environments.
3. Run `cargo fmt --check`, `cargo clippy -- -D warnings`, and `cargo test` in
   `rust/native_event`.
4. Build a release native wheel, build the core wheel from the same commit,
   then clean-install both into an isolated CPython 3.12 virtual environment.
5. Run the installed-wheel Python/Rust full lifecycle parity suite and the
   fresh-process score/RSS benchmark. Archive JSON evidence locally.
6. Compare Rust against warmed Python single-pass only; do not compare cold
   Numba compilation. If parity or performance gates fail, keep Rust explicit
   and fix the boundary before Phase 45C.

Exit criteria:

- The new Rust source compiles and passes format, lint, and unit tests on this
  VPS.
- Built-wheel installed R1/R2 parity tests no longer skip.
- Prepared-market reuse is observed on the actual extension.
- Python/Rust/replay accounting and lifecycle parity passes for the advertised
  R2 capability matrix, with process-RSS and throughput evidence saved.

Local evidence (Linux x86_64, CPython 3.12, 2026-08-01):

- Installed Rust stable `1.97.1`, `rustfmt`, `clippy`, Linux C build tools, and
  Maturin in the QuantBT virtual environment only. Neither project Python venv
  was replaced or removed.
- `cargo fmt --check`, `cargo clippy -- -D warnings`, and `cargo test` pass.
  The first real compiler pass also fixed a missing NumPy trait import in the
  PyO3 crate and strict dead-code handling in the prepared market container.
- Built and clean-installed core plus native CPython 3.12 Linux wheel. The
  extension imports from `site-packages`, advertises `prepared_market_core`,
  and installed R1/R2 capability tests pass `15 passed, 1 skipped`.
- Correctness is therefore evidenced for the advertised R2 subset only. The
  full native-event suite must not run under `QUANTBT_NATIVE_BACKEND=rust`:
  funding, liquidation, OCO/GTD, and multi-symbol remain explicit unsupported
  features and must raise rather than silently fall back.
- Performance gate **fails**: two fresh clean-wheel probes on identical warmed
  R1 workloads place Rust at `0.69x-0.83x` Python throughput. The first probe
  was `2.5499s` vs `1.9472s` low-order (`0.764x`) and `2.7063s` vs `1.9980s`
  high-churn (`0.738x`); the repeat retained the direction and exact final
  equity/fill counts. Peak RSS was also not lower (Rust `239.81/250.89 MB` vs
  Python `238.41/245.23 MB` in the repeat). `auto` remains Python and
  `quantbt-native` remains unpublished/experimental.
- Root cause is now measured rather than speculative: the R2 adapter crosses
  PyO3 once per callback bar and materializes a `PyDict` plus Python event and
  active-order payload processing on that path. `PreparedMarketCore` removes
  the per-trial market copy but cannot compensate for per-bar boundary churn.
  Do not start R3-R5 on this architecture. A future Rust effort must first
  provide a batched/compiled strategy or a compact typed step protocol and
  demonstrate the documented speed/RSS thresholds.

#### Phase 45C - Core Packaging Track A (Python Only)

Detailed source of truth:

- [QuantBT Native Event - Core Packaging, Python Hot Path and Batched Rust
  Execution Plan](quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md)
- Read the guide sections `1`, `2`, `2.1` to `2.4`, `13.1`, `14`, `15`, and
  `16` before changing packaging or release files.

Status: **completed locally: `quantbt-engine==0.1.0` core packaging gates pass;
root compatibility source intentionally retained**.

Scope:

- Certify the Python core distribution independently from Rust/PyO3.
- Keep `src/quantbt` as the wheel/sdist canonical package source.
- Keep the existing root package mirror temporarily for rollback and editable
  compatibility. Do not delete root files in this phase.
- Keep `tests/test_phase45a_source_tree_sync.py` as a SHA256 drift guard while
  both source locations exist.
- Validate wheel and sdist metadata with `twine check`.
- Test clean wheel and sdist installs from outside the repository root.
- Test the unchanged public import:
  `from quantbt import QuantBTEndpoint`.
- Test Pool Alpha-style editable/path compatibility without requiring
  `PYTHONPATH` for installed-package smoke tests.
- Keep `quantbt-engine[native]` empty/unpublished until the separate Rust
  batched path passes its performance and RSS gates.

Required implementation:

1. README installation uses `quantbt-engine==0.1.0` for the released core and
   `uv sync --all-extras --dev` for repository development.
2. CI validates `uv build`, `twine check dist/*`, clean wheel install, and clean
   sdist install on Python 3.11, 3.12, and 3.13.
3. Publish workflow repeats metadata and clean artifact checks before any OIDC
   publication job.
4. Version gate remains `pyproject.toml 0.1.0` to tag `v0.1.0`.
5. No Rust implementation, endpoint, accounting, or fallback behavior changes
   are allowed in this phase.

Validation commands:

```bash
uv sync --all-extras --dev
uv run pytest -q tests/test_phase42_packaging_layout.py \
  tests/test_phase42c_ci_release.py tests/test_phase45a_source_tree_sync.py
uv build
uv run twine check dist/*
```

Clean artifact gates:

```bash
python3 -m venv /tmp/quantbt-phase45c-wheel
/tmp/quantbt-phase45c-wheel/bin/python -m pip install dist/quantbt_engine-*.whl
cd /tmp
/tmp/quantbt-phase45c-wheel/bin/python -c \
  "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"

python3 -m venv /tmp/quantbt-phase45c-sdist
/tmp/quantbt-phase45c-sdist/bin/python -m pip install dist/quantbt_engine-*.tar.gz
cd /tmp
/tmp/quantbt-phase45c-sdist/bin/python -c \
  "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
```

Exit criteria:

- `quantbt-engine==0.1.0` builds wheel and sdist from `src/quantbt`.
- `twine check dist/*` passes.
- Clean wheel and sdist imports resolve from `site-packages` outside the repo.
- Root source mirror remains present and SHA256-identical to `src/quantbt`.
- Existing alpha/notebook public imports remain unchanged.
- Core package release readiness is independent of `quantbt-native`.
- Rust remains explicit experimental and is not enabled by `auto`.

Local implementation evidence (2026-08-01):

- README now documents `pip install quantbt-engine==0.1.0` and the `uv`
  development workflow; obsolete Poetry/PYTHONPATH package instructions were
  removed from the installation/development section.
- CI and publish workflows now validate distribution metadata and both wheel
  and sdist clean-install smoke paths.
- Root compatibility source was not deleted. The source mirror guard remains
  active for safe future migration.
- Native release readiness remains a separate later phase described by the
  linked v3 guide; Phase 45B.1 performance evidence still blocks native
  publication/default rollout.

#### Phase 45D - Python Native Event Zero-Object Hot Path

Detailed source of truth:

- [`quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md`](quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md)
- Read sections `1`, `3`, `4.1` to `4.9`, `6`, `8`, `10`, `11`, `12`, and
  `13.2` to `13.4` before implementation.

Status: **completed locally on 2026-08-01; Python parity/certification gates
pass.**

Purpose:

- Reduce Python Native Event score-path allocations and RSS without changing
  endpoint behavior, strategy callbacks, accounting, or replay semantics.
- Establish the fair zero-object Python baseline that Rust must beat. Rust must
  not be compared with an unnecessarily heavy Python audit path.

Implementation plan:

- `NativeEventScoreRequirements` now has explicit low-retention scalar and
  compatibility ndarray contracts. Score paths conditionally allocate
  accounting arrays; no dummy full-length arrays are used.
- `NativeEventScalarScoreResult` computes the same array-first metrics online
  with stable moments, daily fallback/annualization, drawdown, trade count,
  hit-rate, profit-factor, fee/funding/turnover and margin counters.
- Scalar prepared scores do not create pandas results, full fill/event
  ledgers, terminal-order history, or emitted command tapes. Scheduled queues
  and per-bar callback payloads are released as soon as callbacks consume them.
- `native_context_requirements` lets a strategy disable transient fills,
  events, active-order snapshots, positions, and margin payloads explicitly.
  Unknown declaration keys fail early. `NativeCommandBatch` is an optional
  immutable callback wrapper; legacy list/tuple returns remain unchanged.
- The compatibility `PreparedNativeEventStrategyRunner.score()` call still
  returns ndarray `NativeEventScoreResult`; `PreparedNativeEventStrategyEvaluator`
  uses the scalar contract by default, so existing direct-path consumers do
  not change behavior.
- Immutable prepared market arrays remain shared across trials. No endpoint
  rename, default backend change, Rust routing, or root-source deletion was
  introduced.

Acceptance:

- Optimized scalar Python score equals replay-certified accounting metrics on
  single- and multi-day tapes, including edge cases with no daily return
  sample.
- Public audit/full-report path remains unchanged; compatibility score tests
  remain green.
- Exact parity holds for equity, positions, fees, funding, margin,
  liquidation, trade count, and scalar lifecycle counters; lifecycle fill and
  event parity remains covered by the existing replay/audit suite.
- Fresh-process benchmark `benchmarks/native_event/benchmark_phase45d_zero_object.py`
  records audit, compatibility score, scalar score, CPU, and peak RSS. The
  100k-bar single-symbol probe recorded audit `10.2708s / 443.57 MB`,
  compatibility score `7.7606s / 294.30 MB`, and scalar score
  `7.3513s / 294.36 MB`, with exact final-equity parity. This is a
  lower-retention/object-allocation result, not a claim that HWM RSS is lower
  on every machine; the scalar score was faster in this fresh process. Rust
  must beat this fair baseline before any native default/release claim.

Validation completed:

```text
tests/test_phase45d_native_event_zero_object.py: 5 passed
tests/test_phase34b_native_event_prepared_score.py: 8 passed
tests/test_phase34c_native_event_single_pass.py: 3 passed
tests/native_event: 49 passed, 4 skipped
tests/test_phase45a_source_tree_sync.py: 1 passed
```

Remaining follow-up is intentionally narrow: benchmark repeated 100k-bar
OCO/GTD, funding/liquidation, and multi-symbol profiles in isolated CI, and
replace the live Python order state with a fully primitive side-table only if
profiling proves it improves RSS without parity drift. Those are not blockers
for the scalar score correctness contract.

Non-goals:

- No Rust routing, no endpoint rename, no default backend change, and no
  removal of the root compatibility source.

#### Phase 45E - Rust Batched Full-Tape Execution

Detailed source of truth:

- [`quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md`](quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md)
- Read sections `1`, `3`, `5.1` to `5.3`, `6`, `7`, `8`, `9`, `10`, `11`,
  `12`, and `13.5` to `13.8` before implementation.

Status: **implemented (explicit experimental backend; native rollout still
blocked by the performance gate)**.

Implementation plan:

- Add an internal `RustBatchedRunner` beside `PythonReactiveRunner`.
- Keep `auto` on Python for arbitrary Python callbacks.
- Add prepared immutable Rust market ownership with one market preparation per
  process/session family, not one copy per trial.
- Implement `run_tape_score(...)` as one PyO3 call for a complete static
  command tape, returning scalar/typed score output.
- Implement `run_tape_audit(...)` with contiguous struct-of-arrays buffers for
  fills and events; do not return per-bar `PyDict`, nested lists, or Python row
  objects.
- Start with the advertised single-symbol R1/R2 scope, then add one feature
  slice at a time: stop orders, amend/replace, reduce-only, and quantity
  constraints.
- Preserve the replay-certified oracle as the source of truth.

Implemented surface:

- `RustBatchedRunner` owns one immutable `PreparedMarketCore` and creates a
  fresh Rust session per static tape, so market arrays are not recopied per
  trial.
- `compile_rust_batched_tape(...)` converts the canonical
  `CompiledOrderCommandArrays` once into contiguous `(command_ptr, codes,
  values, expiry)` buffers.
- `run_tape_score(...)` crosses PyO3 once and returns only scalar accounting and
  lifecycle counters.
- `run_tape_audit(...)` crosses PyO3 once and returns contiguous SoA arrays for
  fills and events; no per-bar Python dictionaries or nested Python rows cross
  the boundary.
- `NativeEventBackend.prepare_rust_batched_runner(...)` is an opt-in helper;
  public endpoint defaults and `auto` routing remain unchanged.
- The certified initial scope is single-symbol R1/R2 with immediate GTC
  market/limit/stop commands, cancel/amend/replace, reduce-only, fee and
  slippage. Unsupported funding, liquidation, quantity constraints, package
  orders, expiry, non-GTC TIF and multi-symbol inputs raise before execution.
- The static tape contract uses the native-event v2 effective bar timeline;
  parity tests intentionally place the first executable command at bar 1.

Acceptance:

- Same market, commands, and config produce exact lifecycle/accounting parity.
- Discrete parity has no tolerance: effective bar, order sequence, fill,
  rejection, quantity, OCO/expiry state and liquidation decision must match.
- Numeric parity uses exact equality where possible and `atol=1e-12` only when
  operation ordering requires it.
- Rust wheel is built and tested in a clean environment, but remains explicit
  experimental until end-to-end performance gates pass.

Validation completed for this phase:

```text
cargo fmt --all
cargo check
local maturin release build + editable wheel install
tests/native_event/test_rust_batched_full_tape.py: 5 passed
tests/native_event: 47 passed, 2 skipped
tests/test_phase45a_source_tree_sync.py + tests/test_phase45d_native_event_zero_object.py: 6 passed
full regression: 623 passed, 3 skipped, 25 warnings
clean manylinux_2_34 CPython 3.12 wheel import smoke: passed
```

The Rust/Python full-tape parity test uses the same prepared market, command
tape and account config. It asserts exact lifecycle counts and `atol=1e-12`
for equity, positions, fees, turnover and fill prices. The audit path also
asserts every returned buffer is C-contiguous. A performance claim is not made
as a release claim yet; Phase 45F owns the isolated multi-scenario benchmark
and release gate. The Phase 45E smoke profile (`100,000` bars, `40` GTC
commands, five warm repetitions) recorded Rust score `0.005314s` versus Python
v2 `0.024851s` median (`4.68x` in this process) with exact final-equity and
fill-count parity. This is evidence for the batched boundary, not a substitute
for the required churn/RSS/multi-symbol gate.

Non-goals:

- Do not compile arbitrary Python strategy callbacks.
- Do not add sparse callbacks or native strategy programs in this phase.
- Do not route `auto` to Rust or publish `quantbt-native` from a partial slice.

#### Phase 45F - Sparse Runner, Certification, And Native Release Gate

Detailed source of truth:

- [`quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md`](quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md)
- Read sections `5.4`, `5.5`, `9`, `10`, `11`, `12`, `13.9`, `13.10`, `14`,
  `15`, and `16` before implementation.

Status: **implemented; native release gate not passed**.

Implementation plan:

- Add a stateful `RustBatchedSession.run_until(...)` so Rust runs many bars
  continuously and Python receives only sparse fill/event wake arrays plus an
  end-of-chunk marker. This is intentionally a static command-tape
  continuation, not an arbitrary Python callback runner.
- Extend feature slices in guide order: parent/OCO, GTD/IOC/FOK,
  funding, margin/liquidation, then multi-symbol.
- Consider a restricted numeric native strategy program only after tape and
  sparse paths pass parity; arbitrary Python is never implicitly compiled.
- Add process-isolated profiling for PyO3 calls, callbacks, command/event
  buffers, kernel time, decode time, peak RSS, post-run RSS, and repeated-run
  plateau.
- Run at least five measured repetitions after warm-up on all guide scenarios.
- Build manylinux CPython 3.11-3.13 wheels and perform combined installed-wheel
  parity before any native release.

Release gate:

```text
100% lifecycle/accounting parity
median end-to-end speedup >= 1.50x
high-churn speedup >= 2.00x
peak RSS reduction >= 40%
repeated-run RSS plateau
```

If any gate fails, Rust stays explicit experimental, `auto` stays Python, and
the failure plus evidence is recorded here. No native extra or PyPI claim is
allowed before the gate passes.

Implementation and certification evidence:

- Added `RustBatchedSession` and `RustBatchedChunkResult` to the canonical
  `src/quantbt` package and kept the root compatibility mirror synchronized.
- The session keeps one Rust lifecycle/accounting state across consecutive
  chunks, caches the compiled command tape, releases the GIL for each long
  chunk, and returns only contiguous sparse fill/event/wake arrays and scalar
  accounting. It does not materialize dense equity or position paths.
- Added `tests/native_event/test_rust_batched_sparse.py`: chunk boundaries,
  cumulative accounting, exact fill/event ledger replay, wake filtering, and
  invalid session transitions all pass.
- Added the process-isolated gate
  `benchmarks/native_event/benchmark_phase45f_release_gate.py` and evidence
  `benchmarks/native_event/phase45f_release_gate.json`.
- Gate run: `100,000` bars, low/high churn, five warm repetitions per backend;
  lifecycle smoke parity passed; speedup was `5.09x` low-churn and `79.06x`
  high-churn; repeated RSS plateau passed; the lower process peak RSS
  reduction was `18.3%`, so the required `40%` RSS gate failed.
- The local installed wheel was rebuilt and exercised on CPython 3.12. The
  CPython 3.11/3.13 manylinux matrix remains a release follow-up, not an
  unverified claim.

Scope integrity note:

- Phase45F adds only the static single-symbol sparse continuation needed by
  the linked guide. It does not expand feature semantics, route `auto` to
  Rust, or claim portfolio/arbitrage/native-program parity.
- The RSS miss is a release blocker, not a domain fallback: the explicit Rust
  backend remains available for the certified feature slice, while unsupported
  features continue to raise before execution.

Non-goals:

- No silent semantic fallback from an unsupported Rust feature.
- No claim of portfolio/arbitrage/native-program parity until those feature
  slices have their own saved evidence bundles.

### Phase 42-44 Definition Of Done

This roadmap is complete only when:

- `pip install quantbt-engine` works independently.
- `from quantbt import QuantBTEndpoint` remains unchanged.
- Existing alphas do not require migration.
- `pool_alpha` can use editable/path dependency and later PyPI dependency.
- Clean wheel install and public import smoke pass.
- GitHub Release can publish through OIDC, not long-lived tokens.
- Missing Rust wheel falls back to Python/Numba.
- Rust version mismatch fails/falls back clearly.
- Rust path passes lifecycle/accounting parity before any default rollout.
- Candidate optimization results can rerun through replay-certified oracle.
- Repeated prepared-score runs reach RSS plateau.
- End-to-end benchmark proves benefit before Rust default.
- `main` remains stable/releasable; no tag is cut from `dev`.

### Phase 42-44 Agent Execution Addendum

Purpose:

- This addendum is the executable checklist for future agents.
- The detailed source of truth remains:
  - Phases 42-44: `upgrade/quantbt_engine_packaging_pypi_pyo3_final_plan_v2_expanded.md`
  - Phase 45 and later: [`upgrade/quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md`](quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md)
- Agents must read the referenced sections before implementing each phase.
- Do not treat the summary above as enough context to code from.
- If this addendum and the detailed guide conflict, follow the detailed guide
  and update this file with the discovered correction.

#### Global Execution Protocol

Hard rule:

- Before starting every Phase 42-44 phase, the agent must first read this
  `Phase 42-44 Agent Execution Addendum` and the detailed guide sections listed
  under that specific phase. This is mandatory even if the agent read it in a
  previous turn.

Before any phase:

1. Confirm branch and remote state:
   ```bash
   git status --short --branch
   git log --oneline --decorate --max-count=8
   git fetch --all --prune
   ```
2. Work from `dev`, not `main`.
3. Use feature branches exactly as the guide specifies.
4. Do not rewrite shared history:
   - no `commit --amend` after remote push;
   - no force-push to `main`;
   - prefer follow-up commits.
5. Keep public imports unchanged:
   ```python
   from quantbt import QuantBTEndpoint
   ```
6. Keep endpoints unchanged unless the guide explicitly allows an internal-only
   selector or environment variable.
7. Preserve domain semantics first; optimize only after parity.
8. Every phase must end with:
   - tests run;
   - exact command output summary;
   - implementation note;
   - remaining debt note;
   - commit.

#### Phase 42A Detailed Guide - Packaging Baseline

Read first:

- Guide sections `1` to `5`.
- Guide section `24`, especially `Phase 1`.
- Guide section `26.1`, `26.2`, `26.3`, `26.4`, `26.5`.
- Guide section `42`.

Branch:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/quantbt-engine-packaging
```

Required artifacts:

- Baseline tag:
  ```bash
  git tag pre-quantbt-engine-packaging-20260731
  ```
- Baseline note in this file containing:
  - commit SHA;
  - branch;
  - Python version;
  - dependency versions for NumPy, Pandas, Numba, Optuna if installed;
  - full test command and result;
  - current Native Event benchmark command and result if benchmark exists;
  - current import mode: root package, not `src/quantbt` yet.

Implementation rules:

- Do not move source in Phase 42A.
- Do not add `src/quantbt` yet unless Phase 42A baseline is complete.
- Do not edit Native Event implementation.
- Do not edit endpoint behavior.
- Do not publish anything.

Validation commands:

```bash
git status --short --branch
python --version
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests
```

Optional if benchmark exists:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 \
  quantbt/benchmarks/native_event/benchmark_reactive_session.py
```

Exit criteria:

- Baseline recorded.
- Rollback tag exists locally.
- Full tests pass or failure is documented as pre-existing with exact failing
  tests.
- No production code changed.

Phase 42A baseline captured on 2026-07-31 UTC:

```text
branch: feat/quantbt-engine-packaging
source branch: dev
baseline commit SHA: 6762cd7ac872e6344fbab13dc23ca790733990ab
origin/dev SHA after fetch/pull: 6762cd7ac872e6344fbab13dc23ca790733990ab
bobby-origin/dev SHA after fetch: 6762cd7ac872e6344fbab13dc23ca790733990ab
rollback/reference tag: pre-quantbt-engine-packaging-20260731
origin tag verification: refs/tags/pre-quantbt-engine-packaging-20260731 -> 6762cd7ac872e6344fbab13dc23ca790733990ab
current import mode: root package layout, no src/quantbt package layout yet
system python3: Python 3.10.4
poetry python3: Python 3.12.13
numpy: 2.2.6
pandas: 2.3.3
numba: 0.65.1
optuna: 4.8.0
```

Baseline protocol commands:

```bash
git fetch --all --prune
git pull --ff-only origin dev
git tag pre-quantbt-engine-packaging-20260731
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q quantbt/tests
```

Baseline full test result:

```text
561 passed, 1 skipped, 25 warnings in 54.19s
```

Baseline Native Event benchmark commands:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 \
  benchmarks/run_phase34a_native_event_memory.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 \
  benchmarks/run_phase34b_native_event_prepared_score.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python3 \
  benchmarks/run_phase34c_native_event_single_pass.py
```

Baseline Native Event benchmark result:

```text
Phase 34A artifact memory:
- minimal: 0.334564s, peak RSS 339.957 MB, commands 3100, fills 3000, events 6100
- standard: 0.501138s, peak RSS 344.855 MB, commands 3100, fills 3000, events 6100
- audit: 0.638208s, peak RSS 348.371 MB, commands 3100, fills 3000, events 6100

Phase 34B prepared score:
- public audit seconds: 2.869046
- prepared score seconds: 1.846037
- speedup: 1.554x
- peak RSS: 335.645 MB
- metric parity: True
- prepared endpoint result retained: False

Phase 34C single-pass:
- replay-certified seconds: 2.352882
- single-pass seconds: 1.977425
- speedup: 1.190x
- peak RSS: 347.438 MB
- accounting parity: True
```

Phase 42A implementation note:

- No package source was moved.
- No `src/quantbt` layout was created.
- No Native Event implementation was changed.
- No endpoint behavior was changed.
- Only the implementation roadmap/baseline notes and generated benchmark
  baseline artifacts changed.

#### Phase 42B Detailed Guide - Python Package Layout

Read first:

- Guide section `6`: target repo structure.
- Guide section `7`: migration rules into `src/quantbt`.
- Guide section `8`: `pyproject.toml`.
- Guide section `23`: pool_alpha migration.
- Guide section `25`: Definition of Done.

File-level patch order:

1. Add packaging metadata:
   - `pyproject.toml`;
   - package metadata for PyPI distribution `quantbt-engine`;
   - Python import module remains `quantbt`;
   - exact dependencies must come from current repo/environment, not guessed
     major upgrades.
2. Add source layout:
   - `src/quantbt/`;
   - `src/quantbt/py.typed`;
   - copy current package source into `src/quantbt` without rewriting logic.
3. Keep root source during migration:
   - do not delete root modules until wheel install, public import smoke, and
     pool_alpha smoke pass.
4. Fix only import/path issues that are caused by package layout.
5. Add packaging smoke tests if missing.

Implementation rules:

- Copy/move safely; do not manually rewrite modules.
- Do not introduce compatibility shim as a long-term source of truth.
- If a root shim is temporarily needed, document it as temporary and add a
  removal gate.
- Do not change domain/accounting/native-event semantics.
- Do not optimize runtime in this branch.
- Do not add Rust.

Validation commands:

```bash
uv sync --all-extras --dev
uv run pytest
uv build
python -m pip install dist/quantbt_engine-*.whl
python -c "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
```

Clean import smoke must run outside repository root:

```bash
cd /tmp
python -c "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
```

Pool Alpha compatibility smoke:

```bash
cd /root/bobby/pool_alpha
poetry run python3 -c "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
```

Exit criteria:

- Wheel builds.
- Wheel installs in a clean environment.
- Public import unchanged.
- Existing tests pass through installed package path.
- pool_alpha can still import QuantBT.
- Backtest fingerprints are unchanged for representative fixtures.

Phase 42B implementation note captured on 2026-07-31 UTC:

```text
branch: feat/quantbt-engine-packaging
distribution name: quantbt-engine
public import module: quantbt
package layout: src/quantbt
root source status: retained during migration
py.typed: src/quantbt/py.typed
build backend: setuptools.build_meta
uv version used for validation: uv 0.12.0
uv cache override: UV_CACHE_DIR=/tmp/uv-cache
native extra status: intentionally empty until Phase 44 creates quantbt-native
```

Phase 42B source/layout changes:

- Added `pyproject.toml` with PEP 621 metadata for the PyPI distribution
  `quantbt-engine`.
- Kept the Python import surface unchanged:
  ```python
  from quantbt import QuantBTEndpoint
  ```
- Copied current runtime source into `src/quantbt` without rewriting domain
  logic.
- Added `src/quantbt/benchmarks` because existing tests and certification
  helpers currently import `quantbt.benchmarks.*`; this preserves compatibility
  with the root package surface during migration. Only benchmark helper Python
  files, `README.md`, and `phase7_thresholds.json` are kept in package source;
  generated benchmark outputs are not copied.
- Added `src/quantbt/py.typed`.
- Added `tests/test_phase42_packaging_layout.py` to lock:
  - distribution name vs import module;
  - `src/quantbt` package layout;
  - root source retained until migration exit gates pass.
- Adjusted `.gitignore` so root benchmark artifacts remain ignored while
  `src/quantbt/benchmarks` can be tracked as package compatibility source.

Phase 42B dependency policy:

- Dependency ranges were pinned around the currently validated Poetry baseline
  instead of broad major ranges:
  - NumPy `>=2.2.6,<2.3`;
  - Pandas `>=2.3.3,<2.4`;
  - Numba `>=0.65.1,<0.66`;
  - Optuna `>=4.8.0,<4.9`;
  - Matplotlib `>=3.10.9,<3.11`;
  - scikit-learn `>=1.8.0,<1.9`;
  - NautilusTrader `>=1.230.0,<1.231`.
- This avoids the package env drifting from the certified baseline, for
  example accidentally resolving NumPy `2.4.x`.

Phase 42B validation commands and results:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q \
  quantbt/tests/test_phase42_packaging_layout.py
```

```text
3 passed in 2.96s
```

```bash
env UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp \
  /root/bobby/pool_alpha/.venv/bin/uv sync --all-extras --dev
```

```text
Resolved 95 packages
Checked 93 packages
```

```bash
env UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp \
  /root/bobby/pool_alpha/.venv/bin/uv run pytest -q
```

```text
564 passed, 1 skipped, 25 warnings in 48.74s
```

```bash
env UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp \
  /root/bobby/pool_alpha/.venv/bin/uv build
```

```text
Successfully built dist/quantbt_engine-0.1.0.tar.gz
Successfully built dist/quantbt_engine-0.1.0-py3-none-any.whl
```

```bash
MPLCONFIGDIR=/tmp poetry run python3 -m pip install --force-reinstall --no-deps \
  /root/bobby/pool_alpha/quantbt/dist/quantbt_engine-0.1.0-py3-none-any.whl
```

```text
Successfully installed quantbt-engine-0.1.0
```

```bash
cd /tmp
MPLCONFIGDIR=/tmp /root/bobby/pool_alpha/.venv/bin/python -c \
  "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
```

```text
<class 'quantbt.endpoint.QuantBTEndpoint'>
```

```bash
cd /tmp
MPLCONFIGDIR=/tmp /root/bobby/pool_alpha/.venv/bin/python -c \
  "from quantbt.benchmarks.run_phase7 import PROFILES; print(sorted(PROFILES)[:3])"
```

```text
['large', 'smoke', 'standard']
```

```bash
cd /root/bobby/pool_alpha
MPLCONFIGDIR=/tmp poetry run python3 -c \
  "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
```

```text
<class 'quantbt.endpoint.QuantBTEndpoint'>
```

Phase 42B validation caveat:

- A first `uv run pytest -q` attempt was accidentally launched from the
  `pool_alpha` parent directory and collected unrelated MLops/alpha tests.
  That failure was unrelated to QuantBT packaging. The accepted gate is the
  rerun from `/root/bobby/pool_alpha/quantbt`, where `pyproject.toml`
  `testpaths = ["tests"]` is active.

Phase 42B remaining debt:

- Root source is still retained intentionally. It should only be removed after
  a later migration gate confirms editable install, wheel install, pool_alpha
  compatibility, and import-path parity across the service notebooks.
- `native` extra remains empty until Phase 44 creates and publishes the
  `quantbt-native` PyO3 package.

#### Phase 42C Detailed Guide - CI, Release Workflow, PyPI Prep

Read first:

- Guide section `16`: versioning.
- Guide section `17`: CI.
- Guide section `18`: PyPI release through Trusted Publishing/OIDC.
- Guide section `19`: publish package workflow.
- Guide section `21`: token fallback rules.
- Guide section `22`: GitHub release procedure.
- Guide section `41`: workflow correction/addendum.
- Guide section `42`: main/dev release policy.

File-level patch order:

1. Add or update `.github/workflows/*` for core package:
   - Python 3.11;
   - Python 3.12;
   - Python 3.13;
   - `uv sync`;
   - tests;
   - wheel build;
   - clean wheel install;
   - public import smoke.
2. Add release workflow skeleton:
   - publish only on GitHub Release `published`;
   - use protected environment `pypi`;
   - use OIDC/trusted publishing, not long-lived token by default.
3. Add manual/TestPyPI token fallback docs only:
   - do not put token in repo;
   - do not require token for normal release path.
4. Add pool_alpha dependency migration docs:
   - local editable/path dependency during development;
   - `quantbt-engine` PyPI dependency after release.

Implementation rules:

- Do not publish to real PyPI without explicit user approval.
- Do not tag from `dev`.
- Do not make push-to-main publish automatically.
- GitHub Release from `main` is the only intended publish trigger.
- Native package workflow must not assume core wheel exists unless the workflow
  builds/downloads/installs it explicitly.

Validation commands:

```bash
uv sync --all-extras --dev
uv run pytest
uv build
python -m pip install dist/quantbt_engine-*.whl
cd /tmp && python -c "from quantbt import QuantBTEndpoint"
```

Exit criteria:

- CI workflow is syntactically valid.
- Local CI-equivalent commands pass.
- Release workflow is prepared but not triggered.
- No PyPI publish happened.
- Release policy documented.

Phase 42C implementation note captured on 2026-08-01 UTC:

```text
branch: feat/quantbt-engine-packaging
publish status: not published
tag status: no release tag created
workflow added: .github/workflows/publish.yml
workflow updated: .github/workflows/ci.yml
release environment: pypi
publish trigger: GitHub Release published event only
trusted publishing: OIDC / id-token write
token fallback: docs only, no token added
```

Phase 42C source/layout changes:

- Replaced the old `PYTHONPATH`-based CI with package-layout CI:
  - Python matrix `3.11`, `3.12`, `3.13`;
  - `uv sync --all-extras --dev`;
  - `uv run pytest -q`;
  - `uv build`;
  - clean wheel install smoke;
  - public import smoke;
  - Pool Alpha style import smoke.
- Added `.github/workflows/publish.yml` for `quantbt-engine`:
  - trigger is only `release: published`;
  - build/test jobs must pass first;
  - artifact upload/download is explicit;
  - publish job uses protected environment `pypi`;
  - publish job uses PyPI Trusted Publishing/OIDC;
  - no long-lived PyPI token is referenced.
- Added `tools/check_release_version.py`:
  - checks `GITHUB_REF_NAME == v{pyproject.version}` when running under GitHub;
  - allows local execution without `GITHUB_REF_NAME`.
- Added `docs/release_packaging.md` and linked it from `docs/README.md`.
- Updated README Python badge to `3.11+`.
- Updated `pyproject.toml`:
  - `requires-python = ">=3.11,<3.14"`;
  - moved `matplotlib` and `seaborn` into core dependencies because public
    import currently imports `quantbt.viz`;
  - kept `nautilus-trader` as optional validation dependency with
    `python_version >= "3.12"` marker because NautilusTrader `1.230.0` does
    not support Python 3.11.

Phase 42C validation commands and results:

```bash
env UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp \
  /root/bobby/pool_alpha/.venv/bin/uv lock
```

```text
Resolved 100 packages
```

```bash
env UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp \
  /root/bobby/pool_alpha/.venv/bin/uv run pytest -q \
  tests/test_phase42_packaging_layout.py tests/test_phase42c_ci_release.py
```

```text
6 passed in 4.94s
```

```bash
env UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp \
  /root/bobby/pool_alpha/.venv/bin/uv sync --all-extras --dev
```

```text
Resolved 100 packages
Checked 93 packages
```

```bash
env UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp \
  /root/bobby/pool_alpha/.venv/bin/uv run pytest -q
```

```text
567 passed, 1 skipped, 25 warnings in 49.23s
```

```bash
env UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp \
  /root/bobby/pool_alpha/.venv/bin/uv build
```

```text
Successfully built dist/quantbt_engine-0.1.0.tar.gz
Successfully built dist/quantbt_engine-0.1.0-py3-none-any.whl
```

Clean wheel install smoke:

```bash
env UV_CACHE_DIR=/tmp/uv-cache \
  /root/bobby/pool_alpha/.venv/bin/uv venv --clear \
  /tmp/quantbt-wheel-smoke-42c \
  --python /root/bobby/pool_alpha/.venv/bin/python
env UV_CACHE_DIR=/tmp/uv-cache \
  /root/bobby/pool_alpha/.venv/bin/uv pip install \
  --python /tmp/quantbt-wheel-smoke-42c/bin/python \
  /root/bobby/pool_alpha/quantbt/dist/quantbt_engine-0.1.0-py3-none-any.whl
cd /tmp
MPLCONFIGDIR=/tmp /tmp/quantbt-wheel-smoke-42c/bin/python -c \
  "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
```

```text
Installed 18 packages
<class 'quantbt.endpoint.QuantBTEndpoint'>
```

Version gate smoke:

```bash
env UV_CACHE_DIR=/tmp/uv-cache MPLCONFIGDIR=/tmp \
  /root/bobby/pool_alpha/.venv/bin/uv run python tools/check_release_version.py
```

```text
quantbt-engine version check passed: 0.1.0
```

Pool Alpha compatibility smoke:

```bash
cd /root/bobby/pool_alpha
MPLCONFIGDIR=/tmp poetry run python3 -c \
  "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
```

```text
<class 'quantbt.endpoint.QuantBTEndpoint'>
```

Phase 42C remaining debt:

- No real PyPI/TestPyPI publish has been performed. Publishing still requires
  explicit user approval, a protected GitHub `pypi` environment, and a GitHub
  Release from `main`.
- `quantbt-native` workflow is intentionally not added yet. Phase 44 must build
  and test the core `quantbt-engine` artifact before any native wheel publish.
- Root source remains retained until a later migration/removal gate proves
  Pool Alpha notebooks/services are using installed/editable package layout
  safely.

#### Phase 43A Detailed Guide - Native Event Behavior Freeze

Read first:

- Guide section `27`: implementation map and public contract.
- Guide section `28`: NE-0 behavior freeze.
- Guide section `34`: lifecycle parity.
- Guide section `39`: required test names.
- Guide section `40`, PR/commit 1: tests only.
- Guide section `43`: Native Event core DoD.

Branch:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b perf/native-event-python-hotpath
```

Required files to add:

- `tests/native_event/test_reactive_callback_contract.py`
- `tests/native_event/test_reactive_lifecycle_parity.py`
- `tests/native_event/test_reactive_accounting_parity.py`
- `tests/native_event/test_reactive_memory_lifetime.py`
- `tests/native_event/test_reactive_backend_matrix.py`
- `benchmarks/native_event/benchmark_reactive_session.py`

Required golden cases:

- market order;
- limit order;
- stop-market;
- stop-limit;
- GTC;
- GTD;
- IOC;
- FOK;
- PLACE;
- AMEND;
- REPLACE;
- CANCEL;
- CANCEL_ALL;
- reduce-only;
- parent first-fill;
- parent full-fill;
- OCO;
- quantity quantization;
- insufficient margin;
- funding;
- intrabar liquidation;
- after-funding liquidation;
- after-order liquidation;
- multi-symbol.

Required fingerprint fields:

- command effective bar;
- command sequence;
- event type/status/reject reason;
- fill bar/symbol/side/qty/price/fee;
- position after each bar;
- equity after each bar;
- margin after each bar;
- liquidation result.

Implementation rules:

- Tests only first.
- Do not change `native_event.py` implementation in the tests-only commit.
- Do not use DataFrame string representation as fingerprint.
- Randomized tests must use fixed seeds and print the seed on failure.
- Reference oracle is `replay_certified`.
- Python single-pass must pass before Rust is attempted.

Validation commands:

```bash
pytest -q tests/native_event
python benchmarks/native_event/benchmark_reactive_session.py
```

Exit criteria:

- Behavior/timing contract locked by tests.
- Baseline benchmark recorded:
  - wall time;
  - CPU time if available;
  - peak RSS;
  - post-run RSS;
  - command count;
  - event count;
  - fill count;
  - max active orders.
- No implementation changed before baseline tests exist.

#### Phase 43B Detailed Guide - Native Event Python Hotpath Optimization

Read first:

- Guide section `29`: score retention and result path.
- Guide section `30`: queue and object lifetime.
- Guide section `31`: context allocation.
- Guide section `32`: beneficial indexes.
- Guide section `33`: margin/accounting cache.
- Guide section `35`: prepared runner integration.
- Guide section `40`, PR/commit 2 to PR/commit 5.
- Guide section `43`: Native Event core DoD.

Patch order:

1. Retention and queue cleanup:
   - mostly `quantbt/backends/native_event.py` or
     `src/quantbt/backends/native_event.py` after packaging;
   - pop consumed scheduled commands;
   - release fills/events after callback;
   - separate active order state from terminal history;
   - add one terminal transition helper.
2. Context and margin cache:
   - cache symbols tuple;
   - cache size helper;
   - use empty tuple constants;
   - make prepared market arrays read-only after build;
   - use OHLCV row views, not copies;
   - keep position snapshot semantics;
   - refresh close margin once per bar;
   - dirty margin after fill.
3. Parent/OCO/expiry indexes:
   - children by parent ID;
   - members by OCO group;
   - expiry bucket by bar;
   - avoid changing order priority.
4. Prepared score integration:
   - internal score requirements;
   - no pandas materialization in score path;
   - mutable session reset per trial;
   - evaluator does not retain last strategy/result/session;
   - selected candidate reruns replay-certified audit.

Implementation rules:

- No `fastmath`.
- No formula simplification.
- Do not change callback timing.
- Do not change command next-bar semantics.
- Do not change same-bar command ordering.
- Do not change public `BacktestResultV2`.
- Do not change public endpoint signatures.
- If a speed optimization changes lifecycle/accounting parity, revert it.
- Add benchmark evidence before claiming performance improvement.

Required parity checks:

- lifecycle state exact;
- command count/effective bar/order exact;
- reject codes exact;
- fill side/qty/price/fee exact;
- parent activation exact;
- OCO cancellation exact;
- expiry exact;
- liquidation flag/bar/reason exact;
- positions/equity/fees/funding/turnover/margin exact or `atol <= 1e-12`
  only when float operation order is the sole difference.

Validation commands:

```bash
pytest -q tests/native_event
pytest -q tests/test_phase34*.py
python benchmarks/native_event/benchmark_reactive_session.py
pytest -q quantbt/tests
```

Exit criteria:

- Lifecycle parity 100%.
- Accounting parity 100%.
- Repeated prepared-score RSS plateaus.
- Score path avoids unnecessary pandas/report materialization.
- Public audit path remains compatible.
- Benchmark report shows runtime/RSS before vs after.

#### Phase 44A Detailed Guide - PyO3 R0 Scaffold

Read first:

- Guide section `9`: Rust/PyO3 subpackage.
- Guide section `10`: Rust scope and boundary.
- Guide section `36.1` and `36.2`: adapter and rollout.
- Guide section `37`, Slice R0.
- Guide section `40`, PR/commit 6.
- Guide section `41`: native workflow correction.
- Guide section `42`: release policy.

Branch:

```bash
git checkout dev
git pull --ff-only origin dev
git checkout -b feat/native-event-pyo3
```

Required files:

- `rust/native_event/Cargo.toml`
- `rust/native_event/pyproject.toml`
- `rust/native_event/src/lib.rs`
- later split candidates:
  - `rust/native_event/src/session.rs`
  - `rust/native_event/src/types.rs`
  - `rust/native_event/src/matching.rs`
  - `rust/native_event/src/accounting.rs`
- Python adapter:
  - `quantbt/backends/_native_event_rust.py`
  - or `src/quantbt/backends/_native_event_rust.py` after packaging.

Implementation rules:

- R0 exposes only version/capabilities/import smoke.
- Do not route production runs through Rust in R0.
- Keep `auto -> python`.
- `rust` explicit opt-in must raise clearly if extension is absent or version
  incompatible.
- No domain logic in adapter.
- No async runtime, message bus, actor model, Rayon, unsafe optimization, or
  fast-math.

Validation commands:

```bash
cargo fmt --check
cargo clippy -- -D warnings
cargo test
maturin build --release
python -c "import _quantbt_native"
pytest -q tests/native_event
```

Exit criteria:

- Rust crate builds.
- Python fallback works without extension.
- Explicit Rust mode fails clearly when unavailable.
- Version/capability check exists.
- No production behavior changed.

#### Phase 44B Detailed Guide - PyO3 R1 POC

Read first:

- Guide section `12`: PyO3 POC.
- Guide section `36.3` to `36.11`: Rust session API and boundary.
- Guide section `37`, Slice R1.
- Guide section `38`: benchmark and stop conditions.

R1 supported scope:

- single symbol;
- PLACE;
- CANCEL;
- market;
- limit;
- GTC;
- fee;
- slippage;
- position/equity accounting.

Python/Rust boundary:

- one Rust call per bar;
- no per-fill/per-fee/per-margin PyO3 calls;
- Python compiles command batches into contiguous numeric buffers;
- Rust returns compact arrays/scalars;
- Python materializes events/context only at callback boundary;
- strategy callbacks remain Python.

Bar 0 flow must match guide:

1. `step(0, empty commands)`;
2. build context 0;
3. `initialize(context0)`;
4. `on_bar_close(context0)`;
5. concatenate initialize commands before bar0 commands;
6. execute them at bar 1.

Opt-in behavior:

- `QUANTBT_NATIVE_BACKEND=rust` may route R1-supported cases to Rust.
- `auto` remains Python.
- Unsupported Rust feature must raise/fallback according to selected backend,
  never silently change semantics.

Validation commands:

```bash
pytest -q tests/native_event
pytest -q tests/native_event -k rust
python benchmarks/native_event/benchmark_reactive_session.py --backend python
python benchmarks/native_event/benchmark_reactive_session.py --backend rust
```

Exit criteria:

- Same commands.
- Same fills.
- Same positions.
- Same fee/slippage.
- Same final equity.
- Median end-to-end speedup >= 1.20x.
- High-churn speedup >= 1.50x.
- Peak RSS reduction >= 30%.
- Repeated-run RSS plateau.

Stop conditions:

- Boundary conversion dominates runtime.
- Strategy Python time dominates and Rust cannot move needle.
- RSS does not improve.
- Parity requires loose tolerance.
- Maintenance complexity exceeds benefit.

Status: implemented on `feat/quantbt-engine-packaging`; local native wheel
build/parity remains pending the Rust toolchain and Maturin CI gate.

Implemented:

- Rust `ReactiveSessionCore` now owns single-symbol R1 market arrays, active
  order state, GTC market/limit matching, PLACE/CANCEL lifecycle, fee,
  slippage, PnL, position, equity, and basic post-cost margin acceptance.
- The Python adapter compiles per-bar `OrderCommand` batches into contiguous
  `int64` code and `float64` value arrays, preserves command identity through
  a session-local interner, and materializes callback objects only at the
  boundary.
- Explicit `QUANTBT_NATIVE_BACKEND=rust` routes to R1 only for: one symbol,
  no funding, no quantity constraints, immediate non-contingent orders, GTC,
  and `maintenance_ratio=0.0`. Unsupported scope raises rather than falling
  back silently. `auto` remains Python.
- Rust path is compared with `replay_certified` via an installed-wheel parity
  test. The native CI workflow now builds the wheel, installs it into the core
  test environment, and runs `tests/native_event -k rust`.

Remaining R1 certification gate:

- This local machine has no Rust toolchain/Maturin, therefore only the Python
  adapter/buffer/fake-extension boundary tests run locally. The real Rust
  compile, Python-Rust differential parity, RSS plateau, and speed gates must
  pass in `Native R0` CI before R1 can be called certified or considered for
  further Rust expansion.

#### Phase 44C Detailed Guide - PyO3 Expansion And Release Gate

Read first:

- Guide section `13`: Rust expansion order.
- Guide section `37`, Slices R2 to R5.
- Guide section `38`: benchmark gates.
- Guide section `41`: workflow correction.
- Guide section `42`: main/dev release policy.

Expansion order:

1. Stop orders.
2. AMEND.
3. REPLACE.
4. Reduce-only.
5. Quantity constraints.
6. Parent-child.
7. OCO.
8. GTD.
9. IOC.
10. FOK.
11. Funding.
12. Margin/liquidation.
13. Multi-symbol.

Implementation rules:

- One feature slice at a time.
- Every slice must add differential parity tests first or in the same commit.
- Do not enable Rust as default `auto` after a partial POC.
- Do not publish native wheels until combined core+native parity passes.
- Keep Python/Numba fallback and replay oracle.

Native wheel CI requirements:

- Linux x86-64 first.
- Build native wheel.
- Build/install core wheel from same tag/ref.
- Install both wheels.
- Run native parity tests.
- Run RSS benchmark smoke.

Release gate:

```text
feature branches -> dev -> release branch -> main -> GitHub Release -> PyPI
```

Do not:

- tag from `dev`;
- publish from uncommitted local tree;
- publish on push to `main`;
- publish native package if core compatible package has not passed combined
  wheel install tests.

Exit criteria:

- All Rust-supported features have exact lifecycle/accounting parity.
- Unsupported features fallback/raise clearly.
- Native package remains optional.
- Core package installs without Rust.
- `quantbt-engine[native]` installs both packages when wheels are available.

#### Required Test Name Checklist

Agents should map the detailed guide section `39` to concrete tests. Minimum
test names:

- `test_native_event_initialize_and_bar0_ordering`
- `test_native_event_commands_effective_next_bar`
- `test_native_event_same_bar_command_sequence`
- `test_native_event_cancel_replace_amend_parity`
- `test_native_event_parent_activation_parity`
- `test_native_event_oco_parity`
- `test_native_event_gtd_expiry_bar_parity`
- `test_native_event_ioc_fok_parity`
- `test_native_event_reduce_only_parity`
- `test_native_event_quantity_constraint_parity`
- `test_native_event_funding_parity`
- `test_native_event_margin_sequence_parity`
- `test_native_event_liquidation_priority_parity`
- `test_native_event_multisymbol_parity`
- `test_native_event_score_no_pandas_materialization`
- `test_native_event_score_does_not_retain_terminal_orders`
- `test_native_event_consumed_queues_are_released`
- `test_native_event_repeated_score_rss_plateaus`
- `test_native_event_python_vs_replay_randomized`
- `test_native_event_rust_vs_replay_randomized`
- `test_native_event_backend_fallback_without_extension`
- `test_native_event_backend_version_mismatch_falls_back`

#### Phase 45C Detailed Guide - Core Packaging Track A

Read first, every time this phase is resumed:

- [`quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md`](quantbt_engine_packaging_pypi_pyo3_final_plan_v3_branch_audit.md),
  sections `1`, `2`, `2.1` to `2.4`, `13.1`, `14`, `15`, and `16`.
- This Phase 45C entry above, including the explicit root-source retention
  decision.

Hard rules:

- Work on core packaging only; do not modify Rust execution semantics.
- `src/quantbt` is the distribution source.
- Root `quantbt` compatibility files stay in place during this phase.
- Keep the SHA256 root/src mirror guard; do not replace it with a deletion
  check.
- Do not publish or enable `quantbt-native`.
- Keep `from quantbt import QuantBTEndpoint` unchanged.

Required checks:

```bash
uv sync --all-extras --dev
uv run pytest -q tests/test_phase42_packaging_layout.py \
  tests/test_phase42c_ci_release.py tests/test_phase45a_source_tree_sync.py
uv build
uv run twine check dist/*
```

Then install both `dist/quantbt_engine-*.whl` and
`dist/quantbt_engine-*.tar.gz` into separate temporary environments and import
from a directory outside the repository. Record the exact result, source
path, version, and root/src mirror status in this implementation log.

Phase 45C is complete only when wheel, sdist, CI metadata, public import,
editable/path compatibility, and source-sync checks pass. Python hot-path work
is Phase 45D; Rust batched execution is a separate Phase 45E/45F track.

#### Final Merge Checklist For This Roadmap

Before merging each branch into `dev`:

- update this implementation log with:
  - implemented items;
  - exact tests;
  - exact benchmark numbers;
  - known remaining debt;
  - commit hashes.
- run branch-specific tests;
- run full tests where feasible;
- verify public import unchanged.

Before merging any release branch into `main`:

- clean wheel install passes;
- no `PYTHONPATH` dependency;
- pool_alpha smoke passes;
- release notes/changelog/version are correct;
- PyPI workflow is configured but not accidentally triggered.

Before enabling Rust by default:

- full lifecycle parity passes;
- randomized differential tests pass;
- production soak completed;
- wheel coverage is sufficient;
- fallback tests pass;
- runtime/RSS gates pass end-to-end, not just inside Rust kernel.

## Final Upgrade - Dual Backend, RSS, And PyPI Release

Status: **Phases 46A-46B implemented locally; Phases 46C-46F remain planned**.

Detailed source of truth:

- [`quantbt_final_upgrade_dual_backend_pypi_plan.md`](quantbt_final_upgrade_dual_backend_pypi_plan.md)
- Before implementing each phase, read the linked guide sections named in
  that phase. This summary is a tracking plan, not a replacement for the
  detailed guide.

Branch baseline:

- Work from `feat/quantbt-engine-packaging` after the committed Phase45F
  state.
- Phase45F sparse runner is implemented and full regression is green.
- Rust remains explicit experimental because the current process peak-RSS
  gate is not passed; `auto` remains Python.

Global rules for all six phases:

- Correctness and replay certification precede optimization claims.
- Keep `from quantbt import QuantBTEndpoint` and existing endpoint defaults
  compatible.
- Never silently fallback from an explicit unsupported Rust capability or
  silently change execution semantics.
- Keep the root compatibility mirror through the intermediate phases. Remove
  it only in the final packaging phase after the source-sync and clean-install
  gates pass.
- Do not use total-process RSS alone as an engine-memory claim. Record
  interpreter, import, prepared, execution-peak, and post-run checkpoints.
- Every phase ends with focused tests, exact benchmark/evidence output, a
  technical-debt note, and a commit using the configured contributor identity.
- Do not publish to production PyPI without explicit release approval. Build
  and TestPyPI/OIDC validation may be prepared earlier, but credentials and
  tokens must never enter the repository.

### Phase 46A - PyPI Baseline And Correctness Certification

Status: **implemented locally; focused correctness and mirror gates pass**.

Detailed guide sections:

- Guide [`quantbt_final_upgrade_dual_backend_pypi_plan.md`](quantbt_final_upgrade_dual_backend_pypi_plan.md), sections `1`, `2`,
  `2.1` to `2.3`, `13.1`, and Patch `F1` in section `16`.

Objective:

- Establish one correctness contract before changing the performance path.
- Capture the core PyPI readiness baseline while keeping source layout and
  public imports stable.

Implementation:

- Add one canonical `assert_native_event_full_parity(candidate, oracle, ...)`
  helper used by Python optimized, Rust batched, and replay-certified tests.
- Compare effective bar, command sequence, acceptance/rejection, status
  transitions, fills, position/equity/fee/funding/turnover paths, margin,
  parent/OCO/TIF/expiry/liquidation state where the capability exists, and
  final state.
- Use exact equality for discrete fields; use `rtol=0, atol=1e-12` only for
  numeric operation-order differences that cannot change a discrete decision.
- Create the canonical capability matrix consumed by the Python selector,
  Rust `capabilities()`, tests, and docs. Rust unsupported requests must fail
  clearly before execution.
- Add seeded randomized differential tests and remove any required `xfail`
  from the advertised single-symbol R2 scope.
- Verify `pyproject` version, public metadata, core wheel/sdist entry points,
  and existing root/src mirror integrity without deleting the mirror yet.

Required tests/evidence:

- Full Python/replay lifecycle matrix.
- Rust/replay R2 matrix for the installed wheel.
- Randomized Python-vs-replay and Rust-vs-replay fingerprints.
- Public import and source-sync tests.
- Evidence JSON must include `oracle_fingerprint`, candidate fingerprints,
  exact parity status, capability matrix version, and commit hash.

Acceptance and debt:

- No performance result is accepted unless full parity passes first.
- Any unsupported capability remains an explicit debt and is not included in
  the Rust release claim.
- Evidence is emitted by
  [`benchmark_phase46a_certification.py`](../benchmarks/native_event/benchmark_phase46a_certification.py)
  and records fingerprints, exact parity, capability version, and source
  commit. The root compatibility mirror remains intentionally retained.
- Remaining Phase 46A scope note: the installed Rust audit/replay matrix is
  covered by the existing Rust batched full-tape tests and the new parity
  contract; full score-path equivalence is deliberately Phase 46B.

### Phase 46B - Apples-To-Apples Score And RSS Benchmark

Status: **implemented locally; scalar parity, audit parity, and standard RSS
evidence pass**.

Detailed guide sections:

- Guide sections `3`, `3.1` to `3.3`, `4`, `4.1` to `4.2`, and Patch `F2`.

Objective:

- Replace the current unfair Rust-scalar versus Python-minimal-result
  comparison with equivalent scalar artifacts and staged RSS evidence.

Implementation:

- Add an internal Python `run_compiled_tape_score(...)` that avoids pandas,
  `BacktestResultV2`, full ledgers, command reports, and nested artifacts.
- Return the same scalar fields as Rust:
  `final_equity`, `final_position`, `total_fee`, `total_turnover`, fill/event
  counters, rejection/cancellation counters, and margin maxima.
- Run one full audit parity pass before timing and persist its fingerprint.
- Build separate Python, Rust, and replay child fixtures. Do not prepare two
  backend representations in one process.
- Record `rss_interpreter`, `rss_after_import_quantbt`,
  `rss_after_market_prepare`, `rss_after_command_compile`,
  `rss_after_runner_prepare`, `peak_rss_during_run`, and `rss_after_run`.
- Run at least five warm measured repetitions for low churn, high churn, and
  repeated prepared-score scenarios; add the 100-run RSS plateau workload.

Required evidence:

- JSON fields for fingerprints, scalar parity, timing medians, CPU time,
  absolute RSS, incremental prepared RSS, incremental execution peak, and
  post-run RSS.
- No claim based only on final equity/fill count or total-process percentage.

Acceptance and debt:

- The benchmark is valid only when Python and Rust have the same scalar
  artifact contract and the one-time audit fingerprint matches.
- If Python score-path overhead dominates, record it as facade debt instead
  of overstating Rust speedup.
- Implementation is in `NativeEventBackend.run_compiled_tape_score(...)` and
  the scalar properties on `NativeEventScalarScoreResult`; source mirrors are
  kept byte-identical during the packaging transition.
- Evidence runner:
  [`benchmark_phase46b_score_rss.py`](../benchmarks/native_event/benchmark_phase46b_score_rss.py).
  Standard evidence:
  [`phase46b_score_rss.json`](../benchmarks/native_event/phase46b_score_rss.json).
  Methodology and runnable command:
  [`native_event_score_rss.md`](../docs/native_event_score_rss.md).
- The 2,000-bar, five-sample profile passed full audit parity and scalar
  parity for low/high churn; both Python and Rust 100-run score plateaus
  passed. Rust was faster on this host, while total process RSS remained
  dominated by the shared Python/package import floor. Prepared and execution
  deltas are reported separately and are not conflated with that floor.
- Phase 46B does not change public endpoint defaults and does not certify
  portfolio, arbitrage, multi-symbol, or unsupported Rust capabilities.

### Phase 46C - Import Graph, Core Dependencies, And RSS Floor

Status: **implemented locally; import, public-API, mirror, metadata, and fresh-process RSS gates pass**.

Detailed guide sections:

- Guide section `5`, subsections `5.1` to `5.4`, section `13.1`, and Patch
  `F3`.

Objective:

- Lower the process RSS floor for both backends without removing public names.
- Make the core PyPI distribution usable without visualization, optimization,
  Nautilus, or report extras installed.

Implementation:

- Refactor `src/quantbt/__init__.py` to keep only minimal core imports eager
  and expose non-core public names through safe lazy imports.
- Preserve public export identity for `QuantBTEndpoint`, results, schemas,
  `quick_plot`, `tearsheet`, `OptunaOptimizer`, Nautilus helpers, and other
  existing names.
- Move matplotlib/seaborn to `viz`, Optuna to `optimization`, Nautilus to
  `validation`, and QuantStats/report dependencies to `reports` extras as
  specified by the guide. Core import must work without those extras.
- Add import-time and fresh-process RSS tests; use `-X importtime` evidence.
- Keep the root mirror and SHA256 sync guard during this phase. Do not turn
  lazy import work into an unreviewed source deletion.

Implementation completed:

- Core `quantbt` import now resolves optional public exports through a cached
  module-level lazy resolver. `QuantBTEndpoint`, engines, schemas, execution
  contracts, metrics, and result types remain eager core imports.
- `matplotlib` and `seaborn` were removed from core `project.dependencies` and
  the corresponding `uv.lock` package metadata. They remain in `viz`/`all`;
  Optuna, QuantStats, and Nautilus remain owned by their existing extras.
- `walkforward.DuplicatePruner` no longer imports Optuna at module import;
  Optuna is loaded only by the optimization execution path.
- Top-level backend/report/viz imports were moved behind the method or lazy
  export boundary. Existing root compatibility mirror files were synchronized
  from `src/quantbt` and remain protected by the mirror test.
- Added [`import_graph_and_rss_floor.md`](../docs/import_graph_and_rss_floor.md),
  [`test_phase46c_import_graph.py`](../tests/test_phase46c_import_graph.py),
  and [`benchmark_phase46c_import_rss.py`](../benchmarks/native_event/benchmark_phase46c_import_rss.py).

Evidence:

- [`phase46c_import_rss.json`](../benchmarks/native_event/phase46c_import_rss.json)
  records a fresh `/tmp` child process with no forbidden optional modules,
  `QuantBTEndpoint.__module__ == "quantbt.endpoint"`, 1,007 loaded modules,
  and 188,170,240 bytes RSS after core import on the current host for the
  saved run. RSS is allocator/environment dependent; the JSON is the exact
  evidence for that run.
- The focused Phase 46A/46B/46C and source-mirror suite passed with `23 passed`.
- The complete public `quantbt.__all__` surface (351 names) resolved in the
  full development environment. Optional names still require their declared
  extra when installed in a core-only environment.
- The pinned build toolchain produced
  `quantbt_engine-0.1.0-py3-none-any.whl` and
  `quantbt_engine-0.1.0.tar.gz`. The wheel was imported from a target
  directory with `--no-deps`; its metadata contains only NumPy/pandas/Numba as
  unconditional requirements and keeps optional markers for viz,
  optimization, reports, and validation.
- Full regression passed with `648 passed, 3 skipped`.

Required tests/evidence:

- `import quantbt` does not import matplotlib, seaborn, Optuna, Nautilus, or
  reporting modules.
- All public exports remain accessible and preserve direct-import identity.
- Thread-safety smoke for lazy export access.
- Core-only wheel/sdist install plus each optional extra in isolation.
- Full regression and before/after import RSS report.

Acceptance and debt:

- Core package import must not require optional extras.
- Any downstream import that depended on eager side effects must be fixed
  explicitly and tested; no hidden fallback import is allowed.
- Phase 46C does not claim prepared-tape, execution, portfolio, or Rust RSS
  improvements. Those remain Phase 46D/46E work; the measured value here is
  the fresh core import/process floor only.

### Phase 46D - Market Ownership, Tape Memory, And Rust Hot State

Status: **implemented locally on `feat/quantbt-engine-packaging`; ownership,
hot-state, score-boundary, reset, and bounded-cache gates pass.** The Rust
extension remains explicit/experimental under the Phase 46 release policy;
this phase does not silently change the endpoint default.

Detailed guide sections:

- Guide sections `6`, `6.1` to `6.4`, `7`, `7.1` to `7.3`, `8`, `8.1` to
  `8.4`, `9`, `9.1` to `9.2`, and Patches `F4` and `F5`.

Objective:

- Remove avoidable duplicate market/tape ownership and reduce Rust order/
  buffer allocation churn without altering domain semantics.

Implementation:

- Split fixtures and prepared containers into explicit Python-owned and
  Rust-owned paths. After one safe Rust copy, release DataFrame/Series and
  temporary NumPy inputs before timing checkpoints.
- Keep Rust `PreparedMarketCore` immutable and consider `Box<[T]>` or
  `Arc<[T]>` only after parity; do not use unsafe NumPy borrows in this
  phase.
- Replace linear active-order scans with an order-slot table, O(1) ID lookup,
  priority-preserving active sequence, tombstone compaction, and tested alias
  path compression.
- Add reusable SoA audit buffers, typed score result boundary where safe, and
  reset parity tests before allowing buffer reuse.
- Replace unbounded object/tape retention with stable-fingerprint bounded
  cache policy and `clear_tape_cache()` service control.
- Avoid simultaneously retaining original `OrderCommand` objects, compiled
  objects, and Rust arrays in score runs unless audit explicitly requests it.

Implementation completed:

- Prepared market arrays now cross the PyO3 boundary once into immutable Rust
  `Box<[T]>` storage. The runner can release the Python market frame and
  temporary arrays after preparation without invalidating execution.
- Reactive Rust state now uses an O(1) order-slot table with an ID index,
  priority-preserving active sequence, tombstone compaction, and bounded alias
  path compression/cycle protection. Slot reuse is delayed until compaction
  so same-bar replacement cannot duplicate priority entries.
- Score execution uses a typed `BatchedScoreResultCore` and scalar counters;
  fill/event/order snapshots are materialized only by audit or sparse paths.
  The static tape adapter explicitly translates canonical compiler
  `REPLACE/AMEND` codes to the stable reactive ABI, preserving the existing
  R2 behavior.
- Static tapes use a stable primitive-array fingerprint and one runner-local
  byte-bounded cache. `RustBatchedRunner.clear_tape_cache()` gives services a
  deterministic release control. Sparse sessions expose `reset()` and retain
  Rust buffer capacity while resetting accounting/lifecycle state.
- Evidence and operational notes are recorded in
  [`docs/native_event_rust_ownership_r2.md`](../docs/native_event_rust_ownership_r2.md).

Required tests/evidence:

- Exact lifecycle/accounting parity after each Rust state change.
- Replacement-chain and alias-cycle tests.
- Audit/score reset parity and 100-run memory plateau.
- Rust-only prepared RSS checkpoints with Python inputs released.
- Low/high order churn benchmarks and command-cache byte limits.

Evidence:

- `cargo fmt --check` and `cargo check --manifest-path
  rust/native_event/Cargo.toml` pass after the ownership/order-table changes.
- Focused ownership, replacement-chain/cycle, typed-score, bounded-cache, and
  sparse-reset tests pass with the installed local extension: `60 passed,
  2 skipped`. The full repository regression is `654 passed, 3 skipped`.
  The JSON evidence file is at
  `benchmarks/native_event/phase46d_ownership_r2.json`.
- The benchmark reports low/high order churn, first/repeated score timing,
  Rust-owned incremental RSS, cache bytes before/after clear, and 100-run
  sparse-session reset parity. Its RSS numbers are incremental Rust-path
  measurements, not a claim about the Phase 46C fresh-process import floor.
  On the 2,000-bar/100-run profile it passed with 40 low-churn orders and
  3,999 high-churn orders; repeated score RSS growth was 0 bytes in both
  profiles, and reset/cache gates passed.

Acceptance and debt:

- All discrete decisions and accounting must remain exact.
- If memory is not reduced after ownership separation, record allocator/import
  floor separately; do not loosen domain parity or gate thresholds.

Residual scope is intentionally unchanged: the later Phase 46E Python hot
state and dual-backend release gate remain open, and the Rust backend is not
auto-enabled until its complete parity/RSS/release gates pass.

### Phase 46D.1 - Fast Score Cache And RSS Refinement

Status: **implemented locally on `feat/quantbt-engine-packaging`; benchmark
parity and score/RSS plateau gates pass.** The optional prepared-RSS reduction
target was measured but not claimed; execution remains explicit Rust and
`auto` remains Python.

Guide link:

- [`quantbt_final_upgrade_dual_backend_pypi_plan.md`](quantbt_final_upgrade_dual_backend_pypi_plan.md),
  sections `8.2`, `8.4`, `9.1` to `9.2`, `10.1`, and gate section `12`.

Objective:

- Remove per-score tape fingerprint work from the measured Rust path while
  preserving a stable, complete cache identity and avoiding retention of the
  original command object.
- Reduce avoidable sparse-result allocation when the caller does not request
  fill/order-event wake payloads, without changing scalar accounting or the
  default audit path.
- Re-run the exact Phase 46B benchmark and target a return toward the earlier
  `~167x` to `~180x` Rust/Python score ratio where the workload supports it;
  report failure honestly if the state-table or ABI boundary remains the
  limiting factor.

Implementation:

- Compute the complete primitive command-tape fingerprint at compile time,
  including all fields that affect Rust validation or execution. Treat the
  compiled tape arrays as an immutable internal contract so cache identity
  cannot become stale through post-compile mutation.
- Make `RustBatchedRunner._tape_arrays()` use the stored fingerprint in the
  hot score loop; retain only bounded primitive arrays and the digest.
- Keep the explicit `clear_tape_cache()` and byte-limit behavior unchanged.
- Add a sparse fast path that retains scalar counters but does not materialize
  fill/event arrays when both wake payload flags are disabled. Keep the
  default wake/audit behavior byte-for-byte compatible.
- Add focused cache-invalidation, immutable-tape, sparse-fast-path, parity,
  and repeated-run RSS tests. Re-run the Phase 46B low/high benchmark in a
  fresh subprocess and retain before/after JSON evidence.

Acceptance:

- Exact Python/Rust audit and scalar parity remains 100%.
- Existing full regression remains green.
- Rust score median returns toward the Phase 46B range, or the measured
  residual cause is documented with no false speed claim.
- Prepared/score RSS does not regress; repeated score RSS remains plateaued.
- No new endpoint argument is required and `auto` remains Python until the
  Phase 46E release gate passes.

Implementation completed and evidence:

- `CompiledOrderCommandArrays` now carries a complete compile-time primitive
  fingerprint covering execution and validation fields. Its arrays are
  read-only after compilation, preventing stale cache identity through
  mutation. Rust score cache hits use the stored digest and avoid rehashing
  the tape.
- `OrderTable` uses a bounded small-book sequence lookup and early tombstone
  compaction; larger live books retain the numeric O(1) ID map. Sparse calls
  with both wake payload flags disabled keep scalar accounting without
  materializing fill/event arrays.
- Focused native tests pass: `16 passed`. The final apples-to-apples evidence
  is [`phase46d1_score_rss.json`](../benchmarks/native_event/phase46d1_score_rss.json):
  `270.3x` low-churn and `175.3x` high-churn Rust/Python score speedup in the
  saved run; scalar/full parity and repeated RSS plateau pass.
- Ownership evidence is in
  [`phase46d1_ownership_r2.json`](../benchmarks/native_event/phase46d1_ownership_r2.json):
  both low/high sparse reset RSS deltas are zero and cache/reset gates pass.
  Prepared incremental RSS was approximately `2.79 MB`/`2.98 MB` in the
  staged score benchmark, so no 20% prepared-RSS reduction is claimed.

### Phase 46E - Python Hot State, Dual Backend Contract, And Release Gate

Status: **implemented on `feat/quantbt-engine-packaging`; dual-backend
behavior, common-result adaptation, parity tests, and the fresh release-gate
evidence are complete.** The native PyPI extra remains intentionally closed
because the explicit prepared-RSS reduction threshold is not met; `auto`
therefore remains Python by policy.

Detailed guide sections:

- Guide sections `10`, `10.1` to `10.3`, `11`, `11.1` to `11.3`, `12`, and
  Patch `F6` plus the first part of Patch `F7`.

Objective:

- Keep Python the full-featured canonical backend while making its static tape
  fallback fair, compact, and explicit.
- Re-run certification under the final dual-backend contract.

Implementation:

- Use primitive active-order state and optional metadata side tables in Python
  score mode, without changing public `OrderCommand` or event types.
- Make context fields such as active orders, event ledgers, fills, margin, and
  positions lazy by score requirements; preserve the full compatibility
  default.
- Define the public/internal selection contract exactly as `python`, `rust`,
  `auto`, and `replay_certified`.
- Keep `python` full reactive/default, `rust` explicit capability-gated,
  `auto` Python for this release, and `replay_certified` the audit oracle.
- Keep the per-bar Rust adapter for debug/correctness only; do not call it a
  performance route.
- Re-run fresh-process benchmarks with identical scalar artifacts and at
  least five repetitions plus 100-run plateau.

Release gate:

```text
full lifecycle/accounting parity          = 100%
low-churn speedup                         >= 1.50x
high-churn speedup                        >= 2.00x
incremental prepared RSS reduction       >= 40%
incremental execution peak reduction     >= 40%
absolute peak RSS                        below declared budget
100-run RSS                              plateau
```

Acceptance and debt:

- A failed RSS gate keeps Rust experimental and leaves `auto` on Python.
- Native feature claims must be generated from the canonical capability
  matrix; no package/docs drift is accepted.

Execution checklist for this phase:

- Preserve `BacktestResultV2` and existing endpoint behavior for `python` and
  public audit/report calls.
- Add explicit backend selection and capability errors for direct Rust use;
  never silently downgrade an explicit `rust` request.
- Certify Rust audit-to-common-result conversion and Python/Rust scalar,
  lifecycle, fills, fees, margin, and report parity.
- Add score-requirement/lazy-state tests and fresh-process dual-backend
  benchmark evidence. Record every release-gate result, including failed RSS
  thresholds, without changing the declared policy.

Implementation completed and evidence:

- Added `native_backend` to `NativeEventConfig`, `EndpointConfig`, and
  `BacktestEngineV2`. The selector is exactly `python`, `rust`, `auto`, or
  `replay_certified`; explicit Rust requests fail fast for unsupported
  multi-symbol, funding, liquidation, and quantity-constraint semantics.
- Added `RustBatchedAuditResult.to_backtest_result(...)`. Rust SoA audit output
  now reaches the common `BacktestResultV2` contract with equity, positions,
  fees, margins, `fills_report`, `order_report`, `Fill` objects, and the normal
  metrics/report/plot helpers. The adapter is outside the scalar score path.
- Python scalar score state now drops non-execution strategy metadata when the
  declared context requirements disable all related payloads. Full audit and
  compatibility defaults retain their existing objects and metadata.
- Added [`docs/native_event_dual_backend_phase46e.md`](../docs/native_event_dual_backend_phase46e.md),
  the endpoint selector documentation, and
  [`tests/native_event/test_phase46e_dual_backend_contract.py`](../tests/native_event/test_phase46e_dual_backend_contract.py).
- The reproducible gate is
  [`benchmarks/native_event/benchmark_phase46e_release_gate.py`](../benchmarks/native_event/benchmark_phase46e_release_gate.py),
  with evidence in
  [`benchmarks/native_event/phase46e_release_gate.json`](../benchmarks/native_event/phase46e_release_gate.json).
  The fresh run passed full parity, low/high speed thresholds (`155.6x` and
  `218.4x`), absolute peak RSS budget (`183.14 MB < 512 MB`), and the 100-run
  RSS plateau. The prepared-RSS reduction was `-28.5%` low churn and `-17.8%`
  high churn, so the required `40%` prepared-RSS gate is honestly recorded as
  failed; no native extra or automatic Rust selection is claimed.
- Focused Phase 46E and prior Rust/Python parity tests pass: `26 passed`.

### Phase 46F - Core PyPI Finalization And Native Release Decision

Status: implemented on `feat/quantbt-engine-packaging`; core release gate
passed locally, native release gate remains intentionally closed.

Detailed guide sections:

- Guide sections `13`, `13.1` to `13.2`, `14`, `14.1` to `14.4`, `15`,
  `15.1` to `15.4`, `16` Patches `F7` to `F9`, and `17`.

Objective:

- Finish the independently installable `quantbt-engine` core release first.
- Only publish `quantbt-native` and expose a non-empty native extra if its
  full parity, RSS, wheel, and fallback gates genuinely pass.

Core PyPI implementation:

- `src/quantbt` remains the distribution source of truth. The root mirror is
  deliberately retained because the repository owner approved a staged
  migration; it is byte-locked by `tests/test_phase45a_source_tree_sync.py`
  and is not included as a second package source in the wheel.
- Aligned `__version__`, `pyproject` version, wheel metadata, and release
  notes at `1.0.7`; added Python 3.11/3.12/3.13 classifiers,
  Documentation/Changelog URLs, and [`CHANGELOG.md`](../CHANGELOG.md).
- Added local package-gate commands to
  [`docs/release_packaging.md`](../docs/release_packaging.md): isolated
  wheel/sdist build, metadata inspection, `twine check`, clean import, and
  dependency-complete `pip check`.
- Added manual `.github/workflows/publish-testpypi.yml` for RC tags with a
  protected `testpypi` environment and OIDC. The production workflow now
  refuses prerelease/draft GitHub Releases and retains the protected `pypi`
  OIDC gate.
- Added package metadata, workflow contract, native-extra, and release-note
  tests in `tests/test_phase46f_packaging_release.py`.
- The root mirror was not deleted; removing it remains a separate, explicitly
  approved migration and is outside this release-finalization scope.

Native release decision:

- Build `quantbt-native` for CPython 3.11, 3.12, and 3.13 on Linux
  manylinux-compatible x86-64 runners, install the wheel with the matching
  core wheel, and run combined parity/fallback/RSS smoke.
- Complete native metadata, README, license inclusion, Cargo.lock, API
  compatibility documentation, and separate distribution/API versioning.
- If every gate passes: publish `quantbt-native` first, verify installation,
  then add `quantbt-engine[native]` and publish the compatible core release.
- If any gate fails: publish only `quantbt-engine`, keep Rust explicit
  experimental, keep `auto=Python`, and leave the native extra empty/absent.

Phase 46E evidence and the Phase 46F fresh rerun confirm the second branch:
Python/Rust parity and score speed thresholds pass. The fresh run measured
`182.2x` low churn and `251.3x` high churn, with absolute peak RSS
`184.11 MB < 512 MB` and a passing 100-run plateau. The prepared RSS
reduction gate fails (`-26.1%` low churn, `-7.6%` high churn), so
`quantbt-native` is not published and `project.optional-dependencies
["native"]` remains empty. This is a deliberate release decision, not an
unresolved correctness claim.

Final definition of done:

- Core `quantbt-engine` clean wheel/sdist install works without optional
  dependencies and `from quantbt import QuantBTEndpoint` is unchanged.
- Pool Alpha compatibility, full tests, source/import checks, and TestPyPI
  RC smoke pass.
- Python remains canonical/full-featured; replay remains the certification
  oracle.
- Rust claims, capabilities, wheel matrix, RSS evidence, and fallback policy
  agree with one source of truth.
- No production release is declared from a failed parity or RSS gate.

Phase 46F local evidence:

- Packaging metadata and workflow tests: pass.
- Core package build toolchain: `build 1.5.0`, `twine 6.2.0`.
- Full regression on the Phase 46F commit: `664 passed, 3 skipped`.
- Root/source parity: pass for the complete mirrored Python tree.
- Native release: intentionally not ready because the prepared RSS gate is
  measured and failed; no automatic Rust selection or non-empty native extra
  is claimed.
- Fresh Phase 46F gate artifact:
  [`benchmarks/native_event/phase46f_release_gate.json`](../benchmarks/native_event/phase46f_release_gate.json).

### Final Upgrade Tracking Rules

- This section is the only active plan for the final dual-backend/PyPI
  upgrade; older Phase42-45 notes remain historical evidence.
- Each agent must first read the linked detailed guide and this section before
  starting a phase, then update the phase status with commit, tests, evidence,
  and remaining debt.
- The scope deliberately stops at the guide's dual-backend/static-tape and
  PyPI release goals. It does not add arbitrary Python-to-Rust compilation,
  portfolio/arbitrage Rust parity, or silent default routing.

## Final Grid Python/Rust Full-Contract Upgrade

Status: **Phases 47A-47C implemented locally; Phase 47D remains planned.**

Detailed source of truth:

- [`quantbt_final_grid_python_rust_full_contract_guide.md`](quantbt_final_grid_python_rust_full_contract_guide.md)

This plan condenses the complete Grid guide into four implementation phases.
The linked guide remains normative; this section is only the execution tracker
and must not replace the detailed code snippets, contracts, or acceptance rules
in that guide.

### Scope and non-negotiable rules

- Work only with the existing Grid module at
  `/root/bobby/pool_alpha/alphas_storage/TA/dynamic_grid_quantbt_native_event.py`.
  Do not copy its source into the QuantBT repository.
- Keep the public endpoints unchanged:
  `QuantBTEndpoint.native_event_strategy(...)` and
  `QuantBTEndpoint.prepare_native_event_strategy(...)`.
- Add only the Grid-side `native_backend` selector and scalar/prepared helpers
  described by the guide. Do not create a Grid-specific endpoint family.
- Preserve the full Grid domain contract: `PLACE`, `AMEND`, `CANCEL`,
  `CANCEL_ALL`, `MARKET`, `LIMIT`, `GTC`, `reduce_only`, OCO entry/exit
  batches, active-order snapshots, per-bar fills, funding, initial and
  maintenance margin, liquidation, and single-symbol lifecycle semantics.
- Do not disable funding, OCO, maintenance margin, liquidation, or lifecycle
  fields to make Rust run. An explicit unsupported Rust capability must raise a
  clear capability error; it must never silently fallback or change semantics.
- Keep Python/replay as the correctness reference until the Rust contract has
  passed the shared conformance suite and both Grid parity workloads.
- Keep the root compatibility mirror during all intermediate phases. Its
  removal is not part of this Grid contract upgrade and requires a separately
  approved packaging migration after clean-install/import verification.
- Do not claim Rust production support, publish a native extra, or route
  `native_backend="auto"` to Rust before all release gates pass.
- Every completed phase must include focused tests, evidence/benchmark output,
  explicit remaining debt, and an immediate commit using the configured
  contributor identity. Do not modify `main`.

### Phase 47A - Grid Adapter, Python Scalar Baseline, And Diagnostic Lock

Status: **implemented locally; Python scalar/public/replay gates pass.**

Detailed guide sections:

- Sections `1` to `7` of
  [`quantbt_final_grid_python_rust_full_contract_guide.md`](quantbt_final_grid_python_rust_full_contract_guide.md):
  source of truth, current Python/Rust status, endpoint policy, Grid config
  forwarding, public-result versus scalar-score separation, notebook import,
  and the three canonical Python paths.
- Sections `16` to `16.2` for the required Python-versus-replay diagnostic
  before any Rust parity claim.

Objective:

- Freeze the actual Grid contract through the existing Python implementation
  and replay-certified oracle before expanding Rust.
- Make the existing Grid alpha selectable through the current endpoint without
  changing its strategy callback, command generation, or accounting behavior.
- Separate public result materialization from the prepared scalar score path.

Implementation:

- Add `native_backend` to the end of the existing `GridExecutionConfig` with
  exactly `python`, `rust`, `auto`, and `replay_certified` validation.
- Forward the selector and the existing reactive/report/audit settings once
  through `build_grid_endpoint`; do not add a new endpoint or alter defaults.
- Add `prepare_grid_score_runner(...)` and `score_grid_params(...)` using
  `NativeEventScoreRequirements.scalar_score_contract()` and a fresh strategy
  instance per evaluation.
- Add the notebook import/version guard from guide section `6`, without
  changing the source module or copying it into QuantBT.
- Define and run the three Python paths exactly as specified:
  replay-certified audit, Python public minimal, and Python scalar v2.
- Add the diagnostic comparison that separates position transitions, fill
  count, entry/exit/flatten fills, fees, funding, and `num_trades`; identify
  the exact first divergent bar/transition before treating any result change
  as an engine bug.

Tests and evidence:

- Python replay-certified versus Python single-pass full lifecycle parity.
- Python public minimal versus replay position/fill/accounting parity.
- Python scalar totals/fingerprint versus the same Python audit run.
- Config forwarding, allowed selector values, default compatibility, fresh
  strategy instances, and no `endpoint.result` materialization in score mode.
- Diagnostic evidence explaining every `num_trades +2` or proving the metric
  counting semantics are the only difference.

Acceptance and possible debt:

- Python must remain correct and unchanged for existing Grid users before Rust
  work begins.
- Scalar mode must not call `full_report()` or retain public ledgers.
- Any unexplained command/fill/position/equity divergence blocks Phase 47B.
- Expected residual debt is Rust capability incompleteness; it must be listed,
  not hidden by disabling Grid features.

Implementation and evidence:

- Updated the existing Grid module only at
  `/root/bobby/pool_alpha/alphas_storage/TA/dynamic_grid_quantbt_native_event.py`;
  the source was imported directly and was not copied into QuantBT.
- `GridExecutionConfig.native_backend` now validates and normalizes exactly
  `python`, `rust`, `auto`, and `replay_certified`, while the existing endpoint
  forwarding remains the only routing change.
- Added `prepare_grid_score_runner(...)` and `score_grid_params(...)`. Each
  score creates a fresh mutable Grid strategy, reuses the prepared market tape,
  uses `NativeEventScoreRequirements.scalar_score_contract()`, and leaves
  `endpoint.result` untouched.
- Added the scalar retention evidence flag
  `score_full_ledgers_materialized=False` to both canonical `src/quantbt` and
  the compatibility mirror; this is metadata only and does not change fills,
  accounting, or execution order.
- Added [`test_phase47a_grid_adapter.py`](../tests/test_phase47a_grid_adapter.py)
  covering selector forwarding, public-result/scalar separation, repeated
  score determinism, reportability, and Python single-pass/replay parity.
- Focused Phase 47A suite: **5 passed**. Related native-event regression:
  **20 passed**. Full repository regression: **669 passed, 3 skipped**.
- Syntax compile and the complete mirrored Python-tree check pass with no
  `src/quantbt` to root-mirror content differences.

Phase 47A completion boundary:

- Python/replay baseline is locked and safe to use as the Phase 47B oracle.
- No Rust Grid claim, no 2,000-bar Grid production parity claim, no RSS
  benchmark claim, and no optimizer speedup claim is made by this phase.
- Existing dirty notebook changes in the external TA repository were left
  untouched; only the Grid module was changed for this phase.

### Phase 47B - Rust Native Event V2 Full Contract And Conformance Suite

Status: **implemented locally; full-contract conformance and focused Rust
regressions pass. Grid workload certification remains Phase 47C.**

Detailed guide sections:

- Sections `8` to `10` of
  [`quantbt_final_grid_python_rust_full_contract_guide.md`](quantbt_final_grid_python_rust_full_contract_guide.md):
  full Rust domain contract, file-level adapter/core design, order table,
  exact bar execution order, and shared conformance tests.

Objective:

- Upgrade Rust from the currently narrower/static scope to the same advertised
  Native Event V2 domain contract used by Python and Grid.
- Make the replay-certified execution order the single lifecycle ordering
  reference; Rust must reproduce it rather than infer a new ordering.

Implementation:

- Extend the Python Rust adapter command ABI for `PLACE`, `CANCEL`,
  `CANCEL_ALL`, `AMEND`, `REPLACE`, order type, TIF, expiry, activation,
  parent/group/OCO IDs, and symbol index.
- Remove hardcoded unsupported behavior only after the Rust core implements
  the corresponding semantics; pass real funding arrays/masks, maintenance
  ratio, quantity constraints, liquidation state, and active-order metadata.
- Split Rust internals into the guide's `types`, `session`, `commands`,
  `order_table`, `matching`, `lifecycle`, `accounting`, and `buffers` roles.
- Implement priority-preserving order slots, ID lookup, parent/group/OCO and
  expiry indexes without `Vec.remove()` priority shifts.
- Copy the oracle's exact bar sequence for mark/PnL, intrabar liquidation,
  funding, after-funding liquidation, expiry, commands, matching, parent/OCO
  lifecycle, after-order liquidation, and state recording.
- Use compact primitive/SoA state at the Rust boundary; preserve public result
  semantics and avoid per-bar Python object materialization in the score path.

Tests and evidence:

- Add the shared `tests/native_event/contract/` matrix and run every fixture
  through replay-certified, Python, and Rust.
- Cover command timing, all command kinds, MARKET/LIMIT/STOP variants,
  GTC/GTD/IOC/FOK, reduce-only, quantity constraints, parent activation,
  group/OCO, funding, margin, liquidation, and multi-symbol behavior declared
  by the capability matrix.
- Compare command tape, effective bars, statuses/reject reasons, fills,
  positions, equity, fee, funding, turnover, margin, liquidation, and final
  state. Discrete fields must be exact; numeric tolerance is only
  `rtol=0, atol=1e-12` where operation order cannot change a decision.
- Add explicit Rust capability/version mismatch tests proving fail-fast
  behavior and no silent fallback.

Acceptance and possible debt:

- No Grid Rust integration is accepted if any full-contract lifecycle or
  accounting field is missing from parity.
- If multi-symbol or another capability is not implemented safely, capability
  metadata must report it as unsupported and Phase 47C must not claim it.
- Rust remains explicit/experimental until the conformance suite is green;
  this phase does not change `auto` routing.

Implementation and evidence:

- Added the versioned Rust API `0.4` full-contract ABI and capability gate.
  The existing R1/R2 API remains readable for compatibility, while explicit
  full execution requires every `native_event_v2_*` capability listed above.
- Added `rust/native_event/src/full.rs` with the compact full session,
  flattened multi-symbol market tape, lifecycle/order table, matching,
  funding, margin, liquidation, quantity-preflight boundary, and SoA audit
  output. Its execution ordering is locked to the Python replay oracle.
- Extended `src/quantbt/backends/_native_event_rust.py` and the compatibility
  mirror for full command compilation, per-symbol reactive batches, funding,
  liquidation, full active-order relationship metadata, event reject codes,
  and `RustFullAuditResult` adaptation to `BacktestResultV2`.
- Corrected two parity defects found by the conformance suite: `REPLACE`
  target aliases now resolve subsequent CANCEL/AMEND commands to the newest
  slot, and replacement no longer emits a spurious cancellation event.
  Quantity preflight also selects constraints by the command's symbol rather
  than always using symbol column zero.
- Added [`test_phase47b_full_contract.py`](../tests/native_event/contract/test_phase47b_full_contract.py).
  It covers multi-symbol funding, parent activation, OCO, TIF/expiry,
  CANCEL_ALL, liquidation, replace aliasing, amend, stop order types,
  reduce-only, per-symbol quantity constraints, active metadata, event
  status, and reject-code parity. Focused result after a release rebuild:
  **9 passed**.
- Updated [`native_event_rust_full_contract.md`](../docs/native_event_rust_full_contract.md)
  and the endpoint/backend documentation. Public endpoint names and defaults
  remain unchanged; `native_backend="rust"` is still explicit and fail-fast,
  while `auto` remains Python.
- Verification after the final Rust rebuild: `cargo check` passed, focused
  Phase 47B/native-event regressions passed **41 tests**, and the complete
  repository regression passed **678 passed, 3 skipped** with the existing
  warning set only.

Phase 47B completion boundary and remaining debt:

- Rust and Python now execute the same tested Native Event V2 contract on the
  synthetic conformance matrix, including full accounting and lifecycle
  metadata. This is a domain-contract lock, not a production performance or
  Grid result claim.
- Phase 47C still must run Grid 2,000-bar long-only and long-short parity,
  scalar-to-audit fingerprint checks, isolated runtime/RSS benchmarks, and
  repeated-run leak checks before any Rust promotion policy can change.
- The full Rust score call currently returns typed Rust equity/position paths
  so common metrics can be computed correctly; it avoids pandas/report-frame
  construction but is not yet the final scalar-only memory optimization.

### Phase 47C - Grid 2,000-Bar Parity, Backend Policy, And RSS Benchmark

Status: **implemented locally; 2,000-bar parity, scalar retention, backend
policy, and isolated RSS/runtime gates pass.**

Detailed guide sections:

- Sections `11` to `15` of
  [`quantbt_final_grid_python_rust_full_contract_guide.md`](quantbt_final_grid_python_rust_full_contract_guide.md):
  2,000-bar data/configuration, parity gate, isolated benchmark process,
  backend policy, and primary Definition of Done.

Objective:

- Prove that Grid itself, not merely synthetic micro-fixtures, produces the
  same lifecycle/accounting result on Python and Rust.
- Establish a fair runtime/RSS evidence bundle without mixing backend-owned
  market representations in one process.

Implementation:

- Run the last 2,000 monotonic, unique bars for both
  `best_params_long_only` and `best_params_long_short`.
- Execute in this order: replay audit, Python audit/minimal, Python scalar v2,
  Rust audit, Rust scalar. Never reuse a strategy instance between runs.
- Compare full command/fill/position/equity/fee/funding/margin/liquidation
  parity; certify scalar paths using audit fingerprints plus scalar totals,
  never only Sharpe, final equity, or fill count.
- Add `benchmarks/native_event/benchmark_grid_2000.py` with isolated child
  processes, one warm-up, five measured runs, median runtime, CPU time,
  peak/post-run RSS, and parity fingerprint.
- Add repeated-run RSS plateau evidence and keep the accepted approximately
  180 MB baseline rule: no regression beyond the guide's 10–15% allowance,
  no linear leak, and no false 40% reduction requirement.
- Make backend selection policy explicit: Python full/default, Rust explicit
  capability-gated, replay oracle, and `auto` Rust only after all certification
  and wheel/version checks pass.

Tests and evidence:

- Long-only and long-short Grid 2,000-bar parity tests.
- Python/Rust scalar-to-audit fingerprint and totals parity.
- Fresh-process low/high churn and repeated-run memory tests.
- Explicit Rust unsupported capability and no-silent-fallback tests.
- Benchmark JSON must record commit, module version, backend, fixture,
  fingerprints, parity status, runtime medians, RSS checkpoints, and gate
  results.

Implementation and evidence:

- Added [`test_phase47c_grid_parity.py`](../tests/test_phase47c_grid_parity.py).
  It imports the external Grid module read-only, generates a deterministic
  sorted/unique 2,000-bar OHLCV fixture, and runs both `long_only` and
  `long_short` through replay-certified, Python, and explicit Rust audit paths.
  It compares command tape, event ledger, fill ledger, positions, equity,
  fees, funding, margin, liquidation, and lifecycle counters. Result:
  **3 passed** after the Rust scalar retention patch.
- Completed Rust reactive scalar retention: when the prepared runner receives
  `scalar_score_contract()`, the Rust adapter uses the same online score state
  as Python and does not allocate dense equity/position/fee/funding/margin
  paths or retain full ledgers. Both Python and Rust now return
  `NativeEventScalarScoreResult`; the public audit path remains unchanged.
- Added [`benchmark_grid_2000.py`](../benchmarks/native_event/benchmark_grid_2000.py).
  It accepts optional OHLCV CSV/CSV.GZ input, otherwise uses the deterministic
  fixture, runs one warm-up plus five measurements in one backend-owned
  process, records median/p95 wall time, CPU time, peak/post RSS, repeated-run
  RSS slope, and a SHA-256 audit fingerprint. `gc.collect()` is performed
  between retained runs so Python allocator high-water behavior is not falsely
  classified as a live-object leak.
- Added the runbook [`grid_native_event_phase47c.md`](../docs/grid_native_event_phase47c.md)
  and linked it from the documentation map and endpoint guide. It records the
  public endpoint contract, scalar/audit separation, policy, fingerprint
  evidence, and the exact benchmark commands.
- Full audit runs produced identical fingerprints for all three backends in
  both Grid modes. Long-only terminal equity is `28972.788456089613` with
  `839` fills; long-short terminal equity is `20457.971765918566` with `107`
  fills. Scalar totals match the same-backend audit for equity, positions,
  fees, funding, fills, rejects, cancels, and liquidation.
- The final five-run benchmark evidence on commit `54525d3` (synthetic 2,000
  bars) shows Python scalar medians of `1.138s` long-only and `1.846s`
  long-short; Rust scalar medians of `1.245s` and `1.985s`. Rust remains a correctness
  and explicit experimental backend here; this workload does not claim Rust
  is faster than the Python reactive score facade.
- Audit process RSS stayed bounded under the repeated-run tail-slope gate
  after explicit collection. Rust and Python retained different
  allocator/high-water profiles, so RSS is reported as evidence, not a
  universal hardware claim. The observed full Grid facade peaks are about
  `265.6-293.4 MB`; the guide's approximately `180 MB` reference is from a
  different native-event process profile, so this phase does not claim an
  apples-to-apples absolute no-regression result against that number.

Acceptance and possible debt:

- Rust is not promoted or selected by `auto` unless every required gate passes.
- Any RSS failure is reported separately from correctness; it cannot relax
  accounting or lifecycle parity.
- If a real Grid workload exposes a contract gap, freeze the result as a
  reproducible failing fixture and keep Rust explicit until repaired.

Phase 47C completion boundary and remaining debt:

- The Grid integration now has an executable 2,000-bar correctness gate for
  both supported modes, a low-retention Python/Rust score contract, and a
  reproducible process-isolated RSS/runtime benchmark. The repeated-run
  plateau gate passes, while an apples-to-apples pre-Phase47C Grid RSS
  baseline remains required before claiming an absolute RSS regression
  improvement. `native_backend="rust"` is explicit and fail-fast; `auto`
  still resolves to Python.
- The canonical parity surface intentionally excludes the diagnostic
  `filled_command_count` aggregate because replay counts filled command
  states while reactive sessions count fill records. The exact command/event/
  fill ledgers and accounting paths are compared instead; this naming
  difference is documented and not used to hide a lifecycle mismatch.
- Phase 47D remains open for optimizer root-cause profiling, optional Grid
  alpha preparation caching, and safe diagnostics-off patches. This phase
  does not claim Rust promotion, portfolio/arbitrage/options parity, L2 depth,
  or venue-specific cross-margin certification.

### Phase 47D - Optimizer Root-Cause, Safe Hot-Path Patches, And Final Certification

Status: **implemented locally; optimizer gate, parity, and RSS certification pass.**

Detailed guide sections:

- Sections `17` to `22` of
  [`quantbt_final_grid_python_rust_full_contract_guide.md`](quantbt_final_grid_python_rust_full_contract_guide.md):
  optimizer bottleneck analysis, scalar-path gate, single-trial profiling,
  safe Grid optimizer patches, performance acceptance, and supplemental
  Definition of Done.

Objective:

- Improve optimizer throughput only after proving that it uses the prepared
  scalar evaluator and that every optimization change preserves domain
  behavior.
- Explain whether remaining wall time is alpha preparation, strategy callback,
  engine score, objective/reporting, or Optuna overhead rather than blaming the
  backend generically.

Implementation:

- Added `benchmarks/native_event/profile_grid_optimizer_trial.py` to separate
  alpha preparation, strategy construction, prepared engine score, public
  objective/report work, fill count, and `num_trades`. The apples-to-apples
  prepared scalar path measured `0.813s` on the local 2,000-bar five-repeat
  profile after the patch.
- The scalar gate is enforced by the external Grid helper: `scores` increments
  exactly once, `runs` does not increment, `endpoint.result is None`, and the
  score path materializes no public result.
- Added the minimal Grid context declaration and changed
  `score_grid_params(...)` to derive `NativeEventScoreRequirements` with
  `from_strategy(...)`; fills, active orders, and positions remain enabled.
- Added optional `GridExecutionConfig.collect_diagnostics=True`. The score
  helper forces a fresh diagnostics-off policy, avoids all `_diag_*` arrays,
  and keeps public/audit behavior unchanged.
- Made `long_entry_*`, `long_exit_*`, `short_entry_*`, and `short_exit_*`
  aliases optional. Canonical execution columns are parity-tested and remain
  present in scalar mode.
- Did not add `PreparedGridAlphaFactory`: profiling showed alpha preparation
  was only about `2.2%`, while the reactive engine callback was about `97.9%`;
  a bounded indicator cache would add state complexity
  without addressing the measured bottleneck.
- Updated the Grid endpoint/docs and recorded the external adapter patch as
  commit `fda46c3` in the separate `alphas_storage` repository.

Tests and evidence:

- Added `tests/test_phase47d_grid_optimizer.py` for context requirements,
  alias parity, diagnostics retention, scalar gate, public-accounting parity,
  and the explicit diagnostics-off report guard.
- Focused Grid suite passes **13 tests** when combined with Phase 47A/47C
  (Phase 47C Rust tests remain environment-gated if the extension is absent).
- Re-ran the 2,000-bar Python/Rust scalar benchmark in isolated processes:
  long-only `0.850s`/`1.086s`, long-short `1.412s`/`1.831s`; fingerprint,
  terminal accounting, and repeated RSS tail gates pass. Peak RSS was
  `265.4/271.2 MB` long-only and `291.0/293.6 MB` long-short.
- The public/audit default remains diagnostic-enabled; no public lifecycle,
  command, fill, fee, funding, margin, liquidation, or report contract was
  relaxed. The detailed evidence is in
  [`docs/grid_native_event_phase47c.md`](../docs/grid_native_event_phase47c.md).

Final acceptance and explicit non-goals:

- Python single-pass matches replay-certified lifecycle.
- The `num_trades +2` discrepancy is explained by exact transitions/fills or
  corrected metric semantics; it is never hidden with tolerance.
- Prepared scalar evaluator is actually used and does not materialize public
  results.
- Score-mode diagnostics are optional and do not alter domain decisions.
- Rust full contract, both Grid 2,000-bar modes, scalar paths, RSS plateau,
  explicit failure policy, and benchmark evidence all pass.
- This phase does not add a new endpoint, copy the Grid source into QuantBT,
  claim portfolio/arbitrage/options Rust parity, or delete the root mirror.

### Final Grid Upgrade Tracking Rules

- Before every Phase 47 implementation, read this section and the linked
  detailed guide in full; the guide's code snippets and exact contracts take
  precedence over a shortened summary here.
- Mark each phase only after its focused tests and the full regression pass,
  record the commit and evidence paths, then state remaining debt explicitly.
- The phrase “Rust Grid supported” is reserved for a pass of the complete
  Native Event V2 conformance suite plus both 2,000-bar parity workloads.
- Until that point, Python remains canonical, replay remains the oracle, Rust
  remains explicit experimental, and `auto` remains Python.

## Final Release Audit Upgrade: Six-Phase Plan

Status: **planned; implementation awaits approval.**

This release pass follows the complete guide:

[`quantbt_final_release_native_event_endpoint_packaging_audit.md`](quantbt_final_release_native_event_endpoint_packaging_audit.md)

The guide is the detailed source of truth. The phase summaries below are
tracking boundaries only; every implementation must read the linked sections
and execute the exact contracts, examples, and gates described there.

### Release baseline and non-negotiable policy

Current baseline before this plan:

```text
core distribution: quantbt-engine 1.0.7
import package: quantbt
native API: 0.4
Python/replay/Rust: Phase 47 domain evidence available
backend="auto": Python
native extra: empty until public native wheels are certified
src/quantbt: wheel source of truth
root mirror: intentionally retained for Pool Alpha/local development
```

Release priority remains:

```text
domain correctness
→ replay-certified parity
→ stable public endpoint
→ no runtime/RSS regression
→ clean artifacts and TestPyPI
```

No phase may:

- change command timing, fill priority, funding, margin, liquidation, or
  accounting semantics to obtain a benchmark result;
- silently fallback when `backend="rust"` is explicit;
- remove the root compatibility mirror before two-way parity and migration
  evidence pass;
- claim a public dual backend while `quantbt-engine[native]` is empty or
  `quantbt-native` wheels do not install from a clean public index;
- publish to TestPyPI/PyPI without the exact-SHA release gate and user approval.

The final acceptance target is not a fixed speedup ratio. It is exact lifecycle
parity, no unexplained runtime regression, no RSS regression above the guide's
10–15% tolerance, no positive repeated-run RSS slope, and no trial-proportional
retention. The accepted benchmark scope remains separate for static/batched
Rust and arbitrary Python reactive strategies.

### Phase 48A - P0 Release Surfaces, API 0.4 CI, And Stale Documentation

Status: **implemented and locally certified**.

Detailed guide sections:

- Sections `1`, `2.1`, `2.2`, `2.3`, `8.1` to `8.4`.
- Patch `1` and the native workflow examples in the guide.

Objective:

Close the blockers that would make CI or documentation contradict the actual
Native Event API 0.4 implementation before touching optimization or release
publishing.

Implementation scope:

- Update native CI assertions from API `0.3` to API `0.4`.
- Assert the complete required capability set:
  `native_event_v2_full_contract`, multisymbol, funding, liquidation,
  cancel-all/OCO, TIF expiry, relationships, and quantity preflight.
- Rename stale R0 workflow/job terminology to the current Native Event API
  0.4 terminology; no compatibility redirect is needed for workflow names.
- Add the clean combined core/native install smoke specified in Section 2.1,
  but keep the public native wheel matrix gate in Phase 48E.
- Update `docs/release_packaging.md` from the obsolete R1/R2 restrictions to
  the API 0.4 contract, explicit Rust fail-fast policy, and `auto=Python`
  policy. Keep historical R0/R1/R2 material only under a clearly labelled
  history section.
- Align native package metadata, API version wording, project URLs, and
  distribution-version/API-version distinction. Never reuse an uploaded
  version.

Tests and evidence:

- Native workflow API/capability smoke on the exact commit.
- Existing full Native Event conformance suite and Grid long-only/long-short
  integration tests.
- Documentation consistency scan for stale API `0.3`, R0/R1/R2 restrictions,
  and claims that Rust is the default backend.
- Record the exact workflow file, job names, capability keys, and release
  metadata in the phase report.

Exit gate:

```text
CI checks API 0.4
required capabilities are present
release docs match implementation
no execution logic changed
```

Phase 48A evidence:

- `.github/workflows/native.yml` is now the Native Event API 0.4 workflow. Its
  smoke gate asserts `_quantbt_native.api_version() == "0.4"` and all eight
  required capability keys, including full contract, multisymbol, funding,
  liquidation, cancel-all/OCO, TIF expiry, relationships, and quantity
  preflight.
- Native metadata is aligned at distribution version `0.4.0` in Cargo,
  maturin metadata, and the exported native version constant. The Python
  distribution remains `quantbt-engine 1.0.7`; the distribution version and
  native API version remain separate contracts.
- `docs/release_packaging.md` now describes the current API 0.4 contract,
  explicit Rust failure policy, and `auto=Python` policy. R0/R1/R2 text is
  retained only as historical scaffold material.
- The core wheel and native wheel were built and installed together into an
  isolated target directory. The smoke imported `quantbt` from that target,
  verified native version `0.4.0`, API `0.4`, and all required capabilities.
  Both wheels passed `twine check`.
- Focused regression: `87 passed, 2 skipped`. Rust checks passed with
  `cargo fmt --check`, `cargo clippy --all-targets --all-features --
  -D warnings`, and `cargo test --release`.
- The host does not provide `uv`, `python3-venv`, or a network-independent
  clean virtualenv bootstrap. The combined wheel smoke therefore used the
  repository Poetry Python with a fresh `pip --target` install; the CI clean
  install workflow remains the authoritative isolated-environment gate.
- No execution semantics changed. The Rust source adjustments outside version
  metadata are formatting and explicit dead-code annotations required by the
  strict lint gate.

### Phase 48B - Two-Way Mirror, Git Hygiene, Secret Safety, And Artifact Allowlist

Status: **implemented and locally certified**.

Detailed guide sections:

- Sections `2.4`, `7.1` to `7.7`, and the mirror code block in Section 2.4.
- Patch `2` and the artifact inspection commands in Section 7.7.

Objective:

Make the open-source repository auditable without deleting the root mirror or
mistaking private/local artifacts for package source.

Implementation scope:

- Add the explicit mirror manifest and two-way byte/hash test. It must detect
  both missing files in the root mirror and extra root-only Python files.
- Add `tools/sync_source_mirror.py` with explicit, non-automatic directions:
  `--src-to-root`, `--root-to-src`, and `--check`. Never merge both trees
  automatically.
- Keep `src/quantbt` as wheel source of truth and the root mirror as a
  compatibility source until migration is explicitly completed.
- Replace blanket `.gitignore` rules for `upgrade/` and `benchmarks/` with
  selective private/local/cache/build rules from Section 7.3.
- Keep tracked implementation plans, tests, docs, deterministic fixtures,
  benchmark scripts, accepted summaries, and small JSON evidence visible.
- Add the `implement.md` presence/non-ignored CI gate.
- Add the release secret scan and review documented false positives.
- Add explicit wheel/sdist artifact inspection and an allowlist/denylist gate;
  secrets must never be protected only by `MANIFEST.in` after entering Git.
- Add or align `MANIFEST.in` only for sdist content control, with private data,
  credentials, profiler output, and local artifacts excluded.

Tests and evidence:

- Two-way mirror test and sync-tool check mode.
- `git ls-files --error-unmatch upgrade/implement.md` and check-ignore gate.
- Secret-path scan and manual review record.
- Wheel/sdist listing plus suspicious-path rejection fixture.
- Full regression after `.gitignore`, manifest, and tooling changes.

Exit gate:

```text
src/root trees are byte-identical over the explicit manifest
implement.md remains visible
private files remain ignored
accepted benchmark evidence remains trackable
wheel/sdist contain no suspicious private paths
```

Phase 48B evidence:

- `tools/source_mirror_manifest.py` defines the allowlisted compatibility
  surface. The current manifest-listed root/source Python mirror is byte-identical;
  `src/quantbt/benchmarks` and root benchmark scripts are intentionally not
  mirror entries, so benchmark/tool files cannot be confused with package
  compatibility source.
- `tools/sync_source_mirror.py` supports only explicit `--src-to-root`,
  `--root-to-src`, or `--check` directions. It never merges both trees and
  never deletes an unknown root-only file. Extra, missing, or drifted files
  stop the command with a reviewable report.
- `.gitignore` no longer blankets `upgrade/` or `benchmarks/`. Public plans,
  tests, docs, tools, benchmark scripts, and accepted evidence remain visible;
  only private planning, local benchmark output, caches, credentials, local
  data, and build/profiling artifacts are ignored.
- CI, TestPyPI, and PyPI workflows now require tracked/non-ignored
  `upgrade/implement.md`, run `tools/scan_public_secrets.py`, and inspect
  built artifacts with `tools/check_release_artifacts.py` before upload.
  Generic documentation terms are excluded from the high-confidence scanner;
  actual credential-shaped matches still fail for manual review.
- `MANIFEST.in` controls sdist content and excludes private/local paths and
  credential extensions. The core wheel allowlist is `quantbt/**` plus its
  own dist-info metadata; a suspicious-path fixture is rejected by tests.
- Focused Phase 48B hygiene checks: **8 passed**; the compatibility/release
  bundle with prior source-tree and CI packaging locks passed **15 passed**.
  Coverage includes mirror parity, extra/missing/drift detection, check mode,
  visibility, secret scanning, workflow gates, and artifact rejection. Built
  `quantbt-engine 1.0.7` wheel/sdist passed `twine check` and the artifact gate.

### Phase 48C - Stable Event-Driven Facade And Strategy Protocol

Status: **implemented and locally certified**.

Detailed guide sections:

- Sections `3.1` to `3.6` and `9`.
- Patch `3` and all stable usage examples in Section 3.4.

Objective:

Stop endpoint surface drift while preserving every existing constructor and
execution behavior. The new facade is a configuration resolver, not a second
execution engine.

Implementation scope:

- Add `NativeEventProfile` values `research`, `optimize`, and `audit`.
- Add canonical `QuantBTEndpoint.event_driven(...)` with the small public
  surface:

  ```python
  event_driven(
      input_mode="strategy",  # strategy | orders
      profile="research",      # research | optimize | audit
      backend="auto",          # auto | python | rust
      ...,
  )
  ```

- Delegate `input_mode="strategy"` to the existing
  `native_event_strategy(...)` path and `input_mode="orders"` to the existing
  `native_event_lifecycle(...)` path. Do not duplicate matching/accounting.
- Resolve profiles exactly as the guide specifies:
  `research=fast/single_pass/minimal/none`,
  `optimize=fast/single_pass/score/none`,
  `audit=audit/replay_certified/audit/memory`.
- Map public `backend` to internal `native_backend`; do not expose
  `replay_certified` as a language backend in this facade.
- Raise on contradictory profile-controlled low-level options instead of
  silently overriding them. Keep the advanced legacy constructors available
  for custom combinations and backward compatibility.
- Document one `NativeEventStrategy` protocol for stateful reactive alphas:
  `initialize`, `on_bar_close`, `finalize`, and declared context requirements.
- Document the three input levels: target/signal, explicit order tape, and
  stateful reactive strategy. Grid remains a strategy-level integration, not a
  Grid-specific endpoint.
- Add a concise README quick start and move low-level flags into advanced docs.

Tests and evidence:

- Profile mapping tests for research/optimize/audit.
- Strategy and explicit-order delegation parity against existing endpoints.
- Conflict validation tests.
- Backward compatibility tests for
  `native_event_strategy`, `native_event_lifecycle`, and `orders`.
- Grid 2,000-bar fingerprint/accounting parity through the new facade.
- Public result API smoke: `simulate`, `show_metrics`, `full_report`,
  `quick_plot`/tearsheet where applicable.

Exit gate:

```text
new facade changes configuration only
existing endpoint snippets remain valid
no domain behavior changes
new users need profile/backend, not internal lifecycle flags
```

Phase 48C evidence:

- `QuantBTEndpoint.event_driven(...)` is the stable public resolver for both
  `input_mode="strategy"` and `input_mode="orders"`. It delegates to the
  existing `native_event_strategy(...)` and `native_event_lifecycle(...)`
  constructors, so no second matcher, fill engine, or accounting path was
  introduced.
- `NativeEventProfile` exposes only `research`, `optimize`, and `audit`. Their
  exact mappings are `fast/single_pass/minimal/none`,
  `fast/single_pass/score/none`, and `audit/replay_certified/audit/memory`.
  The public `backend` selector is limited to `auto`, `python`, and `rust`;
  `replay_certified` remains an advanced internal kernel selector.
- Profile-controlled low-level values raise an explicit conflict error rather
  than being silently overwritten. Existing low-level constructors remain
  available for advanced combinations and backward compatibility.
- `NativeEventStrategy` is exported as a runtime-checkable structural protocol
  for `initialize`, `on_bar_close`, and `finalize`; the existing duck-typed
  `NativeEventStrategyProtocol` remains compatible with older strategies.
- Focused facade/profile/delegation tests pass, including accounting equality
  against direct native-event strategy and lifecycle endpoints. README and
  `docs/endpoint.md` now document the stable declaration, profiles, input
  modes, strategy responsibilities, backend release policy, and escape hatch.
- Added `benchmarks/benchmark_phase48c_event_driven.py`, which runs direct and
  facade routes in fresh processes on the fixed 2,000-bar baseline and reports
  the external reactive Grid separately. The latest five-run evidence records
  common throughput of `12,407` versus `12,942` bars/s and Grid throughput of
  `1,410` versus `1,430` bars/s; facade/direct fingerprints and accounting are
  identical in both cases.
- The source mirror was synchronized with `tools/sync_source_mirror.py` and
  `--check` passes. Focused Phase 48C and compatibility tests pass **22/22**;
  full regression passes **704 passed, 3 skipped** with no failures.

### Phase 48D - Rust Full-Session Ownership, Output Requirements, And Indexed Lifecycle

Detailed guide sections:

- Sections `5.1` to `5.8`, including P1–P6.
- Optimization order `O1` to `O3` in Section 5.17.

Objective:

Reduce full-contract Rust allocation/RSS overhead without changing the
replay-certified lifecycle. This is the main native performance phase and must
be implemented as individually testable patches, not one broad rewrite.

Implementation scope, in order:

1. Share immutable prepared market data with `Arc<FullMarketData>`; sessions
   own only mutable account/lifecycle state and never clone OHLCV/funding tape.
2. Replace the growing historical order vector with a stable-priority arena,
   free list, generation-safe slot references, and bounded tombstone
   compaction. Preserve active insertion priority and relationship references.
3. Add relationship/expiry indexes for parent activation, OCO cancellation,
   GTD expiry, group filters, and active-only `CANCEL_ALL`. Index lookup must
   preserve replay event order.
4. Add internal `FullOutputRequirements` for score, reactive-context, and audit
   output. Keep the old full `step()` behavior as a compatibility wrapper.
5. Replace nested per-step vectors with reusable SoA buffers; clear without
   shrinking on every bar and expose explicit excess-capacity release.
6. Add typed frozen PyO3 step/sparse chunk result classes while retaining
   dictionary conversion only at backward-compatible public boundaries.

Every subpatch must preserve:

```text
command effective bar and priority
accept/reject and reason
parent/group/OCO/expiry lifecycle
fills and prices
funding
margin/liquidation ordering
positions/equity/fees/turnover
```

Tests and evidence after each subpatch:

- Replay-certified → Python single-pass → Rust exact conformance.
- All actions/order types/TIF/quantity constraints/reduce-only/relationships.
- Single- and multi-symbol, funding, margin and liquidation.
- Stable priority after arena slot reuse and compaction.
- 100k terminal-order retention fixture and active-only scan evidence.
- Prepared market shared by two sessions; reset cannot mutate the tape.
- Output requirement combinations and old `step()` compatibility.
- SoA capacity/release counters and typed result field parity.
- Grid long-only/long-short parity after every patch.
- Repeated 100-run RSS plateau and high-churn benchmark.

Exit gate:

```text
exact discrete lifecycle parity
numeric parity at documented tolerance
no prepared-market duplication in full sessions
no historical-order retention proportional to terminal orders
RSS/runtime improvement or neutral result
no Rust fallback or API drift
```

### Pre-Phase 48E - Apples-To-Apples Native Event Performance Pass

Detailed guide: [`quantbt_final_grid_python_rust_full_contract_guide.md`](./quantbt_final_grid_python_rust_full_contract_guide.md), sections `# QuantBT pre-48E`, `pre-48E.A` through `pre-48E.F`, and acceptance sections `8` and `9`.

Status: **complete**. The accepted evidence is frozen before Phase 48E.

Objective: establish a current, reproducible performance baseline and apply only
domain-preserving zero-work optimizations to the native event Python/Rust paths.
Historical Phase 43 numbers are reference-only; all accepted numbers must use
the same commit, machine, tape, contract, and process-isolated runner.

Scope and execution order:

1. **Baseline freeze (`pre-48E.A`)**
   - Add `benchmarks/native_event/benchmark_pre48e.py`.
   - Use one deterministic `2,000`-bar single-symbol tape for comparable
     native-event/common reporting and the same command tape for Python/Rust.
   - Measure explicit lifecycle orders and generic `native_event_strategy` in
     separate cases; run `score` and `audit` separately.
   - Separate cold preparation/first execution from warm execution. Use a fresh
     subprocess per route, `7` measured warm runs, median, p95, CPU time,
     `VmHWM`/peak RSS, post-prepare RSS, and post-run RSS.
   - Record bars, commands, events, fills, active-order peak, commit SHA,
     Python/NumPy/Numba/Rust API versions, backend resolution and contract.
   - Save JSON/Markdown under `benchmarks/native_event/results/pre48e/`.

2. **Python safe fast paths (`pre-48E.B`)**
   - Cache quantity-constraint enablement at session construction.
   - Skip retime, quantization and schedule allocation for empty command batches.
   - Preserve all preflight behavior for `PLACE`/`REPLACE` when constraints are
     enabled; do not change timestamp, next-bar, rejection, fill or accounting
     semantics.
   - Expose execution counters for bars, commands, retime/quantize calls,
     contexts, snapshots and constraint preflight so speed claims are auditable.

3. **Score/audit separation (`pre-48E.C`)**
   - Keep score output scalar/minimal and audit output full. Do not create audit
     ledger objects in score mode merely to discard them later.
   - Preserve the existing public result surface and undeclared-strategy
     compatibility. Any strategy context requirement remains explicit.

4. **Rust bridge/allocation evidence (`pre-48E.D`)**
   - Benchmark the existing prepared Rust full-tape score/audit contract with
     the identical compiled tape. Do not claim Rust parity where the extension
     capability gate rejects a feature.
   - Report PyO3 call count, prepared-market reuse, command-buffer reuse and
     allocation/copy counters where available. No silent Python fallback for an
     explicit Rust route.

5. **Lifecycle and Grid evidence (`pre-48E.E`)**
   - Run high-churn explicit lifecycle and Grid smoke/parity separately.
   - Grid/reactive results are written to this plan only; they are not merged
     into the README native-event throughput headline.

6. **Freeze accepted result (`pre-48E.F`)**
   - Save before/after artifacts, exact fingerprints, parity tolerances and
     remaining hotspots. Required parity covers effective commands, lifecycle
     status/rejection, fills, positions, fees, funding, turnover, margin,
     liquidation and final equity.

Acceptance gates:

```text
Python/replay/Rust exact lifecycle parity on the supported contract
score/audit parity and prepared/non-prepared parity
no changed fill, rejection, fee, funding, margin or liquidation behavior
no RSS regression >10-15%; repeated-run RSS remains bounded
same 2,000-bar contract and s/ms formatting in the README benchmark table
explicit Rust remains fail-fast when its capability contract is unavailable
```

Deliverables:

- benchmark script, JSON and Markdown evidence;
- focused parity/counter tests;
- README native-event benchmark table only for the common native-event routes;
- Grid/reactive evidence and remaining hotspots in this implementation plan;
- a committed pre-48E result before entering Phase 48E.

#### Pre-48E evidence and close-out

The gate was executed with `benchmarks/native_event/benchmark_pre48e.py` using
the required deterministic 2,000-bar, one-symbol tape, fresh subprocesses,
seven warm runs, separate score/audit routes, and the same compiled command
tape for Python and Rust. The complete before/after evidence is in
[`benchmarks/native_event/results/pre48e/report.md`](../benchmarks/native_event/results/pre48e/report.md);
the machine-readable artifacts are `baseline.json` and `after.json` in the
same directory.

All eight required parity groups passed:

```text
common_low/high_churn     x score/audit       PASS
explicit_low/high_churn   x score/audit       PASS
numeric accounting        atol <= 1e-12       PASS
discrete lifecycle fields  exact               PASS
```

The fingerprint covers effective accounting outputs, positions, fees,
funding, margin, fill rows, final equity, and fill/event/rejection/cancellation
counters. The Python safe-path patch removed empty-batch retime/quantize work
and retained quantity preflight whenever constraints are enabled. The common
Python score route improved from `0.148483s` to `0.087736s` on the frozen
workload (`13,470` to `22,796` bars/s); common Python audit improved from
`0.166945s` to `0.087327s` (`11,980` to `22,902` bars/s). Rust used the prepared
full-tape bridge and stayed parity-locked; its common score route moved from
`0.232064s` to `0.188448s`. Explicit Rust score remained the fastest measured
route at `0.000964s` (`2,075,635` bars/s) for the low-churn tape. Short explicit
high-churn score runs varied slightly and are intentionally not presented as a
universal speed claim.

Peak RSS is reported alongside every route. The Python common audit path fell
from `316.3MB` in the old warm baseline to `240.8MB` after the patch; other RSS
changes remain within normal process/import noise and no route exceeded the
accepted regression envelope. No accounting, preflight, fill, rejection,
funding, margin, or liquidation work was removed for the speed result.

Reactive evidence was measured separately with the existing
`benchmarks/benchmark_phase48c_event_driven.py`, also on 2,000 bars. Direct
Grid and `event_driven(profile="audit")` both produced `839` fills and final
equity `28,972.788456`, with parity **PASS**. The measured Grid facade overhead
was `+2.04%` (`1.146060s` direct vs `1.169473s` facade); peak RSS was about
`274.5MB` for both routes. This result stays in the plan and is deliberately
excluded from the README common native-event throughput headline.

Pre-48E remaining hotspots, carried into Phase 48E, are Python context/timestamp
boxing and higher-level WFO/service loops, PyO3/context bridge cost on generic
callbacks, audit report construction, and deeper RSS retention analysis. These
are optimization candidates only after the same parity contract continues to
pass. The pre-phase does not certify Rust as the default reactive Grid backend.

### Phase 48E - Python Context/Command Reuse, Dual Backend Wheels, And Native Certification

Detailed guide sections:

- Sections `5.9` to `5.16`, `8.4` to `8.5`, and `6.3` to `6.4`.
- Optimization `O4` and `O5` in Section 5.17.
- Native wheel matrix in Section 2.2.
- The deeper implementation and release evidence is also governed by
  [`quantbt_final_release_native_event_endpoint_packaging_audit.md`](./quantbt_final_release_native_event_endpoint_packaging_audit.md),
  sections `5.2` to `5.18` and `O1` to `O5`. That guide is normative for
  ownership, output profiles, cache/reset behavior, RSS evidence, and the
  PyO3/maturin release boundary.

Objective:

Finish the Python↔Rust boundary and certify a real public native distribution
before considering a non-empty `[native]` extra.

Status: **implemented; local gates pass, public wheel matrix remains a CI/release gate**.
The source contract, local CPython 3.12 extension, parity suite, cache/reset
suite, and 2,000-bar benchmark pass. CPython 3.11/3.13 manylinux wheels are
generated by the committed workflow and still require a successful CI run
before `quantbt-native` can be advertised or added to `[native]`.

Implementation scope:

- Add a reusable full-contract Python command buffer with one canonical ABI
  layout, capacity growth counters, and no per-bar `zeros/full` allocation.
- Reuse the Python context container and materialize fills, events,
  active-order snapshots, positions, margin, and metadata only when required.
- Thread the same context requirements into the Rust full-contract projection
  mask. Accounting and live positions remain mandatory; fills, lifecycle
  events, and active-order snapshots are omitted from the PyO3 payload when
  neither the strategy nor the audit contract requests them.
- Compact terminal Rust order records conservatively after lifecycle work,
  preserving insertion order and all `REPLACE` aliases. This bounds long Grid
  tapes without changing fill, cancellation, OCO, or replacement semantics.
- Add active-order generation caching and bounded metadata behavior while
  preserving full compatibility for undeclared strategies and audit profiles.
- Remove duplicate Python retention through separate prepared Python/Rust
  market ownership; `backend="rust"` must release temporary normalized arrays
  when safe, while `auto` must not eagerly prepare both backends.
- Add exact session reset, `clear_caches()`, `cache_info()`, capacity counters,
  and 100-run reset/fresh-session parity.
- Apply GIL policy from the guide: detach long Rust-only tape/chunk calls;
  benchmark, but do not automatically detach very short per-bar reactive
  callbacks.
- Add portable Rust release profile (`opt-level=3`, thin LTO, one codegen
  unit, stripped symbols, no `target-cpu=native`, no panic-abort shortcut).
- Split the large Python adapter only after behavior/performance stabilizes,
  preserving all re-exports and isolating legacy API 0.3 compatibility from
  API 0.4 full/ batched modules.
- Add observability counters for bars, commands, fills/events, active peaks,
  slots/compactions, snapshots, copies, GIL calls, cache bytes/entries.
- Build native wheels for CPython `3.11`, `3.12`, `3.13`, Linux x86_64
  manylinux2014/`manylinux_2_17` using maturin/PyO3 CI. Do not publish a
  locally built Ubuntu-only wheel as public artifact.
- Clean-install each native wheel together with the core wheel, run API and
  capability smoke, full Rust contract, Python/replay/Rust parity, Grid
  integration, and `pip check`.
- Align native package metadata (`quantbt-native`, preferred `0.4.0`) with API
  version and project URLs. If no native wheel is published, keep
  `quantbt-engine[native]` empty and label Rust local/experimental.

Tests and evidence:

- Python context/command buffer parity and memory counter tests.
- Fresh-vs-reset session exact fingerprint parity.
- 100 repeated runs plateau with bounded capacities and no retained trial
  result/strategy.
- Cargo fmt, clippy `-D warnings`, release cargo tests.
- CPython 3.11/3.12/3.13 manylinux wheel install matrix.
- Combined core+native clean install, API `0.4`, required capability keys,
  contract suite, Grid smoke, and `pip check` for every wheel.
- Static tape speed evidence remains separate from reactive facade evidence;
  no universal Rust speed claim is made.

#### Phase 48E close-out evidence

Focused Phase 48E tests are in
[`tests/native_event/test_phase48e_reuse.py`](../tests/native_event/test_phase48e_reuse.py)
and cover reusable command storage, exact reset/cache reuse, context projection
masking, and long-tape terminal compaction parity. The native-event suite is
`75 passed, 2 skipped` with the local API `0.4` extension; the Phase 48E
focused suite is `4 passed`. Cargo `fmt`, Clippy with `-D warnings`, release
tests, and release build pass.

The apples-to-apples 2,000-bar evidence is frozen in
[`benchmarks/native_event/results/phase48e/after.md`](../benchmarks/native_event/results/phase48e/after.md)
and `after.json`. All eight Python/Rust score/audit groups pass exact lifecycle
fingerprints and numeric accounting at `atol <= 1e-12`. Common callback Rust
remains slower than the optimized Python callback path on this workload; the
Rust advantage is confined to the explicit prepared full-tape route. This is
why `auto` remains Python. The benchmark also records bounded command-tape
cache bytes, one PyO3 static call, output requirements, and RSS separately.

Local PyO3 execution used the repository Rust toolchain and a CPython 3.12
extension built with the portable release profile. The committed
`.github/workflows/native.yml` is the authoritative CPython `3.11/3.12/3.13`
manylinux/maturin matrix. Until that matrix and clean combined-wheel install
pass in CI, the native extra stays empty and the native package remains
experimental rather than a public performance/certification claim.

Exit gate:

```text
native wheels install on every supported Python target
API/capabilities are 0.4 and complete
full parity and RSS plateau pass per wheel
explicit Rust is fail-fast
auto remains Python for 1.0.7
[native] is populated only if the public install is real
```

### Phase 48E.1 - Native Production Closure Before 48F

**Status: implemented locally; CI wheel gate pending.** This is a required closure phase between Phase 48E and
Phase 48F. The normative implementation guide is
[`quantbt_final_grid_python_rust_full_contract_guide.md`](quantbt_final_grid_python_rust_full_contract_guide.md),
section `QuantBT Phase 48E.1 - Native Production Closure Before 48F`, including
P0-P7, patch order `48E.1-A` through `48E.1-G`, the mandatory test matrix, and
the acceptance gate. That guide is authoritative; this section tracks the
actual repository work and evidence.

#### Scope and non-regression contract

- Complete Rust conditional output allocation, not only PyO3 payload omission.
- Use one lifecycle implementation with count-only and collecting sinks.
- Replace nested per-row hot-path projections with reusable Rust-owned SoA
  buffers. Score must not materialize audit rows; audit converts once at the
  boundary. No unsafe borrowed NumPy views.
- Preserve the public command ABI (`i64/f64`, 16/3 full command arrays), public
  endpoint, timing, fee, funding, margin, liquidation, parent/OCO/TIF and
  quantity semantics.
- Add validated compact internal enums/flags, immutable market storage and a
  typed PyO3 scalar step result without changing the legacy `step()` surface.
- Make `command_report`, `order_report`, `fills_report` and `order_events`
  distinct, with command metadata enrichment performed once at the Python
  audit boundary. Rust score/research/audit profiles must have explicit
  retention semantics.
- Harden existing compaction/reset relationships and isolate API 0.4 full
  capability routing from legacy adapters. Explicit `backend="rust"` must
  fail fast when its capability contract is unavailable; no silent fallback.

#### Tracked implementation order

1. `48E.1-A`: freeze current parity, report schema, RSS/runtime and counters.
2. `48E.1-B`: implement `StepCounters`/`DetailSink` and prove score allocation
   suppression with exact Python/oracle parity.
3. `48E.1-C`: implement reusable `FillBuffer`, `EventBuffer`,
   `ActiveOrderBuffer`, typed step payload and adapter projection tests.
4. `48E.1-D`: compact validated internal types/flags and fixed market arrays;
   run Rust format, clippy and release tests without ABI changes.
5. `48E.1-E`: close report semantics, command metadata, full-report parity and
   export bundle tests.
6. `48E.1-F`: cover replacement aliases, waiting parent/child, OCO, GTD,
   priority, multi-symbol and fresh/reset parity; run 100-run memory plateau.
7. `48E.1-G`: build/install CPython 3.11/3.12/3.13 manylinux wheels in CI,
   clean-install core plus native, run capability/full-contract/Grid/report/
     `pip check` and RSS gates. Local Ubuntu wheels are not public evidence.

#### Required tests and evidence

- All command actions, order types, GTC/GTD/IOC/FOK, quantity constraints,
  reduce-only, parent/group/OCO, funding, margin and liquidation paths.
- Every valid output-mask combination: counts, positions, fills, events,
  active orders, mixed projections and full audit; accounting/lifecycle must
  remain identical.
- Python/Rust/oracle parity at `atol <= 1e-12` for accounting and exact
  discrete lifecycle parity, including report schema/value parity.
- Score buffers do not grow, audit buffers reuse capacity, reset is equivalent
  to a fresh session, prepared market is shared, and 100 runs have bounded RSS.
- Isolated low/high-churn explicit, generic callback and Grid benchmarks with
  CPU time, median/p95, VmHWM, RSS, capacity growth, PyO3 calls, returned bytes,
  compactions and margin recomputes. No speed claim may hide missing domain
  work, and no unexplained regression over 10-15% is accepted.

#### Exit gate

Phase 48E.1 is complete only when R3/R4 allocation counters, typed/result and
report contracts, parity, compaction/reset, bounded RSS and the installed-wheel
matrix pass. Any unavailable wheel target or report/correctness blocker keeps
this phase open; Phase 48F remains limited to artifact/TestPyPI/release work.

#### Phase 48E.1 implementation and local evidence

Implemented in the Rust full-contract core and both Python mirrors:

- `StepCounters`/`DetailSink` is the single lifecycle output path. Score uses
  count-only mode, so fills/events/active rows are not materialized or allocated
  before the PyO3 boundary.
- Reusable `FillBuffer`, `EventBuffer`, `ActiveOrderBuffer` SoA storage is
  cleared without shrinking. Static audit consumes those columns directly;
  compatibility/reactive projections materialize rows only when requested.
- API 0.4 `FullStepResultCore` provides typed scalar fields and optional
  projection fields. The old dictionary `step()` method remains intact.
- Rust internal order state now validates side/order-type/TIF at the boundary,
  stores symbol/side/type/TIF/activation in compact representations and packs
  reduce-only into a flag. Public command IDs and the 16/3 ABI remain `i64/f64`.
- Market and fixed account arrays use boxed immutable storage behind the shared
  `Arc<FullMarketData>` ownership. Existing compaction/reset behavior is kept;
  relationship coverage includes replacement aliases, parent/OCO/GTD paths.
- Per-bar margin valuation is cached safely. The first close-margin lookup scans
  the symbol set once; accepted fills update only the changed symbol's initial
  and maintenance contribution in O(1), while liquidation invalidates the
  cache. `margin_recompute_count` is observable through `cache_info()` and is
  covered by parity/plateau tests; formulas and post-cost margin gates are
  unchanged.
- Rust audit now exposes independent command-intent, lifecycle order and fill
  reports. Fill metadata is enriched from the immutable command side table;
  `command_report` is never an alias of `order_report`.
- Explicit Rust capability selection includes quantity-preflight capability and
  continues to fail fast; no silent Python fallback was introduced.

Focused evidence:

```text
tests/native_event/test_phase48e1_closure.py       4 passed
tests/native_event suite                            79 passed, 2 skipped
cargo fmt / clippy -D warnings / cargo test --release PASS
margin recomputes are bounded to at most one per bar on the 100-run
score/reset fixture
```

The isolated 2,000-bar rerun is in
[`benchmarks/native_event/results/phase48e1/after.md`](../benchmarks/native_event/results/phase48e1/after.md)
and `after.json`. All eight score/audit Python/Rust parity groups pass exact
fingerprints and `atol <= 1e-12`. Common callback measurements remain a
separate facade result (Python is faster on this tape); explicit prepared Rust
score reaches `6.92M bars/s` low churn and `5.46M bars/s` high churn, while
explicit Rust audit reaches `459K` and `309K bars/s`. Explicit Rust audit RSS
is about `182-183 MB`, versus Python audit about `238-240 MB`; common score RSS
is about `182-186 MB` and common audit about `239-242 MB`. The benchmark also
records one margin recompute per bar for the explicit score/audit sessions,
with fill updates handled by the O(1) cache delta path.

The local clean wheel smoke was run on CPython 3.12 with API `0.4` and
`pip check`. The committed `.github/workflows/native.yml` is the authoritative
CPython 3.11/3.12/3.13 manylinux/maturin gate and now runs the Phase 48E.1
closure tests. Since this host does not contain CPython 3.11/3.13, those two
installed-wheel jobs remain CI evidence rather than being claimed as local
passes. The native extra therefore remains empty and `auto` remains Python
until the public matrix passes.

### Phase 48F - TestPyPI Artifact Gate, Release Workflow, And Final Handoff

**Status: `1.0.7rc1` was blocked before publication by a stale lockfile;
`1.0.7rc2` passed TestPyPI artifact and functional endpoint smoke, and
`release/1.0.7` is being finalized for production review.** The
implementation follows the packaging/release sections linked from the guide;
no tag, merge, or publish action was triggered from this branch.

Detailed guide sections:

- Sections `8.2`, `8.3`, `7.7`, `9`, `10`, `11`, and `12`.
- Patches `6` and `7`.

Objective:

Prove that the exact release artifacts install and behave correctly in clean
environments, then prepare a controlled TestPyPI RC. Public PyPI release is a
separate user-approved action after the RC is inspected.

Implementation scope:

- Add clean wheel and sdist install steps to `publish-testpypi.yml` before
  upload. Install the exact built artifacts, run isolated import smoke, and
  run `pip check` for both paths.
- Keep production publishing release-only: exact tag/version gate, GitHub
  Release trigger, protected PyPI environment, OIDC trusted publishing, and
  no normal `dev`/`main` push upload.
- Build to a clean directory and run `twine check`.
- Inspect wheel/sdist contents against the allowlist; fail on credentials,
  private data, profiler output, `.env`, `.pypirc`, key material, or private
  planning paths.
- Run the complete local gate from Section 11: clean tree/diff check, `uv
  sync`, full pytest, native tests, cargo fmt/clippy/test, build, wheel/sdist
  smoke, and artifact scan.
- Update README/docs so the quick start uses stable `event_driven(profile,
  backend)` and phase details remain in engineering evidence docs.
- Verify Pool Alpha/local editable-path usage and a clean wheel import in
  separate environments; ensure package import resolves from `site-packages`.
- Produce the TestPyPI RC checklist containing exact SHA, version, artifact
  hashes, test results, wheel matrix, parity fingerprints, RSS results, and
  known policy (`auto=Python`, native extra state).
- Add `tools/create_release_manifest.py` for deterministic artifact SHA256,
  commit/ref, version, benchmark-evidence and backend-policy recording. The
  manifest is uploaded separately from the publishable wheel/sdist files.
- Extend `tools/check_release_artifacts.py` to inspect archive members and
  small file contents, rejecting secret-like content, private/local data,
  profiler/compiler output and unsafe paths while allowing the public
  `quantbt/benchmarks` Python package.
- Keep the source mirror and local editable workflow unchanged; the wheel is
  still built only from `src/quantbt` and the root mirror is not copied into
  the distribution.
- Do not publish PyPI or merge branches in this implementation phase without
  explicit approval. The guide's public order remains: native first if real,
  then populate `[native]`, then core release, otherwise release Python-first
  with native clearly experimental.

Tests and evidence:

- `uv run pytest -q`, Native Event tests, source mirror tests.
- `cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test --release`.
- `uv build`, `twine check`, wheel clean install, sdist clean install, and
  `pip check`.
- TestPyPI workflow dry-run/build validation and exact artifact install.
- Secret scan, package-path allowlist, version/tag/ref consistency, and
  `quantbt.__file__` site-packages check.
- Final report must classify:
  `domain correctness`, `Python performance/RSS`, `Rust performance/RSS`,
  `endpoint usability`, `core PyPI`, and `public dual-backend installation`
  separately, exactly as Section 12 does.

Local Phase 48F evidence:

```text
tests/test_phase48f_release_gate.py and release regressions  20 passed
full repository regression                                   720 passed, 3 skipped
native-event regression                                     79 passed, 2 skipped
twine check wheel + sdist                                   PASS
archive allowlist/secret scan                               PASS
wheel target import from /tmp                               PASS
sdist target import from /tmp                               PASS
manifest version/hash/backend policy                         PASS
```

The reproducible local artifact manifest records the exact `1.0.7` wheel and
sdist hashes, the release commit SHA/ref, and the current policy `auto=Python`,
`native extra=empty`, explicit Rust experimental. The GitHub workflows recreate
this manifest after checkout so its SHA always identifies the exact release
artifact commit. They additionally run the dependency-complete fresh-venv
`pip check` and CPython 3.11/3.12/3.13 matrix; those hosted jobs are the final
multi-interpreter evidence because this VPS has only CPython 3.12 and no
system `python3-venv` package.

Exit gate:

```text
exact release SHA is green
wheel and sdist are clean-installable
artifact contents are safe
TestPyPI RC is reproducible once the workflow is run with the matching RC tag
endpoint quick start is stable
native extra claim matches actual public wheels
```

#### Final release decision boundary

The six phases are complete only when Phase 48F has produced a reproducible
TestPyPI-ready artifact bundle. At that point:

```text
core Python package: publishable after user approval
Rust reactive correctness: certified for Native Event V2 tested matrix
Rust static/batched performance: report separately
backend="auto": Python for 1.0.7 unless policy is explicitly changed
native extra: empty unless quantbt-native wheels passed public clean install
```

The plan deliberately does not promise further raw benchmark gains before
TestPyPI. Any future native DSL, portfolio/arbitrage/options native backend,
or deeper reactive callback optimization must be a new parity-first upgrade
after this release gate rather than being mixed into the packaging release.

---

## Phase 49 - Per-Fold Walk-Forward Schedules And Retraining Audit

**Status: Phase 49A and 49B completed on `feat/wfengine_v2`.
The compatible `global` schedule is unchanged by default.**

### Why This Phase Exists

The existing multi-fold WFO lifecycle builds every fold, runs one Optuna study
over the aggregate of their train windows, selects one global parameter set,
then stitches all OOS outputs. The existing Mode 4 selector is IS-only at the
trial/candidate level, but later train windows contain periods that were OOS
for earlier folds. Therefore the current global lifecycle is appropriate for
retrospective global-parameter calibration, not a strict historical causal
retraining claim for the earliest OOS folds.

This roadmap adds explicit *schedules*, not a sixth mixed objective mode:

```python
optimization_mode="mode_4_is_only_robust"
optimization_schedule="per_fold_causal"
```

and, for the existing Mode 1 decay research workflow:

```python
optimization_mode="mode_1_decay"
optimization_schedule="per_fold_decay"
```

`optimization_mode` continues to mean *how candidates are scored/selected*.
`optimization_schedule` means *when a fresh parameter search is allowed*.
This keeps the five existing modes stable and makes the lifecycle visible to
notebooks, services, and audit consumers.

Authoritative current-code references before implementation:

- `walkforward.py::WalkForwardEngine.run`, `optimize_params`,
  `evaluate_params_is`, and `stitch_oos_outputs`;
- `endpoint.py::_run_walk_forward`, which routes one stitched OOS target tape
  through the normal account engine exactly once;
- `docs/` WFO methodology and `docs/endpoint.md` for public contract updates.

### Public Contract To Add

Add one optional, backward-compatible parameter to both
`QuantBTEndpoint.walk_forward(...)` and
`QuantBTEndpoint.train_test_split(...)`, and to `WalkForwardConfig`:

```python
optimization_schedule: str = "global"
```

Allowed values:

| Value | Meaning | Historical causality claim |
|---|---|---|
| `global` | Current behavior: one study and one parameter set across all folds. | No causal multi-fold claim; retrospective global calibration. |
| `per_fold_decay` | One independent study per chronological outer fold. Mode 1 retains its existing two-stage IS-candidate then same-fold OOS-decay selection. | Fold-local decay calibration; the selected candidate has seen that fold's OOS metrics, so this is not an untouched-OOS or causal deployment claim. |
| `per_fold_causal` | Chronologically optimize on each fold's own train window, freeze that fold's params, then emit only its next OOS window. | Strict fold-local retraining, subject to a causal strategy implementation. |

The existing default remains `global`; no current notebook, endpoint call, or
stored result may change merely because this feature is added.

The Phase 49 initial scope deliberately has two distinct protocols that must
never be conflated:

- `mode_1_decay + per_fold_decay` is the requested fold-local version of the
  current Mode 1 workflow. It deliberately evaluates selected IS candidates
  on the current fold's OOS segment to measure decay and choose the fold's
  candidate. It is useful for regime-by-regime parameter robustness research,
  but the stitched result is **selection-adjusted OOS**, not a strict causal
  validation claim.
- `mode_4_is_only_robust + per_fold_causal` is the direct strict selector.
  Each outer fold chooses parameters solely from that fold's train window
  using IS temporal/plateau robustness, freezes them, and only then emits the
  next OOS segment.

Initial compatibility is intentionally narrow:

| `optimization_mode` | `global` | `per_fold_decay` | `per_fold_causal` |
|---|---:|---:|---:|
| `mode_1_decay` | supported, existing behavior | supported, same-fold OOS decay selection | future nested-validation extension; raise for now |
| `mode_4_is_only_robust` | supported, existing behavior | not needed in initial scope; raise | supported, strict IS-only selection |
| `mode_2_sbb`, `mode_3_flat_minima`, `mode_5_full_robust` | existing behavior | raise | raise |

Mode 5 must reject both per-fold schedules because it explicitly treats the
supplied history as full-sample calibration. Modes 2 and 3 remain `global`
until a separate, explicit schedule contract and tests exist; unsupported
combinations must raise rather than fall back to `global`.

### Mode 1 Per-Fold Decay Selection

For an outer chronological fold \(i\), let \(D_i\) be its train history and
\(T_i\) its immediately following OOS window. For example, a split may yield
\(D_i =\) 2020--2021, \(T_i =\) 2021--2022, followed chronologically by a new
independent study for the next fold. Boundary ownership must be explicit and
non-overlapping: a timestamp belongs to exactly one side of a fold.

The study for fold \(i\) reuses the current Mode 1 two-stage implementation
without changing its objective semantics:

1. Run the configured `optuna_trials` only against \(D_i\)'s IS score.
2. Rank completed trials by that IS objective and form the existing top-IS
   candidate set \(C_i\), using `top_is_fraction` or `top_is_k`.
3. For each unique \(\theta \in C_i\), run the strategy on both \(D_i\) and
   \(T_i\), then calculate the existing Mode 1 metrics:

\[
 d_i(\theta) = S(D_i; \theta) - S(T_i; \theta)
\]

\[
 J_i(\theta) = S(T_i; \theta)
 - \lambda\,\operatorname{std}(d_i)
 - \gamma\,\max(0, d_i(\theta))
\]

For one train/OOS pair, \(\operatorname{std}(d_i) = 0\); it remains in the
formula and metadata so the per-fold record is mathematically identical to the
current Mode 1 record shape and can be compared with global multi-fold Mode 1.
The chosen \(\theta_i^\star = \arg\max_{\theta\in C_i} J_i(\theta)\) then
generates the stored output for \(T_i\). Only after this fold is complete may
the engine create a new, independent Optuna study for fold \(i+1\).

This is intentionally **not** strict causal WFO: \(T_i\) is used in candidate
selection. The value of this schedule is isolation: the study for fold \(i\)
cannot see later folds, later regimes, or their OOS metrics, unlike the current
single global study. It should be labelled fold-local decay calibration or
selection-adjusted OOS in research and stakeholder reports.

### Deferred Strict Causal Mode 1 Extension

Strict `mode_1_decay + per_fold_causal` remains a future, separately certified
extension. It requires nested inner train/validation folds wholly contained in
\(D_i\), then records outer \(T_i\) decay only after the parameters are frozen.
It is explicitly out of the first Phase 49 implementation so neither its
heavier compute cost nor its causality claim is hidden behind `per_fold_decay`.

When implemented later, the public surface must make its inner schedule
explicit rather than silently reuse an outer rolling window:

```python
optimization_mode="mode_1_decay"
optimization_schedule="per_fold_causal"
inner_split_frequency="quarterly"
inner_window_mode="rolling"
inner_train_window="180D"
inner_min_folds=2
```

Until that extension exists, this exact combination must raise an actionable
`NotImplementedError`; it must never silently substitute `per_fold_decay`.

The schedule also adds an explicit boundary policy:

```python
fold_boundary_position_policy: str = "carry"
```

`carry` is the only planned default. It does not fabricate a close/reopen at a
retraining boundary: the final account run receives the actual stitched target
series and trades only its normal target delta. A future explicit `flatten`
policy may be added only with dedicated domain tests; it is not implied by
retraining.

### Phase 49A - Per-Fold Study Core, Decay Protocol, And Audit Contract

**Status: completed on `feat/wfengine_v2`.**

Goal:

Implement independent chronological studies for `per_fold_decay` and
`per_fold_causal` without changing `global` behavior or Mode 1 mathematics.

Scope:

- Extend `WalkForwardConfig`, endpoint factories, validation, compatibility
  matrix, and public docstrings with `optimization_schedule="global"`.
- For both supported per-fold schedules, iterate folds chronologically. For
  each fold:
  1. create an independent deterministic Optuna study using only
     `fold.train_index`;
  2. run the existing trial sampling, duplicate handling, seed, early-stop,
     IS scoring, top-candidate, and selection helpers within that fold only;
  3. select according to the declared schedule/mode contract;
  4. invoke the strategy to emit only `fold.test_index` output;
  5. append that output and immutable selection ledger to the chronological
     OOS tape.
- Derive reproducible fold seeds from the configured base seed and `fold_id`;
  no fold may share mutable Optuna state with a later fold.
- For `mode_1_decay + per_fold_decay`, preserve current two-stage behavior
  exactly inside every outer fold: all trials are ranked on fold IS; only the
  unique top-IS candidates run on that same fold's OOS; `robust_decay` then
  selects the candidate. Store the candidate IS/OOS/decay rows, but classify
  the result as `fold_local_decay_calibration`, with
  `outer_oos_used_for_selection=True`.
- For the strict Mode 4 path, prohibit OOS candidate scoring before selection.
  The candidate ledger is IS-only; OOS metrics are recorded only for the one
  previously selected, frozen parameter set as a post-selection realization.
- Reject `mode_1_decay + per_fold_causal` until its nested inner-validation
  extension is implemented. Do not substitute current fold OOS, a full-sample
  selector, or `global` behavior.
- Preserve strategy context: IS scoring may expose data only through the train
  end; OOS execution may expose data through that fold's test end. QuantBT
  cannot prove that user strategy code is causal internally, so this contract
  and requirement must be documented.
- Reuse existing `stitch_oos_outputs(...)`; do not concatenate per-fold equity
  curves or reset capital. The final target tape must continue to route once
  into `_run_single`, portfolio, basket, or arbitrage as currently supported.
- Keep `WalkForwardResult.params` backward-compatible and add unambiguous
  schedule-specific fields rather than pretending all folds used one params
  dictionary.

Required audit metadata:

```text
optimization_schedule
causality_claim
oos_used_for_selection
params_by_fold
fold_selection_table
selection_data_start / selection_data_end
test_start / test_end
fold_seed
selected_trial_id
selected_is_objective
candidate_count
fold_boundary_position_policy

# Required for Mode 1 per_fold_decay
candidate_is_metric / candidate_oos_metric / candidate_decay
outer_oos_used_for_selection
selection_adjustment_note
```

For `global`, add a truthful metadata classification such as
`retrospective_global_calibration`; preserve all existing values for backward
compatibility. For `per_fold_decay`, emit `fold_local_decay_calibration`,
`oos_used_for_selection=True`, and a no-untouched-OOS validation claim. For
`per_fold_causal`, emit `strict_fold_local_retraining` and
`oos_used_for_selection=False`.

Phase 49A tests:

- deterministic two-regime mock: earlier and later folds select different
  expected params from their own train data;
- Mode 1 per-fold decay: assert the study's raw trial rows are IS-only, only
  top-IS candidates receive same-fold OOS metrics, and the selected candidate
  is the maximum existing `robust_decay` objective within that fold;
- Mode 1 perturbation: changing a fold's OOS may change only that fold's
  candidate selection and output; it must not alter any prior fold's study,
  params, or output, and it must be reported as OOS-used-for-selection;
- Mode 4 per-fold causal: assert each fold Optuna/candidate record has no OOS
  metric/decay during selection and uses only its train window;
- causal Mode 1 raises `NotImplementedError` rather than reading outer OOS or
  falling back to `global`;
- append-future **prefix invariance**: adding future bars must not change
  params or OOS output of already completed folds;
- exact parity for current `optimization_schedule="global"` behavior;
- single `train_test_split` parity: Mode 1 `per_fold_decay` retains current
  two-stage selection within the declared train/test pair; Mode 4
  `per_fold_causal` retains strict train-only selection;
- invalid schedule/mode combinations raise actionable errors.

Implemented evidence:

- Added the optional endpoint/config fields `optimization_schedule` and
  `fold_boundary_position_policy` while retaining `global` and `carry` as the
  compatible defaults.
- Added independent deterministic studies and fold-local ledgers for
  `mode_1_decay + per_fold_decay`; the implementation reuses the existing
  IS-search -> top-IS candidate -> OOS `robust_decay` selector exactly inside
  each fold.
- Added strict IS-only selection for
  `mode_4_is_only_robust + per_fold_causal`; only the frozen selected params
  receive one post-selection outer OOS realization.
- Per-fold strategy calls receive data physically truncated at `train_end` or
  `test_end`. The global path retains its historical data-passing behavior.
- Added `params_by_fold`, `fold_selection_table`, `fold_boundary_table`, study
  seeds, selection claims, params semantics and one-pass account metadata.
- Added Series, DataFrame/multi-symbol, prefix-invariance, single holdout,
  schedule rejection, global parity and direct-account parity tests in
  `tests/test_phase49a_walkforward_schedules.py`.
- Updated endpoint docs, public README and both WFO methodology documents.
- Root/source package mirrors remain byte-identical for modified Python files.
- Verification gate: `731 passed, 3 skipped`; skips are existing optional
  backend-dependent tests, with no Phase 49A failure.

### Phase 49B - Prepared WFO Context, Scalar Scoring, And Performance Certification

**Status: completed on `feat/wfengine_v2` (2026-08-09). Phase 49A remained the correctness oracle.**

Goal:

Reduce the cost per trial and bound RSS systematically across `global`,
`per_fold_decay`, and `per_fold_causal` without changing selected params,
objective values, stitched targets, boundary behavior, or final accounting.

Scope:

- Profile one representative real WFO/service workload before changing code.
  Report strategy generation, market normalization, scoring/account kernel,
  Optuna orchestration, ledger/report construction, cold compile, warm runtime
  and peak RSS separately.
- Introduce a run-local immutable `PreparedWalkForwardContext` (exact public or
  internal name may follow existing prepared-context conventions) containing:
  canonical aligned index/OHLCV/funding arrays, integer fold slices,
  scoring/account config, market signature and backend-prepared state.
- Normalize and prepare market inputs once. Fold/train/test evaluators must use
  validated views/slices instead of repeated pandas alignment and ndarray
  packing. Cache keys/signatures must include all result-affecting market and
  account fields; no mutable global cache is allowed.
- Reuse the existing prepared native-vectorized and native-portfolio scoring
  paths. Extend only through parity-first typed interfaces; do not create a
  second scoring formula or a WFO-only accounting implementation.
- Add scalar-only trial scoring: each trial retains only objective inputs,
  params, trade-count constraint fields and compact audit identifiers. Full
  result/report construction is deferred to selected/top candidates and the
  final stitched backtest.
- Keep strategy output caching conservative. QuantBT may cache immutable market
  preparation and fold definitions, but must not cache arbitrary strategy
  signals/indicators unless a future explicit deterministic strategy-prepare
  protocol owns the signature and lifecycle.
- Process fold studies sequentially by default and release fold-local Optuna
  objects after compact ledgers are extracted. `n_trials` and early stopping
  remain per-fold for per-fold schedules and must be labelled as such.
- Preserve the Phase 49A one-pass account contract and deepen boundary tests
  for flat, reversal, size change, fee, slippage, funding and margin paths.

Phase 49B tests and gates:

- exact prepared/non-prepared parity for sampled params, selected params,
  objective values, candidate order, trial status and per-fold seeds;
- exact stitched target and final account parity for signal-notional,
  `%_equity`, native portfolio and currently supported package routes;
- one target held across a boundary: zero extra turnover/fee; flat/reversal/
  size-change boundaries: exact normal target delta and costs;
- prepared context mutation/signature tests, timezone/alignment tests and no
  cross-run cache contamination;
- cold/warm benchmark on the same bars, folds, trials, candidate count and
  strategy implementation; never compare one global study with many per-fold
  studies as if they performed equal mathematical work;
- peak RSS measured in isolated child processes. Memory must remain bounded by
  prepared market state plus compact trial ledgers, not retained per-trial
  backtest/report objects;
- full WFO/endpoint regression suite and realistic multi-fold alpha smoke.

Release condition:

```text
global behavior remains parity-locked;
both per-fold schedules pass completed-fold prefix invariance;
per_fold_decay is explicitly labelled selection-adjusted and has no
cross-fold future observation;
no OOS candidate metric influences per_fold_causal Mode 4 selection;
prepared and reference paths are domain-identical;
one-pass account parity and boundary-cost tests pass;
benchmark artifacts separate mathematical work from framework overhead;
docs expose performance lifecycle and calibration-vs-validation scope.
```

Non-goals for this roadmap:

- proving arbitrary user strategy code free of internal indicator look-ahead;
- automatic intrabar/order-level state transfer between separate strategy
  objects; this roadmap transfers target positions through the existing final
  account engine;
- changing the five existing objective semantics or silently upgrading current
  `global` WFO notebooks.

Phase 49B completion evidence:

- Added run-local `PreparedWalkForwardContext` with full content/config/fold
  signatures, integer causal slices, timezone normalization, mutation checks and
  no cross-run global cache.
- Added array-first scalar score contracts to native vectorized and native
  portfolio backends. They execute the same sizing/accounting kernels and call
  the shared `compute_performance_metrics`; public report construction is
  skipped only for optimizer trials.
- Added exact-index signal packing fast paths and compact completed-trial
  ledgers. The selected trial retains full fold metrics and all public trial /
  candidate tables remain stable.
- Preserved strategy execution per trial. No arbitrary indicator/signal cache
  was introduced.
- Added optional `profile_walkforward=True` timing evidence plus context/scorer/
  ledger metadata. Compatible defaults are prepared context, scalar scoring and
  compact ledgers; each can be disabled independently for reference replay.
- Added direct scalar/public report parity, prepared/reference WFO parity,
  content mutation, timezone, run-local isolation, single-symbol, `%_equity`,
  portfolio and Phase 49A schedule regression tests in
  `tests/test_phase49b_wfo_performance.py`.
- Committed benchmark artifacts:
  `benchmarks/phase49b_wfo_performance.{json,md}`. At 1,000 bars, portfolio
  global improved from `0.386s` to `0.330s` (`1.17x`), while six-study Mode 4
  per-fold causal improved from `4.051s` to `1.781s` (`2.27x`). Equity,
  positions, params, best trial, trial order and candidate order matched exactly.
- Warm isolated peak RSS remained a plateau (`-0.14%` to `+0.05%`, below a
  material regression threshold), so Phase 49B makes no unsupported memory
  reduction claim. Memory remains bounded by market/kernel state plus compact
  ledgers rather than retained per-trial public reports.

---

## Phase 50 - Strict Mode 1 Causal Retraining And WFO Release Closure

**Status: completed on `feat/wfengine_v2`; release target `1.0.8`.**

This closure addresses the WFO debt that cannot be hidden behind the existing
`per_fold_decay` label. It adds a strict causal route for Mode 1 without
changing the default `global` lifecycle, Mode 1 decay mathematics, or the
already-certified Mode 4 per-fold causal route.

Detailed implementation rules for this closure remain in this section and the
existing Phase 49 contract above. Every implementation change must preserve the
root/source mirror and pass reference/prepared parity before it is released.

### Phase 50A - Nested Mode 1 Causal Selection And Audit Contract

Goal: support:

```python
optimization_mode="mode_1_decay"
optimization_schedule="per_fold_causal"
```

without allowing an outer OOS bar to influence parameter selection.

For every outer fold \(D_i, T_i\):

1. Build chronological inner folds entirely inside \(D_i\), using explicit
   `inner_split_frequency`, `inner_window_mode`, `inner_train_window`, and
   `inner_min_folds` inputs.
2. Run one independent Optuna study on those inner folds. Mode 1 keeps its
   existing IS search, top-IS candidate set, and decay objective, but every
   inner OOS used by `robust_decay` is a subset of \(D_i\).
3. Freeze the selected parameters, generate exactly one target output for
   outer \(T_i\), then record outer OOS metrics as post-selection realization
   only.
4. Stitch outer targets and run the normal account engine once with
   `fold_boundary_position_policy="carry"`.

Required safeguards:

- The outer test index must never be passed to Optuna, candidate evaluation, or
  inner-fold construction.
- Insufficient inner history/folds must raise an actionable `ValueError`; no
  fallback to `per_fold_decay`, global selection, or a synthetic inner OOS.
- Store `inner_*` configuration, `inner_fold_table`, inner/outer selection
  boundaries, seed, and explicit `outer_oos_used_for_selection=False` in the
  audit ledger.
- Keep `mode_1_decay + per_fold_decay` explicitly selection-adjusted and
  preserve Mode 4 `per_fold_causal` behavior byte-for-byte at the public
  result boundary.

### Phase 50B - WFO Metadata, Test Sharding, And 1.0.8 Gate

Goal: make the WFO contract unambiguous to notebook, service, and release
consumers, then certify it under bounded host RSS.

Scope:

- Add a separate chronological-validation metadata field for global WFO so a
  consumer cannot mistake `validation_claim="walk_forward_oos"` for a causal
  multi-fold deployment claim. Preserve legacy fields for compatibility.
- Document the complete mode/schedule matrix, inner Mode 1 contract, and the
  distinction between `selection_adjusted_oos`, strict outer OOS, and Mode 5
  full-sample calibration.
- Add a repository test-shard runner that invokes isolated pytest processes;
  it must preserve existing test selection while releasing Numba/pandas memory
  between shards. It is a release-test harness, not a production runtime path.
- Add deterministic tests for nested-fold boundaries, outer-OOS exclusion,
  append-future prefix invariance, malformed/insufficient inner configurations,
  prepared/reference parity, target carry accounting, and root/source mirror
  identity.
- Run the WFO suite and the full release suite through isolated shards, then
  record the exact command and result before the `1.0.8` version bump.

Completion evidence:

- Phase 50A nested-causal checks pass: outer-OOS exclusion, inner-boundary
  audit, append-future prefix invariance, insufficient-history fail-closed
  behavior, prepared/reference accounting parity, and global metadata
  compatibility.
- `poetry run python tools/run_test_shards.py --profile release
  --max-files-per-shard 8` completed **16 isolated shards: 745 passed,
  3 skipped, exit 0**. `test_real.py` and `test_real_endpoints.py` remain
  intentionally excluded because they require local Pool Alpha data.
- The runner launches each shard in a fresh interpreter, preventing Numba,
  pandas, and plotting imports from accumulating RSS across the suite. It is a
  verification harness only; product execution and endpoint semantics are
  unchanged.
- Wheel/sdist smoke commands use a unique `mktemp -d` working directory rather
  than bare `/tmp`, preventing an unrelated local `quantbt/` directory from
  shadowing the installed artifact on `sys.path`.
- Fresh `1.0.8` artifacts built from `src/quantbt` passed strict `twine check`,
  archive allowlist/secret scan, matching `v1.0.8` version gate, `pip check`,
  and independent wheel/sdist imports from `site-packages` in clean managed
  virtual environments.
- `tools/audit_phase50_wfo_causal.py` is the repeatable final behavior audit.
  It fails closed and emits JSON proving inner-fold containment, untouched
  outer OOS, completed-prefix invariance, fail-closed malformed-history
  behavior, and public endpoint prepared/reference parity. It explicitly does
  not claim to prove look-ahead safety inside arbitrary user strategies.
- Public release docs now include `docs/walkforward_causal.md` as the concise
  schedule-selection and audit guide. The README, docs map, endpoint reference,
  packaging guide, and TestPyPI checklist link it; PyPI WFO smoke explicitly
  installs the `optimization` extra rather than assuming Optuna is in core.

Deliberate non-goals retained after Phase 50:

- automatic state checkpoint/restore for arbitrary reactive grid/DCA strategy
  objects across WFO folds;
- per-fold schedule variants for Mode 2 SBB, Mode 3 flat minima, or Mode 5
  full-sample calibration without their own causal contracts;
- a `flatten` boundary policy without dedicated accounting semantics and tests;
- proving arbitrary user strategy code free of internal look-ahead.

---

## Phase 51-54 - Rust Production Execution Core Upgrade

**Status: planned. No implementation phase has started.**

The authoritative detailed guide for this roadmap is:

- [`quantbt_p0_p3_native_rust_upgrade_blueprint.md`](quantbt_p0_p3_native_rust_upgrade_blueprint.md)

Every agent implementing any phase below must first read:

1. the blueprint [executive summary](quantbt_p0_p3_native_rust_upgrade_blueprint.md#0-executive-summary);
2. the [confirmed findings and must-prove risks](quantbt_p0_p3_native_rust_upgrade_blueprint.md#2-chẩn-đoán-trạng-thái-hiện-tại);
3. the detailed P0, P1, P2, or P3 sections linked by that phase;
4. the [architecture invariants](quantbt_p0_p3_native_rust_upgrade_blueprint.md#10-architecture-invariants-that-must-remain-true);
5. the [final acceptance matrix](quantbt_p0_p3_native_rust_upgrade_blueprint.md#15-final-acceptance-matrix).

The condensed plan below is a tracking and delivery contract. It does not
replace the algorithms, state machines, schemas, fixtures, workload taxonomy,
or acceptance guidance in the linked blueprint.

### Adjusted End State

This roadmap deliberately tightens the original dual-backend promotion policy.
The intended production architecture is:

```text
Python
  public API + request planning + preparation + research integration
  executable semantic oracle + certification tools + result/report adapters

Rust
  canonical production execution/order/account/risk core
  native strategy runtime + scenario batch execution
  shared event, portfolio, and package/arbitrage primitives

PyO3
  thin typed transport with amortized run/chunk/batch calls
```

The distinction is mandatory:

- Rust replaces Python as the normal production execution core only after the
  relevant contract/workload passes exact certification.
- Python remains runnable, readable, and independently testable as the oracle,
  historical reproducer, emergency fallback, and explicit debug backend.
- Python is not deleted and must not become stale or unexecutable.
- A production run has exactly one authoritative mutable execution state.
- A Rust run must not maintain Python shadow orders, positions, equity, margin,
  fill history, or lifecycle state.
- A normal Rust run must not replay the Python engine to construct reports.
- Explicit Rust never silently falls back. Automatic routing may fall back only
  for an unavailable, incompatible, uncertified, or deliberately unsupported
  contract, and must record a structured reason.
- After the final release gate, `auto` resolves to Rust for every certified
  production execution workload. Python becomes the documented oracle/fallback
  route rather than an equal default production choice.

This is a replacement of the production **core**, not a claim that all Python
objects disappear. Arbitrary Python strategy callbacks remain a hybrid driver
unless migrated to a static command tape, sparse wake protocol, or validated
strategy IR. In every case, order/account state remains owned by Rust once the
Rust backend is selected.

### Non-Negotiable Program Rules

- Implement from a new feature branch created from the latest `dev`; suggested
  branch name: `feat/51-native-rust-production-core`.
- Pin the exact starting SHA, package versions, toolchains, wheel hashes, test
  corpus, and E0-E6 benchmark manifests before behavior changes.
- Correctness gates always precede optimization and backend promotion.
- Preserve public imports and stable endpoint signatures through compatibility
  facades unless a separately approved deprecation record exists.
- Never change fill/account/output semantics inside a performance-only commit.
- Keep current behavior reproducible under an explicitly named legacy contract.
- Use one machine-readable contract/capability/trace registry to generate
  Python and Rust artifacts and conformance parameters.
- Numeric parity means exact discrete lifecycle agreement and audited numeric
  agreement. Tolerance must never hide a different fill, phase, reason, order
  transition, or liquidation decision.
- Benchmark end-to-end workload classes, not only Rust kernel microbenchmarks.
- Do not compare static Rust tape with arbitrary Python callbacks as equivalent
  workloads.
- Do not use `fast-math`, public-wheel `target-cpu=native`, unchecked indexing,
  custom allocators, SIMD, PGO, or unsafe code without profile evidence and the
  blueprint's proof gates.
- Commit each coherent contract, architecture, optimization, or packaging
  change separately with its tests and evidence.

### Current-Code Findings To Lock Before Refactoring

The Phase 51 baseline must reproduce and classify these observed conditions:

- `ExecutionContract.event_lifecycle()` declares `NEXT_OPEN`, while the current
  Rust full-session market matcher uses the execution bar close.
- The current Rust reactive adapter retains Python scheduled/pending orders,
  positions, dense paths, fill/event maps, and lifecycle projections alongside
  Rust state.
- The Rust full engine still scans `orders` for several expiry, parent, OCO,
  cancel, matching, and active-output operations.
- Current storage uses a `Vec<OrderState>` plus compaction and slot remapping,
  rather than generation-safe handles and active lifecycle indexes.
- Compatibility output still has nested row materialization and conditional
  full-position cloning.
- `endpoint.py`, Python native-event backend, Rust adapter, and Rust full engine
  remain broad modules with mixed planning/execution/report responsibilities.

These findings are baseline inputs, not permission to rewrite immediately.
Each must first receive a fixture, counter, trace, or architecture test.

---

### Phase 51A - P0 Contract Baseline, Event Clock, Fill, And Lifecycle Lock

**Status: completed on `feat/51-native-rust-production-core` (2026-08-19).**

Detailed guide:

- [P0.0 - Pin baseline and classify contracts](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p00--pin-baseline-và-phân-loại-contract)
- [P0.1 - Version event clock and bar timeline](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p01--version-hóa-event-clock-và-bar-timeline)
- [P0.2 - Fill, gap, and intrabar ambiguity](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p02--fill-policy-gap-policy-và-intrabar-ambiguity)
- [P0.3 - Order lifecycle state machine](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p03--order-lifecycle-state-machine)
- [Wave 0 and PR-00 through PR-04](quantbt_p0_p3_native_rust_upgrade_blueprint.md#53-wave-0--baseline-và-guardrails)

Goal:

Freeze what the current engines actually do, separate legacy behavior from the
correct next-open contract, and establish one versioned event/lifecycle model
before changing ownership or data structures.

Scope:

- Archive the exact baseline SHA, Python/Rust/compiler/package versions,
  installed-wheel hashes, native descriptor, current parity corpus, and E0/E1
  cold/warm benchmarks.
- Add low-overhead `EngineDiagnosticsV1` counters needed to locate preparation,
  callback, PyO3, engine, output, scan, copy, allocation, and report costs.
- Introduce a machine-readable execution contract registry and generated
  Python/Rust IDs/fingerprints.
- Freeze current event behavior as a clearly named legacy
  `event_v2_next_bar_close` contract without changing historical results.
- Implement `event_v3_next_open` first in the readable Python oracle and then
  in Rust, using actual `open[t]`, explicit gap handling, bar-zero/last-bar
  behavior, and exact phase trace.
- Version market, limit, stop-market, stop-limit, gap, same-bar ambiguity,
  child activation, and contingent-order priority policies.
- Split command outcome, order status, and lifecycle event kind into different
  typed concepts.
- Define generated transition tables for place, activate, amend, replace,
  cancel, expire, fill, reject, liquidate, parent/child, OCO, IOC/FOK/GTD, and
  invalid terminal transitions.
- Preserve legacy aliases only through an explicit compatibility translator and
  deprecation manifest; no alias may silently point to new semantics.

Required tests and evidence:

- Python/Rust exact phase and discrete trace for V2 historical fixtures.
- V3 actual-next-open tests proving the `open` array affects execution.
- Long/short golden matrix for market, limit, stop-market, stop-limit, gaps,
  same-bar SL/TP, child activation, OCO, replace, IOC/FOK/GTD, bar zero, final
  bar, duplicate timestamps, timezone, and multi-symbol clock ordering.
- Generated lifecycle transition tests run against both languages.
- Invalid transition and malformed command fixtures fail before mutation with
  the same structured reason code.
- Diagnostics counter values are exact on tiny fixtures and disabled overhead
  stays within the frozen budget.
- Installed editable/core/native wheel routes reproduce the same contract and
  trace fingerprints as source runs.

Exit gate:

```text
baseline and manifests archived;
V2 behavior is reproducible under an honest next-bar-close name;
V3 uses real next-open and passes Python/Rust parity;
all fill/gap/ambiguity policies have versioned IDs;
lifecycle state transitions and reasons exact-match;
no P1 ownership refactor has started.
```

Completion evidence:

- Baseline SHA, environment, wheel hash, fixture hashes, and E0/E1 evidence are
  frozen under `docs/contracts/baseline_manifest.json`,
  `tests/corpus/p0_baseline/`, and
  `benchmarks/native_event/results/p0_baseline/`.
- `contracts/native_event_contract_registry.json` is the canonical source for
  generated Python/Rust contract, command-outcome, order-status, lifecycle,
  transition, and fingerprint constants.
- V2 is frozen under the honest
  `event_lifecycle_v2_next_bar_close` ID. V3 uses actual open prices and has
  explicit market, limit-gap, stop-gap, and conservative stop-limit ambiguity
  semantics.
- Python, prepared, reactive replay, public facade, Rust full-tape, and the
  installed editable native extension consume the same contract ID and
  registry fingerprint.
- Audit outputs now separate command outcome, lifecycle order status, and
  lifecycle event kind on both Python and Rust; phase trace rows carry bar,
  UTC nanosecond timestamp, phase, and deterministic sequence. Legacy reports
  remain unchanged.
- Bar zero is an immutable initial snapshot in both Python and Rust. Explicit
  final-bar commands remain executable; reactive post-finalize intent remains
  outside tape.
- `EngineDiagnosticsV1` has exact tiny-fixture scan counters. The 2,000-bar
  public audit benchmark in
  `benchmarks/native_event/results/phase51a/contracts.json` observed no output
  drift and at most 7.0% positive diagnostics overhead (negative samples are
  timing noise).
- Certification: 43 Phase 51A contract tests, 90 focused contract/lifecycle
  tests, 113 native-event tests, 8 Rust unit tests, and the full release
  profile passed with 779 passed / 3 skipped / 0 failed.
  Evidence is archived in `docs/contracts/phase51a_certification.json`.
- P1 state-ownership, arena/index, and module-boundary refactors have not
  started in this phase.

---

### Phase 51B - P0 Ledger, Numeric, Trace, Portfolio/Package, And Wheel Certification

**Status: completed.**

Detailed guide:

- [P0.4 - Accounting ledger and invariants](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p04--accounting-ledger-và-invariants)
- [P0.5 - Instrument and deterministic numeric policy](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p05--instrument-constraints-và-deterministic-numeric-policy)
- [P0.6 - Canonical trace and replay](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p06--canonical-execution-trace-và-replay-fingerprint)
- [P0.7 - Property, model, and fuzz testing](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p07--differential-property-model-based-và-fuzz-testing)
- [P0.8 through P0.11](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p08--portfolio-correctness-foundation)
- [PR-05 through PR-09 and P0 checkpoint](quantbt_p0_p3_native_rust_upgrade_blueprint.md#pr-05--accounting-ledgerinvariants)

Goal:

Build independently auditable accounting, deterministic numeric behavior, one
canonical trace, and reference semantics for portfolio and package execution so
Rust can later replace Python without changing financial meaning.

Scope:

- Define canonical collateral, realized/unrealized PnL, fee, funding, carry,
  slippage, liquidation cost, position, average entry, initial/maintenance/
  reserved margin, and available-equity ledger components.
- Check equity, per-bar delta, position-fill, gross/net exposure, portfolio
  attribution, and package-leg reconciliation invariants.
- Version fee currency, funding event phase/sign/price, margin, and liquidation
  models. Legacy zero-equity liquidation remains reproducible; auditable forced
  close emits decision, fill, fee, cancellation, and residual-equity records.
- Compile instrument constraints into contiguous IDs/tables with tick size,
  quantity step, min/max quantity, min notional, contract size, settlement,
  fee model, and margin model.
- Quantize price and quantity in the same phase and direction in Python/Rust;
  reject inverse/quanto/options formulas unless the selected model is certified.
- Add canonical trace schema, streaming/hash sinks, normalized rolling
  fingerprint, and a replay verifier that reconstructs state from trace without
  invoking the matcher.
- Add Hypothesis, proptest, model-based, metamorphic, minimized regression
  corpus, and scheduled fuzz foundations.
- Freeze portfolio allocator versus execution boundaries and policies including
  sequential legacy, pro-rata margin scaling, all-or-none target, and
  reduce-first-then-increase.
- Freeze arbitrage/package planned/preflight/reserved/commit/abort/compensate
  transitions and atomic, best-effort, sequential, and hedge-after-primary
  semantics, including cross-venue staleness and reservation rollback.
- Replace flat capability booleans with a structured semantic descriptor and
  runtime protocol/contract/trace/ABI handshake.
- Certify core-only, explicit Rust unavailable/mismatch, automatic fallback,
  and clean installed-wheel behavior on supported CPython versions.

Required tests and evidence:

- Every golden scenario passes ledger identities on every bar, not only final
  equity.
- Scale, reduce, close, reverse, fee, funding, slippage, margin rejection, and
  liquidation attribution parity.
- Exact tick/step vectors and rejection reasons across Python/Rust.
- Audit trace exact-match in discrete fields; hash-only and full-trace
  fingerprints agree; replayer reconstructs terminal state.
- Randomized and minimized corpus produces no panic, invalid transition,
  unexplained accounting residual, or cross-run nondeterminism.
- Portfolio target/accepted/cost/attribution reconciliation and package
  rollback/residual exposure tests pass.
- Clean wheel matrix validates native availability, incompatibility, explicit
  failure, and structured fallback before expensive preparation.

Exit gate:

All items in the blueprint [P0 exit checklist](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p011--p0-exit-checklist)
must pass. P1 cannot start if the trace tooling cannot identify the first
divergent bar, phase, event, status, reason, or ledger component.

Completion evidence:

- Native-event audit runs now attach an independently reconstructed canonical
  accounting ledger and per-symbol ledger. Every bar checks equity,
  position/fill, gross/net exposure, fee, funding, margin, and attribution
  invariants for the versioned linear quote-settled model.
- Instrument constraints compile into immutable contiguous tables. Python and
  Rust apply identical side/order-aware tick and lot quantization and
  post-quantization minimum checks. Inverse, quanto, and option formulas fail
  fast rather than using an uncertified linear approximation.
- `canonical-execution-trace-v1` provides materialized and hash-only sinks,
  deterministic SHA-256 fingerprints, first-divergence diagnostics, and an
  independent terminal-state replayer. Python/Rust exact-match on the P0 audit
  fixture.
- Portfolio target allocation and package transaction behavior are frozen as
  reference semantics for sequential, pro-rata, all-or-none,
  reduce-first-then-increase, atomic, best-effort, sequential-leg, and
  hedge-after-primary policies. This checkpoint does not claim Rust
  portfolio/package execution.
- Native API `0.4` now requires a structured semantic descriptor covering the
  core protocol range, registry fingerprint, trace schema, command ABI, order
  semantics, and account model. A mismatch fails before expensive
  preparation; legacy `0.3` probes remain readable but are not accepted as the
  current certified contract.
- Hypothesis, Rust proptest, metamorphic cases, and the minimized regression
  corpus cover numeric monotonicity, deterministic replay, reversals, and
  package rollback. Full `cargo-fuzz` soak remains intentionally downstream of
  pure-core extraction and is not claimed here.
- Focused evidence passed: 72 native-event contract tests, 20
  portfolio/arbitrage reference tests, and 10 Rust unit/property tests. The
  clean CPython 3.12 Linux installation of `quantbt-engine 1.0.8` plus
  `quantbt-native 0.4.0` passed import isolation, semantic handshake,
  accounting, trace parity, and replay. CI repeats the Phase 51B contract gate
  on CPython 3.11-3.13.
- The reproducible wheel gate is
  `tools/certify_phase51b_wheel.py`; detailed semantics and hashes are archived
  in `docs/contracts/p0_accounting_trace.md` and
  `docs/contracts/phase51b_certification.json`.

---

### Phase 52A - P1 Immutable Planning, Preparation, Backend SPI, And Output Contract

**Status: completed (2026-08-19).**

Detailed guide:

- [P1 objective and dependency rules](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p1--tái-kiến-trúc-endpoint-và-pythonrust-boundary)
- [P1.1 - Endpoint resolver, planner, and executor](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p11--tách-quantbtendpoint-thành-resolver-planner-và-executor)
- [P1.2 - Equal backend SPI](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p12--thiết-kế-backend-spi-ngang-hàng)
- [P1.3 - OutputRequirements](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p13--resolve-outputrequirements-một-lần)
- [PR-10 through PR-13](quantbt_p0_p3_native_rust_upgrade_blueprint.md#pr-10--immutable-executionplan)

Goal:

Make the public endpoint a stable facade over one immutable plan, one
preparation pass, one selected backend, one raw result contract, and one result
adaptation pass without changing public behavior or P0 fingerprints.

Scope:

- Enforce dependency direction before moving code: planning cannot import
  reporting, backend cannot import endpoint/report builders, result adapters
  cannot resolve a backend, and Rust adapters cannot invoke the Python oracle.
- Introduce immutable, serializable `BacktestRequest`, resolved
  `ExecutionPlan`, `PreparedRun`, `EngineRunRequest`, and `RawEngineResult`.
- Resolve aliases, contract, strategy mode, workload class, output/profile,
  numeric policy, capabilities, backend decision, and fingerprints exactly once.
- Move DataFrame/index/market/instrument/command normalization into preparation;
  engines receive contiguous typed data, never pandas.
- Implement one backend SPI for Python and Rust with prepare/run/reset/close and
  structured descriptor/error contracts.
- Compile `OutputRequirements` once from strategy context, public output,
  metrics, and trace needs. Distinguish scalar aggregation, dense paths,
  streamed audit, and callback-only projections.
- Keep existing imports and endpoint methods as compatibility facades while
  progressively moving responsibilities into planning, preparation, engines,
  results, and reporting modules.
- Lazy-load the native module only for explicit Rust, automatic capability
  resolution, or explicit diagnostics.

Required tests and evidence:

- One plan fingerprint, normalization, instrument preparation, capability
  resolution, and output projection per run.
- Python and Rust consume the same plan/prepared inputs and pass the same
  backend contract fixtures.
- Backend cannot mutate the plan or construct pandas/report objects.
- Score path allocates no fill/event rows; count-only counters remain exact.
- Import-boundary, circular-import, cold-import, lazy-native, and source/wheel
  module-path tests.
- All P0 traces, public results, metadata compatibility fields, and historical
  endpoints remain parity-locked.

Exit gate:

The public API is unchanged, but execution is reachable only through the
planner/preparation/backend/result pipeline. No backend-specific execution
branch may remain in the endpoint outside the registry/decision layer.

Completion evidence:

- Added frozen, slot-based, deterministic `BacktestRequest`, `ExecutionPlan`,
  `OutputRequirements`, and trace/numeric/backend policy models under
  `quantbt.planning`.
- Added one-pass lifecycle preparation with read-only contiguous OHLCV,
  funding, instrument, account, and command buffers. Plan, market,
  instruments, commands, account, and combined preparation identities are
  SHA-256 fingerprinted.
- Added equal Python/Rust `EngineBackend` and `PreparedEngineSession` SPI plus
  pandas-free struct-of-arrays `RawEngineResult`. Both implementations consume
  the same plan and prepared tape; exact path/fill/summary parity passed on the
  certified fixture.
- Routed public static lifecycle runs through the immutable planner and
  preparation layer. The P0 public adapter remains after execution so existing
  `BacktestResultV2`, accounting ledger, trace, and report behavior stay
  unchanged. Reactive callbacks, baskets, and event v1 remain explicitly out
  of this phase and are carried by Phase 52B.
- Public score runs preserve the historical result surface while retaining no
  fill/event detail rows in the projection. Internal score SPI runs retain
  scalar summaries and exact counts with zero dense/fill/event buffers.
- AST/import gates prove no forbidden planning/SPI/raw-result dependencies,
  no circular imports, and no eager `_quantbt_native` import under automatic
  Python policy.
- P0 oracle parity is exact for equity, positions, fees, funding, margin,
  fills, accounting invariants, and canonical trace fingerprint. Quantity
  preflight and command compilation each run once on the endpoint route.
- Focused Phase 52A tests passed `16/16`; the lifecycle, grid, event-driven,
  P0 contract, and Python/Rust regression gate passed `129/129` with no skips.
- A clean `quantbt-engine 1.0.8` wheel included every P1 module and passed the
  installed-wheel gate. Median cold import was `1383.989 ms` versus
  `1307.411 ms` at the pre-route baseline (`+5.857%`, eight isolated runs),
  within the 10% architecture budget and without importing the native module.
- Detailed semantics and repeatable evidence are in
  [P1 planning/backend SPI](../docs/contracts/p1_planning_backend_spi.md),
  [Phase 52A certification](../docs/contracts/phase52a_certification.json), and
  `tools/certify_phase52a_wheel.py`.

---

### Phase 52B - P1 Strategy Boundary, Rust Ownership, Audit, Cache, And Observability

**Status: complete (2026-08-19).**

Detailed guide:

- [P1.4 - Context compatibility, numeric view, and projection](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p14--strategy-context-protocol-compatibility-view-và-projection)
- [P1.5 - Reusable command writer](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p15--reusable-command-writer-thay-listordercommand)
- [P1.6 through P1.11](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p16--xóa-python-shadow-state-trong-rust-adapter)
- [P1.12 through P1.14](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p112--kế-hoạch-tách-file-cụ-thể-từ-code-hiện-tại)
- [PR-14 through PR-18](quantbt_p0_p3_native_rust_upgrade_blueprint.md#pr-14--numeric-context-view--command-writer)

Goal:

Eliminate duplicate Python execution state and unnecessary Python/Rust traffic.
Rust becomes the sole owner of order/account state whenever selected, while
legacy callback code remains compatible through an explicit adapter.

Scope:

- Keep the existing materialized strategy context as compatibility mode.
- Add a numeric `StrategyContextView` using interned IDs, integer timestamps,
  array/delta views, explicit lifetime generation, and declared requirements.
- Add a reusable preallocated SoA `CommandWriter`; legacy command objects
  compile into the same canonical command trace outside the native hot path.
- Add static command-tape and sparse run-until-wake drivers. Arbitrary every-bar
  callbacks remain supported but are labelled hybrid compatibility workload.
- Add native fill/event/order/position cursor ranges and compact projection so
  callbacks receive only requested changes.
- Remove Python scheduled/pending/order/account/position/path/metric mirrors
  from the Rust adapter after all consumers use authoritative native state.
- Separate `native_trace`, `verify_against_oracle`, and sampled dual-run audit.
  Normal Rust audit must use one primary engine run and report from its trace.
- Introduce layered prepared cache keys, byte/entry budgets, LRU/pinning rules,
  explicit reset scopes, result ownership, generation, and session poisoning.
- Add structured cross-language errors and fail-fast ordering before expensive
  market preparation.
- Emit versioned phase, boundary, copy, callback, scan, allocation, output, and
  memory diagnostics needed for P2 profiling.
- Complete the module split described by the blueprint while retaining tested
  temporary compatibility imports with owners and removal deadlines.

Required tests and evidence:

- Compatibility context and numeric view create identical canonical commands.
- Writer reuse, growth, capacity limit, stale context, callback exception, and
  malformed command tests.
- Static path uses O(1) PyO3 calls; sparse callback calls equal wake schedule;
  arbitrary callbacks have no hidden additional calls.
- Rust adapter has one authoritative mutable state and performs no Python-side
  cash, equity, margin, or order transition calculation.
- Native audit runs one engine; optional oracle verifier detects injected
  divergence without replacing the primary result.
- Run/reset/rerun equals fresh session; result lifetime/GC and retained-result
  tests have no stale view or use-after-reset.
- Thousands of prepared resets/runs reach bounded RSS; cache collisions,
  mutation, cross-run contamination, and thread-safety tests pass.
- Per-phase timings answer whether cost lies in callback, boundary, kernel,
  output, adaptation, or report construction.

Exit gate:

All blueprint [P1 exit checklist](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p114--p1-exit-checklist)
items pass, all P0 fingerprints remain unchanged, and Python/Rust switching
within one run is architecturally impossible.

Implementation and certification:

- `quantbt.strategies` now owns the declared context requirements, generation-
  guarded numeric view, reusable struct-of-arrays command writer, sparse wake
  schedule, and legacy callback adapter. Legacy strategies remain conservative
  and compatible; declared numeric strategies keep commands primitive through
  the Rust full-contract adapter for `minimal` reports.
- Rust is the sole mutable owner for a Rust reactive run. The adapter exposes
  compact cursor/projection data only, maintains no Python account, position,
  pending-order, lifecycle, or metric shadow state, and supports explicit
  account-and-orders reset/replay.
- Public retention is resolved after the strategy declaration: accounting paths
  and report-level artifacts remain compatible, while unrequested fills,
  events, and active-order callback snapshots are not built. `standard` and
  `audit` materialize exactly one terminal active-order artifact when needed,
  preserving the historical report surface without per-bar snapshot cost.
- Numeric quantity preflight now preserves Python/Rust parity for accepted,
  rounded, and dropped rows, including public drop metadata and emitted-command
  counters. `native_trace`, `verify_against_oracle`, and deterministic
  `dual_run_sampled` audit policies are explicit; an oracle never replaces the
  primary result.
- Prepared cache identity includes market timestamps, OHLC, volume, funding,
  funding mask, symbols, and relevant constraints. It is bounded LRU with
  pin/release diagnostics; session reset and result ownership are covered by
  focused tests.
- Versioned observability records preparation, callback, command compilation,
  engine, report, oracle, allocation/copy, boundary, PyO3, and RSS counters.

Evidence:

- Focused strategy/cache/audit plus lifecycle parity: `33 passed`.
- Full repository regression gate: `844 passed, 3 skipped`.
- Rust unit suite: `10 passed`.
- Source certification: 2,000 bars, exact Python/Rust equity/position/fee/
  funding/margin/trace parity; zero numeric `OrderCommand` objects and zero
  active snapshots for the declared minimal workload; 2,000 reset/reruns with
  zero RSS growth.
- Installed-wheel smoke certification passed from an isolated target site.
  See [P1 strategy/Rust ownership contract](../docs/contracts/p1_strategy_rust_ownership.md)
  and [machine-readable Phase 52B evidence](../docs/contracts/phase52b_certification.json).

Performance interpretation:

- The exact 2,000-bar every-bar numeric Python callback fixture records
  Python median `49.913 ms` and Rust median `210.527 ms`. This is expected for
  a callback-bound workload with 2,000 controlled PyO3/GIL transitions; it is
  not an accounting or parity regression. Static command tapes and sparse
  schedules already avoid this boundary. Fully native strategy IR, chunking,
  and batched execution belong to the explicitly planned P2 phases below, not
  an untracked Phase 52B defect.

---

### Phase 53A - P2 Pure Rust Core, ABI 0.5, Arena, Indexes, Account, And Output

**Status: completed (2026-08-19).**

Detailed guide:

- [P2 benchmark taxonomy E0-E6](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p20--freeze-benchmark-taxonomy-trước-khi-sửa-kernel)
- [P2.1 through P2.5](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p21--chuyển-thành-rust-workspace-pyo3-chỉ-ở-outer-crate)
- [P2.6 through P2.9](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p26--specialized-execution-kernels-không-dùng-một-universal-hot-loop)
- [PR-19 through PR-27](quantbt_p0_p3_native_rust_upgrade_blueprint.md#pr-19--rust-workspace-extraction)

Goal:

Create a pure, independently testable Rust execution engine and replace the
current history-scaled order/output/account hot structures without changing the
certified semantics.

Scope:

- Freeze E0-E6 fixture manifests, phase timings, cold/warm methodology, RSS,
  allocation, copy, callback, PyO3, and lifecycle counters before optimization.
- Extract a Rust workspace with domain, engine, strategy-IR, batch, portfolio,
  package, and outer PyO3 crates. The domain/engine crates cannot depend on
  PyO3, NumPy, pandas, Python exceptions, or report models.
- Preserve native API 0.4 through a translator while adding typed ABI 0.5 IDs,
  enums, generation-safe handles, command offsets, instrument tables, and
  structured errors.
- Keep Rust-owned immutable prepared market tapes, record all copies, and reuse
  them across scenarios. Do not introduce unsafe long-lived NumPy borrowing.
- Replace `Vec<OrderState>` plus hot compaction with a generation-safe arena,
  free list, monotonic priority sequence, resource limits, and terminal-event
  emission before slot release.
- Add active-by-symbol, expiry, parent-child, OCO, waiting-parent, and optional
  group/tag indexes. Matching cost must follow relevant active orders rather
  than all historical orders.
- Use adaptive candidate matching and deterministic deferred mutation for
  market, limit, stop, stop-limit, IOC/FOK, reduce-only, and relationship flows.
- Implement incremental positions, PnL, fee, funding, margin, dirty-symbol MTM,
  active-position indexes, and auditable liquidation over the shared ledger.
- Separate specialized score, compact, and audit kernels/output sinks. Replace
  nested rows and per-step position clones with flat typed SoA buffers, online
  metrics, move/view ownership, and chunked audit streaming.

Required tests and evidence:

- Pure Rust unit/proptest/bench works without Python headers.
- API 0.4 translation produces the exact P0 canonical trace.
- Stale handle, slot reuse, priority, resource-limit, and malformed ABI fuzz
  tests pass without panic or out-of-bounds mutation.
- Debug index validator remains consistent after every generated transition.
- Accounting, margin, liquidation, output profile, and result-lifetime parity.
- High-churn memory scales with peak live orders plus requested output, not
  historical order count.
- E0 score/compact/audit end-to-end gates include preparation and adaptation;
  low-churn small workloads cannot regress outside the documented budget.

Exit gate:

The production Rust event engine has no PyO3 dependency internally, no hot
order compaction, no scan of terminal/historical orders in the execution loop,
no score-via-audit path, and no unrequested dense or nested result
materialization on the static-tape route. Stable-priority matching still visits
the relevant live book; a price/type candidate specialization must prove exact
trace parity before it replaces that conservative route.

Implementation completed:

- Extracted the Cargo workspace into `quantbt-domain`, `quantbt-engine`,
  `quantbt-strategy-ir`, `quantbt-batch`, `quantbt-portfolio`,
  `quantbt-package`, and the outer `native_event` PyO3 binding. The domain and
  engine dependency trees contain no PyO3 or NumPy dependency.
- Preserved public Native Event API `0.4` and introduced the internal ABI
  `0.5` contract: typed IDs/enums, generation-safe `OrderHandle`, immutable
  command-tape validation/translation, structured domain errors, and a
  bar-major prepared market/instrument boundary. The P0-compatible static
  reader continues consuming the established API-0.4 wire tape until the full
  typed SoA reader migration receives its own trace certification.
- Replaced full-session terminal compaction with an arena/free list plus
  monotonic lifecycle indexes for active priority, symbol, GTD expiry,
  parent-child, and OCO relationships. Terminal events are emitted before slot
  release and index invariants are checked by generated-transition tests.
- Added score, compact, and audit static-tape sinks. Score retains terminal
  scalars only; compact retains account paths without detail rows; audit adds
  typed fill/event columns. All use the same matching/accounting path and flat
  bar-major position storage.
- Added the frozen E0-E6 taxonomy and an E0 profile benchmark. The strategy
  IR, batch/WFO, portfolio, and package crates deliberately expose typed
  contracts only in this phase; executable semantics are Phase 53B scope and
  are not advertised through a public endpoint.
- Kept the P0-compatible API-0.4 reader and verified account loop as the live
  static execution path. Full ABI-0.5 tape consumption, price/type candidate
  specialization, and adoption of the new account primitives remain explicit
  Phase 53B promotion work, each gated by canonical trace and accounting
  parity rather than silently replacing the certified path.

Evidence:

- `cargo fmt --all -- --check`, `cargo test --offline --workspace`, and
  `cargo clippy --offline --workspace --all-targets -- -D warnings` pass.
- Full Python native-event contract/regression suite: `182 passed, 2 skipped`.
- Repository regression after the extracted workspace and rebuilt local
  extension: `848 passed, 3 skipped`.
- E0 static command-tape profile benchmark at 2,000 bars and five warm
  repeats verifies exact score/compact/audit terminal accounting parity and
  compact/audit path parity for low and high churn. See
  [`e0_profiles.json`](../benchmarks/native_event/results/phase53a/e0_profiles.json).
- The artifact records score at 8.19M/2.15M bars/s, compact at 1.56M/1.04M
  bars/s, and audit at 655k/81k bars/s for low/high churn. These are E0-only,
  machine-local measurements rather than a promotion claim for E1-E6.

---

### Phase 53B - P2 Native Strategy IR, Batch/WFO, Portfolio, Package, And Performance Gate

**Status: completed (scoped native-driver certification; no default endpoint promotion).**

Detailed guide:

- [P2.10 - Native strategy hierarchy and IR](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p210--native-strategy-execution-hierarchy)
- [P2.11 - Scenario batch for optimizer/WFO](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p211--scenario-batch-engine-cho-optimizer-và-walk-forward)
- [P2.12 and P2.13 - Portfolio and package cores](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p212--rust-portfolio-execution-core-dùng-chung-accountorder-engine)
- [P2.14 through P2.20](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p214--parallelism-đúng-tầng-deterministic-và-không-oversubscribe)
- [P2 performance promotion gates](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p219--recommended-performance-promotion-gates)

Goal:

Move common deterministic strategy and repeated-scenario workloads fully into
Rust, then extend the same certified order/account/risk core to portfolio and
arbitrage packages without creating separate engines.

Scope:

- Promote the typed ABI-0.5 reader, specialized live-order candidate sets, and
  incremental account primitives only after isolated P0 trace/accounting
  parity gates. The Phase 53A live-priority scan is the conservative baseline,
  not a hidden performance claim.
- Preserve four explicit strategy levels: legacy Python objects, numeric
  Python view/writer, sparse Python callback, and fully native strategy IR.
- Implement a bounded, validated IR v1 plus readable Python reference
  interpreter for market reads, parameters, state, arithmetic/comparison,
  branch/control, order/bracket/cancel/amend, and scheduled wake operations.
- Prove IR with Grid, DCA, bracket/OCO, rebalance, and selected signal-tape
  strategies. Do not build a general-purpose Python VM.
- Add one-call scenario batch execution using shared prepared market/strategy,
  worker-local mutable state, deterministic reset, compact scalar metric rows,
  stable top-K, and selected-candidate audit reruns.
- Integrate batch execution with optimization and WFO without changing existing
  objective, split, schedule, seed, candidate-selection, or accounting rules.
- Parallelize independent scenario/fold work only; prevent nested Optuna/Rayon/
  BLAS/Numba oversubscription and preserve exact results at 1/2/4/8 workers.
- Add Rust portfolio target execution over the shared account/order engine;
  keep allocator/risk-estimation research in Python until independently worth
  porting. Support versioned rebalance/margin/rejection/attribution policies.
- Add Rust package/arbitrage preflight, reserve, commit, abort, compensate, and
  residual-risk execution over the same core. Atomicity remains explicitly a
  bar-simulation transaction, not exchange atomicity.
- Detach the interpreter for Rust-only run/chunk/batch work and minimize typed
  arrays/handles crossing PyO3.
- Evaluate compiler, PGO, SIMD, allocator, hashing, or unsafe changes only after
  profile evidence across representative E0-E6 workloads and exact parity.

Required tests and evidence:

- Python IR interpreter and Rust runtime exact trace for Grid/DCA/bracket
  fixtures, including state reset and malformed-program rejection.
- Scenario `i` equals standalone scenario `i`; worker counts are exact and
  deterministic; cancellation leaves reusable sessions healthy.
- Zero market copy per trial after prepare and bounded RSS over large batches.
- Existing WFO modes/schedules retain params, objective, fold, stitched target,
  and final account parity on the compatibility path.
- Portfolio target/accepted/cost/PnL attribution parity against certified
  Python/Numba reference.
- Package reservation, rollback, actual-fill hedge sizing, staleness, and
  residual exposure parity.
- E0-E6 performance and memory matrix reports honest boundary calls, callbacks,
  copies, engine time, adaptation, reports, peak/steady RSS, and fingerprints.

Phase 53B exit gate:

The scoped native IR and batch drivers must pass the reference trace,
single/batch, worker-count, prepared-market reuse, selected-audit, and
installed-extension gates before they are documented. Portfolio/package drivers
must retain reference-preflight and typed-tape lifecycle parity. The full
blueprint [P2 exit checklist](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p220--p2-exit-checklist)
remains a wider production-promotion horizon; it is **not** silently marked
passed until generic WFO, portfolio, package, and E0--E6 endpoint paths have
their own evidence. Rust must be demonstrably faster end to end only for the
native workloads actually promoted, while callback compatibility remains
correctly labelled rather than used to hide boundary overhead.

Implementation slices and evidence discipline:

1. **Native Strategy IR v1:** add a bounded declarative Python compiler,
   deterministic reference interpreter, Rust instruction/runtime contract, a
   human-readable disassembler and stable program fingerprint. Promote only
   precomputed-signal strategies whose command tape matches the reference
   trace exactly; Grid/DCA/bracket fixtures are mandatory.
2. **Batch and WFO bridge:** run independent parameter rows over one shared
   prepared market with scalar score rows, stable top-K and selected audit
   reruns. Existing Optuna/WFO scheduling, objectives, splits and defaults
   remain compatibility routes until direct batch parity is demonstrated.
3. **Portfolio and package drivers:** compile approved target and package
   plans into immutable native tapes. Every target/package action must pass
   through the certified event/account lifecycle; Python remains the reference
   oracle for rejection, reservation, rollback and attribution reconciliation.
4. **Promotion gate:** test reference/Rust traces, single/batch and
   worker-count determinism, prepared-market reuse, selected audit equality,
   portfolio/package accounting and bounded RSS. Publish E0--E6 evidence only
   for workload routes that actually use the new runtime. Unsupported strategy
   constructs continue to raise a capability error on explicit Rust selection
   and retain their existing Python path.

Delivered:

- Added the bounded Strategy IR v1 and a pure Python reference compiler for
  `signal_target`, `grid_level`, `dca_periodic`, and `fixed_bracket`. Rust
  compiles the same immutable ABI-0.5 tape, exposes a human-readable
  disassembly and cross-language fingerprint, and executes with zero Python
  callbacks after the boundary call.
- Added a prepared scenario batch runtime with immutable shared market/program,
  worker-local `FullSession` state, stable ID order/top-K tie-breaks, score-only
  retention, selected audit reruns, and explicit `NativeIRFold` OOS windows.
  This is intentionally a low-level execution bridge: existing Optuna/WFO
  objectives, schedules, seeds, folds, stitching, and endpoint defaults are
  unchanged.
- Added Rust portfolio target and package preflight drivers that preserve the
  certified Python reference contracts, compile approved deltas/legs into
  typed ABI-0.5 tapes, and prove those tapes run through the shared event,
  fill, fee, slippage, margin, and lifecycle core.
- Added [`docs/native_strategy_ir.md`](../docs/native_strategy_ir.md), the
  [`Phase 53B certification`](../docs/contracts/phase53b_certification.json),
  and reproducible E3/E6 evidence at
  [`native_drivers.json`](../benchmarks/native_event/results/phase53b/native_drivers.json).

Evidence:

- Focused native-driver differential suite: `16 passed`.
- Full native-event regression: `197 passed, 2 skipped`; WFO compatibility
  regression: `75 passed`.
- Repository regression excluding the two external real-data tests: `864
  passed, 3 skipped`.
- `cargo test --offline --workspace` passed (`39` Rust tests), and
  `cargo clippy --offline --workspace --all-targets -- -D warnings` passed.
- On the committed 2,000-bar/64-scenario fixture, native Grid IR score ran at
  `5.997M bars/s` versus `418,613 bars/s` for the Python reference command
  route with exact audit parity. Four-worker batch reached `21.41M` simulated
  bars/s, zero prepared-market copies per scenario, and an observed incremental
  RSS delta of `1.16 MiB`. This is E3/E6 local evidence only, not a universal
  callback/portfolio/arbitrage claim.

Remaining P2 scope is intentionally explicit rather than silently claimed:

- Native IR v1 is bounded templates, not a general strategy VM, dynamic
  trailing/amend runtime, or arbitrary Python callback replacement.
- `NativeIRFold` is not wired as an automatic `WalkForwardEngine`/Optuna
  backend until full strategy/objective/fold-accounting parity is separately
  demonstrated.
- Portfolio/package native support is a replayable preflight-to-typed-tape
  driver. General Rust portfolio reports, cross-currency accounting, actual
  fill-derived dynamic hedging/unwind, and venue-native atomicity remain future
  capabilities, not current endpoint claims.
- E4/E5 full endpoint performance promotion and the broader E0-E6 production
  matrix remain a later promotion decision. The current tests prove accounting
  and lifecycle reuse, not generic endpoint speed.

---

### Phase 54A - P3 Source, Registry, Packaging, CI, Security, And Documentation

**Status: complete (Phase 54A scope).**

Detailed guide:

- [P3.0 through P3.4](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p30--một-source-tree-python-duy-nhất)
- [P3.6 through P3.10](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p36--benchmark-governance-và-regression-ci)
- [Target repository structure](quantbt_p0_p3_native_rust_upgrade_blueprint.md#6-target-repository-structure-after-p0p3)
- [Test and CI command contract](quantbt_p0_p3_native_rust_upgrade_blueprint.md#8-test-and-ci-command-contract)

Goal:

Turn the certified engines into reproducible source and installed products with
one source of truth, generated contracts, exact core/native compatibility,
stable diagnostics, governed benchmarks, and supply-chain evidence.

Scope:

- Complete migration to `src/quantbt` as the only authoritative Python source.
  A transitional root mirror may exist only as generated/read-only with byte
  identity CI, then is removed under an approved cleanup release.
- Split large modules according to ownership boundaries; enforce import rules,
  internal visibility, public API inventory, and ADRs for contract/backend/
  arena/IR/batch/portfolio/package/package-compatibility decisions.
- Generate Python/Rust enums, schemas, capability descriptors, docs tables,
  conformance cases, ABI fingerprints, and release manifests from one versioned
  contract registry.
- Maintain independent package, native protocol, command ABI, result ABI,
  execution contract, trace schema, and IR versions with a machine-readable
  compatibility/deprecation matrix.
- Build `quantbt-engine` core and lockstep `quantbt-native` wheels from the same
  release ref. Keep core-only functional and enable the native extra only after
  clean-index compatibility gates pass.
- Test CPython 3.11/3.12/3.13 and supported manylinux targets from staged wheels,
  with no repository path leakage or undeclared shared libraries.
- Establish PR, main, nightly, and release CI layers for generated files,
  differential/property/fuzz corpus, lifetime, memory plateau, E0-E6 benchmark,
  clean wheels, mismatch, and rollback gates.
- Add signed/checksummed provenance, SBOM, dependency/license/vulnerability
  review, unsafe inventory, fuzz/sanitizer evidence, and portable CPU metadata.
- Publish versioned diagnostics/counter schemas and complete architecture,
  contract, native install/capability/troubleshooting, performance, and strategy
  migration documentation with executable examples.

Required tests and evidence:

- Source, editable install, core wheel, and native wheel production module
  hashes and behavior agree.
- Generated artifacts are clean and Python/Rust registry fingerprints match.
- Core-only, core+native, exact compatible pair, mismatched pair, missing native,
  and unsupported platform matrix behaves as documented.
- All docs examples run in CI; capability claims are generated from installed
  descriptors rather than handwritten marketing text.
- Benchmark baselines are immutable, reproducible, tied to release/toolchain/
  hardware, and cannot pass by changing outputs or semantics.
- Supply-chain and unsafe reports are release artifacts.

Exit gate:

Installed wheels, not source-tree tests, are the authority for release support.
No production capability may be advertised without a clean-wheel trace,
accounting, performance, RSS, compatibility, and rollback result.

Implemented:

- `src/quantbt` is the single authoritative Python tree. The temporary root
  mirror is generated only through `tools/sync_source_mirror.py`; byte identity
  is checked in local and CI contract gates. It remains intentionally present
  until the separately approved Phase 54B deletion/migration release.
- Added the versioned product registry
  `contracts/native_event_product_registry.json`. It generates Python/Rust
  product constants, exact core/native pairing, workload maturity records,
  public API inventory, compatibility documentation, and a generated product
  conformance corpus. The frozen lifecycle registry remains unchanged.
- Rust now builds its API version, capabilities, semantic descriptor, and
  separate product ABI descriptor from generated contract values. The Python
  probe validates semantic behavior plus product fingerprint, exact package
  pair, protocol range, command/result ABI, trace schema, and strategy-IR
  version before any explicit Rust execution.
- Added ownership/import-boundary review gates, CODEOWNERS, ADRs, public API
  inventory, documentation map, generated capability table, native install and
  troubleshooting documentation, and a stable Makefile command surface.
- Added core/native wheel source-hash verification, native artifact allowlist,
  exact staged-pair verification, a release manifest that distinguishes core
  artifacts from an optional exact staged-native companion, CycloneDX SBOM,
  supply-chain/unsafe inventory/provenance evidence, scheduled `cargo audit`,
  PR/main/release source gates, and a non-promoting nightly E0/E3/E6 evidence
  workflow.

Evidence:

- `874 passed, 3 skipped` for the full Python suite excluding only the two
  repository-local real-data scripts.
- `206 passed, 2 skipped` for `tests/native_event`; product/release focused
  tests and legacy release-surface coverage pass.
- Rust workspace `fmt`, tests, and `clippy -D warnings` pass.
- Built `quantbt-engine==1.0.8` wheel/sdist and
  `quantbt-native==0.4.0` local wheel: artifact allowlist, source-to-wheel hash
  parity, generated registry checks, exact staged pairing, runtime extension
  import, semantic descriptor, and product descriptor all pass.
- Full dependency-resolving clean-install verification remains an installed
  wheel CI gate. The local sandbox cannot resolve the package index; a
  no-repository-path wheel smoke with the already provisioned dependency set
  passed, so this is an environment limitation rather than a fallback claim.

Boundary after Phase 54A:

- `backend="auto"` remains Python-first; `backend="rust"` is explicit and
  fail-closed. No workload was silently promoted.
- Phase 54B owns workload-aware Rust promotion, rollback controls, real
  installed-wheel performance certification, and deletion of the generated root
  mirror/shadow compatibility paths. Those are deliberate promotion/cleanup
  scope, not unresolved Phase 54A correctness defects.

---

### Phase 54A.5 - Rust Execution Ownership Completion, Typed Request, And Boundary Collapse

**Status: in progress. Must complete before any Phase 54B auto-promotion work.**

Detailed guide:

- [P1.3 - Resolve output requirements once](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p13--resolve-outputrequirements-một-lần)
- [P1.6 through P1.9 - Remove shadow state, reduce transitions, primary audit, and prepared cache](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p16--xóa-python-shadow-state-trong-rust-adapter)
- [P2.2 and P2.3 - Typed ABI 0.5 and market ownership](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p22--chuyển-thành-rust-workspace-pyo3-chỉ-ở-outer-crate)
- [P2.9 - Flat SoA output and online metrics](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p29--output-architecture-flat-soa-online-metrics-và-zero-unnecessary-materialization)
- [P2.10 through P2.13 - Strategy hierarchy, batch/WFO, portfolio, and package execution](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p210--native-strategy-execution-hierarchy)
- [P2.15 - Correct PyO3 boundary optimization](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p215--pyo3-boundary-tối-ưu-đúng-cách)
- [P2.19 - Performance promotion gates](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p219--recommended-performance-promotion-gates)
- [P3.7 - Generated conformance corpus and test matrix](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p37--generated-conformance-corpus-và-test-matrix-control)

Goal:

Finish the shared Rust execution substrate before promotion. Rust must own one
authoritative market/account/order/lifecycle state for every native-event
workload that will later be eligible for Rust-first routing. Python remains the
public facade, strategy-research layer, report adapter, and executable oracle;
it must not retain a competing execution state or force an execution replay.

This phase is intentionally a **completion and conformance phase**, not an
automatic-backend-promotion phase. `backend="auto"` remains Python-first until
the individual Phase 54B workload gates pass.

#### 54A.5.1 - One Rust Execution Core And Compatibility Adapters

**Status: completed on `feat/51-native-rust-production-core`.**

Implementation:

- Retired the compiled `legacy::ReactiveSession` / `PreparedMarketData`
  runtime. The legacy module now retains only frozen R1/R2 integer ABI
  constants; its former accounting, matching, and session state machines are
  removed from the Rust build.
- Kept public PyO3 `PreparedMarketCore` and `ReactiveSessionCore` names and
  eight-column input shape stable. They are now compatibility facades over a
  one-symbol `FullMarketData` and `LegacyFullSessionAdapter`, whose only
  mutable execution state is `FullSession`.
- Added a mechanical R1/R2-to-API-0.4 command translator at the binding
  ingress. It preserves action remapping, GTC/immediate constraints,
  reduce-only, command order, and mask-aware `AMEND`; unsupported expiry,
  funding, and legacy liquidation semantics fail closed rather than silently
  acquiring different full-contract behavior.
- Added legacy output projection at the binding egress. Historical scalar,
  fill, event, and active-order schemas remain compatible while all lifecycle
  mutation, margin, fee, fill, and position work occurs in `FullSession`.
- Fixed a core replacement-chain defect uncovered by the adapter migration:
  `REPLACE a -> b -> c` now keeps all existing external aliases, so a later
  `CANCEL a` resolves the live `c` order. The fix lives in `FullSession`, not
  in an adapter-side alias table.

Evidence:

- Added `tests/native_event/test_phase54a5_one_rust_execution_core.py`:
  direct 8-column compatibility versus 16-column `FullReactiveSessionCore`
  parity covers bar zero, amend-mask handling, replace, reduce-only exit,
  active-order projection, reset, and fail-closed funding/liquidation inputs.
- Added a pure Rust replacement-chain alias invariant to
  `quantbt-engine::session` tests.
- `cargo test --workspace` passed: 40 Rust tests.
- `cargo clippy --workspace --all-targets -- -D warnings` passed.
- Fresh editable native wheel build passed via `maturin develop --release`.
- Focused native regressions passed: `53 passed`.
- Full native-event suite passed: `211 passed, 2 skipped`.

Boundary:

- This completes the one-runtime ownership lock. It does **not** yet define
  the versioned typed `NativeExecutionRequestV1`, common portfolio/package
  tape ingress, or zero-Python-object score output. Those remain the explicit
  work of 54A.5.2 through 54A.5.6.

- Make `quantbt_engine::FullSession` the sole Rust owner of market state,
  instrument constraints, positions, cash/equity, fees, funding, margin,
  liquidation, order lifecycle, trace counters, and terminal state for every
  native execution route eligible for promotion.
- Collapse the old R1/R2 `legacy::ReactiveSession` runtime into a compatibility
  adapter over `FullSession`, or retire it only after exact transition,
  accounting, sparse-wake, and lifetime parity proves that no public consumer
  depends on its independent state machine.
- Preserve legacy Python endpoint signatures and historical contract
  translators. A legacy input may be translated at the ingress boundary, but
  it must not cause a second Rust lifecycle implementation or a Python shadow
  accounting loop.
- Keep all execution contracts versioned. The complete resolved contract,
  including event clock, fill/gap/ambiguity policy, funding phase,
  quantization, liquidation priority, and close policy, must travel into the
  Rust request as one immutable value; unsupported fields fail closed.

#### 54A.5.2 - Typed Native Execution Request And Workload Tapes

Introduce one versioned internal request family, conceptually:

```text
PreparedMarketCore + InstrumentTable + AccountModel + ExecutionContract
    + OutputProfile + WorkloadPayload
    -> NativeExecutionRequestV1
```

`WorkloadPayload` is a tagged typed payload, never a Python callback hidden in
an untyped dictionary:

- `CommandTapeV5` for explicit static orders;
- `StrategyIRV1` plus immutable numeric signal/parameter tape;
- `PortfolioTargetTapeV1` for prepared target-unit rebalances;
- `PackageTapeV1` for prepared multi-leg transaction intent.

Requirements:

- The API-0.4 flat-array translator remains a compatibility ingress only.
  `CommandTapeV5` becomes the canonical execution representation consumed by
  the shared engine.
- String IDs, symbols, order IDs, policy enums, timestamps, quantity/price
  constraints, and contract settings are normalized once before the hot loop.
- Portfolio and package tapes must be able to enter the same `FullSession`
  lifecycle without direct position mutation or a separate account loop.
- The request has a deterministic fingerprint covering market, instruments,
  contract, workload tape, output profile, and native protocol/ABI versions.

**Status: completed on `feat/51-native-rust-production-core`.**

Implementation:

- Added the pure-Rust `quantbt-execution` workspace crate and its immutable,
  versioned `NativeExecutionRequestV1` contract. A request contains exactly one
  prepared `FullMarketData`, normalized `InstrumentTableV1`, `AccountModelV1`,
  fail-closed `ExecutionContractV1`, output profile, typed workload payload,
  and deterministic request/protocol provenance.
- `CommandTapeV5` is now the canonical static representation. The API-0.4
  16-column arrays are translated once at the PyO3 compatibility ingress, then
  `FullSession::run_typed_score`, `run_typed_compact`, or `run_typed_audit`
  executes that tape. No second array-driven lifecycle/accounting loop remains
  on the full static route.
- Implemented typed `CommandTapeV5`, `StrategyIrWorkloadV1`,
  `PortfolioTargetWorkloadV1`, and `PackageTapeV1` variants. Strategy IR
  compiles to its immutable canonical tape at request construction. Portfolio
  and package variants retain preflight/planning provenance and lower only to
  the shared session tape; neither may mutate positions or run a separate
  account loop.
- Each `execute()` creates one fresh Rust-owned `FullSession`. Therefore a
  reusable request never retains account/order/lifecycle state across runs.
  The fingerprint covers timestamps, OHLCV, volume, funding rate/mask,
  instrument sizing/leverage/fee, account model, contract, output profile,
  exact workload data/provenance, and generated ABI/registry versions.
- Added additive `NativeExecutionRequestCore` PyO3 construction for static
  command tapes and declarative strategy IR. It crosses Python-to-Rust once per
  `execute()` and has no callback or per-bar Python boundary. Existing public
  API-0.4 session classes and endpoint routing are unchanged.

Evidence:

- Added `tests/native_event/test_phase54a5_typed_execution_request.py`.
  It locks typed request versus API-0.4 full-session parity for equity,
  positions, fees, turnover, funding, margin, fill/event trace, scalar
  accounting, fresh-account repeated execution, score-output materialization,
  strategy-IR compilation, bad contract/tape rejection, and API-0.4 translator
  use.
- Pure Rust request tests lock static score/compact/audit parity, fingerprint
  invalidation for market/instrument/contract/output changes, one-time IR tape
  compilation, portfolio/package shared-session entry, and pre-execution
  rejection of invalid tape/contract mappings.
- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D
  warnings`, and `cargo test --workspace` passed (`45` Rust unit tests).
- Fresh editable extension build passed via `maturin develop --release`.
  Focused Phase 54A.5 tests passed: `8 passed`. Full native-event regression
  passed: `216 passed, 2 skipped`.

Boundary:

- This is an internal ABI-0.5 substrate, not a backend promotion. `auto`
  remains Python-first and no existing endpoint changes its public signature or
  execution route.
- The new PyO3 request currently adapts result data into a cold-path `PyDict`.
  Versioned typed SoA score/compact/audit buffers, cache ownership/budgets,
  batch public ingress, and public portfolio/package typed routes remain the
  explicit work of 54A.5.3 through 54A.5.6; they are not silently claimed here.

#### 54A.5.3 - Rust-Owned State Across Static, IR, Batch, Portfolio, And Package

**Status: completed on `feat/51-native-rust-production-core`.**

- Static tape: one prepared Rust session executes the entire tape; no Python
  per-bar transition, no Python ledger recomputation, and no audit replay.
- Strategy IR: compile supported declarative strategies inside Rust from a
  bounded program and numeric signal tape. The existing templates
  (`signal_target`, grid level, periodic DCA, fixed bracket) remain bounded
  and inspectable; arbitrary Python callbacks are not falsely represented as
  native programs.
- Batch/WFO: one Rust-owned prepared market is shared across scenarios/folds;
  score batches retain scalar columns only, while selected candidates are
  explicitly rerun in compact/audit mode.
- Portfolio/package: implement the shared tape/session entry point and state
  ownership now, but keep policy-by-policy public certification and promotion
  for Phase 54B.3/54B.4. This prevents those phases from creating another
  bridge or another accounting loop.
- A Python callback remains a compatibility workload. It may cross the
  boundary only at declared callback or sparse-wake points. An every-bar
  callback cannot honestly be described as fully native and must retain that
  classification in metadata and benchmarks.

Implementation completed:

- Added `NativeExecutionTemplateV1`: one immutable Rust owner for the prepared
  market view, instruments, account model, execution contract, and content
  fingerprint. `NativeExecutionRunnerV1` owns the only mutable `FullSession`
  buffer and deterministically resets account, order, lifecycle, margin, and
  trace state before every independent workload.
- Added `FullSession::new_window(...)`. An OOS fold now has a local bar clock
  and fresh account snapshot over a shared `Arc<FullMarketData>` range. It is
  bit-for-bit parity-tested against the former materialized `FullMarketData`
  window, including fills, fee, funding, paths, and events, while avoiding the
  OHLCV/funding copy.
- `BatchTemplate` now owns the execution template rather than duplicate market
  and account fields. Each batch worker creates one runner and reuses it across
  scenarios; Strategy IR close projections are materialized once per template
  or fold, not once per scenario. The typed projection is bound to the exact
  template fingerprint and symbol, so a projection from another market view is
  rejected before command compilation. `score_fold_batch` reports
  `market_windows_created=0`, logical view bytes, physical source bytes, and
  `market_view_shared=true` so no-copy behavior is observable.
- Static, strategy-IR, portfolio-target, and package workloads all enter the
  same typed request/runner/session path. A shared-runner conformance test
  proves that a portfolio target cannot leak its long position into a following
  package short, and that a replay starts from the same clean state.

Evidence:

- `cargo fmt --all`, `cargo test --workspace`, and
  `cargo clippy --workspace --all-targets -- -D warnings` passed (`47` Rust
  unit tests).
- Fresh editable extension build passed through `maturin develop --release`.
  Focused typed-request, compatibility-core, and fold-batch Python regressions
  passed: `24 passed`. Full native-event regression passed: `216 passed, 2
  skipped`; full QuantBT suite passed: `882 passed, 3 skipped`.

Boundary:

- This completes shared native ownership and no-copy fold preparation only.
  It does not promote any public endpoint, change `backend="auto"`, or claim
  arbitrary Python callbacks are native workloads.
- Typed SoA result ownership, cache budgets/lifetime controls, public prepared
  batch ingress, and endpoint-level portfolio/package promotion remain the
  explicit work of 54A.5.4 through 54B. No Python execution replay is added by
  this phase.

#### 54A.5.4 - Flat Output, Cold-Path Adaptation, And No Replay

- Replace hot-path `PyDict`, nested row vectors, per-fill Python objects, and
  unconditional pandas construction with versioned typed native outputs:
  `NativeScoreOutputV1`, `NativeCompactOutputV1`, and
  `NativeAuditOutputV1`.
- Score output contains only scalar/online metrics required by the caller. It
  must not materialize equity paths, audit rows, `DataFrame`s, or a Python
  dictionary merely to calculate a score.
- Compact/audit output uses contiguous typed SoA buffers with explicit owner
  lifetime. Python adapts those buffers into `BacktestResultV2`, plots, and
  reports only after execution, and only for the report level requested.
- The Rust audit result is the production artifact. Python oracle comparison
  is an optional verifier/sampled test path, never an implicit second run.

**Status: completed on `feat/51-native-rust-production-core`.**

Implementation:

- Added versioned pure-Rust `NativeScoreOutputV1`, `NativeCompactOutputV1`,
  `NativeAuditOutputV1`, and `NativeExecutionOutputV1`. Output requirements
  are resolved once from the profile before the canonical typed session loop;
  profile selection changes only retention, never lifecycle, fill, accounting,
  funding, margin, or liquidation semantics.
- `score` now retains only scalar terminal accounting plus one final-position
  vector. It allocates neither dense paths nor fill/event columns and copies
  final positions only once after the last bar rather than cloning positions on
  every bar. `compact` retains flat bar-major account columns, while `audit`
  adds typed `i64` lifecycle IDs and `f64` fill columns with no nested rows.
- `NativeExecutionRunnerV1` and static/IR/batch/portfolio/package typed
  workloads consume the new output family. API-0.4 `StaticTapeOutput` is now a
  move-only compatibility adapter from the authoritative typed result; it does
  not replay the engine or clone result vectors in production paths.
- Added additive PyO3 `NativeScoreOutputV1`, `NativeCompactOutputV1`, and
  `NativeAuditOutputV1` objects behind
  `NativeExecutionRequestCore.execute_typed()`. Rust `Vec` buffers move
  directly into NumPy-owned contiguous arrays through `PyArray1::from_vec`.
  Each object exposes deterministic request/output provenance, retained payload
  bytes, one-pass boundary metadata, scalar fields, and only the columns its
  profile declares. `as_dict()` and the retained `execute()` method are explicit
  cold-path compatibility adapters.
- Documented the ABI-0.5 typed output boundary in
  `docs/native_event_rust_full_contract.md` and `docs/native_strategy_ir.md`.
  Result/report construction remains explicit; no public endpoint or
  `backend="auto"` route changed in this phase.

Evidence:

- Extended `tests/native_event/test_phase54a5_typed_execution_request.py` to
  lock score/compact/audit typed-class selection, profile-specific retention,
  `float64`/`int64` SoA dtypes, byte accounting, cold `as_dict()` parity,
  legacy `execute()` parity, empty audit columns, request-GC lifetime, and
  repeated-run/session-reset immutability.
- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D
  warnings`, and `cargo test --workspace` passed (`47` Rust tests).
- Fresh `maturin develop --release` passed. Focused typed-request tests passed
  (`8 passed`), full native-event regression passed (`219 passed, 2 skipped`),
  and the full QuantBT suite passed (`885 passed, 3 skipped`).

Boundary:

- This is an additive ABI-0.5 request/result surface, not a silent public
  backend promotion. Existing API-0.4 dictionary/session methods and the
  stable mapping-based `RustNativeIRRunner` facade remain compatibility paths
  until their own public promotion gates.
- `native_execution_output_bytes` measures retained numeric payload bytes, not
  Python object overhead or allocator capacity. Audit streaming/chunk limits,
  prepared-cache budgeting, public prepared batch ingress, and endpoint-level
  portfolio/package promotion remain the explicit next work of 54A.5.5 and
  54B; no Python execution replay was introduced here.

#### 54A.5.5 - Prepared Ownership, Cache, Reset, And Boundary Budget

- `PreparedMarketCore` owns one immutable, contiguous market tape and a
  validated instrument table per content fingerprint. Its lifetime is explicit
  and independent of transient Python `DataFrame`s.
- Reuse prepared market/instrument state across static reruns, IR scenarios,
  WFO folds, and service loops without duplicate pandas normalization or
  market-array packing per trial. Fold-local account reset/window semantics
  remain causal and must not leak positions/orders across folds.
- Cache entries have byte budgets, ref/lifetime diagnostics, deterministic
  clear/reset behavior, and signatures covering all result-affecting arrays
  and constraints. No cache uses object identity as a correctness substitute.
- Define and test a boundary budget: static/IR/full batch is one Python-to-Rust
  call per run/batch; sparse callbacks cross once per wake chunk; arbitrary
  every-bar callbacks report their crossing count honestly.

**Status: completed on `feat/51-native-rust-production-core`.**

Implementation:

- Added `NativeExecutionTemplateCore` as the output-independent ABI-0.5
  immutable owner for prepared market, instrument, account, and event-contract
  state. It exposes a zero-copy `window(start, end)` whose local bar clock is
  independent of the source tape, preventing a fold-local command tape from
  accidentally using global bar offsets. The immutable tape stays in one Rust
  `Arc`; no market arrays are rebuilt for a cached template/window.
- Added `NativeExecutionRunnerCore` over one `NativeExecutionRunnerV1` and an
  immutable request. Every execution resets account/orders/indexes/cursors
  before running, tracks native generation and run count, releases the GIL for
  Rust-only execution, and produces one typed output in one boundary call.
  `account_and_orders`, `scenario_state`, `result_buffers`, and `full_rebuild`
  are explicit scopes. `account_only` fails closed because it would leave an
  ambiguous active-order/lifecycle state.
- Added `NativeExecutionPreparationCache` in `quantbt.preparation`: L2 market,
  L3 template, and L4 immutable static/IR request tiers use SHA-256 content
  signatures and bounded LRU budgets split 60%/15%/25%. Keys include all market
  arrays (timestamps, OHLCV, funding, event mask), symbols, instrument/account
  values, contract, program/signal/parameter or command-tape data, and output
  profile. Cache diagnostics report hits/misses, resident bytes, eviction/reuse,
  ingress copies, tier budgets, and generation. Object identity is never used.
- Strengthened `PreparedObjectCache.clear(force=False)` so a normal clear
  refuses pinned entries and returns deterministic released-byte/generation
  provenance. Results own detached NumPy output buffers, therefore clearing a
  cache or releasing runner scratch capacity cannot invalidate an earlier
  result. Source-tree and temporary local-package mirrors are kept identical
  for the preparation modules while both import paths remain supported.

Evidence:

- Added `tests/native_event/test_phase54a5_prepared_cache_boundary.py`:
  market/template/request hit reuse; invalidation for volume, funding, close,
  fee, contract, and output profile; cached-versus-direct typed-output parity;
  bounded tier diagnostics; pin/clear behavior; zero-copy local window; runner
  generation/reset/no-state-leak behavior; result lifetime after cache clear;
  and static/IR one-boundary-call assertions.
- Added a pure Rust `quantbt-execution` test for local window tape layout,
  shared market ownership, repeated runner parity, and explicit reset
  generation. It caught and fixed a real window bug: typed command translation
  now uses the template's local bar count rather than the source market's full
  length.
- `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D
  warnings`, `cargo test --workspace`, a fresh release `maturin develop`, and
  the focused ABI-0.5 Python suite passed after the change.

Boundary:

- Static/IR requests and reusable runners now meet the one Python-to-Rust call
  per run boundary. Sparse callbacks and arbitrary every-bar callback drivers
  retain their separate published boundary counters; this phase does not make
  an unsupported callback look fully native.
- Cache budget is for cache-owned resident entries. Explicitly retained Python
  market/template/request handles may correctly outlive an LRU eviction, and
  diagnostics never pretend they were freed. Audit streaming/chunk limits,
  shared public prepared-batch ingress, and endpoint-level portfolio/package
  promotion remain 54A.5.6/54B work, not hidden behavior changes here.

#### 54A.5.6 - Differential Corpus, Performance Baseline, And Exit Gate

The canonical corpus must compare the Python oracle, legacy compatibility
adapter, typed Rust request, and prepared Rust reuse path for the same
contract. It must lock:

- accepted/rejected commands and rejection reasons;
- fill time, price, quantity, reason, ambiguity, parent/OCO/TIF transitions;
- position, cash/equity, fee, slippage, funding, margin, liquidation, and
  per-symbol/package attribution where the workload supports them;
- trace/fingerprint determinism, reset/lifetime behavior, and legacy endpoint
  result/report compatibility;
- score/compact/audit accounting parity, including the absence of a hidden
  audit replay;
- prepared versus non-prepared, single versus batch, and repeated-run cache
  parity.

Benchmark evidence must separately record E0 static, E1 callback, E2 sparse
callback, E3 IR, E4 portfolio, E5 package, and E6 batch/WFO workloads with
Python/Rust call counts, copies, engine time, adaptation time, peak/steady RSS,
and result fingerprints. No speed claim or promotion is permitted until the
corresponding parity and installed-wheel gate passes.

Exit gate:

```text
One authoritative Rust execution/accounting state exists for the promotable
native-event workload family;
typed request/output contracts are versioned and fingerprinted;
legacy compatibility is adapter-only and parity-locked;
static/IR/batch have no per-bar Python execution boundary;
portfolio/package enter the shared Rust session through typed tapes;
score has no dictionary/dataframe/audit materialization or forced replay;
prepared ownership/cache/reset is deterministic and bounded;
the full Python-oracle/legacy/typed/prepared differential corpus passes.
```

Non-goals and fail-closed scope:

- This phase does not auto-promote any workload and does not remove the Python
  oracle, historical translators, or public endpoint compatibility.
- It does not claim arbitrary Python strategy code is compilable to Rust.
- It does not certify venue-exact L2/queue/partial-fill simulation,
  inverse/quanto/options accounting, universal portfolio margin, or Nautilus
  execution. Those require separate contracts and must remain explicitly
  unsupported/fallback paths.
- Native intrabar, vectorized, options, and Nautilus backends retain their own
  contracts. They are not silently redirected into the Rust native-event core.

**Status: completed on `feat/51-native-rust-production-core`.**

Implementation:

- Added the versioned corpus at
  `tests/corpus/native_event/phase54a5_full_session.json` and the four-route
  differential harness at
  `tests/native_event/test_phase54a5_differential_corpus.py`. The harness
  compares Python oracle, public API-0.4 Rust compatibility, direct ABI-0.5
  typed request, and prepared ABI-0.5 reusable runner for deterministic
  multi-symbol/OCO/funding and IOC/GTD/reduce-only lifecycle cases.
- The corpus locks raw accounting paths, fill/event SoA columns, accepted and
  rejected command outcomes, canonical trace/fingerprint, reset/lifetime
  behavior, score/compact/audit no-replay parity, static/IR/batch boundary
  counts, and typed portfolio/package preflight parity.
- Fixed three exposed cold-path projection mismatches without changing engine
  accounting: semantic order-ID decoding in event parity, relationship/reason
  fallback from immutable command metadata into the canonical trace, and
  event-specific rejection reasons on Python lifecycle events. The canonical
  trace fingerprint now uses a 12-decimal projection to absorb equivalent f64
  accumulation-order artifacts under the public parity contract; raw accounting
  data remains unrounded and parity-checked at `1e-12`.
- Added
  `benchmarks/native_event/benchmark_phase54a5_exit_gate.py`. It emits
  reproducible E0/E3/E6 engine-time versus cold-adaptation-time, current/peak
  RSS, call/callback/copy counters, output fingerprints, and an explicit
  non-promotion record for E1/E2/E4/E5.

Evidence:

- Focused trace plus four-route corpus: `11 passed`; full native-event suite:
  `229 passed, 2 skipped`; complete QuantBT suite: `895 passed, 3 skipped`.
- `cargo fmt --all -- --check`, strict `cargo clippy`, and `cargo test
  --workspace` passed (`48` Rust unit tests); a fresh release
  `maturin develop` installed the ABI-0.5 extension before Python regression.
- The frozen 2,000-bar / 64-scenario artifact at
  `benchmarks/native_event/results/phase54a5/exit_gate.json` and its checksum
  manifest record machine-specific medians: prepared E0 score `6.57M` bars/s
  low churn and `1.20M` high churn, E3 IR score `5.99M` bars/s, and E6 shared
  batch `10.93M` simulated bars/s. All measured rows passed their documented
  parity checks; these are not universal endpoint speed claims.

Boundary:

- This phase is a certification lock, not a default-backend promotion. Rust
  stays explicit/experimental and `backend="auto"` behavior remains unchanged.
- E1 arbitrary callbacks, E2 sparse reactive callbacks, E4 full portfolio
  endpoints, and E5 full package endpoints have no synthetic performance
  claim. Their Phase 54B domain-specific endpoint, installed-wheel, rollback,
  and RSS gates are still mandatory.

Dependency for Phase 54B:

Phase 54B may promote only a workload whose typed request/output path is
complete under this phase and whose domain-specific Phase 54B parity,
installed-wheel, performance, RSS, rollback, and public endpoint gates pass.

---

### Phase 54B - P3 Rust-First Promotion, Migration, Cleanup, And Final Release

**Status: complete (54B.1 through 54B.4).**

Detailed guide:

- [P3.5 - Workload-aware backend promotion](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p35--auto-backend-promotion-theo-workload)
- [P3.11 and P3.12 - Cleanup and exit](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p311--cleanupdeletion-plan)
- [Definition of dual native backend](quantbt_p0_p3_native_rust_upgrade_blueprint.md#14-definition-of-dual-native-backend-cho-quantbt)
- [Final acceptance matrix](quantbt_p0_p3_native_rust_upgrade_blueprint.md#15-final-acceptance-matrix)
- [Recommended promotion order](quantbt_p0_p3_native_rust_upgrade_blueprint.md#16-recommended-promotion-order)
- [Immediate implementation backlog](quantbt_p0_p3_native_rust_upgrade_blueprint.md#17-immediate-implementation-backlog)

Goal:

Promote Rust from an explicit experimental accelerator to the canonical
production execution core for every certified workload, retain Python as the
executable oracle/fallback, remove obsolete duplicate hot paths, and publish a
reversible release with no ambiguous backend behavior.

Prerequisite:

Phase 54A.5 must be complete. Promotion is prohibited while a candidate route
still depends on an independent legacy Rust state machine, Python execution
shadow state, untyped request/dictionary hot path, forced audit replay, or an
uncertified portfolio/package bridge.

Scope:

- Replace the original equal-default dual-backend policy with a versioned
  Rust-first production promotion table:
  - certified static tape, strategy IR, and batch/WFO resolve to Rust;
  - certified portfolio target modes resolve to Rust;
  - certified package/arbitrage policies resolve to Rust;
  - hybrid Python callback drivers still use Rust-owned execution state;
  - uncertified or unavailable routes fall back to Python only with explicit
    structured reason and declared maturity.
- Preserve `backend="python"` as explicit oracle, debugging, historical replay,
  and emergency operation. Preserve `backend="rust"` as strict fail-fast.
- Make automatic decisions deterministic from contract, workload, profile,
  scale, account model, installed descriptor, platform, and versioned promotion
  table. Record selection and rejected-candidate reasons in every result.
- Add tested emergency disable/rollback controls without remote nondeterminism.
- Run full differential, installed-wheel, corpus, fuzz smoke, lifetime, memory,
  E0-E6, public endpoint, WFO, portfolio, arbitrage, and report regression gates.
- Run real representative alpha/service workloads and archive stakeholder
  bundles containing configs, plan/trace fingerprints, performance phase data,
  metrics, fills/orders/accounting, and backend evidence.
- Remove only paths proven unused by counters/import graph and protected by
  migration tests: manual root mirror, Python shadow-state, nested Rust rows,
  score-via-audit, forced production replay, expired compatibility shims, and
  monolithic duplicate execution branches.
- Do not remove the readable Python oracle, canonical conformance corpus,
  explicit Python backend, or historical contract translators.
- Publish release notes that distinguish native execution, hybrid callbacks,
  unsupported contracts, OHLC intrabar limitations, package atomicity model,
  platform coverage, and rollback procedure.

Required tests and evidence:

- Same certified request under `auto` resolves to Rust deterministically and
  produces the same canonical trace/accounting as explicit Rust and the Python
  oracle.
- Missing/mismatched/disabled native routes resolve exactly as policy states;
  internal Rust invariant failures never silently rerun Python.
- Public score/research/audit results, metrics, quick plots, reports, fills,
  diagnostics, metadata, and retained-result lifetimes remain compatible.
- Static/IR/batch production paths have O(1) Python/Rust calls; sparse paths
  call only at wake points; arbitrary callback costs are reported honestly.
- Final release tests pass from clean published-candidate wheels on all declared
  Python/platform combinations.
- Deletion manifest proves every removed path has a replacement, migration
  test, rollback ref, and no public import consumer.

Final release gate:

```text
P0 semantics, trace, ledger, numeric, portfolio, and package gates PASS;
P1 plan, preparation, ownership, boundary, audit, cache, and lifetime gates PASS;
P2 Rust engine, IR, batch, portfolio/package, performance, and RSS gates PASS;
P3 source, registry, wheel, CI, security, docs, migration, and cleanup gates PASS;

Rust is the canonical production execution core for certified workloads;
Python remains a first-class executable oracle and emergency fallback;
no normal run switches mutable execution ownership between languages;
no capability or speed claim exceeds installed-wheel evidence.
```

#### 54B.1 - Versioned Promotion Policy, Deterministic Routing, And Rollback

**Status: complete (2026-08-20).**

Detailed guide to read before every implementation decision:

- [P3.5 - Workload-aware auto promotion](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p35--auto-backend-promotion-theo-workload)
- [P3.8 - Stable diagnostics and observability](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p38--stable-diagnostics-và-observability-contract)
- [P3.6 - Benchmark governance](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p36--benchmark-governance-và-regression-ci)
- [P2.19 - Correctness before performance promotion](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p219--recommended-performance-promotion-gates)

Goal:

Replace the current binary selector (`auto` always Python, `rust` explicit) with
a versioned, data-driven decision contract. The policy must know a workload,
event contract, output profile, account model, platform/wheel descriptor,
symbol count, and declared strategy mode. It must never infer promotion merely
from a native extension being importable.

Implementation scope:

- Add a single machine-readable promotion table and typed resolver result. A
  decision contains requested backend, `backend_policy`, resolved backend,
  workload ID, matched rule ID/table version, maturity, fallback/rejection
  code, exact wheel/ABI/contract fingerprints, and emergency-switch state.
- Preserve stable explicit behavior: `backend="python"` is the executable
  oracle; `backend="rust"` is strict fail-fast; `backend="auto"` is the only
  promotion candidate. A Rust internal invariant failure must propagate and
  must never re-run Python silently.
- Support deterministic local rollback only: an explicit config policy plus
  `QUANTBT_DISABLE_NATIVE=1` and bounded
  `QUANTBT_NATIVE_PROMOTION_MAX=<stage>`. No remote flag, wall-clock choice,
  benchmark auto-calibration, random routing, or network telemetry is allowed.
- Publish the resolved decision in every eligible result as a versioned
  diagnostics object. Diagnostics are structured data, not log parsing, and
  default logging remains one summary per run rather than per-bar output.
- Start from conservative Stage B candidates only: static command tapes, native
  IR v1, and shared native batch/WFO requests. Python callback/replay,
  unsupported contracts, unavailable/mismatched wheels, non-certified account
  models, and E4/E5 endpoint routes stay Python with an explicit reason.
- Keep product registry generation as the only source for capability/maturity
  metadata; promotion table updates must be checked into the same review as
  their differential and benchmark evidence.

Required tests and evidence:

- Exhaustive decision snapshot matrix for explicit Python/Rust/auto,
  disabled/missing/mismatched extensions, platform mismatch, unsupported
  contract/profile/account model, threshold boundary, and environment rollback.
- Same request/config/environment always produces the same resolved backend,
  plan fingerprint, and decision metadata. Changing a relevant capability,
  promotion table version, or rollback input changes the decision fingerprint.
- Explicit Rust failure proves no Python execution occurred; auto fallback
  carries a stable reason code; `QUANTBT_DISABLE_NATIVE=1` wins over every
  promotable rule.
- Existing endpoint arguments remain source-compatible and default to the
  previous Python behavior until the later route-specific promotion phase.

Exit gate:

```text
Promotion decision is deterministic, versioned, observable, and fail-closed.
No public workload is promoted by this phase alone.
Python remains the unchanged default until its route passes Phase 54B.2/54B.3.
```

Completion evidence:

- Added generated `promotion_policy` table `native-event-promotion-v1` to the
  native product registry. It declares staged candidates for static tape,
  native IR, portfolio target, and package transaction, but every rule remains
  disabled and every workload remains non-promoted in this phase.
- Added one pure, dependency-light resolver shared by planning and the legacy
  native backend selector. It evaluates requested backend, user policy,
  workload/contract/profile/account shape, platform, capability snapshot,
  `QUANTBT_DISABLE_NATIVE`, and `QUANTBT_NATIVE_PROMOTION_MAX` before market
  preparation. `auto` does not probe Rust while the table is locked.
- Added optional `backend_policy` propagation through endpoint, V2 facade,
  static lifecycle API, native-event config, plan fingerprint, and result
  metadata. Existing callers retain `auto -> python`; explicit Rust remains
  fail-fast and no internal failure silently reruns Python.
- Added `native_event_promotion_v1` provenance with policy/table/registry
  fingerprints, contract, workload maturity, rule ID, rollback state, and
  wheel/API/capability evidence when a native probe occurs.
- Rebuilt the local API-0.4 wheel after the product-registry fingerprint change
  and refreshed checked benchmark-manifest registry references without changing
  the measured baselines.
- Tests passed: `34` focused promotion/planning/product/dual-backend checks;
  `235 passed, 2 skipped` native-event regression; Rust workspace fmt/clippy
  and `48` unit tests; full `PYTHONPATH=. poetry run pytest -q` result
  `901 passed, 3 skipped`.

#### 54B.2 - Static, Native-IR, And Batch Rust-First Public Routes

**Status: completed (2026-08-20) on `feat/51-native-rust-production-core`.**

Detailed guide to read before every implementation decision:

- [P3.5 Stage B - Auto static/IR](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p35--auto-backend-promotion-theo-workload)
- [P3.7 - Generated conformance corpus](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p37--generated-conformance-corpus-và-test-matrix-control)
- [P3.8 - Result diagnostics](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p38--stable-diagnostics-và-observability-contract)
- [P3.9 - User migration and capability documentation](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p39--documentation-compatibility-table-và-user-migration)

Goal:

Promote only the certified E0 static, E3 native-IR, and E6 batch/WFO workload
families through stable public facades. The Rust execution session remains the
only mutable lifecycle/accounting owner for a promoted run; Python adapts typed
output only on the requested cold report path.

Implementation scope:

- Wire the Phase 54B.1 resolver into the existing order-command and native-IR
  facades without renaming or removing current endpoints. Existing callers that
  omit new policy parameters retain their current compatible behavior.
- Promote static tape only for contract/profile/account/platform rows proven by
  the 54A.5 corpus and installed-wheel matrix. Resolve every other static row
  to Python with a structured reason rather than a partial Rust route.
- Promote bounded `NativeStrategyIR` score/compact/audit and shared batch/WFO
  only when the program, signal/parameter matrix, causal fold window, and
  output profile are supported by the typed request contract. One run/batch
  has one Python-to-Rust boundary, zero audit replay for score, and zero market
  copies per batch scenario.
- Preserve reporting behavior: `show_metrics`, reports, plots, fills, order
  ledgers, trace, result lifetime, and metadata use the typed Rust output for
  promoted audit/compact runs. Python oracle execution is optional verifier
  sampling only, never a normal second run.
- Keep arbitrary Python callback and reactive execution on the explicitly
  labeled compatibility route. Do not force callbacks into IR, and do not claim
  their bars are native throughput.

Required tests and evidence:

- For each promoted static/IR/batch request: auto == explicit Rust == Python
  oracle on canonical trace, accepted/rejected lifecycle, accounting, report
  outputs, and retained-result lifetime.
- Public endpoint and low-level runner parity cover score, compact, audit,
  V2/V3 clocks, one/multi-symbol static tape where certified, Grid/DCA/bracket
  IR, batch worker counts, causal fold reset, and selected audit rerun.
- Cold adaptation is benchmarked separately from engine time. Boundary/copy
  counters, score no-replay, and RSS plateau gates are checked on installed
  extension artifacts, not only the source tree.
- Run complete API compatibility regression so unsupported user code keeps the
  old Python route and all historical endpoint imports/options remain valid.

Exit gate:

```text
Only certified E0/E3/E6 public requests may resolve Rust-first under auto.
All non-certified callback and domain routes remain Python, with explicit
decision metadata. No portfolio/package endpoint is promoted in this phase.
```

Completion evidence:

- Promoted the generated `native-event-promotion-v2` Stage-B rows only:
  - static V2/V3 command tapes at `>= 10,000` bars;
  - bounded `NativeStrategyIR` v1 and shared batch/fold scoring at `>= 2,000`
    bars.
  The resolver records `minimum_bars`, matched rule, exact table fingerprint,
  and a stable fallback reason such as `below_promotion_min_bars` in
  `native_event_promotion_v1` and the immutable execution plan.
- Kept `native_backend="python"` as the executable oracle and
  `native_backend="rust"` as strict fail-fast. `auto` uses Rust only on a
  certified row with an executable exact-pair wheel. Callback/reactive,
  portfolio, and package/arbitrage routes remain Python by policy, never by a
  silent partial fallback. `QUANTBT_DISABLE_NATIVE=1` and
  `QUANTBT_NATIVE_PROMOTION_MAX=explicit_only` deterministically roll a local
  run back to Python.
- Added the stable `NativeIRExecutionRunner` public facade via
  `NativeEventBackend.prepare_native_strategy_ir(...)`. It performs one native
  run/batch with Rust as the only mutable lifecycle/accounting owner. Score and
  compact output do not replay audit; public results adapt typed Rust buffers on
  the cold path. The full audit path projects command identity and lifecycle
  ledgers without rerunning execution.
- Fixed an actual full-contract IR drift discovered by the new corpus:
  `fixed_bracket` target-to-flat transitions must not be emitted as
  `reduce_only` because Python `sign(0) == 0`; Rust now matches that contract.
  The generic native-event parity normalizer also resolves cancel/reject target
  identities from the immutable source command, so raw event ledgers and
  canonical traces compare consistently.
- Added public differential coverage for static V2/V3 (including
  multi-symbol funding and quantity constraints), Grid/DCA/fixed-bracket IR,
  score/compact/audit profiles, selected audit rerun, batch worker determinism,
  and causal-fold fresh-state behavior. Exact `auto == explicit Rust == Python`
  accounting/lifecycle/canonical-trace parity passed.
- Added the reproducible public-route benchmark and governed manifest:
  `benchmarks/native_event/benchmark_phase54b2_public_routes.py`,
  `benchmarks/native_event/results/phase54b2/public_routes.json`, and
  `benchmarks/native_event/manifests/phase54b2_public_routes_v1.json`.
  Five warmed local repetitions recorded `0.741 ms / 2.70M bars/s` for a
  2,000-bar IR score versus Python `31.565 ms / 63,361 bars/s`; the 64-scenario
  batch reached `11.25M bars/s` with one boundary call and zero shared-market
  copies per scenario. Static public facade timing is intentionally reported
  separately and is not claimed as a generic Rust speedup because common
  pandas/report adaptation dominates it.
- Updated endpoint, capability, install, architecture, release, IR, README,
  public inventory, and benchmark-governance documentation to distinguish the
  local Stage-B policy from the core-only PyPI fallback policy.

Certification commands passed:

```bash
UV_CACHE_DIR=/tmp/quantbt-uv-cache poetry run maturin develop --release \
  --manifest-path rust/native_event/Cargo.toml
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run pytest -q \
  tests/native_event tests/native_event/contract
cargo fmt --manifest-path rust/Cargo.toml --all --check
cargo clippy --manifest-path rust/Cargo.toml --workspace --all-targets -- -D warnings
cargo test --manifest-path rust/Cargo.toml --workspace
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run pytest -q
```

Results: `245 passed, 2 skipped` native-event; Rust fmt/clippy plus all
workspace tests passed; full QuantBT regression `911 passed, 3 skipped`.

Boundary after Phase 54B.2:

- No correctness debt remains inside the promoted E0/E3/E6 rows under the
  declared local Linux/CPython exact-pair evidence.
- Static public audit/report construction remains a cold Python adaptation
  cost; it is transparent in the benchmark and is not used to claim a generic
  facade speedup. Any further report/trace optimization must retain the exact
  canonical-trace contract.
- Clean manylinux wheel matrix, published companion decision, and any
  portfolio/package Rust promotion remain explicit Phase 54B.3/B.4 work, not
  implied by this local Stage-B promotion.

#### 54B.3 - Portfolio/Package Domain Promotion And Institutional Certification

**Status: completed (certified explicit E4/E5 contracts; generic endpoint
auto-promotion intentionally remains out of scope).**

Detailed guide to read before every implementation decision:

- [P3.5 Stage C and Stage D](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p35--auto-backend-promotion-theo-workload)
- [P2.19 E4/E5 gates](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p219--recommended-performance-promotion-gates)
- [P3.7 generated corpus requirements](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p37--generated-conformance-corpus-và-test-matrix-control)
- [P3.8 observability contract](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p38--stable-diagnostics-và-observability-contract)

Goal:

Turn Phase 54A.5 portfolio-target and package typed tapes into either complete
Rust-first endpoint routes or explicit non-promotion results. Preflight parity
alone is not treated as full execution certification.

Implementation scope:

- Establish a shared native market/account/target/package request contract for
  each candidate E4/E5 endpoint. Rust must own target delta, constraints,
  fee/slippage, funding, margin, lifecycle, reservation/rollback, output, and
  trace for a promoted route; Python may only adapt cold outputs.
- Promote portfolio target modes individually, beginning with certified
  linear-quote-settled gross-cross `target_units` only. Each added sizing,
  rebalance, missing-price, funding, or margin mode gets its own registry row,
  corpus, parity profile, and rollback reason.
- Promote package/arbitrage policies individually, starting only with policies
  whose atomicity/reservation/hedge-after-primary semantics are fully modeled
  by the native session. Cross-exchange, inverse/quanto, venue-specific
  portfolio margin, and actual partial-fill dynamic hedging remain fail-closed
  unless a dedicated domain contract exists.
- Reconcile symbol and portfolio/package accounting: accepted targets/legs,
  turnover, fee, slippage, funding, margin, cash/equity, residual exposure,
  rejection/rollback state, and canonical trace must agree exactly with the
  Python oracle at the published tolerance.

Required tests and evidence:

- Generated/minimized corpus covers reversal, post-cost margin reject,
  stale/missing asynchronous prices, funding, liquidation, all-or-none
  rollback, sequential/best-effort/hedge-after-primary policy boundaries, and
  failure-to-no-orphan invariant.
- Native endpoint, typed request, prepared/non-prepared, and Python oracle
  match accounting and trace. Public reports reconcile per-symbol attribution
  to portfolio/package totals.
- E4/E5 benchmarks report engine and report-inclusive timing separately,
  active-position/order scaling, output retained bytes, peak/steady RSS, and
  no hidden Python replay. A candidate may be promoted only after its own
  installed-wheel correctness/performance budget passes.

Exit gate:

```text
Portfolio/package promotion is per exact registry row, never blanket.
Any incomplete domain semantics remains routed to Python with a stable reason.
```

Implementation and evidence:

- Added two immutable typed Rust requests backed by the shared
  `FullSession`, never by a second Python accounting state:
  `portfolio_target_market_v1` for bar-major `target_units`, and
  `package_atomic_market_v1` for one same-bar `AtomicBarSimulation` market
  package. Both are exposed explicitly through
  `run_portfolio_target_market(...)` and `run_atomic_package_market(...)`.
- The target contract is deliberately narrow: V2 next-bar-close, linear
  quote-settled gross-cross, finite `target_units`, canonical market price and
  one-way fee, target-row all-or-none admission, per-bar tradability/staleness,
  min quantity/notional, sequential post-cost free-margin checks, funding,
  intrabar/close liquidation, and canonical fill lifecycle. A rejected row
  retains all prior units; malformed non-finite target tape input fails before
  any session/account state is created.
- The package contract is deliberately narrow: one non-empty ordered package,
  known symbols, nondecreasing `venue_sequence`, exact market cost/margin
  preflight, and all-or-none bar-transaction rollback. It records
  `package_accepted`, rejection/transition codes, reservation/release, fee,
  and residual notional. It does not claim exchange-native order-list
  atomicity, queue/depth, partial fills, cross-venue settlement, sequential,
  best-effort, or hedge-after-primary semantics.
- `NativeExecutionPreparationCache` now content-signs the target/package tape
  together with every result-affecting prepared market/template array. A
  cached typed request is immutable, a fresh runner resets its state for every
  run, and a score/compact result cannot be silently converted into audit
  output. Audit adaptation is a cold `RustFullAuditResult` conversion and
  never replays Python execution.
- The product registry adds two `certified`, `auto_promotion=false` workload
  rows. Automatic routing remains `static_ir`; generic
  `QuantBTEndpoint.portfolio()` and `QuantBTEndpoint.arbitrage()` preserve
  their Python/native-portfolio behavior. The registry generator was also
  tightened so Rust preserves JSON scalar types in the semantic descriptor;
  the installed wheel and core now fail closed on any descriptor drift.
- Added the B3 contract suite and governed E4/E5 benchmark artifact:
  `tests/native_event/contract/test_phase54b3_portfolio_package_promotion.py`,
  `benchmarks/native_event/benchmark_phase54b3_portfolio_package.py`, and
  `benchmarks/native_event/results/phase54b3/portfolio_package.json`.
  It covers reversal, stale retry, post-cost rejection, invalid-input
  fail-fast, target/package all-or-none rollback, no orphan leg, funding,
  prepared versus direct parity, signature invalidation, score/compact/audit
  retention, direct audit-report adaptation, explicit/auto promotion policy,
  and native semantic-descriptor parity.
- The committed five-warm-run E4/E5 evidence is exact to `atol=1e-12` against
  the Python event oracle for equity, positions, fees, and funding. At
  2,000 bars x 8 symbols it records Rust score execution of 3.594 ms
  (556,551 bars/s) for target units and 3.512 ms (569,514 bars/s) for the
  atomic package; cold audit adaptation is reported separately. Both routes
  use one PyO3 boundary call, zero Python callbacks, zero ingress copies on
  reused contiguous arrays, and no steady-run RSS growth in the recorded
  artifact.

Certification commands passed after the final descriptor rebuild:

```bash
cargo fmt --manifest-path rust/Cargo.toml --all -- --check
cargo clippy --manifest-path rust/Cargo.toml --workspace --all-targets -- -D warnings
cargo test --manifest-path rust/Cargo.toml --workspace
UV_CACHE_DIR=/tmp/quantbt-uv-cache poetry run maturin develop --release \
  --manifest-path rust/native_event/Cargo.toml
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run pytest -q \
  tests/native_event tests/native_event/contract
MPLCONFIGDIR=/tmp PYTHONPATH=src:. poetry run pytest -q
```

Results: Rust fmt/clippy and all workspace tests passed; native-event regression
passed `251 passed, 2 skipped`; full QuantBT regression passed
`917 passed, 3 skipped`. Source-mirror, generated-contract, API inventory,
module-boundary, benchmark-governance, documentation-link, and Ruff gates also
passed.

Remaining boundary, not a hidden B3 correctness debt:

- A generic portfolio endpoint adapter with exact Python fallback must be
  certified before any Stage-C automatic route is enabled.
- `target_weight`, `target_notional`, `%_equity`, risk parity, cross-currency,
  isolated/venue-specific margin, and shared cross-margin need individual
  contracts and parity corpora.
- Sequential, best-effort, hedge-after-primary, cross-exchange, partial-fill,
  queue/depth, and delivery/inverse/quanto package semantics remain Python or
  future specialized native contracts.

#### 54B.4 - Installed-Wheel Release Gate, Migration Audit, And Final Handoff

**Status: complete (installed-wheel release gate and handoff).**

Detailed guide to read before every implementation decision:

- [P3.6 - Three-tier benchmark and regression CI](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p36--benchmark-governance-và-regression-ci)
- [P3.9 - Docs, compatibility, migration](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p39--documentation-compatibility-table-và-user-migration)
- [P3.10 - Supply chain and release integrity](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p310--rust-supply-chain-safety-và-release-integrity)
- [P3.11/P3.12 - Cleanup and final exit](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p311--cleanupdeletion-plan)

Goal:

Produce a reversible release candidate whose installed core/native wheels,
promotion policy, conformance corpus, diagnostics, benchmark evidence, docs,
and release artifacts all describe exactly the same support surface.

Implementation scope:

- Extend CI into PR smoke, nightly evidence, and release certification lanes.
  Release lane builds clean core/native wheels, installs only those artifacts in
  isolated environments, verifies the exact package handshake and source/wheel
  module identity, then runs promotion matrix, corpus, public API, report,
  WFO, portfolio/package, memory, and benchmark governance gates.
- Add versioned capability/maturity table and migration guide: auto choice,
  explicit Python/Rust behavior, rollback commands, contract clocks, OHLC
  limitations, native IR boundaries, package atomicity scope, unsupported
  domains, and reproduction instructions. Examples are executable in CI.
- Produce release evidence: build provenance, lockfile/registry fingerprints,
  wheel checksums, platform/python matrix, benchmark manifest references,
  performance/RSS summaries, native disable proof, and rollback test results.
- Maintain a deletion manifest for shadow state, nested-row conversion,
  score-via-audit, forced replay, root mirror, aliases, and duplicate paths.
  This phase may remove only a candidate whose replacement, migration test,
  public-import audit, compatibility window, and rollback archival all pass.
  The root mirror is explicitly **not deleted** in this release without a
  separate approved breaking-cleanup decision; it remains byte-identity gated.
- Do not publish, tag, force-push, or delete public/source surfaces as part of
  the implementation phase. Those are explicit release-owner actions after the
  release candidate passes.

Required tests and evidence:

- Clean installed-wheel tests across every declared CPython/platform row;
  extension unavailable/mismatched/disabled tests; signed deterministic
  decision snapshots; no repository-root import leakage.
- Full differential corpus, native-event suite, complete QuantBT suite,
  benchmark governance, fuzz/security smoke, and release bundle integrity all
  pass. Benchmark promotion table is generated/validated from passed evidence,
  never hand-waved by a README claim.
- Deletion manifest has a replacement, test, migration note, and rollback
  status for every candidate; no deletion is justified merely because a newer
  module exists.

Final exit gate:

```text
Rust is canonical only for registry rows that pass installed-wheel correctness,
RSS, benchmark, public-result, and rollback gates. Python remains the explicit
oracle and emergency fallback. The release capability table is the source of
truth; unsupported workloads fail closed or stay on Python by design.
```

Completion evidence:

- Added `tools/certify_native_release.py`, a release-candidate gate that builds
  its proof from installed artifacts only. It creates independent core-only and
  exact core/native virtual environments with `PYTHONPATH`, user-site, Poetry,
  Conda, and active-venv leakage removed. The exact-pair probe verifies the
  core/native version and API-0.4 handshake, installed module paths, generated
  promotion decisions, explicit rollback/fail-closed behavior, public static
  execution, native-IR batch/fold scoring, and bounded E4/E5 helper parity
  against the installed Python event oracle at `atol=1e-12`.
- Added a tagged `Native Release Certification` workflow for CPython 3.11,
  3.12, and 3.13. It builds a manylinux core/native pair, verifies every clean
  pair, runs the full release shard plus governed B2/B3 benchmarks on 3.12,
  emits supply-chain/SBOM evidence, and archives certificates and staged
  artifacts. The regular PyPI workflow remains core-only and no native upload
  is introduced.
- Added nightly E4/E5 evidence alongside the existing E0/E3/E6 artifacts,
  a versioned deletion/migration manifest, `make migration-audit`, and
  `make certify-native-release`. The manifest is deliberately conservative:
  root-level Pool Alpha compatibility modules, the Python oracle/adapters, and
  legacy ABI compatibility all remain retained; generic portfolio/package
  routes are explicitly deferred. Nothing was deleted in this phase.
- Added the user-facing [native release handoff](../docs/migration/native_release_handoff.md)
  and linked it from the packaging, native installation/capability, Rust
  contract, README, and docs index surfaces. It explains the narrow automatic
  Stage-B rows, explicit-only E4/E5 helpers, rollback, reproduction, and the
  release-owner sequence without over-claiming generic endpoint support.
- Local evidence passed on Linux x86_64 / CPython 3.12: the staged wheel
  certificate, artifact allowlist and Twine checks, migration audit, generated
  registry/API/module/doc/benchmark gates, Ruff, Rust fmt/clippy/workspace
  tests, `cargo audit`, `255 passed, 2 skipped` native-event tests,
  `921 passed, 3 skipped` full QuantBT tests, and all 19 isolated release test
  shards. The tagged CI workflow remains the required platform-matrix evidence
  for CPython 3.11/3.12/3.13 and manylinux before any public native claim.

Certified release boundary:

- Core-only `quantbt-engine` remains a fully functional Python distribution;
  `auto` resolves Python when no native companion exists.
- With a matching local companion, `auto` may select Rust only for the
  generated Stage-B static command and bounded native-IR/batch rows. Direct
  `target_units` and same-bar atomic market package helpers are certified but
  remain explicit-only. Generic portfolio, basket, arbitrage, callback, and
  reactive routes remain Python by policy.
- `quantbt-native` remains unpublished. Its future public release needs the
  tagged installed-wheel matrix and an explicit distribution decision; this is
  a release boundary, not a hidden correctness defect in the certified rows.

### Phase 51-54 Deferred Scope

These items require separate contracts and are not silently implied by this
roadmap:

- venue-exact L2 queue simulation where only OHLCV is available;
- universal exchange portfolio-margin clones without venue specifications;
- unbounded arbitrary Python execution compiled automatically into Rust;
- inverse/quanto/options accounting without certified instrument models;
- platform expansion beyond the release matrix without wheel and parity gates;
- removing the Python oracle or historical execution contracts.

Any deferred item must fail closed or route through an explicitly documented
fallback. It must not be represented as certified native support.

## Phase 55 - Public Rust Companion Distribution And Consumer Install Closure

**Status: Phase 55A is complete. Phase 55B implementation and local release
locks are complete; its immutable public-index/OIDC execution remains a
release-owner gate.**

This follow-up closes the public packaging gap discovered after `v1.0.9`:
the governed Rust routes are certified from a matching local/CI companion, but
the public core wheel does not yet install that companion. This is a packaging
and delivery task only. It must not change endpoint signatures, event-domain
semantics, promotion thresholds, or Python-oracle fallback behavior.

Read before implementation:

- [P3.4 - dual-package architecture](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p34--dual-package-architecture-core-python--native-rust)
- [P3.5 - workload-based `auto` promotion](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p35--auto-backend-promotion-theo-workload)
- [P3.6 - benchmark and release certification](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p36--benchmark-governance-và-regression-ci)
- [P3.9/P3.10 - documentation and supply-chain release integrity](quantbt_p0_p3_native_rust_upgrade_blueprint.md#p39--documentation-compatibility-table-và-user-migration)
- [Release packaging contract](../docs/release_packaging.md)
- [Native companion installation contract](../docs/native/install.md)
- [Native capability and fallback matrix](../docs/native/capabilities.md)

### Public platform policy

Initial public native support is deliberately limited to pre-built
`manylinux_2_17_x86_64` / `manylinux2014_x86_64` wheels for CPython 3.11, 3.12,
and 3.13. This covers the current Ubuntu 22.04 x86_64 VPS and mainstream
glibc-based Linux servers. It is not an Ubuntu-specific wheel.

ARM64/aarch64, Alpine/musl, PyPy, and 32-bit Linux are outside this release.
Those platforms retain the fully supported Python/Numba core fallback. No
public consumer should be required to install Cargo, Rust, or Maturin.

`quantbt-engine==1.0.9` is immutable once published. The public dependency
wiring therefore lands in the next core patch release, not by mutating `1.0.9`.

### Phase 55A - Native Distribution And Core Dependency Wiring

**Status: complete (local implementation and artifact certification).**

**Goal:** make a matching Rust companion resolvable by a normal Linux consumer
without source compilation.

Implementation:

- Produce a versioned `quantbt-native` PyO3 distribution from the exact release
  ref, with ABI/product-registry mapping locked to the next `quantbt-engine`
  patch version.
- Build wheel-only native artifacts for Linux x86_64 / CPython 3.11, 3.12, and
  3.13 using the declared manylinux baseline. Do not use a native source
  distribution as a fallback that could trigger an accidental local compile.
- Change the next core release metadata so a normal
  `poetry add quantbt-engine` resolves the matching `quantbt-native` wheel on
  the supported Linux marker. Unsupported platforms must resolve core-only and
  retain the existing structured Python fallback.
- Keep `backend="python"`, `backend="auto"`, and `backend="rust"` semantics
  unchanged. `auto` may promote only the already-certified Stage-B static/IR/
  batch routes; all other routes remain Python by policy.
- Regenerate product contracts, release manifests, package metadata, and user
  docs so they state the public installation behavior accurately.

Focused acceptance only (do not re-run already-certified domain regressions):

- inspect native wheel tags, metadata, hashes, ABI descriptor, and exact
  core/native compatibility mapping;
- clean installed-wheel import/status checks for CPython 3.11, 3.12, and 3.13;
- verify a certified Rust route is selectable through `backend="auto"` on the
  supported Linux pair, while a missing/unsupported companion selects Python
  or fails fast for explicit Rust;
- retain source-mirror and generated-contract checks.

Exit condition:

```text
On supported Linux, a normal core install has a matching pre-built native
companion available without a Rust toolchain. On every other platform, the
same core package remains installable and deterministic on Python.
```

Completion evidence:

- Staged the exact candidate pair `quantbt-engine==1.0.10` and
  `quantbt-native==0.4.1` in the product registry, generated contracts, Cargo
  metadata, Maturin metadata, and `uv.lock`.
- Added the direct PEP 508 Linux x86_64 / CPython 3.11-3.13 dependency to the
  core wheel. The local `tool.uv.sources` override exists only to make the
  unpublished candidate reproducible in this checkout; it is not emitted in
  wheel metadata. A built core wheel was inspected and contains the exact
  `Requires-Dist` marker requirement.
- Added a wheel-only native artifact contract tool and CI gate. It rejects
  native sdists and non-manylinux tags, verifies CPython/ABI/platform tags,
  extension layout, wheel metadata, and the exact core-wheel dependency. The
  native CI workflow builds one artifact per CPython 3.11/3.12/3.13 row with
  `manylinux: "2014"` and uploads each verified wheel separately.
- Locally built the CPython 3.12 native wheel and core wheel/sdist from the
  same candidate, then passed artifact allowlist, source-to-wheel parity,
  exact pair handshake, clean venv import, and `pip check`. The local native
  artifact intentionally has the host-only `linux_x86_64` tag and is rejected
  by the public manylinux gate; it is evidence only, never an upload artifact.
- Focused packaging tests passed (`24 passed`), along with Ruff, Cargo locked
  workspace check, source-mirror/product-contract/doc-link/benchmark-governance
  checks. No endpoint, promotion, accounting, or execution-domain behavior was
  changed or re-certified in this packaging-only phase.

Phase 55A does not satisfy the public-install exit condition alone: the
not-yet-uploaded native wheel must be published and resolved by a real package
manager in Phase 55B before any public Rust-install claim is made.

### Phase 55B - Public Publish, Poetry Consumer Proof, And Release Handoff

**Goal:** prove the public index behavior that users actually receive, then
publish in dependency-safe order.

Implementation:

- Configure/verify trusted publishing for the separate `quantbt-native`
  distribution and its Linux wheel artifacts.
- Publish the matching native wheel matrix first on TestPyPI, then publish the
  core candidate and run the TestPyPI consumer proof. Repeat native-first on
  production PyPI after approval, then publish the matching core release.
- In an isolated Ubuntu 22.04 and Ubuntu 24.04 consumer environment, install
  the released package with exactly:

  ```bash
  poetry add quantbt-engine
  ```

  Confirm that the resolver installs the matching native wheel, native status
  is compatible/executable, and a certified auto-promoted static/IR route
  actually selects Rust.
- Prove the complementary contracts: `backend="python"` remains forced Python;
  unsupported/missing native environments keep Python fallback; explicit
  `backend="rust"` fails with an actionable compatibility error rather than
  silently replaying Python.
- Update README, installation, capability, troubleshooting, release handoff,
  and changelog pages with the exact platform matrix and the fact that Rust is
  pre-built rather than compiled at install time.

Focused release gate:

- `twine check`, artifact allowlist, hash/registry checks, package install,
  `pip check`, Poetry resolution, native import, status probe, and one
  certified public-route smoke per declared CPython/platform row;
- no full domain/parity suite rerun unless packaging changes a domain surface.

Exit condition:

```text
`poetry add quantbt-engine` on supported Linux installs and uses the certified
Rust companion automatically for its governed routes. The next public release
states this boundary truthfully, and unsupported platforms remain safe on the
Python backend.
```

Implementation and local release-lock evidence:

- Added dispatch-only `publish-native.yml`. It builds the CPython
  3.11/3.12/3.13 `manylinux2014` matrix, rejects non-wheel/non-manylinux
  artifacts, aggregates the matrix, certifies an installed exact pair, and
  only then exposes separate OIDC jobs for `testpypi` or `pypi`. It never
  uploads the core distribution.
- Added `public-native-consumer.yml`: a six-row matrix over Ubuntu 22.04 and
  Ubuntu 24.04 / CPython 3.11-3.13. Its isolated consumer uses a fresh cache,
  runs exactly `poetry add quantbt-engine`, verifies the package paths and
  exact versions, then proves one governed 10,000-bar static route resolves to
  Rust, forced Python remains Python, disabled-native auto falls back, and
  explicit Rust fails closed.
- Added `tools/verify_public_native_consumer.py`. The default uses TestPyPI or
  PyPI; its optional TestPyPI-compatible index override exists only for
  isolated tool testing and does not change the public workflow.
- Updated core TestPyPI/PyPI workflows to install Rust for the local source
  override, preflight the public matching native wheel before core upload, and
  install the companion before clean wheel/sdist `pip check`. Main CI now builds
  a temporary native wheel solely to satisfy this exact dependency during its
  clean package smoke.
- Promoted the product release metadata from the Phase 55A staged state to the
  Phase 55B public-wheel policy, regenerated product contracts, and made
  supply-chain/SBOM/release-manifest output report the same release state.
- Updated README, release packaging, native installation/capability/
  troubleshooting pages, native handoff, docs map, Rust package README, and
  changelog. The canonical step-by-step owner guide is
  [`docs/testpypi_release_checklist.md`](../docs/testpypi_release_checklist.md).
- Focused packaging/release tests passed (`48 passed`), as did product contract
  generation, source-mirror verification, documentation-link verification, and
  a local Poetry source-configuration smoke. No execution-domain code,
  endpoint signature, lifecycle semantics, or promotion threshold changed.

External release-owner gate remaining before this phase can be marked fully
public-complete:

1. Configure the two `quantbt-native` trusted publishers for
   `publish-native.yml` / `testpypi` and `publish-native.yml` / `pypi`.
2. Run the documented native-first TestPyPI -> core TestPyPI -> public Poetry
   consumer sequence from the exact `v1.0.10` release tag and archive its
   artifacts.
3. Repeat native-first on PyPI, publish the GitHub Release for the core, then
   run and archive the PyPI consumer matrix.

## Phase 56-71 - QuantBT Rust-Primary, Correctness-Certified Runtime V1.1

**Status: planned. No implementation begins until the corresponding phase is
explicitly approved.**

**Follow-up review:** the capability-scoped implementation records below do
not certify completion of every public workload or the full guide definition
of done. See [Phase 72-78: public workload closure](#phase-72-78---rust-primary-public-workload-and-performance-closure)
for the approved-to-document follow-up plan. Each follow-up phase still needs
separate implementation approval; historical benchmark claims are not new
release evidence.

This is the V1.1 successor program after the public `quantbt-engine==1.1.0`
and `quantbt-native==0.4.1` baseline. It is not a blanket Rust rewrite and it
does not authorize a new fast path merely because a Rust crate or enum exists.
The objective is to make Rust the single simulation authority for each
linear-domain capability that has passed independent correctness certification,
while preserving Python for research, strategy logic, public ergonomics, lazy
reporting, and the independent test oracle.

**Canonical detailed guide:**
[QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).
Every implementation phase must read its cited guide sections, plus the
agent rules and PR evidence template in guide sections 95-96, before editing.
The guide is authoritative for domain semantics; this section is the concise
delivery, exit-gate, and progress-tracking plan.

### V1.1 Program Contract

The non-negotiable ordering is:

```text
written domain and causal specification
-> independent oracle and canonical trace
-> differential parity and invariants
-> end-to-end performance evidence
-> explicit Rust route
-> workload-aware auto promotion
-> stable soak/shadow evidence
-> removal of an eligible production duplicate
```

Program-wide rules:

- Strategy research remains outside QuantBT. Features, indicators, alpha state,
  parameter logic, target generation, hedge ratios, and package intent remain
  strategy-owned.
- Rust must own mutable simulation state for a promoted route: market/calendar
  view, instrument constraints, order/fill lifecycle, cash, PnL, fees,
  funding, margin, liquidation, metrics, and native result buffers.
- Python must not maintain a shadow account or replay execution to create a
  normal Rust result. Python adapts native result buffers only on the cold path.
- `backend="rust"` is explicit and fail-closed outside the exact certified
  capability. `backend="auto"` promotes only after capability, installed-wheel,
  parity, RSS, and end-to-end speed gates pass. It must record why it selected
  Python or Rust.
- Final equity parity alone is insufficient. Every promoted route needs the
  declared canonical trace, terminal fingerprint, field-specific tolerance,
  hand-computable fixtures, and independent-oracle evidence.
- Historical timing IDs and legacy routes remain reproducible until their A5
  removal gate. No timing change is allowed as a performance optimization.
- Each phase is closed only when all in-scope work items pass. A capability
  deliberately outside V1.1 must be represented as an explicit unsupported or
  experimental contract with fail-fast behavior, never as an undocumented
  technical debt or silent fallback.
- No phase combines a semantic rewrite, broad auto-promotion, and deletion of
  the old production implementation. Every phase has an explicit rollback
  boundary and records requested/resolved contracts in result metadata.

### V1.1 Authority And Promotion Vocabulary

The following maturity ladder from guide section 7 is mandatory in all phase
reports:

```text
A0: module/substrate exists
A1: differential parity
A2: written spec + oracle + trace + invariant certification
A3: explicit Rust route, fail-closed outside capability
A4: auto eligible after installed-wheel/RSS/end-to-end gates
A5: Rust primary after shadow release and stable soak; old production path may retire
```

The runtime class must be reported separately from authority. In particular, a
reactive run with one Python-to-Rust public entry and thousands of callbacks is
`RustPrimaryPythonCallback`, not fully native. A benchmark must report
preparation, strategy generation, intent ingestion, native execution, native
metrics, materialization/report time, copy counters, cold peak RSS, and warm
steady RSS.

### Phase Map

| Local tracking phase | Guide phase | Primary outcome | Required guide references |
|---|---:|---|---|
| 56 | 0 | Baseline, inventory, corpus, diagnostics, clean-wheel baseline | sections 41-42, 81 |
| 57 | 1 | Written specs, canonical trace, independent Python oracle | sections 16-21, 43, 81 |
| 58 | 2 | CalendarPlanV2, prepared market, InstrumentRegistryV2 | sections 22-23, 44, 82 |
| 59 | 3 | Linear Rust account authority and FillReplay certification | sections 24-25, 45, 83 |
| 60 | 4 | ExecutionModelV1, MetricContractV2, NativeResultV2 | sections 26-27, 46, 84 |
| 61 | 5 | Static order tape Rust-primary closure | sections 28, 47, 85 |
| 62 | 6 | Reactive numeric co-runtime R1 foundation | sections 29.1-29.7, 29.13-29.17, 48, 86 |
| 63 | 7 | Sparse wake, block intent, reactive candidate batching | sections 29.8-29.12, 49, 86 |
| 64 | 8 | WFO calendar, causality, lifecycle, account-policy closure | sections 30-31, 50, 87 |
| 65 | 9 | Persistent Rust WFO evaluation runtime V2 | sections 32, 51, 87 |
| 66 | 10 | Rust target/vectorized authority | sections 33, 52, 88 |
| 67 | 11 | Rust shared-account portfolio executor | sections 34, 53, 88 |
| 68 | 12 | Bounded same-account package/arbitrage authority | sections 35, 54, 88 |
| 69 | 13 | Rust bounded intrabar authority | sections 36, 55, 89 |
| 70 | 14 | Options P0 correctness containment | sections 37, 56, 89 |
| 71 | 15 | Reliability, productization, A4/A5 promotion and cleanup | sections 38-40, 57, 90-92 |

### Shared Evidence And Review Protocol

Every phase PR/commit series must include the guide section 96 evidence:

```text
Contract IDs and authority before/after
Specification examples, independent-oracle comparison, canonical trace
Invariants/property/fuzz or mutation evidence appropriate to the phase
Workload manifest, phase timings, boundary/copy counters, RSS, end-to-end comparison
Public API/legacy compatibility, capability-registry and installed-wheel result
Explicit rollback route, flag, backend selection, or package pin
```

The target repository structure in guide section 70 is directional. Crate
extraction follows section 71 only after behavior is frozen and all consumers
are migrated. A crate move, numeric rewrite, semantic change, ABI change, and
auto-promotion must never be combined in one phase or PR.

### Phase 56 / Guide Phase 0 - Baseline, Inventory, And Measurement Contract

**Status: complete.**

**Goal:** freeze a reproducible V1.1 starting point without changing runtime
semantics. Every later performance or authority claim must be comparable to
this baseline.

**Read first:** [V1.1 guide sections 1-3, 39-42, and 81](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-000` through `RP-004`.

Implementation scope:

- Write the V1.1 ADR set for Rust-primary authority, strategy/engine boundary,
  correctness-before-performance, runtime classes, and WFO optimizer schedules.
- Generate a deterministic, machine-readable endpoint/capability inventory
  covering endpoint, input mode, account/timing contract, output profile,
  requested/resolved backend, authority dimensions, runtime class, and fallback.
- Freeze a baseline corpus for static V2/V3 orders, FillReplay, reactive
  Grid/MRS-like behavior, signal/target routes, portfolio, WFO schedules,
  intrabar, atomic package, and basic European options. Store config, result,
  traces where available, metrics, artifacts, and declared known deviations.
- Add one cross-route timing/copy/RSS diagnostics schema. It must separate
  Python-to-Rust entries, Rust-to-Python callbacks, GIL acquisitions, market/
  intent/result copy bytes, worker starts, session resets, phase timings, and
  cold/warm RSS.
- Build and install the exact core/native wheel pair in clean environments,
  recording import path, protocol handshake, capability registry, route choice,
  and test subset. This is a baseline only, not a new public promotion.

Required tests and evidence:

- inventory JSON and generated documentation are deterministic and agree;
- benchmark/corpus manifests resolve immutable data/config fingerprints;
- source and installed-wheel baseline show the same declared authority and
  routing for covered capabilities;
- diagnostics are emitted without pandas/report side effects in score profiles;
- no domain result, timing ID, or default endpoint behavior changes.

Exit gate:

```text
V1.1 has an approved ADR set, a reproducible corpus, comparable phase/RSS/
boundary counters, an endpoint-authority inventory, and a clean-wheel baseline.
No implementation may claim an improvement without comparing against it.
```

No-debt rule and rollback:

- No incomplete inventory field or ambiguous baseline fixture is allowed to
  pass into Phase 57. Missing coverage must be labeled unsupported and added
  before its consuming domain migrates.
- This phase is documentation/test instrumentation only; rollback is removal of
  new diagnostic collection behind an opt-in flag, with no execution fallback
  change.

**Completion evidence (2026-09-04):**

- `docs/adr/ADR-RP-001-rust-primary-authority.md` through
  `docs/adr/ADR-RP-005-wfo-optimizer-schedules.md` freeze authority, strategy
  boundary, correctness, runtime-class, and WFO-schedule decisions.
- `tools/generate_v1_1_baseline.py` deterministically emits
  `benchmarks/baselines/v1_1_endpoint_inventory.json`,
  `benchmarks/baselines/v1_1_corpus_manifest.json`, the matching generated
  documentation, and `contracts/v1_1_measurement_contract.json`.
- The inventory covers every current `QuantBTEndpoint` classmethod and records
  authority dimensions, runtime class, fallback, product versions, and the
  actual bounded Rust promotion state. The corpus includes the requested
  static, reactive, signal, pct-equity, portfolio, WFO, intrabar, replay,
  package, and basic-option snapshots; unsupported nested WFO is explicit.
- `tools/capture_v1_1_installed_wheel_baseline.py` recorded a clean CPython
  3.12 Linux core-only and exact-pair proof in
  `benchmarks/baselines/v1_1_installed_wheel_baseline.json`. The exact pair
  imported from `site-packages`, selected the governed static Rust route, and
  retained explicit portfolio/package policy; core-only auto selected Python.
- Gates: `poetry run python tools/generate_v1_1_baseline.py --check`,
  `poetry run pytest -q tests/test_phase56_v1_1_baseline.py`, source-mirror
  and contract generators, module-architecture, documentation-link, and
  native-event contract checks all pass. No runtime/domain source changed.

### Phase 57 / Guide Phase 1 - Domain Specifications, Oracle, And Canonical Trace

**Status: completed on 2026-09-04.**

**Goal:** establish a specification and executable correctness control that is
independent from both legacy production code and new Rust code.

**Read first:** [V1.1 guide sections 10-21, 43, 60, and 81](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-005` through `RP-010`.

Implementation scope:

- Write versioned timing/execution-clock specifications for observation,
  effective phase, first-bar behavior, V2/V3 lifecycle ordering, gap behavior,
  same-bar ambiguity, funding boundary, and effective timestamps.
- Write linear accounting, margin, funding, fee, scale/reduce/reverse, and
  liquidation specifications with hand-computable examples. Preserve `f64` in
  V1.1 hot paths but introduce typed IDs, centralized comparison/rounding
  policy, and field-specific tolerances.
- Define backend-neutral `CanonicalTraceV2`, stable serializer, trace hash, and
  `TerminalFingerprintV2`. Trace rows include event/order/account identifiers,
  timestamps, reason code, qty, price, fee, cash, position, PnL, margin, and
  state hash before/after where applicable.
- Create an independent pure-Python oracle tree, starting with linear
  accounting and FillReplay. It must not import production QuantBT, Rust, or
  Numba and must remain small enough to audit.
- Add specification fixtures, differential harnesses, property/metamorphic
  generators, causal mutation fixtures, and bounded Rust fuzz/mutation gates.

Required tests and evidence:

- hand-computable timing/accounting fixtures are exact;
- old Python route and current Rust substrate emit normalized trace records for
  bounded fixtures without claiming parity yet;
- required mutations catch funding sign, fee side, fill ordering, timing,
  quantity rounding, maintenance comparison, OCO cancellation, and calendar
  relabel defects;
- score/compact/audit fingerprint policy and field-specific tolerance table are
  versioned;
- independent oracle import audit proves no production implementation leakage.

Exit gate:

```text
The timing, accounting, trace, oracle, property, and mutation foundations pass.
No downstream Rust authority migration begins without an executable independent
oracle and canonical-trace comparison path for its financial contract.
```

No-debt rule and rollback:

- A known semantic disagreement must be resolved in the written specification
  before it can be encoded in Rust; legacy parity alone cannot waive this rule.
- New trace/oracle code is test-only and additive. Existing production routes
  remain the explicit compatibility baseline until later promotion gates.

Implementation evidence:

- Added the machine-readable
  [`contracts/v1_1_correctness_contract.json`](../contracts/v1_1_correctness_contract.json)
  plus versioned [execution-clock](../docs/contracts/v1_1_execution_clock.md),
  [linear-accounting](../docs/contracts/v1_1_linear_accounting.md), and
  [Canonical Trace V2](../docs/contracts/v1_1_canonical_trace_v2.md)
  specifications. They freeze V2/V3 timing, close timestamp semantics,
  effective timestamps, linear scale/reduce/reverse accounting, one-way fees,
  signed funding, margin preview, field-specific tolerances, and the bounded
  mutation catalog.
- Added `quantbt.verification.canonical_trace_v2`: typed integer IDs,
  backend-neutral rows, stable little-endian dual-FNV serializer/hash,
  field-aware comparison, terminal fingerprints, and an explicitly lossy V1
  trace adapter. Existing `canonical-execution-trace-v1` output and product
  trace ABI remain unchanged.
- Added the matching Rust domain vocabulary in
  `rust/crates/quantbt-domain/src/trace_v2.rs`, including typed `BarIndex`,
  `TimestampNs`, `AccountId`, and `PackageId`. A shared fixed vector locks
  Python/Rust byte order and hash behavior without introducing a new runtime
  emitter or a second execution authority.
- Added the standard-library-only reference tree under `reference/python` for
  linear accounting, FillReplay, timing, exact calendar, quantity rounding,
  maintenance, and OCO rules. It is outside `src/`, excluded from wheels, and
  guarded by AST import audit against QuantBT, Rust, Numba, NumPy, and pandas.
- Added hand fixtures, FillReplay differential evidence, normalized legacy
  Python/Rust trace projection, Hypothesis split-fill metamorphism, and
  explicit mutations for funding sign, fee side, fill ordering, timing,
  quantity rounding, maintenance comparison, OCO cancellation, and calendar
  relabeling. `tests/conftest.py` now prioritizes `src/` so these tests cannot
  accidentally validate a stale site-packages wheel.
- Repaired the historical root/source mirror guard exposed by the full suite:
  it now compares only the manifest-approved local compatibility surface rather
  than treating package-only benchmark helpers as a second source tree. The
  new `verification` package is included in that manifest and copied
  byte-identically to the retained root mirror; `benchmarks` remains
  deliberately source-only.
- Added `tools/check_v1_1_phase57_foundation.py` and
  `make v1_1-phase57-check`; `make test-contracts` now includes both the
  foundation validator and Phase 57 tests.
- Verification on local CPython 3.12/Linux: `make v1_1-phase57-check`,
  `make test-contracts` (`160 passed`), `make test-rust-unit` (all workspace
  unit/doc tests), and the full Python suite excluding the two local real-data
  scripts (`934 passed, 22 skipped`) pass. A temporary core wheel contains
  `quantbt/verification/canonical_trace_v2.py` and excludes `reference/`.

Phase boundary:

- No endpoint timing, accounting, auto-routing, public trace schema, or
  production `FullSession` behavior changed. Direct V2 runtime emission,
  executable Rust FillReplay parity, CalendarPlanV2, and a common accounting
  authority remain intentionally scheduled Phase 58 onward, not hidden
  technical debt in this completed foundation phase.

### Phase 58 / Guide Phase 2 - Canonical Market, Calendar, And Instrument V2

**Status: completed on 2026-09-04.**

**Goal:** establish one canonical market clock and one instrument-rule source
of truth for every certified multi-symbol route.

**Read first:** [V1.1 guide sections 22-23, 44, 60.1, 72, and 82](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-011` through `RP-017`.

Implementation scope:

- Add the equal-length/different-timestamp WFO regression first. Any `Exact`
  request must fail with the first divergent timestamp rather than relabel a
  symbol by row count.
- Implement `CalendarPlanV2` with `Exact`, `Intersection`, `Union`, and
  `PrimaryClock` policy IDs; per-symbol canonical/local mappings; observed,
  stale, and tradable flags; and explicit missing-observation behavior.
- Build immutable, fingerprinted `PreparedMarketHandleV2` with bounded cache,
  explicit close/release, one canonical timestamp allocation, and safe reuse
  across runs, folds, and candidates.
- Add `InstrumentRegistryV2` as the only certified owner for price tick,
  quantity step, min/max quantity, min notional, multiplier, leverage limit,
  settlement currency, fee/funding schedule, and purpose-specific rounding.
- Adapt current static event, Rust target helper, and atomic package helper to
  the registry. Legacy per-workload fields resolve through compatibility
  adapters and are recorded in requested/resolved metadata.

Required tests and evidence:

- exact, intersection, union, and primary-clock maps match the independent
  calendar oracle, including reordered symbol dictionaries and future append;
- no observer/marking/execution value is silently forward-filled without the
  declared policy;
- OHLC, timestamp, volume, funding, duplicate, stale, and tradability
  validation tests pass;
- tick/lot/min-notional/min-quantity and reduce-only close parity pass in
  Python and Rust;
- prepared/unprepared input has identical mapping/trace and repeated WFO runs
  show zero market copies per candidate or fold.

Exit gate:

```text
All V1.1-certified multi-symbol routes consume CalendarPlanV2 and
InstrumentRegistryV2. No len-based relabel or divergent instrument constraint
remains in a certified route.
```

No-debt rule and rollback:

- Unsupported calendar/missing-data semantics fail during preparation. They are
  not approximated by a generic `fillna` or hidden legacy fallback.
- `calendar_contract="legacy_v1"` remains explicit for historical
  reproduction only; `Exact` is the certified default.

Implementation evidence:

- Added `CalendarPlanV2` and `SymbolCalendarMapV2` in
  `quantbt.core.market_calendar_v2`. `exact`, `intersection`, `union`, and
  `primary_clock` are explicit policy IDs; canonical/local mapping arrays,
  observed/stale/tradable flags, raw missing OHLCV, separate mark prices,
  funding event matrices, and a result-affecting fingerprint are immutable.
  Exact reports the first divergent timestamp, including equal-length shifted
  frames; it never relabels values by row count.
- Added `PreparedMarketHandleV2` and `PreparedMarketCacheV2`: one canonical
  timestamp allocation per handle, read-only contiguous arrays, bounded
  content-addressed reuse, `close()`/`release()`, cutoff-stable fingerprints,
  and a zero-copy finite execution view. Current V1 lowering rejects missing
  observations or per-symbol funding clocks rather than fabricating a market.
- `WalkForwardConfig.calendar_contract` defaults to `exact_v2`. The WFO
  boundary now rejects duplicate/unsorted or equal-length shifted timelines
  before strategy execution. `legacy_v1` retains the former row-count adapter
  only when deliberately requested for historical reproduction.
- Added `InstrumentRegistryV2`, purpose-specific price/quantity rounding,
  canonical one-way fee, multiplier/leverage/minimum/settlement/funding rule
  provenance, and `PreparedExecutionPlanV2`. New public helpers are
  `QuantBTEndpoint.prepare_market`, `.prepare_instruments`, and
  `.prepare_execution_plan`; their generated V1.1 inventory rows classify
  them as preparation-only, not a hidden second execution engine.
- The prepared static `event_driven(input_mode="orders")` route now bypasses
  facade normalization and pandas open/volume reconstruction. Its Python and
  Rust executions receive registry-resolved contract-size, leverage, and fee
  arrays, while metadata records requested versus resolved calendar and
  instrument fields. Bounded `run_portfolio_target_market_v2` and
  `run_atomic_package_market_v2` lower the same handle/registry pair into the
  existing Rust market helpers without execution replay.
- Added matching typed Rust vocabulary in `quantbt-domain` and the
  `InstrumentTableV1::from_registry_v2` compatibility lowering in
  `quantbt-execution`. The pure-Python calendar and instrument oracles remain
  standard-library-only under `reference/python`, outside production wheels.
- Added the machine contract
  [`contracts/v1_1_market_instrument_v2_contract.json`](../contracts/v1_1_market_instrument_v2_contract.json),
  the [calendar](../docs/contracts/v1_1_market_calendar_v2.md) and
  [instrument](../docs/contracts/v1_1_instrument_registry_v2.md) contracts,
  public endpoint/README documentation, the `v1_1-phase58-check` Make target,
  and a 16-case focused differential suite. The historical 1.1.0
  installed-wheel record is now correctly treated as immutable evidence for
  its own revision; a later release gate, rather than an arbitrary source
  edit, is responsible for fresh current-wheel hash parity.
- Verification on local CPython 3.12/Linux: focused Phase 58 suite (`16
  passed`); native-event, WFO, and portfolio/package regression groups (`155
  passed`); `make test-contracts` (`176 passed`); full Rust workspace
  `fmt`/`clippy -D warnings`/unit-doc tests; and the full Python suite excluding
  two local real-data scripts (`950 passed, 22 skipped`). Source/root mirror,
  generated API inventory, V1.1 baseline artifacts, module architecture, and
  documentation link gates all pass.

Phase boundary:

- V1.1-certified routes in this phase are prepared static command tapes and
  the explicit bounded target/package adapters. Generic portfolio,
  arbitrage/package, and stateful callback routes retain their published
  compatibility contracts and do not claim V2 certification yet.
- `union`/`primary_clock` with missing observations are represented faithfully
  and fail at current execution lowering. A missing-data-aware execution model
  is intentionally a later authority phase, not an approximation or hidden
  fallback in this completed phase.

### Phase 59 / Guide Phase 3 - Linear Accounting Authority And FillReplay

**Status: complete (2026-09-04).**

**Goal:** certify one Rust linear gross-cross account transition authority
before any complex matching, target, portfolio, package, or intrabar route
adopts it.

**Read first:** [V1.1 guide sections 24-25, 45, 60.2, and 83](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-018` through `RP-025`.

Implementation scope:

- Stabilize an internal preview-reserve-commit transaction trait around the
  existing Rust account substrate. Preview is immutable; a rejected preview or
  aborted transaction cannot mutate the account fingerprint.
- Implement typed reject codes, reservation tokens, consumption/release
  accounting, explicit scheduled funding/fee events with apply-once IDs, and
  deterministic linear liquidation state transitions with executable fills.
- Build the explicit whole-run Rust `FillReplayV2` route using the common
  account authority and separate typed fill, funding, and mark rows.
- Migrate financial arithmetic in a behavior-preserving manner only after the
  contract is documented. Do not construct a second account engine beside
  `FullSession`.
- Add debug/certification invariant checks after randomized account transitions
  while preserving release hot-path performance policy.

Required tests and evidence:

- independent oracle and Rust FillReplay agree on the complete canonical
  account trace and terminal fingerprint for open, scale, reduce, close,
  reverse, fee, funding, margin reject, liquidation, and multi-symbol
  shared-margin fixtures; the historical V1 Numba route remains a terminal
  arithmetic comparator only over its declared single-symbol/no-funding/no-
  margin overlap because it cannot emit a complete V2 account trace;
- split-fill metamorphism, zero-quantity rejection, funding apply-once,
  reject immutability, reservation leak, and liquidation state-machine tests
  pass;
- randomized valid/invalid fill streams run invariant checks after every
  transition;
- field tolerances are quantity/tick/cash/metric specific and are recorded.

Exit gate:

```text
FillReplay is A2 domain-certified: written linear accounting semantics,
independent-oracle/Rust canonical trace, legacy-V1 terminal-overlap comparison,
and invariant/property/fuzz evidence are all green. No downstream route may
use a different linear accounting authority.
```

No-debt rule and rollback:

- Any unresolved funding, fee, margin, reservation, or liquidation disagreement
  blocks this phase and downstream migration. It cannot be marked as a
  tolerance exception.
- Existing accounting routes stay available as explicit comparators until each
  consuming route reaches its own promotion gate.

**Completion evidence (2026-09-04):**

- Added `LinearGrossCrossAccountV1` inside the existing Rust account substrate,
  not beside it. It implements typed preview/reserve/commit/release, binds
  reservations to the complete candidate fill, preserves raw IEEE transaction
  fingerprints for staleness, exposes a normalized cross-language checkpoint,
  applies funding once by event ID, and liquidates through deterministic
  executable close fills.
- Added whole-run Rust `FillReplayV2` with typed mark, fill, and funding tapes;
  `score`, `compact`, and `audit` share one accounting run and terminal/trace
  fingerprints. The PyO3 boundary makes one detached native call, and Python
  only validates input and adapts cold-path buffers into `BacktestResultV2`.
- `QuantBTEndpoint.fill_replay(accounting_backend="rust_v2")` is explicit and
  fail-closed. It preserves `numba_v1` as the default compatibility comparator,
  rejects conflicting metadata, accepts scheduled `funding_replay`, requires
  close-timestamp bars, and records the resolved accounting/funding contract.
  `FillReplayTapeV2`, `FundingReplayTapeV2`, the typed result, and V2 errors
  are also exported from `quantbt` for reusable advanced tapes.
- Added the machine contract, A2 accounting documentation, independent
  standard-library-only oracle, phase checker, endpoint docs, generated V1.1
  route inventory, and source/root mirror. The generated inventory now names
  `fill_replay_v1_numba` as a legacy comparator and `fill_replay_v2_rust` as
  the Rust accounting authority instead of presenting one ambiguous route.
- Certification coverage includes scale/reduce/reverse, split-fill
  metamorphism, zero quantity, invalid market atomicity, post-cost rejection,
  reservation leak/mismatch, before/after-close funding, duplicate funding,
  shared multi-symbol margin, liquidation, audit/compact/score fingerprints,
  normal report surfaces, and randomized valid/invalid streams. Canonical
  trace parity is exact between Rust and the independent oracle; V1 terminal
  overlap is intentionally documented as narrower.
- Local CPython 3.12/Linux verification: `tests/test_phase59_linear_accounting_fill_replay.py`
  (`11 passed`); phase 56-59 plus native-contract group (`187 passed`);
  full Python suite excluding the two local real-data scripts (`961 passed,
  22 skipped`); `cargo fmt --check`, workspace `clippy -D warnings`, and all
  workspace Rust unit/doc tests pass. Source mirror, generated public/product/
  V1.1 inventory, module-architecture, documentation-link, and Phase 59
  machine-contract checks all pass.

Phase boundary and remaining work:

- There is no unresolved accounting discrepancy in the declared Phase 59
  linear gross-cross FillReplay scope. Matching/fill generation, slippage and
  liquidity models, common metrics/result ownership, and migration of static
  event/target/portfolio/package/intrabar consumers are deliberately Phase 60+
  work, not hidden fallback or untracked Phase 59 debt.

### Phase 60 / Guide Phase 4 - Execution Model, Metrics, And Native Result Closure

**Status: complete.**

**Goal:** make execution cost, standard metrics, and result ownership common
contracts rather than duplicated Python/Rust per-endpoint behavior.

**Read first:** [V1.1 guide sections 26-27, 46, 60.3, 63, and 84](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-026` through `RP-033`.

Implementation scope:

- Separate `AccountModel`, `ExecutionModelV1`, and `InstrumentRegistryV2`.
  Legacy fee/slippage fields are resolved into typed plans and provenance; no
  slippage remains hidden inside an account contract.
- Freeze and implement `BarTouchV1` first as the deterministic parity anchor,
  then `CostModelV1` for fee, spread, slippage, participation, simple impact,
  and optional shared liquidity ledger. Deep/L2 models remain out of default
  WFO scope.
- Implement `MetricContractV2`, online reducers, annualization/DDOF/zero-run
  policies, and domain-specific `NativeResultV2` score/compact/audit envelopes.
- Route Rust results through flat SoA buffers. Python materializes metrics,
  pandas, fill/event dataframes, and reports only on demand with bounded cache
  ownership and truncation metadata.

Required tests and evidence:

- event lifecycle corpus covers market/limit/stop/stop-limit, gap cases,
  TIF, cancel/amend/replace, reduce-only, OCO, partial fills, funding, and
  liquidation under the declared execution-model ID;
- execution cost is reconciled independently from account state;
- participation/shared-liquidity conservation and partial-fill behavior pass;
- standard metrics match contract fixtures, including short-run and zero
  variance behavior;
- score, compact, and audit return the same terminal accounting fingerprint;
- score path creates zero pandas/nested fill-event Python objects, audit is
  bounded/truncation-aware, and RSS plateaus under repeated score runs.

Exit gate:

```text
ExecutionModelV1, MetricContractV2, and NativeResultV2 are reusable common
authorities. Static event and specialized kernels can adopt them without a new
accounting or reporting implementation.
```

No-debt rule and rollback:

- An execution model exists only when its fill semantics, cost semantics, and
  liquidity contract are tested. Merely adding an enum does not imply support.
- Legacy result/report compatibility remains via lazy adapters; no public
  report API is removed in this phase.

**Phase 60 implementation sequence (mandatory before Phase 61):**

1. `RP-026/027` - add one Rust-owned `ExecutionModelV1` contract adjacent to
   the existing `FullSession`, with explicit `BarTouchV1` parity semantics,
   `CostModelV1` cost policy, deterministic per-bar `LiquidityLedgerV1`, and
   typed rejection/capability behavior. The default plan must be equivalent to
   the frozen legacy fee/slippage behavior; no public route may silently opt
   into participation, impact, or shared-liquidity behavior.
2. `RP-028/029` - keep account, instrument, and execution concerns separate:
   `InstrumentRegistryV2` remains the immutable source of fee/multiplier
   rules, `AccountModelV1` retains capital/margin/funding state, and the new
   execution plan owns only fill-cost/liquidity decisions. Add independent
   fixtures for gap/touch, fee/slippage, participation, partial-fill, and
   shared-liquidity conservation.
3. `RP-030/031` - add `MetricContractV2` plus Rust online reducers and an
   explicit short-run/zero-variance policy. A metric snapshot must be emitted
   from the authoritative native pass, while arbitrary research metrics and
   presentation remain Python cold-path responsibilities.
4. `RP-032/033` - add a `NativeResultV2` header/envelope over existing flat
   score/compact/audit SoA payloads. Include request/contract provenance,
   retention/truncation metadata, terminal fingerprint, and lazy Python
   adapters. The score path must not materialize pandas, nested fill/event
   rows, or replay execution.
5. Certification - run Rust unit tests, Python contract tests, direct native
   score/compact/audit terminal fingerprint parity, Python-oracle cost/metric
   fixtures, repeated-score RSS plateau evidence, source/root mirror checks,
   format and clippy. Record exact commands/results here before marking the
   phase complete. Do not start Phase 61 unless these gates pass.

**Completed implementation and evidence:**

- `ExecutionModelV1` is now a common Rust authority: the frozen
  `BarTouchV1` plan preserves legacy parity by default, while explicit
  `CostModelV1` covers fee, spread, proportional/fixed slippage, simple
  impact, participation, and a deterministic shared `LiquidityLedgerV1`.
  The account model remains separate from fill-cost and liquidity policy.
- `MetricContractV2` and its online reducer own native standard metrics with
  declared annualization, DDOF, short-run, zero-variance, drawdown, exposure,
  cost, and liquidation policies. Exact fixtures cover manual return
  dispersion, downside, omega, and drawdown calculations.
- `NativeResultV2` now wraps score, compact, and audit SoA output with a typed
  V2 header: request/contract provenance, workload authority, terminal
  fingerprint, metric contract, and bounded retention/truncation counters.
  `NativeResultV2Adapter` keeps pandas/report construction lazy and cached on
  the Python cold path; score materializes neither pandas nor nested audit
  objects. Portfolio/package dynamic audit sinks use the same explicit row cap.
- Domain tests include exact cost reconciliation, shared-liquidity
  conservation, GTC/IOC/FOK partial-fill behavior, invalid score retention
  rejection before execution, score/compact/audit terminal parity, bounded
  audit invariance, and dynamic workload retention caps.
- Verification completed locally on CPython 3.12/Linux:
  `cargo fmt --manifest-path rust/Cargo.toml --all -- --check`, workspace
  `cargo clippy -- -D warnings`, and workspace Rust tests (`41` engine and
  `14` execution tests among all passing crates); rebuilt the release PyO3
  extension; Phase 56-60/native typed-request group (`54 passed`); and full
  Python suite excluding the two local real-data scripts (`964 passed,
  22 skipped`). Source/root mirror plus V1.1 baseline, public API, native
  contract, and product-contract generated checks all pass.
- Repeated prepared static score benchmark: 2,000 bars x 250 runs completed at
  `1,755,602 bars/s`; RSS stayed at `30,195,712` bytes with `0` byte plateau
  growth against the `8 MiB` gate. This is a local retention/RSS evidence run,
  not a cross-machine performance claim.

**Phase 60 closure:** no unresolved debt remains inside the declared common
execution-model, native-metric, or bounded-result scope. L2/order-book
microstructure, multi-currency/cross-margin models, and endpoint-specific
adoption beyond the static route are explicit later scopes, not fallback
behavior hidden by this phase.

### Phase 61 / Guide Phase 5 - Static Event Rust-Primary Closure

**Status: completed (2026-09-04).**

**Goal:** make prepared static `OrderCommand` tapes the first full public,
whole-run Rust-primary reference route.

**Read first:** [V1.1 guide sections 28, 47, 60.3, 63, 73, and 85](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-034` through `RP-040`.

Implementation scope:

- Close public request ABI 0.5 around one prepared market, instrument registry,
  command tape, execution plan, `FullSession`, common accounting, native
  metrics, and `NativeResultV2`.
- Use existing `OrderArena`, active/lifecycle indexes, expiry buckets,
  parent-child/OCO indexes, and generation-safe handles. Remove historical
  full-arena scans only from the certified path after trace parity.
- Retain API 0.4 behind an explicit compatibility flag and record the resolved
  lifecycle/timing contract. No silent reinterpretation of V2/V3 tape data.
- Make score avoid active-order projection; compact/audit iterate only active
  indexes and bounded retention sinks.

Required tests and evidence:

- complete lifecycle corpus: market/limit/stop/stop-limit, TIF, cancel/amend,
  replace, reduce-only, parent/OCO, funding, margin/liquidation, multi-symbol,
  V2/V3 timing, low/high churn;
- independent-oracle/legacy/Rust canonical trace and terminal fingerprint
  parity for supported contracts;
- prepared command/market path has one main native entry, releases the GIL for
  whole native execution where legal, has zero replay-market copy and zero
  command-tape copy after preparation;
- installed-wheel test passes and promoted score workload is faster end-to-end
  than the Python comparator, with compact/audit adaptation budget reported.

Exit gate:

```text
The exact static command capability is A4 auto-eligible on supported installed
wheels. API 0.4 remains an explicit rollback route until stable-soak A5.
```

No-debt rule and rollback:

- Unsupported order semantics must fail with typed capability/error codes,
  never degrade to a partial Python simulation under explicit Rust.
- `backend="python"`, the legacy ABI flag, and the prior package version remain
  the rollback boundary; no duplicate production path is deleted here.

**Completed implementation and evidence:**

- `NativeEventConfig`, endpoint configuration, lifecycle API, and Engine SPI
  now preserve `native_static_abi`. Static Rust command execution resolves to
  typed ABI `0.5` by default; API `0.4_compat` is the only explicit legacy
  rollback. The typed route creates one immutable prepared market/template and
  one cached `CommandTapeV5` request/runner per tape/profile rather than
  recreating a Python lifecycle state machine.
- The static public route now calls `execute_typed()` exactly once with the GIL
  detached for the Rust execution pass. Rust owns the `FullSession`, arena,
  active/lifecycle indexes, fills, fee, funding, margin, liquidation, trace,
  and online metrics. `NativeResultV2Adapter` performs only cold result/report
  adaptation; `rust_audit_replay` is false for the typed route.
- Compact and audit output adapt direct typed SoA fields without a dictionary
  conversion. Score retains no dense/audit output; the prepared score helper
  intentionally chooses compact only when exact public score metrics require
  paths. V3 prepared scoring now requires explicit open prices and fails closed
  if they are absent; V2 retains its declared close-timing behavior.
- Cache diagnostics now expose actual typed request/run/boundary, arena,
  terminal-release, compaction, margin-recompute, and lifecycle scan counters.
  Reset/clear releases logical typed request/runner ownership without invalid
  output mutation. Static Engine SPI has the same ABI-0.5 typed request and
  one-call contract.
- The release certifier's installed-wheel probe now requires an auto-promoted
  V3 static tape to report ABI `0.5`, one native boundary, and a V2 native
  result. A local source-free consumer proof installed the newly built core and
  CPython 3.12 native wheels, resolved both modules from its own
  `site-packages`, and passed the complete static/IR/package oracle probe.
- Focused lifecycle and compatibility evidence passed: Phase 61 plus Phase 46B
  tests (`10 passed`), full differential/SPI/Rust-first/ResultV2 corpus
  (`28 passed`), and release-handoff lock plus Phase 61 tests (`10 passed`).
  Formatting, workspace clippy, and workspace Rust tests passed (`82` tests).
  The release PyO3 extension was rebuilt successfully.
- Full Python regression excluding only the two explicitly local real-data
  scripts passed: `970 passed, 22 skipped` in `346.88s`. Source/root mirror,
  V1.1 baseline, generated API/native/product contracts, and documentation
  link checks pass.
- Final 10,000-bar V3 benchmark (five warm repetitions) passed all gates:
  typed kernel `6.73M bars/s`; prepared Rust score `1.34M bars/s` versus
  prepared Python `56.5k bars/s` (`23.74x`); zero prepared-score RSS delta;
  one native boundary; no score dense/audit retention; and typed request reuse.
  Public optimize facade timings are reported separately (`135.7k` Rust versus
  `186.6k` Python bars/s) because pandas/result adaptation is intentionally a
  cold-path cost, not a hidden kernel comparison.

**Phase 61 closure:** the declared static command-tape route is A4
auto-eligible on supported exact installed wheels and is complete without
unresolved debt inside this scope. API 0.4 compatibility remains an intentional
rollback boundary. Reactive callbacks/co-runtime, sparse wake/block execution,
generic portfolio/package/arbitrage endpoints, options, vectorized/intrabar,
and WFO orchestration remain later explicitly scoped phases; they are not
partial fallbacks within this static Rust-primary certification.

### Phase 62 / Guide Phase 6 - Reactive Numeric Co-runtime R1 Foundation

**Status: complete (R1 explicit; no auto-promotion).**

**Goal:** preserve arbitrary Python reactive strategy logic while moving the
outer simulation timeline, execution state, and hot buffer ownership into Rust.

**Read first:** [V1.1 guide sections 5-6, 29.1-29.7, 29.13-29.17, 48, 61, and 86](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-041` through `RP-048`.

Implementation scope:

- Add truthful reactive diagnostics: public native entries, Python callbacks,
  GIL acquisitions, context projection/copy bytes, command ingestion, engine,
  result materialization, and callback timing.
- Implement one persistent numeric `ReactiveContextBufferV1` wrapper per
  session with generation/lifetime validation, declared projection
  requirements, and delta-only fills/events/order changes by default.
- Implement one Rust-owned primitive `ReactiveCommandBufferV2` per session,
  bounded growth, typed numeric IDs, immediate validation/consumption, and no
  per-callback dict/dataclass/array concatenation.
- Introduce Rust-driven outer loop with one public entry and a compatibility
  bridge retained as comparator. Benchmark held-GIL and release-between-
  callbacks policies rather than assuming one is universally faster.
- Establish the A/B/C/D four-way oracle: Python strategy plus independent
  execution oracle, current bridge, new co-runtime, and captured static tape
  replay.

Required tests and evidence:

- exact callback-input, command-output, execution/account trace, and strategy
  state fingerprint parity on Grid/MRS-like fixtures;
- no pandas/dict/dataclass context allocations after warmup; no per-bar command
  array allocation; stale generation/capacity misuse fails deterministically;
- lifecycle, callback exception, invalid command, cancellation, and strategy
  reset/state ownership tests pass;
- separate lightweight, low-churn, high-churn, and concurrent-session GIL
  benchmarks are recorded. R1 cannot auto-promote while slower end-to-end.

Exit gate:

```text
R1 NumericEveryBar is A3 explicit with four-way trace parity. Rust owns
simulation/accounting/control flow, Python owns only declared strategy
decisions, and metadata truthfully reports the hybrid runtime class.
```

No-debt rule and rollback:

- Every-bar Python callbacks are intentionally still hybrid, not an unresolved
  debt. They must not be marketed as fully native.
- Existing object callback route remains the comparator/rollback route until
  R1 demonstrates the stated exact semantics and performance on each promoted
  capability.

**Completion evidence (local source checkout, 2026-09-04):**

- Implemented `ReactiveContextBufferV1` and `ReactiveCommandBufferV2` in the
  PyO3 extension. Both are persistent, bounded, generation-scoped numeric
  wrappers. R1 rejects stale reads/writes, invalid primitive rows, and command
  capacity exhaustion deterministically; it does not create pandas,
  dictionary, or dataclass callback contexts.
- Added `ReactiveNumericRunnerCore`: one Python-to-Rust public entry owns the
  full `FullSession` bar clock, lifecycle, matching, fees, funding, margin,
  liquidation, command ingestion, and output buffers. Python owns only the
  declared strategy callback and its private state. The legacy Python loop and
  old Rust per-bar bridge remain unchanged as comparators/rollback paths.
- Added the explicit public route
  `reactive_runtime="numeric_every_bar_v1"`, requiring explicit Rust,
  `single_pass`, a numeric every-bar callback schedule, and the opt-in marker
  `quantbt_reactive_numeric_v1 = True`. It fails closed for scalar score,
  hidden oracle modes, sidecar audit sinks, sparse schedules, missing native
  capability, and non-numeric strategies. It never changes `backend="auto"`.
- Exact A/B/C/D evidence is locked in
  `tests/test_phase62_reactive_numeric_coruntime.py`: Python independent
  oracle, legacy Rust bridge, R1 co-runtime, and captured static Rust replay
  agree on callback/state fingerprints, command tape, fills, equity,
  positions, fees, funding, margin, canonical execution/account trace, and
  terminal state. The suite also covers quantity quantization, cancellation,
  invalid command and callback errors, stale wrappers, capacity exhaustion,
  reset, and prepared-market reuse.
- Focused Python regression passed `37 passed`; the R1 conformance suite passed
  `8 passed`; `cargo fmt --check`, native crate tests, and full Rust workspace
  tests passed (`82` Rust tests). Product-generation and source/root-mirror
  checks pass after the build. The final full non-real Python regression passed
  `978 passed, 22 skipped` in `337.30s`; its warnings are pre-existing Optuna,
  missing-intrabar-OHLC fallback, and matplotlib-layout warnings, not Phase 62
  execution regressions.
- `benchmarks/native_event/benchmark_phase62_reactive_coruntime.py` records
  Python R0, legacy Rust bridge R0, R1 held-GIL, R1 release-between-callbacks,
  and two-session evidence. On the committed 10,000-bar / three-repeat fixture:
  low-churn held R1 measured `150.8k bars/s` versus Python R0 `46.2k bars/s`
  (`3.26x`); high-churn held R1 `101.2k` versus Python `20.6k bars/s`
  (`4.92x`). R1 callback and public-result adaptation are included. Current RSS
  is reported with one result retained and after it is released; the sampled
  post-release allocator delta was `0-1.11 MiB`. These are local,
  workload-scoped measurements, not an automatic routing promise.

**Phase 62 closure:** `numeric_every_bar_v1` is A3 explicit and usable for the
declared single-session numeric callback contract. It has one Rust-owned
simulation/accounting authority and truthful hybrid provenance. There is no
unresolved implementation debt inside R1. Sparse wake plans, block intents,
candidate batches, multi-session route policy, and any reactive auto-promotion
are intentionally separate Phase 63 capabilities, not missing fallback logic.

### Phase 63 / Guide Phase 7 - Sparse Wake, Block Intent, And Reactive Batching

**Status: complete (2026-09-04).**

**Goal:** reduce Python callback frequency only where a strategy has declared
engine-level decision boundaries that can be certified against every-bar
semantics.

**Read first:** [V1.1 guide sections 29.8-29.12, 49, 60.4, 61, and 86](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-049` through `RP-056`.

Implementation scope:

- Define `WakePlanV1` for time, fill, order-event, liquidation, funding,
  price-cross, position, equity, and margin triggers. QuantBT may observe
  these execution-level conditions but may not calculate alpha indicators.
- Implement dynamic `run_until_next_wake`, deterministic coalescing/order of
  simultaneous reasons, typed wake trace, and one callback per declared
  coalesced boundary.
- Add `BlockIntentProviderV1` with explicit invalidation on fill/reject/margin
  changes and bounded block ranges. Add candidate-batch context/command buffers
  for reactive WFO with per-candidate typed errors.
- Add workload-aware route selection among Python, R1, sparse R2, block R3,
  and candidate-batch R3B. Auto may choose Python if a declared optimized
  capability is slower or not certified.

Required tests and evidence:

- every sparse/block-capable strategy has a shadow run with every-bar callback;
  actual decision-boundary inputs, commands, execution trace, account trace,
  and strategy state fingerprint must match;
- tests cover fill/order/liquidation/funding/price-cross wake collisions,
  append/replace wake plan behavior, block invalidation, candidate isolation,
  stable candidate ordering, bounded capacity, and deterministic cancellation;
- benchmark callback count, skipped bars, wake ratio, context/command bytes,
  GIL transitions, speedup, and RSS. Sparse speedup must scale with genuinely
  skipped decisions, not a changed strategy semantic.

Exit gate:

```text
R2/R3/R3B are A3 explicit only for strategies with certified wake/block
contracts. No callback may be omitted when the every-bar oracle would have
produced a different command.
```

No-debt rule and rollback:

- Unsupported dynamic wake condition fails fast; it cannot be approximated by
  polling on a different bar schedule.
- `reactive_runtime="numeric_every_bar_v1"` and legacy callbacks remain
  explicit fallbacks. No general auto-promotion occurs without per-capability
  benchmark evidence.

Implementation and closure evidence:

- `WakePlanV1`, typed static price/position/equity/margin conditions,
  `BlockPlanV1`, candidate-indexed `CandidateWakePlansV1`, typed candidate
  errors, reason-mask decoding, and `certify_reactive_shadow_v1` are public
  Python contracts. Plans are immutable and their native payloads are
  versioned; no alpha indicator is moved into QuantBT.
- The Rust `ReactiveNumericRunnerCore` implements explicit R2
  `numeric_sparse_wake_v1` and R3 `numeric_block_intent_v1` routes. It keeps
  one Rust session/accounting authority, evaluates declared engine-level
  conditions after market/funding/matching/lifecycle processing, coalesces
  same-bar reasons, and invokes Python once. R3 retains only valid bounded
  future rows; fill/reject/margin invalidation marks future rows
  `invalidated_before_execution` rather than inventing rejected orders.
- `ReactiveCandidateBatchRunnerCore` supplies R3B over one immutable prepared
  market tape and `1..64` independent Rust-owned sessions. It batches same-bar
  candidate wakes, has candidate-scoped writers, preserves candidate-ID order,
  isolates typed local candidate errors, and returns flat SoA candidate output.
  It is intentionally a prepared primitive, not an undocumented WFO loop.
- R2/R3 are exposed through `native_event_strategy` only with explicit
  `native_backend="rust"`, numeric requirements, matching capability marker,
  a single-pass kernel, and a strategy-side shadow-certification declaration.
  R3B is exposed as `RustReactiveCandidateBatchCoRuntime`. Product registry
  maturity is experimental/minimal and every R2/R3/R3B promotion row remains
  `auto_promotion=false`; `backend="auto"` remains the conservative Python
  callback route.
- Early native termination after liquidation now pads only the cold public
  result path: terminal equity/position/margin state is retained over the
  remaining submitted timestamps while fees, turnover, and funding are zero.
  The execution session is not replayed or changed. Observability records
  `bars_processed`, `terminal_path_padded`, and
  `terminal_path_original_bars`.
- Focused evidence: `tests/test_phase63_sparse_block_reactive.py` covers typed
  conditions, fill/order/liquidation/funding/price-cross collisions, complete
  wake-plan replacement, exact timestamp rejection, fill/reject/margin block
  invalidation, cancellation provenance, early-liquidation result padding,
  candidate isolation/order/capacity/stale handles, and reset. Combined R1/R2/
  R3/R3B focused suites passed `21 passed`; Rust check/test and `cargo fmt`
  passed. The generated V1.1 public inventory/corpus and the immutable
  Phase-63 benchmark manifest were refreshed after adding the public contracts;
  source/root mirror and benchmark-governance checks pass. Final package
  regression excluding only external real-data tests passed `991 passed,
  22 skipped` in `327.88s`.
- `benchmark_phase63_sparse_block_batch.py` first proves exact R1/R2/R3
  accounting and canonical-trace parity on one 10,000-bar tape. Local
  warm-median evidence: R1 `74.534 ms` / `134.2k bars/s` / 10,000 decision
  callbacks; R2 `64.673 ms` / `154.6k bars/s` / 313 callbacks; R3 `59.608 ms`
  / `167.8k bars/s` / one callback. R3B ran 16 x 10,000 prepared candidate-bars
  at `1.20M candidate-bars/s` with 313 batch callbacks. These are
  workload-specific measurements; no automatic route promotion follows.

**Phase 63 closure:** the declared R2/R3/R3B contracts are usable and
auditable at A3 explicit scope. There is no hidden Python accounting loop,
no callback omission without a declared/certified boundary, and no unresolved
implementation debt inside this phase. Persistent WFO integration, broader
WFO lifecycle correctness, and any future auto-promotion remain separately
planned Phase 64/65 work, not incomplete Phase 63 behavior.

### Phase 64 / Guide Phase 8 - WFO Correctness, Causality, And Lifecycle Closure

**Status: completed (2026-09-04).**

**Goal:** close WFO time alignment, signal timing, strategy isolation, fold
state, and objective provenance before changing WFO throughput architecture.

**Read first:** [V1.1 guide sections 2.1-2.2, 30-31, 50, 60.1, 60.5, 64, and 87](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-057` through `RP-064`.

Implementation scope:

- Replace WFO row-count alignment with `CalendarPlanV2`. Preserve an explicit
  legacy calendar ID only for reproducibility; never relabel a symbol because
  lengths match.
- Make each WFO adapter declare intent kind, observation phase, effective
  phase, whether it is already shifted, and target/order/position semantics.
  A generic Series is never assumed to be an already-effective position.
- Implement and record purge, embargo, label horizon, warmup policy, cutoff,
  and fold account policy: `ResetFlat`, `CarryPosition`, `CloseAtBoundary`, or
  `ReplayPriorState` with auditable event behavior.
- Implement `StrategyLifecycleV1` spawn/reset/seed/fingerprint/snapshot rules.
  Prohibit unsafe mutable strategy reuse across trial/fold/thread boundaries.
- Version WFO causality schedules as retrospective global, trusted strategy
  global, engine-enforced per-fold, and engine-enforced nested. Preserve legacy
  aliases but resolve them into exact metadata.
- Treat proxy scoring as screening only. Add rank correlation, Top-K overlap,
  winner regret, and false-positive gates against native accounting scores.

Implementation design lock (read together with guide sections 30-31):

1. Add versioned public contracts rather than overloading a raw Series:
   `WfoIntentContractV1`, `WfoCausalityScheduleV2`,
   `FoldWarmupPolicyV1`, `FoldAccountPolicyV1`, and
   `StrategyLifecycleV1`. Legacy endpoint arguments remain aliases and resolve
   into an exact contract ID in result metadata.
2. Make `CalendarPlanV2` the WFO clock source. `exact_v2` stays the default;
   `intersection_v2` is accepted only when it produces one fully observed
   canonical clock. Union/primary-clock WFO execution remains fail-closed until
   a downstream execution route can consume observed/stale masks end-to-end.
3. Build each `WalkForwardFold` from integer spans on the canonical clock and
   retain train, validation, test, warmup, purge, embargo, cutoff, and account
   policy provenance. A nonzero label horizon removes the final affected train
   observations before an OOS boundary; embargo bars are explicit non-trading
   gaps before the subsequent eligible OOS window.
4. Spawn/reset strategy state by stable `(run, candidate, fold, cutoff)` IDs.
   Classes instantiate per invocation; lifecycle-aware objects use `spawn` and
   `reset`; callable instances are isolated by deep-copy or fail in certified
   mode. No mutable instance is silently reused across trial/fold calls.
5. Keep `CarryPosition` as the existing continuous stitched-account route.
   `CloseAtBoundary`, `ResetFlat`, and `ReplayPriorState` are exposed only
   through explicit boundary execution plans; any target/route combination
   without an auditable implementation raises instead of falling back to
   carry. Boundary metadata always says whether final accounting is continuous
   or segmented.
6. Proxy certification never changes a chosen candidate. It evaluates a
   bounded IS-only candidate sample with the endpoint/native scorer, records
   Spearman rank, Top-K overlap, winner regret, and false-positive rate, and
   can fail closed when a declared screening contract misses thresholds.

Phase 64 test matrix:

- exact/intersection calendar plan, shifted timestamp rejection, cutoff and
  future-funding mutation invariance;
- zero/nonzero label horizon, purge, embargo, and all warmup range
  construction;
- function/class/lifecycle object/copy-isolated object, stable seed,
  fold-order, reset, close, and fingerprint provenance;
- explicit intent timing declaration validation and legacy compatibility
  labeling;
- carry/replay/close/reset policy capability or deterministic fail-closed
  behavior, including boundary provenance;
- proxy pass/fail screening evidence and no-selection-mutation proof;
- source/root mirror, focused WFO regression, then package regression.

Required tests and evidence:

- causal mutation tests: change future bars/funding/test labels/calendar/fold
  execution order and prove prior selection, signal, score, and per-fold result
  remain unchanged where contract requires;
- train/validation/test/warmup/purge/embargo ranges and account boundary events
  appear in fold provenance;
- class/instance lifecycle, repeat seed, worker count, fold ordering, cache
  cutoff, position carry/close/reset/replay, and timing declarations pass;
- proxy is disabled for a workload when its declared native ranking gates fail.

Exit gate:

```text
WFO is A2 correct independently of runtime speed: calendar mapping, causal
cutoffs, timing, lifecycle, account policy, proxy role, and selection
provenance are explicit and tested.
```

No-debt rule and rollback:

- A legacy/global schedule remains available only with its retrospective or
  trusted semantics recorded. It must not be described as engine-enforced
  causal merely because its output is OOS-shaped.
- Unsupported fold account policy or strategy lifecycle capability fails at
  construction; it does not reuse state silently.

**Completed implementation and certification evidence:**

- Added the public versioned WFO contract surface:
  `WfoIntentContractV1`, `WfoCausalityScheduleV2`,
  `FoldWarmupPolicyV1`, `FoldAccountPolicyV1`, and
  `StrategyLifecycleV1`. A legacy `Series` route remains compatible but is
  explicitly marked `legacy_series_adapter_v1` and timing-unverified. Result
  metadata now records the contract schema, intent timing, resolved causality
  schedule, and the precise scope of the strategy causality claim.
- WFO now builds its clock through CalendarPlanV2. `exact_v2` rejects shifted
  equal-length timestamps; `intersection_v2` projects only the common fully
  observed clock; `legacy_v1` remains an explicitly named reproduction route.
  Prepared WFO signatures include calendar and all fold range witnesses.
- Fold construction is integer-clock based and separately records warmup,
  label-horizon, purge, test, embargo, cutoff, and account policy ranges.
  `label_horizon_bars`, `purge_bars`, and `embargo_bars` are no longer hidden
  in a row mask. Optional strategy `warmup(...)` receives only the declared
  warmup range and never contributes PnL to the emitted OOS target.
- Strategy lifecycle isolation is now deterministic: classes instantiate per
  call; lifecycle objects must spawn an isolated resettable instance; callable
  objects are deep-copied or fail in `isolated_v1`; and seeds/market
  fingerprints are derived at the causal cutoff rather than from a full-tape
  prepared-context identity. The bounded lifecycle ledger records spawn/reset/
  warmup/close/fingerprint provenance and dropped-row count.
- Carry accounting remains the continuous stitched target route. `close_at_boundary`
  is accepted only with an explicit embargo gap, where the stitched target is
  flat. `reset_flat` and `replay_prior_state` now fail closed on the generic
  stitched endpoint rather than being misrepresented as carry. They require a
  segmented-account or explicit order/fill-replay adapter respectively.
- Proxy rank validation is IS-only and bounded. It records Spearman, Top-K
  overlap, winner regret, and false-positive rate against an endpoint/native
  scorer. `enforce` rejects a failed proxy contract; the audit never mutates a
  candidate selection through an undeclared native rerank.
- Added `tests/test_phase64_wfo_correctness.py` (16 cases) covering calendar
  mismatch/intersection, all temporal guard/warmup policies, future funding and
  test-label mutation invariance, fold-call order, lifecycle isolation,
  intent fail-closed behavior, boundary-account capability, proxy pass/fail,
  and endpoint metadata propagation. Focused WFO/product checks passed
  `94 passed`; source/root mirror, generated public API/product/V1.1 baseline,
  and documentation link gates all pass.
- Final non-real package regression passed `1007 passed, 22 skipped` in
  `326.06s`. The warnings are existing Optuna experimental notices, documented
  missing-intrabar-OHLC fallback warnings, one legacy slippage conversion
  notice, and matplotlib layout warnings; no Phase 64 failure or regression
  occurred.

**Phase 64 closure:** WFO orchestration is A2-correct at the declared boundary:
calendar mapping, fold exclusions, lifecycle state, strategy timing declaration,
account-policy capability, proxy role, and selection provenance are explicit
and tested. Arbitrary batch Python feature code remains strategy-owned and is
not falsely certified as intra-fold causal. Segmented accounts, full order/fill
replay boundaries, and persistent Rust WFO ownership are later explicit
capabilities in Phase 65, not silent fallbacks or unresolved Phase 64 behavior.

### Phase 65 / Guide Phase 9 - Native WFO Runtime V2

**Status: complete (2026-09-04; source-tree certification complete).**

**Goal:** move repeated candidate x fold x scenario simulation into a persistent
Rust evaluation runtime without pretending that arbitrary Python feature
generation has become native.

**Read first:** [V1.1 guide sections 32, 51, 60.5, 62, 63, 77-78, and 87](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-065` through `RP-077`.

Implementation scope:

- Implement `NativeWfoPlanV2` with shared prepared market, instrument registry,
  fold plan, execution/account/metric contracts, scenario plan, optimizer
  schedule, resource budget, and immutable fingerprints.
- Define prepared signal, target, static command, portfolio target, and
  Strategy IR intent handles. Market allocations, fold windows, and prepared
  tape physical storage must not copy per candidate/fold/scenario.
- Build one persistent worker pool per WFO run with retained sessions, account
  scratch, order arena, metric reducers, bounded error rows, deterministic RNG,
  cancellation, poison recovery, and cost-aware work stealing.
- Implement W0 compatibility, W1 prepared Python strategy, W2 batched intent
  generation, and declared reactive WFO process/batch paths without moving
  features or indicators into QuantBT.
- Support separately versioned `certified_sequential_v1` ask/evaluate/tell
  parity and `throughput_batch_v1` behavior. Batch adaptive TPE must never
  claim sequential candidate-sequence parity.
- Return compact native candidate/fold/scenario metric matrices; compose custom
  objectives in Python without materializing an equity path for every trial.
  Top-K audit reruns use the exact same plan/intent/seed and match score
  fingerprint.

Implementation design lock (read together with guide section 32):

1. `NativeWfoPlanV2` owns one prepared market/template, immutable fold and
   contract tables, resource budget, and content fingerprints for a complete
   WFO invocation. It rejects a changed calendar, instrument, execution, or
   intent contract before scoring.
2. `NativeWfoRuntimeV2` retains Rust workers/session scratch for the complete
   plan lifetime. Certified sequential calls preserve ask/evaluate/tell order;
   throughput batching is separately versioned and never claims identical TPE
   candidate sequence.
3. W0 remains the exact compatibility adapter. W1/W2 accept causally prepared
   Python signal/target/command handles; static Strategy IR is the first A4
   capability. Unsupported target, portfolio, package, or reactive contracts
   fail with a capability reason rather than crossing a new Python bridge.
4. Score rows are typed SoA arrays only. Python materializes DataFrames,
   reports, and audit detail after selection; score/audit reruns compare the
   same plan/intent/seed fingerprint.

Phase 65 test matrix:

- fixed candidate x fold matrix parity against Phase 64 oracle;
- sequential seed/candidate/objective/pruning/selection parity;
- prepared/unprepared and one/many worker deterministic parity;
- top-K score/audit fingerprint parity, cancellation/poison/reset behavior,
  and no-copy market/tape counters;
- warm/cold benchmark breakdown for strategy generation, native score,
  optimizer, adaptation, copy bytes, worker utilization, and RSS plateau;
- installed-extension source/root mirror and full regression gate.

Required tests and evidence:

- fixed candidate matrix parity covers every candidate/fold metric/trace;
- sequential optimizer has exact seed, candidate sequence, objective/pruning,
  selected parameter, and stitched OOS parity;
- batched schedule has fixed-matrix exact score parity, deterministic seed plus
  batch-size behavior, worker-count invariance, and quality/regret report;
- prepared/unprepared, score/audit, one/many worker, cancel/poison recovery,
  and strategy cache cutoff tests pass;
- benchmark reports strategy preparation/generation separately from ingestion,
  native simulation, metrics, optimizer, report, cold/warm RSS, worker
  utilization, and copy bytes.

Exit gate:

```text
Prepared signal/target/order WFO is A4 only for capability rows that pass
correctness and end-to-end evidence. Runtime creates one worker pool per run,
has zero market/tape copies per candidate execution, bounded retained results,
and RSS plateaus after warmup.
```

No-debt rule and rollback:

- Python strategy generation time is reported rather than hidden from the
  endpoint benchmark. A strategy that cannot prepare/batch remains an exact
  W0/W1 hybrid capability, not an incomplete native claim.
- Legacy WFO orchestration and explicit optimizer schedule IDs remain rollback
  paths until each promoted workload reaches stable soak.

**Closure evidence (2026-09-04):**

- Added `NativeWfoPlanV2` / `NativeWfoRuntimeV2` as an explicit A4
  single-symbol `strategy_ir_signal_target_v1` execution companion. Rust owns
  the immutable prepared market/fold/account plan, retained fold sessions,
  candidate-by-fold task scheduling, scalar metric rows, bounded error side
  table, cancellation, reset, worker teardown, and selected audit replay.
  Python owns W1/W2 causal signal generation, Optuna control, custom objective
  composition, and cold DataFrame/report adaptation.
- Added one controlled `NativeWfoPreparedSignalBatchV2` ingest boundary. Its
  plan fingerprint prevents cross-plan reuse; repeated score/audit calls reuse
  the Rust-owned signal batch. Evidence reports `0` market bytes and `0`
  candidate-execution bytes copied per score, while making the one `8,389,120`
  byte Python-to-Rust ingest explicit rather than falsely calling it zero-copy.
- `certified_sequential_v1` uses an explicit `NopPruner` because WFO has one
  valid scalar only after every fold completes. It was compared against the
  previous ask/evaluate/tell fold oracle at the same seed: candidate sequence,
  parameters, objective values, trial states, and selected winner match.
  `throughput_batch_v1` is separately deterministic by seed/batch size and
  records no sequential-equivalence claim; optional quality regret is emitted
  only against an explicit external reference objective.
- Exact score/audit checks cover W1/W2 equivalence, one/many worker
  determinism, source-batch intent fingerprint replay, terminal fingerprint
  parity, bounded error-slot remapping, cancellation/reset recovery, and
  fail-closed unsupported intent kinds. Rust unit tests cover bounded worker
  poison recovery and worker-pool reuse.
- The reproducible local 64-candidate x 4-fold x 4,096-bar fixture measured
  `232.514 ms` for native score/metrics (`4.51M` candidate-fold-bars/s),
  versus `319.437 ms` for the prior fold-batch oracle (`1.37x`). Scalar
  accounting parity is exact for final equity, fees, funding, turnover, and
  fill/rejection counts. Strategy preparation/generation, intent ingestion,
  report adaptation, worker use, and RSS are separately recorded in
  `benchmarks/native_event/results/phase65_native_wfo.{json,md}`.
- Documentation now includes `docs/native_wfo_runtime.md`, endpoint and
  methodology links, capability boundaries, and benchmark interpretation.
  Source/root mirror, generated native/product/public inventories, baseline,
  docs-link, benchmark-governance, and module-ownership checks are clean.
- Final local gates: focused Phase 64/65 tests `24 passed`; full Python suite
  `1015 passed, 22 skipped`; Rust workspace format, `clippy -D warnings`, and
  `85` Rust unit tests pass. Existing warnings are Optuna experimental APIs,
  documented missing-intrabar fallback, legacy slippage conversion, and
  matplotlib layout warnings; none is a Phase 65 failure.

**Certified boundary:** this phase intentionally does **not** silently replace
generic `QuantBTEndpoint.walk_forward()`. Arbitrary pandas callbacks (W0),
target-unit/notional/weight/equity workloads, static order tapes, portfolio or
package targets, carry/replay account policies, and reactive WFO are not
coerced through this runtime. They remain separately versioned future
capabilities in later phases, not incomplete behavior hidden behind this A4
claim.

### Phase 66 / Guide Phase 10 - Rust Target And Vectorized Authority

**Status: complete (A3/A4 explicit target routes).**

**Goal:** migrate common static signal/target simulation to direct Rust target
delta kernels using the certified market, instrument, execution, account,
metric, and result authorities.

**Read first:** [V1.1 guide sections 33, 52, 60.2, 63, and 88](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-078` through `RP-086`.

Implementation scope:

- Freeze all legacy target timing IDs, including same-close and next-open/close,
  before porting. Never silently turn same-close research behavior into
  next-open execution.
- Implement direct-delta `TargetUnits` first: read target, resolve quantity,
  quantize, calculate delta from actual position, validate stale/tradable/
  instrument constraints, apply execution model, preview/commit account, and
  update native metrics without generic `OrderCommand` allocation.
- Promote `TargetNotional`, `TargetWeight`, and `EquityFraction` separately.
  Each must define price source, multiplier, equity denominator/snapshot,
  leverage/gross semantics, missing/invalid-target behavior, and rounding.
- Compile static DCA schedule to typed target/order tape only. Dynamic
  fill-dependent DCA remains a reactive workload.
- Wire prepared target handles into NativeWfoRuntimeV2 and stage explicit Rust
  routes before any auto policy change.

Required tests and evidence:

- independent target oracle, legacy Numba production, and Rust compare target
  resolution, accepted quantities, execution/account trace, metrics, and
  terminal fingerprint;
- units/notional/weight/equity fraction are tested as distinct contracts with
  long/short, constraints, missing/invalid target, scale/reduce/reverse,
  fee/funding/margin/liquidation cases;
- prepared/non-prepared and score/compact/audit parity pass;
- warm and cold endpoint benchmarks include conversion/ingestion/materialization
  and demonstrate no JIT dependency, no pandas in score, one market pass, and
  no generic arena for simple direct target delta.

Exit gate:

```text
Each separately certified target intent reaches A3 first and A4 only after its
installed-wheel/end-to-end route passes. Native WFO consumes target handles
without event-command conversion.
```

No-debt rule and rollback:

- A target mode with unresolved denominator/timing/rounding semantics remains
  explicit Python/Numba compatibility, not a partially promoted Rust route.
- Numba remains version-pinned/reproducible until Phase 71 A5 removal review.

**Completion evidence (local, 2026-09-05):**

- Added the frozen `close_target_v2_same_close` direct Rust target authority
  for `target_units`, `target_notional`, `target_weight`, and
  `equity_fraction`. Quantity resolution uses the bar's pre-rebalance equity
  snapshot where required; leverage remains a buying-power/margin constraint,
  never a hidden target multiplier. Non-finite targets, unsupported target
  clocks, stale/non-tradable rows, lot constraints, post-cost margin failure,
  funding, and liquidation fail or account deterministically.
- Added a typed static-DCA absolute-target compiler and the separate,
  single-symbol, serial `NativeTargetWfoRuntimeV2`. It owns a prepared direct
  target tensor and Rust score/audit replay without converting target intent to
  generic event commands. Shared-account multi-symbol target WFO is explicitly
  deferred to Phase 67 rather than being misrepresented as portfolio support.
- Kept `target_runtime="auto"` on the frozen Numba compatibility route. Rust
  is selected only by `target_runtime="rust"`; there is no silent public
  migration. Numba remains the reproducibility comparator through the Phase 71
  A5 removal review.
- Exact three-way independent-Python-oracle / Numba / Rust accounting parity,
  prepared versus non-prepared target WFO parity, score/compact/audit parity,
  invalid-target and static-DCA contracts passed. Focused Python gates: `44
  passed`; package regression: `1021 passed, 22 skipped` with
  `tests/test_real.py` and `tests/test_real_endpoints.py` deliberately outside
  this local gate because their external data-loader dependency requires
  `pyarrow`. Rust workspace: `86 passed`, including the four direct target /
  target-WFO unit gates; `cargo fmt` and workspace `clippy -D warnings` pass.
- The controlled 20,000-bar benchmark recorded Rust typed prepared score
  `1.607 ms` (`12.45M bars/s`) versus Numba pure kernel `0.607 ms`
  (`32.97M bars/s`), and Rust public compact `23.432 ms` (`853,549 bars/s`)
  versus Numba compact `58.600 ms` (`341,295 bars/s`). The narrow Rust score
  path is therefore not overclaimed as faster than Numba's pure kernel; the
  public compact route is `2.50x` faster on this fixture. Warm score RSS delta
  was `3.01 MiB` with no retained path arrays, one native pass, and no generic
  order arena.
- Rebuilt a current `quantbt-engine==1.1.0` / `quantbt-native==0.4.1` pair and
  proved wheel source hash parity plus clean wheel and sdist installation. The
  installed-wheel smoke executes all four direct target kinds and static DCA
  from `site-packages`; it is not merely an import probe.
- The scope has no unresolved Phase 66 implementation debt. Phase 67 shared
  multi-symbol account admission/portfolio semantics, dynamic fill-dependent
  grid/DCA, generic callback WFO, and automatic Rust promotion are deliberate
  next-phase boundaries, not fallback behavior hidden in this route.

### Phase 67 / Guide Phase 11 - Rust Shared-Account Portfolio Authority

**Status: complete (explicit shared-account Rust target authority certified).**

**Goal:** execute linear multi-symbol portfolio targets in Rust against one
shared account with deterministic admission, attribution, and liquidation.

**Read first:** [V1.1 guide sections 34, 53, 60.2, 60.6, 62, and 88](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-087` through `RP-096`.

Implementation scope:

- Rewire the existing Rust target-units helper to CalendarPlanV2,
  InstrumentRegistryV2, common execution/account/result contracts, and one
  shared linear account. Do not create a per-symbol shadow cash/margin model.
- Implement and certify `SequentialLegacy`, `ReduceFirstThenIncrease`,
  `ProRataToAvailableMargin`, and `AllOrNoneRebalance` as distinct admission
  policy IDs. Reductions have priority; pro-rata scales only risk increases and
  allocates residual lots deterministically; all-or-none has reservation-backed
  transaction immutability.
- Add units, notional, weight, and equity-fraction target matrices through the
  common target resolver, with explicit planner/execution authority separation.
- Add native per-symbol realized/unrealized PnL, fees, funding, turnover,
  exposure, margin, and reconciliation attribution. Integrate portfolio target
  matrices with NativeWfoRuntimeV2.
- Implement account-wide liquidation and deterministic symbol-reduction policy,
  with stale/missing/no-observation/non-tradable behavior explicit.

Required tests and evidence:

- 1/2/8/20-symbol portfolio corpus covers long-only, long/short,
  market-neutral targets, sparse/high-turnover rebalance, sufficient/
  insufficient margin, simultaneous reduce/increase, stale/missing symbols,
  liquidation, and calendar policy;
- accepted target positions, quantization, margin admission, account trace,
  fees/funding/turnover, equity, and per-symbol attribution sum to portfolio
  totals within contract tolerance;
- all-or-none reject is fingerprint-immutable; pro-rata residual allocation is
  stable under symbol-input permutation; worker count does not change results;
- score avoids per-symbol pandas outputs, audit/compact retain bounded
  attribution, and prepared multi-symbol benchmark reports RSS and phase split.

Exit gate:

```text
Target-units portfolio reaches A3/A4 first; notional/weight/equity fraction
promote independently after their complete matrix. Generic portfolio routing
records planning versus execution authority and never promotes unavailable
planner semantics.
```

Completion evidence:

- `SharedPortfolioTargetRequestV1` now owns one linear quote-settled
  gross-cross account in Rust for planned bar-major target matrices. It has
  distinct fingerprinted `sequential_legacy`, `reduce_first_then_increase`,
  `pro_rata_to_available_margin`, and `all_or_none_rebalance` admission
  policies; reductions precede increases where declared, pro-rata residual
  lots use canonical symbol order, and all-or-none preview leaves the account
  immutable on rejection.
- The explicit helper and prepared target-WFO companion use the same typed
  Rust request, canonical market/template handles, account, fees, funding,
  margin, liquidation, bounded audit, and flat attribution. A WFO
  candidate/fold is reset-flat with one fresh shared account, never a stitched
  account or a callback-WFO replacement. Generic `portfolio()` continues to
  record `python_portfolio_planner_v1` / `numba_native_portfolio_v1` and does
  not silently promote.
- The corpus covers 1/2/8/20 symbols, all four policies, reductions before
  increases, deterministic pro-rata, atomic rollback, units/notional/weight/
  equity-fraction resolution, stale/non-tradable rejection, funding,
  liquidation reconciliation, score retention, V2 canonical symbol ordering,
  prepared/direct WFO parity, serial fail-closed scheduling, and the generic
  route authority boundary. `target_units` and prepared shared target-WFO are
  certified explicit rows; notional/weight/equity-fraction remain explicit
  experimental rows.
- Final local gates: focused release/domain suite `113 passed`; complete Python
  suite `1057 passed, 22 skipped` with only the policy-excluded external
  `test_real.py` and `test_real_endpoints.py`; Rust workspace `86 passed`,
  `cargo fmt --check`, and workspace `clippy -D warnings` pass. Source mirror,
  generated product/baseline artifacts, module ownership, release-manifest,
  and benchmark governance checks pass.
- The committed 2,000-bar × 20-symbol benchmark records a prepared score
  median of `2.390 ms` (`16.74M bar-symbols/s`) and a 16-candidate × 2-fold
  prepared WFO median of `28.462 ms` (`44.97M
  candidate-fold-bar-symbols/s`). It proves score/compact terminal parity,
  prepared/direct fold parity, `market_copy_bytes=0` in WFO, and no generic
  order arena. Process RSS was `151.30 MiB` at start, `155.39 MiB` prepared,
  `158.41 MiB` after score, and `173.18 MiB` after prepared WFO; these are
  workload-scoped retained-process observations, not a generic endpoint claim.
- The Phase 67 Python request builders were split out of
  `native_execution.py`, returning that cache owner below the module size
  budget while preserving content signatures, cache ownership, ingress-copy
  counters, and public cache methods exactly.

No-debt rule and rollback:

- Risk-parity/covariance/beta estimation remains strategy-owned, not a missing
  executor feature. Cross-margin beyond the declared linear contract is
  unsupported/fail-fast.
- Existing Python/Numba portfolio implementation remains explicit rollback
  until the individual capability has A5 certification.

### Phase 68 / Guide Phase 12 - Bounded Package And Arbitrage Authority

**Status: complete.**

**Goal:** make selected same-account linear package policies executable in Rust
with actual-fill dependencies, reservations, residual accounting, and explicit
policy-level capability claims.

**Read first:** [V1.1 guide sections 35, 54, 60.7, 62, and 88](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-097` through `RP-107`.

Implementation scope:

- Freeze `PackageIntentV2`, leg dependency/quantity contracts, residual schema,
  package state machine, reservation lifecycle, and package terminal status.
- Rewire `AtomicBarSimulation` to common calendar/instrument/execution/account
  authority. Then implement, certify, and expose `Sequential`, `BestEffort`,
  `HedgeAfterPrimary`, and partial compensation/unwind in that order.
- Use actual committed fill quantity for dependent hedge legs; apply hedge
  instrument quantization after actual-fill calculation. Residual exposure is
  a required output, never a hidden orphan position.
- Add typed basis, stat-pair, calendar, and index-basket adapters only where
  their same-account linear contract is complete. Integrate package scenarios
  and WFO batching only after policy correctness.
- Add triangular/cross-exchange foundation types but fail closed until currency
  conservation/multi-venue accounts/clocks/prefunding authority are certified.

Required tests and evidence:

- all-leg fill, primary/hedge partial fill, secondary reject, reservation
  failure/leak, atomic reject, residual detection, compensation/unwind,
  sequential timing, actual-fill hedge, cancel/fill ordering, and package PnL
  reconciliation tests pass;
- package trace and account fingerprint reconcile reservations created minus
  consumed minus released to zero;
- single package, multiple package, low/high leg count, and scenario/WFO
  benchmarks show bounded flat leg buffers and no Python object per leg/fill in
  score mode;
- mutation/fuzz suite catches requested-vs-actual hedge mistakes and hidden
  residual/orphan exposure.

Exit gate:

```text
Only individually certified same-account linear package policies reach A3/A4.
The generic arbitrage endpoint routes by exact package subtype/policy rather
than treating an enum declaration as executable authority.
```

No-debt rule and rollback:

- Triangular and cross-exchange are intentional foundation-only non-goals in
  V1.1 unless their distinct multi-currency/multi-venue contracts pass. They
  must return explicit unsupported/experimental metadata.
- Python package path stays an explicit fallback for unpromoted policy rows;
  no blanket endpoint auto-promotion is permitted.

Completion record:

- Implemented a typed `PackageIntentV2` / `PackageLegIntentV2` request path
  under the common Rust `FullSession`; Rust is the single account, order,
  lifecycle, fill, fee, funding, margin, reservation, and terminal-result
  authority for this bounded workload. The package planner only validates,
  reserves, resolves leg dependencies, and compiles accepted commands.
- Certified the explicit same-account linear policies
  `atomic_bar_simulation`, `sequential`, `best_effort`, and
  `hedge_after_primary`. Dependent hedge quantity is derived from the committed
  primary fill and quantized only afterwards. Residuals are explicit audit
  data; `unwind_package` emits deterministic reverse-order compensation and
  cannot hide remaining gross exposure.
- Added score/compact/audit output levels plus an isolated
  `PackageScenarioBatchV2`: one Python-to-Rust call for pre-built independent
  scenario rows, immutable prepared market/template reuse, and reset-flat
  account state per row. It is intentionally scalar-only; a selected candidate
  is rerun through the single package route for audit provenance.
- Added typed adapters for same-account linear basis, stat-pair, calendar, and
  index-basket plans. Generic `arbitrage()` remains Python-authoritative;
  triangular and cross-exchange requests fail closed because their
  multi-currency/multi-venue authority is not claimed.
- The semantic descriptor now iterates every registry-owned portfolio scalar
  generated from `native_event_product_registry.json`. This prevents a future
  capability addition from leaving the installed Rust extension on an older
  descriptor shape.
- Evidence: `tests/test_phase68_rust_package_authority.py` covers actual-fill
  hedge parity, atomic immutability, residual/unwind, reservation/margin,
  stale/same-bar rejection, 2/4/20-leg parity, selected adapter routing,
  fail-closed venue cases, and mutation/fuzz checks. The 2,000-bar artifact at
  `benchmarks/native_event/results/phase68_bounded_package.md` records
  score/compact/audit terminal parity, batch/single parity, zero market copies,
  and bounded RSS.
- Final gates: focused package/release suite `81 passed`; full Python suite
  `1072 passed, 22 skipped` (external real-data tests excluded by policy);
  Rust workspace tests, `cargo clippy -D warnings`, generated-contract,
  source-mirror, benchmark-governance, baseline, architecture, and docs-link
  gates pass.

Scope conclusion:

- No unresolved correctness debt remains within the certified bounded Package
  V2 contract. The explicit-only promotion policy is deliberate, not a gap:
  there is no generic endpoint auto-route until its complete Python fallback,
  public result contract, and exact domain parity are separately certified.
- L2/queue matching, venue-native atomicity, cross-currency settlement,
  multi-venue prefunding, triangular/cross-exchange arbitrage, and generic
  callback WFO are distinct future contracts, not silently approximated by
  this route.

### Phase 69 / Guide Phase 13 - Rust Intrabar Authority

**Status: complete.**

**Goal:** port the already bounded intrabar contract into specialized Rust
kernels without changing timing, ambiguity, bracket, trailing, or session
semantics to chase performance.

**Read first:** [V1.1 guide sections 36, 55, 60.8, 63, and 89](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-108` through `RP-114`.

Implementation scope:

- Produce an intrabar contract manifest for entry timing, SL/TP, gap behavior,
  same-bar ambiguity, trailing update phase, technical exit ordering, session
  window, EOD flatten, stale-signal cancellation, re-entry suppression,
  funding, and liquidation.
- Implement specialized `BracketIntrabarKernelV1` and `SessionIntrabarKernelV1`
  over common market/instrument/execution/account/result authorities. Do not
  force the branch-heavy intrabar semantics through the generic event engine.
- Generate a frozen corpus from the current Python reference and Numba path;
  any legacy bug is resolved in written spec before a documented parity
  difference is accepted.
- Add ambiguity audit fields and explicit path-policy ID. Stage an explicit
  Rust route before auto promotion and retain Numba as the reproducibility
  comparator.

Required tests and evidence:

- Python reference, Numba production, and Rust compare entry/exit, SL/TP,
  gap, trailing state, technical-exit conflict, session, EOD, stale/re-entry,
  funding/liquidation, trace, and terminal fingerprint;
- fixtures cover stop-only, target-only, both-touched, stop/target gaps,
  trailing-before/after extreme, session boundary, and EOD force-flat;
- compact/audit preserve chosen ambiguity path, audit retention is bounded,
  and score has no JIT cold-start dependency;
- warm/cold installed-wheel benchmark is no worse than the approved Numba
  budget and reports adapter versus kernel time separately.

Exit gate:

```text
The bounded intrabar capability reaches A3, then A4 only after complete
trace parity, installed-wheel evidence, and end-to-end performance gate.
FillReplay remains its separate accounting anchor.
```

No-debt rule and rollback:

- OHLC intrabar remains a declared bounded-path simulation, never a claim of
  reconstructed L2 order-book truth. Unsupported path policy fails fast.
- The existing Numba route remains version-pinned for at least one stable
  release after A4 and is the explicit rollback path until A5.

Completion evidence:

- Added the versioned [`intrabar_bracket_v1`](../contracts/intrabar_contract_v1.json)
  contract manifest and the specialized Rust `BracketIntrabarKernelV1` /
  `SessionIntrabarKernelV1` path. The route owns one prepared strict-OHLC
  market tape, compact intent/session tapes, account state, fills, funding,
  margin, liquidation, bounded audit rows, and typed SoA output for one run.
- Added `QuantBTEndpoint.intrabar_bracket_rust(...)` as an explicit-only
  route. It preserves the public `BacktestResultV2` surface for
  `minimal`/`standard`/`audit`; direct native `score` remains deliberately
  scalar-only and cannot quietly construct a report. `intrabar_bracket()`
  remains the Numba default and rollback comparator; no generic auto route was
  changed.
- `tests/test_phase69_rust_intrabar_authority.py` validates exact
  Python-reference/Numba/Rust paths for SL/TP, gaps, all supported ambiguity
  policies, trailing, technical reversal, open funding, quantity/tick rules,
  liquidation, session/EOD/stale/re-entry behavior, bounded audit retention,
  prepared-runner parity, and public contract propagation. The focused
  intrabar/product/baseline gate passed `84`; final repository regression
  passed `1083 passed, 22 skipped` with only external real-data tests excluded.
- `cargo test --workspace` and `cargo clippy --workspace --all-targets -- -D
  warnings` pass. A freshly built `quantbt-native==0.4.1` CPython 3.12 Linux
  wheel was force-installed without network; it exposes
  `rust_intrabar_bracket_v1` and the Phase 69 authority suite passes against
  that installed extension.
- The reproducible 2,000-bar artifact records exact terminal/path parity, one
  native boundary, zero Python callbacks, zero prepared-market copy bytes, and
  bounded audit behavior. Current local medians are `0.096 ms` / `20.90M
  bars/s` for direct prepared score, `0.159 ms` / `12.60M bars/s` for prepared
  compact, and `2.538 ms` / `788,099 bars/s` for the ordinary public compact
  adapter, compared with the Numba standard/path comparator at `2.053 ms` /
  `974,199 bars/s`. Adapter and kernel measurements remain explicitly
  separated.
- Generated product contracts, V1.1 baseline inventory/corpus, source mirror,
  benchmark governance, docs links, and whitespace gates pass.

Certified scope and deliberate future contracts:

- Certified: deterministic, next-open, single-symbol strict-OHLC bracket
  execution with declared funding timestamp semantics, bounded audit, and
  fail-closed unsupported ambiguity policies.
- Not claimed: L2/order-book reconstruction, queue priority, partial-fill
  matching, dynamic grid/DCA state machines, multi-symbol shared cross-margin,
  portfolio/package execution, or options. These are separate future domain
  contracts, not untracked defects in the certified intrabar route.

### Phase 70 / Guide Phase 14 - Options P0 Correctness Containment

**Status: complete (2026-09-05).**

**Goal:** prevent options simulations from silently claiming unsupported
lifecycle, settlement, fee, margin, or liquidation semantics while full Rust
options authority remains a V1.2 program.

**Read first:** [V1.1 guide sections 2.8, 3.2, 37, 56, 60.9, and 89](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-115` through `RP-122`.

Implementation scope:

- Add an options capability registry keyed by exercise style, premium
convention, settlement style, margin model, execution model, and validation
status.
- Fail fast at plan construction for American, Quanto, physical settlement, or
venue-exact portfolio margin requests without the required authoritative model.
- Consolidate package guard, fill ledger, fee schedule, cash/position ledger,
  margin preview/admission, maintenance, liquidation, expiry, and settlement
  sequencing so only one authority commits financial state.
- Require explicit settlement event/source/timestamp provenance. A last-row
  mark fallback, if retained for legacy research, is visibly non-certified.
- Expand independent oracle/corpus for supported European linear and explicitly
  modeled inverse contracts, fees, margin rejects, settlement, and capability
  rejection. Write a V1.2 handoff for multi-currency Rust options, assignment,
  exercise, and portfolio margin.

Required tests and evidence:

- supported European contract lifecycle/accounting tests pass;
- unsupported American/Quanto/physical requests fail before simulation with
  actionable capability code;
- package guard/ledger/result fee totals reconcile; failed pre-fill margin
  admission leaves state unchanged; settlement occurs exactly once;
- maintenance breach and liquidation status derive from timeline state, not
  post-hoc final flags; option capability metadata appears in results/docs.

Exit gate:

```text
Options remain Python-primary but are correctness-contained. Every supported
result has one ledger/fee/margin/settlement authority, and every unsupported
combination fails before a misleading simulation can run.
```

No-debt rule and rollback:

- Full Rust options, American exercise/assignment, Quanto, physical delivery,
  multi-currency ledger, and venue-exact portfolio margin are intentionally
  deferred V1.2 contracts, not V1.1 Rust-primary claims.
- Existing supported Python options routes remain public; containment introduces
  only explicit rejection or provenance where a claim was previously unsafe.

Implementation and evidence:

- Added a public, machine-readable option capability matrix and stable
  `OptionCapabilityError.code` values. American, Quanto, physical settlement,
  unmodeled future delivery, and unvalidated venue-exact margin fail before
  option-tape preparation; European linear/inverse cash contracts retain their
  supported Python-primary route.
- Package execution now has one financial sequence: BBO quote, authoritative
  fee resolution, cloned-ledger preview, reporting-currency debit/credit guard,
  post-cost margin admission, and exact-fill atomic commit. Rejected admission
  is ledger-immutable and reports an actionable reason.
- Maintenance is evaluated on the event/market timeline. Actual adverse-BBO
  liquidation fills, including the authoritative fee schedule, drive ledger
  state and `result.liquidated`; final flags are not inferred post hoc.
- Explicit settlement events carry expiry, last-trading, source, publication
  timestamp, and official-source provenance. Exact-once/order-after-expiry
  guards fail closed. The retained `settle_expired=True` compatibility alias is
  mapped to `legacy_last_tape_mark_research` and is visibly non-certified.
- Split orchestration, financial authority, and cold report materialization
  across `backends/native_option.py`, `options/authority.py`, and
  `options/reporting.py`; all modules pass the repository ownership/size gate.
- Added [Options P0 containment](../docs/options_p0_containment.md) and the
  explicit [V1.2 Rust authority handoff](../docs/options_v1_2_rust_handoff.md).

Verification:

```text
pytest -q tests/options/test_phase70_correctness_containment.py tests/options
  -> 114 passed, 5 skipped
pytest -q tests/options/test_phase70_correctness_containment.py tests/options \
  tests/native_event/contract/test_phase54a_productization.py::test_generated_product_and_lifecycle_artifacts_are_clean
  -> 115 passed, 5 skipped
full repository regression before the ownership split
  -> 1092 passed, 22 skipped; sole failure was the now-fixed module-size gate
sync_source_mirror.py --check
  -> PASS
generated native/product/public-API/V1.1 baseline checks
  -> PASS
```

Phase 70 exit: **PASS.** Options are Python-primary and correctness-contained;
unsupported lifecycle claims are rejected rather than approximated silently.
The V1.2 items above are explicit future products, not hidden V1.1 debt.

### Phase 71 / Guide Phase 15 - Reliability, Productization, Promotion, And A5 Closure

**Status: complete (2026-09-05).**

**Goal:** turn individually certified Rust routes into safe installed products,
operate them under bounded long-running workloads, then retire only the
production duplicates that have reached A5.

**Read first:** [V1.1 guide sections 38-40, 57, 59, 63-69, 79-80, and 90-92](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).

**Work packages:** `RP-123` through `RP-135`.

Implementation scope:

- Implement common runtime budgets, cancellation status, explicit prepared
  handle lifetime/close semantics, generation IDs, poison recovery,
  deterministic teardown, cache byte/entry budgets, audit chunking/truncation,
  and one parallelism coordinator for Python processes, Rust threads, and
  BLAS/OpenMP/Numba threads.
- Generate one machine-readable capability registry that drives Rust/Python
  routing, public docs, installed-wheel tests, and promotion reports. Add exact
  core/native protocol negotiation for capability hash, contract/result ABI,
  and build features.
- Expand clean installed-wheel certification across the approved platform wheel
  matrix. Every route is tested from wheels, never source-tree imports alone.
- Add workload-aware `backend="auto"` policy using exact capability, runtime
  class, native companion compatibility, parity status, and end-to-end
  performance/RSS evidence. `backend="rust"` remains fail-closed.
- Run sampled shadow-oracle releases with mismatch bundles and kill switch,
  stable soak, fallback-usage telemetry, and A5 review route by route.
- Remove the root source mirror only after source-layout/import/notebook/example
  evidence. Remove a Python/Numba production duplicate only after its own A5
  approval, documented migration manifest, rollback package version, and one
  stable release cycle. Preserve Python facade, strategy protocol, reporting,
  adapters, Nautilus validator, and independent oracle.

Required tests and evidence:

- runtime budget/cancel, use-after-close, cross-runtime mismatch, poisoned
  worker recreation, deterministic teardown, cache eviction, audit truncation,
  and nested-parallelism budget tests pass;
- generated capability registry agrees across Rust, Python, documentation,
  endpoint inventory, wheel test, and auto-router; CI rejects drift;
- installed-wheel source parity and exact protocol negotiation pass on every
  supported platform/Python pair;
- warm repeated service/WFO score runs demonstrate RSS plateau; full benchmark
  manifests report cold/warm peak/steady RSS, copy bytes, phase timings, and
  route-specific end-to-end performance;
- shadow mismatches generate evidence and kill-switch fallback. A5 removal is
  blocked by any unexplained mismatch, degraded fallback behavior, or missing
  migration manifest.

Exit gate:

```text
QuantBT can truthfully claim a correctness-certified Rust-primary simulation
core for the exact certified linear capabilities: static orders, promoted
targets, promoted portfolio policies, promoted same-account package policies,
promoted intrabar contracts, and prepared WFO evaluation. Reactive Python
strategies remain explicitly Rust-led hybrid. Unsupported advanced options and
cross-venue domains remain capability-gated.
```

No-debt rule and rollback:

- No generic endpoint is promoted merely because one subtype passed. Capability
registry, result authority metadata, and docs must agree on the boundary.
- Any route not at A5 retains its explicit Python/Numba route and package-pin
rollback. The independent Python oracle is permanent test infrastructure and
is never removed.

Implementation record:

- Added `RuntimeBudgetV1`, typed budget/cancellation errors, coordinated
  `ParallelismPlanV1`, bounded audit retention, runtime identity, telemetry,
  mismatch bundles, and a backend-instance kill switch. Limits are propagated
  through the stable event-driven facade, lifecycle engine, reactive/static
  routes, and prepared WFO runtime without changing existing defaults.
- Prepared WFO handles now have explicit session ownership, generation IDs,
  `reset()`, `cancel()`, recovery, `close()`, cross-runtime rejection, and
  use-after-close rejection. Rust returns typed canceled/budget-exceeded rows;
  warm score runs reuse immutable market and intent tapes without per-score
  market packing.
- `contracts/native_event_product_registry.json` now governs platform status,
  route-specific performance/RSS evidence, and automatic promotion. Generated
  Python, Rust, documentation, public API inventory, and corpus artifacts are
  drift-checked. `backend="auto"` requires exact capability plus parity,
  end-to-end speed, and RSS evidence; explicit Rust remains fail-closed.
- Added the Linux x86_64 published matrix and Linux aarch64, macOS arm64/x86_64,
  and Windows x86_64 CPython 3.11-3.13 certification-target workflow. Each CI
  target builds and installs its wheel outside the source tree before protocol
  and capability negotiation; certification-target is not mislabeled as a
  published wheel.
- Added the route-by-route A5 review and validator. Static tape and Native
  Strategy IR remain A4; prepared WFO and bounded portfolio/package/intrabar
  routes remain A3. No production duplicate was deleted because sampled
  fallback-rate evidence, a stable release cycle, or explicit deletion approval
  is still absent. This is the enforced A5 outcome and rollback policy, not an
  untracked implementation omission.
- The Phase 71 soak used 4,096 bars, 32 candidates, four folds, two Rust workers,
  and 30 repeated warm scores. Median warm score was `13.325 ms`, throughput was
  `39.35M candidate-fold-bars/s`, steady RSS was `162.98 MiB`, and RSS tail
  spread was `0.00 MiB`. Terminal fingerprints, reset generation, typed
  cancellation, post-cancel recovery, deterministic teardown, and zero warm
  market/intent copy all passed.

Verification:

```text
cargo fmt --all -- --check
  -> PASS
cargo clippy --workspace --all-targets -- -D warnings
  -> PASS
cargo test --workspace
  -> PASS (89 Rust unit tests; all doc tests pass)
pytest -q tests/test_phase71_runtime_productization.py \
  tests/test_phase48c_event_driven_facade.py
  -> 18 passed
focused native/runtime/capability regression
  -> 92 passed
pytest -q --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py
  -> 1102 passed, 22 skipped
generate_v1_1_baseline.py --check and generated product/public API checks
  -> PASS
sync_source_mirror.py --check, benchmark governance, A5 review, docs links,
and module architecture gates
  -> PASS
```

The two excluded real-data tests require the optional external `pyarrow` data
loader and are outside the deterministic repository regression gate. Phase 71
exit: **PASS** for the exact capability-scoped V1.1 product. Advanced options,
cross-venue execution, and future A5 deletion remain the explicit non-goals
below; no unsupported authority is advertised.

### V1.1 Explicit Non-Goals And Deferred Domains

The following are intentionally outside V1.1 and must stay fail-fast or
explicitly experimental. They are not hidden technical debt within a completed
V1.1 phase:

- automatic compilation/translation of arbitrary Python alpha logic into Rust;
- feature/indicator ownership inside QuantBT;
- universal event loop replacing all specialized kernels;
- venue-exact L2 reconstruction from OHLCV or synthetic-book claims;
- cross-exchange atomicity, multi-venue ledger, latency/prefunding authority;
- triangular execution without exact dependent-currency conservation;
- American exercise/assignment, Quanto, physical-settlement, multi-currency
  options ledger, and venue-exact options portfolio margin;
- a universal exchange portfolio-margin clone without a specified venue model;
- whole-core fixed-point rewrite before domain-specific precision requirements
  and benchmarks justify it;
- deleting Python oracle, historical timing IDs, or production fallback before
  the A5 and rollback gates.

### V1.1 Final Definition Of Done

V1.1 is complete only when the guide section 91 checklist is met:

- linear accounting is independently proven through FillReplay and canonical
  trace, then reused by promoted static event, target, portfolio, package, and
  intrabar kernels;
- WFO calendar/timing/causality/fold lifecycle are explicit and tested, while
  native WFO owns prepared repeated evaluation rather than Python per-trial
  simulation overhead;
- reactive optimized routes preserve callback/command/account traces and state
  that they are hybrid when Python strategy decisions remain;
- native metrics and result buffers are authoritative, lazy Python adaptation
  does not replay execution, and score/compact/audit agree financially;
- no auto-promoted Rust route is slower end-to-end than its intended Python
  route without an approved correctness-first exception recorded in capability
  metadata;
- installed wheels, protocol negotiation, capability registry, runtime/RSS
  soak, shadow-oracle release, migration manifests, docs, and rollback paths
  are complete for every A4/A5 claim.

## Phase 72-78 - Rust-Primary Public Workload And Performance Closure

**Status: Phase 72-77 and 77.1-77.3 have the scoped completion records below.
The additional PERF-01 through PERF-07 plan was authorized on 2026-09-06;
each new phase still awaits individual implementation approval. Phase 78
remains planned and additionally depends on their validated handoff.
Recording this plan does not authorize automatic promotion or release.**

**Canonical detailed guide:**
[QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).
This follow-up closes integration and performance gaps in the original V1.1
goal; it does not replace the guide with a narrower helper-only objective.
The guide owns domain semantics. This plan owns delivery order, concrete code
integration, test obligations, and measurable exit gates. Conflicts require an
explicit decision, not an agent assumption or a silent change of scope.

### Closure Objective And Approval Boundary

The deliverable is a stable public QuantBT workflow whose certified linear
simulation, repeated evaluation, standard metrics, and mutable execution state
are Rust-owned. A callable Rust helper is necessary but not sufficient: the
normal endpoint must reach it with the same declared accounting and selection
contract, and the installed distribution must execute that route.

Keep these three outcomes separate in every report:

1. Implementation exists and passes its own unit tests.
2. Public workload reaches the implementation and passes independent parity.
3. That exact workload/profile/platform passes performance, RSS, wheel, and
   promotion gates and is eligible for the declared A3/A4/A5 level.

The following existing evidence requires review, not deletion of prior work:

- Public WFO still constructs Python-controlled endpoint scorers; `%_equity`
  resolves to the legacy scoring backend. Native WFO companions do not by
  themselves accelerate the ordinary five-mode public optimizer.
- Target/portfolio WFO creates candidate/fold target, tradability, and stale
  slices with `to_vec()` and currently limits its helper to one worker.
- Numeric reactive output retains per-bar financial paths even without detailed
  diagnostics. Candidate batching still performs dense candidate bookkeeping.
- The Phase 71 throughput numerator counts the full tape for every fold, while
  its fixture executes disjoint test windows. The archived `13.325 ms` duration
  and the interpretation of `39.35M candidate-fold-bars/s` are separate issues.
  Recounting test-window volume gives approximately `8.20M candidate-bars/s`;
  this is arithmetic review, not a fresh measured throughput certification.
- Rust scalar score versus Numba path output is not a matched-profile speed
  gate. A native-only benchmark or protocol import check cannot certify public
  end-to-end superiority or installed endpoint behavior.

Do not rewrite historical raw results to make them pass. Preserve their hashes
and scope, add a superseding measurement contract, and regenerate current
candidate evidence. The prior per-phase completion records must not be used to
mark these gaps closed without the gates below.

### Mandatory Agent Execution Contract For Phase 72-78

Before each approved phase, read this whole follow-up contract, that phase's
linked guide sections, the corresponding implementation/tests, and
[guide 95: coding-agent rules](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#95-rules-for-coding-agents)
plus [guide 96: evidence template](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#96-required-pr-evidence-template).
These are required inputs for Terra or any other implementing agent, not
optional background reading.

- Inspect branch, worktree, native extension identity, and existing artifacts
  first. Preserve unrelated changes. Do not switch branches, merge, publish,
  retag, or delete environments as part of implementing a phase.
- Obtain phase-specific user approval before code changes. Start with the
  smallest independently testable domain slice, then expand within the approved
  phase. Update work-package status incrementally in this plan.
- Reuse `FullSession`, prepared market/calendar/instrument contracts, metrics,
  existing WFO selection functions, and output contracts. Do not create another
  account authority, separate optimizer, or feature engine to bypass them.
- Keep `walk_forward()`, `train_test_split()`, `event_driven()`, existing target,
  portfolio/package and intrabar endpoints stable. No required new notebook
  plumbing, `_rust` endpoint family, or flags that silently change old behavior.
- Preserve historical timing IDs, target semantics, one-way canonical fee,
  funding phase, constraints, and liquidation priority. `%_equity` compatibility
  is not established by mapping it to a similarly named target-weight policy.
- Implement new responsibilities in small cohesive modules. Python classes or
  Protocols own orchestration/preparation/adaptation; Rust structs/traits own
  execution state and typed buffers. Prefer composition over inheritance.
- Keep new Rust hot-loop dispatch monomorphic or use bounded enums where useful;
  OOP is an ownership tool, not a reason to add per-bar objects or virtual calls.
  Extend old files with narrow delegation; no wholesale file split/refactor.
- Keep `src/quantbt` canonical and use the existing source-mirror checker/sync
  rules while mirrors remain supported. Do not independently patch both trees
  or delete mirrors in an implementation/optimization patch.
- No replay to reconstruct a normal result; selected audit reruns are explicit,
  deterministic evaluations with the same prepared inputs and contracts.
- Record all failures, missing dependencies, skips, and commands accurately.
  A successful import, stale wheel, regenerated manifest, or selected subset
  of tests is not evidence that the complete release gate passed.

### Shared Scope, Ownership, And No-Debt Rules

Python retains research logic, indicator/feature generation, custom objectives,
Optuna orchestration, and presentation. Rust must retain simulation/accounting
authority, including between Python decisions. Arbitrary Python alpha logic
does not become native automatically. R1/R2/R3 Python strategies remain truthfully
hybrid; bounded native strategy/policy drivers can be whole-run native.

V1.1 non-goals above remain unchanged: full Rust options, arbitrary Python
compilation, venue-exact L2/portfolio margin, and unsupported cross-venue or
inverse/quanto semantics are not added by this performance plan.

**No-debt means no unresolved in-scope implementation or correctness work at a
phase exit.** It does not mean hiding a missing route behind `unsupported`,
calling a failed gate an optimization opportunity, or declaring an unmeasured
speed target passed. External observation time for A5 is a release dependency,
not a completed test. If a gate cannot pass, retain `in_progress`/`blocked`,
document the exact blocker and rollback, and request a decision. Only the user
may approve a changed requirement or a correctness-first performance exception.

Planned downstream work is named explicitly by owner phase; it is not required
to be implemented prematurely. Once its owner phase exits, it cannot be carried
forward as the same unfinished technical debt.

### Phase Map And Dependency Order

| Phase | Main outcome | Prerequisite | Original guide work packages |
|---|---|---|---|
| 72 | Trustworthy route inventory and matched measurement gates | User approval | RP-000-004, RP-126-130 |
| 73 | Shared no-copy prepared native evaluation substrate | 72 contract lock | RP-065-072, RP-084, RP-094, RP-106 |
| 74 | Five-mode public WFO integration with unchanged mathematics | 73 fixed-matrix parity | RP-057-064, RP-073-074, RP-084, RP-094 |
| 75 | Reactive scalar retention and persistent Rust hot state | 72 baseline; reuse 73 ownership | RP-041-056 |
| 76 | Reactive WFO, persistent processes, sparse candidate batching | 73-75 | RP-075-077, RP-125 |
| 77 | Profile-driven kernel and public adapter performance closure | 72-76 workload evidence | RP-028-033, RP-078-114 |
| 77.1 | Public workload baseline and domain contract lock | 77 plus individual approval | Guide 24-27, 31-32, 60-63 |
| 77.2 | Public WFO Rust execution and prepared ownership closure | 77.1 exit plus individual approval | RP-057-074, RP-078-084, RP-094, RP-106 |
| 77.3 | Reactive hot loop and specialized kernel closure | 77.2 exit plus individual approval | RP-041-056, RP-085-114, RP-123-126 |
| PERF-01 | Source/profiling and computation/output contract | 77.1-77.3 records; current baseline inspection | APC-1.0 section 3; AP-01/AP-11 |
| PERF-02 | Safe session reset and derived account state | PERF-01 gate | APC-1.0 section 4; AP-02/AP-04 |
| PERF-03 | Reactive context, command staging and boundary cost | PERF-01/02 gates | APC-1.0 section 5; AP-03 |
| PERF-04 | Native matching/layout and contract specialization | PERF-01/02 gates | APC-1.0 section 6; AP-05/AP-06 |
| PERF-05 | Five-mode WFO reuse, reducers and locality | PERF-03/04 and PERF-01 audit schema | APC-1.0 section 7; AP-07/AP-08/AP-09 |
| PERF-06 | Full research audit, columnar retention and compatibility | PERF-01 schema and PERF-05 identities | APC-1.0 section 8; AP-10 |
| PERF-07 | Combined qualification, build tuning and closure manifest | PERF-01 through PERF-06 gates | APC-1.0 section 9; AP-12 and all AP integration |
| 78 | Public promotion, installed-wheel certification, release handoff | Original exit artifacts plus current READY_FOR_PHASE78 manifest | RP-123-135 and APC-1.0 handoff |

Execution order is 72 -> 73 -> 74 -> 75 -> 76 -> 77 -> 77.1 -> 77.2 -> 77.3
-> PERF-01 -> PERF-02 -> PERF-03 -> PERF-04 -> PERF-05 -> PERF-06 -> PERF-07
-> 78, one user approval at a time. The detailed
[additional performance plan](#additional-performance-closure---perf-01-to-perf-07)
is inserted directly before Phase 78. Independent profiling may occur inside an
approved phase; that does not authorize starting a later implementation phase.

### Phase 72 - Measurement And Capability Gate Correction

**Status: complete; measurement and capability gate corrected.**

**Goal:** establish an honest, reproducible denominator for performance and a
public-route coverage matrix before further optimization or promotion.

**Read first:**
- [39.1-39.6: timing, counters, RSS and performance governance](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#391-common-phase-timings).
- [61.1-61.4: reactive comparison protocol](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#611-workloads).
- [62.1-62.4: WFO workload and comparison rules](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#621-dimensions).
- [63.1-63.3: boundary and route budgets](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#631-boundary-budgets).
- [15: endpoint capability target matrix](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#15-endpoint-capability-target-matrix).

**Implementation sequence:**

1. P72-01: inventory actual public endpoint -> planner/scorer -> native entry ->
   result adapter paths. Separate helper availability, runtime authority,
   profile, timing, account policy, optimizer mode/schedule, and platform.
   Every promised linear subtype gets an owner phase and an executable fixture;
   no generic endpoint is marked native solely because one subtype is native.
2. P72-02: version the work counters. Report supplied bars, warmup visits,
   simulation bar visits, symbol-bar visits, candidates/folds/scenarios actually
   evaluated, early termination, and skipped/pruned tasks separately. Derive
   execution throughput from counters, not full tape length times fold count.
   A logical input-volume metric may remain only under its own explicit name.
3. P72-03: capture source SHA plus dirty-tree/content fingerprint, wheel hashes,
   protocol/API/ABI IDs, CPU, worker/BLAS counts, versions, output retention,
   timing/fee/account/metric contracts, data/intent hashes, and warmup procedure.
   Historical wheel baselines stay historical; build/current-candidate proof
   must use the candidate source rather than overwrite the baseline snapshot.
4. P72-04: benchmark score/score, compact/compact, and audit/audit where supported.
   Match metric computation and work performed, not only output labels. Include
   preparation, feature generation, ingest, execution, metrics, optimizer and
   selected report in end-to-end timing; avoid summing overlapping timers.
5. P72-05: enforce registry evidence: a pass requires the exact workload pair,
   fresh identity, measured limits and parity. Reject native-only, missing,
   stale or incompatible comparator evidence for speed promotion. Keep any
   withdrawn promotion fail-safe and visible, not a blanket default change.
6. P72-06: supersede misleading benchmark summaries, including Phase 71's volume
   interpretation. Preserve original measured duration/raw evidence. Update
   performance docs with explicit units and scope; do not advertise new speed.

**Code anchors and proposed deliverables:**
- Extend `benchmarks/native_event/benchmark_phase65_native_wfo.py`,
  `benchmark_phase66_rust_target_vectorized.py`,
  `benchmark_phase69_rust_intrabar.py`, and `benchmark_phase71_runtime_soak.py`.
- Reuse `tools/check_benchmark_governance.py` and the product registry validator;
  introduce small shared workload/counter helpers rather than four new harnesses.
- Add `tests/test_phase72_measurement_contract.py` and a versioned measurement
  manifest with machine-readable acceptance budgets locked before tuning.

**Tests and exit gate:**
- Hand-count unequal/overlapping folds, scenarios, warmup, zero tasks, partial
  final folds and liquidation-terminated runs; verify numerator/units exactly.
- Reject mismatched profiles, timing, annualization, data hashes and wheel IDs;
  test that a manually asserted `pass=true` cannot override failing evidence.
- Record fresh-process cold peak RSS and warmed repeated-run RSS separately;
  alternate comparator order, use repeated paired timing, and report median,
  p95, sample count and noise policy. Do not mix both backends in one RSS claim.
- Required benchmark axes follow guide 62.1: 1k/10k/100k bars, 1/8/20 symbols,
  16/64/256/1k candidates, 3/6/12 folds, and low/high churn. Use a documented
  representative covering matrix, not an unbounded Cartesian product. Resource
  limits and any excluded cells must be explicit before measurements.
- Exit requires a verified route matrix and reliable harness, not speedups from
  code that has not yet been optimized. Unresolved promotion-evidence errors
  block exit. Implementation speed gaps are owned by 73-77, not concealed.

**Rollback and evidence:** benchmark/evidence changes must not alter trading
semantics. Archive before/after measurement interpretation, exact commands and
results in the Phase 72 record; leave runtime promotion unchanged unless fixing
an evidenced invalid promotion with a narrow tested guard.

**Implementation record (2026-09-05):**

1. Added the versioned machine-readable measurement contract at
   `benchmarks/native_event/manifests/phase72_measurement_contract_v1.json`.
   It inventories every public endpoint route, its actual planner/native entry/
   result adapter, profile pair, authority status, executable fixture, and owner
   phase. Generic callback WFO is explicitly Python orchestration rather than
   being inferred native from its prepared companion.
2. Added shared `tools/measurement_contract.py` work counters. WFO throughput
   now uses actual candidate-test-bar visits; supplied tape volume remains a
   separately named logical-input metric. The helper covers unequal and partial
   test windows, zero-task batches, scenarios, warmup, skipped tasks, and
   early termination, which must report an observed counter.
3. Benchmark identity now binds source/dirty state, source tree, registries,
   core/native distribution plus compiled-extension hashes, machine/thread
   context, typed market/intent hashes, and declared warmup procedure. Historical
   manifests remain immutable scope evidence rather than being rewritten as a
   current candidate.
4. Corrected a runtime-admission bug in `NativeWfoRuntimeV2`: a per-fold intent
   cube now budgets `candidates * folds`, not an accidental fold-squared count.
   This only corrects resource admission; it does not change fills, accounting,
   or selector behavior.
5. The registry/governance gate now rejects a manually asserted pass unless it
   has a fresh identity, exact route/profile, parity, end-to-end comparison, and
   RSS evidence. Existing static-command and StrategyIR evidence is held as
   historical, so `backend="auto"` safely resolves Python while explicit Rust
   remains available subject to its capability handshake.
6. Superseded the misleading historical interpretations: Phase 65's preserved
   raw duration is approximately `0.94M` actual candidate-test-bar visits/s,
   and Phase 71's is approximately `8.20M`; the former `4.51M` and `39.35M`
   figures are retained only as logical full-tape input-volume/s. No new
   automatic-promotion speed claim is made.

**Exit evidence (source candidate, no historical artifact overwritten):**

- `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_phase71_runtime_productization.py tests/test_phase72_measurement_contract.py`
  and the focused product-routing suites passed (`41 passed`), including exact
  work-counter/budget regression, comparator identity, manual-pass rejection,
  and auto-hold versus explicit-Rust coverage.
- Product/capability focused suites passed:
  `test_phase54a_productization.py` (`10 passed`) and
  `test_phase54b1_native_promotion.py` (`6 passed`); the public static
  auto-hold/explicit-Rust parity route also passed.
- `tools/generate_product_contracts.py --check`,
  `tools/check_benchmark_governance.py`, and
  `tools/sync_source_mirror.py --src-to-root` passed.
- Fresh 4,096-bar controls passed exact accounting parity. Phase 65 ran 64
  candidates across four OOS windows (`218,496` actual visits); Phase 71 ran
  32 candidates across the same windows (`109,248` actual visits), with
  deterministic reset/recovery/cancellation evidence and an RSS plateau.

**Phase boundary:** Phase 72 closes measurement correctness and the unsafe
promotion claim. It intentionally does not claim broad fresh performance
coverage or generic WFO Rust authority: reusable prepared ownership is Phase
73, causal WFO execution is Phase 74, reactive batching is Phases 75-76, and
the full current-candidate route matrix/promotion decision is Phase 77. These
are owned next steps, not hidden Phase 72 execution debt.

### Phase 73 - Shared Prepared Native Evaluation Runtime

**Status: complete (2026-09-05).**

**Goal:** reuse immutable market and typed intent ownership across all claimed
linear evaluation workloads, with one persistent scheduling substrate and no
market or O(T) intent copy for each candidate/fold/scenario execution.

**Read first:**
- [22.6: prepared handle lifetime](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#226-prepared-handle).
- [30.2-30.5: strategy lifecycle, cache and RNG](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#302-contract).
- [32.3-32.8: plan, typed tapes, workers and no-copy](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#323-nativewfoplanv2).
- [32.9-32.12: scalar rows, reducers and audit rerun](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#329-native-candidate-metric-row).
- [32.18: WFO performance gates](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#3218-wfo-performance-gates).
- [38.1-38.7: budgets, cancellation and lifetime](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#381-runtime-budget).

**Implementation sequence:**

1. P73-01: map existing `NativeWfoRuntimeV2`, `NativeTargetWfoRuntimeV2`,
   `FullSession`, target/package/intrabar prepared requests and scalar results.
   Write the adapter contract before code; keep specialized kernels specialized.
2. P73-02: provide typed evaluation adapters for signal/target units/notional/
   weight/equity fraction, static command tapes, StrategyIR, shared portfolio,
   bounded same-account packages and intrabar. Reuse versioned request types;
   introduce a union/adapter only where it removes duplicate orchestration.
3. P73-03: replace target/tradable/stale per-task vectors with immutable owned
   storage plus validated ranges/offsets. Hold owners safely through worker
   lifetime; a one-time controlled ingestion copy is allowed. Parameter-dependent
   intent generation is real work and must not be mislabeled a cache hit.
4. P73-04: reuse one persistent worker scheduler with isolated account/order/
   metric scratch. Add cost-aware dynamic dispatch for heterogeneous churn;
   return rows sorted by stable IDs, not completion order. Enable target and
   portfolio workers beyond one only after worker-count parity passes.
5. P73-05: validate immutable market/instrument data once, cache execution plans,
   and validate only changing intent/bindings per batch. Cache keys cover market
   values/timestamps/calendar, funding events/rates, constraints, contracts,
   metric policy and strategy preparation fingerprint; changing any relevant
   field invalidates safely. Never cache parameter-dependent features as static.
6. P73-06: carry candidate/fold/scenario identity, cutoff, evaluation range,
   account policy and `MetricContractV2` into every request. Do not silently use
   default Sharpe policy, scenario zero, or only test ranges for IS scoring.
7. P73-07: reuse online reducers and compact typed rows. Bound retained metrics,
   error side tables and intent batches; do not allocate a full
   folds x candidates x full_tape cube when bounded batches/views suffice.
   Retain return paths only when a declared objective actually needs them.
8. P73-08: implement enforceable cancellation, memory/task budgets, reset/close,
   cross-runtime and generation checks, worker recovery, deterministic teardown,
   and identical-input top-K audit reruns. No budget field may be metadata-only.

**Code anchors and proposed deliverables:**
- `src/quantbt/backends/native_wfo*.py`,
  `src/quantbt/preparation/native_*_requests.py`,
  `rust/crates/quantbt-batch/src/lib.rs` and `src/target_wfo.rs`.
- Use new small internal evaluation/ownership/scheduling modules under existing
  packages/crates; do not move all existing runtime code or fork `FullSession`.
- Add `tests/test_phase73_prepared_evaluation.py`, Rust ownership/scheduler tests,
  and a workload-adapter support matrix linked to the Phase 72 inventory.

**Tests and exit gate:**
- Differential fixed candidate x fold x scenario corpus for every admitted
  adapter; compare acceptance, fills, costs, funding, margin, liquidation,
  metrics and fingerprints, not only final equity.
- Prepared/non-prepared, single/batch, 1/N-worker, reset/repeat and selected
  score/audit parity. Test empty tape, invalid constraints, asynchronous/stale
  symbols, failure isolation, use-after-close and cancellation during work.
- Mutate source arrays after ingestion, funding, constraints and metric policy;
  verify immutable ownership and invalidation, without stale-cache reuse.
- Counter gate: one pool creation per runtime, none per score call; zero market
  copies and zero O(T) prepared intent copy per execution; no pandas in native
  score; one main native score entry per prepared batch.
- RSS scales with shared tapes, bounded workers/batches and retained metric
  rows, not all trial paths. Run enough repeats to distinguish warmup growth
  from leaks; plateau limits come from Phase 72, not post-hoc adjustments.
- No missing adapter promised in this phase may be reclassified as unsupported
  simply to pass. Public optimizer integration is specifically owned by 74/76.

**Rollback and evidence:** keep existing adapters/contract IDs callable through
thin compatibility delegation. No auto-promotion or Python/Numba deletion here.
Record copy/allocation counters and parity corpus for each workload separately.

**Implemented closure:**

- Added `NativePreparedEvaluationRuntimeV1` and a Rust-owned
  `NativePreparedEvaluationRuntimeCore`. A complete prepared
  candidate/fold/scenario batch crosses Python/Rust once, uses a persistent
  cost-descending dynamic worker queue, and returns sorted compact scalar SoA
  rows only.
- Admitted every planned typed family without changing its specialized executor:
  static command tape, StrategyIR, direct target units/notional/weight/equity
  fraction, shared portfolio target, bounded atomic/V2 package, and
  single-symbol intrabar. Request binding validates the exact workload/contract
  pair rather than proxying an unsupported request.
- Converted the static, target, shared-portfolio, and intrabar binding payloads
  to `Arc` ownership. Market/template/request payloads are immutable and shared;
  each execution has zero market copies and zero O(T) intent copies. Controlled
  Python normalization and Rust-owned ingress are measured separately.
- Kept candidate/fold/scenario evaluations fresh-account only. Partial ranges,
  continuity policy, incompatible metric annualization, stale cache generation,
  cross-runtime bindings, reset generation, use-after-close, and resource
  budget violations fail before execution. Local causal folds use
  `window_template()` rather than slicing a bound full request.
- Added MetricContractV2 provenance and validation to every successful scalar
  row. The shared runtime certifies crypto-daily annualization `365` only and
  rejects a request for `252` rather than silently relabelling metrics.
- Added bounded error retention, candidate-boundary cancellation, deterministic
  reset/close, and panic containment. A worker panic produces a failed row and
  forces whole-pool replacement before any later batch; recovery failure closes
  the runtime fail-closed.
- Closed a multi-worker ownership race in the prepared scheduler: a worker now
  drops its temporary request `Arc` before delivering the completed row. This
  makes post-batch handle ownership deterministic rather than exposing a brief
  scheduling-dependent extra owner to Python diagnostics.
- Documented the internal surface in
  [`docs/native_prepared_evaluation.md`](../docs/native_prepared_evaluation.md)
  and added a narrow reproducible benchmark. This is intentionally not a public
  WFO routing or generic callback performance claim.

**Exit evidence:**

- `tests/test_phase73_prepared_evaluation.py` covers all 11 typed request
  instances, direct-specialized-result parity, score/audit parity,
  deterministic identity ordering, one-boundary/no-copy counters, cache and
  runtime generation invalidation, cancellation/recovery, budgets, zero-copy
  local windows, source-array mutation after ingress, and volume/funding
  signature invalidation. A repeated multi-worker batch also locks the
  post-result request-owner release invariant (`5 passed`).
- The focused dependent corpus passed (`88 passed`): Phase 54 productization
  and native promotion plus Phase 66 target, Phase 67 shared portfolio, Phase
  68 package, Phase 69 intrabar, and the Phase 73 conformance suite.
- `cargo fmt -p quantbt-native --check`, `cargo test -p quantbt-native --lib`
  (including poison-recovery), and `cargo test -p quantbt-execution --lib`
  passed. `tools/sync_source_mirror.py --check`,
  `tools/check_benchmark_governance.py`, and `git diff --check` passed.
- The recorded 4,096-bar x 64-candidate x 2-worker warm target batch has a
  median `16.956 ms` (`15.46M` candidate-bar visits/s), one worker pool, one
  native boundary per score batch, zero warm market/intent copies, and a
  `0.0 MiB` RSS tail spread over 30 repeats. It explicitly excludes Python
  strategy generation, Optuna, reporting, and public WFO selection.

**Phase boundary:** no unresolved Phase 73 correctness, lifecycle, ownership,
or measurement debt remains. Normal `QuantBTEndpoint.walk_forward()` and
`train_test_split()` still use their existing scorer path by design; wiring the
prepared evaluator into all five public optimization modes, while preserving
selection/account-reconstruction semantics, is the owned Phase 74 scope.

### Phase 74 - Public WFO Integration Across Five Modes

**Status: complete (2026-09-05).**

**Goal:** make normal `QuantBTEndpoint.walk_forward()` and its shared train/test
scoring path benefit from native prepared evaluation without changing the five
optimization methods, notebook calling style, or financial reconstruction.

**Read first:**
- [31.2-31.12: folds, timing, account policy and causality](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#312-fold-plan).
- [32.2: W0/W1/W2/W3 adapters](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#322-strategy-adapter-levels).
- [32.10-32.13: reducers, rerun and optimizer schedules](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#3210-fold-reducers).
- [32.17: parity program](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#3217-wfo-parity-program).
- [64.1-64.2: resolution and historical reproduction](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#641-config-resolution).
- [Current WFO schedule semantics](../docs/walkforward_causal.md) and
  [current selection methodology](../docs/walkforward_methodology_vi.md).

**Implementation sequence:**

1. P74-01: freeze a mode x optimization_schedule x target x account/timing
   compatibility table from current code/tests. Distinguish optimization mode,
   chronological study schedule, and sequential/batch ask-tell schedule.
   Do not add new mode/schedule combinations as a performance shortcut.
2. P74-02: inject a prepared native evaluator below the existing WFO scorer
   interface. Keep `WalkForwardEngine` selection/orchestration reusable; retire
   duplicate companion objective logic through delegation, not a second public
   optimization engine. Resolve compatibility before native execution.
3. P74-03: connect W0 existing pandas callbacks and W1 prepared/W2 batched intent
   generation. Existing users keep their wrapper and parameter ranges; optional
   protocol adoption can reduce Python work without becoming a prerequisite.
   Compile intent using its actual observation/effective timing and shifted
   state; never add a generic one-bar lag or infer semantics from array length.
4. P74-04: preserve each mode's objective and selector stages exactly:

   | Mode | Required preservation |
   |---|---|
   | `mode_1_decay` | Existing IS scoring, candidate admission and decay formula; same-stage OOS use and trade penalties; nested versus same-fold selection remains explicit. |
   | `mode_2_sbb` | Existing bootstrap/resampling/path and scenario semantics, seeds and penalties; required paths are bounded and explicit, not replaced by a scalar Sharpe shortcut. |
   | `mode_3_flat_minima` | Existing candidate ranking, neighborhood/cluster construction, selector, ties and centroid reevaluation. |
   | `mode_4_is_only_robust` | Existing IS temporal/plateau/bootstrap/complexity inputs and selectors; no OOS input to parameter selection for the strict causal schedule. |
   | `mode_5_full_robust` | Full declared sample calibration and its supported selectors; do not invent chronological OOS or label the result holdout validation. |

5. P74-05: keep `global` retrospective semantics; `per_fold_decay` Mode 1 uses
   same-fold OOS for selection and remains selection-adjusted. Mode 4
   `per_fold_causal` selects only from current IS; Mode 1 `per_fold_causal` uses
   its declared nested inner folds. Do not extend IS-isolation claims to
   retrospective global studies whose later training ranges include earlier OOS.
   Modes 2/3/5 retain their existing global lifecycle unless a separate domain
   change is approved; native routing must not invent per-fold support for them.
6. P74-06: preserve parameter sampling, fixed-parameter precedence, duplicate
   handling, pruning, exceptions, early stopping, top fractions, tie-breaking
   and complete metadata. Native rows feed current objective code; standard
   numeric reducers may run in Rust without changing their mathematical policy.
7. P74-07: for `certified_sequential_v1`, ask/tell one candidate in the same order.
   `throughput_batch_v1` is explicit opt-in with its own sampling contract and
   metadata; do not claim adaptive TPE sequence parity across batch sizes.
8. P74-08: separate fresh-account candidate diagnostics from final chronological
   account reconstruction. Route selected intent into the authoritative final
   engine once under the declared boundary policy; never concatenate independent
   fold equities or silently reset capital/funding/positions at every fold.
9. P74-09: specify boundary transitions for unchanged position, reversal,
   changed target size, open stop/bracket orders, pending commands and final
   flatten. `CarryPosition` carries actual state, not a guessed target;
   `CloseAtBoundary` creates a timed costed event; `ReplayPriorState` uses causal
   input; `ResetFlat` reports independent segments without claiming continuity.
   Preserve existing fail-fast combinations until their actual contract is
   implemented and certified; the supported-route matrix cannot be reduced.
10. P74-10: preserve `show_metrics()`, `quick_plot()`, `full_report()`, fold/trial/
    candidate tables and selected-parameter provenance. Lazy report adaptation
    must use the final account and correct evaluation scope, not trial histories.

**Code anchors and proposed deliverables:**
- `_run_walk_forward`, `_WalkForwardEndpointScorer` and compatibility resolution
  in `src/quantbt/endpoint.py`; selection/lifecycle in `src/quantbt/walkforward.py`.
- Reuse `src/quantbt/optimization/` contracts and Phase 49/50/64 fixtures. Put new
  evaluator adapters in focused internal modules, not another large endpoint file.
- Add `tests/test_phase74_public_wfo_native.py`, mode/schedule conformance fixtures,
  stable examples and updates to endpoint/WFO methodology documentation.

**Tests and exit gate:**
- All five modes and every already-supported schedule pair: fixed candidate
  matrix metric/objective/ranking parity; deterministic sequential study parity
  for sampled params, trial states, pruning, winner and stitched output.
- Test near ties, float tolerances, zero trades, penalties, rejected/liquidated
  candidates, infinite/undefined metrics and centroid rerun. Never round scores
  to force the same winner or treat a failing candidate as zero profit.
- Mutate future bars, funding, labels and one symbol's calendar: strict causal
  selection cannot change before cutoff. Selection-adjusted/retrospective modes
  must retain their declared behavior rather than pass a false isolation test.
- Boundary fixtures include same-side carry, reversal, gap, fee/funding event,
  slippage, leverage/margin, overlapping folds, warmup and incomplete final fold.
  Reconcile positions/orders/cash/equity at every join against a chronological
  reference; test execution-contract propagation and no extra signal shifting.
- Assert actual native entry/authority from the normal endpoint, not only helper
  outputs. Run WFO plus `train_test_split` regression for shared scorer changes;
  single-symbol, portfolio and bounded package routes promised by the matrix
  must use their own certified semantics, not a forced signal-target proxy.
- Publish full-study timing and memory breakdown, including Python strategy
  time. Exit closes public non-reactive integration; reactive W3 is owned by 76
  and final performance/promotion decisions by 77/78.

**Rollback and evidence:** retain existing explicit backend/contract selection
and package-pin reproduction. Do not change optimizer defaults or widen auto
eligibility in this integration patch. Archive selected params and join traces
for both native and reference runs.

**Implemented closure:**

- Added `NativePreparedPublicWfoScorerV1` below the existing endpoint scorer.
  It prepares one immutable single-symbol market/template per WFO run, builds
  zero-copy local fold/shard views, and sends already-generated scalar targets
  through one Phase 73 Rust boundary per scoring batch. Candidate/fold/shard
  accounts remain fresh; selected output is still stitched once into the
  existing chronological final endpoint account.
- Added explicit `optimization_config` controls:
  `native_prepared_wfo="off|auto|require"`,
  `native_prepared_wfo_workers`, `prepared_wfo_strategy="off|auto|require"`,
  `prepared_wfo_strategy_adapter="auto|w1|w2"`, and optional immutable
  `prepared_wfo_strategy_static_config`. Defaults remain off, so no existing
  notebook, optimizer sequence, or auto-backend behavior changes.
- Certified W0 legacy callbacks plus optional W1 prepared and W2 typed signal
  generation. W1/W2 are restricted to finite full-tape scalar signals; the
  public facade preserves one-candidate certified sequential ask/evaluate/tell.
  For per-fold schedules, a strategy must explicitly declare
  `causal_cache_contract="causal_parameter_independent_v1"`; malformed opt-in
  adapters fail rather than silently reverting after generation begins.
- Routed compatible `mode_1_decay`, `mode_3_flat_minima`,
  `mode_4_is_only_robust`, and `mode_5_full_robust` score tasks without
  rewriting objectives, penalties, reducers, selectors, ties, sampling,
  pruning, or final-account reconstruction. `mode_2_sbb` deliberately retains
  its bounded proxy path: `auto` records `proxy_preserved` and `require` fails
  closed rather than substituting a scalar Sharpe score.
- Preserved schedule semantics: global remains retrospective; Mode 1
  `per_fold_decay` stays selection-adjusted; Mode 1 nested
  `per_fold_causal` and Mode 4 `per_fold_causal` keep their existing strict
  IS rules. No signal is generically shifted and no independent fold equity is
  concatenated. Metadata records native resolution, signatures, counters,
  cache/runtime lifecycle, W1/W2 provenance, and final account policy.
- Added `docs/native_prepared_wfo_public.md` and linked endpoint, causal WFO,
  methodology, capability, backend-selection, performance, and README guides.
  The benchmark artifact now separates prepare/fold plan, Python strategy
  generation, scorer, Rust prepared execution, residual facade work, peak RSS,
  and steady RSS instead of hiding the latter behind a headline speedup.
- Corrected the release manifest to reflect the Phase 72 safety policy: with
  promotion rules disabled, `backend="auto"` remains Python even when an exact
  native wheel pair is present; static/StrategyIR remain explicit certified
  routes. The release-surface regression now derives this state from the
  registry rather than preserving the old contradictory expectation.

**Exit evidence:**

- `tests/test_phase74_public_wfo_native.py` passed (`18 passed`) and covers
  endpoint authority, exact W0/W1/W2 selection/final-account parity, all five
  mode outcomes (including explicit Mode 2 preservation), supported causal
  schedules, funding/fee/slippage transitions, target-unit/notional routes,
  future market/funding mutation, strict cache declarations, and auto/require
  fallback behavior.
- The combined regression corpus passed (`220 passed`): Phase 73 prepared
  ownership, Phase 49/50/64/65 WFO schedules and lifecycle, Phase 66-69
  specialized Rust routes, legacy WFO plotting/report surfaces, and Phase 54
  product/release contract gates. The only output was two known
  `matplotlib.tight_layout` warnings from quick-plot tests.
- Rust gates passed: `cargo fmt -p quantbt-engine -p quantbt-execution
  -p quantbt-native --check`; `cargo test -p quantbt-engine --lib` (`41`),
  `cargo test -p quantbt-execution --lib` (`14`), and
  `cargo test -p quantbt-native --lib` (`3`). Source mirror, documentation
  links, and benchmark governance checks passed.
- Final post-warm W0 Mode 1 global facade evidence on `2,048` bars,
  `16` sequential trials, one symbol, one Rust worker, and five repeats:
  historical endpoint `1.053043 s` versus prepared-native `0.431730 s`
  (`2.44x`); candidate scorer `0.800033 s` versus `0.166156 s` (`4.81x`);
  `54,908` actual candidate-bar visits (`127,181/s`); peak/steady process RSS
  `221.984 MiB`, tail spread `0.008 MiB`; exact winner, trial metrics,
  stitched positions/equity, fees, funding, and final account parity passed.
  See `benchmarks/native_event/results/phase74_public_wfo.{json,md}`.

**Phase boundary:** no unresolved Phase 74 correctness, lifecycle, causality,
selection, accounting, ownership, or measurement debt remains inside its
declared public non-reactive scalar matrix. Reactive W3/candidate batching is
owned by Phase 76; portfolio/package and wider performance/promotion decisions
retain their separately declared Phase 77/78 contracts and are not silently
treated as supported by this route.

### Phase 75 - Reactive Scalar Retention And Rust Hot State

**Status: complete (2026-09-05).**

**Goal:** remove unnecessary reactive path retention and engine-side hot-loop
objects while preserving every decision, command, execution and account event.

**Read first:**
- [27.5-27.7: retention and Python result compatibility](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#275-retention-profiles).
- [29.1-29.7: runtime levels, numeric buffers and GIL](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#291-objective).
- [29.8-29.12: sparse wake and block/batch intents](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#298-dynamic-sparse-wake-protocol).
- [29.13-29.17: errors, ownership and four-way parity](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#2913-error-model).
- [61.1-61.4: reactive benchmarks](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#611-workloads).

**Implementation sequence:**

1. P75-01: split internal online accounting/metric state from optional retained
   paths. `record_step` must not append full paths for scalar score. Final margin,
   equity, positions and flags must come from state, not `.last()` on a removed
   path. Compact/audit retain exactly their documented outputs.
2. P75-02: bind callbacks once; reuse context projections, command writers, wake
   plans and symbol scratch. Replace per-observation positions clones and wake
   payload dict/list conversions with lifetime-safe typed buffers where the
   optimized protocol permits; keep legacy callbacks via a cold adapter.
3. P75-03: reduce FullSession step projection/allocation only for fields not
   required by execution, metric reducers or declared callback requirements.
   Preserve callbacks' delta event views even when final audit storage is off.
   Truncation/backpressure cannot silently discard events the strategy needs.
4. P75-04: formalize buffer capacity, generation and borrow lifetime. Reject
   stale retained views, command overflow, invalid symbol/side and unsupported
   wake flags with typed errors and bounded diagnostic detail. Keep callback
   exceptions/traceback available without allocating error strings every bar.
5. P75-05: retain Rust's outer clock/account/lifecycle between Python decisions;
   optimize both held-GIL and release-between-callback policies with actual
   callback/GIL counters. Do not claim fully native from one public entry alone.
6. P75-06: complete bounded execution-policy drivers for already-supported
   grid/DCA behavior: typed ladder/block intents, fill/reject reconciliation,
   sibling cancellation and deterministic invalidation live beside the existing
   strategy IR/runtime. Declare exact policy scope before coding. A native driver
   can avoid Python decisions for that policy; alpha features/regime/parameter
   research remain external. Arbitrary Python translation/R4 auto-promotion is
   not an implicit requirement or shortcut.
7. P75-07: expose reuse through existing event-driven protocol/profile resolution.
   Do not make users manually build execution tapes just to keep using their
   old strategy. Add an optional advanced driver example only when that contract
   is genuinely different and requires explicit user intent.

**Code anchors and proposed deliverables:**
- `rust/native_event/src/reactive_numeric.rs`, existing FullSession output
  adapters, `src/quantbt/strategies/reactive_protocols.py`, and the event facade.
- New focused retention, context, wake-plan and driver modules with small
  delegation changes to the existing large file; no unrelated decomposition.
- Add `tests/test_phase75_reactive_retention.py`, Rust buffer/metric tests,
  four-way corpus extensions and profile/driver examples.

**Tests and exit gate:**
- Four-way parity: independent Python execution, legacy bridge, numeric
  co-runtime, and captured static command replay. Compare callback inputs,
  commands, execution/account trace and terminal strategy-state fingerprint.
- Score/compact/audit agree on accounting and metrics, including reversal,
  partial fill, rejected replacement, OCO/bracket, funding, liquidation,
  finalization, empty tape and no-fill strategy. Trace collection for the oracle
  run is separate from retention during the measured scalar run.
- Every-bar versus sparse/block driver parity includes simultaneous wake
  reasons, intra-block fills/rejects, invalidation and gap prices. Sparse
  optimization cannot skip required mark, funding, expiry or margin processing.
- Scalar output memory has no O(bars x symbols) retained financial paths unless
  a declared metric/strategy history requirement demands them. Such retention
  must be bounded/identified, not silently imposed on all users.
- Engine-provided context/command object allocation after warmup is zero per
  callback in the numeric path. Measure, do not assume, scratch/copy reduction.
  Arbitrary allocations inside user Python alpha remain separately attributed.
- Profile-matched R1 no-regression is required for future auto eligibility;
  sparse speed is reported against actual wake reduction. No unresolved
  retention/lifetime/callback parity issue may leave this phase as debt.

**Rollback and evidence:** legacy object callback remains available. Preserve
requested/resolved runtime class and GIL policy; explicit unsupported native
drivers fail before simulation. Automatic promotion waits for 78.

**Completion evidence:**

- Implemented a Rust-owned `ReactiveOnlineScoreV1` reducer and retention
  profile for the existing R1/R2/R3 `ReactiveNumericRunnerCore`. Explicit
  prepared scalar scoring keeps O(symbols) account/metric state only; it does
  not retain equity/account paths, command rows, callback trace, or terminal
  active orders. Public minimal/standard/audit profiles retain their existing
  cold-path result contract unchanged.
- The reducer receives the full tape boundaries and Python-equivalent bar
  annualization. Final margin, equity, positions, counters, funding and
  liquidation state are read from the live account state, not a removed last
  row. `RustReactiveNumericCoRuntime.run_scalar(...)` rejects a non-scalar
  runner and verifies the Rust payload contains no retained public artifact.
- Added one explicit prepared `NativeEventScalarScoreResult` route through the
  existing event backend. It uses the same single Rust session as public R1/R2/R3
  execution, creates no pandas result/audit adapter, preserves the declared
  strategy callback boundary and GIL policy, and fails before simulation when a
  score request asks for paths or ledgers. Existing public endpoints and
  `backend="auto"` behavior are unchanged.
- Focused reactive regression passed: `44 passed` across Phase 45D, 62, 63,
  75 and native reactive lifecycle/accounting/callback suites. Coverage includes
  R1/R2/R3 score-to-audit metric/terminal parity, funding, quantity constraints,
  liquidation, a short tape annualization fallback, held/released GIL parity,
  stale/capacity/lifetime behavior and existing public trace contracts. Rust
  `cargo fmt -p quantbt-native --check` and `cargo test -p quantbt-native --lib`
  passed (`4 passed`).
- Recorded warmed 10,000-bar prepared evidence in
  `benchmarks/native_event/results/phase75_reactive_scalar_retention.{json,md}`:
  score is `2.09x` (R1), `2.00x` (R2), and `1.95x` (R3) faster than the matching
  public-minimal cold path, with exact terminal equity. RSS fields are correctly
  labeled as same-process warm incremental allocation rather than a cold peak
  claim.
- Updated endpoint, Rust-contract, benchmark and README documentation. No
  unresolved correctness, retention, lifetime, callback-boundary, accounting,
  or documentation debt remains inside Phase 75. Public reactive WFO workers,
  candidate scheduling and their resource lifecycle are Phase 76 scope, not a
  deferred Phase 75 defect.

### Phase 76 - Reactive WFO And Sparse Candidate Scheduling

**Status: complete (2026-09-05).**

**Goal:** extend the public native WFO pipeline to reactive workloads without
per-trial worker imports, market packing or dense Python candidate dispatch.

**Read first:**
- [29.9-29.12: wake ordering, block invalidation and candidate batching](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#299-wake-semantics).
- [30.3-30.5: preparation, RNG and isolation](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#303-prepared-cache-contract).
- [32.13-32.18: sampling, reactive workers and performance](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#3213-optimizer-schedules).
- [38.3-38.8: lifetime, recovery and parallelism](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#383-handle-lifetime).

**Implementation sequence:**

1. P76-01: reuse Phase 74 mode/selection orchestration and Phase 73 evaluation
   rows; add reactive W3 adapters, not another Optuna driver. The current
   public strategy protocol stays valid; batched decisions remain opt-in.
2. P76-02: provide persistent Python process workers for heavy Python alpha.
   Each imports the strategy once, attaches immutable shared market, and owns
   native sessions. Use safe platform-specific shared memory/mmap ownership;
   serialize only small task bindings, never full market frames per trial.
3. P76-03: use candidate-indexed state and reusable sparse wake subscriptions
   for R3B. Scheduled-time queues, fill/order subscriptions and price/account
   conditions determine which candidate IDs enter Python. Avoid full context
   allocation or cloning for candidates that do not need a decision.
4. P76-04: continue each active account's necessary bar/event processing.
   Sparse decision dispatch does not imply O(wakes) accounting complexity. A
   skipped callback is legal only if the declared protocol and shadow trace
   prove it would not change commands/state.
5. P76-05: implement deterministic coalescing, candidate-local command/error
   ranges, fairness for mixed high/low churn, cancellation and bounded backpressure.
   Isolate mutable strategy state per candidate/fold; retry/reset must not inherit
   another candidate's orders, indicator state or RNG stream.
6. P76-06: coordinate Python processes, Rust workers and BLAS threads within the
   runtime budget. Handle callbacks' GIL needs without claiming threads remove
   Python compute cost. Report total worker RSS/PSS and shared-memory accounting;
   do not add identical mapped pages and call that unique retained memory.
7. P76-07: preserve sequential ask/tell when selected. Parallelize only independent
   evaluation work within that contract; candidate batching with adaptive search
   requires explicit throughput schedule and independent quality evidence.

**Code anchors and proposed deliverables:**
- Extend the Phase 73 runtime scheduler, Phase 74 WFO adapter modules and
  `ReactiveCandidateBatchRunnerCore` through focused new worker/wake modules.
- Reuse runtime budget/lifecycle helpers rather than maintain competing process
  or thread pools inside endpoint, strategy and optimizer layers.
- Add `tests/test_phase76_reactive_wfo.py`, process-lifecycle integration tests,
  and reactive WFO benchmark manifests with shared-memory cleanup assertions.

**Tests and exit gate:**
- Fixed candidate matrix: every-bar, sparse, block, process and candidate-batch
  routes agree on candidate/fold/scenario metrics, command/account traces and
  strategy-state fingerprints under the same declared decision contract.
- Worker counts, task completion order and reset/retry do not change fixed-matrix
  results. Same sequential sampling seed preserves trial/winner/OOS parity.
  Throughput schedule repeats deterministically for its batch size; quality/
  regret thresholds and seed ensemble are locked before measuring, not chosen
  after seeing a favorable best trial.
- Test simultaneous fill/funding/liquidation wake, sparse no-op, bad callback,
  worker death, cancel while waiting/in callback/between bars, budget overflow,
  teardown and repeated create/close. No leaked processes/shared-memory handles.
- One shared market preparation per logical run, no per-task full tape IPC,
  bounded in-flight intents/results and persistent pools. Callback dispatch
  follows required/coalesced decisions, not all candidates by default.
- Benchmark lightweight and Python-heavy strategies separately. Exit requires
  functioning public reactive WFO and resource/parity gates, not a native helper
  microbenchmark. All in-scope scheduler/worker leaks are fixed before closure.

**Rollback and evidence:** keep sequential single-process protocol available.
Record process/thread plan, effective sampling schedule, callback counts and
error attribution in existing metadata without dumping per-bar logs by default.

**Completion evidence:**

- Added the explicit public W3 route through
  `QuantBTEndpoint.native_event_strategy(...).prepare_reactive_walk_forward(...)`.
  It prepares one immutable single-symbol market tape and reuses
  `WalkForwardEngine` fold construction, parameter validation, Optuna control,
  and selector mathematics while scoring dynamic lifecycle strategies through
  prepared Rust account sessions. It certifies `mode_1_decay`,
  `mode_3_flat_minima`, `mode_4_is_only_robust`, and `mode_5_full_robust` with
  `fold_account_policy="reset_flat"`; it rejects Mode 2 and carry/replay
  boundaries before execution. Output is explicitly segmented reset-flat OOS
  accounts, not a fabricated stitched signal or compounded equity curve.
- Each candidate/fold task has absolute prepared-market bar coordinates and a
  fresh account at its task boundary. Rust `FullSession` supports fresh
  absolute windows, so callback timestamps, scheduled orders and causal
  history are identical between scalar selection and cold selected-fold audit.
  Mode 4/5 score only IS rows for selection. R3B Mode 1/3 scores every
  candidate on IS first, then scores only the IS shortlist on OOS; the former
  erroneous full IS+OOS pre-ranking path is removed.
- Added a run-scoped `ReactiveScalarSessionPoolV1` for the in-process route and
  a persistent Linux/POSIX fork-COW worker for sequential scalar scoring. A
  child inherits the immutable prepared market and owns resettable native
  session scratch; IPC carries only a small task marker and scalar row, with
  `worker_market_ipc_bytes_per_task=0`. Fork is fail-closed unless the parent
  has exactly one kernel thread. Worker cancellation, death, callback failure,
  poison/retry and closure discard mutable state before reuse; metadata records
  COW/PSS/RSS/shared/private memory rather than double-counted RSS.
- Added opt-in R3B fixed-matrix and adaptive
  `throughput_batch_v1` scheduling. Fixed matrices are canonically ordered by
  stable parameter hash. Adaptive batching uses explicit ask-B/score-B/tell-B
  with declared seed and batch size and is not presented as sequential TPE.
  It is global-schedule/in-process only. Native candidate-local command or wake
  errors become typed pruned trial records; a shared Python batch callback
  exception fails closed. Telemetry now exposes batch size, callback count,
  candidate dispatches, failures, zero market copy/IPC, and scalar callback/GIL
  counters from Rust payloads.
- Added `docs/reactive_wfo.md`, linked it from the documentation map, endpoint
  guide, capability guide, Rust contract, README and benchmark guide. The guide
  documents W3 scope, factory/lifecycle protocol, selection semantics,
  R3B/Optuna distinction, COW safety contract, metadata and no-fabricated-
  equity rule.
- The module-ownership gate exposed an oversized initial W3 orchestration file
  during final regression. It was split without a behavior change into the
  `reactive_wfo` runtime/lifecycle module and `reactive_wfo_support` contract,
  selector-bridge and cold-segment module; both are below the 1,000-line
  review threshold and the ownership/import-boundary gate passes without a
  whitelist exception.
- Added `benchmarks/native_event/benchmark_phase76_reactive_wfo.py` and
  committed `phase76_reactive_wfo.{json,md}`. On the declared 2,000-bar,
  eight-candidate, six-fold Mode 1 global fixture (three warmed repeats),
  lightweight sequential W3 measured `224.935 ms` / `96,517` actual
  candidate-fold visits/s; fixed R3B measured `233.752 ms` / `102,245`
  visits/s. These are separate sampling contracts, so no TPE speedup ratio is
  claimed. With deliberately Python-heavy callback work, sequential measured
  `464.960 ms` while R3B measured `252.496 ms`, coalescing `21,710`
  candidate callbacks into `36` shared batch callbacks while Rust continued all
  account processing. A clean one-thread worker subprocess completed `66`
  scalar tasks with zero market IPC and reported `53.4 MiB` PSS / `105.1 MiB`
  RSS, with shared mappings recorded separately.
- Focused evidence passes after rebuilding the local native wheel:
  `tests/test_phase76_reactive_wfo.py` (`16 passed, 3 direct-fork skips`);
  combined Phase 62/63/73/74/75/76 regression (`66 passed, 3 direct-fork
  skips`). The skipped direct tests are intentionally guarded against a
  multi-threaded parent; the same COW lifecycle passes in a clean constrained
  subprocess. Rust closure passes `cargo fmt --check`, `41` engine unit tests,
  `14` execution unit tests and `4` native unit tests.
- Final repository closure after source/root mirror synchronization and
  generated inventory, baseline, and benchmark-governance refresh is
  `1161 passed, 25 skipped` with real-data tests excluded. The 25 skips are
  declared external/direct-fork capability boundaries; they do not suppress a
  supported W3 public route or its clean-subprocess COW test.

**Phase boundary:** no unresolved Phase 76 correctness, selection, causality,
account-boundary, worker ownership, bounded-backpressure, candidate-local
failure, resource-observability, benchmark, or documentation debt remains in
the declared W3 single-symbol reset-flat scope. Generic target WFO, arbitrary
callback auto-promotion, reactive continuous/cross-margin portfolio/package
accounts, and later kernel/result-adapter performance work remain separately
scoped Phase 77/78 work, not unrecorded Phase 76 debt.

### Phase 77 - Rust Kernel And Result-Adapter Performance Closure

**Status: complete (2026-09-06).**

**Goal:** close measured losses to Numba/Python and excessive RSS in the actual
certified workloads, after public integration and copy ownership are correct.

**Read first:**
- [24.7-24.10: accounting invariants and incremental authority](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#247-incremental-accounting).
- [27.3-27.7: online reducers and lazy results](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#273-online-reducers).
- [33.4-33.8: target deltas, semantics and performance](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#334-direct-delta-flow).
- [34.3-34.11: portfolio admission, rebalance and performance](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#343-admission-policies).
- [35.7-35.12: bounded package reconciliation](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#357-previewreserveexecutereconcile).
- [36.3-36.7: specialized intrabar and promotion](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#363-specialized-not-universal).
- [63.2-63.3: budget and optimization order](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#632-route-review-budgets).

**Implementation sequence:**

1. P77-01: profile preparation, request validation, execution, metrics, output
   transfer and pandas adaptation separately. Reproduce Phase 66's prepared
   target loss and Phase 69's public intrabar loss with matched output/metrics;
   do not assume the language or one component is the cause before measuring.
2. P77-02: remove repeated immutable validation/fingerprinting and per-bar
   allocation where Phase 73 ownership already proves safety. Reuse per-symbol
   scratch, reject/outcome masks, candidate account buffers and native metrics.
   Mutable intent still receives its necessary validation.
3. P77-03: add guarded specializations for no funding, no slippage, fixed targets,
   equity sizing and absent quantity constraints only when profiler evidence
   justifies them. Skip unchanged-symbol trade work without skipping MTM,
   funding, margin or liquidation checks. Expose the selected specialization
   in diagnostics for regression tests.
4. P77-04: preserve one canonical accepted delta for turnover, fee, slippage,
   cash and attribution. Portfolio admission and package preview/reserve/commit
   remain transactional; replacing a state clone requires equivalent rollback
   scratch, including rejection and partial-package failure paths.
5. P77-05: reuse common account/instrument/cost primitives across specialized
   loops. Do not force targets/intrabar through an order arena when their
   certified semantics do not need it, or duplicate formulas for convenience.
   Preserve every execution-contract policy and funding timestamp convention.
6. P77-06: make normal Rust result adaptation lazy by field group. Score returns
   scalar metric rows; compact retains required buffers; audit adds detailed
   artifacts. Accessing metrics or plots must materialize only needed data and
   never rerun execution. An intentionally scalar-only result cannot fabricate
   an unavailable equity curve; request an explicit selected rerun instead.
7. P77-07: optimize data layout/cache locality before PGO/SIMD/allocator changes.
   CPU features need portable wheel dispatch; no `target-cpu=native` assumption
   for published wheels. No fast-math/accounting precision reduction or unsafe
   lifetime shortcut. Any unsafe work requires separate approved safety ADR.
8. P77-08: rerun representative full-study WFO, reactive, vectorized/target,
   portfolio, bounded package and intrabar comparisons. Report cold and warm
   latency, median/p95, throughput units, peak/steady RSS and boundary counters.

**Code anchors and proposed deliverables:**
- `rust/crates/quantbt-execution/src/{target,intrabar,package}.rs`, shared metrics
  and accounting primitives, native request adapters and `NativeResultV2`.
- New fast paths in small workload-specific modules, with reference dispatch
  tests; no broad rewriting of existing kernels or automatic backend changes.
- Add `tests/test_phase77_native_performance_parity.py`, native differential
  cases and matched public/score benchmark artifacts per workload.

**Tests and exit gate:**
- Fast/reference/Python-oracle parity for accepted positions, fill timing/price,
  costs, funding, margin, turnover, rejection state and liquidation. Include
  rounding boundaries, extreme leverage, stale/missing data, target reversal,
  risk-parity warmup and package failure conservation.
- Scalar/compact/audit metrics and final accounting agree. Test lazy cache
  ownership, repeat report access, retained outputs after runner reset/close,
  chart/metrics scope and result schema compatibility.
- Public and kernel benchmarks use Phase 72's locked contracts, noise policy
  and budgets. WFO aims for 2-5x end-to-end where execution/metrics dominate;
  target 1.2-2.5x and portfolio 1.5-4x are guide review targets, not fabricated
  guaranteed gains. Report the achieved value for every nominated workload.
- A public route eligible for promotion cannot be slower than its intended
  comparator without prior explicit user approval of a correctness-first
  exception. Intrabar must meet its locked no-regression budget versus warmed
  Numba. An unmet target is reported as unmet and requires a decision; do not
  silently redefine the workload or lower the threshold after optimization.
- Resource gates require bounded score retention and stable service/WFO RSS;
  do not promise arbitrary package-wide RSS reductions below import/shared-data
  floors. No known in-scope correctness, leak or report-replay issue at exit.

**Rollback and evidence:** each optimization has a tested reference/dispatch
fallback under the same contract. No auto promotion or deletion in this phase.
Archive before/after public latency as seconds/ms and workload throughput, not
only an internal phase-to-phase multiplier.

**Completion evidence:**

- P77-01 through P77-08 closed for the two affected certified surfaces without
  changing a public default or automatic promotion. The new matched artifact
  [`phase77_native_performance_closure.md`](../benchmarks/native_event/results/phase77_native_performance_closure.md)
  and its JSON companion separate raw kernel, immutable-market/request preparation, public result
  adaptation, median/p95, boundary counters, and same-process retention from
  unsupported generic claims.
- `PreparedRustIntrabarMarketV1` now owns a strict one-symbol native market
  handle and UTC index for `prepare_intrabar(...).run(...)`. A fresh candidate
  intent remains normalized and shape-checked, and Rust still computes its
  authoritative request fingerprint; only the redundant Python content digest
  and L4 retention are skipped for the explicitly prepared one-shot intent.
  Normal `backtest(...)` remains content-addressed. Cache eviction cannot
  invalidate a live prepared runner.
- Rust intrabar compact/standard no longer materializes fill objects,
  fill-report rows, or ambiguity vectors; audit alone materializes the bounded
  detail ledger. Direct close-target adaptation consumes typed compact output
  rather than first expanding it to a Python dictionary. The units/no-constraint
  direct-target loop skips only zero-delta resolution work; it never skips
  marking, funding, margin, liquidation, or accepted-delta accounting.
- On the locked 20,000-bar, one-symbol, one-hour intrabar fixture with nine
  post-warm samples, Rust prepared adapter measured `6.211 ms` (`3.22M bars/s`)
  versus the matching Numba path result at `9.446 ms` (`2.12M bars/s`). The
  public Rust prepared runner measured `10.233 ms` (`1.95M bars/s`) versus the
  matching Numba prepared runner at `13.884 ms` (`1.44M bars/s`), a `1.36x`
  improvement with exact path/fill/accounting parity. One-shot public endpoints
  were effectively tied: `72.241 ms` Rust versus `72.906 ms` Numba.
- The same artifact keeps the direct close-target distinction honest: prepared
  Rust score was `1.740 ms` versus the narrower Numba raw kernel at `0.592 ms`,
  while the public compact Rust route was `22.589 ms` versus `57.985 ms` for the
  matching Numba facade (`2.57x`). Rust score includes its native online metric
  reducer while the historical Numba raw comparator does not; no raw-kernel
  ratio is used as a public-promotion claim. Exact positions, equity, fee,
  funding, margin, turnover, rejection and liquidation parity passed.
- The 96-run prepared intrabar service probe reached a same-process RSS plateau
  after the initial adapter allocation: the sample was `251.020 MiB` at run 32
  and `250.715 MiB` at run 96 (`-0.305 MiB` final-half change). It is explicitly
  documented as a retention plateau containing both Python and Rust runtime
  allocations, not a fabricated standalone Rust-memory number. Direct-target
  RSS remains governed by its independent Phase 66 artifact.
- Added `tests/test_phase77_native_performance_parity.py` (five tests):
  content-addressed versus ephemeral prepared parity, native fingerprint
  preservation without Python digest, zero-delta units specialization parity,
  typed target metadata provenance, profile/repeat/cache-eviction runner
  lifetime parity. Focused Phase 60-77 regression passed `195 passed, 3
  skipped`; complete deterministic regression passed `1166 passed, 25 skipped`
  with real-data suites excluded. Rust gates passed: `cargo fmt --all -- --check`,
  `cargo test -p quantbt-engine --lib` (`41`),
  `cargo test -p quantbt-execution --lib` (`14`), and
  `cargo test -p quantbt-native --lib` (`4`). Source/root mirror, generated
  V1.1 baseline, documentation-link, module-architecture, benchmark-governance
  and `git diff --check` gates pass.
- README, endpoint, fast-intrabar, native-capability, and benchmark guides now
  state the new prepared-runner contract and its matched measurement. No known
  in-scope correctness, retention leak, report replay, cache-lifetime, or
  documentation debt remains. Generic promotion, installed-wheel validation,
  shadow observation, and release decisions remain Phase 78 scope; they are not
  silently represented as completed Phase 77 work.

### Pre-78 Follow-Up Scope And Inspection Record

**Planning approval: 2026-09-06. Implementation of each phase is pending.**

The user requested three bounded follow-up phases after the Phase 77 review.
They combine the proposed five-mode benchmark pass with concrete public-route,
ownership, and hot-loop work. This supplements the existing guide and scoped
Phase 72-77 evidence; it does not turn those earlier measurements into a claim
that every public WFO, portfolio, or reactive strategy is already Rust-primary.

**Canonical guide:**
[QuantBT Rust-Primary V1.1](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).
Read each phase's section links, the [shared execution rules](#mandatory-agent-execution-contract-for-phase-72-78),
and [guide 95-96](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#95-rules-for-coding-agents)
before implementation. Where historical behavior and the general guide differ,
write the exact compatibility contract first; never silently change a financial
or optimization method to make a native route eligible.

Inspection findings to verify against the implementation candidate:

| Finding | Source anchor | Required owner |
|---|---|---|
| Historical Phase 77.1 public prepared WFO accepted scalar signal/notional/unit targets and recorded `pct_equity` fallback | `src/quantbt/backends/native_wfo_public.py::_SUPPORTED_TARGETS`, `_prepare_state` | Phase 77.2 adds only explicit `pct_equity_transition_v1`; default/auto remain legacy |
| Legacy `%_equity` trades on signal changes; native direct `equity_fraction` resolves equity-dependent targets each bar | `src/quantbt/core/engine.py::_engine_pct_equity`; `rust/crates/quantbt-execution/src/target.rs::execute_direct_target` | 77.1 separate contracts; 77.2 transition-compatible executor |
| Dedicated target/portfolio WFO copies fold targets and masks and restricts workers to one | `rust/crates/quantbt-batch/src/target_wfo.rs`; `src/quantbt/backends/native_wfo_target.py` | 77.2 shared views and scheduler delegation |
| Prepared scalar output passes through native row-to-column collection, `as_dict()`, Python rows and WFO dictionaries | `rust/native_event/src/prepared_evaluation.rs`; `src/quantbt/backends/native_prepared_evaluation.py::_adapt_native_matrix` | 77.2 columnar internal score transport |
| Mode 2 bootstrap index generation still loops in Python before its accelerated Sharpe reduction | `src/quantbt/walkforward.py::_stationary_bootstrap_indices`, `_regime_bootstrap_indices` | 77.1 sampling lock; 77.2 native sampling/reduction |
| Sparse reactive observations allocate close/position vectors; batch field getters clone arrays; release-GIL stepping currently occurs per bar | `rust/native_event/src/reactive_numeric.rs::wake_observation`, `advance_bar`, `run_range` | 77.3 persistent observation and boundary work |
| Target execution rechecks immutable market windows; shared portfolio allocates bar scratch and clones transactional previews | `rust/crates/quantbt-execution/src/target.rs` | 77.3 validation lifetime and scratch reuse |
| Shared prepared worker cancellation is checked before a task executes, not throughout its long specialized loop | `rust/native_event/src/prepared_evaluation.rs::worker_loop` | 77.3 cooperative execution checkpoints |

The Phase 74 artifact measures Mode 1 global with `signal_notional`, not
`pct_equity` or every mode/schedule. Its separately measured median full-facade
and prepared-execute durations are approximately `431.7 ms` and `25.9 ms`.
This motivates profiling preparation and adaptation, but does not make a
precise additive CPU profile from independent medians. Prior artifacts remain
historical snapshots; 77.1 must bind new evidence to the current source and
extension identity before any new speed claim.

**Scope and architecture rules for all three phases:**

- Keep existing public endpoint names, strategy callbacks, parameter ranges,
  report methods and explicit compatibility routes. Extend current configuration
  resolution rather than adding a new `_rust` endpoint family or compulsory
  notebook plumbing. Default promotion remains Phase 78 work.
- Prioritize the normal `%_equity` alpha workflow. Public candidate scoring and
  final account reconstruction must reach the matching Rust authority when
  explicitly requested; helper-only parity cannot close that requirement.
- Reuse `FullSession`, specialized certified executors, the shared prepared
  runtime, canonical market/instrument contracts, and existing selectors.
  Introduce small cohesive modules using Python Protocols/classes for adapters
  and Rust structs/traits or bounded enums for execution and ownership.
  Avoid per-bar dynamic dispatch, a parallel accounting state machine, and
  broad rewrites of existing large files.
- Preserve canonical one-way fee, legacy `fee` conversion, price/quantity
  rounding, funding event phase, accepted-delta costs, and liquidation priority.
  Rust language choice is not evidence of correct financial behavior.
- Scalar optimization may omit paths; standard/compact/audit results must retain
  their declared information. Distinguish historical signal-based trade counts
  from committed fills or lifecycle events. Do not replace one with another
  inside a trade penalty or report simply because a native counter exists.
- Public Mode 2 keeps its existing return-proxy/synthetic-path objective for
  historical reproduction. This is not promoted to execution-account truth by
  moving sampling into Rust. Switching it to net executed returns, or adding
  Mode 2 to reactive W3, is a separate methodological change outside these phases.
- Existing bounded shared-account target and same-account linear package
  contracts are included. Generic risk-parity/hedge-model migration, arbitrary
  Python strategy compilation, new dynamic grid/DCA policy languages, reactive
  carry/cross-margin accounts, full Rust options, and venue-exact L2/inverse/
  quanto/cross-venue engines are not newly promised by this follow-up.
- Every work package starts pending. A discovered in-scope bug or unmet gate
  blocks phase completion; it cannot be renamed future work or hidden behind
  unsupported routing. Broader product non-goals remain explicit. Preserve the
  independent oracle and mirrors; no automatic deletion, merge, tag or publish.

### Phase 77.1 - Public Workload Baseline And Domain Contract Lock

**Status: complete. Implemented on `feat/rust-primary-v1_1`; this phase added
only baseline/contract/test/documentation evidence. It changed no runtime
dispatch, promotion decision, or financial execution semantics.**

**Goal:** produce the missing matched public benchmark matrix and freeze the
financial, optimization, and ownership contracts for 77.2/77.3. Establish which
paths are Rust, Python/Numba, hybrid, or unsupported before changing dispatch.

**Prerequisite:** inspect Phase 72-77 evidence and the current source/extension;
the historical completion records alone are not the new baseline.

**Read first:**
- [24.5-24.9: accounting sequence, arithmetic and invariants](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#245-deterministic-accounting-sequence).
- [25.4-25.5: independent FillReplay corpus](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#254-certification-corpus).
- [27.1-27.7: metrics, retention and public results](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#271-metrics-authority-boundary).
- [31.2-31.12: calendar, warmup, account boundaries and causality](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#312-fold-plan).
- [32.13-32.18: optimizer schedules, parity and performance](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#3213-optimizer-schedules).
- [33.3-33.6: timing and target semantics](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#333-timing-contracts).
- [60: domain certification matrices](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#60-certification-matrix-by-domain).
- [61: reactive measurements](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#61-reactive-benchmark-protocol),
  [62: WFO dimensions and reporting](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#62-wfo-benchmark-protocol),
  [63: locked review budgets](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#63-performance-budgets).
- [Current causal schedules](../docs/walkforward_causal.md),
  [public prepared scorer](../docs/native_prepared_wfo_public.md),
  [reactive W3 contract](../docs/reactive_wfo.md), and
  [measurement contract](../docs/performance/measurement_contract_v1.md).

**Implementation sequence (P77.1-01 through P77.1-09: complete):**

1. P77.1-01: record source hash, worktree state, installed native binary hash,
   API/capabilities, dependency versions, CPU and thread configuration. Rebuild
   only if native source and loaded extension differ. Archive a reproducible
   local baseline without treating a dirty development snapshot as an approved
   release artifact. Do not stage other phases' uncommitted work.
2. P77.1-02: record requested/resolved public backend, scoring backend, execution
   clock, sizing/rebalance policy, account/metric contracts and actual native
   entry counts for each nominated workload. Distinguish preparation ingress,
   per-execution copies, retained cache bytes and output conversion. A missing
   native path is a baseline gap with an owner, not a measured speedup.
3. P77.1-03: freeze the `%_equity` compatibility contract from the public
   endpoint through `_engine_pct_equity`: first-bar snapshot, signal processing
   with pyramiding on/off, allocation fraction/percentage conversion, resize
   only on weight change, frozen accepted units, reversal, and rejection retry
   behavior. Lock equity used for sizing, fee/slippage prices, buying power,
   funding/liquidation ordering, constraints and legacy report semantics.
   Keep it distinct from direct weight/equity-fraction per-bar rebalance.
4. P77.1-04: create the following public mode/schedule measurement matrix. Reuse
   actual calendar folds; numeric bar volume must not produce empty or invented
   folds. WFO frequency, study schedule and Optuna batch schedule are separate
   dimensions in artifacts.

   | Mode | Required public studies | Selection contract |
   |---|---|---|
   | `mode_1_decay` | `global`, `per_fold_decay`, nested `per_fold_causal`, single train/test | Existing two-stage IS admission and declared OOS decay; outer-OOS isolation only for the strict nested schedule |
   | `mode_2_sbb` | Existing `global` and single train/test routes | Same return proxy, simulation variants, RNG, synthetic metrics and selector stages; no new per-fold or reactive method |
   | `mode_3_flat_minima` | Existing `global` and single train/test routes | Same shortlist, clustering, tie-breaking and medoid/centroid reevaluation |
   | `mode_4_is_only_robust` | `global`, `per_fold_causal`, single train/test | Same temporal/plateau/bootstrap/complexity inputs; strict selection uses current IS only |
   | `mode_5_full_robust` | Full declared sample through existing facade | Full-sample calibration; no fabricated OOS fold or holdout claim |

5. P77.1-05: cover W0 callbacks and eligible W1/W2 adapters for single-symbol
   `%_equity` plus existing scalar signal/notional/unit targets. Add direct
   prepared target/shared-portfolio/package workloads as separately labelled
   rows; do not imply they are generic public WFO. Measure W3 Mode 1/3/4/5
   sequential and supported per-fold schedules, plus R3B fixed/adaptive batches
   under their existing global contract. Negative rows explicitly cover W3
   Mode 2, carry accounts, and unsupported mode/schedule pairs.
6. P77.1-06: use both identical fixed candidate matrices and separately paired
   whole sequential Optuna studies. Preserve seed, startup/sampler settings,
   duplicate/pruning/error policy, trial budget, early stopping and task order.
   For Mode 2 lock index/path fingerprints for stationary, regime, stress and
   GARCH fixtures. R3B throughput gets a distinct sampling label; its TPE
   sequence cannot be certified against sequential TPE as if unchanged.
7. P77.1-07: nominate bounded small/standard/long profiles before timing: retain
   existing 2,000/2,048-bar comparators where compatible; use a standard
   10,000-bar, 64-candidate, 3/6-fold set; and representative 100,000-bar,
   256-candidate, 12-fold stress cases. Use 1/8/20 symbols only for contracts
   that support them. Avoid an uncontrolled Cartesian product; list every
   included/excluded row and reason. Keep at least five warm paired repeats
   for headline standard results, separate cold/JIT/extension cost, and apply
   the existing noise, timeout and memory policy without changing it afterward.
8. P77.1-08: measure preparation/fold planning, Python strategy generation,
   signal/target packing, SBB index/path generation, native execution, metric
   reduction, selection/Optuna, final selected execution and report adaptation.
   Report per-run totals and median/p95; do not add independent component
   medians as an exact full-run decomposition. Publish actual executed
   candidate/fold/scenario/bar-symbol counts, RSS/PSS, worker utilization,
   allocation/retention and Python/native boundary counts.
9. P77.1-09: publish a prioritized finding-to-work-package table for 77.2/77.3,
   including baseline loss, proposed mechanism, domain risk, exact comparator
   and a predeclared gate. Separate measured bottlenecks from code-inspection
   hypotheses. No runtime optimization or automatic promotion closes in 77.1.

**Code anchors and proposed deliverables:**
- Existing benchmark scripts for Phase 65/66/67/68/69/73/74/75/76/77 and
  `tools/measurement_contract.py`; reuse their fixture/identity utilities.
- Add `benchmarks/native_event/benchmark_phase77_1_public_matrix.py`, focused
  fixture/measurement helpers, a manifest and JSON/Markdown results. Put future
  filenames in code formatting until the files exist; do not add dead links.
- Add `tests/test_phase77_1_measurement_contract.py` for counters, row eligibility
  and invalid evidence; extend independent financial fixtures where the
  `%_equity` migration contract needs an explicit baseline.
- Add a documented transition-sizing contract and a five-mode baseline guide;
  link them from endpoint/performance docs and this plan after creation.

**Tests and exit gate:**
- Hand-computable entry/hold/reversal/rejection, costs/funding and fold-join
  fixtures identify exact accepted units and account values. Check discrete
  events exactly and specify per-field float tolerances before porting; never
  round objective scores merely to reproduce a winner.
- Baseline fixed-matrix and same-sequence study fingerprints reproduce. Check
  undefined/zero-trade metrics, trade-frequency penalties and near ties.
- Strict schedules pass future-price/funding/label mutation; retrospective
  and selection-adjusted schedules retain truthful provenance. Shared-account
  calendar mismatches cannot be relabelled to match length.
- Every required public mode row has measured historical behavior; native
  coverage and missing routes are explicit. Existing-route parity failures
  are investigated before using the result as an optimization reference.
- Benchmark units, output profiles, sample counts and binary identity pass
  governance checks. Resource-limited rows remain pending, not successful.
  Exit requires a complete baseline and contract lock, not a speedup yet.

**Technical debt and phase boundary:** existing migration/performance gaps are
assigned explicitly to 77.2/77.3 in the findings table. No unresolved baseline,
metric-definition, sampling, or measurement ambiguity may pass to 77.2.
Future Rust options/advanced execution domains retain their existing scope.

**Rollback, docs and evidence:** this phase adds specifications, fixtures and
measurement tools only. Preserve old artifacts and expose their dates/hashes.
Append real commands, results and exclusions to the standard completion record;
mark the phase complete only after its gate and await separate 77.2 approval.

**Completion record (2026-09-06):**

- P77.1-01/P77.1-02: added
  `benchmarks/native_event/benchmark_phase77_1_public_matrix.py` and
  `benchmarks/native_event/manifests/phase77_1_public_matrix_v1.json`.
  Each output captures source/worktree/native-extension identity, requested and
  resolved prepared-native policy, final backend, score rows/batches/bars,
  fold/candidate work counters, component timings, RSS/PSS snapshots, and a
  fixed-candidate result fingerprint. The new manifest is explicitly
  baseline-only and the governance checker rejects any attempt to make it a
  promotion artifact.
- P77.1-03: added the executable
  `legacy_pct_equity_transition_sizing_v1` hand fixture and
  `docs/contracts/pct_equity_transition_v1.md`. It locks first-bar snapshot,
  entry/hold/reversal, carried-position funding, no retry after an unchanged
  rejected signal, `0.5`/`50` allocation equivalence, and raw-weight reporting.
  The historical `fee` compatibility input is stated explicitly. It is a
  frozen migration boundary for Phase 77.2, not a fee reinterpretation in this
  documentation-only phase.
- P77.1-04/P77.1-05: smoke measured all required W0 public rows: Mode 1 global,
  per-fold decay, per-fold causal and train/test; Mode 2 global/train-test
  proxy-preserved; Mode 3 global/train-test; Mode 4 global/per-fold causal/
  train-test; Mode 5 full sample; and the legacy `%_equity` fallback. All ten
  eligible prepared-native rows passed public result fingerprint/account parity.
  Mode 2 and `%_equity` correctly remain unpaired `proxy_preserved`/`fallback`
  rows with zero native score rows. W3 reactive, direct target, shared
  portfolio, and bounded package evidence is recorded separately in the
  artifact with its own Phase 66/67/68/76 comparator; none is mislabeled as a
  W0 public-WFO speedup.
- P77.1-06/P77.1-08: the benchmark warms both lanes, asserts equity/returns/
  fees/funding/positions plus selector fingerprint parity, then alternates
  paired timing order. The standard profile is a real 10,000-bar `1h` tape,
  three quarterly calendar folds after 180D training, 64 requested Optuna
  trials, and five paired repetitions; it does not accidentally turn 10,000
  daily bars into a 100-fold study.
- P77.1-07 measured standard output is
  `benchmarks/native_event/results/phase77_1_public_standard.json`: reference
  median `0.775200 s`, prepared-native median `0.385958 s`, `2.009x` paired
  speedup, exact fingerprint parity, 24 native score rows / 6 batches / 89,024
  native-scored bars. Its same-process RSS/PSS delta is reported as
  `+78.40/+78.17 MiB` with a `4.86 MiB` warm-tail spread; it is not a
  cold-process ownership or release-memory claim. Smoke/standard/long now use
  separate output filenames so evidence cannot overwrite another profile.
- P77.1-09: the artifact carries a prioritized 77.2/77.3 finding table with
  mechanism, financial risk, comparator and gate. The declared next work is
  intentional phase ownership, not unresolved Phase 77.1 ambiguity: Rust must
  reproduce transition-sized `%_equity` before eligibility widens; W0 prepared
  ownership can be reduced only with same-study parity; Mode 2/W3 retain their
  own sampling/reactive contracts.
- Tests/gates passed:
  `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_phase77_1_measurement_contract.py tests/test_phase72_measurement_contract.py`
  (`16 passed`),
  `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_phase77_1_measurement_contract.py tests/test_phase74_public_wfo_native.py tests/test_phase64_wfo_correctness.py tests/test_phase76_reactive_wfo.py`
  (`54 passed, 3 skipped`),
  `PYTHONPATH=src .venv/bin/python tools/check_benchmark_governance.py`
  (PASS), and `git diff --check` / `py_compile` (PASS).

**Phase boundary:** there is no unresolved 77.1 measurement or contract
ambiguity. The artifacts are intentionally non-promotional because Phase 77.1
does not change execution. Phase 77.2 remains separately approved work and
must pass the stated accepted-unit/account/selector parity gates before any
new public Rust authority is claimed.

### Phase 77.2 - Public WFO Rust Execution And Prepared Ownership Closure

**Status: complete.** The explicit Rust transition route, columnar score
boundary, shared prepared ownership, public-mode parity and matched benchmark
gates passed on `feat/rust-primary-v1_1`. Compatibility defaults remain
unchanged: legacy/`auto` stays historical, while Rust requires explicit
`target_runtime="rust"` and `native_prepared_wfo="require"` for the admitted
single-symbol `%_equity` scope.

**Goal:** accelerate the real public alpha/WFO workflow through Rust execution,
prepared ownership and native numeric scoring while preserving all five
optimization methods, chronological policies and existing result APIs.

**Prerequisite:** Phase 77.1 contract, comparator and required-route matrix pass.
Implement in the order below; do not start by widening backend eligibility.

**Read first:**
- [24.4-24.10: transactions, financial state and invariants](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#244-previewreservecommit).
- [27.1-27.7: native metrics and result adaptation](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#271-metrics-authority-boundary).
- [30.2-30.5: strategy isolation, cache and RNG](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#302-contract).
- [31.6-31.12: fold accounts, proxy and provenance](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#316-fold-account-policy).
- [32.4-32.12: typed inputs, persistent workers, no-copy and reducers](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#324-generic-prepared-workload-inputs).
- [32.13-32.18: optimizer schedules and parity](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#3213-optimizer-schedules).
- [33.3-33.8: direct execution and frozen target semantics](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#333-timing-contracts).
- [34.7-34.11: shared accounts and portfolio WFO](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#347-shared-account-invariants).
- [35.7-35.12: package reconciliation and scope](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#357-previewreserveexecutereconcile).
- [63-65: performance budgets and API compatibility](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#63-performance-budgets),
  [public prepared WFO](../docs/native_prepared_wfo_public.md),
  [shared runtime](../docs/native_prepared_evaluation.md) and
  [selection methodology](../docs/walkforward_methodology_vi.md).

**Implementation sequence (P77.2-01 through P77.2-11: pending):**

1. P77.2-01: implement the frozen `%_equity` transition policy in a focused Rust
   execution module using existing account/instrument/cost primitives. Preserve
   first-bar behavior, processed-signal transitions, no drift rebalance, and
   rejection retry semantics. Keep previous requested signal separate from
   accepted position; a rejected order must not alter either state incorrectly.
   Do not implement it as an alias for per-bar `equity_fraction` rebalance.
2. P77.2-02: route `QuantBTEndpoint.pct_equity`, compatible WFO/train-test
   candidate tasks, and the selected chronological final execution through
   that exact native contract when explicitly requested. Reuse existing public
   backend/configuration conventions. Keep W0 strategy signatures and old
   notebook calls; expose requested/resolved authority and unsupported reasons.
   Default behavior and automatic promotion remain unchanged until Phase 78.
3. P77.2-03: move existing scalar signal sizing/transition expansion into the
   matching native request where it removes measured Python work. Prepare
   market/calendar/instruments and stable masks once, store fold/shard integer
   ranges once, and avoid repeated pandas reindex/Series construction inside
   candidate scoring. Validate every newly supplied mutable signal/target.
4. P77.2-04: delegate target/shared-portfolio WFO execution to the shared
   persistent scheduler. Use immutable `Arc`-backed intent/mask views plus
   range offsets instead of `to_vec()` for every fold. Preserve absolute market
   timestamps and local fresh-account start behavior. Certify 1/N-worker
   equivalence and bounded scheduling before lifting the old serial restriction.
   Existing helper APIs become compatibility delegates, not parallel runtimes.
5. P77.2-05: connect the nominated existing bounded portfolio target routes to
   public scoring/final execution only through matching sizing, rebalance and
   admission contracts. Reuse existing Python strategy-owned hedge/risk
   preparation where valid; do not force a shared account into independent
   single-symbol accounts. Bounded package/scenario evaluation reuses the same
   scheduler and its actual leg/dependency contract, with route scope explicit.
6. P77.2-06: keep scalar columns typed through native evaluation and internal
   reducers. Avoid mandatory `as_dict()` -> per-row dataclass -> per-row dict
   conversion on every score batch. Provide lazy compatibility row access for
   existing callers and adapt small Optuna objective values at their boundary.
   Preserve candidate/fold/scenario IDs, status/error slots and native
   fingerprints; keep trade-count definitions distinct from lifecycle counts.
7. P77.2-07: provide bounded native bootstrap sampling/reduction for Mode 2
   stationary, regime and stress variants using the 77.1 sampling contract.
   Preserve the NumPy seed/bit-generator/version, conditional integer draws,
   sample order, floating reduction and all penalties. First replay recorded
   sampling tapes through the native reducer; then certify live native index
   generation against the reference before routing it. Chunking must preserve
   the original random stream; a new seed per chunk is not equivalent.
8. P77.2-08: retain the proven GARCH fitting implementation in Python and move
   repeated path reduction to Rust where certified. Preserve all Mode 2
   original/synthetic/OOS stages and proxy provenance. A native implementation
   does not turn return-proxy results into fee/margin-aware execution metrics.
   Failure to reproduce RNG/ranking blocks the nominated sampling work; it is
   not permission to change the objective or silently call it completed.
9. P77.2-09: feed existing Mode 1/3/4/5 selectors from the same scalar columns.
   Optimize temporal reductions or parameter-distance preparation only when
   profiling justifies it and fixed-candidate/tie parity passes. Retain existing
   clustering libraries and algorithms unless independently justified; do not
   introduce a new robust selector, centroid rounding or early-stop behavior.
10. P77.2-10: apply bounded request retention appropriate to sequential trials.
    Reuse immutable signatures while an owner is alive; avoid keeping every
    one-shot candidate tape in a long-lived cache. Mutation, configuration,
    funding, constraints, metric policy and window changes invalidate the
    relevant layer. Reset/clear/eviction cannot invalidate retained results.
11. P77.2-11: run the full 77.1 public WFO matrix after integration, with both
    scalar and selected audit/report paths. Update endpoint, WFO methodology,
    prepared runtime and performance documentation, including which old calls
    use compatibility and how existing configuration requests native execution.

**Code anchors and proposed deliverables:**
- Narrow delegates in `src/quantbt/endpoint.py`, `walkforward.py`,
  `backends/native_wfo_public.py`, `native_wfo_target.py`, and
  `native_prepared_evaluation.py`; focused internal request/column adapters.
- Existing `rust/crates/quantbt-execution`, `quantbt-batch`, shared metrics and
  `rust/native_event/src/prepared_evaluation.rs`. Proposed focused modules:
  transition-equity policy, prepared target windows and bootstrap reducers;
  do not put every new responsibility in `lib.rs` or `target.rs`.
- Add `tests/test_phase77_2_wfo_execution_parity.py`,
  `tests/test_phase77_2_sampling_parity.py`, Rust ownership/RNG tests, and
  benchmark results against the unchanged 77.1 manifest.
- Add runnable examples using existing `pct_equity`, WFO and train-test
  endpoints. Preserve source/root mirror checks without independently editing
  both source trees.

**Tests and exit gate:**
- Compare transition `%_equity` against independent expected ledger fixtures
  and the frozen public oracle: flat/nonflat initial signal, same-side hold,
  reversal, fractional weights, pyramiding, allocation conventions, tiny lots,
  rounding boundaries, rejected resize, insufficient post-cost margin,
  positive/negative funding and liquidation on either side of execution.
- Validate accepted units and `delta_qty` -> notional/turnover/fee/slippage/cash
  reconciliation. No extra trade or missed funding event may be hidden by
  matching final equity. Keep old reporting provenance if it historically
  reports signals rather than actual units; expose accepted positions explicitly.
- Same candidate matrices yield matching metrics, penalties, ranking, shortlist,
  tie/centroid decisions and final params across all five modes. Sequential
  studies preserve trial params/states, pruning and early stopping. Bootstrap
  indices/path fingerprints and reductions match for multiple seeds, sizes,
  block lengths, regimes and chunk boundaries, including degenerate samples.
- Causal schedules resist future mutation. Final stitched target execution
  preserves account continuity, same-side boundary carry, reversals, gaps,
  sizing transitions, costs and incomplete last folds. Candidate account reset
  and final account continuity are tested separately.
- Prepared/window/serial/batch/1/N-worker/score/audit parity passes, including
  failure isolation, stable result ownership, changed input signatures, cache
  eviction and repeat use. No market or existing immutable intent copy per
  execution; controlled new-candidate ingestion is counted honestly.
- Normal public endpoints prove actual native execution and preserve report
  scope/schema. New Rust requests fail clearly with an incompatible wheel;
  old explicit Python/Numba paths remain reproducible.
- Full-study timings and RSS pass the locked workload gates. Use the guide's
  2-5x WFO review target only where simulation/metrics dominate; report actual
  per-mode gains, misses and strategy-time ceilings. Unmet mandatory gates or
  unexplained ranking/performance regressions prevent closure, not lower limits.

**Technical debt and phase boundary:** no unfinished `%_equity` public route,
shared-window/pool integration, or score-column contract is deferred to 78.
Mode 2's established NumPy/Numba bootstrap/GARCH proxy remains deliberately
authoritative and `proxy_preserved`: it is not a partially migrated Rust route,
and exact RNG/path ranking is protected by the existing fail-closed `require`
boundary. Reactive hot-loop changes and specialized scratch/output optimization
are owned by 77.3. GARCH fitting, custom indicators/objectives and unsupported
reactive Mode 2 remain explicitly outside the migration contract.

**Completion record (2026-09-06):**

- P77.2-01/P77.2-02: added Rust `pct_equity_transition_v1` under the existing
  direct-target authority. It preserves first-bar snapshot, processed-signal
  transition-only sizing, no drift rebalance, carried-unit funding, pre-cost
  margin admission, liquidation, raw public signal positions, and accepted
  units under `metadata["pct_equity_transition"]["accepted_positions"]`.
  Legacy `fee` and explicit one-way `fee_rate`, and legacy fractional slippage
  and V2 slippage, must agree exactly or fail before execution.
- P77.2-03/P77.2-04/P77.2-05: the public single-symbol WFO scorer emits a
  typed transition request over its existing one-time prepared market/template
  and persistent Rust runtime. It keeps fresh candidate accounts and one final
  continuous stitched account. Existing shared portfolio/package workloads
  continue through the same prepared runtime; `103` focused cross-domain
  tests cover their unchanged authority and 1/N worker behavior.
- P77.2-06/P77.2-09: `score_columns()` returns typed scalar SoA buffers. The
  WFO adapter no longer constructs native score dataclasses/dicts per row; it
  adapts only the compact metrics used by the established objective/selectors.
  Mode 1/3/4/5 `%_equity` selection, trial table, selected params, stitched
  result and public report match the legacy oracle.
- P77.2-07/P77.2-08: Mode 2 is certified as `proxy_preserved`, not silently
  reimplemented. Its NumPy/Numba path sampler/GARCH contract keeps the current
  seeded draws, reduction order and proxy provenance. `auto` records that
  authority; `require` raises. This is a deliberate no-migration boundary, not
  an incomplete Rust score claim.
- P77.2-10: existing prepared signatures cover timestamp, symbols, OHLCV,
  funding, funding mask, constraints and request content. Regression verifies
  volume/funding invalidation, cache clear/stale binding rejection, source-array
  detachment and one-versus-many worker parity.
- P77.2-11 evidence: `tests/test_phase77_2_pct_equity_native.py`,
  `tests/test_phase73_prepared_evaluation.py`,
  `tests/test_phase74_public_wfo_native.py`,
  `tests/test_phase64_wfo_correctness.py`,
  `tests/test_phase67_rust_shared_portfolio.py`, and
  `tests/test_phase68_rust_package_authority.py` passed (`103 passed`).
  `cargo test -p quantbt-execution` passed (`14 passed`) and
  `cargo test --manifest-path rust/native_event/Cargo.toml` passed (`4 passed`).
  The Phase 77.1 smoke/standard controls and Phase 77.2 smoke/standard paired
  artifacts pass. Standard `%_equity` is `1.558 s` legacy versus `0.698 s`
  explicit Rust (`2.231x`) on 10,000 `1h` bars / 64 trials / 5 repeats.
- Docs/manifests: `docs/contracts/pct_equity_transition_v1.md`,
  `docs/native_prepared_wfo_public.md`, `docs/native_prepared_evaluation.md`,
  endpoint/WFO methodology references, and
  `benchmarks/native_event/manifests/phase77_2_pct_equity_wfo_v1.json`.
  Rollback is explicit: omit `target_runtime="rust"` or use
  `native_prepared_wfo="off"`/`"auto"`.

**Rollback, docs and evidence:** preserve versioned compatibility timing and
sampling policies; existing explicit backend controls restore the prior path.
Archive baseline/current hashes and selected parameter/join artifacts. Add
real test commands and per-work-package status before completion. No automatic
promotion or package publication occurs in this phase.


**Status: complete (2026-09-06). P77.3-01 through P77.3-10 passed their
development-candidate closure gate; Phase 78 remains planned and unapproved.**

**Goal:** reduce remaining reactive allocation/GIL overhead and repeated native
kernel/result work, close responsive resource enforcement, and hand measured
public capabilities to Phase 78 without changing strategy decisions or finance.

**Prerequisite:** 77.2 passes its domain, integration and ownership gate. Reuse
the locked 77.1 comparison contracts and the now-current shared runtime.

**Read first:**
- [24.4-24.9: transactional state and accounting invariants](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#244-previewreservecommit).
- [27.3-27.7: reducers, retention and lazy results](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#273-online-reducers).
- [29.3-29.7: numeric context, commands, outer loop and GIL](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#293-persistent-reactivecontextbuffer).
- [29.8-29.12: sparse wake, invalidation and candidate batching](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#298-dynamic-sparse-wake-protocol).
- [29.13-29.17: errors, ownership and four-way parity](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#2913-error-model).
- [32.14-32.18: reactive WFO and parallelism](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#3214-reactive-wfo-paths).
- [33.4-33.8: specialized target execution](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#334-direct-delta-flow).
- [34.3-34.11: portfolio admission and rollback](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#343-admission-policies).
- [35.7-35.12: package transactions and residuals](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#357-previewreserveexecutereconcile).
- [36.3-36.7: intrabar scope and gates](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#363-specialized-not-universal).
- [38.1-38.8: budget, cancellation, lifetime and teardown](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#381-runtime-budget).
- [61-63: reactive/public performance protocol](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#61-reactive-benchmark-protocol),
  [runtime contract](../docs/native_event_rust_full_contract.md) and
  [resource governance](../docs/native_runtime_governance.md).

**Implementation sequence (P77.3-01 through P77.3-10: completed):**

1. P77.3-01: reuse previous/current observation storage, candidate wake lists
   and projection buffers in R1/R2/R3/R3B. Preserve chronological observation
   phases and generation checks; do not expose a mutable buffer as an immutable
   historical snapshot. Any borrowed view expires safely at its declared
   boundary, while callers can request a detached cold snapshot.
2. P77.3-02: replace repeated batch getter clones and dict wake-plan conversion
   on the optimized path with bounded typed numeric access. Keep old strategy
   protocols callable through adapters. Validate order handles, candidate IDs,
   command capacity, wake thresholds and invalidation policies once per changed
   plan, with deterministic per-candidate error isolation.
3. P77.3-03: group Rust execution while no Python decision is needed so sparse/
   block routes do not detach/reacquire the GIL for every skipped callback bar.
   Still process every account bar and stop at the first required wake or block
   invalidation. Preserve funding, fills, rejects, liquidation and scheduled
   commands as wake sources; no hindsight-based decision skipping.
4. P77.3-04: improve candidate scheduling and session reuse within the existing
   W3 contract. R3B wake coalescing may share market observation, not account,
   open orders, strategy state or RNG. Keep sequential TPE and adaptive batch
   schedules distinct. Known bounded StrategyIR drivers may use existing native
   dispatch; arbitrary Python callback compilation is not introduced here.
5. P77.3-05: move redundant immutable market/window validation out of repeated
   target/portfolio execution only after request construction certifies the
   relevant domain constraints. A general market handle is not automatically a
   valid specialized request. Keep mutable intent validation, signatures,
   stale/tradable masks and configuration invalidation intact.
6. P77.3-06: reuse target/portfolio rejection masks, candidates and commit scratch.
   Replace full transactional clones only with an equivalent bounded preview/
   rollback mechanism covering positions, cash/equity, attribution, reservations,
   margin and costs. Preserve `sequential_legacy`, reduce-first, pro-rata and
   all-or-none ordering. Skipping unchanged trade work never skips MTM, funding,
   margin or liquidation. Add specializations only for measured hot cases.
7. P77.3-07: preserve package primary/hedge actual-fill dependencies and residual
   artifacts while optimizing buffers. Keep intrabar SL/TP/trailing, gap/tick
   policies and ambiguity order identical. Use the shared metric/account
   primitives; do not replace a specialized loop with order-arena work that
   changes its contract or duplicates another accounting authority.
8. P77.3-08: finish nominated public cold adapters using typed native buffers and
   lazy field groups. Score remains scalar; standard/compact/audit expose their
   documented paths and artifacts. Repeated metrics/plot/report access must not
   execute or replay again. Reset/close/eviction cannot mutate an earlier result.
9. P77.3-09: thread cancellation/deadline checks through long prepared native
   tasks at deterministic bounded intervals. Preserve transactional commits and
   fail/cancel statuses; canceled partial scores cannot compete as successes.
   Validate timeout latency, worker join/teardown, panic recovery and bounded
   audit/error retention. Metadata-only or preflight-only budgets do not pass.
10. P77.3-10: rerun all nominated public WFO/reactive/target/shared-portfolio/
    bounded-package/intrabar workloads from 77.1, including one-shot and prepared
    routes. Report each optimization's measured effect and unaffected controls.
    Update docs and nominate exact capabilities for 78; do not change auto
    eligibility, release versions or advertised wheel scope in this phase.

**Code anchors and proposed deliverables:**
- `rust/native_event/src/reactive_numeric.rs`, `reactive_score.rs`,
  `prepared_evaluation.rs`; `rust/crates/quantbt-engine/src/session.rs` and
  `rust/crates/quantbt-execution/src/{target,intrabar,package}.rs`.
- Add focused observation/wake, execution-budget, scratch and typed-output
  modules, with narrow delegation from existing files. Safe ownership and
  portable wheel compilation remain mandatory; no fast-math, lower accounting
  precision, host-only CPU flags or unsafe lifetime shortcuts.
- `src/quantbt/backends/reactive_wfo*.py`, native portfolio/package/intrabar
  adapters and `src/quantbt/core/native_result_v2.py` retain public interfaces.
- Add `tests/test_phase77_3_reactive_parity.py`,
  `tests/test_phase77_3_kernel_resource_parity.py`, Rust unit/property fixtures,
  and before/after results under the unchanged 77.1 workload manifests.

**Tests and exit gate:**
- Compare Python oracle, numeric every-bar, sparse/block, batch and command
  replay where contracts match. Assert observations, decisions, command order,
  accepted/rejected orders, actual fills, fees, funding, positions and account
  trace. Cover simultaneous wakes, fill-driven rearming, OCO siblings, partial
  fills, gaps, stop/TP/trailing, margin change and liquidation invalidation.
- Batch-vs-single and W3 selected-score/audit parity pass for Mode 1/3/4/5 and
  each supported schedule. Per-fold state is reset exactly; reset-flat W3 output
  is never presented as compounded continuous equity. Candidate failure and
  callback exceptions must not contaminate peers or later runs.
- Fast/reference specialized kernel parity includes stale/asynchronous data,
  rounding/minimum boundaries, reversals, post-cost margin rejection, portfolio
  atomic rollback and partial-package conservation. Pure-kernel comparisons
  include matching metric/retention work on both sides.
- Lifetime tests retain a result or user-visible context past reset/close and
  verify the documented snapshot/stale-view behavior. Repeated report access
  preserves data, scope, metric definitions and artifact availability without
  another execution entry. No new unbounded candidate or bar cache is allowed.
- Cancellation/deadline/panic/resource tests exercise long active work, not only
  preflight rejection. Workers terminate or recover within the locked budget;
  interrupted transactions never publish success or leak state to the next run.
- New extension build, focused Rust/domain tests and shared-boundary regression
  pass before timing. Run the full deterministic regression after the final
  shared core changes, recording every skip; installed distribution/platform
  and release-observation gates remain Phase 78 responsibilities.
- Matched public median/p95 and RSS gates pass; report cold cost, warm plateau,
  callbacks/GIL crossings, allocations and copies. Use PSS for shared workers;
  do not sum shared RSS as private retention. Check enough repetitions to
  distinguish allocator warmup from candidate-proportional growth.
- No nominated promoted route may regress beyond its predeclared budget without
  an explicit user decision. Report review-target misses honestly; do not claim
  universal speedup from native kernels or different sequential/batch candidates.

**Technical debt and phase boundary:** no unresolved in-scope finance, sampling,
state isolation, responsive resource enforcement, retention leak, public report
regression or missing measurement remains at exit. Arbitrary strategy compilation,
new reactive account-continuity semantics, full Rust options and venue-specific
advanced domains remain the declared non-goals. A newly discovered mandatory
defect stays an open blocker, not an item silently transferred to release.

**Rollback, docs and evidence:** retain reference dispatch and current explicit
backend controls; preserve old contract IDs and oracle fixtures. Update README
with comparable seconds/ms and throughput only for measured public workloads;
keep reactive/WFO sampling and work units separate. Attach exact source/native
identity, test counts, parity bundles and resource results. Phase 78 may begin
only after 77.1, 77.2 and 77.3 have concrete passing completion records and
the user separately approves the release-certification phase.

**Completion record (2026-09-06):**
- P77.3-01/P77.3-02 passed: R1/R2/R3/R3B reuse resettable native observation
  and candidate buffers; `WakePlanV1.as_native_wire()` supplies the typed
  `quantbt-wake-wire-v1` path while legacy payload-only plans remain an exact
  compatibility adapter. No historical observation is exposed as a mutable
  view.
- P77.3-03/P77.3-04 passed: R2/R3 advance no-decision gaps in Rust, R3B shares
  only immutable market observation across isolated candidate accounts, and
  sequential Optuna versus ask-B/score-B/tell-B retain separate declared
  sampling contracts. R3B selection orchestration now lives in
  `reactive_wfo_batch_selection.py`; the public runtime lifecycle facade is
  583 lines and the batch-selection module is 497 lines, both below the
  ownership threshold without an exception.
- P77.3-05/P77.3-07 controls passed without a speculative accounting rewrite:
  public WFO, shared portfolio, bounded package, and intrabar control harnesses
  retained their existing one-owner request/account contracts and showed exact
  required parity. No result construction replays execution.
- P77.3-08 passed: scalar score remains path-free; materialized public result,
  compact, and audit routes remain cold-path adapters with no re-execution.
- P77.3-09 passed: cancellation and `RuntimeBudgetV1.max_wall_time_ms` are now
  checked during active Rust work. R1 checks each completed account bar; R2/R3
  gaps check at most every 64 completed bars plus wake/end boundaries. Scalar,
  R3B, and clean POSIX COW-worker routes propagate typed cancellation/deadline
  failure and discard a partial score before selection. Reset clears active
  cancellation/deadline state before reuse.
- P77.3-10 evidence: `benchmark_phase77_3_reactive_closure.py --profile
  standard` passed with all parity/resource controls. On its declared 10,000-bar
  scalar workload, R2/R3 score paths measured `13.588 ms` / `735,954 bars/s`
  and `20.949 ms` / `477,346 bars/s`; the 2,000-bar, eight-candidate W3
  lightweight rows measured `196.556 ms` sequential (`110,452`
  candidate-fold bar visits/s) and `226.748 ms` R3B (`105,404`). Python-heavy
  callback work remains separately reported, not claimed as Rust speedup.
- Validation: focused reactive suites passed `29 passed, 3 skipped`; expanded
  product/baseline/governance/reactive matrix passed `83 passed, 3 skipped`;
  `cargo test --manifest-path rust/native_event/Cargo.toml` passed `4`,
  `cargo test --manifest-path rust/Cargo.toml -p quantbt-execution` passed `14`,
  and the full deterministic suite passed `1191 passed, 25 skipped` with
  `tests/test_real.py` and `tests/test_real_endpoints.py` intentionally excluded
  because they require external real-data dependencies. Mirror, generated
  baseline, benchmark governance, product-contract, and module-architecture
  checks all passed.
- Documentation/artifacts: README, endpoint, reactive WFO, runtime-governance,
  benchmark and native-contract guides plus the Phase 77.3 JSON/Markdown
  artifact were refreshed. Phase 77.2/77.3 manifests are explicit
  non-promotional workload contracts; they cannot satisfy a release/promotion
  gate by themselves.
- Open debt in this phase: none. Declared non-goals remain arbitrary callback
  compilation, new continuous-account reactive WFO semantics, generic
  portfolio/package WFO promotion, full Rust options, and venue-specific
  advanced domains. No auto eligibility, version, wheel scope, or release
  state changed. Rollback remains the existing explicit Python/reference route.

## Additional Performance Closure - PERF-01 To PERF-07

**Status: PERF-01 COMPLETE (2026-09-06); PERF-02 through PERF-07 remain
PLANNED. Planning was authorized on 2026-09-06. PERF-01 adds source/profiler
contracts only; no benchmark qualification or promotion is authorized by this
group until its later phase gates are closed. Each remaining phase requires the
user's individual approval before its implementation starts.**

**Canonical detailed guide:**
[APC-1.0: seven-phase pre-78 performance closure](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md).
The guide's work packages, adversarial cases, measurement rules and handoff
schema are normative for this group. Read the whole guide once, then the
linked sections for each approved phase. Also read the existing
[agent execution contract](#mandatory-agent-execution-contract-for-phase-72-78)
and the original
[V1.1 domain guide](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md).
This delivery plan provides ownership and gates; it does not replace the
detailed guide with a smaller implementation target.

**Integration and evidence boundary:**
[0: evidence scope](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#0-phạm-vi-bằng-chứng-và-cách-đọc),
[1: insertion and dependencies](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#1-tích-hợp-vào-upgradeimplementmd),
[15: integration checklist](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#15-checklist-merge-vào-implementmd-và-tiếp-tục-phase-78) and
[17: source and dependency evidence policy](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#17-nguồn-và-evidence-policy).

- Use the current `feat/rust-primary-v1_1` branch. Planning inspected commit
  `0b396fa1e6e08d5d5dea6017615fe6fa21825bd1`; that identifies the planning
  context, not the future measurement baseline or a released candidate.
  PERF-01 must pin the actual source/build when its work starts.
- No existing `PERF-01` through `PERF-07` IDs were found in the main plan
  during insertion. Keep these seven IDs together and preserve all previous
  phase IDs, completion evidence, and the Phase 78 release scope.
- The detailed guide explicitly says its author did not audit this source
  snapshot. Treat claimed hotspots, proposed types, source locations and old
  benchmark observations as investigation inputs. Verify existing work before
  adding replacements; `VERIFIED_EXISTING` requires current public-path proof.
- Source types such as `RequiredComputationPlan`,
  `DerivedAccountSnapshot` and `PerformanceClosureManifest` are proposed
  contracts until mapped/implemented. Do not infer that they already exist.
- Each approved phase must close its own work packages and update this plan
  before the next phase starts. Commit each coherent verified change on this
  feature branch immediately; stage only that change and its required tests,
  docs and evidence. Do not accumulate another multi-phase dirty checkpoint.
- Phase 78 keeps its original status and gates. It additionally requires a
  validated `READY_FOR_PHASE78` handoff from PERF-07 matching the current
  source/build. These seven phases do not authorize merge, tags, public wheel
  upload, blanket Rust promotion, or deletion of Python/oracle/mirror sources.

### PERF Dependency And Proposal Map

Follow [1.3: dependency graph](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#13-dependency-và-thứ-tự) and
[1.4: all twelve AP proposals](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#14-mapping-12-ap-sang-bảy-phase).

| Phase | Primary proposals | Required integration | Dependency |
|---|---|---|---|
| PERF-01 | AP-01 computation/output; AP-11 observer overhead | Public requests, five WFO modes, audit schemas | Existing 77.1-77.3 records; new baseline inspection |
| PERF-02 | AP-02 touched reset; AP-04 derived account state | Session lifecycle, reactive workers, target/portfolio/package consumers | PERF-01 contracts |
| PERF-03 | AP-03 hidden callback crossings | Public reactive endpoint and reactive WFO; reuse AP-01/02/04 | PERF-01/02 gates |
| PERF-04 | AP-05 matcher/layout; AP-06 specialization | Existing native loops and derived-state consumers | PERF-01/02 gates |
| PERF-05 | AP-07 evaluation graph; AP-08 statistical reducers; AP-09 locality | Public five-mode WFO, reactive WFO, full trial identity | PERF-03/04 plus PERF-01 audit schema |
| PERF-06 | AP-10 columnar research audit | PERF-01 computation plan and PERF-05 evaluation/selection graph | PERF-01 schema; close integration after PERF-05 |
| PERF-07 | AP-12 build/PGO; closure of AP-01 through AP-11 | Combined public workloads, candidate wheels and release handoff | All PERF-01 through PERF-06 gates |

Default approval/closure order is PERF-01 -> PERF-02 -> PERF-03 -> PERF-04 ->
PERF-05 -> PERF-06 -> PERF-07 -> Phase 78. The guide permits PERF-03/04 and
parts of PERF-05/06 to overlap technically; that is not permission to start an
unapproved phase. PERF-01 locks the PERF-06 schema early, so PERF-05 can use
that contract without inventing a competing audit model or waiting for the
writer implementation.

### PERF Shared Domain, Architecture, And Evidence Contract

Read [2: shared acceptance rules](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#2-chuẩn-nghiệm-thu-dùng-chung),
[10: AC-01 through AC-44](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#10-adversarial-test-matrix-bắt-buộc),
[11: benchmark fixtures and hard gates](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#11-benchmark-portfolio-và-gates-theo-nhóm),
[12: work-package and PR organization](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#12-tổ-chức-prwork-packages) and
[13: public-path integration requirements](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#13-đường-chạy-tích-hợp-tối-thiểu-để-tránh-helper-only) before each phase.

**Domain and ownership:**

- Strategy owns indicators/features, research models, decisions and declared
  strategy state. Python strategies remain first-class; no `quantbt-features`,
  mandatory Rust strategy rewrite, model fitting, or hidden feature authority.
  Rust owns admitted simulation/accounting work between Python decisions.
- Preserve public endpoint names, existing notebook calls, callback timing,
  one-way fee/legacy conversion, funding, margin, quantity/tick rules,
  effective intent timing, account carry and actual selected parameters.
- Reuse the existing FullSession, prepared handles, arenas/indexes, pools,
  co-runtime, reducers and SoA/result substrate. New modules/classes/Protocols
  and Rust structs/traits must own a specific responsibility. No second
  accounting authority, optimizer or scheduler; no broad file relocation.
- Keep economic and performance fingerprints separate. Economic identity covers
  all outcome-affecting data/state/clock/cost/strategy/RNG semantics.
  Performance identity covers kernel/layout/tiling/topology/retention encoding
  and build choices. A physical optimization cannot silently change economics.
  Version public API, internal command ABI, request/result schemas and package
  release separately; retain lockfile/toolchain versions unless an approved
  dependency migration is required.
- Pin exact comparisons for IDs, timestamps, phases, ordering, lot/tick
  quantities, statuses, pruning/checkpoints and selected-candidate tie-breaks.
  Pin float comparator/reduction policy before implementation. No fast-math,
  RNG-sequence substitution, relaxed tolerances or nondeterministic reductions.
  A ranking, admission or pruning change is not excused by close final equity.
- Preserve the independent oracle. If the baseline has a domain bug, record a
  separate correctness repair/spec delta, test it and repin affected evidence.
  Do not preserve an incorrect economic rule merely to match the baseline, or
  conceal that repair inside a performance claim.
- Resource/ownership correctness and requested audit completeness are hard
  gates. Callback suppression, reduced trials, missing candidates, lost audit,
  simplified execution fidelity and changed sampling cannot fund a speedup.

**Requirement disposition and no-debt policy:**

Every AP, PF work package and mandatory AC case must map to actual public
consumers, source symbols, test IDs, evidence and an owner. Work packages start
`pending`; their phase starts `PLANNED`. Use the guide's final dispositions:

| Disposition | Minimum evidence and closure meaning |
|---|---|
| `IMPLEMENTED_VERIFIED` | New implementation, real public wiring, independent/compatibility tests and measured decision; candidate qualification supplied at PERF-07 |
| `VERIFIED_EXISTING` | Existing symbols/tests/counters and current public-path evidence already satisfy the requirement |
| `NOT_BENEFICIAL` | Controlled experiment or measured analysis supports retaining the baseline; no unsupported speedup claim |
| `BLOCKED_CORRECTNESS` | Reproducer, affected capability and owner; that capability cannot close or promote |
| `DEFERRED_APPROVED` | Explicit user-approved scope decision with impact and provenance; never silently treated as a passed mandatory release requirement |

No `UNKNOWN`, `BENCHMARK_ONLY`, `HELPER_ONLY`, unresolved in-scope defect,
or missing required artifact can close a phase. An unsuccessful measured
optimization may close its investigation as `NOT_BENEFICIAL`; an unperformed
investigation may not. Named downstream implementation remains with its owner,
while current defects stay blockers. Final manifest eligibility must validate
the accepted scope and all required dispositions, not silently omit deferred
or blocked rows.

**Measurement and validation cadence:**

- Pin baseline/source/native identity, dataset/corpus/strategy/params,
  economic/retention contract, worker topology, budgets and toolchain.
  Preserve earlier raw evidence under its original identity.
- Measure public end-to-end, native execution, preparation, analysis and
  export separately; distinguish exclusive stage times, wall time and aggregate
  worker CPU. Record actual visited bars, candidates/folds/scenarios, commands,
  fills, callback/getter/writer boundaries and emitted audit rows.
- Report cold cost, warm prepared cost, cache-miss/hit/mixed cost, reset and
  queue cost, RSS/PSS, retained bytes and steady plateau. A cache hit is an
  avoided execution, not newly processed bars/s; use actual visited prefixes
  for pruned/canceled tasks.
- Alternate paired baseline/candidate samples with identical work. Use at
  least 30 pairs for warm macrobenchmark p50; use sufficient observations for
  p95 (guide proposes at least 100) or label it exploratory. PERF-01 locks
  noise-aware per-class budgets; 3% p50 and 5% p95 are starting proposals,
  not automatically approved gates. Inadequate evidence is `INCONCLUSIVE`.
- Test independent invariants/oracle, public equivalence, audit/selection,
  ownership/concurrency/faults, exact candidate wheels, then performance and
  route eligibility. During implementation run focused affected tests; rebuild
  when Rust/ABI changes. PERF-07 runs combined qualification, and Phase 78
  retains final distribution/platform gates for the actual release artifacts.
- Report a performance decision for every investigated shape. Do not multiply
  overlapping speedups or force an indexed/Rust/PGO path onto small workloads
  where a contract-equivalent baseline is faster.

**Artifact organization:** extend the existing benchmark/governance and
`docs/performance/` structures. Proposed evidence groups may live under
`benchmarks/native_event/manifests/` and `benchmarks/native_event/results/`
with `perf_01` through `perf_07` IDs. PERF-01 chooses actual files and schema
ownership after inventory. These names are deliverables, not existing passing
artifacts. Keep private strategy/data, credentials and machine-only build
outputs out of Git and public distributions.

### Phase PERF-01 - Source Traceability, Profiling, And Computation/Output Plan

**Status: COMPLETE (2026-09-06).**
**Goal:** pin the real public-workload baseline, identify repeated work, and
implement or verify the computation/output plan and low-cost observation path.
**Proposal owners:** AP-01 and AP-11.
**Prerequisite:** current branch access and prior phase evidence inspected.

**Read first:** [3: PERF-01 detailed guide](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#3-perf-01--source-traceability-profiling-và-computationoutput-plan),
[2.3: economic versus performance identity](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#23-economic-contract-và-performance-plan-là-hai-thứ-khác-nhau),
[2.5: measurement policy](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#25-performance-measurement) and
[8.1: financial versus research retention](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#81-pf-061--hai-chiều-retention-độc-lập).
The common AC/benchmark/approval rules above apply in full.

**Implementation sequence (completed):**

1. PF-01.1, [3.1: pin and public inventory](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#31-pf-011--pin-baseline-và-map-public-workloads): record source SHA,
   dirty state, lockfile/toolchain/native module origins and available artifact
   hashes; hash fixture strategy/data/params privately where appropriate.
   Map public factory -> resolved request -> runtime -> metrics/result -> export
   for static orders, replay, target/signal/pct-equity/static DCA, reactive,
   portfolio/basket, bounded package/arb, intrabar, each WFO mode and options
   containment. Classify every AP as still open, already satisfied, or needing
   a measured experiment; do not recreate existing prepared or sparse code.
2. PF-01.2, [3.2: exclusive profiler and workloads](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#32-pf-012--causal-profiler-và-workload-suite): instrument
   prepare/validate/ingest, native advance/match/account/wake, projection/Python
   decision/command write+ingest, metrics/analysis/audit encode+flush/adapt,
   reset/cache/queue. Avoid nested double counting; distinguish native entries,
   callback entries and Python-to-native getters/writers. Establish B-01 through
   B-14 shape classes, including failures and slow audit. MRS is one nominated
   fixture, not a runtime dependency; unavailable MRS inputs remain unqualified
   rather than being replaced by a synthetic fixture labelled MRS.
3. PF-01.3, [3.3: RequiredComputationPlan](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#33-pf-013--requiredcomputationplan): resolve objective,
   constraints/pruning, strategy context, financial retention and research audit
   into required observations/paths/reducers/sinks at prepare. Reuse the
   canonical observation stream with observation IDs; do not count fills as
   returns or update reducers twice for multiple readers. Opaque custom metrics
   receive conservative complete inputs. Preserve actual pruning checkpoint
   values/order and all public result fields; path elision requires every
   consumer to be satisfied under its declared retention contract.
4. PF-01.4, [3.4: immutable work and observers](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#34-pf-014--hoist-immutable-work-và-giảm-observer-cost): hoist stable
   contract/symbol/schema/callback resolution and immutable hashes only within
   valid lifetimes. Remove writable aliases before treating content as fixed.
   Use typed success codes and worker-local counters; retain required validation,
   public status detail and canonical events. Compare coarse measurement and
   detailed profiling against observers-off economics.
5. PF-01.5, [3.5: cross-cutting contract lock](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#35-pf-015--khóa-cross-cutting-contracts-sớm): record ADR/schema
   contracts for retained/borrowed views and staged commands, reset versus carry,
   semantic cache identity/authorization/retention, research ledger/legacy
   exports, callback exceptions/re-entry/cancel/capacity, numeric/RNG/tie-breaks
   and actual WFO mode/schedule migration. PERF-06 writer implementation remains
   downstream; the schema and compatibility obligations must be decided here.

**Current code anchors to inspect:** `src/quantbt/endpoint.py`,
`walkforward.py`, `backends/native_wfo_public.py`,
`backends/native_prepared_evaluation.py`, `core/native_result_v2.py`,
`core/runtime_governance.py`, `rust/native_event/src/prepared_evaluation.rs`,
`rust/crates/quantbt-engine/src/metrics_v2.rs` and
`tools/measurement_contract.py`. Python paths after the first are relative to
`src/quantbt/`; verify exact functions before recording the implementation map.

**Tests and exit gate:** [3.6: PERF-01 gates](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#36-gates-và-output).
AC-01 through AC-04 and AC-42 must cover repeated readers, custom metric
fallback, intermediate pruning, writable input aliases and observers on/off.
Use future-suffix mutations and actual public result/checkpoint comparisons.
Profiler counters must measure the intended work without changing it. Lock
metric pass count, allocations, hash cost, observer overhead and public timing
with per-workload uncertainty/budgets. Exit requires a complete source/AP
investigation map and no unresolved baseline contamination or ambiguous
economics/audit contract. It does not require unapproved later-phase kernels.

**Deliverables/docs:** baseline identity and route/AP/AC/B matrix, profiler and
workload harness, computation-plan ADR, safety/cache/audit schema contracts,
prioritized hotspots and budget report; update measurement and endpoint docs
for any implemented optional surface.

**Technical debt/rollback:** no missing baseline, metric dependency or contract
decision at exit. Reuse verified existing logic; reject measured harmful
optimizations. Roll back the performance plan/profiler to the pinned compatible
path, preserving any separately approved correctness repair. PERF-02 owns reset
implementation; PERF-05 owns evaluation cache; PERF-06 owns durable writer.

**Completed implementation and evidence:**

- PF-01.1: [`perf_01_traceability_v1.json`](../benchmarks/native_event/traceability/perf_01_traceability_v1.json)
  and its generated [human route map](../docs/performance/perf_01_traceability.md)
  record every required public family, all five WFO modes, options containment,
  AP-01 through AP-12 disposition, AC-01 through AC-44 ownership, B-01 through
  B-14 workload registration, concrete source hashes and actual oracle/fixture
  anchors. Dynamic commit/dirty/toolchain/module identity is intentionally
  captured separately rather than baked into a static artifact that would go
  stale after a documentation commit.
- PF-01.2 and PF-01.4: [`performance_contracts.py`](../src/quantbt/core/performance_contracts.py)
  provides the opt-in `ExclusiveWorkProfilerV1` with five non-overlapping
  buckets and explicit nullable boundary counters. `WalkForwardEngine` records
  preparation, strategy projection, candidate score/account work and WFO
  result adaptation; prepared-native score batches report native outer calls
  without double-timing the outer scorer. The disabled path skips per-strategy
  and per-score observer calls.
- PF-01.3 and PF-01.5: `RequiredComputationPlanV1` is compiled for each WFO
  invocation and exported through both engine and endpoint metadata. It locks
  objective/selector paths, retention, reducer identity, sinks and checkpoint
  needs. Opaque custom metric requirements retain complete inputs and reject a
  scalar-only native score route; existing `OnlineMetricReducerV2` remains the
  financial authority. The durable contract is documented in
  [`perf_01_computation_and_observer.md`](../docs/contracts/perf_01_computation_and_observer.md).
- The paired public-facade harness
  [`benchmark_perf01_observer.py`](../benchmarks/native_event/benchmark_perf01_observer.py)
  alternates observer-off/on Mode 1 runs and fails on any selection/accounting
  fingerprint difference. Its committed [100-pair clean-source artifact]
  (../benchmarks/native_event/results/perf_01_observer_baseline_v1.json)
  contains the exact candidate/data/intent provenance and separate latency p50,
  latency p95, and pair-order noise diagnostics. These measures are evaluated
  against provisional `3%`/`5%` proposals without pretending a local baseline
  is backend-promotion evidence; the artifact is generated only from a clean
  source candidate and redacts machine-local extension paths. The current
  `3634f65` evidence has exact economics, `+0.17%` p50 observer overhead and
  `-13.66%` p95 quantile ratio, both within the provisional budget; its
  `11.41%` pair-delta p95 is retained only as scheduling-noise context.
- Focused evidence: `tests/test_perf_01_traceability_and_computation.py` covers
  reducer de-duplication, conservative custom-metric fallback, Optuna trial
  ledger/order equivalence, observer on/off economics, exclusive-stage safety,
  public endpoint forwarding, generator validation and the paired facade
  harness. Existing WFO schedule/prepared/native tests remain the compatibility
  lock.

**Exit disposition:** AP-01 and AP-11 are `IMPLEMENTED_VERIFIED` for the WFO
computation-plan/observer scope. The traceability artifact explicitly leaves
AP-02 through AP-10 and AP-12 with their named downstream PERF owners; that is
planned phase scope, not hidden PERF-01 debt. No execution, accounting,
selection, Optuna ordering, strategy lifecycle, audit retention policy or
public endpoint name changed. The rollback is to disable `perf_01_profile` and
use the existing scorer path; the plan metadata is observational and does not
alter economic state. The measured p95 observation is a PERF-01 baseline fact,
not a qualification failure or an unowned correctness debt; PERF-07 owns
cross-workload performance qualification and promotion decisions.

### Phase PERF-02 - Safe Session Reuse And Shared Derived Account State

**Status: IMPLEMENTED_VERIFIED (2026-09-06).**
**Goal:** make repeated independent sessions cheap while proving reset,
retained-view lifetime and derived-account invalidation correctness.
**Proposal owners:** AP-02 and AP-04.
**Prerequisite:** PERF-01 locked contracts and independent account oracle.

**Read first:** [4: PERF-02 detailed guide](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#4-perf-02--session-reuse-an-toàn-và-shared-derived-account-state),
[3.5: locked safety contracts](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#35-pf-015--khóa-cross-cutting-contracts-sớm) and
[10: adversarial ownership/reset cases](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#10-adversarial-test-matrix-bắt-buộc).

**Implementation sequence (completed):**

1. PF-02.1, [4.1: measure reset first](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#41-pf-021--đo-reset-trước-khi-thay-data-structure): profile logical clear,
   destructor, zeroing, index rebuild and allocation separately. Compare fresh,
   reused and huge-then-small independent trials (including the proposed
   100,000-order predecessor). Introduce touched lists/generations only for
   measured capacity/history-dependent costs; a cheap `Vec::clear()` is not
   automatically a replacement target.
2. PF-02.2, [4.2: complete reset manifest](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#42-pf-022--reset-manifest-đầy-đủ): classify immutable
   shared input, run state, worker scratch and retained output. Enumerate wallet,
   positions, marks, fees/funding cursors, margin/reservations/liquidation,
   orders/parents/OCO/expiry/pending commands, IDs/generations/sequencing,
   liquidity/RNG, wake/callback/strategy state, metrics/path/audit namespaces,
   cancel/error/poison state. Define generation wrap quarantine/recreation.
   Reset fresh candidates only; never reset carried deployment state implicitly.
3. PF-02.3, [4.3: retained buffer ownership](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#43-pf-023--ownership-của-retained-buffers): implement verified
   snapshots, pinned leases/refcounts, or a proxy that never exports unchecked
   raw views. A wrapper generation token cannot revoke a retained raw ndarray.
   Prevent writable aliasing, concurrent writes/native reads and resize under
   exported views. Budget leases; choose copy or explicit failure on overflow.
   Old results must remain readable after repeated worker resets.
4. PF-02.4, [4.4: phase-aware derived snapshot](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#44-pf-024--derivedaccountsnapshot-theo-phase): reuse a coherent
   equity/margin/exposure snapshot keyed by phase and mark, position, wallet,
   reservation, fee/funding, risk/instrument versions. Invalidate at every
   relevant mutation including no-position-change marks and reserve/release
   within one bar. Consumers cannot mutate accounting by reading metrics.
   Incremental additive terms require certified semantics; nonlinear margin,
   tiers, offsets/FX use supported full recomputation with a debug comparator.
5. PF-02.5, [4.5: fault/reset oracle](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#45-pf-025--faultreset-oracle): compare a fresh session with
   reuse after success, rejection, liquidation, callback failure, cancellation,
   open reservations, writer failures and large capacity. Test independent
   candidate permutation, stale handles, forced-small generation wrap, retained
   arrays, poison/recreate recovery and Python factory/reset contracts.
   Never retry a mutated Python strategy without an explicit restore contract.

**Implementation record (2026-09-06):**

1. `FullSession` now classifies immutable template data, mutable account/order
   lifecycle, resettable scratch, and owned result output. Reset clears wallet,
   positions, marks, fee/funding state, lifecycle indexes, commands, liquidity,
   buffers, caches, counters, and poison-adjacent reactive state before each
   independent run. It remains prohibited for carried account state.
2. `OrderArena` does an O(1) terminal clear only when no order is live. A live
   arena is scanned and cancelled. Generation `u32::MAX` retires its slot rather
   than wrapping, while order sequencing fails explicitly on exhaustion.
3. `DerivedAccountSnapshotV1` is post-execution only and is keyed by named
   mark/position/wallet/fee/funding/risk/instrument versions. The current
   single-session route has no persistent reservation ledger, so reservation is
   explicit in the snapshot schema but remains unchanged; package reservation
   preflight retains its existing separate contract. The full recompute path is
   the parity oracle.
4. Native typed outputs transfer owned storage to Python. Prepared and reactive
   reset diagnostics expose manifest, result policy, reset count, cache counts,
   capacities, and retired arena slots without entering the score hot path.
5. The focused corpus covers fresh/reuse parity, 128 repeated prepared runs,
   retained output after scratch release, stale handles, mark/fill/fee/funding/
   liquidation snapshots, callback failure plus explicit recovery, cancellation,
   rejection/writer failure, and existing package reservation regression cases.
6. The release fixture reproduces normal, terminal-100k, and live-100k reset
   behavior. Its evidence is scoped to native lifecycle reset; it makes no WFO
   or public-facade throughput claim.

**Current code anchors:** `rust/crates/quantbt-engine/src/session.rs`,
`rust/native_event/src/{prepared_evaluation,reactive_numeric,reactive_score}.rs`,
`src/quantbt/backends/{native_prepared_evaluation,reactive_wfo_workers}.py`,
`src/quantbt/core/{native_result_v2,runtime_governance}.py`; reuse actual
session/arena/account ownership found there.

**Tests and exit gate:** [4.6: PERF-02 gates](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#46-gates-và-output).
AC-04 through AC-10 require fresh/reuse trace parity, zero residual
reservations/events, unchanged retained bytes, safe stale handles, and derived
snapshots matching from-scratch recomputation after every small-corpus event.
Measure reset time/bytes zeroed/touched ratio, recompute counts, retained leases,
scratch/high-watermark growth and peak/steady RSS. Fixed independent candidate
outcomes must not depend on their predecessor; carried simulations are tested
under their separate stateful contract.

**Deliverables/docs:** reset/ownership manifest, event invalidation table,
fresh/fault/permutation corpus and per-optimization decision benchmark; update
runtime lifecycle and prepared-use documentation.

**Technical debt/rollback:** no cross-trial leakage, stale snapshot or unsafe
buffer reuse at exit. Safe fallback is fresh independent construction and full
derived recomputation, never a reset of a carried account. Existing memory
budgets remain enforced across leases, scratch and outputs.

### Phase PERF-03 - Reactive Boundary, Context Projection, And Command Staging

**Status: IMPLEMENTED_VERIFIED (2026-09-06).**
**Goal:** reduce the real cost per Python decision/wake while retaining
first-class Python strategy behavior and Rust execution ownership.
**Proposal owner:** AP-03; integrates AP-01/02/04.
**Prerequisite:** PERF-01/02 gates; existing R1/R2/R3/R3B scope inspected.

**Read first:** [5: PERF-03 detailed guide](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#5-perf-03--reactive-pythonrust-giảm-hidden-crossings-và-công-việc-mỗi-wake),
[5.6: four-way comparison](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#56-four-way-parity-và-benchmark),
[14.3: runtime changes outside this critical path](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#143-free-threadedcompiled-strategy-paths-gpu-và-thêm-domain).

**Implementation sequence (completed):**

1. PF-03.1, [5.1: callback access plan](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#51-pf-031--lập-callback-access-plan): compile declared context
   fields, handles and delta cursors once at a valid strategy lifecycle
   boundary. Measure outer entries, callback calls and nested getter/writer
   calls separately. Use fixed numeric projections where profitable; retain
   safe snapshots for historical-context consumers. Dynamic callback mutation
   needs explicit invalidation or compatibility routing. Apply PyO3 optimizations
   against the pinned version; do not claim zero scalar boxing without evidence.
2. PF-03.2, [5.2: shared staged commands](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#52-pf-032--shared-staged-command-batch): measure the existing
   writer, then use bounded primitive rows/stable numeric handles and one
   valid-prefix ingest where beneficial. Resolve immutable enums/schema early;
   perform dynamic admission at its original phase. Discard all unsubmitted
   staged rows on a callback exception and record dirty strategy state. Successful
   callbacks retain per-command business acceptance/rejection; callback staging
   atomicity must not turn an ordinary batch into an all-or-none trading package.
   Capacity growth uses a boundary handshake, never resize under active views.
3. PF-03.3, [5.3: wake before projection](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#53-pf-033--sparse-wake-giảm-projection-không-chỉ-invocation): evaluate wake conditions
   before expensive context materialization using existing timers/indexes.
   Continue matching, valuation, funding, margin and metrics on idle bars.
   Preserve on-fill/on-close ordering and effective command times. OHLC
   high/low may only influence decisions after their availability. No-command
   callbacks may update counters/RNG/state, so every-bar callbacks cannot be
   skipped without a versioned strategy/parameter/timing safety contract.
4. PF-03.4, [5.4: GIL and process lifetime](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#54-pf-034--rút-ngắn-critical-section-giữ-threadprocess-semantics-đúng): optimize existing
   co-runtime policies without a redundant GIL mode or pool. Do not hold native
   locks across callbacks that can re-enter. Verify attach/detach while waiting.
   Python-heavy work may require an already-supported process path; fork only
   under safe pool/thread lifecycle rules and measure whether IPC pays off.
5. PF-03.5, [5.5: batch and block protocols](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#55-pf-035--candidate-batch-và-block-protocols-đã-có): verify numeric batch
   decisions actually combine candidates, rather than wrapping individual
   callbacks in one native call. Isolate each candidate's state/RNG/namespace
   and errors; preserve optimizer IDs/order. Separate precomputed exogenous
   tapes from online block observations. Future block contents cannot affect
   commands before availability. Insufficiently certified fast protocols remain
   explicit; mandatory every-bar access/writer improvement is still evaluated.

**Current code anchors:** `src/quantbt/api/event_driven.py`,
`src/quantbt/backends/{native_event,reactive_wfo,reactive_wfo_batch}.py`,
`src/quantbt/strategies/{context,reactive_protocols,reactive_wfo}.py`,
`rust/native_event/src/{reactive_numeric,reactive_hot_loop,reactive_score}.rs`.
Preserve the existing public facade and callbacks; use narrow delegation.

**Implementation record (2026-09-06):**

1. PF-03.1: `ReactiveCallbackAccessPlanV1` compiles the optional
   `quantbt_reactive_callback_binding_v1="run_stable"` plan once per native
   run. The default stays `dynamic_compatibility_v1`, resolving lifecycle
   methods on each boundary so in-run Python method replacement remains
   compatible. R1, R2, and R3 share the access plan; a pinned plan is scoped
   to one fresh run and never crosses reset/candidate/fold/WFO boundaries.
2. PF-03.2: the persistent numeric writer is an explicit callback-local staged
   primitive buffer. Rust validates the full structural timing envelope before
   scheduling any row; normal quantity/notional/margin admission remains
   per-command. Callback exception, invalid return, or invalid envelope clears
   every unsubmitted row, marks strategy state dirty, and poisons the reusable
   runner until explicit reset. Capacity remains bounded and no view is resized
   while active.
3. PF-03.3: lifecycle callable resolution now happens before projection. An
   absent optional hook allocates no context; every declared every-bar callback
   still runs. Sparse and block wake detection remains before projection and
   keeps existing event-clock/availability ordering.
4. PF-03.4/03.5: existing `held_for_session` and
   `release_between_callbacks` policies remain the only policies. R1/R2/R3
   and candidate-batch semantics retain isolated strategy/account/RNG state;
   no pool or callback compilation route was introduced.
5. Observability now separates callback-plan compilation, dynamic lookups,
   context projections/getters, writer entries, completed command callbacks,
   discarded staged rows, and callback dirty state. It is telemetry only and
   never enters financial state or scoring.

**Evidence:** `tests/test_perf_03_reactive_boundary.py` adds A/B/C/D financial
parity, dynamic mutation, R2/R3 pinned-plan, staged exception/invalid-output,
business-rejection, and absent-hook coverage. Existing Phase 62/63/75/76/77.3
corpora retain stale-handle, wake ordering, future availability, capacity, and
candidate failure-isolation coverage. The public 2,000-bar artifact
[`perf_03_reactive_boundary.json`](../benchmarks/native_event/results/perf_03_reactive_boundary.json)
alternates dynamic/pinned sample order across a no-op control and B-02 through
B-06; it reports full facade timing, counters, and RSS without making a
general promotion claim.

**Tests and exit gate:** [5.7: PERF-03 gates](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#57-gates-và-output).
AC-11 through AC-17 compare independent small-corpus oracle, pinned baseline
bridge, optimized bridge, and captured effective-command static replay.
Compare callback inputs, ordering, commands, financial traces and supported
strategy-state fingerprints; replay alone cannot prove decisions or sparse
wake completeness. Include many getters/commands, retained contexts, exception
after writes, ordinary business rejection, overflow/re-entry/cancel, silent
state/RNG changes, future suffix perturbation, competing wakes and peer failure.
Benchmark B-02 through B-06 with ns/wake, projection/allocations, all boundary
counters and full public time. Preserve every-bar callback counts; declare
sparse/batch sampling contracts explicitly.

**Deliverables/docs:** context/writer ownership plan, wake/projection integration,
four-way corpus, route-by-shape recommendation and measured Python residual;
update reactive endpoint/protocol/WFO docs with stable usage.

**Technical debt/rollback:** no stale alias, lost staged commands, future
availability leak, deadlock or unexplained callback difference at exit.
Restore the compatible baseline bridge/snapshot writer when a fast shape
fails safety/performance. Arbitrary Python compilation and free-threaded
deployment remain outside this phase.

**Exit disposition:** AP-03 and AC-11 through AC-17 are
`IMPLEMENTED_VERIFIED` for the declared numeric reactive contract. Python-heavy
callbacks remain Python-bound by design; that measured Amdahl residual is not
an unowned correctness or performance debt. PERF-04 matching specialization,
PERF-05 WFO reuse, and later runtime capabilities remain separately planned
work, not hidden requirements for this phase.

### Phase PERF-04 - Native Matching, Layout, And Contract Specialization

**Status: IMPLEMENTED_VERIFIED (2026-09-06).**
**Goal:** remove measured native matching/account/kernel work while preserving
all declared priorities, transactions and unsupported-domain behavior.
**Proposal owners:** AP-05 and AP-06; consumes AP-04.
**Prerequisite:** PERF-01/02 gates; use PERF-03 workloads where applicable.

**Read first:** [6: PERF-04 detailed guide](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#6-perf-04--native-matching-targetportfolio-kernels-và-contract-specialization),
[6.5: domain tests before speed](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#65-pf-045--domain-tests-trước-throughput) and
[11.2: non-negotiable hard gates](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#112-hard-gates-không-được-trade-off).

**Implementation sequence (completed):**

1. PF-04.1, [6.1: existing-index prefilter](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#61-pf-041--broad-phase-filter-dùng-indexes-hiện-có): profile examined,
   eligible and active orders plus maintenance cost. Use existing arena,
   symbol/expiry/parent/OCO indexes as a conservative superset with no false
   negatives. Keep contiguous scan for small/high-maintenance sets when better.
   Reestablish exact matching priority and shared-liquidity consumption after
   filtering; process same-phase child activation, stop-limit continuation,
   OCO cancellation and newly eligible orders, not only a start-of-bar list.
2. PF-04.2, [6.2: hot/cold order layout](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#62-pf-042--hotcold-order-layout): keep frequently read
   numeric handles/types/sides/activation/remaining quantities/effective prices
   and lifecycle flags hot; keep strings/tags/provenance/history cold. Maintain
   one mutable order authority and generation-safe links, with full audit
   reconstruction. Measure cancel/amend-heavy index maintenance as well as fills.
3. PF-04.3, [6.3: prepare-time specialization](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#63-pf-043--specialization-một-lần-ở-prepare): select a small
   measured set of existing loop shapes for linear target score, static orders,
   reactive compact, shared portfolio rebalance and bounded package audit.
   Hoist only stable mapping/branches/validations/metric requirements. Dynamic
   equity sizing, admission, marks, funding/fee/tradability and collateral remain
   at their correct phases. Share accounting primitives rather than cloning
   formulas into five new engines.
4. PF-04.4, [6.4: target/portfolio/package semantics](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#64-pf-044--targetportfoliopackage-correctness-specific-checks): compare
   direct target fills/accounts without inventing order-lifecycle parity.
   Preserve portfolio sizing snapshot, explicit priority and supported
   sequential/reduce-first/pro-rata/all-or-none policies. Replace transactional
   state copies only where a measured delta/rollback preserves account, fees,
   reservations and synthetic liquidity. Hedge against actual fills after lot
   rounding; distinguish missing legs, partial quantities and recorded dust.
5. PF-04.5, [6.5: differential and mutation tests](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#65-pf-045--domain-tests-trước-throughput): compare indexed
   versus full-scan execution with gaps, equality, competing orders, expiry,
   partial liquidity, parent/stop activation and deterministic cancel/amend/OCO
   races. Deliberately missing a candidate or changing priority must fail tests.
   Include scale-in/reduce/reversal, costs, funding timestamps, post-cost margin,
   liquidation, frozen/stale symbols and unsupported-shape rejection.

**Current code anchors:** existing matcher/arena/index modules below
`rust/crates/quantbt-engine/src/`, `session.rs`,
`rust/crates/quantbt-execution/src/{target,package,intrabar}.rs`,
`rust/crates/quantbt-package/src/v2.rs` and corresponding native adapters.
PERF-01 records exact index functions; do not add a parallel order engine.

**Tests and exit gate:** [6.6: PERF-04 gates](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#66-gates-và-output).
AC-15, AC-18 through AC-23 and AC-40 lock availability, candidate completeness,
order priority, shared liquidity, package rollback, actual-fill hedging,
portfolio permutation preconditions and direct-target equivalence.
Measure B-06/B-08/B-09, including small shapes, index churn, examined orders,
branch/instruction/cache counters where available and binary size. Every enabled
fast shape requires independent financial parity and a public performance
decision. Unsupported requests still fail or retain their declared approximation.

**Deliverables/docs:** specialization/threshold decision registry, source/index
map, mutation/differential corpus and per-shape report; update native capability,
portfolio/package/target usage and rollback docs.

**Technical debt/rollback:** no hidden priority change, false-negative filter,
account-cache stale state, incomplete transaction rollback or duplicated
authority at exit. Retain the baseline scan/generic certified loop and
compatible schemas wherever measured specialization is not beneficial.

**Implementation record (PERF-04):**

1. **PF-04.1 / PF-04.2:** `FullSession` now retains matching and lifecycle
   candidate scratch instead of allocating a candidate vector per bar/operation.
   `LifecycleIndexes` appends its exact active/live/expiry/parent/OCO members
   into that scratch in existing stable-sequence order. Same-phase child orders
   append to the current continuation queue exactly as before. The new
   `validate_complete(...)` debug/test oracle compares the index against a full
   arena traversal and rejects a missing candidate or priority mutation.
   `ExternalOrderAliases` provides one bidirectional live alias authority:
   replacement chains retain last-writer-wins public behavior, while terminal
   cleanup is proportional to aliases owned by the released order.
2. **PF-04.3:** the specialization registry
   [`perf_04_specialization_registry_v1.json`](../benchmarks/native_event/registries/perf_04_specialization_registry_v1.json)
   records the existing certified shapes: direct target, static command tape,
   reactive compact, shared-account portfolio, and bounded package. It states
   precisely which prepare-time values may be hoisted and which account/market
   values remain dynamic. No duplicate accounting formula or second order arena
   was introduced.
3. **PF-04.4 / PF-04.5:** the new lifecycle corpus verifies public Python/Rust
   parity for high-churn place/amend/replace/cancel-all, score/audit parity,
   scratch release/reset, and zero residual aliases. Existing independent Phase
   51/54A.5, 66, 67, and 68 corpora retain next-open/gap/stop-limit, direct
   target, shared-account priority/rollback, actual-fill hedge, funding,
   liquidation, package atomicity, and fail-closed unsupported-domain evidence.

**Measured evidence:**
[`benchmark_perf04_native_matching.py`](../benchmarks/native_event/benchmark_perf04_native_matching.py)
ran the prepared one-symbol 2,000-bar lifecycle fixture with nine score repeats
after an audit-parity warmup. The 64-live-order churn case processed `96,307`
commands in about `48.3 ms` (`1.99M commands/s`); the one-order control
processed `1,996` commands in about `1.01 ms` (`1.97M commands/s`). Both had exact
score/audit terminal account parity, zero live aliases after cancel-all, and
zero timed RSS tail spread. This is scoped matcher evidence only, not a public
endpoint, WFO, generic grid, L2, or venue-native speed claim.

**Exit disposition:** AP-05 and AP-06 plus AC-18 through AC-23 and AC-40/41
are `IMPLEMENTED_VERIFIED` for their declared static lifecycle/direct
target/shared-account/bounded-package contracts. The documented generic
lifecycle matcher and compatible output schema remain the rollback route.
L2/order-book depth, queue priority, venue-native matching, cross-margin, and
new order-domain semantics remain outside PERF-04 rather than hidden debt.

### Phase PERF-05 - WFO Evaluation Reuse, Streaming Analysis, And Locality

**Status: IMPLEMENTED_VERIFIED.**
**Goal:** avoid redundant economic evaluations while preserving all five modes,
optimizer interaction, chronological accounts and full trial identity.
**Proposal owners:** AP-07, AP-08 and AP-09.
**Prerequisite:** PERF-03/04 runtime gates and PERF-01 audit/identity contracts.

**Read first:** [7: PERF-05 detailed guide](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#7-perf-05--wfo-evaluation-reuse-streaming-analysis-và-locality-runtime),
[8.2: research identities](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#82-pf-062--manifests-bất-biến-và-record-identities) and
[13: public endpoint integration](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#13-đường-chạy-tích-hợp-tối-thiểu-để-tránh-helper-only).

**Implementation sequence (implemented; detailed source guide remains normative):**

1. PF-05.1, [7.1: five-mode evaluation/retention matrix](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#71-pf-051--chốt-mode-by-mode-evaluationretention-matrix): map
   actual `mode_1_decay`, `mode_2_sbb`, `mode_3_flat_minima`,
   `mode_4_is_only_robust`, `mode_5_full_robust`, public schedules and
   supported reactive combinations from source. Retain decay components,
   bootstrap paths/replicates, parameter neighborhoods, IS/subperiod robustness
   and full-sample components actually used. Preserve historical proxy versus
   execution-account semantics and unsupported mode/schedule combinations.
   Custom objectives keep declared inputs/Python authority; no opaque-objective
   introspection or substitution with terminal Sharpe.
2. PF-05.2, [7.2: execution-analysis graph](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#72-pf-052--executionanalysis-artifact-graph): separate strategy
   input/intent, execution, analysis, objective, selection, deployment and
   selected replay. Version `run_id/trial_id/candidate_id/execution_id/
   execution_attempt_id/analysis_id/selection_id/deployment_id` relationships.
   Duplicate params still produce separate trials. Reuse report-only analysis
   only when it has no strategy, pruning or execution-termination feedback.
3. PF-05.3, [7.3: semantic cache and authorization](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#73-pf-053--semantic-cache-retention-và-authorization): key by
   semantic engine/numeric build, market/calendar/instruments, initial
   account/orders/reservations/funding state, strategy implementation/config/
   state/intent, clock/fold/warmup/cutoff/account policy, execution/cost/risk,
   RNG algorithm/version/seed/scenario/replicate and completed horizon/prefix.
   Validate actual immutability, data-role/cutoff permission, retention coverage,
   deterministic isolation and complete/prefix status. Do not cache transient
   resource/IO failures, skip promised callbacks/side effects, share independent
   stochastic replications or reuse across unproven semantic builds.
4. PF-05.4, [7.4: pruning and optimizer schedule](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#74-pf-054--pruning-và-optimizer-semantics-không-bị-cache-phá): retain certified
   ask-one -> report/check/prune -> tell-one behavior. On eligible cache hits,
   replay intermediate observations to the current pruner, never its historical
   decision; otherwise bypass cache. A complete cached score cannot replace a
   pruned prefix. Key or disable caching for constraints/objectives affecting
   termination. Preserve throughput-batch schedule IDs, batch/ask/tell order
   separately from sequential parity; never let finish order drive the sampler.
5. PF-05.5, [7.5: bounded public pipeline and locality](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#75-pf-055--public-lifetime-bounded-pipeline-và-locality): keep
   prepared market/runtime/session lifetime across the existing public WFO
   request; count pool creation, market ingestion, distinct intent copies,
   resets and selected reruns. Allow controlled distinct-tape ingestion while
   removing repeated fold/scenario copies where ownership permits. Use bounded
   typed queues and one coordinated memory/CPU budget for caches, leases,
   worker scratch, audit and actual concurrent/nested Python/Rust/BLAS work.
   Reuse the pool, sweep candidate/time tiles and task grain for independent
   workloads, preserve each candidate's temporal order, and never pre-sample
   future adaptive sequential trials or parallelize carried folds as fresh.
6. PF-05.6, [7.6: streaming statistical reducers](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#76-pf-056--streaming-statistical-reducers): retain a needed
   path once and consume deterministic resample descriptors/indices with
   worker-local scratch. Avoid replicate-by-bar-by-candidate tensors when
   replicate statistics suffice. Pin bootstrap blocks/wrap, RNG indices,
   formula/ddof/NaN/horizon/quantile/reduction order and replicate ID order.
   Preserve all-candidate robustness when required. Keep GARCH/model fitting
   in research, and never combine reset-flat summaries into carried equity.
7. PF-05.7, [7.7: reactive WFO and replay](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#77-pf-057--reactive-wfo-và-deterministic-replay): factory/reset/snapshot
   Python state under the certified contract and verify causal feature cutoff.
   A captured command tape under changed fills/costs is counterfactual execution,
   not a new reactive strategy run. Carry wallet/positions/orders/parents/OCO/
   reservations/funding/RNG/strategy state chronologically when requested;
   preserve current unsupported policies instead of adding implicit continuity.
   Label selected reconstructed audit separately from original retained data.

**Current code anchors:** `src/quantbt/walkforward.py`,
`backends/{native_wfo_public,native_wfo_target,native_prepared_evaluation,
reactive_wfo,reactive_wfo_batch_selection,reactive_wfo_workers}.py`,
`core/wfo_contracts.py`, `strategies/{wfo_prepared,reactive_wfo}.py`,
`rust/native_event/src/prepared_evaluation.rs`,
`rust/crates/quantbt-batch/src/target_wfo.rs`. Python relative anchors are
under `src/quantbt/`; reuse existing selectors, workers and metadata adapters.

**Tests and exit gate:** [7.8: PERF-05 gates](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#78-gates-và-output).
AC-03, AC-17, AC-24 through AC-34 cover fixed candidates in every supported
mode/schedule, cache on/off, fresh/reuse, worker/chunk permutations, actual
intermediate reports/pruning/tell order, duplicate records, economic-key changes,
independent RNG replications, future/global cache rejection, prefix/carry
isolation, fixed bootstrap indices and all-candidate selection.
Compare full public studies and final params/positions/accounts under the same
method. B-07 through B-11 and B-13 separate unique executions, avoided visits,
lookup/store cost, allocation/copy/reset cost, queue/topology, public latency
and peak/steady memory. Every attempted trial remains auditable.

**Deliverables/docs:** mode/schedule/retention matrix, semantic DAG/cache
eligibility and invalidation contract, bounded pipeline/reducer corpus,
topology/shape decisions and WFO compatibility report. Update WFO methodology,
causal schedule, prepared runtime and endpoint guides with unchanged usage.

**Technical debt/rollback:** no leakage, sampling/pruning drift, hidden loss of
landscape points/statuses, invalid cached completeness or broken final account
join at exit. Disable cache or restore baseline reducers/layout on the same
schedule while preserving research IDs/records. PERF-06 supplies the qualified
writer against the schema already locked in PERF-01; PERF-07 tests the combined
runtime/writer. Prefix checkpoint reuse is not introduced here.

**Implementation record (PERF-05):**

1. Added `core/wfo_evaluation.py` with a bounded, run-local terminal-metric
   cache and versioned `run_id`, `trial_id`, `candidate_id`, `execution_id`,
   `execution_attempt_id`, `analysis_id`, `selection_id`, and `deployment_id`.
   The key commits prepared data/config/template signatures, engine/numeric
   contract, strategy fingerprint/params/intent, fold window/account policy,
   actual study ID/seed, trial identity, and completed horizon. A scorer must
   explicitly declare deterministic terminal semantics and whether diagnostic
   score context affects metrics; otherwise reuse is fail-closed.
2. Integrated the runtime into the existing `WalkForwardEngine` public path,
   without adding a second scheduler or worker pool. Adaptive Optuna reads are
   always bypassed and store only completed metric rows; only a later exact
   candidate-analysis pass may hit. Failed/partial rows never enter the cache.
   Per-fold studies receive their own study identity. Runtime teardown clears
   cache/index digests on both success and exception paths.
3. Kept the existing five-mode authorities: Modes 1/3 and eligible global Mode
   4 may reuse exact prepared-native score rows; Mode 2 keeps the proxy/SBB
   path and its existing one-path-plus-replicate-vector retention; Mode 5 and
   strict Mode 4 `per_fold_causal` disable an unusable cache rather than retain
   dead entries. Reactive WFO R1/R2/R3/R3B remains its own strategy-state and
   replay contract; only its per-fold study provenance is aligned.
4. Added public controls `wfo_execution_reuse={off,auto,require}`,
   `wfo_execution_reuse_max_entries`, and `wfo_execution_reuse_trace_limit`.
   Existing callers remain compatible: `auto` is inert unless the certified
   prepared-native endpoint scorer is active, and `off` restores the previous
   score path exactly.

**Evidence and exit gate:**

- `tests/test_perf_05_wfo_evaluation_reuse.py` covers global Modes 1/3/4/5,
  Mode 2 proxy preservation, Mode 1 per-fold decay study isolation, Mode 4
  causal non-reuse, data/config/seed/study key separation, duplicate attempts,
  deterministic-contract rejection, real prepared-native endpoint parity, and
  cache release.
- Targeted WFO/reactive suite: `87 passed, 3 skipped` on the local native
  extension environment.
- `benchmark_perf05_wfo_evaluation_reuse.py --bars 2048 --trials 16 --repeats 15`
  passed exact public parity across all five modes. In the alternating Mode 1
  high-hit lane, 32 exact post-study hits avoided `11,680` terminal-score bars,
  reduced median scorer time from `143.177 ms` to `131.516 ms` (`8.14%`), and
  full facade time from `410.082 ms` to `399.369 ms` (`2.61%`); RSS tail spread
  was `0.000 MiB`. The bounded
  capacity-one lane is intentionally reported separately and is not presented
  as a speed win.

**Exit disposition:** AP-07/AP-08/AP-09 are `IMPLEMENTED_VERIFIED` for the
declared prepared-native, terminal-metric, run-local scope. Selection formulas,
OOS roles, Optuna ordering, strategy lifecycle, final stitched account, and
reactive state authority are unchanged. There is no unresolved PERF-05
correctness or retention debt. PERF-06 durable columnar research writing and
PERF-07 combined qualification remain separate planned scopes, not deferred
parts of this cache contract.

### Phase PERF-06 - Columnar Research Audit, Retention, And Compatibility

**Status: PLANNED; awaiting individual implementation approval.**
**Goal:** reduce object/serialization and retained-memory cost while preserving
requested financial outputs and complete research interpretation.
**Proposal owner:** AP-10; integrates AP-01/AP-07/AP-11.
**Prerequisite:** PERF-01 schemas and PERF-05 evaluation/selection identities;
writer work may overlap only when separately approved.

**Read first:** [8: PERF-06 detailed guide](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#8-perf-06--research-auditresult-tốc-độ-cao-và-không-mất-dữ-liệu),
[2.4: numeric/schema exactness](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#24-exactness-và-floating-point-policy) and
[11.2: audit completeness is a hard gate](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#112-hard-gates-không-được-trade-off).

**Implementation sequence (all pending):**

1. PF-06.1, [8.1: independent retention axes](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#81-pf-061--hai-chiều-retention-độc-lập): resolve financial
   `score/compact/audit` separately from research
   `full_trial_ledger/selected_only/none` using compatible existing surfaces.
   Keep legacy defaults. The nominated research WFO retains full trial history
   even with scalar financial scoring. Full trial ledger need not mean every
   candidate fill, but must retain actual params, attempts/folds/scenarios,
   objective inputs, statuses and selection provenance. Full financial audit
   requests are fulfilled or explicitly rejected by resource contract.
2. PF-06.2, [8.2: immutable manifests and records](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#82-pf-062--manifests-bất-biến-và-record-identities): store run,
   search-space, instrument and contracts once with stable references. Retain
   Run, SearchSpace, Trial, Evaluation/Fold/Scenario, Analysis, Selection,
   Deployment, Replay and Performance records with the guide's full field set.
   Include declared/observed distributions, bounds/steps/log/category order,
   conditional inactive reasons, fixed overrides, actual params, cutoff/purge/
   embargo/warmup, initial state, attempts/reuse/prefix/errors, constraints/
   tie-break/deployment intervals and original/reconstructed provenance.
   Dynamic unknown branches use `space_completeness=observed_only`; never
   invent a declared search space or use arbitrary repr as semantic identity.
3. PF-06.3, [8.3: typed chunks and ownership](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#83-pf-063--typed-columnar-chunks): append typed SoA
   rows/chunks in workers; materialize pandas/legacy output once or lazily under
   its API contract. Prefer the existing substrate; Arrow/Parquet/database are
   not required additions. Transfer chunk ownership before worker recycling.
   Logical IDs/order do not follow worker completion order. Preserve numeric,
   timestamp and category precision with no implicit downcast/quantization.
4. PF-06.4, [8.4: bounded writer and completion](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#84-pf-064--bounded-writer-và-trạng-thái-hoàn-tất): reuse or extend
   the current sink with bounded queues, backpressure, controlled spill or
   explicit budget failure. Distinguish memory-complete, process flush/close and
   tested crash-durable guarantees. Record financial and audit status separately
   and aggregate truthfully; no certified success with missing requested audit.
   Preserve canceled prefix/missing range/reason and make chunk retries
   idempotent without retrying an uncertain optimizer tell.
5. PF-06.5, [8.5: digest and legacy round-trip](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#85-pf-065--hashprovenance-và-schema-round-trip): hash immutable
   manifests once, preserve ordered financial traces, and version changed
   physical codecs/digests. Compare logical records through compatible adapters
   instead of promising unchanged JSON/binary hashes. A digest is not the
   original audit payload; selected regenerated data records
   `reconstructed=true`. Preserve row counts/joins/dtypes/timezones/nulls/
   statuses/params/objectives/selection/deployment on legacy exports; distinguish
   observed parameter points from visual interpolation.

**Current code anchors:** `src/quantbt/core/native_result_v2.py`,
`core/runtime_governance.py`, `walkforward.py`, `reporting/`, existing WFO
result/metadata adapters and Rust typed output/reducer modules. Verify current
sink and serializer ownership in PERF-01 before creating focused additions.

**Tests and exit gate:** [8.6: PERF-06 gates](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#86-gates-và-output).
AC-24 and AC-35 through AC-39 require duplicate-trial identity, conditional
search-space fidelity, slow/full queues, disk-full, worker death, serialization/
schema faults, cancel-mid-flush and duplicate chunk retry. Round-trip all
promised fields/cardinalities/statuses and recompute objectives from their
recorded components; selected deployment must join the right candidate.
B-10/B-11/B-12 measure identical full research retention, bytes/allocations,
encode/flush/adapt latency, queue pressure and retained/peak memory. Financial
success plus missing required research/financial audit is a failed aggregate
contract, regardless of score parity.

**Deliverables/docs:** versioned research records, typed writer/legacy adapters,
ownership/durability ADR, compatibility and fault corpus, and measured retention
report. Document how users obtain metrics, plots, trial tables, landscape data,
selection provenance and original versus reconstructed audit.

**Technical debt/rollback:** no silent row/status/precision loss, unsafe chunk
reuse, unbounded queue or unsupported durability promise at exit. Restore the
existing serializer/sink with the same requested retention; do not disable
audit as rollback. Cross-domain combined qualification belongs to PERF-07.

### Phase PERF-07 - Combined Qualification, Build Tuning, And Phase 78 Handoff

**Status: PLANNED; awaiting individual implementation approval.**
**Goal:** qualify the combined implementation on real public routes and exact
candidate wheels, and produce a validated scoped handoff to Phase 78.
**Proposal owner:** AP-12 and the final dispositions of AP-01 through AP-11.
**Prerequisite:** PERF-01 through PERF-06 closed with valid evidence and no
unresolved mandatory correctness, public integration or audit requirement.

**Read first:** [9: PERF-07 detailed guide](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#9-perf-07--cross-domain-qualification-build-tuning-và-handoff-về-phase-78),
[9.6: PerformanceClosureManifest](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#96-pf-076--release-handoff-không-trộn-với-publish),
[11: paired benchmarks and hard gates](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#11-benchmark-portfolio-và-gates-theo-nhóm),
[14: out-of-critical-path research](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#14-những-hướng-mạnh-nhưng-giữ-ngoài-critical-path),
[16: intended seven-phase outcomes](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#16-kết-quả-đích-sau-bảy-phase).

**Implementation sequence (all pending):**

1. PF-07.1, [9.1: combined and ablation qualification](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#91-pf-071--combined-path-và-ablation-qualification): compare
   baseline, computation plan, reset/derived reuse, reactive boundary, native
   kernels, WFO cache/reducers/locality, audit representation and combined/chosen
   build. Test shared ownership/numeric interactions, not an unnecessary full
   Cartesian sweep. Public timings are the gate; overlapping gains are not
   multiplied. Apply the paired/noise/memory budgets locked in PERF-01.
2. PF-07.2, [9.2: cross-domain regression](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#92-pf-072--cross-domain-regression): exercise every
   advertised affected market/calendar/account/funding/order/target/portfolio/
   package/intrabar surface and existing options containment. Shared primitives
   need affected-domain tests even when those endpoints were not hotspots.
   Unsupported spot-carry, inverse/quanto, cross-venue and option models retain
   correct rejection/approximation labels instead of nearest-kernel fallback.
3. PF-07.3, [9.3: controlled PGO/build experiment](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#93-pf-073--pgobuild-experiment-có-kiểm-soát): only after
   dataflow stabilizes, pin instrumented training, profile merge, profile hash,
   toolchain/flags and chosen build. Hold out short/long, score/audit, Python-heavy,
   many-order, target and portfolio/package workloads. Retain non-PGO as
   `NOT_BENEFICIAL` if public/cold/binary-size gates lose. Public wheels keep
   their certified portable CPU baseline; no unqualified host-native flags,
   fast-math, panic/safety change or disabled PyO3 reference-pool safeguards.
4. PF-07.4, [9.4: resource and fault soak](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#94-pf-074--resource-cancellation-và-ownership-soak): combine heterogeneous
   long WFO, cache pressure, retained results and slow sinks. Measure governed
   peak and steady memory after contractual releases. Cancel at prepare,
   callback, active native work, queue wait, reducer and audit flush; verify
   bounded response, committed financial prefix, worker join/poison recovery
   and no orphan/deadlock/invalid alias. Test approved worker topologies with
   fixed deterministic candidate IDs; time-budgeted async sampling remains
   separately labelled and cannot claim exact sequential history.
5. PF-07.5, [9.5: installed candidate and eligibility](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#95-pf-075--installed-candidate-và-route-enablement): build a
   matched core/native pair from the pinned candidate and install in clean
   pip/Poetry consumers outside the checkout/mirror. Prove public endpoint,
   analysis/selection and output behavior with actual import/module origins
   and extension versions. Qualify the approved platform/CPython/worker cells.
   Record endpoint, intent/account/clock/execution, retention, reactive/WFO
   protocol and platform -> explicit/auto-eligible/safe-baseline/rejected.
   Eligibility is a recommendation to Phase 78; do not blanket-enable routes.
6. PF-07.6, [9.6: scoped release handoff](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#96-pf-076--release-handoff-không-trộn-với-publish): generate and validate
   `quantbt.performance_closure.v1` with source/baseline/build identities,
   immutable evidence references for all seven phases, AP/PF/AC dispositions,
   scoped route matrix, empty required correctness blockers, audit round-trip,
   performance uncertainty and contract-compatible rollback. Reject placeholder
   values, missing artifacts, stale source/build identity and unsupported scope.
   State explicit research decisions for prefix checkpoints, inert blocks and
   free-threaded/compiled/GPU/new-domain paths; they remain outside this group.

**Current code anchors:** existing measurement/governance tooling, product
registry/capability negotiation, `tools/{verify_wheels,certify_native_release}.py`,
Cargo profiles and native CI/consumer workflows. Reuse existing release
infrastructure; the phase produces local/CI candidate evidence, not uploads.

**Tests and exit gate:** [9.7: PERF-07 gates](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#97-gates-và-output).
Close AC-01 through AC-44 mapping and all required B-01 through B-14 decisions.
AC-32 and AC-40 through AC-44 additionally verify combined topology, direct-target
contract equivalence, unsupported containment, observers/PGO on/off, clean wheel
imports and source/build invalidation. Run full deterministic and independent
affected-domain regression, Rust fmt/clippy/unit/differential checks, mirror,
generated contract/API/baseline, architecture, docs, secret and benchmark gates.
Use actual wheel behavior with no advertised native capability silently skipped.
Uncertainty is reported; no unmatched speedup, requested audit loss, finance
mismatch, unsafe lifetime or unresolved mandatory case can pass.

**Deliverables/docs:** combined/ablation report, full oracle/public/audit/resource
matrix, candidate core/native/platform evidence, PGO decision, exact eligibility
table, rollback package/contract reproduction and validated closure manifest.
Refresh README with comparable seconds/ms and appropriate work units; explain
execution versus Python decision authority and cache avoidance separately.

**Technical debt/rollback:** `READY_FOR_PHASE78` applies only to the proven
capability set with all mandatory evidence resolved. A missing MRS/platform/
audit/oracle requirement remains explicitly unqualified until its approved
scope decision, not a fabricated pass. Keep compatible baseline kernels and
package rollback. Do not publish, promote every endpoint, remove the oracle,
or silently bypass original A4/A5 observation/cleanup conditions.

### PERF Test Matrix And Coverage Tracking

The full cases and assertions in [10: AC-01 through AC-44](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#10-adversarial-test-matrix-bắt-buộc)
and workload definitions in [11.1: B-01 through B-14](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#111-benchmark-fixtures)
must be mapped to concrete tests/fixtures during PERF-01 and reconciled at
PERF-07. This compact index does not reduce those requirements.

| AC IDs | Required invariant | Owning phase(s) |
|---|---|---|
| AC-01, AC-02 | Single observation updates; conservative custom-metric inputs | PERF-01 |
| AC-03, AC-04 | Pruning checkpoints; immutable input/alias ownership | PERF-01/02/05 as applicable |
| AC-05, AC-06, AC-07, AC-08 | Huge/tiny reset, fault predecessors, retained results, stale/wrapped handles | PERF-02 |
| AC-09, AC-10 | Mark/reservation/fee/funding derived-state invalidation | PERF-02 |
| AC-11, AC-12, AC-13, AC-14 | Callback exceptions versus trading rejects, re-entry/capacity, silent state/RNG | PERF-03 |
| AC-15, AC-16, AC-17 | Availability/wake ordering and candidate failure isolation | PERF-03/04/05 as applicable |
| AC-18, AC-19, AC-20 | Conservative prefilter, exact priority, cancel/amend/OCO maintenance | PERF-04 |
| AC-21, AC-22, AC-23 | Atomic rollback/liquidity, actual partial fills/hedge dust, portfolio priority | PERF-04 |
| AC-24 | Duplicate trials and execution-reuse identity | PERF-05/06 |
| AC-25, AC-26, AC-27, AC-28, AC-29 | Cache economics/feedback, current pruning, prefix status, independent replicate identity | PERF-05 |
| AC-30, AC-31, AC-32 | Causal authorization, reset/carry separation, deterministic topology | PERF-05/07 |
| AC-33, AC-34 | Fixed resampling/reducers and required all-candidate analysis | PERF-05 |
| AC-35, AC-36, AC-37, AC-38, AC-39 | Conditional space, writer faults/retries, legacy/digest compatibility | PERF-06 |
| AC-40, AC-41 | Direct-target equivalence and unsupported-domain containment | PERF-04/07 |
| AC-42, AC-43, AC-44 | Observer/build equivalence, clean wheel import, changed-candidate invalidation | PERF-01/07/78 |

| Workload IDs | Required measurement | Primary phase(s) |
|---|---|---|
| B-01 | No-trade short/long fixed preparation/observer/result overhead | PERF-01 |
| B-02, B-03, B-04, B-05 | Numeric getters, many commands, Python-heavy and sparse behavior | PERF-03 |
| B-06 | High-churn resting/cancel/amend/grid with audit | PERF-03/04 |
| B-07 | Heterogeneous fresh/reused trials and retained high-watermark | PERF-02/05 |
| B-08, B-09 | Target shape sweep; shared portfolio/package priority and cache | PERF-04/05 |
| B-10, B-11 | Every WFO mode; zero/mixed/high cache hits with actual work | PERF-05/06 |
| B-12, B-13 | Same full research retention with slow sink; long WFO failure/cancel | PERF-05/06/07 |
| B-14 | Held-out PGO workload and cold/binary/error behavior | PERF-07 |

Every released family also needs the real public-input-to-export-to-installed-
wheel integration chain in [13: minimum public integration](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#13-đường-chạy-tích-hợp-tối-thiểu-để-tránh-helper-only), with
negative requests for unsupported account/timing, missing metric inputs,
malformed commands, stale buffers, protocol mismatch and exceeded budgets.
Metamorphic tests must state preconditions: fill splitting, permutations and
rescaling are not unconditional invariants with per-fill fees, rounding,
priority-dependent liquidity or phase-sensitive margin.

### PERF Completion Record And Handoff Control

Use [12: work-package evidence](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#12-tổ-chức-prwork-packages) and
[15: integration checklist](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#15-checklist-merge-vào-implementmd-và-tiếp-tục-phase-78) together with the existing completion
record below Phase 78. Each phase must append real outcomes as they occur:

```text
Phase and approval reference:
Status: PLANNED | IN_PROGRESS | BLOCKED | COMPLETE
AP/PF requirement dispositions and actual source/public consumer mapping:
AC test IDs and B workload IDs, including unqualified cases:
Pinned baseline/candidate/source/native/wheel identity:
Economic fingerprint; performance fingerprint; schema/numeric/RNG contract:
Public route before/after, including decision/execution/analysis authorities:
Exact commands and pass/fail/skip reasons; independent oracle and field parity:
Selection/pruning/checkpoint/tell order; state carry and cache authorization:
Retained research/financial outputs, compatibility and durability evidence:
Paired p50/p95/sample counts/noise, actual work and cache avoidance:
Cold/warm RSS/PSS, ownership/copy/reset/topology and resource/fault outcomes:
Docs/examples and implementation commit:
Open mandatory blockers; measured NOT_BENEFICIAL decisions:
Approved deferrals and scoped impact (never counted as a passing requirement):
Named downstream owner; rollback and whether the next phase may be approved:
```

Planning alone does not fill any of those evidence fields. `PERF-07` issues the
validated closure manifest only after the scoped mandatory requirements pass.
Source/build changes invalidate affected qualification even if package version
strings remain equal. Phase 78 must verify that manifest and run affected
integration/distribution gates against the final artifacts it will release.

### Phase 78 - Public Rust-Primary Promotion And Release Certification

**Status: planned; not started.**

**Goal:** close the actual guide definition of done with truthful public routing,
current installed artifacts, supported-user workflows and a safe release handoff.

**Prerequisite:** passing completion records for Phase 77.1, 77.2 and 77.3,
including the public five-mode matrix, transition `%_equity` integration and
reactive/resource closure. Historical Phase 77 completion alone does not admit
this phase. Public promotion is separate from implementation and still needs
this phase's individual approval and current installed-wheel evidence.

**Additional prerequisite (APC-1.0):** PERF-01 through PERF-07 must supply a
validated `PerformanceClosureManifest` with status `READY_FOR_PHASE78` for
the proposed capability set, matching the current source/build candidate.
Original prerequisites remain required. Read the
[seven-phase handoff contract](#perf-completion-record-and-handoff-control) and
[guide 9.6](QUANTBT_V1_1_PRE_PHASE78_PERFORMANCE_CLOSURE_7_PHASES_VI.md#96-pf-076--release-handoff-không-trộn-với-publish).
P78-00 is the admission check for that manifest: validate actual source/build,
baseline, core/native identities, all required phase/requirement evidence,
audit compatibility and rollback references. Missing/placeholder/stale evidence
blocks admission. Requalify impacted gates after source/build changes; matching
version strings alone do not carry certification across artifacts. PERF-07
candidate-wheel proof supplements, rather than replaces, P78-04/P78-05 tests
of the exact final artifacts intended for distribution.

**Read first:**
- [7: authority/promotion ladder](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#7-promotion-maturity-ladder).
- [38.1-38.8: reliability and resource governance](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#381-runtime-budget).
- [40.2-40.9: wheels, registry, shadow and cleanup](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#402-protocol-compatibility).
- [64-66: API, backend semantics and removal policy](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#64-public-api-compatibility).
- [90: productization checklist](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#90-productization-checklist).
- [91: full definition of done](QUANTBT_RUST_PRIMARY_V1_1_UPGRADE_GUIDE_VI.md#91-v11-is-complete-when).

**Implementation sequence:**

1. P78-01: reconcile the Phase 72 matrix with actual routes after 73-77,
   77.1-77.3 and the qualified PERF-01 through PERF-07 changes. For
   each endpoint/workload/profile/timing/platform, record state, control-flow,
   data, metric and result authority, native entry/callback counts, and exact
   supported/unsupported policy. No generic `Rust supported` stamp from one case.
2. P78-02: wire promotion only for exact capabilities whose prior implementation
   and independent tests already passed. Preserve explicit Python/oracle paths,
   fail-closed explicit Rust, and truthful `auto` selection/fallback reasons.
   Never change execution semantics to fit an available native route.
3. P78-03: verify cancellation, memory budgets, worker teardown, poisoned-state
   recovery, cache lifetime and service concurrency across public WFO/reactive
   and specialized routes. Limits must be enforced during native work, not only
   before entry or recorded in result metadata.
4. P78-04: build a fresh matching core/native wheel pair from the exact approved
   release candidate. Install outside source/mirror paths in clean consumers;
   exercise actual endpoints, optimizer selection, result/report access and
   unsupported-capability behavior. Checking `api_version()` alone is inadequate.
5. P78-05: certify approved published platforms/CPython versions with behavioral
   matrix jobs and evidence per cell. Keep additional architectures as explicit
   certification targets until they really pass. Do not demand unrelated new
   platforms to close the approved matrix, or advertise untested wheels.
6. P78-06: shadow the selected Rust paths against the independent oracle using
   saved synthetic/public-data workloads, plus approved local alpha fixtures
   without publishing private strategy source or data. Record fallback/mismatch
   rate, RSS plateau, timeout/cancel behavior and reproducible mismatch bundles.
7. P78-07: assess A4 and A5 separately. Stable observation and removal approval
   cannot be manufactured by a microbenchmark. Keep Phase 78 pending if mandatory
   shadow evidence is unavailable; report implementation-ready versus release-
   certified explicitly instead of declaring full closure.
8. P78-08: eligible production duplicate/mirror removal is a separate gated
   change after exact inventories, consumer migration, package-pin rollback
   proof and user approval. Do not delete Rust build sources, tests, examples
   or independent Python oracle. Existing safe mirrors remain until that gate.
9. P78-09: update README, endpoint/backend guides, WFO mode/schedule methodology,
   native/release installation docs and runnable stable examples. Show matched
   seconds/ms and bars/s with workload/retention/CPU; separate reactive/WFO units.
   Document whether existing notebooks gain native routing automatically or need
   an optional declared protocol; do not force strategy rewrites for old calls.
10. P78-10: prepare PR/version/core-native compatibility matrix and TestPyPI/PyPI
    handoff using existing workflows. Verify published-version immutability;
    choose a new version through user approval. No publish, tag rewrite or
    merge is implicitly authorized by approval to implement this phase.

**Code anchors and proposed deliverables:**
- Product registry/generator and capability negotiation, current native platform
  workflows, `tools/verify_wheels.py`, and `tools/certify_native_release.py`.
- Add `tests/test_phase78_public_release_closure.py`, installed consumer scripts,
  route-scoped evidence manifests and a release/migration checklist.
- Refresh official docs only with the candidate's verified capability and
  benchmark evidence; preserve historical measurements under their own labels.

**Tests and exit gate:**
- Full deterministic regression with exact pass/fail/skip accounting; independent
  oracle/differential suites, Rust fmt/clippy/unit tests, typed ABI negotiation,
  generated-contract drift, mirror, architecture, docs and benchmark validators.
- Native execution must be required, not skipped, in advertised wheel jobs.
  Run pip and Poetry consumer proof outside the repository, static/target,
  all supported WFO mode/schedule pairs, reactive, portfolio/package, intrabar,
  and the existing options containment regression.
- Test public metrics/plots/reports on materialized profiles, empty/short input,
  failure/cancel results, explicit native mismatch, absent wheel and incompatible
  platform. Installation fallback must not masquerade as Rust execution.
- Compare baseline/current fixed candidates and whole public studies under the
  same contracts. Include long-running bounded-RSS and parallel service cases;
  keep private artifacts out of public wheels, sdists, logs and release bundles.
- Every mandatory guide 91 item maps to concrete passing evidence. Unavailable
  platform, shadow cycle, approved cleanup or failed performance gate remains
  visibly pending; no overall percentage may hide a mandatory failed gate.
- Exit requires no unresolved in-scope P0/P1 defect, missing public integration,
  misleading evidence, memory leak or untested advertised native capability.
  Release actions occur only after the user's separate release authorization.

**Rollback and evidence:** include exact previous/new core-native package pins,
contract reproduction examples, promotion kill switch, downgrade verification,
platform matrix, parity bundles, and final list of genuine out-of-scope domains.

### Cross-Phase Certification Matrix

The owner phase must fill concrete case IDs and artifact links before marking
its row passed. Planned filenames below are requirements, not tests already run.

| Requirement | Owner | Required proof |
|---|---|---|
| Honest bars/candidates/folds/scenarios and profile comparator | 72 | Hand-count fixtures; stale/mismatched evidence rejected |
| Typed prepared adapters and no per-execution tape copy | 73 | All admitted workload variants; copy counters and lifetime tests |
| One persistent pool and bounded scratch/cache | 73 | Worker-count parity, cancel/reset/close and long-repeat RSS |
| Ordinary public WFO uses native evaluation | 74 | Actual native entry from existing endpoint, not companion alone |
| Five modes keep objective/selection mathematics | 74 | Fixed matrix plus sequential trial/prune/winner parity |
| Causal versus selection-adjusted schedules stay distinct | 74 | Future mutation and metadata assertions |
| Final positions/account reconstructed across folds correctly | 74 | Chronological join traces, costs, funding and order state |
| Reactive score does not retain unnecessary dense paths | 75 | Allocation/retention checks plus score/audit accounting parity |
| Reactive command/account/strategy state parity | 75 | Four-way replay and every-bar/sparse/block corpus |
| Reactive public WFO and worker/resource isolation | 76 | Process/batch fixed matrix, sampling contract and teardown proof |
| Rust/Numba/Python fair public and kernel comparisons | 77 | Locked-profile paired benchmarks and phase breakdown |
| Shared financial authority across specialized kernels | 77 | Accepted-delta, FillReplay and invariant regression |
| Current public five-mode/schedule baseline including `%_equity` | 77.1 | Matched fixed candidates/full studies, route identity, time/copy/RSS breakdown |
| Transition `%_equity` Rust execution in public scoring and final account | 77.2 | Independent ledger/legacy parity, accepted units, rejection retry and continuous joins |
| Shared target/portfolio fold ownership and columnar scoring | 77.2 | No per-execution immutable tape copies, 1/N-worker parity, bounded candidate retention |
| Mode 2 sampling/reduction preserves historical mathematics | 77.2 | RNG/index/path fingerprints, metric/ranking parity and bounded sampling memory |
| Reactive wake/GIL/buffer optimization and specialized scratch | 77.3 | Decision/execution traces, transactional rollback and matched public speed/RSS |
| Cooperative long-task budgets and immutable report ownership | 77.3 | Mid-execution cancellation, worker recovery and report access without replay |
| Current source/AP inventory and output dependency contract | PERF-01 | AC-01-04/42, public baseline, schema lock and noise-aware budgets |
| Fresh/reused sessions and coherent derived account snapshots | PERF-02 | AC-04-10, retained ownership, fault/reset oracle and bounded memory |
| Reactive getter/writer/projection cost with unchanged decisions | PERF-03 | AC-11-17, four-way corpus, real public boundary/ownership evidence |
| Conservative matching and exact specialized transactions | PERF-04 | AC-15/18-23/40, indexed/reference ordering, rollback and shape decisions |
| WFO cache/reducers preserve optimizer, roles and accounts | PERF-05 | AC-03/17/24-34, five-mode fixed/full-study parity and actual work measurement |
| Full research ledger and financial retention remain independent | PERF-06 | AC-24/35-39, legacy round-trip, writer faults and no requested audit loss |
| Combined public qualification and scoped performance handoff | PERF-07 | Complete AC/B dispositions, exact candidate wheels and valid READY_FOR_PHASE78 manifest |
| Public promotion reflects exact measured capability | 78 | Registry negative tests and authority metadata |
| Current installed core/native artifacts behave correctly | 78 | Behavioral wheel matrix plus pip/Poetry consumer runs |
| A5/shadow/cleanup and final guide completion | 78 | Actual observation evidence, approval and rollback proof |

### Test Cadence And Required Completion Record

Run focused contract/unit/differential tests while each phase is being built.
Rebuild the native extension when Rust or ABI changes; do not benchmark a stale
installed module. Broaden regression at shared-boundary changes, and run the
combined candidate-wheel qualification at PERF-07 and complete release/
installed-wheel matrix at 78. Do not repeat unchanged large
suites for a docs-only edit, but never substitute focused tests for the final
gate or omit a newly affected domain to save time.

For every phase append this record with real evidence:

```text
Status: planned | in_progress | blocked | complete
User approval reference:
Work packages: each pending/in_progress/passed, not one blanket completion flag
Guide sections and contract IDs:
Code/data/wheel identity and environment:
Public routes exercised and authority before/after:
Tests: exact commands, passed/failed/skipped and reason for each exclusion
Parity: fields/tolerance, trace/fingerprint, sampling and fold-account outcomes
Performance: matched baseline/current, phases, median/p95, work counters
Memory: cold peak, warm plateau, retained buffers, pool/process/shared ownership
Docs/examples updated:
Open blockers/debt: none, or explicit failure that prevents phase closure
Named downstream work: phase owner; not a relabeling of failed current scope
Rollback:
Conclusion: what is usable, what is certified, and whether next phase may start
```

The original guide's full completion claim is made only after Phase 78's
mandatory checks pass. Until then, reports must state exact completed phases
and capabilities, not an unweighted completion percentage or a promise that
every possible Python strategy is now fully native.

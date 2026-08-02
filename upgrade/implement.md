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
- The first five-run benchmark evidence (synthetic 2,000 bars) shows Python
  scalar medians of about `1.162s` long-only and `1.856s` long-short; Rust
  scalar medians of about `1.294s` and `2.039s`. Rust remains a correctness
  and explicit experimental backend here; this workload does not claim Rust
  is faster than the Python reactive score facade.
- Audit process RSS stayed bounded under the repeated-run gate after explicit
  collection. Rust and Python retained different allocator/high-water
  profiles, so RSS is reported as evidence, not a universal hardware claim.

Acceptance and possible debt:

- Rust is not promoted or selected by `auto` unless every required gate passes.
- Any RSS failure is reported separately from correctness; it cannot relax
  accounting or lifecycle parity.
- If a real Grid workload exposes a contract gap, freeze the result as a
  reproducible failing fixture and keep Rust explicit until repaired.

Phase 47C completion boundary and remaining debt:

- The Grid integration now has an executable 2,000-bar correctness gate for
  both supported modes, a low-retention Python/Rust score contract, and a
  reproducible process-isolated RSS/runtime benchmark. `native_backend="rust"`
  is explicit and fail-fast; `auto` still resolves to Python.
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

Status: **planned; final phase after Phase 47C.**

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

- Add the one-trial timing breakdown for alpha preparation, strategy
  initialization, engine score, objective overhead, total time, fills, and
  `num_trades`.
- Add the scalar optimizer gate: `scores` increments exactly once, `runs` does
  not increment, `endpoint.result is None`, and evaluator does not retain the
  last result or strategy.
- Add minimal `native_context_requirements` for Grid and derive score
  requirements without disabling fills, active orders, or positions.
- Add optional `collect_diagnostics=True` to the Grid config. Score mode may
  set it false to avoid `_diag_*` allocations, while public/audit defaults
  remain unchanged.
- Make diagnostic alias columns optional in
  `prepare_grid_alpha_frame(...)`; execution columns remain identical.
- Only if profiling proves alpha preparation is dominant, add a bounded
  `PreparedGridAlphaFactory` that reuses immutable OHLC/indicator components,
  has byte/entry limits and `clear()`, and always creates fresh strategy state.
- Update endpoint/Grid docs and the phase evidence report with exact parity,
  performance, RSS, and remaining capability results.

Tests and evidence:

- Re-run all Phase 47A-C parity tests after every optimization patch.
- Verify command tape, fills, accounting, funding, margin, liquidation, and
  report semantics are unchanged between diagnostics enabled/disabled and
  cached/uncached alpha paths.
- Test context requirement combinations, cache bounds/clear, fresh state per
  trial, no result retention, and repeated optimizer score runs.
- Report legacy public objective seconds/trial, prepared scalar seconds/trial,
  alpha/strategy/engine/objective percentages, total wall time, and peak RSS.

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

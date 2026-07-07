# ArbitrageBacktestEngine Design Roadmap

Ngay lap tuc can giu lai note nay de sau nay quay lai implement khong bi
troi mat context. Day la ban thiet ke tong hop cho `ArbitrageBacktestEngine`
trong QuantBT, dua tren cac discussion gan day ve basis trading,
multi-leg/statistical arbitrage, native event-driven backend, Nautilus
validation, va yeu cau "institutional-grade" cua package.

## Muc Tieu

Xay dung mot arbitrage framework chung, khong chi phuc vu basis trading.
Basis giua `BTCUSDT perpetual` va `BTCUSDT quarterly` chi la mot subtype.
Engine moi phai mo rong duoc cho:

- `BasisArbitrageSpec`
- `CalendarSpreadSpec`
- `FundingArbitrageSpec`
- `StatArbPairSpec`
- `IndexBasketArbSpec`
- `TriangularArbSpec`
- `CrossExchangeArbSpec`
- `SpotPerpCashCarrySpec`
- `OptionsVolArbSpec`

Nguyen tac quan trong:

- Arbitrage khong nen duoc model nhu mot multi-symbol portfolio doc lap.
- Arbitrage la mot package trade / multi-leg trade: entry, hedge, sizing,
  execution, fill, funding, margin va exit phai duoc hieu nhu mot don vi logic.
- PortfolioBacktestEngine chi nen dung cho screening / portfolio matrix rough
  research. Truth engine cua arbitrage nen la ArbitrageBacktestEngine hoac
  Basket/EventDriven engine co domain arb adapter.

## Vi Sao MultiSymbolPortfolio Khong Du Cho Arbitrage

`PortfolioBacktestEngine` tra loi cau hoi:

```text
Neu portfolio giu cac exposure nay qua cac symbol thi equity curve ra sao?
```

Arbitrage can tra loi cau hoi khac:

```text
Neu mot package multi-leg vao/ra theo spread signal thi order/fill/account/margin
va carry cua ca package ra sao?
```

Sai lech thuong gap neu dung portfolio matrix cho arbitrage:

- Hai leg bi xem nhu hai position doc lap, khong phai mot package trade.
- Hedge ratio co the bi rebalance moi bar gay price-drift micro-trading.
- Entry/exit khong duoc dam bao dong thoi.
- Khong model legging risk, partial fill, all-or-none reject.
- Funding, borrow, carry, expiry, settlement va roll khong gan voi tung leg.
- Margin offset/cross margin cua hedge package khong ro rang.
- Bao cao PnL khong tach duoc spread PnL, carry PnL, funding PnL, execution PnL.

## Bai Hoc Tu Nautilus

Nautilus khong can mot "arbitrage engine" rieng theo nghia hard-coded. Cach dung
dung la:

- Engine event-driven xu ly data stream, order lifecycle, portfolio, risk,
  margin va reports.
- Strategy/adaptor tu tinh synthetic spread/basis signal.
- Strategy submit order vao cac component instruments.
- Synthetic instrument co the dung lam analytical/trigger instrument, nhung
  execution van phai di qua component legs.
- OMS co the NETTING hoac HEDGING tuy venue/account.
- Account/portfolio/cache/fills/orders la source of truth.

QuantBT nen hoc pattern do:

```text
Market Data -> Synthetic/Spread Builder -> Arb Signal -> Package Target State
            -> Multi-Leg Order Planner -> Execution Backend -> Arb Result
```

Native QuantBT can nhanh va de audit. Nautilus adapter la validation/oracle cho
nhung case event-driven kho, khong phai default cho optimizer lon.

## Kien Truc De Xuat

Khong lam mot class khong lo voi day if/else. Lam framework chung voi spec con.

```text
QuantBTEndpoint.arbitrage(...)
        |
        v
ArbitrageBacktestEngine
        |
        +-- ArbDataAdapter
        +-- SyntheticSpreadBuilder
        +-- ArbSignalAdapter
        +-- Hedge/SizingPolicy
        +-- PackageOrderPlanner
        +-- NativeVectorizedArbBackend
        +-- NativeEventArbBackend
        +-- NautilusArbAdapter
        +-- ArbResult / BacktestResultV2 metadata
```

Public endpoint du kien:

```python
bt = QuantBTEndpoint.arbitrage(
    arb_type="basis",
    spec=BasisArbitrageSpec(...),
    backend="native_event",
    initial_capital=100_000,
    leverage=5,
    fee_rate=0.0004,
    use_funding=True,
)

result = bt.simulate(data=data_dict, signal=basis_signal)
```

Hoac direct engine:

```python
engine = ArbitrageBacktestEngine(
    spec=BasisArbitrageSpec(...),
    backend="native_event",
    data=data_dict,
    signal=basis_signal,
    account=AccountConfig(...),
    execution=ExecutionConfig(...),
)
```

## Core Schema

### ArbitrageSpec

Base class / protocol chung:

```python
ArbitrageSpec(
    arb_id: str,
    arb_type: str,
    legs: tuple[ArbitrageLeg, ...],
    spread_formula: SpreadFormula,
    signal_model: SignalModel | None,
    sizing_policy: SizingPolicy,
    hedge_policy: HedgePolicy,
    execution_policy: PackageExecutionPolicy,
    cost_model: CostModel,
    carry_model: CarryModel | None,
    margin_model: MarginModel,
    lifecycle_model: LifecycleModel,
    metadata: dict,
)
```

### ArbitrageLeg

Can bieu dien du cac loai instrument:

```python
ArbitrageLeg(
    symbol: str,
    venue: str | None,
    role: str,                 # rich, cheap, hedge, anchor, funding, option, etc.
    asset_class: str,          # spot, perp, future, option, fx, equity, index
    quote_currency: str,
    base_currency: str | None,
    contract_type: str,        # linear, inverse, quanto, spot, option
    contract_size: float,
    qty_step: float,
    min_qty: float,
    min_notional: float,
    tick_size: float,
    fee_rate: float | None,
    funding_enabled: bool,
    expiry: pd.Timestamp | None,
    settlement_policy: str | None,
)
```

### SpreadFormula

Spread builder khong duoc hard-code basis only. Can support:

- Price difference: `F1 - F2`
- Log spread: `log(P1) - beta * log(P2)`
- Ratio spread: `P1 / P2 - fair`
- Annualized basis: `(future / spot_or_perp - 1) * 365 / days_to_expiry`
- Funding spread: expected funding minus borrow/carry
- Basket residual: `base - sum(beta_i * hedge_i)`
- Triangular FX/crypto cycle: implied cross minus traded cross
- Options volatility spread: implied vol / delta-vega neutral package

Output can include:

```text
spread
zscore
annualized_basis
fair_value
mispricing
days_to_expiry
carry_component
funding_component
```

### HedgePolicy

Important policies:

- `freeze_on_entry`: compute units at entry and hold exact units until exit.
- `rebalance_threshold`: rebalance only if hedge drift exceeds threshold.
- `rebalance_interval`: rebalance periodically, e.g. daily/weekly.
- `delta_neutral`: hedge by delta, not notional.
- `notional_neutral`: equal quote notional when domain requires it.
- `base_qty_equal`: equal base quantity, used by linear futures/perps basis.
- `beta_neutral`: hedge by rolling/Kalman beta.
- `vega_neutral`, `gamma_neutral`: options arb later.

Default for most pair/basis strategies should be `freeze_on_entry=True`.
No price-drift micro-rebalancing unless explicitly configured.

### SizingPolicy

Sizing must be separated from hedge policy.

Examples:

- `target_gross_notional`
- `target_net_notional`
- `target_base_qty`
- `equity_fraction`
- `risk_budget_vol`
- `margin_budget`
- `delta_target`
- `vega_target`

For basis USDM perp-vs-quarterly, correct sizing flow:

```text
1. Choose risk/notional budget.
2. Convert budget to target BTC quantity using reference price.
3. Round quantity to common executable step across both legs.
4. Trade same base qty on both legs.
```

## Basis Trading: USDM Perp vs USDM Quarterly

Case:

```text
BTCUSDT perpetual vs BTCUSDT quarterly
USDT-M linear contracts
```

Domain rule:

```text
qty_perp_BTC == qty_quarterly_BTC
```

Khong dung equal notional lam hedge truth:

```text
notional_perp == notional_quarterly     # wrong for clean delta hedge
```

Ly do:

- Linear USDT-M PnL xap xi `qty_base * price_change`.
- Neu equal notional khi gia perp va quarterly khac nhau, base qty bi lech.
- Base qty lech tao residual delta voi BTC.
- Basis PnL nen den tu spread convergence, khong nen den tu huong BTC con sot lai.

Example:

```text
Perp price      = 100,000
Quarterly price = 102,000
Target qty      = 0.5 BTC

Short perp      0.5 BTC -> notional 50,000
Long quarterly  0.5 BTC -> notional 51,000
```

Notional khong bang nhau la binh thuong. Delta/base unit bang nhau moi dung.

Execution rounding:

```python
target_qty = target_notional / reference_price
qty = round_down_to_common_step(target_qty, perp_step, quarterly_step)

if qty < max(perp_min_qty, quarterly_min_qty):
    reject_or_skip()

if qty * perp_price < perp_min_notional:
    reject_or_skip()

if qty * quarterly_price < quarterly_min_notional:
    reject_or_skip()
```

Important:

- USDT-M linear futures/perps thuong order bang base asset quantity, co the la
  fractional qty neu symbol cho phep.
- Khong bat buoc integer "1 contract" nhu COIN-M inverse.
- COIN-M inverse co `contractSize`, nhieu contract la integer. Khi do hedge
  theo delta/face value, khong may moc equal `0.5 contract`.

Arbitrage engine phai co `InstrumentSpec` dung cho tung leg, khong hard-code
BTCUSDT rules.

## Arb Type Roadmap

### BasisArbitrageSpec

Use cases:

- Perp vs dated future.
- Spot vs future.
- Future vs fair value/carry.

Required domain models:

- same-underlying validation;
- base-qty/delta-neutral hedge;
- funding for perp leg;
- expiry/settlement for dated future;
- calendar roll;
- annualized basis;
- fee and spread per leg;
- margin offset/cross margin optional.

Initial implementation can support:

- USDM linear perp vs USDM quarterly;
- close-price market execution first;
- event-driven multi-leg entry/exit;
- funding on perp leg;
- expiry metadata but settlement can be phase 2 if no expiry in data range.

### CalendarSpreadSpec

Use cases:

- Quarterly vs next-quarterly.
- Front future vs back future.

Rules:

- same underlying;
- normally equal base qty/delta;
- spread is `F_near - F_far` or annualized roll yield;
- lifecycle requires expiry/roll handling;
- both legs are dated futures, so funding may be none but settlement matters.

### FundingArbitrageSpec

Use cases:

- Long/short instruments to capture funding.
- Cross-venue perp funding differential.

Rules:

- funding schedule per venue/symbol;
- mark/index price data;
- funding accrual at exact funding timestamps;
- borrow/cash yield optional;
- trade may be directionally hedged by spot/future/perp.

### StatArbPairSpec

Use cases:

- Cointegration pair.
- Kalman/rolling beta residual pair.
- Mean-reversion residual basket.

Rules:

- beta/hedge ratio can be time-varying;
- freeze beta at entry by default;
- optional rebalance threshold;
- spread formula supports log residual;
- entry signal is scalar spread/zscore;
- units computed across all legs simultaneously.

This should reuse current `BasketSpec` / `build_frozen_basket_orders` as the
foundation, but add richer arb-level result diagnostics.

### IndexBasketArbSpec

Use cases:

- Index future vs constituent basket.
- ETF vs basket.
- Crypto index perp vs basket.

Rules:

- many legs;
- weights from index constituents;
- stale/missing component handling;
- rebalance schedule;
- transaction cost model is important;
- vectorized research path useful, event path needed for fill realism.

### TriangularArbSpec

Use cases:

- FX or crypto triangular cycles.
- Example: BTC/USDT, ETH/BTC, ETH/USDT.

Rules:

- execution order matters;
- latency and partial fill risk dominate;
- order-book/tick data eventually required;
- bar-close backtest is only rough screening.

This should be event-driven/HFT phase, not initial implementation.

### CrossExchangeArbSpec

Use cases:

- Same instrument across venues.
- Perp funding/price discrepancy across exchanges.

Rules:

- per-venue fees, funding, latency;
- inventory constraints per venue;
- transfer delay not instantaneous;
- separate accounts/margins;
- execution is not atomic across venues;
- quote/order-book data needed for realistic fills.

### SpotPerpCashCarrySpec

Use cases:

- Spot vs perp.
- Spot vs future.

Rules:

- spot inventory;
- borrow/financing/cash yield;
- perp/future funding/carry;
- custody/transfer assumptions;
- no liquidation on spot, but leverage/margin if borrowed.

### OptionsVolArbSpec

Use cases:

- Vol spread.
- Calendar/vertical options spread.
- Delta-neutral option package.

Rules:

- Greeks time series;
- implied vol surface;
- delta/vega/gamma hedge;
- exercise/expiry;
- nonlinear PnL;
- underlying hedge leg;
- this is later phase, not initial arb engine.

## Execution Semantics

Arb execution must be package-aware.

Package execution policies:

- `atomic_all_or_none`: fill all legs or reject package.
- `best_effort`: submit all legs, accept partial fills and report legging risk.
- `sequential`: ordered execution, useful for triangular/cross-exchange later.
- `hedge_after_primary`: fill primary then hedge secondary.
- `rebalance_only`: submit deltas when drift threshold reached.

OHLC bar fill policy for native event backend:

- Market orders fill at configured price policy, e.g. close or next open.
- Buy limit fills if `low <= limit_price`.
- Sell limit fills if `high >= limit_price`.
- Fill at limit/trigger price, not at close.
- Ambiguous same-bar ordering must be configurable.

Package result must expose:

```text
orders_report
fills_report
package_report
leg_pnl_report
spread_report
carry_report
funding_report
margin_report
rejection_report
legging_risk_report
```

## Accounting And Margin

Minimum required accounting:

- cash/equity;
- realized/unrealized PnL per leg;
- package-level PnL;
- fees per leg;
- funding per leg;
- carry/borrow per leg;
- turnover/gross/net exposure;
- initial margin and maintenance margin;
- liquidation checks;
- rejected package orders due to margin/precision/min notional.

Margin modes:

- gross margin: conservative default.
- hedged margin offset: simple discount for recognized hedged packages.
- portfolio margin style diagnostics: later.
- venue/account-specific margin model: Nautilus validation or future adapter.

Important rule already established in QuantBT:

```text
buying_power = equity * leverage
alloc_per_trade is order notional/budget
leverage does not multiply alloc_per_trade
initial_margin_required = notional / leverage
```

## Native Vectorized vs Native Event vs Nautilus

### Native Vectorized Arb

Purpose:

- fast research;
- parameter sweeps;
- broad screening;
- simple package target states.

Limits:

- no detailed partial fill;
- no legging sequence;
- atomic assumptions likely simplified.

Inputs:

- aligned close matrix;
- spread/signal series;
- hedge ratio matrix;
- instrument specs arrays;
- cost/funding arrays.

Output:

- BacktestResultV2 plus arb diagnostics.

Numba rules:

- no Python dict/object in kernel;
- pass arrays: `(N, M)` prices, signals `(N,)`, hedge ratios `(N, M)`;
- use integer reason codes for rejection/fill states;
- keep pandas conversion outside kernel.

### Native Event Arb

Purpose:

- package order lifecycle;
- fills/orders/trades;
- limit/high-low fill;
- partial fill/legging policy;
- DCA/grid/basket/arb correctness.

This should be first truth backend for initial arbitrage implementation.

### Nautilus Arb Adapter

Purpose:

- high-fidelity validation;
- production-like event model;
- instrument precision;
- OMS netting/hedging semantics;
- account and portfolio reports.

Design:

- QuantBT computes synthetic spread/signal outside Nautilus strategy.
- Nautilus strategy subscribes to component instruments.
- Strategy submits component orders; synthetic instrument is analytical only.
- Convert Nautilus reports back to BacktestResultV2/ArbResult.

Not first step:

- do not rely on Nautilus as only core due to dependency size, callback overhead,
  report conversion, and optimizer speed constraints.

## Result Schema Extension

Keep `BacktestResultV2` compatible. Add metadata and optional objects:

```python
result.metadata["arb_type"]
result.metadata["arb_spec"]
result.metadata["package_report"]
result.metadata["spread_report"]
result.metadata["leg_pnl_report"]
result.metadata["carry_report"]
result.metadata["funding_report"]
result.metadata["margin_report"]
result.metadata["rejection_report"]
result.metadata["package_orders"]
result.metadata["package_fills"]
```

Potential future class:

```python
ArbitrageBacktestResult(BacktestResultV2)
```

But avoid breaking existing metrics/viz. Better first return BacktestResultV2
with rich metadata.

## Suggested Implementation Phases

### Phase A - Design And Golden Tests

Deliverables:

- Add docs and explicit API skeleton.
- Add synthetic fixtures for:
  - USDM perp-vs-quarterly basis;
  - stat-arb pair with frozen beta;
  - package reject due to min qty/min notional;
  - partial fill vs atomic reject behavior.

Acceptance:

- No engine code needed yet, but tests define target behavior.
- Golden tests should compare package PnL and leg PnL separately.

### Phase B - Core Arb Schema

Deliverables:

- `core/arbitrage.py`
- `ArbitrageLeg`
- `ArbitrageSpec`
- subtype dataclasses;
- `SpreadFormula`;
- `HedgePolicy`;
- `SizingPolicy`;
- `PackageExecutionPolicy`.

Acceptance:

- validation for leg count, symbols, contract types, expiry, qty step.
- no heavy engine logic yet.

### Phase C - BasisArbitrageSpec Minimal Native Event

Status: implemented in `NativeEventBackend.run_basis_arbitrage()` and
`QuantBTEndpoint.arbitrage(..., spec=BasisArbitrageSpec(...))`.

Deliverables:

- USDM linear perp-vs-quarterly support.
- Equal base quantity sizing.
- Market package entry/exit.
- Fees per leg.
- Funding on perp leg if data provided.
- Frozen units until exit.

Acceptance:

- equal BTC qty on both legs;
- notional can differ;
- package PnL equals leg PnL sum;
- close all legs together at exit;
- result has spread_report and leg_pnl_report.

Implementation notes:

- Signal transitions generate package leg orders from `build_arbitrage_order_plan()`.
- Units are frozen through `package_target_units` until the next transition.
- Per-leg `fee_rate` is respected by the native event kernel.
- Scalar funding inputs are applied only to legs with `funding_enabled=True`.
- `result.metadata["spread_report"]`, `result.metadata["leg_pnl_report"]`, and
  `result.metadata["package_pnl_report"]` are the primary Phase C diagnostics.

### Phase D - StatArbPairSpec / Basket Integration

Status: implemented in `NativeEventBackend.run_stat_arb_pair_arbitrage()` and
`QuantBTEndpoint.arbitrage(..., spec=StatArbPairSpec(...))`.

Deliverables:

- reuse BasketSpec / frozen basket order plan;
- time-varying hedge ratios;
- freeze beta at entry;
- optional rebalance threshold.

Acceptance:

- no price-drift micro rebalancing;
- exit closes exact frozen units;
- beta drift diagnostic exists.

Implementation notes:

- `StatArbPairSpec` is converted internally to `BasketSpec` and executed by the
  frozen basket planner.
- Dynamic `hedge_ratios` are sampled on signal transitions and held frozen while
  the signal is unchanged.
- `HedgePolicy.rebalance_threshold` can trigger package rebalance on beta drift
  only; price movement alone does not rebalance the package.
- `result.metadata["beta_drift_report"]` records frozen ratio, current ratio,
  relative drift, threshold, and breach state per leg.

### Phase E - Native Vectorized Arb Fast Path

Status: implemented in `NativeVectorizedBackend.run_basis_arbitrage()`,
`NativeVectorizedBackend.run_stat_arb_pair_arbitrage()`, and
`QuantBTEndpoint.arbitrage(..., backend="native_vectorized", ...)`.

Deliverables:

- Numba kernel for package target units and PnL.
- Basis and stat-arb vectorized variants.
- Fast benchmark suite.

Acceptance:

- matches native event under deterministic market-fill assumptions;
- much faster for grid search.

Implementation notes:

- The existing `_engine_units_v2` Numba kernel is now the package target-units
  fast path and supports per-symbol fee rates.
- Basis and stat-arb vectorized routes reuse the same frozen target-unit plans as
  the native event routes, then execute those target units through the Numba
  kernel.
- Vectorized reports expose `spread_report`, `beta_drift_report`,
  `leg_pnl_report`, and `package_pnl_report` without event fill objects.
- Unit tests assert parity against native event under zero-slippage deterministic
  market-fill assumptions.
- `benchmarks/run_arbitrage_phase_e.py` provides basis/stat-arb event vs
  vectorized smoke and standard benchmark profiles.

### Phase F - Nautilus Arb Validation

Status: implemented via `NautilusBacktestEngine.run_order_packages()` and
`QuantBTEndpoint.arbitrage(..., backend="nautilus", ...)`.

Deliverables:

- Nautilus strategy adapter for component order packages.
- Convert package order intent to Nautilus order list.
- Report conversion to BacktestResultV2.

Acceptance:

- parity test with native event on simple market fills.
- metadata exposes Nautilus orders/fills and package mapping.

Implementation notes:

- `build_nautilus_package_order_table()` converts quantbt `OrderIntent`
  component orders into a stable package mapping table.
- The Nautilus package strategy submits market IOC component orders once per
  package timestamp across all subscribed instruments.
- Endpoint integration reuses Basis and StatArb package plans, then forwards
  component orders to Nautilus.
- Metadata exposes `package_order_map`, `package_target_units`, raw Nautilus
  reports, and arb identifiers.
- Current Nautilus instrument helper supports Binance perpetual test/synthetic
  instruments; quarterly/futures instrument wiring remains a later extension.

### Phase G - Advanced Arb Types

Status: Phase G.1 implemented.

Add gradually:

- CalendarSpreadSpec with expiry/roll.
- FundingArbitrageSpec with funding schedule.
- SpotPerpCashCarrySpec with borrow/cash yield.
- IndexBasketArbSpec with many legs.
- CrossExchangeArbSpec with venue/account split.
- TriangularArbSpec with sequence/latency.
- OptionsVolArbSpec with Greeks/IV surface.

Implementation notes:

- Added domain validation for calendar, funding, spot-perp cash carry, index
  basket, cross-exchange, triangular, and options-vol specs.
- Added generic package-style engine routes:
  - `NativeEventBackend.run_package_arbitrage()`;
  - `NativeVectorizedBackend.run_package_arbitrage()`;
  - `QuantBTEndpoint.arbitrage(...)` for native event/vectorized Phase G package
    specs.
- Package-style route currently supports:
  - `CalendarSpreadSpec`;
  - `FundingArbitrageSpec`;
  - `SpotPerpCashCarrySpec`;
  - `IndexBasketArbSpec`.
- Reports include `spread_report`, `carry_report`, `leg_pnl_report`,
  `package_pnl_report`, and `package_target_units`.
- `CrossExchangeArbSpec`, `TriangularArbSpec`, and `OptionsVolArbSpec` remain
  explicit specialized-engine gaps. They now validate domain shape but raise
  clear `NotImplementedError` in generic engines because they require venue
  account state, sequence/latency modeling, or Greeks/IV surface semantics.

## Initial API Sketch

```python
from quantbt import (
    QuantBTEndpoint,
    ArbitrageLeg,
    BasisArbitrageSpec,
    HedgePolicy,
    SizingPolicy,
    PackageExecutionPolicy,
)

spec = BasisArbitrageSpec(
    arb_id="BTC_USDM_PERP_QUARTERLY",
    legs=(
        ArbitrageLeg(
            symbol="BTCUSDT-PERP.BINANCE",
            role="perp",
            contract_type="linear",
            contract_size=1.0,
            qty_step=0.001,
            min_qty=0.001,
            min_notional=100.0,
            funding_enabled=True,
        ),
        ArbitrageLeg(
            symbol="BTCUSDT-QUARTERLY.BINANCE",
            role="quarterly",
            contract_type="linear",
            contract_size=1.0,
            qty_step=0.001,
            min_qty=0.001,
            min_notional=100.0,
            funding_enabled=False,
        ),
    ),
    hedge_policy=HedgePolicy(kind="base_qty_equal", freeze_on_entry=True),
    sizing_policy=SizingPolicy(kind="target_notional_to_base_qty", notional=50_000),
    execution_policy=PackageExecutionPolicy(kind="atomic_all_or_none"),
)

bt = QuantBTEndpoint.arbitrage(
    arb_type="basis",
    spec=spec,
    backend="native_event",
    initial_capital=100_000,
    leverage=5,
)

result = bt.simulate(
    data={
        "BTCUSDT-PERP.BINANCE": perp_df,
        "BTCUSDT-QUARTERLY.BINANCE": quarterly_df,
    },
    signal=basis_signal,
)
```

## Rules To Preserve

- Do not hide domain assumptions.
- Do not silently rebalance hedge legs.
- Do not treat package legs as independent signals unless user explicitly asks.
- Every precision/min-notional/margin rejection must be visible.
- Every package trade should have a package id.
- Every leg fill should map back to package id and leg role.
- Vectorized path is for speed; event path is source of execution truth.
- Nautilus path is validation/reference, not optimizer default.
- Specs must be extensible without rewriting engine internals.

## References To Revisit Before Implementation

Official docs and references worth re-checking before coding:

- NautilusTrader backtesting concepts:
  `https://nautilustrader.io/docs/latest/concepts/backtesting/`
- NautilusTrader synthetic instruments:
  `https://nautilustrader.io/docs/latest/concepts/synthetics/`
- NautilusTrader positions / OMS semantics:
  `https://nautilustrader.io/docs/latest/concepts/positions/`
- HftBacktest order fill / queue / latency models:
  `https://hftbacktest.readthedocs.io/en/latest/order_fill.html`
- VectorBT portfolio/order function design:
  `https://vectorbt.dev/api/portfolio/base/`
- Binance USD-M exchange info for lot size, tick size, min notional:
  `https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information`
- Binance COIN-M exchange info for inverse contract size:
  `https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/rest-api/Exchange-Information`

## Open Questions

- Should `ArbitrageBacktestResult` subclass `BacktestResultV2`, or should
  BacktestResultV2 metadata remain the universal contract?
- Should package execution default to atomic reject or best-effort partial fill?
- How much venue-specific margin offset should native QuantBT model before
  delegating validation to Nautilus?
- Should `BasisArbitrageSpec` support spot-vs-future in phase C, or start only
  with USDM linear perp-vs-quarterly?
- What is the default reference price for converting target notional to base
  qty: perp, quarterly, mark/index, or configurable?
- Should funding data be required for perp basis backtests, or optional with
  explicit warning?

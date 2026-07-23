# Portfolio Engine V3 Methodology

Portfolio Engine V3 is the roadmap for replacing the current compatibility
portfolio path with a native, array-first, institutional-grade engine.

The key rule is simple: legacy behavior is an oracle, not a permanent design.
We keep it until the new engine proves that it preserves existing alpha meaning
or intentionally improves a documented flaw.

## Phase 11A - Domain Contract

Implemented in `quantbt.core.portfolio`.

Public helpers:

```python
from quantbt import (
    PortfolioDomainSpec,
    portfolio_capability_matrix,
    validate_portfolio_result_contract,
)
```

Current native portfolio modes:

- `longshort`
- `market_neutral`
- `directional`
- `equal_weight`
- `risk_parity`
- `beta_neutral`

Current legacy-compatible sizing modes:

- `signal_notional`
- `signal`
- `notional`
- `unit`

Native portfolio roadmap sizing modes:

- `signal_notional`
- `signal`
- `notional`
- `unit`
- `%_equity`
- `target_weight`
- `target_notional`
- `target_units`
- `fixed_notional`
- `gross_exposure`
- `net_exposure`
- `dca_ladder`

Example validation:

```python
spec = PortfolioDomainSpec(
    mode="market_neutral",
    sizing_mode="signal_notional",
)

report = validate_portfolio_result_contract(result, spec, raise_on_fail=True)
```

The validator checks accounting reconciliation, required reports, margin
columns, exposure identities, and mode-specific invariants.

## Phase 11B - Native Core

Implemented as an explicit backend:


```python
QuantBTEndpoint.portfolio(backend="native_portfolio", ...)
```

The default is now `native_portfolio`. Use `backend="legacy_portfolio"` when a
run must reproduce historical legacy behavior.

Current Phase 11C behavior:

- array-first market and signal packing;
- NumPy portfolio-mode transforms;
- `_engine_portfolio` kernel execution for exact legacy parity;
- V2 result reports for target units, accepted units, exposure, margin,
  per-symbol PnL, fees, funding, turnover, and contract validation;
- explicit support for:
  - `signal_notional`;
  - `signal`;
  - `notional`;
  - `unit`;
  - `%_equity`;
  - `target_weight`;
  - `target_units`;
  - `target_notional`;
  - `fixed_notional`;
  - `gross_exposure`;
  - `net_exposure`.

Equity-dependent sizing modes use the native equity-aware portfolio kernel and
size from live equity at the execution bar. `dca_ladder` remains on the
DCA/grid engine because it requires intrabar high/low grid-trigger semantics,
not simple target-matrix sizing.

## Phase 11C - Institutional Validation

Phase 11C adds mock-domain institutional validation:

- mock scenario tests;
- legacy parity tests;
- benchmark runs;
- migration documentation.

Covered mock scenarios:

- flat book;
- long-only;
- short-only;
- long/short;
- market-neutral rebalance;
- equal-weight rebalance;
- inverse-volatility risk-parity allocation;
- beta-neutral allocation;
- price drift without signal change;
- missing data;
- fee and funding reconciliation;
- leverage and buying-power gate;
- margin rejection;
- liquidation audit without fake force-flat fees.

Any intentional difference from legacy behavior must be explicitly named,
tested, and documented.

Default-readiness status:

- `QuantBTEndpoint.portfolio(...)` defaults to `native_portfolio`;
- `PortfolioBacktestEngine(...)` defaults to `native_portfolio`;
- `backend="legacy_portfolio"` remains available;
- deterministic parity audit lives in
  `benchmarks/portfolio_real_parity_report.md`;
- `dca_ladder` is intentionally rejected by native portfolio and remains on the
  DCA/grid endpoint.

## Phase 11D - Nautilus Validation

Implemented for portfolio package validation. Nautilus validates representative
portfolio packages as a third-party event-driven trustee. The native portfolio
engine remains the optimizer and research hot path; Nautilus validates
execution/accounting behavior for selected runs.

The endpoint route:

```python
result = QuantBTEndpoint.portfolio(
    backend="nautilus",
    portfolio_mode="market_neutral",
    hedge_type="signal_notional",
    alloc_per_trade={"BTCUSDT-PERP.BINANCE": 50_000, "ETHUSDT-PERP.BINANCE": 50_000},
    initial_capital=1_000_000,
).simulate(
    positions=positions_df,
    data=data_dict,
    symbols=["BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE"],
)

validation = result.metadata["portfolio_nautilus_validation_report"]
```

Important implementation rule: Nautilus package orders are compiled from the
native portfolio `target_units_report`, not directly from raw signals. This
means `market_neutral`, `directional`, and `equal_weight` transforms are applied
before the third-party validation run.

Validation targets:

- order and fill count;
- fill price policy;
- fee convention;
- gross/net exposure path;
- final equity;
- drawdown and account timeline.

Public helpers:

```python
from quantbt import (
    build_portfolio_nautilus_position_report,
    build_portfolio_nautilus_validation_report,
)
```

## Phase 12B - Prepared Cache And Report Optimization

The native portfolio backend now exposes prepared-array APIs for services and
WFO loops that replay many parameter sets over the same market tape.

```python
from quantbt.backends import NativePortfolioBackend, NativePortfolioConfig
from quantbt import AccountConfig

backend = NativePortfolioBackend(
    NativePortfolioConfig(
        account=AccountConfig(initial_capital=250_000, leverage=5),
        fee_rate=0.0002,
        use_funding=False,
    )
)

market = backend.prepare_market_arrays(
    datetime_index=idx,
    closes=closes,
    highs=highs,
    lows=lows,
    funding_rate=0.0,
    symbols=symbols,
)

signals = backend.prepare_signal_matrix(positions, idx, symbols)

result = backend.run_signals(
    positions=None,
    closes=closes,
    datetime_index=idx,
    symbols=symbols,
    mode="longshort",
    hedge_type="signal_notional",
    alloc_per_trade=10_000,
    market_arrays=market,
    raw_signal_matrix=signals,
)
```

Safety rule: prepared arrays are validated by datetime/symbol signature before
execution. A stale index, different symbol order, or wrong signal shape raises
instead of silently reusing incompatible cache.

Prepared arrays are copied market snapshots, not mutable global caches. If the
underlying OHLC/funding values change, rebuild `market = backend.prepare_market_arrays(...)`.
The signature guard protects layout compatibility; it intentionally does not
hide data mutation behind object-identity cache magic.

## Phase 14C - Report Levels

Native portfolio now supports opt-in report artifact controls:

```python
result = QuantBTEndpoint.portfolio(
    backend="native_portfolio",
    portfolio_mode="market_neutral",
    report_level="minimal",  # full | standard | minimal
).backtest(
    positions=positions_df,
    data=data_dict,
)
```

Use `report_level="full"` for final research artifacts and stakeholder review.
This is the default and keeps the complete audit surface:

- target and accepted units;
- target and accepted notional;
- exposure and margin reports;
- risk volatility and risk contribution;
- symbol PnL and kernel symbol PnL;
- rebalance rejection report;
- portfolio contract validation.

Use `report_level="standard"` for lighter service reports that still need
portfolio contract validation and leg-level PnL explainability. It keeps
target/accepted notional, exposure, funding rates, and symbol PnL, but omits
selected expansion tables.

Use `report_level="minimal"` only for optimizer/service loops where the
objective needs accounting outputs but not full audit artifacts. It preserves
equity, returns, positions, closes, fees, funding, margin, diagnostics,
target/accepted units, totals, config metadata, and quantity constraints.
Contract validation is marked as skipped because the heavy reports it needs are
intentionally omitted.

Parity contract: core accounting must be identical across `full`, `standard`,
and `minimal`. Tests lock equality for equity, returns, positions, fees,
funding, margin, and diagnostics before any report-level speed claim is used.

Optimization scope completed:

- `notional` and `unit` sizing use ndarray vector paths;
- market normalization can be reused through `PreparedMarketArrays`;
- symbol PnL report construction is vectorized into one DataFrame build;
- pure kernel benchmark and full facade benchmark are reported separately.
- WFO endpoint scoring can reuse prepared market arrays for portfolio scoring
  and for single-symbol `signal_notional` native-vectorized scoring.

Remaining optimization target: report construction is still a residual bucket
for full stakeholder artifacts, so Cython/C++ is not justified before larger
real service-loop profiling.

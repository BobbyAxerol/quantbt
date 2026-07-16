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

Current legacy modes:

- `longshort`
- `market_neutral`
- `directional`
- `equal_weight`

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

The default should remain `legacy_portfolio` until golden parity and real alpha
validation are complete.

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
  - `target_units`;
  - `target_notional`;
  - `fixed_notional`.

Equity-dependent sizing modes such as `%_equity`, `target_weight`,
`gross_exposure`, and `net_exposure` remain unsupported until an equity-aware
portfolio kernel is added. `dca_ladder` remains on the DCA/grid engine because
it requires intrabar high/low grid-trigger semantics, not simple target-matrix
sizing.

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
- price drift without signal change;
- missing data;
- fee and funding reconciliation;
- leverage and buying-power gate;
- margin rejection;
- liquidation audit without fake force-flat fees.

Any intentional difference from legacy behavior must be explicitly named,
tested, and documented.

## Phase 11D - Nautilus Validation

Nautilus should validate representative portfolio packages as a third-party
event-driven trustee.  The native portfolio engine remains the optimizer and
research hot path; Nautilus validates execution/accounting behavior for selected
runs.

Validation targets:

- order and fill count;
- fill price policy;
- fee convention;
- gross/net exposure path;
- final equity;
- drawdown and account timeline.

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

The native engine should be a separate backend, requested explicitly:

```python
QuantBTEndpoint.portfolio(backend="native_portfolio", ...)
```

The default should remain `legacy_portfolio` until golden parity and real alpha
validation are complete.

The core must be array-first:

- signal/position matrix to target exposure;
- target exposure to target units;
- target units to trade deltas;
- fees, slippage, funding;
- per-symbol PnL;
- gross/net exposure;
- margin and liquidation;
- attribution reports.

## Phase 11C - Institutional Validation

Before changing defaults, the native engine must pass:

- mock scenario tests;
- legacy parity tests;
- real-strategy smoke tests;
- benchmark runs;
- migration documentation.

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

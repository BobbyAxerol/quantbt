# Phase 6 - Hedging And Margin Status

Date: 2026-07-23

Branch: `feat/option-engine`

## Scope Completed

Phase 6 added option hedge-policy primitives, option margin approximations, an
external margin validator interface, and liquidation audit primitives. It does
not add the full option backend, endpoint route, Nautilus validation, or
venue-exact margin adapter.

Implemented:

- `options/hedging.py`
  - `OptionHedgePolicyType`;
  - `OptionHedgeConfig`;
  - `HedgeDecision`;
  - `HedgePathResult`;
  - `compute_net_option_delta(...)`;
  - `hedge_decision(...)`;
  - `run_delta_hedge_path(...)`.
- `options/margin.py`
  - `OptionMarginModel`;
  - `OptionMarginConfig`;
  - `OptionMarginRequirement`;
  - `ExternalOptionMarginValidator`;
  - `OptionLiquidationAudit`;
  - `calculate_option_margin(...)`;
  - `liquidate_option_positions(...)`.
- Public exports through `quantbt.options` and top-level `quantbt`.

## Domain Guarantees Locked

- Hedge PnL for the prior price move uses the hedge quantity held before the
  move.
- Hedge rebalance is evaluated after current option delta is recomputed.
- Fixed-threshold hedge policy is explicit.
- Hysteresis band policy is explicit and has separate enter/exit bands.
- Time-based hedge policy respects `rebalance_interval_ns`.
- Realized-vol scaled band uses observable underlying path history.
- Whalley-Wilmott is not implemented.
- Long-premium-only margin model is available.
- Standard venue approximation margin model is available.
- Scenario PM approximation reports `venue_exact=false`.
- No-margin research mode is available and labelled.
- External margin validator path requires an explicit validator.
- Liquidation audit explains:
  - breach status;
  - breach reason;
  - equity before;
  - maintenance margin;
  - adverse bid/ask liquidation orders;
  - fees;
  - final cash;
  - final positions.

## Tests Run

Commands:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options __init__.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.OptionHedgeConfig; assert quantbt.OptionMarginConfig; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase6_import_smoke=pass')"
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py
```

Results:

- compileall: pass.
- options tests: `71 passed`.
- import smoke: `phase6_import_smoke=pass`.
- full non-real regression: `357 passed, 1 skipped, 3 warnings`.

Existing warnings are unrelated to options:

- one pandas runtime warning in a portfolio missing-data scenario;
- two matplotlib tight-layout warnings in walk-forward quick plot tests.

## Technical Debt

- Hedge and margin are primitives, not yet wired into a full option backend
  event loop.
- Whalley-Wilmott remains intentionally excluded until objective, cost units,
  and paper reproduction are explicit.
- Standard/scenario PM models are approximations; venue-exact margin requires
  external validator integration and sample parity.
- Liquidation closes all option positions with adverse BBO prices. It is not an
  exchange-native liquidation optimizer or queue model.
- Underlying hedge instrument execution, hedge fees, and hedge slippage are not
  integrated with package execution yet.
- Nautilus option validation remains future work.

## Conclusion

Phase 6 is complete and safe to build on. QuantBT options now has transparent
hedge-policy, margin, and liquidation audit primitives. Phase 7 can wire these
into a native option backend, result contract, endpoint, and support matrix.

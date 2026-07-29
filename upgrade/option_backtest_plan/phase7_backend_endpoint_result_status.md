# Options Engine Phase 7 Status

Status: completed.

## Scope

Phase 7 wires the option domain components from Phases 1-6 into the public
QuantBT backend, engine, endpoint, result, and metrics contracts.

This phase does not add strategy templates or Nautilus option validation. Those
remain Phase 8 and Phase 9 respectively.

## Implemented

- `backends/native_option.py`
  - `NativeOptionConfig`;
  - `NativeOptionBackend`;
  - `OptionSettlementEvent`;
  - option chain tape preparation;
  - option package execution;
  - multi-currency ledger fill application;
  - settlement event application;
  - option margin calculation;
  - standard `OptionBacktestResult` construction.

- `core/results.py`
  - `OptionBacktestResult`, compatible with `BacktestResultV2`;
  - explicit option artifacts:
    - `fills_report`;
    - `packages_report`;
    - `cash_report`;
    - `marks_report`;
    - `greeks_report`;
    - `settlements_report`;
    - `margin_report`;
    - `attribution_report`;
    - `run_manifest`.

- `engines.py`
  - `OptionBacktestEngine` facade.

- `endpoint.py`
  - `QuantBTEndpoint.options(...)`;
  - `QuantBTEndpoint.options_support_matrix()`;
  - options dispatch in `backtest()` / `simulate()`;
  - `OptionsVolArbSpec` generic arbitrage guard now points to the option route.

- `metrics/options_analytics.py`
  - `option_run_manifest`;
  - `option_attribution_report`;
  - `option_report_bundle`.

- Public exports through `quantbt`, `quantbt.backends`, and `quantbt.metrics`.

## Domain Validation

- Option PnL is not computed by a standalone payoff shortcut.
- Package fills come from `execute_option_package`.
- Cash, position, realized PnL, fees, and settlement cashflows are applied by
  `OptionLedger`.
- Marked equity uses premium/settlement currency conversion into the configured
  reporting currency.
- Margin is reported through `calculate_option_margin`.
- Result position and close columns follow the common QuantBT contract:
  `Position_<symbol>` and `Close_<symbol>`.

## Tests

Commands:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.NativeOptionConfig; assert quantbt.OptionBacktestResult; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase7_import_smoke=pass')"
```

Phase-local tests added:

- `tests/options/test_result_contract.py`
- `tests/options/test_endpoint_contract.py`

## Technical Debt

- Venue-exact option margin still requires an external validator or later
  Nautilus/venue adapter.
- Nautilus option instrument mapping is intentionally not claimed in Phase 7.
- Strategy/package templates and golden payoff grids are Phase 8.
- Exchange-native combo order behavior, assignment/exercise nuances, and L2
  queue priority are future fidelity upgrades.

## Conclusion

Phase 7 is complete and safe to build on. QuantBT now has a public native option
endpoint that can run mock option-chain package examples and return the same
core metrics contract as other QuantBT engines, plus option-specific audit
artifacts for fills, packages, cash, marks, Greeks, settlement, margin, and
attribution.

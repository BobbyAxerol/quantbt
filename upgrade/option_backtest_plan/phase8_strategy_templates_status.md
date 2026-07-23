# Options Engine Phase 8 Status

Status: completed.

## Scope

Phase 8 adds option strategy/package templates and golden terminal payoff tests.
It does not add new accounting logic to production code.

## Implemented

- `options/templates/packages.py`
  - `long_call`;
  - `short_call`;
  - `long_put`;
  - `short_put`;
  - `straddle`;
  - `strangle`;
  - `vertical`;
  - `butterfly`;
  - `condor`;
  - `calendar`;
  - `covered_call`;
  - `collar`;
  - `risk_reversal`.

- `options/templates/__init__.py`
  - public template namespace.

- Public exports:
  - `quantbt.options`;
  - top-level `quantbt`.

- Examples:
  - `examples/options/deribit_inverse_gamma_scalping.py`;
  - `examples/options/linear_spread.py`;
  - `examples/options/covered_call.py`;
  - `examples/options/calendar_spread.py`.

- Tests:
  - `tests/options/test_strategy_payoffs.py`.

## Domain Rules

- Templates emit `OptionPackageIntent` only.
- Templates do not calculate payoff, PnL, Greeks, margin, or account state.
- Direction belongs to `OrderSide`; leg ratios are always positive.
- Package quantity scales the full structure.
- Covered call and collar templates include an explicit underlying leg for
  domain clarity.

## Golden Payoff Coverage

The terminal payoff tests cover:

- single long/short calls and puts;
- long straddle and strangle;
- debit vertical;
- long butterfly;
- long condor;
- calendar spread terminal intrinsic neutrality;
- covered call;
- collar;
- bullish and bearish risk reversal.

The tests use a linear USD option registry so terminal shapes are transparent
and do not mix inverse currency conversion into template validation.

## Validation Commands

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options examples/options __init__.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python examples/options/linear_spread.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python examples/options/calendar_spread.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python examples/options/covered_call.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python examples/options/deribit_inverse_gamma_scalping.py
```

## Technical Debt

- Mixed underlying+option package execution remains future work. The templates
  describe covered call/collar intent correctly, but Phase 7 native option
  execution only fills option-chain instruments.
- Golden payoff tests validate payoff shape, not premium-adjusted net PnL.
  Premium, fees, ledger, and margin remain backend responsibilities.
- Nautilus option validation is still Phase 9.

## Conclusion

Phase 8 is complete and safe to build on. QuantBT now has a clear V1 package
template layer for common option structures, with payoff-shape tests ensuring
the emitted legs match canonical option strategy behavior.

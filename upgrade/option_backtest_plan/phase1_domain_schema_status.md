# Phase 1 - Domain Schema And Conventions Status

Date: 2026-07-23

Branch: `feat/option-engine`

## Scope Completed

Phase 1 added the option domain boundary without changing existing backtest
execution behavior.

Implemented:

- `AssetType.OPTION` in `core/schema.py`.
- `quantbt.options` namespace:
  - `schema.py`;
  - `conventions.py`;
  - `data.py`.
- Option enums:
  - `OptionKind`;
  - `ExerciseStyle`;
  - `PremiumConvention`;
  - `SettlementStyle`;
  - `OptionDecisionFillPolicy`.
- `OptionInstrumentSpec` extending the existing `InstrumentSpec`.
- `OptionInstrumentRegistry` with deterministic convention signatures.
- Versioned venue convention descriptors:
  - Deribit inverse BTC/ETH;
  - Deribit linear USDC;
  - Binance European options metadata-safe descriptor.
- Canonical long-form option chain validator.
- Public top-level exports from `quantbt`.

## Domain Guarantees Locked

- Linear quote options require `premium_currency == quote_currency`.
- Inverse base options require `premium_currency == settlement_currency`.
- Inverse base options require quote currency distinct from premium currency.
- Physical settlement is not allowed for linear quote options in Phase 1.
- Strike, expiry, multiplier, currency fields, venue, and underlying identifiers
  are validated.
- Registry symbols must be unique.
- Registry signatures are stable after sorting by symbol.
- Canonical option chain input is long-form, not dense matrix based.
- Crossed quotes, expired rows, duplicate snapshot rows, missing required
  columns, invalid option kinds, invalid timestamps, and invalid numeric fields
  reject explicitly.
- `import quantbt` does not import `nautilus_trader`.

## Tests Run

Commands:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options core/schema.py __init__.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options/test_phase1_schema_conventions.py tests/options/test_phase1_data.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase1_import_smoke=pass')"
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py
```

Results:

- compileall: pass.
- Phase 1 option tests: `12 passed`.
- import smoke: `phase1_import_smoke=pass`.
- full non-real regression: `298 passed, 1 skipped, 3 warnings`.

Existing warnings are unrelated to options:

- one pandas runtime warning in a portfolio missing-data scenario;
- two matplotlib tight-layout warnings in walk-forward quick plot tests.

## Technical Debt

- `OptionInstrumentSpec.multiplier` must currently match
  `InstrumentSpec.contract_size`. This is transparent and safe, but Phase 2+
  should decide whether one field becomes canonical for option reports.
- `OptionInstrumentSpec.qty_step` mirrors `InstrumentSpec.lot_size`. This is
  explicit and tested, but endpoint docs should later settle on one user-facing
  term for order quantity increment.
- The canonical chain validator rejects zero bid/ask quotes. That is safest for
  executable quote input now; Phase 3 tape work may add explicit one-sided
  quote semantics.
- Venue conventions are static descriptors. Historical fee, margin, settlement,
  and contract metadata versioning still need venue samples or Nautilus parity.
- Binance European options support is metadata-safe only and does not claim
  exact Binance venue margin behavior.
- Pricing, IV, Greeks, surface calibration, execution, ledger, expiry, endpoint,
  and Nautilus validation are intentionally not implemented in Phase 1.

## Conclusion

Phase 1 is complete and safe to build on. It establishes option identity,
conventions, and chain input validation only; it does not alter any existing
QuantBT backtest engine behavior.

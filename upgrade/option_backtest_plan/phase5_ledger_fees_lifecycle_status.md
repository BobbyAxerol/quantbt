# Phase 5 - Multi-Currency Ledger, Fees, Lifecycle Status

Date: 2026-07-23

Branch: `feat/option-engine`

## Scope Completed

Phase 5 added option accounting primitives: multi-currency ledger, capped
per-leg fees, and expiry lifecycle settlement. It does not add the full option
backend, endpoint route, margin engine, liquidation, or Nautilus validation.

Implemented:

- `options/fees.py`
  - `OptionFeeSchedule`;
  - `OptionFeeResult`;
  - Deribit-like inverse base-currency schedule;
  - Deribit-like linear USDC schedule;
  - per-leg fee cap calculation.
- `options/ledger.py`
  - `OptionLedger`;
  - `OptionPosition`;
  - cash balances by currency;
  - position quantity;
  - average entry;
  - realized PnL;
  - fee totals;
  - settlement cashflows;
  - margin-locked bucket;
  - event audit rows;
  - reporting-currency equity identity report.
- `options/lifecycle.py`
  - `OptionSettlementRepresentation`;
  - `OptionSettlementResult`;
  - expiry payoff calculation;
  - settlement exactly-once handling.
- Public exports through `quantbt.options` and top-level `quantbt`.

## Domain Guarantees Locked

- Long option fills pay premium.
- Short option fills receive premium.
- Fees are recorded separately from premium cashflow.
- Inverse fees settle in base/premium currency.
- Linear fees settle in USDC/premium currency for the Deribit-like schedule.
- Fee caps are per leg, not package-level.
- Round trip with no price move reconciles to spread plus fees.
- Inverse BTC premium and USD reporting equity reconcile through explicit
  conversion rates.
- OTM expiry closes position with zero payoff.
- ITM linear cash payoff settles in quote/settlement currency.
- ITM inverse payoff settles in base currency using:

```text
call payoff_base = max(S - K, 0) / S
put payoff_base  = max(K - S, 0) / S
```

- Settlement closes exactly once; a second settlement attempt raises.
- Deribit linear `economic_cash` and `future_then_cash` representations are
  auditable labels with equivalent economic cashflow in Phase 5.

## Tests Run

Commands:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options __init__.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.OptionLedger; assert quantbt.settle_option_expiry; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase5_import_smoke=pass')"
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py
```

Results:

- compileall: pass.
- options tests: `63 passed`.
- import smoke: `phase5_import_smoke=pass`.
- full non-real regression: `349 passed, 1 skipped, 3 warnings`.

Existing warnings are unrelated to options:

- one pandas runtime warning in a portfolio missing-data scenario;
- two matplotlib tight-layout warnings in walk-forward quick plot tests.

## Technical Debt

- Ledger is not yet wired into a full `NativeOptionBackend` or endpoint route.
- `margin_locked` exists as an audit bucket, but margin models and liquidation
  sequencing are Phase 6.
- Fee schedules are deterministic Deribit-like approximations, not venue-exact
  certified schedules.
- `future_then_cash` currently records equivalent economic cashflow with a
  representation label; later venue adapters may split delivery and cash rows.
- Quanto lifecycle payoff is intentionally not implemented.
- Reporting currency conversion requires caller-supplied conversion rates; no
  external FX/index feed is implicitly fetched.

## Conclusion

Phase 5 is complete and safe to build on. QuantBT options now has auditable
premium/fee cashflow, realized PnL, reporting equity reconciliation, and expiry
settlement primitives. Phase 6 should add hedging, margin, and liquidation on
top of this accounting layer.

# Phase 2 - Pricing, IV, Greeks Status

Date: 2026-07-23

Branch: `feat/option-engine`

## Scope Completed

Phase 2 added deterministic option analytics primitives only. It does not add
option execution, ledger accounting, expiry handling, endpoint routing, or
Nautilus validation.

Implemented:

- `options/pricing.py`
  - linear Black-76 call/put pricing;
  - linear intrinsic value;
  - linear put-call parity value and residual;
  - inverse base-currency pricing;
  - inverse base-currency intrinsic;
  - inverse base-currency parity value and residual.
- `options/greeks.py`
  - `OptionGreeks`;
  - linear quote-currency Greeks;
  - inverse native base-currency Greeks;
  - inverse quote-reporting Greeks;
  - static reporting-currency scaling.
- `options/iv.py`
  - `IVStatus`;
  - `ImpliedVolResult`;
  - deterministic bisection solver for linear Black-76 IV;
  - deterministic bisection solver for inverse base-currency IV;
  - explicit invalid-price statuses.
- `options/surface.py`
  - `TotalVarianceSurface`;
  - `SurfaceDiagnostics`;
  - same-snapshot total variance calibration;
  - strike-then-expiry interpolation;
  - basic calendar total variance diagnostics.
- Public exports through `quantbt.options` and top-level `quantbt`.

## Domain Guarantees Locked

- Linear call-put parity holds:

```text
C - P = DF * (F - K)
```

- Inverse base-currency parity holds:

```text
C_base - P_base = DF * (1 - K / F)
```

- Inverse base option price equals linear quote option price divided by forward
  under the Phase 2 forward convention.
- IV recovers generated volatility for both linear and inverse prices.
- Invalid IV inputs return explicit status and `NaN` implied vol instead of a
  silent fallback.
- Analytic delta, gamma, and vega match finite-difference checks.
- Vega is internally represented per `1.0` volatility change; `vega_per_vol_point`
  exposes the reporting-scale value.
- Surface calibration rejects future timestamp rows and expired expiries.
- Phase 2 code contains no `fastmath=True`.
- `import quantbt` does not import `nautilus_trader`.

## Tests Run

Commands:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options __init__.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options
rg -n "fastmath" options tests/options
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.black76_price(100,100,1,0.2,'call') > 0; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase2_import_smoke=pass')"
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py
```

Results:

- compileall: pass.
- options tests: `31 passed`.
- fastmath scan: no matches.
- import smoke: `phase2_import_smoke=pass`.
- full non-real regression: `317 passed, 1 skipped, 3 warnings`.

Existing warnings are unrelated to options:

- one pandas runtime warning in a portfolio missing-data scenario;
- two matplotlib tight-layout warnings in walk-forward quick plot tests.

## Technical Debt

- Pricing and Greeks are scalar deterministic primitives. Vectorized or Numba
  kernels should wait until Phase 3/4 tape and execution shapes are stable.
- Inverse pricing uses the Phase 2 forward convention. Venue-exact option
  accounting still needs Deribit/Binance samples, fee schedules, settlement
  rules, and Nautilus parity.
- Theta holds forward and discount fixed. Full curve/rate theta attribution is
  deferred.
- Surface diagnostics are intentionally minimal. Butterfly convexity and full
  arbitrage-free surface fitting remain future work.
- IV uses auditable bisection. Faster Newton/hybrid methods may be added later
  only with deterministic parity tests.
- No option tape, selector, execution, ledger, endpoint, expiry, lifecycle, or
  Nautilus adapter behavior is implemented in Phase 2.

## Conclusion

Phase 2 is complete and safe to build on. QuantBT now has tested option
analytics primitives, but it is not yet an options backtest engine. Phase 3
must compile validated long-form chains into a no-lookahead ragged tape and
selection layer before execution logic is introduced.

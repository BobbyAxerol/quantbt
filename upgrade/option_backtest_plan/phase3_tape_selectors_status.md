# Phase 3 - Data Tape And Selectors Status

Date: 2026-07-23

Branch: `feat/option-engine`

## Scope Completed

Phase 3 added the option market-data tape and no-lookahead selector layer. It
does not add option execution, ledger accounting, expiry handling, endpoint
routing, or Nautilus validation.

Implemented:

- `options/tape.py`
  - `PreparedOptionTape`;
  - `OptionTapeSignature`;
  - `prepare_option_tape(...)`;
  - CSR-style snapshot arrays:
    - `timestamp_ns`;
    - `row_ptr`;
    - per-row instrument and market fields.
- `options/selectors.py`
  - `OptionSelectionFilters`;
  - `OptionSelection`;
  - `available_option_rows(...)`;
  - ATM selector;
  - target-delta selector;
  - target-DTE selector;
  - target-moneyness selector.
- Public exports through `quantbt.options` and top-level `quantbt`.

## Domain Guarantees Locked

- Canonical chain stays long-form; no dense bar-by-contract matrix is used.
- Prepared tape uses CSR-style ragged arrays.
- Chain instruments must exist in the registry.
- Chain static fields must match registry:
  - expiry;
  - strike;
  - option kind;
  - venue;
  - underlying;
  - quote currency;
  - settlement currency.
- Crossed quotes reject during canonical validation.
- Source latency can reject stale rows at tape preparation time.
- Decision-time quote age can reject stale snapshots at selector time.
- Selectors use the latest snapshot at or before the decision timestamp.
- Selectors reject decisions before the first observable snapshot.
- Expired contracts are filtered at decision time.
- Delta and IV selectors only use observable columns already present in the
  chain/tape.
- Prepared tape can validate registry, convention, and timestamp signatures.

## Tests Run

Commands:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -m compileall options __init__.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.prepare_option_tape; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase3_import_smoke=pass')"
rg -n "pivot|unstack|N_bars|dense|fastmath" options tests/options
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py
```

Results:

- compileall: pass.
- options tests: `43 passed`.
- import smoke: `phase3_import_smoke=pass`.
- dense/fastmath scan: no dense matrix construction and no `fastmath`.
- full non-real regression: `329 passed, 1 skipped, 3 warnings`.

Existing warnings are unrelated to options:

- one pandas runtime warning in a portfolio missing-data scenario;
- two matplotlib tight-layout warnings in walk-forward quick plot tests.

## Technical Debt

- Tape and selectors are array-first but selector scans are still Python/NumPy.
  Numba optimization should wait until Phase 4 execution/package shapes are
  finalized.
- Delta/IV selectors trust observable tape columns. Model-derived fallback
  Greeks/IV should be explicit and tagged in later phases, not implicit.
- Source latency and quote age checks are snapshot guards only, not L2 replay or
  queue-priority simulation.
- Tie-breaks currently use first minimum after canonical sort. If a strategy
  needs secondary ranking such as max OI or tightest spread, add explicit
  selector policy fields.
- No option package compiler, execution, ledger, expiry lifecycle, endpoint, or
  Nautilus validation is implemented in Phase 3.

## Conclusion

Phase 3 is complete and safe to build on. QuantBT now has validated long-form
option data, a ragged prepared tape, signatures, and no-lookahead selectors.
Phase 4 can now compile option packages and simulate fills against this tape.

# Options Engine Phase 9 Status

Status: completed at experimental constructor-pinned validation level.

## Scope

Phase 9 adds optional Nautilus option validation helpers. The implementation is
honest about its fidelity level: it pins Nautilus option constructors and BBO
quote matching semantics, but it does not claim full Nautilus option engine
replay yet.

## Implemented

- `adapters/nautilus/options.py`
  - `NautilusOptionValidationConfig`;
  - `NautilusOptionValidationResult`;
  - `inspect_nautilus_option_support`;
  - `make_nautilus_option_instrument`;
  - `build_nautilus_option_quote_table`;
  - `validate_option_packages_with_nautilus`.

- Exports through `quantbt.adapters.nautilus`.

- `docs/nautilus_backend.md`
  - documented the Phase 9 validation level;
  - documented why the route is experimental;
  - documented what is not yet full Nautilus engine parity.

- `QuantBTEndpoint.options_support_matrix()`
  - marks `nautilus_options` as experimental;
  - points to `validate_option_packages_with_nautilus`.

## Validation Level

Current label:

```text
constructor_pinned_quote_surrogate
```

Meaning:

- Nautilus is optional.
- Installed Nautilus version is inspected before use.
- Option constructors are checked and pinned before mapping.
- QuantBT option specs can be mapped to Nautilus `CryptoOption` or
  `OptionContract`.
- Option BBO rows are converted to a QuoteTick-equivalent audit table.
- Matching semantics are labelled explicitly:
  - market buy at ask;
  - market sell at bid;
  - limit fills only when BBO crosses the limit policy.
- Final accounting still uses the native QuantBT option backend.

## Component Parity

The report labels parity components separately:

- quantity;
- fill timestamp;
- fill price;
- fee;
- settlement;
- realized cashflow;
- final equity.

This avoids hiding execution/accounting differences inside a single final
equity tolerance.

## Tests

Added `tests/options/test_nautilus_options.py`.

Coverage:

- missing Nautilus returns a clear skipped validation result;
- constructor mapping and quote table;
- linear option round trip;
- inverse option constructor validation;
- two-leg spread;
- expiry settlement;
- fees/account artifacts;
- option plus underlying hedge labelled as future mixed-instrument replay.

Validation commands:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests/options
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run pytest -q tests --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha poetry run python -c "import sys, quantbt; assert quantbt.QuantBTEndpoint.options_support_matrix()['nautilus_options']['status'] == 'experimental'; assert not any(n.startswith('nautilus_trader') for n in sys.modules); print('phase9_import_smoke=pass')"
```

## Technical Debt

- Full Nautilus option engine replay with QuoteTick data ingestion is future
  work.
- `CryptoOptionSpread` and `OptionSpread` are inspected, but Phase 9 package
  validation still uses component option legs.
- Mixed underlying/perpetual + option package execution is labelled future
  work until a multi-instrument replay path is implemented.
- Venue-exact option margin and settlement still require venue adapter depth.

## Conclusion

Phase 9 is complete for its planned experimental validation level. It improves
trust by pinning Nautilus option instrument compatibility and making every
native-vs-Nautilus semantic comparison explicit, while avoiding the false claim
that full Nautilus option backtest-engine parity is already complete.

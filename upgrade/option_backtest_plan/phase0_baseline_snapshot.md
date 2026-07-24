# Options Engine Phase 0 Baseline Snapshot

Status: **pass**

Branch: `feat/option-engine`

Baseline commit before this artifact: `726e92d`

Date: `2026-07-23 UTC`

## Scope

Phase 0 is baseline protection only. No options engine code was added.

The purpose is to prove the current QuantBT state before Phase 1 touches schema
or conventions.

## Regression

Command:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha \
  poetry run pytest -q tests \
  --ignore=tests/test_real.py \
  --ignore=tests/test_real_endpoints.py
```

Result:

- passed: `286`
- skipped: `1`
- warnings: `3`
- status: `pass`

## Import Boundary

Import smoke:

- `import quantbt`: `pass`
- Python: `3.12.13`
- `nautilus_trader` imported as side effect: `false`

This preserves the required optional Nautilus boundary.

## Support Matrix Snapshot

Arbitrage:

- supported:
  - `BasisArbitrageSpec`
  - `StatArbPairSpec`
  - `CalendarSpreadSpec`
  - `FundingArbitrageSpec`
  - `SpotPerpCashCarrySpec`
  - `IndexBasketArbSpec`
- schema-only:
  - `CrossExchangeArbSpec`
  - `TriangularArbSpec`
  - `OptionsVolArbSpec`

Important options baseline:

```text
OptionsVolArbSpec.status = schema_only
OptionsVolArbSpec.backends = none
OptionsVolArbSpec.route = needs option/greeks engine
```

This is the expected pre-options-engine state. Phase 7 may later route
`OptionsVolArbSpec` through `native_option`, but generic arbitrage routes should
remain schema-only for this spec.

Nautilus:

- supported:
  - `signal_series`
  - `explicit_orders`
  - `parity_audit`
- experimental:
  - `dca_grid`
  - `bracket_oco`
  - `basket_pair`
  - `multi_symbol_portfolio`
  - `arbitrage_package_orders`

## Benchmark Snapshot

Command:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha \
  poetry run python benchmarks/run_phase16_performance_debt.py \
  --rows 720 \
  --symbols 4 \
  --replays 4 \
  --repeats 1 \
  --skip-large-wfo \
  --output-json /tmp/options_phase0_benchmark.json \
  --output-md /tmp/options_phase0_benchmark.md
```

Result:

| workload | normal | prepared/minimal | speedup | parity |
|---|---:|---:|---:|---|
| single `signal_notional` | `0.031234s` | `0.016127s` | `1.937x` | pass |
| native portfolio | `0.090314s` | `0.025911s` | `3.486x` | pass |
| portfolio reports | `0.042831s` full | `0.022004s` minimal | `1.946x` | pass |

## Acceptance

- Existing tests pass: `yes`
- No public endpoint regression observed: `yes`
- No import-time Nautilus dependency: `yes`
- Options engine code added: `no`

## Next Phase

Phase 1 should be the first code phase:

- `AssetType.OPTION`
- `options/schema.py`
- `options/conventions.py`
- `options/data.py`
- schema/convention tests only

Do not start pricing, endpoint wiring, or backend execution until Phase 1
schema/convention tests pass.

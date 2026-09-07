# Options P0 Correctness Containment

QuantBT V1.1 keeps options Python-primary. The supported route is
`QuantBTEndpoint.options(...)`; Rust-primary promotion is not claimed for any
option lifecycle, margin, or settlement policy.

## Supported Contract

The backend supports European cash-settled options with either:

- `PremiumConvention.LINEAR_QUOTE`; or
- `PremiumConvention.INVERSE_BASE` with explicit conversion rates.

The capability result is evaluated before option-chain preparation. The
following requests fail with an actionable `OptionCapabilityError.code`:

| Request | Code |
|---|---|
| American exercise without an authoritative model | `OPTION_EXERCISE_MODEL_REQUIRED` |
| Quanto premium/payoff | `OPTION_QUANTO_UNSUPPORTED` |
| Physical settlement | `OPTION_PHYSICAL_SETTLEMENT_UNSUPPORTED` |
| Future-then-cash without explicit research opt-in | `OPTION_FUTURE_SETTLEMENT_MODEL_REQUIRED` |
| Venue-exact margin without an external validator | `OPTION_VENUE_EXACT_MARGIN_VALIDATOR_REQUIRED` |

`OptionLimitFidelity.MAKER_TOUCH` and the opt-in future-then-cash economic
bridge remain visibly labelled `research_approximation`. They do not model L2
queue priority or a delivered-future lifecycle.

Inspect the same public matrix used by the endpoint:

```python
from quantbt import option_capability_registry_v1

matrix = option_capability_registry_v1()
```

## Financial Authority

Every package follows one sequence:

```text
observable BBO quote
-> authoritative per-leg fee
-> cloned OptionLedger preview
-> premium and fee cashflows
-> post-fill positions
-> initial-margin calculation
-> reporting-currency max-debit/min-credit guard
-> atomic commit or immutable rejection
```

`execute_option_package(...)` remains a snapshot quote simulator. Inside the
backend its provisional cash guard is disabled, then reapplied from the exact
fills and fee schedule that the `OptionLedger` commits. Rejected admission
leaves cash, positions, fees, realized PnL, and ledger events unchanged.

Package debit and credit guards are denominated in `reporting_currency`.
Passing another `package.metadata["guard_currency"]` fails closed in V1.1.

## Margin And Liquidation

`OptionMarginModel.STANDARD_VENUE_APPROX` and
`OptionMarginModel.SCENARIO_PM_APPROX` retain their approximation names.
`venue_exact_margin=True` is only valid when an
`OptionMarginModel.EXTERNAL_VALIDATOR` returns `venue_exact=True`.

Margin is evaluated after package admission, settlement, and every observable
market snapshot. A maintenance breach can liquidate open options at the
adverse bid/ask. `result.liquidated` is derived from those committed
liquidation fills, rather than inferred from final equity.

Useful evidence:

```python
result.metadata["margin_timeline_report"]
result.metadata["liquidation_report"]
result.metadata["accounting_reconciliation"]
```

## Settlement Contract

The default policy is `OptionSettlementPolicy.EXPLICIT_EVENTS_ONLY`.
Certified settlement provenance requires an official source and all relevant
timestamps:

```python
from quantbt import OptionSettlementEvent

event = OptionSettlementEvent(
    symbol="BTC-27SEP26-100000-C.DERIBIT",
    timestamp_ns=settlement_ns,
    settlement_price=103_250.0,
    source="deribit_delivery_price",
    source_timestamp_ns=settlement_ns,
    last_trading_timestamp_ns=last_trade_ns,
    expiry_timestamp_ns=expiry_ns,
    source_is_official=True,
)

result = endpoint.backtest(
    chain=chain,
    instruments=registry,
    packages=packages,
    settlement_events=[event],
)
```

Settlement before expiry, duplicate events, mismatched expiry provenance, and
orders at or after expiry fail before financial state changes.

The legacy `settle_expired=True` alias maps to
`legacy_last_tape_mark_research`. It is retained for compatibility, but result
metadata and `settlements_report` record:

```text
settlement_certified = false
settlement_fallback_used = true
source = last_tape_mark_research_fallback
```

It must not be used as exchange settlement evidence.

## Endpoint Configuration

```python
endpoint = QuantBTEndpoint.options(
    initial_capital=100_000,
    reporting_currency="USD",
    initial_balances={"USD": 100_000},
    conversion_rates={"BTC": 100_000},
    option_execution=execution,
    option_margin=margin,
    fee_schedule=fee_schedule,
    settlement_policy="explicit_events_only",
    require_venue_exact_margin=False,
    liquidate_on_maintenance_breach=True,
)
```

The result exposes the usual metrics/report helpers plus:

- `fills_report` with quoted and applied fees;
- `packages_report` with preflight debit, credit, equity, margin, and rejection;
- `ledger_event_report` and `accounting_reconciliation`;
- `margin_timeline_report` and `liquidation_report`;
- `settlements_report` with source/timestamp provenance;
- per-instrument `capability_assessments` and effective settlement policy.

The independent Phase 70 corpus covers European linear/inverse accounting,
fee reconciliation, immutable margin rejection, timeline liquidation,
official and fallback settlement, and unsupported capability rejection.

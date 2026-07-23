from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    ExerciseStyle,
    NativeOptionConfig,
    OptionInstrumentRegistry,
    OptionInstrumentSpec,
    OptionKind,
    OptionPackageIntent,
    OptionPackageLeg,
    OrderSide,
    PremiumConvention,
    QuantBTEndpoint,
    SettlementStyle,
    covered_call,
    vertical,
)
from quantbt.adapters.nautilus.options import (
    NautilusOptionValidationConfig,
    build_nautilus_option_quote_table,
    inspect_nautilus_option_support,
    make_nautilus_option_instrument,
    validate_option_packages_with_nautilus,
)


TS0 = int(pd.Timestamp("2026-01-01 00:00:00", tz="UTC").value)
TS1 = int(pd.Timestamp("2026-01-01 01:00:00", tz="UTC").value)
EXPIRY = int(pd.Timestamp("2026-02-01 08:00:00", tz="UTC").value)


def test_nautilus_option_missing_dependency_reports_skip(monkeypatch, linear_option_chain_registry):
    import quantbt.adapters.nautilus.options as options_adapter

    def missing():
        raise ImportError("forced missing nautilus")

    chain, registry = linear_option_chain_registry
    package = OptionPackageIntent(
        timestamp_ns=TS0,
        package_id="skip-case",
        legs=(OptionPackageLeg("BTC-C100.TEST", OrderSide.BUY, 1.0),),
    )
    monkeypatch.setattr(options_adapter, "require_nautilus", missing)

    result = validate_option_packages_with_nautilus(chain=chain, instruments=registry, packages=[package])

    assert result.status == "skipped_missing_nautilus"
    assert result.skipped
    assert "forced missing nautilus" in result.metadata["reason"]


def test_nautilus_option_constructor_mapping_and_quote_table(linear_option_chain_registry):
    support = inspect_nautilus_option_support()
    if not support["available"]:
        pytest.skip(support["reason"])

    chain, registry = linear_option_chain_registry
    instrument = make_nautilus_option_instrument(registry.by_symbol["BTC-C100.TEST"])
    table = build_nautilus_option_quote_table(chain, {"BTC-C100.TEST": instrument})

    assert support["constructor_pinned"]
    assert type(instrument).__name__ in {"CryptoOption", "OptionContract"}
    assert str(instrument.id).endswith(".TEST")
    assert table["matching_semantics"].str.contains("market_buy_at_ask").all()


def test_nautilus_option_linear_round_trip_validation(linear_option_chain_registry):
    chain, registry = linear_option_chain_registry
    packages = [
        OptionPackageIntent(TS0, "buy-call", (OptionPackageLeg("BTC-C100.TEST", OrderSide.BUY, 1.0),)),
        OptionPackageIntent(TS1, "sell-call", (OptionPackageLeg("BTC-C100.TEST", OrderSide.SELL, 1.0),)),
    ]

    validation = validate_option_packages_with_nautilus(
        chain=chain,
        instruments=registry,
        packages=packages,
        native_config=NativeOptionConfig(initial_balances={"USD": 20_000.0}, reporting_currency="USD"),
    )
    if validation.skipped:
        pytest.skip(validation.status)

    assert validation.status == "completed"
    assert validation.validation_level == "constructor_pinned_quote_surrogate"
    assert (validation.component_parity_report["status"] == "matched").all()
    assert len(validation.native_result.fills_report) == 2
    assert {"fills_report", "cash_report", "attribution_report"} <= set(validation.native_result.metadata)


def test_nautilus_option_inverse_constructor_validation(option_phase3_chain, option_phase3_registry):
    package = OptionPackageIntent(
        timestamp_ns=int(option_phase3_chain["timestamp_ns"].min()),
        package_id="inverse-call",
        legs=(OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", OrderSide.BUY, 1.0),),
    )

    validation = validate_option_packages_with_nautilus(
        chain=option_phase3_chain,
        instruments=option_phase3_registry,
        packages=[package],
        conversion_rates={"BTC": 100_000.0},
    )
    if validation.skipped:
        pytest.skip(validation.status)

    assert validation.instrument_report.loc[0, "class"] == "CryptoOption"
    assert validation.native_result.metadata["fill_count"] == 1


def test_nautilus_option_two_leg_spread_and_settlement(linear_option_chain_registry):
    chain, registry = linear_option_chain_registry
    package = vertical(TS0, "BTC-C100.TEST", "BTC-C110.TEST", package_id="call-vertical")

    validation = validate_option_packages_with_nautilus(
        chain=chain,
        instruments=registry,
        packages=[package],
        native_config=NativeOptionConfig(initial_balances={"USD": 20_000.0}, reporting_currency="USD"),
        settlement_events=[
            {
                "symbol": "BTC-C100.TEST",
                "timestamp_ns": EXPIRY,
                "settlement_price": 120_000.0,
            }
        ],
    )
    if validation.skipped:
        pytest.skip(validation.status)

    components = set(validation.component_parity_report["component"])
    assert {"quantity", "fill_price", "fee", "settlement", "realized_cashflow", "final_equity"} <= components
    assert len(validation.native_result.packages_report) == 1
    assert len(validation.native_result.settlements_report) == 1


def test_nautilus_option_underlying_delta_hedge_is_labelled_future_work(linear_option_chain_registry):
    chain, registry = linear_option_chain_registry
    package = covered_call(TS0, "BTC-PERP.TEST", "BTC-C110.TEST", package_id="covered-call")

    validation = validate_option_packages_with_nautilus(
        chain=chain,
        instruments=registry,
        packages=[package],
        native_config=NativeOptionConfig(initial_balances={"USD": 20_000.0}, reporting_currency="USD"),
    )
    if validation.skipped:
        pytest.skip(validation.status)

    hedge_rows = validation.component_parity_report[
        validation.component_parity_report["component"] == "underlying_delta_hedge"
    ]
    assert not hedge_rows.empty
    assert set(hedge_rows["status"]) == {"future_work"}


def test_endpoint_options_support_matrix_mentions_nautilus_phase9():
    matrix = QuantBTEndpoint.options_support_matrix()
    assert matrix["nautilus_options"]["status"] in {"future", "experimental"}


@pytest.fixture
def linear_option_chain_registry():
    registry = OptionInstrumentRegistry.from_iterable(
        [
            _linear_spec("BTC-C100.TEST", 100_000.0, OptionKind.CALL),
            _linear_spec("BTC-C110.TEST", 110_000.0, OptionKind.CALL),
            _linear_spec("BTC-P100.TEST", 100_000.0, OptionKind.PUT),
        ]
    )
    rows = []
    for ts, index_price, bump in ((TS0, 100_000.0, 0.0), (TS1, 104_000.0, 250.0)):
        rows.extend(
            [
                _row(ts, "BTC-C100.TEST", 100_000.0, "call", index_price, 2_000.0 + bump, 0),
                _row(ts, "BTC-C110.TEST", 110_000.0, "call", index_price, 1_000.0 + bump, 1),
                _row(ts, "BTC-P100.TEST", 100_000.0, "put", index_price, 1_800.0 + bump, 2),
            ]
        )
    return pd.DataFrame(rows), registry


def _linear_spec(symbol: str, strike: float, kind: OptionKind) -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol=symbol,
        venue="test",
        underlying_id="BTC-PERP.TEST",
        underlying_index_id="BTC-INDEX.TEST",
        option_kind=kind,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        settlement_style=SettlementStyle.CASH,
        strike=strike,
        expiry_ns=EXPIRY,
        settlement_currency="USD",
        premium_currency="USD",
        quote_currency="USD",
        multiplier=1.0,
        contract_size=1.0,
        qty_step=1.0,
        tick_size=0.01,
        convention_version="phase9_linear_v1",
    )


def _row(ts: int, symbol: str, strike: float, kind: str, index_price: float, mark: float, sequence_id: int) -> dict:
    return {
        "timestamp_ns": ts,
        "instrument_id": symbol,
        "venue": "TEST",
        "underlying_id": "BTC-PERP.TEST",
        "expiry_ns": EXPIRY,
        "strike": strike,
        "option_kind": kind,
        "bid_price": mark * 0.99,
        "bid_size": 10.0,
        "ask_price": mark * 1.01,
        "ask_size": 10.0,
        "mark_price": mark,
        "last_price": mark,
        "index_price": index_price,
        "forward_price": index_price,
        "mark_iv": 0.6,
        "bid_iv": 0.58,
        "ask_iv": 0.62,
        "delta": 0.5 if kind == "call" else -0.5,
        "gamma": 0.0001,
        "vega": 100.0,
        "theta": -10.0,
        "open_interest": 100.0,
        "volume": 25.0,
        "quote_currency": "USD",
        "settlement_currency": "USD",
        "sequence_id": sequence_id,
        "source_latency_ns": 1_000_000,
    }

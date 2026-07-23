from __future__ import annotations

import pandas as pd
import pytest

from quantbt import (
    ExerciseStyle,
    OptionInstrumentSpec,
    OptionKind,
    OptionLedger,
    OptionMarginConfig,
    OptionMarginModel,
    OptionMarginRequirement,
    PremiumConvention,
    SettlementStyle,
    calculate_option_margin,
    liquidate_option_positions,
)
from quantbt.core.orders import Fill
from quantbt.core.schema import LiquiditySide, OrderSide


def _linear_spec(symbol: str = "BTC-USDC-C", kind=OptionKind.CALL) -> OptionInstrumentSpec:
    return OptionInstrumentSpec(
        symbol=symbol,
        venue="deribit",
        underlying_id="BTC-PERP",
        underlying_index_id="BTC-INDEX",
        option_kind=kind,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        settlement_style=SettlementStyle.CASH,
        strike=100_000.0,
        expiry_ns=int(pd.Timestamp("2026-02-01 08:00:00", tz="UTC").value),
        settlement_currency="USDC",
        premium_currency="USDC",
        quote_currency="USDC",
    )


def test_phase6_long_premium_only_and_no_margin_research_models():
    spec = _linear_spec()
    ledger = OptionLedger.from_cash({"USDC": 10_000.0})
    ledger.apply_fill(
        Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.BUY, qty=2.0, price=100.0, liquidity=LiquiditySide.TAKER),
        spec,
        timestamp_ns=1,
    )
    instruments = {spec.symbol: spec}
    marks = {spec.symbol: 120.0}
    underlying = {spec.underlying_id: 100_000.0}

    long_margin = calculate_option_margin(
        ledger,
        instruments,
        marks,
        underlying,
        config=OptionMarginConfig(model=OptionMarginModel.LONG_PREMIUM_ONLY, maintenance_ratio=0.5),
        reporting_currency="USDC",
    )
    no_margin = calculate_option_margin(
        ledger,
        instruments,
        marks,
        underlying,
        config=OptionMarginConfig(model=OptionMarginModel.NO_MARGIN_RESEARCH),
        reporting_currency="USDC",
    )

    assert long_margin.initial_margin == pytest.approx(240.0)
    assert long_margin.maintenance_margin == pytest.approx(120.0)
    assert long_margin.venue_exact is False
    assert no_margin.initial_margin == pytest.approx(0.0)


def test_phase6_standard_and_scenario_margin_reports_venue_exact_false():
    spec = _linear_spec("BTC-USDC-P", OptionKind.PUT)
    ledger = OptionLedger.from_cash({"USDC": 0.0})
    ledger.apply_fill(
        Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.SELL, qty=1.0, price=100.0, liquidity=LiquiditySide.TAKER),
        spec,
        timestamp_ns=1,
    )
    instruments = {spec.symbol: spec}
    marks = {spec.symbol: 120.0}
    underlying = {spec.underlying_id: 100_000.0}

    standard = calculate_option_margin(
        ledger,
        instruments,
        marks,
        underlying,
        config=OptionMarginConfig(model="standard_venue_approx", short_option_margin_rate=0.10, maintenance_ratio=0.25),
        reporting_currency="USDC",
    )
    scenario = calculate_option_margin(
        ledger,
        instruments,
        marks,
        underlying,
        config=OptionMarginConfig(model="scenario_pm_approx", short_option_margin_rate=0.05, maintenance_ratio=0.25),
        reporting_currency="USDC",
    )

    assert standard.initial_margin == pytest.approx(10_000.0)
    assert standard.maintenance_margin == pytest.approx(2_500.0)
    assert standard.venue_exact is False
    assert bool(standard.detail_report.loc[0, "venue_exact"]) is False
    assert scenario.initial_margin >= 5_000.0
    assert scenario.metadata["venue_exact"] is False


def test_phase6_external_margin_validator_interface_is_explicit():
    class DummyValidator:
        def calculate_margin(self, ledger, instruments, marks, underlying_prices, reporting_currency, conversion_rates):
            return OptionMarginRequirement(
                initial_margin=123.0,
                maintenance_margin=12.3,
                model=OptionMarginModel.EXTERNAL_VALIDATOR,
                venue_exact=True,
                reporting_currency=reporting_currency,
                detail_report=pd.DataFrame([{"source": "dummy"}]),
            )

    result = calculate_option_margin(
        OptionLedger.from_cash({"USDC": 1_000.0}),
        {},
        {},
        {},
        config=OptionMarginConfig(model="external_validator"),
        reporting_currency="USDC",
        external_validator=DummyValidator(),
    )

    assert result.initial_margin == pytest.approx(123.0)
    assert result.venue_exact is True

    with pytest.raises(ValueError, match="external_validator"):
        calculate_option_margin(
            OptionLedger.from_cash({"USDC": 1_000.0}),
            {},
            {},
            {},
            config=OptionMarginConfig(model="external_validator"),
            reporting_currency="USDC",
        )


def test_phase6_liquidation_audit_explains_breach_orders_fees_final_state(option_phase3_registry):
    spec = option_phase3_registry.by_symbol["BTC-01FEB26-100000-C.DERIBIT"]
    ledger = OptionLedger.from_cash({"BTC": 0.0})
    ledger.apply_fill(
        Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.SELL, qty=1.0, price=0.01, liquidity=LiquiditySide.TAKER),
        spec,
        timestamp_ns=1,
    )
    margin = OptionMarginRequirement(
        initial_margin=10_000.0,
        maintenance_margin=1_000.0,
        model=OptionMarginModel.STANDARD_VENUE_APPROX,
        venue_exact=False,
        reporting_currency="USD",
        detail_report=pd.DataFrame(),
    )

    audit = liquidate_option_positions(
        ledger,
        {spec.symbol: spec},
        bid_prices={spec.symbol: 0.049},
        ask_prices={spec.symbol: 0.052},
        margin_requirement=margin,
        conversion_rates={"BTC": 100_000.0},
        reporting_currency="USD",
        timestamp_ns=2,
        fee_rate=0.001,
    )

    assert audit.breached is True
    assert audit.breach_reason == "maintenance_margin_breach"
    assert audit.equity_before < audit.maintenance_margin
    assert audit.final_positions == {}
    assert audit.liquidation_orders.loc[0, "side"] == "buy"
    assert audit.liquidation_orders.loc[0, "price"] == pytest.approx(0.052)
    assert audit.liquidation_orders.loc[0, "fee"] == pytest.approx(0.000052)
    assert audit.metadata["liquidation_sequence"] == "all_positions_adverse_bid_ask"
    assert ledger.positions[spec.symbol].is_flat


def test_phase6_liquidation_noops_when_equity_above_maintenance(option_phase3_registry):
    spec = option_phase3_registry.by_symbol["BTC-01FEB26-100000-C.DERIBIT"]
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    margin = OptionMarginRequirement(
        initial_margin=1.0,
        maintenance_margin=1.0,
        model=OptionMarginModel.NO_MARGIN_RESEARCH,
        venue_exact=False,
        reporting_currency="USD",
        detail_report=pd.DataFrame(),
    )

    audit = liquidate_option_positions(
        ledger,
        {spec.symbol: spec},
        bid_prices={spec.symbol: 0.01},
        ask_prices={spec.symbol: 0.02},
        margin_requirement=margin,
        conversion_rates={"BTC": 100_000.0},
        reporting_currency="USD",
        timestamp_ns=2,
    )

    assert audit.breached is False
    assert audit.liquidation_orders.empty
    assert audit.equity_after == pytest.approx(100_000.0)

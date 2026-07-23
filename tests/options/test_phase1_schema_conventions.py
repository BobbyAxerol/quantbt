from __future__ import annotations

import sys

import pandas as pd
import pytest

import quantbt
from quantbt import (
    AssetType,
    ExerciseStyle,
    OptionInstrumentRegistry,
    OptionInstrumentSpec,
    OptionKind,
    PremiumConvention,
    SettlementStyle,
    binance_european_options_convention,
    deribit_inverse_option_convention,
    deribit_linear_usdc_option_convention,
)


def _expiry_ns() -> int:
    return int(pd.Timestamp("2026-12-25 08:00:00", tz="UTC").value)


def test_phase1_import_quantbt_does_not_import_nautilus():
    assert quantbt.OptionInstrumentSpec is OptionInstrumentSpec
    assert not any(name.startswith("nautilus_trader") for name in sys.modules)


def test_phase1_option_asset_type_is_additive_to_core_schema():
    assert AssetType.OPTION.value == "option"
    assert AssetType.CRYPTO.value == "crypto"


def test_phase1_inverse_option_spec_requires_base_premium_and_settlement_currency():
    spec = OptionInstrumentSpec(
        symbol="BTC-25DEC26-100000-C.DERIBIT",
        venue="DERIBIT",
        underlying_id="BTC-PERPETUAL.DERIBIT",
        underlying_index_id="BTC-INDEX.DERIBIT",
        option_kind="call",
        exercise_style="european",
        premium_convention="inverse_base",
        settlement_style="cash",
        strike=100_000.0,
        expiry_ns=_expiry_ns(),
        settlement_currency="btc",
        premium_currency="BTC",
        quote_currency="USD",
        contract_size=1.0,
        multiplier=1.0,
        fee_schedule_id="deribit_btc_inverse_options",
        convention_version="deribit_inverse_v1",
    )

    assert spec.asset_type is AssetType.OPTION
    assert spec.option_kind is OptionKind.CALL
    assert spec.exercise_style is ExerciseStyle.EUROPEAN
    assert spec.premium_convention is PremiumConvention.INVERSE_BASE
    assert spec.settlement_style is SettlementStyle.CASH
    assert spec.venue == "deribit"
    assert spec.premium_currency == "BTC"
    assert spec.settlement_currency == "BTC"
    assert spec.quote_currency == "USD"


def test_phase1_linear_option_spec_rejects_wrong_premium_currency_and_physical_settlement():
    kwargs = dict(
        symbol="BTC-25DEC26-100000-P.DERIBIT",
        venue="deribit",
        underlying_id="BTC-PERPETUAL.DERIBIT",
        underlying_index_id="BTC-INDEX.DERIBIT",
        option_kind=OptionKind.PUT,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        strike=100_000.0,
        expiry_ns=_expiry_ns(),
        settlement_currency="USDC",
        quote_currency="USDC",
    )
    with pytest.raises(ValueError, match="premium_currency == quote_currency"):
        OptionInstrumentSpec(**kwargs, settlement_style=SettlementStyle.CASH, premium_currency="BTC")

    with pytest.raises(ValueError, match="cannot use physical settlement"):
        OptionInstrumentSpec(**kwargs, settlement_style=SettlementStyle.PHYSICAL, premium_currency="USDC")


def test_phase1_option_quantity_step_alias_normalizes_with_lot_size():
    spec_from_qty_step = OptionInstrumentSpec(
        symbol="BTC-QTY-STEP",
        venue="deribit",
        underlying_id="BTC-PERP",
        underlying_index_id="BTC-INDEX",
        option_kind=OptionKind.CALL,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.INVERSE_BASE,
        settlement_style=SettlementStyle.CASH,
        strike=100_000.0,
        expiry_ns=_expiry_ns(),
        settlement_currency="BTC",
        premium_currency="BTC",
        quote_currency="USD",
        qty_step=0.1,
    )
    assert spec_from_qty_step.lot_size == 0.1
    assert spec_from_qty_step.qty_step == 0.1

    spec_from_lot_size = OptionInstrumentSpec(
        symbol="BTC-LOT-SIZE",
        venue="deribit",
        underlying_id="BTC-PERP",
        underlying_index_id="BTC-INDEX",
        option_kind=OptionKind.CALL,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.INVERSE_BASE,
        settlement_style=SettlementStyle.CASH,
        strike=100_000.0,
        expiry_ns=_expiry_ns(),
        settlement_currency="BTC",
        premium_currency="BTC",
        quote_currency="USD",
        lot_size=0.2,
    )
    assert spec_from_lot_size.lot_size == 0.2
    assert spec_from_lot_size.qty_step == 0.2

    with pytest.raises(ValueError, match="qty_step must match lot_size"):
        OptionInstrumentSpec(
            symbol="BTC-BAD-STEP",
            venue="deribit",
            underlying_id="BTC-PERP",
            underlying_index_id="BTC-INDEX",
            option_kind=OptionKind.CALL,
            exercise_style=ExerciseStyle.EUROPEAN,
            premium_convention=PremiumConvention.INVERSE_BASE,
            settlement_style=SettlementStyle.CASH,
            strike=100_000.0,
            expiry_ns=_expiry_ns(),
            settlement_currency="BTC",
            premium_currency="BTC",
            quote_currency="USD",
            lot_size=0.1,
            qty_step=0.2,
        )


def test_phase1_option_registry_signature_is_stable_and_rejects_duplicates():
    call = OptionInstrumentSpec(
        symbol="BTC-C",
        venue="deribit",
        underlying_id="BTC-PERP",
        underlying_index_id="BTC-INDEX",
        option_kind=OptionKind.CALL,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.INVERSE_BASE,
        settlement_style=SettlementStyle.CASH,
        strike=100_000.0,
        expiry_ns=_expiry_ns(),
        settlement_currency="BTC",
        premium_currency="BTC",
        quote_currency="USD",
        convention_version="v1",
    )
    put = OptionInstrumentSpec(
        symbol="BTC-P",
        venue="deribit",
        underlying_id="BTC-PERP",
        underlying_index_id="BTC-INDEX",
        option_kind=OptionKind.PUT,
        exercise_style=ExerciseStyle.EUROPEAN,
        premium_convention=PremiumConvention.INVERSE_BASE,
        settlement_style=SettlementStyle.CASH,
        strike=90_000.0,
        expiry_ns=_expiry_ns(),
        settlement_currency="BTC",
        premium_currency="BTC",
        quote_currency="USD",
        convention_version="v1",
    )

    registry = OptionInstrumentRegistry((put, call))
    assert registry.symbols == ("BTC-P", "BTC-C")
    assert registry.by_symbol["BTC-C"] is call
    assert registry.signature.symbols == ("BTC-C", "BTC-P")
    assert registry.signature.convention_versions == ("v1", "v1")

    with pytest.raises(ValueError, match="unique"):
        OptionInstrumentRegistry((call, call))


def test_phase1_venue_conventions_are_versioned_and_do_not_claim_exact_margin():
    inverse = deribit_inverse_option_convention(underlying="BTC")
    linear = deribit_linear_usdc_option_convention(underlying="ETH")
    binance = binance_european_options_convention(underlying="BTC")

    assert inverse.premium_convention is PremiumConvention.INVERSE_BASE
    assert inverse.premium_currency == "BTC"
    assert inverse.settlement_currency == "BTC"
    assert inverse.quote_currency == "USD"
    assert inverse.exact_venue_margin is False

    assert linear.premium_convention is PremiumConvention.LINEAR_QUOTE
    assert linear.premium_currency == "USDC"
    assert linear.settlement_style is SettlementStyle.FUTURE_THEN_CASH
    assert linear.exact_venue_margin is False

    assert binance.venue == "binance"
    assert binance.premium_currency == "USDT"
    assert binance.exact_venue_margin is False

    with pytest.raises(ValueError, match="BTC or ETH"):
        deribit_inverse_option_convention(underlying="SOL")

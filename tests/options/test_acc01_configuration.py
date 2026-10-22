"""ACC-01 F06/F07/F14 finite and supported-configuration boundaries."""

from dataclasses import replace

import pandas as pd
import pytest

from quantbt import (
    AccountConfig, GammaScalpingConfig, NativeOptionConfig, OptionCapabilityError, OptionExecutionConfig,
    OptionFeeResult, OptionFeeSchedule, OptionHedgeConfig, OptionLedger,
    OptionMarginConfig, OptionMarginModel, OptionMarginRequirement, OptionSettlementEvent,
    calculate_option_fee, calculate_option_margin,
)
from quantbt.core.orders import Fill
from quantbt.core.schema import ExecutionConfig, FillPricePolicy, MarginMode, OmsMode, OrderSide, SameBarPolicy


@pytest.mark.parametrize("overrides", [
    {"margin_mode": MarginMode.ISOLATED}, {"margin_mode": MarginMode.CASH},
    {"margin_mode": MarginMode.PORTFOLIO}, {"oms_mode": OmsMode.HEDGING},
    {"leverage": 2.0}, {"maintenance_ratio": 0.1}, {"base_currency": "BTC"},
])
def test_f06_generic_option_account_nondefaults_are_rejected(overrides):
    with pytest.raises(OptionCapabilityError, match=r"account\."):
        NativeOptionConfig(account=AccountConfig(initial_capital=20_000.0, **overrides))


@pytest.mark.parametrize("overrides", [
    {"fill_price_policy": FillPricePolicy.OPEN}, {"fill_price_policy": FillPricePolicy.NEXT_OPEN},
    {"slippage_bps": 1_000.0}, {"min_order_notional": 1e9},
    {"allow_partial_fill": True}, {"reject_on_insufficient_margin": False},
    {"same_bar_policy": SameBarPolicy.ENTRY_FIRST},
])
def test_f06_generic_option_execution_nondefaults_are_rejected(overrides):
    with pytest.raises(OptionCapabilityError, match=r"execution\."):
        NativeOptionConfig(execution=ExecutionConfig(**overrides))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["maintenance_ratio", "long_option_margin_rate", "short_option_margin_rate", "liquidation_fee_rate"])
def test_f07_nonfinite_margin_config_rejected(bad, field):
    with pytest.raises(ValueError, match=field):
        OptionMarginConfig(**{field: bad})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_f07_nonfinite_scenarios_rejected(bad):
    with pytest.raises(ValueError, match="scenario_shocks"):
        OptionMarginConfig(scenario_shocks=(-0.2, bad, 0.2))


@pytest.mark.parametrize("field,value", [
    ("initial_margin", float("nan")), ("maintenance_margin", float("inf")),
    ("initial_margin", -1.0), ("maintenance_margin", -1.0),
    ("reporting_currency", "BTC"), ("venue_exact", "yes"),
])
def test_f07_external_margin_output_validated_without_mutating_ledger(field, value):
    requirement = OptionMarginRequirement(10.0, 2.0, OptionMarginModel.EXTERNAL_VALIDATOR, True, "USD", pd.DataFrame())
    # An external implementation can return a corrupted/mutable requirement.
    object.__setattr__(requirement, field, value)

    class Validator:
        def calculate_margin(self, ledger, *args):
            ledger.cash["USD"] = 0.0
            return requirement

    ledger = OptionLedger.from_cash({"USD": 1_000.0})
    before = ledger.clone()
    with pytest.raises(ValueError):
        calculate_option_margin(ledger, {}, {}, {}, config=OptionMarginConfig(model="external_validator"), external_validator=Validator())
    assert ledger == before


def test_f07_existing_standard_and_scenario_formula_is_unchanged(option_phase3_registry):
    original = option_phase3_registry.by_symbol["BTC-01FEB26-100000-C.DERIBIT"]
    spec = replace(original, multiplier=2.0, contract_size=2.0)
    ledger = OptionLedger.from_cash({"USD": 100_000.0})
    ledger.apply_fill(Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.SELL, qty=1.0, price=0.02), spec)
    args = (ledger, {spec.symbol: spec}, {spec.symbol: 0.02}, {spec.underlying_id: 100_000.0})
    standard = calculate_option_margin(*args, conversion_rates={"BTC": 100_000.0})
    scenario = calculate_option_margin(*args, conversion_rates={"BTC": 100_000.0},
                                       config=OptionMarginConfig(model="scenario_pm_approx"))
    assert standard.initial_margin == pytest.approx(30_000.0)
    assert standard.maintenance_margin == pytest.approx(6_000.0)
    # Preserve the existing scenario approximation's base-currency conversion.
    assert scenario.initial_margin == pytest.approx(3_000_000_000.0)
    assert standard.venue_exact is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["maker_rate", "taker_rate", "per_contract_fee", "cap_premium_fraction"])
def test_f14_nonfinite_fee_schedules_rejected(bad, field):
    with pytest.raises(ValueError, match=field):
        OptionFeeSchedule(schedule_id="synthetic", fee_currency="USD", **{field: bad})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["fee", "raw_fee", "cap"])
def test_f14_nonfinite_applied_fee_results_rejected(bad, field):
    values = dict(fee=0.0, raw_fee=0.0, cap=0.0, currency="USD", capped=False, schedule_id="synthetic")
    values[field] = bad
    with pytest.raises(ValueError, match=field):
        OptionFeeResult(**values)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_f14_nonfinite_cash_fx_execution_and_settlement_admission(bad):
    factories = [
        lambda: OptionLedger.from_cash({"USD": bad}),
        lambda: NativeOptionConfig(initial_balances={"USD": bad}),
        lambda: NativeOptionConfig(conversion_rates={"BTC": bad}),
        lambda: OptionExecutionConfig(fee_rate=bad),
        lambda: OptionExecutionConfig(initial_cash=bad),
        lambda: OptionHedgeConfig(target_delta=bad),
        lambda: OptionSettlementEvent(symbol="synthetic", timestamp_ns=1, settlement_price=bad),
    ]
    for factory in factories:
        with pytest.raises(ValueError, match="finite"):
            factory()


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -1.0])
def test_f14_invalid_used_fx_cannot_claim_reconciled(bad):
    ledger = OptionLedger.from_cash({"BTC": -0.1, "USD": 20_000.0})
    with pytest.raises(ValueError):
        ledger.equity_identity_report(conversion_rates={"BTC": bad})


def test_f14_signed_wallet_and_missing_conversion_contract():
    ledger = OptionLedger.from_cash({"BTC": -0.1, "USD": 20_000.0})
    assert ledger.equity(conversion_rates={"BTC": 100_000.0}) == pytest.approx(10_000.0)
    with pytest.raises(ValueError, match="missing conversion rate"):
        ledger.equity(conversion_rates={})
    ledger.fees["BTC"] = float("nan")
    with pytest.raises(ValueError, match="finite"):
        ledger.equity_identity_report(conversion_rates={"BTC": 100_000.0})


@pytest.mark.parametrize("field", ["threshold", "enter_band", "exit_band", "rebalance_interval_ns", "realized_vol_window",
                                  "realized_vol_multiplier", "min_band", "hedge_contract_multiplier"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_f14_nonfinite_hedge_configuration_rejected(field, bad):
    with pytest.raises(ValueError, match="finite"):
        OptionHedgeConfig(**{field: bad})


@pytest.mark.parametrize("field", ["quantity", "min_dte_days", "max_dte_days", "roll_dte_days", "max_spread_bps",
                                  "min_bid_size", "min_ask_size", "min_volume", "min_open_interest"])
def test_f14_nonfinite_strategy_configuration_rejected(field):
    with pytest.raises(ValueError, match="finite"):
        GammaScalpingConfig(**{field: float("nan")})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -1.0])
def test_f14_fee_reference_price_must_be_finite_positive(option_phase3_registry, bad):
    spec = option_phase3_registry.by_symbol["BTC-01FEB26-100000-C.DERIBIT"]
    fill = Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.BUY, qty=1.0, price=0.02)
    schedule = OptionFeeSchedule(schedule_id="synthetic", fee_currency="BTC", premium_convention="inverse_base")
    with pytest.raises(ValueError, match="reference_price"):
        calculate_option_fee(fill, spec, schedule, reference_price=bad)


def test_f14_identity_requires_all_held_marks(option_phase3_registry):
    spec = option_phase3_registry.instruments[0]
    ledger = OptionLedger.from_cash({"BTC": 1.0})
    ledger.apply_fill(Fill(timestamp=1, symbol=spec.symbol, side=OrderSide.BUY, qty=1.0, price=0.02), spec)
    with pytest.raises(ValueError, match="missing mark"):
        ledger.equity_identity_report(conversion_rates={"BTC": 100_000.0}, marks={}, instruments={spec.symbol: spec})

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from quantbt import (
    AccountConfig,
    ExerciseStyle,
    NativeOptionBackend,
    NativeOptionConfig,
    OptionCapabilityError,
    OptionExecutionConfig,
    OptionInstrumentRegistry,
    OptionMarginConfig,
    OptionPackageIntent,
    OptionPackageLeg,
    OptionSettlementEvent,
    OptionSettlementPolicy,
    OrderSide,
    PremiumConvention,
    SettlementStyle,
    deribit_inverse_fee_schedule,
    option_capability_registry_v1,
    prepare_option_tape,
)


def _single_inverse(option_phase3_chain, option_phase3_registry):
    symbol = "BTC-01FEB26-100000-C.DERIBIT"
    instrument = option_phase3_registry.by_symbol[symbol]
    chain = option_phase3_chain.loc[option_phase3_chain["instrument_id"] == symbol].copy()
    return chain, OptionInstrumentRegistry.from_iterable([instrument]), instrument


def _package(instrument, *, side=OrderSide.BUY, package_id="pkg", max_debit=None, min_credit=None):
    return OptionPackageIntent(
        timestamp_ns=1,
        package_id=package_id,
        legs=(OptionPackageLeg(instrument_id=instrument.symbol, side=side, ratio=1.0),),
        max_debit=max_debit,
        min_credit=min_credit,
    )


def _at_first_snapshot(package, chain):
    return replace(package, timestamp_ns=int(chain["timestamp_ns"].min()))


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("exercise_style", ExerciseStyle.AMERICAN, "OPTION_EXERCISE_MODEL_REQUIRED"),
        ("premium_convention", PremiumConvention.QUANTO, "OPTION_QUANTO_UNSUPPORTED"),
        ("settlement_style", SettlementStyle.PHYSICAL, "OPTION_PHYSICAL_SETTLEMENT_UNSUPPORTED"),
    ],
)
def test_phase70_unsupported_contracts_fail_before_tape_prepare(
    option_phase3_chain,
    option_phase3_registry,
    monkeypatch,
    field,
    value,
    code,
):
    chain, _, instrument = _single_inverse(option_phase3_chain, option_phase3_registry)
    unsupported = replace(instrument, **{field: value})
    registry = OptionInstrumentRegistry.from_iterable([unsupported])

    def fail_if_called(*args, **kwargs):
        raise AssertionError("market tape must not be prepared for an unsupported capability")

    monkeypatch.setattr("quantbt.backends.native_option.prepare_option_tape", fail_if_called)
    with pytest.raises(OptionCapabilityError) as exc_info:
        NativeOptionBackend().run(chain=chain, instruments=registry)

    assert exc_info.value.code == code


def test_phase70_european_linear_and_inverse_paths_are_explicitly_supported(
    option_phase3_chain,
    option_phase3_registry,
):
    inverse_chain, inverse_registry, inverse = _single_inverse(option_phase3_chain, option_phase3_registry)
    inverse_result = NativeOptionBackend(
        NativeOptionConfig(
            account=AccountConfig(initial_capital=20_000.0),
            initial_balances={"USD": 20_000.0},
            conversion_rates={"BTC": 100_000.0},
        )
    ).run(
        chain=inverse_chain,
        instruments=inverse_registry,
        packages=[_at_first_snapshot(_package(inverse, package_id="inverse"), inverse_chain)],
    )

    linear = replace(
        inverse,
        premium_convention=PremiumConvention.LINEAR_QUOTE,
        premium_currency="USD",
        settlement_currency="USD",
        quote_currency="USD",
        convention_version="linear_test_v1",
    )
    linear_chain = inverse_chain.copy()
    for column in ("bid_price", "ask_price", "mark_price", "last_price"):
        linear_chain[column] = linear_chain[column] * 1_000.0
    linear_chain["settlement_currency"] = "USD"
    linear_registry = OptionInstrumentRegistry.from_iterable([linear])
    linear_result = NativeOptionBackend(
        NativeOptionConfig(
            account=AccountConfig(initial_capital=20_000.0),
            initial_balances={"USD": 20_000.0},
        )
    ).run(
        chain=linear_chain,
        instruments=linear_registry,
        packages=[_at_first_snapshot(_package(linear, package_id="linear"), linear_chain)],
    )

    assert inverse_result.metadata["capability_assessments"][0]["status"] == "certified"
    assert linear_result.metadata["capability_assessments"][0]["status"] == "certified"
    assert inverse_result.metadata["accounting_reconciliation"]["reconciled"] is True
    assert linear_result.metadata["accounting_reconciliation"]["reconciled"] is True
    assert inverse_result.equity.iloc[-1] == pytest.approx(19_950.0)
    assert linear_result.equity.iloc[-1] == pytest.approx(19_999.5)


def test_phase70_fee_schedule_drives_guard_ledger_fill_and_result(
    option_phase3_chain,
    option_phase3_registry,
):
    chain, registry, instrument = _single_inverse(option_phase3_chain, option_phase3_registry)
    schedule = deribit_inverse_fee_schedule(per_contract_fee=0.0003)
    config = NativeOptionConfig(
        account=AccountConfig(initial_capital=20_000.0),
        option_execution=OptionExecutionConfig(fee_rate=0.0),
        fee_schedule=schedule,
        initial_balances={"USD": 20_000.0},
        conversion_rates={"BTC": 100_000.0},
    )
    rejected = NativeOptionBackend(config).run(
        chain=chain,
        instruments=registry,
        packages=[_at_first_snapshot(_package(instrument, package_id="guard-reject", max_debit=2_120.0), chain)],
    )
    accepted = NativeOptionBackend(config).run(
        chain=chain,
        instruments=registry,
        packages=[_at_first_snapshot(_package(instrument, package_id="guard-accept", max_debit=2_140.0), chain)],
    )

    assert rejected.fills_report.empty
    assert rejected.packages_report.loc[0, "reject_reason"] == "MAX_DEBIT_EXCEEDED"
    assert rejected.packages_report.loc[0, "preflight_debit"] == pytest.approx(2_130.0)
    assert rejected.metadata["ledger_event_report"].empty
    assert rejected.equity.iloc[-1] == pytest.approx(20_000.0)

    assert accepted.fills_report.loc[0, "applied_fee"] == pytest.approx(0.0003)
    assert accepted.fills_report.loc[0, "fee_currency"] == "BTC"
    assert accepted.packages_report.loc[0, "net_cash_delta"] == pytest.approx(-2_130.0)
    assert accepted.metadata["accounting_reconciliation"]["reconciled"] is True
    assert accepted.metadata["accounting_reconciliation"]["per_currency"]["BTC"]["ledger"] == pytest.approx(0.0003)


def test_phase70_post_cost_margin_rejection_is_immutable(
    option_phase3_chain,
    option_phase3_registry,
):
    chain, registry, instrument = _single_inverse(option_phase3_chain, option_phase3_registry)
    result = NativeOptionBackend(
        NativeOptionConfig(
            account=AccountConfig(initial_capital=1_000.0),
            initial_balances={"USD": 1_000.0},
            conversion_rates={"BTC": 100_000.0},
        )
    ).run(
        chain=chain,
        instruments=registry,
        packages=[_at_first_snapshot(_package(instrument, package_id="margin-reject"), chain)],
    )

    report = result.packages_report.iloc[0]
    assert report["reject_reason"] == "POST_COST_MARGIN"
    assert report["preflight_available_collateral"] < 0.0
    assert result.fills_report.empty
    assert result.metadata["ledger_event_report"].empty
    assert result.equity.iloc[-1] == pytest.approx(1_000.0)


def test_phase70_maintenance_breach_liquidates_from_market_timeline(
    option_phase3_chain,
    option_phase3_registry,
):
    chain, registry, instrument = _single_inverse(option_phase3_chain, option_phase3_registry)
    second_timestamp = int(chain["timestamp_ns"].max())
    second = chain["timestamp_ns"] == second_timestamp
    chain.loc[second, "bid_price"] = 0.24
    chain.loc[second, "ask_price"] = 0.26
    chain.loc[second, "mark_price"] = 0.25
    chain.loc[second, "last_price"] = 0.25
    result = NativeOptionBackend(
        NativeOptionConfig(
            account=AccountConfig(initial_capital=20_000.0),
            margin=OptionMarginConfig(maintenance_ratio=0.20, short_option_margin_rate=0.15),
            initial_balances={"USD": 20_000.0},
            conversion_rates={"BTC": 100_000.0},
        )
    ).run(
        chain=chain,
        instruments=registry,
        packages=[_at_first_snapshot(_package(instrument, side=OrderSide.SELL, package_id="short"), chain)],
    )

    assert result.liquidated is True
    assert result.metadata["liquidated_from_timeline"] is True
    assert result.metadata["liquidation_count"] == 1
    assert len(result.fills_report) == 2
    assert bool(result.fills_report.iloc[-1]["liquidation"]) is True
    assert result.positions.iloc[-1][f"Position_{instrument.symbol}"] == pytest.approx(0.0)
    assert result.metadata["liquidation_report"].loc[0, "breach_reason"] == "maintenance_margin_breach"


def test_phase70_explicit_settlement_provenance_and_duplicate_guard(
    option_phase3_chain,
    option_phase3_registry,
):
    chain, registry, instrument = _single_inverse(option_phase3_chain, option_phase3_registry)
    package = _at_first_snapshot(_package(instrument, package_id="settle"), chain)
    event = OptionSettlementEvent(
        symbol=instrument.symbol,
        timestamp_ns=instrument.expiry_ns,
        settlement_price=105_000.0,
        source="deribit_delivery_price",
        source_timestamp_ns=instrument.expiry_ns,
        last_trading_timestamp_ns=int(chain["timestamp_ns"].max()),
        expiry_timestamp_ns=instrument.expiry_ns,
        source_is_official=True,
    )
    backend = NativeOptionBackend(
        NativeOptionConfig(
            account=AccountConfig(initial_capital=20_000.0),
            initial_balances={"USD": 20_000.0},
            conversion_rates={"BTC": 100_000.0},
        )
    )
    result = backend.run(chain=chain, instruments=registry, packages=[package], settlement_events=[event])

    assert len(result.settlements_report) == 1
    assert result.settlements_report.loc[0, "source"] == "deribit_delivery_price"
    assert result.settlements_report.loc[0, "provenance_status"] == "official_source"
    assert result.metadata["settlement_certified"] is True
    assert result.positions.iloc[-1][f"Position_{instrument.symbol}"] == pytest.approx(0.0)
    assert result.equity.index.is_monotonic_increasing
    assert result.equity.index[-1] == pd.Timestamp(instrument.expiry_ns, unit="ns")

    with pytest.raises(OptionCapabilityError) as exc_info:
        backend.run(chain=chain, instruments=registry, packages=[package], settlement_events=[event, event])
    assert exc_info.value.code == "OPTION_SETTLEMENT_DUPLICATE_EVENT"


def test_phase70_legacy_last_tape_settlement_is_visibly_non_certified(
    option_phase3_chain,
    option_phase3_registry,
):
    chain, _, instrument = _single_inverse(option_phase3_chain, option_phase3_registry)
    registry = OptionInstrumentRegistry.from_iterable([instrument])
    prepared_tape = prepare_option_tape(chain, registry)
    # A synthetic post-expiry terminal snapshot exercises the retained legacy
    # fallback without weakening canonical-chain validation for ordinary users.
    prepared_tape.timestamp_ns[-1] = int(instrument.expiry_ns)
    result = NativeOptionBackend(
        NativeOptionConfig(
            account=AccountConfig(initial_capital=20_000.0),
            initial_balances={"USD": 20_000.0},
            conversion_rates={"BTC": 100_000.0},
            settle_expired=True,
        )
    ).run(
        chain=chain,
        instruments=registry,
        packages=[_at_first_snapshot(_package(instrument, package_id="legacy-settle"), chain)],
        prepared_tape=prepared_tape,
    )

    assert result.metadata["settlement_policy"] == OptionSettlementPolicy.LEGACY_LAST_TAPE_MARK_RESEARCH.value
    assert result.metadata["settlement_fallback_used"] is True
    assert result.metadata["settlement_certified"] is False
    assert result.settlements_report.loc[0, "source"] == "last_tape_mark_research_fallback"
    assert bool(result.settlements_report.loc[0, "fallback"]) is True


def test_phase70_capability_registry_is_public_and_truthful():
    registry = option_capability_registry_v1()

    assert registry["european_linear_cash"]["status"] == "certified"
    assert registry["european_inverse_cash"]["status"] == "certified"
    assert registry["american_exercise_assignment"]["status"] == "unsupported"
    assert registry["quanto"]["status"] == "unsupported"
    assert registry["physical_settlement"]["status"] == "unsupported"

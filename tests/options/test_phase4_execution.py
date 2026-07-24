from __future__ import annotations

import pytest

from quantbt import (
    OptionExecutionConfig,
    OptionLimitFidelity,
    OptionPackageExecutionPolicy,
    OptionPackageIntent,
    OptionPackageLeg,
    prepare_option_tape,
    execute_option_package,
)


def _package(timestamp_ns: int, *legs: OptionPackageLeg, policy=OptionPackageExecutionPolicy.ATOMIC_ALL_OR_NONE, **kwargs):
    return OptionPackageIntent(
        timestamp_ns=timestamp_ns,
        package_id=kwargs.pop("package_id", "pkg"),
        quantity=kwargs.pop("quantity", 1.0),
        execution_policy=policy,
        legs=tuple(legs),
        **kwargs,
    )


def test_phase4_market_fills_use_ask_for_buy_and_bid_for_sell(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    ts = int(tape.timestamp_ns[0])
    package = _package(
        ts,
        OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", "buy", 1.0),
        OptionPackageLeg("BTC-01FEB26-110000-P.DERIBIT", "sell", 1.0),
        policy=OptionPackageExecutionPolicy.BEST_EFFORT,
    )

    result = execute_option_package(package, tape, config=OptionExecutionConfig(initial_cash=10.0))

    assert len(result.fills) == 2
    buy = result.order_report.loc[result.order_report["side"] == "buy"].iloc[0]
    sell = result.order_report.loc[result.order_report["side"] == "sell"].iloc[0]
    assert buy["fill_price"] == pytest.approx(0.021)
    assert sell["fill_price"] == pytest.approx(0.030)
    assert buy["fill_price"] != pytest.approx((0.020 + 0.021) / 2.0)
    assert bool(result.package_report.loc[0, "exchange_combo"]) is False
    assert bool(result.package_report.loc[0, "block_trade_style"]) is False


def test_phase4_atomic_all_or_none_rolls_back_on_leg_failure(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    ts = int(tape.timestamp_ns[0])
    package = _package(
        ts,
        OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", "buy", 1.0),
        OptionPackageLeg("BTC-01FEB26-110000-P.DERIBIT", "sell", 100.0),
        quantity=1.0,
        policy=OptionPackageExecutionPolicy.ATOMIC_ALL_OR_NONE,
    )

    result = execute_option_package(package, tape, config=OptionExecutionConfig(initial_cash=10.0))

    assert len(result.fills) == 0
    assert result.cash == 10.0
    assert result.positions == {}
    assert set(result.order_report["status"]) == {"rejected"}
    assert result.package_report.loc[0, "status"] == "rejected"
    assert result.package_report.loc[0, "atomicity"] == "simulated_atomic_all_or_none"
    assert result.margin_report["position_count"] == 0


def test_phase4_ioc_partial_reports_residual_risk(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    ts = int(tape.timestamp_ns[0])
    package = _package(
        ts,
        OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", "buy", 20.0, tif="ioc"),
        policy=OptionPackageExecutionPolicy.BEST_EFFORT,
    )

    result = execute_option_package(package, tape, config=OptionExecutionConfig(initial_cash=10.0, allow_partial_fill=True))
    row = result.order_report.iloc[0]

    assert len(result.fills) == 1
    assert row["status"] == "partial"
    assert row["filled_qty"] == pytest.approx(12.0)
    assert row["residual_qty"] == pytest.approx(8.0)
    assert bool(row["residual_risk"]) is True
    assert result.package_report.loc[0, "status"] == "partial"


def test_phase4_debit_guard_rejects_without_mutating_state(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    ts = int(tape.timestamp_ns[0])
    package = _package(
        ts,
        OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", "buy", 1.0),
        policy=OptionPackageExecutionPolicy.BEST_EFFORT,
        max_debit=0.001,
    )

    result = execute_option_package(package, tape, config=OptionExecutionConfig(initial_cash=10.0))

    assert len(result.fills) == 0
    assert result.cash == 10.0
    assert result.positions == {}
    assert result.package_report.loc[0, "reject_reason"] == "max_debit_exceeded"


def test_phase4_limit_fidelity_modes_are_explicit(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    ts = int(tape.timestamp_ns[0])
    passive = _package(
        ts,
        OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", "buy", 1.0, order_type="limit", limit_price=0.0205, tif="gtc"),
        policy=OptionPackageExecutionPolicy.BEST_EFFORT,
    )

    cross_only = execute_option_package(passive, tape, config=OptionExecutionConfig(limit_fidelity=OptionLimitFidelity.CROSS_ONLY))
    maker_touch = execute_option_package(passive, tape, config=OptionExecutionConfig(limit_fidelity=OptionLimitFidelity.MAKER_TOUCH))

    assert cross_only.order_report.loc[0, "status"] == "open"
    assert cross_only.order_report.loc[0, "reject_reason"] == "limit_not_crossed"
    assert maker_touch.order_report.loc[0, "status"] == "filled"
    assert maker_touch.order_report.loc[0, "fill_price"] == pytest.approx(0.0205)
    assert maker_touch.order_report.loc[0, "liquidity"] == "maker"
    assert maker_touch.metadata["limit_fidelity"] == "maker_touch"


def test_phase4_hedge_after_primary_skips_hedges_when_primary_fails(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    ts = int(tape.timestamp_ns[0])
    package = _package(
        ts,
        OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", "buy", 100.0, role="primary"),
        OptionPackageLeg("BTC-01FEB26-110000-P.DERIBIT", "sell", 1.0, role="hedge"),
        policy=OptionPackageExecutionPolicy.HEDGE_AFTER_PRIMARY,
    )

    result = execute_option_package(package, tape, config=OptionExecutionConfig(initial_cash=10.0))

    assert len(result.fills) == 0
    assert result.order_report.iloc[0]["status"] == "rejected"
    assert result.order_report.iloc[1]["status"] == "skipped"
    assert result.order_report.iloc[1]["reject_reason"] == "primary_not_filled"
    assert result.positions == {}


def test_phase4_rebalance_only_trades_delta_to_target(option_phase3_chain, option_phase3_registry):
    tape = prepare_option_tape(option_phase3_chain, option_phase3_registry)
    ts = int(tape.timestamp_ns[0])
    package = _package(
        ts,
        OptionPackageLeg("BTC-01FEB26-100000-C.DERIBIT", "buy", 2.0),
        policy=OptionPackageExecutionPolicy.REBALANCE_ONLY,
    )

    result = execute_option_package(
        package,
        tape,
        config=OptionExecutionConfig(initial_cash=10.0),
        positions={"BTC-01FEB26-100000-C.DERIBIT": 1.5},
    )

    assert len(result.fills) == 1
    assert result.fills[0].qty == pytest.approx(0.5)
    assert result.positions["BTC-01FEB26-100000-C.DERIBIT"] == pytest.approx(2.0)

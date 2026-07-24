from __future__ import annotations

import pytest

from quantbt import (
    OptionPackageExecutionPolicy,
    OptionPackageIntent,
    OptionPackageLeg,
    compile_option_package_orders,
)


def test_phase4_option_package_leg_side_owns_direction_and_ratio_positive():
    with pytest.raises(ValueError, match="ratio must be > 0"):
        OptionPackageLeg(instrument_id="BTC-C", side="buy", ratio=-1.0)

    leg = OptionPackageLeg(instrument_id="BTC-C", side="sell", ratio=2.0, role="short_call")
    assert leg.side.value == "sell"
    assert leg.ratio == 2.0


def test_phase4_option_package_intent_compiles_to_order_intents_with_metadata():
    package = OptionPackageIntent(
        timestamp_ns=1_767_225_600_000_000_000,
        package_id="vertical-1",
        quantity=3.0,
        execution_policy=OptionPackageExecutionPolicy.ATOMIC_ALL_OR_NONE,
        legs=(
            OptionPackageLeg(instrument_id="BTC-01FEB26-100000-C.DERIBIT", side="buy", ratio=1.0, role="long_call"),
            OptionPackageLeg(instrument_id="BTC-01FEB26-110000-P.DERIBIT", side="sell", ratio=2.0, role="short_put"),
        ),
    )

    orders = compile_option_package_orders(package)

    assert len(orders) == 2
    assert orders[0].qty == 3.0
    assert orders[1].qty == 6.0
    assert orders[0].metadata["package_type"] == "option_package"
    assert orders[0].metadata["option_package_id"] == "vertical-1"
    assert orders[0].metadata["option_leg_ratio"] == 1.0
    assert orders[0].metadata["option_leg_role"] == "long_call"
    assert orders[0].metadata["atomicity"] == "simulated_all_or_none"
    assert orders[0].metadata["exchange_combo"] is False
    assert orders[0].metadata["block_trade_style"] is False


def test_phase4_option_package_rejects_empty_or_invalid_guards():
    with pytest.raises(ValueError, match="at least one leg"):
        OptionPackageIntent(timestamp_ns=1, package_id="empty", legs=())

    leg = OptionPackageLeg(instrument_id="BTC-C", side="buy", ratio=1.0)
    with pytest.raises(ValueError, match="max_debit"):
        OptionPackageIntent(timestamp_ns=1, package_id="bad", legs=(leg,), max_debit=-1.0)
    with pytest.raises(ValueError, match="min_credit"):
        OptionPackageIntent(timestamp_ns=1, package_id="bad", legs=(leg,), min_credit=-1.0)


def test_phase4_option_package_leg_rejects_stop_orders_until_lifecycle_phase():
    with pytest.raises(ValueError, match="market and limit"):
        OptionPackageLeg(instrument_id="BTC-C", side="buy", ratio=1.0, order_type="stop_market")

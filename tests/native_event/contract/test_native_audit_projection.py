import numpy as np
import pandas as pd
import pytest

from quantbt.backends.native_audit_projection import (
    TERMINAL_BOOL_COLUMNS, TERMINAL_FLOAT_COLUMNS, TERMINAL_INT_COLUMNS,
    legacy_liquidity, terminal_columns, terminal_fill_summary,
)
from quantbt.core.schema import LiquiditySide, OrderType


def _payload():
    payload = {name: np.zeros(2, dtype=np.int64) for name in TERMINAL_INT_COLUMNS}
    payload.update({name: np.zeros(2, dtype=bool) for name in TERMINAL_BOOL_COLUMNS})
    payload.update({name: np.zeros(2) for name in TERMINAL_FLOAT_COLUMNS})
    payload["sorted_index"] = payload["original_index"] = np.arange(2)
    payload["command_canceled_order_count"] = payload.pop("canceled_order_count")
    return payload | dict(version=1, schema="terminal-command-slots-v1",
        canceled_orders_by_bar=np.array([0, 2, 0]), canceled_event_count=1, canceled_order_count=2)


def test_terminal_slot_and_cancel_event_units_are_distinct():
    columns = terminal_columns(_payload(), n_bars=3)
    assert columns["canceled_orders_by_bar"].sum() == 2
    assert columns["canceled_event_count"] == 1
    np.testing.assert_array_equal(columns["canceled_order_count"], [0, 0])
    assert terminal_columns(None, n_bars=3) is None


def test_native_wire_without_original_index_keeps_missing_provenance_explicit():
    payload = _payload()
    payload["original_index"] = np.array([-1, -1])
    assert not terminal_columns(payload, n_bars=3)["native_original_index_available"]


@pytest.mark.parametrize("mutation", ["version", "length", "sorted", "original", "calendar"])
def test_malformed_terminal_contract_fails_closed(mutation):
    payload = _payload()
    if mutation == "version":
        payload["version"] = 2
    elif mutation == "length":
        payload["active"] = np.array([True])
    elif mutation == "sorted":
        payload["sorted_index"] = np.array([0, 0])
    elif mutation == "original":
        payload["original_index"] = np.array([0, 0])
    elif mutation == "calendar":
        payload["canceled_orders_by_bar"] = np.array([0, -1, 0])
    with pytest.raises(ValueError):
        terminal_columns(payload, n_bars=3)


def test_liquidity_labels_preserve_oracle_convention_not_venue_claim():
    labels, sources = legacy_liquidity(np.array([0, 1, 2, 3]), tuple("abcd"), None)
    assert labels == (LiquiditySide.TAKER, LiquiditySide.MAKER, LiquiditySide.MAKER, LiquiditySide.MAKER)
    assert sources == ("native_matched_order_type_v1",) * 4
    report = pd.DataFrame({"order_id": ["market", "stop"], "order_type": [OrderType.MARKET.value, OrderType.STOP_MARKET.value]})
    labels, sources = legacy_liquidity(None, ("market", "stop", "unknown"), report)
    assert labels == (LiquiditySide.TAKER, LiquiditySide.MAKER, LiquiditySide.TAKER)
    assert sources == ("compiler_order_type_v1", "compiler_order_type_v1", "legacy_default_unqualified")


def test_invalid_fill_type_does_not_silently_default():
    with pytest.raises(ValueError, match="unsupported"):
        legacy_liquidity(np.array([9]), ("a",), None)
    with pytest.raises(ValueError, match="match"):
        legacy_liquidity(np.array([]), ("a",), None)


def test_partial_fill_summary_keeps_native_terminal_state_and_all_fees():
    report = pd.DataFrame({"order_id": ["partial", "empty"], "status": [3, 0],
                           "remaining_qty": [2.0, 1.0], "active": [False, True]})
    result = terminal_fill_summary(report, order_ids=["partial", "partial"],
        quantities=[1.0, 2.0], prices=[100.0, 103.0], fees=[0.1, 0.206])
    assert result.fill_qty.tolist() == [3.0, 0.0]
    assert result.fill_price.tolist() == [102.0, 0.0]
    assert result.retained_fill_count.tolist() == [2, 0]
    np.testing.assert_allclose(result.fill_fee, [0.306, 0.0])
    pd.testing.assert_frame_equal(result[report.columns], report)


def test_partial_fill_summary_rejects_mismatched_ledger_lengths():
    with pytest.raises(ValueError):
        terminal_fill_summary(pd.DataFrame({"order_id": ["a"]}), order_ids=["a"],
            quantities=[], prices=[100.0], fees=[0.1])

"""Cold projections of authoritative native terminal/fill columns, never replay."""

from collections.abc import Mapping

import numpy as np
import pandas as pd

from ..core.event import ORDER_EVENT_EXPIRE, ORDER_STATUS_CANCELED, ORDER_STATUS_FILLED, ORDER_STATUS_PENDING, ORDER_STATUS_REJECTED
from ..core.event_contracts import CommandOutcome, LifecycleOrderStatus
from ..core.orders import OrderAction
from ..core.schema import LiquiditySide, OrderType


TERMINAL_INT_COLUMNS = (
    "command_index", "sorted_index", "original_index", "command_bar", "action",
    "order_id", "target_id", "symbol", "side", "order_type", "tif", "parent_id",
    "group_id", "oco_id", "activation", "expires_bar", "status", "reject_code",
    "qty_semantics", "event_kind", "bar", "canceled_order_count",
)
TERMINAL_BOOL_COLUMNS = (
    "reduce_only", "processed", "working_state_available", "active", "waiting_parent", "trigger_armed",
)
TERMINAL_FLOAT_COLUMNS = ("qty", "remaining_qty", "price", "trigger")


def _value(payload, key):
    return payload[key] if isinstance(payload, Mapping) else getattr(payload, key)


def terminal_columns(payload, *, n_bars):
    """Validate the complete additive terminal contract before adapting it."""
    if payload is None:
        return None
    if int(_value(payload, "version")) != 1 or _value(payload, "schema") != "terminal-command-slots-v1":
        raise ValueError("native terminal schema/version is unsupported")
    arrays = {}
    for names, dtype in (
        (TERMINAL_INT_COLUMNS, np.int64), (TERMINAL_BOOL_COLUMNS, bool),
        (TERMINAL_FLOAT_COLUMNS, np.float64),
    ):
        for name in names:
            key = "command_canceled_order_count" if name == "canceled_order_count" else name
            arr = np.asarray(_value(payload, key), dtype=dtype)
            if arr.ndim != 1:
                raise ValueError(f"native terminal {name} must be one-dimensional")
            arrays[name] = arr
    count = len(arrays["sorted_index"])
    if any(len(arr) != count for arr in arrays.values()):
        raise ValueError("native terminal columns have inconsistent slot lengths")
    if not np.array_equal(arrays["sorted_index"], np.arange(count)):
        raise ValueError("native terminal sorted indices do not cover the command slots")
    native_original_available = not np.all(arrays["original_index"] == -1)
    if native_original_available and (
        np.any(arrays["original_index"] < 0) or len(np.unique(arrays["original_index"])) != count
    ):
        raise ValueError("native terminal original command indices are not unique")
    arrays["native_original_index_available"] = native_original_available
    canceled = np.asarray(_value(payload, "canceled_orders_by_bar"), dtype=np.int64)
    if canceled.shape != (int(n_bars),) or np.any(canceled < 0):
        raise ValueError("native canceled-order path does not match the bar calendar")
    arrays["canceled_orders_by_bar"] = canceled
    arrays["canceled_event_count"] = int(_value(payload, "canceled_event_count"))
    return arrays


def command_terminal_report(command_report, state, *, order_id):
    """Join compiler identity to the final native slot state, including retired orders."""
    count = len(state["sorted_index"])
    if len(command_report) != count:
        raise ValueError("native terminal slot count differs from the compiler command report")
    if not count:
        return command_report.copy()
    report = command_report.sort_values("sorted_index", kind="stable").reset_index(drop=True).copy()
    if state["native_original_index_available"] and not np.array_equal(report["original_index"].to_numpy(), state["original_index"]):
        raise ValueError("native terminal original identity differs from the compiler tape")
    native_ids = [order_id(code) for code in state["order_id"]]
    if report["order_id"].where(report["order_id"].notna(), None).tolist() != native_ids:
        raise ValueError("native terminal order identity differs from the compiler tape")
    for name in ("status", "reject_code", "active", "waiting_parent", "trigger_armed",
                 "processed", "working_state_available", "remaining_qty", "qty_semantics",
                 "canceled_order_count"):
        report[name] = state[name]
    report["working_qty"] = state["qty"]
    report["working_price"] = state["price"]
    report["working_trigger_price"] = state["trigger"]
    report["terminal_event_kind"] = state["event_kind"]
    report["terminal_bar"] = state["bar"]
    report["command_bar"] = state["command_bar"]
    creates = report["action"].isin((OrderAction.PLACE.value, OrderAction.REPLACE.value)).to_numpy()
    filled = creates & (state["status"] == ORDER_STATUS_FILLED)
    report["fill_bar"] = np.where(filled, state["bar"], -1)
    report["native_terminal_contract"] = "native_terminal_state_v1"
    report["original_index_provenance"] = "native" if state["native_original_index_available"] else "compiler_identity_join"
    return report.sort_values("original_index", kind="stable").reset_index(drop=True)


def terminal_outcomes(report, *, n_bars):
    """Canonical command/order concepts from native slots, not causal event IDs."""
    rows = []
    for row in report.to_dict("records"):
        status = int(row["status"])
        creates = row["action"] in (OrderAction.PLACE.value, OrderAction.REPLACE.value)
        # Preserve the existing canonical label contract, while the separate
        # processed column distinguishes commands never reached after liquidation.
        outside = row["command_bar"] <= 0 or row["command_bar"] >= n_bars
        if outside:
            outcome = CommandOutcome.OUTSIDE_TAPE
        elif status == ORDER_STATUS_REJECTED:
            outcome = CommandOutcome.REJECTED
        elif creates or status == ORDER_STATUS_FILLED:
            outcome = CommandOutcome.ACCEPTED
        else:
            outcome = CommandOutcome.NOOP
        order_status = None
        if creates and not outside:
            if status == ORDER_STATUS_REJECTED:
                order_status = LifecycleOrderStatus.REJECTED
            elif row["fill_bar"] >= 0:
                order_status = LifecycleOrderStatus.FILLED
            elif row["active"]:
                order_status = LifecycleOrderStatus.ACTIVE
            elif row["waiting_parent"]:
                order_status = LifecycleOrderStatus.WAITING_PARENT
            elif status == ORDER_STATUS_CANCELED:
                order_status = (LifecycleOrderStatus.EXPIRED if row["terminal_event_kind"] == ORDER_EVENT_EXPIRE
                                else LifecycleOrderStatus.CANCELED)
            else:
                order_status = LifecycleOrderStatus.CREATED
        rows.append({
            **{key: row[key] for key in ("original_index", "sorted_index", "timestamp", "action", "order_id", "target_order_id")},
            "command_outcome_code": int(outcome), "command_outcome": outcome.name,
            "order_status_code": None if order_status is None else int(order_status),
            "order_status": None if order_status is None else order_status.name,
            "legacy_status_code": ORDER_STATUS_PENDING if status < 0 else status,
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("original_index", kind="stable").reset_index(drop=True)


def terminal_fill_summary(report, *, order_ids, quantities, prices, fees):
    """Reduce retained fills without pretending partial orders were fully filled."""
    totals = {}
    for code, qty, price, fee in zip(order_ids, quantities, prices, fees, strict=True):
        qty_sum, notional_sum, fee_sum, count = totals.get(code, (0.0, 0.0, 0.0, 0))
        totals[code] = (qty_sum + float(qty), notional_sum + float(qty) * float(price),
                        fee_sum + float(fee), count + 1)
    result = report.copy()
    rows = [totals.get(code, (0.0, 0.0, 0.0, 0)) for code in report.order_id]
    result["fill_qty"] = [row[0] for row in rows]
    result["fill_price"] = [row[1] / row[0] if row[0] else 0.0 for row in rows]
    result["fill_fee"] = [row[2] for row in rows]
    result["retained_fill_count"] = [row[3] for row in rows]
    return result


def legacy_liquidity(order_types, fill_ids, command_report):
    """Preserve the oracle label convention without claiming venue liquidity.

    The frozen Python convention labels MARKET as taker and every other type
    as maker (including STOP_MARKET). This is reporting provenance, not a new
    execution, fee, or exchange-rule contract.
    """
    supplied = None if order_types is None else np.asarray(order_types, dtype=np.int64)
    if supplied is not None and supplied.shape != (len(fill_ids),):
        raise ValueError("native fill order types do not match the fill ledger")
    lookup = {}
    if command_report is not None and {"order_id", "order_type"}.issubset(command_report.columns):
        lookup = dict(zip(command_report["order_id"], command_report["order_type"]))
    labels, sources = [], []
    for index, fill_id in enumerate(fill_ids):
        if supplied is not None:
            code = int(supplied[index])
            if code not in (0, 1, 2, 3):
                raise ValueError("native fill order type is unsupported")
            market = code == 0
            source = "native_matched_order_type_v1"
        elif fill_id in lookup and lookup[fill_id] is not None:
            kind = lookup[fill_id]
            market = kind == OrderType.MARKET or kind == OrderType.MARKET.value
            source = "compiler_order_type_v1"
        else:
            market = True
            source = "legacy_default_unqualified"
        labels.append(LiquiditySide.TAKER if market else LiquiditySide.MAKER)
        sources.append(source)
    return tuple(labels), tuple(sources)

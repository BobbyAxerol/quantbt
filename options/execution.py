"""
Snapshot-level option package execution.

Phase 4 is an execution simulator on a prepared option tape. It is intentionally
not the final multi-currency ledger, margin, expiry, or Nautilus adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..core.orders import Fill, OrderIntent
from ..core.schema import LiquiditySide, OrderSide, OrderType, TimeInForce
from .packages import OptionPackageExecutionPolicy, OptionPackageIntent, compile_option_package_orders
from .tape import PreparedOptionTape


class OptionLimitFidelity(str, Enum):
    CROSS_ONLY = "cross_only"
    MAKER_TOUCH = "maker_touch"


class OptionDepthFidelity(str, Enum):
    TOP_OF_BOOK = "top_of_book"


@dataclass(frozen=True)
class OptionExecutionConfig:
    initial_cash: float = 0.0
    fee_rate: float = 0.0
    allow_partial_fill: bool = True
    max_quote_age_ns: Optional[int] = None
    limit_fidelity: OptionLimitFidelity = OptionLimitFidelity.CROSS_ONLY
    depth_fidelity: OptionDepthFidelity = OptionDepthFidelity.TOP_OF_BOOK
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "limit_fidelity", _coerce_enum(OptionLimitFidelity, self.limit_fidelity, "limit_fidelity"))
        object.__setattr__(self, "depth_fidelity", _coerce_enum(OptionDepthFidelity, self.depth_fidelity, "depth_fidelity"))
        if self.fee_rate < 0.0:
            raise ValueError("fee_rate must be >= 0")
        if self.max_quote_age_ns is not None and self.max_quote_age_ns < 0:
            raise ValueError("max_quote_age_ns must be >= 0")


@dataclass(frozen=True)
class OptionPackageExecutionResult:
    fills: Tuple[Fill, ...]
    order_report: pd.DataFrame
    package_report: pd.DataFrame
    cash: float
    positions: Dict[str, float]
    margin_report: Dict
    metadata: Dict = field(default_factory=dict)


@dataclass
class _ExecutionState:
    cash: float
    positions: Dict[str, float]

    def copy(self) -> "_ExecutionState":
        return _ExecutionState(cash=float(self.cash), positions=dict(self.positions))


@dataclass(frozen=True)
class _OrderEvaluation:
    fill: Optional[Fill]
    row: Dict
    cash_delta: float
    position_delta: float


_ORDER_REPORT_COLUMNS = [
    "package_id",
    "order_id",
    "symbol",
    "side",
    "order_type",
    "tif",
    "requested_qty",
    "filled_qty",
    "residual_qty",
    "fill_price",
    "fee",
    "cash_delta",
    "status",
    "reject_reason",
    "liquidity",
    "snapshot_timestamp_ns",
    "decision_timestamp_ns",
    "row_index",
    "depth_fidelity",
    "limit_fidelity",
    "residual_risk",
    "atomicity",
]

_PACKAGE_REPORT_COLUMNS = [
    "package_id",
    "execution_policy",
    "status",
    "reject_reason",
    "requested_orders",
    "filled_orders",
    "partial_orders",
    "cash_before",
    "cash_after",
    "net_cash_delta",
    "gross_premium",
    "debit",
    "credit",
    "max_debit",
    "min_credit",
    "atomicity",
    "exchange_combo",
    "block_trade_style",
    "depth_fidelity",
]


def execute_option_package(
    package: OptionPackageIntent,
    tape: PreparedOptionTape,
    *,
    config: Optional[OptionExecutionConfig] = None,
    positions: Optional[Dict[str, float]] = None,
    compiled_orders: Optional[Tuple[OrderIntent, ...]] = None,
) -> OptionPackageExecutionResult:
    """Execute one option package against the latest observable tape snapshot."""
    cfg = config or OptionExecutionConfig()
    state = _ExecutionState(cash=float(cfg.initial_cash), positions=dict(positions or {}))
    orders = tuple(compiled_orders) if compiled_orders is not None else compile_option_package_orders(package)
    policy = package.execution_policy
    if policy is OptionPackageExecutionPolicy.ATOMIC_ALL_OR_NONE:
        return _execute_atomic_all_or_none(package, orders, tape, cfg, state)
    if policy is OptionPackageExecutionPolicy.BEST_EFFORT:
        return _execute_best_effort(package, orders, tape, cfg, state)
    if policy is OptionPackageExecutionPolicy.SEQUENTIAL:
        return _execute_sequential(package, orders, tape, cfg, state)
    if policy is OptionPackageExecutionPolicy.HEDGE_AFTER_PRIMARY:
        return _execute_hedge_after_primary(package, orders, tape, cfg, state)
    if policy is OptionPackageExecutionPolicy.REBALANCE_ONLY:
        return _execute_rebalance_only(package, orders, tape, cfg, state)
    raise ValueError(f"unsupported option execution policy: {policy}")


def _execute_atomic_all_or_none(
    package: OptionPackageIntent,
    orders: Tuple[OrderIntent, ...],
    tape: PreparedOptionTape,
    cfg: OptionExecutionConfig,
    state: _ExecutionState,
) -> OptionPackageExecutionResult:
    trial = state.copy()
    evaluations = [_evaluate_order(order, tape, cfg, trial, package.package_id) for order in orders]
    all_full = all(row.row["status"] == "filled" for row in evaluations)
    guard_ok, guard_reason = _package_cash_guard(package, evaluations)
    if not all_full or not guard_ok:
        reason = guard_reason or "atomic_all_or_none_unfilled_leg"
        rows = [_rejected_row(ev.row, reason) for ev in evaluations]
        return _final_result(package, cfg, state, state, [], rows, "rejected", reason)
    fills = []
    for ev in evaluations:
        _apply_evaluation(trial, ev)
        fills.append(ev.fill)
    return _final_result(package, cfg, state, trial, fills, [ev.row for ev in evaluations], "filled", "")


def _execute_best_effort(
    package: OptionPackageIntent,
    orders: Tuple[OrderIntent, ...],
    tape: PreparedOptionTape,
    cfg: OptionExecutionConfig,
    state: _ExecutionState,
) -> OptionPackageExecutionResult:
    trial = state.copy()
    fills: List[Fill] = []
    evaluations = []
    for order in orders:
        ev = _evaluate_order(order, tape, cfg, trial, package.package_id)
        evaluations.append(ev)
        if ev.fill is not None:
            _apply_evaluation(trial, ev)
            fills.append(ev.fill)
    guard_ok, guard_reason = _package_cash_guard(package, evaluations)
    if not guard_ok:
        rows = [_rejected_row(ev.row, guard_reason) for ev in evaluations]
        return _final_result(package, cfg, state, state, [], rows, "rejected", guard_reason)
    status = _package_status(evaluations)
    return _final_result(package, cfg, state, trial, fills, [ev.row for ev in evaluations], status, "")


def _execute_sequential(
    package: OptionPackageIntent,
    orders: Tuple[OrderIntent, ...],
    tape: PreparedOptionTape,
    cfg: OptionExecutionConfig,
    state: _ExecutionState,
) -> OptionPackageExecutionResult:
    trial = state.copy()
    fills: List[Fill] = []
    evaluations = []
    stopped = False
    for order in orders:
        if stopped:
            row = _base_skipped_row(package.package_id, order, "sequential_previous_leg_failed", cfg)
            evaluations.append(_OrderEvaluation(fill=None, row=row, cash_delta=0.0, position_delta=0.0))
            continue
        ev = _evaluate_order(order, tape, cfg, trial, package.package_id)
        evaluations.append(ev)
        if ev.fill is not None:
            _apply_evaluation(trial, ev)
            fills.append(ev.fill)
        if ev.row["status"] not in {"filled", "partial"}:
            stopped = True
    guard_ok, guard_reason = _package_cash_guard(package, evaluations)
    if not guard_ok:
        rows = [_rejected_row(ev.row, guard_reason) for ev in evaluations]
        return _final_result(package, cfg, state, state, [], rows, "rejected", guard_reason)
    status = _package_status(evaluations)
    return _final_result(package, cfg, state, trial, fills, [ev.row for ev in evaluations], status, "")


def _execute_hedge_after_primary(
    package: OptionPackageIntent,
    orders: Tuple[OrderIntent, ...],
    tape: PreparedOptionTape,
    cfg: OptionExecutionConfig,
    state: _ExecutionState,
) -> OptionPackageExecutionResult:
    trial = state.copy()
    fills: List[Fill] = []
    evaluations = []
    primary = next((order for order in orders if order.metadata.get("option_leg_role") == "primary"), orders[0])
    hedge_orders = tuple(order for order in orders if order is not primary)
    primary_ev = _evaluate_order(primary, tape, cfg, trial, package.package_id)
    evaluations.append(primary_ev)
    if primary_ev.row["status"] != "filled":
        rows = [primary_ev.row] + [_base_skipped_row(package.package_id, order, "primary_not_filled", cfg) for order in hedge_orders]
        return _final_result(package, cfg, state, state, [], rows, "rejected", "primary_not_filled")
    _apply_evaluation(trial, primary_ev)
    fills.append(primary_ev.fill)
    for order in hedge_orders:
        ev = _evaluate_order(order, tape, cfg, trial, package.package_id)
        evaluations.append(ev)
        if ev.fill is not None:
            _apply_evaluation(trial, ev)
            fills.append(ev.fill)
    guard_ok, guard_reason = _package_cash_guard(package, evaluations)
    if not guard_ok:
        rows = [_rejected_row(ev.row, guard_reason) for ev in evaluations]
        return _final_result(package, cfg, state, state, [], rows, "rejected", guard_reason)
    status = _package_status(evaluations)
    return _final_result(package, cfg, state, trial, fills, [ev.row for ev in evaluations], status, "")


def _execute_rebalance_only(
    package: OptionPackageIntent,
    orders: Tuple[OrderIntent, ...],
    tape: PreparedOptionTape,
    cfg: OptionExecutionConfig,
    state: _ExecutionState,
) -> OptionPackageExecutionResult:
    trial = state.copy()
    fills: List[Fill] = []
    evaluations = []
    for order in orders:
        target_signed = float(order.side.sign) * float(order.qty)
        current = float(trial.positions.get(order.symbol, 0.0))
        delta = target_signed - current
        if abs(delta) <= 1e-12:
            row = _base_skipped_row(package.package_id, order, "already_at_target", cfg)
            row["status"] = "no_op"
            evaluations.append(_OrderEvaluation(fill=None, row=row, cash_delta=0.0, position_delta=0.0))
            continue
        adjusted = OrderIntent(
            timestamp=order.timestamp,
            symbol=order.symbol,
            side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
            order_type=order.order_type,
            qty=abs(delta),
            price=order.price,
            tif=order.tif,
            tag=order.tag,
            metadata={**order.metadata, "rebalance_target_signed_qty": target_signed, "rebalance_current_qty": current},
        )
        ev = _evaluate_order(adjusted, tape, cfg, trial, package.package_id)
        evaluations.append(ev)
        if ev.fill is not None:
            _apply_evaluation(trial, ev)
            fills.append(ev.fill)
    guard_ok, guard_reason = _package_cash_guard(package, evaluations)
    if not guard_ok:
        rows = [_rejected_row(ev.row, guard_reason) for ev in evaluations]
        return _final_result(package, cfg, state, state, [], rows, "rejected", guard_reason)
    status = _package_status(evaluations)
    return _final_result(package, cfg, state, trial, fills, [ev.row for ev in evaluations], status, "")


def _evaluate_order(
    order: OrderIntent,
    tape: PreparedOptionTape,
    cfg: OptionExecutionConfig,
    state: _ExecutionState,
    package_id: str,
) -> _OrderEvaluation:
    snapshot_index = tape.snapshot_index_at_or_before(int(order.timestamp), max_quote_age_ns=cfg.max_quote_age_ns)
    rows = tape.snapshot_slice(snapshot_index)
    row_index = _find_row_index(tape, rows, order.symbol)
    if row_index is None:
        return _OrderEvaluation(None, _base_rejected_row(package_id, order, "instrument_not_listed_at_snapshot", cfg), 0.0, 0.0)
    fill_price, liquidity, fillable, reason = _fill_price(order, tape, row_index, cfg)
    if not fillable:
        return _OrderEvaluation(None, _row_from_order(package_id, order, tape, row_index, cfg, 0.0, 0.0, "open", reason, liquidity), 0.0, 0.0)
    available = _available_qty(order, tape, row_index)
    fill_qty = min(float(order.qty), available)
    residual = float(order.qty) - fill_qty
    if fill_qty <= 0.0:
        return _OrderEvaluation(None, _row_from_order(package_id, order, tape, row_index, cfg, 0.0, fill_price, "open", "no_top_of_book_size", liquidity), 0.0, 0.0)
    if residual > 1e-12 and order.tif is TimeInForce.FOK:
        return _OrderEvaluation(None, _row_from_order(package_id, order, tape, row_index, cfg, 0.0, fill_price, "rejected", "fok_insufficient_size", liquidity), 0.0, 0.0)
    if residual > 1e-12 and order.tif is TimeInForce.IOC:
        if not cfg.allow_partial_fill:
            return _OrderEvaluation(None, _row_from_order(package_id, order, tape, row_index, cfg, 0.0, fill_price, "rejected", "ioc_partial_not_allowed", liquidity), 0.0, 0.0)
        status = "partial"
        reason = "ioc_residual_canceled"
    elif residual > 1e-12 and order.tif is TimeInForce.GTC:
        if not cfg.allow_partial_fill:
            return _OrderEvaluation(None, _row_from_order(package_id, order, tape, row_index, cfg, 0.0, fill_price, "open", "gtc_waiting_for_size", liquidity), 0.0, 0.0)
        status = "partial"
        reason = "gtc_residual_open"
    else:
        status = "filled"
        reason = ""
    fee = fill_qty * fill_price * cfg.fee_rate
    cash_delta = fill_qty * fill_price - fee if order.side is OrderSide.SELL else -(fill_qty * fill_price + fee)
    position_delta = order.side.sign * fill_qty
    fill = Fill(
        timestamp=tape.timestamp_ns[snapshot_index],
        symbol=order.symbol,
        side=order.side,
        qty=fill_qty,
        price=fill_price,
        fee=fee,
        liquidity=liquidity,
        order_id=order.order_id,
        metadata={**order.metadata, "option_row_index": int(row_index), "package_id": package_id},
    )
    row = _row_from_order(package_id, order, tape, row_index, cfg, fill_qty, fill_price, status, reason, liquidity, fee=fee, cash_delta=cash_delta)
    return _OrderEvaluation(fill, row, cash_delta, position_delta)


def _fill_price(
    order: OrderIntent,
    tape: PreparedOptionTape,
    row_index: int,
    cfg: OptionExecutionConfig,
) -> tuple[float, LiquiditySide, bool, str]:
    bid = float(tape.bid_price[row_index])
    ask = float(tape.ask_price[row_index])
    if order.order_type is OrderType.MARKET:
        return (ask if order.side is OrderSide.BUY else bid), LiquiditySide.TAKER, True, ""
    if order.order_type is not OrderType.LIMIT:
        return float("nan"), LiquiditySide.TAKER, False, "unsupported_option_order_type"
    limit = float(order.price)
    if cfg.limit_fidelity is OptionLimitFidelity.CROSS_ONLY:
        if order.side is OrderSide.BUY and limit >= ask:
            return ask, LiquiditySide.TAKER, True, ""
        if order.side is OrderSide.SELL and limit <= bid:
            return bid, LiquiditySide.TAKER, True, ""
        return limit, LiquiditySide.MAKER, False, "limit_not_crossed"
    if order.side is OrderSide.BUY and limit >= bid:
        return min(limit, ask), LiquiditySide.MAKER if limit < ask else LiquiditySide.TAKER, True, "maker_touch_simulated"
    if order.side is OrderSide.SELL and limit <= ask:
        return max(limit, bid), LiquiditySide.MAKER if limit > bid else LiquiditySide.TAKER, True, "maker_touch_simulated"
    return limit, LiquiditySide.MAKER, False, "limit_not_touched"


def _available_qty(order: OrderIntent, tape: PreparedOptionTape, row_index: int) -> float:
    return float(tape.ask_size[row_index] if order.side is OrderSide.BUY else tape.bid_size[row_index])


def _find_row_index(tape: PreparedOptionTape, rows: slice, symbol: str) -> Optional[int]:
    for idx in range(rows.start, rows.stop):
        if tape.instrument_id[idx] == symbol:
            return idx
    return None


def _apply_evaluation(state: _ExecutionState, evaluation: _OrderEvaluation) -> None:
    if evaluation.fill is None:
        return
    state.cash += float(evaluation.cash_delta)
    state.positions[evaluation.fill.symbol] = state.positions.get(evaluation.fill.symbol, 0.0) + evaluation.position_delta


def _package_cash_guard(package: OptionPackageIntent, evaluations: List[_OrderEvaluation]) -> tuple[bool, str]:
    net_cash_delta = sum(ev.cash_delta for ev in evaluations if ev.fill is not None)
    debit = max(-net_cash_delta, 0.0)
    credit = max(net_cash_delta, 0.0)
    if package.max_debit is not None and debit > float(package.max_debit) + 1e-12:
        return False, "max_debit_exceeded"
    if package.min_credit is not None and credit + 1e-12 < float(package.min_credit):
        return False, "min_credit_not_met"
    return True, ""


def _final_result(
    package: OptionPackageIntent,
    cfg: OptionExecutionConfig,
    initial_state: _ExecutionState,
    final_state: _ExecutionState,
    fills: List[Optional[Fill]],
    rows: List[Dict],
    package_status: str,
    reject_reason: str,
) -> OptionPackageExecutionResult:
    concrete_fills = tuple(fill for fill in fills if fill is not None)
    order_report = pd.DataFrame(rows, columns=_ORDER_REPORT_COLUMNS)
    filled_orders = int((order_report["status"] == "filled").sum()) if not order_report.empty else 0
    partial_orders = int((order_report["status"] == "partial").sum()) if not order_report.empty else 0
    net_cash_delta = float(final_state.cash - initial_state.cash)
    gross_premium = float(order_report["filled_qty"].mul(order_report["fill_price"]).sum()) if not order_report.empty else 0.0
    package_report = pd.DataFrame(
        [
            {
                "package_id": package.package_id,
                "execution_policy": package.execution_policy.value,
                "status": package_status,
                "reject_reason": reject_reason,
                "requested_orders": len(package.legs),
                "filled_orders": filled_orders,
                "partial_orders": partial_orders,
                "cash_before": initial_state.cash,
                "cash_after": final_state.cash,
                "net_cash_delta": net_cash_delta,
                "gross_premium": gross_premium,
                "debit": max(-net_cash_delta, 0.0),
                "credit": max(net_cash_delta, 0.0),
                "max_debit": package.max_debit,
                "min_credit": package.min_credit,
                "atomicity": _atomicity_for_report(package.execution_policy),
                "exchange_combo": False,
                "block_trade_style": False,
                "depth_fidelity": cfg.depth_fidelity.value,
            }
        ],
        columns=_PACKAGE_REPORT_COLUMNS,
    )
    positions = {symbol: qty for symbol, qty in final_state.positions.items() if abs(qty) > 1e-12}
    return OptionPackageExecutionResult(
        fills=concrete_fills,
        order_report=order_report,
        package_report=package_report,
        cash=float(final_state.cash),
        positions=positions,
        margin_report={
            "phase": "phase4_snapshot_execution",
            "margin_model": "not_implemented_until_phase5",
            "gross_premium": gross_premium,
            "position_count": len(positions),
        },
        metadata={
            "backend": "native_option_phase4",
            "execution_scope": "snapshot_package_execution",
            "depth_fidelity": cfg.depth_fidelity.value,
            "limit_fidelity": cfg.limit_fidelity.value,
            "atomicity": _atomicity_for_report(package.execution_policy),
            **cfg.metadata,
        },
    )


def _package_status(evaluations: List[_OrderEvaluation]) -> str:
    statuses = [ev.row["status"] for ev in evaluations]
    if statuses and all(status == "filled" for status in statuses):
        return "filled"
    if any(status == "partial" for status in statuses):
        return "partial"
    if any(status == "filled" for status in statuses):
        return "partial"
    if any(status == "open" for status in statuses):
        return "open"
    return "rejected"


def _row_from_order(
    package_id: str,
    order: OrderIntent,
    tape: PreparedOptionTape,
    row_index: int,
    cfg: OptionExecutionConfig,
    filled_qty: float,
    fill_price: float,
    status: str,
    reject_reason: str,
    liquidity: LiquiditySide,
    *,
    fee: float = 0.0,
    cash_delta: float = 0.0,
) -> Dict:
    snapshot_idx = tape.snapshot_index_at_or_before(int(order.timestamp), max_quote_age_ns=cfg.max_quote_age_ns)
    return {
        "package_id": package_id,
        "order_id": order.order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "order_type": order.order_type.value,
        "tif": order.tif.value,
        "requested_qty": float(order.qty),
        "filled_qty": float(filled_qty),
        "residual_qty": max(float(order.qty) - float(filled_qty), 0.0),
        "fill_price": float(fill_price),
        "fee": float(fee),
        "cash_delta": float(cash_delta),
        "status": status,
        "reject_reason": reject_reason,
        "liquidity": liquidity.value,
        "snapshot_timestamp_ns": int(tape.timestamp_ns[snapshot_idx]),
        "decision_timestamp_ns": int(order.timestamp),
        "row_index": int(row_index),
        "depth_fidelity": cfg.depth_fidelity.value,
        "limit_fidelity": cfg.limit_fidelity.value,
        "residual_risk": bool(status == "partial"),
        "atomicity": order.metadata.get("atomicity", ""),
    }


def _base_rejected_row(package_id: str, order: OrderIntent, reason: str, cfg: OptionExecutionConfig) -> Dict:
    return _base_skipped_row(package_id, order, reason, cfg, status="rejected")


def _base_skipped_row(
    package_id: str,
    order: OrderIntent,
    reason: str,
    cfg: OptionExecutionConfig,
    *,
    status: str = "skipped",
) -> Dict:
    return {
        "package_id": package_id,
        "order_id": order.order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "order_type": order.order_type.value,
        "tif": order.tif.value,
        "requested_qty": float(order.qty),
        "filled_qty": 0.0,
        "residual_qty": float(order.qty),
        "fill_price": float("nan"),
        "fee": 0.0,
        "cash_delta": 0.0,
        "status": status,
        "reject_reason": reason,
        "liquidity": "",
        "snapshot_timestamp_ns": 0,
        "decision_timestamp_ns": int(order.timestamp),
        "row_index": -1,
        "depth_fidelity": cfg.depth_fidelity.value,
        "limit_fidelity": cfg.limit_fidelity.value,
        "residual_risk": False,
        "atomicity": order.metadata.get("atomicity", ""),
    }


def _rejected_row(row: Dict, reason: str) -> Dict:
    rejected = dict(row)
    rejected["status"] = "rejected"
    rejected["reject_reason"] = reason
    rejected["filled_qty"] = 0.0
    rejected["residual_qty"] = rejected["requested_qty"]
    rejected["fee"] = 0.0
    rejected["cash_delta"] = 0.0
    rejected["residual_risk"] = False
    return rejected


def _atomicity_for_report(policy: OptionPackageExecutionPolicy) -> str:
    if policy is OptionPackageExecutionPolicy.ATOMIC_ALL_OR_NONE:
        return "simulated_atomic_all_or_none"
    if policy is OptionPackageExecutionPolicy.HEDGE_AFTER_PRIMARY:
        return "simulated_primary_then_hedge"
    if policy is OptionPackageExecutionPolicy.REBALANCE_ONLY:
        return "simulated_rebalance_only"
    return f"simulated_{policy.value}"


def _coerce_enum(enum_cls, value, field_name: str):
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be one of {[item.value for item in enum_cls]}") from exc

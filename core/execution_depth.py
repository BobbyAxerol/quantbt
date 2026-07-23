"""
Execution-depth preflight for Nautilus-style package validation.

This module is intentionally dependency-free from NautilusTrader. It gives
QuantBT a deterministic, fast, auditable preflight layer for package orders
before a heavier event backend is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .orders import OrderIntent
from .schema import OrderSide, OrderType


SUPPORTED_DEPTH_MODELS = ("ohlcv_volume_cap", "synthetic_book", "l2_replay")


@dataclass(frozen=True)
class NautilusExecutionDepthConfig:
    """
    Optional execution-depth policy for package-order validation.

    Defaults are intentionally conservative and mostly observational: existing
    endpoints are unchanged unless callers explicitly run this preflight layer.
    """

    all_or_none_packages: bool = False
    all_or_none_package_types: Tuple[str, ...] = ("basket_package", "arbitrage_package")
    allow_partial_fills: bool = False
    max_participation_rate: Optional[float] = None
    queue_ahead_qty: float = 0.0
    latency_bars: int = 0
    depth_model: str = "ohlcv_volume_cap"
    synthetic_spread_bps: float = 2.0
    synthetic_level_spacing_bps: Optional[float] = None
    synthetic_levels: int = 5
    synthetic_base_depth_qty: Optional[float] = None
    synthetic_base_depth_notional: Optional[float] = None
    synthetic_depth_slope: float = 0.0
    activate_oco_after_entry_fill: bool = True
    cancel_oco_sibling_on_first_exit_fill: bool = True
    cap_reduce_only_to_position: bool = True
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.depth_model not in SUPPORTED_DEPTH_MODELS:
            raise ValueError(f"depth_model must be one of {SUPPORTED_DEPTH_MODELS}")
        if self.max_participation_rate is not None and not 0.0 <= self.max_participation_rate <= 1.0:
            raise ValueError("max_participation_rate must be in [0, 1]")
        if self.queue_ahead_qty < 0.0:
            raise ValueError("queue_ahead_qty must be >= 0")
        if self.latency_bars < 0:
            raise ValueError("latency_bars must be >= 0")
        if self.synthetic_spread_bps < 0.0:
            raise ValueError("synthetic_spread_bps must be >= 0")
        if self.synthetic_level_spacing_bps is not None and self.synthetic_level_spacing_bps < 0.0:
            raise ValueError("synthetic_level_spacing_bps must be >= 0")
        if self.synthetic_levels <= 0:
            raise ValueError("synthetic_levels must be > 0")
        if self.synthetic_base_depth_qty is not None and self.synthetic_base_depth_qty <= 0.0:
            raise ValueError("synthetic_base_depth_qty must be > 0")
        if self.synthetic_base_depth_notional is not None and self.synthetic_base_depth_notional <= 0.0:
            raise ValueError("synthetic_base_depth_notional must be > 0")
        if self.synthetic_depth_slope < -1.0:
            raise ValueError("synthetic_depth_slope must be >= -1")


@dataclass(frozen=True)
class PackageDepthPreflightResult:
    orders: Tuple[OrderIntent, ...]
    order_report: pd.DataFrame
    package_report: pd.DataFrame
    metadata: Dict = field(default_factory=dict)


def l2_replay_available(provider: object = None) -> bool:
    """
    Return whether a real L2 replay provider is configured.

    QuantBT intentionally does not synthesize Level-3 venue claims. A provider
    must expose venue snapshots, incremental book updates, and trade prints.
    """
    required = ("snapshots", "updates", "trades")
    return provider is not None and all(hasattr(provider, name) for name in required)


def simulate_nautilus_order_package_depth(
    orders: Sequence[OrderIntent],
    data: Dict[str, pd.DataFrame],
    config: Optional[NautilusExecutionDepthConfig] = None,
) -> PackageDepthPreflightResult:
    """
    Simulate lightweight package execution constraints on OHLCV bars.

    This is not a full matching engine. It is a deterministic package preflight
    for domain checks that Nautilus package routes need before deeper adapter
    integration: touch eligibility, latency, queue/volume caps, partial fills,
    reduce-only caps, OCO sibling cancellation, and all-or-none package reject.
    """
    cfg = config or NautilusExecutionDepthConfig()
    if cfg.depth_model == "l2_replay":
        raise NotImplementedError(
            "depth_model='l2_replay' requires real venue L2 snapshots, incremental updates, "
            "trade prints, and a provider adapter. Use depth_model='synthetic_book' for deterministic stress tests."
        )
    if not orders:
        return PackageDepthPreflightResult(
            orders=tuple(),
            order_report=_empty_order_report(),
            package_report=_empty_package_report(),
            metadata={"accepted_orders": 0, "input_orders": 0},
        )

    frames = _normalize_data(data)
    states = _State()
    accepted: list[OrderIntent] = []
    rows: list[Dict] = []
    package_rows: list[Dict] = []

    planned = [_PlannedOrder(order=order, effective_timestamp=_effective_timestamp(order, frames, cfg)) for order in orders]
    planned.sort(key=lambda item: (item.effective_timestamp.value if item.effective_timestamp is not None else np.iinfo(np.int64).max))

    groups: Dict[Tuple[pd.Timestamp, str], list[_PlannedOrder]] = {}
    singles: list[_PlannedOrder] = []
    for item in planned:
        package_id = _package_id(item.order)
        package_type = _package_type(item.order)
        if cfg.all_or_none_packages and package_type in set(cfg.all_or_none_package_types) and package_id:
            key = (item.effective_timestamp or _utc_timestamp(item.order.timestamp), package_id)
            groups.setdefault(key, []).append(item)
        else:
            singles.append(item)

    timeline = sorted(
        [(key[0], "group", key, values) for key, values in groups.items()]
        + [(item.effective_timestamp or _utc_timestamp(item.order.timestamp), "single", None, [item]) for item in singles],
        key=lambda value: value[0].value,
    )

    for _, kind, group_key, items in timeline:
        if kind == "group":
            trial = states.copy()
            trial_rows: list[Dict] = []
            trial_orders: list[OrderIntent] = []
            for item in items:
                evaluated = _evaluate_order(item, frames, cfg, trial)
                trial_rows.append(evaluated.row)
                if evaluated.accepted_order is not None:
                    trial_orders.append(evaluated.accepted_order)
            group_ok = bool(trial_orders) and all(row["status"] == "filled" for row in trial_rows)
            package_id = group_key[1] if group_key else ""
            if group_ok:
                states = trial
                accepted.extend(trial_orders)
                rows.extend(trial_rows)
                package_rows.append(_package_row(package_id, items, "accepted", "all_or_none_filled"))
            else:
                for row in trial_rows:
                    rejected = dict(row)
                    rejected["status"] = "rejected"
                    rejected["reject_reason"] = "all_or_none_package_rejected"
                    rejected["filled_qty"] = 0.0
                    rows.append(rejected)
                package_rows.append(_package_row(package_id, items, "rejected", "all_or_none_package_rejected"))
            continue

        item = items[0]
        evaluated = _evaluate_order(item, frames, cfg, states)
        rows.append(evaluated.row)
        if evaluated.accepted_order is not None:
            accepted.append(evaluated.accepted_order)

    order_report = pd.DataFrame(rows, columns=_ORDER_REPORT_COLUMNS)
    package_report = pd.DataFrame(package_rows, columns=_PACKAGE_REPORT_COLUMNS)
    metadata = {
        "input_orders": int(len(orders)),
        "accepted_orders": int(len(accepted)),
        "rejected_orders": int((order_report["status"] == "rejected").sum()) if not order_report.empty else 0,
        "partial_orders": int((order_report["status"] == "partial").sum()) if not order_report.empty else 0,
        "canceled_orders": int((order_report["status"] == "canceled").sum()) if not order_report.empty else 0,
        "latency_bars": int(cfg.latency_bars),
        "allow_partial_fills": bool(cfg.allow_partial_fills),
        "all_or_none_packages": bool(cfg.all_or_none_packages),
        "depth_model": str(cfg.depth_model),
        "supported_depth_models": SUPPORTED_DEPTH_MODELS,
        **cfg.metadata,
    }
    return PackageDepthPreflightResult(
        orders=tuple(accepted),
        order_report=order_report,
        package_report=package_report,
        metadata=metadata,
    )


@dataclass
class _State:
    position: Dict[str, float] = field(default_factory=dict)
    filled_tags: set[str] = field(default_factory=set)
    canceled_oco_groups: set[str] = field(default_factory=set)
    filled_oco_groups: set[str] = field(default_factory=set)

    def copy(self) -> "_State":
        return _State(
            position=dict(self.position),
            filled_tags=set(self.filled_tags),
            canceled_oco_groups=set(self.canceled_oco_groups),
            filled_oco_groups=set(self.filled_oco_groups),
        )


@dataclass(frozen=True)
class _PlannedOrder:
    order: OrderIntent
    effective_timestamp: Optional[pd.Timestamp]


@dataclass(frozen=True)
class _EvaluatedOrder:
    row: Dict
    accepted_order: Optional[OrderIntent]


@dataclass(frozen=True)
class _DepthFill:
    fillable: bool
    fill_price: float
    reason: str
    available_qty: float
    levels_consumed: int = 0
    participation_cap_qty: float = np.nan


_ORDER_REPORT_COLUMNS = [
    "timestamp",
    "effective_timestamp",
    "symbol",
    "side",
    "order_type",
    "qty",
    "filled_qty",
    "fill_price",
    "status",
    "reject_reason",
    "package_id",
    "package_type",
    "leg_role",
    "oco_group_id",
    "latency_bars",
    "available_qty",
    "depth_model",
    "levels_consumed",
    "spread_bps",
    "queue_ahead_qty",
    "participation_cap_qty",
    "requested_notional",
    "filled_notional",
]

_PACKAGE_REPORT_COLUMNS = ["package_id", "package_type", "timestamp", "orders", "status", "reason"]


def _evaluate_order(
    item: _PlannedOrder,
    frames: Dict[str, pd.DataFrame],
    cfg: NautilusExecutionDepthConfig,
    state: _State,
) -> _EvaluatedOrder:
    order = item.order
    ts = item.effective_timestamp
    base = _base_row(order, ts, cfg)
    if ts is None:
        return _reject(base, "latency_out_of_range")
    if order.symbol not in frames:
        return _reject(base, "missing_symbol_data")
    frame = frames[order.symbol]
    if ts not in frame.index:
        return _reject(base, "timestamp_not_in_data")
    if _is_oco_exit(order) and cfg.activate_oco_after_entry_fill:
        parent_tag = order.metadata.get("parent_tag")
        if parent_tag and parent_tag not in state.filled_tags:
            return _reject(base, "parent_entry_not_filled")
    oco_group = order.metadata.get("oco_group_id")
    if oco_group and oco_group in state.canceled_oco_groups:
        row = {**base, "status": "canceled", "reject_reason": "oco_sibling_already_filled"}
        return _EvaluatedOrder(row=row, accepted_order=None)

    bar = frame.loc[ts]
    depth_fill = _evaluate_depth_fill(order, bar, cfg)
    if not depth_fill.fillable:
        return _reject(base, depth_fill.reason)

    available = depth_fill.available_qty
    requested = float(order.qty)
    reduce_only_capped = False
    if order.reduce_only and cfg.cap_reduce_only_to_position:
        current = float(state.position.get(order.symbol, 0.0))
        if current == 0.0 or np.sign(current) == order.side.sign:
            return _reject({**base, "available_qty": available}, "reduce_only_no_opposite_position")
        available = min(available, abs(current))
        reduce_only_capped = available < requested

    if available <= 0.0:
        return _reject({**base, "available_qty": available}, "no_queue_capacity")
    filled_qty = min(requested, available)
    if filled_qty < requested and not cfg.allow_partial_fills and not reduce_only_capped:
        return _reject({**base, "available_qty": available}, "insufficient_queue_capacity")

    status = "partial" if filled_qty < requested else "filled"
    accepted_order = order
    if filled_qty != requested or ts != _utc_timestamp(order.timestamp):
        metadata = {
            **order.metadata,
            "depth_original_qty": requested,
            "depth_effective_timestamp": ts,
            "depth_status": status,
            "depth_model": cfg.depth_model,
        }
        accepted_order = replace(order, timestamp=ts, qty=float(filled_qty), metadata=metadata)

    _commit_fill(state, accepted_order)
    if accepted_order.tag:
        state.filled_tags.add(accepted_order.tag)
    if oco_group and _is_oco_exit(order) and cfg.cancel_oco_sibling_on_first_exit_fill:
        state.filled_oco_groups.add(str(oco_group))
        state.canceled_oco_groups.add(str(oco_group))

    row = {
        **base,
        "filled_qty": float(filled_qty),
        "fill_price": float(depth_fill.fill_price),
        "status": status,
        "reject_reason": "",
        "available_qty": float(available),
        "levels_consumed": int(depth_fill.levels_consumed),
        "participation_cap_qty": float(depth_fill.participation_cap_qty),
        "requested_notional": float(requested * depth_fill.fill_price),
        "filled_notional": float(filled_qty * depth_fill.fill_price),
    }
    return _EvaluatedOrder(row=row, accepted_order=accepted_order)


def _commit_fill(state: _State, order: OrderIntent) -> None:
    current = float(state.position.get(order.symbol, 0.0))
    delta = float(order.qty) * order.side.sign
    if order.reduce_only and current != 0.0 and np.sign(current) != order.side.sign:
        delta = np.sign(delta) * min(abs(delta), abs(current))
    state.position[order.symbol] = current + delta


def _fillability(order: OrderIntent, bar: pd.Series) -> tuple[bool, float, str]:
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    if order.order_type is OrderType.MARKET:
        return True, close, ""
    if order.order_type is OrderType.LIMIT:
        price = float(order.price)
        touched = low <= price if order.side is OrderSide.BUY else high >= price
        return touched, price, "" if touched else "limit_not_touched"
    if order.order_type is OrderType.STOP_MARKET:
        trigger = float(order.trigger_price)
        touched = high >= trigger if order.side is OrderSide.BUY else low <= trigger
        return touched, trigger, "" if touched else "stop_not_triggered"
    if order.order_type is OrderType.STOP_LIMIT:
        trigger = float(order.trigger_price)
        price = float(order.price)
        triggered = high >= trigger if order.side is OrderSide.BUY else low <= trigger
        touched = low <= price if order.side is OrderSide.BUY else high >= price
        ok = triggered and touched
        return ok, price, "" if ok else "stop_limit_not_triggered_or_touched"
    return False, np.nan, "unsupported_order_type"


def _evaluate_depth_fill(order: OrderIntent, bar: pd.Series, cfg: NautilusExecutionDepthConfig) -> _DepthFill:
    if cfg.depth_model == "synthetic_book":
        return _synthetic_book_fill(order, bar, cfg)

    fillable, fill_price, reason = _fillability(order, bar)
    if not fillable:
        return _DepthFill(False, fill_price, reason, 0.0)
    available = _available_qty(order, bar, cfg)
    participation_cap = _participation_cap_qty(bar, cfg)
    return _DepthFill(
        fillable=True,
        fill_price=float(fill_price),
        reason="",
        available_qty=float(available),
        levels_consumed=1,
        participation_cap_qty=participation_cap,
    )


def _synthetic_book_fill(order: OrderIntent, bar: pd.Series, cfg: NautilusExecutionDepthConfig) -> _DepthFill:
    eligible, executable_price, reason = _fillability(order, bar)
    if not eligible:
        return _DepthFill(False, executable_price, reason, 0.0)

    close = float(bar["close"])
    if not np.isfinite(close) or close <= 0.0:
        return _DepthFill(False, np.nan, "invalid_close_for_synthetic_book", 0.0)

    levels = _synthetic_book_levels(order, close, cfg)
    if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
        limit_price = float(order.price)
        if order.side is OrderSide.BUY:
            levels = tuple((price, qty) for price, qty in levels if price <= limit_price)
        else:
            levels = tuple((price, qty) for price, qty in levels if price >= limit_price)

    participation_cap = _participation_cap_qty(bar, cfg)
    requested = float(order.qty)
    target_qty = min(requested, participation_cap) if np.isfinite(participation_cap) else requested
    if target_qty <= 0.0:
        return _DepthFill(True, executable_price, "", 0.0, participation_cap_qty=participation_cap)

    remaining_queue = float(cfg.queue_ahead_qty)
    remaining = target_qty
    filled = 0.0
    notional = 0.0
    consumed = 0
    for price, level_qty in levels:
        qty_after_queue = float(level_qty)
        if remaining_queue > 0.0:
            queue_take = min(qty_after_queue, remaining_queue)
            qty_after_queue -= queue_take
            remaining_queue -= queue_take
        if qty_after_queue <= 0.0:
            consumed += 1
            continue
        take = min(remaining, qty_after_queue)
        if take <= 0.0:
            break
        filled += take
        notional += take * float(price)
        remaining -= take
        consumed += 1
        if remaining <= 1e-15:
            break

    if filled <= 0.0:
        return _DepthFill(True, executable_price, "", 0.0, levels_consumed=consumed, participation_cap_qty=participation_cap)
    return _DepthFill(
        fillable=True,
        fill_price=float(notional / filled),
        reason="",
        available_qty=float(filled),
        levels_consumed=int(consumed),
        participation_cap_qty=participation_cap,
    )


def _synthetic_book_levels(
    order: OrderIntent,
    reference_price: float,
    cfg: NautilusExecutionDepthConfig,
) -> Tuple[Tuple[float, float], ...]:
    half_spread = reference_price * float(cfg.synthetic_spread_bps) / 20_000.0
    spacing_bps = cfg.synthetic_level_spacing_bps
    if spacing_bps is None:
        spacing_bps = max(float(cfg.synthetic_spread_bps), 1.0)
    spacing = reference_price * float(spacing_bps) / 10_000.0

    if cfg.synthetic_base_depth_qty is not None:
        base_qty = float(cfg.synthetic_base_depth_qty)
    elif cfg.synthetic_base_depth_notional is not None:
        base_qty = float(cfg.synthetic_base_depth_notional) / reference_price
    else:
        base_qty = float(order.qty)

    out: list[Tuple[float, float]] = []
    for level in range(int(cfg.synthetic_levels)):
        if order.side is OrderSide.BUY:
            price = reference_price + half_spread + level * spacing
        else:
            price = reference_price - half_spread - level * spacing
        qty_multiplier = max(0.0, 1.0 + float(cfg.synthetic_depth_slope) * level)
        out.append((float(price), float(base_qty * qty_multiplier)))
    return tuple(out)


def _available_qty(order: OrderIntent, bar: pd.Series, cfg: NautilusExecutionDepthConfig) -> float:
    if cfg.max_participation_rate is None:
        return float(order.qty)
    volume = float(bar.get("volume", 0.0))
    capacity = max(0.0, volume * float(cfg.max_participation_rate) - float(cfg.queue_ahead_qty))
    return min(float(order.qty), capacity)


def _participation_cap_qty(bar: pd.Series, cfg: NautilusExecutionDepthConfig) -> float:
    if cfg.max_participation_rate is None:
        return np.nan
    volume = float(bar.get("volume", 0.0))
    return max(0.0, volume * float(cfg.max_participation_rate))


def _effective_timestamp(
    order: OrderIntent,
    frames: Dict[str, pd.DataFrame],
    cfg: NautilusExecutionDepthConfig,
) -> Optional[pd.Timestamp]:
    ts = _utc_timestamp(order.timestamp)
    if cfg.latency_bars == 0:
        return ts
    frame = frames.get(order.symbol)
    if frame is None or frame.empty:
        return None
    index = frame.index
    pos = index.searchsorted(ts)
    if pos >= len(index) or index[pos] != ts:
        return None
    target = pos + int(cfg.latency_bars)
    if target >= len(index):
        return None
    return pd.Timestamp(index[target])


def _normalize_data(data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    out = {}
    for symbol, frame in data.items():
        df = frame.copy()
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
        rename = {col: str(col).lower() for col in df.columns}
        df = df.rename(columns=rename)
        if "close" not in df:
            raise ValueError(f"data for {symbol!r} must include close")
        for col in ("open", "high", "low", "volume"):
            if col not in df:
                df[col] = df["close"] if col != "volume" else 0.0
        out[symbol] = df[["open", "high", "low", "close", "volume"]].sort_index()
    return out


def _base_row(order: OrderIntent, effective_timestamp: Optional[pd.Timestamp], cfg: NautilusExecutionDepthConfig) -> Dict:
    return {
        "timestamp": _utc_timestamp(order.timestamp),
        "effective_timestamp": effective_timestamp,
        "symbol": order.symbol,
        "side": order.side.value if isinstance(order.side, OrderSide) else str(order.side),
        "order_type": order.order_type.value if isinstance(order.order_type, OrderType) else str(order.order_type),
        "qty": float(order.qty),
        "filled_qty": 0.0,
        "fill_price": np.nan,
        "status": "pending",
        "reject_reason": "",
        "package_id": _package_id(order),
        "package_type": _package_type(order),
        "leg_role": order.metadata.get("leg_role"),
        "oco_group_id": order.metadata.get("oco_group_id"),
        "latency_bars": int(cfg.latency_bars),
        "available_qty": np.nan,
        "depth_model": str(cfg.depth_model),
        "levels_consumed": 0,
        "spread_bps": float(cfg.synthetic_spread_bps) if cfg.depth_model == "synthetic_book" else np.nan,
        "queue_ahead_qty": float(cfg.queue_ahead_qty),
        "participation_cap_qty": np.nan,
        "requested_notional": np.nan,
        "filled_notional": 0.0,
    }


def _reject(base: Dict, reason: str) -> _EvaluatedOrder:
    return _EvaluatedOrder(row={**base, "status": "rejected", "reject_reason": reason}, accepted_order=None)


def _package_row(package_id: str, items: Sequence[_PlannedOrder], status: str, reason: str) -> Dict:
    first = items[0].order if items else None
    ts = _utc_timestamp(first.timestamp) if first is not None else pd.NaT
    return {
        "package_id": package_id,
        "package_type": _package_type(first) if first is not None else "",
        "timestamp": ts,
        "orders": int(len(items)),
        "status": status,
        "reason": reason,
    }


def _is_oco_exit(order: OrderIntent) -> bool:
    return order.metadata.get("leg_role") in {"take_profit", "stop_loss"} and bool(order.metadata.get("oco_group_id"))


def _package_id(order: Optional[OrderIntent]) -> str:
    if order is None:
        return ""
    return str(order.metadata.get("package_id") or order.metadata.get("basket_id") or order.metadata.get("arb_id") or "")


def _package_type(order: Optional[OrderIntent]) -> str:
    if order is None:
        return ""
    return str(order.metadata.get("package_type") or order.metadata.get("structured_type") or "")


def _utc_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tz is None else ts.tz_convert("UTC")


def _empty_order_report() -> pd.DataFrame:
    return pd.DataFrame(columns=_ORDER_REPORT_COLUMNS)


def _empty_package_report() -> pd.DataFrame:
    return pd.DataFrame(columns=_PACKAGE_REPORT_COLUMNS)

"""Versioned native-event clock, fill, and lifecycle contracts.

This module is the readable Python oracle for bar-level execution semantics.
The Numba and Rust kernels consume compact contract codes generated from the
same registry and are certified against this implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import IntEnum
import warnings
from typing import Mapping, Optional

from .generated_native_event_contracts import (
    COMMAND_OUTCOME_CODES,
    CONTRACT_CODES,
    CONTRACT_IDS_BY_CODE,
    LIFECYCLE_EVENT_KIND_CODES,
    NATIVE_EVENT_CONTRACT_FINGERPRINT,
    NATIVE_EVENT_CONTRACT_REGISTRY,
    ORDER_STATUS_CODES,
)


EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE = "event_lifecycle_v2_next_bar_close"
EVENT_LIFECYCLE_V3_NEXT_OPEN = "event_lifecycle_v3_next_open"


class CommandOutcome(IntEnum):
    ACCEPTED = COMMAND_OUTCOME_CODES["ACCEPTED"]
    REJECTED = COMMAND_OUTCOME_CODES["REJECTED"]
    NOOP = COMMAND_OUTCOME_CODES["NOOP"]
    OUTSIDE_TAPE = COMMAND_OUTCOME_CODES["OUTSIDE_TAPE"]


class LifecycleOrderStatus(IntEnum):
    CREATED = ORDER_STATUS_CODES["CREATED"]
    WAITING_PARENT = ORDER_STATUS_CODES["WAITING_PARENT"]
    ACTIVE = ORDER_STATUS_CODES["ACTIVE"]
    PARTIALLY_FILLED = ORDER_STATUS_CODES["PARTIALLY_FILLED"]
    FILLED = ORDER_STATUS_CODES["FILLED"]
    CANCELED = ORDER_STATUS_CODES["CANCELED"]
    EXPIRED = ORDER_STATUS_CODES["EXPIRED"]
    REJECTED = ORDER_STATUS_CODES["REJECTED"]
    LIQUIDATED = ORDER_STATUS_CODES["LIQUIDATED"]


class LifecycleEventKind(IntEnum):
    PLACE = LIFECYCLE_EVENT_KIND_CODES["PLACE"]
    ACTIVATE = LIFECYCLE_EVENT_KIND_CODES["ACTIVATE"]
    AMEND = LIFECYCLE_EVENT_KIND_CODES["AMEND"]
    REPLACE = LIFECYCLE_EVENT_KIND_CODES["REPLACE"]
    CANCEL = LIFECYCLE_EVENT_KIND_CODES["CANCEL"]
    EXPIRE = LIFECYCLE_EVENT_KIND_CODES["EXPIRE"]
    FILL = LIFECYCLE_EVENT_KIND_CODES["FILL"]
    REJECT = LIFECYCLE_EVENT_KIND_CODES["REJECT"]
    LIQUIDATE = LIFECYCLE_EVENT_KIND_CODES["LIQUIDATE"]
    PACKAGE_COMMIT = LIFECYCLE_EVENT_KIND_CODES["PACKAGE_COMMIT"]
    PACKAGE_ABORT = LIFECYCLE_EVENT_KIND_CODES["PACKAGE_ABORT"]


@dataclass(frozen=True, slots=True)
class EventClockContract:
    contract_id: str
    contract_code: int
    contract_version: int
    classification: str
    bar_timestamp_semantics: str
    observation_phase: str
    command_activation_phase: str
    phase_sequence: tuple[str, ...]
    last_bar_policy: str
    fill_policy: Mapping[str, str]
    registry_fingerprint: str = NATIVE_EVENT_CONTRACT_FINGERPRINT

    def to_metadata(self) -> dict:
        return {
            "contract_id": self.contract_id,
            "contract_code": self.contract_code,
            "contract_version": self.contract_version,
            "classification": self.classification,
            "bar_timestamp_semantics": self.bar_timestamp_semantics,
            "observation_phase": self.observation_phase,
            "command_activation_phase": self.command_activation_phase,
            "phase_sequence": list(self.phase_sequence),
            "last_bar_policy": self.last_bar_policy,
            "fill_policy": dict(self.fill_policy),
            "registry_fingerprint": self.registry_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class BarView:
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("bar violates OHLC envelope")
        if self.high < self.low:
            raise ValueError("bar high must be >= low")


@dataclass(frozen=True, slots=True)
class WorkingOrderView:
    order_type: int
    side: int
    price: float = 0.0
    trigger_price: float = 0.0
    trigger_armed: bool = False

    def __post_init__(self) -> None:
        if self.side not in {-1, 1}:
            raise ValueError("order side must be -1 or 1")


@dataclass(frozen=True, slots=True)
class FillDecision:
    matched: bool
    fill_price: float
    triggered: bool
    ambiguous: bool
    ambiguity_code: str
    liquidity_assumption: str
    price_reason: str
    path_assumption: str


@dataclass(frozen=True, slots=True)
class LifecycleTransition:
    action: str
    from_status: str
    to_status: str
    outcome: CommandOutcome
    reason: str


@dataclass(frozen=True, slots=True)
class EngineDiagnosticsV1:
    bars_processed: int = 0
    symbols_processed: int = 0
    commands_processed: int = 0
    expiry_scan_count: int = 0
    matching_scan_count: int = 0
    relationship_scan_count: int = 0
    fills_emitted: int = 0
    events_emitted: int = 0
    output_bytes: int = 0
    prepare_ns: int = 0
    engine_ns: int = 0
    report_ns: int = 0

    def to_metadata(self) -> dict:
        return {key: int(value) for key, value in asdict(self).items()}


def _contracts_by_id() -> dict[str, EventClockContract]:
    return {
        item["contract_id"]: EventClockContract(
            contract_id=item["contract_id"],
            contract_code=int(item["contract_code"]),
            contract_version=int(item["contract_version"]),
            classification=item["classification"],
            bar_timestamp_semantics=item["bar_timestamp_semantics"],
            observation_phase=item["observation_phase"],
            command_activation_phase=item["command_activation_phase"],
            phase_sequence=tuple(item["phase_sequence"]),
            last_bar_policy=item["last_bar_policy"],
            fill_policy=dict(item["fill_policy"]),
        )
        for item in NATIVE_EVENT_CONTRACT_REGISTRY["contracts"]
    }


EVENT_CLOCK_CONTRACTS = _contracts_by_id()


def get_event_clock_contract(contract: str | int | EventClockContract) -> EventClockContract:
    if isinstance(contract, EventClockContract):
        return contract
    if isinstance(contract, int):
        try:
            contract = CONTRACT_IDS_BY_CODE[int(contract)]
        except KeyError as exc:
            raise KeyError(f"unknown native-event contract code {contract!r}") from exc
    key = str(contract).lower().strip()
    aliases = NATIVE_EVENT_CONTRACT_REGISTRY["aliases"]
    if key in aliases:
        message = NATIVE_EVENT_CONTRACT_REGISTRY["deprecations"].get(key)
        if message:
            warnings.warn(message, DeprecationWarning, stacklevel=2)
        key = aliases[key]
    try:
        return EVENT_CLOCK_CONTRACTS[key]
    except KeyError as exc:
        raise KeyError(f"unknown native-event contract {contract!r}") from exc


def lifecycle_transitions() -> tuple[LifecycleTransition, ...]:
    return tuple(
        LifecycleTransition(
            action=item["action"],
            from_status=item["from"],
            to_status=item["to"],
            outcome=CommandOutcome[item["outcome"]],
            reason=item["reason"],
        )
        for item in NATIVE_EVENT_CONTRACT_REGISTRY["transitions"]
    )


def validate_lifecycle_transition(action: str, from_status: str, to_status: Optional[str] = None) -> LifecycleTransition:
    action_key = str(action).upper().strip()
    status_key = str(from_status).upper().strip()
    candidates = [
        item
        for item in lifecycle_transitions()
        if item.action == action_key and item.from_status == status_key
    ]
    if to_status is not None:
        target_key = str(to_status).upper().strip()
        candidates = [item for item in candidates if item.to_status == target_key]
    if len(candidates) != 1:
        raise ValueError(
            f"invalid or ambiguous lifecycle transition action={action_key!r}, "
            f"from={status_key!r}, to={to_status!r}"
        )
    return candidates[0]


def _slipped(price: float, side: int, slippage: float) -> float:
    return price * (1.0 + slippage if side > 0 else 1.0 - slippage)


def _decision(
    *,
    matched: bool,
    fill_price: float = 0.0,
    triggered: bool = False,
    ambiguous: bool = False,
    ambiguity_code: str = "NONE",
    liquidity_assumption: str = "INFINITE_BAR_LIQUIDITY",
    price_reason: str = "NOT_TOUCHED",
    path_assumption: str = "NONE",
) -> FillDecision:
    return FillDecision(
        matched=matched,
        fill_price=float(fill_price),
        triggered=triggered,
        ambiguous=ambiguous,
        ambiguity_code=ambiguity_code,
        liquidity_assumption=liquidity_assumption,
        price_reason=price_reason,
        path_assumption=path_assumption,
    )


def decide_bar_fill(
    order: WorkingOrderView,
    bar: BarView,
    contract: str | int | EventClockContract,
    *,
    slippage: float = 0.0,
) -> FillDecision:
    """Return one deterministic bar-fill decision under a versioned contract."""

    if slippage < 0.0:
        raise ValueError("slippage must be >= 0")
    clock = get_event_clock_contract(contract)
    if clock.contract_id == EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE:
        return _decide_v2_legacy(order, bar, slippage)
    if clock.contract_id == EVENT_LIFECYCLE_V3_NEXT_OPEN:
        return _decide_v3_next_open(order, bar, slippage)
    raise NotImplementedError(f"fill oracle does not implement {clock.contract_id!r}")


def _decide_v2_legacy(order: WorkingOrderView, bar: BarView, slippage: float) -> FillDecision:
    if order.order_type == 0:
        return _decision(matched=True, fill_price=_slipped(bar.close, order.side, slippage), price_reason="NEXT_BAR_CLOSE")
    if order.order_type == 1:
        touched = bar.low <= order.price if order.side > 0 else bar.high >= order.price
        return _decision(matched=touched, fill_price=order.price if touched else 0.0, price_reason="LIMIT_TRIGGER" if touched else "NOT_TOUCHED")
    if order.order_type == 2:
        touched = bar.high >= order.trigger_price if order.side > 0 else bar.low <= order.trigger_price
        return _decision(
            matched=touched,
            fill_price=_slipped(order.trigger_price, order.side, slippage) if touched else 0.0,
            triggered=touched,
            price_reason="STOP_TRIGGER_LEGACY" if touched else "NOT_TOUCHED",
        )
    if order.order_type == 3:
        trigger_touched = bar.high >= order.trigger_price if order.side > 0 else bar.low <= order.trigger_price
        limit_touched = bar.low <= order.price if order.side > 0 else bar.high >= order.price
        touched = trigger_touched and limit_touched
        return _decision(
            matched=touched,
            fill_price=order.price if touched else 0.0,
            triggered=trigger_touched,
            ambiguous=touched,
            ambiguity_code="UNORDERED_OHLC_RANGE" if touched else "NONE",
            price_reason="STOP_LIMIT_LEGACY" if touched else "NOT_TOUCHED",
            path_assumption="UNORDERED_RANGE",
        )
    return _decision(matched=False, price_reason="UNSUPPORTED_ORDER_TYPE")


def _decide_v3_next_open(order: WorkingOrderView, bar: BarView, slippage: float) -> FillDecision:
    if order.order_type == 0:
        return _decision(matched=True, fill_price=_slipped(bar.open, order.side, slippage), price_reason="NEXT_OPEN")
    if order.order_type == 1:
        favorable_gap = bar.open <= order.price if order.side > 0 else bar.open >= order.price
        touched = bar.low <= order.price if order.side > 0 else bar.high >= order.price
        if favorable_gap:
            return _decision(matched=True, fill_price=bar.open, price_reason="LIMIT_OPEN_IMPROVEMENT")
        return _decision(matched=touched, fill_price=order.price if touched else 0.0, price_reason="LIMIT_TRIGGER" if touched else "NOT_TOUCHED")
    if order.order_type == 2:
        gap = bar.open >= order.trigger_price if order.side > 0 else bar.open <= order.trigger_price
        touched = bar.high >= order.trigger_price if order.side > 0 else bar.low <= order.trigger_price
        if gap:
            return _decision(matched=True, fill_price=_slipped(bar.open, order.side, slippage), triggered=True, price_reason="STOP_OPEN_WORSE")
        return _decision(
            matched=touched,
            fill_price=_slipped(order.trigger_price, order.side, slippage) if touched else 0.0,
            triggered=touched,
            price_reason="STOP_TRIGGER" if touched else "NOT_TOUCHED",
        )
    if order.order_type == 3:
        if order.trigger_armed:
            limit_order = WorkingOrderView(order_type=1, side=order.side, price=order.price)
            decision = _decide_v3_next_open(limit_order, bar, slippage)
            return FillDecision(
                matched=decision.matched,
                fill_price=decision.fill_price,
                triggered=True,
                ambiguous=False,
                ambiguity_code="NONE",
                liquidity_assumption=decision.liquidity_assumption,
                price_reason="ARMED_STOP_LIMIT_" + decision.price_reason,
                path_assumption="TRIGGERED_PRIOR_BAR",
            )
        gap_trigger = bar.open >= order.trigger_price if order.side > 0 else bar.open <= order.trigger_price
        trigger_touched = bar.high >= order.trigger_price if order.side > 0 else bar.low <= order.trigger_price
        limit_touched = bar.low <= order.price if order.side > 0 else bar.high >= order.price
        if not trigger_touched:
            return _decision(matched=False)
        if gap_trigger:
            favorable = bar.open <= order.price if order.side > 0 else bar.open >= order.price
            if favorable:
                return _decision(matched=True, fill_price=bar.open, triggered=True, price_reason="STOP_LIMIT_OPEN_IMPROVEMENT", path_assumption="TRIGGER_AT_OPEN")
            if limit_touched:
                return _decision(matched=True, fill_price=order.price, triggered=True, price_reason="STOP_LIMIT_AFTER_OPEN_TRIGGER", path_assumption="TRIGGER_AT_OPEN")
            return _decision(matched=False, triggered=True, price_reason="TRIGGERED_LIMIT_NOT_TOUCHED", path_assumption="TRIGGER_AT_OPEN")
        if limit_touched:
            return _decision(
                matched=False,
                triggered=True,
                ambiguous=True,
                ambiguity_code="STOP_LIMIT_INTRABAR_PATH_UNKNOWN",
                price_reason="TRIGGERED_AWAIT_NEXT_BAR",
                path_assumption="CONSERVATIVE_NO_SAME_BAR_FILL",
            )
        return _decision(matched=False, triggered=True, price_reason="TRIGGERED_LIMIT_NOT_TOUCHED", path_assumption="TRIGGER_INTRABAR")
    return _decision(matched=False, price_reason="UNSUPPORTED_ORDER_TYPE")


__all__ = [
    "BarView",
    "CommandOutcome",
    "EngineDiagnosticsV1",
    "EventClockContract",
    "FillDecision",
    "LifecycleEventKind",
    "LifecycleOrderStatus",
    "LifecycleTransition",
    "WorkingOrderView",
    "EVENT_CLOCK_CONTRACTS",
    "EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE",
    "EVENT_LIFECYCLE_V3_NEXT_OPEN",
    "NATIVE_EVENT_CONTRACT_FINGERPRINT",
    "decide_bar_fill",
    "get_event_clock_contract",
    "lifecycle_transitions",
    "validate_lifecycle_transition",
]

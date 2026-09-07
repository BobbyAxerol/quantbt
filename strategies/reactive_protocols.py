"""Typed R2/R3/R3B reactive scheduling contracts.

The contracts in this module deliberately describe *engine observable* state
only.  A wake may depend on bar time, lifecycle, funding, price touch/cross,
position, equity, or margin.  Feature calculations such as RSI, EMA, or a
strategy's private state remain exclusively in user strategy code.

The Rust co-runtime prefers the compact positional ``as_native_wire`` form on
the optimized path and retains ``as_native_payload`` as a compatibility
adapter. Keeping the Python types immutable makes an emitted wake/block plan
auditable and prevents a strategy from mutating the plan after the callback
has returned.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, IntFlag
from math import isfinite
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class WakeReasonV1(IntFlag):
    """Versioned coalesced R2 wake reasons.

    A single callback sees the bitwise union for one processed market bar.
    This prevents duplicate decisions when, for example, an order fill also
    creates an order lifecycle event on the same boundary.
    """

    INITIAL = 1 << 0
    TIME = 1 << 1
    FILL = 1 << 2
    ORDER_EVENT = 1 << 3
    LIQUIDATION = 1 << 4
    FUNDING = 1 << 5
    PRICE_CROSS = 1 << 6
    POSITION_THRESHOLD = 1 << 7
    EQUITY_THRESHOLD = 1 << 8
    MARGIN_THRESHOLD = 1 << 9
    BLOCK_INVALIDATED = 1 << 10


class ThresholdDirectionV1(IntEnum):
    """Crossing direction for price/account/position thresholds."""

    DOWN = -1
    EITHER = 0
    UP = 1


class MarginMetricV1(IntEnum):
    """Engine-owned account projection used by a margin threshold."""

    INITIAL_MARGIN = 0
    MAINTENANCE_MARGIN = 1
    AVAILABLE_EQUITY = 2


def _direction(value: ThresholdDirectionV1 | str | int) -> ThresholdDirectionV1:
    if isinstance(value, ThresholdDirectionV1):
        return value
    if isinstance(value, str):
        normalized = value.lower().strip()
        aliases = {"down": -1, "either": 0, "any": 0, "up": 1}
        if normalized in aliases:
            return ThresholdDirectionV1(aliases[normalized])
    try:
        return ThresholdDirectionV1(int(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("threshold direction must be down, either, or up") from exc


def _metric(value: MarginMetricV1 | str | int) -> MarginMetricV1:
    if isinstance(value, MarginMetricV1):
        return value
    if isinstance(value, str):
        normalized = value.lower().strip()
        aliases = {
            "initial_margin": MarginMetricV1.INITIAL_MARGIN,
            "maintenance_margin": MarginMetricV1.MAINTENANCE_MARGIN,
            "available_equity": MarginMetricV1.AVAILABLE_EQUITY,
        }
        if normalized in aliases:
            return aliases[normalized]
    try:
        return MarginMetricV1(int(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "margin metric must be initial_margin, maintenance_margin, or available_equity"
        ) from exc


def _finite_level(value: float, label: str) -> float:
    numeric = float(value)
    if not isfinite(numeric):
        raise ValueError(f"{label} must be finite")
    return numeric


@dataclass(frozen=True, slots=True)
class PriceCrossConditionV1:
    """Wake when a declared symbol crosses a static price level."""

    symbol_id: int
    level: float
    direction: ThresholdDirectionV1 | str | int = ThresholdDirectionV1.EITHER

    def __post_init__(self) -> None:
        if int(self.symbol_id) < 0:
            raise ValueError("price-cross symbol_id must be >= 0")
        object.__setattr__(self, "symbol_id", int(self.symbol_id))
        object.__setattr__(self, "level", _finite_level(self.level, "price-cross level"))
        object.__setattr__(self, "direction", _direction(self.direction))

    def native_row(self) -> tuple[int, float, int]:
        return self.symbol_id, self.level, int(self.direction)


@dataclass(frozen=True, slots=True)
class PositionThresholdV1:
    """Wake when a symbol's signed position crosses a quantity threshold."""

    symbol_id: int
    level: float
    direction: ThresholdDirectionV1 | str | int = ThresholdDirectionV1.EITHER

    def __post_init__(self) -> None:
        if int(self.symbol_id) < 0:
            raise ValueError("position-threshold symbol_id must be >= 0")
        object.__setattr__(self, "symbol_id", int(self.symbol_id))
        object.__setattr__(self, "level", _finite_level(self.level, "position-threshold level"))
        object.__setattr__(self, "direction", _direction(self.direction))

    def native_row(self) -> tuple[int, float, int]:
        return self.symbol_id, self.level, int(self.direction)


@dataclass(frozen=True, slots=True)
class EquityThresholdV1:
    """Wake when account equity crosses a static level."""

    level: float
    direction: ThresholdDirectionV1 | str | int = ThresholdDirectionV1.EITHER

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", _finite_level(self.level, "equity-threshold level"))
        object.__setattr__(self, "direction", _direction(self.direction))

    def native_row(self) -> tuple[float, int]:
        return self.level, int(self.direction)


@dataclass(frozen=True, slots=True)
class MarginThresholdV1:
    """Wake when one engine-owned margin projection crosses a level."""

    metric: MarginMetricV1 | str | int
    level: float
    direction: ThresholdDirectionV1 | str | int = ThresholdDirectionV1.EITHER

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric", _metric(self.metric))
        object.__setattr__(self, "level", _finite_level(self.level, "margin-threshold level"))
        object.__setattr__(self, "direction", _direction(self.direction))

    def native_row(self) -> tuple[int, float, int]:
        return int(self.metric), self.level, int(self.direction)


@dataclass(frozen=True, slots=True)
class WakePlanV1:
    """The complete replacement wake plan returned after one R2 callback.

    ``next_timestamp_ns`` has exact-bar semantics: it must match a timestamp
    on the prepared market tape.  The native runner rejects an in-between
    timestamp rather than rounding it to a nearby bar.
    """

    next_bar: int | None = None
    next_timestamp_ns: int | None = None
    on_fill: bool = False
    on_order_event: bool = False
    on_liquidation: bool = False
    on_funding: bool = False
    price_crosses: tuple[PriceCrossConditionV1, ...] = ()
    position_thresholds: tuple[PositionThresholdV1, ...] = ()
    equity_thresholds: tuple[EquityThresholdV1, ...] = ()
    margin_thresholds: tuple[MarginThresholdV1, ...] = ()

    def __post_init__(self) -> None:
        if self.next_bar is not None and int(self.next_bar) < 0:
            raise ValueError("next_bar must be >= 0 or None")
        object.__setattr__(self, "next_bar", None if self.next_bar is None else int(self.next_bar))
        object.__setattr__(
            self,
            "next_timestamp_ns",
            None if self.next_timestamp_ns is None else int(self.next_timestamp_ns),
        )
        for field_name, kind in (
            ("price_crosses", PriceCrossConditionV1),
            ("position_thresholds", PositionThresholdV1),
            ("equity_thresholds", EquityThresholdV1),
            ("margin_thresholds", MarginThresholdV1),
        ):
            values = tuple(getattr(self, field_name))
            if not all(isinstance(value, kind) for value in values):
                raise TypeError(f"{field_name} must contain only {kind.__name__}")
            object.__setattr__(self, field_name, values)

    def as_native_payload(self) -> dict[str, object]:
        """Return the stable primitive wire form consumed by the Rust runner."""

        return {
            "schema": "quantbt-wake-plan-v1",
            "next_bar": self.next_bar,
            "next_timestamp_ns": self.next_timestamp_ns,
            "on_fill": bool(self.on_fill),
            "on_order_event": bool(self.on_order_event),
            "on_liquidation": bool(self.on_liquidation),
            "on_funding": bool(self.on_funding),
            "price_crosses": tuple(item.native_row() for item in self.price_crosses),
            "position_thresholds": tuple(item.native_row() for item in self.position_thresholds),
            "equity_thresholds": tuple(item.native_row() for item in self.equity_thresholds),
            "margin_thresholds": tuple(item.native_row() for item in self.margin_thresholds),
        }

    def as_native_wire(self) -> tuple[object, ...]:
        """Return the allocation-light positional wire preferred by Rust R2/R3.

        The public dataclass and validation contract remain unchanged.  This
        immutable tuple simply avoids constructing a string-keyed dict for
        every optimized wake callback.  Older extensions fall back to
        :meth:`as_native_payload` without changing strategy code.
        """

        return (
            self.next_bar,
            self.next_timestamp_ns,
            bool(self.on_fill),
            bool(self.on_order_event),
            bool(self.on_liquidation),
            bool(self.on_funding),
            tuple(item.native_row() for item in self.price_crosses),
            tuple(item.native_row() for item in self.position_thresholds),
            tuple(item.native_row() for item in self.equity_thresholds),
            tuple(item.native_row() for item in self.margin_thresholds),
        )


@dataclass(frozen=True, slots=True)
class BlockPlanV1:
    """One R3 block range and its explicit invalidation contract.

    The strategy writes commands with ``effective_bar`` in
    ``[start_bar, stop_bar)``.  Rust cancels the unexecuted remainder and asks
    for a replacement block immediately after an enabled invalidation.
    """

    stop_bar: int
    invalidate_on_fill: bool = True
    invalidate_on_reject: bool = True
    invalidate_on_margin_change: bool = False

    def __post_init__(self) -> None:
        if int(self.stop_bar) <= 0:
            raise ValueError("block stop_bar must be > 0")
        object.__setattr__(self, "stop_bar", int(self.stop_bar))

    def as_native_payload(self) -> dict[str, object]:
        return {
            "schema": "quantbt-block-plan-v1",
            "stop_bar": self.stop_bar,
            "invalidate_on_fill": bool(self.invalidate_on_fill),
            "invalidate_on_reject": bool(self.invalidate_on_reject),
            "invalidate_on_margin_change": bool(self.invalidate_on_margin_change),
        }


@dataclass(frozen=True, slots=True)
class CandidateWakePlansV1:
    """Candidate-indexed R3B replacement plans from one batch callback."""

    plans: Mapping[int, WakePlanV1] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = {int(candidate_id): plan for candidate_id, plan in self.plans.items()}
        if any(candidate_id < 0 for candidate_id in normalized):
            raise ValueError("candidate IDs must be >= 0")
        if not all(isinstance(plan, WakePlanV1) for plan in normalized.values()):
            raise TypeError("candidate wake plans must be WakePlanV1 values")
        object.__setattr__(self, "plans", normalized)

    def as_native_payload(self) -> dict[int, dict[str, object]]:
        return {candidate_id: plan.as_native_payload() for candidate_id, plan in self.plans.items()}

    def as_native_wire(self) -> tuple[tuple[int, tuple[object, ...]], ...]:
        """Return deterministic typed candidate-plan rows for Rust R3B.

        Candidate IDs are sorted so the optimized transport cannot inherit a
        mapping insertion-order accident.  The legacy payload method remains
        available for an older installed native extension.
        """

        return tuple(
            (candidate_id, self.plans[candidate_id].as_native_wire())
            for candidate_id in sorted(self.plans)
        )


class CandidateErrorCodeV1(IntEnum):
    """Typed local failures that do not poison unrelated batch candidates."""

    STRATEGY_REJECTED = 1
    INVALID_COMMAND = 2
    CANCELED = 3
    BUDGET_EXCEEDED = 4


@dataclass(frozen=True, slots=True)
class ReactiveShadowCertificationV1:
    """Evidence from an explicit every-bar versus optimized-reactive run.

    R2/R3 do not silently execute an oracle inside a production run.  Instead
    callers run the intended every-bar strategy and its sparse/block variant
    deliberately, then keep this compact result with the research artifact.
    ``decision_trace`` is optional only when a strategy has no private mutable
    decision state; otherwise both traces must be supplied by the strategy.
    """

    passed: bool
    execution_trace_equal: bool
    command_trace_equal: bool
    decision_trace_equal: bool | None
    state_fingerprint_equal: bool | None
    details: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "quantbt-reactive-shadow-certification-v1",
            "passed": self.passed,
            "execution_trace_equal": self.execution_trace_equal,
            "command_trace_equal": self.command_trace_equal,
            "decision_trace_equal": self.decision_trace_equal,
            "state_fingerprint_equal": self.state_fingerprint_equal,
            "details": dict(self.details),
        }


def _command_trace(result: Any) -> tuple[tuple[object, ...], ...]:
    """Normalize cold-path emitted commands without touching execution state."""

    metadata = getattr(result, "metadata", {}) or {}
    commands = metadata.get("emitted_command_tape", ())
    rows: list[tuple[object, ...]] = []
    for command in commands:
        rows.append(
            (
                getattr(command, "timestamp", None),
                getattr(getattr(command, "action", None), "value", getattr(command, "action", None)),
                getattr(command, "symbol", None),
                getattr(getattr(command, "side", None), "value", getattr(command, "side", None)),
                getattr(getattr(command, "order_type", None), "value", getattr(command, "order_type", None)),
                getattr(command, "qty", None),
                getattr(command, "price", None),
                getattr(command, "trigger_price", None),
                getattr(command, "order_id", None),
                getattr(command, "target_order_id", None),
            )
        )
    return tuple(rows)


def certify_reactive_shadow_v1(
    *,
    every_bar_result: Any,
    optimized_result: Any,
    every_bar_decision_trace: Sequence[object] | None = None,
    optimized_decision_trace: Sequence[object] | None = None,
    every_bar_state_fingerprint: object | None = None,
    optimized_state_fingerprint: object | None = None,
) -> ReactiveShadowCertificationV1:
    """Compare an explicit every-bar oracle with R2/R3 at real boundaries.

    The helper is intentionally a verifier, not a hidden fallback.  It checks
    the canonical execution/account trace, emitted executable command tape,
    and optional strategy-owned decision/fingerprint evidence.  A caller must
    retain the returned artifact before setting a strategy's explicit
    ``quantbt_*_shadow_certified_v1`` marker.
    """

    from ..core.execution_trace import compare_canonical_traces

    oracle_metadata = getattr(every_bar_result, "metadata", {}) or {}
    optimized_metadata = getattr(optimized_result, "metadata", {}) or {}
    oracle_trace = oracle_metadata.get("canonical_trace_v1")
    optimized_trace = optimized_metadata.get("canonical_trace_v1")
    if oracle_trace is None or optimized_trace is None:
        raise ValueError("both results must retain metadata['canonical_trace_v1'] for shadow certification")
    trace_report = compare_canonical_traces(oracle_trace, optimized_trace)
    execution_equal = bool(trace_report.get("passed", False))
    command_equal = _command_trace(every_bar_result) == _command_trace(optimized_result)
    if (every_bar_decision_trace is None) != (optimized_decision_trace is None):
        raise ValueError("pass both decision traces or neither")
    decision_equal = (
        None
        if every_bar_decision_trace is None
        else tuple(every_bar_decision_trace) == tuple(optimized_decision_trace or ())
    )
    if (every_bar_state_fingerprint is None) != (optimized_state_fingerprint is None):
        raise ValueError("pass both state fingerprints or neither")
    fingerprint_equal = (
        None
        if every_bar_state_fingerprint is None
        else every_bar_state_fingerprint == optimized_state_fingerprint
    )
    passed = execution_equal and command_equal and decision_equal is not False and fingerprint_equal is not False
    return ReactiveShadowCertificationV1(
        passed=passed,
        execution_trace_equal=execution_equal,
        command_trace_equal=command_equal,
        decision_trace_equal=decision_equal,
        state_fingerprint_equal=fingerprint_equal,
        details={
            "schema": "quantbt-reactive-shadow-certification-v1",
            "trace_report": trace_report,
            "oracle_command_count": len(_command_trace(every_bar_result)),
            "optimized_command_count": len(_command_trace(optimized_result)),
        },
    )


def wake_reason_names(mask: int | WakeReasonV1) -> tuple[str, ...]:
    """Decode one versioned coalesced wake bitmask for audit presentation."""

    value = WakeReasonV1(int(mask))
    return tuple(reason.name.lower() for reason in WakeReasonV1 if reason & value)


@runtime_checkable
class ReactiveSparseStrategyV1(Protocol):
    """Duck-typed R2 protocol; ``on_wake`` returns a replacement plan."""

    def on_wake(self, context, out) -> WakePlanV1:
        ...


@runtime_checkable
class BlockIntentProviderV1(Protocol):
    """Duck-typed R3 protocol for bounded future command blocks."""

    def next_block(self, context, start_bar: int, max_stop_bar: int, out) -> BlockPlanV1:
        ...


@runtime_checkable
class ReactiveCandidateBatchStrategyV1(Protocol):
    """Duck-typed R3B protocol; one callback receives all waking candidates."""

    def on_wake_batch(self, context_batch, out_batch) -> CandidateWakePlansV1:
        ...


__all__ = [
    "BlockIntentProviderV1",
    "BlockPlanV1",
    "CandidateErrorCodeV1",
    "CandidateWakePlansV1",
    "EquityThresholdV1",
    "MarginMetricV1",
    "MarginThresholdV1",
    "PositionThresholdV1",
    "PriceCrossConditionV1",
    "ReactiveCandidateBatchStrategyV1",
    "ReactiveShadowCertificationV1",
    "ReactiveSparseStrategyV1",
    "ThresholdDirectionV1",
    "WakePlanV1",
    "WakeReasonV1",
    "certify_reactive_shadow_v1",
    "wake_reason_names",
]

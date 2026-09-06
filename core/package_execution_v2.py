"""Bounded same-account package execution reference contract.

This module is intentionally a readable oracle for the Phase 68 Rust route.
It does not own a production account and does not construct pandas artifacts.
The production route lowers the same immutable package intent into Rust, where
``FullSession`` remains the only state that commits fills and accounting.

The V2 contract is deliberately narrower than a venue package API:

* one linear, quote-settled, gross-cross account;
* one declared bar per package and deterministic leg ordering;
* explicit simulated fill fractions, rather than an implied L2 fill model;
* residuals and reservation movement are output on every terminal path; and
* triangular/cross-venue currency-flow semantics are not represented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import floor
from typing import Sequence

import numpy as np


PACKAGE_EXECUTION_V2_CONTRACT_VERSION = "package-intent-v2"
_EPSILON = 1e-12


class PackageExecutionPolicyV2(str, Enum):
    """Bounded same-account package admission/execution policies."""

    ATOMIC_BAR_SIMULATION = "atomic_bar_simulation"
    SEQUENTIAL = "sequential"
    BEST_EFFORT = "best_effort"
    HEDGE_AFTER_PRIMARY = "hedge_after_primary"


class ResidualRiskPolicyV1(str, Enum):
    """What the bounded simulator does after a visible package residual."""

    RECORD = "record"
    UNWIND_PACKAGE = "unwind_package"


class LegQuantitySourceV1(str, Enum):
    """Declared source for a signed leg quantity."""

    FIXED = "fixed"
    PROPORTION_OF_REQUESTED = "proportion_of_requested"
    PROPORTION_OF_ACTUAL_FILL = "proportion_of_actual_fill"
    CONSUME_PREVIOUS_OUTPUT = "consume_previous_output"


class PackageStateV2(str, Enum):
    """Lifecycle states retained by the package V2 audit contract."""

    PLANNED = "PLANNED"
    VALIDATED = "VALIDATED"
    PREFLIGHT_REJECTED = "PREFLIGHT_REJECTED"
    RESERVED = "RESERVED"
    SUBMITTING = "SUBMITTING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    RESIDUAL_DETECTED = "RESIDUAL_DETECTED"
    COMPENSATING = "COMPENSATING"
    UNWINDING = "UNWINDING"
    COMPLETED_HEDGED = "COMPLETED_HEDGED"
    COMPLETED_WITH_RESIDUAL = "COMPLETED_WITH_RESIDUAL"
    ABORTED = "ABORTED"
    CLOSED = "CLOSED"


class PackageRejectReasonV2(str, Enum):
    """Leg-level rejection/reconciliation reasons."""

    ACCEPTED = "ACCEPTED"
    INVALID_LEG = "INVALID_LEG"
    INVALID_DEPENDENCY = "INVALID_DEPENDENCY"
    STALE_MARKET = "STALE_MARKET"
    MIN_QTY = "MIN_QTY"
    MIN_NOTIONAL = "MIN_NOTIONAL"
    NO_LIQUIDITY = "NO_LIQUIDITY"
    POST_COST_MARGIN = "POST_COST_MARGIN"
    ATOMIC_ROLLBACK = "ATOMIC_ROLLBACK"
    SIBLING_PREFLIGHT_REJECTED = "SIBLING_PREFLIGHT_REJECTED"
    PRIMARY_REJECTED = "PRIMARY_REJECTED"
    UNWOUND = "UNWOUND"


class ResidualReasonCodeV1(str, Enum):
    """Why an explicit residual row exists."""

    PARTIAL_FILL = "PARTIAL_FILL"
    REJECTED = "REJECTED"
    QUANTIZATION = "QUANTIZATION"
    UNWOUND = "UNWOUND"


@dataclass(frozen=True, slots=True)
class PackageLegIntentV2:
    """One immutable linear package leg in canonical execution order."""

    order_id: int
    symbol_id: int
    signed_qty: float
    quantity_source: LegQuantitySourceV1 = LegQuantitySourceV1.FIXED
    source_leg: int = -1
    quantity_ratio: float = 1.0
    fill_fraction: float = 1.0
    qty_step: float = 0.0
    min_qty: float = 0.0
    min_notional: float = 0.0
    source_age_ns: int = 0
    venue_code: int = 0
    venue_sequence: int = 0


@dataclass(frozen=True, slots=True)
class PackageIntentV2:
    """Typed same-account package input consumed by the bounded executor."""

    package_id: int
    command_bar: int
    execution_policy: PackageExecutionPolicyV2
    residual_policy: ResidualRiskPolicyV1
    legs: tuple[PackageLegIntentV2, ...]
    max_staleness_ns: int = 0


@dataclass(frozen=True, slots=True)
class ResidualExposureV1:
    """Visible residual for one leg; never a hidden orphan position."""

    leg_index: int
    symbol_id: int
    quantity: float
    notional: float
    reason: ResidualReasonCodeV1


@dataclass(frozen=True, slots=True)
class PackageLegExecutionV2:
    """Resolved requested/actual quantity and terminal leg outcome."""

    order_id: int
    symbol_id: int
    requested_signed_qty: float
    filled_signed_qty: float
    compensation_signed_qty: float
    accepted: bool
    rejection_reason: PackageRejectReasonV2


@dataclass(frozen=True, slots=True)
class PackageExecutionResultV2:
    """Reference planner output; the Rust session commits its commands."""

    package_id: int
    policy: PackageExecutionPolicyV2
    final_state: PackageStateV2
    transitions: tuple[PackageStateV2, ...]
    legs: tuple[PackageLegExecutionV2, ...]
    residuals: tuple[ResidualExposureV1, ...]
    reservation_created: float
    reservation_consumed: float
    reservation_released: float
    package_fee: float
    residual_gross_notional: float
    outstanding_residual_gross_notional: float

    @property
    def command_signed_qty(self) -> tuple[float, ...]:
        """Net package command quantity per declared leg after compensation."""

        return tuple(leg.filled_signed_qty + leg.compensation_signed_qty for leg in self.legs)

    def invariants(self, *, tolerance: float = _EPSILON) -> dict[str, bool]:
        """Return the package V2 accounting/visibility invariants."""

        reservation_reconciles = abs(
            self.reservation_created - self.reservation_consumed - self.reservation_released
        ) <= tolerance
        atomic_clean = not (
            self.policy is PackageExecutionPolicyV2.ATOMIC_BAR_SIMULATION
            and self.final_state is PackageStateV2.ABORTED
            and any(leg.accepted for leg in self.legs)
        )
        residual_visible = bool(np.isfinite(self.residual_gross_notional)) and all(
            np.isfinite(item.quantity) and np.isfinite(item.notional) for item in self.residuals
        )
        return {
            "reservation_reconciles": reservation_reconciles,
            "atomic_immutable": atomic_clean,
            "residual_visible": residual_visible,
            "passed": reservation_reconciles and atomic_clean and residual_visible,
        }


def execute_package_intent_v2_reference(
    intent: PackageIntentV2,
    *,
    previous_units: Sequence[float],
    close_prices: Sequence[float],
    contract_sizes: Sequence[float],
    leverages: Sequence[float],
    fee_rates: Sequence[float],
    slippage_rate: float,
    equity: float,
) -> PackageExecutionResultV2:
    """Plan one package with the exact V2 preview/residual contract.

    The returned quantities are the simulated actual market fills to submit to
    the authoritative execution session. A ``fill_fraction`` is explicit test
    input, not a claim that this reference reconstructs order-book liquidity.
    """

    policy = _coerce(PackageExecutionPolicyV2, intent.execution_policy)
    residual_policy = _coerce(ResidualRiskPolicyV1, intent.residual_policy)
    legs = tuple(intent.legs)
    arrays = tuple(np.asarray(values, dtype=np.float64) for values in (
        previous_units,
        close_prices,
        contract_sizes,
        leverages,
        fee_rates,
    ))
    if not legs or any(values.ndim != 1 for values in arrays):
        raise ValueError("package V2 requires non-empty legs and one-dimensional account arrays")
    n_symbols = len(arrays[0])
    if any(len(values) != n_symbols for values in arrays[1:]) or n_symbols == 0:
        raise ValueError("package V2 account arrays must have one shared symbol width")
    if (
        not np.isfinite(equity)
        or equity <= 0.0
        or not np.isfinite(slippage_rate)
        or slippage_rate < 0.0
        or np.any(~np.isfinite(arrays[0]))
        or np.any(~np.isfinite(arrays[1]))
        or np.any(arrays[1] <= 0.0)
        or np.any(~np.isfinite(arrays[2]))
        or np.any(arrays[2] <= 0.0)
        or np.any(~np.isfinite(arrays[3]))
        or np.any(arrays[3] <= 0.0)
        or np.any(~np.isfinite(arrays[4]))
        or np.any(arrays[4] < 0.0)
    ):
        raise ValueError("package V2 has invalid account/instrument inputs")
    if policy is PackageExecutionPolicyV2.ATOMIC_BAR_SIMULATION and any(
        abs(float(leg.fill_fraction) - 1.0) > _EPSILON for leg in legs
    ):
        # Atomic bar simulation is deliberately all-or-none; a partial intent
        # must use BestEffort, Sequential, or HedgeAfterPrimary.
        return _atomic_reject(intent, PackageRejectReasonV2.ATOMIC_ROLLBACK)

    transitions: list[PackageStateV2] = [PackageStateV2.PLANNED]
    units = arrays[0].astype(np.float64, copy=True)
    working_equity = float(equity)
    requested = np.zeros(len(legs), dtype=np.float64)
    filled = np.zeros(len(legs), dtype=np.float64)
    compensation = np.zeros(len(legs), dtype=np.float64)
    accepted = np.zeros(len(legs), dtype=bool)
    reasons = [PackageRejectReasonV2.ACCEPTED for _ in legs]
    residuals: list[ResidualExposureV1] = []
    reservation_created = 0.0
    reservation_consumed = 0.0
    package_fee = 0.0

    if not _validate_leg_order(legs, n_symbols):
        return _atomic_reject(intent, PackageRejectReasonV2.INVALID_LEG)
    transitions.append(PackageStateV2.VALIDATED)

    # Atomic packages need a whole-transaction preview before any leg becomes
    # eligible. Other policies commit in canonical leg order.
    if policy is PackageExecutionPolicyV2.ATOMIC_BAR_SIMULATION:
        preview = _simulate_all(
            legs,
            units,
            working_equity,
            arrays,
            slippage_rate,
            int(intent.max_staleness_ns),
        )
        if preview is None:
            return _atomic_reject(intent, PackageRejectReasonV2.ATOMIC_ROLLBACK)
        transitions.extend((PackageStateV2.RESERVED, PackageStateV2.SUBMITTING))
        (
            units,
            working_equity,
            requested,
            filled,
            accepted,
            reasons,
            created,
            fees,
            computed_residuals,
        ) = preview
        reservation_created += created
        reservation_consumed += created
        package_fee += fees
        residuals.extend(computed_residuals)
    else:
        transitions.extend((PackageStateV2.RESERVED, PackageStateV2.SUBMITTING))
        for index, leg in enumerate(legs):
            resolved = _resolve_requested(legs, index, requested, filled)
            if resolved is None:
                reasons[index] = PackageRejectReasonV2.INVALID_DEPENDENCY
                if policy is PackageExecutionPolicyV2.HEDGE_AFTER_PRIMARY and index > 0:
                    reasons[index] = PackageRejectReasonV2.PRIMARY_REJECTED
                residuals.append(_rejected_residual(index, leg, arrays[1], arrays[2]))
                continue
            requested[index] = resolved
            if policy is PackageExecutionPolicyV2.HEDGE_AFTER_PRIMARY and index > 0 and not accepted[0]:
                reasons[index] = PackageRejectReasonV2.PRIMARY_REJECTED
                residuals.append(_rejected_residual(index, leg, arrays[1], arrays[2], quantity=resolved))
                continue
            outcome = _attempt_leg(
                leg,
                resolved,
                units,
                working_equity,
                arrays,
                slippage_rate,
                int(intent.max_staleness_ns),
            )
            if outcome is None:
                reasons[index] = _leg_reject_reason(leg, resolved, arrays[1], arrays[2], int(intent.max_staleness_ns))
                residuals.append(_rejected_residual(index, leg, arrays[1], arrays[2], quantity=resolved))
                continue
            units, working_equity, actual, demand, fee = outcome
            filled[index] = actual
            accepted[index] = True
            reservation_created += demand
            reservation_consumed += demand
            package_fee += fee
            if abs(resolved - actual) > _EPSILON:
                residuals.append(
                    ResidualExposureV1(
                        leg_index=index,
                        symbol_id=leg.symbol_id,
                        quantity=resolved - actual,
                        notional=(resolved - actual) * arrays[1][leg.symbol_id] * arrays[2][leg.symbol_id],
                        reason=ResidualReasonCodeV1.PARTIAL_FILL,
                    )
                )

    any_fill = bool(accepted.any())
    any_residual = bool(residuals)
    if not any_fill:
        transitions.extend((PackageStateV2.PREFLIGHT_REJECTED, PackageStateV2.ABORTED, PackageStateV2.CLOSED))
        return _result(
            intent, policy, PackageStateV2.ABORTED, transitions, legs, requested, filled,
            compensation, accepted, reasons, residuals, 0.0, 0.0, 0.0, 0.0,
        )

    if any_residual:
        transitions.extend((PackageStateV2.PARTIALLY_FILLED, PackageStateV2.RESIDUAL_DETECTED))
        if residual_policy is ResidualRiskPolicyV1.UNWIND_PACKAGE:
            transitions.extend((PackageStateV2.COMPENSATING, PackageStateV2.UNWINDING))
            for index in range(len(legs) - 1, -1, -1):
                if not accepted[index] or abs(filled[index]) <= _EPSILON:
                    continue
                leg = legs[index]
                outcome = _attempt_leg(
                    leg,
                    -filled[index],
                    units,
                    working_equity,
                    arrays,
                    slippage_rate,
                    int(intent.max_staleness_ns),
                    ignore_fraction=True,
                )
                if outcome is None:
                    # A failed unwind leaves the prior actual leg visible as
                    # outstanding residual. It is never silently flattened.
                    continue
                units, working_equity, actual, demand, fee = outcome
                compensation[index] += actual
                reservation_created += demand
                reservation_consumed += demand
                package_fee += fee
                residuals.append(
                    ResidualExposureV1(
                        leg_index=index,
                        symbol_id=leg.symbol_id,
                        quantity=actual,
                        notional=actual * arrays[1][leg.symbol_id] * arrays[2][leg.symbol_id],
                        reason=ResidualReasonCodeV1.UNWOUND,
                    )
                )
            outstanding = _outstanding_residual_notional(legs, filled + compensation, arrays[1], arrays[2])
            final_state = (
                PackageStateV2.COMPLETED_HEDGED
                if abs(outstanding) <= _EPSILON
                else PackageStateV2.COMPLETED_WITH_RESIDUAL
            )
        else:
            outstanding = _outstanding_residual_notional(legs, filled, arrays[1], arrays[2])
            final_state = PackageStateV2.COMPLETED_WITH_RESIDUAL
    else:
        transitions.append(PackageStateV2.FILLED)
        outstanding = 0.0
        final_state = PackageStateV2.COMPLETED_HEDGED
    transitions.extend((final_state, PackageStateV2.CLOSED))
    return _result(
        intent,
        policy,
        final_state,
        transitions,
        legs,
        requested,
        filled,
        compensation,
        accepted,
        reasons,
        residuals,
        reservation_created,
        reservation_consumed,
        0.0,
        package_fee,
        outstanding=outstanding,
    )


def _simulate_all(legs, units, equity, arrays, slippage_rate, max_staleness_ns):
    local_units = units.copy()
    local_equity = float(equity)
    requested = np.zeros(len(legs), dtype=np.float64)
    filled = np.zeros(len(legs), dtype=np.float64)
    accepted = np.zeros(len(legs), dtype=bool)
    reasons = [PackageRejectReasonV2.ACCEPTED for _ in legs]
    created = fees = 0.0
    residuals: list[ResidualExposureV1] = []
    for index, leg in enumerate(legs):
        resolved = _resolve_requested(legs, index, requested, filled)
        if resolved is None:
            return None
        requested[index] = resolved
        outcome = _attempt_leg(
            leg, resolved, local_units, local_equity, arrays, slippage_rate, max_staleness_ns
        )
        if outcome is None or abs(resolved - outcome[2]) > _EPSILON:
            return None
        local_units, local_equity, actual, demand, fee = outcome
        filled[index] = actual
        accepted[index] = True
        created += demand
        fees += fee
    return local_units, local_equity, requested, filled, accepted, reasons, created, fees, residuals


def _attempt_leg(leg, requested, units, equity, arrays, slippage_rate, max_staleness_ns, *, ignore_fraction=False):
    reason = _leg_reject_reason(leg, requested, arrays[1], arrays[2], max_staleness_ns)
    if reason is not PackageRejectReasonV2.ACCEPTED:
        return None
    fraction = 1.0 if ignore_fraction else float(leg.fill_fraction)
    if not np.isfinite(fraction) or fraction < 0.0 or fraction > 1.0:
        return None
    actual = _quantize_signed(requested * fraction, float(leg.qty_step))
    if abs(actual) <= _EPSILON:
        return None
    symbol = int(leg.symbol_id)
    close = float(arrays[1][symbol])
    contract_size = float(arrays[2][symbol])
    leverage = float(arrays[3][symbol])
    fee_rate = float(arrays[4][symbol])
    execution_price = close * (1.0 + slippage_rate if actual > 0.0 else 1.0 - slippage_rate)
    old_initial = abs(units[symbol]) * close * contract_size / leverage
    new_units = units.copy()
    new_units[symbol] += actual
    new_initial = abs(new_units[symbol]) * execution_price * contract_size / leverage
    current_initial = _total_initial_margin(units, arrays[1], arrays[2], arrays[3])
    fee = abs(actual) * execution_price * contract_size * fee_rate
    demand = fee + max(0.0, new_initial - old_initial)
    if demand > equity - current_initial + _EPSILON:
        return None
    next_equity = equity + actual * (close - execution_price) * contract_size - fee
    return new_units, next_equity, actual, demand, fee


def _resolve_requested(legs, index, requested, filled):
    leg = legs[index]
    source = _coerce(LegQuantitySourceV1, leg.quantity_source)
    if source is LegQuantitySourceV1.FIXED:
        value = float(leg.signed_qty)
    else:
        source_index = int(leg.source_leg)
        if source_index < 0 or source_index >= index:
            return None
        source_values = requested if source is LegQuantitySourceV1.PROPORTION_OF_REQUESTED else filled
        value = float(source_values[source_index]) * float(leg.quantity_ratio)
    if not np.isfinite(value):
        return None
    return _quantize_signed(value, float(leg.qty_step))


def _leg_reject_reason(leg, requested, close_prices, contract_sizes, max_staleness_ns):
    values = (leg.signed_qty, leg.quantity_ratio, leg.fill_fraction, leg.qty_step, leg.min_qty, leg.min_notional)
    if (
        any(not np.isfinite(float(value)) for value in values)
        or int(leg.symbol_id) < 0
        or abs(requested) <= _EPSILON
        or float(leg.qty_step) < 0.0
        or float(leg.min_qty) < 0.0
        or float(leg.min_notional) < 0.0
    ):
        return PackageRejectReasonV2.INVALID_LEG
    if max_staleness_ns >= 0 and int(leg.source_age_ns) > max_staleness_ns:
        return PackageRejectReasonV2.STALE_MARKET
    if abs(requested) + _EPSILON < float(leg.min_qty):
        return PackageRejectReasonV2.MIN_QTY
    notional = abs(requested) * float(close_prices[leg.symbol_id]) * float(contract_sizes[leg.symbol_id])
    if notional + _EPSILON < float(leg.min_notional):
        return PackageRejectReasonV2.MIN_NOTIONAL
    if float(leg.fill_fraction) <= _EPSILON:
        return PackageRejectReasonV2.NO_LIQUIDITY
    return PackageRejectReasonV2.ACCEPTED


def _validate_leg_order(legs, n_symbols):
    return all(
        int(leg.order_id) >= 0
        and 0 <= int(leg.symbol_id) < n_symbols
        and (index == 0 or int(legs[index - 1].venue_sequence) <= int(leg.venue_sequence))
        for index, leg in enumerate(legs)
    )


def _atomic_reject(intent, reason):
    legs = tuple(intent.legs)
    outcomes = tuple(
        PackageLegExecutionV2(
            order_id=int(leg.order_id), symbol_id=int(leg.symbol_id), requested_signed_qty=0.0,
            filled_signed_qty=0.0, compensation_signed_qty=0.0, accepted=False,
            rejection_reason=reason,
        )
        for leg in legs
    )
    return PackageExecutionResultV2(
        package_id=int(intent.package_id),
        policy=_coerce(PackageExecutionPolicyV2, intent.execution_policy),
        final_state=PackageStateV2.ABORTED,
        transitions=(
            PackageStateV2.PLANNED,
            PackageStateV2.PREFLIGHT_REJECTED,
            PackageStateV2.ABORTED,
            PackageStateV2.CLOSED,
        ),
        legs=outcomes,
        residuals=(),
        reservation_created=0.0,
        reservation_consumed=0.0,
        reservation_released=0.0,
        package_fee=0.0,
        residual_gross_notional=0.0,
        outstanding_residual_gross_notional=0.0,
    )


def _result(intent, policy, final_state, transitions, legs, requested, filled, compensation, accepted, reasons, residuals, created, consumed, released, package_fee, *, outstanding=0.0):
    outcomes = tuple(
        PackageLegExecutionV2(
            order_id=int(leg.order_id),
            symbol_id=int(leg.symbol_id),
            requested_signed_qty=float(requested[index]),
            filled_signed_qty=float(filled[index]),
            compensation_signed_qty=float(compensation[index]),
            accepted=bool(accepted[index]),
            rejection_reason=reasons[index],
        )
        for index, leg in enumerate(legs)
    )
    residual_gross = float(sum(abs(item.notional) for item in residuals if item.reason is not ResidualReasonCodeV1.UNWOUND))
    return PackageExecutionResultV2(
        package_id=int(intent.package_id),
        policy=policy,
        final_state=final_state,
        transitions=tuple(transitions),
        legs=outcomes,
        residuals=tuple(residuals),
        reservation_created=float(created),
        reservation_consumed=float(consumed),
        reservation_released=float(released),
        package_fee=float(package_fee),
        residual_gross_notional=residual_gross,
        outstanding_residual_gross_notional=float(abs(outstanding)),
    )


def _rejected_residual(index, leg, close_prices, contract_sizes, *, quantity=None):
    quantity = float(leg.signed_qty if quantity is None else quantity)
    if not 0 <= int(leg.symbol_id) < len(close_prices):
        return ResidualExposureV1(index, int(leg.symbol_id), quantity, 0.0, ResidualReasonCodeV1.REJECTED)
    return ResidualExposureV1(
        index,
        int(leg.symbol_id),
        quantity,
        quantity * float(close_prices[leg.symbol_id]) * float(contract_sizes[leg.symbol_id]),
        ResidualReasonCodeV1.REJECTED,
    )


def _outstanding_residual_notional(legs, effective_qty, close_prices, contract_sizes):
    # Outstanding exposure is a gross package quantity, never a signed
    # cross-leg net. A long primary and short hedge can offset market beta yet
    # still remain two visible legs that must be reconciled independently.
    return float(sum(
        abs(float(effective_qty[index]))
        * float(close_prices[leg.symbol_id])
        * float(contract_sizes[leg.symbol_id])
        for index, leg in enumerate(legs)
    ))


def _total_initial_margin(units, close_prices, contract_sizes, leverages):
    return float(np.sum(np.abs(units) * close_prices * contract_sizes / leverages))


def _quantize_signed(value: float, step: float) -> float:
    if not np.isfinite(value) or not np.isfinite(step) or step < 0.0:
        return 0.0
    if step == 0.0:
        return float(value)
    return float(np.copysign(floor(abs(value) / step + 1e-12) * step, value))


def _coerce(enum_type, value):
    return value if isinstance(value, enum_type) else enum_type(value)


__all__ = [
    "PACKAGE_EXECUTION_V2_CONTRACT_VERSION",
    "LegQuantitySourceV1",
    "PackageExecutionPolicyV2",
    "PackageExecutionResultV2",
    "PackageIntentV2",
    "PackageLegExecutionV2",
    "PackageLegIntentV2",
    "PackageRejectReasonV2",
    "PackageStateV2",
    "ResidualExposureV1",
    "ResidualReasonCodeV1",
    "ResidualRiskPolicyV1",
    "execute_package_intent_v2_reference",
]

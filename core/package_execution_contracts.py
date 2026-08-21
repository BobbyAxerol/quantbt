"""Transactional reference semantics for multi-leg execution packages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

import numpy as np
import pandas as pd


PACKAGE_EXECUTION_CONTRACT_VERSION = "package-transaction-v1"


class PackageTransactionPolicy(str, Enum):
    ATOMIC_ALL_OR_NONE = "atomic_all_or_none"
    BEST_EFFORT = "best_effort"
    SEQUENTIAL = "sequential"
    HEDGE_AFTER_PRIMARY = "hedge_after_primary"


class PackageState(str, Enum):
    PLANNED = "PLANNED"
    PREFLIGHT_ACCEPTED = "PREFLIGHT_ACCEPTED"
    PREFLIGHT_REJECTED = "PREFLIGHT_REJECTED"
    RESERVED = "RESERVED"
    COMMITTING = "COMMITTING"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    ABORTED = "ABORTED"
    COMPENSATING = "COMPENSATING"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class PackageLegRequest:
    leg_id: str
    symbol: str
    signed_qty: float
    price: float
    initial_margin: float
    fee_rate: float = 0.0
    source_age_ns: int = 0
    venue_code: int = 0
    venue_sequence: int = 0
    min_qty: float = 0.0
    min_notional: float = 0.0
    contract_size: float = 1.0


@dataclass(frozen=True)
class PackageTransactionResult:
    package_id: str
    policy: PackageTransactionPolicy
    final_state: PackageState
    accepted_legs: tuple[str, ...]
    rejected_legs: tuple[str, ...]
    fills: pd.DataFrame
    transitions: pd.DataFrame
    reservation_ledger: pd.DataFrame
    reserved_margin: float
    released_margin: float
    package_fee: float
    residual_notional: float
    rejection_reasons: tuple[str, ...]

    def invariants(self, *, tolerance: float = 1e-12) -> dict[str, object]:
        atomic_clean = not (
            self.policy is PackageTransactionPolicy.ATOMIC_ALL_OR_NONE
            and self.final_state in {PackageState.ABORTED, PackageState.PREFLIGHT_REJECTED}
            and not self.fills.empty
        )
        reservation_reconciles = abs(self.reserved_margin - self.released_margin) <= tolerance
        fee_reconciles = self.fills.empty or abs(float(self.fills["fee"].sum()) - self.package_fee) <= tolerance
        passed = atomic_clean and reservation_reconciles and fee_reconciles
        return {
            "contract_version": PACKAGE_EXECUTION_CONTRACT_VERSION,
            "passed": passed,
            "atomic_has_no_partial_mutation": atomic_clean,
            "reservation_released": reservation_reconciles,
            "leg_fees_reconcile": fee_reconciles,
            "residual_exposure_visible": bool(np.isfinite(self.residual_notional)),
        }


def execute_package_transaction_reference(
    package_id: str,
    legs: Sequence[PackageLegRequest],
    *,
    available_equity: float,
    policy: PackageTransactionPolicy | str = PackageTransactionPolicy.ATOMIC_ALL_OR_NONE,
    max_staleness_ns: int = 0,
) -> PackageTransactionResult:
    """Run deterministic preflight and commit without mutating an account."""

    selected = policy if isinstance(policy, PackageTransactionPolicy) else PackageTransactionPolicy(policy)
    if not package_id:
        raise ValueError("package_id is required")
    if not legs:
        raise ValueError("package requires at least one leg")
    if not np.isfinite(available_equity) or available_equity < 0.0:
        raise ValueError("available_equity must be finite and >= 0")

    transitions = [(PackageState.PLANNED.value, "package_created")]
    reasons = [_validate_leg(leg, max_staleness_ns) for leg in legs]
    valid = np.asarray([reason == "ACCEPTED" for reason in reasons], dtype=bool)
    margin = np.asarray([max(float(leg.initial_margin), 0.0) for leg in legs])
    fees = np.asarray([abs(leg.signed_qty) * leg.price * leg.contract_size * leg.fee_rate for leg in legs])
    required = margin + fees

    accepted = np.zeros(len(legs), dtype=bool)
    if selected is PackageTransactionPolicy.ATOMIC_ALL_OR_NONE:
        if valid.all() and float(required.sum()) <= available_equity + 1e-12:
            accepted[:] = True
        else:
            for col in range(len(legs)):
                if valid[col] and reasons[col] == "ACCEPTED":
                    reasons[col] = "ATOMIC_ROLLBACK" if valid.all() else "SIBLING_PREFLIGHT_REJECTED"
    else:
        remaining = float(available_equity)
        order = range(len(legs))
        for col in order:
            if not valid[col]:
                continue
            if required[col] <= remaining + 1e-12:
                accepted[col] = True
                remaining -= required[col]
            else:
                reasons[col] = "POST_COST_MARGIN"
        if selected is PackageTransactionPolicy.HEDGE_AFTER_PRIMARY and not accepted[0]:
            accepted[:] = False
            reasons = ["PRIMARY_REJECTED" if col else reasons[col] for col in range(len(legs))]

    if not accepted.any():
        transitions.extend(
            [(PackageState.PREFLIGHT_REJECTED.value, "preflight_failed"), (PackageState.ABORTED.value, "no_mutation")]
        )
        final_state = PackageState.ABORTED
        reserved = released = 0.0
    else:
        transitions.extend(
            [(PackageState.PREFLIGHT_ACCEPTED.value, "accepted_legs_locked"), (PackageState.RESERVED.value, "margin_reserved")]
        )
        reserved = float(margin[accepted].sum())
        transitions.append((PackageState.COMMITTING.value, "deterministic_leg_order"))
        if accepted.all():
            final_state = PackageState.FILLED
            transitions.append((PackageState.FILLED.value, "all_accepted_legs_committed"))
        else:
            final_state = PackageState.PARTIAL
            transitions.append((PackageState.PARTIAL.value, "residual_exposure_recorded"))
            if selected is PackageTransactionPolicy.HEDGE_AFTER_PRIMARY:
                transitions.append((PackageState.COMPENSATING.value, "hedge_failure_visible"))
        released = reserved

    fill_rows = [
        {
            "package_id": package_id,
            "leg_index": col,
            "leg_id": leg.leg_id,
            "symbol": leg.symbol,
            "venue_code": int(leg.venue_code),
            "venue_sequence": int(leg.venue_sequence),
            "signed_qty": float(leg.signed_qty),
            "price": float(leg.price),
            "notional": float(leg.signed_qty * leg.price * leg.contract_size),
            "fee": float(fees[col]),
            "initial_margin": float(margin[col]),
        }
        for col, leg in enumerate(legs)
        if accepted[col]
    ]
    fills = pd.DataFrame(fill_rows)
    residual = float(fills["notional"].sum()) if not fills.empty else 0.0
    reservation_ledger = pd.DataFrame(
        [
            {"package_id": package_id, "action": "reserve", "amount": reserved},
            {"package_id": package_id, "action": "release", "amount": released},
        ]
    )
    transition_frame = pd.DataFrame(
        [
            {"package_id": package_id, "sequence": sequence, "state": state, "reason": reason}
            for sequence, (state, reason) in enumerate(transitions)
        ]
    )
    return PackageTransactionResult(
        package_id=package_id, policy=selected, final_state=final_state,
        accepted_legs=tuple(legs[col].leg_id for col in range(len(legs)) if accepted[col]),
        rejected_legs=tuple(legs[col].leg_id for col in range(len(legs)) if not accepted[col]),
        fills=fills, transitions=transition_frame, reservation_ledger=reservation_ledger,
        reserved_margin=reserved, released_margin=released,
        package_fee=float(fees[accepted].sum()), residual_notional=residual,
        rejection_reasons=tuple(reasons),
    )


def _validate_leg(leg: PackageLegRequest, max_staleness_ns: int) -> str:
    if not leg.leg_id or not leg.symbol:
        return "INVALID_LEG"
    values = (leg.signed_qty, leg.price, leg.initial_margin, leg.fee_rate, leg.contract_size)
    if any(not np.isfinite(float(value)) for value in values) or leg.signed_qty == 0.0 or leg.price <= 0.0:
        return "INVALID_LEG"
    if leg.initial_margin < 0.0 or leg.fee_rate < 0.0 or leg.contract_size <= 0.0:
        return "INVALID_LEG"
    if max_staleness_ns >= 0 and leg.source_age_ns > max_staleness_ns:
        return "STALE_MARKET"
    if abs(leg.signed_qty) + 1e-12 < leg.min_qty:
        return "MIN_QTY"
    if abs(leg.signed_qty) * leg.price * leg.contract_size + 1e-12 < leg.min_notional:
        return "MIN_NOTIONAL"
    return "ACCEPTED"


__all__ = [
    "PACKAGE_EXECUTION_CONTRACT_VERSION",
    "PackageLegRequest",
    "PackageState",
    "PackageTransactionPolicy",
    "PackageTransactionResult",
    "execute_package_transaction_reference",
]

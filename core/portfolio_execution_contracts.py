"""Reference portfolio target executor used to freeze P0 rebalance semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

import numpy as np


PORTFOLIO_EXECUTION_CONTRACT_VERSION = "portfolio-target-execution-v1"


class PortfolioMarginAllocationPolicy(str, Enum):
    SEQUENTIAL_LEGACY = "sequential_legacy"
    PRO_RATA_TO_AVAILABLE_MARGIN = "pro_rata_to_available_margin"
    ALL_OR_NONE_TARGET = "all_or_none_target"
    REDUCE_FIRST_THEN_INCREASE = "reduce_first_then_increase"


class PortfolioTargetRejectReason(str, Enum):
    ACCEPTED = "ACCEPTED"
    NON_TRADABLE = "NON_TRADABLE"
    STALE_PRICE = "STALE_PRICE"
    INVALID_TARGET = "INVALID_TARGET"
    MIN_QTY = "MIN_QTY"
    MIN_NOTIONAL = "MIN_NOTIONAL"
    POST_COST_MARGIN = "POST_COST_MARGIN"
    ATOMIC_ROLLBACK = "ATOMIC_ROLLBACK"


@dataclass(frozen=True)
class PortfolioTargetExecutionResult:
    requested_units: np.ndarray
    accepted_units: np.ndarray
    delta_qty: np.ndarray
    traded_notional: np.ndarray
    fees: np.ndarray
    slippage: np.ndarray
    initial_margin: np.ndarray
    rejection_reasons: tuple[str, ...]
    policy: PortfolioMarginAllocationPolicy
    available_equity_after: float

    @property
    def gross_notional(self) -> float:
        return float(np.sum(np.abs(self.accepted_units) * self._prices * self._contract_sizes))

    # Private immutable arrays are attached by the constructor helper.  They
    # keep the public report concise without recomputing from mutable inputs.
    _prices: np.ndarray
    _contract_sizes: np.ndarray

    def invariants(self, *, tolerance: float = 1e-12) -> dict[str, object]:
        delta_residual = self.delta_qty - (self.accepted_units - self._previous_units)
        notional_residual = self.traded_notional - np.abs(self.delta_qty) * self._prices * self._contract_sizes
        passed = bool(
            np.max(np.abs(delta_residual), initial=0.0) <= tolerance
            and np.max(np.abs(notional_residual), initial=0.0) <= tolerance
            and self.available_equity_after >= -tolerance
        )
        return {
            "contract_version": PORTFOLIO_EXECUTION_CONTRACT_VERSION,
            "passed": passed,
            "delta_qty_identity": bool(np.max(np.abs(delta_residual), initial=0.0) <= tolerance),
            "traded_notional_identity": bool(np.max(np.abs(notional_residual), initial=0.0) <= tolerance),
            "post_cost_margin_valid": bool(self.available_equity_after >= -tolerance),
        }

    _previous_units: np.ndarray


def execute_portfolio_target_reference(
    previous_units: Sequence[float],
    requested_units: Sequence[float],
    prices: Sequence[float],
    *,
    equity: float,
    contract_sizes: float | Sequence[float] = 1.0,
    leverages: float | Sequence[float] = 1.0,
    fee_rates: float | Sequence[float] = 0.0,
    slippage_rates: float | Sequence[float] = 0.0,
    tradable: bool | Sequence[bool] = True,
    stale: bool | Sequence[bool] = False,
    min_qty: float | Sequence[float] = 0.0,
    min_notional: float | Sequence[float] = 0.0,
    reserved_margin: float = 0.0,
    policy: PortfolioMarginAllocationPolicy | str = PortfolioMarginAllocationPolicy.SEQUENTIAL_LEGACY,
) -> PortfolioTargetExecutionResult:
    """Execute one portfolio target against a deterministic cross-margin gate."""

    selected = policy if isinstance(policy, PortfolioMarginAllocationPolicy) else PortfolioMarginAllocationPolicy(policy)
    previous = _vector(previous_units)
    requested = _vector(requested_units, len(previous))
    price = _vector(prices, len(previous))
    valuation_price = np.where(np.isfinite(price) & (price > 0.0), price, 0.0)
    cs = _broadcast(contract_sizes, len(previous))
    lev = _broadcast(leverages, len(previous))
    fee = _broadcast(fee_rates, len(previous))
    slip = _broadcast(slippage_rates, len(previous))
    is_tradable = _broadcast_bool(tradable, len(previous))
    is_stale = _broadcast_bool(stale, len(previous))
    minimum_qty = _broadcast(min_qty, len(previous))
    minimum_notional = _broadcast(min_notional, len(previous))
    if not np.isfinite(equity) or equity <= 0.0 or reserved_margin < 0.0:
        raise ValueError("equity must be finite and > 0; reserved_margin must be >= 0")
    if np.any(cs <= 0.0) or np.any(lev <= 0.0) or np.any(fee < 0.0) or np.any(slip < 0.0):
        raise ValueError("contract sizes/leverages must be > 0 and cost rates >= 0")

    accepted = previous.copy()
    reasons = np.full(len(previous), PortfolioTargetRejectReason.ACCEPTED.value, dtype=object)
    valid = np.ones(len(previous), dtype=bool)
    for col in range(len(previous)):
        reason = _target_validation_reason(
            requested[col], price[col], cs[col], is_tradable[col], is_stale[col],
            minimum_qty[col], minimum_notional[col],
        )
        if reason is not PortfolioTargetRejectReason.ACCEPTED:
            valid[col] = False
            reasons[col] = reason.value

    if selected is PortfolioMarginAllocationPolicy.ALL_OR_NONE_TARGET:
        candidate = requested.copy()
        delta = candidate - previous
        costs = np.abs(delta) * valuation_price * cs * (fee + slip)
        margin = np.abs(candidate) * valuation_price * cs / lev
        if not valid.all() or margin.sum() + costs.sum() + reserved_margin > equity + 1e-12:
            reasons[:] = [
                reason if not valid[col] else PortfolioTargetRejectReason.ATOMIC_ROLLBACK.value
                for col, reason in enumerate(reasons)
            ]
        else:
            accepted = candidate
    elif selected is PortfolioMarginAllocationPolicy.PRO_RATA_TO_AVAILABLE_MARGIN:
        accepted = _reduction_baseline(previous, requested, valid)
        remaining = max(equity - reserved_margin - _margin(accepted, valuation_price, cs, lev), 0.0)
        increase = requested - accepted
        required = (
            np.abs(increase) * valuation_price * cs / lev
            + np.abs(increase) * valuation_price * cs * (fee + slip)
        )
        total_required = float(required[valid].sum())
        scale = min(1.0, remaining / total_required) if total_required > 0.0 else 1.0
        accepted[valid] += increase[valid] * scale
        if scale < 1.0:
            reasons[valid & (np.abs(increase) > 1e-12)] = PortfolioTargetRejectReason.POST_COST_MARGIN.value
    else:
        order = list(range(len(previous)))
        if selected is PortfolioMarginAllocationPolicy.REDUCE_FIRST_THEN_INCREASE:
            order.sort(key=lambda col: (not _is_reduction(previous[col], requested[col]), col))
        for col in order:
            if not valid[col]:
                continue
            candidate = accepted.copy()
            candidate[col] = requested[col]
            delta = candidate - previous
            costs = np.abs(delta) * valuation_price * cs * (fee + slip)
            required = _margin(candidate, valuation_price, cs, lev) + costs.sum() + reserved_margin
            if required <= equity + 1e-12:
                accepted[col] = requested[col]
            else:
                reasons[col] = PortfolioTargetRejectReason.POST_COST_MARGIN.value

    delta = accepted - previous
    traded_notional = np.abs(delta) * valuation_price * cs
    fees = traded_notional * fee
    slippage = traded_notional * slip
    margin = np.abs(accepted) * valuation_price * cs / lev
    available = float(equity - reserved_margin - margin.sum() - fees.sum() - slippage.sum())
    return PortfolioTargetExecutionResult(
        requested_units=_readonly(requested), accepted_units=_readonly(accepted), delta_qty=_readonly(delta),
        traded_notional=_readonly(traded_notional), fees=_readonly(fees), slippage=_readonly(slippage),
        initial_margin=_readonly(margin), rejection_reasons=tuple(map(str, reasons)), policy=selected,
        available_equity_after=available, _prices=_readonly(valuation_price), _contract_sizes=_readonly(cs),
        _previous_units=_readonly(previous),
    )


def _target_validation_reason(target, price, contract_size, tradable, stale, min_qty, min_notional):
    if not tradable:
        return PortfolioTargetRejectReason.NON_TRADABLE
    if stale or not np.isfinite(price) or price <= 0.0:
        return PortfolioTargetRejectReason.STALE_PRICE
    if not np.isfinite(target):
        return PortfolioTargetRejectReason.INVALID_TARGET
    if target != 0.0 and abs(target) + 1e-12 < min_qty:
        return PortfolioTargetRejectReason.MIN_QTY
    if target != 0.0 and abs(target) * price * contract_size + 1e-12 < min_notional:
        return PortfolioTargetRejectReason.MIN_NOTIONAL
    return PortfolioTargetRejectReason.ACCEPTED


def _reduction_baseline(previous, requested, valid):
    accepted = previous.copy()
    for col in range(len(previous)):
        if not valid[col]:
            continue
        if _is_reduction(previous[col], requested[col]):
            accepted[col] = requested[col]
        elif previous[col] != 0.0 and np.sign(previous[col]) != np.sign(requested[col]):
            accepted[col] = 0.0
    return accepted


def _is_reduction(previous: float, target: float) -> bool:
    return target == 0.0 or (np.sign(previous) == np.sign(target) and abs(target) <= abs(previous))


def _margin(units, prices, contract_sizes, leverages) -> float:
    return float(np.sum(np.abs(units) * prices * contract_sizes / leverages))


def _vector(value, length: int | None = None):
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 1 or (length is not None and len(array) != length):
        raise ValueError("portfolio vectors must be one-dimensional and equal length")
    return np.ascontiguousarray(array)


def _broadcast(value, length: int):
    return np.full(length, float(value)) if np.isscalar(value) else _vector(value, length)


def _broadcast_bool(value, length: int):
    array = np.full(length, bool(value), dtype=bool) if np.isscalar(value) else np.asarray(value, dtype=bool)
    if array.shape != (length,):
        raise ValueError("portfolio boolean vectors must match target length")
    return array


def _readonly(value):
    array = np.ascontiguousarray(value)
    array.setflags(write=False)
    return array


__all__ = [
    "PORTFOLIO_EXECUTION_CONTRACT_VERSION",
    "PortfolioMarginAllocationPolicy",
    "PortfolioTargetExecutionResult",
    "PortfolioTargetRejectReason",
    "execute_portfolio_target_reference",
]

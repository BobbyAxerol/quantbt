"""Fail-closed lowering from selected linear arbitrage plans to package V2.

This adapter does not promote ``QuantBTEndpoint.arbitrage``.  It translates a
small, audited subset of already-built Python order plans into immutable arrays
for :func:`run_bounded_package_market`; the common Rust session remains the
execution/accounting authority once the caller explicitly selects that route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from ..core.arbitrage import (
    ArbitragePlan,
    BasisArbitrageSpec,
    CalendarSpreadSpec,
    CrossExchangeArbSpec,
    IndexBasketArbSpec,
    PackageExecutionKind,
    StatArbPairSpec,
    TriangularArbSpec,
)
from ..core.schema import OrderType


_SUPPORTED_LINEAR_TYPES = (
    BasisArbitrageSpec,
    StatArbPairSpec,
    CalendarSpreadSpec,
    IndexBasketArbSpec,
)
_POLICY_MAP = {
    PackageExecutionKind.ATOMIC_ALL_OR_NONE: "atomic_bar_simulation",
    PackageExecutionKind.SEQUENTIAL: "sequential",
    PackageExecutionKind.BEST_EFFORT: "best_effort",
    PackageExecutionKind.HEDGE_AFTER_PRIMARY: "hedge_after_primary",
}


@dataclass(frozen=True, slots=True)
class BoundedArbitragePackageTapeV1:
    """Canonical arrays accepted by the explicit Rust package V2 helper."""

    command_bars: np.ndarray
    package_ids: np.ndarray
    package_leg_offsets: np.ndarray
    execution_policies: np.ndarray
    residual_policies: np.ndarray
    max_staleness_ns: np.ndarray
    order_ids: np.ndarray
    symbol_ids: np.ndarray
    signed_qty: np.ndarray
    quantity_sources: np.ndarray
    source_legs: np.ndarray
    quantity_ratios: np.ndarray
    fill_fractions: np.ndarray
    qty_step: np.ndarray
    min_qty: np.ndarray
    min_notional: np.ndarray
    source_age_ns: np.ndarray
    venue_codes: np.ndarray
    venue_sequence: np.ndarray
    metadata: Mapping[str, object]

    def request_kwargs(self) -> dict[str, object]:
        """Return the exact package-only arguments for the native helper."""

        return {
            "command_bars": self.command_bars,
            "package_ids": self.package_ids,
            "package_leg_offsets": self.package_leg_offsets,
            "execution_policies": self.execution_policies,
            "residual_policies": self.residual_policies,
            "max_staleness_ns": self.max_staleness_ns,
            "order_ids": self.order_ids,
            "symbol_ids": self.symbol_ids,
            "signed_qty": self.signed_qty,
            "quantity_sources": self.quantity_sources,
            "source_legs": self.source_legs,
            "quantity_ratios": self.quantity_ratios,
            "fill_fractions": self.fill_fractions,
            "qty_step": self.qty_step,
            "min_qty": self.min_qty,
            "min_notional": self.min_notional,
            "source_age_ns": self.source_age_ns,
            "venue_codes": self.venue_codes,
            "venue_sequence": self.venue_sequence,
        }


def compile_bounded_linear_arbitrage_package_tape(
    plan: ArbitragePlan,
    *,
    symbol_to_id: Mapping[str, int],
    datetime_index: pd.DatetimeIndex | None = None,
    residual_policy: str = "record",
    actual_fill_hedge: bool | None = None,
    fill_fraction: float | Mapping[str, float] = 1.0,
    max_staleness_ns: int = 0,
    source_age_ns: int | Mapping[str, int] = 0,
    external_id_start: int = 1,
) -> BoundedArbitragePackageTapeV1:
    """Lower a complete same-account linear arbitrage plan to package V2.

    Only basis, stat-arb pair, calendar-spread, and index-basket plans with
    linear contracts and immediate market orders qualify.  Triangular and
    cross-exchange plans reject explicitly because they require currency-flow
    or multi-venue/prefunding authority absent from the shared linear account.
    Funding/cash-carry/options remain on their specialized Python routes.
    """

    spec = plan.spec
    if isinstance(spec, TriangularArbSpec):
        raise NotImplementedError(
            "triangular arbitrage is not representable by bounded package V2: "
            "currency conservation is required"
        )
    if isinstance(spec, CrossExchangeArbSpec):
        raise NotImplementedError(
            "cross-exchange arbitrage is not representable by bounded package V2: "
            "multi-venue prefunding and settlement clocks are required"
        )
    if not isinstance(spec, _SUPPORTED_LINEAR_TYPES):
        raise NotImplementedError(
            f"{type(spec).__name__} remains on its specialized Python executor; "
            "bounded package V2 only accepts selected same-account linear plans"
        )
    if any(leg.contract_type.value != "linear" for leg in spec.legs):
        raise NotImplementedError("bounded package V2 accepts linear arbitrage legs only")
    nonempty_venues = {str(leg.venue) for leg in spec.legs if leg.venue}
    if len(nonempty_venues) > 1:
        raise NotImplementedError("bounded package V2 requires one same-account venue")
    policy = _POLICY_MAP.get(spec.execution_policy.kind)
    if policy is None:
        raise NotImplementedError(
            f"arbitrage execution policy={spec.execution_policy.kind.value!r} has no package V2 mapping"
        )
    if actual_fill_hedge is None:
        actual_fill_hedge = policy == "hedge_after_primary"
    if actual_fill_hedge and policy != "hedge_after_primary":
        raise ValueError("actual_fill_hedge is valid only for hedge_after_primary packages")
    if policy == "hedge_after_primary" and not actual_fill_hedge:
        raise ValueError(
            "hedge_after_primary must derive hedge legs from the actual primary fill; "
            "use sequential for fixed independent legs"
        )
    if spec.execution_policy.order_type is not OrderType.MARKET:
        raise NotImplementedError("bounded package V2 accepts immediate market orders only")
    if residual_policy not in {"record", "unwind_package"}:
        raise ValueError("residual_policy must be 'record' or 'unwind_package'")
    if max_staleness_ns < 0:
        raise ValueError("max_staleness_ns must be >= 0 for the bounded adapter")

    market_index = pd.DatetimeIndex(plan.target_units.index if datetime_index is None else datetime_index)
    if market_index.empty:
        raise ValueError("bounded package V2 requires a non-empty market datetime index")
    if not market_index.is_unique or not market_index.is_monotonic_increasing:
        raise ValueError("bounded package V2 market datetime index must be unique and ascending")
    missing = [leg.symbol for leg in spec.legs if leg.symbol not in symbol_to_id]
    if missing:
        raise ValueError(f"symbol_to_id is missing arbitrage legs: {sorted(missing)}")
    if any(int(symbol_to_id[leg.symbol]) < 0 for leg in spec.legs):
        raise ValueError("symbol_to_id values must be non-negative")

    leg_by_symbol = {leg.symbol: leg for leg in spec.legs}
    grouped: dict[pd.Timestamp, list] = {}
    for order in plan.orders:
        timestamp = pd.Timestamp(order.timestamp)
        if timestamp.tz is None and market_index.tz is not None:
            timestamp = timestamp.tz_localize(market_index.tz)
        elif timestamp.tz is not None and market_index.tz is not None:
            timestamp = timestamp.tz_convert(market_index.tz)
        grouped.setdefault(timestamp, []).append(order)
    if not grouped:
        raise ValueError("arbitrage plan has no package orders to lower")

    command_bars: list[int] = []
    package_ids: list[int] = []
    offsets = [0]
    order_ids: list[int] = []
    symbol_ids: list[int] = []
    signed_qty: list[float] = []
    quantity_sources: list[str] = []
    source_legs: list[int] = []
    quantity_ratios: list[float] = []
    fill_fractions: list[float] = []
    qty_step: list[float] = []
    min_qty: list[float] = []
    min_notional: list[float] = []
    source_ages: list[int] = []
    venue_codes: list[int] = []
    venue_sequence: list[int] = []
    next_order_id = int(external_id_start)

    for package_offset, (timestamp, orders) in enumerate(sorted(grouped.items())):
        bar = int(market_index.get_indexer([timestamp])[0])
        if bar <= 0 or bar + 1 >= len(market_index):
            raise ValueError(
                "bounded package V2 requires each plan timestamp to leave a preceding "
                "snapshot and one following reconciliation bar"
            )
        ordered = sorted(orders, key=lambda order: tuple(leg.symbol for leg in spec.legs).index(order.symbol))
        if len(ordered) < 2:
            raise ValueError("bounded arbitrage package must contain at least two legs")
        command_bars.append(bar)
        package_ids.append(package_offset + 1)
        primary_signed_qty = float(ordered[0].signed_qty)
        if actual_fill_hedge and abs(primary_signed_qty) <= 1e-12:
            raise ValueError("actual-fill hedge package primary leg must have non-zero signed quantity")
        for leg_index, order in enumerate(ordered):
            if order.symbol not in leg_by_symbol or order.reduce_only:
                raise ValueError("bounded package V2 requires non-reduce-only declared arbitrage legs")
            leg = leg_by_symbol[order.symbol]
            actual_dependency = actual_fill_hedge and leg_index > 0
            if isinstance(fill_fraction, Mapping):
                fraction = float(fill_fraction.get(order.symbol, 1.0))
            else:
                fraction = float(fill_fraction)
            if isinstance(source_age_ns, Mapping):
                age = int(source_age_ns.get(order.symbol, 0))
            else:
                age = int(source_age_ns)
            order_ids.append(next_order_id)
            next_order_id += 1
            symbol_ids.append(int(symbol_to_id[order.symbol]))
            signed_qty.append(float(order.signed_qty))
            quantity_sources.append("proportion_of_actual_fill" if actual_dependency else "fixed")
            source_legs.append(0 if actual_dependency else -1)
            quantity_ratios.append(float(order.signed_qty) / primary_signed_qty if actual_dependency else 1.0)
            fill_fractions.append(fraction)
            qty_step.append(float(leg.qty_step))
            min_qty.append(float(leg.min_qty))
            min_notional.append(float(leg.min_notional))
            source_ages.append(age)
            venue_codes.append(0)
            venue_sequence.append(leg_index)
        offsets.append(len(order_ids))

    return BoundedArbitragePackageTapeV1(
        command_bars=np.asarray(command_bars, dtype=np.uint64),
        package_ids=np.asarray(package_ids, dtype=np.uint64),
        package_leg_offsets=np.asarray(offsets, dtype=np.uint64),
        execution_policies=np.asarray([policy] * len(package_ids)),
        residual_policies=np.asarray([residual_policy] * len(package_ids)),
        max_staleness_ns=np.full(len(package_ids), int(max_staleness_ns), dtype=np.int64),
        order_ids=np.asarray(order_ids, dtype=np.int64),
        symbol_ids=np.asarray(symbol_ids, dtype=np.uint32),
        signed_qty=np.asarray(signed_qty, dtype=np.float64),
        quantity_sources=np.asarray(quantity_sources),
        source_legs=np.asarray(source_legs, dtype=np.int64),
        quantity_ratios=np.asarray(quantity_ratios, dtype=np.float64),
        fill_fractions=np.asarray(fill_fractions, dtype=np.float64),
        qty_step=np.asarray(qty_step, dtype=np.float64),
        min_qty=np.asarray(min_qty, dtype=np.float64),
        min_notional=np.asarray(min_notional, dtype=np.float64),
        source_age_ns=np.asarray(source_ages, dtype=np.int64),
        venue_codes=np.asarray(venue_codes, dtype=np.uint16),
        venue_sequence=np.asarray(venue_sequence, dtype=np.uint32),
        metadata={
            "adapter": "bounded_linear_arbitrage_package_v1",
            "arb_type": spec.arb_type.value,
            "execution_policy": policy,
            "actual_fill_hedge": bool(actual_fill_hedge),
            "auto_promoted": False,
            "unsupported": "triangular/cross_exchange/funding/cash_carry/options",
        },
    )


__all__ = ["BoundedArbitragePackageTapeV1", "compile_bounded_linear_arbitrage_package_tape"]

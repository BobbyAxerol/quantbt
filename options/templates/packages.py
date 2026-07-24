"""
V1 option package builders.

Builders intentionally emit `OptionPackageIntent` only. They do not calculate
payoff, PnL, Greeks, margin, or account state.
"""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from ...core.schema import OrderSide, OrderType, TimeInForce
from ..packages import OptionPackageExecutionPolicy, OptionPackageIntent, OptionPackageLeg


def long_call(timestamp_ns: int, call_id: str, *, quantity: float = 1.0, package_id: Optional[str] = None, **kwargs) -> OptionPackageIntent:
    """Buy one call package."""
    return _single(timestamp_ns, call_id, OrderSide.BUY, "long_call", quantity=quantity, package_id=package_id, **kwargs)


def short_call(timestamp_ns: int, call_id: str, *, quantity: float = 1.0, package_id: Optional[str] = None, **kwargs) -> OptionPackageIntent:
    """Sell one call package."""
    return _single(timestamp_ns, call_id, OrderSide.SELL, "short_call", quantity=quantity, package_id=package_id, **kwargs)


def long_put(timestamp_ns: int, put_id: str, *, quantity: float = 1.0, package_id: Optional[str] = None, **kwargs) -> OptionPackageIntent:
    """Buy one put package."""
    return _single(timestamp_ns, put_id, OrderSide.BUY, "long_put", quantity=quantity, package_id=package_id, **kwargs)


def short_put(timestamp_ns: int, put_id: str, *, quantity: float = 1.0, package_id: Optional[str] = None, **kwargs) -> OptionPackageIntent:
    """Sell one put package."""
    return _single(timestamp_ns, put_id, OrderSide.SELL, "short_put", quantity=quantity, package_id=package_id, **kwargs)


def straddle(
    timestamp_ns: int,
    call_id: str,
    put_id: str,
    *,
    side: str = "long",
    quantity: float = 1.0,
    package_id: Optional[str] = None,
    **kwargs,
) -> OptionPackageIntent:
    """Create a long or short straddle."""
    order_side = _side_from_direction(side, long_side=OrderSide.BUY)
    return _package(
        timestamp_ns,
        package_id or f"{side}_straddle:{call_id}:{put_id}",
        (
            _leg(call_id, order_side, 1.0, role="call", **kwargs),
            _leg(put_id, order_side, 1.0, role="put", **kwargs),
        ),
        quantity=quantity,
        strategy="straddle",
        **_package_kwargs(kwargs),
    )


def strangle(
    timestamp_ns: int,
    call_id: str,
    put_id: str,
    *,
    side: str = "long",
    quantity: float = 1.0,
    package_id: Optional[str] = None,
    **kwargs,
) -> OptionPackageIntent:
    """Create a long or short strangle."""
    order_side = _side_from_direction(side, long_side=OrderSide.BUY)
    return _package(
        timestamp_ns,
        package_id or f"{side}_strangle:{call_id}:{put_id}",
        (
            _leg(call_id, order_side, 1.0, role="call", **kwargs),
            _leg(put_id, order_side, 1.0, role="put", **kwargs),
        ),
        quantity=quantity,
        strategy="strangle",
        **_package_kwargs(kwargs),
    )


def vertical(
    timestamp_ns: int,
    long_option_id: str,
    short_option_id: str,
    *,
    quantity: float = 1.0,
    package_id: Optional[str] = None,
    **kwargs,
) -> OptionPackageIntent:
    """Create a debit vertical: buy one option and sell another same-type option."""
    return _package(
        timestamp_ns,
        package_id or f"vertical:{long_option_id}:{short_option_id}",
        (
            _leg(long_option_id, OrderSide.BUY, 1.0, role="long_strike", **kwargs),
            _leg(short_option_id, OrderSide.SELL, 1.0, role="short_strike", **kwargs),
        ),
        quantity=quantity,
        strategy="vertical",
        **_package_kwargs(kwargs),
    )


def butterfly(
    timestamp_ns: int,
    lower_id: str,
    middle_id: str,
    upper_id: str,
    *,
    quantity: float = 1.0,
    package_id: Optional[str] = None,
    **kwargs,
) -> OptionPackageIntent:
    """Create a 1:-2:1 long butterfly."""
    return _package(
        timestamp_ns,
        package_id or f"butterfly:{lower_id}:{middle_id}:{upper_id}",
        (
            _leg(lower_id, OrderSide.BUY, 1.0, role="lower_wing", **kwargs),
            _leg(middle_id, OrderSide.SELL, 2.0, role="body", **kwargs),
            _leg(upper_id, OrderSide.BUY, 1.0, role="upper_wing", **kwargs),
        ),
        quantity=quantity,
        strategy="butterfly",
        **_package_kwargs(kwargs),
    )


def condor(
    timestamp_ns: int,
    lower_long_id: str,
    lower_short_id: str,
    upper_short_id: str,
    upper_long_id: str,
    *,
    quantity: float = 1.0,
    package_id: Optional[str] = None,
    **kwargs,
) -> OptionPackageIntent:
    """Create a 1:-1:-1:1 long condor."""
    return _package(
        timestamp_ns,
        package_id or f"condor:{lower_long_id}:{lower_short_id}:{upper_short_id}:{upper_long_id}",
        (
            _leg(lower_long_id, OrderSide.BUY, 1.0, role="lower_wing", **kwargs),
            _leg(lower_short_id, OrderSide.SELL, 1.0, role="lower_body", **kwargs),
            _leg(upper_short_id, OrderSide.SELL, 1.0, role="upper_body", **kwargs),
            _leg(upper_long_id, OrderSide.BUY, 1.0, role="upper_wing", **kwargs),
        ),
        quantity=quantity,
        strategy="condor",
        **_package_kwargs(kwargs),
    )


def calendar(
    timestamp_ns: int,
    near_id: str,
    far_id: str,
    *,
    side: str = "long",
    quantity: float = 1.0,
    package_id: Optional[str] = None,
    **kwargs,
) -> OptionPackageIntent:
    """Create a calendar spread. Long calendar sells near expiry and buys far expiry."""
    near_side = OrderSide.SELL if str(side).lower() == "long" else OrderSide.BUY
    far_side = OrderSide.BUY if str(side).lower() == "long" else OrderSide.SELL
    return _package(
        timestamp_ns,
        package_id or f"{side}_calendar:{near_id}:{far_id}",
        (
            _leg(near_id, near_side, 1.0, role="near_expiry", **kwargs),
            _leg(far_id, far_side, 1.0, role="far_expiry", **kwargs),
        ),
        quantity=quantity,
        strategy="calendar",
        **_package_kwargs(kwargs),
    )


def covered_call(
    timestamp_ns: int,
    underlying_id: str,
    call_id: str,
    *,
    quantity: float = 1.0,
    underlying_ratio: float = 1.0,
    package_id: Optional[str] = None,
    **kwargs,
) -> OptionPackageIntent:
    """Create a covered call package: long underlying, short call."""
    return _package(
        timestamp_ns,
        package_id or f"covered_call:{underlying_id}:{call_id}",
        (
            _leg(underlying_id, OrderSide.BUY, underlying_ratio, role="underlying", **_with_leg_metadata(kwargs, {"asset_role": "underlying"})),
            _leg(call_id, OrderSide.SELL, 1.0, role="short_call", **kwargs),
        ),
        quantity=quantity,
        strategy="covered_call",
        **_package_kwargs(kwargs),
    )


def collar(
    timestamp_ns: int,
    underlying_id: str,
    put_id: str,
    call_id: str,
    *,
    quantity: float = 1.0,
    underlying_ratio: float = 1.0,
    package_id: Optional[str] = None,
    **kwargs,
) -> OptionPackageIntent:
    """Create a collar package: long underlying, long put, short call."""
    return _package(
        timestamp_ns,
        package_id or f"collar:{underlying_id}:{put_id}:{call_id}",
        (
            _leg(underlying_id, OrderSide.BUY, underlying_ratio, role="underlying", **_with_leg_metadata(kwargs, {"asset_role": "underlying"})),
            _leg(put_id, OrderSide.BUY, 1.0, role="protective_put", **kwargs),
            _leg(call_id, OrderSide.SELL, 1.0, role="covered_call", **kwargs),
        ),
        quantity=quantity,
        strategy="collar",
        **_package_kwargs(kwargs),
    )


def risk_reversal(
    timestamp_ns: int,
    put_id: str,
    call_id: str,
    *,
    direction: str = "bullish",
    quantity: float = 1.0,
    package_id: Optional[str] = None,
    **kwargs,
) -> OptionPackageIntent:
    """Create a bullish or bearish risk reversal."""
    bullish = str(direction).lower() == "bullish"
    return _package(
        timestamp_ns,
        package_id or f"{direction}_risk_reversal:{put_id}:{call_id}",
        (
            _leg(put_id, OrderSide.SELL if bullish else OrderSide.BUY, 1.0, role="put", **kwargs),
            _leg(call_id, OrderSide.BUY if bullish else OrderSide.SELL, 1.0, role="call", **kwargs),
        ),
        quantity=quantity,
        strategy="risk_reversal",
        **_package_kwargs(kwargs),
    )


def _single(
    timestamp_ns: int,
    instrument_id: str,
    side: OrderSide,
    strategy: str,
    *,
    quantity: float,
    package_id: Optional[str],
    **kwargs,
) -> OptionPackageIntent:
    return _package(
        timestamp_ns,
        package_id or f"{strategy}:{instrument_id}",
        (_leg(instrument_id, side, 1.0, role=strategy, **kwargs),),
        quantity=quantity,
        strategy=strategy,
        **_package_kwargs(kwargs),
    )


def _package(
    timestamp_ns: int,
    package_id: str,
    legs: Sequence[OptionPackageLeg],
    *,
    quantity: float,
    strategy: str,
    execution_policy: OptionPackageExecutionPolicy = OptionPackageExecutionPolicy.ATOMIC_ALL_OR_NONE,
    max_debit: Optional[float] = None,
    min_credit: Optional[float] = None,
    tag: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> OptionPackageIntent:
    return OptionPackageIntent(
        timestamp_ns=timestamp_ns,
        package_id=package_id,
        legs=tuple(legs),
        quantity=quantity,
        execution_policy=execution_policy,
        max_debit=max_debit,
        min_credit=min_credit,
        tag=tag,
        metadata={"template": strategy, **(metadata or {})},
    )


def _leg(
    instrument_id: str,
    side: OrderSide,
    ratio: float,
    *,
    role: str,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Optional[float] = None,
    tif: TimeInForce = TimeInForce.FOK,
    tag: Optional[str] = None,
    metadata: Optional[dict] = None,
    **_,
) -> OptionPackageLeg:
    return OptionPackageLeg(
        instrument_id=instrument_id,
        side=side,
        ratio=ratio,
        order_type=order_type,
        limit_price=limit_price,
        tif=tif,
        role=role,
        tag=tag,
        metadata=dict(metadata or {}),
    )


def _package_kwargs(kwargs: dict) -> dict:
    return {
        key: kwargs[key]
        for key in ("execution_policy", "max_debit", "min_credit", "tag", "metadata")
        if key in kwargs
    }


def _with_leg_metadata(kwargs: dict, extra: dict) -> dict:
    out = dict(kwargs)
    out["metadata"] = {**dict(kwargs.get("metadata") or {}), **extra}
    return out


def _side_from_direction(direction: str, *, long_side: OrderSide) -> OrderSide:
    value = str(direction).lower().strip()
    if value == "long":
        return long_side
    if value == "short":
        return OrderSide.SELL if long_side is OrderSide.BUY else OrderSide.BUY
    raise ValueError("direction must be long or short")

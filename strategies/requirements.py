"""Explicit callback projection and scheduling requirements."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping


_MARKET_FIELDS = frozenset({"open", "high", "low", "close", "volume"})
_ACCOUNT_FIELDS = frozenset(
    {"equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated"}
)
_POSITION_FIELDS = frozenset({"qty"})
_DETAIL_LEVELS = frozenset({"none", "new_only", "snapshot"})
_CONTEXT_MODES = frozenset({"compatibility", "numeric"})


def _fields(values: Iterable[str], valid: frozenset[str], label: str) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(value).lower().strip() for value in values))
    unknown = sorted(set(normalized) - valid)
    if unknown:
        raise ValueError(f"unsupported strategy {label}: {', '.join(unknown)}")
    return normalized


@dataclass(frozen=True, slots=True)
class CallbackSchedule:
    """Declare when Python must be called after a bar is processed.

    ``every_n_bars=1`` is the conservative compatibility behavior. Set it to
    ``None`` and provide explicit bars/wake reasons for sparse callbacks.
    """

    every_n_bars: int | None = 1
    explicit_bars: tuple[int, ...] = ()
    on_fill: bool = True
    on_order_event: bool = True
    on_liquidation: bool = True

    def __post_init__(self) -> None:
        if self.every_n_bars is not None and int(self.every_n_bars) <= 0:
            raise ValueError("every_n_bars must be > 0 or None")
        bars = tuple(sorted(set(int(bar) for bar in self.explicit_bars)))
        if any(bar < 0 for bar in bars):
            raise ValueError("explicit callback bars must be >= 0")
        object.__setattr__(self, "every_n_bars", None if self.every_n_bars is None else int(self.every_n_bars))
        object.__setattr__(self, "explicit_bars", bars)

    @property
    def is_every_bar(self) -> bool:
        return self.every_n_bars == 1 and not self.explicit_bars

    def should_callback(
        self,
        bar: int,
        *,
        has_fill: bool = False,
        has_order_event: bool = False,
        liquidated: bool = False,
    ) -> bool:
        periodic = self.every_n_bars is not None and int(bar) % self.every_n_bars == 0
        return bool(
            periodic
            or int(bar) in self.explicit_bars
            or (self.on_fill and has_fill)
            or (self.on_order_event and has_order_event)
            or (self.on_liquidation and liquidated)
        )


@dataclass(frozen=True, slots=True)
class StrategyContextRequirements:
    """Compile-time strategy projection contract.

    Compatibility is intentionally conservative. Numeric strategies opt into
    primitive IDs, nanosecond timestamps, array views, and a command writer.
    """

    market: tuple[str, ...] = ("open", "high", "low", "close", "volume")
    account: tuple[str, ...] = (
        "equity",
        "available_equity",
        "initial_margin",
        "maintenance_margin",
        "liquidated",
    )
    positions: tuple[str, ...] = ("qty",)
    fills: str = "new_only"
    events: str = "new_only"
    active_orders: str = "snapshot"
    callback: CallbackSchedule = field(default_factory=CallbackSchedule)
    context_mode: str = "compatibility"

    def __post_init__(self) -> None:
        object.__setattr__(self, "market", _fields(self.market, _MARKET_FIELDS, "market fields"))
        object.__setattr__(self, "account", _fields(self.account, _ACCOUNT_FIELDS, "account fields"))
        object.__setattr__(self, "positions", _fields(self.positions, _POSITION_FIELDS, "position fields"))
        for name in ("fills", "events", "active_orders"):
            value = str(getattr(self, name)).lower().strip()
            if value not in _DETAIL_LEVELS:
                raise ValueError(f"{name} must be one of: {', '.join(sorted(_DETAIL_LEVELS))}")
            object.__setattr__(self, name, value)
        mode = str(self.context_mode).lower().strip()
        if mode not in _CONTEXT_MODES:
            raise ValueError("context_mode must be compatibility or numeric")
        object.__setattr__(self, "context_mode", mode)

    @property
    def declared(self) -> bool:
        return True

    @property
    def projection_mask(self) -> int:
        mask = 0
        if self.positions:
            mask |= 1
        if self.fills != "none":
            mask |= 2
        if self.events != "none":
            mask |= 4
        if self.active_orders != "none":
            mask |= 8
        return mask


def strategy_requirements(**kwargs):
    """Attach validated requirements to a strategy function or class."""

    requirements = StrategyContextRequirements(**kwargs)

    def decorate(strategy):
        setattr(strategy, "quantbt_requirements", requirements)
        return strategy

    return decorate


def resolve_strategy_requirements(strategy) -> StrategyContextRequirements:
    """Resolve typed requirements, legacy declarations, or safe defaults."""

    declaration = getattr(strategy, "quantbt_requirements", None)
    if declaration is not None:
        if not isinstance(declaration, StrategyContextRequirements):
            raise TypeError("quantbt_requirements must be StrategyContextRequirements")
        return declaration
    legacy = getattr(strategy, "native_context_requirements", None)
    if legacy is None:
        return StrategyContextRequirements()
    if not isinstance(legacy, Mapping):
        raise TypeError("native_context_requirements must be a mapping")
    valid = {"fills", "events", "active_orders", "positions", "margin"}
    unknown = sorted(set(legacy) - valid)
    if unknown:
        raise ValueError(f"unsupported native context requirement: {unknown[0]!r}")
    margin = bool(legacy.get("margin", True))
    return StrategyContextRequirements(
        account=(
            ("equity", "available_equity", "initial_margin", "maintenance_margin", "liquidated")
            if margin
            else ("equity", "liquidated")
        ),
        positions=("qty",) if bool(legacy.get("positions", True)) else (),
        fills="new_only" if bool(legacy.get("fills", True)) else "none",
        events="new_only" if bool(legacy.get("events", True)) else "none",
        active_orders="snapshot" if bool(legacy.get("active_orders", True)) else "none",
        context_mode="compatibility",
    )


__all__ = [
    "CallbackSchedule",
    "StrategyContextRequirements",
    "resolve_strategy_requirements",
    "strategy_requirements",
]

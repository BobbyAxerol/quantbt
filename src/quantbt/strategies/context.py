"""Ephemeral numeric callback context and materialization adapter."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..core.reactive import NativeStrategyContext
from .requirements import StrategyContextRequirements


class StaleStrategyContextError(RuntimeError):
    """Raised when a callback retains an ephemeral context beyond its lease."""


@dataclass(slots=True)
class _ContextLease:
    generation: int
    active: bool = True


class StrategyContextView:
    """Read-only numeric view over one authoritative engine projection."""

    __slots__ = ("_session", "_bar", "_requirements", "_lease", "_symbols")

    def __init__(self, session, bar: int, requirements: StrategyContextRequirements, generation: int):
        self._session = session
        self._bar = int(bar)
        self._requirements = requirements
        self._lease = _ContextLease(int(generation))
        self._symbols = tuple(session.symbols)

    def _check(self) -> None:
        if not self._lease.active or int(getattr(self._session, "generation", -1)) != self._lease.generation:
            raise StaleStrategyContextError(
                "StrategyContextView is ephemeral and is no longer valid; copy primitive values inside the callback"
            )

    def invalidate(self) -> None:
        self._lease.active = False

    @property
    def bar_index(self) -> int:
        self._check()
        return self._bar

    @property
    def timestamp_ns(self) -> int:
        self._check()
        return int(self._session.idx.asi8[self._bar])

    @property
    def symbol_count(self) -> int:
        return len(self._symbols)

    @property
    def symbols(self) -> tuple[str, ...]:
        return self._symbols

    def _market(self, name: str) -> np.ndarray:
        self._check()
        if name not in self._requirements.market:
            raise AttributeError(f"strategy did not declare market field {name!r}")
        source = self._session.opens_arr if name == "open" else (
            self._session.volumes_arr if name == "volume" else getattr(self._session.market_arrays, f"{name}s")
        )
        return source[self._bar]

    @property
    def open_values(self) -> np.ndarray:
        return self._market("open")

    @property
    def high_values(self) -> np.ndarray:
        return self._market("high")

    @property
    def low_values(self) -> np.ndarray:
        return self._market("low")

    @property
    def close_values(self) -> np.ndarray:
        return self._market("close")

    @property
    def volume_values(self) -> np.ndarray:
        return self._market("volume")

    def close(self, symbol_id: int) -> float:
        return float(self.close_values[int(symbol_id)])

    # Scalar field access is the common numeric callback surface shared by
    # the compatibility bridge and Rust-led R1 co-runtime. The array-valued
    # properties above remain available for legacy numeric strategies.
    def open(self, symbol_id: int) -> float:
        return float(self.open_values[int(symbol_id)])

    def high(self, symbol_id: int) -> float:
        return float(self.high_values[int(symbol_id)])

    def low(self, symbol_id: int) -> float:
        return float(self.low_values[int(symbol_id)])

    def volume(self, symbol_id: int) -> float:
        return float(self.volume_values[int(symbol_id)])

    def position_qty(self, symbol_id: int) -> float:
        self._check()
        if not self._requirements.positions:
            raise AttributeError("strategy did not declare positions")
        return float(self._session.current_pos[int(symbol_id)])

    def _account(self, name: str, value: float | bool):
        self._check()
        if name not in self._requirements.account:
            raise AttributeError(f"strategy did not declare account field {name!r}")
        return value

    @property
    def equity(self) -> float:
        return float(self._account("equity", self._session.equity))

    @property
    def initial_margin(self) -> float:
        return float(self._account("initial_margin", self._session.last_initial_margin))

    @property
    def maintenance_margin(self) -> float:
        return float(self._account("maintenance_margin", self._session.last_maintenance_margin))

    @property
    def available_equity(self) -> float:
        return float(self._account("available_equity", self._session.equity - self._session.last_initial_margin))

    @property
    def liquidated(self) -> bool:
        return bool(self._account("liquidated", self._session.liquidated))

    def iter_new_fills(self):
        self._check()
        if self._requirements.fills == "none":
            return iter(())
        return iter(self._session.fills_by_bar.get(self._bar, ()))

    def iter_new_events(self):
        self._check()
        if self._requirements.events == "none":
            return iter(())
        return iter(self._session.events_by_bar.get(self._bar, ()))

    def active_orders(self):
        self._check()
        if self._requirements.active_orders == "none":
            return ()
        return tuple(getattr(self._session, "_active_snapshot_cache", ()))

    def size_order(self, *, symbol_id: int, notional: float, price: float, side=1) -> float:
        self._check()
        from ..core.schema import OrderSide

        order_side = side if isinstance(side, OrderSide) else (OrderSide.BUY if int(side) > 0 else OrderSide.SELL)
        return float(
            self._session.size_helper(
                symbol=self._symbols[int(symbol_id)],
                notional=float(notional),
                price=float(price),
                side=order_side,
            )
        )


class MaterializedStrategyContext:
    """Compatibility adapter from a numeric view to the historical context."""

    @staticmethod
    def from_view(view: StrategyContextView) -> NativeStrategyContext:
        session = view._session
        bar = view.bar_index
        requirements = view._requirements
        initial_margin = session.last_initial_margin if "initial_margin" in requirements.account else 0.0
        maintenance_margin = session.last_maintenance_margin if "maintenance_margin" in requirements.account else 0.0
        return NativeStrategyContext(
            bar_index=bar,
            timestamp=pd.Timestamp(view.timestamp_ns, unit="ns", tz="UTC"),
            open=session.opens_arr[bar],
            high=session.market_arrays.highs[bar],
            low=session.market_arrays.lows[bar],
            close=session.market_arrays.closes[bar],
            volume=session.volumes_arr[bar],
            equity=float(session.equity),
            available_equity=float(session.equity - initial_margin),
            initial_margin=float(initial_margin),
            maintenance_margin=float(maintenance_margin),
            positions=(
                {symbol: float(session.current_pos[col]) for col, symbol in enumerate(session.symbols)}
                if requirements.positions else {}
            ),
            fills_this_bar=tuple(session.fills_by_bar.get(bar, ())) if requirements.fills != "none" else (),
            order_events_this_bar=tuple(session.events_by_bar.get(bar, ())) if requirements.events != "none" else (),
            active_orders=view.active_orders(),
            liquidated=bool(session.liquidated),
            symbols=tuple(session.symbols),
            size_order=session.size_helper,
        )


__all__ = ["MaterializedStrategyContext", "StaleStrategyContextError", "StrategyContextView"]

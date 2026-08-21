"""Bounded declarative strategy IR and its Python reference interpreter.

The native IR deliberately accepts a precomputed numeric signal tape instead of
an arbitrary Python callback.  It is therefore useful for the event-driven
strategies that can state their transition logic declaratively, while legacy,
numeric and sparse callback strategies keep their existing execution routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import struct
from typing import Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from ..core.orders import OrderAction, OrderActivationPolicy, OrderCommand
from ..core.schema import OrderSide, OrderType, TimeInForce


STRATEGY_IR_VERSION = 1
STRATEGY_IR_PARAMETER_NAMES = (
    "quantity",
    "threshold",
    "take_profit_pct",
    "stop_loss_pct",
)
_EPSILON = 1e-12
_MAX_INSTRUCTIONS_PER_BAR = 16
_MAX_COMMANDS_PER_BAR = 8


class NativeStrategyKind(str, Enum):
    """Bounded v1 templates supported by the Rust native strategy runtime."""

    SIGNAL_TARGET = "signal_target"
    GRID_LEVEL = "grid_level"
    DCA_PERIODIC = "dca_periodic"
    FIXED_BRACKET = "fixed_bracket"

    @property
    def code(self) -> int:
        return {
            NativeStrategyKind.SIGNAL_TARGET: 0,
            NativeStrategyKind.GRID_LEVEL: 1,
            NativeStrategyKind.DCA_PERIODIC: 2,
            NativeStrategyKind.FIXED_BRACKET: 3,
        }[self]


@dataclass(frozen=True, slots=True)
class NativeIRLimits:
    """Static resource bounds validated by both reference and Rust compilers."""

    max_instructions_per_bar: int = _MAX_INSTRUCTIONS_PER_BAR
    max_commands_per_bar: int = _MAX_COMMANDS_PER_BAR
    state_slots: int = 3

    def __post_init__(self) -> None:
        if not 0 < int(self.max_instructions_per_bar) <= _MAX_INSTRUCTIONS_PER_BAR:
            raise ValueError("max_instructions_per_bar must be in 1..16")
        if not 0 < int(self.max_commands_per_bar) <= _MAX_COMMANDS_PER_BAR:
            raise ValueError("max_commands_per_bar must be in 1..8")
        if not 0 <= int(self.state_slots) <= 8:
            raise ValueError("state_slots must be in 0..8")


@dataclass(frozen=True, slots=True)
class NativeStrategyParameters:
    """Default parameter row for a bounded native strategy program."""

    quantity: float
    threshold: float = 0.0
    take_profit_pct: float = 0.0
    stop_loss_pct: float = 0.0
    dca_period: int = 1
    max_levels: int = 1

    def __post_init__(self) -> None:
        values = (self.quantity, self.threshold, self.take_profit_pct, self.stop_loss_pct)
        if not all(np.isfinite(value) for value in values):
            raise ValueError("native IR parameters must be finite")
        if float(self.quantity) <= 0.0 or float(self.threshold) < 0.0:
            raise ValueError("quantity must be > 0 and threshold must be >= 0")
        if int(self.dca_period) <= 0 or int(self.max_levels) <= 0:
            raise ValueError("dca_period and max_levels must be > 0")

    def parameter_row(self) -> np.ndarray:
        """Return the stable Rust batch parameter-row layout."""

        return np.asarray(
            (self.quantity, self.threshold, self.take_profit_pct, self.stop_loss_pct),
            dtype=np.float64,
        )

    def with_row(self, row: Sequence[float]) -> "NativeStrategyParameters":
        """Overlay the four tunable values while retaining structural DCA fields."""

        array = np.asarray(row, dtype=np.float64)
        if array.shape != (len(STRATEGY_IR_PARAMETER_NAMES),) or not np.isfinite(array).all():
            raise ValueError("native IR parameter row must be finite with width 4")
        return NativeStrategyParameters(
            quantity=float(array[0]),
            threshold=float(array[1]),
            take_profit_pct=float(array[2]),
            stop_loss_pct=float(array[3]),
            dca_period=self.dca_period,
            max_levels=self.max_levels,
        )


@dataclass(frozen=True, slots=True)
class NativeIRReferenceTape:
    """Reference command tape and state target path for one program run."""

    commands: tuple[OrderCommand, ...]
    target_units: np.ndarray
    command_count_by_bar: np.ndarray
    fingerprint: str
    disassembly: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NativeStrategyIR:
    """Validated declarative strategy accepted by the Rust IR v1 runtime.

    Parameters are intentionally split into a structural program contract and
    a four-column numeric row.  The latter is the only matrix varied by a
    native batch run; it cannot add arbitrary operations or change resource
    bounds mid-run.
    """

    kind: NativeStrategyKind | str
    symbol: str
    symbol_id: int = 0
    parameters: NativeStrategyParameters | Mapping[str, object] = NativeStrategyParameters(1.0)
    limits: NativeIRLimits = NativeIRLimits()
    version: int = STRATEGY_IR_VERSION

    def __post_init__(self) -> None:
        kind = self.kind if isinstance(self.kind, NativeStrategyKind) else NativeStrategyKind(str(self.kind))
        params = self.parameters
        if isinstance(params, Mapping):
            params = NativeStrategyParameters(**params)
        if not isinstance(params, NativeStrategyParameters):
            raise TypeError("parameters must be NativeStrategyParameters or a mapping")
        if int(self.version) != STRATEGY_IR_VERSION:
            raise ValueError("unsupported native strategy IR version")
        if not self.symbol:
            raise ValueError("native IR requires a non-empty symbol")
        if int(self.symbol_id) < 0:
            raise ValueError("symbol_id must be >= 0")
        if kind is NativeStrategyKind.FIXED_BRACKET and (
            params.take_profit_pct <= 0.0 or params.stop_loss_pct <= 0.0
        ):
            raise ValueError("fixed_bracket requires positive take_profit_pct and stop_loss_pct")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "parameters", params)

    @property
    def parameter_names(self) -> tuple[str, ...]:
        """The fixed numeric batch row schema used by Rust and Python."""

        return STRATEGY_IR_PARAMETER_NAMES

    @property
    def default_parameter_row(self) -> np.ndarray:
        """Return a readonly contiguous default row for batch construction."""

        row = self.parameters.parameter_row()
        row.setflags(write=False)
        return row

    @property
    def requirements(self) -> Mapping[str, object]:
        """Return the bounded market/state projection consumed by the program."""

        return {
            "signal_columns": 1,
            "needs_close": self.kind is NativeStrategyKind.FIXED_BRACKET,
            "needs_position_state": True,
            "python_callback": False,
        }

    @property
    def fingerprint(self) -> str:
        """Stable, cross-language identifier for the immutable program contract."""

        return _fingerprint_program(self)

    def disassemble(self) -> tuple[str, ...]:
        """Return a short human-readable instruction view for audit metadata."""

        target = {
            NativeStrategyKind.SIGNAL_TARGET: "THRESHOLD_TARGET",
            NativeStrategyKind.GRID_LEVEL: "GRID_TARGET",
            NativeStrategyKind.DCA_PERIODIC: "DCA_STATE",
            NativeStrategyKind.FIXED_BRACKET: "THRESHOLD_TARGET",
        }[self.kind]
        lines = [
            "000 LOAD_SIGNAL dst=0 a=0 b=0 imm=0",
            f"001 {target} dst=1 a=0 b=0 imm=0",
            "002 EMIT_MARKET_DELTA dst=0 a=1 b=0 imm=0",
        ]
        if self.kind is NativeStrategyKind.FIXED_BRACKET:
            lines.append("003 EMIT_BRACKET dst=0 a=1 b=0 imm=0")
        return tuple(lines)

    def parameter_row(self, values: Mapping[str, float] | Sequence[float] | None = None) -> np.ndarray:
        """Normalize a parameter override to the fixed four-float native row."""

        if values is None:
            return self.default_parameter_row
        if isinstance(values, Mapping):
            merged = {
                "quantity": self.parameters.quantity,
                "threshold": self.parameters.threshold,
                "take_profit_pct": self.parameters.take_profit_pct,
                "stop_loss_pct": self.parameters.stop_loss_pct,
            }
            merged.update({str(key): float(value) for key, value in values.items()})
            unknown = set(merged) - set(self.parameter_names)
            if unknown:
                raise ValueError(f"unknown native IR parameter: {sorted(unknown)[0]}")
            values = tuple(merged[name] for name in self.parameter_names)
        row = np.ascontiguousarray(np.asarray(values, dtype=np.float64))
        if row.shape != (len(self.parameter_names),) or not np.isfinite(row).all():
            raise ValueError("native IR parameter row must be finite with width 4")
        self.parameters.with_row(row)
        row.setflags(write=False)
        return row

    def reference_tape(
        self,
        datetime_index: pd.DatetimeIndex | Iterable[object],
        signal: Sequence[float],
        close: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None = None,
    ) -> NativeIRReferenceTape:
        """Compile the canonical Python reference command tape.

        It is intentionally pure and side-effect-free: this function does not
        simulate fills.  The returned commands are fed to the existing native
        event Python oracle, while Rust compiles the same state transition
        directly into the ABI-0.5 tape for differential tests.
        """

        idx = pd.DatetimeIndex(datetime_index)
        signals = np.ascontiguousarray(np.asarray(signal, dtype=np.float64))
        closes = np.ascontiguousarray(np.asarray(close, dtype=np.float64))
        if len(idx) == 0 or signals.shape != (len(idx),) or closes.shape != (len(idx),):
            raise ValueError("datetime_index, signal, and close must share one non-empty one-dimensional shape")
        if not np.isfinite(signals).all():
            raise ValueError("native IR signal values must be finite")
        if self.kind is NativeStrategyKind.FIXED_BRACKET and (
            not np.isfinite(closes).all() or np.any(closes <= 0.0)
        ):
            raise ValueError("fixed_bracket requires finite positive closes")
        params = self.parameters.with_row(self.parameter_row(parameters))
        commands: list[OrderCommand] = []
        targets = np.zeros(len(idx), dtype=np.float64)
        count_by_bar = np.zeros(len(idx), dtype=np.int64)
        state_target = 0.0
        dca_level = 0
        dca_side = 0
        bracket: tuple[str, str] | None = None
        next_id = 0

        def order_id(value: int) -> str:
            return f"ir-{self.fingerprint[:16]}-{value}"

        for bar, raw_signal in enumerate(signals):
            if self.kind in {NativeStrategyKind.SIGNAL_TARGET, NativeStrategyKind.FIXED_BRACKET}:
                target = _threshold_target(float(raw_signal), params.quantity, params.threshold)
            elif self.kind is NativeStrategyKind.GRID_LEVEL:
                target = _grid_target(float(raw_signal), params.quantity)
            else:
                side = 1 if raw_signal > params.threshold else (-1 if raw_signal < -params.threshold else 0)
                if side == 0:
                    dca_level = 0
                    dca_side = 0
                    target = 0.0
                else:
                    if side != dca_side:
                        dca_side = side
                        dca_level = 1
                    elif bar % int(params.dca_period) == 0 and dca_level < int(params.max_levels):
                        dca_level += 1
                    target = float(dca_level * side) * params.quantity

            before = len(commands)
            if abs(target - state_target) > _EPSILON:
                if self.kind is NativeStrategyKind.FIXED_BRACKET and bracket is not None:
                    commands.append(OrderCommand(timestamp=idx[bar], action=OrderAction.CANCEL, target_order_id=bracket[0]))
                    commands.append(OrderCommand(timestamp=idx[bar], action=OrderAction.CANCEL, target_order_id=bracket[1]))
                    bracket = None
                delta = target - state_target
                if abs(delta) > _EPSILON:
                    parent = order_id(next_id)
                    next_id += 1
                    reduce_only = (
                        self.kind is NativeStrategyKind.FIXED_BRACKET
                        and np.sign(target) == np.sign(state_target)
                        and abs(target) < abs(state_target)
                    )
                    commands.append(
                        OrderCommand(
                            timestamp=idx[bar],
                            symbol=self.symbol,
                            side=OrderSide.BUY if delta > 0.0 else OrderSide.SELL,
                            order_type=OrderType.MARKET,
                            qty=abs(delta),
                            tif=TimeInForce.GTC,
                            reduce_only=bool(reduce_only),
                            order_id=parent,
                            metadata={"native_ir": self.fingerprint, "kind": self.kind.value, "bar": bar},
                        )
                    )
                    if self.kind is NativeStrategyKind.FIXED_BRACKET and abs(target) > _EPSILON:
                        take_profit_id = order_id(next_id)
                        next_id += 1
                        stop_loss_id = order_id(next_id)
                        next_id += 1
                        side = OrderSide.SELL if target > 0.0 else OrderSide.BUY
                        if target > 0.0:
                            take_profit = closes[bar] * (1.0 + params.take_profit_pct)
                            stop_loss = closes[bar] * (1.0 - params.stop_loss_pct)
                        else:
                            take_profit = closes[bar] * (1.0 - params.take_profit_pct)
                            stop_loss = closes[bar] * (1.0 + params.stop_loss_pct)
                        oco = parent
                        commands.append(
                            OrderCommand(
                                timestamp=idx[bar],
                                symbol=self.symbol,
                                side=side,
                                order_type=OrderType.LIMIT,
                                qty=abs(target),
                                price=float(take_profit),
                                tif=TimeInForce.GTC,
                                reduce_only=True,
                                order_id=take_profit_id,
                                parent_order_id=parent,
                                oco_group_id=oco,
                                activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
                                metadata={"native_ir": self.fingerprint, "child": "take_profit", "bar": bar},
                            )
                        )
                        commands.append(
                            OrderCommand(
                                timestamp=idx[bar],
                                symbol=self.symbol,
                                side=side,
                                order_type=OrderType.STOP_MARKET,
                                qty=abs(target),
                                trigger_price=float(stop_loss),
                                tif=TimeInForce.GTC,
                                reduce_only=True,
                                order_id=stop_loss_id,
                                parent_order_id=parent,
                                oco_group_id=oco,
                                activation_policy=OrderActivationPolicy.ON_PARENT_FIRST_FILL,
                                metadata={"native_ir": self.fingerprint, "child": "stop_loss", "bar": bar},
                            )
                        )
                        bracket = (take_profit_id, stop_loss_id)
                state_target = target
            count_by_bar[bar] = len(commands) - before
            if count_by_bar[bar] > self.limits.max_commands_per_bar:
                raise RuntimeError("native IR command bound was exceeded")
            targets[bar] = target

        targets.setflags(write=False)
        count_by_bar.setflags(write=False)
        return NativeIRReferenceTape(
            commands=tuple(commands),
            target_units=targets,
            command_count_by_bar=count_by_bar,
            fingerprint=self.fingerprint,
            disassembly=self.disassemble(),
        )


def _threshold_target(signal: float, quantity: float, threshold: float) -> float:
    if signal > threshold:
        return float(quantity)
    if signal < -threshold:
        return -float(quantity)
    return 0.0


def _grid_target(signal: float, quantity: float) -> float:
    level = float(np.rint(signal))
    if abs(signal - level) > _EPSILON:
        raise ValueError("grid_level signal values must be structural integers")
    return level * float(quantity)


def _fingerprint_program(program: NativeStrategyIR) -> str:
    instructions = _instruction_rows(program.kind)
    payload = bytearray(b"quantbt-strategy-ir-v1")
    payload.extend(struct.pack("<H", int(program.version)))
    payload.extend(struct.pack("<B", program.kind.code))
    payload.extend(struct.pack("<I", int(program.symbol_id)))
    params = program.parameters
    for value in (params.quantity, params.threshold, params.take_profit_pct, params.stop_loss_pct):
        payload.extend(struct.pack("<d", float(value)))
    payload.extend(struct.pack("<I", int(params.dca_period)))
    payload.extend(struct.pack("<I", int(params.max_levels)))
    payload.extend(struct.pack("<H", int(program.limits.max_instructions_per_bar)))
    payload.extend(struct.pack("<H", int(program.limits.max_commands_per_bar)))
    payload.extend(struct.pack("<H", int(program.limits.state_slots)))
    for opcode, dst, a, b, imm in instructions:
        payload.extend(struct.pack("<BHHHI", opcode, dst, a, b, imm))
    seeds = (
        0xCBF29CE484222325,
        0x84222325CBF29CE4,
        0x9E3779B97F4A7C15,
        0x517CC1B727220A95,
    )
    lanes: list[int] = []
    for lane_index, seed in enumerate(seeds):
        value = seed
        for byte in payload:
            value ^= int(byte) + (lane_index << 1)
            value = (value * 0x00000100000001B3) & ((1 << 64) - 1)
        lanes.append(value)
    return b"".join(struct.pack("<Q", lane) for lane in lanes).hex()


def _instruction_rows(kind: NativeStrategyKind) -> tuple[tuple[int, int, int, int, int], ...]:
    target_opcode = {
        NativeStrategyKind.SIGNAL_TARGET: 1,
        NativeStrategyKind.GRID_LEVEL: 2,
        NativeStrategyKind.DCA_PERIODIC: 3,
        NativeStrategyKind.FIXED_BRACKET: 1,
    }[kind]
    rows: list[tuple[int, int, int, int, int]] = [(0, 0, 0, 0, 0), (target_opcode, 1, 0, 0, 0), (4, 0, 1, 0, 0)]
    if kind is NativeStrategyKind.FIXED_BRACKET:
        rows.append((5, 0, 1, 0, 0))
    return tuple(rows)


__all__ = [
    "NativeIRLimits",
    "NativeIRReferenceTape",
    "NativeStrategyIR",
    "NativeStrategyKind",
    "NativeStrategyParameters",
    "STRATEGY_IR_PARAMETER_NAMES",
    "STRATEGY_IR_VERSION",
]

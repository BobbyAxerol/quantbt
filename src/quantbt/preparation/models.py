"""Pandas-free immutable prepared inputs consumed by engine SPI sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from ..core.instrument_contracts import PreparedInstrumentTable
from ..planning import ExecutionPlan


def _readonly(array, dtype=None) -> np.ndarray:
    value = np.ascontiguousarray(array, dtype=dtype)
    value.setflags(write=False)
    return value


@dataclass(frozen=True, slots=True)
class PreparedMarket:
    timestamps_ns: np.ndarray
    symbols: tuple[str, ...]
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray
    funding_rates: np.ndarray
    funding_event_mask: np.ndarray
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamps_ns", _readonly(self.timestamps_ns, np.int64))
        for name in ("opens", "highs", "lows", "closes", "volumes", "funding_rates"):
            object.__setattr__(self, name, _readonly(getattr(self, name), np.float64))
        object.__setattr__(self, "funding_event_mask", _readonly(self.funding_event_mask, np.bool_))
        shape = (len(self.timestamps_ns), len(self.symbols))
        for name in ("opens", "highs", "lows", "closes", "volumes", "funding_rates"):
            if getattr(self, name).shape != shape:
                raise ValueError(f"prepared market {name} shape must be {shape}")
        if self.funding_event_mask.shape != (shape[0],):
            raise ValueError("funding_event_mask must have one value per bar")

    @property
    def n_bars(self) -> int:
        return len(self.timestamps_ns)

    @property
    def n_symbols(self) -> int:
        return len(self.symbols)


@dataclass(frozen=True, slots=True)
class PreparedInstruments:
    table: PreparedInstrumentTable
    leverages: np.ndarray
    fee_rates: np.ndarray
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "leverages", _readonly(self.leverages, np.float64))
        object.__setattr__(self, "fee_rates", _readonly(self.fee_rates, np.float64))
        expected = (self.table.n_symbols,)
        if self.leverages.shape != expected or self.fee_rates.shape != expected:
            raise ValueError("prepared leverage/fee arrays must match instrument count")


@dataclass(frozen=True, slots=True)
class PreparedAccount:
    initial_capital: float
    maintenance_ratio: float
    slippage_rate: float
    use_funding: bool
    fingerprint: str

    def __post_init__(self) -> None:
        if self.initial_capital <= 0.0:
            raise ValueError("initial_capital must be > 0")
        if self.maintenance_ratio < 0.0 or self.slippage_rate < 0.0:
            raise ValueError("maintenance_ratio and slippage_rate must be >= 0")


@dataclass(frozen=True, slots=True)
class PreparedCommandTape:
    symbols: tuple[str, ...]
    id_values: tuple[str, ...]
    command_ptr: np.ndarray
    command_bar: np.ndarray
    command_action: np.ndarray
    command_symbol: np.ndarray
    command_side: np.ndarray
    command_type: np.ndarray
    command_qty: np.ndarray
    command_price: np.ndarray
    command_trigger_price: np.ndarray
    command_tif: np.ndarray
    command_reduce_only: np.ndarray
    command_order_id: np.ndarray
    command_target_order_id: np.ndarray
    command_parent_order_id: np.ndarray
    command_group_id: np.ndarray
    command_oco_group_id: np.ndarray
    command_activation: np.ndarray
    command_expires_bar: np.ndarray
    original_index: np.ndarray
    fingerprint: str

    def __post_init__(self) -> None:
        int_arrays = (
            "command_ptr", "command_bar", "command_action", "command_symbol",
            "command_side", "command_type", "command_tif", "command_reduce_only",
            "command_order_id", "command_target_order_id", "command_parent_order_id",
            "command_group_id", "command_oco_group_id", "command_activation",
            "command_expires_bar", "original_index",
        )
        float_arrays = ("command_qty", "command_price", "command_trigger_price")
        for name in int_arrays:
            object.__setattr__(self, name, _readonly(getattr(self, name), np.int64))
        for name in float_arrays:
            object.__setattr__(self, name, _readonly(getattr(self, name), np.float64))
        n_commands = len(self.original_index)
        if self.command_ptr.ndim != 1:
            raise ValueError("command_ptr must be one-dimensional")
        for name in (*int_arrays[1:], *float_arrays):
            if len(getattr(self, name)) != n_commands:
                raise ValueError(f"{name} must contain one value per command")

    @property
    def n_commands(self) -> int:
        return len(self.original_index)

    @property
    def tape_fingerprint(self) -> str:
        return self.fingerprint

    def arrays(self) -> Iterable[np.ndarray]:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, np.ndarray):
                yield value


@dataclass(frozen=True, slots=True)
class PreparationKeys:
    plan: str
    market: str
    instruments: str
    commands: str
    account: str
    combined: str


@dataclass(frozen=True, slots=True)
class PreparationDiagnostics:
    market_normalizations: int = 1
    instrument_normalizations: int = 1
    command_compilations: int = 1
    output_projections: int = 1
    backend_resolutions: int = 1
    market_bytes: int = 0
    instrument_bytes: int = 0
    command_bytes: int = 0


@dataclass(frozen=True, slots=True)
class PreparedRun:
    plan: ExecutionPlan
    market: PreparedMarket
    instruments: PreparedInstruments
    account: PreparedAccount
    command_tape: PreparedCommandTape
    keys: PreparationKeys
    diagnostics: PreparationDiagnostics

    def __post_init__(self) -> None:
        if self.plan.plan_fingerprint != self.keys.plan:
            raise ValueError("prepared run plan fingerprint mismatch")
        if self.market.symbols != self.command_tape.symbols:
            raise ValueError("prepared market and command symbols differ")
        if self.market.symbols != self.instruments.table.symbols:
            raise ValueError("prepared market and instrument symbols differ")


__all__ = [
    "PreparationDiagnostics",
    "PreparationKeys",
    "PreparedAccount",
    "PreparedCommandTape",
    "PreparedInstruments",
    "PreparedMarket",
    "PreparedRun",
]

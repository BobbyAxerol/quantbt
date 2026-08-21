"""Pandas-free struct-of-arrays result contract for engine backends."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _readonly(array, dtype=None) -> np.ndarray:
    value = np.ascontiguousarray(array, dtype=dtype)
    value.setflags(write=False)
    return value


@dataclass(frozen=True, slots=True)
class RawEngineSummary:
    final_equity: float
    final_positions: np.ndarray
    total_fee: float
    total_funding: float
    total_turnover: float
    fill_count: int
    event_count: int
    rejected_count: int
    canceled_count: int
    max_initial_margin: float
    max_maintenance_margin: float
    liquidated: bool
    liquidation_bar: int
    liquidation_reason: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "final_positions", _readonly(self.final_positions, np.float64))


@dataclass(frozen=True, slots=True)
class RawEnginePaths:
    equity: np.ndarray
    positions: np.ndarray
    fees: np.ndarray
    turnover: np.ndarray
    funding: np.ndarray
    initial_margin: np.ndarray
    maintenance_margin: np.ndarray
    rejected_orders: np.ndarray
    canceled_orders: np.ndarray

    def __post_init__(self) -> None:
        for name in (
            "equity", "positions", "fees", "turnover", "funding",
            "initial_margin", "maintenance_margin", "rejected_orders", "canceled_orders",
        ):
            dtype = np.float64 if name not in {"rejected_orders", "canceled_orders"} else np.int64
            object.__setattr__(self, name, _readonly(getattr(self, name), dtype))


@dataclass(frozen=True, slots=True)
class RawFillBuffer:
    bar: np.ndarray
    command_index: np.ndarray
    order_id_code: np.ndarray
    symbol_code: np.ndarray
    side: np.ndarray
    qty: np.ndarray
    price: np.ndarray
    fee: np.ndarray
    reason: np.ndarray
    ambiguity: np.ndarray

    def __post_init__(self) -> None:
        for name in ("bar", "command_index", "order_id_code", "symbol_code", "side", "reason", "ambiguity"):
            object.__setattr__(self, name, _readonly(getattr(self, name), np.int64))
        for name in ("qty", "price", "fee"):
            object.__setattr__(self, name, _readonly(getattr(self, name), np.float64))


@dataclass(frozen=True, slots=True)
class RawEventBuffer:
    bar: np.ndarray
    kind: np.ndarray
    status: np.ndarray
    command_index: np.ndarray
    order_id_code: np.ndarray
    target_id_code: np.ndarray
    symbol_code: np.ndarray
    reject_code: np.ndarray

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _readonly(getattr(self, name), np.int64))


@dataclass(frozen=True, slots=True)
class RawCommandStateBuffer:
    status: np.ndarray
    reject_code: np.ndarray
    fill_bar: np.ndarray
    fill_qty: np.ndarray
    fill_price: np.ndarray
    fill_fee: np.ndarray
    active: np.ndarray
    waiting_parent: np.ndarray
    working_qty: np.ndarray
    working_price: np.ndarray
    working_trigger: np.ndarray
    trigger_armed: np.ndarray
    fill_reason: np.ndarray
    fill_ambiguity: np.ndarray

    def __post_init__(self) -> None:
        int_names = (
            "status", "reject_code", "fill_bar", "active", "waiting_parent",
            "trigger_armed", "fill_reason", "fill_ambiguity",
        )
        for name in int_names:
            object.__setattr__(self, name, _readonly(getattr(self, name), np.int64))
        for name in ("fill_qty", "fill_price", "fill_fee", "working_qty", "working_price", "working_trigger"):
            object.__setattr__(self, name, _readonly(getattr(self, name), np.float64))


@dataclass(frozen=True, slots=True)
class RawEngineDiagnostics:
    backend: str
    protocol_version: int
    run_calls: int
    prepare_calls: int
    output_projection_fingerprint: str
    expiry_scan_count: int = 0
    matching_scan_count: int = 0
    relationship_scan_count: int = 0
    retained_path_bytes: int = 0
    retained_fill_bytes: int = 0
    retained_event_bytes: int = 0


@dataclass(frozen=True, slots=True)
class RawEngineResult:
    summary: RawEngineSummary
    paths: RawEnginePaths | None
    fills: RawFillBuffer | None
    events: RawEventBuffer | None
    command_states: RawCommandStateBuffer | None
    diagnostics: RawEngineDiagnostics
    plan_fingerprint: str
    prepared_fingerprint: str
    backend_metadata: tuple[tuple[str, str], ...] = ()


__all__ = [
    "RawCommandStateBuffer",
    "RawEngineDiagnostics",
    "RawEnginePaths",
    "RawEngineResult",
    "RawEngineSummary",
    "RawEventBuffer",
    "RawFillBuffer",
]

"""Equal Python/Rust engine SPI with pandas-free requests and results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..planning import BackendKind, ExecutionPlan, OutputRequirements, TraceRequirements
from ..preparation import PreparedRun
from ..results import RawEngineResult


@dataclass(frozen=True, slots=True)
class BackendDescriptor:
    name: BackendKind
    implementation_version: str
    protocol_version: int
    command_abi_version: str
    result_abi_version: str
    contracts: tuple[str, ...]
    workloads: tuple[str, ...]
    build: str


@dataclass(frozen=True, slots=True)
class EngineRunRequest:
    run_id: int
    output: OutputRequirements
    trace: TraceRequirements
    seed: int | None = None
    parameters: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if self.run_id < 0:
            raise ValueError("run_id must be >= 0")


@dataclass(frozen=True, slots=True)
class ResetRequest:
    reset_account: bool = True
    reset_orders: bool = True
    reset_strategy: bool = True


@runtime_checkable
class PreparedEngineSession(Protocol):
    @property
    def descriptor(self) -> BackendDescriptor: ...

    def run(self, request: EngineRunRequest) -> RawEngineResult: ...

    def reset(self, reset: ResetRequest = ResetRequest()) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class EngineBackend(Protocol):
    @property
    def descriptor(self) -> BackendDescriptor: ...

    def prepare(self, plan: ExecutionPlan, prepared: PreparedRun) -> PreparedEngineSession: ...


__all__ = [
    "BackendDescriptor",
    "EngineBackend",
    "EngineRunRequest",
    "PreparedEngineSession",
    "ResetRequest",
]

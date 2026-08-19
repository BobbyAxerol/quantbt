"""Explicit Python facade for the bounded Rust native strategy IR.

The facade intentionally sits below :class:`QuantBTEndpoint`: it is a prepared
research/runtime primitive for declarative signal, grid, DCA, and fixed-bracket
templates. Existing callback and endpoint routes retain their behaviour until
their complete parity/promotion gates are separately satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
from typing import Mapping, Sequence

import numpy as np

from ..strategies.native_ir import NativeStrategyIR
from ._native_event_rust import (
    NativeEventRustBackendError,
    RustFullRunner,
    probe_native_event_rust_extension,
)


_REQUIRED_CAPABILITIES = frozenset(
    {
        "native_strategy_ir_v1",
        "native_strategy_ir_batch_v1",
    }
)


@dataclass(frozen=True, slots=True)
class NativeIRRunResult:
    """One explicit Rust native-IR result without forced pandas adaptation."""

    profile: str
    payload: Mapping[str, object]

    @property
    def final_equity(self) -> float:
        """Return the canonical final account equity."""

        return float(self.payload["final_equity"])

    @property
    def command_count(self) -> int:
        """Return typed commands compiled inside the Rust-only run."""

        return int(self.payload["strategy_ir_command_count"])


@dataclass(frozen=True, slots=True)
class NativeIRBatchResult:
    """Scalar scenario table emitted by one Rust batch boundary call."""

    scenario_id: np.ndarray
    status: np.ndarray
    final_equity: np.ndarray
    total_fee: np.ndarray
    total_funding: np.ndarray
    turnover: np.ndarray
    fill_count: np.ndarray
    rejected_count: np.ndarray
    liquidated: np.ndarray
    errors: tuple[str | None, ...]
    metadata: Mapping[str, object]

    def top_ids(self, k: int) -> np.ndarray:
        """Return stable top-K completed IDs, equity descending then ID."""

        if k < 0:
            raise ValueError("k must be >= 0")
        completed = self.status == 0
        ids = self.scenario_id[completed]
        equity = self.final_equity[completed]
        order = np.lexsort((ids, -equity))
        return np.ascontiguousarray(ids[order][:k], dtype=np.uint32)


@dataclass(frozen=True, slots=True)
class NativeIRFold:
    """Causal OOS execution window for :meth:`run_fold_batch_score`.

    The caller owns strategy generation and parameter selection.  This object
    only records the complete parent-tape boundaries and lets the Rust batch
    runner execute ``test_start:test_end`` on a fresh account for every
    scenario.  It cannot make OOS observations available to selection code.
    """

    fold_id: int
    warmup_start: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int

    def __post_init__(self) -> None:
        values = (
            self.fold_id,
            self.warmup_start,
            self.train_start,
            self.train_end,
            self.test_start,
            self.test_end,
        )
        if any(not isinstance(value, Integral) or isinstance(value, bool) for value in values):
            raise TypeError("native IR fold boundaries must be integer bar offsets")
        if any(int(value) < 0 or int(value) > np.iinfo(np.uint32).max for value in values):
            raise ValueError("native IR fold boundaries must fit a non-negative u32 offset")
        if not (
            self.warmup_start <= self.train_start < self.train_end <= self.test_start < self.test_end
        ):
            raise ValueError("native IR fold must be causal: warmup <= train < test")

    def validate_for_bars(self, n_bars: int) -> None:
        """Validate that this declared causal window fits a prepared tape."""

        if self.test_end > int(n_bars):
            raise ValueError("native IR fold exceeds prepared-market bars")


class RustNativeIRRunner:
    """Run one validated :class:`NativeStrategyIR` on a prepared Rust market.

    Parameters
    ----------
    full_runner:
        A configured :class:`RustFullRunner`; it owns the prepared market and
        account/execution contract.
    program:
        Declarative strategy template. Python may compute signal columns, but
        Rust compiles and executes the command tape with no Python callbacks.

    Notes
    -----
    This is an opt-in low-level path. It does not silently replace legacy
    endpoint execution, and score/compact/audit preserve the same execution
    contract with different retained output levels.
    """

    def __init__(self, full_runner: RustFullRunner, program: NativeStrategyIR) -> None:
        self.full_runner = full_runner
        self.program = program
        module = full_runner._module
        status = probe_native_event_rust_extension(module=module)
        missing = sorted(
            capability
            for capability in _REQUIRED_CAPABILITIES
            if not status.capabilities.get(capability, False)
        )
        if missing:
            raise NativeEventRustBackendError(
                "installed _quantbt_native wheel lacks native strategy IR capabilities: "
                + ", ".join(missing)
            )
        if int(program.symbol_id) >= len(full_runner.symbols):
            raise ValueError("NativeStrategyIR.symbol_id is outside RustFullRunner symbols")
        limits = program.limits
        parameters = program.parameters
        self._core = module.NativeStrategyProgramCore(
            program.kind.code,
            symbol_id=int(program.symbol_id),
            quantity=float(parameters.quantity),
            threshold=float(parameters.threshold),
            take_profit_pct=float(parameters.take_profit_pct),
            stop_loss_pct=float(parameters.stop_loss_pct),
            dca_period=int(parameters.dca_period),
            max_levels=int(parameters.max_levels),
            max_instructions_per_bar=int(limits.max_instructions_per_bar),
            max_commands_per_bar=int(limits.max_commands_per_bar),
            state_slots=int(limits.state_slots),
        )
        if str(self._core.fingerprint) != program.fingerprint:
            raise NativeEventRustBackendError(
                "native strategy IR fingerprint differs from the Python reference compiler"
            )

    @property
    def fingerprint(self) -> str:
        """Return the shared Python/Rust program fingerprint."""

        return str(self._core.fingerprint)

    def disassemble(self) -> tuple[str, ...]:
        """Return the native instruction listing retained in run metadata."""

        return tuple(self._core.disassemble())

    def run_score(
        self,
        signal: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None = None,
    ) -> NativeIRRunResult:
        """Run a scalar-only native simulation with O(1) PyO3 calls."""

        payload = self._new_session().run_ir_score(
            self._core,
            self._signal(signal),
            self._parameter_row(parameters),
        )
        return NativeIRRunResult("score", dict(payload))

    def run_compact(
        self,
        signal: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None = None,
    ) -> NativeIRRunResult:
        """Run with dense equity/position paths but no fill/event rows."""

        payload = dict(
            self._new_session().run_ir_compact(
                self._core,
                self._signal(signal),
                self._parameter_row(parameters),
            )
        )
        self._normalize_compact_payload(payload)
        return NativeIRRunResult("compact", payload)

    def run_audit(
        self,
        signal: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None = None,
    ) -> NativeIRRunResult:
        """Run with typed fill/event ledgers for selected-candidate parity."""

        payload = dict(
            self._new_session().run_ir_audit(
                self._core,
                self._signal(signal),
                self._parameter_row(parameters),
            )
        )
        self._normalize_compact_payload(payload)
        for key in (
            "fill_bar",
            "fill_order_id",
            "fill_symbol",
            "fill_side",
            "fill_reason",
            "fill_ambiguity",
            "event_bar",
            "event_kind",
            "event_status",
            "event_order_id",
            "event_target_id",
            "event_symbol",
            "event_reject_code",
        ):
            payload[key] = np.ascontiguousarray(np.asarray(payload[key]), dtype=np.int64)
        for key in ("fill_qty", "fill_price", "fill_fee"):
            payload[key] = np.ascontiguousarray(np.asarray(payload[key]), dtype=np.float64)
        return NativeIRRunResult("audit", payload)

    def run_batch_score(
        self,
        signals: np.ndarray | Sequence[Sequence[float]],
        *,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None = None,
        workers: int = 1,
        chunk_size: int = 256,
        fail_fast: bool = False,
    ) -> NativeIRBatchResult:
        """Score independent signal/parameter rows over one prepared market.

        No fill/event audit rows are built for the batch. Use :meth:`run_audit`
        for IDs selected by :meth:`NativeIRBatchResult.top_ids`.
        """

        signal_matrix, parameters = self._batch_inputs(signals, parameter_matrix)
        payload = dict(
            self._new_session().run_ir_batch_score(
                self._core,
                signal_matrix,
                parameters,
                workers=int(workers),
                chunk_size=int(chunk_size),
                fail_fast=bool(fail_fast),
            )
        )
        return self._batch_result(payload)

    def run_fold_batch_score(
        self,
        signals: np.ndarray | Sequence[Sequence[float]],
        fold: NativeIRFold,
        *,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None = None,
        workers: int = 1,
        chunk_size: int = 256,
        fail_fast: bool = False,
    ) -> NativeIRBatchResult:
        """Score scenarios on one causal OOS fold with fresh account state.

        ``signals`` is aligned to the full prepared tape so indicators may use
        prior history in the strategy layer. Rust creates one immutable OOS
        market window, slices only the declared test range, and never carries
        positions, cash, or orders from a preceding fold.
        """

        if not isinstance(fold, NativeIRFold):
            raise TypeError("fold must be NativeIRFold")
        signal_matrix, parameters = self._batch_inputs(signals, parameter_matrix)
        fold.validate_for_bars(signal_matrix.shape[1])
        payload = dict(
            self._new_session().run_ir_fold_batch_score(
                self._core,
                signal_matrix,
                int(fold.fold_id),
                int(fold.warmup_start),
                int(fold.train_start),
                int(fold.train_end),
                int(fold.test_start),
                int(fold.test_end),
                parameters,
                workers=int(workers),
                chunk_size=int(chunk_size),
                fail_fast=bool(fail_fast),
            )
        )
        return self._batch_result(payload)

    def _batch_inputs(
        self,
        signals: np.ndarray | Sequence[Sequence[float]],
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Normalize contiguous batch input once at the Python boundary."""

        signal_matrix = np.ascontiguousarray(np.asarray(signals, dtype=np.float64))
        if signal_matrix.ndim != 2 or signal_matrix.shape[1] != len(self.full_runner.idx):
            raise ValueError("signals must have shape (scenarios, prepared_market_bars)")
        if not np.isfinite(signal_matrix).all():
            raise ValueError("native IR signals must be finite")
        if parameter_matrix is None:
            parameters = np.broadcast_to(
                self.program.default_parameter_row,
                (signal_matrix.shape[0], len(self.program.parameter_names)),
            ).copy()
        else:
            parameters = np.ascontiguousarray(np.asarray(parameter_matrix, dtype=np.float64))
        if parameters.shape != (signal_matrix.shape[0], len(self.program.parameter_names)):
            raise ValueError("parameter_matrix must have shape (scenarios, 4)")
        if not np.isfinite(parameters).all():
            raise ValueError("native IR parameters must be finite")
        return signal_matrix, parameters

    @staticmethod
    def _batch_result(payload: Mapping[str, object]) -> NativeIRBatchResult:
        """Convert stable Rust scalar columns without constructing pandas rows."""

        return NativeIRBatchResult(
            scenario_id=np.ascontiguousarray(np.asarray(payload["scenario_id"]), dtype=np.uint32),
            status=np.ascontiguousarray(np.asarray(payload["status"]), dtype=np.uint16),
            final_equity=np.ascontiguousarray(np.asarray(payload["final_equity"]), dtype=np.float64),
            total_fee=np.ascontiguousarray(np.asarray(payload["total_fee"]), dtype=np.float64),
            total_funding=np.ascontiguousarray(np.asarray(payload["total_funding"]), dtype=np.float64),
            turnover=np.ascontiguousarray(np.asarray(payload["turnover"]), dtype=np.float64),
            fill_count=np.ascontiguousarray(np.asarray(payload["fill_count"]), dtype=np.uint64),
            rejected_count=np.ascontiguousarray(np.asarray(payload["rejected_count"]), dtype=np.uint64),
            liquidated=np.ascontiguousarray(np.asarray(payload["liquidated"]), dtype=bool),
            errors=tuple(payload["error"]),
            metadata={
                key: value
                for key, value in payload.items()
                if key
                not in {
                    "scenario_id", "status", "final_equity", "total_fee", "total_funding",
                    "turnover", "fill_count", "rejected_count", "liquidated", "error",
                }
            },
        )

    def _new_session(self):
        return self.full_runner._new_session()

    def _signal(self, signal: Sequence[float]) -> np.ndarray:
        values = np.ascontiguousarray(np.asarray(signal, dtype=np.float64))
        if values.shape != (len(self.full_runner.idx),) or not np.isfinite(values).all():
            raise ValueError("signal must be a finite one-dimensional prepared-market-length array")
        return values

    def _parameter_row(
        self,
        parameters: Mapping[str, float] | Sequence[float] | None,
    ) -> np.ndarray:
        return np.ascontiguousarray(self.program.parameter_row(parameters), dtype=np.float64)

    def _normalize_compact_payload(self, payload: dict[str, object]) -> None:
        for key in (
            "equity", "positions", "fees", "turnover", "funding", "initial_margin", "maintenance_margin",
        ):
            payload[key] = np.ascontiguousarray(np.asarray(payload[key]), dtype=np.float64)
        payload["positions"] = np.asarray(payload["positions"], dtype=np.float64).reshape(
            len(self.full_runner.idx), len(self.full_runner.symbols)
        )


__all__ = ["NativeIRBatchResult", "NativeIRFold", "NativeIRRunResult", "RustNativeIRRunner"]

"""Explicit Python facade for the bounded Rust native strategy IR.

The facade intentionally sits below :class:`QuantBTEndpoint`: it is a prepared
research/runtime primitive for declarative signal, grid, DCA, and fixed-bracket
templates. Existing callback and endpoint routes retain their behaviour until
their complete parity/promotion gates are separately satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from numbers import Integral
from typing import TYPE_CHECKING, Mapping, Sequence

import numpy as np
import pandas as pd

from ..core.event_contracts import EventClockContract, get_event_clock_contract
from ..core.order_compiler import compile_order_commands
from ..planning import (
    BacktestRequest,
    RunProfile,
    StrategyMode,
    WorkloadClass,
    resolve_execution_plan,
)
from ..planning.capabilities import CapabilitySnapshot, load_rust_capability_snapshot
from ..strategies.native_ir import NativeStrategyIR
from ._native_event_rust import (
    NativeEventRustBackendError,
    RustFullAuditResult,
    RustFullRunner,
    probe_native_event_rust_extension,
)

if TYPE_CHECKING:
    from .native_event import NativeEventBackend


_REQUIRED_CAPABILITIES = frozenset(
    {
        "native_strategy_ir_v1",
        "native_strategy_ir_batch_v1",
    }
)

_PROMOTED_IR_CAPABILITIES = frozenset(
    {
        "native_event_v2_full_contract",
        "native_strategy_ir_v1",
        "native_strategy_ir_signal_target",
        "native_strategy_ir_grid_level",
        "native_strategy_ir_dca_periodic",
        "native_strategy_ir_fixed_bracket",
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

    def to_backtest_result(
        self,
        run: NativeIRRunResult,
        signal: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None = None,
        metadata: Mapping[str, object] | None = None,
    ):
        """Adapt one compact/audit IR output to ``BacktestResultV2``.

        Rust remains the only execution owner.  Python may rebuild the pure
        command *identity* table on this cold reporting path so fill and event
        IDs remain readable, but it never runs matching, accounting, or a
        second simulation.
        """

        if run.profile not in {"compact", "audit"}:
            raise ValueError("score output has no dense paths; use run_compact or run_audit for BacktestResultV2")
        signal_values = self._signal(signal)
        parameter_row = self._parameter_row(parameters)
        close = self.full_runner.market_arrays.closes[:, int(self.program.symbol_id)]
        reference = self.program.reference_tape(
            self.full_runner.idx,
            signal_values,
            close,
            parameters=parameter_row,
        )
        compiled = compile_order_commands(
            idx=self.full_runner.idx,
            commands=reference.commands,
            symbol_to_col={symbol: col for col, symbol in enumerate(self.full_runner.symbols)},
        )
        command_report = pd.DataFrame(
            [
                {
                    "timestamp": command.timestamp,
                    "action": command.action.value,
                    "symbol": command.symbol,
                    "side": None if command.side is None else command.side.value,
                    "order_type": None if command.order_type is None else command.order_type.value,
                    "order_id": command.order_id,
                    "target_order_id": command.target_order_id,
                    "parent_order_id": command.parent_order_id,
                    "oco_group_id": command.oco_group_id,
                    "qty": command.qty,
                    "price": command.price,
                    "trigger_price": command.trigger_price,
                    "tif": command.tif.value,
                    "reduce_only": bool(command.reduce_only),
                    "report_kind": "command_intent",
                }
                for _, command in compiled.sorted_commands
            ]
        )
        command_metadata = {
            command.order_id: dict(command.metadata)
            for _, command in compiled.sorted_commands
            if command.order_id
        }
        if run.profile == "audit":
            audit = RustFullAuditResult.from_audit_payload(
                run.payload,
                n_bars=len(self.full_runner.idx),
                n_symbols=len(self.full_runner.symbols),
                id_values=tuple(compiled.id_values),
                command_report=command_report,
                command_metadata=command_metadata,
            )
        else:
            audit = RustFullAuditResult.from_compact_payload(
                run.payload,
                n_bars=len(self.full_runner.idx),
                n_symbols=len(self.full_runner.symbols),
                id_values=tuple(compiled.id_values),
                command_report=pd.DataFrame(),
                command_metadata=command_metadata,
            )
        result_metadata = {
            "backend": "native_event",
            "engine": "event_rust_native_ir_v1",
            "report_level": run.profile,
            "strategy_ir_version": 1,
            "strategy_ir_kind": self.program.kind.value,
            "strategy_ir_fingerprint": self.fingerprint,
            "strategy_ir_command_count": int(run.payload["strategy_ir_command_count"]),
            "strategy_ir_disassembly": self.disassemble(),
            "python_callbacks": 0,
            "boundary_calls": 1,
            "audit_materialized": run.profile == "audit",
            "cold_path_command_identity_compilation": True,
            "rust_audit_replay": False,
        }
        if metadata:
            result_metadata.update(dict(metadata))
        closes = pd.DataFrame(
            {
                symbol: self.full_runner.market_arrays.closes[:, col]
                for col, symbol in enumerate(self.full_runner.symbols)
            },
            index=self.full_runner.idx,
        )
        result = audit.to_backtest_result(
            datetime_index=self.full_runner.idx,
            closes=closes,
            symbols=self.full_runner.symbols,
            initial_capital=self.full_runner.initial_capital,
            leverage=float(np.mean(self.full_runner.leverages)),
            metadata=result_metadata,
        )
        if run.profile == "audit":
            # This uses Rust-owned typed ledgers plus the immutable command
            # identity table built above. It never replays matching/accounting.
            from ..core.accounting_contracts import attach_native_accounting_audit
            from ..core.execution_trace import attach_canonical_execution_trace
            from .native_event import NativeEventBackend

            NativeEventBackend._project_rust_lifecycle_audit(
                result=result,
                compiled_commands=compiled,
                n_bars=len(self.full_runner.idx),
            )
            result.metadata["event_phase_trace_v1"] = NativeEventBackend._build_event_phase_trace(
                self.full_runner.idx,
                self.full_runner.event_contract,
                int(audit.liquidation_bar),
                int(audit.liquidation_reason),
            )
            attach_native_accounting_audit(
                result,
                contract_sizes=np.asarray(self.full_runner.contract_sizes, dtype=np.float64),
            )
            attach_canonical_execution_trace(result)
        else:
            result.metadata["command_outcome_report_v1"] = pd.DataFrame()
            result.metadata["lifecycle_event_report_v1"] = pd.DataFrame()
        return result

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


class NativeIRExecutionRunner:
    """Stable auto-routing facade for bounded Native Strategy IR v1.

    This facade is intentionally narrower than the reactive callback engine.
    It accepts a validated :class:`NativeStrategyIR`, one immutable prepared
    market tape, and numeric signal rows.  Under Stage-B policy, certified
    medium/large IR work resolves to one Rust boundary per run or batch. Small,
    unsupported, disabled, or unavailable-native requests use the Python
    command-tape oracle with the resolver reason retained in metadata.

    ``run_score``/``run_compact``/``run_audit`` expose the low-level retained
    outputs. ``backtest`` materializes a normal ``BacktestResultV2`` only on a
    cold reporting path and never replays a Rust execution.
    """

    def __init__(
        self,
        *,
        backend: "NativeEventBackend",
        program: NativeStrategyIR,
        datetime_index: pd.DatetimeIndex,
        symbols: Sequence[str],
        market_arrays,
        opens_arr: np.ndarray,
        contract_sizes: np.ndarray,
        leverages: np.ndarray,
        fee_rates: np.ndarray,
        execution_contract: EventClockContract | str,
    ) -> None:
        self.backend = backend
        self.program = program
        self.idx = pd.DatetimeIndex(datetime_index)
        self.symbols = tuple(str(symbol) for symbol in symbols)
        self.market_arrays = market_arrays
        self.opens_arr = np.ascontiguousarray(np.asarray(opens_arr, dtype=np.float64))
        self.contract_sizes = np.ascontiguousarray(np.asarray(contract_sizes, dtype=np.float64))
        self.leverages = np.ascontiguousarray(np.asarray(leverages, dtype=np.float64))
        self.fee_rates = np.ascontiguousarray(np.asarray(fee_rates, dtype=np.float64))
        self.execution_contract = get_event_clock_contract(execution_contract)
        if not self.symbols or len(self.symbols) != self.market_arrays.closes.shape[1]:
            raise ValueError("native IR symbols do not match the prepared market")
        if self.opens_arr.shape != self.market_arrays.closes.shape:
            raise ValueError("native IR open prices do not match the prepared market")
        if int(program.symbol_id) >= len(self.symbols):
            raise ValueError("NativeStrategyIR.symbol_id is outside the prepared market")
        self._rust_runner: RustNativeIRRunner | None = None
        self._capability_snapshot: CapabilitySnapshot | None = None
        self._plans: dict[tuple[str, bool], object] = {}

    @property
    def prepared_bars(self) -> int:
        """Return the immutable market length used by routing policy."""

        return len(self.idx)

    @property
    def last_plans(self) -> Mapping[str, Mapping[str, object]]:
        """Return resolved plan provenance keyed by profile/output intent."""

        return {
            f"{profile}:{'public' if public else 'scalar'}": plan.to_dict()
            for (profile, public), plan in self._plans.items()
        }

    @staticmethod
    def _profile(value: str | RunProfile) -> RunProfile:
        if isinstance(value, RunProfile):
            return value
        aliases = {
            "compact": "minimal",
            "full": "audit",
            "debug": "audit",
            "research": "standard",
            "optimizer": "score",
            "scoring": "score",
        }
        normalized = aliases.get(str(value or "audit").lower().strip(), str(value or "audit").lower().strip())
        return RunProfile(normalized)

    def _required_capabilities(self) -> tuple[str, ...]:
        required = set(_PROMOTED_IR_CAPABILITIES)
        if self.execution_contract.contract_id == "event_lifecycle_v3_next_open":
            required.update(
                {
                    "event_contract_registry_v1",
                    "event_lifecycle_v3_next_open",
                    "bar_fill_reason_v1",
                }
            )
        return tuple(sorted(required))

    def _load_capabilities(self) -> CapabilitySnapshot:
        if self._capability_snapshot is None:
            self._capability_snapshot = load_rust_capability_snapshot()
        return self._capability_snapshot

    def _plan_for(self, profile: RunProfile, *, public_result: bool):
        key = (profile.value, bool(public_result))
        plan = self._plans.get(key)
        if plan is not None:
            return plan
        requested_backend = self.backend.config.native_backend or "auto"
        request = BacktestRequest(
            endpoint_mode="native_strategy_ir",
            input_mode="signal",
            requested_backend=requested_backend,
            backend_policy=self.backend.config.backend_policy or "certified_only",
            execution_contract_id=self.execution_contract.contract_id,
            strategy_mode=StrategyMode.NATIVE_IR,
            workload=WorkloadClass.SIGNAL_TAPE,
            profile=profile,
            report_level=profile.value,
            audit_sink=self.backend.config.audit_sink,
            symbols=self.symbols,
            bars=len(self.idx),
            trace_requested=profile is RunProfile.AUDIT,
            public_result=bool(public_result),
            required_capabilities=self._required_capabilities(),
        )
        plan = resolve_execution_plan(request, rust_capability_loader=self._load_capabilities)
        self._plans[key] = plan
        return plan

    def _ensure_rust_runner(self) -> RustNativeIRRunner:
        if self._rust_runner is None:
            full_runner = RustFullRunner(
                idx=self.idx,
                symbols=self.symbols,
                market_arrays=self.market_arrays,
                contract_sizes=self.contract_sizes,
                leverages=self.leverages,
                fee_rates=self.fee_rates,
                initial_capital=float(self.backend.config.account.initial_capital),
                maintenance_ratio=float(self.backend.config.account.maintenance_ratio),
                slippage=float(self.backend.config.execution.slippage_rate),
                use_funding=bool(self.backend.config.use_funding),
                opens_arr=self.opens_arr,
                event_contract=self.execution_contract,
            )
            self._rust_runner = RustNativeIRRunner(full_runner, self.program)
        return self._rust_runner

    def _native_metadata(self, plan, *, profile: str, output_profile: str) -> dict[str, object]:
        return {
            "execution_plan_v1": plan.to_dict(),
            "execution_plan_fingerprint": plan.plan_fingerprint,
            "output_projection_fingerprint": plan.projection_fingerprint,
            "native_event_promotion_v1": {
                "backend_policy": plan.backend_policy,
                "reason": plan.promotion_reason,
                "table_version": plan.promotion_table_version,
                "rule_id": plan.promotion_rule_id,
                "minimum_bars": plan.promotion_minimum_bars,
                "fingerprint": plan.promotion_fingerprint,
            },
            "native_strategy_ir_execution_v1": {
                "backend": plan.backend.value,
                "profile": profile,
                "output_profile": output_profile,
                "program_fingerprint": self.program.fingerprint,
                "program_kind": self.program.kind.value,
                "prepared_bars": len(self.idx),
                "shared_market_copies_per_scenario": 0,
                "python_callbacks": 0,
                "rust_audit_replay": False,
            },
            "event_clock_contract": self.execution_contract.to_metadata(),
            "execution_contract_id": self.execution_contract.contract_id,
            "fee_rate_oneway": {
                symbol: float(self.fee_rates[col])
                for col, symbol in enumerate(self.symbols)
            },
        }

    def _run_rust(
        self,
        signal: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None,
        profile: RunProfile,
        plan,
    ) -> NativeIRRunResult:
        runner = self._ensure_rust_runner()
        if profile is RunProfile.SCORE:
            value = runner.run_score(signal, parameters=parameters)
        elif profile is RunProfile.MINIMAL:
            value = runner.run_compact(signal, parameters=parameters)
        else:
            value = runner.run_audit(signal, parameters=parameters)
        payload = dict(value.payload)
        payload.update(self._native_metadata(plan, profile=profile.value, output_profile=value.profile))
        return NativeIRRunResult(value.profile, payload)

    def _market_slice(self, start: int = 0, end: int | None = None):
        stop = len(self.idx) if end is None else int(end)
        begin = int(start)
        if not 0 <= begin < stop <= len(self.idx):
            raise ValueError("native IR market slice must be a non-empty prepared-market range")
        idx = self.idx[begin:stop]

        def series_map(values: np.ndarray) -> dict[str, pd.Series]:
            return {
                symbol: pd.Series(values[begin:stop, col], index=idx)
                for col, symbol in enumerate(self.symbols)
            }

        return (
            idx,
            series_map(self.market_arrays.closes),
            series_map(self.market_arrays.highs),
            series_map(self.market_arrays.lows),
            series_map(self.opens_arr),
            series_map(self.market_arrays.funding),
        )

    def _run_python(
        self,
        signal: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None,
        profile: RunProfile,
        plan,
        start: int = 0,
        end: int | None = None,
    ):
        """Run the existing command-tape oracle for an unpromoted IR request."""

        from .native_event import NativeEventBackend

        idx, closes, highs, lows, opens, funding = self._market_slice(start, end)
        signal_values = np.ascontiguousarray(np.asarray(signal, dtype=np.float64))
        if signal_values.shape != (len(idx),) or not np.isfinite(signal_values).all():
            raise ValueError("native IR signal must be finite and match the selected market window")
        close = closes[self.symbols[int(self.program.symbol_id)]].to_numpy(dtype=np.float64)
        reference = self.program.reference_tape(idx, signal_values, close, parameters=parameters)
        python_config = replace(
            self.backend.config,
            native_backend="python",
            report_level=profile.value,
            execution_contract=self.execution_contract,
        )
        python_backend = NativeEventBackend(python_config)
        result = python_backend.run_order_commands(
            datetime_index=idx,
            commands=reference.commands,
            closes=closes,
            highs=highs,
            lows=lows,
            opens=opens,
            funding_rate=funding,
            contract_size={symbol: float(self.contract_sizes[col]) for col, symbol in enumerate(self.symbols)},
            leverage={symbol: float(self.leverages[col]) for col, symbol in enumerate(self.symbols)},
            fee_rate={symbol: float(self.fee_rates[col]) for col, symbol in enumerate(self.symbols)},
            symbols=list(self.symbols),
            report_level=profile.value,
            audit_sink=self.backend.config.audit_sink,
            execution_contract=self.execution_contract,
        )
        result.metadata.update(
            self._native_metadata(plan, profile=profile.value, output_profile="python_compatibility")
        )
        result.metadata["native_strategy_ir_execution_v1"].update(
            {
                "backend": "python",
                "python_callbacks": 0,
                "shared_market_copies_per_scenario": None,
                "rust_audit_replay": False,
                "reference_command_count": len(reference.commands),
            }
        )
        return result, reference

    @staticmethod
    def _python_payload(result, reference, profile: RunProfile) -> NativeIRRunResult:
        counters = dict(result.metadata.get("lifecycle_counters", {}))
        payload: dict[str, object] = {
            "final_equity": float(result.equity.iloc[-1]),
            "total_fee": float(result.fees.sum()),
            "total_turnover": float(result.diagnostics.get("turnover", pd.Series(dtype=float)).sum()),
            "total_funding": float(result.funding.sum()),
            "fill_count": int(counters.get("fill_count", len(result.fills))),
            "event_count": int(counters.get("event_count", 0)),
            "rejected_count": int(counters.get("rejected_count", 0)),
            "canceled_count": int(counters.get("canceled_count", 0)),
            "liquidated": bool(result.liquidated),
            "liquidation_bar": int(result.liquidation_bar),
            "liquidation_reason": int(result.metadata.get("liquidation_reason", 0)),
            "strategy_ir_fingerprint": reference.fingerprint,
            "strategy_ir_command_count": len(reference.commands),
            "strategy_ir_disassembly": reference.disassembly,
            "python_result": result,
        }
        if profile is not RunProfile.SCORE:
            payload.update(
                {
                    "equity": np.ascontiguousarray(result.equity.to_numpy(dtype=np.float64)),
                    "positions": np.ascontiguousarray(result.positions.to_numpy(dtype=np.float64)),
                    "fees": np.ascontiguousarray(result.fees.to_numpy(dtype=np.float64)),
                    "turnover": np.ascontiguousarray(result.diagnostics["turnover"].to_numpy(dtype=np.float64)),
                    "funding": np.ascontiguousarray(result.funding.to_numpy(dtype=np.float64)),
                    "initial_margin": np.ascontiguousarray(
                        result.margin["initial_margin"].to_numpy(dtype=np.float64)
                    ),
                    "maintenance_margin": np.ascontiguousarray(
                        result.margin["maintenance_margin"].to_numpy(dtype=np.float64)
                    ),
                }
            )
        return NativeIRRunResult("score" if profile is RunProfile.SCORE else ("compact" if profile is RunProfile.MINIMAL else "audit"), payload)

    def run_score(
        self,
        signal: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None = None,
    ) -> NativeIRRunResult:
        """Score one IR signal with Rust-first promotion and Python fallback."""

        plan = self._plan_for(RunProfile.SCORE, public_result=False)
        if plan.backend.value == "rust":
            return self._run_rust(signal, parameters=parameters, profile=RunProfile.SCORE, plan=plan)
        result, reference = self._run_python(
            signal, parameters=parameters, profile=RunProfile.SCORE, plan=plan
        )
        return self._python_payload(result, reference, RunProfile.SCORE)

    def run_compact(
        self,
        signal: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None = None,
    ) -> NativeIRRunResult:
        """Run dense-path IR output without Rust audit ledger retention."""

        plan = self._plan_for(RunProfile.MINIMAL, public_result=False)
        if plan.backend.value == "rust":
            return self._run_rust(signal, parameters=parameters, profile=RunProfile.MINIMAL, plan=plan)
        result, reference = self._run_python(
            signal, parameters=parameters, profile=RunProfile.MINIMAL, plan=plan
        )
        return self._python_payload(result, reference, RunProfile.MINIMAL)

    def run_audit(
        self,
        signal: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None = None,
    ) -> NativeIRRunResult:
        """Run selected IR candidate with typed audit retention or Python fallback."""

        plan = self._plan_for(RunProfile.AUDIT, public_result=False)
        if plan.backend.value == "rust":
            return self._run_rust(signal, parameters=parameters, profile=RunProfile.AUDIT, plan=plan)
        result, reference = self._run_python(
            signal, parameters=parameters, profile=RunProfile.AUDIT, plan=plan
        )
        return self._python_payload(result, reference, RunProfile.AUDIT)

    def backtest(
        self,
        signal: Sequence[float],
        *,
        parameters: Mapping[str, float] | Sequence[float] | None = None,
        report_level: str | RunProfile = "audit",
    ):
        """Return a normal result/report surface without Rust execution replay."""

        requested = self._profile(report_level)
        # Public results need dense paths. Score retains compact Rust paths once
        # rather than executing scalar score and then replaying for a report.
        execution_profile = RunProfile.MINIMAL if requested is RunProfile.SCORE else requested
        plan = self._plan_for(requested, public_result=True)
        if plan.backend.value != "rust":
            result, _ = self._run_python(
                signal, parameters=parameters, profile=execution_profile, plan=plan
            )
            result.metadata["native_strategy_ir_execution_v1"].update(
                {"requested_profile": requested.value, "output_profile": execution_profile.value}
            )
            return result
        native = self._run_rust(
            signal,
            parameters=parameters,
            profile=execution_profile,
            plan=plan,
        )
        result = self._ensure_rust_runner().to_backtest_result(
            native,
            signal,
            parameters=parameters,
            metadata=self._native_metadata(
                plan,
                profile=requested.value,
                output_profile=native.profile,
            ),
        )
        result.metadata["native_strategy_ir_execution_v1"].update(
            {"requested_profile": requested.value, "output_profile": native.profile}
        )
        return result

    def run_batch_score(
        self,
        signals: np.ndarray | Sequence[Sequence[float]],
        *,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None = None,
        workers: int = 1,
        chunk_size: int = 256,
        fail_fast: bool = False,
    ) -> NativeIRBatchResult:
        """Score independent scenarios through one Rust batch when promoted."""

        plan = self._plan_for(RunProfile.SCORE, public_result=False)
        if plan.backend.value == "rust":
            value = self._ensure_rust_runner().run_batch_score(
                signals,
                parameter_matrix=parameter_matrix,
                workers=workers,
                chunk_size=chunk_size,
                fail_fast=fail_fast,
            )
            metadata = dict(value.metadata)
            metadata.update(self._native_metadata(plan, profile="score", output_profile="score"))
            return NativeIRBatchResult(
                scenario_id=value.scenario_id,
                status=value.status,
                final_equity=value.final_equity,
                total_fee=value.total_fee,
                total_funding=value.total_funding,
                turnover=value.turnover,
                fill_count=value.fill_count,
                rejected_count=value.rejected_count,
                liquidated=value.liquidated,
                errors=value.errors,
                metadata=metadata,
            )
        return self._run_python_batch(
            signals,
            parameter_matrix=parameter_matrix,
            profile=RunProfile.SCORE,
            plan=plan,
            fail_fast=fail_fast,
        )

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
        """Score one causal OOS window with fresh state per scenario."""

        if not isinstance(fold, NativeIRFold):
            raise TypeError("fold must be NativeIRFold")
        plan = self._plan_for(RunProfile.SCORE, public_result=False)
        if plan.backend.value == "rust":
            value = self._ensure_rust_runner().run_fold_batch_score(
                signals,
                fold,
                parameter_matrix=parameter_matrix,
                workers=workers,
                chunk_size=chunk_size,
                fail_fast=fail_fast,
            )
            metadata = dict(value.metadata)
            metadata.update(self._native_metadata(plan, profile="score", output_profile="score"))
            return NativeIRBatchResult(
                scenario_id=value.scenario_id,
                status=value.status,
                final_equity=value.final_equity,
                total_fee=value.total_fee,
                total_funding=value.total_funding,
                turnover=value.turnover,
                fill_count=value.fill_count,
                rejected_count=value.rejected_count,
                liquidated=value.liquidated,
                errors=value.errors,
                metadata=metadata,
            )
        fold.validate_for_bars(np.asarray(signals).shape[1])
        return self._run_python_batch(
            signals,
            parameter_matrix=parameter_matrix,
            profile=RunProfile.SCORE,
            plan=plan,
            fail_fast=fail_fast,
            start=int(fold.test_start),
            end=int(fold.test_end),
            fold=fold,
        )

    def _run_python_batch(
        self,
        signals: np.ndarray | Sequence[Sequence[float]],
        *,
        parameter_matrix: np.ndarray | Sequence[Sequence[float]] | None,
        profile: RunProfile,
        plan,
        fail_fast: bool,
        start: int = 0,
        end: int | None = None,
        fold: NativeIRFold | None = None,
    ) -> NativeIRBatchResult:
        signal_matrix = np.ascontiguousarray(np.asarray(signals, dtype=np.float64))
        if signal_matrix.ndim != 2 or signal_matrix.shape[1] != len(self.idx):
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
        records = []
        errors: list[str | None] = []
        for scenario_id, (signal, params) in enumerate(zip(signal_matrix, parameters)):
            try:
                result, _ = self._run_python(
                    signal[int(start) : end],
                    parameters=params,
                    profile=profile,
                    plan=plan,
                    start=start,
                    end=end,
                )
                counters = dict(result.metadata.get("lifecycle_counters", {}))
                records.append(
                    (
                        int(scenario_id),
                        0,
                        float(result.equity.iloc[-1]),
                        float(result.fees.sum()),
                        float(result.funding.sum()),
                        float(result.diagnostics["turnover"].sum()),
                        int(counters.get("fill_count", len(result.fills))),
                        int(counters.get("rejected_count", 0)),
                        bool(result.liquidated),
                    )
                )
                errors.append(None)
            except Exception as exc:
                if fail_fast:
                    raise
                records.append((int(scenario_id), 1, np.nan, np.nan, np.nan, np.nan, 0, 0, False))
                errors.append(f"{type(exc).__name__}: {exc}")
        values = list(zip(*records)) if records else [()] * 9
        metadata = self._native_metadata(plan, profile="score", output_profile="python_compatibility")
        metadata["native_strategy_ir_execution_v1"].update(
            {
                "backend": "python",
                "boundary_calls": len(records),
                "shared_market_copies_per_scenario": None,
                "workers_requested": 1,
                "fold_id": None if fold is None else int(fold.fold_id),
            }
        )
        return NativeIRBatchResult(
            scenario_id=np.asarray(values[0], dtype=np.uint32),
            status=np.asarray(values[1], dtype=np.uint16),
            final_equity=np.asarray(values[2], dtype=np.float64),
            total_fee=np.asarray(values[3], dtype=np.float64),
            total_funding=np.asarray(values[4], dtype=np.float64),
            turnover=np.asarray(values[5], dtype=np.float64),
            fill_count=np.asarray(values[6], dtype=np.uint32),
            rejected_count=np.asarray(values[7], dtype=np.uint32),
            liquidated=np.asarray(values[8], dtype=np.bool_),
            errors=tuple(errors),
            metadata=metadata,
        )


__all__ = [
    "NativeIRBatchResult",
    "NativeIRExecutionRunner",
    "NativeIRFold",
    "NativeIRRunResult",
    "RustNativeIRRunner",
]

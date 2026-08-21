"""Pandas-free Python and Rust sessions for prepared native-event tapes."""

from __future__ import annotations

import importlib

import numpy as np

from ..core.event import (
    ORDER_STATUS_CANCELED,
    ORDER_STATUS_REJECTED,
    _engine_event_v2,
)
from ..core.event_contracts import get_event_clock_contract
from ..planning import BackendKind, DetailLevel, ExecutionPlan, PathMask
from ..preparation import PreparedRun
from ..results import (
    RawCommandStateBuffer,
    RawEngineDiagnostics,
    RawEnginePaths,
    RawEngineResult,
    RawEngineSummary,
    RawEventBuffer,
    RawFillBuffer,
)
from .protocol import BackendDescriptor, EngineRunRequest, ResetRequest


_CONTRACTS = (
    "event_lifecycle_v2_next_bar_close",
    "event_lifecycle_v3_next_open",
)


def _array_bytes(*arrays: np.ndarray) -> int:
    return sum(int(array.nbytes) for array in arrays)


def _summary(
    *,
    equity,
    positions,
    fees,
    funding,
    turnover,
    initial_margin,
    maintenance_margin,
    fill_count,
    event_count,
    rejected_count,
    canceled_count,
    liquidated,
    liquidation_bar,
    liquidation_reason,
) -> RawEngineSummary:
    return RawEngineSummary(
        final_equity=float(equity[-1]),
        final_positions=np.asarray(positions[-1], dtype=np.float64),
        total_fee=float(np.sum(fees)),
        total_funding=float(np.sum(funding)),
        total_turnover=float(np.sum(turnover)),
        fill_count=int(fill_count),
        event_count=int(event_count),
        rejected_count=int(rejected_count),
        canceled_count=int(canceled_count),
        max_initial_margin=float(np.max(initial_margin, initial=0.0)),
        max_maintenance_margin=float(np.max(maintenance_margin, initial=0.0)),
        liquidated=bool(liquidated),
        liquidation_bar=int(liquidation_bar),
        liquidation_reason=int(liquidation_reason),
    )


def _project_paths(request: EngineRunRequest, values) -> RawEnginePaths | None:
    if request.output.dense_paths == PathMask.NONE:
        return None
    return RawEnginePaths(*values)


class PythonNativeEventBackend:
    _descriptor = BackendDescriptor(
        name=BackendKind.PYTHON,
        implementation_version="p1-reference-v1",
        protocol_version=1,
        command_abi_version="full-command-v1",
        result_abi_version="raw-engine-result-v1",
        contracts=_CONTRACTS,
        workloads=("static_command_tape",),
        build="python-numba",
    )

    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    def prepare(self, plan: ExecutionPlan, prepared: PreparedRun):
        if plan.backend is not BackendKind.PYTHON:
            raise ValueError("Python backend received a non-Python plan")
        return _PythonNativeEventSession(plan, prepared, self.descriptor)


class _PythonNativeEventSession:
    def __init__(self, plan, prepared, descriptor):
        self.plan = plan
        self.prepared = prepared
        self._descriptor = descriptor
        self._runs = 0
        self._closed = False

    @property
    def descriptor(self):
        return self._descriptor

    def run(self, request: EngineRunRequest) -> RawEngineResult:
        if self._closed:
            raise RuntimeError("prepared engine session is closed")
        if request.output.fingerprint != self.plan.output.fingerprint:
            raise ValueError("EngineRunRequest output differs from the immutable execution plan")
        market = self.prepared.market
        tape = self.prepared.command_tape
        instruments = self.prepared.instruments
        account = self.prepared.account
        clock = get_event_clock_contract(self.plan.contract_id)
        output = _engine_event_v2(
            n_bars=market.n_bars,
            n_syms=market.n_symbols,
            n_commands=tape.n_commands,
            n_ids=len(tape.id_values),
            command_ptr=tape.command_ptr,
            command_action=tape.command_action,
            command_symbol=tape.command_symbol,
            command_side=tape.command_side,
            command_type=tape.command_type,
            command_qty=tape.command_qty,
            command_price=tape.command_price,
            command_trigger_price=tape.command_trigger_price,
            command_tif=tape.command_tif,
            command_reduce_only=tape.command_reduce_only,
            command_order_id=tape.command_order_id,
            command_target_order_id=tape.command_target_order_id,
            command_parent_order_id=tape.command_parent_order_id,
            command_group_id=tape.command_group_id,
            command_oco_group_id=tape.command_oco_group_id,
            command_activation=tape.command_activation,
            command_expires_bar=tape.command_expires_bar,
            opens=market.opens,
            highs=market.highs,
            lows=market.lows,
            closes=market.closes,
            funding_rates=market.funding_rates,
            is_funding_bar=market.funding_event_mask,
            init_capital=account.initial_capital,
            leverages=instruments.leverages,
            maint_ratio=account.maintenance_ratio,
            fee_rates=instruments.fee_rates,
            contract_sizes=instruments.table.contract_size,
            slippage=account.slippage_rate,
            use_funding=account.use_funding,
            event_contract_code=clock.contract_code,
        )
        (
            equity, positions, fees, turnover, funding, initial_margin, maintenance_margin,
            rejected_bar, canceled_bar, command_status, reject_code, fill_bar, fill_qty,
            fill_price, fill_fee, active, waiting_parent, working_qty, working_price,
            working_trigger, trigger_armed, fill_reason, fill_ambiguity, event_count,
            event_bar, event_command, event_type, event_status, event_related_command,
            liquidated, liquidation_bar, liquidation_reason, expiry_scans, matching_scans,
            relationship_scans,
        ) = output
        fill_mask = (fill_bar >= 0) & (fill_qty != 0.0)
        fill_indexes = np.flatnonzero(fill_mask).astype(np.int64)
        fills = None
        if request.output.fill_detail not in {DetailLevel.NONE, DetailLevel.COUNT}:
            fills = RawFillBuffer(
                bar=fill_bar[fill_mask],
                command_index=fill_indexes,
                order_id_code=tape.command_order_id[fill_mask],
                symbol_code=tape.command_symbol[fill_mask],
                side=tape.command_side[fill_mask],
                qty=fill_qty[fill_mask],
                price=fill_price[fill_mask],
                fee=fill_fee[fill_mask],
                reason=fill_reason[fill_mask],
                ambiguity=fill_ambiguity[fill_mask],
            )
        events = None
        if request.output.event_detail not in {DetailLevel.NONE, DetailLevel.COUNT}:
            size = int(event_count)
            event_commands = np.asarray(event_command[:size], dtype=np.int64)
            valid = (event_commands >= 0) & (event_commands < tape.n_commands)
            order_ids = np.full(size, -1, dtype=np.int64)
            target_ids = np.full(size, -1, dtype=np.int64)
            symbols = np.full(size, -1, dtype=np.int64)
            order_ids[valid] = tape.command_order_id[event_commands[valid]]
            target_ids[valid] = tape.command_target_order_id[event_commands[valid]]
            symbols[valid] = tape.command_symbol[event_commands[valid]]
            events = RawEventBuffer(
                bar=event_bar[:size],
                kind=event_type[:size],
                status=event_status[:size],
                command_index=event_commands,
                order_id_code=order_ids,
                target_id_code=target_ids,
                symbol_code=symbols,
                reject_code=np.where(event_status[:size] == ORDER_STATUS_REJECTED, 1, 0),
            )
        command_states = None
        if request.output.active_order_detail is not DetailLevel.NONE or request.output.event_detail is DetailLevel.FULL:
            command_states = RawCommandStateBuffer(
                status=command_status,
                reject_code=reject_code,
                fill_bar=fill_bar,
                fill_qty=fill_qty,
                fill_price=fill_price,
                fill_fee=fill_fee,
                active=active,
                waiting_parent=waiting_parent,
                working_qty=working_qty,
                working_price=working_price,
                working_trigger=working_trigger,
                trigger_armed=trigger_armed,
                fill_reason=fill_reason,
                fill_ambiguity=fill_ambiguity,
            )
        paths = _project_paths(
            request,
            (
                equity, positions, fees, turnover, funding, initial_margin,
                maintenance_margin, rejected_bar, canceled_bar,
            ),
        )
        summary = _summary(
            equity=equity,
            positions=positions,
            fees=fees,
            funding=funding,
            turnover=turnover,
            initial_margin=initial_margin,
            maintenance_margin=maintenance_margin,
            fill_count=np.sum(fill_mask),
            event_count=event_count,
            rejected_count=np.sum(command_status == ORDER_STATUS_REJECTED),
            canceled_count=np.sum(command_status == ORDER_STATUS_CANCELED),
            liquidated=liquidated,
            liquidation_bar=liquidation_bar,
            liquidation_reason=liquidation_reason,
        )
        self._runs += 1
        return RawEngineResult(
            summary=summary,
            paths=paths,
            fills=fills,
            events=events,
            command_states=command_states,
            diagnostics=RawEngineDiagnostics(
                backend="python",
                protocol_version=1,
                run_calls=1,
                prepare_calls=1,
                output_projection_fingerprint=request.output.fingerprint,
                expiry_scan_count=int(expiry_scans),
                matching_scan_count=int(matching_scans),
                relationship_scan_count=int(relationship_scans),
                retained_path_bytes=0 if paths is None else _array_bytes(
                    paths.equity, paths.positions, paths.fees, paths.turnover, paths.funding,
                    paths.initial_margin, paths.maintenance_margin, paths.rejected_orders,
                    paths.canceled_orders,
                ),
                retained_fill_bytes=0 if fills is None else _array_bytes(
                    fills.bar, fills.command_index, fills.order_id_code, fills.symbol_code,
                    fills.side, fills.qty, fills.price, fills.fee, fills.reason, fills.ambiguity,
                ),
                retained_event_bytes=0 if events is None else _array_bytes(
                    events.bar, events.kind, events.status, events.command_index,
                    events.order_id_code, events.target_id_code, events.symbol_code, events.reject_code,
                ),
            ),
            plan_fingerprint=self.plan.plan_fingerprint,
            prepared_fingerprint=self.prepared.keys.combined,
            backend_metadata=(("engine", "event_v2_p1_python_raw"),),
        )

    def reset(self, reset: ResetRequest = ResetRequest()) -> None:
        if self._closed:
            raise RuntimeError("prepared engine session is closed")
        self._runs = 0

    def close(self) -> None:
        self._closed = True


class RustNativeEventBackend:
    _descriptor = BackendDescriptor(
        name=BackendKind.RUST,
        implementation_version="native-api-0.4",
        protocol_version=1,
        command_abi_version="full-command-v1",
        result_abi_version="raw-engine-result-v1",
        contracts=_CONTRACTS,
        workloads=("static_command_tape",),
        build="pyo3",
    )

    @property
    def descriptor(self) -> BackendDescriptor:
        return self._descriptor

    def prepare(self, plan: ExecutionPlan, prepared: PreparedRun):
        if plan.backend is not BackendKind.RUST:
            raise ValueError("Rust backend received a non-Rust plan")
        return _RustNativeEventSession(plan, prepared, self.descriptor)


class _RustNativeEventSession:
    def __init__(self, plan, prepared, descriptor):
        self.plan = plan
        self.prepared = prepared
        self._descriptor = descriptor
        self._closed = False
        self._module = importlib.import_module("_quantbt_native")
        market = prepared.market
        self._market_core = self._module.FullPreparedMarketCore(
            market.timestamps_ns,
            market.opens,
            market.highs,
            market.lows,
            market.closes,
            market.volumes,
            market.funding_rates,
            market.funding_event_mask,
        )
        self._session = self._new_session()
        self._command_arrays = self._compile_commands()

    @property
    def descriptor(self):
        return self._descriptor

    def _new_session(self):
        instruments = self.prepared.instruments
        account = self.prepared.account
        session = self._module.FullReactiveSessionCore.from_prepared(
            self._market_core,
            instruments.table.contract_size,
            instruments.leverages,
            instruments.fee_rates,
            account.initial_capital,
            account.maintenance_ratio,
            account.slippage_rate,
            account.use_funding,
        )
        session.set_event_contract(get_event_clock_contract(self.plan.contract_id).contract_code)
        return session

    def _compile_commands(self):
        tape = self.prepared.command_tape
        n = tape.n_commands
        # API 0.4 reserves columns 13-15 for forward-compatible full-command
        # flags. The current semantic compiler writes columns 0-12 only.
        codes = np.full((n, 16), -1, dtype=np.int64)
        values = np.zeros((n, 3), dtype=np.float64)
        if n:
            codes[:, 0] = tape.command_action
            codes[:, 1] = tape.command_symbol
            codes[:, 2] = tape.command_side
            codes[:, 3] = tape.command_type
            codes[:, 4] = tape.command_tif
            codes[:, 5] = tape.command_reduce_only
            codes[:, 6] = tape.command_order_id
            codes[:, 7] = tape.command_target_order_id
            codes[:, 8] = tape.command_parent_order_id
            codes[:, 9] = tape.command_group_id
            codes[:, 10] = tape.command_oco_group_id
            codes[:, 11] = tape.command_activation
            codes[:, 12] = np.arange(n, dtype=np.int64)
            values[:, 0] = tape.command_qty
            values[:, 1] = tape.command_price
            values[:, 2] = tape.command_trigger_price
        return tape.command_ptr, codes, values, tape.command_expires_bar

    def run(self, request: EngineRunRequest) -> RawEngineResult:
        if self._closed:
            raise RuntimeError("prepared engine session is closed")
        if request.output.fingerprint != self.plan.output.fingerprint:
            raise ValueError("EngineRunRequest output differs from the immutable execution plan")
        ptr, codes, values, expiry = self._command_arrays
        score_only = request.output.dense_paths == PathMask.NONE
        if score_only:
            payload = self._session.run_tape_score(ptr, codes, values, expiry)
            summary = RawEngineSummary(
                final_equity=float(payload["final_equity"]),
                final_positions=np.asarray(payload["final_positions"], dtype=np.float64),
                total_fee=float(payload["total_fee"]),
                total_funding=float(payload["total_funding"]),
                total_turnover=float(payload["total_turnover"]),
                fill_count=int(payload["fill_count"]),
                event_count=int(payload["event_count"]),
                rejected_count=int(payload["rejected_count"]),
                canceled_count=int(payload["canceled_count"]),
                max_initial_margin=float(payload["max_initial_margin"]),
                max_maintenance_margin=float(payload["max_maintenance_margin"]),
                liquidated=bool(payload["liquidated"]),
                liquidation_bar=int(payload["liquidation_bar"]),
                liquidation_reason=int(payload["liquidation_reason"]),
            )
            paths = fills = events = None
        else:
            payload = self._session.run_tape_audit(ptr, codes, values, expiry)
            equity = np.asarray(payload["equity"], dtype=np.float64)
            positions = np.asarray(payload["positions"], dtype=np.float64).reshape(
                self.prepared.market.n_bars, self.prepared.market.n_symbols
            )
            fees = np.asarray(payload["fees"], dtype=np.float64)
            turnover = np.asarray(payload["turnover"], dtype=np.float64)
            funding = np.asarray(payload["funding"], dtype=np.float64)
            initial_margin = np.asarray(payload["initial_margin"], dtype=np.float64)
            maintenance_margin = np.asarray(payload["maintenance_margin"], dtype=np.float64)
            zeros = np.zeros(len(equity), dtype=np.int64)
            paths = RawEnginePaths(
                equity=equity,
                positions=positions,
                fees=fees,
                turnover=turnover,
                funding=funding,
                initial_margin=initial_margin,
                maintenance_margin=maintenance_margin,
                rejected_orders=zeros,
                canceled_orders=zeros,
            )
            fill_size = int(payload["fill_count"])
            fills = None
            if request.output.fill_detail not in {DetailLevel.NONE, DetailLevel.COUNT}:
                fills = RawFillBuffer(
                    bar=np.asarray(payload["fill_bar"][:fill_size]),
                    command_index=np.full(fill_size, -1, dtype=np.int64),
                    order_id_code=np.asarray(payload["fill_order_id"][:fill_size]),
                    symbol_code=np.asarray(payload["fill_symbol"][:fill_size]),
                    side=np.asarray(payload["fill_side"][:fill_size]),
                    qty=np.asarray(payload["fill_qty"][:fill_size]),
                    price=np.asarray(payload["fill_price"][:fill_size]),
                    fee=np.asarray(payload["fill_fee"][:fill_size]),
                    reason=np.asarray(payload["fill_reason"][:fill_size]),
                    ambiguity=np.asarray(payload["fill_ambiguity"][:fill_size]),
                )
            event_size = int(payload["event_count"])
            events = None
            if request.output.event_detail not in {DetailLevel.NONE, DetailLevel.COUNT}:
                events = RawEventBuffer(
                    bar=np.asarray(payload["event_bar"][:event_size]),
                    kind=np.asarray(payload["event_kind"][:event_size]),
                    status=np.asarray(payload["event_status"][:event_size]),
                    command_index=np.full(event_size, -1, dtype=np.int64),
                    order_id_code=np.asarray(payload["event_order_id"][:event_size]),
                    target_id_code=np.asarray(payload["event_target_id"][:event_size]),
                    symbol_code=np.asarray(payload["event_symbol"][:event_size]),
                    reject_code=np.asarray(payload["event_reject_code"][:event_size]),
                )
            summary = _summary(
                equity=equity,
                positions=positions,
                fees=fees,
                funding=funding,
                turnover=turnover,
                initial_margin=initial_margin,
                maintenance_margin=maintenance_margin,
                fill_count=payload["fill_count"],
                event_count=payload["event_count"],
                rejected_count=payload["rejected_count"],
                canceled_count=payload["canceled_count"],
                liquidated=payload["liquidated"],
                liquidation_bar=payload["liquidation_bar"],
                liquidation_reason=payload["liquidation_reason"],
            )
        return RawEngineResult(
            summary=summary,
            paths=paths,
            fills=fills,
            events=events,
            command_states=None,
            diagnostics=RawEngineDiagnostics(
                backend="rust",
                protocol_version=1,
                run_calls=1,
                prepare_calls=1,
                output_projection_fingerprint=request.output.fingerprint,
                retained_path_bytes=0 if paths is None else _array_bytes(
                    paths.equity, paths.positions, paths.fees, paths.turnover, paths.funding,
                    paths.initial_margin, paths.maintenance_margin,
                ),
                retained_fill_bytes=0 if fills is None else _array_bytes(
                    fills.bar, fills.order_id_code, fills.symbol_code, fills.side,
                    fills.qty, fills.price, fills.fee, fills.reason, fills.ambiguity,
                ),
                retained_event_bytes=0 if events is None else _array_bytes(
                    events.bar, events.kind, events.status, events.order_id_code,
                    events.target_id_code, events.symbol_code, events.reject_code,
                ),
            ),
            plan_fingerprint=self.plan.plan_fingerprint,
            prepared_fingerprint=self.prepared.keys.combined,
            backend_metadata=(("engine", "event_v2_p1_rust_raw"), ("pycalls", "1")),
        )

    def reset(self, reset: ResetRequest = ResetRequest()) -> None:
        if self._closed:
            raise RuntimeError("prepared engine session is closed")
        self._session.reset()
        self._session.set_event_contract(get_event_clock_contract(self.plan.contract_id).contract_code)

    def close(self) -> None:
        self._closed = True
        self._session = None


__all__ = ["PythonNativeEventBackend", "RustNativeEventBackend"]

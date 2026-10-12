"""Source-bound continuous witnesses for the original next-open event provider.

This sidecar does not dispatch, execute, replay, or reduce financial accounts.
Only static lifecycle tapes and single-pass Python callbacks are qualified here.
The strategy file pin does not qualify its dependencies or preload permissions.
"""

from __future__ import annotations

from hashlib import sha256
from importlib import import_module
import inspect
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ..core.constraints import build_quantity_constraints
from ..core.event_contracts import EVENT_LIFECYCLE_V3_NEXT_OPEN, get_event_clock_contract
from ..core.results import BacktestResultV2
from ..core.wfo_contracts import strategy_fingerprint
from ..optimization.meta_selection.observer import economics_identity
from .diagnostics.identity import digest
from .dossier.records import Record

if TYPE_CHECKING:
    from ..endpoint import EndpointConfig, _WalkForwardEndpointScorer
    from .continuous import ContinuousAccountContract

__all__ = ["producer_records", "qualify_producer", "validate_result"]

_SOURCE_MODULES = (
    "mode5.event_producer", "endpoint", "engines", "wfo_execution", "api.event_driven",
    "backends.native_event", "backends._native_event_rust", "backends.native_audit_projection",
    "core.event", "core.order_compiler", "core.orders", "core.event_contracts",
    "core.generated_native_event_contracts", "core.generated_product_contracts",
    "core.native_event_capabilities", "core.native_event_promotion", "core.product_contracts",
    "core.constraints", "core.schema", "core.preprocessor", "core.results", "core.reactive",
    "core.accounting_contracts", "core.execution_trace", "core.wfo_contracts",
    "planning.resolve", "planning.models", "planning.capabilities", "planning.output",
    "preparation.native_event", "preparation.native_execution", "preparation.models",
    "strategies.driver", "strategies.context", "strategies.requirements", "strategies.commands",
    "optimization.meta_selection.observer",
)


def _qualified_clock(config: EndpointConfig) -> dict:
    from ..endpoint import EndpointConfig

    if type(config) is not EndpointConfig:
        raise TypeError("original EndpointConfig required")
    if (config.mode not in {"native_event_strategy", "orders"}
            or config.backend != "native_event" or config.native_backend not in {"python", "rust"}
            or config.event_engine_version != "v2" or config.native_static_abi != "0.5"):
        raise NotImplementedError("qualified event lifecycle route requires explicit python/rust and ABI 0.5")
    try:
        clock = get_event_clock_contract(config.execution_contract)
    except (KeyError, TypeError, ValueError) as error:
        raise NotImplementedError("explicit qualified v3-next-open clock required") from error
    canonical = get_event_clock_contract(EVENT_LIFECYCLE_V3_NEXT_OPEN).to_metadata()
    if clock.to_metadata() != canonical:
        raise NotImplementedError("only the exact registered v3-next-open clock is qualified")
    if not config.symbols or len(set(config.symbols)) != len(config.symbols):
        raise ValueError("explicit fixed symbol universe required")
    if config.mode == "native_event_strategy" and (
            config.reactive_runtime != "legacy_python_loop"
            or config.reactive_execution_mode not in {"fast", "audit"}
            or config.reactive_kernel_mode != "single_pass"
            or config.audit_mode not in {None, "native_trace"}
            or config.oracle_sample_rate != 0):
        raise NotImplementedError("unqualified callback runtime or replay mode")
    return canonical


def _source_identity(config: EndpointConfig) -> str:
    pins = [(name, sha256(Path(import_module("quantbt." + name).__file__).read_bytes()).hexdigest())
            for name in _SOURCE_MODULES]
    if config.native_backend == "rust":
        from ..backends._native_event_rust import probe_native_event_rust_extension

        status = probe_native_event_rust_extension()
        if not status.available or not status.compatible:
            raise NotImplementedError("compatible installed native event binary required")
        native = import_module("_quantbt_native._quantbt_native")
        pins.append(("_quantbt_native", sha256(Path(native.__file__).read_bytes()).hexdigest()))
    return digest(pins)


def _input_identity(value: object) -> str:
    # Endpoint reporting describes Series shape, not its actual funding values.
    if isinstance(value, pd.Series):
        return digest(dict(name=value.name, dtype=str(value.dtype),
            values=sha256(pd.util.hash_pandas_object(value, index=True).to_numpy().tobytes()).hexdigest()))
    if isinstance(value, dict):
        return digest({str(k): _input_identity(v) for k, v in value.items()})
    from ..endpoint import _jsonable

    return digest(_jsonable(value))


def _execution_record(config: EndpointConfig) -> Record:
    from ..endpoint import _endpoint_run_config_payload, _jsonable

    clock = _qualified_clock(config)
    engine = ("event_v3_reactive_single_pass" if config.mode == "native_event_strategy"
        else "event_v2_rust_full_contract" if config.native_backend == "rust" else "event_v3_lifecycle")
    constraints = build_quantity_constraints(config.symbols, instruments=config.instruments,
        qty_step=config.qty_step, lot_size=config.lot_size, slot_size=config.slot_size,
        min_qty=config.min_qty, min_notional=config.min_notional).as_dict()
    return Record.of(dict(route=config.mode, backend="native_event",
        clock=dict(id=clock["contract_id"], equity_clock="bar_close", event_clock_contract=clock,
            command_timestamp_semantics="signal_bar_close" if config.mode == "native_event_strategy" else "effective_bar",
            # Preserve the original public adapter's generic metadata separately
            # from the authoritative, fully specified event clock above.
            execution_contract=dict(engine_id=engine, signal_phase="unspecified",
                fill_phase="unspecified", intrabar_exit_model="unspecified")),
        initial_state=dict(equity=float(config.account.initial_capital), position_policy="flat",
            order_policy="empty", phase="before_first_bar"),
        terminal_policy=dict(id="event_lifecycle_v3_original", equity_clock="bar_close",
            positions="original_no_forced_flatten", orders="original_terminal_state",
            last_bar_policy=clock["last_bar_policy"]),
        economics=dict(identity=economics_identity(config), source_identity=_source_identity(config),
            run_config=_endpoint_run_config_payload(config), native_backend=config.native_backend,
            backend_policy=config.backend_policy, native_static_abi=config.native_static_abi,
            reactive_runtime=config.reactive_runtime, reactive_gil_policy=config.reactive_gil_policy,
            reactive_execution_mode=config.reactive_execution_mode, reactive_kernel_mode=config.reactive_kernel_mode,
            audit_mode=config.audit_mode, oracle_sample_rate=config.oracle_sample_rate,
            oracle_sample_seed=config.oracle_sample_seed, quantity_constraints=constraints,
            instruments=_jsonable(config.instruments), qty_step=_jsonable(config.qty_step),
            lot_size=_jsonable(config.lot_size), slot_size=_jsonable(config.slot_size),
            min_qty=_jsonable(config.min_qty), min_notional=_jsonable(config.min_notional),
            funding_input_identity=_input_identity(config.funding_rate))))


def producer_records(config: EndpointConfig, strategy: object) -> tuple[Record, Record]:
    """Freeze actual endpoint/source configuration, never researcher metadata."""
    execution = _execution_record(config)
    candidate = strategy if inspect.isclass(strategy) or inspect.isroutine(strategy) else type(strategy)
    path = inspect.getsourcefile(candidate)
    if path is None or not Path(path).is_file():
        raise TypeError("source-backed original strategy required")
    source = Record.of(dict(alpha=strategy_fingerprint(strategy),
        alpha_source=sha256(Path(path).read_bytes()).hexdigest(),
        financial_provider=execution.data["economics"]["source_identity"]))
    return source, execution


def qualify_producer(scorer: _WalkForwardEndpointScorer, strategy: object,
                     contract: ContinuousAccountContract) -> Record:
    """Require the existing original scorer, not a lookalike witness supplier."""
    from ..endpoint import _WalkForwardEndpointScorer

    if type(scorer) is not _WalkForwardEndpointScorer:
        raise TypeError("original public endpoint scorer required; no self-certified execution witness")
    if list(scorer.symbols or ()) != list(scorer.score_config.symbols or ()):
        raise ValueError("original scorer universe differs from continuous event config")
    source, execution = producer_records(scorer.score_config, strategy)
    if source != contract.source or execution != contract.execution:
        raise ValueError("actual event producer source/backend/clock/economics differs from continuous binding")
    return execution


def validate_result(result: BacktestResultV2, execution: Record, config: EndpointConfig) -> None:
    """Reconcile the original result in place without editing or replaying it.

    Provenance comes from qualification of the original scorer. Metadata alone
    is not proof of execution, nor is this a new fill/accounting oracle.
    """
    if not isinstance(execution, Record) or execution != _execution_record(config):
        raise ValueError("event producer source/config/backend/clock/economics drift")
    if type(result) is not BacktestResultV2:
        raise TypeError("original BacktestResultV2 account paths required")
    e = execution.data
    metadata = result.metadata
    expected = dict(backend="native_event", execution_contract_id=e["clock"]["id"],
        event_clock_contract=e["clock"]["event_clock_contract"],
        execution_contract=e["clock"]["execution_contract"],
        engine=e["clock"]["execution_contract"]["engine_id"],
        native_event_backend_requested=config.native_backend, native_event_backend_resolved=config.native_backend,
        run_config=e["economics"]["run_config"], quantity_constraints=e["economics"]["quantity_constraints"],
        fee_rate_oneway=float(config.canonical_one_way_fee_rate),
        fee_rate=float(config.canonical_one_way_fee_rate),
        canonical_one_way_fee_rate=float(config.canonical_one_way_fee_rate),
        fee_round_trip=float(config.fee), slippage_bps=float(config.execution.slippage_bps),
        slippage=float(config.slippage), use_funding=bool(config.use_funding),
        initial_capital=float(config.account.initial_capital), leverage=float(config.account.leverage),
        maintenance_ratio=float(config.account.maintenance_ratio))
    if config.native_backend == "rust":
        expected.update(native_event_rust_available=True, native_event_rust_compatible=True,
            native_event_rust_fallback_reason=None)
    if config.mode == "native_event_strategy":
        expected.update(reactive_execution_mode=config.reactive_execution_mode,
            reactive_kernel_mode="single_pass", command_effective_phase="next_bar",
            single_pass_accounting_source="reactive_session_state", state_owner=config.native_backend,
            authoritative_mutable_state_count=1, python_shadow_accounting=False,
            primary_engine_runs=1, oracle_engine_runs=0, reactive_static_replay_count=0,
            single_pass_replay_certified=False, static_replay_available=False)
    elif config.native_backend == "rust":
        expected.update(rust_contract="native_event_v3_full_contract", rust_audit_replay=False,
            native_static_abi_requested="0.5", native_static_abi_resolved="0.5",
            native_terminal_state_v1=dict(authority="rust", available=True, reason=None, replayed=False))
    if any(k not in metadata or Record.of(dict(value=metadata[k])) != Record.of(dict(value=v))
           for k, v in expected.items()):
        raise ValueError("original event result backend/clock/economics/lifecycle metadata mismatch")
    if (result.initial_capital != config.account.initial_capital or result.leverage != config.account.leverage
            or list(result.symbols) != list(config.symbols)):
        raise ValueError("original account initial capital/leverage/symbol universe mismatch")
    if not isinstance(result.equity, pd.Series):
        raise TypeError("original bar-close equity Series required")
    index = result.equity.index
    if (not isinstance(index, pd.DatetimeIndex) or not len(index) or str(index.tz) != "UTC"
            or not index.is_unique or not index.is_monotonic_increasing):
        raise ValueError("original complete UTC bar-close account required")
    for name in ("equity", "returns", "positions", "closes", "fees", "funding", "margin"):
        path = getattr(result, name)
        expected_type = pd.DataFrame if name in {"positions", "closes", "margin"} else pd.Series
        if (not isinstance(path, expected_type) or not path.index.equals(index) or not path.size
                or not np.isfinite(path.to_numpy(dtype=float)).all()):
            raise ValueError("original finite bar-close account path required: " + name)
    if not config.use_funding and np.any(result.funding.to_numpy() != 0):
        raise ValueError("disabled funding differs from original executed account")
    if type(result.liquidated) is not bool or (result.liquidated and (
            type(result.liquidation_bar) is not int or not 0 <= result.liquidation_bar < len(index))):
        raise ValueError("original liquidation lifecycle required")

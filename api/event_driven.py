"""Plan, prepare, execute, and adapt native-event lifecycle requests once."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from ..backends.native_event import NativeEventBackend, NativeEventConfig
from ..core.event_contracts import EVENT_LIFECYCLE_V3_NEXT_OPEN, get_event_clock_contract
from ..core.orders import OrderCommand
from ..core.schema import AccountConfig, ExecutionConfig
from ..planning import (
    BacktestRequest,
    RunProfile,
    StrategyMode,
    WorkloadClass,
    resolve_execution_plan,
)
from ..preparation import NativeEventPreparation, prepare_native_event_lifecycle


@dataclass(frozen=True, slots=True)
class NativeEventLifecycleOutcome:
    result: object
    engine: NativeEventBackend
    preparation: NativeEventPreparation


def _profile(report_level: str) -> RunProfile:
    value = str(report_level or "audit").lower().strip()
    aliases = {
        "full": "audit",
        "debug": "audit",
        "research": "standard",
        "optimizer": "score",
        "scoring": "score",
    }
    return RunProfile(aliases.get(value, value))


def execute_native_event_lifecycle(
    *,
    datetime_index,
    commands: Sequence[OrderCommand],
    closes,
    highs,
    lows,
    opens,
    volumes,
    symbols,
    account: AccountConfig,
    execution: ExecutionConfig,
    native_backend: str | None,
    backend_policy: str | None,
    execution_contract,
    report_level: str,
    audit_sink: str,
    audit_sink_path: str | None,
    funding_rate,
    use_funding: bool,
    contract_size,
    leverage,
    fee_rate,
    instruments,
    qty_step,
    lot_size,
    slot_size,
    min_qty,
    min_notional,
    diagnostics: bool = False,
) -> NativeEventLifecycleOutcome:
    """Execute the P1 static-command compatibility route.

    Planning and all pandas normalization happen before backend construction.
    The current public-result adapter remains the P0 implementation so report,
    trace, and metadata behavior stay exact while P1 ownership migrates.
    """

    symbol_values = tuple(symbols)
    clock = get_event_clock_contract(execution_contract or "event_lifecycle_v2_next_bar_close")
    requested_backend = str(native_backend or "auto").lower().strip()
    # Declare the complete static-command capability shape for every backend
    # request.  Stage-B ``auto`` must validate the same V2/V3 contract as an
    # explicit Rust request before it can promote a route.
    required = (
        "native_event_v2_full_contract",
        "native_event_v2_multisymbol",
        "native_event_v2_funding",
        "native_event_v2_liquidation",
        "native_event_v2_cancel_all_oco",
        "native_event_v2_tif_expiry",
        "native_event_v2_relationships",
        "native_event_v2_quantity_preflight",
    )
    if clock.contract_id == EVENT_LIFECYCLE_V3_NEXT_OPEN:
        required += (
            "event_contract_registry_v1",
            "event_lifecycle_v3_next_open",
            "bar_fill_reason_v1",
        )
    profile = _profile(report_level)
    request = BacktestRequest(
        endpoint_mode="orders",
        input_mode="orders",
        requested_backend=requested_backend,
        backend_policy=backend_policy or "certified_only",
        execution_contract_id=clock.contract_id,
        strategy_mode=StrategyMode.STATIC_COMMANDS,
        workload=WorkloadClass.STATIC_COMMAND_TAPE,
        profile=profile,
        report_level=profile.value,
        audit_sink=str(audit_sink),
        symbols=symbol_values,
        command_count=len(commands),
        bars=len(datetime_index),
        trace_requested=profile is RunProfile.AUDIT,
        # The stable facade always returns BacktestResultV2. Internal score
        # sessions set this false and retain scalar counters only.
        public_result=True,
        required_capabilities=required,
    )
    plan = resolve_execution_plan(request)
    preparation = prepare_native_event_lifecycle(
        plan=plan,
        datetime_index=datetime_index,
        commands=commands,
        closes=closes,
        highs=highs,
        lows=lows,
        opens=opens,
        volumes=volumes,
        funding_rate=funding_rate,
        symbols=symbol_values,
        instruments=instruments,
        contract_size=contract_size,
        leverage=account.leverage if leverage is None else leverage,
        fee_rate=fee_rate,
        qty_step=qty_step,
        lot_size=lot_size,
        slot_size=slot_size,
        min_qty=min_qty,
        min_notional=min_notional,
        account=account,
        execution=execution,
        use_funding=use_funding,
    )
    engine = NativeEventBackend(
        NativeEventConfig(
            account=account,
            execution=execution,
            fee_rate=fee_rate,
            use_funding=use_funding,
            report_level=profile.value,
            audit_sink=audit_sink,
            audit_sink_path=audit_sink_path,
            native_backend=plan.backend.value,
            backend_policy=plan.backend_policy,
            execution_contract=clock,
            diagnostics=diagnostics,
        )
    )
    result = engine.run_order_commands(
        datetime_index=preparation.datetime_index,
        commands=preparation.effective_commands,
        closes=closes,
        highs=highs,
        lows=lows,
        opens=opens,
        _prepared_opens_arr=preparation.prepared.market.opens,
        funding_rate=funding_rate,
        contract_size=contract_size,
        leverage=leverage,
        fee_rate=fee_rate,
        symbols=list(symbol_values),
        market_arrays=preparation.legacy_market_arrays,
        compiled_commands=preparation.compiled_commands,
        # Quantity constraints were already applied once by preparation.
        instruments=None,
        qty_step=None,
        lot_size=None,
        slot_size=None,
        min_qty=None,
        min_notional=None,
        report_level=profile.value,
        audit_sink=audit_sink,
        audit_sink_path=audit_sink_path,
        execution_contract=clock,
        diagnostics_enabled=diagnostics,
    )
    result.metadata.update(
        {
            "execution_plan_v1": plan.to_dict(),
            "execution_plan_fingerprint": plan.plan_fingerprint,
            "output_projection_fingerprint": plan.projection_fingerprint,
            "prepared_run_keys_v1": asdict(preparation.prepared.keys),
            "preparation_diagnostics_v1": asdict(preparation.prepared.diagnostics),
            "quantity_constraints": {
                symbol: {
                    "qty_step": float(preparation.prepared.instruments.table.qty_step[col]),
                    "lot_size": float(preparation.prepared.instruments.table.qty_step[col]),
                    "min_qty": float(preparation.prepared.instruments.table.min_qty[col]),
                    "min_notional": float(preparation.prepared.instruments.table.min_notional[col]),
                }
                for col, symbol in enumerate(symbol_values)
            },
            "quantity_preflight": dict(preparation.quantity_preflight),
            "p1_execution_route": "plan_prepare_legacy_public_adapter_v1",
            "native_event_backend_requested": requested_backend,
            "native_event_backend_resolved": plan.backend.value,
            "native_event_promotion_v1": {
                "backend_policy": plan.backend_policy,
                "reason": plan.promotion_reason,
                "table_version": plan.promotion_table_version,
                "rule_id": plan.promotion_rule_id,
                "minimum_bars": plan.promotion_minimum_bars,
                "fingerprint": plan.promotion_fingerprint,
            },
        }
    )
    return NativeEventLifecycleOutcome(result=result, engine=engine, preparation=preparation)


__all__ = ["NativeEventLifecycleOutcome", "execute_native_event_lifecycle"]

"""Resolve one immutable execution plan before market preparation."""

from __future__ import annotations

from typing import Callable, Mapping

from .capabilities import CapabilitySnapshot, load_rust_capability_snapshot, python_capability_snapshot
from .models import (
    BackendDecisionReason,
    BackendKind,
    BacktestRequest,
    ExecutionPlan,
    RunProfile,
    TraceRequirements,
)
from .output import compile_output_requirements
from ..core.native_event_promotion import (
    NativePromotionContext,
    NativePromotionDecision,
    NativePromotionError,
    native_event_workload_id,
    resolve_native_event_promotion,
)


class PlanningError(RuntimeError):
    """Raised before expensive preparation when a request cannot be planned."""


_REPORT_ALIASES = {
    "full": RunProfile.AUDIT,
    "debug": RunProfile.AUDIT,
    "research": RunProfile.STANDARD,
    "optimizer": RunProfile.SCORE,
    "scoring": RunProfile.SCORE,
}


def _resolved_profile(request: BacktestRequest) -> RunProfile:
    report = str(request.report_level).lower().strip()
    return _REPORT_ALIASES.get(report, RunProfile(report)) if report not in _REPORT_ALIASES else _REPORT_ALIASES[report]


def _promotion_context(
    request: BacktestRequest,
    *,
    profile: RunProfile,
    capability: CapabilitySnapshot | None = None,
) -> NativePromotionContext:
    """Translate immutable planner input into the pure promotion contract."""

    return NativePromotionContext(
        requested_backend=str(request.requested_backend or "auto"),
        backend_policy=request.backend_policy,
        workload_id=native_event_workload_id(
            workload=request.workload.value,
            strategy_mode=request.strategy_mode.value,
        ),
        execution_contract_id=request.execution_contract_id,
        strategy_mode=request.strategy_mode.value,
        profile=profile.value,
        account_model=request.account_model.value,
        bars=int(request.bars),
        symbol_count=len(request.symbols),
        required_capabilities=tuple(request.required_capabilities),
        native_available=None if capability is None else capability.available,
        native_compatible=None if capability is None else capability.compatible,
        native_executable=None if capability is None else capability.executable,
        native_capabilities=(
            ()
            if capability is None
            else tuple(name for name, enabled in capability.capabilities if enabled)
        ),
        native_reason=None if capability is None else capability.reason,
        native_version=None if capability is None else capability.version,
        native_api_version=None if capability is None else capability.api_version,
        native_capability_fingerprint=None if capability is None else capability.fingerprint,
    )


def _backend_decision_reason(decision: NativePromotionDecision) -> BackendDecisionReason:
    """Map stable promotion codes to the existing planner enum surface."""

    try:
        return BackendDecisionReason(decision.reason)
    except ValueError:
        return BackendDecisionReason.AUTO_PYTHON_RELEASE_POLICY


def resolve_execution_plan(
    request: BacktestRequest,
    *,
    rust_capability_loader: Callable[[], CapabilitySnapshot] = load_rust_capability_snapshot,
    environment: Mapping[str, str] | None = None,
) -> ExecutionPlan:
    profile = _resolved_profile(request)
    requested = str(request.requested_backend or "auto").lower().strip()
    try:
        decision = resolve_native_event_promotion(
            _promotion_context(request, profile=profile),
            environment=environment,
        )
        native_capability: CapabilitySnapshot | None = None
        if decision.native_probe_required:
            native_capability = rust_capability_loader()
            decision = resolve_native_event_promotion(
                _promotion_context(request, profile=profile, capability=native_capability),
                environment=environment,
            )
    except NativePromotionError as exc:
        raise PlanningError(str(exc)) from exc

    if requested == "rust" and decision.resolved_backend != "rust":
        detail = decision.native_reason or decision.reason
        if decision.reason == "native_missing_capabilities":
            available = set(() if native_capability is None else (name for name, enabled in native_capability.capabilities if enabled))
            missing = sorted(set(request.required_capabilities) - available)
            if missing:
                detail = "native_backend='rust' lacks capabilities: " + ", ".join(missing)
        raise PlanningError("native_backend='rust' failed before preparation: " + str(detail))

    capability = native_capability if decision.resolved_backend == "rust" and native_capability is not None else python_capability_snapshot()
    backend = BackendKind.RUST if decision.resolved_backend == "rust" else BackendKind.PYTHON
    reason = _backend_decision_reason(decision)

    output = compile_output_requirements(
        profile=profile,
        public_result=request.public_result,
        declared_strategy_requirements=request.declared_strategy_requirements,
    )
    trace = TraceRequirements(
        enabled=bool(request.trace_requested or profile is RunProfile.AUDIT),
        materialize=bool(profile is RunProfile.AUDIT and request.audit_sink == "memory"),
        fingerprint=bool(request.trace_requested or profile is RunProfile.AUDIT),
        stream=bool(profile is RunProfile.AUDIT and request.audit_sink not in {"none", "memory"}),
    )
    plan = ExecutionPlan(
        contract_id=request.execution_contract_id,
        workload=request.workload,
        backend=backend,
        backend_reason=reason,
        strategy_mode=request.strategy_mode,
        profile=profile,
        output=output,
        trace=trace,
        numeric=request.numeric,
        market_layout=request.market_layout,
        account_model=request.account_model,
        capability_fingerprint=capability.fingerprint,
        request_fingerprint=request.fingerprint,
        projection_fingerprint=output.fingerprint,
        backend_policy=decision.backend_policy,
        promotion_reason=decision.reason,
        promotion_table_version=decision.promotion_table_version,
        promotion_rule_id=decision.matched_rule_id,
        promotion_minimum_bars=decision.minimum_bars,
        promotion_fingerprint=decision.fingerprint,
    )
    return plan.with_fingerprint()


__all__ = ["PlanningError", "resolve_execution_plan"]

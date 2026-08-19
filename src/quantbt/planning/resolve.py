"""Resolve one immutable execution plan before market preparation."""

from __future__ import annotations

from typing import Callable

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


def resolve_execution_plan(
    request: BacktestRequest,
    *,
    rust_capability_loader: Callable[[], CapabilitySnapshot] = load_rust_capability_snapshot,
) -> ExecutionPlan:
    profile = _resolved_profile(request)
    requested = str(request.requested_backend or "auto").lower().strip()

    if requested == "rust":
        capability = rust_capability_loader()
        if not (capability.available and capability.compatible and capability.executable):
            raise PlanningError(
                "native_backend='rust' failed before preparation: "
                + str(capability.reason or "native extension is unavailable or incompatible")
            )
        if not capability.supports(request.required_capabilities):
            missing = sorted(set(request.required_capabilities) - {name for name, value in capability.capabilities if value})
            raise PlanningError("native_backend='rust' lacks capabilities: " + ", ".join(missing))
        backend = BackendKind.RUST
        reason = BackendDecisionReason.EXPLICIT_RUST_CERTIFIED
    elif requested in {"python", "replay_certified"}:
        capability = python_capability_snapshot()
        backend = BackendKind.PYTHON
        reason = (
            BackendDecisionReason.REPLAY_CERTIFIED_COMPATIBILITY
            if requested == "replay_certified"
            else BackendDecisionReason.EXPLICIT_PYTHON
        )
    elif requested == "auto":
        capability = python_capability_snapshot()
        backend = BackendKind.PYTHON
        reason = BackendDecisionReason.AUTO_PYTHON_RELEASE_POLICY
    else:
        raise PlanningError("requested_backend must be auto, python, replay_certified, or rust")

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
    )
    return plan.with_fingerprint()


__all__ = ["PlanningError", "resolve_execution_plan"]

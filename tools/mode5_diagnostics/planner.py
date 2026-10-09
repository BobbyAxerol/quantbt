"""Compile a diagnostic union into the existing shared computation contract."""

from dataclasses import dataclass

from quantbt.core.performance_contracts import RequiredComputationPlanV1

# These are input requirements, not alternative implementations of metrics.
REQUIREMENTS = {
    "score": ("score",),
    "return": ("timestamps", "equity"),
    "psr": ("timestamps", "equity"),
    "hac": ("timestamps", "equity"),
    "account_tail": ("timestamps", "equity"),
    "campaign_tail": ("campaign_pnl",),
    "accounting": ("timestamps", "equity", "positions", "fees", "funding", "margin", "turnover"),
    "fill_audit": ("fill_time", "fill_qty", "fill_price", "fill_fee"),
}


@dataclass(frozen=True)
class DiagnosticNeeds:
    objective: tuple[str, ...] = ("score",)
    constraints: tuple[str, ...] = ()
    axes: tuple[str, ...] = ()
    batteries: tuple[str, ...] = ()
    audit: tuple[str, ...] = ()


def compile_plan(needs, *, route_id, backend):
    selected = tuple(dict.fromkeys(metric for group in (
        needs.objective, needs.constraints, needs.axes, needs.batteries, needs.audit
    ) for metric in group))
    if not selected or any(metric not in REQUIREMENTS for metric in selected):
        raise ValueError("unknown or empty diagnostic requirement; declare inputs explicitly")
    streams = tuple(sorted({stream for metric in selected for stream in REQUIREMENTS[metric]}))
    rich = streams != ("score",)
    return RequiredComputationPlanV1(
        route_id=route_id, optimization_mode="mode_5_full_robust",
        optimization_schedule="diagnostic_fixed_panel_v1", scoring_backend=backend,
        financial_retention="compact" if rich else "score", research_retention="full_trial_ledger",
        required_observation_kinds=streams, required_intermediate_paths=streams,
        reducers=selected, output_sinks=("candidate_environment_panel", "trial_ledger"),
        requires_intermediate_checkpoints=rich, opaque_custom_metric=False,
        native_score_eligible=not rich,
        notes=("research-only; request union before simulation; no implicit reporting replay",))

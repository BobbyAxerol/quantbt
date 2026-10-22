"""Legacy Mode 5 defaults on the shared mode-independent planner."""
from quantbt.diagnostics.planner import DiagnosticNeeds, REQUIREMENTS
from quantbt.diagnostics.planner import compile_plan as _compile_plan


def compile_plan(needs, *, route_id, backend):
    return _compile_plan(needs, route_id=route_id, backend=backend,
        optimization_mode="mode_5_full_robust")

"""Public synthetic evidence, not strategy presets or market performance."""
from tools.mode5_diagnostics.access import AccessPolicy, AccessWitness
from tools.mode5_diagnostics.identity import AnalysisKey, digest
from tools.mode5_selection.contracts import Candidate, Channel, Formula, Panel, SelectionPlan
from tools.mode5_statistics.contracts import MetricValue
from tools.mode5_statistics.tails import FrozenReference


def panel(rows=((.1, .2), (.2, .1)), *, channel=None, weights=None, benchmark=None, ids=None):
    channel = channel or Channel("ECONOMIC_UTILITY_V1", "mode5.utility.net_v1", "decimal_return")
    n = len(rows[0])
    reference = FrozenReference("synthetic-dev-reference", tuple(f"e{i}" for i in range(n)),
        tuple(benchmark or [.5]*n), tuple(weights or [1.]*n), channel.identity, "revision-1")
    access = AccessPolicy("synthetic-selection", ("synthetic",), ("synthetic-panel",), 10, "selection")
    candidates = []
    for i, row in enumerate(rows):
        candidates.append(Candidate(ids[i] if ids else f"c{i}", digest({"synthetic_point": i}),
            tuple(MetricValue(channel.metric_contract, channel.unit, 100, x, "VALID" if x is not None else "UNDEFINED",
                              None if x is not None else "missing environment") for x in row),
            tuple(AnalysisKey(f"execution-{i}", f"env-{j}", "statistics-v1", reference.identity) for j in range(n)),
            tuple(AccessWitness("synthetic-panel", "synthetic", 0, 5, 5) for _ in range(n)),
            "synthetic-qualified-gates-v1", True, True, True, True, True, 0., activity_penalty_unit=channel.unit))
    return Panel("synthetic-economics-schema-scope", "analysis-v1", channel, reference,
                 tuple(candidates), access, "qmc", "synthetic-qmc-provenance")


def plan(p, version="environment_floor_mean_v1", coefficients=(("mean", .25),),
         selector="full_dro_cvar", **kwargs):
    return SelectionPlan("synthetic-plan", p.context_id, "stage-1", Formula(version, p.channel, coefficients),
                         p.reference.identity, selector, 0., access_identity=p.access.identity, **kwargs)

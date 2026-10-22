"""Bounded panel fixture from tests/mode5/selection_fixtures, canonical imports.

Staged as selection_fixtures.py for the retained winner-record fixture. This is
literal synthetic evidence, not a sampler, account engine or financial oracle.
"""

from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.mode5.diagnostics.identity import AnalysisKey, digest
from quantbt.mode5.selection.contracts import Candidate, Channel, Formula, Panel, SelectionPlan
from quantbt.mode5.statistics.contracts import MetricValue
from quantbt.mode5.statistics.tails import FrozenReference


def panel(rows=((.1, .2), (.2, .1)), *, channel=None, weights=None, benchmark=None, ids=None):
    channel = channel or Channel("ECONOMIC_UTILITY_V1", "mode5.utility.net_v1", "decimal_return")
    size = len(rows[0])
    reference = FrozenReference("synthetic-dev-reference", tuple(f"e{i}" for i in range(size)),
        tuple(benchmark or [.5] * size), tuple(weights or [1.] * size), channel.identity, "revision-1")
    access = AccessPolicy("synthetic-selection", ("synthetic",), ("synthetic-panel",), 10, "selection")
    candidates = tuple(Candidate(ids[i] if ids else f"c{i}", digest({"synthetic_point": i}),
        tuple(MetricValue(channel.metric_contract, channel.unit, 100, value,
            "VALID" if value is not None else "UNDEFINED",
            None if value is not None else "missing environment") for value in row),
        tuple(AnalysisKey(f"execution-{i}", f"env-{j}", "statistics-v1", reference.identity)
              for j in range(size)),
        tuple(AccessWitness("synthetic-panel", "synthetic", 0, 5, 5) for _ in range(size)),
        "synthetic-qualified-gates-v1", True, True, True, True, True, 0.,
        activity_penalty_unit=channel.unit) for i, row in enumerate(rows))
    return Panel("synthetic-economics-schema-scope", "analysis-v1", channel, reference,
                 candidates, access, "qmc", "synthetic-qmc-provenance")


def plan(value, version="environment_floor_mean_v1", coefficients=(("mean", .25),),
         selector="full_dro_cvar", **kwargs):
    return SelectionPlan("synthetic-plan", value.context_id, "stage-1",
        Formula(version, value.channel, coefficients), value.reference.identity, selector, 0.,
        access_identity=value.access.identity, **kwargs)

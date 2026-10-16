"""Whole-work admission from measured evaluations, not kernel throughput."""

from dataclasses import asdict, dataclass
from math import isfinite
from numbers import Real


PRIMARY_ALPHAS = ("A-SC", "A-HMA", "A-HASH", "A-VWAP")
REFERENCE_ALPHA = "A-RSI"


@dataclass(frozen=True)
class ControlTiming:
    alpha: str
    role: str
    elapsed_seconds: float
    peak_rss_mib: float
    includes_preparation: bool = True
    execution_identity: str = ""

    def __post_init__(self):
        if self.alpha not in (*PRIMARY_ALPHAS, REFERENCE_ALPHA):
            raise ValueError("registered alpha required")
        if self.role not in {"is", "forward", "final"}:
            raise ValueError("explicit financial role required")
        if (self.includes_preparation is not True
                or not isinstance(self.execution_identity, str) or not self.execution_identity.strip()
                or isinstance(self.elapsed_seconds, bool) or not isinstance(self.elapsed_seconds, Real)
                or not isfinite(self.elapsed_seconds) or self.elapsed_seconds <= 0
                or isinstance(self.peak_rss_mib, bool) or not isinstance(self.peak_rss_mib, Real)
                or not isfinite(self.peak_rss_mib) or self.peak_rss_mib <= 0):
            raise ValueError("finite end-to-end timing and execution identity required")


def proposal_budget():
    primary = len(PRIMARY_ALPHAS) * 19 * 2 * 128
    reference = 19 * 128
    return dict(primary=primary, reference=reference, total=primary + reference)


def forecast(timings, *, workers=4, queue_cap_seconds=5400., overhead_fraction=.25,
             observer_candidates=36, setup_seconds=0.):
    """Conservative fixed-work estimate using observed maxima in each role.

    The partial forecast counts only measured roles and ideal worker sharing.
    Its per-evaluation costs are observed maxima, so it is NOT a mathematical
    lower bound on future adaptive work. A partial forecast exceeding the cap
    rejects conservative admission, not the physical possibility of a faster
    future run. PASS additionally needs all roles and resource admission.
    """
    rows = tuple(timings)
    if (not rows or any(not isinstance(row, ControlTiming) for row in rows)
            or type(workers) is not int or not 1 <= workers <= 4
            or not isfinite(queue_cap_seconds) or queue_cap_seconds <= 0
            or not isfinite(overhead_fraction) or overhead_fraction < 0
            or type(observer_candidates) is not int or observer_candidates < 36
            or not isfinite(setup_seconds) or setup_seconds < 0):
        raise ValueError("valid controls and prospectively bounded resources required")
    costs, missing = {}, []
    for alpha in (*PRIMARY_ALPHAS, REFERENCE_ALPHA):
        measured = {}
        for role in ("is", "forward", "final"):
            values = [r.elapsed_seconds for r in rows if r.alpha == alpha and r.role == role]
            measured[role] = max(values) if values else None
            if not values:
                missing.append(f"{alpha}:{role}")
        streams = 1 if alpha == REFERENCE_ALPHA else 2
        policies = 2 if alpha == REFERENCE_ALPHA else 8
        search = None if measured["is"] is None else 19 * streams * 128 * measured["is"]
        # Each selector retains its own anchor-first 16-member panel. The two
        # panels can differ; only their physical financial-query union dedups.
        panel_budget = 18 if alpha == REFERENCE_ALPHA else observer_candidates
        observer = (None if measured["forward"] is None else
                    19 * streams * panel_budget * measured["forward"])
        final = None if measured["final"] is None else policies * measured["final"]
        costs[alpha] = dict(measured_maxima=measured, search_worker_seconds=search,
                            observer_worker_seconds=observer, final_worker_seconds=final,
                            observer_candidates_per_pool=panel_budget)
    known_search = sum(c["search_worker_seconds"] or 0. for c in costs.values())
    partial_search_wall = known_search / workers
    known_total = sum(sum(c[key] or 0. for key in
                    ("search_worker_seconds", "observer_worker_seconds", "final_worker_seconds"))
                    for c in costs.values())
    estimated_wall = setup_seconds + known_total * (1. + overhead_fraction) / workers
    if partial_search_wall > queue_cap_seconds:
        status = "REJECT_PARTIAL_SEARCH_FORECAST_EXCEEDS_CAP"
    elif missing:
        status = "NOT_ADMITTED_MISSING_WHOLE_WORK_MEASUREMENTS"
    elif estimated_wall > queue_cap_seconds:
        status = "REJECT_WHOLE_WORK_FORECAST_EXCEEDS_CAP"
    else:
        status = "TIMING_ADMITTED_RESOURCE_CHECK_STILL_REQUIRED"
    return dict(schema="mode4.quarterly.timing-admission.v1", status=status,
        measurements=[asdict(row) for row in rows], proposal_slots=proposal_budget(),
        workers=workers, queue_cap_seconds=queue_cap_seconds, costs=costs,
        partial_search_wall_seconds=partial_search_wall,
        estimated_whole_work_wall_seconds=estimated_wall, missing=missing,
        setup_seconds=setup_seconds, overhead_fraction=overhead_fraction,
        observer_candidates_per_pool=observer_candidates, optimizer_started=False,
        work_units="ELAPSED_WORKER_SECONDS_NOT_MEASURED_CPU_SECONDS",
        timing_admitted=status == "TIMING_ADMITTED_RESOURCE_CHECK_STILL_REQUIRED",
        launch_allowed=False,
        interpretation="OBSERVED_MAXIMUM_CONDITIONAL_MODEL_NOT_HARD_LOWER_BOUND_P95_OR_ETA")

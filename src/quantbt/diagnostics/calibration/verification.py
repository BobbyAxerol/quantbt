"""Reuse canonical selection/sampler descriptions; never ask, rank or execute."""
from types import SimpleNamespace

from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.selection.contracts import Channel, Formula, SelectionPlan
from quantbt.mode5.selection.pareto import ParetoPreference
from quantbt.mode5.statistics.tails import FrozenReference
from quantbt.optimization import SamplerConfig
from quantbt.optimization.wfo_study import WfoSamplerStudy

from .worksheet import selection_access


def expected_selection(pack):
    d = pack.record.data
    recipe, b = d["plan"]["recipe"], d["binding"]
    obj, s = recipe["objective"], b["selection"]
    reference = FrozenReference(**{**b["reference"],
        **{k: tuple(b["reference"][k]) for k in ("environment_ids", "values", "weights")}})
    preference = ParetoPreference(**s["pareto_preference"]) if s["pareto_preference"] else None
    formula = Formula(obj["version"], Channel(**obj["channel"]), tuple(obj["coefficients"].items()))
    return SelectionPlan(d["plan_id"], digest(d["worksheet"]["context"]), "formal_search_v1",
        formula, reference.identity, s["requested_selector"], s["minimum_improvement"],
        incumbent_id=digest(s["incumbent_params"]) if s["incumbent_params"] is not None else None,
        local_reference_id=s["local_reference_id"], local_reference_scale=s["local_reference_scale"],
        pareto_preference_identity=preference.identity if preference else None,
        access_identity=selection_access(recipe["reuse"]["selection_policy"]).identity)


def policy_mismatches(pack, metadata):
    d = pack.record.data
    recipe, b = d["plan"]["recipe"], d["binding"]
    sampler, decision = metadata["sampler"], metadata.get("decision")
    mismatches = []
    config = SamplerConfig(**b["sampler"])
    # Reuse the shared telemetry owner, including conditional Sobol's category
    # seed/settings. A fresh local delegate draws no candidates and asks no trial.
    import pandas as pd
    ranges = {s["name"]: recipe["domain"]["ranges"][s["name"]]
              for s in b["continuous"]["geometry"]["parameters"]}
    bridge = WfoSamplerStudy(config, ranges, seed=recipe["sampler"]["seeds"][0],
        budget=d["plan"]["search_budget"],
        cutoff=pd.Timestamp(selection_access(recipe["reuse"]["selection_policy"]).cutoff_ns, tz="UTC"),
        strategy_identity=d["worksheet"]["context"]["alpha"], stage="is_search")
    bridge.sampler(result_constraints=False)
    expected = bridge.metadata(SimpleNamespace(get_trials=lambda deepcopy=False: []))
    for key in ("recipe", "seed", "kwargs", "constraint_mode", "mixed_space_policy"):
        if sampler.get(key) != expected.get(key):
            mismatches.append("actual sampler " + key + " differs from resolved shared configuration")
    rows = sampler["rows"]
    starts = b["warm_start"]
    from quantbt.mode5.continuous_binding import restore_geometry
    geometry = restore_geometry(b["continuous"]["geometry"])
    for i, row in enumerate(rows):
        if (row.get("source") == "warm_start") != (i < len(starts)):
            mismatches.append("actual initialization source/order differs from declared warm starts")
            break
        if i < len(starts):
            try:
                expected_point = geometry.resolve(starts[i]["params"]).params
                same = (geometry.resolve(row["requested_params"]).params == expected_point
                        and row.get("effective_params") == expected_point)
            except (ValueError, KeyError, TypeError):
                same = False
            if not same:
                mismatches.append("actual warm-start effective coordinates differ from declared initialization")
    if sampler.get("warm_start_attempts") != min(len(rows), len(starts)):
        mismatches.append("actual warm-start count differs from initialization")
    if (metadata.get("optimizer_schedule") != recipe["sampler"]["schedule"]
            or metadata.get("batch_size") != b["batch_size"]):
        mismatches.append("actual optimizer schedule/batch differs from compiled plan")
    if metadata.get("eligibility_policy") != b["continuous"].get("eligibility_policy"):
        mismatches.append("actual eligibility policy differs from compiled binding")
    if decision is not None:
        expected_plan = expected_selection(pack)
        if (decision.get("plan_identity") != expected_plan.identity
                or decision.get("formula_identity") != expected_plan.formula.identity
                or decision.get("formula_version") != expected_plan.formula.version
                or decision.get("formula_coefficients") != [list(v) for v in expected_plan.formula.coefficients]
                or decision.get("minimum_improvement") != b["selection"]["minimum_improvement"]
                or decision.get("reference") != b["reference"]
                or decision.get("requested_selector") != b["selection"]["requested_selector"]
                or decision.get("resolved_selector") != recipe["selector"]["id"]):
            mismatches.append("actual selection plan/reference/incumbent policy differs from frozen recipe")
    return mismatches

"""Describe actual work and observable shared sampler dispatch, not winner tables."""
import math
from tools.mode5_diagnostics.identity import digest


def audit_sampler(records, *, recipe, seed, proposal_budget, observed_relative,
                  observed_independent, objective_id, economic_contract):
    if (not recipe or type(seed) is not int or seed<0 or type(proposal_budget) is not int or proposal_budget<1
            or len(records)!=proposal_budget or not objective_id or not economic_contract):
        raise ValueError("complete registered trial roster and work identity required")
    ids=[r["trial_id"] for r in records]
    if len(set(ids))!=len(ids):
        raise ValueError("every attempted trial has one record")
    for row in records:
        if row["status"] not in {"COMPLETE","FAIL","PRUNED","CANCELLED"}:
            raise ValueError("actual attempt status required")
        for name in ("actual_execution_calls","visited_bars"):
            if type(row[name]) is not int or row[name]<0:
                raise ValueError("integral actual work required including replay passes")
        if not row.get("effective_digest") or not row.get("evidence_ref"):
            raise ValueError("effective geometry and retained attempt required")
        if row["status"]!="COMPLETE" and row.get("objective") is not None:
            raise ValueError("failed runtime is not an adverse economic observation")
        if row["status"]=="COMPLETE" and (isinstance(row.get("objective"),bool) or not isinstance(row.get("objective"),(int,float))
                or not math.isfinite(row["objective"])):
            raise ValueError("complete objective requires a measured finite scalar")
    complete=[r for r in records if r["status"]=="COMPLETE"]
    unique={r["effective_digest"] for r in complete}
    relative=dict(observed_relative)
    return dict(recipe=recipe,seed=seed,proposal_budget=proposal_budget,all_trials=tuple(dict(r) for r in records),
        objective_id=objective_id,economic_contract=economic_contract,
        completed=len(complete),failed=len(records)-len(complete),unique_effective=len(unique),
        duplicate_completed=len(complete)-len(unique),
        actual_execution_calls=sum(r["actual_execution_calls"] for r in records),
        visited_bars=sum(r["visited_bars"] for r in records),
        actual_relative_trials=sum(bool(v) for v in relative.values()),relative_samples=relative,
        independent_samples=dict(observed_independent),
        resolved_recipe="ALL_INDEPENDENT_OBSERVED" if not any(relative.values()) else "RELATIVE_WITH_REPORTED_INDEPENDENT_STARTUP_OR_FALLBACK",
        dispatch_interpretation="sample_independent is also primary parameter-wise TPE, not necessarily random fallback",
        trial_ledger_identity=digest(records),same_integer_seed_aligns_sequences=False,
        universal_superiority_claim=False)


def matched_sampler_work(audits):
    if len(audits)<2:
        raise ValueError("at least two actual sampler audits required")
    for key in ("proposal_budget","objective_id","economic_contract"):
        if len({a[key] for a in audits})!=1:
            raise ValueError("same objective/economics/proposal budget required")
    work=tuple((a["recipe"],a["seed"],a["unique_effective"],a["visited_bars"],a["actual_execution_calls"]) for a in audits)
    return dict(comparison="MATCHED_PROPOSAL_BUDGET",unique_work_matched=len({a["unique_effective"] for a in audits})==1,
        financial_work_matched=len({(a["visited_bars"],a["actual_execution_calls"]) for a in audits})==1,
        work=work,claim="wall-clock and fixed-work differences must be reported separately",
        no_winner_only_export=all(len(a["all_trials"])==a["proposal_budget"] for a in audits))

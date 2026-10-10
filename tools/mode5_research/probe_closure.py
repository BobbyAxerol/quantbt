"""Cold closure of the sealed 195+108 probe union, never account execution.

Recipes inherit reviewed development math. Completion custody is reconciled
before numerical work; validation never chooses the representative. Annual
rows are continuous-path attribution, not an annual-local estimator.
"""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
from time import perf_counter

from tools.mode5_research import jobs, probe_views as views, selector_checkpoint as prior


ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "upgrade/private/mode5_upgrade_v1/m5-11-1/attempt-01"
LANE = PARENT / "goal-step1/missing-analysis01"
ROLES = ("selection_probe", "local_validation")
TARGETS = {"rsi": [10, 49, 114], "sc": [33]}
LOCAL = dict(formula_id="local_downside_v1", gamma=1, reference_scale=1,
    activity_penalty=0, aggregate="whole_path", unit="decimal_return", quality_floor=0,
    risk_drawdown_max=.5, minimum_daily_count=1095,
    roles_used_for_selection=["selection_probe"], validation_access="post_decision_only",
    tie_break="candidate_id_lexicographic_v1", coverage="sealed_original_owner_schema_and_covariance_union",
    covariance="sealed supported regularized proposals, not a Hessian or plateau volume",
    annual_local="NOT_AUTHORIZED", full_128_local="NOT_EVALUABLE")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def recipe_identity(local, utility):
    require(local == LOCAL and utility == views.UTILITY, "unapproved reducer/gates/utility recipe")
    return prior.digest(dict(local=local, annual_utility=utility))


def union_scope(base, union):
    """Join by exact request identity, never replace a preserved request design ID."""
    require(union["status"] == "PASS" and union["fit_requests_closed"] == 4 and
            [(f["alpha"], f["original_index"]) for f in union["fits"]] ==
            [(key, i) for key, indices in TARGETS.items() for i in indices] and
            all(f["supported"] for f in union["fits"]), "four supported fits required")
    old = {prior.digest(e["request"]): e for e in base["entries"]}
    require(len(old) == len(base["entries"]) == 195, "195 unique original requests required")
    entries, preserved, extra, hashes = [], [], [], set()
    for execution in union["executions"]:
        request = execution["request"]
        sha = prior.digest(request)
        require(sha == execution["request_sha256"] and sha not in hashes and
                request["design_id"] == execution["request_design_id"] and
                request["role"] == execution["role"] and request["candidate_id"] == execution["candidate_id"],
                "duplicate or changed union request identity")
        hashes.add(sha)
        if execution["source"] == "PRESERVED_SEALED_SCHEMA_REQUEST":
            require(sha in old and execution["original_schema_execution"]["request"] == old[sha]["request"],
                    "preserved schema request changed")
            cell_id = old[sha]["cell_id"]
            preserved.append(sha)
        else:
            require(execution["source"] == "NEW_COVARIANCE_ROLE_REQUEST_NO_ACCOUNT_EVIDENCE" and sha not in old and
                    request["probe_direction"].startswith("covariance:") and
                    request["design_id"] == execution["union_design_id"], "unexpected overlay request")
            cell_id = None  # Bound later to the adapter's immutable jobs registration.
            extra.append(sha)
        entries.append(dict(request=request, request_sha256=sha, cell_id=cell_id, execution_index=execution["index"],
            alpha=execution["alpha"], union_design_id=execution["union_design_id"], source=execution["source"]))
    require(set(preserved) == set(old) and len(preserved) == 195 and len(extra) == 108 and len(entries) == 303 and
            [e["execution_index"] for e in entries] == list(range(303)), "all ordered 303 union requests required")
    neighborhoods = {key: [n for n in union["neighborhoods"] if n["alpha"] == key] for key in TARGETS}
    by_index = {e["execution_index"]: e for e in entries}
    used = []
    for key, indices in TARGETS.items():
        require([(n["original_index"], n["role"]) for n in neighborhoods[key]] ==
                [(i, role) for i in indices for role in ROLES], "original center/role order differs")
        for n in neighborhoods[key]:
            require(n["covariance_status"] == "REGULARIZED_PROPOSALS_NOT_HESSIAN", "unsupported covariance ledger")
            for row in n["rows"]:
                if row["status"] != "READY":
                    require(row["execution_index"] is None, "alias/infeasible rows cannot count as executions")
                    continue
                e = by_index[row["execution_index"]]
                require(e["alpha"] == key and e["union_design_id"] == n["neighborhood_id"] and
                        e["request"]["parent_panel_index"] == n["original_index"] and e["request"]["role"] == n["role"] and
                        e["request"]["proposal_row"] == row["row_id"] and e["request"]["params"] == row["effective"] and
                        e["request"]["candidate_id"] == row["candidate_id"] and
                        e["request"]["probe_direction"] == row["direction"], "union ledger/request mismatch")
                used.append(row["execution_index"])
    require(sorted(used) == list(range(303)), "each exact union request must occur once in READY ledgers")
    return entries, neighborhoods


def register(parent=PARENT, lane=LANE, attempt="registration-union-01.json"):
    parent, lane = jobs._safe(parent), jobs._safe(lane)
    require(lane == parent / "goal-step1/missing-analysis01", "exact private analysis lane required")
    before = jobs._preflight(parent, jobs.Budget(scratch_bytes=32*jobs.MIB, retained_bytes=64*jobs.MIB))
    base_pin = prior.pin(lane / "registration.json")
    registration = views.sealed_json(base_pin)
    software = registration["software"]
    snapshot = prior.pin(lane / "source-initial/probe_closure.py")
    require(snapshot["sha256"] == next(p["sha256"] for p in software if p["path"] == str(Path(__file__).resolve())),
            "initial recipe source snapshot differs")
    jobs.verify_pins([p for p in software if p["path"] != str(Path(__file__).resolve())])
    union_pin = prior.pin(parent / "goal-step1/cov-fit01/union_01.json")
    integration_pin = prior.pin(Path(union_pin["path"]).with_name("integration_01.json"))
    integration, union = views.sealed_json(integration_pin), views.sealed_json(union_pin)
    require(integration["seals"]["union_01.json"] == union_pin["sha256"], "integration union seal differs")
    entries, neighborhoods = union_scope(registration, union)
    software = [prior.pin(p["path"]) for p in software]
    registration.update(schema="mode5.probe_union_closure.v1", created_at=prior.now(),
        status="REGISTERED_AWAITING_BASE_AND_OVERLAY_COMPLETE", entries=entries,
        base_recipe_registration=base_pin, initial_source_snapshot=snapshot, union=union_pin, union_integration=integration_pin,
        local_recipe=LOCAL, recipe_id=recipe_identity(LOCAL, views.UTILITY), neighborhoods=neighborhoods,
        request_roster_sha256=prior.digest([e["request"] for e in entries]), software=software,
        outcome_timing="CURRENT_READ_DEVELOPMENT; two tranches already exposed to main; "
                       "existing frozen math only, not prospective preregistration or clean OOS",
        read_rights="no newly completed financial values inspected during recipe registration",
        expected_annual_rows=909, expected_whole_path_rows=303, covariance_union_claim=True,
        budget=dict(scratch_bytes=32*jobs.MIB, retained_bytes=64*jobs.MIB, reserve_bytes=5*jobs.GIB),
        cleanup_inventory=dict(scratch_paths=[str(lane / "scratch-test-01")],
            delete_only=[str(lane / "scratch-test-01")], preserve=["all finance/source/data/receipts/environments"]),
        resources_before=before, financial_executions=0, builds=0)
    path = lane / jobs._name(attempt)
    validate_registration(registration)
    jobs._seal(path, registration)
    return path


def validate_registration(registration):
    require(recipe_identity(registration["local_recipe"], registration["annual_utility"]) == registration["recipe_id"],
            "recipe seal differs")
    jobs.verify_pins(registration["software"] + [registration["financial_registration"],
        registration["financial_handoff"], registration["request_bundle"], registration["controller_registration"],
        registration["original_step_registration"], *registration["original_panel_rows"].values(),
        *registration["spec_pins"], registration["base_recipe_registration"], registration["initial_source_snapshot"],
        registration["union"], registration["union_integration"]])
    base, union = views.sealed_json(registration["base_recipe_registration"]), views.sealed_json(registration["union"])
    entries, neighborhoods = union_scope(base, union)
    require(entries == registration["entries"] and neighborhoods == registration["neighborhoods"] and
            prior.digest([e["request"] for e in entries]) == registration["request_roster_sha256"] and
            registration["expected_whole_path_rows"] == 303 and registration["expected_annual_rows"] == 909,
            "closure scope differs from sealed union")
    for key in ("objectives", "parent_roster", "geometries", "original_reporting_contract", "original_panel_rows"):
        require(registration[key] == base[key], "original reporting/local context changed")


def reconcile(registration, completion_pin, overlay_pin):
    """Reuse the original checkpoint verifier; no filesystem guesses or survivor subset."""
    validate_registration(registration)
    controller = views.sealed_json(completion_pin)
    require(controller["status"] == "COMPLETE_ACCOUNT_WORK_NOT_SCIENCE_GATE" and not controller["error"] and
            not controller["interrupted_signals"], "all controller lanes must finish without faults")
    planned = views.sealed_json(registration["controller_registration"])
    require(controller["registered_lanes"] == len(planned["lanes"]) == len(controller["completed_lanes"]),
            "missing or duplicate completed lanes")
    overlay = views.sealed_json(overlay_pin)
    require(overlay["schema"] == "mode5.probe_overlay_completion.v1" and overlay["store"] == registration["store"],
            "sealed overlay completion manifest in the same global store required")
    lanes = []
    for lane, pin in zip(planned["lanes"], controller["completed_lanes"], strict=True):
        require(Path(pin["path"]) == Path(lane["lane"]) / "completion.json", "controller lane order differs")
        lanes.append((lane["registration"], pin, lane["candidates"], "PRESERVED_SEALED_SCHEMA_REQUEST"))
    for lane in overlay["lanes"]:
        require(Path(lane["completion"]["path"]) == Path(lane["registration"]["path"]).with_name("completion.json"),
                "overlay registration/completion lineage differs")
        lanes.append((lane["registration"], lane["completion"], None, "NEW_COVARIANCE_ROLE_REQUEST_NO_ACCOUNT_EVIDENCE"))
    require(len({pin["path"] for _, pin, _, _ in lanes}) == len(lanes), "duplicate completion lane")
    expected = {e["request_sha256"]: e for e in registration["entries"]}
    seen, inputs = set(), {}
    cell_ids = set()
    for custody_pin, pin, count, source in lanes:
        result = views.sealed_json(pin)
        custody = views.sealed_json(custody_pin)
        require(custody["store"] == registration["store"], "separate financial stores cannot certify the union")
        count = len(custody["candidates"]) if count is None else count
        require(result["status"] == "COMPLETE" and result["all_owned_children_reaped"] and
                not result["errors"] and len(result["records"]) == count == len(custody["candidates"]), "unqualified lane completion")
        records = {r["cell_id"]: r for r in result["records"]}
        require(len(records) == len(result["records"]) and set(records) == {c["cell_id"] for c in custody["candidates"]},
                "duplicate or unregistered lane candidate")
        for value in custody["candidates"]:
            candidate = jobs.Candidate.from_dict(value)
            cell_id = candidate.cell_id
            request = json.loads(candidate.request_json)
            sha = prior.digest(request)
            require(sha in expected and sha not in seen and cell_id not in cell_ids and expected[sha]["source"] == source and
                    request == expected[sha]["request"] and expected[sha]["cell_id"] in (None, cell_id),
                    "unexpected/repeated/changed request")
            record = records[cell_id]
            require(record["status"] in {"COMPLETE", "REUSED"}, "failed/censored cells cannot be dropped")
            path = (Path(record["checkpoint"]["path"]) if record["status"] == "REUSED" else
                    Path(record["log"]["path"]).parent / "checkpoint.json")
            require(path.parent.parent == Path(registration["store"]) / "cells" / cell_id,
                    "checkpoint outside registered global store")
            checkpoint_pin = prior.pin(path)  # Present input seal; not invented historical provenance.
            checkpoint = views.sealed_json(checkpoint_pin)
            receipt = views.sealed_json(checkpoint["receipt"])
            require((record == receipt if record["status"] == "COMPLETE" else
                     record["checkpoint"] == checkpoint_pin), "checkpoint lacks controller receipt lineage")
            reused = jobs._reuse(candidate, path.parent)
            passes = 2 if request["alpha"] == "A-RSI" else 1
            require(reused["exact_counts"] == dict(account_passes=passes, account_bars=passes*26280),
                    "completed original-owner bill differs")
            inputs[sha] = dict(cell_id=cell_id, request_sha256=sha, checkpoint=checkpoint_pin,
                                  exact_counts=reused["exact_counts"], output=checkpoint["output"])
            seen.add(sha)
            cell_ids.add(cell_id)
    require(seen == set(expected), "all exact base+overlay requests required, no survivor closure")
    ordered = [inputs[e["request_sha256"]] for e in registration["entries"]]
    return dict(status="PASS", schema="mode5.missing_probe_reconciliation.v1", controller_completion=completion_pin,
        overlay_completion_manifest=overlay_pin, custody_pins=[p for lane in lanes for p in lane[:2]],
        recipe_id=registration["recipe_id"], request_roster_sha256=registration["request_roster_sha256"], inputs=ordered,
        inherited_account_passes=sum(r["exact_counts"]["account_passes"] for r in ordered),
        inherited_account_bars=sum(r["exact_counts"]["account_bars"] for r in ordered), financial_executions=0)


def compare_local(registration, key, centers, evaluations):
    objective = registration["objectives"][key]
    neighborhoods = {(n["original_index"], n["role"]): n for n in registration["neighborhoods"][key]}
    require([c["panel_index"] for c in centers] == TARGETS[key] and len(neighborhoods) == 2*len(centers),
            "exact limited original center roster required")
    preferences = {k: LOCAL[k] for k in ("risk_drawdown_max", "minimum_daily_count")}
    selections, validations, overlaps = [], [], []

    def row(center, role):
        neighborhood = deepcopy(neighborhoods[center["panel_index"], role])
        require(neighborhood["center"] == center["center"] and neighborhood["parent_candidate_id"] == center["candidate_id"],
                "original center/union ledger identity differs")
        if center["metrics"]["economic_utility"] is None:
            return dict(candidate_id=center["candidate_id"], index=center["panel_index"], role=role,
                        eligible=False, score=None, evidence_complete=False, status="UNDEFINED_CENTER_RETAINED",
                        reasons=["CENTER_QUALITY_RISK_SUPPORT_FAIL"], coverage=neighborhood["coverage"])
        return prior.local_row(center, neighborhood, evaluations, preferences, objective)

    for center in centers:
        selections.append(row(center, ROLES[0]))
    chosen = prior.best(selections) if all(r["evidence_complete"] for r in selections) else None
    decision = dict(chosen_candidate=chosen, selection_input_sha256=prior.digest(selections),
                    status="SELECTED_LIMITED_UNION_ROSTER" if chosen else "NO_SELECTION" if
                    all(r["evidence_complete"] for r in selections) else "NOT_EVALUABLE")
    for center in centers:  # Validation is accessed only after the decision above.
        validations.append(row(center, ROLES[1]))
        require(neighborhoods[center["panel_index"], ROLES[0]]["seed"] !=
                neighborhoods[center["panel_index"], ROLES[1]]["seed"], "distinct role seeds required")
        role_sets = [{r["candidate_id"] for r in neighborhoods[center["panel_index"], role]["rows"]
                      if r["status"] == "READY"} for role in ROLES]
        overlaps.append(dict(candidate_id=center["candidate_id"], overlapping_effective=len(role_sets[0] & role_sets[1]),
            ready_selection=len(role_sets[0]), ready_validation=len(role_sets[1]),
            held_distinct=len(role_sets[1]-role_sets[0]), independent_overlaps=False, temporal_oos=False))
    return dict(**decision, formula_id=LOCAL["formula_id"], gamma=1, reference_scale=1,
        compared_candidate_ids=[c["candidate_id"] for c in centers], component_rows=selections,
        validation_post_decision=validations, overlap=overlaps, full_panel_local_status="NOT_EVALUABLE",
        annual_local_status="NOT_AUTHORIZED", covariance_union_status="SEALED_UNION_ACCOUNT_EVIDENCE_REQUIRED",
        claim="original whole-path utility; registered schema+covariance centers only, not whole128 or annual local")


def completed_cell(registration, entry, item):
    p = views.numeric_owner()
    import numpy as np
    checkpoint = views.sealed_json(item["checkpoint"])
    require(checkpoint["output"] == item["output"] and checkpoint["exact_counts"] == item["exact_counts"],
            "reconciled checkpoint output/count differs")
    candidate = jobs.Candidate.from_dict(checkpoint["candidate"])
    require(candidate.cell_id == item["cell_id"] and json.loads(candidate.request_json) == entry["request"],
            "checkpoint immutable candidate/request differs")
    jobs._reuse(candidate, Path(item["checkpoint"]["path"]).parent)
    pool = views.indexed(checkpoint["artifacts"])
    output = Path(item["output"])

    def load(name):
        return views.sealed_json(pool[str(output / name)])

    result, cell, request, access = load("result.json"), load("actual/cell.json"), entry["request"], load("actual/development_access.json")
    require(result["status"] == "PASS" and result["request"] == cell["request"] == request and
            load("actual/request.json") == request and result["accounting_qualification"] == load("accounting_qualification.json") and
            result["accounting_qualification"]["status"] == "PASS", "qualified exact account result required")
    require(not access["future_tape_opened"] and access["original_contract_preserved"] and
            not access["mutable_strategy_or_account_reused"] and access["allowed_stop"] == request["stop"],
            "development-only fresh account access required")
    require(cell["scored_bars"] == 26280 and cell["scored_days"] == 1095 and not cell["clean_oos"] and
            cell["actual_execution_calls"] == item["exact_counts"]["account_passes"] and
            cell["visited_bars"] == item["exact_counts"]["account_bars"], "actual resource/calendar bill differs")
    path_pin = pool[str(output / "actual/paths.npz")]
    require(path_pin == cell["path"], "original sealed path identity differs")
    with np.load(views.BytesIO(views.sealed_bytes(path_pin)), allow_pickle=False) as paths:
        arrays = {name: paths[name] for name in paths.files}
    start, stop = p._ns(request["start"]), p._ns(request["stop"])
    require(arrays["times_ns"].dtype == np.dtype("int64") and np.array_equal(
        arrays["times_ns"], np.arange(start, stop, p.HOUR_NS, dtype=np.int64)), "complete ordered account calendar required")
    for name in ("equity", "positions", "fees", "funding", "turnover"):
        if name in arrays:
            require(arrays[name].shape == (26280,) and bool(np.isfinite(arrays[name]).all()), "finite aligned account stream required")
    require(arrays["daily_returns"].shape == (1095,) and bool(np.isfinite(arrays["daily_returns"]).all()), "complete daily returns required")
    contract = p.ReportingContractV1(**registration["original_reporting_contract"])
    covered = p.ReportingCoverageV1(result_identity=path_pin["sha256"], producer="jobs COMPLETE qualified original finance",
        profile="compact", ledger="omitted", retained_rows=0, dropped_rows=0, reason="separate qualified ledger or legacy unavailable")
    obs = p.AccountObservations(times_ns=arrays["times_ns"], equity=arrays["equity"], coverage=covered)
    if np.all(obs.equity > 0):
        obs = obs.with_derived_returns(contract, partial_mask=np.zeros(1095, dtype=bool), witness="complete retained UTC days")
        np.testing.assert_allclose(obs.returns.values, arrays["daily_returns"], rtol=0, atol=1e-12)
    campaigns = fills = None
    if request["alpha"] == "A-SC":
        campaigns, fills = load("actual/campaigns.json"), load("actual/fills.json")
    provenance = p.CandidateProvenance("m5111_goal_step1", "missing-analysis01", request["alpha"], request["candidate_id"],
        prior.digest(request["params"]), prior.digest(request["params"]), request["probe_direction"], (request["proposal_row"],),
        cell["execution_key"], request["design_id"], request["symbol"], "REVIEWED_EXPLORATORY_DEVELOPMENT",
        registration["outcome_timing"], p._ns("2020-01-01"), stop, p._ns(prior.now()), p._ns(prior.now()),
        cell["route"], (("paths", path_pin["sha256"]), ("checkpoint", item["checkpoint"]["sha256"])))
    buffers = tuple(p.FrozenBuffer.from_array(name, arrays[name]) for name in ("positions", "fees", "funding", "turnover") if name in arrays)
    verified = p.VerifiedCell(provenance, start, stop, contract, obs, buffers,
        json.dumps(campaigns) if campaigns is not None else None, json.dumps(fills) if fills is not None else None,
        json.dumps(cell["metrics"]), "PASS", None)
    rows = [views.row_metadata(r) for r in p.continuous_annual_rows(verified,
        utility_policy=p.UtilityPolicy(**registration["annual_utility"]), backend="python")]
    views.verify_reconciliation(rows, verified)
    for row in rows:
        row.update(cell_id=item["cell_id"], role=request["role"], parent_panel_index=request["parent_panel_index"],
                   source_checkpoint=item["checkpoint"], union_design_id=entry["union_design_id"],
                   request_sha256=entry["request_sha256"], annual_local_authorized=False)
    return cell, rows


def original_centers(registration, key):
    pool = views.indexed(views.sealed_json(registration["original_step_registration"])["protected_prior_files"])
    by_sha = {p["sha256"]: p for p in pool.values()}
    rows = views.sealed_json(registration["original_panel_rows"][key])["rows"]
    centers = []
    for position, parent in enumerate(registration["parent_roster"][key]):
        matches = [r for r in rows if r["provenance"]["candidate_id"] == parent["candidate_id"] and r["environment_id"] == "whole_path"]
        require(len(matches) == 1, "exact original center whole-path row required")
        row = matches[0]
        pin = by_sha[dict(row["provenance"]["evidence_refs"])["cell"]]
        cell = views.sealed_json(pin)
        require(cell["request"]["candidate_id"] == parent["candidate_id"] and
                cell["request"]["params"] == parent["params"] and cell["status"] == "PASS", "original center identity differs")
        views.close(prior.metric(row, "economic_utility"), cell["metrics"]["economic_utility"], "center original utility")
        union = views.sealed_json(registration["union"])
        fit = next(f for f in union["fits"] if f["alpha"] == key and f["original_index"] == parent["panel_index"])
        require(fit["candidate_id"] == parent["candidate_id"], "covariance fit center differs")
        centers.append(dict(parent, center=position, cell=pin, metrics=cell["metrics"],
                            covariance=fit, held_support="dependent development directions"))
    return centers


def analyze(registration, inputs, progress=None):
    validate_registration(registration)
    require(inputs["status"] == "PASS" and inputs["recipe_id"] == registration["recipe_id"] and
            inputs["request_roster_sha256"] == registration["request_roster_sha256"] and
            [r["request_sha256"] for r in inputs["inputs"]] == [e["request_sha256"] for e in registration["entries"]],
            "all ordered reconciled inputs required")
    jobs.verify_pins(inputs["custody_pins"] + [inputs["controller_completion"], inputs["overlay_completion_manifest"]])
    whole, annual, evaluations = [], [], {key: {} for key in TARGETS}
    for entry, item in zip(registration["entries"], inputs["inputs"], strict=True):
        cell, rows = completed_cell(registration, entry, item)
        whole.append(rows[0])
        annual.extend(rows[1:])
        request = entry["request"]
        key = "rsi" if request["alpha"] == "A-RSI" else "sc"
        index = entry["execution_index"]
        evaluations[key][index] = dict(index=index, center=request["neighborhood_center"], role=request["role"],
            candidate_id=request["candidate_id"], direction=request["probe_direction"], metrics=cell["metrics"],
            utility=cell["metrics"]["economic_utility"], status="COMPLETE", cell=cell_pin(item, "actual/cell.json"),
            paths=cell["path"])
        if progress is not None:
            progress(dict(completed_cells=len(whole), annual_rows=len(annual),
                inherited_account_passes=sum(r["exact_counts"]["account_passes"] for r in inputs["inputs"][:len(whole)]),
                inherited_account_bars=sum(r["exact_counts"]["account_bars"] for r in inputs["inputs"][:len(whole)])))
    require(len(whole) == registration["expected_whole_path_rows"] and len(annual) == registration["expected_annual_rows"],
            "all 303 whole-path and 909 annual rows required")
    comparisons = {key: compare_local(registration, key, original_centers(registration, key), evaluations[key]) for key in TARGETS}
    return dict(status="PASS_COLD_UNION_CLOSURE", recipe_id=registration["recipe_id"], whole_path_rows=whole,
        annual_attribution_rows=annual, local_comparisons=comparisons, new_financial_executions=0,
        inherited_account_passes=inputs["inherited_account_passes"], inherited_account_bars=inputs["inherited_account_bars"],
        clean_oos=False, annual_local_status="NOT_AUTHORIZED", covariance_union_claim=True, full_panel_local_status="NOT_EVALUABLE")


def cell_pin(item, name):
    return views.indexed(views.sealed_json(item["checkpoint"])["artifacts"])[str(Path(item["output"]) / name)]


def check_budget(lane, registration):
    budget = jobs.Budget(**registration["budget"])
    space = jobs._preflight(lane, budget)
    _, total, inodes = jobs._tree(lane)
    _, scratch, scratch_inodes = jobs._tree(lane / "scratch-test-01")
    require(scratch <= budget.scratch_bytes and total-scratch <= budget.retained_bytes and
            scratch_inodes <= budget.scratch_inodes and inodes-scratch_inodes <= budget.retained_inodes,
            "cold sidecar byte/inode cap exceeded; evidence preserved")
    return dict(**space, scratch_bytes=scratch, retained_bytes=total-scratch,
                scratch_inodes=scratch_inodes, retained_inodes=inodes-scratch_inodes)


def run_phase(registration_path, input_path, attempt, command, overlay_path=None):
    """Exclusive bounded cold attempt with progress, fault and cleanup custody."""
    require(command in {"reconcile", "analyze"}, "unknown cold phase")
    registration_path = jobs._safe(registration_path)
    target = registration_path.parent / jobs._name(attempt)
    target.mkdir(exist_ok=False)
    journal = jobs.Journal(target / "journal")
    started, protected, handlers = perf_counter(), [], {}
    journal.append("cold_start", phase=command, owner=jobs.process_identity(os.getpid()), financial_executions=0)

    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"cold phase interrupted by signal {signum}")

    def progress(fields):
        check_budget(registration_path.parent, registration)
        journal.append("cold_progress", **fields, elapsed_seconds=perf_counter()-started, financial_executions=0)

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            handlers[sig] = signal.signal(sig, interrupted)
        registration_pin, input_pin = prior.pin(registration_path), prior.pin(input_path)
        protected += [registration_pin, input_pin]
        registration = views.sealed_json(registration_pin)
        before = check_budget(registration_path.parent, registration)
        if command == "reconcile":
            overlay_pin = prior.pin(overlay_path)
            protected.append(overlay_pin)
            result = reconcile(registration, input_pin, overlay_pin)
        else:
            result = analyze(registration, views.sealed_json(input_pin), progress)
        result.update(elapsed_seconds=perf_counter()-started, input=input_pin, registration=registration_pin,
                      resources_before=before)
        jobs._seal(target / "result.json", result)
        check_budget(registration_path.parent, registration)
        journal.append("cold_completion", result=prior.pin(target / "result.json"), elapsed_seconds=perf_counter()-started,
                       financial_executions=0)
        return target / "result.json"
    except BaseException as error:
        jobs._seal(target / "fault.json", dict(status="INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "FAULT",
            error_type=type(error).__name__, error=str(error), elapsed_seconds=perf_counter()-started, financial_executions=0))
        journal.append("cold_fault", fault=prior.pin(target / "fault.json"), financial_executions=0)
        raise
    finally:
        hash_errors = []
        try:
            jobs.verify_pins(protected)
        except Exception as error:
            hash_errors.append(str(error))
        jobs._seal(target / "cleanup.json", dict(after=jobs._space(target), protected_pins=protected,
            hash_errors=hash_errors, deleted=[], scratch_created=False, evidence_deleted=False, financial_executions=0))
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("register").add_argument("--attempt", default="registration-union-01.json")
    for command in ("plan", "reconcile", "analyze"):
        child = commands.add_parser(command)
        child.add_argument("--registration", type=Path, default=LANE / "registration-union-01.json")
        if command != "plan":
            child.add_argument("--input", type=Path, required=True)
            child.add_argument("--attempt", required=True)
        if command == "reconcile":
            child.add_argument("--overlay", type=Path, required=True, help="sealed overlay completion manifest")
    args = parser.parse_args()
    if args.command == "register":
        print(register(attempt=args.attempt))
        return
    if args.command == "plan":
        registration = views.sealed_json(prior.pin(args.registration))
        validate_registration(registration)
        print(json.dumps(dict(status=registration["status"], requests=len(registration["entries"]), annual_rows=909,
                              store=registration["store"], financial_executions=0, recipe_id=registration["recipe_id"])))
        return
    output = run_phase(args.registration, args.input, args.attempt, args.command, getattr(args, "overlay", None))
    print(json.dumps(dict(output=str(output), financial_executions=0)))


if __name__ == "__main__":
    main()

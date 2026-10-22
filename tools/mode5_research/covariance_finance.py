"""Cold custody for sealed covariance additions; finance remains the original owner.

Preparation never imports an account engine or launches jobs. The worker entry
delegates to missing_probes.execute_one and the frozen spec02 private hooks.
"""

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path

from tools.mode5_research import missing_probes as original
from tools.mode5_research import selector_checkpoint as custody
from tools.mode5_research.covariance_requests import QUALIFICATION, RECIPE, TARGETS
from tools.mode5_research.feedback_observer import FrozenPins, file_pin
from tools.mode5_research.jobs import Budget, GIB, MIB, _safe, _seal


ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "upgrade/private/mode5_upgrade_v1/m5-11-1/attempt-01"
STEP = PARENT / "goal-step1"
DEFAULT = STEP / "cov-finance01"
BASE_DRIVER = ROOT / "upgrade/local/mode5_upgrade_v1/m5-11-1/goal-selector-finance01/driver.py"
DRIVER = BASE_DRIVER.with_name("cov_driver.py")
SCHEMA = "mode5.covariance_selector_accounts.v1"
NEW = "NEW_COVARIANCE_ROLE_REQUEST_NO_ACCOUNT_EVIDENCE"
PRESERVED = "PRESERVED_SEALED_SCHEMA_REQUEST"
SEALS = {
    "missing-finance01/spec-02/registration.json": "826edf8c9d1fa79eb80146adecbbd5720daba8b22ede78459733e521ec9b8350",
    "missing_evidence_requests_08.json": "f23b1b3cae547cf6868c22bac743c4e73f22e2ebbb53004010133a23206bd3ba",
    "cov-fit01/registration_01.json": "20b8e342a800211a52ea0cb70ee5ffff891788401143ea307ffafeb8d51d6cb9",
    "cov-fit01/union_01.json": "95a3d764c751f9a207be79cb1a9247a2981befee26811159aaa0857af2c69065",
    "missing-launch01/budget.json": "5f78a5ba28173a96da41c58dd1d95e0d70bb77786660842f8b7b7bf94e8df158",
}
require = original.require
digest = original.canonical_digest


def sealed_input(relative):
    pin = file_pin(_safe(STEP / relative))
    require(pin["sha256"] == SEALS[relative], "accepted input seal differs: " + relative)
    return original.read_json(pin["path"]), pin


def unique_pins(records):
    by_path = {}
    for pin in records:
        require(pin["path"] not in by_path or by_path[pin["path"]] == pin,
                "conflicting inherited pin: " + pin["path"])
        by_path[pin["path"]] = pin
    return list(FrozenPins(list(by_path.values())).records)


def collect_covariance(union, base, bundle, parents):
    """Check all 303 ledgers, returning only the 108 genuinely missing additions."""
    require(union["schema"] == "m5111_covariance_fit_and_union_v1" and union["status"] == "PASS",
            "measured sealed union required")
    require(not any(union[k] for k in ("launch_authorized", "reuse_authorized", "account_union_complete",
            "whole_128_probe_expansion", "annual_local_ranking_authorized", "financial_executions", "builds")),
            "cold union must not imply account evidence or authority")
    prior, pending = original.collect_missing(bundle, parents, base["geometries"])
    require(prior == base["entries"] and len(prior) == 195 and len(pending) == 4,
            "all frozen spec02 schema requests must remain unchanged")
    old = {(key, e["request_sha256"]): e for key in TARGETS
           for e in bundle[key]["bounded_neighborhood_manifest"]["executions"]}
    fits = {(f["alpha"], f["original_index"]): f for f in union["fits"]}
    expected_fits = {(key, index) for key, indices in TARGETS.items() for index in indices}
    require(set(fits) == expected_fits and len(union["fits"]) == 4 and union["fit_requests_closed"] == 4,
            "four exact supported fit requests required")
    rosters = {}
    for key, alpha in (("rsi", "A-RSI"), ("sc", "A-SC")):
        metadata, design = base["geometries"][alpha], parents[alpha]
        roster = [r for r in design["rows"] if r["admitted"]]
        rosters[key] = roster
        require(len(roster) == 128 and len({r["candidate_id"] for r in roster}) == 128 and
                design["schema_id"] == digest(metadata), "original 128-panel/domain identity differs")
        for row in roster:
            require(original.effective_id(metadata, row["effective"]) == row["candidate_id"],
                    "original parent coordinate differs")
        for request in bundle[key]["bounded_neighborhood_manifest"]["covariance_requests"]:
            fit = fits[key, request["original_index"]]
            require(fit["request_identity"] == digest(request) and
                    request["candidate_roster"] == [r["candidate_id"] for r in roster] and
                    fit["candidate_id"] == roster[fit["original_index"]]["candidate_id"] and
                    request["geometry_id"] == design["schema_id"] and fit["recipe"] == request["recipe"] == RECIPE,
                    "exact cloud-fit request/domain/parent differs")
            cloud = fit["cloud_ids"]
            require(fit["status"] == "MEASURED_SUPPORTED" and fit["supported"] and fit["center_quality_eligible"] and
                    fit["covariance_status"] == "REGULARIZED_PROPOSALS_NOT_HESSIAN" and
                    fit["distinct_cloud_count"] == len(cloud) == len(set(cloud)) and len(cloud) >= 5 and
                    set(cloud) <= {r["candidate_id"] for r in roster} and fit["candidate_id"] in cloud and
                    fit["centered_coordinate_rank"] == fit["numeric_dimensions"] == len(fit["numeric_names"]) and
                    len(fit["coordinates"]) == len(cloud) and
                    all(len(c) == fit["numeric_dimensions"] for c in fit["coordinates"]) and
                    not any(fit[k] for k in ("independent", "clean_oos", "launch_authorized")),
                    "measured full-rank/minimum-five cloud support differs")
    neighborhoods = {n["neighborhood_id"]: n for n in union["neighborhoods"]}
    require(len(neighborhoods) == len(union["neighborhoods"]) == 8 and
            {(n["alpha"], n["original_index"], n["role"]) for n in neighborhoods.values()} ==
            {(key, index, role) for key, index in expected_fits for role in ("selection_probe", "local_validation")},
            "eight exact role neighborhoods required")
    for n in neighborhoods.values():
        fit = fits[n["alpha"], n["original_index"]]
        alpha = "A-RSI" if n["alpha"] == "rsi" else "A-SC"
        require(n["role"] in {"selection_probe", "local_validation"}, "unknown probe role")
        prefix = "selection" if n["role"] == "selection_probe" else "validation"
        require(n["radius"] == RECIPE[prefix + "_radius"] and n["seed"] == RECIPE[prefix + "_seed"] and
                n["parent_candidate_id"] == fit["candidate_id"] and n["covariance_status"] == fit["covariance_status"] and
                not n["independent"] and not n["account_evidence_available"], "covariance role/seed/radius differs")
        identity = dict(parent_design=parents[alpha]["design_id"], center=fit["candidate_id"],
            geometry=parents[alpha]["schema_id"], role=n["role"], radius=n["radius"], minimum_radius=.05,
            seed=n["seed"], joint_groups=n["coverage"]["joint_groups"], cloud_ids=fit["cloud_ids"],
            rho=.2, tau=.001, proposal_identity=n["proposal_identity"])
        require(digest(identity) == n["neighborhood_id"], "sealed cloud/proposal neighborhood identity differs")
        floor = next(v for v in bundle[n["alpha"]]["bounded_neighborhood_manifest"]["neighborhoods"]
                     if v["neighborhood_id"] == n["original_schema_neighborhood_id"])
        require((floor["original_index"], floor["role"], floor["center"]) ==
                (n["original_index"], n["role"], n["center"]), "original schema role mapping differs")
        require(len({r["row_id"] for r in n["rows"]}) == len(n["rows"]), "duplicate proposal row")
    entries, preserved, coordinates, indexes, bound_rows = [], set(), set(), set(), set()
    for e in union["executions"]:
        require(e["source"] in {NEW, PRESERVED}, "unregistered execution source")
        r, key = e["request"], e["alpha"]
        require(key in TARGETS and type(e["index"]) is int and e["index"] not in indexes,
                "duplicate/unknown union execution index")
        indexes.add(e["index"])
        require(digest(r) == e["request_sha256"] and set(r) == set(original.BASE) | original.EXTRA and
                all(r[k] == v for k, v in original.BASE.items()), "request SHA/scope/economics differs")
        alpha, symbol = ("A-RSI", "ETHUSDT") if key == "rsi" else ("A-SC", "BTCUSDT")
        require(r["alpha"] == alpha and r["symbol"] == symbol and
                r["candidate_id"] == original.effective_id(base["geometries"][alpha], r["params"]),
                "effective coordinate/domain/symbol differs")
        n = neighborhoods[e["union_design_id"]]
        require(n["alpha"] == key and r["parent_panel_index"] == e["original_index"] == n["original_index"] and
                r["parent_candidate_id"] == n["parent_candidate_id"] and
                r["parent_design_id"] == parents[alpha]["design_id"] and
                r["role"] == e["role"] == n["role"] and r["probe_radius"] == n["radius"] and
                r["probe_seed"] == n["seed"] and r["neighborhood_center"] == e["center"] == n["center"] and
                r["design_id"] == e["request_design_id"] and r["proposal_row"] == e["row_id"] and
                r["candidate_id"] == e["candidate_id"], "exact parent/role/direction contract differs")
        row = next(v for v in n["rows"] if v["row_id"] == e["row_id"])
        require(row["status"] == "READY" and row["role"] == r["role"] and
                row["direction"] == r["probe_direction"] and row["effective"] == r["params"] and
                row["candidate_id"] == r["candidate_id"] and row["execution_index"] == e["index"] and
                row["point"]["schema_id"] == parents[alpha]["schema_id"] and
                json.loads(row["point"]["effective_json"]) == r["params"] and
                json.loads(row["requested_json"]) == row["requested"], "exact READY proposal ledger differs")
        coordinate = (key, n["neighborhood_id"], r["candidate_id"])
        require(coordinate not in coordinates, "within-role effective-coordinate alias cannot execute twice")
        coordinates.add(coordinate)
        bound_rows.add((n["neighborhood_id"], row["row_id"]))
        require(e["execution_status"] == "NOT_EXECUTED_BY_COV_FIT" and not e["launch_authorized"] and
                not e["reuse_authorized"] and not e["annual_views_available"] and
                e["required_annual_views"] == list(custody.ANNUAL), "unexecuted account/view disposition differs")
        if e["source"] == PRESERVED:
            old_key = key, e["request_sha256"]
            require(old_key in old and old_key not in preserved and e["original_schema_execution"] == old[old_key] and
                    r == old[old_key]["request"] and r["design_id"] == n["original_schema_neighborhood_id"],
                    "sealed 195 request/role/design was rewritten")
            preserved.add(old_key)
            continue
        require(e["original_schema_execution"] is None and not e["coordinate_role_matches"] and
                r["design_id"] == n["neighborhood_id"] and r["probe_direction"].startswith("covariance:"),
                "only missing, non-reused covariance additions may become specs")
        fit = fits[key, e["original_index"]]
        analysis = dict(schema=SCHEMA, request_sha256=e["request_sha256"], source=NEW,
            scope="incremental_covariance_roles_bounded_union_not_whole_128_local_qualification",
            annual_views=list(custody.ANNUAL), annual_policy="continuous_path_attribution_no_account_reset",
            annual_local_ranking_authorized=False, role=r["role"], radius=r["probe_radius"], seed=r["probe_seed"],
            union_design_id=n["neighborhood_id"], original_schema_neighborhood_id=n["original_schema_neighborhood_id"],
            proposal_row_sha256=digest(row), cloud_fit_sha256=digest(fit), fit_request_sha256=fit["request_identity"],
            original_domain_id=parents[alpha]["schema_id"],
            parent_coordinate_sha256=digest(rosters[key][e["original_index"]]["effective"]))
        entries.append(dict(cell_id=f"cov-{key}-{e['original_index']:03d}-{e['index']:03d}",
                            request=deepcopy(r), analysis=analysis, analysis_id=digest(analysis)))
    ready_rows = {(n["neighborhood_id"], r["row_id"]) for n in neighborhoods.values()
                  for r in n["rows"] if r["status"] == "READY"}
    require(bound_rows == ready_rows and indexes == set(range(303)) and preserved == set(old) and
            len(entries) == 108 and Counter(e["request"]["alpha"] for e in entries) == {"A-RSI": 96, "A-SC": 12} and
            Counter(e["request"]["role"] for e in entries) == {"selection_probe": 54, "local_validation": 54},
            "complete 195+108 READY role union/counts required")
    return entries


def execute_registered(registration, registration_pin, cell, *, request_path, output, progress, load_driver):
    """Verify custody before loading even the cold private owner; delegate unchanged."""
    registration = _safe(registration)
    require(registration_pin["path"] == str(registration), "registration pin path differs")
    FrozenPins([registration_pin]).verify()
    registry = original.read_json(registration)
    require(registry["schema"] == SCHEMA and registry["status"] == "PREPARED_NOT_LAUNCHED" and
            len(registry["entries"]) == 108, "full covariance registration required")
    FrozenPins(registry["pins"]).verify()
    matches = [e for e in registry["entries"] if e["cell_id"] == cell]
    require(len(matches) == 1, "exact unique covariance cell required")
    entry = matches[0]
    require(original.read_json(request_path) == entry["request"] and
            digest(entry["request"]) == entry["analysis"]["request_sha256"] and
            digest(entry["analysis"]) == entry["analysis_id"] and entry["analysis"]["source"] == NEW and
            entry["request"]["probe_direction"].startswith("covariance:"), "registered covariance request differs")
    owner = load_driver(registry["base_driver"])
    return original.execute_one(entry, output=output, progress=progress,
        pins=[*registry["pins"], registration_pin], context_factory=owner.context_factory, qualify=owner.qualify,
        validate_context=lambda context, request: owner.validate_context(context, request, registry))


def prepare(lane=DEFAULT):
    lane = _safe(lane)
    require(lane == DEFAULT and not lane.exists(), "fresh exact cov-finance01 lane required")
    before = custody.resources(STEP)
    require(before["free_bytes"] >= 5*GIB + 4*GIB + 96*MIB and before["free_inodes"] >= 101024,
            "global budget and reserve/inode preflight failed")
    source_paths = [Path(__file__), ROOT / "tests/test_mode5_covariance_finance.py", DRIVER]
    lane.mkdir()
    _seal(lane / "preparation_registration.json", dict(schema=SCHEMA, created_at=custody.now(),
        status="REGISTERED_BEFORE_COLD_VALIDATION", sources=[file_pin(p) for p in source_paths],
        accepted_input_seals=SEALS, budget=dict(scratch_bytes=32*MIB, retained_bytes=128*MIB, reserve_bytes=5*GIB),
        resources_before=before, financial_executions=0, builds=0, launch_authorized=False,
        write_set=[str(p) for p in source_paths] + [str(lane)],
        cleanup_inventory=dict(scratch_paths=[], eligible_deletions=[], preserve="all prior pins, failures, sources, data and environments")))
    values, inputs = {}, []
    for relative in SEALS:
        values[relative], pin = sealed_input(relative)
        inputs.append(pin)
    base = values["missing-finance01/spec-02/registration.json"]
    fit_registration = values["cov-fit01/registration_01.json"]
    require(fit_registration["recipe"] == RECIPE and fit_registration["qualification"] == QUALIFICATION,
            "original fit/quality preferences changed")
    FrozenPins(base["pins"]).verify()
    FrozenPins([*fit_registration["software"], *fit_registration["prior_step_files"]]).verify()
    preserved = custody.verify_prior(custody.read(fit_registration["original_registration"]))
    require(preserved["verified"] == 4752, "all historical 4,752 pins required")
    pins_by_path = {p["path"]: p for p in base["pins"]}
    parents = {}
    for alpha in ("A-RSI", "A-SC"):
        parent_pin = pins_by_path[str(PARENT / f"design-{alpha}.json")]
        parents[alpha] = custody.read(parent_pin)
    base_driver_pin = pins_by_path[str(BASE_DRIVER)]
    require(file_pin(BASE_DRIVER) == base_driver_pin, "spec02 driver must remain frozen")
    entries = collect_covariance(values["cov-fit01/union_01.json"], base,
                                 values["missing_evidence_requests_08.json"], parents)
    pins = unique_pins([*base["pins"], *inputs, *[file_pin(p) for p in source_paths],
        file_pin(ROOT / "tools/mode5_research/covariance_requests.py"),
        file_pin(ROOT / "tools/mode5_research/selector_checkpoint.py")])
    budget = Budget(**values["missing-launch01/budget.json"])
    require((budget.scratch_bytes, budget.retained_bytes, budget.reserve_bytes) == (96*MIB, 4*GIB, 5*GIB),
            "same global financial budget required")
    budget_path = lane / "financial-budget.json"
    _seal(budget_path, asdict(budget))
    registration = {k: deepcopy(base[k]) for k in ("geometries", "native_gate", "native_gate_artifact",
        "controlled_prefix", "controlled_python_real", "controlled_shell_real", "runtime_proof",
        "geometry_inheritance", "analysis_inheritance")}
    registration.update(schema=SCHEMA, status="PREPARED_NOT_LAUNCHED", entries=entries, pins=pins,
        base_driver=base_driver_pin, spec02_registration=inputs[0], covariance_union=inputs[3],
        original_bundle=base["original_bundle"], preserved_schema_requests=195, incremental_covariance_requests=108,
        financial_executions=0, builds=0, forward_tape_opened=False, launch_authorized=False,
        scope="108 additional covariance paths only; preserve 195 sealed requests; no whole128 local claim",
        expected_returned_owner_passes=204, expected_returned_owner_bars=204*26280,
        count_status="FORECAST_NOT_COMPLETED_WORK", future_annual_views=324,
        historical_custody=preserved, budget=file_pin(budget_path),
        launch_prerequisite="main must finish and qualify original 195 before covariance launch, then compound analysis")
    registry_path = lane / "registration.json"
    _seal(registry_path, registration)
    wrapper = BASE_DRIVER.with_name("controlled-python.sh")
    require(file_pin(wrapper) == pins_by_path[str(wrapper)] and os.access(wrapper, os.X_OK),
            "same pinned executable wrapper required")
    specs = original.job_specs(entries, driver=DRIVER, registration=registry_path, executable=wrapper,
        cwd=ROOT, pins=pins, env=(("PYTHONNOUSERSITE", "1"),))
    inventory = []
    for group, candidates in specs.items():
        path = lane / f"specs-{group}.json"
        _seal(path, candidates)
        require(path.stat().st_size <= 3*MIB, "split specs exceed 3 MiB cap")
        inventory.append(dict(group=group, count=len(candidates), spec=file_pin(path)))
    require(sum(v["count"] for v in inventory) == 108, "spec inventory count differs")
    store = STEP / "financial-jobs-store"
    cli = [str(ROOT / ".maturin/qms08/release-regression-v1/bin/python"), "-B", "-m", "tools.mode5_research.jobs"]
    handoff = dict(schema=SCHEMA, status="PREPARED_NOT_LAUNCHED", cwd=str(ROOT), global_store=str(store),
        workers=3, numeric_threads=1, registration=file_pin(registry_path), budget=file_pin(budget_path),
        base_driver=base_driver_pin, covariance_union=inputs[3], specs=inventory, accounts=108,
        counts=dict(rsi=96, sc=12, selection_probe=54, local_validation=54),
        plan_argv=[cli + ["plan", "--specs", v["spec"]["path"], "--store", str(store),
                         "--budget", str(budget_path)] for v in inventory],
        register_argv_templates=[cli + ["register", "--specs", v["spec"]["path"], "--store", str(store),
            "--lane", v["group"] + "-01", "--workers", "3", "--native-gate", base["native_gate"]["path"],
            "--budget", str(budget_path)] for v in inventory],
        launch_argv=[cli + ["launch", "--lane", str(store / "runs" / (v["group"] + "-01"))] for v in inventory],
        watch_argv=[cli + ["watch", "--lane", str(store / "runs" / (v["group"] + "-01"))] for v in inventory],
        prerequisites=[registration["launch_prerequisite"], "verify all frozen pins and main native gate before launch",
            "one shared global budget/store; sequential spec lanes, at most three independent one-thread workers",
            "jobs custody registration remains main-owned; no second store or waiting supervisor pool",
            "do not change request IDs, deduplicate across roles, infer independence, or drop adverse completed results"],
        financial_executions=0, builds=0, launches=0, global_store_mutated=False,
        annual_local_ranking_authorized=False, phase_complete=False, full_goal_complete=False)
    _seal(lane / "handoff.json", handoff)
    FrozenPins(pins).verify()
    retained = sum(p.stat().st_size for p in lane.rglob("*") if p.is_file())
    require(retained + 65536 <= 128*MIB, "cold preparation retained cap exceeded")
    _seal(lane / "cleanup-prepare.json", dict(status="PASS", retained_bytes=retained, scratch_bytes=0,
        deleted_paths=[], deleted_bytes=0, resources_before=before, resources_after=custody.resources(lane),
        reserve_bytes=5*GIB, original_pins_verified=4752, spec02_pins_verified=len(base["pins"]),
        financial_executions=0, builds=0, launches=0, global_store_mutated=False, all_prior_evidence_preserved=True))
    return lane / "handoff.json"

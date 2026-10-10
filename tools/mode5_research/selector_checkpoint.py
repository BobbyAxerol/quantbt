"""Stdlib-only, append-only selector replay over sealed development evidence.

This adapter never imports QuantBT or opens a financial runtime. Registration
records present custody, not a retroactive execution or untouched-OOS seal.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys


MIB = 1024**2
ANNUAL = ("2021", "2022", "2023")
ENVIRONMENTS = ("whole_path", *ANNUAL)
ROOT_SEALS = {
    "analyst_final_manifest_01.json": "015d1e67538a351dc13783bf18b95a30d29eeea1153c5442a9ccc7fa62034100",
    "rsi_probes_final_receipt.json": "4d141df310785408ae104487f98a03c86b1226a330ec16a9a93366e0f0fd90c4",
    "sc_probes_closeout_receipt_01.json": "6a74ea89dabcc4f0f41e96a6ced8a0903ee6acc876396c3f7af904c4b8fa8b0d",
}
BOUNDED_RECIPE = dict(version="selector_schema_floor_requests_v1",
    targets=dict(rsi=[10, 49, 114], sc=[33]), selection_radius=.1, validation_radius=.12,
    selection_seed=732, validation_seed=733, minimum_radius=.05,
    covariance="PENDING_LOCAL_CLOUD_FIT_NOT_A_SCHEMA_ONLY_SPARSE_FALLBACK",
    rho=.2, tau=.001, minimum_cloud=5, cloud_radius=.25,
    scope="schema floor only; conditional covariance extension needs its own sealed design",
    launches_authorized=False)


def now():
    return datetime.now(timezone.utc).isoformat()


def pin(path):
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"regular nonsymlink file required: {path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(MIB), b""):
            h.update(block)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=h.hexdigest())


def checked(record):
    actual = pin(record["path"])
    if actual != {k: record[k] for k in ("path", "bytes", "sha256")}:
        raise ValueError(f"size/SHA mismatch: {record['path']}")
    return actual


def read(record):
    checked(record)
    return json.loads(Path(record["path"]).read_text())


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    return pin(path)


def resources(path):
    import os
    stat = os.statvfs(path)
    return dict(free_bytes=stat.f_bavail * stat.f_frsize, free_inodes=stat.f_favail)


def register(parent, lane):
    parent, lane = Path(parent).resolve(), Path(lane).resolve()
    if lane.parent != parent or lane.name != "goal-step1" or lane.exists():
        raise ValueError("new exact parent/goal-step1 lane required")
    before = resources(parent)
    if before["free_bytes"] < 5 * 1024**3 + (32 + 256) * MIB or not before["free_inodes"]:
        raise ValueError("5 GiB reserve plus incremental budget required")
    roots = {name: pin(parent / name) for name in ROOT_SEALS}
    for name, record in roots.items():
        if record["sha256"] != ROOT_SEALS[name]:
            raise ValueError(f"historical root seal differs: {name}")
    protected = [pin(p) for p in sorted(parent.rglob("*")) if p.is_file()]
    registration = dict(
        schema="m5111_selector_only_registration_v1", created_at=now(),
        authority="owner bounded step1 sidecar; ordered full-goal approval",
        disclosure="existing outcomes reviewed; retrospective cold replay only",
        root_seals=roots, protected_prior_files=protected, resources_before=before,
        budget=dict(scratch_bytes=32*MIB, retained_bytes=256*MIB, reserve_bytes=5*1024**3),
        cleanup_inventory=dict(scratch_paths=[], eligible_deletions=[],
            retained_lane=str(lane), retained_environment=".maturin/qms08/release-regression-v1",
            excluded=["all prior evidence", "all caches/environments", "source/data/artifacts"],
            process_review="sandbox process view only; no deletion or worker launch"),
        recipes=dict(annual="inherit exact sealed preferences and canonical decisions",
            raw_sharpe="same original 128; defined whole-path Sharpe; unqualified control",
            local=dict(formula_id="local_downside_v1", gamma=1, activity_penalty=0,
                aggregate="whole_path economic utility only", reference_scale=1,
                roster="two actually evaluated registered centers per alpha",
                roles_used_for_selection=["selection_probe"], validation_access="post-decision reporting only",
                quality="original all-probe quality policy plus unchanged DD/day gates",
                annual_local="NOT_EVALUABLE until sealed annual probe/aggregate contracts exist")),
        financial_executions=0, builds=0, installs=0, launches_authorized=False,
        write_set=["tools/mode5_research/selector_checkpoint.py",
            "tests/test_mode5_selector_checkpoint.py", "docs/mode5/M5_11_1_SELECTOR_ONLY.md", str(lane)],
        tests=[str(Path(sys.executable)), "-B", "-m", "unittest", "discover", "-s", "tests",
            "-p", "test_mode5_selector_checkpoint.py", "-v"],
    )
    return write_new(lane / "registration_01.json", registration)


def metric(row, name):
    matches = [m for m in row["metrics"] if m["metric_id"] == "mode5.panel." + name]
    if len(matches) != 1:
        raise ValueError(f"exact metric contract required: {name}")
    m = matches[0]
    if m["unit"] != ("ratio" if name == "sharpe" else "decimal_return"):
        raise ValueError("metric units differ")
    if m["status"] != "VALID" or row["compute_status"] != "PASS":
        if m["value"] is not None or not m["reason"]:
            raise ValueError("undefined metric needs null and reason")
        return None
    if type(m["value"]) not in (int, float) or not math.isfinite(m["value"]):
        raise ValueError("VALID metric must be finite")
    return m["value"]


def grid_for(result):
    ids = result["candidate_ids"]
    if len(ids) != 128 or len(set(ids)) != 128:
        raise ValueError("exact original 128 candidate roster required")
    grid = {}
    for row in result["candidate_environment_rows"]:
        key = (row["provenance"]["candidate_id"], row["environment_id"])
        if key in grid or key[0] not in ids or key[1] not in ENVIRONMENTS:
            raise ValueError("duplicate/unexpected candidate/environment")
        if (row["clean_oos"] is not False or row["estimand_id"] != "CONTINUOUS_PATH_ATTRIBUTION"
                or row["provenance"]["data_role"] != "REVIEWED_EXPLORATORY_DEVELOPMENT"):
            raise ValueError("reviewed continuous development only")
        expected_days = 1095 if key[1] == "whole_path" else 365
        if row["calendar_days"] != expected_days or row["actual_bar_count"] != expected_days*24:
            raise ValueError("original complete daily/hourly calendar required")
        for name in ("economic_utility", "drawdown", "daily_loss_es", "net_return", "sharpe"):
            metric(row, name)
        grid[key] = row
    if set(grid) != {(c, e) for c in ids for e in ENVIRONMENTS}:
        raise ValueError("missing candidate/environment; no survivor averaging")
    for index, cid in enumerate(ids):
        rows = [grid[cid, e] for e in ENVIRONMENTS]
        if any(r["index"] != index for r in rows) or len({r["provenance"]["execution_id"] for r in rows}) != 1:
            raise ValueError("same original continuous account/index required")
    return grid


def gates(row, preferences):
    utility, dd = metric(row, "economic_utility"), metric(row, "drawdown")
    return dict(risk=dd is not None and 0 <= dd <= preferences["risk_drawdown_max"],
        quality=utility is not None and utility > preferences["quality_utility_strictly_greater_than"],
        days=row["compute_status"] == "PASS" and row["calendar_days"] >= preferences["minimum_daily_count"])


def outcome(grid, cid, preferences):
    if cid is None:
        return None
    return dict(candidate_id=cid, index=grid[cid, "whole_path"]["index"],
        environments={env: dict(
            utility=metric(grid[cid, env], "economic_utility"),
            sharpe=metric(grid[cid, env], "sharpe"),
            drawdown=metric(grid[cid, env], "drawdown"),
            gates=gates(grid[cid, env], preferences), status=grid[cid, env]["status"],
            null_reasons=grid[cid, env]["null_reasons"]) for env in ENVIRONMENTS})


def best(rows):
    eligible = [r for r in rows if r["eligible"] and r["score"] is not None]
    return min(eligible, key=lambda r: (-r["score"], r["candidate_id"]))["candidate_id"] if eligible else None


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def schema_floor_rows(geometry_id, geometry, params, radius, groups):
    """Cold request serializer for the sealed unconditional linear RSI/SC schemas.

    Mirrors only active_neighbors' deterministic schema floor, never its numeric
    covariance fitter or financial evaluator. Reject all other schema shapes.
    """
    specs = geometry["parameters"]
    if (geometry["constraints"] or geometry["inactive"] or any(s["active_if"] or
            s["scale"] != "linear" or s["step"] is not None for s in specs)):
        raise ValueError("unsupported request schema; use the registered canonical designer")
    if digest(geometry) != geometry_id:
        raise ValueError("geometry identity differs")
    center_id = digest(dict(schema=geometry_id, effective=params))
    seen, rows = {center_id: -1}, []

    def add(changes, direction, clipped=False):
        requested, effective = params | changes, {}
        valid = True
        for s in specs:
            value = requested[s["name"]]
            if s["fixed"]:
                value = s["fixed_value"]
            elif s["categories"]:
                valid &= value in s["categories"]
            else:
                value = int(value) if s["kind"] == "integer" else float(value)
                valid &= s["low"] <= value <= s["high"]
            effective[s["name"]] = value
        cid = digest(dict(schema=geometry_id, effective=effective)) if valid else None
        duplicate = seen.get(cid) if valid else None
        status = "INFEASIBLE" if not valid else "COLLISION" if duplicate is not None else "READY"
        rows.append(dict(row_id=len(rows), direction=direction, requested=requested,
            effective=effective if valid else None, candidate_id=cid, status=status,
            duplicate_of=duplicate, clipped=clipped, reason="out_of_domain" if not valid else
            "boundary_clipped" if clipped else None))
        if valid:
            seen.setdefault(cid, len(rows)-1)

    def shift(s, sign):
        low, high = s["low"], s["high"]
        z = (params[s["name"]]-low)/(high-low) + sign*radius
        raw = low + min(1., max(0., z))*(high-low)
        if s["kind"] == "integer":
            raw = int(low + min(math.floor(high-low+1e-10), max(0, math.floor(raw-low+.5))))
        return raw, not 0 <= z <= 1

    numeric = {}
    for s in specs:
        name = s["name"]
        if s["fixed"]:
            continue
        if s["categories"]:
            for choice in s["categories"]:
                if choice != params[name]:
                    add({name: choice}, f"category:{name}")
            continue
        if s["high"] <= s["low"]:
            raise ValueError("variable numeric domain must have positive width")
        numeric[name] = s
        for sign in (-1, 1):
            value, clipped = shift(s, sign)
            add({name: value}, f"axis:{name}:{sign}", clipped)
            if s["kind"] == "integer":
                add({name: params[name]+sign}, f"adjacent:{name}:{sign}")
    for group in groups:
        for sign in (-1, 1):
            shifted = {name: shift(numeric[name], sign) for name in group}
            add({name: value for name, (value, _) in shifted.items()},
                "joint:"+",".join(group)+f":{sign}", any(clipped for _, clipped in shifted.values()))
    return rows


def bounded_neighborhood_requests(alpha, result, probes, evaluations):
    targets = BOUNDED_RECIPE["targets"][alpha]
    design = read(probes["parent_design"])
    originals = {r["candidate_id"]: r for r in design["rows"] if r["admitted"]}
    groups = probes["neighborhoods"][0]["coverage"]["joint_groups"]
    neighborhoods, executions = [], []
    for center, index in enumerate(targets):
        cid = result["candidate_ids"][index]
        params = originals[cid]["effective"]
        for role, radius, seed in (("selection_probe", .1, 732), ("local_validation", .12, 733)):
            rows = schema_floor_rows(probes["geometry_id"], probes["geometry"], params, radius, groups)
            nid = digest(dict(recipe=BOUNDED_RECIPE, parent_design_id=probes["parent_design_id"],
                parent_candidate_id=cid, role=role, radius=radius, seed=seed, rows=rows))
            for row in rows:
                row["execution_index"] = None
                if row["status"] != "READY":
                    continue
                request = dict(probes["executions"][0]["request"])
                request.update(params=row["effective"], candidate_id=row["candidate_id"], role=role,
                    design_id=nid, proposal_row=row["row_id"], parent_design_id=probes["parent_design_id"],
                    parent_candidate_id=cid, parent_panel_index=index, neighborhood_center=center,
                    probe_radius=radius, probe_seed=seed, probe_direction=row["direction"])
                matches = [dict(cell=r["cell"], paths=r["paths"], execution_key=r["execution_key"],
                    previous_index=r["index"], previous_center=r["center"]) for r in evaluations.values()
                    if r["candidate_id"] == row["candidate_id"] and r["role"] == role and r["status"] == "COMPLETE"]
                row["execution_index"] = len(executions)
                executions.append(dict(index=len(executions), center=center, role=role,
                    row_id=row["row_id"], candidate_id=row["candidate_id"], neighborhood_id=nid,
                    request=request, request_sha256=digest(request), compatible_coordinate_role_matches=matches,
                    status="COLD_REUSE_COMPATIBILITY_CHECK_REQUIRED" if matches else "MISSING_ACCOUNT_EVALUATION",
                    required_annual_views=list(ANNUAL), annual_views_status="NOT_RUN_AWAITING_ACTUAL_CONTINUOUS_PATH",
                    launch_authorized=False))
            selection = {r["candidate_id"] for r in rows if r["status"] == "READY"}
            neighborhoods.append(dict(center=center, original_index=index, parent_candidate_id=cid,
                role=role, radius=radius, seed=seed, neighborhood_id=nid, rows=rows,
                distinct_ready=len(selection), covariance_status=BOUNDED_RECIPE["covariance"],
                joint_groups=groups, scope="schema-floor requests only; not measured neighborhood coverage"))
    covariance_requests = [dict(original_index=index, candidate_id=result["candidate_ids"][index],
        request_type="FIT_EXISTING_DEVELOPMENT_CLOUD_THEN_REGISTER_CONDITIONAL_COVARIANCE_PROPOSALS",
        geometry_id=probes["geometry_id"], parent_design=probes["parent_design"],
        candidate_roster=result["candidate_ids"], eligibility="original whole-path quality/risk/support gates",
        cloud_policy="same categorical branch and schema distance <= .25; minimum 5 distinct and full numeric rank",
        recipe=dict(rho=.2, tau=.001, cloud_radius=.25, minimum_cloud=5,
            selection_radius=.1, validation_radius=.12, selection_seed=732, validation_seed=733,
            proposal_generator="existing active_neighbors_v1 np.default_rng normal/eigh; no replacement RNG",
            proposals_per_role="max(2, 2*active_numeric_dimensions) before feasibility/dedup"),
        status="FIT_AND_EXACT_DIRECTIONS_NOT_REGISTERED", financial_launch_authorized=False,
        fallback="schema-only only after measured sparse/singular support; no guessed fallback") for index in targets]
    return dict(recipe=BOUNDED_RECIPE, parent_geometry_id=probes["geometry_id"],
        targets=targets, neighborhoods=neighborhoods, executions=executions,
        covariance_requests=covariance_requests, future_annual_view_requests=3*len(executions),
        request_count=len(executions), new_account_requests=sum(not e["compatible_coordinate_role_matches"] for e in executions),
        reuse_check_requests=sum(bool(e["compatible_coordinate_role_matches"]) for e in executions),
        launches_authorized=False, financial_executions=0,
        entry_gates=["fresh financial resource/source/data/account registration before any launch",
            "cold exact-account/role/seed compatibility review before reusing any match",
            "constructor/effective-ID validation using the existing qualified route",
            "same gates and negative outcomes; no threshold or alpha changes",
            "seal local cloud/rank and conditional covariance proposals before a full union claim",
            "seal annual path views/common aggregate before any annual-local comparison"])


def lower_tail(values, alpha):
    if not values or not 0 < alpha <= 1 or not all(math.isfinite(v) for v in values):
        raise ValueError("complete finite equal-weight distribution required")
    mass, terms = alpha * len(values), []
    for value in sorted(values):
        used = min(1., mass)
        if used > 0:
            terms.append(value * used / (alpha * len(values)))
        mass = max(0., mass-used)
    return math.fsum(terms)


def annual_replay(result, grid):
    """Independent scalar oracle; retain the canonical decisions verbatim."""
    preferences = result["preferences"]
    versions = {f["version"]: f["coefficients"] for f in preferences["formulas"]}
    decisions = result["selector_diagnostics"]["canonical_comparison"]["decisions"]
    for decision in decisions:
        if decision["compared_candidate_ids"] != result["candidate_ids"]:
            raise ValueError("canonical decision roster differs")
        rows = decision["component_rows"]
        if [r["candidate_id"] for r in rows] != result["candidate_ids"]:
            raise ValueError("all canonical components must remain visible")
        version, p = decision["formula_version"], versions[decision["formula_version"]]
        for row in rows:
            cid = row["candidate_id"]
            values = [metric(grid[cid, e], "economic_utility") for e in ANNUAL]
            eligible = all(all(gates(grid[cid, e], preferences).values()) for e in ANNUAL)
            if row["eligible"] != eligible:
                raise ValueError("canonical gate mismatch")
            if None in values:
                if row["score"] is not None:
                    raise ValueError("undefined annual score cannot be ranked")
                continue
            floor, mean = min(values), math.fsum(values)/3
            median = sorted(values)[1]
            mad = sorted(abs(x-median) for x in values)[1]
            if version == "environment_floor_mean_v1":
                score = floor + p["mean"]*mean - preferences["activity_penalty"]
            elif version == "environment_lower_tail_v2":
                tail = lower_tail(values, p["alpha"])
                score = p["floor"]*floor + p["tail"]*tail - p["dispersion"]*mad - preferences["activity_penalty"]
            elif version == "pareto_chebyshev_v1":
                ref = preferences["pareto"]
                if ref["ideal"] <= ref["worst"] or ref["directions"] != 1:
                    raise ValueError("fixed nonzero maximize reference required")
                gaps = [(ref["ideal"]-x)/(ref["ideal"]-ref["worst"]) for x in values]
                score = -(max(gaps)*ref["weights"] + p["rho"]*sum(gaps)*ref["weights"])
            else:
                raise ValueError("unregistered replay formula")
            if not math.isclose(score, row["score"], rel_tol=1e-12, abs_tol=1e-14):
                raise ValueError("canonical numerical score mismatch")
        if version == "pareto_chebyshev_v1":
            eligible_rows = [r for r in rows if r["eligible"]]
            front = []
            for row in eligible_rows:
                values = [metric(grid[row["candidate_id"], e], "economic_utility") for e in ANNUAL]
                dominated = any(all(a >= b for a, b in zip(other["values"], values)) and
                    any(a > b for a, b in zip(other["values"], values)) for other in eligible_rows)
                if not dominated:
                    front.append(row["candidate_id"])
            if set(front) != set(decision["pareto_candidate_ids"]):
                raise ValueError("canonical eligible front mismatch")
            ranking = [r for r in rows if r["candidate_id"] in front]
        else:
            ranking = rows
        if best(ranking) != decision["chosen_candidate"]:
            raise ValueError("canonical selected candidate mismatch")
    return decisions


def raw_control(result, grid, sealed):
    rows = [dict(candidate_id=c, score=metric(grid[c, "whole_path"], "sharpe"),
        eligible=metric(grid[c, "whole_path"], "sharpe") is not None,
        status=grid[c, "whole_path"]["status"],
        null_reasons=grid[c, "whole_path"]["null_reasons"],
        gates_post_choice=gates(grid[c, "whole_path"], result["preferences"])) for c in result["candidate_ids"]]
    chosen = best(rows)
    if chosen != sealed["chosen_candidate"]:
        raise ValueError("raw-Sharpe control changed")
    return dict(formula_id="raw_original_whole_path_sharpe_v1", chosen_candidate=chosen,
        status="SELECTED_UNQUALIFIED_CONTROL" if chosen else "NO_SELECTION",
        compared_candidate_ids=result["candidate_ids"], component_rows=rows,
        tie_break=result["preferences"]["tie_break"],
        outcome=outcome(grid, chosen, result["preferences"]))


def local_row(center, neighborhood, evaluations, preferences, objective):
    if neighborhood["role"] not in ("selection_probe", "local_validation"):
        raise ValueError("registered probe role required")
    expected = {r["execution_index"]: r for r in neighborhood["rows"] if r["status"] == "READY"}
    if len(expected) != sum(r["status"] == "READY" for r in neighborhood["rows"]):
        raise ValueError("unique READY execution indices required")
    coverage = neighborhood["coverage"]
    missing, failed, utilities, probe_gates = [], [], [], []
    refs = []
    for index, proposal in expected.items():
        result = evaluations.get(index)
        if result is None:
            missing.append(index)
            continue
        if (result["center"] != center["center"] or result["role"] != neighborhood["role"] or
                result["candidate_id"] != proposal["candidate_id"] or
                result.get("direction") != proposal["direction"]):
            raise ValueError("probe candidate/role/direction mismatch")
        m = result["metrics"]
        if result["status"] != "COMPLETE" or m["return_status"] != "VALID":
            failed.append(index)
            continue
        if (m["account_mode"] != "continuous_development_2021_2023" or m["daily_count"] != 1095 or
                not math.isfinite(result["utility"]) or result["utility"] != m["economic_utility"]):
            raise ValueError("complete same-channel whole-path probe required")
        utilities.append(result["utility"])
        probe_gates.append(0 <= m["max_drawdown"] <= preferences["risk_drawdown_max"] and
            result["utility"] >= objective["quality_floor"] and
            m["daily_count"] >= preferences["minimum_daily_count"])
        refs.append(dict(index=index, candidate_id=result["candidate_id"], cell=result["cell"], paths=result["paths"]))
    c = center["metrics"]
    if c["account_mode"] != "continuous_development_2021_2023" or c["daily_count"] != 1095:
        raise ValueError("center/probe aggregate mismatch")
    complete = bool(expected) and not missing and not failed and coverage["status"] == "OBSERVED_REQUIRED_RADII"
    if coverage["uncovered_axes"] or coverage["uncovered_groups"]:
        complete = False
    worst = min(c["economic_utility"], *utilities) if complete else None
    downside = max(0., c["economic_utility"]-worst) if complete else None
    center_pass = (c["economic_utility"] >= objective["quality_floor"] and
        0 <= c["max_drawdown"] <= preferences["risk_drawdown_max"] and
        c["daily_count"] >= preferences["minimum_daily_count"])
    eligible = complete and center_pass and all(probe_gates)
    reasons = ([] if complete else ["INCOMPLETE_LOCAL_EVIDENCE"])
    if not center_pass:
        reasons.append("CENTER_QUALITY_RISK_SUPPORT_FAIL")
    if complete and not all(probe_gates):
        reasons.append("ALL_PROBE_QUALITY_RISK_SUPPORT_FAIL")
    return dict(candidate_id=center["candidate_id"], index=center["panel_index"],
        center=center["center"], role=neighborhood["role"],
        eligible=eligible, reasons=reasons, score=worst,
        components=dict(center_utility=c["economic_utility"], max_downside=downside,
            gamma=1, activity_penalty=0, empirical_worst_utility=worst,
            reference_id=objective["reference_id"], reference_scale=objective["reference_scale"],
            unit=objective["unit"], aggregate="whole_path", actual_days=1095),
        evidence_complete=complete, expected_probes=len(expected), valid_probes=len(utilities),
        missing=missing, failed=failed, coverage=coverage,
        quality_survival_fraction=sum(u >= objective["quality_floor"] for u in utilities)/len(expected) if expected else None,
        covariance_status=neighborhood["covariance_status"], covariance_cloud=center["covariance"],
        representative_kind="actually_evaluated_registered_center", representative=center["cell"], evidence_refs=refs,
        status="INSUFFICIENT_COVERAGE" if not complete else "OBSERVED_QUALITY_BASIN" if eligible else "FRAGILE_CENTER")


def local_comparison(registration, evaluations, preferences):
    objective = registration["objective"]
    if (objective["metric"] != "economic_utility" or objective["unit"] != "decimal_return"
            or objective["reference_scale"] != 1 or objective["quality_floor"] != 0):
        raise ValueError("sealed local preference/reference required")
    centers = {c["center"]: c for c in registration["centers"]}
    neighborhoods = {(n["center"], n["role"]): n for n in registration["neighborhoods"]}
    if (len(centers) != 2 or len(registration["centers"]) != 2 or
            len(neighborhoods) != 4 or len(registration["neighborhoods"]) != 4 or
            set(neighborhoods) != {(i, role) for i in centers for role in ("selection_probe", "local_validation")}):
        raise ValueError("exact registered two-center/two-role roster required")
    if set(evaluations) - {e["index"] for e in registration["executions"]}:
        raise ValueError("unexpected probe execution")
    selection = [local_row(c, neighborhoods[i, "selection_probe"], evaluations, preferences, objective)
        for i, c in sorted(centers.items())]
    chosen = best(selection) if all(r["evidence_complete"] for r in selection) else None
    # The decision is frozen before the validation tranche is inspected.
    validation = [local_row(c, neighborhoods[i, "local_validation"], evaluations, preferences, objective)
        for i, c in sorted(centers.items())]
    overlap = []
    for i, center in sorted(centers.items()):
        used = {r["point"]["effective_json"] for r in neighborhoods[i, "selection_probe"]["rows"] if r["status"] == "READY"}
        held = {r["point"]["effective_json"] for r in neighborhoods[i, "local_validation"]["rows"] if r["status"] == "READY"}
        if neighborhoods[i, "selection_probe"]["seed"] == neighborhoods[i, "local_validation"]["seed"]:
            raise ValueError("distinct role seeds required")
        overlap.append(dict(candidate_id=center["candidate_id"], ready_selection=len(used),
            ready_validation=len(held), overlapping_effective=len(used & held), held_distinct=len(held-used),
            producer_held_support=center["held_support"], temporal_oos=False, independent_overlaps=False))
    return dict(formula_id="local_downside_v1", requested_selector="full_sam_basin",
        resolved_selector="registered_two_center_whole_path_local_v1", gamma=1,
        aggregate="whole_path", compared_candidate_ids=[c["candidate_id"] for c in centers.values()],
        chosen_candidate=chosen, pre_quality_numeric_best=best([dict(r, eligible=r["evidence_complete"]) for r in selection]),
        status="SELECTED_LIMITED_ROSTER" if chosen else "NO_SELECTION" if all(r["evidence_complete"] for r in selection) else "NOT_EVALUABLE",
        component_rows=selection, validation_post_decision=validation, overlap=overlap,
        tie_break="candidate_id_lexicographic_v1", fallback="explicit schema-only when registered sparse covariance cloud",
        full_panel_local_status="NOT_EVALUABLE", annual_local_status="NOT_EVALUABLE",
        claim="finite registered centers only; neither full-panel nor annual local contest")


def requests_for(alpha, result, grid, probe_registration, evaluations, local, raw):
    centers = {c["candidate_id"] for c in probe_registration["centers"]}
    decisions = result["selector_diagnostics"]["canonical_comparison"]["decisions"]
    controls = {c for c in [raw["chosen_candidate"], *[d["chosen_candidate"] for d in decisions]] if c}
    missing = [c for c in result["candidate_ids"] if c not in centers]
    design_rows = {r["candidate_id"]: r for r in read(probe_registration["parent_design"])["rows"] if r["admitted"]}
    annual_eligible = [c for c in result["candidate_ids"] if
        all(all(gates(grid[c, e], result["preferences"]).values()) for e in ANNUAL)]
    candidates = [dict(candidate_id=c, index=grid[c, "whole_path"]["index"],
        needed_for="matched control/winner local contrast" if c in controls else "only if full-panel local contest is requested",
        needed_for_annual_gated_local=c in annual_eligible, registered_candidate=design_rows[c],
        annual_gates={e: gates(grid[c, e], result["preferences"]) for e in ANNUAL},
        identity=grid[c, "whole_path"]["provenance"],
        request_type="REGISTER_NEIGHBOR_DESIGN_THEN_EVALUATE_MISSING_FEASIBLE_COORDINATES",
        status="DESIGN_NOT_REGISTERED_NO_EXACT_NEIGHBOR_COORDINATES_AVAILABLE",
        geometry_id=probe_registration["geometry_id"], parent_design=probe_registration["parent_design"],
        requirements=["same source/data/account/cost/utility contract", "freeze schema signed/adjacent/category/joint coverage",
            "same probe budget policy; covariance only with local support, otherwise explicit schema-only",
            "separate selection and held seeds/directions; record clipping/aliases/infeasible points",
            "reuse only exact role-compatible executions; no invented centroid or annual account reset"])
        for c in missing]
    annual = []
    for execution in probe_registration["executions"]:
        e = evaluations.get(execution["index"])
        for env in ANNUAL:
            annual.append(dict(alpha=alpha, candidate_id=execution["candidate_id"],
                center=execution["center"], role=execution["role"], execution_index=execution["index"],
                environment_id=env, exact_execution_request=execution["request"],
                source_cell=e["cell"] if e else None, source_path=e["paths"] if e else None,
                status="MISSING_SEALED_ANNUAL_METRIC_VIEW",
                request_type="REDUCE_RETAINED_CONTINUOUS_PATH_NO_ACCOUNT_RERUN" if e else "MISSING_REGISTERED_EXECUTION",
                required_metrics=["economic_utility", "net_return", "drawdown", "daily_loss_es", "daily_count"],
                aggregate_contract="freeze same annual aggregate/weights for center and all neighbors before local ranking"))
    return dict(alpha=alpha, launches_authorized=False, new_financial_work=0,
        full_panel_unprobed_candidate_count=len(missing), candidate_requests=candidates,
        minimal_matched_control_indices=[grid[c, "whole_path"]["index"] for c in missing if c in controls],
        annual_gate_eligible_indices=[grid[c, "whole_path"]["index"] for c in annual_eligible],
        annual_local_eligible_unprobed_indices=[grid[c, "whole_path"]["index"] for c in missing if c in annual_eligible],
        annual_view_requests=annual, annual_views_available=False,
        existing_registered_missing_execution_indices=sorted({e["index"] for e in probe_registration["executions"]}-set(evaluations)),
        preserved_whole_path_centers=[r["index"] for r in local["component_rows"]],
        scope_note="candidate requests are design prerequisites, not fabricated exact neighbor execution manifests")


def load_inputs(registration):
    roots = {name: read(record) for name, record in registration["root_seals"].items()}
    analytic = {Path(p["path"]).name: p for p in roots["analyst_final_manifest_01.json"]["files"]}
    rsi_pins = {Path(p["path"]).name: p for p in roots["rsi_probes_final_receipt.json"]["retained_manifest"]}
    rsi_summary = read(rsi_pins["rsi_probes_summary.json"])
    sc_summary = read(roots["sc_probes_closeout_receipt_01.json"]["summary"])
    rsi_registration = read(rsi_summary["registration"])
    sc_registration = read(sc_summary["registration"])
    rsi_panel = read(rsi_summary["panel"])
    inputs = dict(rsi=(read(analytic["analyst_results_02.json"]), rsi_registration,
            rsi_panel["execution_results"], read(rsi_summary["local_summary"])["center_role_summaries"]),
        sc=(read(analytic["analyst_results_sc_01.json"]), sc_registration,
            sc_summary["results"], sc_summary["local_summaries"]))
    period = read(analytic["analyst_period_results_01.json"])
    for result, probes, rows, _ in inputs.values():
        checked(probes["parent_design"])
        for c in probes["centers"]:
            checked(c["cell"])
        for r in rows:
            checked(r["cell"])
            checked(r["paths"])
    return inputs, period["raw_sharpe_controls"]


def analyze(registration):
    inputs, controls = load_inputs(registration)
    reports, requests = {}, {}
    for alpha, (result, probes, execution_rows, summaries) in inputs.items():
        grid = grid_for(result)
        annual = annual_replay(result, grid)
        control = raw_control(result, grid, controls["A-" + alpha.upper()])
        evaluations = {r["index"]: r for r in execution_rows}
        if len(evaluations) != len(execution_rows):
            raise ValueError("duplicate execution result")
        for c in probes["centers"]:
            row = grid[c["candidate_id"], "whole_path"]
            if c["panel_index"] != row["index"] or c["metrics"]["economic_utility"] != metric(row, "economic_utility"):
                raise ValueError("local center not the original actual candidate")
        for e in probes["executions"]:
            r = evaluations.get(e["index"])
            if r:
                if any(e[k] != r[k] for k in ("center", "role", "candidate_id", "row_id")):
                    raise ValueError("execution request/result differs")
                cell = read(r["cell"])
                if cell["request"] != e["request"] or cell["metrics"] != r["metrics"]:
                    raise ValueError("sealed producer cell/request/metrics differs")
            if e["request"]["start"] != "2021-01-01" or e["request"]["stop"] != "2024-01-01":
                raise ValueError("development-only request required")
        local = local_comparison(probes, evaluations, result["preferences"])
        for row in local["component_rows"] + local["validation_post_decision"]:
            sealed = next(s for s in summaries if (s["center"], s["role"]) == (row["center"], row["role"]))
            if (row["score"] != sealed["empirical_worst_utility"] or
                    row["components"]["max_downside"] != sealed["max_downside"] or row["status"] != sealed["status"]):
                raise ValueError("local result differs from original producer summary")
        side_by_side = [dict(recipe="raw_sharpe", scope="original_128_whole_path_unqualified_control",
            chosen_index=control["outcome"]["index"], status=control["status"])]
        side_by_side += [dict(recipe=d["formula_version"], scope="original_128_annual_gated",
            chosen_index=grid[d["chosen_candidate"], "whole_path"]["index"] if d["chosen_candidate"] else None,
            status=d["status"]) for d in annual]
        side_by_side.append(dict(recipe="local_downside_v1", scope="registered_two_centers_whole_path_gated",
            chosen_index=grid[local["chosen_candidate"], "whole_path"]["index"] if local["chosen_candidate"] else None,
            status=local["status"]))
        reports[alpha] = dict(candidate_count=128, side_by_side=side_by_side, preferences=result["preferences"],
            inherited_annual_decisions=annual, raw_sharpe=control, local=local,
            inherited_selector_diagnostics=result["selector_diagnostics"],
            annual_outcomes={d["formula_version"]: outcome(grid, d["chosen_candidate"], result["preferences"]) for d in annual},
            clean_oos=False, selector_superiority_claim=False)
        requests[alpha] = requests_for(alpha, result, grid, probes, evaluations, local, control)
        requests[alpha]["bounded_neighborhood_manifest"] = bounded_neighborhood_requests(alpha, result, probes, evaluations)
        for candidate in requests[alpha]["candidate_requests"]:
            if candidate["index"] in BOUNDED_RECIPE["targets"][alpha]:
                candidate["status"] = "SCHEMA_FLOOR_REQUEST_DESIGN_REGISTERED_COVARIANCE_PENDING"
                candidate["request_type"] = "EXECUTE_ONLY_AFTER_FINANCIAL_ENTRY_GATES_AND_UNION_DESIGN_DISPOSITION"
                candidate["bounded_recipe_version"] = BOUNDED_RECIPE["version"]
    return dict(schema="m5111_selector_only_checkpoint_v1", created_at=now(),
        reports=reports, financial_executions=0, builds=0, phase_complete=False,
        status="COLD_REPLAY_COMPLETE_LOCAL_SCOPE_INCOMPLETE", full_goal_complete=False), requests


def verify_prior(registration, *, strict=True):
    failures = []
    for record in registration["protected_prior_files"]:
        try:
            checked(record)
        except (ValueError, OSError) as exc:
            failures.append(dict(path=record["path"], error=str(exc)))
    if strict and failures:
        raise ValueError(f"prior custody verification failed: {failures}")
    return dict(verified=len(registration["protected_prior_files"])-len(failures), hash_failures=len(failures), failures=failures)


def run(lane, attempt):
    if len(attempt) != 2 or not attempt.isdigit():
        raise ValueError("two-digit append-only cold attempt required")
    registration_pin = pin(lane / "registration_01.json")
    registration = read(registration_pin)
    before = resources(lane)
    if before["free_bytes"] < registration["budget"]["reserve_bytes"] + (32+256)*MIB:
        raise ValueError("reserve plus budget required before analysis/tests")
    previous = [pin(p) for p in sorted(lane.rglob("*")) if p.is_file()]
    prereg = write_new(lane / f"cold_run_registration_{attempt}.json", dict(created_at=now(),
        registration=registration_pin, source=pin(__file__), tests=pin("tests/test_mode5_selector_checkpoint.py"),
        resources_before=before, scratch_paths=[], retained_fixture_root=str(lane / "cold-fixtures"),
        previous_lane_files=previous, command=registration["tests"],
        bounded_missing_evidence_recipe=BOUNDED_RECIPE,
        financial_imports_authorized=False, financial_launches_authorized=False))
    status, error, test_result = "FAIL", None, None
    try:
        verified = verify_prior(registration)
        report, requests = analyze(registration)
        report["registration"] = registration_pin
        report["prior_custody"] = verified
        write_new(lane / f"comparison_{attempt}.json", report)
        write_new(lane / f"missing_evidence_requests_{attempt}.json", requests)
        test_result = subprocess.run(registration["tests"], capture_output=True, text=True, check=False)
        write_new(lane / f"tests_{attempt}.json", dict(command=registration["tests"],
            returncode=test_result.returncode, stdout=test_result.stdout, stderr=test_result.stderr))
        if test_result.returncode:
            raise ValueError("scoped cold suite failed; original logs retained")
        status = "PASS"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        write_new(lane / f"failure_{attempt}.json", dict(created_at=now(), error=error, phase_pass=False))
    finally:
        after_verification = verify_prior(registration, strict=False)
        try:
            for record in previous:
                checked(record)
            checked(read(prereg)["source"])
            checked(read(prereg)["tests"])
        except (ValueError, OSError) as exc:
            status, error = "FAIL", str(exc)
        if after_verification["hash_failures"]:
            status, error = "FAIL", "prior custody changed; see cleanup verification failures"
        retained = [pin(p) for p in sorted(lane.rglob("*")) if p.is_file()]
        retained_bytes = sum(p["bytes"] for p in retained)
        after = resources(lane)
        if retained_bytes >= 256*MIB or after["free_bytes"] < 5*1024**3:
            status, error = "FAIL", "retained/reserve budget failed"
        write_new(lane / f"cleanup_{attempt}.json", dict(created_at=now(), status=status,
            deleted_paths=[], deleted_bytes=0, scratch_bytes=0, retained_bytes_before_receipt=retained_bytes,
            retained_cap_pass=retained_bytes < 256*MIB, reserve_pass=after["free_bytes"] >= 5*1024**3,
            resources_before=before, resources_after=after,
            observed_free_byte_change=after["free_bytes"]-before["free_bytes"],
            observed_change_is_attributable_to_deletion=False, prior_custody=after_verification,
            preserved_environment=registration["cleanup_inventory"]["retained_environment"],
            source=pin(__file__), cold_run_registration=prereg, retained_manifest=retained,
            financial_executions=0, builds=0, error=error))
    if status != "PASS":
        raise ValueError(error)
    return dict(status=status, lane=str(lane), prior_verified=after_verification["verified"],
        retained_bytes=retained_bytes, tests_returncode=test_result.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "run"))
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--lane", type=Path, required=True)
    parser.add_argument("--attempt", default="01")
    args = parser.parse_args()
    result = register(args.parent, args.lane) if args.command == "register" else run(args.lane.resolve(), args.attempt)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

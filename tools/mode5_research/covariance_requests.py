"""Register four cold cloud fits and their exact bounded neighborhood union.

The original geometry, covariance/proposal owner and RNG are used unchanged.
Existing schema requests keep their identities; the union is a sealed overlay,
not an execution receipt, reuse authorization or whole-128 probe expansion.
"""

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import importlib
from importlib.machinery import ModuleSpec
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import traceback
from types import ModuleType

from tools.mode5_research import selector_checkpoint as custody


ROOT = Path(__file__).resolve().parents[2]
MIB = 1024**2
REQUEST_SHA = "f23b1b3cae547cf6868c22bac743c4e73f22e2ebbb53004010133a23206bd3ba"
ORIGINAL_SOFTWARE = {
    "src/quantbt/mode5/geometry/schema.py": "0ef9627726d78bb02f9a3fb8773e5d3b377e7c0353cf9bd965df31de6e8b73d1",
    "tools/mode5_geometry/design.py": "e0f8957604696457eca39a8346ef113e7a7e23273df2a2b7d1910b43971adfea",
    "tools/mode5_geometry/neighborhoods.py": "2743b218494d369011edf3ec106c46f0b873e19b6657f93bb22d738434574922",
}
RECIPE = dict(cloud_radius=.25, minimum_cloud=5, rho=.2, tau=.001,
    selection_radius=.1, validation_radius=.12, selection_seed=732, validation_seed=733,
    proposal_generator="existing active_neighbors_v1 np.default_rng normal/eigh; no replacement RNG",
    proposals_per_role="max(2, 2*active_numeric_dimensions) before feasibility/dedup")
QUALIFICATION = dict(minimum_days=365, quality_floor=0., max_drawdown=.5,
                     minimum_fills_if_available=30, minimum_closed_campaigns_if_available=20)
TARGETS = dict(rsi=[10, 49, 114], sc=[33])
ROLES = (("selection_probe", .1, 732), ("local_validation", .12, 733))
THREADS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS",
           "NUMBA_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS", "RAYON_NUM_THREADS")
PACKAGES = ("quantbt", "quantbt.mode5", "quantbt.mode5.geometry", "quantbt.mode5.diagnostics",
            "quantbt.optimization", "tools.mode5_geometry", "tools.mode5_diagnostics")
ALLOWED = ("quantbt.mode5.geometry.schema", "quantbt.mode5.diagnostics.identity",
           "quantbt.optimization.parameter_space", "quantbt.optimization.space")


def forbidden(name):
    if name.startswith("_quantbt_native"):
        return True
    if name.startswith("quantbt.") and name not in PACKAGES:
        return not any(name == p or name.startswith(p+".") for p in ALLOWED)
    return name.startswith("upgrade.local.")


class ColdImports:
    def find_spec(self, fullname, path=None, target=None):
        if forbidden(fullname):
            raise ImportError("cold covariance requests prohibit runtime import: " + fullname)
        return None


def numeric_owner():
    if any(forbidden(name) for name in sys.modules):
        raise RuntimeError("fresh cold process required")
    if not any(isinstance(f, ColdImports) for f in sys.meta_path):
        sys.meta_path.insert(0, ColdImports())
    for name in PACKAGES:
        if name not in sys.modules:
            package = ModuleType(name)
            base = ROOT / "src" if name.startswith("quantbt") else ROOT
            package.__path__ = [str(base / name.replace(".", "/"))]
            package.__spec__ = ModuleSpec(name, loader=None, is_package=True)
            package.__spec__.submodule_search_locations = package.__path__
            package._cov_fit_cold_namespace = True
            sys.modules[name] = package
        elif not getattr(sys.modules[name], "_cov_fit_cold_namespace", False):
            raise RuntimeError("fresh namespace required: " + name)
    return importlib.import_module("tools.mode5_geometry.neighborhoods")


def load_geometry(metadata, expected_id):
    numeric_owner()
    from quantbt.mode5.geometry.schema import EffectiveGeometry, OrderedConstraint
    from quantbt.optimization.parameter_space import ParameterSpec
    specs = tuple(ParameterSpec(s["name"], s["kind"], s["low"], s["high"], s["step"],
        s["scale"] == "log", tuple(s["categories"]), tuple((k, tuple(v)) for k, v in s["active_if"].items()),
        s["fixed"], s["fixed_value"]) for s in metadata["parameters"])
    geometry = EffectiveGeometry(specs, tuple(metadata["weights"].items()), tuple(metadata["inactive"].items()),
        tuple(metadata["casts"].items()), tuple(OrderedConstraint(tuple(c["names"]), c["strict"]) for c in metadata["constraints"]),
        metadata["version"])
    if geometry.metadata() != metadata or geometry.identity != expected_id:
        raise ValueError("hydrated original geometry identity differs")
    return geometry


def qualify(row, policy):
    if policy != QUALIFICATION:
        raise ValueError("original whole-path cloud gates required")
    m, support = row["metrics"], row["support"]
    return (row["status"] == "PASS" and m["daily_count"] >= policy["minimum_days"]
        and m["economic_utility"] is not None and math.isfinite(m["economic_utility"])
        and m["economic_utility"] >= policy["quality_floor"] and m["max_drawdown"] is not None
        and 0 <= m["max_drawdown"] <= policy["max_drawdown"]
        and all(support.get(name) is None or support[name] >= policy[key] for name, key in
            (("fills", "minimum_fills_if_available"), ("closed_campaigns", "minimum_closed_campaigns_if_available"))))


def cloud_for(geometry, center, ranked, recipe):
    if recipe != RECIPE:
        raise ValueError("original frozen covariance recipe required")
    return tuple(v["point"] for v in ranked if v["point"].active_names == center.active_names
        and all(v["point"].params[s.name] == center.params[s.name] for s in geometry.specs if s.choices and s.name in center.params)
        and geometry.distance(center, v["point"]) <= recipe["cloud_radius"])


def serialize(row):
    result = asdict(row)
    result.update(candidate_id=row.point.identity if row.point else None,
        requested=json.loads(row.requested_json), effective=row.point.params if row.point else None,
        clipped=row.reason == "boundary_clipped", execution_index=None)
    return result


def require_schema_prefix(rows, sealed):
    prefix = [r for r in rows if not r["direction"].startswith("covariance:")]
    if len(prefix) != len(sealed):
        raise ValueError("original schema-floor prefix length differs")
    for actual, original in zip(prefix, sealed):
        if any(actual[k] != original[k] for k in ("row_id", "direction", "requested", "effective",
                                                 "status", "candidate_id", "duplicate_of", "clipped")):
            raise ValueError("original schema-floor direction/coordinate/dedup differs")


def verify_historical_neighborhoods(geometry, probes, ranked):
    owner = numeric_owner()
    verified = 0
    for center in probes["centers"]:
        point = geometry.resolve(json.loads(center["point"]["effective_json"]))
        cloud = cloud_for(geometry, point, ranked, RECIPE)
        if [p.identity for p in cloud] != center["covariance"]["cloud_ids"]:
            raise ValueError("original historical cloud order/membership differs")
        for sealed in probes["neighborhoods"]:
            if sealed["center"] != center["center"]:
                continue
            groups = tuple(tuple(g) for g in sealed["coverage"]["joint_groups"])
            actual = owner.active_neighbors(geometry, point, radius=sealed["radius"], seed=sealed["seed"],
                role=sealed["role"], minimum_radius=.05, joint_groups=groups, cloud=cloud,
                rho=.2, tau=.001, minimum_cloud=5, cloud_radius=.25)
            if actual.covariance_status != sealed["covariance_status"] or actual.coverage != sealed["coverage"]:
                raise ValueError("historical original-owner coverage/covariance disposition differs")
            if len(actual.rows) != len(sealed["rows"]):
                raise ValueError("historical neighborhood proposal length differs")
            for row, original in zip(actual.rows, sealed["rows"]):
                serialized = json.loads(json.dumps(asdict(row)))
                if any(serialized[key] != original[key] for key in serialized):
                    raise ValueError("historical exact neighborhood direction differs")
            verified += 1
    return verified


def union_requests(rows, original_neighborhood, original_executions, template, nid, center, index):
    require_schema_prefix(rows, original_neighborhood["rows"])
    by_row = {e["row_id"]: e for e in original_executions if e["neighborhood_id"] == original_neighborhood["neighborhood_id"]}
    requests = []
    for row in rows:
        if row["status"] != "READY":
            row["disposition"] = "retained infeasible/center/within-role alias; no execution or independent support"
            continue
        prior = by_row.get(row["row_id"])
        if prior is not None:
            request = deepcopy(prior["request"])
            if custody.digest(request) != prior["request_sha256"]:
                raise ValueError("original schema request digest differs")
            source = "PRESERVED_SEALED_SCHEMA_REQUEST"
        else:
            if not row["direction"].startswith("covariance:"):
                raise ValueError("schema READY row lacks preserved request")
            request = deepcopy(template)
            request.update(params=row["effective"], candidate_id=row["candidate_id"], role=original_neighborhood["role"],
                design_id=nid, proposal_row=row["row_id"], parent_candidate_id=original_neighborhood["parent_candidate_id"],
                parent_panel_index=index, neighborhood_center=center, probe_radius=original_neighborhood["radius"],
                probe_seed=original_neighborhood["seed"], probe_direction=row["direction"])
            source = "NEW_COVARIANCE_ROLE_REQUEST_NO_ACCOUNT_EVIDENCE"
        row["execution_index"] = len(requests)
        requests.append(dict(index=len(requests), center=center, original_index=index, role=request["role"],
            row_id=row["row_id"], candidate_id=row["candidate_id"], request=request, request_sha256=custody.digest(request),
            request_design_id=request["design_id"], union_design_id=nid, source=source,
            original_schema_execution=deepcopy(prior) if prior is not None else None,
            launch_authorized=False, execution_status="NOT_EXECUTED_BY_COV_FIT",
            required_annual_views=list(custody.ANNUAL), annual_views_available=False))
    if len({r["candidate_id"] for r in requests}) != len(requests):
        raise ValueError("within-role union must use original effective-coordinate dedup")
    return requests


def register(parent, lane):
    parent, lane = Path(parent).resolve(), Path(lane).resolve()
    step = parent / "goal-step1"
    if lane != step / "cov-fit01" or lane.exists():
        raise ValueError("new exact goal-step1/cov-fit01 lane required")
    before = custody.resources(parent)
    if before["free_bytes"] < 5*1024**3 + 160*MIB or not before["free_inodes"]:
        raise ValueError("reserve plus bounded incremental budget required")
    original_pin = custody.pin(step / "registration_01.json")
    original = custody.read(original_pin)
    verified = custody.verify_prior(original)
    if verified["verified"] != 4752:
        raise ValueError("historical 4,752-pin custody required")
    requests_pin = custody.pin(step / "missing_evidence_requests_08.json")
    if requests_pin["sha256"] != REQUEST_SHA:
        raise ValueError("accepted four-fit/195-request seal required")
    requests = custody.read(requests_pin)
    for alpha in TARGETS:
        fits = requests[alpha]["bounded_neighborhood_manifest"]["covariance_requests"]
        if [f["original_index"] for f in fits] != TARGETS[alpha] or any(f["recipe"] != RECIPE for f in fits):
            raise ValueError("exact four original fit requests required")
    prior = [custody.pin(p) for p in sorted(step.rglob("*")) if p.is_file()]
    software_paths = [ROOT / path for path in ORIGINAL_SOFTWARE]
    software_paths.extend(ROOT / path for path in ("tools/mode5_geometry/schema.py",
        "tools/mode5_research/selector_checkpoint.py", "src/quantbt/optimization/parameter_space.py",
        "src/quantbt/optimization/space.py", "src/quantbt/mode5/diagnostics/identity.py",
        "tools/mode5_diagnostics/identity.py"))
    software = [custody.pin(path) for path in software_paths]
    for path, expected in ORIGINAL_SOFTWARE.items():
        if custody.pin(ROOT / path)["sha256"] != expected:
            raise ValueError("original geometry/proposal owner changed: " + path)
    return custody.write_new(lane / "registration_01.json", dict(schema="m5111_covariance_request_registration_v1",
        created_at=custody.now(), authority="owner four-fit cold sidecar after annual639 commit 78e57e3",
        timing="reviewed original development only; current-knowledge registration, not untouched OOS",
        original_registration=original_pin, original_custody=verified, prior_step_files=prior,
        requests=requests_pin, targets=TARGETS, recipe=RECIPE, qualification=QUALIFICATION,
        minimum_radius=.05, software=software, resources_before=before,
        union_policy="preserve 195 exact schema requests; conditional covariance ledger uses original center/within-role dedup; cross-role coordinates remain dependent",
        request_identity_policy="union_design_id is overlay custody; preserved schema request design_id is never rewritten",
        budget=dict(scratch_bytes=32*MIB, retained_bytes=128*MIB, reserve_bytes=5*1024**3),
        cleanup_inventory=dict(scratch_paths=[], eligible_deletions=[], retained_lane=str(lane),
            exclusions=["all prior receipts including failures", "all source/data", "all environments/caches"],
            process_review="sandbox process view only; no worker or deletion"),
        tests=[str(Path(sys.executable).absolute()), "-B", "-m", "unittest", "discover", "-s", "tests",
               "-p", "test_mode5_covariance_requests.py", "-v"],
        write_set=["tools/mode5_research/covariance_requests.py", "tests/test_mode5_covariance_requests.py", str(lane)],
        whole_128_probe_expansion=False, financial_executions=0, builds=0, installs=0, launches_authorized=False))


def analyze(registration):
    if (registration["recipe"] != RECIPE or registration["qualification"] != QUALIFICATION
            or registration["targets"] != TARGETS or registration["minimum_radius"] != .05):
        raise ValueError("unapproved fit policy")
    original = custody.read(registration["original_registration"])
    inputs, _ = custody.load_inputs(original)
    requests = custody.read(registration["requests"])
    pool = {r["path"]: r for r in original["protected_prior_files"]}
    owner = numeric_owner()
    import numpy as np
    from tools.mode5_geometry.design import design_identity
    fit_rows, neighborhoods, executions, historical_checks = [], [], [], {}
    for alpha, (result, probes, evaluations, _) in inputs.items():
        geometry = load_geometry(probes["geometry"], probes["geometry_id"])
        policy_receipt = custody.read(probes["analysis_registration"])
        if any(policy_receipt["center_policy"][k] != v for k, v in QUALIFICATION.items()):
            raise ValueError("original registered whole-path cloud gates differ")
        parent = custody.read(probes["parent_panel"])
        parent_rows = parent["rows"] if alpha == "rsi" else parent["cells"]
        design = custody.read(probes["parent_design"])
        candidates = [r for r in design["rows"] if r["admitted"]]
        if (len(parent_rows) != 128 or len(candidates) != 128 or
                [r["candidate_id"] for r in candidates] != result["candidate_ids"]):
            raise ValueError("original ordered 128 candidate roster required")
        values = []
        for row in parent_rows:
            if row["cell"] != pool[row["cell"]["path"]]:
                raise ValueError("original cell lacks independent prior custody")
            cell = custody.read(row["cell"])
            point = geometry.resolve(cell["request"]["params"])
            index = row["index"]
            if (point.identity != result["candidate_ids"][index] or point.params != candidates[index]["effective"]
                    or cell["request"]["candidate_id"] != point.identity or cell["metrics"] != row["metrics"]
                    or cell["support"] != row["support"]):
                raise ValueError("original candidate/source/whole-path evidence differs")
            values.append(dict(point=point, row=row, index=index, qualified=qualify(row, QUALIFICATION)))
        if {v["index"] for v in values} != set(range(128)):
            raise ValueError("duplicate/missing original panel index")
        ranked = sorted((v for v in values if v["qualified"]), key=lambda v: (-v["row"]["metrics"]["economic_utility"], v["point"].identity))
        historical_checks[alpha] = verify_historical_neighborhoods(geometry, probes, ranked)
        manifest = requests[alpha]["bounded_neighborhood_manifest"]
        for center_number, fit in enumerate(manifest["covariance_requests"]):
            index, cid = fit["original_index"], fit["candidate_id"]
            if (fit["candidate_roster"] != result["candidate_ids"] or fit["parent_design"] != probes["parent_design"]
                    or fit["geometry_id"] != geometry.identity or fit["recipe"] != RECIPE
                    or result["candidate_ids"][index] != cid):
                raise ValueError("exact fit roster/center/geometry request differs")
            center_value = next(v for v in values if v["index"] == index)
            center = center_value["point"]
            cloud = cloud_for(geometry, center, ranked, RECIPE)
            distinct = {p.identity: p for p in cloud}
            numeric = geometry.numeric_names(center)
            coordinates = np.array([[geometry.coordinate(name, p.params[name]) for name in numeric] for p in distinct.values()])
            rank = int(np.linalg.matrix_rank(coordinates-coordinates.mean(axis=0))) if len(coordinates) else 0
            directions, pair = {}, {}
            for role, radius, seed in ROLES:
                floor = next(n for n in manifest["neighborhoods"] if n["original_index"] == index and n["role"] == role)
                groups = tuple(tuple(g) for g in floor["joint_groups"])
                neighborhood = owner.active_neighbors(geometry, center, radius=radius, seed=seed, role=role,
                    minimum_radius=.05, joint_groups=groups, cloud=cloud, rho=.2, tau=.001, minimum_cloud=5, cloud_radius=.25)
                pair[role] = neighborhood
                proposal_id = design_identity(neighborhood.rows, method="active_neighbors_v1", seed=seed, schema_id=geometry.identity)
                nid = custody.digest(dict(parent_design=probes["parent_design_id"], center=cid, geometry=geometry.identity,
                    role=role, radius=radius, minimum_radius=.05, seed=seed, joint_groups=groups,
                    cloud_ids=list(distinct), rho=.2, tau=.001, proposal_identity=proposal_id))
                rows = [serialize(r) for r in neighborhood.rows]
                role_requests = union_requests(rows, floor, manifest["executions"], probes["executions"][0]["request"], nid, center_number, index)
                for request in role_requests:
                    request["index"] = len(executions)
                    rows[request["row_id"]]["execution_index"] = request["index"]
                    matches = [dict(cell=r["cell"], paths=r["paths"], previous_index=r["index"], execution_key=r["execution_key"])
                        for r in evaluations if r["candidate_id"] == request["candidate_id"] and r["role"] == role and r["status"] == "COMPLETE"]
                    request["coordinate_role_matches"] = matches
                    request["reuse_authorized"] = False
                    executions.append(dict(alpha=alpha, **request))
                neighborhoods.append(dict(alpha=alpha, center=center_number, original_index=index, parent_candidate_id=cid,
                    role=role, radius=radius, seed=seed, neighborhood_id=nid, original_schema_neighborhood_id=floor["neighborhood_id"],
                    proposal_identity=proposal_id, covariance_status=neighborhood.covariance_status,
                    coverage=neighborhood.coverage, rows=rows, request_count=len(role_requests),
                    preserved_schema_request_count=sum(r["source"] == "PRESERVED_SEALED_SCHEMA_REQUEST" for r in role_requests),
                    new_covariance_request_count=sum(r["source"].startswith("NEW_") for r in role_requests),
                    independent=False, account_evidence_available=False))
                directions[role] = dict(status=neighborhood.covariance_status,
                    raw_covariance_proposals=sum(r.direction.startswith("covariance:") for r in neighborhood.rows),
                    ready_covariance_proposals=sum(r.direction.startswith("covariance:") and r.status == "READY" for r in neighborhood.rows))
            statuses = {n.covariance_status for n in pair.values()}
            if len(statuses) != 1:
                raise ValueError("same cloud must have same covariance disposition across roles")
            status = next(iter(statuses))
            supported = status == "REGULARIZED_PROPOSALS_NOT_HESSIAN"
            selection = {r.point.identity for r in pair["selection_probe"].rows if r.status == "READY"}
            validation = {r.point.identity for r in pair["local_validation"].rows if r.status == "READY"}
            reason = ("supported original-owner covariance; regularized proposals are not a Hessian" if supported else
                f"original owner {status}: {len(distinct)} distinct eligible local points; centered coordinate rank {rank}/{len(numeric)}; minimum count 5; unregularized covariance must be full rank")
            fit_rows.append(dict(alpha=alpha, original_index=index, candidate_id=cid, request_identity=custody.digest(fit),
                status="MEASURED_SUPPORTED" if supported else "MEASURED_SCHEMA_ONLY_FALLBACK", exact_reason=reason,
                covariance_status=status, supported=supported, eligible_panel_count=len(ranked), center_quality_eligible=center_value["qualified"],
                numeric_dimensions=len(numeric), numeric_names=list(numeric), cloud_ids=list(distinct), distinct_cloud_count=len(distinct),
                centered_coordinate_rank=rank, coordinates=coordinates.tolist(), cloud_order="original utility descending, candidate identity tie break",
                recipe=RECIPE, directions=directions, ready_overlap=len(selection & validation), ready_selection=len(selection),
                ready_validation=len(validation), held_distinct=len(validation-selection), independent=False,
                clean_oos=False, launch_authorized=False))
    preserved = [r for r in executions if r["source"] == "PRESERVED_SEALED_SCHEMA_REQUEST"]
    extra = [r for r in executions if r["source"].startswith("NEW_")]
    old = [(a, e["request_sha256"]) for a in TARGETS for e in requests[a]["bounded_neighborhood_manifest"]["executions"]]
    if len(preserved) != 195 or sorted((r["alpha"], r["request_sha256"]) for r in preserved) != sorted(old):
        raise ValueError("all 195 exact original requests must be preserved, without additions/rewrite")
    return dict(schema="m5111_covariance_fit_and_union_v1", created_at=custody.now(), status="PASS", input_requests=registration["requests"],
        fit_requests_closed=4, fits=fit_rows, neighborhoods=neighborhoods, executions=executions,
        original_historical_neighborhoods_reproduced=historical_checks,
        counts=dict(fits=len(fit_rows), neighborhoods=len(neighborhoods), preserved_schema_requests=len(preserved),
            new_covariance_requests=len(extra), union_requests=len(executions), future_annual_views=3*len(executions),
            incremental_annual_views=3*len(extra), covariance_dispositions=dict(Counter(r["covariance_status"] for r in fit_rows))),
        union_design_policy=registration["request_identity_policy"], financial_executions=0, builds=0,
        launch_authorized=False, reuse_authorized=False, account_union_complete=False, whole_128_probe_expansion=False,
        annual_local_ranking_authorized=False, phase_complete=False, full_goal_complete=False)


def verify_prior(registration):
    original = custody.verify_prior(custody.read(registration["original_registration"]))
    for record in [*registration["prior_step_files"], *registration["software"]]:
        custody.checked(record)
    return dict(original=original, prior_step_files_verified=len(registration["prior_step_files"]),
                software_verified=len(registration["software"]), hash_failures=0)


def run(lane, attempt):
    if len(attempt) != 2 or not attempt.isdigit():
        raise ValueError("two-digit append-only attempt required")
    reg_pin = custody.pin(lane / "registration_01.json")
    registration = custody.read(reg_pin)
    before = custody.resources(lane)
    if before["free_bytes"] < registration["budget"]["reserve_bytes"] + 160*MIB:
        raise ValueError("reserve plus incremental budget required")
    if any(os.environ.get(name) != "1" for name in THREADS):
        raise ValueError("single-thread controlled numeric environment required")
    previous = [custody.pin(p) for p in sorted(lane.rglob("*")) if p.is_file()]
    prereg = custody.write_new(lane / f"cold_run_registration_{attempt}.json", dict(created_at=custody.now(), registration=reg_pin,
        source=custody.pin(__file__), tests=custody.pin(ROOT / "tests/test_mode5_covariance_requests.py"),
        previous_lane_files=previous, command=registration["tests"], numeric_threads={k: os.environ[k] for k in THREADS},
        financial_imports_authorized=False, financial_launches_authorized=False))
    status, error, verified, result_pin = "FAIL", None, None, None
    try:
        verified = verify_prior(registration)
        result = analyze(registration)
        result["registration"] = reg_pin
        result_pin = custody.write_new(lane / f"union_{attempt}.json", result)
        tests = subprocess.run(registration["tests"], text=True, capture_output=True, check=False)
        custody.write_new(lane / f"tests_{attempt}.json", dict(command=registration["tests"], returncode=tests.returncode,
            stdout=tests.stdout, stderr=tests.stderr))
        if tests.returncode:
            raise ValueError("focused cold suite failed; log retained")
        status = "PASS"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        custody.write_new(lane / f"failure_{attempt}.json", dict(created_at=custody.now(), error=error,
            traceback=traceback.format_exc(), phase_pass=False))
    finally:
        try:
            verified = verify_prior(registration)
            for record in previous:
                custody.checked(record)
            custody.checked(custody.read(prereg)["source"])
            custody.checked(custody.read(prereg)["tests"])
            if any(forbidden(name) for name in sys.modules):
                raise ValueError("prohibited runtime module imported")
        except Exception as exc:
            status, error = "FAIL", str(exc)
        retained = [custody.pin(p) for p in sorted(lane.rglob("*")) if p.is_file()]
        size = sum(r["bytes"] for r in retained)
        after = custody.resources(lane)
        if size >= 128*MIB or after["free_bytes"] < 5*1024**3:
            status, error = "FAIL", "retained/reserve budget failed"
        cleanup = custody.write_new(lane / f"cleanup_{attempt}.json", dict(created_at=custody.now(), status=status, error=error,
            registration=reg_pin, cold_run_registration=prereg, result=result_pin, prior_custody=verified,
            retained_manifest=retained, retained_bytes_before_receipt=size, scratch_bytes=0, deleted_paths=[], deleted_bytes=0,
            retained_cap_pass=size < 128*MIB, reserve_pass=after["free_bytes"] >= 5*1024**3,
            resources_before=before, resources_after=after, observed_free_byte_change=after["free_bytes"]-before["free_bytes"],
            observed_change_attributable=False, financial_executions=0, builds=0,
            preserved_environment=".maturin/qms08/release-regression-v1",
            imported_quantbt_modules=sorted(n for n in sys.modules if n.startswith("quantbt"))))
    if status != "PASS":
        raise ValueError(error)
    return dict(status=status, result=result_pin, cleanup=cleanup, retained_bytes=size)


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

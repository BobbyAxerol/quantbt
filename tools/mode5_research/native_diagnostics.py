"""Cold native-panel diagnostics and a gated adapter to the unchanged owner.

Planning consumes externally sealed admissions, original requests and access
witnesses. It is not financial qualification, recipe approval or a global
robustness certificate. Importing this module never imports a financial owner.
"""

from copy import deepcopy
import json
import math
from types import SimpleNamespace


SCHEMA = "mode5.native_diagnostic_plan.v1"
PROBE_SCHEMA = "source_admitted_native_probe_views_v1"
ALPHAS = ("A-HMA", "A-HASH", "A-VWAP")
ENVIRONMENTS = ("whole_path", "2021", "2022", "2023")
BASE = dict(start="2021-01-01", stop="2024-01-01",
            account_mode="continuous_development_2021_2023", max_feedback_runs=4096)
PARENT_KEYS = {*BASE, "alpha", "symbol", "params", "candidate_id", "design_id", "proposal_row", "role"}
CENTER_POLICY = dict(count=2, quality_floor=0., minimum_days=365, max_drawdown=.5,
    minimum_fills_if_available=30, minimum_closed_campaigns_if_available=20, top_fraction=.25)
NEIGHBOR_POLICY = dict(maximum_centers=2, selection_radius=.1, validation_radius=.12,
    selection_seed=732, validation_seed=733, minimum_radius=.05,
    covariance_cloud_radius=.25, covariance_minimum_cloud=5, covariance_rho=.2, covariance_tau=.001)
RECIPES = ("raw_sharpe", "environment_floor_mean_v1", "environment_lower_tail_v2",
           "pareto_chebyshev_v1", "local_downside_v1")
BATTERIES = {
    "B1": ("selector_only", "candidate_environment", "recipe_split_seed"),
    "B2": ("selector_only", "center_neighbor_environment"),
    "B3": ("selector_only", "environment_environment", "recipe_split_seed"),
    "B4": ("end_to_end_recipe", "recipe_split_seed"),
    "B5": ("sampler_only", "recipe_split_seed"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def contracts():
    from quantbt.mode5.diagnostics.identity import digest
    from quantbt.mode5.dossier.records import Record
    return Record, digest


def registered_policy(analysis):
    require(analysis["schema"] == "mode5_broad_analysis_v1"
            and analysis["role"] == "REVIEWED_EXPLORATORY_DEVELOPMENT"
            and analysis["forward_snapshot_allowed"] is False
            and analysis["clean_independent_claim"] is False, "original reviewed-development registration required")
    for section, expected in (("center_policy", CENTER_POLICY), ("neighbors", NEIGHBOR_POLICY)):
        require(all(analysis[section].get(k) == v for k, v in expected.items()),
                "original two-center quality/support/probe policy changed")
    require(analysis["center_policy"]["fallback"] ==
            "deterministic geometric controls with QUALITY_FAIL/INSUFFICIENT_SUPPORT, never promoted as good basin",
            "explicit original nonquality geometric fallback required")
    require(analysis["neighbors"]["no_reuse_of_selection_probes_as_independent_confirmation"] is True,
            "selection and held-local rights must remain separate")


def quality(row):
    from tools.mode5_research.selector_checkpoint import metric
    u, dd = metric(row, "economic_utility"), metric(row, "drawdown")
    support = {k: row[k] for k in ("fills", "closed_campaigns")}
    require(all(v is None or type(v) is int and v >= 0 for v in support.values()),
            "actual nonnegative support or explicit unknown required")
    support_pass = all(v is None or v >= CENTER_POLICY["minimum_"+k+"_if_available"]
                       for k, v in support.items())
    quality_pass = u is not None and u >= 0 and dd is not None and 0 <= dd <= .5
    days = row["calendar_days"] >= 365
    eligible = quality_pass and days and support_pass
    issue = ("INSUFFICIENT_SUPPORT" if not support_pass or None in support.values() else
             "QUALITY_FAIL" if not quality_pass or not days else None)
    return dict(eligible=eligible, utility=u, drawdown=dd, days_pass=days,
                support=support, support_pass=support_pass, quality_issue=issue)


def choose_centers(geometry, points, grid):
    """Exact registered utility/top-quarter diversity rule, not a new selector."""
    pool = [dict(index=i, point=p, gates=quality(grid[p.identity, "whole_path"]))
            for i, p in enumerate(points)]
    ranked = sorted((v for v in pool if v["gates"]["eligible"]),
                    key=lambda v: (-v["gates"]["utility"], v["point"].identity))
    top = ranked[:max(2, math.ceil(.25*len(ranked)))]
    fallback = len(ranked) < 2
    choices = sorted(pool, key=lambda v: v["point"].identity) if fallback else top
    first = choices[0] if fallback else ranked[0]
    second = min((v for v in choices if v["point"].identity != first["point"].identity),
                 key=lambda v: (-geometry.distance(first["point"], v["point"]), v["point"].identity))
    return (first, second), ranked, dict(eligible_count=len(ranked), top_ids=[v["point"].identity for v in top],
        status="QUALITY_FAIL_CONTROL_NOT_PROMOTED" if fallback else "TWO_REGISTERED_CENTERS",
        quality_issue="FEWER_THAN_TWO_QUALITY_CENTERS" if fallback else None,
        fallback=fallback, not_a_winner=True)


def _parent_access(catalog, parent, request):
    """Read real legacy ACCESS or registered recovery authority, never synthesize it."""
    if "authority_ref" in parent:
        actual = catalog.require_ref(parent["authority_ref"])
        require(actual["request_file"] == actual["request"]
                and actual["request_file_origin"] == "CURRENT_KNOWLEDGE_EXACT_COPY_OF_SEALED_REQUEST",
                "explicit cold request projection required")
        for original in actual["original_request_refs"]:
            require(catalog.require_ref(artifact_ref(catalog, original["artifact"], original["pointer"])) == request,
                    "cold projection differs from actual original request authority")
        require(len(actual["original_request_refs"]) >= 2, "actual result/worker or file/cell request pair required")
        access = actual["access_refs"]
        schema = access["schema"]
        if schema == "original_development_access_v1":
            require(access["original_access_file_unchanged"] is True
                    and actual["access"] == access["access"]["artifact"]
                    and actual["original_request_file"] is not None, "unchanged historical ACCESS/request required")
            return _parent_access(catalog, dict(access_schema=schema,
                access_ref=artifact_ref(catalog, actual["access"])), request)
        require(schema in {"snapshot_recovery_v1", "early_owner_registered_sources_limited_v1"}
                and actual["access"] is None and access["access_file"] is None,
                "explicit snapshot or limited early authority required; no synthetic ACCESS")
        registration = catalog.require_ref(artifact_ref(catalog, actual["original_artifact_refs"]["original_registration"]))
        worker = catalog.require_ref(artifact_ref(catalog, actual["external_recovery_registration"]))
        raw = catalog.require_ref(artifact_ref(catalog, access["actual_result_claims"]["artifact"]))
        protocol = registration["protocol"]
        require(protocol["preload_start"] == "2020-01-01" and protocol["development_start"] == BASE["start"]
                and protocol["development_stop"] == BASE["stop"] and protocol["continuous_within_scope"] is True
                and protocol["data_role"] == "DEVELOPMENT_REVIEWED_RETROSPECTIVE"
                and registration["symbols"][request["alpha"]] == request["symbol"], "original registered recovery rights differ")
        require(worker["request"] == raw["request"] == request
                and raw["future_tape_opened"] is access["future_tape_opened"] is False
                and raw["clean_oos"] is access["clean_oos"] is False
                and raw["status"] == actual["source_compute_status"], "actual recovery request/status/access claims differ")
        market = access["market_metadata"]
        witness = catalog.require_ref(artifact_ref(catalog, market["artifact"], market["pointer"]))
        require(witness == access["development_witness"], "actual market metadata witness differs")
        if schema == "snapshot_recovery_v1":
            roster = access["source_snapshot_roster"]
            snapshots = catalog.require_ref(artifact_ref(catalog, roster["artifact"], roster["pointer"]))
            require(snapshots == actual["original_source_snapshots"] == worker["source_snapshots"]
                    and any(s["original"] == actual["approved_source_refs"]["market_metadata"]
                            and s["retained"] == market["artifact"] for s in snapshots),
                    "actual retained recovery snapshot authority differs")
        else:
            roster = access["original_worker_source_roster"]
            pins = catalog.require_ref(artifact_ref(catalog, roster["artifact"], roster["pointer"]))
            require(pins == worker["pins"] and market["artifact"] in pins
                    and not actual["original_source_snapshots"] and actual["early_source_limitations"]
                    and access["limitation"], "limited early-owner authority must retain its limitations")
        return witness["sha256"]
    schema = parent["access_schema"]
    if schema == "original_development_access_v1":
        access = catalog.require_ref(parent["access_ref"])
        require(access["allowed_stop"] == BASE["stop"] and access["future_tape_opened"] is False
                and access["original_contract_preserved"] is True, "original parent access rights differ")
        return access["witness"]["sha256"]
    require(schema == "registered_recovery_development_v1", "explicit original/recovery access authority required")
    registration = catalog.require_ref(parent["original_registration_ref"])
    worker = catalog.require_ref(parent["worker_registration_ref"])
    market = catalog.require_ref(parent["market_ref"])
    protocol = registration["protocol"]
    require(protocol["preload_start"] == "2020-01-01" and protocol["development_start"] == BASE["start"]
            and protocol["development_stop"] == BASE["stop"] and protocol["continuous_within_scope"] is True
            and protocol["data_role"] == "DEVELOPMENT_REVIEWED_RETROSPECTIVE"
            and registration["symbols"][request["alpha"]] == request["symbol"], "original registered recovery rights differ")
    witness = market["development"]
    require(worker["request"] == request
            and any(pin["sha256"] == parent["original_registration_ref"]["sha256"] for pin in worker["pins"])
            and witness in worker["pins"], "actual recovery worker/request/registered market authority differs")
    return witness["sha256"]


def artifact_ref(catalog, artifact, pointer=""):
    """Deterministic source IDs name real byte pins, including original paths."""
    _, digest = contracts()
    source_id = "artifact:"+digest(artifact)
    source = catalog._sources[source_id]
    require(dict(path=source.path, sha256=source.sha256, bytes=source.bytes) == artifact,
            "actual artifact path/content/length authority differs")
    return catalog.ref(source_id, pointer)


def _parents(catalog, values, refs, alpha):
    subject = values["parents"]
    if isinstance(subject, list):
        return subject
    proof = values["admission"]
    require(subject["status"] == "PASS_ACTUAL_PARENT_REFS" and subject["actual_cells"] == 384
            and subject["request_files"] == 384 and subject["fabricated_legacy_access_files"] == 0
            and subject["financial_executions"] == 0 and subject["independent_oos"] is False
            and subject["new_request_files_are_explicit_cold_projections"] is True
            and proof["source_parent_refs"]["sha256"] == refs["parents"]["sha256"]
            and proof["actual_reader_proof"] == subject["original_proof"]
            and proof["no_fabricated_legacy_access"] is True
            and proof["source_status_or_coverage_not_promoted"] is True, "actual consumer parent/admission seals differ")
    cells = subject["cells"]
    reader = catalog.require_ref(artifact_ref(catalog, proof["actual_reader_proof"]))
    completion = catalog.require_ref(artifact_ref(catalog, proof["completed_controller_result"]))
    cleanup = catalog.require_ref(artifact_ref(catalog, completion["cleanup"]))
    require(reader["status"] == completion["status"] == "PASS_ACTUAL_COLD_NATIVE384_PANELS"
            and reader["actual_cells"] == 384 and reader["views"] == 1536
            and reader["panels"] == proof["panels"] and reader["financial_executions"] == 0
            and reader["independent_oos"] is False and reader["no_terminal_or_oracle_promotion"] is True
            and completion["proof"] == proof["actual_reader_proof"]
            and completion["all_owned_children_reaped"] is True and completion["financial_executions"] == 0
            and cleanup["status"] == "PASS" and cleanup["retained_inputs_unchanged"] is True
            and cleanup["protected_source_unchanged"] is True, "actual cold proof/controller/cleanup gates differ")
    require(len(cells) == 384 and {(c["alpha"], c["index"]) for c in cells} ==
            {(a, i) for a in ALPHAS for i in range(128)}
            and sum(c["original_request_file"] is not None for c in cells) == subject["original_request_files"],
            "full actual 384 parent roster required without invented historical files")
    parents = []
    for j, cell in enumerate(cells):
        if cell["alpha"] != alpha:
            continue
        ref = dict(refs["parents"], pointer=refs["parents"]["pointer"]+f"/cells/{j}")
        parents.append(dict(index=cell["index"], request_ref=artifact_ref(catalog, cell["request"]),
            authority_ref=ref, access_schema=cell["access_refs"]["schema"],
            **{k: cell[k] for k in ("source_reader_schema", "source_compute_status", "source_data_role",
                "reader_certification", "oracle_coverage", "original_alias_coverage",
                "original_terminal_limitations", "early_source_limitations", "request_file_origin")}))
    return parents


def _validate_inputs(catalog, refs, geometry):
    from tools.mode5_research.panel_admission import PANEL_SCHEMA
    from tools.mode5_research.selector_checkpoint import grid_for
    Record, digest = contracts()
    require(set(refs) == {"analysis", "panel", "design", "parents", "admission"}, "all five sealed input refs required")
    values = {k: catalog.require_ref(r) for k, r in refs.items()}
    registered_policy(values["analysis"])
    panel, design, proof = values["panel"], values["design"], values["admission"]
    alpha = design["alpha"]
    require(alpha in ALPHAS and panel["schema"] == PANEL_SCHEMA
            and panel["original_design_digest"] == digest(design)
            and design["schema_id"] == geometry.identity, "full admitted original native schema required")
    require(proof["status"] == "PASS_SOURCE_ADMITTED_NATIVE384_PANELS"
            and proof["actual_cells"] == 384 and proof["views"] == 1536
            and proof["financial_executions"] == 0 and proof["independent_oos"] is False
            and proof["panels"][alpha]["sha256"] == refs["panel"]["sha256"], "externally sealed native admission proof differs")
    require(panel["cutoff_ns"] <= catalog.policy.cutoff_ns, "panel not yet available at current access frontier")
    grid = grid_for(panel)
    proposals = [r for r in design["rows"] if r["admitted"]]
    points = tuple(geometry.resolve(r["effective"]) for r in proposals)
    require(len(points) == 128 and [p.identity for p in points] == panel["candidate_ids"]
            and all(p.params == r["effective"] and p.identity == r["candidate_id"]
                    and r["status"] == "READY" and r["role"] == "exploration"
                    and r.get("duplicate_of") is None for p, r in zip(points, proposals)),
            "128 unique original effective candidates required, without recast/repair")
    parents = _parents(catalog, values, refs, alpha)
    values["parents"] = parents
    require(len(parents) == 128, "one actual original parent request/access per admitted candidate required")
    for i, (parent, proposal) in enumerate(zip(parents, proposals)):
        request = catalog.require_ref(parent["request_ref"])
        require(set(request) == PARENT_KEYS and all(request[k] == v for k, v in BASE.items())
                and request["alpha"] == alpha and request["symbol"] == "BTCUSDT"
                and request["params"] == proposal["effective"] and request["candidate_id"] == proposal["candidate_id"]
                and request["design_id"] == design["design_id"] and request["proposal_row"] == proposal["row_id"]
                and request["role"] == "NEUTRAL_BROAD_DISCOVERY", "actual original parent request differs")
        market_id = _parent_access(catalog, parent, request)
        whole = grid[proposal["candidate_id"], "whole_path"]
        if "authority_ref" in parent:
            require(whole["source_reader_schema"] == parent["source_reader_schema"]
                    and whole["compute_status"] == parent["source_compute_status"]
                    and whole["reader_cell_identity"] == parent["reader_certification"]["cell_identity"]
                    and whole["oracle_coverage"] == parent["oracle_coverage"],
                    "actual parent reader/status/oracle coverage must remain unchanged")
        require(whole["provenance"]["warmup_start_ns"] == 1577836800000000000
                and whole["provenance"]["data_cutoff_ns"] == 1704067200000000000
                and whole["provenance"]["symbol"] == request["symbol"], "original 2020 preload/2021-23 scoring required")
        require(dict(whole["provenance"]["evidence_refs"])["development_data"] == market_id,
                "actual original parent market access identity differs")
        require(parent["index"] == i, "original parent ordering differs")
    catalog.verify_current()
    return values, grid, points


def plan_native(catalog, refs, geometry):
    """Only cold sealed admission can produce an exact, still unauthorized roster."""
    from tools.mode5_geometry.neighborhoods import active_neighbors
    from tools.mode5_geometry.design import design_identity
    from quantbt.mode5.dossier.evidence import KINDS
    Record, digest = contracts()
    values, grid, points = _validate_inputs(catalog, refs, geometry)
    design, parents = values["design"], values["parents"]
    centers, ranked, disposition = choose_centers(geometry, points, grid)
    hoods, executions, center_rows = [], [], []
    for ordinal, center in enumerate(centers):
        point, index = center["point"], center["index"]
        cloud = tuple(v["point"] for v in ranked if v["point"].active_names == point.active_names
            and all(v["point"].params[s.name] == point.params[s.name] for s in geometry.specs if s.choices and s.name in point.params)
            and geometry.distance(point, v["point"]) <= .25)
        # Declared coupled groups only; conditional inactive groups remain explicit.
        numeric = geometry.numeric_names(point)
        joint = tuple(c.names for c in geometry.constraints if set(c.names) <= set(numeric))
        center_row = dict(center=ordinal, parent_panel_index=index, candidate_id=point.identity,
            params=point.params, gates=center["gates"], disposition=disposition["status"],
            quality_center=not disposition["fallback"], cloud_ids=[p.identity for p in cloud],
            geometry_fit_role="geometry_fit_candidates", exploration_role="exploration_trials",
            joint_groups=[list(g) for g in joint], inactive_joint_groups=[list(c.names) for c in geometry.constraints if c.names not in joint])
        pair = {}
        for role, radius, seed in (("selection_probe", .1, 732), ("local_validation", .12, 733)):
            neighborhood = active_neighbors(geometry, point, radius=radius, seed=seed, role=role,
                minimum_radius=.05, joint_groups=joint, cloud=cloud, rho=.2, tau=.001, minimum_cloud=5, cloud_radius=.25)
            nid = digest(dict(parent_design=design["design_id"], center=point.identity, schema=geometry.identity,
                role=role, radius=radius, seed=seed, minimum_radius=.05, joint_groups=joint,
                cloud_ids=[p.identity for p in cloud], rho=.2, tau=.001,
                proposal_identity=design_identity(neighborhood.rows, method="active_neighbors_v1", seed=seed, schema_id=geometry.identity)))
            rows = []
            for proposal in neighborhood.rows:
                row = dict(row_id=proposal.row_id, role=role, direction=proposal.direction,
                    requested=json.loads(proposal.requested_json), effective=proposal.point.params if proposal.point else None,
                    candidate_id=proposal.point.identity if proposal.point else None, status=proposal.status,
                    duplicate_of=proposal.duplicate_of, reason=proposal.reason, execution_index=None)
                if proposal.status == "READY":
                    parent = catalog.require_ref(parents[index]["request_ref"])
                    request = parent | dict(params=proposal.point.params, candidate_id=proposal.point.identity,
                        role=role, design_id=nid, proposal_row=proposal.row_id, parent_design_id=design["design_id"],
                        parent_candidate_id=point.identity, parent_panel_index=index, neighborhood_center=ordinal,
                        probe_radius=radius, probe_seed=seed, probe_direction=proposal.direction)
                    row["execution_index"] = len(executions)
                    executions.append(dict(index=len(executions), request=request, request_sha256=digest(request),
                        parent_request_ref=parents[index]["request_ref"], parent_authority=parents[index],
                        source_refs=refs, status="MISSING_ACCOUNT_EVALUATION", launch_authorized=False,
                        rights="selection" if role == "selection_probe" else "post_decision_reporting_only",
                        clean_oos=False, annual_local_authorized=False))
                rows.append(row)
            hoods.append(dict(center=ordinal, parent_panel_index=index, role=role, radius=radius, seed=seed,
                neighborhood_id=nid, covariance_status=neighborhood.covariance_status,
                coverage=neighborhood.coverage, rows=rows))
            pair[role] = {r.point.identity for r in neighborhood.rows if r.status == "READY"}
        center_row["quality_center"] &= center["gates"]["quality_issue"] is None
        center_row["held_support"] = dict(ready_overlap=len(pair["selection_probe"] & pair["local_validation"]),
            held_distinct=len(pair["local_validation"]-pair["selection_probe"]), independent_oos=False,
            shared_directions_are_not_independent=True)
        center_rows.append(center_row)
    for hood in hoods:
        ready = [r for r in hood["rows"] if r["status"] == "READY"]
        hood["comparison_sets"] = {method: [r["execution_index"] for r in ready if
            method == "union" or r["direction"].startswith("covariance:") == (method == "covariance")]
            for method in ("schema", "covariance", "union")}
        hood["covariance_alone_replaces_schema"] = False
    entries = {k: [] for k in KINDS}

    def add(kind, token, operation, **coordinates):
        entries[kind].append(dict(row_id=design["alpha"]+":"+token, operation=operation, coordinates=coordinates))

    for i, spec in enumerate(geometry.metadata()["parameters"]):
        add("parameter_representation", "parameter:"+spec["name"], "parameter", index=i, parameter=spec["name"])
    for i, row in enumerate(design["rows"]):
        add("parameter_representation", f"proposal:{i}", "proposal", index=i)
    for i, cid in enumerate(values["panel"]["candidate_ids"]):
        for env in ENVIRONMENTS:
            add("candidate_environment", f"candidate:{i}:{env}", "candidate", index=i, candidate_id=cid, environment=env)
        for scenario in ("base", "fee_x2"):
            add("execution_stress", f"stress:{i}:{scenario}", "stress", index=i, candidate_id=cid, scenario=scenario)
        add("center_neighbor_environment", f"fullpanel-local:{i}", "unmeasured_fullpanel", candidate_id=cid, index=i)
    for i, center in enumerate(center_rows):
        for env in ENVIRONMENTS:
            add("center_neighbor_environment", f"center:{i}:{env}", "center", center=i, environment=env)
    for h, hood in enumerate(hoods):
        for i, row in enumerate(hood["rows"]):
            for env in ENVIRONMENTS:
                add("center_neighbor_environment", f"probe:{h}:{i}:{env}", "probe", hood=h, index=i,
                    role=hood["role"], environment=env, execution_index=row["execution_index"])
    for left in ENVIRONMENTS:
        for right in ENVIRONMENTS:
            add("environment_environment", f"environment:{left}:{right}", "unmeasured", left=left, right=right)
    for recipe in RECIPES:
        for held in (None, "2021", "2022", "2023"):
            add("recipe_split_seed", f"selector:{recipe}:{held}", "unmeasured", recipe=recipe,
                split="reviewed_development" if held is None else "leave_one_annual_out", held=held, seed=None,
                comparison_level="selector_only")
    for battery in ("B4", "B5"):
        add("recipe_split_seed", battery, "unmeasured", battery=battery, comparison_level=BATTERIES[battery][0])
    result = dict(schema=SCHEMA, alpha=design["alpha"], refs=refs, access=catalog.manifest.data["access"],
        geometry=geometry.metadata(), geometry_id=geometry.identity, candidate_ids=values["panel"]["candidate_ids"],
        centers=center_rows, center_disposition=disposition, neighborhoods=hoods, executions=executions, entries=entries,
        inventory={k: [e["row_id"] for e in entries[k]] for k in KINDS},
        batteries={k: dict(comparison_level=v[0], matrix_kinds=list(v[1:]), status="NOT_RUN",
            reason=values["analysis"]["batteries"][k]) for k, v in BATTERIES.items()},
        coverage="BOUNDED_TWO_CENTERS_NOT_WHOLE128_LOCAL", financial_executions=0,
        launch_authorized=False, recipe_approval=False, clean_oos=False,
        counts=dict(candidates=128, candidate_environment_rows=512, centers=2, neighborhoods=4,
            requested_proposals=sum(len(n["rows"]) for n in hoods), missing_account_requests=len(executions),
            future_annual_views=3*len(executions), distinct_effective_role_pairs=len({(e["request"]["candidate_id"], e["request"]["role"]) for e in executions})))
    catalog.verify_current()
    return Record.of(result)


def missing_roster(plan, catalog, completed_refs=()):
    """Only exact qualified request/role matches can remove planned work."""
    Record, digest = contracts()
    entries = {e["request_sha256"]: e for e in plan.data["executions"]}
    complete = set()
    for ref in completed_refs:
        result = catalog.require_ref(ref)
        sha = result.get("request_sha256", digest(result["request"]))
        require(sha in entries and sha not in complete and result["request"] == entries[sha]["request"]
                and digest(result["request"]) == sha and result["status"] == "PASS_FINAL_COMPILER_AND_ACCOUNTING"
                and result["original_compiler_parity"] is True and result["typed_lifecycle_terminal_parity"] is True
                and result["future_tape_opened"] is False and result["clean_oos"] is False,
                "only source-qualified exact original request/role completions may be reused")
        complete.add(sha)
    catalog.verify_current()
    return tuple(e for e in plan.data["executions"] if e["request_sha256"] not in complete)


def normalized_rows(plan, catalog, *, probe_views_ref=None):
    """Source-bound matrix cells. Unknown values stay null with explicit masks."""
    from tools.mode5_research.selector_checkpoint import grid_for
    from quantbt.mode5.statistics.contracts import MetricValue
    Record, digest = contracts()
    p = plan.data
    panel = catalog.require_ref(p["refs"]["panel"])
    grid = grid_for(panel)
    design = catalog.require_ref(p["refs"]["design"])
    probes = {}
    if probe_views_ref is not None:
        subject = catalog.require_ref(probe_views_ref)
        require(subject["schema"] == PROBE_SCHEMA and subject["plan_identity"] == plan.identity,
                "externally source-admitted probe views must bind this sealed design")
        for i, cell in enumerate(subject["rows"]):
            key = cell["execution_index"], cell["environment_id"]
            require(key not in probes and type(key[0]) is int and 0 <= key[0] < len(p["executions"])
                    and key[1] in ENVIRONMENTS, "duplicate/unexpected probe view")
            execution = p["executions"][key[0]]
            require(cell["request"] == execution["request"] and cell["request_sha256"] == execution["request_sha256"]
                    and cell["role"] == execution["request"]["role"]
                    and cell["annual_local_authorized"] is False and cell["clean_oos"] is False,
                    "probe request/role/annual rights differ")
            value = cell["value"]
            require(cell["analysis_compute_status"] == "PASS" and value["environment_id"] == key[1]
                    and value["calendar_days"] == (1095 if key[1] == "whole_path" else 365)
                    and value["actual_bar_count"] == value["calendar_days"]*24
                    and value["estimand_id"] == "CONTINUOUS_PATH_ATTRIBUTION"
                    and value["clean_oos"] is False and value["provenance"]["candidate_id"] == execution["request"]["candidate_id"],
                    "qualified original full continuous probe view required")
            for m in value["metrics"]:
                MetricValue(**m)
            probes[key] = (value, dict(probe_views_ref, pointer=probe_views_ref["pointer"]+f"/rows/{i}"))
    output = {k: [] for k in p["entries"]}
    for kind, entries in p["entries"].items():
        for entry in entries:
            c, operation = entry["coordinates"], entry["operation"]
            value, sources, status, reason = None, [], "NOT_TESTED", "registered diagnostic not measured"
            if operation in {"parameter", "proposal"}:
                value = p["geometry"]["parameters"][c["index"]] if operation == "parameter" else design["rows"][c["index"]]
                status, reason = "STRUCTURAL_ONLY", "no global sensitivity or behavioral-effect measurement"
                sources = [p["refs"]["design"]]
            elif operation in {"candidate", "center"} or operation == "stress" and c["scenario"] == "base":
                cid = p["centers"][c["center"]]["candidate_id"] if operation == "center" else c["candidate_id"]
                env = c.get("environment", "whole_path")
                original, status, reason = grid[cid, env], "OBSERVED", None
                j = panel["candidate_environment_rows"].index(original)
                ref = p["refs"]["panel"]
                sources = [dict(ref, pointer=ref["pointer"]+f"/candidate_environment_rows/{j}")]
                # The large original report stays in its unchanged sealed source.
                value = {k: v for k, v in original.items() if k != "raw_account_metrics"}
                value["raw_account_metrics_ref"] = dict(sources[0], pointer=sources[0]["pointer"]+"/raw_account_metrics")
            elif operation == "probe":
                proposal = p["neighborhoods"][c["hood"]]["rows"][c["index"]]
                key = c["execution_index"], c["environment"]
                if key in probes:
                    value, ref = probes[key]
                    sources, status, reason = [ref], "OBSERVED", None
                else:
                    status = "MISSING" if proposal["status"] == "READY" else proposal["status"]
                    reason = "missing source-admitted account view" if status == "MISSING" else proposal["reason"] or "structural alias; not independent execution"
            elif operation == "unmeasured_fullpanel":
                reason = "two-center design does not authorize whole-128 local qualification"
            metrics = value.get("metrics", []) if isinstance(value, dict) else []
            masks = [dict(metric=m["metric_id"], value=None, status=m["status"], reason=m["reason"])
                     for m in metrics if m["value"] is None]
            if value is None:
                masks.append(dict(value=None, status=status, reason=reason))
            if isinstance(value, dict):
                masks.extend(dict(field=k, value=None, status="UNAVAILABLE", reason=why)
                             for k, why in value.get("null_reasons", []) if value.get(k) is None)
            output[kind].append(dict(entry, status=status, value=value, reason=reason, metric_masks=masks,
                source_refs=sources, annual_local_authorized=False, independent_oos=False))
    catalog.verify_current()
    return Record.of(dict(schema="mode5.native_diagnostic_rows.v1", plan_identity=plan.identity,
        probe_views_ref=probe_views_ref, values=output, inventory=p["inventory"],
        batteries=p["batteries"], scientific_complete=False, financial_executions=0))


def assemble_matrices(plan, catalog, *, plan_ref, normalized_ref):
    from quantbt.mode5.dossier.evidence import KINDS, Matrix, reconcile_rosters
    Record, digest = contracts()
    require(catalog.require_ref(plan_ref) == plan.data, "independently frozen diagnostic plan differs")
    subject = catalog.require_ref(normalized_ref)
    rebuilt = normalized_rows(plan, catalog, probe_views_ref=subject["probe_views_ref"])
    require(rebuilt.data == subject, "altered/omitted/reordered source-bound diagnostic rows")
    inventory = Record.of(catalog.require_ref(dict(plan_ref, pointer=plan_ref["pointer"]+"/inventory")))
    rosters = tuple(Record.of(dict(kind=k, entries=[dict(row_id=e["row_id"],
        ref=dict(normalized_ref, pointer=normalized_ref["pointer"]+f"/values/{k}/{i}"))
        for i, e in enumerate(plan.data["entries"][k])])) for k in KINDS)
    reconcile_rosters(rosters, inventory)
    matrices = tuple(Matrix.assemble(k, r, catalog) for k, r in zip(KINDS, rosters))
    for m, r in zip(matrices, rosters):
        m.verify(r, catalog)
    catalog.verify_current()
    return matrices, rosters, inventory


def advisory(plan, catalog, *, plan_ref):
    from quantbt.mode5.dossier.dossier import ordered_advice
    require(catalog.require_ref(plan_ref) == plan.data, "frozen plan reference differs")
    return ordered_advice([dict(recipe_id=recipe, status="INSUFFICIENT_COVERAGE", selected_decisions=0,
        refs=[plan_ref], reasons=["planned inventories are not measured selector comparisons"])
        for recipe in RECIPES[1:]])


def prepared_probe_class(base, entry, parent):
    """Use the original preparation/NativeBinding; change only exact request lookup."""
    request = deepcopy(entry["request"])
    Record, digest = contracts()
    require(digest(request) == entry["request_sha256"] and request["role"] in {"selection_probe", "local_validation"},
            "sealed exact outcome-independent probe required")
    index = request["parent_panel_index"]

    class PreparedProbe(base):
        def __init__(self, alias):
            require(alias == request["alpha"], "wrong probe alpha")
            super().__init__(alias)
            require(super().request(index) == parent, "live original parent request differs from seal")
            protocol = self.registration["protocol"]
            require(protocol["preload_start"] == "2020-01-01" and protocol["development_start"] == BASE["start"]
                    and protocol["development_stop"] == BASE["stop"], "original preparation dates changed")
            require(str(self.history.index[0])[:10] == "2020-01-01" and len(self.scored) == 26280
                    and str(self.scored.index[0])[:10] == BASE["start"]
                    and str(self.scored.index[-1])[:10] == "2023-12-31"
                    and self.signature() == self.data_hash, "original full preload/scored context required")

        def request(self, requested_index):
            require(requested_index == index, "one isolated exact probe per worker")
            return deepcopy(request)

    return PreparedProbe


def regenerate_plan(plan, catalog):
    """Rebuild at the frozen input frontier, not later output/auth availability."""
    from quantbt.mode5.diagnostics.access import AccessPolicy
    from quantbt.mode5.dossier.evidence import EvidenceCatalog
    access = plan.data["access"]
    policy = AccessPolicy(access["policy_id"], tuple(access["roles"]), tuple(access["manifests"]),
                          access["cutoff_ns"], access["purpose"])
    sources = [s for s in catalog._sources.values() if s.witness.ready_ns <= policy.cutoff_ns
               and s.witness.role in policy.roles and s.witness.manifest_id in policy.manifests]
    return plan_native(EvidenceCatalog(sources, policy), plan.data["refs"],
                       _hydrate_geometry(plan.data["geometry"], plan.data["geometry_id"]))


def execute_sealed_probe(plan, catalog, *, entry_index, runner, output, cap, authorization_ref):
    """Later worker only. Caller supplies an externally authorized pinned runner.

    No global replacement of PreparedResearch and no edit to fast_native.py.
    Its module-local prepared namespace temporarily supplies the sealed subclass.
    The original final compiler, native audit and fixed-fill oracle remain owners.
    """
    Record, digest = contracts()
    require(type(entry_index) is int and 0 <= entry_index < len(plan.data["executions"]), "exact planned entry required")
    entry = plan.data["executions"][entry_index]
    auth = catalog.require_ref(authorization_ref)
    require(auth["schema"] == "mode5.native_probe_launch_authorization.v1"
            and auth["approved_by"] == "owner" and auth["launch_authorized"] is True
            and auth["plan_identity"] == plan.identity and auth["request_sha256"] == entry["request_sha256"]
            and auth["numeric_threads"] == 1 and auth["financial_workers"] == 1
            and auth["cap_seconds"] == cap and 0 < cap <= 1800
            and auth["output"] == str(output) and auth["reserve_bytes"] >= 5*1024**3,
            "separate external per-probe resource/launch authorization required")
    require(type(auth["python_control"]) is bool and type(auth["retained_limit_bytes"]) is int
            and 0 < auth["retained_limit_bytes"] <= 32*1024**2
            and catalog.require_ref(auth["plan_ref"]) == plan.data, "frozen exact plan and bounded control/retention required")
    completion = catalog.require_ref(auth["admission_completion_ref"])
    admission = catalog.require_ref(plan.data["refs"]["admission"])
    actual_proof = admission.get("actual_reader_proof", plan.data["refs"]["admission"])
    require(completion["status"] in {"PASS_SOURCE_ADMITTED_NATIVE384_PANELS", "PASS_ACTUAL_COLD_NATIVE384_PANELS"}
            and completion["all_owned_children_reaped"] is True
            and completion["proof"]["sha256"] == actual_proof["sha256"],
            "closed cold-admission controller proof required before financial execution")
    from quantbt.mode5.artifacts import file_identity
    require(file_identity(runner.__file__) == auth["runner_pin"], "pinned unchanged financial owner differs")
    require(file_identity(__file__) == auth["adapter_pin"], "sealed external wrapper source differs")
    for source_pin in auth.get("runtime_source_pins", []):
        require(file_identity(source_pin["path"]) == source_pin, "sealed original runtime dependency differs")
    import os
    from pathlib import Path
    require(all(os.environ.get(k) == "1" for k in auth["thread_variables"])
            and set(auth["thread_variables"]) == {"OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "NUMBA_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "BLIS_NUM_THREADS", "RAYON_NUM_THREADS"},
            "one actual numeric thread required")
    output = Path(output)
    require(output.is_absolute() and output == output.resolve() and not output.exists() and not output.is_symlink(),
            "new canonical append-only probe output required, without symlink ancestry")
    stat = os.statvfs(output.parent)
    require(stat.f_bavail*stat.f_frsize >= auth["reserve_bytes"] + auth["retained_limit_bytes"]
            and stat.f_favail > 0, "probe disk reserve/inode budget unavailable")
    parent = catalog.require_ref(entry["parent_request_ref"])
    require(regenerate_plan(plan, catalog) == plan,
            "sealed source/registration cannot regenerate exact request design")
    catalog.verify_current()
    original = runner.prepared
    adapter = prepared_probe_class(original.PreparedResearch, entry, parent)
    from quantbt.mode5.artifacts import write_json
    registration_path = output.parent / (output.name+"-adapter-registration.json")
    write_json(registration_path, dict(schema="mode5.native_probe_adapter_registration.v1",
        plan_identity=plan.identity, exact_entry=entry, authorization_ref=authorization_ref,
        authorization=auth, catalog=catalog.manifest.data, runner_pin=auth["runner_pin"],
        adapter_pin=auth["adapter_pin"], parent_request=parent, cap_seconds=cap,
        original_preparation_source=file_identity(original.__file__),
        expected_final_native_calls=2 if auth["python_control"] else 1,
        expected_python_oracle_calls=int(auth["python_control"]), financial_executions=0,
        recipe_approval=False, same_original_preload_scoring=True))
    runner.prepared = SimpleNamespace(PreparedResearch=adapter, finance=original.finance, __file__=original.__file__)
    try:
        runner.run(entry["request"]["alpha"], entry["request"]["parent_panel_index"], output, cap, control=auth["python_control"])
        result = json.loads((output / "result.json").read_text())
        require(result["request"] == entry["request"] and result["status"] == "PASS_FINAL_COMPILER_AND_ACCOUNTING",
                "original owner did not return the sealed probe request")
        require(result["final_native_calls"] == (2 if auth["python_control"] else 1)
                and result["python_oracle_calls"] == int(auth["python_control"])
                and type(result["native_feedback_calls"]) is int and result["native_feedback_calls"] >= 1
                and result["original_compiler_parity"] is True and result["typed_lifecycle_terminal_parity"] is True
                and result["future_tape_opened"] is False and result["clean_oos"] is False,
                "actual original final-control/accounting counts or role differ")
        catalog.verify_current()
        for source_pin in auth.get("runtime_source_pins", []):
            require(file_identity(source_pin["path"]) == source_pin, "runtime dependency changed during probe")
        require(sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) <= auth["retained_limit_bytes"],
                "separate probe retention cap breached; evidence retained")
        return result
    finally:
        runner.prepared = original


def _hydrate_geometry(metadata, expected_id):
    from quantbt.mode5.geometry.schema import EffectiveGeometry, OrderedConstraint
    from quantbt.optimization.parameter_space import ParameterSpec
    specs = tuple(ParameterSpec(s["name"], s["kind"], s["low"], s["high"], s["step"], s["scale"] == "log",
        tuple(s["categories"]), tuple((k, tuple(v)) for k, v in s["active_if"].items()), s["fixed"], s["fixed_value"])
        for s in metadata["parameters"])
    geometry = EffectiveGeometry(specs, tuple(metadata["weights"].items()), tuple(metadata["inactive"].items()),
        tuple(metadata["casts"].items()), tuple(OrderedConstraint(tuple(c["names"]), c["strict"]) for c in metadata["constraints"]), metadata["version"])
    # JSON changes tuples to lists in constraints; compare canonical records.
    Record, digest = contracts()
    require(Record.of(geometry.metadata()) == Record.of(metadata) and geometry.identity == expected_id,
            "hydrated original geometry differs")
    return geometry

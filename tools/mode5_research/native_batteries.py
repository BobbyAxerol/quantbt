"""Source-bound native selector batteries. No execution or financial imports.

Discovery, selection probes and post-decision held probes keep different rights.
All comparisons are finite, reviewed development diagnostics, not recipe approval.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
from itertools import product
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quantbt.mode5.dossier.records import Record


SCHEMA = "mode5.native_batteries.v1"
ANNUAL = ("2021", "2022", "2023")
ENVIRONMENTS = ("whole_path", *ANNUAL)
ROLES = ("selection_probe", "local_validation")
FORMULAS = (
    dict(selector="full_dro_cvar", version="environment_floor_mean_v1", coefficients=dict(mean=.25)),
    dict(selector="full_dro_cvar", version="environment_lower_tail_v2",
         coefficients=dict(alpha=.25, dispersion=.2, floor=1., tail=.5)),
    dict(selector="full_pareto_chebyshev", version="pareto_chebyshev_v1", coefficients=dict(rho=.01)),
)
LIMITATIONS = (
    "Current-knowledge reviewed development; no untouched OOS or historical live forecast.",
    "Whole and annual views share the same continuous account; no independent replications.",
    "Daily annual eligibility is not campaign/opportunity support or matched-exposure evidence.",
    "Bounded local centers do not establish whole-128 or annual-local robustness.",
    "B4/B5, execution stress, uncertainty and whole-procedure superiority remain unqualified.",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def owners():
    from quantbt.mode5.dossier.records import Record
    from quantbt.mode5.diagnostics.identity import digest
    return Record, digest


@dataclass(frozen=True)
class BatteryReduction:
    rows: Record
    report: Record
    assessment: Record

    def verify(self, catalog):
        refs = self.report.data["input_refs"]
        rebuilt = reduce_batteries(catalog, **{k+"_ref": v for k, v in refs.items()})
        require(rebuilt == self, "altered source-bound battery reduction")


def _preferences(preferences):
    from .probe_views import COMMON
    require(preferences["formulas"] == list(FORMULAS), "original canonical formulas/coefficients required")
    require(all(preferences[k] == COMMON[k] for k in ("activity_penalty", "risk_drawdown_max",
        "quality_utility_strictly_greater_than", "minimum_daily_count"))
        and preferences["environment_weights"] ==
            "equal positive 1.0 per annual environment; whole path not stacked into annual selectors"
        and preferences["floor_reference"] == .25 and preferences["near_optimal_tolerance_decimal"] == .01
        and preferences["pareto"] == dict(ideal=.25, worst=-.25, weights=1., directions=1,
                                          extrapolation="allow_and_report_v1")
        and preferences["minimum_improvement"] == 0 and preferences["incumbent"] is None
        and preferences["tie_break"] == "candidate_id_lexicographic_v1",
        "original annual quality/reference/normalization preferences changed")


def _metric(row, name, *, probe=False):
    from quantbt.mode5.statistics.contracts import MetricValue
    from . import selector_checkpoint as checkpoint
    if not probe:
        checkpoint.metric(row, name)
    matches = [m for m in row["metrics"] if m["metric_id"] == "mode5.panel."+name]
    require(len(matches) == 1, "one exact metric contract required")
    metric = MetricValue(**matches[0])
    require(metric.unit == ("ratio" if name == "sharpe" else "decimal_return")
            and (metric.value is None or type(metric.value) in (int, float)), "original finite numeric metric/unit required")
    return metric


def _source_row_ref(ref, index, field="candidate_environment_rows"):
    return dict(ref, pointer=ref["pointer"]+f"/{field}/{index}")


def _load(catalog, refs):
    from . import native_diagnostics as native, selector_checkpoint as checkpoint
    Record, digest = owners()
    require(catalog.policy.purpose in {"diagnostic", "selection"}, "development-only battery rights required")
    plan = Record.of(catalog.require_ref(refs["plan"]))
    require(plan.data["schema"] == native.SCHEMA and native.regenerate_plan(plan, catalog) == plan,
            "frozen actual native panel/parent/analysis plan differs")
    panel = catalog.require_ref(plan.data["refs"]["panel"])
    preferences = catalog.require_ref(refs["preferences"])
    _preferences(preferences)
    from .probe_views import preference_check
    preference_check(dict(preferences=preferences, candidate_environment_rows=panel["candidate_environment_rows"]))
    grid = checkpoint.grid_for(panel)
    row_refs = {(r["provenance"]["candidate_id"], r["environment_id"]):
                _source_row_ref(plan.data["refs"]["panel"], i) for i, r in enumerate(panel["candidate_environment_rows"])}
    probes = {}
    if refs["probe_views"] is not None:
        from .native_probe_admission import analysis_compute_pass, READER_SCHEMA
        from .probe_views import UTILITY
        envelope = catalog.require_ref(refs["probe_views"])
        require(envelope["schema"] == native.PROBE_SCHEMA and envelope["plan_identity"] == plan.identity
                and envelope["utility_policy"] == UTILITY and envelope["financial_executions"] == 0
                and envelope["annual_local_authorized"] is False and envelope["clean_oos"] is False,
                "source-qualified Planck probe-view envelope required")
        for i, cell in enumerate(envelope["rows"]):
            index, env = cell["execution_index"], cell["environment_id"]
            require(type(index) is int and 0 <= index < len(plan.data["executions"])
                    and env in ENVIRONMENTS and (index, env) not in probes, "distinct expected probe view required")
            execution = plan.data["executions"][index]
            request, value = execution["request"], cell["value"]
            require(cell["request"] == request and cell["request_sha256"] == execution["request_sha256"] == digest(request)
                    and cell["role"] == request["role"] and cell["annual_local_authorized"] is False
                    and cell["clean_oos"] is False and cell["analysis_compute_status"] == "PASS"
                    and value["source_reader_schema"] == READER_SCHEMA and analysis_compute_pass(value),
                    "exact source-qualified probe request/role/reader required")
            provenance = value["provenance"]
            days = 1095 if env == "whole_path" else 365
            require(value["environment_id"] == env and value["calendar_days"] == days
                    and value["actual_bar_count"] == days*24 and value["estimand_id"] == "CONTINUOUS_PATH_ATTRIBUTION"
                    and provenance["candidate_id"] == request["candidate_id"]
                    and provenance["design_id"] == request["design_id"] and provenance["data_role"] == request["role"]
                    and provenance["warmup_start_ns"] == 1577836800000000000
                    and provenance["data_cutoff_ns"] == 1704067200000000000,
                    "original full continuous probe calendar/lineage required")
            for name in ("economic_utility", "drawdown", "sharpe", "net_return", "daily_loss_es"):
                metric = _metric(value, name, probe=True)
                require(metric.sample_count == days, "actual metric observation days differ")
                if name == "economic_utility" and metric.value is not None:
                    parts = dict(metric.components)
                    require(all(parts.get(k) == v for k, v in UTILITY.items()),
                            "original probe utility preference differs")
            probes[index, env] = (value, _source_row_ref(refs["probe_views"], i, "rows"))
        indices = {index for index, _ in probes}
        require(set(probes) == set(product(indices, ENVIRONMENTS)), "four dependent views per admitted execution required")
        for index in indices:
            require(len({probes[index, env][0]["provenance"]["execution_id"] for env in ENVIRONMENTS}) == 1,
                    "one original continuous account per probe required")
    catalog.verify_current()
    return plan, panel, preferences, grid, row_refs, probes


def _canonical_panel(plan, panel, preferences, grid, catalog, refs):
    from quantbt.mode5.selection.contracts import Candidate, Channel, Panel
    from quantbt.mode5.statistics.tails import FrozenReference
    from quantbt.mode5.diagnostics.access import AccessPolicy
    from quantbt.mode5.diagnostics.identity import AnalysisKey
    from . import selector_checkpoint as checkpoint
    _, digest = owners()
    channel = Channel("ECONOMIC_UTILITY_V1", "mode5.utility.net_v1", "decimal_return")
    reference = FrozenReference("m5111-inherited-m508-fixed-reference", ANNUAL,
        (preferences["floor_reference"],)*3, (1.,)*3, channel.identity, plan.identity)
    witness = catalog._sources[plan.data["refs"]["panel"]["source"]].witness
    # Later output custody must not rewrite the selection's input frontier.
    input_refs = [refs["plan"], refs["preferences"], *plan.data["refs"].values()]
    witnesses = [catalog._sources[ref["source"]].witness for ref in input_refs]
    frontier = max(plan.data["access"]["cutoff_ns"], *(w.ready_ns for w in witnesses))
    require(frontier <= catalog.policy.cutoff_ns, "selection input frontier exceeds current access")
    policy = AccessPolicy("native-selector-reviewed-development", tuple(sorted({w.role for w in witnesses})),
        tuple(sorted({w.manifest_id for w in witnesses})), frontier, "selection")
    policy.require(witness)
    design = catalog.require_ref(plan.data["refs"]["design"])
    params = {r["candidate_id"]: digest(r["effective"]) for r in design["rows"] if r["admitted"]}
    gates, candidates = {}, []
    for cid in panel["candidate_ids"]:
        rows = [grid[cid, env] for env in ANNUAL]
        gates[cid] = tuple(tuple(checkpoint.gates(row, preferences).values()) for row in rows)
        metrics = tuple(replace(_metric(row, "economic_utility"), metric_id=channel.metric_contract) for row in rows)
        analyses = tuple(AnalysisKey(row["provenance"]["execution_id"], env,
            digest(dict(metric_contract="mode5.panel.economic_utility", metric=metric.to_metadata())), reference.identity)
            for env, row, metric in zip(ANNUAL, rows, metrics))
        candidates.append(Candidate(cid, params[cid], metrics, analyses, (witness,)*3,
            "original-DD<=.5-U>0-days>=365-annual-policy", True,
            *(all(g[j] for g in gates[cid]) for j in range(3)), True, preferences["activity_penalty"]))
    return Panel(plan.data["alpha"]+":native-fixed-panel", plan.identity, channel, reference,
        tuple(candidates), policy, "fixed_panel", "original neutral frozen 128; current reviewed development"), gates


def _make_plan(panel, setting, preferences, preference=None):
    from quantbt.mode5.selection.contracts import Formula, SelectionPlan
    return SelectionPlan("native-battery:"+setting["version"], panel.context_id, "same_panel_selector_only",
        Formula(setting["version"], panel.channel, tuple(setting["coefficients"].items())), panel.reference.identity,
        setting["selector"], preferences["minimum_improvement"], incumbent_id=preferences["incumbent"],
        tie_break=preferences["tie_break"], pareto_preference_identity=preference.identity if preference else None,
        access_identity=panel.access.identity)


def _selectors(panel, preferences, environment_gates):
    from quantbt.mode5.selection.pareto import ParetoPreference
    from quantbt.mode5.selection.selectors import select
    from quantbt.mode5.statistics.tails import FrozenReference
    from tools.mode5_batteries.comparisons import fixed_panel_leave_out, same_front
    from .selector_checkpoint import best
    p = preferences["pareto"]
    preference = ParetoPreference("m5111-inherited-m508-preference", ANNUAL, panel.channel.identity,
        (p["ideal"],)*3, (p["worst"],)*3, (p["directions"],)*3, (p["weights"],)*3, p["extrapolation"])
    decisions, leave_out = {}, {}
    for setting in preferences["formulas"]:
        version = setting["version"]
        pref = preference if version == "pareto_chebyshev_v1" else None
        plan = _make_plan(panel, setting, preferences, pref)
        decisions[version] = select(panel, plan, **(dict(pareto_preference=pref) if pref else {})).metadata
        if pref is None:
            leave_out[version] = list(fixed_panel_leave_out(panel, plan, environment_gates=environment_gates))
        else:
            leave_out[version] = []
            for omitted, env in enumerate(ANNUAL):
                keep = tuple(i for i in range(3) if i != omitted)
                ref = FrozenReference(panel.reference.reference_id+":leave:"+env, tuple(ANNUAL[i] for i in keep),
                    tuple(panel.reference.values[i] for i in keep), (1.,)*2, panel.channel.identity, panel.revision+":leave:"+env)
                candidates = tuple(replace(c, metrics=tuple(c.metrics[i] for i in keep),
                    witnesses=tuple(c.witnesses[i] for i in keep),
                    analyses=tuple(replace(c.analyses[i], normalization_reference=ref.identity) for i in keep),
                    **{name: all(environment_gates[c.candidate_id][i][j] for i in keep)
                       for j, name in enumerate(("risk_pass", "quality_pass", "support_pass"))}) for c in panel.candidates)
                child = replace(panel, revision=panel.revision+":leave:"+env, reference=ref, candidates=candidates)
                child_pref = replace(pref, reference_id=pref.reference_id+":leave:"+env,
                    **{name: tuple(getattr(pref, name)[i] for i in keep)
                       for name in ("environment_ids", "ideal", "worst", "directions", "weights")})
                decision = select(child, _make_plan(child, setting, preferences, child_pref), pareto_preference=child_pref).metadata
                chosen = decision["chosen_candidate"]
                candidate = next((c for c in panel.candidates if c.candidate_id == chosen), None)
                leave_out[version].append(dict(omitted_environment=env, chosen_candidate=chosen, decision=decision,
                    held_metric=candidate.metrics[omitted].to_metadata() if candidate else None,
                    eligibility_scope="KEPT_ENVIRONMENTS_ONLY", held_gate_information_excluded=True, refit_sampler=False,
                    claim="fixed preferences projected to kept data; retrospective fixed-panel diagnostic"))
    for rows in leave_out.values():
        for row in rows:
            cid = row["chosen_candidate"]
            row.update(held_gates_post_selection_only=True,
                held_gate_flags=list(environment_gates[cid][ANNUAL.index(row["omitted_environment"])]) if cid else None,
                independent_oos=False)
    pareto = decisions["pareto_chebyshev_v1"]
    front = set(pareto["pareto_candidate_ids"])
    means = decisions["environment_floor_mean_v1"]["component_rows"]
    weighted = best([dict(r, eligible=r["candidate_id"] in front,
                         score=r["components"]["mean"] if r["components"] else None) for r in means])
    eligible = [r for r in pareto["component_rows"] if r["eligible"]]
    shared = (same_front([r["values"] for r in eligible], [r["candidate_id"] for r in eligible],
        [cid for cid in (pareto["chosen_candidate"], weighted) if cid is not None], directions=(1,)*3)
        if eligible else dict(front_ids=[], selected_ids=[], hypervolume_value=None,
            hypervolume_discriminates_selectors=False, reason="NO_COMMON_ANNUAL_ELIGIBLE_CONFIGURATION"))
    require(set(shared["front_ids"]) == front, "same canonical eligible Pareto front required")
    shared.update(weighted_mean_candidate=weighted, chebyshev_candidate=pareto["chosen_candidate"],
                  preference_identity=preference.identity, preferences_frozen=True)
    return dict(decisions=decisions, leave_out=leave_out, same_front=shared)


def _environment_matrix(grid, candidate_ids, preferences):
    from scipy.stats import spearmanr
    from quantbt.mode5.statistics.tails import FrozenReference, regret
    from quantbt.mode5.selection.contracts import Channel
    from .selector_checkpoint import gates
    channel = Channel("ECONOMIC_UTILITY_V1", "mode5.utility.net_v1", "decimal_return")
    values = {env: {cid: _metric(grid[cid, env], "economic_utility").value for cid in candidate_ids} for env in ENVIRONMENTS}
    near = {}
    for env, data in values.items():
        valid = [v for v in data.values() if v is not None]
        benchmark = max(valid) if valid else None
        admissible = [cid for cid in candidate_ids if all(gates(grid[cid, env], preferences).values())]
        members = [cid for cid in admissible if data[cid] >= benchmark-preferences["near_optimal_tolerance_decimal"]]
        near[env] = dict(finite_valid_benchmark=benchmark, members=members, valid_count=len(valid),
            admissible_count=len(admissible), tolerance=preferences["near_optimal_tolerance_decimal"],
            benchmark_is_global_optimum=False, reason=None if members else
            "NO_VALID_UTILITY" if not valid else "NO_ADMISSIBLE_MEMBER_WITHIN_REGISTERED_TOLERANCE")
    references, regrets = {}, []
    for envs in (ENVIRONMENTS, ANNUAL):
        if all(near[e]["finite_valid_benchmark"] is not None for e in envs):
            references[envs] = FrozenReference("native-finite-valid-best:"+":".join(envs), envs,
                tuple(near[e]["finite_valid_benchmark"] for e in envs), (1.,)*len(envs), channel.identity, "reviewed-development")
    for cid in candidate_ids:
        per = {e: None if values[e][cid] is None or near[e]["finite_valid_benchmark"] is None else
               near[e]["finite_valid_benchmark"]-values[e][cid] for e in ENVIRONMENTS}
        canonical = {}
        for envs, label in ((ENVIRONMENTS, "whole_and_annual_dependent"), (ANNUAL, "annual")):
            canonical[label] = regret([values[e][cid] for e in envs], environment_ids=envs,
                channel=channel.identity, reference=references[envs]) if envs in references and all(values[e][cid] is not None for e in envs) else dict(
                    status="UNAVAILABLE", value=None, reason="incomplete metric/reference; no survivor mean")
        regrets.append(dict(candidate_id=cid, per_environment=per, canonical=canonical))
    pairs = []
    for left, right in product(ENVIRONMENTS, repeat=2):
        common = [cid for cid in candidate_ids if values[left][cid] is not None and values[right][cid] is not None]
        x, y = [values[left][cid] for cid in common], [values[right][cid] for cid in common]
        reason = "fewer than two common valid candidates" if len(common) < 2 else (
            "constant utility on common candidates" if len(set(x)) < 2 or len(set(y)) < 2 else None)
        coefficient = None if reason else float(spearmanr(x, y).statistic)
        require(coefficient is None or math.isfinite(coefficient), "nonfinite rank arithmetic")
        a, b = set(near[left]["members"]), set(near[right]["members"])
        transferred = [dict(candidate_id=cid, utility=values[right][cid],
            regret=near[right]["finite_valid_benchmark"]-values[right][cid]
                if values[right][cid] is not None and near[right]["finite_valid_benchmark"] is not None else None,
            gates=gates(grid[cid, right], preferences)) for cid in near[left]["members"]]
        complete = bool(transferred) and all(t["regret"] is not None for t in transferred)
        pairs.append(dict(left=left, right=right, spearman=coefficient, spearman_reason=reason,
            common_candidate_ids=common, common_mask=[cid in common for cid in candidate_ids], common_count=len(common),
            left_valid_mask=[values[left][cid] is not None for cid in candidate_ids],
            right_valid_mask=[values[right][cid] is not None for cid in candidate_ids],
            left_ties=dict(Counter(map(str, x))), right_ties=dict(Counter(map(str, y))),
            near_intersection=sorted(a & b), near_union_count=len(a | b),
            near_jaccard=len(a & b)/len(a | b) if a | b else None,
            near_jaccard_reason=None if a | b else "BOTH_NEAR_OPTIMAL_SETS_EMPTY",
            source_set_transfer=transferred,
            max_target_regret=max(t["regret"] for t in transferred) if complete else None,
            mean_target_regret=math.fsum(t["regret"] for t in transferred)/len(transferred) if complete else None,
            transfer_reason=None if complete else "empty source set or missing target; no survivor averaging",
            shared_dates=left == right or "whole_path" in (left, right), same_continuous_account=True,
            independent_replications=False, p_value=None, inference="descriptive finite-panel only"))
    return dict(pairs=pairs, near_optimal_sets=near, finite_panel_regrets=regrets,
                uncertainty="NOT_RUN", finite_benchmark_includes_negative_and_risk_failing=True)


def _local(plan, grid, probes, preferences, row_refs):
    from . import selector_checkpoint as checkpoint
    p = plan.data
    centers = []
    undefined = []
    for center in p["centers"]:
        cid = center["candidate_id"]
        row = grid[cid, "whole_path"]
        utility, dd = (_metric(row, name).value for name in ("economic_utility", "drawdown"))
        if utility is None or dd is None:
            undefined.append(center["center"])
        centers.append(dict(center=center["center"], panel_index=center["parent_panel_index"], candidate_id=cid,
            metrics=dict(account_mode="continuous_development_2021_2023", daily_count=1095,
                         economic_utility=utility, max_drawdown=dd), cell=row_refs[cid, "whole_path"],
            covariance=dict(cloud_ids=center["cloud_ids"], groups=center["joint_groups"]), held_support=center["held_support"]))
    neighborhoods = deepcopy(p["neighborhoods"])
    for hood in neighborhoods:
        for row in hood["rows"]:
            row["point"] = dict(effective_json=checkpoint.digest(row["effective"])) if row["effective"] is not None else None
    evaluations = {}
    for (index, env), (value, ref) in probes.items():
        if env != "whole_path":
            continue
        request = p["executions"][index]["request"]
        utility, dd = (_metric(value, name, probe=True) for name in ("economic_utility", "drawdown"))
        evaluations[index] = dict(center=request["neighborhood_center"], role=request["role"],
            candidate_id=request["candidate_id"], direction=request["probe_direction"], status="COMPLETE",
            metrics=dict(return_status="VALID" if utility.value is not None and dd.value is not None else "UNDEFINED",
                account_mode=request["account_mode"], daily_count=value["calendar_days"],
                economic_utility=utility.value, max_drawdown=dd.value), utility=utility.value, cell=ref, paths=ref,
            source_compute_status=value["compute_status"], source_reader_schema=value["source_reader_schema"])
    if undefined:
        return dict(formula_id="local_downside_v1", status="NOT_EVALUABLE", chosen_candidate=None,
            component_rows=[], validation_post_decision=[], reason="UNDEFINED_CENTER_METRIC", undefined_centers=undefined,
            bounded_centers=p["centers"], evidence_complete=False, full_panel_local_status="NOT_EVALUABLE",
            annual_local_status="NOT_AUTHORIZED", overlap=[c["held_support"] for c in p["centers"]])
    registration = dict(centers=centers, neighborhoods=neighborhoods, executions=p["executions"],
        objective=dict(metric="economic_utility", unit="decimal_return", reference_id="original-whole-path-local",
                       reference_scale=1, quality_floor=0))
    local = checkpoint.local_comparison(registration, evaluations, preferences)
    # Original geometric fallback controls never acquire good-basin authority.
    for rows in (local["component_rows"], local["validation_post_decision"]):
        for row in rows:
            authority = p["centers"][row["center"]]
            row["original_center_gates"] = authority["gates"]
            row["original_quality_center"] = authority["quality_center"]
            if not authority["quality_center"]:
                row["eligible"] = False
                row["reasons"].append(authority["gates"]["quality_issue"] or "ORIGINAL_NONQUALITY_GEOMETRIC_CONTROL")
                if row["evidence_complete"]:
                    row["status"] = "NONQUALITY_CONTROL_NOT_PROMOTED"
    selection = local["component_rows"]
    complete = all(r["evidence_complete"] for r in selection)
    local["chosen_candidate"] = checkpoint.best(selection) if complete else None
    local["status"] = "SELECTED_LIMITED_ROSTER" if local["chosen_candidate"] else "NO_SELECTION" if complete else "NOT_EVALUABLE"
    local["evidence_complete"] = complete and all(r["evidence_complete"] for r in local["validation_post_decision"])
    local["selection_evidence_complete"] = complete
    for row in selection + local["validation_post_decision"]:
        row["quality_survival_scope"] = "REGISTERED_REQUIRED_ROSTER" if row["evidence_complete"] else "OBSERVED_LOWER_BOUND_NOT_COMPLETE"
    local["source_refs"] = [ref for (_, env), (_, ref) in probes.items() if env == "whole_path"]
    local["annual_local_status"] = "NOT_AUTHORIZED"
    return local


def _compact_view(value, ref):
    keys = ("metrics", "environment_id", "calendar_days", "actual_bar_count", "status", "reason", "null_reasons",
        "fills", "closed_campaigns", "open_campaigns", "exposed_bars", "exposure_days", "zero_return_days",
        "compute_status", "analysis_compute_status", "source_reader_schema", "oracle_coverage", "rights",
        "parent_coverage", "source_limitations", "original_coverage_limitations", "actual_account_calls",
        "early_account_witness", "recovery_account_calls", "reader_cell_identity", "reader_certification_id",
        "alpha_source_digest", "economic_config_digest", "provenance", "original_result_schema")
    return dict(projection_schema="mode5.native_battery_view_projection.v1", original_view_ref=ref,
                **{k: value[k] for k in keys if k in value})


def _rows(plan, catalog, refs, selectors, environments, local, raw):
    from . import native_diagnostics as native
    Record, _ = owners()
    baseline = native.normalized_rows(plan, catalog, probe_views_ref=refs["probe_views"]).data
    pairs = {(r["left"], r["right"]): r for r in environments["pairs"]}
    for kind, rows in baseline["values"].items():
        for row in rows:
            if row["status"] == "OBSERVED" and isinstance(row["value"], dict) and "metrics" in row["value"]:
                ref = row["source_refs"][0]
                if row["operation"] == "probe":
                    ref = dict(ref, pointer=ref["pointer"]+"/value")
                row["value"] = _compact_view(row["value"], ref)
            c = row["coordinates"]
            if kind == "environment_environment":
                row.update(value=pairs[c["left"], c["right"]], status="OBSERVED_DESCRIPTIVE", reason=None,
                    source_refs=[refs["plan"], plan.data["refs"]["panel"], refs["preferences"]])
                row["metric_masks"] = [dict(metric=name, value=None, status="UNDEFINED", reason=row["value"][reason])
                    for name, reason in (("spearman", "spearman_reason"), ("near_jaccard", "near_jaccard_reason"),
                                         ("max_target_regret", "transfer_reason"), ("mean_target_regret", "transfer_reason"))
                    if row["value"][name] is None]
            elif kind == "recipe_split_seed":
                recipe, held = c.get("recipe"), c.get("held")
                value = (raw if recipe == "raw_sharpe" and held is None else
                    local if recipe == "local_downside_v1" and held is None else
                    selectors["decisions"].get(recipe) if held is None else
                    next((r for r in selectors["leave_out"].get(recipe, []) if r["omitted_environment"] == held), None))
                if value is not None:
                    row.update(value=value, status="OBSERVED_SELECTOR_ONLY", reason=None, metric_masks=[],
                        source_refs=[refs["plan"], plan.data["refs"]["panel"], refs["preferences"]])
                    if recipe == "local_downside_v1":
                        row["source_refs"] += [refs["probe_views"]] if refs["probe_views"] else []
                        if not local["evidence_complete"]:
                            row["metric_masks"].append(dict(metric="local_qualification", value=None,
                                status="INSUFFICIENT_COVERAGE", reason="complete selection and held source views required"))
                else:
                    reason = ("B4/B5 require actual formal256 sampler/forward work" if c.get("battery") else
                        "annual-local reducer not authorized" if recipe == "local_downside_v1" else
                        "raw whole-Sharpe control is not a held-year annual selector")
                    row.update(value=None, status="NOT_RUN" if c.get("battery") else "NOT_AUTHORIZED", reason=reason,
                        metric_masks=[dict(value=None, status="NOT_TESTED", reason=reason)], source_refs=[refs["plan"]])
    return Record.of(dict(schema="mode5.native_battery_rows.v1", plan_identity=plan.identity, input_refs=refs,
        inventory=plan.data["inventory"], values=baseline["values"], scientific_complete=False, financial_executions=0))


def reduce_batteries(catalog, *, plan_ref, preferences_ref, probe_views_ref=None):
    """Consume sealed native inputs; return immutable rows/report/assessments."""
    from . import selector_checkpoint as checkpoint
    Record, digest = owners()
    refs = dict(plan=plan_ref, preferences=preferences_ref, probe_views=probe_views_ref)
    plan, panel, preferences, grid, row_refs, probes = _load(catalog, refs)
    canonical, environment_gates = _canonical_panel(plan, panel, preferences, grid, catalog, refs)
    selectors = _selectors(canonical, preferences, environment_gates)
    environments = _environment_matrix(grid, panel["candidate_ids"], preferences)
    raw_rows = [dict(candidate_id=cid, score=_metric(grid[cid, "whole_path"], "sharpe").value,
        eligible=_metric(grid[cid, "whole_path"], "sharpe").value is not None,
        gates_post_choice=checkpoint.gates(grid[cid, "whole_path"], preferences),
        source_ref=row_refs[cid, "whole_path"]) for cid in panel["candidate_ids"]]
    raw = dict(formula_id="raw_original_whole_path_sharpe_v1", chosen_candidate=checkpoint.best(raw_rows),
        component_rows=raw_rows, scope="OBSERVED_RAW_WHOLE_SHARPE_UNQUALIFIED_CONTROL",
        common_annual_eligibility_applied=False, clean_oos=False)
    local = _local(plan, grid, probes, preferences, row_refs)
    batteries = dict(
        B1=dict(status="MEASURED_SELECTOR_ONLY", decisions={k: v for k, v in selectors["decisions"].items() if k != "pareto_chebyshev_v1"},
            leave_out={k: v for k, v in selectors["leave_out"].items() if k != "pareto_chebyshev_v1"},
            opportunity_support="not an annual selection gate; actual counts remain descriptive", matched_exposure_rival="NOT_RUN"),
        B2=dict(status="MEASURED_BOUNDED_LOCAL" if local["evidence_complete"] else "INSUFFICIENT_COVERAGE",
            local=local, selection_roles=["selection_probe"], held_access="POST_DECISION_REPORTING_ONLY",
            expected_executions=len(plan.data["executions"]), admitted_executions=len({i for i, _ in probes}),
            whole128_local="NOT_EVALUABLE", annual_local="NOT_AUTHORIZED"),
        B3=dict(status="MEASURED_SELECTOR_ONLY", decision=selectors["decisions"]["pareto_chebyshev_v1"],
            same_front=selectors["same_front"], leave_out=selectors["leave_out"]["pareto_chebyshev_v1"], environment_matrix=environments),
        B4=dict(status="NOT_RUN", reason="actual fixed-parameter forward/multi-origin work absent"),
        B5=dict(status="NOT_RUN", reason="actual matched formal256 adaptive sampler work absent"))
    rows = _rows(plan, catalog, refs, selectors, environments, local, raw)
    assessments = []
    fully_known = all(_metric(grid[cid, env], name).value is not None
        for cid in panel["candidate_ids"] for env in ANNUAL for name in ("economic_utility", "drawdown"))
    for setting in preferences["formulas"]:
        recipe = setting["version"]
        decision = selectors["decisions"][recipe]
        choices = sum(r["chosen_candidate"] is not None for r in selectors["leave_out"][recipe]) + int(decision["chosen_candidate"] is not None)
        status = ("CONSIDER_FINITE_PANEL" if decision["chosen_candidate"] else
            "NO_SUPPORTED_CONFIGURATION_ON_REGISTERED_PANEL") if fully_known else "INSUFFICIENT_COVERAGE"
        assessments.append(dict(recipe_id=setting["selector"]+":"+recipe, status=status, selected_decisions=choices,
            scope="FROZEN_128_COMMON_ANNUAL_ELIGIBILITY_SELECTOR_ONLY", chosen_candidate=decision["chosen_candidate"],
            supported_candidate_ids=[r["candidate_id"] for r in decision["component_rows"] if r["eligible"]],
            complete_metric_coverage=fully_known, whole_procedure_qualified=False,
            refs=[plan_ref, plan.data["refs"]["panel"], preferences_ref], reasons=[
                "source-bound conditional fixed-panel diagnostics, not independently measured recipe superiority",
                "no annual supported configuration" if status.startswith("NO_SUPPORTED") else
                "common annual quality-qualified choice measured" if status == "CONSIDER_FINITE_PANEL" else "incomplete annual metric coverage",
                "outer/opportunity/matched-exposure qualification remains absent"]))
    local_status = ("CONSIDER_FINITE_PANEL" if local["chosen_candidate"] else
        "NO_SUPPORTED_CONFIGURATION_ON_REGISTERED_PANEL") if local["evidence_complete"] else "INSUFFICIENT_COVERAGE"
    assessments.append(dict(recipe_id="full_sam_basin:local_downside_v1", status=local_status,
        selected_decisions=int(local["chosen_candidate"] is not None),
        scope="REGISTERED_TWO_CENTER_WHOLE_PATH_ONLY", chosen_candidate=local["chosen_candidate"],
        supported_candidate_ids=[r["candidate_id"] for r in local["component_rows"] if r["eligible"]],
        complete_selection_and_held_coverage=local["evidence_complete"], annual_local_authorized=False,
        whole_procedure_qualified=False,
        refs=[plan_ref]+([probe_views_ref] if probe_views_ref else []),
        reasons=["bounded centers only; complete source-qualified selection/held required", "whole128/annual-local and outer qualification absent"]))
    from quantbt.mode5.dossier.dossier import ordered_advice
    assessment = Record.of(dict(schema="mode5.native_battery_assessment.v1", recipes=assessments,
        ordered_advice=ordered_advice(assessments), automatic_routing=False, recipe_approval=False, scientific_complete=False))
    report = Record.of(dict(schema=SCHEMA, input_refs=refs, alpha=plan.data["alpha"], plan_identity=plan.identity,
        preferences=preferences, batteries=batteries, raw_whole_sharpe_control=raw,
        rows_identity=rows.identity, assessment_identity=assessment.identity, limitations=LIMITATIONS,
        financial_executions=0, independent_oos=False, recipe_approval=False, phase_complete=False))
    catalog.verify_current()
    return BatteryReduction(rows, report, assessment)


def assemble_matrices(reduction, catalog, *, rows_ref, report_ref):
    """Source-read and reconcile all six matrices against the frozen plan inventory."""
    from quantbt.mode5.dossier.evidence import KINDS, Matrix, reconcile_rosters
    Record, _ = owners()
    reduction.verify(catalog)
    require(catalog.require_ref(rows_ref) == reduction.rows.data and catalog.require_ref(report_ref) == reduction.report.data,
            "frozen battery rows/report differ")
    refs = reduction.report.data["input_refs"]
    plan = catalog.require_ref(refs["plan"])
    inventory_ref = dict(refs["plan"], pointer=refs["plan"]["pointer"]+"/inventory")
    inventory = Record.of(catalog.require_ref(inventory_ref))
    rosters = tuple(Record.of(dict(kind=kind, entries=[dict(row_id=entry["row_id"],
        ref=dict(rows_ref, pointer=rows_ref["pointer"]+f"/values/{kind}/{i}"))
        for i, entry in enumerate(plan["entries"][kind])])) for kind in KINDS)
    reconcile_rosters(rosters, inventory)
    matrices = tuple(Matrix.assemble(kind, roster, catalog) for kind, roster in zip(KINDS, rosters))
    for matrix, roster in zip(matrices, rosters):
        matrix.verify(roster, catalog)
    catalog.verify_current()
    return matrices, rosters, inventory_ref

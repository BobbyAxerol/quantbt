"""Cold, descriptive views of existing public Mode5 decisions, never a selector.

Only bounded metadata is retained: no account paths, data access, execution,
sampler calls or scientific reduction. A snapshot validates internal agreement,
not current evidence rights or independent validation. Export is public by
default; parameter dictionaries require ``private=True``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from html import escape
import json
from typing import Any, Mapping

import pandas as pd

from ..optimization.meta_selection.common import wire
from .diagnostics.identity import digest
from .dossier.records import Record
from .selection.contracts import Channel, Formula


SCHEMA = "quantbt.mode5.decision_report.v1"
RESET = "quantbt.mode5.public_run.v1"
CONTINUOUS = "quantbt.mode5.public_run.continuous.v1"
LIMITS = (
    "Retained full-development calibration, not independent forward evidence or deployment permission.",
    "Cold internal consistency is not fresh source, access or financial qualification.",
    "Trial counts and dependent environment views are not independent observations.",
    "No new sampler comparison, diagnostics, uncertainty estimate or selector is computed.",
)
GATE_REASONS = {"INFEASIBLE", "RISK_FAIL", "QUALITY_FAIL", "INSUFFICIENT_SUPPORT",
    "UNEVALUATED_REPRESENTATIVE", "INCOMPLETE_ENVIRONMENTS", "MISSING_LOCAL_EVIDENCE",
    "INCOMPLETE_LOCAL_PROBES", "INSUFFICIENT_LOCAL_COVERAGE", "ARITHMETIC_INVALID", "REFERENCE_EXTRAPOLATION"}
SELECTORS = {"full_dro_cvar", "full_sam_basin", "full_pareto_chebyshev", "full_alpha_adaptive_invariant"}
TRIAL_REASONS = {"DUPLICATE_EFFECTIVE_PARAMS", "UNDEFINED_OBJECTIVE", "UNAVAILABLE_ANNUAL_METRIC_CONTRACT",
                 "INTERRUPTED_BEFORE_TERMINAL_TRIAL_STATE", "NOT_EVALUATED", "CANCELED", "FAILED"}


def _pick(data: Mapping[str, Any], keys: str) -> dict[str, Any]:
    return {k: data[k] for k in keys.split() if k in data}


def _public_numbers(data: dict, keys: str) -> dict:
    def safe(value):
        return value is None or type(value) in {bool, int, float}
    return {k: v if safe(v) or isinstance(v, list) and all(safe(x) for x in v) else "REDACTED"
            for k, v in _pick(data, keys).items()}


def _public_observation(row: dict, index: int) -> dict:
    view = _public_numbers(row, "raw_sharpe net_return max_drawdown daily_loss_es daily_count "
        "partial_days closed_records support_pass risk_pass quality_pass liquidated")
    view["environment_id"] = f"environment-{index+1}"
    for key in ("utility", "psr"):
        if key in row:
            metric = _public_numbers(row[key], "value sample_count")
            status = row[key].get("status")
            metric.update(status=status if status in {"VALID", "INSUFFICIENT", "UNDEFINED", "INVALID", "UNAVAILABLE",
                "REPLAY_REQUIRED", "NO_LOSS", "BANKRUPT"} else "REDACTED",
                          reason="REDACTED" if row[key].get("reason") is not None else None)
            view[key] = metric
    return view


def _observation(row: dict) -> dict:
    return _pick(row, "environment_id start_ns stop_ns account_policy metric_contract "
        "metric_contract_status null_reason finance raw_sharpe utility psr net_return "
        "max_drawdown daily_loss_es daily_count partial_days closed_records closed_record_unit "
        "support_pass risk_pass quality_pass liquidated initial_capital final_equity "
        "campaign_count fill_count campaign_support_status fill_support_status")


def _snapshot(metadata: Mapping[str, Any]) -> dict:
    m = _pick(metadata, "schema status error_type dossier_id calibration_plan_id "
        "runtime_binding_identity validation_claim chronology decision selection_decision_id "
        "selected_params_digest optimizer_schedule batch_size candidate_sequence_equivalent_to_sequential "
        "trial_reports compute_bill environment_account_policy final_account_policy financial_scope "
        "annual_account_resets meta_learning_activated automatic_routing deployment_authorized advisory_shortlist")
    m["trial_ledger"] = []
    for row in metadata["trial_ledger"]:
        retained = _pick(row, "trial_id state candidate_id requested_params effective_params evaluation_ref "
            "reason error_type objective raw_sharpe raw_whole_sharpe annual_mean_raw_sharpe components "
            "continuous_observation_ref scientific_reason")
        if "observations" in row:
            retained["observations"] = [_observation(o) for o in row["observations"]]
        if "whole_observation" in row:
            retained["whole_observation"] = _observation(row["whole_observation"])
        m["trial_ledger"].append(retained)
    if "selected_audit" in metadata:
        m["selected_audit"] = [_observation(o) for o in metadata["selected_audit"]]
    if "account_scope" in metadata:
        m["account_scope"] = _pick(metadata["account_scope"], "schema identity contract_identity "
            "access_identity witness_identity full_start_ns full_stop_ns scored_start_ns scored_stop_ns "
            "bar_interval_ns full_bars preload_bars scored_bars scored_positions account_policy "
            "candidate_initialization preload_account_execution annual_account_resets validation_claim")
    sampler = metadata["sampler"]
    m["sampler"] = _pick(sampler, "schema recipe sampler_class optuna_version cmaes_version kwargs seed "
        "stage objective_scope is_cutoff warm_start_cutoff cutoff_authority space_identity constraint_mode "
        "mixed_space_policy requested_trials attempts states unique_effective_candidates feasible_complete "
        "warm_start_attempts duplicate_attempts independent_sample_calls relative_proposal_trials "
        "joint_numeric_candidates qmc_dimension_order qmc_sequence_position startup_policy completed_generations "
        "group_decomposition startup_adaptive_counts sampler_wall_seconds ask_tell_digest resume sobol_policy "
        "effective_geometry_identity constraint_policy rng_draws_added_by_geometry")
    m["sampler"]["rows"] = [_pick(r, "trial_id state requested_params effective_params candidate_id source "
        "objective constraints reason relative_dimensions proposal_candidate_id proposal_effective_params "
        "effective_active_mask") for r in sampler["rows"]]
    # Preserve the sampler's declared clock, including an explicitly naive
    # timestamp; report serialization must not invent a timezone or stringify
    # arbitrary payloads. Remaining scalars use the shared finite wire codec.
    for name in ("is_cutoff", "warm_start_cutoff"):
        value = m["sampler"].get(name)
        if isinstance(value, pd.Timestamp):
            if pd.isna(value):
                raise ValueError("sampler cutoff must not be NaT")
            m["sampler"][name] = value.isoformat()
    return wire(m)


def _validate(m: dict, params: dict | None) -> None:
    if m["schema"] not in {RESET, CONTINUOUS} or m["status"] not in {"SELECTED_REPLAY_VERIFIED", "FAILED_CLOSED"}:
        raise ValueError("terminal public Mode5 metadata required")
    if m.get("validation_claim") != "none_full_sample_calibration" or any(
            m.get(k) is not False for k in ("meta_learning_activated", "automatic_routing", "deployment_authorized")):
        raise ValueError("existing descriptive calibration authority required")
    rows, sampler = m["trial_ledger"], m["sampler"]
    by_trial = {r["trial_id"]: r for r in rows}
    if len(by_trial) != len(rows) or any(type(n) is not int for n in by_trial):
        raise ValueError("distinct integer trial IDs required")
    if any(r["state"] not in {"COMPLETE", "PRUNED", "FAILED"} for r in rows):
        raise ValueError("terminal trial states required")
    telemetry = {r["trial_id"]: r for r in sampler["rows"]}
    if (sampler["schema"] != "quantbt-wfo-sampler-study-v1" or sampler["attempts"] != len(rows)
            or len(telemetry) != len(sampler["rows"]) or set(telemetry) != set(by_trial)
            or sampler["states"] != dict(Counter(r["state"] for r in sampler["rows"]))):
        raise ValueError("sampler attempts/states must match the retained ledger")
    for row in rows:
        t = telemetry[row["trial_id"]]
        if t["state"] != {"FAILED": "FAIL"}.get(row["state"], row["state"]):
            raise ValueError("sampler and runtime trial states differ")
        p, cid = row.get("effective_params"), row.get("candidate_id")
        if p is not None and (not isinstance(p, dict) or digest(p) != cid):
            raise ValueError("effective params differ from candidate digest")
        if p is not None and t.get("effective_params") != p:
            raise ValueError("sampler effective params disagree with actual runtime dictionary")
        if cid is not None and p is None:
            raise ValueError("candidate requires actual effective params")
        if row["state"] == "COMPLETE" and (cid is None or row.get("objective") is None
                or not row.get("observations") or not row.get("components")):
            raise ValueError("complete trial requires objective, components and actual observations")
        component = row.get("components")
        if component is not None and (component["candidate_id"] != cid
                or component["params_digest"] != cid or component["score"] != row.get("objective")):
            raise ValueError("trial objective/params disagree with retained components")
        if row.get("reason") == "DUPLICATE_EFFECTIVE_PARAMS":
            if row["state"] != "PRUNED" or not any(
                    prev["trial_id"] < row["trial_id"] and prev.get("candidate_id") == cid
                    and prev.get("components") is not None and prev.get("evaluation_ref") == row.get("evaluation_ref")
                    for prev in rows):
                raise ValueError("duplicate requires an earlier actual evaluation reference")
    if sampler["duplicate_attempts"] != sum(r.get("reason") == "DUPLICATE_EFFECTIVE_PARAMS" for r in rows):
        raise ValueError("duplicate counts disagree")
    if m["schema"] == CONTINUOUS:
        if (m.get("environment_account_policy") != "CONTINUOUS_PATH_ATTRIBUTION"
                or m.get("annual_account_resets") != 0 or "account_scope" not in m
                or m["account_scope"].get("annual_account_resets") != 0
                or m["account_scope"].get("preload_account_execution") is not False):
            raise ValueError("explicit continuous account scope required")
        scope = m["account_scope"]
        if (scope["schema"] != "quantbt.mode5.continuous_account_scope.v1"
                or scope["account_policy"] != "CONTINUOUS_PATH_ATTRIBUTION"
                or scope["full_bars"] != scope["preload_bars"] + scope["scored_bars"]
                or scope["scored_positions"] != [scope["preload_bars"], scope["full_bars"]]):
            raise ValueError("continuous scope policy/bar counts mismatch")
        for row in rows:
            whole = row.get("whole_observation")
            if row.get("components") is not None and whole is None:
                raise ValueError("evaluated continuous candidate requires whole-account evidence")
            if whole is not None and (row.get("raw_sharpe") != whole["raw_sharpe"]
                    or row.get("raw_whole_sharpe") != whole["raw_sharpe"]):
                raise ValueError("continuous raw Sharpe must be the retained whole-account Sharpe")
    elif m.get("environment_account_policy") not in {None, "independent_reset_flat_v1"}:
        raise ValueError("reset schema cannot claim continuous attribution")
    d = m.get("decision")
    if d is None:
        # This is the runtime's pre-decision failure, not an invented sealed decision.
        if (m["status"] != "FAILED_CLOSED" or m.get("error_type") != "Mode5NoSelectionError"
                or any(r.get("components") is not None for r in rows)
                or params is not None or m.get("selected_params_digest") is not None
                or m.get("selected_audit") is not None or m.get("selection_decision_id") is not None):
            raise ValueError("missing selection decision")
        return
    if d["schema"] != "mode5.selection_decision.v1" or digest(d) != m["selection_decision_id"]:
        raise ValueError("selection decision identity mismatch")
    formula = Formula(d["formula_version"], Channel(**d["channel"]), tuple(d["formula_coefficients"]))
    if (formula.identity != d["formula_identity"] or d["tie_break"] != "candidate_id_lexicographic_v1"
            or formula.channel.name not in {"ECONOMIC_UTILITY_V1", "PSR_EVIDENCE_V1"}):
        raise ValueError("frozen formula identity or tie-break mismatch")
    reference = d["reference"]
    if (digest(dict(reference, version="frozen_reference_regret_v1")) != d["reference_identity"]
            or reference["channel"] != formula.channel.identity):
        raise ValueError("frozen reference identity/channel mismatch")
    parts = {r["candidate_id"]: r for r in d["component_rows"]}
    if (len(parts) != len(d["component_rows"]) or set(parts) != set(d["compared_candidate_ids"])
            or digest(d["component_rows"]) != d["component_hash"]):
        raise ValueError("compared pool/components mismatch")
    evaluated = {r["candidate_id"]: r for r in rows if r.get("components") is not None}
    if set(parts) != set(evaluated):
        raise ValueError("decision must match the actual evaluated candidate pool")
    evidence = {r["candidate_id"]: r for r in d["evidence_refs"]}
    if len(evidence) != len(d["evidence_refs"]) or set(evidence) != set(parts):
        raise ValueError("decision evidence roster differs from actual pool")
    for cid, part in parts.items():
        if (part["params_digest"] != cid or part["score"] != evaluated[cid]["objective"]
                or any(part[k] != evaluated[cid]["components"][k] for k in ("eligible", "reasons", "components"))
                or any(part[k] != d[k] for k in ("formula_identity", "reference_identity", "plan_identity"))):
            raise ValueError("decision components disagree with evaluated objective/binding")
        observations = evaluated[cid]["observations"]
        key = "utility" if formula.channel.name == "ECONOMIC_UTILITY_V1" else "psr"
        metrics = [o[key] for o in observations]
        if (len(metrics) != len(reference["environment_ids"])
                or evidence[cid]["gate_ref"] != part["gate_ref"] or any(
                    evidence[cid][target] != [metric[source] for metric in metrics] for source, target in (
                        ("value", "environment_values"), ("status", "environment_statuses"),
                        ("reason", "environment_null_reasons"), ("sample_count", "environment_sample_counts")))):
            raise ValueError("decision evidence differs from actual environment observations")
    chosen = d["chosen_candidate"]
    if d["status"] == "NO_SELECTION":
        if (chosen is not None or d.get("chosen_params_digest") is not None or params is not None
                or m.get("selected_params_digest") is not None or m.get("selected_audit") is not None
                or m["status"] != "FAILED_CLOSED" or m.get("error_type") != "Mode5NoSelectionError"
                or d.get("post_incumbent_candidate") is not None):
            raise ValueError("NO_SELECTION cannot contain selected params or replay")
    elif d["status"] == "SELECTED":
        if (m["status"] != "SELECTED_REPLAY_VERIFIED" or not isinstance(params, dict)
                or chosen not in parts or not parts[chosen]["eligible"] or parts[chosen]["score"] is None
                or not parts[chosen].get("pareto_front", True)
                or digest(params) != chosen or d["chosen_params_digest"] != chosen
                or m.get("selected_params_digest") != chosen or d["post_incumbent_candidate"] != chosen
                or not any(r["state"] == "COMPLETE" and r.get("effective_params") == params for r in rows)):
            raise ValueError("selected actual dictionary/decision/replay binding mismatch")
        audit = m.get("selected_audit")
        observed = evaluated[chosen]["observations"]
        if not audit or len(audit) != len(observed) or any(
                any(a.get(k) != b.get(k) for k in ("finance", "utility", "psr"))
                for a, b in zip(audit, observed, strict=True)):
            raise ValueError("selected audit differs from actual selected observations")
    else:
        raise ValueError("explicit SELECTED or NO_SELECTION decision required")


def _summary(m: dict) -> dict:
    rows, d = m["trial_ledger"], m.get("decision")
    chosen = d["chosen_candidate"] if d else None
    # Display order of retained scores only; never rerun selection/incumbent logic.
    ranked = sorted((r for r in d["component_rows"] if r["eligible"] and r["score"] is not None
        and r.get("pareto_front", True)) if d else (), key=lambda r: (-r["score"], r["candidate_id"]))
    alternative = next((r["candidate_id"] for r in ranked if r["candidate_id"] != chosen), None) if chosen else None
    return dict(selection_status=d["status"] if d else None, chosen_candidate=chosen,
        runner_up_candidate=alternative, runner_up_basis="retained eligible scores and declared tie-break; not a new decision",
        decision_availability="RETAINED" if d else "No decision sealed; runtime failed before candidate selection.",
        trial_states=dict(Counter(r["state"] for r in rows)), attempts=len(rows),
        duplicate_attempts=sum(r.get("reason") == "DUPLICATE_EFFECTIVE_PARAMS" for r in rows),
        unique_evaluated_candidates=len({r["candidate_id"] for r in rows if r.get("components") is not None}),
        gate_excluded_candidates=[r["candidate_id"] for r in d["component_rows"] if not r["eligible"]] if d else [],
        raw_sharpe_semantics=("original continuous whole-account Sharpe; annual mean is separate"
            if m["schema"] == CONTINUOUS else "runtime mean of independent reset-window Sharpes; nulls counted as zero by runtime"),
        objective_semantics="frozen selector score in declared channel; not raw Sharpe",
        objective_unit=d["channel"]["unit"] if d else None,
        raw_sharpe_unit="annualized_daily_return_ratio",
        account_semantics=("one original account per effective query; annual views are dependent attribution, not resets"
            if m["schema"] == CONTINUOUS else "independent reset-flat environment observations; final full-development account is separate"))


def _public(private: dict) -> dict:
    m = private["runtime"]
    ids = list(dict.fromkeys(r["candidate_id"] for r in m["trial_ledger"] if r.get("candidate_id")))
    aliases = {cid: f"candidate-{i+1}" for i, cid in enumerate(ids)}
    def alias(cid):
        return aliases.get(cid)
    summary = dict(private["summary"])
    for key in ("chosen_candidate", "runner_up_candidate"):
        summary[key] = alias(summary[key])
    summary["gate_excluded_candidates"] = [alias(cid) for cid in summary["gate_excluded_candidates"]]
    runtime = _pick(m, "schema status validation_claim optimizer_schedule") | _public_numbers(m,
        "batch_size candidate_sequence_equivalent_to_sequential annual_account_resets meta_learning_activated "
        "automatic_routing deployment_authorized")
    # Public enums are allowlisted; arbitrary supplied prose, IDs and recipe knobs stay private.
    for key, allowed in {"optimizer_schedule": {"sequential_exact", "fixed_batch"}}.items():
        if key in runtime and runtime[key] not in allowed:
            runtime[key] = "REDACTED"
    sampler = m["sampler"]
    runtime["sampler"] = _pick(sampler, "states") | _public_numbers(sampler, "attempts requested_trials unique_effective_candidates "
        "feasible_complete warm_start_attempts duplicate_attempts relative_proposal_trials qmc_sequence_position")
    for key, allowed in {
        "recipe": {"tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"},
        "sampler_class": {"TPESampler", "CmaEsSampler", "QMCSampler", "ConditionalNumericSobol"},
        "resume": {"owned_in_process_study_only"},
        "constraint_mode": {"post_filter", "sampler"},
        "mixed_space_policy": {"reject", "explicit_independent"},
    }.items():
        runtime["sampler"][key] = sampler.get(key) if sampler.get(key) in allowed else "REDACTED"
    runtime["sampler"].update(kwargs="REDACTED", seed="REDACTED", startup_policy="REDACTED",
        independent_sample_calls=_public_numbers({"counts": list(sampler.get("independent_sample_calls", {}).values())}, "counts")["counts"],
        rows=[dict(trial_id=r["trial_id"], state=r["state"],
            source=r.get("source") if r.get("source") in {"sampled", "warm_start"} else "REDACTED",
            relative_dimension_count=len(r.get("relative_dimensions", ()))) for r in sampler["rows"]])
    runtime["trial_ledger"] = [_pick(r, "trial_id state") | _public_numbers(r,
        "objective raw_sharpe raw_whole_sharpe annual_mean_raw_sharpe")
        | dict(candidate_id=alias(r.get("candidate_id")), params="REDACTED",
               reason=r.get("reason") if r.get("reason") in TRIAL_REASONS else "REDACTED")
        for r in m["trial_ledger"]]
    for private_row, public_row in zip(m["trial_ledger"], runtime["trial_ledger"], strict=True):
        if "observations" in private_row:
            public_row["observations"] = [_public_observation(o, i) for i, o in enumerate(private_row["observations"])]
        if "whole_observation" in private_row:
            public_row["whole_observation"] = _public_observation(private_row["whole_observation"], 0)
    d = m.get("decision")
    runtime["decision"] = None
    if d is not None:
        runtime["decision"] = _pick(d, "status formula_version")
        runtime["decision"].update(chosen_candidate=alias(d["chosen_candidate"]),
            formula_coefficients="REDACTED", channel=_pick(d["channel"], "name unit"),
            reference="REDACTED", pre_incumbent_candidate=alias(d.get("pre_incumbent_candidate")),
            post_incumbent_candidate=alias(d.get("post_incumbent_candidate")),
            incumbent_guard=d.get("incumbent_guard") if d.get("incumbent_guard") in {
                "NO_INCUMBENT", "INCUMBENT_INELIGIBLE", "CHALLENGER_ACCEPTED", "INCUMBENT_RETAINED_BY_DECLARED_MARGIN"
            } else "REDACTED", component_rows=[])
        for key in ("requested_selector", "resolved_selector"):
            runtime["decision"][key] = d.get(key) if d.get(key) in SELECTORS else "REDACTED"
        for part in d["component_rows"]:
            components = _public_numbers(part["components"] or {}, "floor mean sd mad tail mean_regret max_regret "
                "activity_penalty fragility normalized_fragility empirical_local_worst normalized_gaps "
                "chebyshev extrapolated non_discriminative floor_tail_redundancy")
            runtime["decision"]["component_rows"].append(dict(candidate_id=alias(part["candidate_id"]),
                eligible=part["eligible"], score=part["score"], components=components or None,
                pareto_front=part.get("pareto_front"),
                reasons=[r if r in GATE_REASONS else "REDACTED" for r in part["reasons"]]))
    runtime["selected_audit"] = ([_public_observation(o, i) for i, o in enumerate(m["selected_audit"])]
                                 if m.get("selected_audit") is not None else None)
    return dict(schema=SCHEMA.replace(".v1", ".public.v1"), runtime=runtime,
                selected_params="REDACTED" if private["selected_params"] is not None else None,
                summary=summary, limits=list(LIMITS))


@dataclass(frozen=True)
class DecisionReport:
    """Immutable bounded snapshot. ``read`` requires actual params on success."""

    record: Record = field(repr=False)

    @classmethod
    def read(cls, metadata: Mapping[str, Any], *, selected_params: Mapping[str, Any] | None = None) -> DecisionReport:
        try:
            runtime = _snapshot(metadata)
            return cls(Record.of(dict(schema=SCHEMA, runtime=runtime,
                selected_params=dict(selected_params) if selected_params is not None else None,
                summary=_summary(runtime), limits=list(LIMITS))))
        except (KeyError, TypeError) as exc:
            raise ValueError("complete retained runtime metadata required") from exc

    @classmethod
    def from_json(cls, payload: str) -> DecisionReport:
        """Reload an explicit private snapshot, not a redacted public view."""
        return cls(Record.of(json.loads(payload)))

    def __post_init__(self) -> None:
        if not isinstance(self.record, Record):
            raise ValueError("immutable report Record required")
        d = self.record.data
        if set(d) != {"schema", "runtime", "selected_params", "summary", "limits"} or d["schema"] != SCHEMA:
            raise ValueError("complete private decision report snapshot required")
        try:
            if d["runtime"] != _snapshot(d["runtime"]):
                raise ValueError("bounded runtime snapshot required")
            _validate(d["runtime"], d["selected_params"])
            if d["summary"] != _summary(d["runtime"]) or d["limits"] != list(LIMITS):
                raise ValueError("altered report summary or limitations")
        except (KeyError, TypeError) as exc:
            raise ValueError("complete retained runtime metadata required") from exc

    def to_dict(self, *, private: bool = False) -> dict:
        if type(private) is not bool:
            raise ValueError("private disclosure requires an explicit boolean")
        data = self.record.data
        return data if private else _public(data)

    def to_json(self, *, private: bool = False) -> str:
        return Record.of(self.to_dict(private=private)).payload + "\n"

    def to_markdown(self, *, private: bool = False) -> str:
        data = self.to_dict(private=private)
        m, d = data["runtime"], data["runtime"].get("decision")
        lines = ["# Mode5 Decision Report", "", *data["limits"], ""]

        def cell(value):
            text = escape(json.dumps(value, sort_keys=True, allow_nan=False), quote=True)
            for char in ("\\", "|", "`", "[", "]", "*", "_"):
                text = text.replace(char, "\\" + char)
            return text.replace("\n", "<br>")

        def table(title, columns, rows):
            lines.extend(["## " + title, "", "| " + " | ".join(columns) + " |",
                          "| " + " | ".join("---" for _ in columns) + " |"])
            for row in rows:
                lines.append("| " + " | ".join(cell(value) for value in row) + " |")
            lines.append("")

        sections = {
            "Summary and Scope": data["summary"] | _pick(m, "status validation_claim account_scope "
                "environment_account_policy final_account_policy financial_scope annual_account_resets"),
            "Actual Sampler Provenance": {k: v for k, v in m["sampler"].items() if k != "rows"},
            "Frozen Selection and Tradeoffs": {k: v for k, v in (d or {"decision": None}).items()
                                              if k not in {"component_rows", "evidence_refs"}},
            "Actual Selected Dictionary": data["selected_params"] if isinstance(data["selected_params"], dict)
                else {"selected_params": data["selected_params"]},
            "Replay and Work": _pick(m, "selected_audit compute_bill chronology"),
        }
        for title, values in sections.items():
            table(title, ("Field", "Retained Value"), values.items())
        table("Trials", ("Trial", "State", "Candidate", "Objective", "Raw Sharpe", "Reason"),
              ((r["trial_id"], r["state"], r.get("candidate_id"), r.get("objective"),
                r.get("raw_sharpe"), r.get("reason")) for r in m["trial_ledger"]))
        if d is not None:
            names = ("floor", "mean", "tail", "mad", "fragility")
            table("Candidate Components", ("Candidate", "Eligible", "Score", *names, "Gate Reasons"),
                  ((r["candidate_id"], r["eligible"], r["score"],
                    *((r.get("components") or {}).get(name) for name in names), r["reasons"])
                   for r in d["component_rows"]))
        table("Environment Observations", ("Trial", "Environment", "Net Return", "DD", "Utility", "Daily Count", "Quality", "Risk", "Support"),
              ((r["trial_id"], o.get("environment_id"), o.get("net_return"), o.get("max_drawdown"),
                (o.get("utility") or {}).get("value"), o.get("daily_count"), o.get("quality_pass"),
                o.get("risk_pass"), o.get("support_pass"))
               for r in m["trial_ledger"] for o in r.get("observations", ())))
        return "\n".join(lines)

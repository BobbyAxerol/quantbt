"""Cold reconciliation to original Mode 5 decisions and actual final marks."""
from dataclasses import dataclass
import json
from types import SimpleNamespace

from quantbt.mode5.decision_report import DecisionReport
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.dossier.records import Record


@dataclass(frozen=True)
class CalibrationRunReport:
    record: Record

    def __post_init__(self):
        d = self.record.data
        if (set(d) != {"schema", "pack_id", "worksheet_id", "plan_id", "binding_id", "status",
                       "mismatches", "actual_decision", "final_account", "partial_work", "limitations"}
                or d["schema"] != "quantbt.calibration_run_report.v1"
                or d["status"] not in {"RECONCILED_RETAINED_RUN", "NO_SELECTION", "FAILED_UNVERIFIED", "MISMATCH"}):
            raise ValueError("complete bounded reconciliation report required")
        if (d["status"] == "MISMATCH") != bool(d["mismatches"]):
            raise ValueError("mismatch status and reasons disagree")
        if d["actual_decision"] is not None:
            actual = DecisionReport(Record.of(d["actual_decision"]))
            runtime = actual.record.data["runtime"]
            for field, key in (("calibration_plan_id", "plan_id"), ("runtime_binding_identity", "binding_id")):
                if d["status"] != "MISMATCH" and runtime.get(field) != d[key]:
                    raise ValueError("reconciliation decision/plan lineage differs")
        else:
            runtime = None
        work = d["partial_work"]
        if (not isinstance(work, dict) or set(work) != {"producer_status", "error_type", "retained_trial_rows", "trial_dispositions"}
                or type(work["retained_trial_rows"]) is not int or work["retained_trial_rows"] < 0
                or not isinstance(work["trial_dispositions"], list)
                or work["retained_trial_rows"] != len(work["trial_dispositions"])):
            raise ValueError("typed retained-work counts required")
        if runtime is not None and work["retained_trial_rows"] != len(runtime["trial_ledger"]):
            raise ValueError("retained-work count differs from actual decision")
        if d["status"] == "RECONCILED_RETAINED_RUN" or d["final_account"].get("status") == "MATCHED_ORIGINAL_MARKS":
            if runtime is None or runtime["status"] != "SELECTED_REPLAY_VERIFIED":
                raise ValueError("a reconciled run needs its actual selected decision")
            final = d["final_account"]
            scope = runtime["account_scope"]
            calendar = dict(start_ns=scope["scored_start_ns"], stop_ns=scope["scored_stop_ns"],
                step_ns=scope["bar_interval_ns"], bars=scope["scored_bars"])
            selected = next(row["whole_observation"] for row in runtime["trial_ledger"]
                if row.get("candidate_id") == runtime["selected_params_digest"] and row["state"] == "COMPLETE")
            if (final.get("status") != "MATCHED_ORIGINAL_MARKS" or final.get("calendar") != calendar
                    or any(final.get(k) != selected[k] for k in
                           ("finance", "initial_capital", "final_equity", "metric_contract", "closed_records", "liquidated"))):
                raise ValueError("final account status is not substantiated by retained decision/calendar")
        if d["status"] == "NO_SELECTION" and (runtime is None or runtime.get("error_type") != "Mode5NoSelectionError"):
            raise ValueError("NO_SELECTION needs an actual validated no-selection outcome")

    @classmethod
    def from_json(cls, payload):
        return cls(Record.of(json.loads(payload)))

    def to_dict(self, *, private=False):
        if type(private) is not bool:
            raise ValueError("private disclosure requires an explicit boolean")
        if private:
            return self.record.data
        d = self.record.data
        decision = DecisionReport(Record.of(d["actual_decision"])) if d["actual_decision"] else None
        return dict(schema="quantbt.calibration_run_report.public.v1", status=d["status"],
            mismatch_count=len(d["mismatches"]),
            actual_decision=decision.to_dict() if decision else None,
            final_account_verified=d["final_account"].get("status") == "MATCHED_ORIGINAL_MARKS",
            retained_trial_rows=d["partial_work"]["retained_trial_rows"],
            deployment_authorized=False)

    def to_json(self, *, private=False):
        return Record.of(self.to_dict(private=private)).payload

    def to_markdown(self, *, private=False):
        from .render import render_run
        return render_run(self, private=private)


def reconcile(pack, outcome):
    """Read existing metadata and reduce final marks once; never replay execution.

    This checks consistency of a retained run, not renewed evidence permissions
    or an independent financial certification. Execution preflight owns those
    current source/role checks.
    """
    expected = pack.record.data
    if hasattr(outcome, "mode5_metadata"):
        metadata, selected, result = outcome.mode5_metadata, None, None
    else:
        result = outcome
        wf = result.metadata.get("walk_forward", {})
        metadata = wf.get("mode5_diagnostics_first", {})
        selected = wf.get("best_trial", {}).get("params")
    mismatches = []
    for field, wanted in (("dossier_id", expected["plan"]["dossier_id"]),
            ("calibration_plan_id", expected["plan_id"]),
            ("runtime_binding_identity", expected["binding_id"])):
        if metadata.get(field) != wanted:
            mismatches.append("actual " + field + " differs from compiled plan")
    decision = None
    status = "FAILED_UNVERIFIED"
    final = dict(status="NOT_AVAILABLE", reason="No selected final account supplied")
    try:
        decision = DecisionReport.read(metadata, selected_params=selected)
    except (ValueError, KeyError, TypeError) as error:
        if metadata.get("status") == "SELECTED_REPLAY_VERIFIED":
            mismatches.append("actual decision validation: " + str(error))
    if decision is not None:
        binding = expected["binding"]
        wanted = expected["plan"]["recipe"]
        from .verification import policy_mismatches
        mismatches.extend(policy_mismatches(pack, metadata))
        if metadata.get("status") == "SELECTED_REPLAY_VERIFIED":
            if len(metadata["trial_ledger"]) != expected["plan"]["search_budget"]:
                mismatches.append("terminal attempt count differs from declared budget")
            actual = metadata["decision"]
            if (actual["formula_version"] != wanted["objective"]["version"]
                    or dict(actual["formula_coefficients"]) != wanted["objective"]["coefficients"]
                    or actual["resolved_selector"] != wanted["selector"]["id"]
                    or actual["requested_selector"] != binding["selection"]["requested_selector"]
                    or actual["channel"] != wanted["objective"]["channel"]
                    or actual["reference"]["reference_id"] != wanted["objective"]["reference_id"]):
                mismatches.append("actual objective/channel/reference/selector differs from recipe")
            if result is not None:
                from quantbt.mode5.evaluation import Mode5MetricPolicy
                policy = Mode5MetricPolicy(SimpleNamespace(binding=Record.of(binding)))
                observed = policy.observe(result, result.equity.index)
                chosen = digest(selected)
                original = next(r["whole_observation"] for r in metadata["trial_ledger"]
                    if r.get("candidate_id") == chosen and r["state"] == "COMPLETE")
                differences = [key for key in ("finance", "metric_contract", "daily_count", "partial_days",
                    "closed_records", "closed_record_unit", "liquidated", "initial_capital", "final_equity",
                    "support_pass", "risk_pass", "quality_pass", "net_return", "max_drawdown", "daily_loss_es", "raw_sharpe", "utility")
                               if Record.of({"value": observed[key]}) != Record.of({"value": original[key]})]
                import numpy as np
                import pandas as pd
                idx, c = result.equity.index, binding["continuous"]
                step = binding["metrics"]["bar_interval_ns"]
                calendar = dict(start_ns=c["start_ns"], stop_ns=c["stop_ns"], step_ns=step,
                    bars=(c["stop_ns"]-c["start_ns"]) // step)
                if (not isinstance(idx, pd.DatetimeIndex) or idx.tz is None or len(idx) != calendar["bars"]
                        or int(idx.asi8[0]) != c["start_ns"] or int(idx.asi8[-1])+step != c["stop_ns"]
                        or np.any(np.diff(idx.asi8) != step)):
                    differences.append("scored_calendar")
                for name in ("positions", "fees", "funding", "margin"):
                    item = getattr(result, name, None)
                    if isinstance(item, (pd.Series, pd.DataFrame)) and not item.index.equals(idx):
                        differences.append(name + "_calendar")
                if differences:
                    mismatches.append("final original account differs in " + ", ".join(differences))
                final = dict(status="MISMATCH" if differences else "MATCHED_ORIGINAL_MARKS",
                    finance=observed["finance"], initial_capital=observed["initial_capital"],
                    final_equity=observed["final_equity"], metric_contract=observed["metric_contract"],
                    calendar=calendar, closed_records=observed["closed_records"], liquidated=observed["liquidated"],
                    ledger_validation="Not an independent reconciliation of every fill/trade ledger field",
                    external_parameters_fixed=True, annual_account_resets=metadata["annual_account_resets"])
                status = "RECONCILED_RETAINED_RUN"
        elif metadata.get("error_type") == "Mode5NoSelectionError":
            status = "NO_SELECTION"
    if mismatches:
        status = "MISMATCH"
    return CalibrationRunReport(Record.of(dict(schema="quantbt.calibration_run_report.v1",
        pack_id=pack.identity, worksheet_id=expected["worksheet_id"], plan_id=expected["plan_id"],
        binding_id=expected["binding_id"], status=status, mismatches=mismatches,
        actual_decision=decision.record.data if decision else None, final_account=final,
        partial_work=dict(producer_status=metadata.get("status"), error_type=metadata.get("error_type"),
            retained_trial_rows=len(metadata.get("trial_ledger", ())),
            trial_dispositions=[{k: row.get(k) for k in ("trial_id", "state", "reason", "error_type")}
                                for row in metadata.get("trial_ledger", ())]),
        limitations=["Cold retained-run consistency, not fresh evidence rights or independent accounting certification.",
            "Full-development calibration, not independent OOS or deployment authority.",
            "Static utility/regret and prefix-forward decay are distinct; missing support remains explicit."])))

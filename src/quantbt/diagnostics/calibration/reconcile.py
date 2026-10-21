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
                       "mismatches", "actual_decision", "final_account", "limitations"}
                or d["schema"] != "quantbt.calibration_run_report.v1"
                or d["status"] not in {"RECONCILED_RETAINED_RUN", "NO_SELECTION", "FAILED_UNVERIFIED", "MISMATCH"}):
            raise ValueError("complete bounded reconciliation report required")
        if (d["status"] == "MISMATCH") != bool(d["mismatches"]):
            raise ValueError("mismatch status and reasons disagree")
        if d["actual_decision"] is not None:
            DecisionReport(Record.of(d["actual_decision"]))

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
        sampler, binding = metadata["sampler"], expected["binding"]
        wanted = expected["plan"]["recipe"]
        if (sampler.get("recipe") != binding["sampler"]["name"]
                or sampler.get("seed") != wanted["sampler"]["seeds"][0]):
            mismatches.append("actual sampler recipe/seed differs from compiled plan")
        # Runtime kwargs include resolved factory defaults; configured overrides
        # must agree, but those additional defaults are not erased from the report.
        if any(sampler.get("kwargs", {}).get(k) != v for k, v in binding["sampler"]["kwargs"].items()):
            mismatches.append("actual sampler kwargs differ from configured overrides")
        if (metadata.get("optimizer_schedule") != wanted["sampler"]["schedule"]
                or metadata.get("batch_size") != binding["batch_size"]):
            mismatches.append("actual optimizer schedule/batch differs from compiled plan")
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
                differences = [key for key in ("finance", "net_return", "max_drawdown", "daily_loss_es", "raw_sharpe", "utility")
                               if observed[key] != original[key]]
                if differences:
                    mismatches.append("final original account differs in " + ", ".join(differences))
                final = dict(status="MISMATCH" if differences else "MATCHED_ORIGINAL_MARKS",
                    finance=observed["finance"], initial_capital=observed["initial_capital"],
                    final_equity=observed["final_equity"], metric_contract=observed["metric_contract"],
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
        limitations=["Cold retained-run consistency, not fresh evidence rights or independent accounting certification.",
            "Full-development calibration, not independent OOS or deployment authority.",
            "Static utility/regret and prefix-forward decay are distinct; missing support remains explicit."])))

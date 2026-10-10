"""Explicit recipe proposals; a deferred seal cannot authorize a search."""
from dataclasses import dataclass

from tools.mode5_selection.contracts import Channel, Formula, FORMULAS
from tools.mode5_diagnostics.access import AccessPolicy
from .records import Record, require_text

FIELDS = ("sampler", "objective", "selector", "domain", "probes", "constraints",
          "support", "validation", "incumbent", "retention", "reuse", "failure")


@dataclass(frozen=True)
class CalibrationPlan:
    record: Record

    @classmethod
    def defer(cls, dossier, reason):
        require_text(reason)
        return cls(Record.of({"schema": "quantbt.calibration_plan.v1", "dossier_id": dossier.record.identity,
            "context": dossier.record.data["context"], "mode_id": "mode_5_full_robust",
            "status": "DEFER_CALIBRATION", "reason": reason, "search_budget": 0,
            "recipe": {k: {"value": None, "reason": "researcher choice not authorized"} for k in FIELDS},
            "deployment_authorized": False, "validation_claim": "none_full_sample_calibration"}))

    @classmethod
    def search(cls, dossier, spec, reason):
        require_text(reason)
        if set(spec) != set(FIELDS) | {"search_budget"}:
            raise ValueError("all frozen recipe/budget fields required")
        if any(not isinstance(spec[k], dict) or not spec[k] for k in FIELDS):
            raise ValueError("explicit nonempty recipe contracts required")
        budget = spec["search_budget"]
        if type(budget) is not int or budget <= 0:
            raise ValueError("positive registered query budget required")
        objective = spec["objective"]
        channel = Channel(**objective["channel"])
        formula = Formula(objective["version"], channel, tuple(objective["coefficients"].items()))
        selector = spec["selector"]
        family = FORMULAS[formula.version][0]
        allowed = {"full_dro_cvar": {"environment", "unified"}, "full_sam_basin": {"local"},
                   "full_pareto_chebyshev": {"pareto"}}
        if (selector["id"] not in allowed or family not in allowed[selector["id"]]
                or selector["tie_break"] != "candidate_id_lexicographic_v1"):
            raise ValueError("canonical selector/formula required")
        recipe_id = selector["id"] + ":" + formula.version
        permitted = [a["recipe_id"] for a in dossier.record.data["recommendations"]["recipes"]
                     if a["status"] == "CONSIDER_FINITE_PANEL"]
        if recipe_id not in permitted:
            raise ValueError("recipe needs an eligible new diagnostic revision")
        sampler = spec["sampler"]
        if sampler["name"] not in {"tpe_legacy", "tpe_multivariate_group", "sobol", "cmaes"}:
            raise ValueError("unsupported sampler recipe")
        if (not sampler["seeds"] or any(type(v) is not int for v in sampler["seeds"])
                or sampler["schedule"] not in {"sequential_exact", "fixed_batch"}):
            raise ValueError("explicit RNG/schedule contract required")
        require_text(sampler["fallback"])
        if spec["validation"].get("no_auto_deploy") is not True:
            raise ValueError("selection is not deployment permission")
        if spec["domain"].get("schema_id") != dossier.record.data["context"]["schema"]:
            raise ValueError("search domain differs from dossier")
        if spec["objective"].get("reference_id") != dossier.record.data["context"]["references"]:
            raise ValueError("frozen references differ from dossier")
        for field in ("probes", "constraints", "support", "validation", "incumbent", "retention", "reuse", "failure"):
            require_text(spec[field].get("contract_id"))
        if not spec["domain"].get("ranges"):
            raise ValueError("explicit effective search domain required")
        if not spec["probes"].get("design") or type(spec["probes"].get("budget")) is not int:
            raise ValueError("frozen local design/budget required")
        if not spec["validation"].get("roles") or not spec["validation"].get("contamination_status"):
            raise ValueError("explicit validation roles/contamination contract required")
        policy = spec["reuse"]["selection_policy"]
        access = AccessPolicy(**{**policy, "roles": tuple(policy["roles"]), "manifests": tuple(policy["manifests"])})
        if access.purpose != "selection":
            raise ValueError("declared selection rights required")
        return cls(Record.of({"schema": "quantbt.calibration_plan.v1", "dossier_id": dossier.record.identity,
            "context": dossier.record.data["context"], "mode_id": "mode_5_full_robust",
            "status": "RESEARCHER_CHOICE", "reason": reason, "search_budget": budget,
            "recipe": {k: spec[k] for k in FIELDS}, "deployment_authorized": False,
            "validation_claim": "none_full_sample_calibration"}))

    def verify(self, dossier):
        data = self.record.data
        if data["status"] == "DEFER_CALIBRATION":
            rebuilt = self.defer(dossier, data["reason"])
        elif data["status"] == "RESEARCHER_CHOICE":
            rebuilt = self.search(dossier, {**data["recipe"], "search_budget": data["search_budget"]}, data["reason"])
        else:
            raise ValueError("unknown calibration authority")
        if self != rebuilt:
            raise ValueError("invalid or stale plan")

"""Append-only, content-bound chronology. Not an engine permission system."""
import json
from pathlib import Path
import time

from tools.mode5_baseline.isolation import write_json
from tools.mode5_diagnostics.access import AccessPolicy
from .records import Record, require_text


class GovernanceLog:
    def __init__(self, directory):
        self.directory = Path(directory)
        if any(p.is_symlink() for p in (self.directory, *self.directory.parents)):
            raise ValueError("symlink journal forbidden")
        self.directory.mkdir(parents=True, exist_ok=True)

    def history(self):
        rows = []
        for i, path in enumerate(sorted(self.directory.glob("*.json"))):
            envelope = json.loads(path.read_text())
            event = Record.of(envelope["event"])
            data = event.data
            if (path.name != f"{i:06d}.json" or envelope["identity"] != event.identity
                    or data["sequence"] != i or data["parent"] != (rows[-1].identity if rows else None)
                    or type(data["sealed_at_ns"]) is not int
                    or (rows and data["sealed_at_ns"] <= rows[-1].data["sealed_at_ns"])):
                raise ValueError("modified, missing or reordered journal event")
            rows.append(event)
        return tuple(rows)

    def _append(self, kind, payload):
        history = self.history()
        now = time.time_ns()
        if history and now <= history[-1].data["sealed_at_ns"]:
            raise ValueError("nonmonotonic seal clock")
        event = Record.of({"schema": "quantbt.diagnostic_governance.v1", "kind": kind,
            "sequence": len(history), "parent": history[-1].identity if history else None,
            "sealed_at_ns": now, "payload": payload})
        write_json(self.directory / f"{len(history):06d}.json", {"event": event.data, "identity": event.identity})
        return event

    def seal_dossier(self, dossier, catalog):
        catalog.verify_current()
        dossier.verify(catalog)
        return self._append("DOSSIER_SEALED", {"dossier_id": dossier.record.identity,
                                               "context": dossier.record.data["context"]})

    def seal_plan(self, dossier, plan, catalog, *, researcher, reason):
        require_text(researcher)
        require_text(reason)
        catalog.verify_current()
        dossier.verify(catalog)
        plan.verify(dossier)
        history = self.history()
        if not any(e.data["kind"] == "DOSSIER_SEALED" and
                   e.data["payload"]["dossier_id"] == dossier.record.identity for e in history):
            raise PermissionError("dossier must be sealed before the plan")
        if any(e.data["kind"] == "FORMAL_SEARCH_STARTED" for e in history):
            raise PermissionError("post-hoc plan revision cannot inherit a pre-search badge")
        choices = dossier.record.data["recommendations"]["recipes"]
        chosen = plan.record.data["recipe"].get("selector", {}).get("id")
        return self._append("PLAN_SEALED", {"dossier_id": dossier.record.identity,
            "plan_id": plan.record.identity, "plan": plan.record.data, "researcher": researcher,
            "reason": reason, "override_first_advice": bool(chosen and choices and
                not choices[0]["recipe_id"].startswith(chosen + ":")), "automatic_routing": False})

    def begin_search(self, dossier, plan, catalog, selection_access, trial_id):
        require_text(trial_id)
        catalog.verify_current()
        dossier.verify(catalog)
        plan.verify(dossier)
        if plan.record.data["status"] != "RESEARCHER_CHOICE":
            raise PermissionError("deferred plan has zero tuning authority")
        if not isinstance(selection_access, AccessPolicy) or selection_access.purpose != "selection":
            raise PermissionError("fresh selection rights required, not a hash/cache hit")
        policy = plan.record.data["recipe"]["reuse"]["selection_policy"]
        declared = AccessPolicy(**{**policy, "roles": tuple(policy["roles"]), "manifests": tuple(policy["manifests"])})
        if selection_access != declared:
            raise PermissionError("selection policy differs from sealed plan")
        for source in catalog.manifest.data["sources"]:
            from tools.mode5_diagnostics.access import AccessWitness
            selection_access.require(AccessWitness(**source["witness"]))
        seals = [e for e in self.history() if e.data["kind"] == "PLAN_SEALED"]
        if not seals or seals[-1].data["payload"]["plan_id"] != plan.record.identity:
            raise PermissionError("matching current sealed plan required before formal trial")
        return self._append("FORMAL_SEARCH_STARTED", {"plan_id": plan.record.identity,
            "trial_id": trial_id, "selection_access_id": selection_access.identity,
            "validation_claim": "none_full_sample_calibration", "deployment_authorized": False})

    def request_auto_route(self, *args, **kwargs):
        raise PermissionError("no whole-procedure-qualified routing policy in V1")


def require_formal_chronology(log, dossier_id, plan_id, first_trial_ns):
    """A late profile may describe old trials, never certify prior registration."""
    if type(first_trial_ns) is not int:
        raise ValueError("exact actual first-formal-trial timestamp required")
    history = log.history()
    dossiers = [e for e in history if e.data["kind"] == "DOSSIER_SEALED"
                and e.data["payload"]["dossier_id"] == dossier_id]
    plans = [e for e in history if e.data["kind"] == "PLAN_SEALED"
             and e.data["payload"]["plan_id"] == plan_id
             and e.data["payload"]["dossier_id"] == dossier_id]
    if (not dossiers or not plans or plans[-1].data["payload"]["plan"]["status"] != "RESEARCHER_CHOICE"
            or not dossiers[-1].data["sealed_at_ns"] < plans[-1].data["sealed_at_ns"] < first_trial_ns):
        raise PermissionError("post-hoc profile cannot certify a pre-search calibration")
    return Record.of(dict(status="PRE_SEARCH_ORDER_VERIFIED", dossier_id=dossier_id,
                          plan_id=plan_id, first_trial_ns=first_trial_ns,
                          validation_claim="none_full_sample_calibration"))

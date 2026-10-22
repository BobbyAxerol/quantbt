"""Five-axis raw evidence and advisory readiness, never an alpha-name router."""
from dataclasses import dataclass
import math

from .evidence import KINDS, Matrix, reconcile_rosters
from .records import Record, require_text

AXES = ("mechanics_economics", "geometry", "environments", "transfer", "distributions_tails")
DEPENDENCIES = ("alpha", "data", "economics", "schema", "roles", "metrics", "references", "scope")


def radar_point(*, metric, value, unit, direction, support, uncertainty, reason,
                ref, definition_ref, reference_id, lower=None, upper=None):
    for text in (metric, unit, reference_id):
        require_text(text)
    if direction not in {-1, 1} or type(direction) is not int:
        raise ValueError("explicit metric direction required")
    if value is None:
        require_text(reason)
    elif type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError("finite raw measure or null+reason required")
    if not isinstance(support, dict) or not support:
        raise ValueError("observed support metadata required")
    if (lower is None) != (upper is None):
        raise ValueError("complete frozen scale or raw-only view")
    if lower is not None and (not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper):
        raise ValueError("nondegenerate frozen reference required")
    normalized = None if value is None or lower is None else (value-lower)/(upper-lower)
    if normalized is not None and direction == -1:
        normalized = 1-normalized
    return dict(metric=metric, value=value, unit=unit, direction=direction,
                support=support, uncertainty=uncertainty, reason=reason, ref=ref, definition_ref=definition_ref,
                reference_id=reference_id, lower=lower, upper=upper,
                normalized=normalized, extrapolated=None if normalized is None else not 0 <= normalized <= 1,
                rendering="RAW_ONLY" if lower is None else "FROZEN_REFERENCE")


def ordered_advice(assessments):
    """Order by observed support readiness; ties are not economic winners."""
    states = {"CONSIDER_FINITE_PANEL": 0, "NO_SUPPORTED_CONFIGURATION_ON_REGISTERED_PANEL": 1,
              "INSUFFICIENT_COVERAGE": 2}
    if len({a["recipe_id"] for a in assessments}) != len(assessments):
        raise ValueError("distinct versioned recipes required")
    for a in assessments:
        if a["status"] not in states or not a["refs"] or not a["reasons"]:
            raise ValueError("measured support and reasons required")
        if type(a["selected_decisions"]) is not int or a["selected_decisions"] < 0:
            raise ValueError("observed decision count required")
    rows = sorted(assessments, key=lambda a: (states[a["status"]], a["recipe_id"]))
    return {"status": "NO_CLEAR_WINNER", "ranking_basis": "evidence_readiness_not_economic_dominance_v1",
            "recipes": rows, "automatic_routing": False, "whole_procedure_qualified": False}


@dataclass(frozen=True)
class Dossier:
    record: Record

    def verify(self, catalog):
        data = self.record.data
        rosters = tuple(Record.of(data["matrices"][k]["roster"]) for k in KINDS)
        matrices = tuple(Matrix(
            Record.of(data["matrices"][k])) for k in KINDS)
        inventory = Record.of(catalog.require_ref(data["inventory_ref"]))
        rebuilt = self.create(context=Record.of(data["context"]), matrices=matrices,
            rosters=rosters, inventory=inventory, inventory_ref=data["inventory_ref"], catalog=catalog, axes=data["axes"],
            radar=data["radar"], batteries=data["batteries"],
            assessments=data["recommendations"]["recipes"], limitations=data["limitations"],
            compute_bill=data["compute_bill"])
        if rebuilt != self:
            raise ValueError("invalid or stale dossier")

    @classmethod
    def create(cls, *, context, matrices, rosters, inventory, inventory_ref, catalog, axes, radar,
               batteries, assessments, limitations, compute_bill):
        context = context.data
        if set(context) != set(DEPENDENCIES) or any(not isinstance(v, str) or not v for v in context.values()):
            raise ValueError("complete alpha/data/economic/schema/role/statistics identities required")
        reconcile_rosters(rosters, inventory)
        if inventory.data != catalog.require_ref(inventory_ref):
            raise ValueError("independent registered inventory differs")
        if len(matrices) != 6 or {m.record.data["kind"] for m in matrices} != set(KINDS):
            raise ValueError("all six evidence matrices required")
        by_kind = {r.data["kind"]: r for r in rosters}
        for matrix in matrices:
            matrix.verify(by_kind[matrix.record.data["kind"]], catalog)
        if set(axes) != set(AXES) or set(radar) != set(AXES):
            raise ValueError("all five axes required")
        for axis in AXES:
            if not axes[axis]["refs"] or not radar[axis]:
                raise ValueError("explicit raw/null measurements and evidence required")
            for ref in axes[axis]["refs"]:
                catalog.require_ref(ref)
            for point in radar[axis]:
                catalog.require_ref(point["ref"])
                rebuilt = radar_point(**{k: v for k, v in point.items()
                                        if k not in {"normalized", "extrapolated", "rendering"}})
                if rebuilt != point:
                    raise ValueError("altered radar reference/measurement")
                raw = catalog.require_ref(point["ref"])
                if raw != point["value"]:
                    raise ValueError("radar value does not match source")
                definition = catalog.require_ref(point["definition_ref"])
                if definition != {k: point[k] for k in (
                        "metric", "unit", "direction", "reference_id", "lower", "upper")}:
                    raise ValueError("radar unit/direction/reference differs from frozen definition")
        for a in assessments:
            for ref in a["refs"]:
                catalog.require_ref(ref)
        return cls(Record.of({"schema": "quantbt.alpha_diagnostic_dossier.v2", "context": context,
            "validity": {"technical": "VERIFIED_SOURCE_RECONCILIATION", "coverage": "BOUNDED_DESCRIPTIVE",
                         "independent_validation": "NOT_QUALIFIED"},
            "matrices": {m.record.data["kind"]: m.record.data for m in matrices},
            "inventory_ref": inventory_ref,
            "source_manifest": catalog.manifest.data, "axes": axes, "radar": radar,
            "batteries": batteries, "recommendations": ordered_advice(assessments),
            "limitations": limitations, "compute_bill": compute_bill,
            "deployment_authorized": False}))


def invalidation(old_context, new_context):
    old, new = old_context.data, new_context.data
    if set(old) != set(DEPENDENCIES) or set(new) != set(DEPENDENCIES):
        raise ValueError("complete dependency identities required")
    changed = sorted(k for k in DEPENDENCIES if old[k] != new[k])
    return {"changed": changed, "dossier_reusable": not changed,
            "plan_reusable": not changed,
            "execution_reusable": not bool(set(changed) & {"alpha", "data", "economics", "schema", "scope"}),
            "analysis_reusable": not bool(set(changed) & {"alpha", "data", "economics", "schema", "scope", "metrics", "references"}),
            "reuse_requires_fresh_access_check": True}

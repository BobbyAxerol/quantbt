"""Read-only D07 views over retained dossier owners; no execution or selection.

Private JSON can be cold-read without source files. ``verify`` checks current
evidence separately; a cold read is not a new integrity or scientific certificate.
Public export deliberately redacts *all* supplied prose and values, including
numbers that could be private parameters. Only counts, enums and masks survive.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html import escape
import json
from typing import Literal, Mapping, Sequence, TypeAlias, Union, get_args

from .dossier import Dossier
from .evidence import EvidenceCatalog, KINDS
from .records import Record, require_text

JSONValue: TypeAlias = Union[None, bool, int, float, str,
                            list["JSONValue"], dict[str, "JSONValue"]]
Basis = Literal["MEASURED", "SOURCE", "HYPOTHESIS"]
Status = Literal["OBSERVED", "NEGATIVE", "MISSING", "NO_TRADE", "FAILED",
                 "NOT_RUN", "INSUFFICIENT_SUPPORT", "NOT_APPLICABLE"]
ViewName = Literal["scope_test_behavior", "parameter_profile", "parameter_regions",
                   "environment_profile", "stress_profile", "decision_worksheet"]
VIEWS = get_args(ViewName)
MASKS = {
    "evaluated": (True, False, None), "interpolated": (True, False, None),
    "support": ("ADEQUATE", "SPARSE", "NONE", "UNKNOWN", "NOT_APPLICABLE"),
    "uncertainty": ("QUANTIFIED", "NOT_ESTIMATED", "NOT_APPLICABLE"),
    "coverage": ("COMPLETE", "PARTIAL", "MISSING", "UNKNOWN", "NOT_APPLICABLE"),
}
VIEW_MATRICES = dict(zip(VIEWS, (
    (), ("parameter_representation",), ("center_neighbor_environment",),
    ("candidate_environment", "environment_environment"),
    ("execution_stress",), ("recipe_split_seed",),
)))
TITLES = ("Scope and Test Behavior", "Parameter Profile", "Parameter Regions",
          "Environment Profile", "Stress Profile", "Decision Worksheet")
ABSENT = {"MISSING", "NOT_RUN", "NOT_APPLICABLE"}
SCHEMA = "quantbt.researcher_report.v1"
AUTHORITY = {"automatic_routing": False, "deployment_authorized": False,
             "independent_validation": "NOT_QUALIFIED"}


def _reference(ref: dict) -> None:
    if not isinstance(ref, dict) or set(ref) != {"source", "pointer", "sha256"}:
        raise ValueError("existing evidence reference required")
    require_text(ref["source"])
    if not isinstance(ref["pointer"], str) or (ref["pointer"] and not ref["pointer"].startswith("/")):
        raise ValueError("absolute JSON pointer required")
    digest = ref["sha256"]
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("evidence digest required")


@dataclass(frozen=True)
class Finding:
    """Immutable annotated finding, using existing Record/ref ownership.

    MEASURED/SOURCE values bind to ``value_ref`` exactly. HYPOTHESIS values are
    proposals, not measured outcomes; their refs supply background only.
    Missing evidence/uncertainty requires an explicit reason, never imputation.
    """

    record: Record

    @classmethod
    def create(cls, *, row_id: str, label: str, basis: Basis, status: Status,
               value: JSONValue, unit: str, support: Mapping[str, JSONValue],
               uncertainty: Mapping[str, JSONValue], evidence: Sequence[dict],
               interpretation: str, rival_explanation: str, decision_implication: str,
               next_test: str, masks: Mapping[str, JSONValue],
               value_ref: dict | None = None, reason: str | None = None) -> Finding:
        return cls(Record.of(dict(row_id=row_id, label=label, basis=basis, status=status,
            value=value, unit=unit, support=dict(support), uncertainty=dict(uncertainty),
            evidence=list(evidence), value_ref=value_ref, interpretation=interpretation,
            rival_explanation=rival_explanation, decision_implication=decision_implication,
            next_test=next_test, masks=dict(masks), reason=reason)))

    def __post_init__(self) -> None:
        if not isinstance(self.record, Record):
            raise ValueError("immutable finding Record required")
        d = self.record.data
        if set(d) != {"row_id", "label", "basis", "status", "value", "unit", "support",
                      "uncertainty", "evidence", "value_ref", "interpretation",
                      "rival_explanation", "decision_implication", "next_test", "masks", "reason"}:
            raise ValueError("complete finding schema required")
        for key in ("row_id", "label", "unit", "interpretation", "rival_explanation",
                    "decision_implication", "next_test"):
            require_text(d[key])
        if d["basis"] not in get_args(Basis) or d["status"] not in get_args(Status):
            raise ValueError("explicit fact/hypothesis and outcome status required")
        if d["value"] is None or d["status"] != "OBSERVED" or d["reason"] is not None:
            require_text(d["reason"])
        if not isinstance(d["support"], dict) or not d["support"]:
            raise ValueError("explicit support metadata required")
        u = d["uncertainty"]
        if not isinstance(u, dict) or not {"value", "reason"} <= set(u):
            raise ValueError("uncertainty value/reason required")
        if u["value"] is None or u["reason"] is not None:
            require_text(u["reason"])
        masks = d["masks"]
        if not isinstance(masks, dict) or set(masks) != set(MASKS):
            raise ValueError("all evaluation/interpolation/support/uncertainty/coverage masks required")
        for key, allowed in MASKS.items():
            if not any(type(masks[key]) is type(v) and masks[key] == v for v in allowed):
                raise ValueError("invalid mask: " + key)
        if masks["interpolated"] is True and masks["evaluated"] is True:
            raise ValueError("interpolation is not an evaluated observation")
        if d["basis"] == "MEASURED" and d["status"] not in ABSENT and (
                masks["evaluated"] is not True or masks["interpolated"] is not False):
            raise ValueError("measured finding requires evaluated, non-interpolated evidence")
        if d["status"] in ABSENT and masks["evaluated"] is True:
            raise ValueError("missing/not-run row cannot be evaluated")
        if (u["value"] is not None) != (masks["uncertainty"] == "QUANTIFIED"):
            raise ValueError("uncertainty mask differs from retained uncertainty")
        refs = d["evidence"]
        if not isinstance(refs, list) or (not refs and d["status"] not in ABSENT):
            raise ValueError("evidence pointers or explicit missing evidence required")
        for ref in refs:
            _reference(ref)
        ref = d["value_ref"]
        if ref is not None:
            _reference(ref)
            if ref not in refs or d["basis"] == "HYPOTHESIS":
                raise ValueError("value binding must be fact evidence, not a hypothesis")
        elif d["basis"] != "HYPOTHESIS" and (d["value"] is not None or d["status"] not in ABSENT):
            raise ValueError("measured/source value requires a source pointer")

    def verify(self, catalog: EvidenceCatalog) -> None:
        d = self.record.data
        for ref in d["evidence"]:
            catalog.require_ref(ref)
        if d["value_ref"] is not None:
            raw = catalog.require_ref(d["value_ref"])
            if Record.of({"value": raw}) != Record.of({"value": d["value"]}):
                raise ValueError("finding value differs from retained source")


@dataclass(frozen=True)
class ReportView:
    """Retained worksheet metadata plus annotated findings, not a new matrix."""

    name: ViewName
    details: Record
    findings: tuple[Finding, ...]

    def __post_init__(self) -> None:
        if self.name not in VIEWS or not isinstance(self.details, Record):
            raise ValueError("known view and immutable retained details required")
        if type(self.findings) is not tuple or any(not isinstance(f, Finding) for f in self.findings):
            raise ValueError("immutable typed findings required")
        ids = [f.record.data["row_id"] for f in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("distinct finding identities within each view required")


def _missing(name: str) -> Finding:
    return Finding.create(row_id=name + "/missing", label="Missing retained annotations",
        basis="SOURCE", status="MISSING", value=None, unit="not_available",
        support={"status": "UNKNOWN"}, uncertainty={"value": None, "reason": "Not supplied"},
        evidence=[], interpretation="No interpretation supplied; retained matrices remain below.",
        rival_explanation="Missing annotation is not evidence of no effect.",
        decision_implication="No decision supported by this absent annotation.",
        next_test="Identify the missing retained analysis and register its question before new work.",
        masks=dict(evaluated=False, interpolated=False, support="UNKNOWN",
                   uncertainty="NOT_ESTIMATED", coverage="MISSING"), reason="No retained findings supplied")


def _summary(dossier: dict, views: dict) -> dict:
    findings = [f for v in views.values() for f in v["findings"]]
    return {"matrix_rows": {k: len(dossier["matrices"][k]["rows"]) for k in KINDS},
            "finding_rows": {k: len(views[k]["findings"]) for k in VIEWS},
            "basis_counts": dict(Counter(f["basis"] for f in findings)),
            "status_counts": dict(Counter(f["status"] for f in findings))}


def _assemble(dossier: Record, supplied: Sequence[ReportView]) -> Record:
    by_name = {v.name: v for v in supplied}
    if len(by_name) != len(supplied):
        raise ValueError("duplicate report view")
    views = {}
    for name in VIEWS:
        view = by_name.get(name, ReportView(name, Record.of({
            "status": "MISSING", "reason": "No retained view details supplied"}), ()))
        views[name] = {"details": view.details.data,
                       "findings": [f.record.data for f in view.findings or (_missing(name),)],
                       "matrix_kinds": list(VIEW_MATRICES[name])}
    raw = dossier.data
    return Record.of({"schema": SCHEMA, "dossier_id": dossier.identity, "dossier": raw,
                      "views": views, "summary": _summary(raw, views), "authority": AUTHORITY})


@dataclass(frozen=True)
class ResearcherReport:
    record: Record

    @classmethod
    def read(cls, dossier: Dossier, catalog: EvidenceCatalog, *,
             views: Sequence[ReportView] = ()) -> ResearcherReport:
        """Assemble from retained owners and annotations; never launch missing work."""
        if not isinstance(dossier, Dossier) or any(not isinstance(v, ReportView) for v in views):
            raise ValueError("existing dossier and typed report views required")
        report = cls(_assemble(dossier.record, views))
        report.verify(catalog)
        return report

    @classmethod
    def from_json(cls, payload: str) -> ResearcherReport:
        """Cold-read a private snapshot; use verify for fresh source/access checks."""
        return cls(Record.of(json.loads(payload)))

    def __post_init__(self) -> None:
        if not isinstance(self.record, Record):
            raise ValueError("immutable report Record required")
        d = self.record.data
        if (set(d) != {"schema", "dossier_id", "dossier", "views", "summary", "authority"}
                or d["schema"] != SCHEMA or set(d["views"]) != set(VIEWS)
                or set(d["dossier"]["matrices"]) != set(KINDS)):
            raise ValueError("complete versioned report required")
        views = self._views()
        if self.record != _assemble(Record.of(d["dossier"]), views):
            raise ValueError("altered report identity, masks, mapping, summary or authority")

    def _views(self) -> tuple[ReportView, ...]:
        data = self.record.data["views"]
        views = []
        for name in VIEWS:
            v = data[name]
            if set(v) != {"details", "findings", "matrix_kinds"}:
                raise ValueError("complete report view required")
            views.append(ReportView(name, Record.of(v["details"]),
                                    tuple(Finding(Record.of(f)) for f in v["findings"])))
        return tuple(views)

    def verify(self, catalog: EvidenceCatalog) -> None:
        catalog.verify_current()
        Dossier(Record.of(self.record.data["dossier"])).verify(catalog)
        for view in self._views():
            for finding in view.findings:
                finding.verify(catalog)

    def public_record(self) -> Record:
        """Allowlist structural data; do not recursively preserve private scalars."""
        private = self.record.data
        d = private["dossier"]
        public = {k: {"status": "REDACTED"} for k in (
            "context", "source_manifest", "axes", "batteries", "compute_bill")}
        public.update(radar={}, limitations=["Private content redacted."],
            validity={"status": "REDACTED"}, inventory_ref=None,
            recommendations={"status": "REDACTED", "recipes": [], "automatic_routing": False},
            matrices={})
        for kind in KINDS:
            rows = []
            for i, row in enumerate(d["matrices"][kind]["rows"]):
                value = row["value"]
                status = value.get("status") if isinstance(value, dict) else None
                status = status if isinstance(status, str) and status in get_args(Status) else "UNKNOWN"
                rows.append({"row_id": f"row-{i+1}", "ref": None, "value": None,
                             "status": status, "reason": "Private content redacted."})
            public["matrices"][kind] = {"rows": rows, "roster_id": None}
        views = {}
        for name in VIEWS:
            findings = []
            for i, f in enumerate(private["views"][name]["findings"]):
                safe = {k: f[k] for k in ("basis", "status", "masks")}
                safe.update(row_id=f"finding-{i+1}", label=f"Finding {i+1}", value=None,
                    unit="REDACTED", support={"status": "REDACTED"},
                    uncertainty={"value": None, "reason": "Private content redacted."},
                    evidence=[], value_ref=None)
                for key in ("interpretation", "rival_explanation", "decision_implication", "next_test", "reason"):
                    safe[key] = "Private content redacted."
                findings.append(safe)
            views[name] = {"details": {"status": "REDACTED"}, "findings": findings,
                           "matrix_kinds": list(VIEW_MATRICES[name])}
        return Record.of({"schema": "quantbt.researcher_report.public.v1", "dossier_id": None,
            "dossier": public, "views": views, "summary": private["summary"], "authority": AUTHORITY})

    def to_json(self, *, public: bool = False) -> str:
        return (self.public_record() if public else self.record).payload + "\n"

    def to_markdown(self, *, public: bool = False) -> str:
        return _markdown((self.public_record() if public else self.record).data)


def _cell(value: JSONValue) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, allow_nan=False)
    text = escape(text, quote=True).replace("\\", "\\\\")
    for char in ("|", "`", "[", "]", "*", "_"):
        text = text.replace(char, "\\" + char)
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _table(headers: Sequence[str], rows: Sequence[Sequence[JSONValue]]) -> list[str]:
    return ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(_cell(v) for v in row) + " |" for row in rows), ""]


def _metadata(data: dict) -> list[str]:
    return _table(("Field", "Retained Record"), sorted(data.items()))


def _markdown(data: dict) -> str:
    d = data["dossier"]
    lines = ["# Researcher Report", "", "Retained descriptive evidence; no new execution or selection.", "",
             "## Identity and Limits", ""]
    lines += _metadata({"schema": data["schema"], "dossier_id": data["dossier_id"],
        "authority": data["authority"], "context": d["context"],
        "source_manifest": d["source_manifest"], "validity": d["validity"],
        "inventory_ref": d["inventory_ref"], "limitations": d["limitations"]})
    lines += ["## Numeric Inventory", ""] + _metadata(data["summary"])
    lines += ["## AlphaQualityRiskProfile", ""] + _metadata(d["axes"])
    for axis, points in sorted(d["radar"].items()):
        lines += ["### " + _cell(axis), ""]
        keys = ("metric", "value", "unit", "support", "uncertainty", "reason")
        lines += _table(("Metric", "Value", "Unit", "Support", "Uncertainty", "Reason", "Frozen Definition"),
            [(*[p[k] for k in keys], {k: v for k, v in p.items() if k not in keys}) for p in points])
    lines += ["## RecipeSuitabilityProfile", ""] + _metadata(d["recommendations"])
    for name, title in zip(VIEWS, TITLES):
        view = data["views"][name]
        lines += ["## " + title, ""] + _metadata(view["details"])
        if name == "scope_test_behavior":
            lines += _metadata({"batteries": d["batteries"], "compute_bill": d["compute_bill"]})
        findings = view["findings"]
        keys = ("row_id", "label", "basis", "status", "value", "unit", "support", "uncertainty", "masks")
        lines += _table(("ID", "Finding", "Basis", "Status", "Value", "Unit", "Support", "Uncertainty", "Masks"),
                        [[f[k] for k in keys] for f in findings])
        lines += _table(("ID", "Evidence", "Interpretation", "Rival Explanation", "Decision Implication", "Next Test", "Reason"),
            [(f["row_id"], {"refs": f["evidence"], "value_ref": f["value_ref"]}, f["interpretation"],
              f["rival_explanation"], f["decision_implication"], f["next_test"], f["reason"]) for f in findings])
        for kind in view["matrix_kinds"]:
            matrix = d["matrices"][kind]
            lines += ["### " + kind.replace("_", " ").title(), ""]
            lines += _metadata({"roster_id": matrix["roster_id"], "retained_rows": len(matrix["rows"])})
            lines += _table(("Registered Row", "Evidence", "Retained Value", "Metadata and Masks"),
                [(r["row_id"], r["ref"], r["value"],
                  {k: v for k, v in r.items() if k not in {"row_id", "ref", "value"}}) for r in matrix["rows"]])
    return "\n".join(lines)

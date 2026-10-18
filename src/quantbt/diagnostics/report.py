"""Immutable cold reports and explicit researcher choices, never activation."""

from dataclasses import dataclass, replace

from quantbt.mode5.dossier.records import Record, require_text

from .access import AccessWitness
from .contracts import require_diagnostic_access
from .identity import digest

AUTHORITY = dict(automatic_routing=False, optimizer_started=False,
                 meta_activated=False, deployment_authorized=False,
                 economic_superiority="NOT_QUALIFIED")


@dataclass(frozen=True)
class AlphaDiagnosticReport:
    record: Record

    def __post_init__(self):
        if not isinstance(self.record, Record):
            raise ValueError("immutable shared report Record required")
        data = self.record.data
        required = {"schema", "context_id", "context", "geometry_id", "access_policy_id",
            "cutoff_ns", "source_witnesses", "evaluation_ids", "observation_identities",
            "source_refs", "geometry", "coverage", "activity", "associations", "analyses",
            "advice", "sampler_compatibility", "researcher_choice", "limitations", "authority"}
        if (set(data) not in (required, required | {"researcher_diagnostics"}) or data["schema"] != "quantbt.alpha_diagnostics.v1"
                or data["authority"] != AUTHORITY
                or data["context_id"] != digest({"schema": "quantbt.diagnostic_context.v1", **data["context"]})
                or len(data["evaluation_ids"]) != len(data["observation_identities"])
                or len(data["evaluation_ids"]) != len(data["source_refs"])):
            raise ValueError("shared diagnostic report without execution authority required")
        for row in data["source_witnesses"]:
            AccessWitness(**row)
        if "researcher_diagnostics" in data:
            research = data["researcher_diagnostics"]
            if (research.get("schema") != "quantbt.presearch_researcher.v1"
                    or research.get("view") not in {"prefix", "full_development", "retrospective"}
                    or research["provenance"]["context_id"] != data["context_id"]
                    or research["provenance"]["geometry_id"] != data["geometry_id"]
                    or research["provenance"]["cutoff_ns"] != data["cutoff_ns"]
                    or research["search"]["retained_observations"] != len(data["evaluation_ids"])):
                raise ValueError("researcher view context/schema/scope mismatch")

    @property
    def identity(self):
        return self.record.identity

    def to_dict(self, *, public=False):
        if public:
            from .research_render import public_data
            return public_data(self.record.data)
        return self.record.data

    def to_json(self, *, public=False):
        if public:
            return Record.of(self.to_dict(public=True)).payload
        return self.record.payload

    def authorize(self, access):
        """Recheck every source even when a retained report has the same hash."""
        require_diagnostic_access(access)
        for row in self.record.data["source_witnesses"]:
            access.require(AccessWitness(**row))
        if access.identity != self.record.data["access_policy_id"]:
            raise PermissionError("changed policy requires fresh report assembly")
        return self

    def with_choice(self, *, access, sampler_id, selector_id, reason):
        self.authorize(access)
        require_text(reason)
        data = self.to_dict()
        for kind, selected in (("sampler", sampler_id), ("selector", selector_id)):
            options = [r for r in data["advice"] if r["kind"] == kind]
            if selected is not None and selected not in {r["recipe_id"] for r in options}:
                raise ValueError("choice outside the explicit shortlist requires revised advice")
            if kind == "sampler" and selected is not None:
                compatible = {r["recipe_id"] for r in data["sampler_compatibility"]
                              if r["compatible"]}
                if selected not in compatible:
                    raise ValueError("incompatible sampler cannot be activated by a report choice")
        data["researcher_choice"] = dict(sampler_id=sampler_id, selector_id=selector_id,
            reason=reason, parent_report_id=self.identity, applies_configuration=False)
        return replace(self, record=Record.of(data))

    def to_markdown(self, *, public=False):
        if public:
            from .research_render import public_markdown
            return public_markdown(self.to_dict(public=True))
        data = self.to_dict()
        def cell(value):
            return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        lines = ["# Alpha Diagnostics", "", "Status: descriptive / researcher decision support.",
                 "No optimizer, meta activation or deployment is performed.", "",
                 "## Scope", f"Context: {data['context_id']}",
                 f"Permitted cutoff (ns): {data['cutoff_ns']}", "", "## Coverage"]
        for key, value in data["coverage"].items():
            lines.append(f"- {cell(key)}: {cell(value)}")
        lines += ["", "## Parameter Support", "| Axis | Kind | Active evaluations | Observed values |",
                  "|---|---|---:|---:|"]
        for row in data["geometry"]["axes"]:
            lines.append("| " + " | ".join(cell(row[k]) for k in
                ("name", "kind", "active_evaluations", "observed_values")) + " |")
        lines += ["", "## Activity"]
        for key, value in data["activity"].items():
            lines.append(f"- {cell(key)}: {cell(value)}")
        lines += ["", "## Parameter Associations", data["associations"]["status"],
                  data["associations"]["reason"]]
        result = data["associations"]["result"]
        if result is not None:
            lines += ["| Branch | Axis | Metric | Rho | Paired candidates |",
                      "|---|---|---|---:|---:|"]
            for branch, value in result["branches"].items():
                for axis, metrics in value["associations"].items():
                    for metric, row in metrics.items():
                        lines.append("| " + " | ".join(cell(v) for v in
                            (branch[:12], axis, metric, row["rho"], row["support"]["paired_candidates"])) + " |")
        lines += ["", "## Recipe Options", "| Kind | Recipe | Basis | Rationale | Missing |",
                  "|---|---|---|---|---|"]
        for row in data["advice"]:
            lines.append("| " + " | ".join(cell(row[k]) for k in
                ("kind", "recipe_id", "basis", "rationale", "missing_evidence")) + " |")
        if not data["advice"]:
            lines.append("No evidence-backed shortlist supplied; schema compatibility is not superiority.")
        lines += ["", "## Analysis Availability"]
        for name, row in data["analyses"].items():
            lines.append(f"- {name}: {cell(row['status'])}; {cell(row.get('reason', 'See source reference'))}")
        lines += ["", "## Limits", *["- " + cell(v) for v in data["limitations"]]]
        rendered = "\n".join(lines) + "\n"
        if "researcher_diagnostics" in data:
            from .research_render import markdown
            rendered += markdown(data["researcher_diagnostics"])
        return rendered

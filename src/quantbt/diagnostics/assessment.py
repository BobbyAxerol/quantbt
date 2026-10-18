"""Cold diagnostic assembly on shared geometry, metrics and access owners."""

from collections import Counter
from dataclasses import asdict
from itertools import islice

from quantbt.mode5.dossier.evidence import EvidenceCatalog
from quantbt.mode5.dossier.records import Record
from quantbt.optimization.config import SamplerConfig
from quantbt.optimization.parameter_space import NormalizedSearchSpace
from quantbt.optimization.samplers import validate_sampler_geometry

from .access import AccessWitness
from .contracts import (DiagnosticAdvice, DiagnosticAnalysis, DiagnosticBudget,
    DiagnosticContext, DiagnosticObservation, require_diagnostic_access)
from .geometry import EffectiveGeometry, finite_panel_screen
from .identity import canonical, digest
from .report import AUTHORITY, AlphaDiagnosticReport


class AlphaDiagnostics:
    """Analyze caller-supplied pre-search evidence, without calling a strategy.

    The caller owns financial evaluation and the permitted information scope.
    No mutable account/model/RNG or implicit result cache belongs to this object.
    """

    def __init__(self, param_ranges, *, context, access, geometry=None,
                 budget=DiagnosticBudget()):
        if not isinstance(context, DiagnosticContext) or not isinstance(budget, DiagnosticBudget):
            raise ValueError("typed diagnostic context and budget required")
        require_diagnostic_access(access)
        space = NormalizedSearchSpace(param_ranges)
        geometry = geometry or EffectiveGeometry.from_ranges(param_ranges)
        if not isinstance(geometry, EffectiveGeometry) or geometry.specs != space.specs:
            raise ValueError("geometry and sampler must share the same parameter schema")
        self.context, self.access, self.geometry, self.budget = context, access, geometry, budget
        portable = space.portable_ranges()
        for spec in space.specs:
            if spec.active_if:
                portable[spec.name]["active_if"] = dict(spec.active_if)
        # Parent order is semantic for conditional spaces; canonical JSON keys
        # are sorted, so retain the shared schema's ordered pairs explicitly.
        self._ranges = Record.of({"parameters": list(portable.items())})

    def sampler_compatibility(self):
        result = []
        for name in ("tpe_legacy", "tpe_multivariate_group", "cmaes", "sobol"):
            try:
                validate_sampler_geometry(SamplerConfig(name=name),
                                          dict(self._ranges.data["parameters"]))
                reason, compatible = "Shared schema preflight passed; performance is unmeasured.", True
            except ValueError as exc:
                reason, compatible = str(exc), False
            result.append(dict(recipe_id=name, compatible=compatible, reason=reason,
                dependency_checked=False, empirical_superiority="NOT_ASSESSED"))
        return result

    def analyze(self, observations=(), *, analyses=(), catalog=None, advice=(),
                bootstrap_seed=731, bootstrap_resamples=64, research=None):
        rows = tuple(islice(iter(observations), self.budget.max_observations + 1))
        analyses, advice = tuple(analyses), tuple(advice)
        if len(rows) > self.budget.max_observations:
            raise ValueError("diagnostic observation budget exceeded; no rows silently dropped")
        units = dict(self.context.metric_units)
        seen, witnesses = set(), {}
        for row in rows:
            if not isinstance(row, DiagnosticObservation):
                raise ValueError("typed diagnostic observations required")
            self.access.require(row.witness)
            if (row.context_id != self.context.identity or row.point.schema_id != self.geometry.identity
                    or set(row.metrics.data) != set(units) or row.evaluation_id in seen):
                raise ValueError("context/schema/metric mismatch or duplicate evaluation ID")
            actual = self.geometry.resolve(row.point.params)
            if actual.identity != row.point.identity or actual.active_names != row.point.active_names:
                raise ValueError("effective point does not match canonical geometry")
            if row.activity_count is not None and self.context.activity_definition is None:
                raise ValueError("activity units/definition must be declared before analysis")
            seen.add(row.evaluation_id)
            witnesses[row.witness.identity] = row.witness

        if research is not None:
            from .researcher import require_research
            require_research(self, rows, research)
            witnesses[research.witness.identity] = research.witness
            for account in research.accounts:
                for witness in (account.evidence.witness, account.label_witness):
                    if witness is not None:
                        witnesses[witness.identity] = witness
            if research.dossier is not None:
                if not isinstance(catalog, EvidenceCatalog):
                    raise ValueError("original Dossier EvidenceCatalog required")
                for item in catalog.manifest.data["sources"]:
                    witness = AccessWitness(**item["witness"])
                    self.access.require(witness)
                    witnesses[witness.identity] = witness
                research.dossier.verify(catalog)
                dependency = research.dossier.record.data["context"]
                if research.dossier_geometry_ref is not None:
                    original_geometry = catalog.require_ref(research.dossier_geometry_ref.data)
                    if Record.of(original_geometry) != Record.of(self.geometry.metadata()):
                        raise ValueError("catalog-bound original dossier geometry differs")
                elif dependency["schema"] != self.geometry.identity:
                    raise ValueError("composite dossier schema requires an explicit catalog-bound geometry reference")
                if (dependency["alpha"] != self.context.alpha_id
                        or dependency["data"] != self.context.market_id
                        or dependency["economics"] != self.context.economics_id):
                    raise ValueError("dossier alpha/market/economics/geometry binding mismatch")

        optional = {name: dict(status="NOT_SUPPLIED", value=None,
            reason="No authorized matching analysis supplied; no financial replay requested.")
            for name in ("fragility", "environments", "factors")}
        if analyses and not isinstance(catalog, EvidenceCatalog):
            raise ValueError("existing hash-verified EvidenceCatalog required for optional analyses")
        if len({a.section for a in analyses if isinstance(a, DiagnosticAnalysis)}) != len(analyses):
            raise ValueError("distinct typed optional analyses required")
        refs = {}
        for analysis in analyses:
            if not isinstance(analysis, DiagnosticAnalysis) or analysis.context_id != self.context.identity:
                raise ValueError("optional analysis context mismatch")
            source = next((s for s in catalog.manifest.data["sources"]
                           if s["source_id"] == analysis.source_id), None)
            if source is None:
                raise ValueError("unknown optional analysis source")
            witness = AccessWitness(**source["witness"])
            self.access.require(witness)
            witnesses[witness.identity] = witness
            ref = catalog.ref(analysis.source_id, analysis.pointer)
            value = catalog.require_ref(ref)
            if not isinstance(value, dict) or value.get("context_id") != self.context.identity:
                raise ValueError("optional analysis context must be bound in verified source bytes")
            if research is not None:
                if value.get("geometry_id", self.geometry.identity) != self.geometry.identity:
                    raise ValueError("optional analysis geometry mismatch")
                if research.view == "prefix" and value.get("view", "prefix") != "prefix":
                    raise PermissionError("retrospective/full-development analysis cannot advise a prefix")
            refs[analysis.source_id] = ref
            optional[analysis.section] = dict(status="SOURCE_BOUND_ANALYSIS", value=value,
                reference=ref, reason="Existing producer analysis; no re-estimation or qualification inferred.")
        if analyses:
            catalog.verify_current()

        unique = {r.point.identity for r in rows}
        complete = [r for r in rows if r.status in {"COMPLETE", "NO_TRADE"}]
        axes = []
        for spec in self.geometry.specs:
            active = [r for r in rows if spec.name in r.point.active_names]
            values = [r.point.params[spec.name] for r in active]
            axes.append(dict(name=spec.name, kind=spec.kind, variable=spec.variable,
                conditional=bool(spec.active_if), source_inactive=spec.name in dict(self.geometry.inactive),
                active_evaluations=len(active), observed_values=len({canonical(v) for v in values}),
                declared_choices=len(spec.choices) if spec.choices else None,
                interpretation="Observed support only; not global importance or an inactive-parameter proof."))

        activity = [r.activity_count for r in complete if r.activity_count is not None]
        screens = self._associations(rows, units, bootstrap_seed, bootstrap_resamples)
        evidence_ids = {"geometry", "coverage", "activity", "associations", *seen, *refs}
        advice_rows = []
        for item in advice:
            if not isinstance(item, DiagnosticAdvice) or not set(item.evidence_ids) <= evidence_ids:
                raise ValueError("advice requires known retained evidence IDs")
            if item.basis == "OBSERVED_COMPARISON" and not set(item.evidence_ids) & set(refs):
                raise ValueError("observed recipe comparison requires a verified analysis source")
            advice_rows.append(asdict(item))
        if len({(r["kind"], r["recipe_id"]) for r in advice_rows}) != len(advice_rows):
            raise ValueError("duplicate recipe options")
        data = dict(schema="quantbt.alpha_diagnostics.v1", context_id=self.context.identity,
            context=asdict(self.context), geometry_id=self.geometry.identity,
            access_policy_id=self.access.identity, cutoff_ns=self.access.cutoff_ns,
            source_witnesses=[asdict(witnesses[k]) for k in sorted(witnesses)],
            evaluation_ids=[r.evaluation_id for r in rows],
            observation_identities=[digest(asdict(r)) for r in rows],
            source_refs=[r.source_ref for r in rows],
            geometry=dict(axes=axes, coupled_constraints=len(self.geometry.constraints)),
            coverage=dict(evaluations=len(rows), unique_effective_candidates=len(unique),
                duplicate_effective_evaluations=len(rows)-len(unique),
                status_counts=dict(sorted(Counter(r.status for r in rows).items())),
                measured_primary=sum(r.metrics.data[self.context.primary_metric] is not None for r in complete),
                missing_primary=sum(r.metrics.data[self.context.primary_metric] is None for r in complete)),
            activity=dict(status="OBSERVED" if activity else "NOT_SUPPLIED",
                definition=self.context.activity_definition, measured_evaluations=len(activity),
                missing_evaluations=len(complete)-len(activity),
                zero_activity_evaluations=sum(v == 0 for v in activity),
                minimum=min(activity) if activity else None, maximum=max(activity) if activity else None),
            associations=screens, analyses=optional, advice=advice_rows,
            sampler_compatibility=self.sampler_compatibility(), researcher_choice=None,
            limitations=["Conditional finite-panel diagnostics, not a universal best-recipe certificate.",
                "Financial metrics/activity are caller-produced; no equity/fill metric is redefined.",
                "Schema compatibility does not establish optimization quality or dependency availability.",
                "Missing local/regime evidence is not filled by a neutral score or market-outcome proxy.",
                "No causal factor, global Sobol, parameter-removal or economic superiority claim.",
                "Using any mode label does not expand meta mode/domain support."],
            authority=AUTHORITY)
        if research is not None:
            from .researcher import assemble_research
            data["researcher_diagnostics"] = assemble_research(self, rows, research,
                optional, data["sampler_compatibility"], advice_rows, screens)
            if research.dossier is not None or analyses:
                catalog.verify_current()
        record = Record.of(data)
        if len(record.payload.encode()) > self.budget.max_report_bytes:
            raise ValueError("diagnostic report byte budget exceeded; evidence not truncated")
        return AlphaDiagnosticReport(record)

    def _associations(self, rows, units, seed, resamples):
        if not self.context.outcome_blind_roster:
            return dict(status="NOT_ESTIMATED_ADAPTIVE_OR_REVIEWED_ROSTER", result=None,
                reason="Use a separately registered outcome-blind roster for finite-panel associations.")
        if len({row.point.identity for row in rows}) != len(rows):
            return dict(status="NOT_ESTIMATED_DUPLICATE_EFFECTIVE_CANDIDATES", result=None,
                reason="Repeated effective candidates remain in coverage; use a distinct qualified roster for association intervals.")
        axis_names = tuple(s.name for s in self.geometry.specs if s.variable and not s.choices
                           and s.name not in dict(self.geometry.inactive))
        if not rows or not axis_names:
            return dict(status="NO_NUMERIC_PANEL", result=None,
                        reason="No observed active numeric axes; categorical states are not ordinal-coded.")
        active_by_branch, candidates = {}, []
        for row in rows:
            params = row.point.params
            active = tuple(n for n in axis_names if n in row.point.active_names)
            branch = digest(dict(active=active, categories={s.name: params[s.name]
                for s in self.geometry.specs if s.choices and s.name in params}))
            active_by_branch[branch] = active
            candidates.append(dict(candidate_id=row.evaluation_id, branch_id=branch,
                status=row.status, parameters={name: params[name] for name in active},
                metrics=row.metrics.data))
        observed_axes = tuple(n for n in axis_names if any(n in a for a in active_by_branch.values()))
        if not observed_axes:
            return dict(status="NO_NUMERIC_PANEL", result=None, reason="All numeric branches inactive on roster.")
        result = finite_panel_screen(candidates, panel_id=digest([r.evaluation_id for r in rows]),
            axis_names=observed_axes, active_axes_by_branch=active_by_branch, units=units,
            outcome_blind=True, bootstrap_seed=seed, bootstrap_resamples=resamples)
        result.pop("candidate_rows")
        return dict(status="DESCRIPTIVE_FINITE_PANEL", result=result,
                    reason="Reuse of the existing branch-local rank-association reducer.")

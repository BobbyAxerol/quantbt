"""Immutable research inputs; financial evidence and permissions stay external."""

from dataclasses import asdict, dataclass
import math
from types import MappingProxyType

from tools.mode5_diagnostics.access import AccessPolicy, AccessWitness
from tools.mode5_diagnostics.identity import AnalysisKey, SelectionKey, canonical, digest
from tools.mode5_statistics.contracts import MetricValue
from tools.mode5_statistics.tails import FrozenReference


def nonempty(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty versioned identity required")


@dataclass(frozen=True)
class Channel:
    name: str
    metric_contract: str
    unit: str

    def __post_init__(self):
        expected = {"ECONOMIC_UTILITY_V1": "decimal_return", "PSR_EVIDENCE_V1": "probability",
                    "LEGACY_SHARPE_UTILITY_REPLAY": "legacy_sharpe_utility"}
        if self.name not in expected or self.unit != expected[self.name]:
            raise ValueError("channel and unit are incompatible")
        nonempty(self.metric_contract)

    @property
    def identity(self):
        return digest(asdict(self))

    def require(self, metric):
        if not isinstance(metric, MetricValue) or metric.unit != self.unit or metric.metric_id != self.metric_contract:
            raise ValueError("same metric contract/channel/unit required")
        if self.name == "PSR_EVIDENCE_V1" and metric.value is not None and not 0 <= metric.value <= 1:
            raise ValueError("evidence probability outside [0,1]")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    params_digest: str
    metrics: tuple[MetricValue, ...]
    analyses: tuple[AnalysisKey, ...]
    witnesses: tuple[AccessWitness, ...]
    gate_ref: str
    feasible: bool
    risk_pass: bool
    quality_pass: bool
    support_pass: bool
    evaluated: bool
    activity_penalty: float
    representative_kind: str = "evaluated_point"

    def __post_init__(self):
        for name in ("candidate_id", "params_digest", "gate_ref"):
            nonempty(getattr(self, name))
        for name in ("metrics", "analyses", "witnesses"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if (not self.metrics or len(self.metrics) != len(self.analyses) or len(self.metrics) != len(self.witnesses)
                or any(not isinstance(a, AnalysisKey) for a in self.analyses)
                or any(not isinstance(w, AccessWitness) for w in self.witnesses)):
            raise ValueError("complete ordered metric/analysis/access records required")
        if any(type(getattr(self, n)) is not bool for n in (
                "feasible", "risk_pass", "quality_pass", "support_pass", "evaluated")):
            raise ValueError("explicit qualification flags required")
        if not math.isfinite(self.activity_penalty) or self.activity_penalty < 0:
            raise ValueError("nonnegative same-channel activity penalty required")
        if self.representative_kind not in {"evaluated_point", "medoid", "centroid"}:
            raise ValueError("unknown representative semantics")


@dataclass(frozen=True)
class Panel:
    context_id: str
    revision: str
    channel: Channel
    reference: FrozenReference
    candidates: tuple[Candidate, ...]
    access: AccessPolicy
    generation: str
    generation_evidence: str

    def __post_init__(self):
        for name in ("context_id", "revision", "generation_evidence"):
            nonempty(getattr(self, name))
        object.__setattr__(self, "candidates", tuple(self.candidates))
        if not isinstance(self.channel, Channel) or not isinstance(self.reference, FrozenReference):
            raise TypeError("typed channel/reference required")
        if not isinstance(self.access, AccessPolicy) or self.access.purpose != "selection":
            raise ValueError("selection-only access policy required")
        if self.reference.channel != self.channel.identity:
            raise ValueError("reference channel differs from panel")
        if any(w <= 0 for w in self.reference.weights):
            raise ValueError("selector environment roster has strictly positive declared weights")
        if self.generation not in {"qmc", "tpe", "cma_es", "nsga_ii", "fixed_panel"}:
            raise ValueError("explicit candidate-generation provenance required")
        if not self.candidates or len({c.candidate_id for c in self.candidates}) != len(self.candidates):
            raise ValueError("nonempty distinct candidate IDs required")
        for c in self.candidates:
            if len(c.metrics) != len(self.reference.values):
                raise ValueError("candidate must retain every declared environment")
            for metric, analysis, witness in zip(c.metrics, c.analyses, c.witnesses, strict=True):
                self.channel.require(metric)
                self.access.require(witness)
                if analysis.normalization_reference != self.reference.identity:
                    raise ValueError("analysis reference differs from frozen panel")

    @property
    def identity(self):
        return digest(asdict(self))


FORMULAS = MappingProxyType({
    "environment_floor_mean_v1": ("environment", ("mean",)),
    "legacy_floor_mean_regret_v1": ("environment", ("mean",)),
    "legacy_spec_1_1_quantile": ("environment", ("floor", "tail", "dispersion", "alpha")),
    "environment_lower_tail_v2": ("environment", ("floor", "tail", "dispersion", "alpha")),
    "finite_panel_minimax_regret_v1": ("environment", ()),
    "local_downside_v1": ("local", ("gamma",)),
    "unified_same_channel_v1": ("unified", ("floor", "mean", "dispersion", "fragility")),
    "pareto_chebyshev_v1": ("pareto", ("rho",)),
})


@dataclass(frozen=True)
class Formula:
    version: str
    channel: Channel
    coefficients: tuple[tuple[str, float], ...]

    def __post_init__(self):
        if self.version not in FORMULAS or not isinstance(self.channel, Channel):
            raise ValueError("unknown versioned formula/channel")
        values = tuple(sorted(tuple(r) for r in self.coefficients))
        object.__setattr__(self, "coefficients", values)
        if tuple(k for k, _ in values) != tuple(sorted(FORMULAS[self.version][1])):
            raise ValueError("all formula coefficients must be explicit exactly once")
        if any(not math.isfinite(v) or v < 0 for _, v in values):
            raise ValueError("finite nonnegative declared preferences required")
        if "alpha" in self.params and not 0 < self.params["alpha"] <= 1:
            raise ValueError("tail alpha in (0,1] required")
        if self.version == "legacy_spec_1_1_quantile" and self.channel.name != "PSR_EVIDENCE_V1":
            raise ValueError("legacy guide quantile replay uses explicit PSR evidence")

    @property
    def params(self):
        return dict(self.coefficients)

    @property
    def identity(self):
        return digest({"registry": "mode5.formulas.v1", **asdict(self)})


@dataclass(frozen=True)
class Probe:
    probe_id: str
    value: float | None
    status: str
    analysis: AnalysisKey
    witness: AccessWitness

    def __post_init__(self):
        nonempty(self.probe_id)
        if self.status not in {"COMPLETE", "MISSING", "INVALID", "FAILED"}:
            raise ValueError("explicit probe result status required")
        if self.status == "COMPLETE":
            if self.value is None or not math.isfinite(self.value):
                raise ValueError("finite complete probe utility required")
        elif self.value is not None:
            raise ValueError("unknown probes require null, not favorable replacement")
        if not isinstance(self.analysis, AnalysisKey) or not isinstance(self.witness, AccessWitness):
            raise TypeError("probe evidence and access witness required")


@dataclass(frozen=True)
class LocalEvidence:
    candidate_id: str
    channel: Channel
    reference_id: str
    reference_scale: float
    aggregate: str
    expected_ids: tuple[str, ...]
    probes: tuple[Probe, ...]
    coverage: str
    covariance_status: str
    design_ref: str
    validation_ref: str

    def __post_init__(self):
        for name in ("candidate_id", "reference_id", "design_ref", "validation_ref"):
            nonempty(getattr(self, name))
        if not isinstance(self.channel, Channel) or not math.isfinite(self.reference_scale) or self.reference_scale <= 0:
            raise ValueError("same channel and positive frozen downside reference required")
        if self.aggregate != "weighted_environment_mean_v1":
            raise ValueError("center and probes must use the same declared aggregate")
        object.__setattr__(self, "expected_ids", tuple(self.expected_ids))
        object.__setattr__(self, "probes", tuple(self.probes))
        if (not self.expected_ids or len(set(self.expected_ids)) != len(self.expected_ids)
                or {p.probe_id for p in self.probes} != set(self.expected_ids)
                or len(self.probes) != len(self.expected_ids)):
            raise ValueError("one result per expected effective probe including failed/missing")
        if self.coverage not in {"OBSERVED_REQUIRED_RADII", "INSUFFICIENT_COVERAGE"}:
            raise ValueError("unknown geometry coverage status")
        if self.covariance_status not in {"SCHEMA_ONLY_REGISTERED", "SCHEMA_ONLY_INSUFFICIENT",
                                          "SCHEMA_PLUS_REGULARIZED_COVARIANCE"}:
            raise ValueError("schema floor cannot be replaced by covariance-only probes")

    @property
    def identity(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class SelectionPlan:
    plan_id: str
    context_id: str
    stage_id: str
    formula: Formula
    reference_identity: str
    requested_selector: str
    minimum_improvement: float
    incumbent_id: str | None = None
    tie_break: str = "candidate_id_lexicographic_v1"
    local_reference_id: str | None = None
    local_reference_scale: float | None = None
    pareto_preference_identity: str | None = None

    def __post_init__(self):
        for name in ("plan_id", "context_id", "stage_id", "reference_identity"):
            nonempty(getattr(self, name))
        allowed = {"full_dro_cvar": {"environment", "unified"}, "full_sam_basin": {"local"},
                   "full_pareto_chebyshev": {"pareto"}, "full_alpha_adaptive_invariant":
                   {"environment", "unified", "local", "pareto"}}
        if (not isinstance(self.formula, Formula) or self.requested_selector not in allowed
                or FORMULAS[self.formula.version][0] not in allowed[self.requested_selector]):
            raise ValueError("selector slot and explicit formula family differ")
        if not math.isfinite(self.minimum_improvement) or self.minimum_improvement < 0:
            raise ValueError("nonnegative same-score incumbent margin required")
        if self.tie_break != "candidate_id_lexicographic_v1":
            raise ValueError("unsupported tie policy")
        if self.incumbent_id is not None:
            nonempty(self.incumbent_id)
        if FORMULAS[self.formula.version][0] in {"local", "unified"}:
            nonempty(self.local_reference_id)
            if (self.local_reference_scale is None or not math.isfinite(self.local_reference_scale)
                    or self.local_reference_scale <= 0):
                raise ValueError("frozen positive local scale must be declared in the plan")
        elif self.local_reference_id is not None or self.local_reference_scale is not None:
            raise ValueError("local scale only belongs to local/unified formulas")
        if FORMULAS[self.formula.version][0] == "pareto":
            nonempty(self.pareto_preference_identity)
        elif self.pareto_preference_identity is not None:
            raise ValueError("Pareto preferences only belong to the vector family")

    @property
    def identity(self):
        return digest(asdict(self))

    def require(self, panel):
        if (panel.context_id != self.context_id or panel.channel != self.formula.channel
                or panel.reference.identity != self.reference_identity):
            raise ValueError("frozen plan context/channel/reference mismatch; create a revision")
        if self.incumbent_id is not None and self.incumbent_id not in {c.candidate_id for c in panel.candidates}:
            raise ValueError("incumbent must receive the same actual panel evaluation")


@dataclass(frozen=True)
class Decision:
    metadata_json: str

    @property
    def metadata(self):
        import json
        return json.loads(self.metadata_json)

    @property
    def identity(self):
        return digest(self.metadata)


def decision(panel, plan, metadata, *, local_refs=(), preference_ref="none"):
    key = SelectionKey(analyses=tuple(a.identity for c in panel.candidates for a in c.analyses),
        candidate_universe=panel.identity,
        objective_selector_preferences=digest((plan.formula.identity, local_refs, preference_ref,
                                               metadata.get("advisory"))),
        diagnostic_calibration_plan=plan.identity, access_scope=panel.access.identity)
    return Decision(canonical(dict(schema="mode5.selection_decision.v1", selection_key=key.identity,
        panel_identity=panel.identity, plan_identity=plan.identity, formula_version=plan.formula.version,
        formula_identity=plan.formula.identity, reference_identity=panel.reference.identity,
        channel=asdict(panel.channel), stage_id=plan.stage_id, requested_selector=plan.requested_selector,
        candidate_generation=panel.generation, generation_evidence=panel.generation_evidence,
        tie_break=plan.tie_break, edge_claim="NOT_ASSESSED", deployment_authorized=False, **metadata)))

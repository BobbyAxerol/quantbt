"""Immutable, mode-independent diagnostic inputs; no optimizer authority."""

from dataclasses import asdict, dataclass
import math

from quantbt.mode5.dossier.records import Record, require_text

from .access import AccessPolicy, AccessWitness
from .geometry.schema import EffectiveGeometry, ResolvedPoint
from .identity import digest


@dataclass(frozen=True)
class DiagnosticContext:
    alpha_id: str
    market_id: str
    economics_id: str
    route_id: str
    metric_units: tuple[tuple[str, str], ...]
    primary_metric: str
    direction: str
    generation_method: str
    outcome_blind_roster: bool = False
    activity_definition: str | None = None

    def __post_init__(self):
        for name in ("alpha_id", "market_id", "economics_id", "route_id",
                     "primary_metric", "generation_method"):
            require_text(getattr(self, name))
        if (type(self.metric_units) is not tuple or not self.metric_units
                or any(type(row) is not tuple or len(row) != 2 for row in self.metric_units)):
            raise ValueError("immutable metric names and units required")
        for name, unit in self.metric_units:
            require_text(name)
            require_text(unit)
        if (len(dict(self.metric_units)) != len(self.metric_units)
                or self.primary_metric not in dict(self.metric_units)
                or self.direction not in {"maximize", "minimize"}
                or type(self.outcome_blind_roster) is not bool):
            raise ValueError("unique metrics, primary direction and explicit design required")
        if self.activity_definition is not None:
            require_text(self.activity_definition)

    @property
    def identity(self):
        return digest({"schema": "quantbt.diagnostic_context.v1", **asdict(self)})


@dataclass(frozen=True)
class DiagnosticObservation:
    evaluation_id: str
    context_id: str
    point: ResolvedPoint
    metrics: Record
    witness: AccessWitness
    source_ref: str
    status: str = "COMPLETE"
    activity_count: int | None = None

    @classmethod
    def from_params(cls, *, geometry, params, metrics, **kwargs):
        if not isinstance(geometry, EffectiveGeometry):
            raise ValueError("shared EffectiveGeometry required")
        return cls(point=geometry.resolve(params), metrics=Record.of(dict(metrics)), **kwargs)

    def __post_init__(self):
        for name in ("evaluation_id", "context_id", "source_ref"):
            require_text(getattr(self, name))
        if (not isinstance(self.point, ResolvedPoint) or not isinstance(self.metrics, Record)
                or not isinstance(self.witness, AccessWitness)
                or self.status not in {"COMPLETE", "NO_TRADE", "FAILED", "INFEASIBLE", "CANCELLED"}
                or (self.activity_count is not None and
                    (type(self.activity_count) is not int or self.activity_count < 0))):
            raise ValueError("typed observation, disposition and optional activity required")
        for name, value in self.metrics.data.items():
            require_text(name)
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value)):
                raise ValueError("finite measured metrics or explicit null required")
        if self.status in {"FAILED", "INFEASIBLE", "CANCELLED"} and any(
                value is not None for value in self.metrics.data.values()):
            raise ValueError("failed observations cannot carry economic sentinels")


@dataclass(frozen=True)
class DiagnosticAnalysis:
    """Reference to a separately produced analysis in the existing catalog."""

    section: str
    context_id: str
    source_id: str
    pointer: str = ""

    def __post_init__(self):
        if self.section not in {"fragility", "environments", "factors", "sensitivity",
                                "selection", "sampler_comparison", "execution_stress"}:
            raise ValueError("known optional diagnostic section required")
        require_text(self.context_id)
        require_text(self.source_id)
        if not isinstance(self.pointer, str) or (self.pointer and not self.pointer.startswith("/")):
            raise ValueError("JSON pointer required")


@dataclass(frozen=True)
class DiagnosticAdvice:
    kind: str
    recipe_id: str
    rationale: str
    evidence_ids: tuple[str, ...]
    missing_evidence: tuple[str, ...] = ()
    basis: str = "RESEARCH_HYPOTHESIS"

    def __post_init__(self):
        if self.kind not in {"sampler", "selector"} or self.basis not in {
                "SCHEMA_COMPATIBILITY", "RESEARCH_HYPOTHESIS", "OBSERVED_COMPARISON"}:
            raise ValueError("explicit advice kind and basis required")
        require_text(self.recipe_id)
        require_text(self.rationale)
        for rows in (self.evidence_ids, self.missing_evidence):
            if type(rows) is not tuple or len(set(rows)) != len(rows):
                raise ValueError("immutable distinct evidence/reason IDs required")
            for value in rows:
                require_text(value)
        if not self.evidence_ids:
            raise ValueError("advice requires traceable evidence, not an alpha-name rule")


@dataclass(frozen=True)
class DiagnosticBudget:
    max_observations: int = 10_000
    max_report_bytes: int = 4 * 1024 * 1024
    max_account_bytes: int = 32 * 1024 * 1024

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError("positive exact diagnostic resource limits required")


def require_diagnostic_access(access):
    if not isinstance(access, AccessPolicy) or access.purpose != "diagnostic":
        raise PermissionError("explicit development diagnostic access required")

"""Inner/outer information frontier layered on the existing access contract."""

from dataclasses import asdict, dataclass

from tools.mode5_diagnostics import AccessPolicy, AccessWitness
from tools.mode5_diagnostics.access import DEVELOPMENT_ROLES, VALIDATION_ROLES
from tools.mode5_diagnostics.identity import digest


@dataclass(frozen=True)
class ChronologyPlan:
    plan_id: str
    train: AccessWitness
    inner_validation: AccessWitness
    outer_validation: AccessWitness
    discovery_cutoff_ns: int
    claim: str = "chronological"

    def __post_init__(self):
        witnesses = (self.train, self.inner_validation, self.outer_validation)
        if (not self.plan_id or any(not isinstance(w, AccessWitness) for w in witnesses)
                or type(self.discovery_cutoff_ns) is not int
                or self.claim not in {"chronological", "retrospective_transfer"}):
            raise ValueError("typed chronological plan required")
        if self.train.role not in DEVELOPMENT_ROLES or self.inner_validation.role not in DEVELOPMENT_ROLES:
            raise PermissionError("inner training/recipe checks require development rights")
        if self.claim == "chronological":
            if (not self.train.end_ns <= self.inner_validation.start_ns
                    or self.train.ready_ns > self.inner_validation.start_ns
                    or self.inner_validation.ready_ns > self.discovery_cutoff_ns
                    or self.discovery_cutoff_ns > self.outer_validation.start_ns):
                raise ValueError("inner/outer chronology or maturity violation")

    @property
    def identity(self):
        return digest(asdict(self))

    def fit_policy(self):
        return AccessPolicy(self.plan_id+"/train-fit", (self.train.role,), (self.train.manifest_id,),
                            self.train.ready_ns, "diagnostic")

    def selection_policy(self):
        return AccessPolicy(self.plan_id+"/selection", (self.train.role, self.inner_validation.role),
            (self.train.manifest_id, self.inner_validation.manifest_id), self.discovery_cutoff_ns, "selection")


@dataclass(frozen=True)
class KnownArtifact:
    artifact_id: str
    witness: AccessWitness
    discovered_ns: int
    selected_ns: int
    lineage_ids: tuple[str, ...]

    def __post_init__(self):
        if (not self.artifact_id or not isinstance(self.witness, AccessWitness)
                or any(type(v) is not int for v in (self.discovered_ns, self.selected_ns))
                or not self.witness.ready_ns <= self.discovered_ns <= self.selected_ns
                or type(self.lineage_ids) is not tuple or not self.lineage_ids
                or any(not isinstance(v, str) or not v for v in self.lineage_ids)):
            raise ValueError("artifact outcome/discovery/selection chronology required")


def require_known(artifact, policy, *, permitted_lineage, log):
    row = dict(artifact=artifact.artifact_id, policy=policy.identity, layer="chronology")
    try:
        policy.require(artifact.witness)
        if (artifact.discovered_ns > policy.cutoff_ns or artifact.selected_ns > policy.cutoff_ns
                or not set(artifact.lineage_ids).issubset(permitted_lineage)):
            raise PermissionError("future discovery/recipe or unauthorized lineage")
    except PermissionError:
        log({**row, "decision": "DENIED"})
        raise
    log({**row, "decision": "AUTHORIZED"})


@dataclass(frozen=True)
class ScopeUse:
    market_id: str
    witness: AccessWitness
    use: str

    def __post_init__(self):
        if (not self.market_id or not isinstance(self.witness, AccessWitness)
                or self.use not in {"diagnostic", "selection", "independent_validation"}):
            raise ValueError("explicit market scope usage required")
        if self.use != "independent_validation" and self.witness.role in VALIDATION_ROLES:
            raise PermissionError("holdout cannot be used for development")


def independent_scope(request, prior_uses):
    """A new manifest name does not erase previously reviewed market dates."""
    if request.use != "independent_validation" or request.witness.role not in VALIDATION_ROLES:
        raise PermissionError("independent validation requires actual holdout rights")
    collisions = [u for u in prior_uses if u.market_id == request.market_id
        and u.use in {"diagnostic", "selection"}
        and max(u.witness.start_ns, request.witness.start_ns) < min(u.witness.end_ns, request.witness.end_ns)]
    if collisions:
        raise PermissionError("SELECTION_ADJUSTED_REVIEWED: overlapping development scope is not independent")
    return dict(status="INDEPENDENT_WITHIN_DECLARED_LINEAGE", manifest=request.witness.manifest_id,
                checked_prior_uses=len(prior_uses))

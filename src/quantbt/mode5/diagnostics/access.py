"""Manifest-bound roles and maturity; checked independently of cache identity."""

from dataclasses import asdict, dataclass

from .identity import digest

DEVELOPMENT_ROLES = frozenset({"development", "diagnostic_development", "DEVELOPMENT_REVIEWED",
    "EXPLORATORY_REVIEWED_2024", "synthetic", "post_selected_diagnostic_fixture"})
VALIDATION_ROLES = frozenset({"holdout", "holdout_live", "independent_validation", "independent_holdout"})


@dataclass(frozen=True)
class AccessWitness:
    manifest_id: str
    role: str
    start_ns: int
    end_ns: int
    ready_ns: int

    def __post_init__(self):
        if (not self.manifest_id or self.role not in DEVELOPMENT_ROLES | VALIDATION_ROLES or not self.start_ns < self.end_ns
                or self.ready_ns < self.end_ns):
            raise ValueError("invalid role, interval or readiness witness")
        if any(type(v) is not int for v in (self.start_ns, self.end_ns, self.ready_ns)):
            raise ValueError("exact integer timestamps required")

    @property
    def identity(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class AccessPolicy:
    policy_id: str
    roles: tuple[str, ...]
    manifests: tuple[str, ...]
    cutoff_ns: int
    purpose: str

    def __post_init__(self):
        if (not self.policy_id or type(self.roles) is not tuple or type(self.manifests) is not tuple
                or not self.roles or not self.manifests or type(self.cutoff_ns) is not int
                or any(role not in DEVELOPMENT_ROLES | VALIDATION_ROLES for role in self.roles)
                or any(not isinstance(ref, str) or not ref for ref in self.manifests)
                or self.purpose not in {"diagnostic", "selection", "independent_validation"}):
            raise ValueError("explicit frozen access scope required")
        if self.purpose != "independent_validation" and any(role in VALIDATION_ROLES for role in self.roles):
            raise ValueError("holdout cannot be authorized for development selection/diagnostics")

    @property
    def identity(self):
        return digest(asdict(self))

    def require(self, witness):
        if witness.role not in self.roles or witness.manifest_id not in self.manifests:
            raise PermissionError("role/manifest not authorized")
        if witness.end_ns > self.cutoff_ns or witness.ready_ns > self.cutoff_ns:
            raise PermissionError("future or immature evidence at current cutoff")

"""Three immutable identities; mathematical identity never grants access."""

from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


class Fingerprint:
    @property
    def identity(self):
        return digest({"schema": type(self).__name__+".v1", **asdict(self)})

    def __post_init__(self):
        for field in fields(self):
            if field.type is str and not isinstance(getattr(self, field.name), str):
                raise ValueError("immutable string identity required: "+field.name)
        for name, value in asdict(self).items():
            if isinstance(value, str) and not value.strip():
                raise ValueError("empty identity component: "+name)
        canonical(asdict(self))


@dataclass(frozen=True)
class ExecutionKey(Fingerprint):
    alpha_code: str
    effective_params: str
    market_snapshot: str
    initial_state: str
    clock: str
    instrument: str
    costs: str
    funding: str
    account: str
    terminal: str
    warmup: str
    scenario_seed: int
    source_backend: str

    def __post_init__(self):
        super().__post_init__()
        if type(self.scenario_seed) is not int:
            raise ValueError("scenario seed must be an exact integer")


@dataclass(frozen=True)
class AnalysisKey(Fingerprint):
    execution: str
    membership_view: str
    metric_statistics: str
    normalization_reference: str


@dataclass(frozen=True)
class SelectionKey(Fingerprint):
    analyses: tuple[str, ...]
    candidate_universe: str
    objective_selector_preferences: str
    diagnostic_calibration_plan: str
    access_scope: str

    def __post_init__(self):
        super().__post_init__()
        if (type(self.analyses) is not tuple or not self.analyses
                or any(not isinstance(x, str) or not x for x in self.analyses)):
            raise ValueError("ordered immutable analysis identities required")

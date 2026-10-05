"""Strict data-only contracts for deterministic sampler event reconstruction."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

from ..config import SamplerConfig
from ..wfo_study import WfoSamplerStudy

SCHEMA = "quantbt-exact-optuna-journal-v1"
BINDINGS = frozenset({
    "market", "calendar", "accounting", "objective", "schedule",
    "meta_snapshot", "meta_basis", "meta_task",
})
MAX_BYTES = 16_000_000
MAX_EVENTS = 100_000


class ContinuationError(ValueError):
    """No silent recovery or fresh-attempt fallback is permitted."""


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ContinuationError("checkpoint requires finite JSON-only data") from exc


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def clone(value):
    return json.loads(canonical(value))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContinuationError("duplicate checkpoint JSON field")
        result[key] = value
    return result


def decode(text, *, expected_digest):
    if not isinstance(text, str) or len(text.encode()) > MAX_BYTES:
        raise ContinuationError("checkpoint type/size limit exceeded")
    try:
        obj = json.loads(text, object_pairs_hook=_unique,
                         parse_constant=lambda value: (_ for _ in ()).throw(
                             ContinuationError("nonfinite checkpoint JSON")))
        if not isinstance(obj, dict) or set(obj) != {"schema", "payload", "digest"}:
            raise ContinuationError("checkpoint envelope fields invalid")
        if obj["schema"] != SCHEMA or not isinstance(expected_digest, str):
            raise ContinuationError("checkpoint schema/expected digest invalid")
        if digest(obj["payload"]) != obj["digest"] or obj["digest"] != expected_digest:
            raise ContinuationError("checkpoint external/content digest mismatch")
        return obj["payload"]
    except ContinuationError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise ContinuationError("corrupt checkpoint JSON") from exc


def binding_payload(binding):
    if not isinstance(binding, dict) or set(binding) != BINDINGS:
        raise ContinuationError("binding requires market/calendar/accounting/objective/schedule/meta identities")
    if any(not isinstance(v, str) or not v.strip() for v in binding.values()):
        raise ContinuationError("binding identities must be nonempty reviewed strings")
    return clone(binding)


def runtime_identity():
    versions = {name: importlib.metadata.version(name)
                for name in ("optuna", "numpy", "scipy", "cmaes")}
    if versions["optuna"] != "4.8.0" or versions["cmaes"] != "0.12.0":
        raise ContinuationError("unsupported exact-continuation dependency version")
    base = Path(__file__).resolve().parents[1]
    files = ["config.py", "wfo_study.py", "samplers.py", "parameter_space.py",
             "space.py", "constraints.py", "callbacks.py"]
    files += ["continuation/" + p.name for p in sorted((base / "continuation").glob("*.py"))]
    return dict(versions=versions, python=list(sys.version_info[:3]),
                implementation=platform.python_implementation(), system=platform.system(),
                machine=platform.machine(),
                source={name: hashlib.sha256((base / name).read_bytes()).hexdigest()
                        for name in files})


@dataclass(frozen=True)
class ContinuationConfig:
    sampler_config: SamplerConfig
    ranges: dict
    seed: int
    budget: int
    cutoff: str
    strategy_identity: str
    study_name: str = "quantbt-owned-continuation"
    stage: str = "is_search"
    direction: str = "maximize"
    result_constraints: bool = False
    warm_start: tuple = ()
    pruner: dict = field(default_factory=lambda: {"name": "nop", "kwargs": {}})
    early_stopping: dict | None = None
    duplicate_policy: str = "prune"

    def bridge(self):
        return WfoSamplerStudy(self.sampler_config, self.ranges, seed=self.seed,
                               budget=self.budget, cutoff=self.cutoff,
                               strategy_identity=self.strategy_identity, stage=self.stage)

    def payload(self):
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            raise ContinuationError("exact continuation requires an explicit uint32 seed")
        if type(self.budget) is not int or not 0 < self.budget <= MAX_EVENTS:
            raise ContinuationError("checkpoint budget invalid")
        if self.direction not in {"maximize", "minimize"} or self.duplicate_policy not in {"allow", "prune"}:
            raise ContinuationError("unsupported direction/duplicate policy")
        if type(self.result_constraints) is not bool:
            raise ContinuationError("result_constraints must be boolean")
        if any(not isinstance(v, str) or not v.strip()
               for v in (self.strategy_identity, self.stage, self.study_name)):
            raise ContinuationError("study/strategy/stage identity invalid")
        if not isinstance(self.sampler_config, SamplerConfig):
            raise ContinuationError("sampler_config must be the shared SamplerConfig")
        if any(k in self.sampler_config.kwargs for k in ("after_trial_strategy", "gamma", "weights")):
            raise ContinuationError("custom sampler callbacks/state are not serializable")
        pruner = clone(self.pruner)
        if not isinstance(pruner, dict) or set(pruner) != {"name", "kwargs"} or pruner["name"] not in {"nop", "median"}:
            raise ContinuationError("unsupported pruner serializer; use nop or median config")
        allowed = set() if pruner["name"] == "nop" else {
            "n_startup_trials", "n_warmup_steps", "interval_steps", "n_min_trials"}
        if not isinstance(pruner["kwargs"], dict) or set(pruner["kwargs"]) - allowed:
            raise ContinuationError("unsupported pruner settings")
        for key, value in pruner["kwargs"].items():
            if type(value) is not int or value < (1 if key in {"interval_steps", "n_min_trials"} else 0):
                raise ContinuationError("invalid median pruner settings")
        early = clone(self.early_stopping)
        if early is not None:
            if not isinstance(early, dict) or set(early) != {"patience", "min_delta", "min_trials"}:
                raise ContinuationError("unsupported callback serializer; use owned early stopping")
            from ..callbacks import SingleObjectiveEarlyStopping
            SingleObjectiveEarlyStopping(direction=self.direction, **early)
        bridge = self.bridge()
        if bridge.cutoff is None or str(bridge.cutoff) == "NaT":
            raise ContinuationError("cutoff must be a valid explicit timestamp")
        bridge.validate_warm_start(self.warm_start)
        return dict(sampler=dict(name=self.sampler_config.name, kwargs=clone(self.sampler_config.kwargs),
                                 constraint_mode=self.sampler_config.constraint_mode,
                                 mixed_space_policy=self.sampler_config.mixed_space_policy),
                    ranges=[[name, spec] for name, spec in bridge.ranges.items()],
                    space_identity=bridge.space.identity, seed=self.seed, budget=self.budget,
                    cutoff=bridge.cutoff.isoformat(), strategy_identity=self.strategy_identity,
                    study_name=self.study_name, stage=self.stage, direction=self.direction,
                    result_constraints=self.result_constraints, warm_start=clone(self.warm_start),
                    pruner=pruner, early_stopping=early, duplicate_policy=self.duplicate_policy)

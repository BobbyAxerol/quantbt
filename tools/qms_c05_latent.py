"""Review-only conditional numeric layout/ledger; NOT a public Optuna sampler."""

from dataclasses import dataclass
from hashlib import sha256
from importlib.metadata import version
import json
import math
from types import MappingProxyType

import numpy as np

from quantbt.optimization.parameter_space import NormalizedSearchSpace

VERSION = "qms-conditional-numeric-latent-v1-proposed"


class FrozenReviewSpace(NormalizedSearchSpace):
    def __init__(self, ranges):
        super().__init__(ranges)
        self.by_name = MappingProxyType(dict(self.by_name))
        self._sealed = True

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("review parameter schema is frozen")
        object.__setattr__(self, name, value)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def numeric_value(spec, u):
    low, high = float(spec.low), float(spec.high)
    if not spec.variable:
        raw = low
    elif spec.log and spec.kind == "integer":
        raw = math.exp(math.log(low - 0.5) + u * (math.log(high + 0.5) - math.log(low - 0.5)))
        raw = min(high, max(low, float(round(raw))))
    elif spec.log:
        raw = math.exp(math.log(low) + u * (math.log(high) - math.log(low)))
        raw = min(raw, np.nextafter(high, low))
    elif spec.step is not None or spec.kind == "integer":
        step = float(spec.step or 1)
        high = low + math.floor((high - low) / step + 1e-10) * step
        scaled = low - step / 2 + u * (high - low + step)
        raw = min(high, max(low, low + step * round((scaled - low) / step)))
    else:
        raw = min(low + u * (high - low), np.nextafter(high, low))
    return int(raw) if spec.kind == "integer" else float(raw)


class LatentLayout:
    """Decode supplied cube points/categories, without owning proposal RNG."""

    def __init__(self, ranges):
        self.space = FrozenReviewSpace(ranges)
        self.numeric = tuple(s for s in self.space.specs if s.variable and not s.choices)
        self.category_names = frozenset(s.name for s in self.space.specs if s.choices)
        self.names = tuple(s.name for s in self.numeric)
        if not self.names or len(self.names) > 21201:
            raise ValueError("review layout requires 1..21201 numeric dimensions")
        self.identity = digest(dict(version=VERSION, space=self.space.identity,
                                    names=self.names, bits=30, optimization=None))
        self._sealed = True

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("review latent layout is frozen")
        object.__setattr__(self, name, value)

    def project(self, point, categories):
        point = np.asarray(point, dtype=float)
        if point.shape != (len(self.names),) or not np.isfinite(point).all() or (point < 0).any() or (point >= 1).any():
            raise ValueError("invalid Sobol cube point/dimension")
        if set(categories) - self.category_names:
            raise ValueError("unknown independent category names")
        requested = {s.name: numeric_value(s, float(u)) for s, u in zip(self.numeric, point, strict=True)}
        active = {}
        for spec in self.space.specs:
            if not spec.active(active):
                continue
            if spec.fixed:
                value = spec.value
            elif spec.choices:
                if spec.variable and spec.name not in categories:
                    raise ValueError(f"missing independent category: {spec.name}")
                value = categories[spec.name] if spec.variable else spec.choices[0]
            else:
                value = requested.get(spec.name, numeric_value(spec, 0.0))
            spec.validate(value)
            active[spec.name] = value
            requested[spec.name] = value
        effective = self.space.effective(requested)
        return requested, effective


def sequence_declaration(layout, *, seed):
    """Proposed provenance only; does not construct or install a sampler."""
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("proposed deterministic contract requires a uint32 seed")
    return dict(schema=VERSION, layout_identity=layout.identity,
                dimensions=layout.names, seed=seed, bits=30, scramble=True,
                optimization=None, scipy_version=version("scipy"),
                optuna_version=version("optuna"),
                category_policy="independent_active_only_declared_inputs",
                first_independent_attempts=1, numeric_draw_policy="whole_point_before_mask",
                activation=False)


@dataclass(frozen=True, slots=True)
class Attempt:
    source: str
    state: str
    candidate_id: str
    qmc_index: int | None = None
    duplicate: bool = False


def consumption(events, *, budget):
    """Check a declared terminal ledger, not actual Optuna sampler telemetry."""
    if type(budget) is not int or budget <= 0 or len(events) > budget:
        raise ValueError("invalid attempted budget")
    qmc_count = 0
    independent = 0
    warming = True
    for event in events:
        if event.state not in {"COMPLETE", "PRUNED", "FAIL"} or not event.candidate_id:
            raise ValueError("terminal state and candidate ID required")
        if type(event.duplicate) is not bool or (event.duplicate and event.state != "PRUNED"):
            raise ValueError("duplicate must remain a pruned attempt")
        if event.source == "warm":
            if not warming or event.qmc_index is not None:
                raise ValueError("warm attempts must be a non-QMC prefix")
        elif event.source == "independent":
            if not warming or independent or event.qmc_index is not None:
                raise ValueError("only one first independent attempt")
            independent += 1
            warming = False
        elif event.source == "qmc":
            if not independent or type(event.qmc_index) is not int or event.qmc_index != qmc_count:
                raise ValueError("QMC indexes must be contiguous after startup")
            qmc_count += 1
        else:
            raise ValueError("unknown attempt source")
    return dict(schema=VERSION, attempted=len(events), budget=budget,
                unspent=budget - len(events), first_independent=independent,
                warm_attempts=sum(e.source == "warm" for e in events),
                qmc_points=qmc_count, next_qmc_index=qmc_count,
                unique_effective_candidates=len({e.candidate_id for e in events}),
                duplicate_attempts=sum(e.duplicate for e in events),
                runtime_telemetry=False, activation=False)

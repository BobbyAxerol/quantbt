"""Explicit frozen numeric Sobol policy; categories remain Optuna-owned."""

from hashlib import sha256
from decimal import Decimal, ROUND_FLOOR
from copy import deepcopy
from importlib.metadata import version
import math
import threading
from types import MappingProxyType

import numpy as np
import optuna
from scipy.stats import qmc

from .parameter_space import NormalizedSearchSpace
from .space import stable_params_key

POLICY = "conditional_numeric_latent_v1"
VERSION = "qms-conditional-numeric-latent-v1"


class FrozenLatentLayout:
    def __init__(self, ranges):
        space = NormalizedSearchSpace(ranges)
        self.specs = space.specs
        self.numeric = tuple(s for s in self.specs if s.variable and not s.choices)
        self.names = tuple(s.name for s in self.numeric)
        self.by_name = MappingProxyType(dict(space.by_name))
        if not 1 <= len(self.names) <= 21201:
            raise ValueError("SAMPLER_SPACE_UNSUPPORTED: latent Sobol requires 1..21201 numeric dimensions")
        self.identity = sha256(stable_params_key(dict(version=VERSION, space=space.identity,
            names=self.names, bits=30, optimization=None)).encode()).hexdigest()
        self._sealed = True

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("latent Sobol layout is frozen")
        object.__setattr__(self, name, value)

    def decode(self, point):
        point = np.asarray(point, dtype=np.float64)
        if (point.shape != (len(self.names),) or not np.isfinite(point).all()
                or (point < 0).any() or (point >= 1).any()):
            raise ValueError("invalid Sobol cube point")
        values = {}
        for spec, u in zip(self.numeric, point, strict=True):
            low, high = float(spec.low), float(spec.high)
            if spec.log:
                if spec.kind == "integer":
                    raw = math.exp(math.log(low-.5)+float(u)*(math.log(high+.5)-math.log(low-.5)))
                    value = int(min(high, max(low, round(raw))))
                else:
                    value = min(math.exp(math.log(low)+float(u)*(math.log(high)-math.log(low))),
                                float(np.nextafter(high, low)))
            elif spec.kind == "integer" or spec.step is not None:
                step = float(spec.step or 1)
                dl, dh, ds = (Decimal(str(v)) for v in (spec.low, spec.high, spec.step or 1))
                stop = float(dl + ((dh-dl)/ds).to_integral_value(rounding=ROUND_FLOOR)*ds)
                raw = low-step/2+float(u)*(stop-low+step)
                value = min(stop, max(low, low+step*round((raw-low)/step)))
                if spec.kind == "integer":
                    value = int(value)
            else:
                value = min(low+float(u)*(high-low), float(np.nextafter(high, low)))
            spec.validate(value)
            values[spec.name] = value
        return values


class ConditionalNumericSobol(optuna.samplers.BaseSampler):
    def __init__(self, ranges, *, seed):
        if type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("SAMPLER_SPACE_UNSUPPORTED: latent Sobol requires an explicit uint32 seed")
        if optuna.__version__ != "4.8.0":
            raise ValueError("SAMPLER_SPACE_UNSUPPORTED: latent Sobol requires Optuna 4.8.0")
        self.layout = FrozenLatentLayout(ranges)
        self.seed = seed
        self.category_seed = seed ^ 0x9E3779B9
        self._owner = threading.get_ident()
        self._cube = qmc.Sobol(len(self.layout.names), scramble=True, bits=30, seed=seed, optimization=None)
        self._startup = optuna.samplers.RandomSampler(seed=seed)
        self._category = optuna.samplers.RandomSampler(seed=self.category_seed)
        self._started = False
        self._index = 0
        self.records = {}

    def _check(self):
        if threading.get_ident() != self._owner:
            raise ValueError("latent Sobol requires one ordered proposal owner")

    def before_trial(self, study, trial):
        self._check()
        if trial.number in self.records:
            raise ValueError("duplicate latent Sobol ask")
        if trial.user_attrs.get("qms_source") == "warm_start":
            if self._started:
                raise ValueError("latent Sobol warm starts must form a prefix")
            row = dict(source="warm_start", qmc_index=None, decoded_numeric={}, cube_point=None)
        elif not self._started:
            self._started = True
            row = dict(source="independent", qmc_index=None, decoded_numeric={}, cube_point=None)
        else:
            # Ask order, not terminal/completion order, owns point consumption.
            point = self._cube.random(1)[0]
            row = dict(source="qmc", qmc_index=self._index,
                       decoded_numeric=self.layout.decode(point), cube_point=point.tolist())
            self._index += 1
        self.records[trial.number] = {**row, "category_draws": []}

    def infer_relative_search_space(self, study, trial):
        if self.records[trial.number]["source"] != "qmc":
            return {}
        from optuna.distributions import FloatDistribution, IntDistribution
        return {s.name: (IntDistribution(s.low, s.high, log=s.log, step=s.step or 1)
                if s.kind == "integer" else FloatDistribution(s.low, s.high, log=s.log, step=s.step))
                for s in self.layout.numeric}

    def sample_relative(self, study, trial, search_space):
        self._check()
        return dict(self.records[trial.number]["decoded_numeric"])

    def sample_independent(self, study, trial, param_name, param_distribution):
        self._check()
        spec = self.layout.by_name[param_name]
        row = self.records[trial.number]
        if spec.choices:
            value = self._category.sample_independent(study, trial, param_name, param_distribution)
            row["category_draws"].append(dict(name=param_name, value=value))
            return value
        if row["source"] == "qmc" and spec.variable:
            raise ValueError("SAMPLER_SPACE_UNSUPPORTED: no independent conditional numeric fallback")
        return self._startup.sample_independent(study, trial, param_name, param_distribution)

    def reseed_rng(self):
        raise ValueError("latent Sobol forbids uncontrolled reseeding/concurrent proposals")

    def state_witness(self):
        return dict(schema=VERSION, layout_identity=self.layout.identity,
            dimensions=list(self.layout.names), seed=self.seed, category_seed=self.category_seed,
            bits=30, scramble=True, scipy_version=version("scipy"), optimization=None,
            startup_used=self._started, next_qmc_index=self._index,
            draw_policy="whole_point_at_ask_before_mask", records=deepcopy(self.records))

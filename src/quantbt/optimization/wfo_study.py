"""Opt-in study policy around the shared factory; never owns financial state."""

from __future__ import annotations

from collections import Counter
import hashlib
import importlib.metadata
import math
import time

import optuna
import pandas as pd

from .config import SamplerConfig
from .constraints import constraints_from_trial, set_trial_constraints
from .parameter_space import NormalizedSearchSpace
from .samplers import WFO_RECIPES, build_sampler, resolved_sampler_kwargs
from .space import stable_params_key


class ObservedSampler(optuna.samplers.BaseSampler):
    """Delegate public sampler methods without extra RNG draws or suggestions."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.wall_seconds = 0.0
        self.independent = Counter()
        self.relative = {}
        self.relative_spaces = {}
        self.events = []

    def _call(self, method, *args):
        start = time.perf_counter()
        try:
            return getattr(self.delegate, method)(*args)
        finally:
            self.wall_seconds += time.perf_counter() - start

    def before_trial(self, study, trial):
        self.events.append(("ask", trial.number))
        return self._call("before_trial", study, trial)

    def after_trial(self, study, trial, state, values):
        self.events.append(("tell", trial.number, state.name, values))
        return self._call("after_trial", study, trial, state, values)

    def infer_relative_search_space(self, study, trial):
        return self._call("infer_relative_search_space", study, trial)

    def sample_relative(self, study, trial, search_space):
        self.relative_spaces[trial.number] = list(search_space)
        result = self._call("sample_relative", study, trial, search_space)
        self.relative[trial.number] = list(result)
        return result

    def sample_independent(self, study, trial, param_name, param_distribution):
        self.independent[param_name] += 1
        return self._call(
            "sample_independent", study, trial, param_name, param_distribution
        )

    def reseed_rng(self):
        return self._call("reseed_rng")


class WfoSamplerStudy:
    def __init__(
        self, config, ranges, *, seed, budget, cutoff, strategy_identity, stage
    ):
        self.config = (
            config
            if isinstance(config, SamplerConfig)
            else SamplerConfig(**dict(config))
        )
        if self.config.name not in WFO_RECIPES:
            raise ValueError(
                f"SAMPLER_SPACE_UNSUPPORTED: WFO supports {sorted(WFO_RECIPES)}, requested {self.config.name!r}"
            )
        if "seed" in self.config.kwargs and self.config.kwargs["seed"] != seed:
            raise ValueError(
                "sampler kwargs.seed must match the resolved fold/stage seed"
            )
        # Old objective observations/custom RNG instances are not portable config.
        if any(
            key in self.config.kwargs
            for key in ("source_trials", "independent_sampler", "constraints_func")
        ):
            raise ValueError(
                "WFO sampler kwargs cannot carry old observations, callbacks or mutable sampler objects"
            )
        self.space = NormalizedSearchSpace(ranges)
        self.seed, self.budget, self.cutoff = seed, budget, pd.Timestamp(cutoff)
        self.strategy_identity, self.stage = strategy_identity, stage
        try:
            stable_params_key(self.config.kwargs)
        except TypeError as exc:
            raise ValueError(
                "WFO sampler kwargs must be serializable constructor settings"
            ) from exc

    def sampler(self, *, result_constraints=False):
        formal = (
            constraints_from_trial
            if result_constraints and self.config.constraint_mode == "sampler"
            else None
        )
        delegate = build_sampler(
            self.config,
            seed=self.seed,
            search_space=self.ranges,
            objective_count=1,
            constraints_func=formal,
        )
        self.observed = ObservedSampler(delegate)
        return self.observed

    @property
    def ranges(self):
        # The factory inspects precisely the same normalized geometry.
        return {
            spec.name: (
                {"kind": "fixed", "value": spec.value}
                if spec.fixed
                else {
                    "kind": spec.kind,
                    **(
                        {"choices": list(spec.choices)}
                        if spec.choices
                        else {
                            "low": spec.low,
                            "high": spec.high,
                            "step": spec.step,
                            "log": spec.log,
                        }
                    ),
                    **({"active_if": dict(spec.active_if)} if spec.active_if else {}),
                }
            )
            for spec in self.space.specs
        }

    def validate_warm_start(self, records):
        if len(records) > self.budget:
            raise ValueError(
                "warm_start attempts exceed the declared study trial budget"
            )
        validated = []
        seen = set()
        for record in records:
            if set(record) != {
                "params",
                "available_at",
                "space_identity",
                "strategy_identity",
            }:
                raise ValueError(
                    "warm_start requires params, available_at, space_identity, strategy_identity only; old scores are forbidden"
                )
            available = pd.Timestamp(record["available_at"])
            if pd.isna(available) or available.tzinfo != self.cutoff.tzinfo:
                # Normalize aware zones, but never guess a naive clock.
                if pd.isna(available) or (available.tzinfo is None) != (
                    self.cutoff.tzinfo is None
                ):
                    raise ValueError(
                        "warm_start availability and cutoff must have compatible clocks"
                    )
            if available >= self.cutoff:
                raise ValueError(
                    "warm_start params must be available strictly before the IS cutoff"
                )
            if record["space_identity"] != self.space.identity:
                raise ValueError(
                    "warm_start space_identity does not match the current schema"
                )
            if record["strategy_identity"] != self.strategy_identity:
                raise ValueError(
                    "warm_start strategy_identity does not match the current alpha semantics"
                )
            effective = self.space.effective(record["params"])
            key = stable_params_key(effective)
            if key in seen:
                raise ValueError("warm_start contains duplicate effective params")
            seen.add(key)
            validated.append((dict(record["params"]), effective))
        return validated

    def enqueue(self, study, records):
        for requested, effective in self.validate_warm_start(records):
            study.enqueue_trial(
                {k: v for k, v in effective.items() if not self.space.by_name[k].fixed},
                user_attrs={"qms_source": "warm_start", "qms_requested": requested},
            )

    def suggest(self, trial):
        start = time.perf_counter()
        effective = self.space.suggest(trial)
        requested = dict(trial.user_attrs.get("qms_requested", effective))
        effective = self.space.effective(effective)
        trial.set_user_attr("qms_requested", requested)
        trial.set_user_attr("qms_effective", effective)
        trial.set_user_attr(
            "qms_candidate_id",
            self.space.candidate_key(
                effective, strategy_identity=self.strategy_identity
            ),
        )
        trial.set_user_attr("qms_source", trial.user_attrs.get("qms_source", "sampled"))
        trial.set_user_attr("qms_proposal_seconds", time.perf_counter() - start)
        return requested, effective

    @staticmethod
    def constraints(trial, values):
        values = tuple(float(v) for v in values)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("constraint values must be finite (<=0 means feasible)")
        set_trial_constraints(trial, values)
        return all(v <= 0 for v in values)

    def metadata(self, study):
        name, kwargs = resolved_sampler_kwargs(self.config, self.seed)
        trials = study.get_trials(deepcopy=False)
        states = Counter(t.state.name for t in trials)
        relative = self.observed.relative
        numeric = [
            s.name
            for s in self.space.specs
            if s.variable and not s.choices and not s.active_if
        ]
        rows = [
            {
                "trial_id": t.number,
                "state": t.state.name,
                "requested_params": t.user_attrs.get("qms_requested", {}),
                "effective_params": t.user_attrs.get("qms_effective", {}),
                "candidate_id": t.user_attrs.get("qms_candidate_id"),
                "source": t.user_attrs.get("qms_source", "sampled"),
                "objective": t.values,
                "constraints": constraints_from_trial(t),
                "reason": t.user_attrs.get("qms_rejection_reason"),
                "relative_dimensions": relative.get(t.number, []),
            }
            for t in trials
        ]
        return {
            "schema": "quantbt-wfo-sampler-study-v1",
            "recipe": self.config.name,
            "sampler_class": type(self.observed.delegate).__name__,
            "optuna_version": optuna.__version__,
            "cmaes_version": importlib.metadata.version("cmaes")
            if name == "cmaes"
            else None,
            "kwargs": kwargs,
            "seed": self.seed,
            "stage": self.stage,
            "objective_scope": "current_is_study_folds",
            "is_cutoff": self.cutoff,
            "space": self.space.metadata(),
            "space_identity": self.space.identity,
            "constraint_mode": self.config.constraint_mode,
            "mixed_space_policy": self.config.mixed_space_policy,
            "requested_trials": self.budget,
            "attempts": len(trials),
            "states": dict(states),
            "unique_effective_candidates": len(
                {r["candidate_id"] for r in rows if r["candidate_id"]}
            ),
            "feasible_complete": sum(
                t.state.name == "COMPLETE"
                and all(v <= 0 for v in constraints_from_trial(t))
                for t in trials
            ),
            "warm_start_attempts": sum(r["source"] == "warm_start" for r in rows),
            "duplicate_attempts": sum(
                r["reason"] == "DUPLICATE_EFFECTIVE_PARAMS" for r in rows
            ),
            "independent_sample_calls": dict(self.observed.independent),
            "relative_proposal_trials": sum(bool(names) for names in relative.values()),
            "joint_numeric_candidates": numeric
            if name in {"cmaes", "sobol"}
            else "see_relative_dimensions",
            "conditional_branches": {
                s.name: dict(s.active_if) for s in self.space.specs if s.active_if
            },
            "qmc_dimension_order": next(
                (
                    self.observed.relative_spaces[n]
                    for n, keys in relative.items()
                    if keys
                ),
                [],
            )
            if name == "sobol"
            else None,
            "qmc_sequence_position": sum(bool(names) for names in relative.values())
            if name == "sobol"
            else None,
            "startup_policy": kwargs.get(
                "n_startup_trials",
                10
                if name == "tpe"
                else 1
                if name == "cmaes"
                else "first_independent_trial",
            ),
            "completed_generations": "not_exposed",
            "group_decomposition": "not_exposed",
            "startup_adaptive_counts": "not_exposed",
            "sampler_wall_seconds": self.observed.wall_seconds,
            "ask_tell_digest": hashlib.sha256(
                stable_params_key({"events": self.observed.events}).encode()
            ).hexdigest(),
            "rows": rows,
            "resume": "owned_in_process_study_only",
        }


def prepare_wfo_studies(config, ranges, groups, *, strategy_identity, derive_seed):
    """Validate all study policies before preparing a scorer or calling an alpha."""
    bridges = {}
    for study_id, folds in groups:
        seed = (
            config.random_seed
            if config.optimization_schedule == "global"
            else derive_seed(config.random_seed, study_id)
        )
        try:
            bridge = WfoSamplerStudy(
                config.sampler_config or SamplerConfig(),
                ranges or {},
                seed=seed,
                budget=int(config.optuna_trials),
                cutoff=max(f.train_end for f in folds),
                strategy_identity=strategy_identity,
                stage="sbb_proxy_is_search"
                if config.optimization_mode == "mode_2_sbb"
                else "is_search",
            )
            if config.flat_selector == "centroid" and (
                config.parameter_constraints is not None
                or config.result_constraints is not None
                or any(s.active_if or s.choices for s in bridge.space.specs)
            ):
                raise ValueError(
                    "SAMPLER_SPACE_UNSUPPORTED: centroid with categorical/conditional/constrained opt-in space is not qualified; use medoid"
                )
            bridge.validate_warm_start(config.sampler_warm_start)
            bridge.sampler(
                result_constraints=(
                    config.result_constraints is not None
                    or config.parameter_constraints is not None
                )
            )
        except (ValueError, TypeError, ImportError) as exc:
            raise type(exc)(
                f"{exc}; mode={config.optimization_mode}, schedule={config.optimization_schedule}, "
                f"route={config.target_mode}, field=optimization_config.sampler_config"
            ) from exc
        bridges[int(study_id)] = bridge
    return bridges


def logging_completed(study, trial):
    if trial.state == optuna.trial.TrialState.COMPLETE and any(
        all(v <= 0 for v in constraints_from_trial(t))
        for t in study.get_trials(
            deepcopy=False, states=(optuna.trial.TrialState.COMPLETE,)
        )
    ):
        previous = study.user_attrs.get("previous_best_value")
        if previous != study.best_value:
            study.set_user_attr("previous_best_value", study.best_value)

"""Domain-agnostic Optuna optimizer core."""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from .callbacks import JsonlOptimizationLogger, SingleObjectiveEarlyStopping
from .config import OptimizationConfig, SamplerConfig
from .constraints import constraints_from_trial, set_trial_constraints
from .evaluator import TrialEvaluator
from .result import ObjectiveResult, OptimizationResult, OptimizationTrialRecord
from .samplers import build_sampler
from .space import stable_params_key, suggest_params


class OptunaOptimizer:
    """Generic Optuna orchestration over a domain-specific evaluator."""

    def __init__(
        self,
        *,
        evaluator: TrialEvaluator,
        config: OptimizationConfig,
        sampler_config: Optional[SamplerConfig] = None,
    ):
        self.evaluator = evaluator
        self.config = config
        self.sampler_config = sampler_config or SamplerConfig()
        self._seen_params: set[str] = set()

    def optimize(
        self,
        *,
        param_ranges: Mapping[str, Any],
        fixed_params: Optional[Mapping[str, Any]] = None,
        candidate_selector=None,
    ) -> OptimizationResult:
        """Run an Optuna study and return a QuantBT result schema."""

        try:
            import optuna
        except Exception as exc:  # pragma: no cover - dependency guard
            raise ImportError("QuantBT optimization requires optuna") from exc

        objective_count = len(self.config.directions)
        constraints_callback = constraints_from_trial if self.sampler_config.name in {"tpe", "nsgaii"} else None
        sampler = build_sampler(
            self.sampler_config,
            seed=int(self.config.seed),
            search_space=param_ranges,
            objective_count=objective_count,
            constraints_func=constraints_callback,
        )
        study = optuna.create_study(
            study_name=self.config.study_name,
            directions=list(self.config.directions),
            sampler=sampler,
            storage=self.config.storage,
            load_if_exists=bool(self.config.load_if_exists),
            pruner=optuna.pruners.NopPruner(),
        )
        callbacks = []
        if self.config.early_stopping_rounds is not None:
            if objective_count != 1:
                raise ValueError("early stopping is supported for single-objective optimization only")
            callbacks.append(
                SingleObjectiveEarlyStopping(
                    self.config.early_stopping_rounds,
                    self.config.directions[0],
                    min_delta=float(self.config.early_stopping_min_delta),
                )
            )
        if self.config.log_path is not None:
            callbacks.append(JsonlOptimizationLogger(self.config.log_path, objective_count=objective_count))

        catch = (Exception,) if self.config.exception_policy == "fail_trial" else ()
        study.optimize(
            lambda trial: self._objective(trial, param_ranges, fixed_params, objective_count),
            n_trials=int(self.config.n_trials),
            n_jobs=int(self.config.n_jobs),
            callbacks=callbacks,
            show_progress_bar=bool(self.config.show_progress_bar),
            catch=catch,
        )
        result = _build_result(study, objective_count)
        if candidate_selector is not None:
            selected = candidate_selector.select(result)
            result.selected_params = dict(getattr(selected, "params", selected))
            result.selection_metadata = dict(getattr(selected, "metadata", {}))
        elif objective_count == 1:
            result.selected_params = dict(result.best_params or {})
        return result

    def _objective(self, trial, param_ranges, fixed_params, objective_count: int):
        try:
            import optuna
        except Exception as exc:  # pragma: no cover
            raise ImportError("QuantBT optimization requires optuna") from exc
        params = suggest_params(trial, param_ranges, fixed_params=fixed_params)
        params_key = stable_params_key(params)
        if params_key in self._seen_params:
            if self.config.duplicate_policy == "prune":
                raise optuna.TrialPruned("duplicate parameter set")
            if self.config.duplicate_policy == "raise":
                raise ValueError(f"duplicate parameter set: {params_key}")
        self._seen_params.add(params_key)

        try:
            objective = self.evaluator.evaluate(params)
        except optuna.TrialPruned:
            raise
        except Exception as exc:
            if self.config.exception_policy == "prune":
                raise optuna.TrialPruned(str(exc)) from exc
            raise
        if not isinstance(objective, ObjectiveResult):
            raise TypeError("TrialEvaluator.evaluate must return ObjectiveResult")
        if len(objective.values) != objective_count:
            raise ValueError(f"objective returned {len(objective.values)} values but config has {objective_count} directions")
        if not all(math.isfinite(float(value)) for value in objective.values):
            raise optuna.TrialPruned("non-finite objective value")

        trial.set_user_attr("quantbt_metrics", dict(objective.metrics))
        trial.set_user_attr("quantbt_metadata", dict(objective.metadata))
        trial.set_user_attr("quantbt_params_key", params_key)
        set_trial_constraints(trial, objective.constraints)

        if objective_count == 1:
            return float(objective.values[0])
        return tuple(float(value) for value in objective.values)


def _build_result(study, objective_count: int) -> OptimizationResult:
    trials = [_trial_record(trial) for trial in study.trials]
    trials_frame = None
    try:
        trials_frame = study.trials_dataframe()
    except Exception:
        trials_frame = None
    if objective_count == 1:
        try:
            best_params = dict(study.best_params)
            best_values = (float(study.best_value),)
        except Exception:
            best_params = None
            best_values = None
        pareto_trials = []
    else:
        best_params = None
        best_values = None
        pareto_trials = list(study.best_trials)
    return OptimizationResult(
        study=study,
        best_params=best_params,
        best_values=best_values,
        pareto_trials=pareto_trials,
        trials=trials,
        trials_frame=trials_frame,
    )


def _trial_record(trial) -> OptimizationTrialRecord:
    values = tuple(float(value) for value in (trial.values or ()))
    return OptimizationTrialRecord(
        number=int(trial.number),
        state=str(trial.state.name),
        params=dict(trial.params),
        values=values,
        metrics=dict(trial.user_attrs.get("quantbt_metrics", {})),
        constraints=tuple(float(value) for value in trial.user_attrs.get("quantbt_constraints", ())),
        metadata=dict(trial.user_attrs.get("quantbt_metadata", {})),
    )

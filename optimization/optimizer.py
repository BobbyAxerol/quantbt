"""Domain-agnostic Optuna optimizer core."""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Optional, Sequence

from .callbacks import JsonlOptimizationLogger, SingleObjectiveEarlyStopping
from .candidate_selection import constraints_feasible
from .config import OptimizationConfig, SamplerConfig
from .constraints import constraints_from_trial, set_trial_constraints
from .evaluator import TrialEvaluator
from .result import ObjectiveResult, OptimizationResult, OptimizationTrialRecord
from .samplers import build_sampler
from .space import search_space_info, stable_params_key, suggest_params


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
        initial_trials: Optional[Sequence[Mapping[str, Any]]] = None,
        effective_params_builder: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
        candidate_selector=None,
    ) -> OptimizationResult:
        """Run an Optuna study and return a QuantBT result schema."""

        try:
            import optuna
        except Exception as exc:  # pragma: no cover - dependency guard
            raise ImportError("QuantBT optimization requires optuna") from exc
        if int(self.config.n_jobs) != 1:
            raise NotImplementedError("parallel optimization is not certified")

        objective_count = len(self.config.directions)
        self._seen_params = set()
        constraints_callback = (
            constraints_from_trial
            if self.sampler_config.name in {"tpe", "nsgaii"} and self.sampler_config.constraint_mode == "sampler"
            else None
        )
        sampler = build_sampler(
            self.sampler_config,
            seed=self.config.seed,
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
        self._preload_seen_params(study)
        self._enqueue_initial_trials(
            study,
            param_ranges=param_ranges,
            fixed_params=fixed_params,
            initial_trials=initial_trials,
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
                    min_trials=int(self.config.early_stopping_min_trials),
                )
            )
        if self.config.log_path is not None:
            callbacks.append(JsonlOptimizationLogger(self.config.log_path, objective_count=objective_count))

        catch = (Exception,) if self.config.exception_policy == "fail_trial" else ()
        study.optimize(
            lambda trial: self._objective(
                trial,
                param_ranges,
                fixed_params,
                objective_count,
                effective_params_builder=effective_params_builder,
            ),
            n_trials=int(self.config.n_trials),
            n_jobs=int(self.config.n_jobs),
            callbacks=callbacks,
            show_progress_bar=bool(self.config.show_progress_bar),
            catch=catch,
        )
        result = _build_result(study, objective_count)
        result.baseline_trials = [
            record
            for record in result.trials
            if record.metadata.get("quantbt_source") == "warm_start"
        ]
        result.search_diagnostics = _search_diagnostics(
            param_ranges=param_ranges,
            fixed_params=fixed_params,
            result=result,
            objective_index=0,
        )
        if candidate_selector is not None:
            selected = candidate_selector.select(result)
            result.selected_params = dict(getattr(selected, "params", selected))
            result.selection_metadata = dict(getattr(selected, "metadata", {}))
        elif objective_count == 1:
            if _result_has_constraints(result):
                result.selected_params = None
                result.selection_metadata = {"selected_by": None, "reason": "constraints_require_explicit_candidate_selector"}
            else:
                result.selected_params = dict(result.best_params or {})
        _apply_baseline_floor(result)
        return result

    def _enqueue_initial_trials(self, study, *, param_ranges, fixed_params, initial_trials) -> None:
        if not initial_trials:
            return
        fixed = dict(fixed_params or {})
        for idx, payload in enumerate(initial_trials):
            full_params = dict(payload or {})
            full_params.update(fixed)
            trial_params = _trial_params_for_enqueue(full_params, param_ranges, fixed)
            study.enqueue_trial(
                trial_params,
                user_attrs={
                    "quantbt_source": "warm_start",
                    "quantbt_initial_trial_id": int(idx),
                    "quantbt_initial_full_params": dict(full_params),
                },
                skip_if_exists=True,
            )

    def _preload_seen_params(self, study) -> None:
        if not self.config.load_if_exists:
            return
        for trial in getattr(study, "trials", ()):
            key = trial.user_attrs.get("quantbt_params_key")
            if key is None:
                params = trial.user_attrs.get("quantbt_full_params", trial.params)
                if params:
                    key = stable_params_key(params)
            if key:
                self._seen_params.add(str(key))

    def _objective(self, trial, param_ranges, fixed_params, objective_count: int, *, effective_params_builder=None):
        try:
            import optuna
        except Exception as exc:  # pragma: no cover
            raise ImportError("QuantBT optimization requires optuna") from exc
        params = suggest_params(trial, param_ranges, fixed_params=fixed_params)
        source = str(trial.user_attrs.get("quantbt_source", "sampled"))
        raw_params_key = stable_params_key(params)
        effective_params = dict(effective_params_builder(params)) if effective_params_builder is not None else dict(params)
        params_key = stable_params_key(effective_params)
        trial.set_user_attr("quantbt_full_params", dict(params))
        trial.set_user_attr("quantbt_source", source)
        trial.set_user_attr("quantbt_params_key", params_key)
        trial.set_user_attr("quantbt_raw_params_key", raw_params_key)
        trial.set_user_attr("quantbt_effective_params", dict(effective_params))
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
        if objective.constraints and self.sampler_config.name not in {"tpe", "nsgaii"} and self.sampler_config.constraint_mode != "post_filter":
            raise ValueError(
                f"sampler {self.sampler_config.name!r} does not support formal constraints; "
                "set SamplerConfig(..., constraint_mode='post_filter') to filter candidates after optimization"
            )
        if len(objective.values) != objective_count:
            raise ValueError(f"objective returned {len(objective.values)} values but config has {objective_count} directions")
        if not all(math.isfinite(float(value)) for value in objective.values):
            raise optuna.TrialPruned("non-finite objective value")

        trial.set_user_attr("quantbt_metrics", dict(objective.metrics))
        metadata = dict(objective.metadata)
        metadata.setdefault("quantbt_source", source)
        metadata.setdefault("quantbt_params_key", params_key)
        metadata.setdefault("quantbt_raw_params_key", raw_params_key)
        trial.set_user_attr("quantbt_metadata", metadata)
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
            best_params = dict(study.best_trial.user_attrs.get("quantbt_full_params", study.best_params))
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


def _result_has_constraints(result: OptimizationResult) -> bool:
    return any(len(record.constraints) > 0 for record in result.trials if record.state == "COMPLETE")


def _trial_record(trial) -> OptimizationTrialRecord:
    values = tuple(float(value) for value in (trial.values or ()))
    metadata = dict(trial.user_attrs.get("quantbt_metadata", {}))
    for key in (
        "quantbt_source",
        "quantbt_params_key",
        "quantbt_raw_params_key",
        "quantbt_initial_trial_id",
    ):
        if key in trial.user_attrs:
            metadata.setdefault(key, trial.user_attrs[key])
    return OptimizationTrialRecord(
        number=int(trial.number),
        state=str(trial.state.name),
        params=dict(trial.user_attrs.get("quantbt_full_params", trial.params)),
        values=values,
        metrics=dict(trial.user_attrs.get("quantbt_metrics", {})),
        constraints=tuple(float(value) for value in trial.user_attrs.get("quantbt_constraints", ())),
        metadata=metadata,
    )


def _trial_params_for_enqueue(params: Mapping[str, Any], param_ranges: Mapping[str, Any], fixed_params: Mapping[str, Any]) -> dict[str, Any]:
    """Return only Optuna-suggested params for `study.enqueue_trial`.

    Scalar constants and fixed params are merged inside `suggest_params`, so
    enqueuing them would create confusing Optuna distributions. Missing active
    search params are rejected because a warm-start baseline must be evaluated
    exactly, not partially sampled.
    """

    queued: dict[str, Any] = {}
    missing: list[str] = []
    fixed = set(dict(fixed_params or {}))
    for name, spec in dict(param_ranges or {}).items():
        if name in fixed or not _is_suggested_spec(spec):
            continue
        if name not in params:
            missing.append(str(name))
        else:
            queued[str(name)] = params[name]
    if missing:
        joined = ", ".join(missing[:10])
        raise ValueError(f"initial trial is missing search params: {joined}")
    return queued


def _is_suggested_spec(spec: Any) -> bool:
    if isinstance(spec, range):
        return True
    if isinstance(spec, tuple) and len(spec) in (2, 3):
        return True
    if isinstance(spec, list):
        return True
    return False


def _apply_baseline_floor(result: OptimizationResult) -> None:
    """Keep the best feasible warm-start when selected candidate regresses."""

    try:
        directions = tuple(str(direction.name).lower() for direction in result.study.directions)
    except Exception:
        directions = ("maximize",)
    if len(directions) != 1:
        return
    baselines = [
        record
        for record in result.baseline_trials
        if record.state == "COMPLETE" and record.values and constraints_feasible(record.constraints)
    ]
    if not baselines:
        result.search_regression = False
        result.selection_metadata.setdefault("best_baseline_trial", None)
        return
    best_baseline = sorted(
        baselines,
        key=lambda record: record.values[0],
        reverse=directions[0] == "maximize",
    )[0]
    selected = _selected_record(result)
    if selected is None:
        selected = best_baseline
    selected_value = selected.values[0] if selected.values else float("-inf")
    baseline_better = _is_better(best_baseline.values[0], selected_value, directions[0])
    result.selection_metadata.setdefault(
        "best_baseline_trial",
        {
            "trial_number": int(best_baseline.number),
            "value": float(best_baseline.values[0]),
            "params": dict(best_baseline.params),
        },
    )
    if not baseline_better:
        result.search_regression = False
        result.selection_metadata.setdefault("search_regression", False)
        return
    result.selected_params = dict(best_baseline.params)
    result.search_regression = True
    result.selection_metadata.update(
        {
            "selected_by": "warm_start_baseline_floor",
            "search_regression": True,
            "previous_selected_trial": None if selected is None else int(selected.number),
            "previous_selected_value": None if selected is None or not selected.values else float(selected.values[0]),
            "trial_number": int(best_baseline.number),
            "value": float(best_baseline.values[0]),
        }
    )


def _selected_record(result: OptimizationResult) -> Optional[OptimizationTrialRecord]:
    trial_number = result.selection_metadata.get("trial_number")
    if trial_number is not None:
        for record in result.trials:
            if int(record.number) == int(trial_number):
                return record
    if result.selected_params is not None:
        selected_key = stable_params_key(result.selected_params)
        for record in result.trials:
            if stable_params_key(record.params) == selected_key and record.state == "COMPLETE":
                return record
    if result.best_params is not None:
        best_key = stable_params_key(result.best_params)
        for record in result.trials:
            if stable_params_key(record.params) == best_key and record.state == "COMPLETE":
                return record
    return None


def _is_better(candidate: float, incumbent: float, direction: str) -> bool:
    if direction == "minimize":
        return float(candidate) < float(incumbent)
    return float(candidate) > float(incumbent)


def _search_diagnostics(
    *,
    param_ranges: Mapping[str, Any],
    fixed_params: Optional[Mapping[str, Any]],
    result: OptimizationResult,
    objective_index: int,
) -> dict[str, Any]:
    info = search_space_info(param_ranges, fixed_params=fixed_params)
    variable_names = list(info.variable_names)
    completed = [
        record
        for record in result.trials
        if record.state == "COMPLETE" and len(record.values) > int(objective_index)
    ]
    try:
        direction = str(result.study.directions[int(objective_index)].name).lower()
    except Exception:
        direction = "maximize"
    ranked = sorted(
        completed,
        key=lambda record: record.values[int(objective_index)],
        reverse=direction == "maximize",
    )
    top_n = max(1, int(math.ceil(len(ranked) * 0.10))) if ranked else 0
    top = ranked[:top_n]
    source_counts: dict[str, int] = {}
    effective_keys: list[str] = []
    for record in result.trials:
        source = str(record.metadata.get("quantbt_source", "sampled"))
        source_counts[source] = source_counts.get(source, 0) + 1
        key = record.metadata.get("quantbt_params_key")
        if key is not None:
            effective_keys.append(str(key))
    coverage = {
        name: len({record.params.get(name) for record in completed if name in record.params})
        for name in variable_names
    }
    return {
        "nominal_dimension": int(len(variable_names)),
        "variable_names": variable_names,
        "grid_size_estimate": info.grid_size,
        "has_categorical": bool(info.has_categorical),
        "has_continuous": bool(info.has_continuous),
        "has_dynamic_float": bool(info.has_dynamic_float),
        "param_kind_counts": _param_kind_counts(param_ranges, fixed_params),
        "completed_trials": int(len(completed)),
        "pruned_trials": int(sum(1 for record in result.trials if record.state == "PRUNED")),
        "failed_trials": int(sum(1 for record in result.trials if record.state == "FAIL")),
        "source_counts": source_counts,
        "effective_duplicate_count": int(len(effective_keys) - len(set(effective_keys))),
        "param_coverage": coverage,
        "top_decile_size": int(top_n),
        "top_decile_distributions": _top_distributions(top, variable_names),
        "baseline_rank": _baseline_rank(ranked),
    }


def _param_kind_counts(param_ranges: Mapping[str, Any], fixed_params: Optional[Mapping[str, Any]]) -> dict[str, int]:
    fixed = set(dict(fixed_params or {}))
    counts = {"fixed": 0, "categorical": 0, "int": 0, "float": 0, "constant": 0}
    for name, spec in dict(param_ranges or {}).items():
        if name in fixed:
            counts["fixed"] += 1
            continue
        if isinstance(spec, range) or isinstance(spec, list):
            counts["categorical"] += 1
        elif isinstance(spec, tuple) and len(spec) in (2, 3):
            numeric = all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in spec)
            looks_int = numeric and all(isinstance(value, int) and not isinstance(value, bool) for value in spec)
            counts["int" if looks_int else "float"] += 1
        else:
            counts["constant"] += 1
    return counts


def _top_distributions(records: Sequence[OptimizationTrialRecord], variable_names: Sequence[str]) -> dict[str, dict[str, Any]]:
    distributions: dict[str, dict[str, Any]] = {}
    for name in variable_names:
        values = [record.params.get(name) for record in records if name in record.params]
        counts: dict[str, int] = {}
        numeric: list[float] = []
        for value in values:
            counts[str(value)] = counts.get(str(value), 0) + 1
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                numeric.append(float(value))
        payload: dict[str, Any] = {"counts": counts}
        if numeric:
            payload.update(
                {
                    "min": float(min(numeric)),
                    "max": float(max(numeric)),
                    "mean": float(sum(numeric) / len(numeric)),
                }
            )
        distributions[str(name)] = payload
    return distributions


def _baseline_rank(ranked: Sequence[OptimizationTrialRecord]) -> list[dict[str, Any]]:
    rows = []
    for rank, record in enumerate(ranked, start=1):
        if record.metadata.get("quantbt_source") != "warm_start":
            continue
        rows.append(
            {
                "rank": int(rank),
                "trial_number": int(record.number),
                "value": None if not record.values else float(record.values[0]),
                "params": dict(record.params),
            }
        )
    return rows

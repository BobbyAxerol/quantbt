"""Candidate selection helpers for optimization results."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable, Optional

from .result import OptimizationResult, OptimizationTrialRecord


def constraints_feasible(constraints: tuple[float, ...]) -> bool:
    """Return True when all Optuna formal constraints are feasible."""

    return all(float(value) <= 0.0 for value in constraints)


@dataclass(frozen=True)
class SelectedCandidate:
    """Selected production candidate after feasibility/robustness filtering."""

    params: dict[str, Any]
    values: tuple[float, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)
    constraints: tuple[float, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RobustSelectionConfig:
    """Configuration for plateau-based production candidate selection.

    The selector is deliberately post-optimization: the sampler still learns
    from the raw objective surface, while the final production params are
    selected from a stable feasible neighborhood instead of a single spike.
    """

    top_quantile: float = 0.10
    min_trades: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    neighborhood_radius: float = 0.10
    min_neighbor_count: int = 3
    seed_consensus: int = 1
    instability_penalty: float = 0.25
    worst_weight: float = 0.25
    drawdown_penalty: float = 0.0
    size_bonus: float = 0.01
    ignore_params: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (0.0 < float(self.top_quantile) <= 1.0):
            raise ValueError("top_quantile must be in (0, 1]")
        if float(self.neighborhood_radius) < 0.0:
            raise ValueError("neighborhood_radius must be non-negative")
        if int(self.min_neighbor_count) <= 0:
            raise ValueError("min_neighbor_count must be positive")
        if int(self.seed_consensus) <= 0:
            raise ValueError("seed_consensus must be positive")
        object.__setattr__(self, "ignore_params", tuple(str(name) for name in self.ignore_params))


@dataclass(frozen=True)
class CandidateSelector:
    """Small public selector interface.

    This is intentionally conservative. Robust WFO plateau selectors can plug
    into this interface later; Phase 32B provides best/feasible/Pareto policies
    so Optuna's best trial is not silently treated as production params.
    """

    mode: str = "feasible_best"
    objective_index: int = 0
    config: Optional[RobustSelectionConfig] = None

    def select(self, result: OptimizationResult) -> SelectedCandidate:
        mode = str(self.mode).lower().strip()
        if mode in {"best", "single_best"}:
            return self._single_best(result, require_feasible=False)
        if mode in {"feasible_best", "best_feasible"}:
            return self._single_best(result, require_feasible=True)
        if mode in {"pareto_first", "first_pareto"}:
            return self._pareto_first(result)
        if mode in {"robust_plateau", "plateau_robust"}:
            return self._robust_plateau(result)
        raise ValueError(f"unsupported candidate selector mode={self.mode!r}")

    def _single_best(self, result: OptimizationResult, *, require_feasible: bool) -> SelectedCandidate:
        direction = _direction(result, int(self.objective_index))
        completed = [record for record in result.trials if record.state == "COMPLETE" and len(record.values) > int(self.objective_index)]
        if require_feasible:
            completed = [record for record in completed if constraints_feasible(record.constraints)]
        if not completed:
            raise ValueError("no completed feasible optimization trials")
        reverse = direction == "maximize"
        best = sorted(completed, key=lambda record: record.values[int(self.objective_index)], reverse=reverse)[0]
        return _selected_from_record(
            best,
            metadata={
                "selector": self.mode,
                "objective_index": int(self.objective_index),
                "feasibility_filter": bool(require_feasible),
            },
        )

    def _pareto_first(self, result: OptimizationResult) -> SelectedCandidate:
        pareto = [trial for trial in result.pareto_trials if constraints_feasible(tuple(float(value) for value in trial.user_attrs.get("quantbt_constraints", ())))] 
        if not pareto:
            raise ValueError("optimization result has no Pareto trials")
        trial = pareto[0]
        params = dict(trial.user_attrs.get("quantbt_full_params", trial.params))
        return SelectedCandidate(
            params=params,
            values=tuple(float(value) for value in (trial.values or ())),
            metrics=dict(trial.user_attrs.get("quantbt_metrics", {})),
            constraints=tuple(float(value) for value in trial.user_attrs.get("quantbt_constraints", ())),
            metadata={
                "selector": self.mode,
                "trial_number": int(trial.number),
                "pareto_count": int(len(result.pareto_trials)),
                "feasible_pareto_count": int(len(pareto)),
            },
        )

    def _robust_plateau(self, result: OptimizationResult) -> SelectedCandidate:
        config = self.config or RobustSelectionConfig()
        objective_index = int(self.objective_index)
        direction = _direction(result, objective_index)
        feasible = [
            record
            for record in result.trials
            if _record_feasible_for_robust(record, objective_index=objective_index, config=config)
        ]
        if not feasible:
            raise ValueError("no completed feasible optimization trials for robust plateau selection")

        ranked = sorted(
            feasible,
            key=lambda record: _signed_objective(record, objective_index, direction),
            reverse=True,
        )
        top_n = max(
            1,
            int(math.ceil(len(ranked) * float(config.top_quantile))),
            min(int(config.min_neighbor_count), len(ranked)),
        )
        top_n = min(top_n, len(ranked))
        top = ranked[:top_n]
        param_names = _param_names(feasible, ignore=config.ignore_params)
        fallback_reasons: list[str] = []
        scored: list[dict[str, Any]] = []
        for record in top:
            neighbors = [
                neighbor
                for neighbor in top
                if _param_distance(record.params, neighbor.params, feasible, param_names) <= float(config.neighborhood_radius)
            ]
            if not neighbors:
                neighbors = [record]
            seed_count = _seed_consensus_count(neighbors)
            meets_count = len(neighbors) >= int(config.min_neighbor_count)
            meets_seed = seed_count >= int(config.seed_consensus)
            if meets_count and meets_seed:
                scored.append(_score_neighborhood(record, neighbors, objective_index, direction, config, feasible, param_names))

        if not scored:
            fallback_reasons.append("no_candidate_met_neighbor_or_seed_consensus")
            for record in top:
                neighbors = [
                    neighbor
                    for neighbor in top
                    if _param_distance(record.params, neighbor.params, feasible, param_names) <= float(config.neighborhood_radius)
                ] or [record]
                scored.append(_score_neighborhood(record, neighbors, objective_index, direction, config, feasible, param_names))

        best_cluster = sorted(scored, key=lambda row: row["plateau_score"], reverse=True)[0]
        selected_record = _medoid_record(best_cluster["neighbors"], feasible, param_names, objective_index, direction)
        result.robust_candidates = [
            {
                "trial_number": int(row["center"].number),
                "plateau_score": float(row["plateau_score"]),
                "neighbor_count": int(len(row["neighbors"])),
                "seed_consensus_count": int(row["seed_consensus_count"]),
                "median_objective": float(row["median_objective"]),
                "worst_objective": float(row["worst_objective"]),
                "objective_std": float(row["objective_std"]),
                "params": dict(row["center"].params),
            }
            for row in sorted(scored, key=lambda item: item["plateau_score"], reverse=True)
        ]
        metadata = {
            "selector": self.mode,
            "selected_by": "robust_plateau",
            "objective_index": objective_index,
            "top_quantile": float(config.top_quantile),
            "top_trials": int(top_n),
            "feasible_trials": int(len(feasible)),
            "neighborhood_radius": float(config.neighborhood_radius),
            "min_neighbor_count": int(config.min_neighbor_count),
            "seed_consensus": int(config.seed_consensus),
            "seed_consensus_count": int(best_cluster["seed_consensus_count"]),
            "neighbor_count": int(len(best_cluster["neighbors"])),
            "plateau_score": float(best_cluster["plateau_score"]),
            "median_objective": float(best_cluster["median_objective"]),
            "worst_objective": float(best_cluster["worst_objective"]),
            "objective_std": float(best_cluster["objective_std"]),
            "cluster_center_trial": int(best_cluster["center"].number),
            "medoid_trial_number": int(selected_record.number),
            "fallback_reasons": fallback_reasons,
            "param_names": param_names,
        }
        return _selected_from_record(selected_record, metadata=metadata)


def _selected_from_record(record: OptimizationTrialRecord, *, metadata: Optional[dict[str, Any]] = None) -> SelectedCandidate:
    merged_metadata = dict(record.metadata)
    merged_metadata.update(metadata or {})
    merged_metadata["trial_number"] = int(record.number)
    return SelectedCandidate(
        params=dict(record.params),
        values=tuple(record.values),
        metrics=dict(record.metrics),
        constraints=tuple(record.constraints),
        metadata=merged_metadata,
    )


def _direction(result: OptimizationResult, objective_index: int) -> str:
    try:
        directions = tuple(str(direction.name).lower() for direction in result.study.directions)
    except Exception:
        directions = ("maximize",)
    if objective_index < 0 or objective_index >= len(directions):
        raise ValueError("objective_index out of range for optimization directions")
    return directions[objective_index]


def _record_feasible_for_robust(
    record: OptimizationTrialRecord,
    *,
    objective_index: int,
    config: RobustSelectionConfig,
) -> bool:
    if record.state != "COMPLETE" or len(record.values) <= int(objective_index):
        return False
    if not constraints_feasible(record.constraints):
        return False
    if config.min_trades is not None:
        trades = _metric(record, ("num_trades", "trades", "trade_count"))
        if trades is None or float(trades) < float(config.min_trades):
            return False
    if config.max_drawdown_pct is not None:
        mdd = _metric(record, ("max_drawdown_pct", "mdd_pct", "max_dd_pct"))
        if mdd is None or float(mdd) > float(config.max_drawdown_pct):
            return False
    return True


def _metric(record: OptimizationTrialRecord, names: Iterable[str]) -> Optional[float]:
    for name in names:
        if name in record.metrics:
            return float(record.metrics[name])
    return None


def _signed_objective(record: OptimizationTrialRecord, objective_index: int, direction: str) -> float:
    value = float(record.values[int(objective_index)])
    if direction == "minimize":
        return -value
    return value


def _param_names(records: Iterable[OptimizationTrialRecord], *, ignore: tuple[str, ...]) -> list[str]:
    ignored = set(ignore)
    names: set[str] = set()
    for record in records:
        names.update(str(name) for name in record.params if str(name) not in ignored)
    return sorted(names)


def _param_distance(
    left: dict[str, Any],
    right: dict[str, Any],
    records: Iterable[OptimizationTrialRecord],
    param_names: list[str],
) -> float:
    if not param_names:
        return 0.0
    total = 0.0
    for name in param_names:
        lv = left.get(name)
        rv = right.get(name)
        if _is_numeric(lv) and _is_numeric(rv):
            span = _numeric_span(records, name)
            diff = 0.0 if span <= 0.0 else abs(float(lv) - float(rv)) / span
        else:
            diff = 0.0 if lv == rv else 1.0
        total += diff * diff
    return math.sqrt(total / len(param_names))


def _numeric_span(records: Iterable[OptimizationTrialRecord], name: str) -> float:
    values = [float(record.params[name]) for record in records if name in record.params and _is_numeric(record.params[name])]
    if not values:
        return 0.0
    return float(max(values) - min(values))


def _is_numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _seed_labels(records: Iterable[OptimizationTrialRecord]) -> set[str]:
    labels = set()
    for record in records:
        for key in ("quantbt_seed", "seed"):
            if key in record.metadata:
                labels.add(str(record.metadata[key]))
                break
    return labels


def _seed_consensus_count(records: Iterable[OptimizationTrialRecord]) -> int:
    records = list(records)
    labels = _seed_labels(records)
    if labels:
        return len(labels)
    return 1 if records else 0


def _score_neighborhood(
    center: OptimizationTrialRecord,
    neighbors: list[OptimizationTrialRecord],
    objective_index: int,
    direction: str,
    config: RobustSelectionConfig,
    all_records: list[OptimizationTrialRecord],
    param_names: list[str],
) -> dict[str, Any]:
    signed = [_signed_objective(record, objective_index, direction) for record in neighbors]
    med = float(median(signed))
    worst = float(min(signed))
    std = _std(signed)
    mdds = [_metric(record, ("max_drawdown_pct", "mdd_pct", "max_dd_pct")) for record in neighbors]
    mdd_penalty = float(median([float(value) for value in mdds if value is not None])) if any(value is not None for value in mdds) else 0.0
    score = (
        med
        + float(config.worst_weight) * worst
        - float(config.instability_penalty) * std
        - float(config.drawdown_penalty) * mdd_penalty
        + float(config.size_bonus) * math.log1p(len(neighbors))
    )
    return {
        "center": center,
        "neighbors": neighbors,
        "plateau_score": float(score),
        "median_objective": med,
        "worst_objective": worst,
        "objective_std": std,
        "seed_consensus_count": _seed_consensus_count(neighbors),
        "mean_distance": _mean_distance(center, neighbors, all_records, param_names),
    }


def _std(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _mean_distance(
    center: OptimizationTrialRecord,
    neighbors: list[OptimizationTrialRecord],
    records: list[OptimizationTrialRecord],
    param_names: list[str],
) -> float:
    if not neighbors:
        return 0.0
    return sum(_param_distance(center.params, record.params, records, param_names) for record in neighbors) / len(neighbors)


def _medoid_record(
    neighbors: list[OptimizationTrialRecord],
    all_records: list[OptimizationTrialRecord],
    param_names: list[str],
    objective_index: int,
    direction: str,
) -> OptimizationTrialRecord:
    return sorted(
        neighbors,
        key=lambda record: (
            _mean_distance(record, neighbors, all_records, param_names),
            -_signed_objective(record, objective_index, direction),
            int(record.number),
        ),
    )[0]

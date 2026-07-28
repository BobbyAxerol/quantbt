"""Callbacks shared by QuantBT optimization workflows."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Optional


class SingleObjectiveEarlyStopping:
    """Stop a single-objective Optuna study after best-value stagnation."""

    def __init__(self, patience: int, direction: str, min_delta: float = 1e-4, min_trials: int = 0):
        if patience <= 0:
            raise ValueError("patience must be positive")
        direction = str(direction).lower().strip()
        if direction not in {"maximize", "minimize"}:
            raise ValueError("direction must be maximize or minimize")
        if min_delta < 0.0:
            raise ValueError("min_delta must be >= 0")
        if min_trials < 0:
            raise ValueError("min_trials must be >= 0")
        self.patience = int(patience)
        self.direction = direction
        self.min_delta = float(min_delta)
        self.min_trials = int(min_trials)
        self._best: Optional[float] = None
        self._stale = 0
        self._completed = 0

    def __call__(self, study, trial) -> None:
        try:
            import optuna
        except Exception:  # pragma: no cover - optuna import guard
            optuna = None
        if optuna is not None and trial.state is not optuna.trial.TrialState.COMPLETE:
            return
        try:
            current = float(study.best_value)
        except Exception:
            return
        self._completed += 1
        if self._is_improved(current):
            self._best = current
            self._stale = 0
        else:
            self._stale += 1
        if self._completed >= self.min_trials and self._stale >= self.patience:
            study.stop()

    def _is_improved(self, current: float) -> bool:
        if self._best is None:
            return True
        if self.direction == "maximize":
            return current > self._best + self.min_delta
        return current < self._best - self.min_delta


class JsonlOptimizationLogger:
    """Append parseable JSONL trial records.

    Single-objective studies log when the best trial changes. Multi-objective
    studies log every completed trial because there is no scalar best value.
    """

    def __init__(self, path, *, objective_count: int):
        self.path = Path(path)
        self.objective_count = int(objective_count)
        self._previous_best_number: Optional[int] = None
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, study, frozen_trial) -> None:
        try:
            import optuna
        except Exception:  # pragma: no cover - optuna import guard
            optuna = None
        if optuna is not None and frozen_trial.state is not optuna.trial.TrialState.COMPLETE:
            return
        if self.objective_count == 1:
            try:
                best_number = int(study.best_trial.number)
            except Exception:
                return
            if best_number == self._previous_best_number:
                return
            self._previous_best_number = best_number
        row = {
            "trial": int(frozen_trial.number),
            "state": str(frozen_trial.state.name),
            "values": _trial_values(frozen_trial),
            "params": dict(frozen_trial.user_attrs.get("quantbt_full_params", frozen_trial.params)),
            "metrics": dict(frozen_trial.user_attrs.get("quantbt_metrics", {})),
            "constraints": list(frozen_trial.user_attrs.get("quantbt_constraints", ())),
            "metadata": dict(frozen_trial.user_attrs.get("quantbt_metadata", {})),
            "duration_seconds": _duration_seconds(frozen_trial),
            "logged_at_unix": time.time(),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _trial_values(frozen_trial) -> list[float]:
    if getattr(frozen_trial, "values", None) is not None:
        return [float(value) for value in frozen_trial.values]
    if getattr(frozen_trial, "value", None) is not None:
        return [float(frozen_trial.value)]
    return []


def _duration_seconds(frozen_trial) -> Optional[float]:
    start = getattr(frozen_trial, "datetime_start", None)
    complete = getattr(frozen_trial, "datetime_complete", None)
    if start is None or complete is None:
        return None
    return float((complete - start).total_seconds())

"""Prepared native-event strategy evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from ..result import ObjectiveResult
from .generic import ObjectiveBuilder


@dataclass
class PreparedNativeEventStrategyEvaluator:
    """Evaluate reactive native-event strategies through a prepared runner."""

    runner: Any
    strategy_factory: Callable[[Mapping[str, Any]], Any]
    objective_builder: ObjectiveBuilder
    trading_days: int = 365

    last_result: Any = field(default=None, init=False)
    last_strategy: Any = field(default=None, init=False)

    def evaluate(self, params: Mapping[str, Any]) -> ObjectiveResult:
        strategy = self.strategy_factory(params)
        result = self.runner.score(strategy, trading_days=self.trading_days)
        objective = self.objective_builder(result, params)
        if not isinstance(objective, ObjectiveResult):
            raise TypeError("objective_builder must return ObjectiveResult")
        self.last_strategy = strategy
        self.last_result = result
        return objective

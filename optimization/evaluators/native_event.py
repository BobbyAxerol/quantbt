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
    retain_last: bool = False

    last_result: Any = field(default=None, init=False)
    last_strategy: Any = field(default=None, init=False)

    def evaluate(self, params: Mapping[str, Any]) -> ObjectiveResult:
        strategy = self.strategy_factory(params)
        result = self.runner.score(strategy, trading_days=self.trading_days)
        objective = self.objective_builder(result, params)
        if not isinstance(objective, ObjectiveResult):
            raise TypeError("objective_builder must return ObjectiveResult")
        if self.retain_last:
            self.last_strategy = strategy
            self.last_result = result
        else:
            # Optimization can run thousands of trials. Retaining a strategy
            # and score result pins their arrays until the evaluator dies.
            self.last_strategy = None
            self.last_result = None
        return objective

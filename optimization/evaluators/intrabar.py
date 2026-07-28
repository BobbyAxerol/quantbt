"""Prepared intrabar evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

import pandas as pd

from ..result import ObjectiveResult
from .generic import ObjectiveBuilder


@dataclass
class PreparedIntrabarEvaluator:
    """Replay intrabar strategy intents through a prepared intrabar runner."""

    runner: Any
    strategy_func: Callable[..., Any]
    objective_builder: ObjectiveBuilder
    intent_builder: Optional[Callable[[Any, Mapping[str, Any]], Any]] = None
    report_level: str = "minimal"
    pass_runner: bool = False
    pass_market: bool = False

    last_result: Any = field(default=None, init=False)
    last_intent: Any = field(default=None, init=False)

    def evaluate(self, params: Mapping[str, Any]) -> ObjectiveResult:
        if self.pass_runner:
            output = self.strategy_func(self.runner, params)
        elif self.pass_market:
            output = self.strategy_func(self.runner.market, params)
        else:
            output = self.strategy_func(params)
        intent = self._to_intent(output, params)
        result = self.runner.run(intent, report_level=self.report_level)
        objective = self.objective_builder(result, params)
        if not isinstance(objective, ObjectiveResult):
            raise TypeError("objective_builder must return ObjectiveResult")
        self.last_intent = intent
        self.last_result = result
        return objective

    def _to_intent(self, output: Any, params: Mapping[str, Any]) -> Any:
        from ...core.intrabar_reference import IntrabarIntentTape

        if self.intent_builder is not None:
            return self.intent_builder(output, params)
        if isinstance(output, IntrabarIntentTape):
            return output
        if isinstance(output, pd.DataFrame):
            return IntrabarIntentTape.from_frame(output)
        raise TypeError("intrabar strategy must return IntrabarIntentTape or DataFrame, or provide intent_builder")

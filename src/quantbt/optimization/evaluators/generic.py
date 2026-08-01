"""Generic QuantBT endpoint evaluator fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from ..result import ObjectiveResult


ObjectiveBuilder = Callable[[Any, Mapping[str, Any]], ObjectiveResult]


@dataclass
class GenericEndpointEvaluator:
    """Evaluate params by building endpoint inputs and calling a run function."""

    build_run_inputs: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    run_func: Callable[..., Any]
    objective_builder: ObjectiveBuilder
    metadata: dict[str, Any] = field(default_factory=dict)

    last_result: Any = field(default=None, init=False)
    last_run_inputs: dict[str, Any] = field(default_factory=dict, init=False)

    def evaluate(self, params: Mapping[str, Any]) -> ObjectiveResult:
        run_inputs = dict(self.build_run_inputs(params))
        result = self.run_func(**run_inputs)
        objective = self.objective_builder(result, params)
        if not isinstance(objective, ObjectiveResult):
            raise TypeError("objective_builder must return ObjectiveResult")
        self.last_run_inputs = run_inputs
        self.last_result = result
        return objective

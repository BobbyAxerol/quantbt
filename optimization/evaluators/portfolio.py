"""Prepared native portfolio evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from ..result import ObjectiveResult
from .generic import ObjectiveBuilder


@dataclass
class PreparedPortfolioEvaluator:
    """Replay strategy position matrices through a prepared portfolio context."""

    prepared_context: Any
    strategy_func: Callable[..., Any]
    objective_builder: ObjectiveBuilder
    pass_context: bool = False
    positions_key: Optional[str] = None

    last_result: Any = field(default=None, init=False)
    last_positions: Any = field(default=None, init=False)

    def evaluate(self, params: Mapping[str, Any]) -> ObjectiveResult:
        output = self.strategy_func(self.prepared_context, params) if self.pass_context else self.strategy_func(params)
        positions = _extract_positions(output, positions_key=self.positions_key)
        result = self.prepared_context.backtest(positions=positions)
        objective = self.objective_builder(result, params)
        if not isinstance(objective, ObjectiveResult):
            raise TypeError("objective_builder must return ObjectiveResult")
        self.last_positions = positions
        self.last_result = result
        return objective


def _extract_positions(output: Any, *, positions_key: Optional[str]) -> Any:
    if positions_key is None:
        return output
    if isinstance(output, Mapping):
        return output[positions_key]
    return getattr(output, positions_key)

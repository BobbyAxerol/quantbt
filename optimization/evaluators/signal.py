"""Prepared single-symbol signal evaluator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from ..result import ObjectiveResult
from .generic import ObjectiveBuilder


@dataclass
class PreparedSignalEvaluator:
    """Replay strategy signals through a prepared single-symbol context."""

    prepared_context: Any
    strategy_func: Callable[..., Any]
    objective_builder: ObjectiveBuilder
    pass_context: bool = False
    signal_key: Optional[str] = None
    signal_col: Optional[str] = None

    last_result: Any = field(default=None, init=False)
    last_signal: Any = field(default=None, init=False)

    def evaluate(self, params: Mapping[str, Any]) -> ObjectiveResult:
        output = self.strategy_func(self.prepared_context, params) if self.pass_context else self.strategy_func(params)
        signal = _extract_signal(output, signal_key=self.signal_key)
        result = self.prepared_context.backtest(signal=signal, signal_col=self.signal_col)
        objective = self.objective_builder(result, params)
        if not isinstance(objective, ObjectiveResult):
            raise TypeError("objective_builder must return ObjectiveResult")
        self.last_signal = signal
        self.last_result = result
        return objective


def _extract_signal(output: Any, *, signal_key: Optional[str]) -> Any:
    if signal_key is None:
        return output
    if isinstance(output, Mapping):
        return output[signal_key]
    return getattr(output, signal_key)

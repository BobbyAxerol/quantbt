"""Evaluator protocol for domain-specific optimization adapters."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from .result import ObjectiveResult


class TrialEvaluator(Protocol):
    """Protocol implemented by domain adapters.

    The optimizer only sees parameters and an ObjectiveResult. Signal,
    intrabar, portfolio, arbitrage, grid/DCA, and options details must remain
    inside evaluator implementations.
    """

    def evaluate(self, params: Mapping[str, Any]) -> ObjectiveResult:
        """Evaluate one parameter set and return objective values."""

        ...

"""Generic arbitrage optimization adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .generic import GenericEndpointEvaluator


@dataclass(frozen=True)
class ArbitrageTrialOutput:
    """Domain output contract for arbitrage trial builders."""

    signal: Any
    hedge_ratios: Any = None
    run_overrides: dict[str, Any] = field(default_factory=dict)


class ArbitrageGenericEvaluator(GenericEndpointEvaluator):
    """Generic fallback for arbitrage endpoints until specialized evaluators exist."""


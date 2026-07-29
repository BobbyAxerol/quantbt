"""Generic grid/DCA optimization adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .generic import GenericEndpointEvaluator


@dataclass(frozen=True)
class GridDCATrialOutput:
    """Domain output contract for structural grid/DCA trial builders."""

    levels: Any = None
    order_plan: Any = None
    run_overrides: dict[str, Any] = field(default_factory=dict)


class GridDCAGenericEvaluator(GenericEndpointEvaluator):
    """Generic fallback for grid/DCA endpoints until prepared adapters exist."""


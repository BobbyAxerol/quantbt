"""Generic option-package optimization adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .generic import GenericEndpointEvaluator


@dataclass(frozen=True)
class OptionTrialOutput:
    """Domain output contract for option package trial builders."""

    package: Any = None
    hedge_plan: Any = None
    run_overrides: dict[str, Any] = field(default_factory=dict)


class OptionPackageGenericEvaluator(GenericEndpointEvaluator):
    """Generic fallback for option package endpoints until prepared adapters exist."""


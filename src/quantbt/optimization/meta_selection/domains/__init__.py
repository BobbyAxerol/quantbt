"""Internal extension contracts; existing public WFO endpoints remain stable."""

from .contracts import (DOMAIN_ABI, DomainCompatibility, DomainEvaluationAdapter, DomainEvaluationOutput,
    EvaluationBinding, EvaluationEvidence, EvaluationStage, InputKind, MarketBinding)
from .registry import capability, check_route_inventory, route_metadata

__all__ = ["DOMAIN_ABI", "DomainCompatibility", "DomainEvaluationAdapter", "DomainEvaluationOutput",
    "EvaluationBinding", "EvaluationEvidence", "EvaluationStage", "InputKind",
    "MarketBinding", "capability", "check_route_inventory", "route_metadata"]

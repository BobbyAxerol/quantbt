"""Opt-in research adapters; not a public endpoint or a financial runtime."""

from .identity import AnalysisKey, ExecutionKey, SelectionKey
from .planner import DiagnosticNeeds, compile_plan
from .access import AccessPolicy, AccessWitness
from .evidence import ExecutionEvidence, MissingInputs, PanelRow
from .reuse import DiagnosticReuse

__all__ = ["AnalysisKey", "ExecutionKey", "SelectionKey", "DiagnosticNeeds",
           "compile_plan", "AccessPolicy", "AccessWitness", "ExecutionEvidence",
           "MissingInputs", "PanelRow", "DiagnosticReuse"]

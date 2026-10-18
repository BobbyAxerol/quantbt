"""Shared, opt-in pre-search diagnostics, independent of WFO/meta mode."""

from .access import AccessPolicy, AccessWitness
from .assessment import AlphaDiagnostics
from .contracts import (DiagnosticAdvice, DiagnosticAnalysis, DiagnosticBudget,
                        DiagnosticContext, DiagnosticObservation)
from .evidence import ExecutionEvidence, MissingInputs, PanelRow
from .identity import AnalysisKey, ExecutionKey, SelectionKey
from .planner import DiagnosticNeeds, compile_plan
from .report import AlphaDiagnosticReport
from .research_contracts import DiagnosticAccount, DiagnosticResearch, DiagnosticTrial
from .reuse import DiagnosticReuse
from .decisions import (FoldDecisionEvidence, FoldSlot, MetricSupplement, ReportCohort,
                        ResearchDecisionReport, RetainedAccountReport, RetainedInterval)

__all__ = ["AccessPolicy", "AccessWitness", "AlphaDiagnostics", "AlphaDiagnosticReport",
    "DiagnosticAdvice", "DiagnosticAnalysis", "DiagnosticBudget", "DiagnosticContext",
    "DiagnosticAccount", "DiagnosticResearch", "DiagnosticTrial",
    "DiagnosticObservation", "DiagnosticNeeds", "DiagnosticReuse", "ExecutionEvidence",
    "MissingInputs", "PanelRow", "ExecutionKey", "AnalysisKey", "SelectionKey", "compile_plan",
    "FoldDecisionEvidence", "FoldSlot", "MetricSupplement", "ReportCohort", "ResearchDecisionReport",
    "RetainedAccountReport", "RetainedInterval"]

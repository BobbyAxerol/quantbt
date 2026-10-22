"""Shared research geometry over existing parameter/execution contracts."""

from .schema import EffectiveGeometry, OrderedConstraint, ResolvedPoint
from .design import ProbeRow, ProposalLedger, neutral_coverage, saltelli_layout
from .neighborhoods import Neighborhood, active_neighbors
from .sensitivity import paired_screen, validate_saltelli_outputs
from .structured import IndependentInputs, TrajectoryLayout, saltelli_completion, saltelli_inputs, trajectory_inputs, trajectory_layout
from .estimators import estimate_saltelli, trajectory_screen
from .finite_panel import finite_panel_screen
from .basins import basin_catalog, local_summary, representative

__all__ = [
    "EffectiveGeometry", "OrderedConstraint", "ResolvedPoint", "ProbeRow", "ProposalLedger",
    "neutral_coverage", "saltelli_layout", "Neighborhood", "active_neighbors", "paired_screen",
    "validate_saltelli_outputs", "basin_catalog", "local_summary", "representative",
    "IndependentInputs", "TrajectoryLayout", "saltelli_inputs", "trajectory_inputs",
    "trajectory_layout", "estimate_saltelli", "trajectory_screen",
    "finite_panel_screen",
    "saltelli_completion",
]

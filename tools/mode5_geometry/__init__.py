"""Opt-in research geometry over existing parameter and execution contracts."""

from .schema import EffectiveGeometry, OrderedConstraint, ResolvedPoint
from .design import ProbeRow, ProposalLedger, neutral_coverage, saltelli_layout
from .neighborhoods import Neighborhood, active_neighbors
from .sensitivity import paired_screen, validate_saltelli_outputs
from .basins import basin_catalog, local_summary, representative

__all__ = [
    "EffectiveGeometry", "OrderedConstraint", "ResolvedPoint", "ProbeRow", "ProposalLedger",
    "neutral_coverage", "saltelli_layout", "Neighborhood", "active_neighbors", "paired_screen",
    "validate_saltelli_outputs", "basin_catalog", "local_summary", "representative",
]

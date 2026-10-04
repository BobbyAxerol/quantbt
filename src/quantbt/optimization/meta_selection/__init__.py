"""Internal QMS record foundation; not a public meta-selection endpoint."""

from .common import MetaRecordError
from .records import (
    CandidateForwardRecord,
    CandidateISRecord,
    CandidateRoleRef,
    CompatibilityFamily,
    MetaTask,
    MetricContract,
    MetricObservation,
    OutcomeStatus,
)

__all__ = [
    "MetaRecordError",
    "CandidateForwardRecord",
    "CandidateISRecord",
    "CandidateRoleRef",
    "CompatibilityFamily",
    "MetaTask",
    "MetricContract",
    "MetricObservation",
    "OutcomeStatus",
]

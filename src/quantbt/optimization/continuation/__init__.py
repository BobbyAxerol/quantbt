"""Opt-in, owned and version-pinned continuation; not an endpoint resume flag."""

from .contract import ContinuationConfig, ContinuationError
from .session import ExactStudySession, Proposal

__all__ = ["ContinuationConfig", "ContinuationError", "ExactStudySession", "Proposal"]

"""Additive verification contracts that do not own production execution."""

from .canonical_trace_v2 import (
    CANONICAL_TRACE_V2_SCHEMA_VERSION,
    CanonicalEventKindV2,
    CanonicalTraceRowV2,
    CanonicalTraceV2,
    TerminalFingerprintV2,
    adapt_legacy_trace_v1_to_v2,
    compare_canonical_traces_v2,
    default_linear_trace_tolerance_v2,
    terminal_fingerprint_v2,
)

__all__ = [
    "CANONICAL_TRACE_V2_SCHEMA_VERSION",
    "CanonicalEventKindV2",
    "CanonicalTraceRowV2",
    "CanonicalTraceV2",
    "TerminalFingerprintV2",
    "adapt_legacy_trace_v1_to_v2",
    "compare_canonical_traces_v2",
    "default_linear_trace_tolerance_v2",
    "terminal_fingerprint_v2",
]

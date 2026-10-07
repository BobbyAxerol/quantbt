"""Exclusive component profiles; instrumented timings are never latency gates."""

from tools.qms07_profile import StageProfile


class PublicCostProfile(StageProfile):
    def __enter__(self):
        super().__enter__()
        from quantbt.endpoint import _WalkForwardEndpointScorer
        from quantbt.optimization.meta_selection.witness import PreparedMetricWitness
        from quantbt.optimization.meta_selection.observer import ResultMetricAdapter
        from quantbt.optimization.meta_selection.nested import NestedISPoolCapture

        self.rows["witness"] = dict(
            calls=0, inclusive_seconds=0.0, exclusive_seconds=0.0
        )
        self.rows["outer_is"] = dict(
            calls=0, inclusive_seconds=0.0, exclusive_seconds=0.0
        )
        for owner, name, stage in (
            (_WalkForwardEndpointScorer, "__call__", "is_score"),
            (PreparedMetricWitness, "market_signature", "witness"),
            (PreparedMetricWitness, "header", "witness"),
            (PreparedMetricWitness, "validate_source", "witness"),
            (ResultMetricAdapter, "observe", "witness"),
        ):
            self.instrument(owner, name, stage)
        self.instrument(NestedISPoolCapture, "capture", "outer_is")
        return self

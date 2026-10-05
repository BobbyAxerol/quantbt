"""W3 stays a reset-flat native window surface, never a scalar signal proxy."""

from .scalar import ScalarDomainAdapter
from .contracts import DomainEvaluationOutput, EvaluationStage, InputKind
from ..common import MetaRecordError


class ReactiveDomainAdapter(ScalarDomainAdapter):
    domain = "reactive"
    input_kind = InputKind.REACTIVE_WINDOW

    def validate_payload(self, payload, index):
        from ....backends.reactive_wfo_support import ReactiveWfoScoreMarkerV1

        if not isinstance(payload, ReactiveWfoScoreMarkerV1):
            raise MetaRecordError("META_DOMAIN_INPUT_MISMATCH: typed reactive marker required")
        runner = self.runtime.engine.scorer.runtime._prepared_runner
        if runner is None or not runner.idx[payload.task.start_bar:payload.task.end_bar].equals(index):
            raise MetaRecordError("META_DOMAIN_CALENDAR_INVALID: reactive window mismatch")

    def observer_evaluator(self, data, fold, task):
        from ....backends.reactive_wfo_support import ReactiveWfoScoreMarkerV1
        from ..runtime import isolated_observer_rng
        from time import perf_counter

        boundary = self.runtime.engine.scorer
        lifecycle_start = len(boundary.lifecycle)

        def evaluate(candidate):
            self._check()
            with isolated_observer_rng(task.resolved_fold_seed + candidate.native_trial_id + 1):
                marker = ReactiveWfoScoreMarkerV1(task=boundary.runtime.make_task(
                    params=candidate.effective_params, fold=fold, evaluation_index=fold.test_index,
                    stage="post_seal_counterfactual_forward"), params=dict(candidate.effective_params))
                signature = boundary.executor().binding(marker,
                    observer_seed=task.resolved_fold_seed + candidate.native_trial_id + 1).market_id
                binding = self.bind_input(payload=marker, index=fold.test_index,
                    params=candidate.effective_params, stage=EvaluationStage.POST_SEAL_FORWARD,
                    input_signature=signature, information_as_of=task.data_cutoff,
                    decision_sealed_at=task.decision_sealed_at)
                started = perf_counter()
                _, result, executed_signature = self.evaluate(binding, lambda b:
                    boundary.execute(b.payload, include_observation=False,
                        observer_seed=task.resolved_fold_seed + candidate.native_trial_id + 1))
                if executed_signature != signature:
                    raise MetaRecordError("META_DOMAIN_RESULT_UNBOUND: reactive signature changed")
                boundary.runtime._score_calls += 1
                boundary.runtime._score_bars += marker.task.bars
                boundary.runtime._score_seconds += perf_counter() - started
                return DomainEvaluationOutput(binding, result)

        class LifecycleView:
            def __iter__(self):
                return iter(boundary.lifecycle[lifecycle_start:])

        return evaluate, LifecycleView()

    def cancel(self):
        super().cancel()
        self.runtime.engine.scorer.cancel_active()

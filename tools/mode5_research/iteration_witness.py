"""Retain existing compiler signatures without changing their financial owner."""

from copy import deepcopy


class FeedbackSignatureObserver:
    """Pair the original signature calls; no hashing, simulation or convergence.

    Callers explicitly bind these two decorators in their worker-local driver.
    An unfinished pair is diagnostic state, never a resumable account snapshot.
    """

    def __init__(self, observer, compilation_signature, result_signature):
        if not callable(compilation_signature) or not callable(result_signature):
            raise TypeError("original signature functions required")
        self._observer = observer
        self._compilation_signature = compilation_signature
        self._result_signature = result_signature
        self._pending = None
        self._completed = 0
        self._fault = False

    def _active(self):
        if self._fault:
            raise RuntimeError("signature witness fault remains latched")

    def compilation(self, compilation):
        self._active()
        try:
            if self._pending is not None:
                raise RuntimeError("previous signature pair has no returned result")
            value = self._observer.call("signature_compilation",
                                        self._compilation_signature, compilation)
            self._pending = dict(run=self._completed + 1, command_hash=value,
                commands=len(compilation.commands), feedback_count=compilation.feedback_count,
                unmapped_feedback=compilation.unmapped_feedback)
            return value
        except BaseException:
            self._fault = True
            raise

    def result(self, result):
        self._active()
        try:
            if self._pending is None:
                raise RuntimeError("returned result has no compilation signature")
            value = self._observer.call("signature_result", self._result_signature, result)
            self._observer.emit("feedback_iteration_witness",
                witness_schema="mode5.feedback-signature-pair.v1",
                **self._pending, result_hash=value, fills=len(result.fills),
                scope="returned_signature_pair_not_convergence_certificate")
            self._completed += 1
            self._pending = None
            return value
        except BaseException:
            self._fault = True
            raise

    def summary(self):
        return deepcopy(dict(schema="mode5.feedback-signature-pair.v1",
            completed_signature_pairs=self._completed, pending_compilation=self._pending,
            fault_latched=self._fault, additional_hash_calls=0,
            additional_financial_calls=0, checkpoint=False,
            unreturned_result="UNAVAILABLE_NOT_ZERO" if self._pending is not None else None))

"""Worker-scoped observation of the frozen driver's existing signature calls."""

from types import SimpleNamespace

from tools.mode5_research.iteration_witness import FeedbackSignatureObserver


def witnessed_observer_type(base, compilation_signature, result_signature):
    """Keep the original observer/guards; journal only the two exact callbacks."""
    if not all(callable(value) for value in (base, compilation_signature, result_signature)):
        raise TypeError("observer type and original signature functions required")
    signatures = {
        "signature_compilation": compilation_signature,
        "signature_result": result_signature,
    }

    class WitnessedObserver(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._binding_fault = False
            original = SimpleNamespace(call=super().call, emit=self.emit)
            self.signature_witness = FeedbackSignatureObserver(
                original, compilation_signature, result_signature)

        def call(self, stage, callback, *args, **kwargs):
            if self._binding_fault:
                raise RuntimeError("driver signature binding fault remains latched")
            if stage not in signatures:
                return super().call(stage, callback, *args, **kwargs)
            if callback is not signatures[stage] or len(args) != 1 or kwargs:
                self._binding_fault = True
                raise RuntimeError("exact original driver signature callback required")
            operation = (self.signature_witness.compilation if stage == "signature_compilation"
                         else self.signature_witness.result)
            return operation(args[0])

        def summary(self):
            return dict(super().summary(), signature_witness=self.signature_witness.summary(),
                        signature_binding_fault_latched=self._binding_fault)

    return WitnessedObserver

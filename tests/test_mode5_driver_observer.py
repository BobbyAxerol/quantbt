"""Exact frozen-driver call pattern, without private strategy execution."""

from contextlib import ExitStack
import json
from unittest.mock import patch

import pytest

from tools.mode5_admission import conformance
from tools.mode5_research.driver_observer import witnessed_observer_type
from tools.mode5_research.feedback_observer import FeedbackObserver


def observer_type():
    return witnessed_observer_type(FeedbackObserver, conformance.Compilation.signature,
                                   conformance.result_signature)


def test_original_driver_pattern_preserves_full_certificate_guards_and_bill(tmp_path):
    from tests.mode5.test_admission_conformance import fixture, run
    data, commands = fixture()
    signatures = conformance.Compilation.signature, conformance.result_signature
    traces = []
    certificates = []
    for label, factory in (("original", FeedbackObserver), ("observed", observer_type())):
        trace = []
        with factory(tmp_path / label, guard=lambda: trace.append("guard")) as observer:
            def build(previous):
                trace.append("build")
                return conformance.Compilation(commands, (), 0 if previous is None else 2)
            def execute(tape):
                trace.append("execute")
                return run(data, tape)
            with ExitStack() as stack:
                stack.enter_context(patch.object(conformance.Compilation, "signature",
                    lambda compilation: observer.call("signature_compilation", signatures[0], compilation)))
                stack.enter_context(patch.object(conformance, "result_signature",
                    lambda result: observer.call("signature_result", signatures[1], result)))
                certificate = conformance.certify_feedback(
                    lambda previous: observer.call("build", build, previous),
                    lambda tape: observer.execute("python", execute, tape, bars=lambda result: len(data)),
                    max_runs=5)
            certificates.append(certificate)
            assert observer.completed_passes == 3
            assert observer.completed_account_bars == 18
            if label == "observed":
                assert observer.summary()["signature_witness"]["completed_signature_pairs"] == 3
        traces.append(trace)
    assert traces[0] == traces[1]
    assert certificates[0].iterations == certificates[1].iterations
    rows = [row for row in map(json.loads, (tmp_path / "observed").read_text().splitlines())
            if row["stage"] == "feedback_iteration_witness"]
    assert [row["run"] for row in rows] == [1, 2, 3]
    for row, expected in zip(rows, certificates[0].iterations, strict=True):
        assert {key: row[key] for key in expected} == expected


@pytest.mark.parametrize("bad", ["callback", "positional", "keyword"])
def test_alternate_driver_signature_binding_fails_closed_before_callback(tmp_path, bad):
    with observer_type()(tmp_path / "progress") as observer:
        compilation = conformance.Compilation((), (), 0)
        callback = conformance.Compilation.signature
        args, kwargs = (compilation,), {}
        if bad == "callback":
            callback = lambda value: pytest.fail("must not run alternate hash")
        elif bad == "positional":
            args = ()
        else:
            kwargs = {"extra": True}
        with pytest.raises(RuntimeError, match="exact original"):
            observer.call("signature_compilation", callback, *args, **kwargs)
        assert observer.summary()["signature_binding_fault_latched"]
        with pytest.raises(RuntimeError, match="latched"):
            observer.call("build", lambda: pytest.fail("must not retry"))
        assert observer.stage_calls == {}


@pytest.mark.parametrize("where", ["before", "after"])
def test_original_guard_fault_prevents_pair_and_latches_witness(tmp_path, where):
    count = 0
    def guard():
        nonlocal count
        count += 1
        if count == (1 if where == "before" else 2):
            raise InterruptedError(where)
    with observer_type()(tmp_path / "progress", guard=guard) as observer:
        with pytest.raises(InterruptedError, match=where):
            observer.call("signature_compilation", conformance.Compilation.signature,
                          conformance.Compilation((), (), 0))
        assert observer.summary()["signature_witness"]["fault_latched"]
        assert observer.completed_passes == 0
        with pytest.raises(RuntimeError, match="latched"):
            observer.call("signature_compilation", conformance.Compilation.signature,
                          conformance.Compilation((), (), 0))


def test_interrupted_result_remains_pending_and_fault_receipt_keeps_work(tmp_path):
    with observer_type()(tmp_path / "progress") as observer:
        observer.call("signature_compilation", conformance.Compilation.signature,
                      conformance.Compilation((), (), 0))
        error = InterruptedError("actual execution interrupted")
        observer.fault_receipt(tmp_path / "fault.json", error)
    receipt = json.loads((tmp_path / "fault.json").read_text())
    assert receipt["work"]["signature_witness"]["unreturned_result"] == "UNAVAILABLE_NOT_ZERO"
    assert receipt["work"]["signature_witness"]["checkpoint"] is False
    assert receipt["work"]["actual_execution_calls"] == 0


def test_independent_workers_do_not_share_signature_state(tmp_path):
    factory = observer_type()
    with factory(tmp_path / "a") as first, factory(tmp_path / "b") as second:
        first.call("signature_compilation", conformance.Compilation.signature,
                   conformance.Compilation((), (), 0))
        assert first.summary()["signature_witness"]["pending_compilation"]
        assert second.summary()["signature_witness"]["pending_compilation"] is None


@pytest.mark.parametrize("bad", [(None, None, None), (FeedbackObserver, None, lambda: None)])
def test_factory_rejects_missing_original_functions(bad):
    with pytest.raises(TypeError):
        witnessed_observer_type(*bad)

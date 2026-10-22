"""Passive actual-signature journaling, never a substitute execution engine."""

from contextlib import ExitStack
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools.mode5_admission import conformance
from tools.mode5_research.feedback_observer import FeedbackObserver
from tools.mode5_research.iteration_witness import FeedbackSignatureObserver


class Calls:
    def __init__(self):
        self.calls, self.events = [], []

    def call(self, stage, function, argument):
        self.calls.append(stage)
        return function(argument)

    def emit(self, stage, **fields):
        self.events.append(dict(stage=stage, **fields))


def fake(observer=None):
    owner = observer or Calls()
    signatures = []
    def compilation(value):
        signatures.append('compilation')
        return 'original-command-digest'
    def result(value):
        signatures.append('result')
        return 'original-result-digest'
    return owner, signatures, FeedbackSignatureObserver(owner, compilation, result)


def inputs():
    return conformance.Compilation((1, 2), (), 3, 1), SimpleNamespace(fills=(1, 2, 3))


def test_pair_uses_each_original_hash_once_and_keeps_return_values():
    owner, calls, witness = fake()
    compilation, result = inputs()
    assert witness.compilation(compilation) == 'original-command-digest'
    assert witness.result(result) == 'original-result-digest'
    assert calls == ['compilation', 'result']
    assert owner.calls == ['signature_compilation', 'signature_result']
    row, = owner.events
    assert (row['run'], row['commands'], row['fills'], row['feedback_count'],
            row['unmapped_feedback']) == (1, 2, 3, 3, 1)
    assert row['scope'] == 'returned_signature_pair_not_convergence_certificate'
    assert witness.summary()['completed_signature_pairs'] == 1


@pytest.mark.parametrize('wrong', ['result_first', 'double_compilation', 'double_result'])
def test_out_of_order_pairs_fail_closed_and_latch(wrong):
    owner, calls, witness = fake()
    compilation, result = inputs()
    with pytest.raises(RuntimeError):
        if wrong == 'result_first':
            witness.result(result)
        else:
            witness.compilation(compilation)
            if wrong == 'double_compilation':
                witness.compilation(compilation)
            else:
                witness.result(result)
                witness.result(result)
    before = list(calls)
    with pytest.raises(RuntimeError, match='latched'):
        witness.compilation(compilation)
    assert calls == before


def test_unreturned_compilation_is_not_zero_work_or_checkpoint_and_export_detaches():
    owner, calls, witness = fake()
    witness.compilation(inputs()[0])
    summary = witness.summary()
    assert summary['unreturned_result'] == 'UNAVAILABLE_NOT_ZERO'
    assert summary['completed_signature_pairs'] == 0
    assert summary['checkpoint'] is False
    summary['pending_compilation']['run'] = 999
    assert witness.summary()['pending_compilation']['run'] == 1
    assert not owner.events


@pytest.mark.parametrize('stage', ['signature_compilation', 'signature_result', 'journal'])
def test_guard_signature_and_journal_faults_propagate_without_retry(stage):
    owner, calls, witness = fake()
    original = owner.call
    def call(name, function, argument):
        if name == stage:
            raise InterruptedError(stage)
        return original(name, function, argument)
    owner.call = call
    if stage == 'journal':
        owner.emit = lambda *args, **kwargs: (_ for _ in ()).throw(InterruptedError(stage))
    compilation, result = inputs()
    with pytest.raises(InterruptedError):
        witness.compilation(compilation)
        witness.result(result)
    assert witness.summary()['fault_latched']
    assert witness.summary()['completed_signature_pairs'] == 0
    with pytest.raises(RuntimeError, match='latched'):
        witness.result(result)


def test_real_compiler_and_original_engine_certificate_stay_exact(tmp_path):
    from tests.mode5.test_admission_conformance import fixture, run
    data, commands = fixture()
    calls = []
    def build(previous):
        calls.append('build')
        return conformance.Compilation(commands, (), 0 if previous is None else 2)
    def execute(tape):
        calls.append('execute')
        return run(data, tape)
    original = conformance.certify_feedback(build, execute, max_runs=5)
    original_calls = list(calls)
    calls.clear()
    path = tmp_path / 'progress.jsonl'
    with FeedbackObserver(path) as observer:
        witness = FeedbackSignatureObserver(observer, conformance.Compilation.signature,
                                            conformance.result_signature)
        with ExitStack() as stack:
            stack.enter_context(patch.object(conformance.Compilation, 'signature',
                                            lambda compilation: witness.compilation(compilation)))
            stack.enter_context(patch.object(conformance, 'result_signature', witness.result))
            observed = conformance.certify_feedback(
                build, lambda tape: observer.execute('python_oracle', execute, tape,
                                                     bars=lambda result: len(result.equity)),
                max_runs=5)
        assert observer.completed_passes == len(original.iterations) == 3
        assert observer.completed_account_bars == len(data) * 3
    assert calls == original_calls
    assert observed.iterations == original.iterations
    assert observed.compilation.signature() == original.compilation.signature()
    assert conformance.result_signature(observed.result) == conformance.result_signature(original.result)
    rows = [row for row in map(json.loads, path.read_text().splitlines())
            if row['stage'] == 'feedback_iteration_witness']
    assert len(rows) == len(original.iterations)
    for row, expected in zip(rows, original.iterations, strict=True):
        assert {name: row[name] for name in expected} == expected
    assert witness.summary()['completed_signature_pairs'] == len(original.iterations)
    assert witness.summary()['additional_financial_calls'] == 0

"""C02: real native original-pass witnesses, strict transport and atomic aborts."""

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from quantbt.backends.reactive_wfo_support import ReactiveWfoRuntimeConfigV1
from quantbt.core.runtime_governance import RuntimeBudgetV1, RuntimeBudgetError, RuntimeCanceledError
from quantbt.optimization.meta_selection.common import MetaRecordError, wire
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.reactive import ReactiveMetricBoundary
from quantbt.optimization.meta_selection.reactive_transport import DetachedReactiveWitnessV1
from tests.meta_selection.test_local_reactive import execute


@pytest.fixture(scope="module")
def packet():
    packets = []
    original = ReactiveMetricBoundary.execute

    def capture(self, marker, **kwargs):
        row, result, signature = original(self, marker, **kwargs)
        packets.append(result)
        return row, result, signature

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ReactiveMetricBoundary, "execute", capture)
        execute("shadow")
    return packets[0]


def test_c02_t01_wire_is_detached_and_exact(packet):
    payload = packet.to_payload()
    restored = DetachedReactiveWitnessV1.from_payload(json.loads(json.dumps(payload)))
    assert restored == packet
    assert restored.row() == packet.row()
    assert len(json.dumps(payload)) < 8192
    assert set(payload) == {"schema", "binding", "scores", "observation", "seal"}
    assert "original_result" == restored.observation.verification


@pytest.mark.parametrize("field", ["task_id", "params_id", "market_id", "calendar_id",
                                  "economics_id", "metric_id", "observer_seed"])
def test_c02_t01_wrong_request_rejected(packet, field):
    value = 42 if field == "observer_seed" else "wrong"
    with pytest.raises(MetaRecordError, match="binding"):
        packet.validate(binding=replace(packet.binding, **{field: value}))


@pytest.mark.parametrize("change", ["missing", "truncated", "schema", "score", "observation", "extra"])
def test_c02_t01_corrupt_wire_rejected(packet, change):
    payload = packet.to_payload()
    if change == "missing":
        payload.pop("binding")
    elif change == "truncated":
        payload["scores"].pop()
    elif change == "schema":
        payload["schema"] = "future"
    elif change == "score":
        payload["scores"][0] = float(99.).hex()
    elif change == "observation":
        payload["observation"]["verification"] = "unverified"
    else:
        payload["market_arrays"] = []
    with pytest.raises(MetaRecordError):
        DetachedReactiveWitnessV1.from_payload(payload)


@pytest.mark.parametrize("kind", ["cancel", "deadline"])
def test_c02_t04_observer_abort_does_not_publish_partial_revision(kind, monkeypatch):
    history = MetaHistory()
    owners = []
    original = ReactiveMetricBoundary.execute

    def abort(self, marker, **kwargs):
        owners.append(self)
        result = original(self, marker, **kwargs)
        if marker.task.stage == "post_seal_counterfactual_forward":
            if kind == "cancel":
                raise RuntimeCanceledError("test observer cancellation")
            raise RuntimeBudgetError("MAX_WALL_TIME", "test observer deadline")
        return result

    monkeypatch.setattr(ReactiveMetricBoundary, "execute", abort)
    with pytest.raises((RuntimeCanceledError, RuntimeBudgetError)):
        execute("active", history=history)
    assert not history._revisions
    assert owners[0]._meta_witness.closed
    assert owners[0]._executor.active_runner is None
    assert owners[0].runtime._adapter is None


def _process_parity():
    import multiprocessing

    from quantbt.backends.reactive_wfo_workers import fork_reactive_wfo_worker_safe

    assert fork_reactive_wfo_worker_safe()
    outputs = {}
    for mode in (None, "shadow", "active"):
        local, _, _ = execute(mode)
        worker, _, runtime = execute(mode, runtime_config=ReactiveWfoRuntimeConfigV1(worker_mode="process"))
        assert local.params_by_fold == worker.params_by_fold
        np.testing.assert_array_equal(local.trial_table.objective, worker.trial_table.objective)
        for a, b in zip(local.fold_results, worker.fold_results, strict=True):
            for field in ("equity", "returns", "positions", "fees", "funding"):
                np.testing.assert_array_equal(getattr(a.result, field), getattr(b.result, field))
        if mode:
            a, b = local.metadata["meta_selection"], worker.metadata["meta_selection"]
            for left, right in zip(a["tasks"], b["tasks"], strict=True):
                assert left.family == right.family
                assert [wire(c.observation) for c in left.candidates] == [wire(c.observation) for c in right.candidates]
                assert [c.objective for c in left.candidates] == [c.objective for c in right.candidates]
            assert b["observer_failures"] == 0
            assert runtime._meta_boundary is None and runtime._process_worker is None
        runtime.close()
        outputs[str(mode)] = len(worker.folds)
    assert not multiprocessing.active_children()
    # The existing reviewed-history fixture must actually switch the applied
    # candidate on process transport too, not merely report 'active' metadata.
    from tests.meta_selection import test_local_reactive as original_tests

    original_execute = original_tests.execute
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(original_tests, "execute", lambda *args, **kwargs: original_execute(
            *args, **kwargs, runtime_config=ReactiveWfoRuntimeConfigV1(worker_mode="process")))
        original_tests.test_w3_supported_meta_actually_switches_the_applied_native_candidate()
        original_tests.test_w3_active_metadata_actual_params_and_future_invariance()
    assert not multiprocessing.active_children()
    print(json.dumps(dict(process_original_pass_parity=outputs, children=0)))


def test_c02_t02_actual_clean_process_parity():
    code = "from tests.meta_selection.test_c02_transport import _process_parity; _process_parity()"
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", NUMBA_NUM_THREADS="1",
        PYTHONPATH=str(Path.cwd() / "src") + ":" + str(Path.cwd()))
    result = subprocess.run([sys.executable, "-c", code], env=environment,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"children": 0' in result.stdout


def test_c02_t04_actual_native_witness_deadline(monkeypatch):
    from tests.test_phase76_reactive_wfo import _TaskStrategy
    import time

    original = _TaskStrategy.on_bar_close

    def slow(self, context, out):
        time.sleep(0.003)
        return original(self, context, out)

    monkeypatch.setattr(_TaskStrategy, "on_bar_close", slow)
    with pytest.raises(RuntimeBudgetError, match="deadline"):
        execute("shadow", runtime_config=ReactiveWfoRuntimeConfigV1(
            runtime_budget=RuntimeBudgetV1(max_wall_time_ms=1)))


def test_c02_t04_cancel_reaches_active_original_native_runner(monkeypatch):
    from tests.test_phase76_reactive_wfo import _TaskStrategy

    owners = []
    original_execute = ReactiveMetricBoundary.execute

    def remember(self, marker, **kwargs):
        owners.append(self)
        return original_execute(self, marker, **kwargs)

    def cancel(self, context, out):
        owner = owners[-1]
        assert owner._executor.active_runner is not None
        owner.runtime.cancel("test active original native witness")

    monkeypatch.setattr(ReactiveMetricBoundary, "execute", remember)
    monkeypatch.setattr(_TaskStrategy, "on_bar_close", cancel)
    with pytest.raises(RuntimeCanceledError):
        execute("shadow")
    assert owners[0]._executor.active_runner is None
    assert owners[0]._executor.closed and owners[0]._meta_witness.closed


def _worker_lifetime():
    import random
    from quantbt.backends.reactive_wfo_workers import ForkReactiveWfoWorkerV1
    from quantbt.optimization.meta_selection.reactive_execution import OriginalReactiveWitnessExecutor
    from tests.test_phase76_reactive_wfo import _worker_fixture, _TaskStrategy

    runtime, previous, marker = _worker_fixture()
    previous.close()
    executor = OriginalReactiveWitnessExecutor(adapter=runtime._adapter,
        prepared_runner=runtime._prepared_runner, data=runtime.data, trading_days=365)
    worker = ForkReactiveWfoWorkerV1(adapter=runtime._adapter, prepared_runner=runtime._prepared_runner,
        trading_days=365, parallelism_plan=runtime._parallelism_plan, max_inflight_tasks=1,
        metric_executor=executor)
    control = ForkReactiveWfoWorkerV1(adapter=runtime._adapter, prepared_runner=runtime._prepared_runner,
        trading_days=365, parallelism_plan=runtime._parallelism_plan, max_inflight_tasks=1,
        metric_executor=executor)
    try:
        def stochastic(self, context, out):
            from quantbt import OrderSide

            bar = int(context.bar_index)
            if bar == self.task.start_bar:
                random.random()  # CPython reseeds this stream automatically on fork.
                self.random_qty = float(np.random.random())
                out.market(0, OrderSide.BUY, self.random_qty)
            elif bar == self.task.start_bar + 4:
                out.market(0, OrderSide.SELL, self.random_qty, reduce_only=True)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(_TaskStrategy, "on_bar_close", stochastic)
            worker._start()
            control._start()
            # Both fork/COW copies begin with exactly the same RNG state.
            # The forward observer must not change the subsequent search stream.
            before = worker.score(marker, canceled=lambda: False, witness_binding=executor.binding(marker))
            assert before == control.score(marker, canceled=lambda: False, witness_binding=executor.binding(marker))
            worker.score(marker, canceled=lambda: False, witness_binding=executor.binding(marker, observer_seed=731))
            after = worker.score(marker, canceled=lambda: False, witness_binding=executor.binding(marker))
            assert after == control.score(marker, canceled=lambda: False, witness_binding=executor.binding(marker))
            assert before.observation.output_ref != after.observation.output_ref
            generation = worker.identity.generation
            worker._process.terminate()
            worker._process.join(1.)
            restarted = worker.score(marker, canceled=lambda: False, witness_binding=executor.binding(marker))
            assert restarted == before and worker.identity.generation > generation
        cancel_checks = []

        def canceled():
            cancel_checks.append(1)
            return len(cancel_checks) > 1

        with pytest.raises(RuntimeCanceledError):
            worker.score(marker, canceled=canceled,
                         witness_binding=executor.binding(marker))
        assert worker._process is None
    finally:
        worker.close()
        worker.close()
        control.close()
        executor.close()
        runtime.close()
    import multiprocessing

    assert not multiprocessing.active_children()
    print("c02-worker-lifetime-ok")


def test_c02_t03_t04_worker_observer_rng_death_recovery_cleanup():
    result = subprocess.run([sys.executable, "-c",
        "from tests.meta_selection.test_c02_transport import _worker_lifetime; _worker_lifetime()"],
        env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1"),
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "c02-worker-lifetime-ok" in result.stdout


def _bad_replies():
    from quantbt.backends.reactive_wfo_workers import ForkReactiveWfoWorkerV1, ReactiveWfoWorkerError
    from quantbt.optimization.meta_selection.reactive_execution import OriginalReactiveWitnessExecutor
    from tests.test_phase76_reactive_wfo import _worker_fixture, _TaskStrategy
    import time

    runtime, old, marker = _worker_fixture()
    old.close()
    executor = OriginalReactiveWitnessExecutor(adapter=runtime._adapter,
        prepared_runner=runtime._prepared_runner, data=runtime.data, trading_days=365)

    class Corruptor:
        def __init__(self, connection, change):
            self.connection, self.change = connection, change

        def poll(self, timeout):
            return self.connection.poll(timeout)

        def close(self):
            return self.connection.close()

        def recv(self):
            reply = self.connection.recv()
            if self.change == "missing":
                reply.pop("request_id")
            elif self.change == "generation":
                reply["generation"] -= 1
            elif self.change == "duplicate":
                reply["request_id"] -= 1
            else:
                reply["witness"]["scores"].pop()
            return reply

    try:
        for change in ("missing", "generation", "duplicate", "truncated"):
            worker = ForkReactiveWfoWorkerV1(adapter=runtime._adapter,
                prepared_runner=runtime._prepared_runner, trading_days=365,
                parallelism_plan=runtime._parallelism_plan, max_inflight_tasks=1, metric_executor=executor)
            try:
                worker._start()
                worker._response_connection = Corruptor(worker._response_connection, change)
                with pytest.raises((MetaRecordError, ReactiveWfoWorkerError)):
                    worker.score(marker, canceled=lambda: False, witness_binding=executor.binding(marker))
                assert worker._process is None
            finally:
                worker.close()
        # The original witness path must enforce the budget inside the child.
        with pytest.MonkeyPatch.context() as patch:
            original = _TaskStrategy.on_bar_close

            def slow(self, context, out):
                time.sleep(.005)
                return original(self, context, out)

            patch.setattr(_TaskStrategy, "on_bar_close", slow)
            with pytest.raises(RuntimeBudgetError):
                execute("shadow", runtime_config=ReactiveWfoRuntimeConfigV1(worker_mode="process",
                    runtime_budget=RuntimeBudgetV1(max_wall_time_ms=1)))
    finally:
        executor.close()
        runtime.close()
    import multiprocessing

    assert not multiprocessing.active_children()
    print("c02-bad-replies-ok")


def test_c02_t01_t04_stale_missing_corrupt_replies_and_child_deadline():
    result = subprocess.run([sys.executable, "-c",
        "from tests.meta_selection.test_c02_transport import _bad_replies; _bad_replies()"],
        env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1"),
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "c02-bad-replies-ok" in result.stdout

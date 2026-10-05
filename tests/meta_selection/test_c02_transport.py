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

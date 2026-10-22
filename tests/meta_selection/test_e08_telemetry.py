import sys
from types import SimpleNamespace

import pytest

from quantbt.optimization.meta_selection.telemetry import observed_threads


def test_requested_one_observed_four_is_reported(monkeypatch):
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("NUMBA_NUM_THREADS", "1")
    monkeypatch.setitem(sys.modules, "numba", SimpleNamespace(get_num_threads=lambda: 4))
    row = observed_threads(native_serial=True)
    assert row["configured"]["numba_threads"] == 1
    assert dict(runtime="numba", configured=1, observed=4) in row["mismatches"]
    assert row["observed"]["pool_measurement"] == "pool_capacity_not_active_thread_utilization"


def test_explicit_requested_policy_is_not_replaced_by_environment(monkeypatch):
    monkeypatch.setenv("NUMBA_NUM_THREADS", "1")
    monkeypatch.setitem(sys.modules, "numba", SimpleNamespace(get_num_threads=lambda: 4))
    row = observed_threads(configured={"numba_threads": 4})
    assert row["configured"] == {"numba_threads": 4} and not row["mismatches"]


@pytest.mark.parametrize("value", ("auto", "0", "-1"))
def test_unresolved_environment_is_not_a_fabricated_request(monkeypatch, value):
    monkeypatch.setenv("NUMBA_NUM_THREADS", value)
    row = observed_threads()
    assert "numba_threads" not in row["configured"]
    assert "UNRESOLVED_NUMBA_THREADS_ENVIRONMENT" in row["inspection_limits"]


@pytest.mark.parametrize("backend", ("python", "rust"))
@pytest.mark.parametrize("clock,boundary", (("event_lifecycle_v2_next_bar_close", "bar_close_next_bar_close"),
    ("event_lifecycle_v3_next_open", "bar_close_next_open")))
def test_callback_metadata_comes_from_actual_execution(backend, clock, boundary):
    from dataclasses import replace
    from tests.meta_selection.test_e07_lifecycle import financial, frame
    from quantbt.wfo_execution import WfoExecutionWindow, execute_window
    data = frame()
    child = SimpleNamespace(on_bar_close=lambda context: ())
    config = replace(financial(backend, "event_driven").config, execution_contract=clock)
    out = WfoExecutionWindow("event_driven", data.index, strategy_factory=lambda: child)
    result = execute_window(config, data, out)
    assert result.metadata["wfo_execution_window"]["callback_boundary"] == boundary
    assert result.metadata["wfo_execution_window"]["execution_contract_id"] == clock
    commands = WfoExecutionWindow("order_commands", data.index)
    config = replace(financial(backend, "order_commands").config, execution_contract=clock)
    result = execute_window(config, data, commands)
    assert result.metadata["wfo_execution_window"]["callback_boundary"] == "not_applicable"
    assert result.metadata["wfo_execution_window"]["command_timestamp_semantics"] == "effective_bar"

"""Phase 77.3 resource and prepared-run lifecycle checks."""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from test_phase77_3_reactive_parity import _SparseWire, _endpoint, _frame


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("_quantbt_native") is None,
    reason="quantbt-native extension is not installed in this environment",
)


def test_phase77_3_prepared_scalar_reuses_resettable_hot_state_without_retaining_paths():
    frame = _frame(bars=384)
    endpoint = _endpoint(frame)
    prepared = endpoint.prepare_native_event_strategy(data=frame, symbols=["BTC"])
    runner, _requirements = prepared.prepare_reactive_scalar_score(_SparseWire(), trading_days=365)

    payloads = []
    for _ in range(2):
        runner.reset()
        payloads.append(
            runner.run_scalar_window(
                _SparseWire(),
                start_bar=0,
                end_bar=len(frame),
                gil_policy="release_between_callbacks",
            )
        )

    left, right = payloads
    for key in (
        "score_final_equity",
        "score_total_return_pct",
        "score_sharpe",
        "score_max_drawdown_pct",
        "score_profit_factor",
        "total_fee",
        "total_funding",
        "total_turnover",
    ):
        np.testing.assert_allclose(float(left[key]), float(right[key]), rtol=0.0, atol=1e-10)
    for key in (
        "equity",
        "positions",
        "fees",
        "turnover",
        "funding",
        "command_bar",
        "callback_bar",
        "terminal_active_order_id",
    ):
        assert np.asarray(left[key]).size == 0
        assert np.asarray(right[key]).size == 0
    assert int(left["wake_observation_buffer_allocations"]) == 2
    assert int(right["wake_observation_buffer_allocations"]) == 2
    assert int(left["native_gap_bars"]) == len(frame) - 1
    assert int(right["native_gap_bars"]) == len(frame) - 1

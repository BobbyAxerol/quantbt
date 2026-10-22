"""Runner safety/reconciliation tests; no private alpha or market in fixtures."""

import json

import numpy as np
import pandas as pd
import pytest

from tools.qms_real_review import (
    ACCOUNT, PRIVATE_ROOT, clean, compare_arrays, endpoint_for, extract_alpha,
    private_path, trial_trace, validate_market,
)


def market():
    return pd.DataFrame(
        {"open": [10., 11., 12.], "high": [11., 12., 13.], "low": [9., 10., 11.],
         "close": [10., 11., 12.], "volume": [100., 100., 100.]},
        index=pd.date_range("2020-01-01", periods=3, freq="1h", tz="UTC"),
    )


def test_private_paths():
    assert private_path(PRIVATE_ROOT / "run.json").parent == PRIVATE_ROOT
    with pytest.raises(ValueError):
        private_path(PRIVATE_ROOT / "../../../public.py")


def test_extract_no_notebook_execution(tmp_path):
    cells = [{"source": []} for _ in range(20)]
    cells[7]["source"] = ["import numpy as np\ndef generate_delta_rsi_signals(df, p):\n    return df\n"]
    cells[19]["source"] = ["param_ranges = " + repr({f"p{i}": (1, 3, 1) for i in range(8)})]
    path = tmp_path / "example.ipynb"
    path.write_text(json.dumps({"cells": cells}))
    code, ranges = extract_alpha(path)
    assert len(ranges) == 8 and "return df" in code
    cells[7]["source"].append("print('unexpected side effect')\n")
    path.write_text(json.dumps({"cells": cells}))
    with pytest.raises(ValueError):
        extract_alpha(path)


def test_market_identity_and_gaps():
    frame = market()
    before = validate_market(frame)
    assert before["missing_hours"] == 0
    frame.iloc[-1, frame.columns.get_loc("volume")] += 1
    assert validate_market(frame)["data_sha256"] != before["data_sha256"]
    assert validate_market(frame.iloc[[0, 2]])["missing_hours"] == 1


@pytest.mark.parametrize("problem", ["duplicate", "naive", "nan", "ohlc", "negative"])
def test_invalid_market(problem):
    frame = market()
    if problem == "duplicate":
        frame.index = pd.DatetimeIndex([frame.index[0]] * 3)
    elif problem == "naive":
        frame.index = frame.index.tz_localize(None)
    elif problem == "nan":
        frame.iloc[0, 0] = np.nan
    elif problem == "ohlc":
        frame.iloc[0, frame.columns.get_loc("high")] = 1
    else:
        frame.iloc[0, frame.columns.get_loc("volume")] = -1
    with pytest.raises(ValueError):
        validate_market(frame)


def test_finite_and_undefined_stay_distinct():
    assert clean([np.float64(0), float("nan"), float("inf")]) == [0., "UNDEFINED_NAN", "inf"]


@pytest.mark.parametrize("arm", ["off", "shadow", "active_rust", "active_reference"])
def test_registered_public_route(arm):
    endpoint = endpoint_for(lambda *args: None, arm, "tpe_legacy", 128)
    wf = endpoint.config.walkforward_config
    assert wf.optimization_schedule == "per_fold_causal"
    assert wf.sampler_config.name == "tpe_legacy"
    assert wf.is_subperiods == 1 and wf.optuna_trials == 128
    assert wf.optuna_early_stopping is None
    assert ACCOUNT["fee"] == 0.0005
    if arm != "off":
        assert wf.meta_selection.min_matured_origins == 12
        assert wf.meta_selection.label_observer


def test_array_parity_detects_real_changes(tmp_path):
    arrays = {k: np.ones(3) for k in ("positions", "equity", "returns")}
    left, right = tmp_path / "a.npz", tmp_path / "b.npz"
    np.savez(left, **arrays)
    np.savez(right, **arrays)
    assert all(v == 0 for v in compare_arrays(left, right).values())
    arrays["equity"][1] += .1
    np.savez(right, **arrays)
    with pytest.raises(AssertionError):
        compare_arrays(left, right)


def test_trial_trace_does_not_hide_objective_change():
    one = {"trials": [{"trial_id": 0, "params": {"a": 1}, "objective": 1., "elapsed": 2}]}
    two = {"trials": [{"trial_id": 0, "params": {"a": 1}, "objective": 1., "elapsed": 3}]}
    assert trial_trace(one) == trial_trace(two)
    two["trials"][0]["objective"] = .9
    assert trial_trace(one) != trial_trace(two)

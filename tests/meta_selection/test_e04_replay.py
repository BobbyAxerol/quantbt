"""Saved-param regeneration uses causal history and continuous target stitching."""

from types import SimpleNamespace

import pandas as pd

from tools.qms_e04_replay import SYMBOLS, regenerate_positions


def test_param_regeneration_uses_each_fold_params_and_never_future_history():
    index = pd.date_range("2020-01-01", periods=6, tz="UTC")
    data = {s: pd.DataFrame(dict(close=range(6)), index=index) for s in SYMBOLS}
    folds = [SimpleNamespace(fold_id=0, test_index=index[2:4]),
             SimpleNamespace(fold_id=1, test_index=index[4:6])]
    calls = []

    def alpha(history, params):
        calls.append((history.index[-1], params["window"]))
        return pd.DataFrame(dict(pos_weight=float(params["window"])), index=history.index)

    result = regenerate_positions(data, {"0":dict(window=2), "1":dict(window=3)}, folds,
                                  SimpleNamespace(generate_delta_rsi_signals=alpha))
    assert calls == [(index[3], 2), (index[3], 2), (index[5], 3), (index[5], 3)]
    assert (result.iloc[:2] == 0).all().all()
    assert (result.iloc[2:4] == 2).all().all()
    assert (result.iloc[4:] == 3).all().all()
    assert tuple(result.columns) == SYMBOLS and result.index.equals(index)

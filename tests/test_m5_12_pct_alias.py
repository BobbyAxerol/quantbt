"""Pct spelling aliases must share the corrected activity producer identity."""
import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.endpoint import _WalkForwardEndpointScorer
from quantbt.optimization.meta_selection.observer import canonical_metric_contract


def strategy(data, params, train_index, test_index, fold):
    return pd.Series(np.where(np.arange(len(test_index)) % 11 < 5, 1., 0.), index=test_index)


def endpoint(alias, policy):
    return QuantBTEndpoint.walk_forward(strategy_class=strategy, target_mode=alias,
        split_mode="2020-07-01", split_frequency="quarterly", window_mode="rolling",
        train_window="90D", optimization_mode="mode_4_is_only_robust",
        optuna_trials=2, random_seed=731, target_runtime="rust", initial_capital=20_000.,
        leverage=1., alloc_per_trade=.5, fee=.0008, fee_rate=.0004, slippage=0.,
        optimization_config=dict(scoring_backend="endpoint", native_prepared_wfo=policy,
            scoring_trading_days=365, candidate_selection_metric="is_only_robust", is_subperiods=1))


@pytest.mark.parametrize("alias", ("pct_equity", "%_equity"))
def test_alias_original_scorer_declares_same_accepted_activity(alias):
    bt = endpoint(alias, "off")
    scorer = _WalkForwardEndpointScorer(bt.config, target_mode=alias, symbols=["X"],
        wf_config=bt.config.walkforward_config, meta_metric_support=True)
    assert scorer._meta_adapter.contract == canonical_metric_contract(accepted_contract_units=True)


def test_alias_prepared_wfo_matches_canonical_params_and_account():
    index = pd.date_range("2020-01-01", periods=400, freq="D", tz="UTC")
    close = 100.+np.arange(len(index))*.01+np.sin(np.arange(len(index))*.2)
    data = pd.DataFrame(dict(open=close, high=close+1., low=close-1., close=close, volume=1_000.), index=index)
    results = [endpoint(alias, "require").backtest(data=data, param_ranges={"unused": [1, 2]})
               for alias in ("pct_equity", "%_equity")]
    a, b = results
    pd.testing.assert_series_equal(a.equity, b.equity)
    pd.testing.assert_frame_equal(a.positions, b.positions)
    assert a.full_report() == b.full_report()
    for value in results:
        assert value.metadata["walk_forward"]["native_prepared_wfo"]["resolved_policy"] == "native_prepared"

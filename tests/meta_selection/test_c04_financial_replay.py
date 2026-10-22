"""C04-T05: real endpoint accounting observations are not rerun on restore."""

from dataclasses import replace
from hashlib import sha256

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.optimization import SamplerConfig, metric_from_result
from quantbt.optimization.continuation import ExactStudySession
from tests.meta_selection.test_c04_continuation import BINDING, RECIPES, config
from tools.qms01_baseline import market


@pytest.mark.parametrize("recipe", RECIPES)
def test_c04_t05_current_is_endpoint_metrics_account_and_winner_exact(recipe, monkeypatch):
    frame = market()
    cfg = replace(config(recipe), ranges={
        "window": {"kind": "integer", "low": 3, "high": 21},
        "weight": {"kind": "float", "low": .2, "high": .8}},
        sampler_config=SamplerConfig(name=recipe), duplicate_policy="allow")
    binding = {**BINDING, "market": sha256(frame.to_numpy().tobytes()).hexdigest(),
               "calendar": sha256(frame.index.asi8.tobytes()).hexdigest(),
               "accounting": "pct-equity-20000-leverage3-fee-oneway0005-funding0001-v1"}
    financial_calls = 0
    def evaluate(params):
        nonlocal financial_calls
        financial_calls += 1
        signal = (np.sign(frame.close - frame.close.rolling(params["window"], min_periods=1).mean())
                  * params["weight"])
        bt = QuantBTEndpoint.pct_equity(initial_capital=20_000, leverage=3,
                                        fee_rate=.0005, slippage=.0001,
                                        use_funding=True, funding_rate=.0001,
                                        alloc_per_trade=.5, use_pyramiding=False)
        result = bt.backtest(data=frame, signal=signal)
        value = metric_from_result(result, "sharpe", trading_days=365)
        return value, result
    def advance(session, count):
        for _ in range(count):
            p = session.ask()
            value, _ = evaluate(p.effective)
            session.tell(p.number, value)
    full, partial = (ExactStudySession(cfg, binding=binding) for _ in range(2))
    advance(full, 24)
    advance(partial, 13)
    text, digest = partial.dumps()
    before = financial_calls
    original = QuantBTEndpoint.backtest
    monkeypatch.setattr(QuantBTEndpoint, "backtest", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("checkpoint restore executed financial accounting")))
    resumed = ExactStudySession.loads(text, config=cfg, binding=binding, expected_digest=digest)
    assert financial_calls == before
    monkeypatch.setattr(QuantBTEndpoint, "backtest", original)
    advance(resumed, 11)
    assert financial_calls == 48
    assert resumed.witness() == full.witness()
    _, actual = evaluate(resumed.best_trial.user_attrs["qms_effective"])
    _, expected = evaluate(full.best_trial.user_attrs["qms_effective"])
    for field in ("equity", "returns", "positions"):
        left, right = getattr(actual, field), getattr(expected, field)
        if isinstance(left, pd.DataFrame):
            pd.testing.assert_frame_equal(left, right, check_exact=True)
        else:
            pd.testing.assert_series_equal(left, right, check_exact=True)
    for field in ("orders_report", "fills_report", "positions_report"):
        pd.testing.assert_frame_equal(actual.metadata[field], expected.metadata[field], check_exact=True)
    assert actual.full_report() == expected.full_report()
    assert actual.metadata["use_funding"] is True
    assert actual.metadata["canonical_one_way_fee_rate"] == .0005

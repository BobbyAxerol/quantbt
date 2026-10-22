"""Diagnostic analysis never converts software or IS-only gains into promotion."""

import pytest

from tools.qms_e04_study import ACCOUNT, make_endpoint, paired_analysis


def record():
    return dict(minimum_origins=12, block_months=3, seed=731, resamples=64,
        confidence=.95, sizing="%_equity", portfolio_mode="longshort",
        split_start="2022-01-01", frequency="monthly", train_window="365D",
        attempts_per_fold=128, account=ACCOUNT)


def pairs(n=28, *, q=.2, r=.3):
    return [dict(fold_id=i, start=f"2022-01-{i+1:02d}T00:00:00+00:00",
        end=f"2022-01-{i+2:02d}T00:00:00+00:00", matured_origins=i,
        selected="meta" if i >= 12 else "native", anchor="native",
        native=dict(status="VALID", is_sharpe=2., forward_sharpe=1.),
        meta=dict(status="VALID", is_sharpe=2.+q-r, forward_sharpe=1.+q)) for i in range(n)]


def test_real_diagnostic_positive_r_q_never_promotes_or_claims_locked_oos():
    result = paired_analysis(pairs(), record())
    assert result["supported_valid_origins"] == 16
    assert result["diagnostic_threshold_pass"]
    assert result["changed_decisions"] == 16
    assert result["supported_means"]["r"] == pytest.approx(.3)
    assert result["supported_means"]["q"] == pytest.approx(.2)
    assert result["empirical_promotion"] is False
    assert "LOCKED_EVALUATION_PENDING" in result["status"]


def test_positive_decay_from_lower_is_cannot_certify_forward_improvement():
    result = paired_analysis(pairs(q=-.1, r=.3), record())
    assert result["supported_means"]["r"] > 0
    assert result["supported_means"]["is_difference"] == pytest.approx(.4)
    assert result["supported_means"]["q"] < 0
    assert not result["diagnostic_threshold_pass"]


def test_unsupported_origins_are_not_counted_as_matured_evidence():
    result = paired_analysis(pairs(20), record())
    assert result["supported_valid_origins"] == 8
    assert result["interval"] is None
    assert result["diagnostic_threshold_pass"] is False


def test_undefined_liquidation_windows_are_not_fake_zero_valid_metrics():
    values = pairs()
    values[15]["meta"] = dict(status="UNDEFINED", is_sharpe=None, forward_sharpe=None)
    result = paired_analysis(values, record())
    assert result["valid_folds"] == 27
    assert result["supported_valid_origins"] == 15
    assert result["interval"] is None  # Never compress an interrupted calendar.


def test_real_portfolio_contract_uses_original_account_and_frozen_search():
    endpoint = make_endpoint(lambda **kwargs: None, "active", record())
    config = endpoint.config
    wf = config.walkforward_config
    assert wf.target_mode == "portfolio"
    assert config.backend == "native_portfolio"
    assert config.fee_rate == .00025
    assert config.alloc_per_trade == .25
    assert wf.optuna_trials == 128 and wf.random_seed == 731
    assert wf.optimization_schedule == "per_fold_causal"
    assert wf.metadata["native_prepared_wfo"] == "off"
    assert wf.meta_selection.native_batch_policy == "require"

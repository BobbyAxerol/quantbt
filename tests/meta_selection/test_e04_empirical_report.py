"""Saved diagnostic rendering keeps financial effect, cost and promotion distinct."""

from tools.qms_e04_empirical_report import render


def test_real_portfolio_report_is_explicitly_diagnostic_not_economic_certificate():
    financial = dict(report=dict(final_equity=21000., total_return_pct=5., sharpe=.2,
        max_drawdown_pct=12.), wall_seconds=100., peak_rss_mib=300.)
    text = render(dict(financial=dict(off=financial, active=financial), observer_attempts=42,
        analysis=dict(valid_folds=28, calendar_folds=28, supported_valid_origins=16,
            changed_decisions=0, diagnostic_threshold_pass=False,
            supported_means=dict(native_decay=1., meta_decay=1., r=0., q=0., is_difference=0.))))
    for phrase in ("NOT PROMOTED", "not locked holdout", "symbol-average",
                   "E03-G01", "No push", "128 attempts", "charged separately"):
        assert phrase in text
    assert "100.000 s" in text
    assert "False" in text


def test_zero_supported_origins_remain_undefined_not_zero_gain():
    financial = dict(report=dict(final_equity=20000., total_return_pct=0., sharpe=0.,
        max_drawdown_pct=0.), wall_seconds=1., peak_rss_mib=200.)
    text = render(dict(financial=dict(off=financial, active=financial), observer_attempts=0,
        analysis=dict(valid_folds=0, calendar_folds=28, supported_valid_origins=0,
            changed_decisions=0, diagnostic_threshold_pass=False, supported_means=None)))
    assert "R (native decay minus meta decay): UNDEFINED" in text
    assert "Forward Q (meta minus native Sharpe): UNDEFINED" in text

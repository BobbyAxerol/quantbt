"""M5T-106/108/110: joint quality, non-vacuous controls and scoped inference."""
from dataclasses import replace
import numpy as np
import pytest

from tools.mode5_economics import paired_economics
from economics_fixtures import path, protocol, returns


def contrast(dev_base,dev_new,fwd_base,fwd_new,**kw):
    return paired_economics(path(dev_base),path(dev_new,vector="challenger"),
        path(fwd_base,year=2025),path(fwd_new,year=2025,vector="challenger"),
        protocol=protocol(**kw),origins=1)


def test_lower_is_alone_cannot_pass_joint_forward_gate():
    values=returns()
    row=contrast(values+.001,values-.001,values,values)
    assert row["observed"]["decay_change"] < 0
    assert row["observed"]["forward_mean_net_change"] == 0
    assert row["status"] == "NEGATIVE_WITHIN_REGISTERED_SCOPE"
    assert row["lower_is_only_does_not_establish_forward_gain"]


def test_capable_positive_control_and_harmful_control():
    values=returns()
    improved=contrast(values,values,values,values+.001)
    harmful=contrast(values,values,values,values-.001)
    assert improved["status"] == "POSITIVE_WITHIN_REGISTERED_SCOPE"
    assert harmful["status"] == "NEGATIVE_WITHIN_REGISTERED_SCOPE"
    assert improved["observed"]["forward_mean_net_change"] == pytest.approx(.001)
    assert not improved["whole_procedure_validation"]


def test_interval_crossing_hurdle_is_inconclusive_without_retuning():
    values=returns()
    result=contrast(values,values,values,values+.00005+.003*np.sin(np.arange(len(values))*.035))
    lo,hi=result["intervals"]["forward_mean_net_change"]
    assert lo < .00005 < hi
    assert result["status"] == "INCONCLUSIVE"


def test_paired_common_shocks_cancel_exactly_and_seed_replay_is_identical():
    values=returns()
    a=contrast(values,values,values,values+.001)
    b=contrast(values,values,values,values+.001)
    assert a==b
    np.testing.assert_allclose(a["intervals"]["forward_mean_net_change"],[.001,.001],rtol=0,atol=1e-15)
    assert a["marginal_confidence"] == .998


def test_undefined_sr_draws_are_not_conditioned_on_survivors():
    zeros=np.zeros(365)
    row=contrast(zeros,zeros,zeros,zeros+.001)
    assert row["status"] == "INCONCLUSIVE" and row["invalid_draws"] == 64
    assert row["intervals"]["forward_sharpe_change"] is None
    assert row["intervals"]["forward_mean_net_change"] == pytest.approx((.001,.001))


def test_missing_ledger_or_required_origins_cannot_be_pooled_away():
    values=returns()
    row=paired_economics(path(values,fills=None,campaigns=None),path(values,vector="challenger"),
        path(values,year=2025),path(values+.001,year=2025,vector="challenger"),
        protocol=protocol(minimum_origins=3),origins=1)
    assert row["status"] == "INCONCLUSIVE"
    assert {g["field"] for g in row["support"]["gaps"]} == {"fills","campaigns","qualified_origins"}
    with pytest.raises(ValueError,match="one origin"):
        paired_economics(path(values),path(values,vector="challenger"),path(values,year=2025),
            path(values+.001,year=2025,vector="challenger"),protocol=protocol(),origins=3)


def test_accounting_invalid_is_not_scientific_no_selection():
    values=returns()
    row=paired_economics(path(values,accounting_verified=False),path(values,vector="challenger"),
        path(values,year=2025),path(values,year=2025,vector="challenger"),protocol=protocol(),origins=1)
    assert row["status"] == "INVALID_NOT_EVALUABLE"
    assert row["intervals"] is None


def test_misaligned_calendar_and_changed_vector_raise_not_interpolate():
    values=returns()
    with pytest.raises(ValueError,match="same calendar"):
        paired_economics(path(values),path(values[:-1],vector="challenger"),path(values,year=2025),
            path(values,year=2025,vector="challenger"),protocol=protocol(),origins=1)
    with pytest.raises(ValueError,match="fixed vector"):
        paired_economics(path(values),path(values,vector="challenger"),path(values,year=2025,vector="changed"),
            path(values,year=2025,vector="challenger"),protocol=protocol(),origins=1)

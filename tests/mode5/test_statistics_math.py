"""Original-frequency and mass-tail identities, independent of private alphas."""

from dataclasses import replace
from fractions import Fraction
import json
import math

import numpy as np
import pytest

from tools.mode5_statistics.contracts import StatisticsPolicy, annual_rf_to_period, converted_return
from tools.mode5_statistics.moments import MomentEstimate, classical_psr, moments, ordinary_kurtosis, sharpe_to_period
from tools.mode5_statistics.tails import FrozenReference, expected_shortfall, lower_tail, regret, weighted_mad, weighted_median
from tests.mode5.statistics_oracle import central_reference


def gaussian_summary(sr, n=43):
    return MomentEstimate(n=n, mean=sr, variance=1., sharpe_period=sr, skew=0., kurtosis_ordinary=3.)


def test_m5t_021_original_frequency_psr_and_explicit_annual_conversion():
    sr = sharpe_to_period(1., source_frequency="annual", annual_periods=365)
    assert classical_psr(gaussian_summary(sr)).value == pytest.approx(.6326896240940183, abs=1e-12)
    assert classical_psr(gaussian_summary(1.)).value > .999999
    annual = replace(gaussian_summary(1.), sr_frequency="annual")
    assert classical_psr(annual).status == "INVALID" and classical_psr(annual).value is None
    with pytest.raises(TypeError, match="typed"):
        classical_psr(1.)
    assert classical_psr(gaussian_summary(sr), reference_period=sr).value == .5
    assert classical_psr(gaussian_summary(0.)).value == .5
    assert classical_psr(gaussian_summary(.05, 400)).value > classical_psr(gaussian_summary(.05, 40)).value


def test_m5t_022_ordinary_excess_explicit_and_same_series_moments():
    ordinary = ordinary_kurtosis(0., convention="excess")
    assert ordinary == ordinary_kurtosis(3., convention="ordinary")
    row = gaussian_summary(.1, 100)
    assert classical_psr(replace(row, kurtosis_ordinary=ordinary)).value == classical_psr(row).value
    assert classical_psr(replace(row, kurtosis_ordinary=0.)).status == "INVALID"
    assert classical_psr(replace(row, kurtosis_ordinary=9.)).value < classical_psr(row).value
    with pytest.raises(ValueError, match="convention"):
        ordinary_kurtosis(0., convention="automatic")


@pytest.mark.parametrize("backend", ["python", "numba"])
@pytest.mark.parametrize("scale", [1., 2., 1e-100, 1e100])
def test_central_moment_independent_decimal_and_scale_oracle(backend, scale):
    data = np.array([.01, -.004, .005, -.002, 0., .03, -.012])*scale
    expected = central_reference(data)
    observed = moments(data, backend=backend)
    assert observed.status == "VALID"
    assert (observed.mean, observed.variance, observed.sharpe_period, observed.skew,
            observed.kurtosis_ordinary) == pytest.approx(expected, rel=1e-11, abs=0.)
    assert observed.sharpe_period == pytest.approx(moments(data/scale).sharpe_period, abs=1e-12)


@pytest.mark.parametrize("values,status", [([], "INSUFFICIENT"), ([1., 2.], "INSUFFICIENT"),
    ([0., 0., 0.], "UNDEFINED"), ([1., np.nan, 0.], "INVALID"), ([1., np.inf, 0.], "INVALID"),
    ([1e308, -1e308, 0.], "INVALID")])
def test_m5t_023_invalid_support_variance_nonfinite_no_favorable_fallback(values, status):
    observed = moments(values)
    value = classical_psr(observed)
    assert observed.status == value.status == status
    assert value.value is None and value.reason
    json.dumps(value.to_metadata(), allow_nan=False)


def test_m5t_023_denominator_moment_units_and_sample_guards():
    row = gaussian_summary(1.)
    den_zero = replace(row, skew=2., kurtosis_ordinary=5.)
    assert classical_psr(den_zero).status == "UNDEFINED"
    assert "variance approximation" in classical_psr(den_zero).reason
    for invalid in (replace(row, n=2), replace(row, n=43.5), replace(row, n=True)):
        assert classical_psr(invalid).value is None
    for invalid in (replace(row, variance=0.), replace(row, skew=math.inf),
                    replace(row, population="closed_campaign_pnl")):
        assert classical_psr(invalid).value is None


def test_m5t_028_fractional_mass_is_not_interpolated_quantile():
    # Independent probability ledger uses exact rational masses.
    expected = (Fraction(1, 5)*0 + Fraction(3, 10)*10)/Fraction(1, 2)
    result = lower_tail([0., 10.], .5, weights=[.2, .8])
    assert result.value == float(expected) == 6.
    assert dict(result.components)["consumed_mass"] == .5
    x = [.01, .90, .91, .92]
    assert lower_tail(x, .25).value == .01
    assert np.quantile(x, .25, method="linear") == pytest.approx(.6775)
    assert lower_tail(x, 1.).value == pytest.approx(np.mean(x))
    assert lower_tail(np.asarray(x)+7, .4).value == pytest.approx(lower_tail(x, .4).value+7)
    assert lower_tail([100., 0., 10.], .5, weights=[0., .2, .8]).value == 6.
    assert dict(lower_tail([100., 0., 10.], .5, weights=[0., .2, .8]).components)["positive_weight_observations"] == 2
    assert lower_tail([0., 10.], 1e-16, weights=[.2, .8]).value == 0.


def test_upper_loss_es_sign_and_weighted_median_tie_are_explicit():
    assert expected_shortfall([0., 10.], .5, weights=[.8, .2]).value == 4.
    assert expected_shortfall([-.01, -.02], .5).value == -.01
    assert weighted_median([0., 10.]).value == 0.
    assert weighted_mad([0., 10.]).value == 0.
    assert weighted_median([0., 10.], weights=[.2, .8]).value == 10.
    assert lower_tail([0., 10.], .5, weights=[1e308, 1e308]).value == 0.
    assert lower_tail([-1e308, 1e308], 1.).value == 0.


@pytest.mark.parametrize("values,alpha,weights", [([], .5, None), ([1., math.nan], .5, None),
    ([1., 2.], 0., None), ([1., 2.], 1.1, None), ([1., 2.], .5, [0., 0.]),
    ([1., 2.], .5, [-1., 1.]), ([1., 2.], .5, [1.]), ([1., 2.], .5, [math.inf, 1.])])
def test_tail_bad_support_never_drops_invalid_environment(values, alpha, weights):
    result = lower_tail(values, alpha, weights=weights)
    assert result.status == "INVALID" and result.value is None and result.reason


def test_frozen_regret_retains_components_and_reference_revision():
    ref = FrozenReference("panel", ("a", "b", "c"), (3., 4., 3.), (1., 1., 1.), "utility", "r1")
    values = (1., 4., 2.)
    row = regret(values, environment_ids=ref.environment_ids, channel="utility", reference=ref)
    assert row["components"] == (2., 0., 1.)
    assert row["weighted_mean"] == 1. and row["maximum"] == 2.
    assert ref.identity != replace(ref, revision="r2").identity
    assert ref.identity != replace(ref, values=(3., 4., 4.)).identity
    with pytest.raises(ValueError, match="channel"):
        regret(values, environment_ids=ref.environment_ids, channel="probability", reference=ref)
    with pytest.raises(ValueError, match="roster"):
        regret(values, environment_ids=("b", "a", "c"), channel="utility", reference=ref)
    u = np.array([[1., 4., 2.], [3., 2., 1.], [2., 3., 3.]])
    original = u.min(1)-.25*(np.asarray(ref.values)-u).mean(1)
    reduced = u.min(1)+.25*u.mean(1)-.25*np.mean(ref.values)
    np.testing.assert_allclose(original, reduced, atol=1e-12, rtol=0.)


def test_risk_free_and_return_account_effect_units():
    assert converted_return(1., source_unit="percent") == converted_return(100., source_unit="bps") == .01
    rf = annual_rf_to_period(.05, 365)
    assert math.expm1(365*math.log1p(rf)) == pytest.approx(.05, abs=1e-14)
    assert .0004*2000. == .8
    account_effect = converted_return(10., source_unit="bps")*.064*(2000./20000.)
    assert account_effect*1e4 == pytest.approx(.064, abs=1e-12)
    values = [.01, -.004, .005, -.002]
    policy = StatisticsPolicy(risk_free_per_period=rf)
    assert moments(values, policy=policy).sharpe_period == pytest.approx(
        np.mean(np.asarray(values)-rf)/np.std(values, ddof=1))
    with pytest.raises(ValueError):
        annual_rf_to_period(-1., 365)

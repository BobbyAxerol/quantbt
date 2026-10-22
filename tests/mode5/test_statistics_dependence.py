from dataclasses import replace

import numpy as np
import pytest

from tools.mode5_statistics.dependence import HACPolicy, sharpe_hac
from tools.mode5_statistics.moments import classical_psr, moments
from tools.mode5_statistics.uncertainty import BlockPolicy, moment_intervals
from tests.mode5.statistics_oracle import hac_matrix_reference


@pytest.mark.parametrize("bandwidth", [0, 1, 5])
def test_m5t_025_hac_matches_independent_raw_gradient_toeplitz_matrix(bandwidth):
    values = np.random.default_rng(731).normal(.002, .01, 64)
    result = sharpe_hac(values, policy=HACPolicy(bandwidth=bandwidth))
    expected_sr, expected_se, expected_lrv = hac_matrix_reference(values, bandwidth)
    components = dict(result.components)
    assert result.status == "VALID"
    assert components["sr_population_period"] == pytest.approx(expected_sr, abs=1e-12)
    assert components["standard_error"] == pytest.approx(expected_se, abs=1e-12)
    assert components["long_run_variance"] == pytest.approx(expected_lrv, abs=1e-12)


def test_m5t_025_same_marginal_dependence_and_negative_dependence_controls():
    clustered = np.r_[np.ones(32)*-.01, np.ones(32)*.01]
    alternating = np.tile([-.01, .01], 32)
    shuffled = np.random.default_rng(731).permutation(clustered)
    assert classical_psr(moments(clustered)).value == pytest.approx(.5, abs=1e-12)
    assert classical_psr(moments(alternating)).value == pytest.approx(.5, abs=1e-12)
    one = dict(sharpe_hac(clustered).components)
    two = dict(sharpe_hac(shuffled).components)
    three = dict(sharpe_hac(alternating).components)
    assert one["standard_error"] > two["standard_error"] > three["standard_error"]
    iid_se = dict(sharpe_hac(alternating, policy=HACPolicy(bandwidth=0)).components)["standard_error"]
    assert three["standard_error"] < iid_se
    for data in (clustered, shuffled, alternating):
        expected = hac_matrix_reference(data, 5)
        assert dict(sharpe_hac(data).components)["standard_error"] == pytest.approx(expected[1], abs=1e-12)


@pytest.mark.parametrize("values,status", [([], "INSUFFICIENT"), ([0.]*64, "UNDEFINED"),
    ([np.nan]*64, "INVALID"), ([np.inf]*64, "INVALID")])
def test_hac_invalid_inputs_and_policy(values, status):
    result = sharpe_hac(values)
    assert result.status == status and result.value is None and result.reason


def test_fixed_path_block_intervals_exact_chunk_rng_and_input_immutability():
    values = np.random.default_rng(731).normal(.001, .01, 91)
    original = values.copy()
    first = moment_intervals(values)
    second = moment_intervals(values, policy=replace(BlockPolicy(), chunk_size=1))
    assert first["status"] == second["status"] == "VALID"
    assert first["intervals"] == second["intervals"]
    assert first["effective_draws"] == 256 and first["invalid_draws"] == 0
    np.testing.assert_array_equal(values, original)
    assert moment_intervals(values[:12])["status"] == "INSUFFICIENT"


def test_invalid_bootstrap_draws_are_retained_not_conditioned_away():
    values = np.zeros(32)
    values[0] = .1
    result = moment_intervals(values, policy=BlockPolicy(block_length=1))
    assert result["status"] == "UNAVAILABLE" and result["invalid_draws"] > 0
    assert result["intervals"] is None


def test_policy_identity_no_automatic_bandwidth_or_ess():
    values = np.linspace(-.01, .02, 64)
    first = sharpe_hac(values, policy=HACPolicy(bandwidth=1))
    second = sharpe_hac(values, policy=HACPolicy(bandwidth=5))
    assert dict(first.components)["policy_identity"] != dict(second.components)["policy_identity"]
    with pytest.raises(NotImplementedError):
        HACPolicy(small_sample="ESS")
    with pytest.raises(ValueError):
        HACPolicy(bandwidth=32)


def test_extreme_reference_or_interval_is_typed_invalid_not_probability_one():
    values = np.tile([-.01, .01], 32)
    result = sharpe_hac(values, reference_period=1e308)
    assert result.status == "INVALID" and result.value is None
    result = sharpe_hac(values, policy=HACPolicy(confidence=np.nextafter(1., 0.)))
    assert result.status == "INVALID" and result.value is None

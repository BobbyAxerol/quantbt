"""Zero-variance Sharpe is not valid forward improvement evidence."""

from types import SimpleNamespace
import pytest

from quantbt.optimization.meta_selection.records import OutcomeStatus
from tools.qms_execution_study import paired_metrics


def observations():
    return [SimpleNamespace(status=OutcomeStatus.VALID, raw_sharpe=s) for s in (2., 1., 1.8, 1.2)]


def test_valid_paired_R_Q_have_independent_expected_values():
    out = paired_metrics(observations())
    assert out["R"] == pytest.approx(.4)
    assert out["Q"] == pytest.approx(.2)


@pytest.mark.parametrize("status", (OutcomeStatus.NO_VARIANCE, OutcomeStatus.CENSORED,
                                     OutcomeStatus.OUTCOME_FAILED, OutcomeStatus.INSUFFICIENT_SAMPLE))
def test_invalid_zero_or_failed_forward_cannot_count_as_improvement(status):
    values = observations()
    values[-1] = SimpleNamespace(status=status, raw_sharpe=0.)
    assert paired_metrics(values) is None

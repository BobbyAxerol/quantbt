from types import SimpleNamespace

import numpy as np
import pytest

from tools.meta_model_research.decision_analysis import (
    raw_effect,
    worst_fraction,
    summarize,
    block_intervals,
)
from tools.meta_model_research.decision_queries import independent_daily


def test_raw_is_forward_identity_and_lower_is_failure():
    actual = raw_effect(2.0, 0.0, 1.0, 0.8)
    assert actual["R"] == pytest.approx(1.8)
    assert actual["Q"] == pytest.approx(-0.2)
    assert actual["R"] == pytest.approx(actual["IS_contribution"] + actual["Q"])


def test_fractional_tail_is_empirical_mass_not_percentile():
    assert worst_fraction([-9, 1, 2, 3, 4], 0.3) == pytest.approx((-9 + 0.5) / 1.5)
    assert worst_fraction([1, 2, 3], 1.0) == 2.0


def test_unchanged_fold_included_unknown_never_zero_and_activity_not_fills():
    base = dict(
        model_status="META_MODEL_PROPOSAL",
        changed_id=True,
        changed_effective=True,
        month="2024-02",
        selected_prediction=dict(qhat=0.3),
        measurement_status="VALID",
    )
    rows = [
        dict(base, effect=dict(R=1.0, Q=0.5, IS_contribution=0.5)),
        dict(base, effect=dict(R=0.2, Q=-0.5, IS_contribution=0.7)),
        dict(
            base,
            changed_id=False,
            changed_effective=False,
            effect=dict(R=0.0, Q=0.0, IS_contribution=0.0),
        ),
        dict(base, measurement_status="NO_VARIANCE", effect=None),
    ]
    s = summarize(rows)
    assert (s["origins"], s["observed"], s["changed_unknown"]) == (4, 3, 1)
    assert (s["helped"], s["hurt"], s["tied"]) == (1, 1, 1)
    assert s["all_observed"]["mean_R"] == pytest.approx(0.4)
    assert s["guard"]["accepted_realized_Q_negative"] == 1
    assert s["guard"]["accepted_realized_Q_below_minus_0_1"] == 1
    assert s["changed_observed"]["mean_R"] == pytest.approx(0.6)


def contrast(constant, missing=False):
    import pandas as pd

    return dict(
        observed=31 if missing else 32,
        rows=[
            dict(
                month=str(m),
                valid=not (missing and i == 4),
                deltaR=constant if not (missing and i == 4) else None,
                deltaQ=-constant if not (missing and i == 4) else None,
            )
            for i, m in enumerate(pd.period_range("2024-02", "2026-09", freq="M"))
        ],
    )


def test_shared_blocks_constant_case_and_fixed_multiplicity():
    c = contrast(0.25)
    result = block_intervals({"a": c, "b": contrast(0.25, missing=True)})
    assert result["a"]["coordinates"] == 16
    assert result["a"]["deltaR"] == dict(mean=0.25, lower=0.25, upper=0.25)
    assert result["b"]["status"] == "INCONCLUSIVE_INCOMPLETE_CALENDAR"
    assert "deltaR" not in result["b"]


def test_wrong_or_compressed_calendar_rejected():
    c = contrast(0.0)
    c["rows"][3]["month"] = "2026-12"
    with pytest.raises(ValueError, match="calendar"):
        block_intervals({"a": c})


def test_independent_daily_oracle_uses_close_marks_excludes_first_day():
    import pandas as pd

    eq = pd.Series(
        [100.0, 101.0, 105.0, 102.0, 108.0, 110.0],
        index=pd.date_range("2024-01-01", periods=6, freq="12h", tz="UTC"),
    )
    r = np.array([(102 - 101) / 101, (110 - 102) / 102])
    obs = SimpleNamespace(
        sample_count=2, raw_sharpe=float(r.mean() / r.std(ddof=1) * np.sqrt(365))
    )
    result = independent_daily(SimpleNamespace(equity=eq), obs)
    assert result["sample_count"] == 2
    assert result["raw_sharpe"] == pytest.approx(obs.raw_sharpe)
    with pytest.raises(ValueError, match="daily"):
        independent_daily(
            SimpleNamespace(equity=eq),
            SimpleNamespace(sample_count=2, raw_sharpe=123.0),
        )

"""Pilot and immutable scientific entry rights; no history outcome reads."""

from copy import deepcopy

import pytest

from tools.meta_model_research.protocol import GROUPS
from tools.meta_model_research.screening import pilot_forecast


def points():
    return [
        dict(group=g, code=c, K=12, wall_seconds=0.2)
        for g in GROUPS
        for c in ("B1", "H135", "X3")
    ]


def test_complete_family_pilot_forecast_before_scale():
    result = pilot_forecast(points(), elapsed_cpu=100)
    assert result["remaining_upper_seconds"] == pytest.approx(96)
    assert result["status"] == "ADMITTED"
    for invalid in (
        points()[:-1],
        [dict(p, K=11) for p in points()],
        [dict(p, wall_seconds=0) for p in points()],
    ):
        with pytest.raises(ValueError, match="twelve"):
            pilot_forecast(invalid, elapsed_cpu=0)
    with pytest.raises(RuntimeError, match="NOT_ADMITTED"):
        pilot_forecast([dict(p, wall_seconds=20) for p in points()], elapsed_cpu=0)
    duplicate = deepcopy(points())
    duplicate[-1] = duplicate[-2]
    with pytest.raises(ValueError, match="twelve"):
        pilot_forecast(duplicate, elapsed_cpu=0)

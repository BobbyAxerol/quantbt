"""Presentation-only cost disclosure; never run a benchmark or optimizer."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


@pytest.mark.parametrize("repeats", (1, 7))
def test_single_observation_does_not_look_like_an_estimated_tail(repeats):
    root = Path(__file__).resolve().parents[1]
    spec = spec_from_file_location("m512_benchmark_reporting", root/"benchmarks/native_event/benchmark_phase77_2_pct_equity_wfo.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = dict(profile=dict(bars=720, frequency="1D", split_frequency="quarterly", trials=4, repeats=repeats),
        paired_result=dict(reference=dict(timing_seconds=dict(median=.7, p95=.9), native_score_rows=0),
            native=dict(timing_seconds=dict(median=.1, p95=.2), native_score_rows=42)))
    text = module._markdown(payload)
    assert "accepted contract units" in text
    if repeats == 1:
        assert "Single Observation" in text and "UNAVAILABLE (n=1)" in text
        assert "| P95 |" not in text and "Paired speedup:" not in text
        assert "no p50/p95 inference or general speedup claim" in text
    else:
        assert "| Median | P95 |" in text and "0.900000 s" in text

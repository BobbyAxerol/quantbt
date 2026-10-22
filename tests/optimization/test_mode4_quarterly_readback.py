import pytest

from tools.mode4_quarterly.readback import summarize_alpha_controls


def fixture():
    return [dict(alpha="A-HMA",activity=activity,stop=stop,repeat=repeat,
        status="PASS_FIXED_CONTROL_TIMING_NOT_FULL_STUDY",role="is",no_optimizer=True,
        scored_bars=8760,scored_days=365,elapsed_seconds=5.,peak_rss_mib=400.,
        includes_preparation=True,research_source="fixture",market="fixture",
        original_params_source="private")
        for activity in ("low","high") for stop in ("2022-01-01","2026-01-01")
        for repeat in (0,1)]


def test_readback_is_not_economics_or_phase_completion():
    result=summarize_alpha_controls(fixture(),native_sha256="a"*64)
    assert result["status"] == "REJECT_PARTIAL_SEARCH_FORECAST_EXCEEDS_CAP"
    assert result["median_search_sensitivity_seconds"] == 6080.
    assert result["optimizer_calls"] == result["meta_fits"] == 0
    assert not result["phase_complete"]
    assert "private" not in str(result)


def test_source_digest_required():
    with pytest.raises(ValueError):
        summarize_alpha_controls(fixture(),native_sha256="unverified")


def test_missing_or_duplicate_stratum_cannot_pass():
    rows=fixture()
    rows[-1]=rows[0]
    with pytest.raises(ValueError):
        summarize_alpha_controls(rows,native_sha256="a"*64)


def test_shortened_horizon_cannot_pass():
    rows=fixture()
    rows[-1]["scored_bars"]=100
    with pytest.raises(ValueError):
        summarize_alpha_controls(rows,native_sha256="a"*64)


def test_failed_control_cannot_be_silently_averaged():
    rows=fixture()
    rows[0]["status"]="FAIL_RETAINED"
    with pytest.raises(ValueError):
        summarize_alpha_controls(rows,native_sha256="a"*64)

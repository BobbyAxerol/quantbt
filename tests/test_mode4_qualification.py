"""M4X-06/09 public arithmetic/calendar and fail-closed launch contract fixtures."""

import ast
from collections import Counter
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.mode4_qualification import Mode4Protocol, build_windows, measure_pair, paired_report, phase_registration


def observation(value=1.0, **changes):
    return dict(raw_sharpe=value, status="VALID", sample_std=0.1, sample_count=30,
                metric_contract_id="synthetic-raw-sharpe", economics_id="synthetic-original", **changes)


def pair(ni=2.0, nf=0.5, mi=1.5, mf=0.75):
    return dict(zip(("native_is", "native_forward", "meta_is", "meta_forward"),
                    (observation(v) for v in (ni, nf, mi, mf))))


def test_frozen_protocol_counts_and_complete_calendar():
    p, windows = Mode4Protocol(), build_windows()
    assert p.alpha_ids == ("A-SC", "A-HMA", "A-HASH", "A-VWAP")
    assert (p.fold_count, p.trials_per_fold, p.seed, p.proposal_slots) == (57, 128, 731, 29184)
    assert p.proposal_slots // 4 == 7296
    assert (p.oos_stop - p.oos_start).days == 1734
    assert p.source_stop == datetime(2026, 10, 6, tzinfo=timezone.utc)
    assert len(windows) == len({w.fold_id for w in windows}) == 57
    assert sum((w.oos_stop - w.oos_start).days for w in windows) == 1734
    assert Counter(w.role for w in windows) == dict(history=13, development=12, evaluation=32)
    assert [windows[i].fold_id for i in (0, 12, 13, 24, 25, 56)] == ["2022-01", "2023-01", "2023-02", "2024-01", "2024-02", "2026-09"]
    with pytest.raises(FrozenInstanceError):
        p.seed = 1
    with pytest.raises(FrozenInstanceError):
        windows[0].is_stop = p.source_stop


def test_all_cutoffs_are_exact_half_open_and_expanding():
    p, windows = Mode4Protocol(), build_windows()
    for i, w in enumerate(windows):
        assert w.is_start == datetime(2020, 1, 1, tzinfo=timezone.utc)
        assert w.information_as_of == w.is_stop == w.oos_start
        assert w.is_start < w.is_stop < w.oos_stop <= p.oos_stop < p.source_stop
        assert w.is_stop - timedelta(microseconds=1) < w.oos_start
        assert w.oos_start.day == w.oos_stop.day == 1
        assert all(d.utcoffset() == timedelta(0) for d in (w.is_start, w.is_stop, w.oos_start, w.oos_stop))
        if i:
            assert windows[i - 1].oos_stop == w.oos_start
            assert windows[i - 1].is_stop < w.is_stop
    assert (windows[0].is_stop - windows[0].is_start).days == 731
    assert (windows[25].oos_stop - windows[25].oos_start).days == 29
    assert windows[-1].oos_stop == p.oos_stop


def test_independent_raw_decomposition_not_penalized_objective():
    inputs = pair()
    for o in inputs.values():
        o["objective"] = -999.0
    before = deepcopy(inputs)
    result = measure_pair("A-HMA", "2024-02", inputs)
    assert result["status"] == "PAIRED_VALID" and result["reasons"] == []
    assert (result["D_native"], result["D_meta"], result["IS_effect"], result["R"], result["Q"]) == (1.5, 0.75, 0.5, 0.75, 0.25)
    assert result["R"] == result["IS_effect"] + result["Q"]
    assert result["identity_residual"] == 0 and inputs == before
    assert result["economic_winner_claim"] is False


@pytest.mark.parametrize("nf,mf,flag", [(0.5, 0.5, "LOWER_IS_ONLY"), (0.5, 0.25, "LOWER_IS_DESPITE_WORSE_FORWARD")])
def test_lower_is_can_reduce_decay_without_forward_improvement(nf, mf, flag):
    result = measure_pair("A-SC", "2024-02", pair(2.0, nf, 1.0, mf))
    assert result["R"] > 0 and result["Q"] <= 0
    assert result["flags"] == [flag] and result["economic_winner_claim"] is False


@pytest.mark.parametrize("changes", [dict(raw_sharpe=None), dict(raw_sharpe=float("nan")), dict(raw_sharpe=float("inf")),
    dict(raw_sharpe=True), dict(raw_sharpe="1"), dict(sample_std=0), dict(sample_std=-1),
    dict(sample_std=None), dict(sample_std=float("nan")), dict(sample_count=1), dict(sample_count=True),
    dict(status="NO_VARIANCE"), dict(status="CENSORED"), dict(status="INCOMPLETE_WINDOW"), dict(status="bogus"),
    dict(metric_contract_id=""), dict(economics_id="different")])
def test_invalid_missing_or_constant_metrics_never_become_zero(changes):
    inputs = pair()
    inputs["meta_forward"].update(changes)
    result = measure_pair("A-HASH", "2024-02", inputs)
    assert result["status"] == "INVALID" and result["reasons"]
    assert all(result[k] is None for k in ("R", "Q", "D_native", "D_meta", "IS_effect", "identity_residual"))


def test_missing_and_valid_zero_effect_have_different_denominators():
    zero = measure_pair("A-VWAP", "2024-02", pair(0, 0, 0, 0))
    assert zero["status"] == "PAIRED_VALID" and zero["R"] == zero["Q"] == 0
    invalid = pair()
    invalid["native_is"]["sample_std"] = 0
    report = paired_report("A-VWAP", {"2024-02": pair(), "2024-04": invalid, "2024-05": pair(0, 0, 0, 0)})
    assert report["counts"] == dict(PAIRED_VALID=2, MISSING=54, INVALID=1)
    assert report["evaluation_pair_mask"] == [True, False, False, True] + [False] * 28
    assert report["evaluation_means"] == dict(R=0.375, Q=0.125, IS_effect=0.25)
    assert report["evaluation_support_limited"] and report["inference"] == "NOT_COMPUTED"
    empty = paired_report("A-SC", {})
    assert empty["counts"] == dict(PAIRED_VALID=0, MISSING=57, INVALID=0)
    assert all(v is None for v in empty["evaluation_means"].values())
    assert empty["economic_winner_claim"] is False


def admission_inputs():
    p, pin = Mode4Protocol(), "a" * 64
    routes = {a: dict(status="PASS", binding_identity=pin, diagnostic_reset_witness=pin, continuous_carry_witness=pin,
        carried_inventory_boundaries=1, actual_route=True, strategy_state_preserved=True,
        pending_orders_preserved=True, event_clock_preserved=True, forced_flatten=False) for a in p.alpha_ids}
    budget = dict(status="MEASURED", measurement_identity=pin, workers=1, proposal_slots=p.proposal_slots,
        includes_auxiliary_work=True, horizon_witnesses={a: {h: pin for h in ("2022-01", "2024-01", "2026-09")} for a in p.alpha_ids},
        p50_seconds=1.0, p95_seconds=2.0, forecast_seconds=30000.0, wall_limit_seconds=40000.0,
        measured_peak_rss_bytes=1024**3, forecast_peak_rss_bytes=1024**3, rss_limit_bytes=2 * 1024**3,
        available_ram_bytes=4 * 1024**3, measured_peak_disk_bytes=1024, forecast_scratch_bytes=64 * 1024**2,
        forecast_retained_bytes=32 * 1024**2, free_disk_bytes=6 * 1024**3, thread_limit=1)
    return routes, budget


def test_generic_pass_and_one_alpha_pass_do_not_admit_financial_launch():
    assert not phase_registration()["long_launch_admitted"]
    routes, budget = admission_inputs()
    assert phase_registration(route_witnesses=routes, budget=budget)["long_launch_admitted"]
    generic = {a: dict(status="PASS") for a in Mode4Protocol().alpha_ids}
    result = phase_registration(route_witnesses=generic, budget=budget)
    assert not result["long_launch_admitted"] and len(result["blockers"]) == 4
    result = phase_registration(route_witnesses={"A-SC": routes["A-SC"]}, budget=budget)
    assert not result["long_launch_admitted"] and len(result["blockers"]) == 3
    assert not phase_registration(route_witnesses=routes, budget=dict(status="PASS"))["long_launch_admitted"]


@pytest.mark.parametrize("alpha", Mode4Protocol().alpha_ids)
@pytest.mark.parametrize("field,value", [("continuous_carry_witness", None), ("carried_inventory_boundaries", 0),
    ("actual_route", False), ("strategy_state_preserved", False), ("pending_orders_preserved", False),
    ("event_clock_preserved", False), ("forced_flatten", True)])
def test_each_actual_carry_witness_is_required(alpha, field, value):
    routes, budget = admission_inputs()
    routes[alpha][field] = value
    assert f"{alpha}:ACTUAL_ROUTE_CARRY_NOT_QUALIFIED" in phase_registration(route_witnesses=routes, budget=budget)["blockers"]


@pytest.mark.parametrize("field,value", [("measurement_identity", "PASS"), ("workers", 2), ("proposal_slots", 128),
    ("includes_auxiliary_work", False), ("forecast_seconds", float("nan")), ("p95_seconds", 0.5),
    ("rss_limit_bytes", 8 * 1024**3), ("available_ram_bytes", 1024), ("free_disk_bytes", 5 * 1024**3),
    ("forecast_scratch_bytes", 257 * 1024**2), ("forecast_retained_bytes", 2 * 1024**3)])
def test_unmeasured_or_over_budget_launch_fails(field, value):
    routes, budget = admission_inputs()
    budget[field] = value
    assert not phase_registration(route_witnesses=routes, budget=budget)["long_launch_admitted"]


def test_missing_horizon_and_unregistered_data_fail_closed():
    routes, budget = admission_inputs()
    del budget["horizon_witnesses"]["A-HASH"]["2026-09"]
    assert not phase_registration(route_witnesses=routes, budget=budget)["long_launch_admitted"]
    for alpha, fold in (("A-RSI", "2024-02"), ("A-SC", "2026-10")):
        with pytest.raises(ValueError):
            measure_pair(alpha, fold, pair())
    with pytest.raises(ValueError):
        paired_report("A-SC", {"2026-10": pair()})


def test_tools_remain_stdlib_only_without_private_alpha_imports():
    path = Path(__file__).resolve().parents[1] / "tools" / "mode4_qualification.py"
    tree = ast.parse(path.read_text())
    imports = {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imports.update(a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names)
    assert imports == {"collections", "dataclasses", "datetime", "math"}

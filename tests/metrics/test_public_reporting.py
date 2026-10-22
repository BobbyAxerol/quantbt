from copy import deepcopy
from dataclasses import asdict, fields, is_dataclass, replace
import hashlib
import inspect
import json
from pathlib import Path
import pickle
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint, ReportingCache, ReportingContractV1, ReportingRequest
from quantbt.core.results import BacktestResultV2, BacktestScalarScoreResult, OptionBacktestResult
from quantbt.metrics.reporting.public import build_completed_report, format_reporting_report
from quantbt.metrics.reporting.execution import ExecutionObservations

from .test_account_reducers import policy
from .test_ledger_reducers import ledger, ledger_policy, rows_from_fixture, ledger_coverage
from .test_reporting_conformance import native_payload, mature_public_meta_fixture


ROOT = Path(__file__).resolve().parents[2]


def raw(cls=BacktestResultV2):
    idx = pd.date_range("2025-01-01", periods=4, freq="h", tz="UTC")
    return cls(equity=pd.Series([90., 95., 100., 90.], index=idx),
        returns=pd.Series([-.1, 1/18, 1/19, -.1], index=idx),
        positions=pd.DataFrame({"Position_ETH": [1., 1., 0., 1.]}, index=idx),
        closes=pd.DataFrame({"Close_ETH": [100., 105., 110., 100.]}, index=idx),
        initial_capital=100., symbols=["ETH"], fees=pd.Series([1., 0., 1., 1.], index=idx))


def request(result, **kwargs):
    idx = result.equity.index
    return ReportingRequest(account=replace(policy([int(idx[0].value), int(idx[-1].value)]), sampling="observed_bar"),
        result_identity="public-completed", partial_mask=(False,) * len(idx), return_witness="explicit complete hourly closes", **kwargs)


def metric(report, group, suffix):
    return next(m for m in report["groups"][group]["metrics"] if m["metric_id"] == "reporting." + suffix)


def raw_digest(value):
    # Pandas index memoization is not accounting data and changes pickle bytes.
    def canonical(obj):
        if isinstance(obj, pd.DataFrame):
            return dict(index=canonical(obj.index), columns=canonical(list(obj.columns)), values=canonical(obj.to_numpy()))
        if isinstance(obj, pd.Series):
            return dict(index=canonical(obj.index), name=obj.name, values=canonical(obj.to_numpy()))
        if isinstance(obj, pd.Index):
            return [str(v) for v in obj]
        if isinstance(obj, np.ndarray):
            return dict(dtype=str(obj.dtype), shape=list(obj.shape), bytes=obj.tobytes().hex()) if obj.dtype != object else canonical(obj.tolist())
        if is_dataclass(obj):
            return {f.name: canonical(getattr(obj, f.name)) for f in fields(obj)}
        if isinstance(obj, dict):
            return {str(k): canonical(v) for k, v in obj.items()}
        if isinstance(obj, (tuple, list)):
            return [canonical(v) for v in obj]
        if isinstance(obj, np.generic):
            return canonical(obj.item())
        if isinstance(obj, (str, int, bool, type(None))):
            return obj
        if isinstance(obj, float):
            return obj if np.isfinite(obj) else str(obj)
        return str(obj)
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, allow_nan=False).encode()).hexdigest()


@pytest.mark.parametrize("cls", [BacktestResultV2, OptionBacktestResult])
def test_met03_t01_t05_t07_public_methods_preserve_defaults_raw_and_serialization(cls, capsys):
    result = raw(cls)
    endpoint = QuantBTEndpoint.pct_equity()
    endpoint.result = result
    before = raw_digest(result)
    old = result.full_report(scope="full")
    config = request(result, retain_episodes=True)
    report = endpoint.full_report(reporting=config)
    assert report == result.full_report(reporting=config)
    assert endpoint.show_metrics(reporting=config) == report
    text = capsys.readouterr().out
    assert "Closed Action" in text and "N/A" in text and "h (" in text
    assert "USDT" in text and "observed_bar" in text and "-10.000%" in text
    assert metric(report, "account_period", "drawdown.max_depth")["value"] == pytest.approx(.1)
    assert report["groups"]["closed_trade"]["status"] == "unavailable"
    assert report["groups"]["account_period"]["drawdown_episodes"][-1]["recovery_time_ns"] is None
    assert old == result.full_report(scope="full") == endpoint.full_report(scope="full")
    assert raw_digest(result) == before
    json.dumps(report, allow_nan=False)
    assert asdict(ReportingContractV1.from_metadata(config.account.to_metadata())) == asdict(config.account)
    assert inspect.signature(endpoint.full_report).parameters["reporting"].kind == inspect.Parameter.KEYWORD_ONLY


def test_met03_t01_t03_invalid_request_scope_and_profiles_fail_closed():
    result = raw()
    cfg = request(result)
    with pytest.raises(TypeError):
        result.full_report(reporting={})
    with pytest.raises(NotImplementedError):
        replace(cfg, backend="rust")
    with pytest.raises(TypeError):
        replace(cfg, partial_mask=[False] * 4)
    with pytest.raises(ValueError):
        replace(cfg, return_witness=None)
    with pytest.raises(ValueError, match="owns exact scope"):
        result.full_report(scope="oos", reporting=cfg)
    with pytest.raises(ValueError, match="agree"):
        replace(cfg, ledger_contracts=(ledger_policy(),))
    with pytest.raises(TypeError):
        replace(cfg, retain_episodes=1)
    scalar = BacktestScalarScoreResult(final_equity=90., final_positions=np.array([0.]), metrics={"sharpe": 5.})
    assert scalar.full_report(reporting=cfg)["groups"]["account_period"]["status"] == "unavailable"
    assert scalar.full_report() == {"sharpe": 5.}


def test_met03_t03_t05_explicit_scoped_carry_baseline_ledger_and_coverage():
    result = SimpleNamespace(equity=pd.Series([100., 120., 125., 132.], index=pd.to_datetime([0, 10, 20, 30], utc=True)))
    config = ReportingRequest(account=replace(policy([10, 30], 120.), scope="scoped"), result_identity="executed-outcomes",
        ledger=ledger(rows_from_fixture()), ledger_contracts=(ledger_policy(start=10, scope="scoped", baseline_equity=120.),
        ledger_policy("closed_action", start=10, scope="scoped", baseline_equity=120.)))
    report = build_completed_report(result, config).to_metadata()
    assert metric(report, "account_period", "account.total_return")["value"] == pytest.approx(.1)
    assert metric(report, "closed_trade", "closed_trade.net_pnl")["value"] == -10
    assert metric(report, "closed_action", "closed_action.net_pnl")["value"] == -10
    assert metric(report, "closed_trade", "closed_trade.win_rate")["value"] == .25
    assert metric(report, "closed_action", "closed_action.win_rate")["value"] == pytest.approx(1/3)
    truncated = replace(config, ledger=replace(config.ledger, coverage=ledger_coverage(5, "truncated")))
    assert all(m["status"] == "unavailable" for m in build_completed_report(result, truncated).to_metadata()["groups"]["closed_trade"]["metrics"])
    with pytest.raises(ValueError, match="different completed result"):
        build_completed_report(result, replace(config, result_identity="other"))


@pytest.mark.parametrize("profile", ["score", "compact", "audit"])
def test_met03_t02_t04_t05_native_profiles_scalar_costs_and_no_hidden_materialization(profile):
    from quantbt.core.native_result_v2 import NativeResultV2Adapter
    from quantbt.metrics.reporting.execution import execution_from_native
    adapter = NativeResultV2Adapter(native_payload(profile))
    idx = pd.date_range("2025-01-01", periods=3, freq="h", tz="UTC")
    contract = policy([int(idx[0].value), int(idx[-1].value)])
    cov = replace(ledger_coverage(1, "truncated"), result_identity="native-output")
    execution = execution_from_native(adapter, coverage=cov, currency="USDT", scope_start_ns=int(idx[0].value), scope_end_ns=int(idx[-1].value))
    config = ReportingRequest(account=contract, result_identity="native-output", index=idx, execution=execution)
    old = dict(adapter.metrics)
    report = build_completed_report(adapter, config).to_metadata()
    assert metric(report, "execution", "execution.fill_count")["value"] == 8
    assert report["groups"]["account_period"]["status"] == ("unavailable" if profile == "score" else "available")
    assert adapter.materialized_frames == () and dict(adapter.metrics) == old


def test_met03_t02_t08_public_python_numba_cache_identity_and_mutable_result():
    result = raw()
    with ReportingCache(max_entries=2) as cache:
        config = request(result, cache=cache, retain_episodes=True)
        python = result.full_report(reporting=config)
        numba = result.full_report(reporting=replace(config, backend="numba"))
        assert python["groups"]["account_period"]["metrics"] == numba["groups"]["account_period"]["metrics"]
        assert python["groups"]["account_period"]["drawdown_episodes"] == numba["groups"]["account_period"]["drawdown_episodes"]
        assert result.full_report(reporting=config) == python and cache.hits == 1
        result.equity.iloc[-1] = 80.
        changed = result.full_report(reporting=config)
        assert changed != python and cache.entry_count == 2
        assert metric(changed, "account_period", "account.total_return")["value"] == pytest.approx(-.2)
    assert cache.retained_bytes == 0


def test_met03_t07_plot_episode_status_geometry_and_no_mutation(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    result = raw()
    before = raw_digest(result)
    for theme in ("light", "dark"):
        fig = result.quick_plot(theme=theme, figsize=(12, 7), reporting=request(result))
        fig.canvas.draw()
        assert len(fig.axes) == 2
        assert fig.axes[0].get_ylabel() == "Equity (USDT)"
        assert fig.axes[1].get_ylabel() == "Drawdown (%)"
        assert "Open / censored episode" in fig.axes[1].get_legend_handles_labels()[1]
        boxes = [ax.get_tightbbox(fig.canvas.get_renderer()) for ax in fig.axes]
        assert boxes[0].y0 > boxes[1].y1
        fig.savefig(tmp_path / (theme + ".png"), dpi=100)
        pixels = np.asarray(fig.canvas.buffer_rgba())
        assert pixels.std() > 10
        plt.close(fig)
    assert raw_digest(result) == before


@pytest.mark.parametrize("mode", ["off", "shadow", "active"])
def test_met03_t06_mature_meta_public_report_is_read_only(mode, mature_public_meta_fixture):
    import random
    fixture, history = mature_public_meta_fixture
    _, result, _ = fixture.run(mode, history=history)
    before = fixture.native_digest(result)
    old = result.full_report(scope="full")
    state_python, state_numpy = random.getstate(), np.random.get_state()
    config = request(result)
    result.full_report(reporting=config)
    assert before == fixture.native_digest(result) and old == result.full_report(scope="full")
    assert state_python == random.getstate()
    state = np.random.get_state()
    assert state[0] == state_numpy[0] and np.array_equal(state[1], state_numpy[1]) and state[2:] == state_numpy[2:]
    if mode != "off":
        assert any(r["proposal"].predictions for r in fixture.sidecar(result)["records"])


def test_met03_t09_t10_lazy_public_exports_no_optional_reporting_dependencies():
    code = '''
import sys
import quantbt
assert not any(n.startswith('quantbt.metrics.reporting') for n in sys.modules)
before = set(sys.modules)
from quantbt import ReportingRequest, ReportingContractV1, ReportingCoverageV1, ReportingCache
assert all(n in quantbt.__all__ for n in ('ReportingRequest', 'ReportingContractV1', 'ReportingCoverageV1', 'ReportingCache'))
assert not any(n.split('.')[0] in {'matplotlib', 'quantstats'} for n in set(sys.modules) - before)
'''
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


@pytest.mark.parametrize("route", ["pct_equity", "portfolio", "basket", "arbitrage", "intrabar", "event_driven", "order_commands"])
def test_met03_t04_t05_completed_real_routes_raw_accounting_and_audit_unchanged(route):
    from tests.meta_selection import pre_e06_02_support as shared
    from quantbt.wfo_execution import execute_window
    data = shared.tape(route, end="2020-03-31")
    idx = next(iter(data.values())).index if isinstance(data, dict) else data.index
    endpoint = shared.endpoint(route, data, "off", start="2020-03-01")
    payload = shared.generate(route, data, {"window": 5}, idx)
    if route in shared.execution_routes():
        result = execute_window(endpoint.config.wfo_execution_config, data, payload)
    else:
        mode = route if route in {"portfolio", "basket", "arbitrage"} else "single_signal"
        diagnostic = QuantBTEndpoint(replace(endpoint.config, mode=mode))
        result = diagnostic.backtest(data=data, **({"positions": payload} if route == "portfolio" else {"signal": payload}))
    before = raw_digest(result)
    old = result.full_report(scope="full")
    contract = replace(policy([int(result.equity.index[0].value), int(result.equity.index[-1].value)], result.initial_capital), sampling="observed_bar")
    cfg = ReportingRequest(account=contract, result_identity="real-" + route,
        partial_mask=(False,) * len(result.equity), return_witness="retained complete daily synthetic account")
    report = result.full_report(reporting=cfg)
    assert metric(report, "account_period", "account.final_equity")["value"] == result.equity.iloc[-1]
    assert report["groups"]["closed_action"]["status"] == "unavailable"
    assert before == raw_digest(result) and old == result.full_report(scope="full")
    assert result.positions.to_numpy().any()


def test_met03_t04_t05_actual_w3_reset_flat_results_remain_independent():
    from tests.meta_selection import e07_support
    value = e07_support.run(("reactive_reset", "rust"), "off")
    assert value.result.fold_results
    old = raw_digest(value.result)
    for fold in value.result.fold_results:
        result = fold.result
        cfg = ReportingRequest(account=replace(policy([int(result.equity.index[0].value), int(result.equity.index[-1].value)], result.initial_capital), sampling="observed_bar"),
            result_identity="w3-" + str(fold.task.start_bar), partial_mask=(False,) * len(result.equity),
            return_witness="one recorded reset-flat segment; not continuous carry")
        report = result.full_report(reporting=cfg)
        assert metric(report, "account_period", "account.total_return")["value"] == pytest.approx(result.equity.iloc[-1]/result.initial_capital - 1)
    assert raw_digest(value.result) == old

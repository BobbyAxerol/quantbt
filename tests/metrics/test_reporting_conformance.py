import ast
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt import QuantBTEndpoint
from quantbt.core.native_result_v2 import NativeResultV2Adapter
from quantbt.core.results import BacktestResultV2
from quantbt.metrics.reporting.adapters import account_from_completed
from quantbt.metrics.reporting.account import reduce_independent_segments
from quantbt.metrics.reporting.cache import ReportingCache
from quantbt.metrics.reporting.execution import execution_from_native, reduce_execution
from quantbt.metrics.reporting.ledger import reduce_ledger
from quantbt.optimization.meta_selection.observer import canonical_metric_contract

from .test_account_reducers import coverage, observations, policy, reduce_account
from .test_ledger_reducers import ledger, ledger_coverage, ledger_policy, rows_from_fixture
from .source_guard import assert_protected


ROOT = Path(__file__).resolve().parents[2]


def test_met02_t08_byte_bounded_cache_scope_identity_eviction_release():
    obs = observations([0, 10, 30], [100., 90., 100.])
    contract = policy([0, 10, 30])
    cache = ReportingCache(max_entries=2, max_bytes=1_000_000)
    first = cache.reduce("account", obs, contract, retain_episodes=True)
    assert cache.reduce("account", obs, contract, retain_episodes=True) is first
    assert cache.hits == 1 and cache.misses == 1
    changed = replace(contract, scope="scoped", baseline_equity=110.)
    second = cache.reduce("account", obs, changed, retain_episodes=True)
    assert second is not first and second.contract_identity != first.contract_identity
    altered = observations([0, 10, 30], [100., 80., 100.])
    cache.reduce("account", altered, contract, retain_episodes=True)
    assert cache.entry_count == 2
    assert cache.retained_bytes <= cache.max_bytes
    cache.release(obs.identity)
    assert cache.entry_count == 1
    cache.release(altered.identity)
    assert cache.entry_count == 0 and cache.retained_bytes == 0
    tiny = ReportingCache(max_bytes=1)
    tiny.reduce("account", obs, contract)
    assert tiny.entry_count == 0
    assert not hasattr(cache, "observations")
    cache.close()
    with pytest.raises(RuntimeError, match="closed"):
        cache.reduce("account", obs, contract)
    with ReportingCache() as temporary:
        temporary.reduce("account", obs, contract)
        assert temporary.entry_count == 1
    assert temporary.entry_count == 0 and temporary.closed
    with pytest.raises(AttributeError):
        temporary.max_bytes = 999999


def test_met02_t02_disjoint_accounts_never_invent_stitched_cagr():
    segments = [(observations([0, 10], [100., 90.]), replace(policy([0, 10]), disjoint_scope="independent_segments")),
                (observations([100, 110], [90., 99.]), replace(policy([100, 110], 90.), disjoint_scope="independent_segments"))]
    reports = reduce_independent_segments(segments)
    assert reports[0].metric("account.total_return").value == pytest.approx(-.1)
    assert reports[1].metric("account.total_return").value == pytest.approx(.1)
    with pytest.raises(ValueError, match="declared"):
        reduce_independent_segments([(segments[0][0], replace(segments[0][1], disjoint_scope="reject"))])
    with pytest.raises(ValueError, match="ordered"):
        reduce_independent_segments(list(reversed(segments)))


@pytest.fixture(scope="module")
def mature_public_meta_fixture():
    path = ROOT / "tests/meta_selection/test_qms05_public.py"
    spec = importlib.util.spec_from_file_location("_met02_qms_public_fixture", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _, cold, _ = module.run("shadow")
    history, _ = module.reviewed_history(module.sidecar(cold)["tasks"][0])
    return module, history


@pytest.mark.parametrize("meta_mode", ["off", "shadow", "active"])
def test_met02_t09_t10_public_meta_reporting_preserves_fit_predictions_and_account(meta_mode, mature_public_meta_fixture):
    fixture, history = mature_public_meta_fixture
    _, result, _ = fixture.run(meta_mode, history=history)
    signature = fixture.native_digest(result)
    if meta_mode != "off":
        records = fixture.sidecar(result)["records"]
        assert any(record["proposal"].predictions for record in records)
        decisions = [(r["selected_evaluation_id"], r["proposal"].predictions) for r in records]
    python_rng, numpy_rng = random.getstate(), np.random.get_state()
    contract = replace(policy([int(result.equity.index[0].value), int(result.equity.index[-1].value)],
        result.initial_capital), sampling="observed_bar")
    obs = account_from_completed(result, contract, result_identity="mature-" + meta_mode,
        partial_mask=[False] * len(result.equity), return_witness="completed explicit stitched account")
    with ReportingCache() as cache:
        cache.reduce("account", obs, contract, backend="numba", retain_episodes=True)
    assert fixture.native_digest(result) == signature
    assert random.getstate() == python_rng
    state = np.random.get_state()
    assert state[0] == numpy_rng[0] and np.array_equal(state[1], numpy_rng[1]) and state[2:] == numpy_rng[2:]
    _, again, _ = fixture.run(meta_mode, history=history)
    assert fixture.native_digest(again) == signature
    if meta_mode != "off":
        assert decisions == [(r["selected_evaluation_id"], r["proposal"].predictions) for r in fixture.sidecar(again)["records"]]


@pytest.mark.parametrize("unit", ["closed_trade", "closed_action"])
def test_met02_t01_t08_ledger_python_numba_parity_cache_profiles(unit):
    obs, contract = ledger(rows_from_fixture()), ledger_policy(unit)
    python = reduce_ledger(obs, contract)
    numba = reduce_ledger(obs, contract, backend="numba")
    assert [m.to_metadata() for m in python.metrics] == [m.to_metadata() for m in numba.metrics]
    cache = ReportingCache()
    assert cache.reduce("ledger", obs, contract, backend="numba").metrics == numba.metrics
    assert cache.reduce("ledger", replace(obs, coverage=ledger_coverage(len(obs.records), "truncated")), contract).metric(unit + ".closed_count").status == "unavailable"


def test_met02_t02_t10_completed_account_adapter_scope_baseline_and_no_mutation():
    index = pd.date_range("2025-01-01", periods=4, freq="D", tz="UTC")
    result = BacktestResultV2(equity=pd.Series([100., 120., 125., 132.], index=index),
        returns=pd.Series([0., .2, 1/24, 7/125], index=index),
        positions=pd.DataFrame({"Position_ETH": [0., 1., 1., 0.]}, index=index),
        closes=pd.DataFrame({"Close_ETH": [100., 120., 125., 132.]}, index=index),
        symbols=["ETH"], initial_capital=100.)
    raw = {name: getattr(result, name).copy(deep=True) for name in ("equity", "returns", "positions", "closes")}
    legacy = result.full_report(scope="full")
    contract = replace(policy([int(index[1].value), int(index[-1].value)], 120.), scope="scoped", sampling="observed_bar")
    obs = account_from_completed(result, contract, result_identity="raw-one", partial_mask=[False] * 3,
                                 return_witness="retained full-bar closes")
    report = reduce_account(obs, contract)
    assert report.metric("account.total_return").value == pytest.approx(.1)
    assert report.metric("period.count").value == 3
    assert result.full_report(scope="full") == legacy
    for name, expected in raw.items():
        if isinstance(expected, pd.Series):
            pd.testing.assert_series_equal(getattr(result, name), expected, check_exact=True)
        else:
            pd.testing.assert_frame_equal(getattr(result, name), expected, check_exact=True)
    assert not result.fills and not result.trades
    naive = SimpleNamespace(equity=result.equity.tz_localize(None))
    with pytest.raises(ValueError, match="naive"):
        account_from_completed(naive, contract, result_identity="naive")
    explicit = account_from_completed(naive, contract, result_identity="naive", naive_timezone="UTC")
    assert explicit.equity.tolist() == obs.equity.tolist()


def native_payload(profile):
    return dict(native_result_version=2, native_execution_contract_bundle_hash="a" * 64,
        native_execution_terminal_fingerprint="b" * 64, output_profile=profile,
        native_execution_output_profile=profile,
        detail_truncated=True, retained_rows=1, dropped_rows=10,
        metrics={"native_metric_fill_count": 8, "native_metric_total_fee": 3., "native_metric_sharpe": 99.},
        equity=np.array([100., 90., 100.]), fees=np.array([1., 1., 1.]),
        funding=np.array([0., 0., 0.]), turnover=np.array([10., 10., 10.]),
        initial_margin=np.array([0., 10., 0.]), maintenance_margin=np.array([0., 1., 0.]))


@pytest.mark.parametrize("profile", ["score", "compact", "audit"])
def test_met02_t07_t09_native_adapter_exact_aggregates_not_scientific_override(profile):
    payload = native_payload(profile)
    adapter = NativeResultV2Adapter(payload)
    old = dict(adapter.metrics)
    coverage = ledger_coverage(1, "truncated")
    aggregate = execution_from_native(adapter, coverage=coverage, currency="USDT", scope_start_ns=0, scope_end_ns=30)
    result = reduce_execution(aggregate, policy([0, 30]))
    assert result.metric("execution.fill_count").value == 8
    assert result.metric("execution.total_fee").value == 3
    assert adapter.materialized_frames == () and dict(adapter.metrics) == old
    index = pd.date_range("2025-01-01", periods=3, freq="D", tz="UTC")
    contract = policy([int(index[0].value), int(index[-1].value)])
    if profile == "score":
        with pytest.raises(LookupError, match="no implicit"):
            account_from_completed(adapter, contract, index=index, result_identity="native")
    else:
        obs = account_from_completed(adapter, contract, index=index, result_identity="native")
        assert reduce_account(obs, contract).metric("account.total_return").value == 0
        assert adapter.materialized_frames == ()
        assert np.array_equal(payload["equity"], [100., 90., 100.])


@pytest.mark.parametrize("mode,schedule", [("mode_1_decay", "per_fold_decay"), ("mode_4_is_only_robust", "per_fold_causal")])
def test_met02_t09_t10_seeded_public_wfo_proposals_objective_selection_account_unchanged(mode, schedule):
    index = pd.date_range("2020-01-01", "2021-06-30", freq="D", tz="UTC")
    phase = np.arange(len(index), dtype=float)
    close = 100. + .05 * phase + 3. * np.sin(phase / 11.)
    data = pd.DataFrame({"open": close, "high": close + 1., "low": close - 1., "close": close, "volume": 1000.}, index=index)
    def strategy(data, params, train_index, test_index, fold):
        history = data.loc[:test_index[-1], "close"]
        side = np.sign(history.diff(int(params["window"]))).fillna(0.)
        return side.reindex(test_index)
    def run():
        endpoint = QuantBTEndpoint.walk_forward(strategy_class=strategy,
            split_mode="2021-01-01", split_frequency="quarterly", window_mode="rolling", train_window="180D",
            target_mode="pct_equity", optimization_mode=mode, optimization_schedule=schedule,
            optimization_config=dict(scoring_backend="endpoint", is_subperiods=1, flat_min_samples=1,
                flat_eps=1., top_is_fraction=1., candidate_selection_metric="robust_decay" if mode == "mode_1_decay" else "is_only_robust"),
            optuna_trials=3, random_seed=731, initial_capital=20_000., leverage=1., alloc_per_trade=.5, fee_rate=.0005)
        return endpoint.backtest(data=data, param_ranges={"window": (3, 9, 2)})
    scientific = canonical_metric_contract()
    before = run()
    old_report = before.full_report(scope="full")
    rng_python, rng_numpy = random.getstate(), np.random.get_state()
    contract = replace(policy([int(before.equity.index[0].value), int(before.equity.index[-1].value)], before.initial_capital), sampling="observed_bar")
    obs = account_from_completed(before, contract, result_identity="seeded-wfo", partial_mask=[False] * len(before.equity),
                                 return_witness="completed stitched-account daily bars")
    with ReportingCache() as cache:
        cache.reduce("account", obs, contract, backend="numba", retain_episodes=True)
        cache.reduce("account", obs, contract, backend="numba", retain_episodes=True)
    assert random.getstate() == rng_python
    after_state = np.random.get_state()
    assert after_state[0] == rng_numpy[0] and np.array_equal(after_state[1], rng_numpy[1]) and after_state[2:] == rng_numpy[2:]
    assert canonical_metric_contract() == scientific and before.full_report(scope="full") == old_report
    after = run()
    for name in ("equity", "returns"):
        pd.testing.assert_series_equal(getattr(before, name), getattr(after, name), check_exact=True)
    assert not hasattr(before, "fees") and not hasattr(after, "fees")
    assert not hasattr(before, "funding") and not hasattr(after, "funding")
    pd.testing.assert_frame_equal(before.positions, after.positions, check_exact=True)
    left, right = before.metadata["walk_forward"], after.metadata["walk_forward"]
    for name in ("trial_table", "candidate_table"):
        pd.testing.assert_frame_equal(left[name], right[name], check_exact=True)
    assert left["trial_table"]["objective"].abs().max() > 0
    assert before.positions.to_numpy().any()
    assert left["params_by_fold"] == right["params_by_fold"] and left["best_trial"] == right["best_trial"]
    assert before.full_report(scope="full") == after.full_report(scope="full")


def test_met02_t08_t10_protected_sources_privacy_no_hot_consumer_or_oracle_import():
    baseline = json.loads((ROOT / "docs/metrics/evidence/met02/baseline.json").read_text())
    for path, value in baseline["protected_sources"].items():
        assert_protected(path, value)
    forbidden = {"quantstats", "matplotlib", "_quantbt_native", "nautilus_trader"}
    for path in (ROOT / "src/quantbt/metrics/reporting").glob("*.py"):
        text = path.read_text()
        assert all(token not in text for token in ("/root/", "alphas_storage", "reference_oracle", "QuantBTEndpoint", "BacktestEngine"))
        tree = ast.parse(text)
        modules = {node.module.split(".")[0] for node in tree.body if isinstance(node, ast.ImportFrom) and node.module}
        modules |= {name.name.split(".")[0] for node in tree.body if isinstance(node, ast.Import) for name in node.names}
        assert not modules & (forbidden | {"numba", "pandas"})
    script = '''
import importlib.abc, sys
forbidden_names = {'quantstats', 'matplotlib', '_quantbt_native', 'nautilus_trader'}
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in forbidden_names:
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
import quantbt.metrics
# Legacy core import already requires Numba; the additive package adds no imports.
forbidden_names.add('numba')
before = {n for n in sys.modules if n.startswith('quantbt.backends')}
from quantbt.metrics.reporting.cache import ReportingCache
assert {n for n in sys.modules if n.startswith('quantbt.backends')} == before
'''
    completed = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr

import ast
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from quantbt.core.orders import Fill, Trade
from quantbt.core.results import BacktestResultV2, OptionBacktestResult
from quantbt.core.native_result_v2 import NativeResultHeaderV2
from quantbt.metrics import performance
from quantbt.optimization.meta_selection.observer import canonical_metric_contract

from .test_contract import contract
from .reference_oracle import drawdown_episodes
from .source_guard import ADMITTED, assert_protected


ROOT = Path(__file__).resolve().parents[2]
BASELINE = json.loads((ROOT / "docs/metrics/evidence/met01/baseline.json").read_text())


@pytest.mark.parametrize("path", sorted(BASELINE["protected_sources"]))
def test_t01_t08_every_existing_production_byte_is_unchanged(path):
    assert_protected(path, BASELINE["protected_sources"][path])


@pytest.mark.parametrize("cls,required", [
    (Fill, {"timestamp", "symbol", "qty", "price", "fee", "trade_id", "order_id", "metadata"}),
    (Trade, {"opened_at", "closed_at", "realized_pnl", "fees", "trade_id", "metadata"}),
    (BacktestResultV2, {"equity", "returns", "positions", "fills", "trades", "fees", "funding", "metadata"}),
    (OptionBacktestResult, {"fills_report", "packages_report", "cash_report", "settlements_report", "run_manifest"}),
    (NativeResultHeaderV2, {"output_profile", "detail_truncated", "retained_rows", "dropped_rows", "terminal_fingerprint", "metric_contract_version"}),
])
def test_t01_existing_raw_shapes_record_capability_not_assumed_completeness(cls, required):
    assert required <= {f.name for f in fields(cls)}


def test_t01_t08_new_schema_has_no_production_consumer_or_heavy_import():
    for path in (ROOT / "src/quantbt").rglob("*.py"):
        if path.name == "report_contracts.py" or path.is_relative_to(ROOT / "src/quantbt/metrics/reporting") or path.relative_to(ROOT).as_posix() in ADMITTED:
            continue
        assert "report_contracts" not in path.read_text(), str(path)
    tree = ast.parse((ROOT / "src/quantbt/metrics/report_contracts.py").read_text())
    modules = {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    modules |= {name.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names}
    assert modules <= {"__future__", "dataclasses", "hashlib", "json", "math"}


def test_t08_optional_dependency_absence_and_no_simulation_import():
    script = '''
import importlib.abc, runpy, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'quantstats', 'matplotlib', '_quantbt_native', 'quantbt_native', 'nautilus_trader'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
runpy.run_path('src/quantbt/metrics/report_contracts.py')
assert not any(name.startswith('quantbt.backends') for name in sys.modules)
import quantbt.metrics
before = {name for name in sys.modules if name.startswith('quantbt.backends')}
from quantbt.metrics.report_contracts import ReportingContractV1
assert {name for name in sys.modules if name.startswith('quantbt.backends')} == before
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_t08_raw_object_legacy_scientific_identity_and_report_are_unchanged():
    idx = pd.date_range("2025-01-01", periods=4, freq="h", tz="UTC")
    raw = BacktestResultV2(equity=pd.Series([100, 90, 95, 100], index=idx, dtype=float),
                           returns=pd.Series([0, -.1, 1 / 18, 1 / 19], index=idx, dtype=float),
                           positions=pd.DataFrame({"Position_BTC": [0., 1., 1., 0.]}, index=idx),
                           closes=pd.DataFrame({"Close_BTC": [100., 90., 95., 100.]}, index=idx),
                           fees=pd.Series([1., 0., 0., 1.], index=idx),
                           funding=pd.Series([0., .1, 0., 0.], index=idx),
                           symbols=["BTC"], initial_capital=100.)
    before = {name: getattr(raw, name).copy(deep=True) for name in ("equity", "returns", "positions", "closes", "fees", "funding")}
    scientific = canonical_metric_contract()
    report = raw.full_report(scope="full")
    policy = contract()
    drawdown_episodes(list(map(int, idx.asi8)), list(raw.equity), 100, int(idx[0].value))
    assert canonical_metric_contract() == scientific
    assert raw.full_report(scope="full") == report
    assert policy.version != "native_metric_v2"
    for name, expected in before.items():
        actual = getattr(raw, name)
        if isinstance(actual, pd.Series):
            pd.testing.assert_series_equal(actual, expected, check_exact=True)
        else:
            pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    assert not raw.fills and not raw.trades


def test_t01_manual_dictionary_covers_all_legacy_report_keys():
    report = performance.compute_performance_metrics(timestamps=pd.date_range("2025-01-01", periods=2),
                                                     equity=[100, 101], returns=[0, .01], positions=[0, 1], symbols=["A"], initial_capital=100.)
    dictionary = (ROOT / "docs/metrics/INVENTORY.md").read_text()
    assert all(key in dictionary for key in report)


def test_t08_fixtures_contain_no_private_alpha_or_machine_paths():
    text = (Path(__file__).parent / "fixtures/manual.json").read_text()
    assert all(token not in text for token in ("/root/", "alphas_storage", "api_key", "secret_key"))
    for path in (ROOT / "tests/metrics").glob("*.py"):
        if path.name == "reference_oracle.py":
            assert "quantbt" not in path.read_text().lower().split('"""', 2)[-1]

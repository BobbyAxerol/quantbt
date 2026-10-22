"""Cold-report extraction parity against the exact preflight-entry facade."""

import ast
from copy import deepcopy
import inspect
from pathlib import Path
import subprocess
import sys
import types

import numpy as np
import pandas as pd
import pytest

from quantbt.backends import native_portfolio, portfolio_reports
from quantbt.core.schema import AccountConfig


ROOT = Path(__file__).resolve().parents[1]
BASELINE = "7cdaadbc573435186ea7901162b9499973ec82b5"
PATH = "src/quantbt/backends/native_portfolio.py"
MOVED = ("_build_symbol_pnl_report", "_build_exposure_report", "_build_rebalance_report", "_build_reconciliation_report")


@pytest.fixture(scope="module")
def original():
    source = subprocess.check_output(["git", "show", BASELINE+":"+PATH], cwd=ROOT)
    module = types.ModuleType("quantbt.backends._pre_m512_portfolio_oracle")
    module.__package__ = "quantbt.backends"
    sys.modules[module.__name__] = module
    try:
        exec(compile(source, PATH, "exec"), module.__dict__)
        yield source, module
    finally:
        sys.modules.pop(module.__name__, None)


@pytest.mark.parametrize("name", MOVED)
def test_moved_reports_keep_original_body_arguments_and_static_binding(original, name):
    source, module = original
    before = next(node for cls in ast.parse(source).body if isinstance(cls, ast.ClassDef) and cls.name == "NativePortfolioBackend"
                  for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    before = deepcopy(before)
    before.decorator_list = []
    actual = next(node for node in ast.parse(inspect.getsource(portfolio_reports)).body
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    assert ast.dump(before) == ast.dump(actual)
    assert isinstance(native_portfolio.NativePortfolioBackend.__dict__[name], staticmethod)
    assert getattr(native_portfolio.NativePortfolioBackend, name) is getattr(portfolio_reports, name)
    assert inspect.signature(getattr(module.NativePortfolioBackend, name)) == inspect.signature(getattr(portfolio_reports, name))


def _equal(actual, expected):
    if isinstance(expected, pd.DataFrame):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    elif isinstance(expected, pd.Series):
        pd.testing.assert_series_equal(actual, expected, check_exact=True)
    elif isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            _equal(actual[key], expected[key])
    elif isinstance(expected, (tuple, list)):
        assert type(actual) is type(expected) and len(actual) == len(expected)
        for left,right in zip(actual, expected):
            _equal(left, right)
    elif isinstance(expected, np.ndarray):
        np.testing.assert_array_equal(actual, expected)
    elif isinstance(expected, (float, np.floating)) and np.isnan(expected):
        assert np.isnan(actual)
    else:
        assert actual == expected


@pytest.mark.parametrize("profile", ["full", "standard", "minimal"])
@pytest.mark.parametrize("case", ["opposite_legs", "liquidation", "quantity_constraints", "heterogeneous_leverage"])
def test_original_account_and_all_requested_report_fields_remain_exact(original, profile, case):
    _, module = original
    idx = pd.date_range("2024-01-01", periods=12, freq="8h", tz="UTC")
    prices = np.array([100, 100, 101, 99, 103, 98, 100, 104, 102, 96, 100, 101], dtype=float)
    closes = {"A": pd.Series(prices, index=idx), "B": pd.Series(200-prices, index=idx)}
    signals = {"A": pd.Series([0, 1, 1, 0, -1, -1, 0, 1, 1, 0, 0, 0], index=idx, dtype=float),
               "B": pd.Series([0, -1, -1, 0, 1, 1, 0, -1, -1, 0, 0, 0], index=idx, dtype=float)}
    extra = {}
    if case == "liquidation":
        closes["A"].iloc[2:] = 1.0
        signals["B"].iloc[:] = 0.0
    if case == "quantity_constraints":
        extra.update(qty_step={"A": 0.3, "B": 0.2}, min_qty=0.5, min_notional=20.0)
    if case == "heterogeneous_leverage":
        extra["leverage"] = {"A": 1.0, "B": 3.0}
    def run(namespace):
        backend = namespace.NativePortfolioBackend(namespace.NativePortfolioConfig(
            account=AccountConfig(initial_capital=1000.0, leverage=2.0),
            fee_rate=0.0004, use_funding=True, report_level=profile))
        return backend.run_signals(positions=signals, closes=closes, highs=closes, lows=closes,
                                   datetime_index=idx, symbols=["A", "B"], hedge_type="notional",
                                   alloc_per_trade=1500.0 if case == "liquidation" else 750.0,
                                   contract_size={"A": 10.0, "B": 1.0},
                                   funding_rate={"A": 0.0001, "B": -0.0002}, **extra)
    expected, actual = run(module), run(native_portfolio)
    for name in ("equity", "returns", "positions", "closes", "fees", "funding", "margin", "diagnostics", "metadata",
                 "liquidated", "liquidation_bar", "symbols", "initial_capital", "leverage"):
        _equal(getattr(actual, name), getattr(expected, name))
    if case == "liquidation":
        assert actual.liquidated


def test_facade_is_below_review_trigger_without_registry_exception():
    assert len(inspect.getsource(native_portfolio).splitlines()) < 1000

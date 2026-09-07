"""Exact legacy audit projection parity, independent of execution authority."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantbt.core import execution_trace as current
from quantbt.core.accounting_contracts import build_native_accounting_audit


def load_oracle(filename="canonical_trace_pre_optimization.py"):
    spec = importlib.util.spec_from_file_location(
        "frozen_" + filename.removesuffix(".py"), Path(__file__).parent / "fixtures" / filename
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ORACLE = load_oracle()
ACCOUNT_ORACLE = load_oracle("accounting_pre_optimization.py")


def assert_accounting_projection(result, contract_sizes=1.0):
    before = ACCOUNT_ORACLE.build_native_accounting_audit(result, contract_sizes=contract_sizes)
    after = build_native_accounting_audit(result, contract_sizes=contract_sizes)
    for field in ("ledger", "symbol_ledger", "liquidation_report"):
        pd.testing.assert_frame_equal(getattr(after, field), getattr(before, field), check_exact=True)
    assert after.invariants == before.invariants
    assert after.policy.to_metadata() == before.policy.to_metadata()


def assert_projection(result):
    expected = ORACLE.build_canonical_execution_trace(result)
    actual = current.build_canonical_execution_trace(result)
    pd.testing.assert_frame_equal(actual.trace, expected.trace, check_exact=True)
    assert actual.fingerprint == expected.fingerprint == current.canonical_trace_fingerprint(actual.trace)
    assert actual.row_count == expected.row_count
    assert actual.event_counts == expected.event_counts
    assert vars(current.TraceReplayer().replay(actual.trace)) == vars(ORACLE.TraceReplayer().replay(expected.trace))
    hash_only = current.build_canonical_execution_trace(result, materialize=False)
    assert hash_only.trace.empty
    assert hash_only.fingerprint == expected.fingerprint


def synthetic_result(n=19):
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    rng = np.random.default_rng(127)
    account = pd.DataFrame({
        "equity_actual": 1000 + rng.normal(size=n).cumsum(),
        "initial_margin": rng.uniform(10, 100, n),
        "maintenance_margin": rng.uniform(0.1, 2, n),
        "fee": rng.uniform(0, 0.1, n),
        "funding": rng.uniform(-0.2, 0.2, n),
    }, index=index)
    source = pd.DataFrame({
        "timestamp": np.repeat(index, 2), "symbol": ["A", "B"] * n,
        "position_qty": rng.integers(-3, 4, 2 * n).astype(float),
        "mark_price": rng.uniform(90, 110, 2 * n),
    })
    return SimpleNamespace(
        equity=account.equity_actual.copy(), initial_capital=1000, symbols=["A", "B"], fills=(),
        metadata={"accounting_ledger_v1": account, "symbol_accounting_ledger_v1": source},
    )


@pytest.mark.parametrize("variant", ["normal", "missing", "unordered", "nan", "no_account", "no_snapshots", "empty", "liquidation"])
def test_dense_projection_exact(variant):
    result = synthetic_result()
    metadata = result.metadata
    if variant == "missing":
        metadata["accounting_ledger_v1"] = metadata["accounting_ledger_v1"].iloc[2::3]
        metadata["symbol_accounting_ledger_v1"] = metadata["symbol_accounting_ledger_v1"].iloc[1::3]
    elif variant == "unordered":
        metadata["accounting_ledger_v1"] = metadata["accounting_ledger_v1"].iloc[::-1]
        metadata["symbol_accounting_ledger_v1"] = metadata["symbol_accounting_ledger_v1"].sample(frac=1, random_state=41)
    elif variant == "nan":
        metadata["accounting_ledger_v1"].iloc[2:5, :] = np.nan
        metadata["accounting_ledger_v1"].iloc[5, 1] = -0.0
        metadata["accounting_ledger_v1"].iloc[6, 1] = float("inf")
    elif variant == "no_account":
        metadata.pop("accounting_ledger_v1")
    elif variant == "no_snapshots":
        metadata.pop("symbol_accounting_ledger_v1")
    elif variant == "empty":
        result = synthetic_result(0)
    elif variant == "liquidation":
        metadata["liquidation_attribution_v1"] = pd.DataFrame([
            {"bar": 4, "liquidation_cost": 2.1, "residual_equity": 997.9, "reason_code": "MARGIN"},
            {"bar": 4, "liquidation_cost": 0.1, "residual_equity": 997.8, "reason_code": "FEE"},
        ])
        metadata["event_phase_trace_v1"] = pd.DataFrame([
            {"bar": 4, "phase": "OPEN"}, {"bar": 4, "phase": "CLOSE"}, {"bar": 3, "phase": "FUNDING"},
        ])
    assert_projection(result)


@pytest.mark.parametrize("kind", ["low", "churn", "parent", "gtd"])
def test_real_callback_accounting_and_requested_audit_unchanged(kind, monkeypatch):
    from benchmarks.native_event.benchmark_reactive_session import _bars, PeriodicStrategy
    from quantbt import QuantBTEndpoint

    monkeypatch.setenv("QUANTBT_NATIVE_BACKEND", "python")
    data = _bars(180)

    def run(level):
        endpoint = QuantBTEndpoint.native_event_strategy(
            initial_capital=100_000, leverage=5, maintenance_ratio=0.005,
            use_funding=True, funding_rate=0.0001, fee_rate=0.0002,
            report_level=level, reactive_kernel_mode="single_pass",
        )
        strategy = PeriodicStrategy(every=40 if kind == "low" else 12, hold=3,
                                    bracket=kind == "parent", gtd=kind == "gtd")
        return endpoint.simulate(data=data, strategy=strategy, symbols=["BTC"])

    audit = run("audit")
    assert_accounting_projection(audit)
    assert_projection(audit)
    expected = deepcopy(audit.metadata["canonical_trace_replay_v1"])
    assert expected["passed"]
    minimal = run("minimal")
    for field in ("equity", "returns", "positions", "fees", "funding", "margin"):
        left, right = getattr(audit, field), getattr(minimal, field)
        if isinstance(left, pd.DataFrame):
            pd.testing.assert_frame_equal(left, right, check_exact=True)
        else:
            pd.testing.assert_series_equal(left, right, check_exact=True)
    # Minimal intentionally omits Fill objects, but retains identical accounting.
    assert audit.fills
    assert not minimal.fills


def test_fingerprint_blocks_preserve_python_round_and_schema():
    result = synthetic_result(4100)
    assert_projection(result)


def test_projection_owns_output_after_source_mutation():
    result = synthetic_result()
    trace = current.build_canonical_execution_trace(result)
    expected = trace.trace.copy(deep=True)
    result.metadata["accounting_ledger_v1"].iloc[:, :] = 0
    result.metadata["symbol_accounting_ledger_v1"]["position_qty"] = 999
    pd.testing.assert_frame_equal(trace.trace, expected, check_exact=True)


@pytest.mark.parametrize("fill_bars", [[], [0], [18], [18, 3, 0, 3], [0, 3, 3, 7, 12, 18], list(range(19))])
@pytest.mark.parametrize("liquidated", [False, True])
def test_ledger_segment_broadcast_matches_each_bar_oracle(fill_bars, liquidated):
    result = synthetic_result()
    index = result.equity.index
    rng = np.random.default_rng(18)
    result.fills = tuple(SimpleNamespace(
        timestamp=index[bar], symbol="A" if i % 2 else "B", signed_qty=(-1 if i % 3 else 1) * (i + 1) * 0.13,
        price=100 + i * 0.12, order_id=str(i),
    ) for i, bar in enumerate(fill_bars))
    result.closes = pd.DataFrame(rng.uniform(95, 105, (19, 2)), index=index, columns=["A", "B"])
    result.positions = pd.DataFrame(rng.uniform(-2, 2, (19, 2)), index=index, columns=["A", "B"])
    result.fees = pd.Series(rng.uniform(0, 0.2, 19), index=index)
    result.funding = pd.Series(rng.uniform(-0.1, 0.1, 19), index=index)
    result.margin = result.metadata["accounting_ledger_v1"][["initial_margin", "maintenance_margin"]]
    result.liquidated = liquidated
    result.liquidation_bar = 12 if liquidated else -1
    assert_accounting_projection(result, contract_sizes={"A": 0.01, "B": 10})

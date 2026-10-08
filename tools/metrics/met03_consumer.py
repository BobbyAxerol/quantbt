"""Outside-checkout installed artifact proof; no local-source path insertion."""

import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import runpy
import sys


def check_reporting_edges():
    from dataclasses import replace
    from types import SimpleNamespace
    import pandas as pd
    from quantbt import ReportingRequest, ReportingContractV1, ReportingCoverageV1
    from quantbt.metrics.reporting.public import build_completed_report, format_metric_value
    from quantbt.metrics.reporting.ledger import reduce_ledger
    from quantbt.metrics.reporting.ledger_inputs import ActionRoster, LedgerObservations, RecordedOutcome

    times = pd.date_range("2025-01-01", periods=3, freq="h", tz="UTC")
    contract = ReportingContractV1(scope="full", unit="account_period", currency="USDT",
        baseline_equity=100., baseline_time_ns=int(times[0].value), scope_end_ns=int(times[-1].value),
        sampling="observed_bar", annual_periods=365*24, equity_clock="bar_close")
    for unit in ("s", "ms", "us", "ns"):
        result = SimpleNamespace(equity=pd.Series([99., 110., 105.], index=times.as_unit(unit)))
        request = ReportingRequest(account=contract, result_identity="installed-clock",
            partial_mask=(False, False, False), return_witness="recorded hourly observations")
        metadata = build_completed_report(result, request).to_metadata()
        metrics = {m["metric_id"]: m for m in metadata["groups"]["account_period"]["metrics"]}
        assert abs(metrics["reporting.account.total_return"]["value"] - .05) < 1e-12
    coverage = ReportingCoverageV1(result_identity="installed-action", producer="recorded-fixture",
        profile="audit", ledger="complete", retained_rows=2, dropped_rows=0)
    rows = (RecordedOutcome(trade_id="closed", action_id="A", symbol="ETH", side="long", currency="USDT",
        closed_at_ns=int(times[1].value), close_sequence=0, net_pnl=10.),
        RecordedOutcome(trade_id="open", action_id="A", symbol="BTC", side="short", currency="USDT",
            closed_at_ns=None, close_sequence=1, net_pnl=-1., open_unrealized_pnl=3.))
    observations = LedgerObservations(records=rows, coverage=coverage, matching="position_episode",
        valuation_time_ns=int(times[-1].value), rosters=(ActionRoster(action_id="A", outcome_ids=("closed", "open"),
            shared_net_adjustment=-2., allocation_witness="recorded at observation end"),))
    action_contract = replace(contract, unit="closed_action", matching="position_episode",
        grouping="authoritative_action_id", ledger_scope="closed_in_scope_lifetime")
    action = reduce_ledger(observations, action_contract)
    assert action.metric("closed_action.open_realized_net_pnl").value == 7
    assert action.metric("closed_action.open_unrealized_pnl").value == 3
    assert action.metric("closed_action.closed_count").value == 0
    absent = reduce_ledger(replace(observations, valuation_time_ns=None), action_contract)
    assert absent.metric("closed_action.open_realized_net_pnl").status == "unavailable"
    assert format_metric_value(1.5, "bars", "USDT") == "1.5 bars"
    return "PASS"


def check_snapshot_roundtrips():
    from copy import copy, deepcopy
    from dataclasses import replace
    import pickle
    import numpy as np
    from quantbt import ReportingContractV1, ReportingCoverageV1, ReportingCache
    from quantbt.metrics.reporting.inputs import AccountObservations, ReturnObservations
    from quantbt.metrics.reporting.account import reduce_account
    from quantbt.metrics.reporting.execution import ExecutionObservations

    coverage = ReportingCoverageV1(result_identity="installed-copy", producer="recorded synthetic marks",
        profile="completed", ledger="unsupported", retained_rows=0, dropped_rows=0, reason="no outcome ledger")
    returns = ReturnObservations(values=[0., -.1, 110/90-1], end_times_ns=np.array([0, 10, 20]),
        partial_mask=np.array([False, False, False]), sampling="observed_bar", witness="complete recorded bars")
    obs = AccountObservations(times_ns=np.array([0, 10, 20]), equity=[100., 90., 110.], coverage=coverage, returns=returns)
    contract = ReportingContractV1(scope="full", unit="account_period", currency="USDT", baseline_equity=100.,
        baseline_time_ns=0, scope_end_ns=20, sampling="observed_bar", annual_periods=8760., equity_clock="bar_close")
    execution = ExecutionObservations(coverage=coverage, currency="USDT", scope_start_ns=0, scope_end_ns=20,
        witness="recorded fee path", times_ns=obs.times_ns, paths=(("fees", np.array([1., 2., 3.])),))
    report = reduce_account(obs, contract, retain_episodes=True)
    clones = [copy, deepcopy] + [lambda value, p=p: pickle.loads(pickle.dumps(value, protocol=p))
                              for p in range(pickle.HIGHEST_PROTOCOL + 1)]
    for clone in clones:
        restored, fees, reduced = clone(obs), clone(execution), clone(report)
        assert restored.identity == obs.identity and fees.identity == execution.identity
        assert reduced.to_metadata() == report.to_metadata()
        for array in (restored.equity, restored.times_ns, restored.returns.values,
                      restored.returns.end_times_ns, restored.returns.partial_mask, fees.times_ns,
                      fees.paths[0][1], reduced.episodes.integers, reduced.episodes.numbers):
            try:
                array.setflags(write=True)
            except ValueError:
                pass
            else:
                raise AssertionError("copy/pickle restored a writable snapshot")
        with ReportingCache() as cache:
            initial = cache.reduce("account", obs, contract)
            assert cache.reduce("account", restored, contract) is initial
            changed = replace(restored, equity=[100., 90., 80.], returns=None)
            assert changed.identity != restored.identity
            assert abs(cache.reduce("account", changed, contract).metric("account.total_return").value + .2) < 1e-12
            assert cache.misses == 2
    return "PASS"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("registration", type=Path)
    parser.add_argument("example", type=Path)
    args = parser.parse_args()
    registration = json.loads(args.registration.read_text())
    import quantbt
    from quantbt import ReportingRequest, ReportingContractV1, ReportingCoverageV1, ReportingCache
    import quantbt.metrics.reporting.public as public
    root = Path(quantbt.__file__).parent
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob("*") if p.is_file() and (p.suffix == ".py" or p.name == "py.typed")}
    assert actual == registration["core_inventory"]
    assert "site-packages" in str(root) and str(root) != str(Path(registration["checkout"]) / "src/quantbt")
    assert quantbt.__version__ == "1.1.2" and metadata.version("quantbt-native") == "0.4.3"
    native = metadata.distribution("quantbt-native")
    binaries = [Path(native.locate_file(p)) for p in native.files if str(p).endswith(".so")]
    assert len(binaries) == 1 and hashlib.sha256(binaries[0].read_bytes()).hexdigest() == registration["native_reuse"]["extension_sha256"]
    from quantbt.backends._native_event_rust import probe_native_event_rust_extension
    status = probe_native_event_rust_extension()
    assert status.available and status.compatible and status.executable, status.reason
    ns = runpy.run_path(str(args.example))
    endpoint, result, request, report = ns["example"]()
    assert endpoint.full_report(reporting=request) == report
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = endpoint.quick_plot(reporting=request)
    fig.canvas.draw()
    assert len(fig.axes) == 2
    plt.close(fig)
    json.dumps(report, allow_nan=False)
    edge_cases = check_reporting_edges()
    snapshot_roundtrips = check_snapshot_roundtrips()
    import numpy as np
    from quantbt.metrics.reporting.inputs import frozen_array
    mutable = np.array([1., 2., 3.])
    mutable.setflags(write=False)
    frozen = frozen_array(mutable, np.float64)
    assert not np.shares_memory(mutable, frozen)
    mutable.setflags(write=True)
    mutable[:] = 0
    assert frozen.tolist() == [1., 2., 3.]
    assert np.shares_memory(frozen, frozen_array(frozen, np.float64))
    isolated_header = frozen_array(frozen, np.float64)
    frozen.shape = (3, 1)
    frozen.dtype = np.int64
    assert isolated_header.shape == (3,) and isolated_header.dtype == np.float64
    np.testing.assert_array_equal(isolated_header, [1., 2., 3.])
    with ReportingCache() as cache:
        from dataclasses import replace
        cached = replace(request, cache=cache)
        first = endpoint.full_report(reporting=cached)
        assert endpoint.full_report(reporting=cached) == first and cache.hits == 1
        result.equity.iloc[-1] -= 1
        assert endpoint.full_report(reporting=cached) != first and cache.misses == 2
    print(json.dumps(dict(status="PASS", modules=len(actual), core="1.1.2", native="0.4.3",
        package_origin=str(root), outside_checkout=True, extension_sha256=registration["native_reuse"]["extension_sha256"],
        matplotlib_optional=True, review_edge_cases=edge_cases, performance_ownership_cache="PASS",
        snapshot_roundtrips=snapshot_roundtrips, publication=False)))


if __name__ == "__main__":
    main()

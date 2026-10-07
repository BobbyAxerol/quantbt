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
    print(json.dumps(dict(status="PASS", modules=len(actual), core="1.1.2", native="0.4.3",
        package_origin=str(root), outside_checkout=True, extension_sha256=registration["native_reuse"]["extension_sha256"],
        matplotlib_optional=True, review_edge_cases=edge_cases, publication=False)))


if __name__ == "__main__":
    main()

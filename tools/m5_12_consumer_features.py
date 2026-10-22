"""Staged public synthetic controls; one explicitly budgeted execution case."""

from dataclasses import replace
from hashlib import sha256
import json

import pytest


def test_shared_diagnostics():
    from examples.shared_alpha_diagnostics import build_example_report
    from quantbt.diagnostics import AccessPolicy, AlphaDiagnosticReport
    report = build_example_report()
    data = report.to_dict()
    assert len(data["evaluation_ids"]) == 12
    assert data["authority"]["optimizer_started"] is False
    assert data["authority"]["automatic_routing"] is False
    assert AlphaDiagnosticReport(report.record).to_json() == report.to_json()
    policy = AccessPolicy("example-prefix", ("synthetic",), ("example-tape",), 101, "diagnostic")
    assert report.authorize(policy) is report
    with pytest.raises(PermissionError):
        report.authorize(replace(policy, cutoff_ns=99))
    assert "Alpha Diagnostics" in report.to_markdown()


def test_cold_calibration(tmp_path, monkeypatch):
    from examples.mode5_diagnostic_handoff import OPTION_ID, build_inputs
    from quantbt import QuantBTEndpoint
    from quantbt.diagnostics import Mode5RunPack
    from quantbt.mode5.dossier.governance import GovernanceLog

    def forbidden(*args, **kwargs):
        raise AssertionError("cold calibration invoked finance or search")

    monkeypatch.setattr(QuantBTEndpoint, "backtest", forbidden)
    inputs = build_inputs(tmp_path / "handoff", optional_archive=True, trials=1)
    worksheet = inputs["worksheet"]
    assert worksheet.record.data["selection"] is None
    assert inputs["archive"].record.data["rows"][0]["disposition"] == "TARGETED_EXECUTION_REQUIRED"
    with pytest.raises(PermissionError):
        Mode5RunPack.compile(worksheet, dossier=inputs["dossier"], catalog=inputs["catalog"],
                            access=inputs["access"], archive_access=inputs["archive_access"])
    chosen = worksheet.choose(OPTION_ID, researcher="installed synthetic consumer",
                              reason="Cold operational coverage only; no economic claim")
    pack = Mode5RunPack.compile(chosen, dossier=inputs["dossier"], catalog=inputs["catalog"],
                               access=inputs["access"], archive_access=inputs["archive_access"])
    path = pack.export(tmp_path / "pack", private=True)
    restored = Mode5RunPack.read(path, expected_identity=pack.identity)
    journal = GovernanceLog(tmp_path / "journal")
    endpoint = restored.prepare(dossier=inputs["dossier"], catalog=inputs["catalog"], journal=journal,
        access=inputs["access"], archive_access=inputs["archive_access"], data=inputs["data"],
        strategy=inputs["strategy"], param_ranges=inputs["param_ranges"],
        account_kwargs=inputs["account_kwargs"], target_mode="pct_equity")
    assert endpoint is not None and restored.identity == pack.identity
    assert journal.history()[-1].data["kind"] == "PLAN_SEALED"
    assert pack.record.data["automatic_routing"] is False
    with pytest.raises(PermissionError):
        restored.verify(dossier=inputs["dossier"], catalog=inputs["catalog"],
            access=replace(inputs["access"], manifests=("not-authorized",)),
            archive_access=inputs["archive_access"])
    with pytest.raises(ValueError):
        Mode5RunPack.read(path, expected_identity="0" * 64)


def test_reporting_example(monkeypatch):
    from examples.reporting_metrics_v1 import example
    endpoint, result, request, report = example()
    legacy = endpoint.full_report()
    before = result.equity.copy(deep=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("report rendering replayed execution")

    monkeypatch.setattr(endpoint, "backtest", forbidden)
    assert endpoint.full_report(reporting=request) == report
    assert result.full_report(reporting=request) == report
    assert json.dumps(endpoint.full_report(), sort_keys=True) == json.dumps(legacy, sort_keys=True)
    assert result.equity.equals(before)
    assert report["groups"]["account_period"]["status"] == "available"
    assert json.loads(json.dumps(report)) == report


def test_bounded_mode5_cross_mode_execution(tmp_path, record_property, request):
    budget = getattr(request.config, "_m512_optimizer_budget", None)
    case = "tools/m5_12_consumer_features.py::test_bounded_mode5_cross_mode_execution"
    assert budget is not None and budget.active == case, "installed budget plugin required before execution"
    from examples.mode5_cross_mode_qualification import run_demo
    from m5_12_consumer_matrix import EXECUTION_PROPERTY

    workdir = tmp_path / "cross-mode"
    outcome = run_demo(workdir, donor_folds=(0,))
    raw = (workdir / "summary.json").read_text()
    summary = json.loads(raw)
    assert summary == outcome["summary"]
    winner = json.loads((workdir / "winner-qualification.json").read_text())
    assert winner == outcome["winner"].to_dict(private=True)
    plan = outcome["challenger"]["donors"].to_dict()
    planned = [row["params"] for row in plan["warm_start"]]
    sampler = outcome["completed"]["challenger"]["metadata"]["sampler"]
    applied = sampler["rows"][:len(planned)]
    reconciled = {}
    for arm in ("baseline", "challenger"):
        retained = json.loads((workdir / (arm + "-reconciliation.json")).read_text())
        assert retained == outcome["completed"][arm]["report"].record.data
        reconciled[arm] = retained["status"]
    evidence = dict(summary=summary, summary_json=raw, summary_sha256=sha256(raw.encode()).hexdigest(),
        protocol=json.loads((workdir / "protocol.json").read_text()),
        reconciliation_statuses=reconciled, winner_report_id=outcome["winner"].identity,
        winner_baseline_status=winner["baseline"]["status"],
        winner_candidate_id=winner["subject"]["candidate_id"],
        baseline_candidate_id=outcome["completed"]["baseline"]["metadata"]["selected_params_digest"],
        planned_donor_params=planned, applied_donor_params=[row["effective_params"] for row in applied],
        donor_sources=[row["source"] for row in applied])
    record_property(EXECUTION_PROPERTY, json.dumps(evidence, sort_keys=True, allow_nan=False))


def _portfolio_control(targets, *, daily=False, **kwargs):
    import pandas as pd
    from quantbt import AccountConfig, PortfolioBacktestEngine
    index = pd.date_range("2024-01-01" if daily else "2024-01-01 06:00",
                          periods=4, freq="D" if daily else "h", tz="UTC")
    price = pd.Series(100., index=index)
    values = dict(positions={"S0": pd.Series(targets, index=index)}, closes={"S0": price},
        highs={"S0": price}, lows={"S0": price}, datetime_index=index,
        account=AccountConfig(initial_capital=1000, leverage=10), contract_size=1,
        hedge_type="target_units", backend="native_portfolio", fee_rate=0,
        use_funding=True, funding_rate=.01, report_level="full")
    values.update(kwargs)
    return PortfolioBacktestEngine(**values).result


def test_portfolio_daily_funding():
    import numpy as np
    result = _portfolio_control([0, 1, 1, 1], daily=True)
    np.testing.assert_allclose(result.equity, [1000, 1000, 997, 994])
    np.testing.assert_allclose(result.funding, [0, 0, 3, 3])
    assert result.metadata["portfolio_contract_report"]["passed"]
    assert result.metadata["symbol_pnl_report"].funding_cost.sum() == pytest.approx(6.)


def test_portfolio_executed_liquidation_report():
    import numpy as np
    import pandas as pd
    from quantbt import AccountConfig
    from quantbt.reporting.portfolio_audit import build_portfolio_domain_audit
    index = pd.date_range("2024-01-01 06:00", periods=4, freq="h", tz="UTC")
    result = _portfolio_control([0, 10, 10, 0],
        account=AccountConfig(initial_capital=100, leverage=20),
        lows={"S0": pd.Series([100., 100., 10., 100.], index=index)})
    np.testing.assert_allclose(result.equity, [100, 100, 0, 0])
    np.testing.assert_array_equal(result.funding, 0)
    report = result.metadata["symbol_pnl_report"]
    assert result.liquidated and report.total_pnl.sum() == pytest.approx(-100.)
    assert report.liquidation_adjustment.sum() == pytest.approx(100.)
    assert report.fee.sum() == 0 and result.metadata["portfolio_contract_report"]["passed"]
    bad = report.copy()
    bad.loc[bad.timestamp == index[2], "total_pnl"] += 1
    result.metadata["symbol_pnl_report"] = bad
    assert not build_portfolio_domain_audit(result)["passed"]

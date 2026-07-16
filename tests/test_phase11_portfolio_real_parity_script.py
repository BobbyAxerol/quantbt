from __future__ import annotations

from quantbt.benchmarks.run_portfolio_real_parity import make_markdown_report, run_suite


def test_phase11_portfolio_real_parity_script_smoke():
    report = run_suite(bars=180, symbols=("BTC", "ETH", "SOL"), seed=7)

    assert report["status"] == "pass"
    assert report["summary"]["legacy_parity_cases"] == 16
    assert report["summary"]["legacy_parity_passed"] is True
    assert report["summary"]["native_only_passed"] is True
    assert report["summary"]["unsupported_rejected"] is True
    assert report["summary"]["max_abs_equity_diff"] <= 1e-8
    assert "target_units" in report["native_supported_sizing_modes"]

    markdown = make_markdown_report(report)
    assert "Native Portfolio Real-Parity Audit" in markdown
    assert "longshort" in markdown

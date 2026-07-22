from __future__ import annotations

from quantbt.benchmarks.run_phase12_arbitrage_cert import make_markdown, run_certification


def test_phase12_arbitrage_certification_smoke():
    report = run_certification(rows=180, include_nautilus=False)

    assert report["status"] == "pass"
    assert report["basis"]["audit"]["passed"] is True
    assert report["basis"]["parity"]["passed"] is True
    assert report["stat_pair"]["accounting_parity_passed"] is True
    assert report["stat_pair"]["audit"]["passed"] is True
    assert report["stat_pair"]["max_package_residual"] < 1e-9
    assert report["index_basket"]["passed"] is True
    assert report["schema_only"]["passed"] is True
    assert report["nautilus"]["status"] == "skipped"

    markdown = make_markdown(report)
    assert "Phase 12A Arbitrage Production Certification" in markdown
    assert "Basis Perp-Quarterly" in markdown

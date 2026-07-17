from __future__ import annotations

from quantbt.benchmarks.run_phase12_benchmark_nautilus_cert import make_markdown, run_certification


def test_phase12_benchmark_nautilus_certification_smoke():
    report = run_certification(rows=180, symbols=3, repeats=1, include_nautilus=False)

    assert report["status"] == "pass"
    assert report["benchmark_followup"]["status"] == "pass"
    assert report["benchmark_followup"]["stages"]["full_facade_seconds"] > 0.0
    assert report["benchmark_followup"]["stages"]["pure_numba_kernel_seconds"] > 0.0
    assert report["all_or_none_basket"]["status"] == "pass"
    assert report["all_or_none_basket"]["accepted_orders"] == 0
    assert report["all_or_none_basket"]["rejected_orders"] == 2
    assert report["nautilus_portfolio"]["status"] == "skipped"

    markdown = make_markdown(report)
    assert "Phase 12B Benchmark And Nautilus Portfolio Certification" in markdown
    assert "Cython/C++ Decision" in markdown

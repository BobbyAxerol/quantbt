from __future__ import annotations

from quantbt.benchmarks.run_phase14_service_loop import make_markdown, run_benchmark


def test_phase14_service_loop_benchmark_smoke_and_parity_guards():
    report = run_benchmark(rows=120, symbols=2, trials=2, order_count=24, repeats=1)

    assert report["status"] == "pass"
    assert set(report["service_loops"]) == {
        "single_symbol_wfo",
        "portfolio_wfo",
        "native_event_replay",
        "arbitrage_package_sweep",
        "report_heavy_vs_light",
    }
    assert all(report["parity"].values())
    assert report["decomposition"]["native_vectorized"]["stages"]
    assert report["decomposition"]["native_event"]["stages"]
    assert report["decomposition"]["native_portfolio"]["stages"]["pure_numba_kernel_seconds"] > 0.0
    assert "Cython/C++ is not justified yet" in report["cython_cpp_recommendation"]


def test_phase14_service_loop_markdown_is_stakeholder_readable():
    report = run_benchmark(rows=96, symbols=2, trials=2, order_count=16, repeats=1)
    markdown = make_markdown(report)

    assert "Phase 14C Prepared Cache And Report-Level Benchmark" in markdown
    assert "Service Loop Timings" in markdown
    assert "Stage Decomposition" in markdown
    assert "Parity Guards" in markdown
    assert "Cython/C++ Decision" in markdown

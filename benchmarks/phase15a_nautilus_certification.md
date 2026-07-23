# Phase 15A Nautilus Certification Bundles

Status: **pass**

- Include Nautilus: `False`
- Output directory: `/root/bobby/pool_alpha/quantbt/benchmarks/phase15a_nautilus_bundles`
- Passed workflows: `0`
- Skipped workflows: `5`
- Failed workflows: `0`

## Workflow Matrix

| workflow | status | bundle | tolerance status | reason |
| --- | --- | --- | --- | --- |
| `pct_equity_signal` | `skipped` | `` | `` | run with --include-nautilus |
| `explicit_orders` | `skipped` | `` | `` | run with --include-nautilus |
| `basket_package` | `skipped` | `` | `` | run with --include-nautilus |
| `portfolio_package` | `skipped` | `` | `` | run with --include-nautilus |
| `basis_arbitrage_package` | `skipped` | `` | `` | run with --include-nautilus |

## Required Bundle Files

- `config.json`
- `run_manifest.json`
- `metrics_summary.json`
- `equity_curve.csv`, `returns.csv`, `account_report.csv`
- `orders_report.csv`, `fills_report.csv`, `positions_report.csv`
- `trade_log.csv`, `fill_log.txt`
- `native_vs_nautilus_parity.csv`
- `tolerance_profile.json`
- `known_differences.md`

## Interpretation

A skipped workflow is not a pass claim. It means the optional Nautilus dependency or instrument route was not available in this environment. A pass means the workflow produced a bundle and satisfied the declared tolerance profile.

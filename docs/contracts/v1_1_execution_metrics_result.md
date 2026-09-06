# V1.1 Execution, Metrics, And Native Result Contract

Phase 60 closes the common execution/result layer used by the Rust-native
workloads. It does not change a public endpoint's trading semantics. Instead,
it makes the execution, accounting, metric, and result boundaries explicit so
that a score run, a compact report, and an audit run can be compared without
silently using different simulation rules.

## Execution Model V1

`FullSession` remains the only owner of order lifecycle, account mutation,
margin, funding, and liquidation. `ExecutionModelV1` owns two separate,
immutable concerns:

1. `BarTouchV1` decides whether a market, limit, stop-market, or stop-limit
   order touches an OHLCV bar and records the raw price, gap behavior, and
   ambiguity code.
2. `CostModelV1` transforms a touched quantity into an executable price, fee,
   turnover, and bounded synthetic-liquidity consumption.

The default `bar_touch_v1` remains parity-compatible with the existing
one-way fee and proportional slippage contract. The optional cost model has
explicit proportional/fixed slippage, full spread in basis points, a simple
participation impact term, and a per-bar shared-liquidity ledger. This is a
deterministic OHLCV approximation, not an L2 queue-position claim.

Partial fills are applied only after post-cost account acceptance. FOK never
consumes partial liquidity; IOC cancels an unfilled remainder; GTC/GTD retain
the remainder for a later bar. A rejected account mutation never consumes the
shared bar ledger.

## Metric Contract V2

`MetricContractV2` is an explicit scalar policy attached to every native
output. The default is crypto daily sampling with annualization `365`, zero
risk-free rate, sample variance `ddof=1`, committed-fill trade counts, and a
finite zero result for short or zero-variance runs. The native online reducer
emits total return, CAGR, Sharpe, Sortino, max drawdown, Calmar, Omega,
average gross exposure, turnover, fee, funding, event counts, and liquidation
state without constructing pandas objects.

The contract belongs to the same native execution pass as accounting. Python
reporting may format these values, but it must not recompute a conflicting
metric result from a different path or timing convention.

## NativeResult V2

Every typed native result has a V2 header containing a request and template
fingerprint, contract-bundle hash, workload authority, execution model ID,
metric contract version, output profile, and terminal-accounting fingerprint.
The terminal fingerprint is identical across score, compact, and audit profiles
when execution inputs are identical. Retention changes the request fingerprint
but never lifecycle/accounting state.

Profiles are deliberately distinct:

| Profile | Retained data | Intended use |
|---|---|---|
| `score` | Scalars and final positions only | optimizer/WFO/service scoring |
| `compact` | score plus dense account paths | plot/report preparation |
| `audit` | compact data plus bounded fill/event and workload-admission SoA | certification and investigation |

Audit detail uses an explicit bounded row cap (default `250,000`). The result
reports retained and dropped rows plus truncation status. Canonical fills/events
and dynamic portfolio/package admission each have bounded sinks; aggregate
header counts cover both, while workload-specific counts are exposed separately
on the audit result.

`NativeResultV2Adapter` is a cold-path Python adapter. Its `metrics` property
is scalar-only. `to_pandas()`, `fills_dataframe()`, `orders_dataframe()`, and
`audit_events()` allocate DataFrames only on explicit request and retain them in
a bounded local LRU cache. The adapter never reruns or replays execution.

## Certification

Run the focused contract suite after changing this layer:

```bash
cargo test --manifest-path rust/Cargo.toml -p quantbt-engine
cargo test --manifest-path rust/Cargo.toml -p quantbt-execution
PYTHONPATH=src poetry run pytest -q tests/test_phase60_execution_metrics_native_result.py
PYTHONPATH=src poetry run python benchmarks/native_event/benchmark_phase60_result_rss.py
```

The benchmark checks the repeated score route for a bounded RSS plateau. It is
not a cross-machine speed claim and should be recorded with the host, wheel,
bar count, and iteration count used for release evidence.

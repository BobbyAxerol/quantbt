# Grid Native Event Phase 47C

Phase 47C is the Grid integration certification gate for the external alpha
module:

```text
/root/bobby/pool_alpha/alphas_storage/TA/dynamic_grid_quantbt_native_event.py
```

QuantBT imports that file read-only. It is not copied into this package and no
Grid-specific endpoint is introduced.

## Backend policy

The existing Grid adapter accepts four values in `GridExecutionConfig`:

| Value | Meaning |
|---|---|
| `python` | Canonical full reactive implementation and default. |
| `rust` | Explicit capability-gated Rust V2. Failure is raised; no fallback. |
| `replay_certified` | Python replay oracle used for audit evidence. |
| `auto` | Resolves to Python until every release gate is certified. |

The public endpoint remains:

```python
QuantBTEndpoint.native_event_strategy(...)
QuantBTEndpoint.prepare_native_event_strategy(...)
```

The Grid strategy still owns command generation. The backend owns lifecycle,
matching, fees, funding, margin, liquidation, and result accounting.

## 2,000-bar certification fixture

Phase 47C requires both `grid_mode="long_only"` and
`grid_mode="long_short"` on a sorted, unique 2,000-bar OHLCV tape. The
certification order is:

```text
replay-certified audit
Python single-pass audit
Python scalar v2
Rust reactive audit
Rust scalar
```

The audit gate compares the emitted command tape and effective bars, order
events/status/rejects, fills, positions, equity, fees, funding, margin,
liquidation state, and final equity. Discrete lifecycle fields are exact;
numeric paths use zero relative tolerance and only the documented floating
point tolerance.

`filled_command_count` is not a canonical parity field. The replay ledger
counts command states that reached `FILLED`, while a reactive session counts
fill records. The exact order-event and fill ledgers, plus the accounting
paths, remain the authoritative comparison.

## Prepared scalar score

Use a fresh strategy for every score and prepare the market tape once:

```python
execution = GridExecutionConfig(
    native_backend="rust",       # or "python"
    reactive_execution_mode="fast",
    reactive_kernel_mode="single_pass",
    report_level="score",
    audit_sink="none",
)

endpoint, prepared = prepare_grid_score_runner(
    df=data_2000,
    execution=execution,
)
score = score_grid_params(
    prepared_runner=prepared,
    df=data_2000,
    params=params,
    execution=execution,
)
```

The result is `NativeEventScalarScoreResult`. It retains scalar accounting,
final positions, metrics, and lifecycle counts, but no pandas report frame or
dense equity/fee/funding/margin paths. `endpoint.result` remains `None`.
For stakeholder reports, rerun the same strategy/config at `report_level="audit"`.

Scalar certification is not based on Sharpe or final equity alone. The audit
run with the same backend/config provides the retained fingerprint; scalar
totals and terminal state must match it:

```text
final equity
final positions
fill/reject/cancel counts
total fee
total funding
total turnover
liquidation state
```

## Isolated benchmark

Run one backend per process:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha \
poetry run python benchmarks/native_event/benchmark_grid_2000.py \
  --grid-module-dir /root/bobby/pool_alpha/alphas_storage/TA \
  --backend python --mode scalar --grid-mode long_only --bars 2000

MPLCONFIGDIR=/tmp PYTHONPATH=/root/bobby/pool_alpha \
poetry run python benchmarks/native_event/benchmark_grid_2000.py \
  --grid-module-dir /root/bobby/pool_alpha/alphas_storage/TA \
  --backend rust --mode scalar --grid-mode long_short --bars 2000
```

Default measurement is one warm-up and five measured runs. The JSON records
module version, commit, backend resolution, runtime median/p95, CPU time, peak
RSS/VmHWM, post-run RSS, full and post-warm-up tail slopes, audit fingerprint,
terminal accounting, and gate status. Optional `--data path.csv.gz` accepts an
OHLCV file; without it the deterministic 2,000-bar smoke tape is used. The
tail slope is the leak gate because the first measured call can still populate
allocator/PyO3 caches after the explicit warm-up; the full slope remains in
the artifact for inspection.

RSS is interpreted as a process-level evidence point, not a universal machine
claim. The accepted reference is approximately 180 MB, with no unexplained
10--15% regression and no linear repeated-run leak. A further 40% reduction is
not a Phase 47C requirement.

## Certification boundary

After Phase 47C, Python/replay/Rust are certified for this single-symbol Grid
workload on the tested full Native Event V2 contract. Rust is still explicit;
`auto` remains Python. Portfolio, arbitrage, options, L2 depth, and venue-
specific cross-margin behavior are outside this certificate. Phase 47D is
reserved for optimizer profiling and safe hot-path patches.

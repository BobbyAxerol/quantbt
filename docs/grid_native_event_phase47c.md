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
claim. The repeated-run tail-slope gate passes and shows no live-object leak.
The observed full Grid facade peaks are approximately 265.6--293.4 MB. The
approximately 180 MB figure in the broader guide belongs to a different
native-event process profile; Phase 47C therefore does not claim an absolute
no-regression comparison until an apples-to-apples pre-Phase47C Grid run is
archived. A further 40% reduction is not a Phase 47C requirement.

## Phase 47D optimizer certification

Phase 47D profiles the actual Grid optimizer path rather than using the
static Rust tape as a proxy. The profile separates:

```text
alpha preparation
strategy initialization
prepared engine score
public objective/report facade
```

On the deterministic 2,000-bar tape, the apples-to-apples prepared scalar
profile after the patch measured `0.813s`, with alpha preparation at `2.15%`
and the engine score at `97.89%`. This is an observed local measurement, not
a fixed performance guarantee. The profile did not justify an indicator
cache: the alpha layer is not the dominant cost, so no cache was added that
could complicate parameter isolation or retain full DataFrames.

The external Grid adapter now has these optimizer-safe policies:

```python
GridExecutionConfig(collect_diagnostics=True)   # public/audit default
GridExecutionConfig(collect_diagnostics=False)  # scalar-only artifact policy
```

`score_grid_params(...)` always creates a fresh diagnostics-off execution
policy for the trial. It also derives context requirements from
`ReactiveDynamicGridStrategy.native_context_requirements`: fills, active
orders, and positions remain enabled; full order events and margin payloads
are not requested by the callback. Diagnostic alias columns and per-bar
`_diag_*` arrays are therefore absent from scalar trials, while canonical
execution columns and all accounting decisions remain unchanged. Calling
`build_output_frame()` on a diagnostics-off strategy raises a clear error;
final stakeholder plots must rerun the same params with the default audit
policy.

The scalar gate remains strict:

```text
prepared.scores += 1
prepared.runs unchanged
endpoint.result is None
evaluator retains no result/strategy
```

The 47D tests compare terminal equity, fee, funding, fill count, liquidation,
and the retained audit evidence. Public/audit diagnostics remain enabled by
default. The exact source patch is committed in the external Grid alpha as
`fda46c3`; QuantBT does not copy or own that strategy source.

Current scalar benchmark evidence after the patch:

| Mode | Python median | Rust median | Python peak RSS | Rust peak RSS | Fingerprint |
|---|---:|---:|---:|---:|---|
| Long-only | 0.850 s | 1.086 s | 265.4 MB | 271.2 MB | pass |
| Long-short | 1.412 s | 1.831 s | 291.0 MB | 293.6 MB | pass |

The repeated-run RSS gates pass with no positive tail slope. Rust remains an
explicit, correctness-certified experimental backend for this workload and
`auto` remains Python. The reactive callback itself is still the dominant
runtime owner; this phase does not claim a new Numba/Rust optimization of the
Python Grid callback or portfolio/arbitrage/options parity. Raw benchmark
artifacts are stored under
`benchmarks/native_event/results/phase47d/`.

## Certification boundary

After Phase 47D, Python/replay/Rust are certified for this single-symbol Grid
workload on the tested full Native Event V2 contract. Rust is still explicit;
`auto` remains Python. Portfolio, arbitrage, options, L2 depth, and venue-
specific cross-margin behavior are outside this certificate. The remaining
performance debt is deeper callback-level optimization, which requires a new
parity-first phase rather than an indicator cache based on this profile.

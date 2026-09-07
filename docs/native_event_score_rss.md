# Native Event Score And RSS Evidence

Phase 46B defines the fair comparison between the Python and Rust static-tape
execution paths. Phase 61 keeps that comparison and promotes its Rust side to
the typed static ABI `0.5` on the certified prepared-command route.

## Artifact Contract

Both score paths consume the same prepared market signature and the same
`CompiledOrderCommandArrays`. Neither path materializes a pandas result or a
full audit ledger during timing. Each returns the following scalar accounting
fields:

```text
final_equity
final_position
total_fee
total_turnover
fill_count
event_count
rejected_count
canceled_count
max_initial_margin
max_maintenance_margin
```

`NativeEventBackend.run_compiled_tape_score(...)` prepares a compact typed
result for exact metrics without fill/event ledger retention. Its default Rust
route is ABI `0.5`; `native_static_abi="0.4_compat"` is an explicit rollback,
not an automatic fallback. Existing public
`run_order_commands(..., report_level="audit")` behavior is unchanged and
adapts a typed audit result without replaying the tape.

For `event_lifecycle_v3_next_open`, the score API requires an explicit `opens`
array. A missing open price raises instead of silently substituting close. V2
uses its declared close-timing contract and can use the close array when no
separate open source is supplied.

## Certification Before Timing

`benchmarks/native_event/benchmark_phase46b_score_rss.py` runs a fresh parity
child for low and high order churn before measuring latency. The certificate
compares:

- equity, positions, fees, turnover, and margin paths;
- every fill including bar, order, side, quantity, price, and fee;
- every lifecycle event including bar, semantic event kind, status, order,
  and related order identifiers.

Rust transport event codes are explicitly normalized to the Python semantic
event codes inside the benchmark adapter. This keeps the ABI mapping visible
without weakening the parity certificate.

## RSS Checkpoints

Each backend runs in its own child process. The benchmark records
`/proc/self/statm` current RSS and `VmHWM` peak RSS at:

```text
rss_interpreter
rss_after_import_quantbt
rss_after_market_prepare
rss_after_command_compile
rss_after_runner_prepare
rss_after_score_warmup
peak_rss_during_run
rss_after_run
```

The reported deltas are:

```text
import_baseline_rss       = after_import - interpreter
prepared_incremental_rss  = after_runner_prepare - after_import
execution_incremental_peak = peak_during_run - after_runner_prepare
```

The score warmup is outside the latency sample. Full audit/replay is isolated
from score timing. A 100-run prepared-score plateau checks that repeated
runs do not retain growing result state.

Run the standard evidence profile with:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=. poetry run python \
  benchmarks/native_event/benchmark_phase46b_score_rss.py \
  --rows 2000 --repeats 5 \
  --json-out benchmarks/native_event/phase46b_score_rss.json
```

The JSON is evidence, not a universal hardware claim. The Phase 61 companion
benchmark is the current static Rust-primary gate:

```bash
PYTHONPATH=src poetry run python \
  benchmarks/native_event/benchmark_phase61_static_rust_primary.py \
  --bars 10000 --repeats 5
```

It records direct typed-kernel, cold compact-adaptation, and prepared
Python/Rust score timings separately. The benchmark gate is the prepared score
route, not the public pandas-report facade. On the recorded local fixture it
achieved `1.34M bars/s` Rust versus `56.5k bars/s` Python (`23.74x`) with no
observed score RSS increase; reproduce it on the target host before comparing
hardware.

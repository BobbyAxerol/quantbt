# Generic Python Callback Audit Regression

## Conclusion

The regression was real, and it was concentrated in the new independent audit
projection, not the optimized numeric co-runtime. This patch reduces public
100k-bar generic callback audit time by **65.3-65.9%** and isolated peak RSS by
**43.1%**, preserving the complete current audit contract.

It does **not** restore historical `v1.1.0` speed: current full audit remains
44.9-52.8% slower than the actual tag on these cases. Do not call this historical
performance parity, a WFO acceleration, or a generic Rust callback benchmark.
Prepared numeric R1/R2/R3 results are deliberately excluded.

## Measurement

- Date: 2026-09-07; Linux x86_64 VPS, four virtual Intel Xeon Platinum 8171M CPUs.
- Same CPython 3.12.13, NumPy 2.2.6 and pandas 2.3.3 environment for all lanes.
- Three independent subprocesses per lane/case; sequential, interleaved lanes.
  No test suite or parallel benchmark was launched during measurement.
- The original `benchmark_reactive_session.py` fixture is unchanged: same data,
  callback, fee, leverage, matching, report level and timed public call.
- Input data construction is excluded by that historical fixture. Imports and
  data allocations still contribute to process peak RSS. RSS is sampled before
  parity hashing, with the complete public result still retained.
- `reference`: current execution code with frozen pre-patch trace and ledger
  builders from `ea7f7c5`. This is the exact-output before/after comparison.
- `v1.1.0`: actual source at tag `e1c6834`, not an old JSON stored in that tag.
  That callback route did not attach the new canonical ledger/trace/replay.
- Source hashes, import paths, all raw samples and parity results are retained
  in [the JSON artifact](../../benchmarks/native_event/results/generic_callback_audit_closure.json).

The earlier quoted 3.55/3.82-second and 386-MiB figures came from the saved Phase
43A baseline. Its same-process high-water RSS is not directly comparable to
isolated per-case peak RSS below. The tag rerun confirms the regression without
relying on that historical artifact's labeling or memory methodology.

## Public Timings

Median wall seconds; audit lanes retain every requested artifact.

| Workload | Actual v1.1.0 | Before patch | After patch | Current throughput |
| --- | ---: | ---: | ---: | ---: |
| 100k bars, low orders | 3.701 s | 16.284 s | **5.655 s** | 17,682 bars/s |
| 100k bars, high churn | 4.296 s | 18.268 s | **6.226 s** | 16,063 bars/s |
| 25k bars, parent/OCO | 1.261 s | 4.357 s | **1.678 s** | 14,903 bars/s |
| 25k bars, GTD | 1.258 s | 4.391 s | **1.662 s** | 15,038 bars/s |
| Prepared score, 100 x 5k bars | 18.484 s | 19.510 s | 19.913 s | 25,109 bar-visits/s |

Prepared score does not execute the changed audit projection. Its roughly 2.1%
sample difference is reported, not advertised as an improvement. This patch
does not address the remaining generic callback/score runtime overhead.
Three samples support a median comparison, not a reliable tail-latency claim.

## Memory

Median isolated peak RSS, including the Python process/import floor:

| Workload | Actual v1.1.0 | Before patch | After patch | Retained RSS after patch |
| --- | ---: | ---: | ---: | ---: |
| 100k low orders | 223.4 MiB | 537.9 MiB | **305.9 MiB** | 287.3 MiB |
| 100k high churn | 227.3 MiB | 544.9 MiB | **310.2 MiB** | 292.9 MiB |
| 25k parent/OCO | 174.4 MiB | 256.3 MiB | 197.3 MiB | 194.3 MiB |
| 25k GTD | 173.1 MiB | 254.9 MiB | 195.8 MiB | 192.7 MiB |
| 100 prepared scores | 152.7 MiB | 157.3 MiB | 157.5 MiB | 157.5 MiB |

Current full audit intentionally retains more data than the old tag. Removing
those outputs or comparing its peak against scalar-only scoring would not be
a valid remedy for this regression.

## Root Cause And Fix

The first 5k-bar cProfile sample spent about 81% of public callback runtime in
`_attach_reactive_accounting_trace`. The previous builder performed per-bar
pandas lookups and retained dense lists of dictionaries for symbol/account
snapshots and the 34-field canonical trace. Fingerprinting serialized every
field repeatedly in Python; DataFrame fingerprinting copied row dictionaries.

The fix is limited to audit construction:

1. `TraceColumns` preallocates typed columns. Dense account snapshots are aligned
   once; sparse lifecycle/fill/liquidation rows retain their original order.
2. SHA-256 serialization works in bounded blocks, sharing repeated encodings.
   Field order, little-endian representation, Python rounding, normalized NaN,
   negative zero, schema and all raw financial values remain unchanged.
3. The independent ledger applies the same fill arithmetic in the same order,
   broadcasting unchanged cost basis between fills and retaining MTM every bar.
4. The generic DataFrame fingerprint helper streams records instead of retaining
   a second full list of dictionaries. Full trace replay remains enabled.

There is no endpoint/config change, no matching or strategy-state modification,
no default routing promotion, and no Rust/ABI change. Source/root mirrors match.

## Correctness Gate

The new differential tests freeze both pre-change implementations as independent
oracles. They check exact frames including dtypes/order, fingerprints, event
counts, replay, ledger invariants, same-bar multiple fills, reversals, funding,
non-unit contracts, liquidation, empty/missing/unsorted calendars, multi-symbol
snapshots, NaN/zero/infinity, block boundaries and retained-output ownership.
Real callback tests cover parent orders, GTD and minimal/audit accounting parity;
minimal still intentionally omits Fill objects.

The 36 audit benchmark runs additionally match complete accounting hashes and
order/event/fill counts across all lanes. Before/after current-code audit runs
also match ledger hashes, canonical trace hashes/row counts and replay results
exactly. The other nine runs are prepared-score controls; the historical
fixture checks their terminal score summary, not retained per-bar audit paths.

Focused shared-boundary regression: **218 passed in 226.41 seconds**. This covers
the new tests, `tests/native_event/contract`, the Phase 54A.5 differential corpus,
Phase 52B ownership/cache audit, Phase 57 trace/oracle, Phase 77.3 reactive parity
and PERF-06 audit retention. Source-mirror and whitespace checks also passed.
Rust was not rebuilt and the full installed-wheel matrix was not rerun: no Rust,
ABI, dependency, packaging or public API changed in this patch.

## Reproduction

```bash
git worktree add --detach /tmp/quantbt-v110-reactive v1.1.0
poetry run python benchmarks/native_event/benchmark_generic_callback_audit.py \
  --tag-source /tmp/quantbt-v110-reactive --repeats 3 \
  --output /tmp/generic_callback_audit_closure.json
poetry run pytest -q tests/test_generic_callback_audit_regression.py
```

The reference builders are test fixtures only and are not production fallbacks.
This mitigation is usable locally after parity checks, but does not by itself
authorize a merge, public release, or a claim that all performance debt is closed.

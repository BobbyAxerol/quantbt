# Reporting Performance Follow-Up

Owner-authorized reporting-only optimization on 2026-10-07. Baseline `24ad469`;
the [registered scope](../../upgrade/implement.md#metrics-met-03), G01..G05 and
[public reporting contract](PUBLIC_REPORTING.md) apply. No endpoint/default,
financial execution, metric formula, scientific objective, sampler/RNG, Rust
ABI, release version, remote workflow or publication changes.

## Changes And Safety

- Construct one final account snapshot/hash with derived returns, rather than
  hash the same account again before adding returns. Hash format is unchanged.
- Reuse contiguous snapshots only when their ultimate owner is immutable
  `bytes`. A readonly flag or readonly memoryview over mutable storage is not
  sufficient; such inputs still get a private snapshot. Even bytes-owned storage
  gets an independent ndarray header, isolating caller shape/dtype mutation.
- Avoid full-scope boolean-index and all-bar fancy-index copies. UTC ns clocks
  need no redundant resolution conversion; s/ms/us clocks still normalize.
- Validate and pack the request's boolean tuple once into canonical 0/1 bytes,
  adding one byte per return. Constructor cost is measured, not hidden.
- Plot observed equity from the same local immutable snapshot used to reduce
  metrics. No second read, persistent account cache or financial replay.
- Public cache hits still snapshot/hash changed result inputs. Missing ledgers,
  valuation or return witnesses still yield documented N/A or explicit errors.

Initial 1M snapshot profiling found duplicate SHA work, copying and tuple
conversion dominated. An intermediate implementation passed all gates but
increased constructor cost with NumPy packing; it is preserved, not relabeled
as final-source evidence. Native `bytes(bool_tuple)` packing retains identical
bytes after strict boolean validation. The final source is separately qualified.

## Measurement Contract

Pinned CPython 3.12.13, NumPy 2.2.6, pandas 2.3.3 and Numba 0.65.1; one thread,
one warmup/five measured repetitions, fresh sequential worker per cell. Same
hourly equity, scope, partial-period witness, requested episode detail and JSON
serialization before/after. Exact SHA256 of the entire report (including
provenance/episode rows) and input identity must agree for all six account and
six recorded trade/action cells. Python/Numba stay explicit, not auto-selected.

Full public, request construction, request+report, mutable cache-hit, snapshot,
reducer, legacy default, compilation and RSS are separate measurements. The
host is not exclusive; five-sample p95 is noisy. Stage medians are not additive.
These timings are reporting, not backtest/WFO execution speedups; smaller
legacy scientific dictionaries are a different workload.

## Absolute Final-Source Cost

This independent 12-cell run measures the entire opt-in public report with
requested episodes and a reused immutable request. It is not added to the
separately measured snapshot/reducer stages.

| Account marks | Python p50 / p95 | Numba p50 / p95 | Peak RSS Python / Numba |
|---:|---:|---:|---:|
| 2,000 | 9.139 / 9.546 ms | 1.809 / 1.952 ms | 201.29 / 305.27 MiB |
| 100,000 | 316.497 / 320.122 ms | 21.869 / 23.207 ms | 169.46 / 265.55 MiB |
| 1,000,000 | 3.168 / 3.309 s | 177.952 / 243.112 ms | 286.44 / 373.51 MiB |

Numba first reduction including compilation: 5.84-6.13 seconds. The 2k RSS row
also includes matplotlib drawing; memory scaling cannot be inferred from it.
Mutable-input public cache hits still cost approximately 1.09/14.09/150.23 ms
at 2k/100k/1M on Numba workers. A direct snapshot call with a raw tuple mask is
about 0.80/20.46/194.22 ms; the public request's mask has already been prepared.
Serialization alone at 1M and matplotlib drawing are still meaningful costs.

| Recorded population | Python p50 / p95 | Numba p50 / p95 |
|---|---:|---:|
| 32 closed trades | 2.737 / 3.990 ms | 2.467 / 2.682 ms |
| 2,000 closed trades | 14.705 / 14.962 ms | 21.976 / 27.098 ms |
| 2,000 legs / 1,000 closed actions | 17.940 / 18.841 ms | 10.995 / 11.765 ms |

The 2k Numba trade-report cell is worse, not dropped from the evidence. Its
matched baseline comparison is measured separately; reducer language does not
guarantee a gain for every population or host state. No threshold/repetition
change, hidden fallback or automatic backend promotion is used.

## Matched Baseline Comparison

Exact full-report SHA and input identity agree in **all 12 cells** against
`24ad469`, including every requested episode and recorded trade/action control.
These measurements are independent of the absolute table above.

| Account marks / reducer | Before p50 / p95 ms | After p50 / p95 ms | Peak RSS before / after MiB |
|---|---:|---:|---:|
| 2k / Python | 8.560 / 10.165 | 9.313 / 11.501 | 166.80 / 155.77 |
| 100k / Python | 349.164 / 378.729 | 320.940 / 336.018 | 183.72 / 168.42 |
| 1M / Python | 3423.440 / 3560.293 | 3103.374 / 3237.883 | 347.82 / 288.18 |
| 2k / Numba | 2.115 / 2.150 | 1.821 / 1.947 | 251.56 / 253.62 |
| 100k / Numba | 38.168 / 40.054 | 22.157 / 27.292 | 269.63 / 265.80 |
| 1M / Numba | 315.899 / 344.960 | 182.206 / 183.859 | 428.70 / 371.25 |

At 1M, Numba full report is **42.32% less time / 1.73x faster**, with peak RSS
down **57.45 MiB / 13.40%**. Request+public report is 362.418 -> 227.065 ms;
request preparation itself remains 44.922 -> 51.085 ms (extra immutable mask),
so the gain is not solely moved setup work. Cache-hit public reporting is
289.054 -> 146.329 ms while still rehashing mutable input. Python 1M median
improves 9.35%; Python 2k is worse. No uniform speedup is claimed.

| Population / reducer | Before p50 / p95 ms | After p50 / p95 ms |
|---|---:|---:|
| 32 trades / Python | 2.548 / 4.085 | 2.657 / 4.043 |
| 2k trades / Python | 15.230 / 15.736 | 16.004 / 24.901 |
| 1k actions / Python | 17.545 / 17.664 | 17.038 / 17.230 |
| 32 trades / Numba | 2.625 / 2.796 | 2.407 / 2.667 |
| 2k trades / Numba | 9.520 / 10.295 | 8.121 / 10.085 |
| 1k actions / Numba | 11.051 / 12.298 | 10.816 / 12.740 |

All timings, including worse cells, are retained. Unchanged legacy defaults
also exhibit worker-history variance: 1M late Numba-worker median 61.059 ->
74.085 ms, despite exact unchanged source/default outputs. Same-process original
legacy-body controls are recorded separately in the absolute receipt. No
algorithmic regression or universal non-regression is inferred just from those
noisy timings; the slower observation is not hidden or erased.

## Qualification

Final source regression: **716 PASS, zero failures/skips**; 49 new ownership,
SHA, scope/daily, Python/Numba, mutable-cache and plot cases. Raw accounting,
WFO/meta objectives/selection/RNG and 325 protected-source guards pass. Source
modules for execution, scientific definitions and Rust remain unchanged.

The primary tooling environment's native 0.4.2 mismatch was recorded as a
failure, not a skip or fallback. Qualification uses isolated native 0.4.3
consumers; the primary environment is unchanged. Two further failed shape/dtype
aliasing repros are retained; independent ndarray headers correct both without
copying bytes or changing hashes. No reproduced in-scope correctness defect
is knowingly left open; this is not proof that every possible bug is absent.

Final source and matched comparison PASS:
[source receipt](evidence/met03/run-20261007T215523607051Z/receipt.json),
[absolute benchmark](evidence/met03/run-20261007T215523607051Z/benchmark.json),
[matched benchmark/profiles](evidence/met03/run-20261007T215523607051Z/performance.json).
Exact wheel and sdist installed consumers **PASS outside checkout**, including
dependency checks, all 275 module hashes, correct unchanged native 0.4.3,
resolution/action/header/cache cases and plotted public example:
[installed receipt](evidence/met03/run-20261007T220807135175Z/receipt.json).

| Retained core artifact | SHA256 |
|---|---|
| `quantbt_engine-1.1.2-py3-none-any.whl` | `37e6620acec1cd71aafa7c5b9e39a78faf13bff78ef9a17dbbf8188763c2c451` |
| `quantbt_engine-1.1.2.tar.gz` | `39e6302748252fc6aa987bc4530e5946acde50e067ffe7997b7d7d0a17dc16c6` |

Artifacts remain under `.maturin/met03/run-20261007T220807135175Z/dist/`.
The [closure](evidence/met03/performance-closure.json) verifies old/new evidence
and original/recheck artifact hashes, source guards, privacy and cleanup;
MET03-T01..T10 PASS, owner final acceptance PENDING. No CI/push/publish.

## Cleanup

Only the three fresh source consumers, final build/sequential installed
consumers and their nested comparison scratch are removed. Focused test images
are retained with hashes before removing exact owned pytest scratch. The first
cleanup inventory rejection (one generated internal symlink) is preserved;
only that exact link and target were subsequently approved in the inventory.
All new/old artifacts, snapshots, failed/passing receipts and logs remain.

Peak installed scratch: 14,886 concurrent files / 694,102,339 apparent bytes,
below the registered 20k / 3 GiB limits. Final package cleanup increased available
space by **13,037,568 bytes**; the 1,373,285,390 hard-linked lifetime bytes are
not freed-space claims. Copying then deleting retained images reclaimed no net
bytes. Primary environment, offline cache, unrelated temp/data and Rust caches
are untouched. Read the [cleanup record](../maintenance/MET03_CLEANUP.md).

## Remaining Boundaries

No universal latency or RSS guarantee, nor claim of exhausting all possible
optimization. Immutable SHA256, requested episode serialization, Python scans,
Numba import/JIT floor and matplotlib rendering still cost time. Reporting V1
has Python/Numba reducers; native scientific metric V2 remains a distinct
contract. Missing executed-ledger coverage cannot be optimized into invented
trades/actions. Remote/public qualification is separately owner-gated.

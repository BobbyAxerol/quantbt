# Reporting Copy, Cost And Handoff Closure

Owner-authorized reporting-only follow-up, 2026-10-08. Read the
[registered scope](../../upgrade/implement.md#metrics-met-03-copy-performance-closure),
[contract](REPORTING_CONTRACT_V1.md) and [public guide](PUBLIC_REPORTING.md).
No engine/raw accounting, scientific metric, WFO selection/RNG, endpoint
default, Rust/native bytes, release-pair or remote/public change.

## Snapshot Correctness

The review reproduced a real defect: default NumPy deepcopy/pickle made an
account snapshot's equity writable while preserving its old derived identity.
Changing equity from 110 to 80 could reuse cached +10% instead of fresh -20%.
This was reporting/cache correctness, not an incorrect engine equity path.

- Account, nested return, execution, reporting result and retained drawdown
  episode value objects now reconstruct through their validated constructors
  after shallow/deep copy and pickle protocols 0-5. Immutable bytes may be
  shared, but each ndarray gets an independent shape/dtype header.
- Derived identity is recomputed from restored content. New serialization
  omits derived hashes; historical dataclass state also revalidates all fields
  and ignores the serialized derived identity. Invalid/incomplete state fails.
- Equity/data writes and `setflags(write=True)` on restored snapshots fail.
  A deliberate new snapshot (`dataclasses.replace`) with final equity 80 has
  a different identity, a cache miss and the independently expected -20%.
- Nested request/cache copies and retained episode buffers are tested. No
  rehash-on-every-typed-cache-hit workaround or persistent engine cache is added.
  Public mutable-result adaptation still snapshots/hashes current input.

Pickle is for trusted same-library state only; this does not make untrusted
pickle safe. Portable JSON remains the cross-process/public artifact format.

The corrected pre-fix repro retains 33 failures/7 passes. The first exploratory
XML also contains a fixture sampling mismatch and is not a clean defect count.
98 focused snapshot/cache cases pass after the fix. Python scalar-access
experiments exposed two extreme-finite overflow regressions; both original
failures are retained. Preserving NumPy scalar-power semantics fixes them
without changing estimator, undefined policy, tolerance or output arithmetic.

## Cost Changes

The Python scans use zero-copy memoryview scalar access rather than repeated
NumPy scalar construction. Account downside-power still uses NumPy semantics;
Numba receives its original array inputs. Ledger streak scans and single-member
holding times avoid unnecessary scalar/generator overhead, preserving sorted
population order and floating-point accumulation. Requested detail is retained.

Pinned CPython 3.12.13, NumPy 2.2.6, pandas 2.3.3, Numba 0.65.1. The following
full public opt-in reports include snapshot/hash, reduction, episode rows and
dictionary adaptation: one warmup/five samples, fresh sequential worker/cell,
one thread. Strategy, backtest/WFO execution and cold compilation are separate.

| Account marks | Python p50 / p95 | Numba p50 / p95 | Worker peak RSS Python / Numba |
|---:|---:|---:|---:|
| 2,000 | 6.435 / 6.828 ms | 1.728 / 1.826 ms | 202.11 / 300.85 MiB |
| 100,000 | 206.818 / 225.768 ms | 21.284 / 22.589 ms | 168.77 / 266.43 MiB |
| 1,000,000 | 2.111 / 2.165 s | 183.730 / 186.878 ms | 286.52 / 373.12 MiB |

Numba throughput: 1.16M / 4.70M / 5.44M observations/s. First account
compilation/reduction costs 5.30-5.80 seconds, outside this warm table. The 2k
worker also draws a plot, so RSS rows are not a memory-scaling forecast.

| Recorded population | Python p50 / p95 | Numba p50 / p95 |
|---|---:|---:|
| 32 closed trades | 2.814 / 3.739 ms | 2.498 / 2.774 ms |
| 2,000 closed trades | 11.242 / 11.784 ms | 6.497 / 7.053 ms |
| 2,000 legs / 1,000 closed actions | 15.688 / 26.441 ms | 10.882 / 11.664 ms |

## Controlled Before/After

Two warmups and 30 alternating before/after repetitions per cell, one pinned
CPU and one observed BLAS/OpenMP thread, same hourly fixtures, contracts,
requested detail and entire JSON/episode/input hash. The worker loads each
sealed parent under a private namespace, with no checkout or engine change.
All 24 cells have exact output SHA equality before and after timing.

This paired measurement exercises the production cold adapter/reducer/metadata
pipeline; endpoint forwarding is unchanged and independently tested. It is
not a fresh-worker end-to-end RSS comparison. Each paired worker's RSS includes
both versions; isolated current RSS is reported above. The host is not exclusive;
finite samples, especially p95, cannot certify universal non-regression.

Against the immediate pre-fix source `dc12427`:

| Population / reducer | Before p50 / p95 ms | After p50 / p95 ms | p50 speed ratio |
|---|---:|---:|---:|
| 2k account / Python | 8.270 / 18.064 | 6.335 / 9.681 | 1.31x |
| 100k account / Python | 323.527 / 399.952 | 207.397 / 225.448 | 1.56x |
| 1M account / Python | 3165.378 / 3491.616 | 2081.022 / 2324.083 | 1.52x |
| 32 trades / Python | 2.487 / 2.777 | 2.400 / 2.502 | 1.04x |
| 2k trades / Python | 15.491 / 17.223 | 11.592 / 12.650 | 1.34x |
| 1k actions / Python | 19.352 / 21.937 | 16.740 / 18.164 | 1.16x |
| 2k account / Numba | 1.747 / 2.359 | 1.783 / 2.451 | 0.98x |
| 100k account / Numba | 17.608 / 19.466 | 17.868 / 23.667 | 0.99x |
| 1M account / Numba | 166.522 / 177.328 | 165.102 / 178.472 | 1.01x |
| 32 trades / Numba | 2.438 / 3.342 | 2.431 / 2.932 | 1.00x |
| 2k trades / Numba | 7.995 / 10.436 | 6.880 / 10.562 | 1.16x |
| 1k actions / Numba | 11.667 / 14.214 | 11.413 / 13.533 | 1.02x |

Against the earlier optimization baseline `24ad469`:

| Population / reducer | Before p50 / p95 ms | After p50 / p95 ms | p50 speed ratio |
|---|---:|---:|---:|
| 2k account / Python | 10.946 / 26.368 | 7.460 / 19.252 | 1.47x |
| 100k account / Python | 330.650 / 440.887 | 201.150 / 220.662 | 1.64x |
| 1M account / Python | 3346.899 / 3497.445 | 2087.918 / 2312.538 | 1.60x |
| 32 trades / Python | 2.715 / 3.008 | 2.498 / 3.006 | 1.09x |
| 2k trades / Python | 17.567 / 19.646 | 12.725 / 13.946 | 1.38x |
| 1k actions / Python | 18.576 / 28.454 | 16.066 / 18.392 | 1.16x |
| 2k account / Numba | 2.246 / 2.703 | 1.841 / 2.020 | 1.22x |
| 100k account / Numba | 36.454 / 39.068 | 18.847 / 22.000 | 1.93x |
| 1M account / Numba | 319.356 / 337.141 | 164.557 / 204.131 | 1.94x |
| 32 trades / Numba | 2.679 / 4.967 | 2.549 / 3.165 | 1.05x |
| 2k trades / Numba | 9.257 / 12.786 | 7.315 / 8.908 | 1.27x |
| 1k actions / Numba | 12.055 / 14.862 | 11.410 / 13.729 | 1.06x |

The Python workloads targeted by this pass improve in the controlled comparison.
Small Numba account p50 is 1.5-2.1% slower versus the immediate parent; 100k
Numba p95 is 21.6% worse. The absolute action Python p95 is also high. These
observations are retained, not called PASS under an invented noise exemption.
No universal speed or 1-10 ms claim, backend promotion or further methodology
change follows from this benchmark. There remains optimization headroom.

Same-process legacy controls execute the exact original `864b38a` scientific
body versus current default, a separate smaller output contract. At 1M,
medians are 82.393 -> 81.982 ms in Python workers and 67.643 -> 68.269 ms in
Numba workers. Exact legacy outputs and protected source remain equal; this
is a variance control, not a gain for changing the scientific definitions.

## Source Qualification

**785 affected tests PASS, zero failures/skips**: independent metric oracles,
new round-trip/extreme cases, Python/Numba, stable reports/plots, actual raw
route and mature WFO/meta objective/selection/RNG preservation. This is the
registered affected suite, not a claim of running every repository test.
325 protected sources PASS: 321 exact byte hashes and four unchanged legacy
cold-method AST bodies. Execution and scientific arithmetic are unchanged.

- [Source receipt](evidence/met03/run-20261008T162715710901Z/receipt.json).
- [Full public cost](evidence/met03/run-20261008T162715710901Z/benchmark.json).
- [24 paired cells, raw samples and profiles](evidence/met03/run-20261008T162715710901Z/copy-review-paired.json).
- [Corrected pre-fix repro](evidence/met03/copy-review-valid-repro.xml),
  [scalar overflow repro](evidence/met03/copy-review-scalar-repro.xml) and
  [full metrics-only rerun](evidence/met03/copy-review-metrics-final.xml).

Both exact-source wheel/sdist consumers **PASS outside checkout**, with pip
dependency checks, all **276 module hashes**, public example/plot,
timestamp/action/header/cache cases and copy/deepcopy/pickle protocols 0-5.
The new focused snapshot module is included in both artifacts. Historical
275-module receipts remain unchanged, not relabelled as this source's proof.

Read the [installed receipt](evidence/met03/run-20261008T164803809338Z/receipt.json)
and [sealed closure](evidence/met03/copy-review-closure.json), which verifies
current core/native identities, all three historical evidence seals and their
artifacts, 325 protected sources, privacy and cleanup. MET03-T01..T10 PASS.
Owner final review remains PENDING, including the resource variance below.

| Retained core artifact | SHA256 |
|---|---|
| `quantbt_engine-1.1.2-py3-none-any.whl` | `055860bbf6402da5a3e14ee48c41d8b74acd894582841179aad3180500b7da35` |
| `quantbt_engine-1.1.2.tar.gz` | `13950cf904ca0397609b40a4c053d5792c1b2c5c95e762c6a75a1d4b8d5d912d` |

Artifacts: `.maturin/met03/run-20261008T164803809338Z/dist/`.
Unchanged native wheel SHA256:
`f5fe1ec4d9268752733ba2c7023cc0e2548215986a8cd73fb6fafb285422a3b6`;
actual loaded extension:
`e338a0f1549395211dc42332ed15eb43c0bb92f71728ca3181b0268f56a57aba`.
The [release handoff](../meta_selection/RELEASE_HANDOFF.md#reporting-local-closure)
now links to these current reporting receipts, not a historical seal alone.

## Resource Disposition

The [focused cleanup receipt](evidence/met03/copy-review-focused-cleanup.json)
records a transient operational miss: overlapping focused/source environments
reached 24,805 files versus the aggregate registered 20k limit. The inactive
focused environment was removed before paired timing, reclaiming 7,036,928
actual bytes with evidence hashes preserved. This is not silently exempted or
relabelled budget PASS; owner final review includes that variance.

The source lane's 12,446 files / 649,018,042 apparent bytes is within its own
budget; its final cleanup recovered 10,874,880 actual bytes. Environments,
paired archives and pytest/JIT/plot scratch have ended their owned lifetimes.
The sequential installed lane peaks at 14,890 files / 694,119,388 apparent
bytes, within its own registered limits. Its final cleanup observes 13,045,760
extra free bytes; the 1,373,311,981 apparent hard-linked lifetime bytes are
not a physical reclamation claim. Keep all old/new receipts, failing repros,
exact artifacts and offline/tooling dependencies. Read
[cleanup](../maintenance/MET03_CLEANUP.md).

No reproduced in-scope snapshot correctness defect is knowingly open. This
does not prove every possible bug absent or exhaust all performance work.
Owner acceptance, current-source remote/manylinux qualification and public
proof remain separate, unrun gates; no push or publication in this pass.

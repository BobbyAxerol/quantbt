# Phase 46D: Market Ownership And Rust R2 Hot State

Phase 46D follows sections 6–9 and patches F4/F5 of the dual-backend guide.
It reduces avoidable allocation and ownership overhead without changing the
public event contract or silently changing execution semantics.

## Ownership contract

`PreparedMarketCore` copies the validated NumPy inputs exactly once into
Rust-owned immutable `Box<[T]>` arrays. The Rust session retains an `Arc` to
that prepared object, but it does not retain the source DataFrame, Series, or
temporary NumPy arrays. Callers may release those Python inputs after runner
construction; the prepared Rust session remains executable.

This is intentionally a safe copy boundary. Phase 46D does not borrow NumPy
memory unsafely and does not claim that source Python arrays are mutated or
shared with Rust.

## Order table

The old reactive Rust session used a `Vec<ActiveOrder>` and linear
`position/find/remove` operations. R2 now uses:

- primitive `OrderSlot` storage;
- `id_to_slot` for O(1) normal lookup;
- `active_sequence` to preserve command/priority order;
- tombstones for terminal orders, avoiding `Vec.remove` shifts;
- bounded compaction when tombstones become material;
- a fixed stack alias path for replacement-chain resolution and cycle guard.

Slots are not reused while a tombstone still exists in the priority sequence.
This prevents a same-bar replace from appearing twice. They become reusable
after compaction, preserving both performance and lifecycle order.

The static tape adapter translates canonical compiler action codes to the
stable reactive R2 ABI explicitly. This keeps the existing reactive ABI
compatible while preventing a replace/amend code collision at the Rust
boundary.

## Score and audit paths

Score mode calls the same state machine with `materialize=false`. It retains
scalar counters and accounting only; it does not build per-bar fill/event or
active-order ledgers. The PyO3 boundary returns a frozen typed
`BatchedScoreResultCore` instead of a final `PyDict`.

Audit and sparse paths retain their existing SoA arrays and lifecycle events.
They remain the correctness/audit oracle and are not weakened to obtain a
smaller benchmark result. Python converts each returned vector once into a
contiguous NumPy array.

## Command tape cache

`RustBatchedRunner` now fingerprints the primitive command arrays, does not
retain the original compiled command object merely for cache identity, and
keeps at most one tape bounded by `max_tape_cache_bytes` (64 MiB by default).
Use:

```python
runner.clear_tape_cache()
print(runner.tape_cache_bytes)
```

This cache is runner-local, not process-global. Setting the byte limit to zero
disables resident tape caching while preserving one-call execution.

## Verification

Run the targeted ownership/R2 suite:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=. poetry run pytest -q \
  tests/native_event/test_rust_phase46d_ownership.py \
  tests/native_event tests/test_phase46b_score_rss.py
```

The current local run is `60 passed, 2 skipped`; the full repository
regression is `654 passed, 3 skipped`.

Run low/high churn and 100-run reset/RSS evidence:

```bash
MPLCONFIGDIR=/tmp PYTHONPATH=. poetry run python \
  benchmarks/native_event/benchmark_phase46d_ownership_r2.py \
  --output benchmarks/native_event/phase46d_ownership_r2.json
```

The benchmark reports Rust-owned incremental RSS, cache bytes, low/high order
counts, score reset parity, sparse-session reset parity, and peak process RSS
separately. The current 2,000-bar/100-run evidence passed with 40 low-churn
orders and 3,999 high-churn orders; repeated score RSS stayed flat at 0-byte
incremental growth in both profiles, and both cache-clear/reset gates passed.
It must not be read as a total process RSS comparison against Phase 46C's
import floor. Sparse result arrays are returned to the caller on each
`run_until` call, so allocator RSS observed during high-churn sparse reset
loops is reported separately rather than claimed as a session-state
reduction.

Acceptance requires exact audit/score accounting parity, replacement-chain and
cycle safety, prepared-input release functionality, cache clearability, and a
100-run scalar plateau. The next planned phase is 46E; Python full-featured
reactive state remains canonical and is not replaced by this Rust optimization.

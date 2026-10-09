# M5-04 Cleanup

Registered budget: 256 MiB incremental disk, at least 5 GiB free reserve,
one tooling environment and one active numeric worker/thread. A two-thread
synthetic duplicate-query control serializes execution inside one cache owner;
it is not a new financial/adaptive worker pool.

After host process review, only ignored, inactive, reproducible scratch
`.maturin/mode5-m504/attempt-01` was removed first. Its file payload was 4,596,082
bytes; observed filesystem free space increased **6,688,768 bytes (6.38 MiB)**.
Free space afterward was **25,320,890,368 bytes**, above the registered reserve.

**669 protected source/input/history hashes**, **73 retained evidence/harness
hashes** and **12 current diagnostic source/test hashes** were unchanged.
Retained private outputs/harnesses occupied **817,951 bytes** at cleanup.

Final source requalification used a separately registered
`.maturin/mode5-m504/attempt-02`, also removed only after host process review.
Its file payload was 4,565,380 bytes; observed free space increased
**6,094,848 bytes (5.81 MiB)**, with **25,313,468,416 bytes** free afterward.
**743 protected hashes**, including all attempt-01 evidence, **48 retained
attempt-02 hashes** and **12 current source/test hashes** were unchanged.
Retained attempt-02 payload was **680,184 bytes** at cleanup. The sum of the two
observed cleanup gains is **12.19 MiB**, not a claim about all intervening disk use.

Passing/failing receipts, private paths/alpha/data, source/Git, exact artifacts,
primary/tooling environments and dependency caches remain. No service was stopped.

No native/distribution build or environment install took place. Cleanup does
not certify new wheels or economic results. A rerun needs a new registered,
append-only receipt lane and disposable scratch; old receipts are never replaced.

See [M5-04 report](../mode5/M5_04_REUSE_REPORT.md) and
[final source-bound seal](../mode5/evidence/m5-04-final.json). Private append-only records:
`host_process_review.json`, `cleanup_receipt.json`, `phase_source_snapshot.json`
and `technical_closure.json` in the registered M5-04 attempt.

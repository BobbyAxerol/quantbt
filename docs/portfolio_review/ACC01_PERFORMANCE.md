# ACC-01 Measured Overhead

[Synthetic raw measurements](evidence/acc01-performance.json). Baseline checkout
`8f7df9d` includes the prior account repair; final runtime is `70fe9f7`.
Reporting bytes are unchanged since `0969ffe`, when the paired reducer samples
were collected. Core and native versions were not changed.

## Method

One active financial/test/build worker, one numeric thread, two warm-ups and
seven measured repeats per cell. Account/ledger reduction uses the same-process
old/new modules with alternating call order; contracts, immutable inputs and
numeric outputs match. These reducers do not run financial execution.

Public boundary/profile probes run separate processes against exact old/new
core checkouts and the corresponding retained native wheels. Option/package
investigation order is before-A, after-A, after-B, before-B, with two warm-ups,
seven samples and one extra profiled call per cell/batch. Total bounded financial
benchmark calls:170. No research optimizer or alpha economic study ran here.
The fixed mini-WFO regression suites are software qualification, not new alpha
research evidence.

Fresh first-call/JIT timings, sample ranges and peak RSS are separate from warm
medians in the raw receipt. They are not a fresh-process speedup claim: compiler
loading, caches and two module identities differ. Seven samples are finite
engineering observations, not a confidence interval or universal performance
certificate.

## Reporting Results

Warm median milliseconds, paired old/new reductions:

| Cell | Before ms | After ms | Change |
|---|---:|---:|---:|
| Python2k | 2.7572 | 2.7626 | +0.2% |
| Python100k | 90.0410 | 94.9376 | +5.4% |
| Python1M | 956.4641 | 969.4173 | +1.4% |
| Numba2k | 0.7152 | 0.5858 | -18.1%, tiny/noisy cell |
| Numba100k | 1.4669 | 1.4147 | -3.6% |
| Numba1M | 8.0431 | 8.3053 | +3.3% |
| Recorded ledger2k, Python | 5.3493 | 5.7219 | +7.0% |
| Recorded ledger2k, Numba | 5.0658 | 5.0178 | -0.9% |

Cache-hit medians are approximately43-56us before and52-64us after. Most matched
cells add roughly9-10us for constant-size header/child checks. This real overhead
protects immutable identities; it is not an O(N) data rehash. Paired cache misses
are also retained, separately from direct reductions and warm hits.

The [first separate-process observations](evidence/acc01-initial-reporting-observations.json)
showed Python100k+10.8% and Numba100k
about+21%, triggering the registered >10% investigation threshold. The paired
measurements above do not reproduce those slowdowns; their full samples and
the original observations remain retained. They do not justify deleting adverse
samples or claiming every workload is regression-free.

A first paired harness completed all18 account cells but stopped at an invalid
ledger-contract constructor. Its JSON log samples were recovered unchanged;
only the four missing ledger cells were executed after fixing the harness.
The failed receipt remains failed; the completed recovery has its own receipt.

## Execution And Reporting Boundary

| Cell | Before ms | After ms | Interpretation |
|---|---:|---:|---|
| Public close-target2k + legacy full report | 12.0499 | 12.0264 | Financial totals and report values equal; effectively unchanged in this probe |
| Prepared Rust score + cold dictionary | 0.5718 | 0.5789 | No attribution buffer; tiny timing difference |
| Prepared Rust compact + cold dictionary | 0.6342 | 0.6506 | No attribution buffer; tiny timing difference |
| Prepared Rust audit + cold dictionary | 0.7656 | 0.7051 | New requested attribution output; no broad speed claim |
| Option short boundary, first observation | 37.5616 | 42.0945 | +12.1%; required investigation, not hidden |
| Option short boundary, paired batch investigation | 37.7795 | 40.3307 | +6.75%, approximately2.55ms extra |
| Rust basis2k +4,000-row leg report, paired batches | 362.2635 | 261.1389 | About27.9% lower latency on this matched financial control |

The option observation includes additional monetary validation, effective-event
snapshots, currency/provenance and accounting checks. cProfile records280
`finite_number` and58 conversion calls in the short control; direct monetary
validation itself is sub-millisecond, not the whole2.55ms difference. Pandas
report construction remains dominant, and observed before/after ranges overlap
substantially (35.95-52.31ms versus38.56-52.56ms). Thus profiling and reversed
batch order explain a mix of added cold-report work and timing noise, not a
guaranteed fixed penalty or proof of zero regression. The option result now has
two real timestamp rows instead of three with a fake baseline; final equity,
fee/funding and fill count agree on this zero-fee control. Broader fee/time
corrections are covered by the independent correctness tests, not this timing.

The basis probe preserves equity19,929.599075464394, fees80.399917505878 and
funding-10.000019016514 in both arms. It replaces inferred leg accounting with
actual executed buffers and a vectorized cold reducer. The report contract is
corrected/expanded; this is not a claim that every package became27.9% faster.

Rust audit output grows161,608 ->225,608bytes for2,000bars/one symbol, exactly
64,000bytes for four float64 attribution columns. Score stays8bytes and compact
144,008bytes in this payload accounting; neither gains the attribution buffer.
The package consumer uses one financial pass and consumes the private buffer.
Audit is not replayed from a score result. These output-byte counters describe
retained native payloads, not whole-process RSS or all Python object overhead.

Observed warm RSS is flat across the seven repeats in each short boundary cell.
This is bounded retention evidence, not proof that every workload is leak-free.
Cross-process before/after peak RSS is not presented as a memory improvement.

## Disposition

The required nontrivial-cell investigations were completed without weakening
correctness, reducing requested outputs or changing economics. Small real
validation/cache overhead and reporting variability remain disclosed. This
phase is a correctness repair, not a universal speedup promotion. Further
optimization remains possible; full-package/manylinux/public qualification is
still the separately approved M5-12/release work.

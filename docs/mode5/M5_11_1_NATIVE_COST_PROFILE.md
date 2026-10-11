# M5-11.1 Native Tranche Cost Profile

Status: **PASS_READ_ONLY_LIVE_PREFIX_PROFILE / FINANCIAL_RUNS_INCOMPLETE**.
Authority: [native custody cost review](../../upgrade/implement.md#mode5-m5-11-1)
and the guide's [actual work accounting](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử).

## Observed Work

At **2026-10-11 01:07:37 UTC**, both original worker identities were live before
and after capture. Exact complete journal prefixes were copied read-only,
re-read against the original descriptors and sealed separately. Original traces,
requests, sources, accounts, six-hour clocks and workers were unchanged.

| Partial Work | HMA | HASH |
| --- | ---: | ---: |
| Configurations in this cell | 1 | 1 |
| Returned owner passes | 1,081 | 1,134 |
| Returned account-bars | 28,408,680 | 29,801,520 |
| Elapsed lower bound | 11,560.605 s | 11,558.898 s |
| Captured bytes | 10,943,067 | 11,482,925 |

Each returned pass visits the unchanged 26,280-bar continuous 2021-2023 account.
Repeated passes are fixed-point compiler work, not candidate trials or independent
economic replications. Unreturned work is **UNKNOWN_NOT_ZERO**. Neither cell has
a certified final result at this checkpoint. Convergence and remaining runtime
are not inferred from pass counts.

## Cost Attribution

The following values use **exclusive intervals between observer events**. They
sum to the observed elapsed lower bound, including outside-timer intervals;
they are not a claim about CPU time or final-run latency.

| Exclusive Stage | HMA | HASH |
| --- | ---: | ---: |
| Source/resource validation | 6,054.678 s | 6,337.329 s |
| Other pin-validation interval | 123.864 s | 131.438 s |
| Compilation signature | 1,666.293 s | 1,185.925 s |
| Result signature | 1,783.078 s | 2,086.850 s |
| Build | 1,608.077 s | 1,415.666 s |
| Execute | 285.525 s | 364.203 s |

Combined validation represents approximately **53% / 56%** of observed elapsed
time; execute approximately **2% / 3%**. Execute is the existing instrumented
owner-call interval, **not an isolated Rust-kernel benchmark**. Signatures and
the many full feedback passes remain material costs.

The original inclusive timers remain available, but `pin_validation` contains
`source_and_resource_validation`; adding them would double count. HMA ends
inside `build`, HASH inside nested validation. Open stages are censored at the
prefix boundary. Small differences between recorded completed-timer durations
and event-interval attribution reflect instrumentation boundaries, not changed
accounting. No timer faults occurred in either captured prefix.

## Next Action And Custody

A separately registered **cold-only** prototype may investigate redundant
dependency path traversal for future workers. It must preserve original guard
frequency, no-symlink ancestry and file checks, full entry/exit hashing,
nondependency hashing, immutable expected pins, PID lifetime and fault latches.
It cannot patch the active source, accelerate convergence by approximation or
authorize the next tranche. Actual output/capacity gates still precede launch.

Nine pure journal fixtures PASS for nested timing, exact returned-work counts,
censored work, sequence corruption, invalid times and retained faults. Cleanup
PASS retains **22,438,666 bytes before its receipt**, within the registered
64-MiB retained/zero-scratch budget and 5-GiB reserve. No evidence, environment
or cache was deleted. No account, engine, sampler, RNG, retry or worker signal
was executed by this read-only reduction.

Result SHA256:
`874d514e5007b3235b67110a98a02ad5a4998fde37819d185627d0833ff9d9a2`.
HMA prefix SHA256:
`84ceff6d59d2611e3d5fc2a16dbe95982d5f3418bceee38169195e6e96a715b3`.
HASH prefix SHA256:
`2c1916db08640c1a4d35088d83a322a5040eee331a689fcf7c2faf5beab89f79`.

## Cold Traversal Disposition

The separately registered directory-descriptor prototype is
**NOT_BENEFICIAL / NOT_QUALIFIED** and is not activated. There was one matched
experiment with ten verify calls per arm in alternating order, unchanged guard
frequency, full entry/exit hashes and original nondependency verification.

| Measured Cold Work | Original Guard | Prototype |
| --- | ---: | ---: |
| Ten verify calls, total | 5.598815 s | 33.169713 s |
| Verify-call median | 514.934 ms | 3,271.315 ms |
| Entry + own ten calls + exit | 9.005985 s | 36.678042 s |

The prototype reduced descriptor opens but added 2,641,950 ancestry stat checks;
total verify work was 5.92x slower. Its extra namespace-binding checks can also
produce stronger faults than the original, so static cold fixtures are not
universal semantic equivalence or financial parity. No benchmark was rerun to
obtain a positive result, and neither implementation claims a namespace lock.

Exact production filtering reconciles **1,635 guarded dependencies + 130
nondependency records = 1,765 witness pins**. The 1,761 eligible-inventory count
has a different scope; it is not the guarded count. No subset was chosen for
speed. Tests PASS: 29 original fixtures on the original class, the same 29
fixture bodies on the prototype, and 28 additional fixtures. These are separate
implementation scopes, not 86 distinct scientific hypotheses.

Source/witness checks and actual matched timings remain retained. Main review
verified 1,785 unique pins, including original registrations and the completed
handoff. Cleanup PASS removed only the registered owned scratch; current owned
receipt bytes total 1,435,726, within the registered 64-MiB retained budget and
5-GiB reserve. Original guards, active financial workers and environments are
unchanged. This rejects one prototype, not all possible custody optimizations.

Handoff SHA256:
`13070609603d8361a663a30847b1f99e500982466cdf5a97b1aa8de6b89b0797`.
Matched measurement SHA256:
`e2f3b7d23126d4983f714fa733a5aa3b9ed1d46590f4ea382d09fbe8efdb55da`.

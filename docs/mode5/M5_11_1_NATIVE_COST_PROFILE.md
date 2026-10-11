# M5-11.1 Native Tranche Cost Profile

Status: **PASS_READ_ONLY_PREFIX_PROFILE / CAPPED_CONFIGURATIONS_INCOMPLETE**.
Authority: [native custody cost review](../../upgrade/implement.md#mode5-m5-11-1)
and the guide's [actual work accounting](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử).

Current follow-up: the fresh instrumented native04 tranche has closed with
[two COMPLETE checkpoints and censored HASH2](M5_11_1_NATIVE04_CLOSED_CHECKPOINTS.md).
Its actual final signature reconciliation and costs are separate from the
historical native03 prefixes and capped work below. Full panels remain open.

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

## Compiler Mechanism And Scope

Read-only source inspection distinguishes offline admission work from a single
Rust backtest. The unchanged compiler copies a pristine prepared strategy,
rebuilds its full command/decision tape from the previous actual execution's
chronological fill/rejection feedback, and starts another fresh account execution.
Protection commands require actual entry-fill feedback; subsequent decisions
can therefore change when the preceding execution supplies new events. This
dependency is not replaced by hypothetical fills or a signal approximation.

The shared certificate requires consecutive equal **compilation signatures**
(commands, decisions and feedback counts), equal full execution signatures and
complete mapped actual fills. Cycle detection and the declared run limit fail
closed. Compilation stability is not inferred from final equity alone or from
an unchanged number of orders. The original native03 cell requests separately
retain their six-hour safety caps; a capped account remains incomplete evidence.

This explains why the measured fixture can require multiple complete passes;
it does not prove the exact causal frontier, convergence rate or final cost of
either unfinished configuration. The current observer journals stage timings
and account-bar witnesses, not each intermediate compilation/result signature.
Do not claim an observed per-pass frontier or predict the number of remaining
passes from source inspection. Do not label this offline certificate as an
online callback or sparse reactive runtime qualification.

Source authorities are the existing
[feedback certificate](../../tools/mode5_admission/conformance.py) and the
unchanged registered private binding/financial driver. The final financial
receipt must retain the actual iteration witnesses before any convergence claim.
No source, guard, feedback frequency, execution contract, account or worker was
changed by this inspection.

## Closed Cap Work

The original guardian stopped both sessions at 2026-10-11 03:54:51 UTC with
`TRANCHE_TIME_CAP`. Host review and the
[closed custody receipt](M5_11_1_NATIVE_TRANCHE_PENDING.md#closed-cap-disposition)
verify complete retained progress sequences and unchanged original epochs.

| Returned Work Lower Bound | HMA | HASH |
| --- | ---: | ---: |
| Original configurations | 1 | 1 |
| Returned owner passes | 1,846 | 1,914 |
| Returned account-bars | 48,512,880 | 50,299,920 |
| Progress journal rows | 77,568 | 80,419 |
| Final financial result | Unavailable | Unavailable |

These 3,760 returned passes / 98,812,800 account-bars are compiler work, not
trials or independent economic replications. The earlier stage attribution is
still a dated partial profile, not a newly measured full-run decomposition.
Elapsed time at the guardian's first-absence observation is 21,608.063 /
21,606.299 seconds; it includes observation latency and is not an exact worker
wall time. No convergence ETA, final alpha metric, whole-run peak RSS or
Rust-kernel speed claim is inferred. Capped cells require fresh attempts, not
mid-compiler continuation or relabeling the last returned account as a result.

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

## Passive Iteration Witness

A new focused [signature observer](../../tools/mode5_research/iteration_witness.py)
pairs the original already-computed compilation/result hashes and actual
command/feedback/fill counts in the durable journal. It neither computes an
extra hash nor simulates an account. A returned pair is diagnostic evidence,
not a convergence certificate or resumable financial checkpoint. Original
conformance remains the sole fixed-point/cycle authority.

Nine new tests, 69 existing observer and 11 existing conformance cases PASS
(89 total, no failure/error/skip). The real synthetic six-bar account comparison
runs three baseline and three observed passes and preserves the complete
iteration certificate and callback order exactly. Interrupted signatures,
unreturned pairs, journal faults and invalid order remain explicit and latched.
Other suites' synthetic account work is not separately instrumented; none of
these counts is a private-alpha trial or an economic replication.

The registered source-only workload takes 21.900 seconds, peak completed-child
RSS 337.008 MiB. Cleanup PASS removes only 2,142,274 logical owned scratch bytes,
retains 80,989 bytes before its receipt and verifies every source pin. No build,
installation, private-alpha execution or new tranche occurred. The future worker
still needs explicit source-pinned wrapper integration; this does not upgrade
the old capped HMA/HASH journals or prove their convergence.

Result SHA256:
`c2c3b49213c7a0fa8625a70257f0566328eab87eb0d0b4b25dd53a1acdfc3077`.

### Frozen Driver Integration

The [worker-local observer factory](../../tools/mode5_research/driver_observer.py)
uses the frozen driver's existing signature callback pattern; the driver,
financial source and compiler remain unchanged. Ten new cases plus the prior
89 cases PASS (99 total, no skips). The new real paired fixture performs three
baseline and three observed account passes, retaining exact certificates,
guards, call order and work bills. This is separate from the earlier six-pass
witness fixture and is not a total bill for all conformance tests.

Unknown callback/argument shapes fail closed before execution. Independent
workers own separate pending pairs; interrupted receipts retain unknown work
without creating a checkpoint. Wall 21.973 seconds, child peak RSS 336.422 MiB;
cleanup PASS, 2,158,106 logical scratch bytes removed and 82,887 bytes retained
before receipt. A future exact financial registration remains required.

Result SHA256:
`0d2c389a41812c3356d977a9dec98918c06200fa155b0a43b6aa0bfec78abaee`.

## Dependency Epoch Prototype Rejected

The revised epoch prototype passes 91 fixtures, including the same 29 original
fixture bodies on each implementation. On the exact 1,635-dependency and
130-nondependency roster, ten alternating verify calls take 4.363 seconds with
the original guard and 1.440 with the candidate; full entry/verify/exit totals
are 7.431 and 4.557 seconds. These are cold custody timings, not compiler or
backtest speedups.

**Strict safety gate FAIL; NOT_USABLE_NOT_ACTIVATED.** Full-path lookup checks
search permission and symlink traversal but does not repeat the original
O_RDONLY authorization for every ancestor on every path stamp. The synthetic
PASS therefore cannot certify the original authorization-race semantics.
Original guard and FrozenPins remain; the earlier descriptor-leak failure and
both measured source versions are retained. No financial execution, build,
installation or wrapper activation occurred. Cleanup PASS removes only the
two owned scratch lanes and retains 1,953,561 bytes of evidence.

The next bounded tranche uses the original guard plus passive signature
observation. It advances missing points without weakening safety or declaring
the capped compiler passes complete. The 16-GiB capacity gate remains closed.

# Reporting Optimization And Core 1.2.0 Qualification

Date: 2026-10-22, Asia/Saigon. Candidate: **core 1.2.0 / native 0.4.3**.
Current execution status: **TECHNICALLY_VALID_LOCAL_SCOPE**. This is local work,
not approval to push, run remote CI, merge, tag or publish.

## Scope And Identity

The owner requested further reporting optimization and a minor-version upgrade
to reflect the full diagnostics/WFO/meta/account program. Mathematical metrics,
financial execution, account arrays, WFO objectives, Ridge, sampler/RNG,
selection policy and public endpoint defaults are not changed by this follow-up.

The reporting comparison uses committed baseline
`b98c59e77bac6ca50d088589e5cd295680fda406`. Performance code is committed as
`61bfeed`; release metadata and consumer wiring as `67f75bf`; exact source
qualification/tooling as `58eda01`. The current runtime source identity is
`67f75bfbbf06932235e30d9d5ebebb0f7cb0aa0f`, with 466 qualified paths.
The [append-only source amendment](../maintenance/evidence/m5-12-release120-source-amendment.json)
admits exactly twelve changed source/metadata paths. Unknown bytes and other
financial/native changes are rejected. Earlier source amendments and receipts
are not rewritten.

The [earlier M5-12 report](M5_12_REPORT_R3.md) certifies its original 1.1.2
candidate scope, not these new artifacts. Parent economic research acceptance
and its measured improvements, trade-offs and inconclusive observations retain
their original meaning. This performance study neither adds independent OOS
evidence nor changes a scientific gate/default.

## What Changed

1. Primitive report metadata avoids recursive `dataclasses.asdict` traversal.
   Exports remain fresh independent dictionaries; non-primitive values and
   subclass fields retain the original recursive/deepcopy behavior. Contract
   JSON, field order and identities are unchanged.
2. Finite-value account/drawdown scans avoid repeated Python `max` dispatch,
   preserving comparison ties, scalar arithmetic order and NumPy downside
   overflow semantics. Explicit Python and Numba remain distinct choices;
   no backend is silently substituted.
3. Closed-ledger reason counts use one pass plus sorted keys, rather than a
   full population scan per distinct reason. Outcome ordering, leg allocation,
   costs, shared adjustments and requested details are unchanged.
4. Core metadata, lockfile, canonical product registry, generated contracts and
   API inventory now declare 1.2.0. Native remains 0.4.3. Public QMS gates also
   recognize the new pair; they cannot silently disappear after the bump.
   Installed domain consumers verify actual distribution/module/contract
   identities instead of reporting hard-coded 1.1.2 values.

The generated Rust descriptor embeds the core version and product fingerprint.
Therefore native was rebuilt at **0.4.3**, not reused by version match. Its
only Rust source change is generated product metadata; financial kernel bodies,
ABI, Cargo lock, default features and numeric capabilities are unchanged.

## Matched Complete-Report Cost

Two warmups, 30 alternating before/after samples per cell, one pinned CPU,
observed numeric pools of one thread, identical synthetic completed results,
immutable request reuse, full requested episodes and metadata. Recorded ledger
fixtures include the mandatory valuation horizon and actual available closed
populations, not an unavailable fast path. Every cell has exact full JSON,
episode, input-identity and contract-identity hash equality before/after timing.

All values below are milliseconds, p50 / p95. The high-cardinality rows are
stress controls, not a claim about ordinary trading ledgers.

| Workload | Backend | Before | After | p50 Ratio |
| --- | --- | ---: | ---: | ---: |
| 2k account marks | Python | 6.565 / 7.255 | 5.269 / 5.968 | 1.25x |
| 100k account marks | Python | 205.884 / 227.958 | 155.656 / 167.449 | 1.32x |
| 1M account marks | Python | 2028.301 / 2117.650 | 1483.228 / 1635.606 | 1.37x |
| 32 closed trades | Python | 2.635 / 3.172 | 2.585 / 2.936 | 1.02x |
| 2k closed trades | Python | 12.364 / 14.724 | 11.084 / 13.359 | 1.12x |
| 1k closed actions / 2k legs | Python | 16.759 / 18.567 | 15.387 / 16.768 | 1.09x |
| 2k distinct close reasons | Python | 334.470 / 354.744 | 14.476 / 15.910 | 23.11x |
| 2k account marks | Numba | 1.968 / 2.122 | 1.962 / 2.291 | 1.00x |
| 100k account marks | Numba | 19.779 / 21.647 | 19.635 / 22.001 | 1.01x |
| 1M account marks | Numba | 169.273 / 195.871 | 168.907 / 199.238 | 1.00x |
| 32 closed trades | Numba | 2.713 / 3.700 | 2.623 / 3.282 | 1.03x |
| 2k closed trades | Numba | 8.760 / 10.136 | 8.259 / 10.283 | 1.06x |
| 1k closed actions / 2k legs | Numba | 13.113 / 14.743 | 12.240 / 13.919 | 1.07x |
| 2k distinct close reasons | Numba | 317.310 / 411.063 | 11.301 / 12.464 | 28.08x |

The Python 1M p50 reduction is about **26.9%**. Numba account medians are
essentially flat; p95 is worse in the 2k/100k/1M account and 2k-trade cells.
Those observations remain in the evidence, not excluded under a post-hoc noise
rule. Small percentage differences are not evidence of a universal improvement.
The host is not exclusive and finite-sample p95 is descriptive.

The paired worker peaks at **354.16 MiB RSS including both implementations**;
this is not an isolated before/after RSS reduction. First calls include imports
or compilation effects but are not cold OS/page-cache measurements. Strategy
execution, full WFO optimization and compilation are not included in warm
reporting ratios. The benchmark executes zero backtests and zero optimizer
trials; qualification tests separately include bounded real engine calls.

Raw samples, source hashes, exact report hashes and thread telemetry are in the
[public paired evidence](../metrics/evidence/release120/paired.json), with an
identical original retained in the private qualification lane.
The public benchmark tool is
[benchmark_reporting_120.py](../../tools/metrics/benchmark_reporting_120.py).

## Correctness And Consumer Gates

| Scope | Recorded Result |
| --- | --- |
| Focused numeric/snapshot/serialization/ledger suite | 509 passed, zero skips |
| Version/pair/consumer-failure propagation | 89 passed |
| Broad reporting and provenance suite | 1,486 passed; four original failures retained |
| Targeted recovery and new native-policy controls | 94 passed; includes all four original failing nodes |
| Exact wheel consumer | 44 feature cases, 34 new reporting cases and 19 pct/alias cases passed |
| Exact sdist consumer | 44 feature cases, 34 new reporting cases and 19 pct/alias cases passed |

The four initial failures are one real native execution test loading the
primary environment's old 0.4.2 extension, plus three historical source-guard
expectations. Recovery uses the exact newly built extension, explicit current
source qualification and separate historical normalization. No runtime error
was hidden by a skip, old guard relaxation or primary-environment replacement.
Original failing logs/XML remain intact; passing recoveries are new receipts.
Counts overlap between suites and are not independent statistical samples.
Two additional wrapper failures are retained separately: a child-log filename
collided with its outer runner, and the pct tool received a relative lane where
an absolute canonical path is required. Neither launched its intended child
tests. Fresh attempts corrected only the wrapper/path; both passed without
changing runtime, test counts or thresholds.

Independent `asdict`/JSON/order/identity oracles test primitive values, subclass
fields, nested mutable extras, stateful float/string deepcopy, detached exports
and metadata mutation. Ledger tests preserve reason counts, sorted populations,
cost attribution and action grouping. Existing oracles cover numerical extremes,
bankruptcy, undefined policies, drawdown clocks, copy/pickle/header safety,
cache behavior, actual completed routes and mature WFO reporting invariance.
Strict source tests reject extra/mutated paths, changed manifests, unauthorized
metadata/native changes and incomplete installed-verifier custody.

No broad claim of rerunning the old entire M5-12 matrix is made. Current work
recertifies the affected reporting/version/product boundary and exact new
archives, reusing unchanged financial-kernel scope explicitly. The new artifact
proof is not a re-labelled 1.1.2 receipt.

## Exact Local Artifacts

| Artifact | SHA256 |
| --- | --- |
| `quantbt_engine-1.2.0-py3-none-any.whl` | `18531ea2323b5397bc816f280dd2f4291956c86a9e439eb9b62620edb27ebdf6` |
| `quantbt_engine-1.2.0.tar.gz` | `ca42eff2e5ab39d3508e92cdafba007e17c0088588e15d934353e4508c15d1c7` |
| `quantbt_native-0.4.3-cp312-cp312-manylinux_2_34_x86_64.whl` | `60935ce1e1f6c424f7188317b98b3301a7a7e0beafd392d98c315fd935c13854` |

Native extension SHA256:
`b89c011eebb8e317939bedd71b1dd9e02f56f1a525e1240cbe10efe4b68ed439`.
Artifacts and the exact build/source proof are retained in
`.maturin/qms08/m5-12-release120/cp312/`. Native build used offline/locked,
one job and default Cargo features; elapsed build time is 73.30 seconds.
Runtime origins, inventory hashes and native capabilities are checked outside
checkout. No alpha source or private research payload is included in archives.

## Resources, Limits And Next Step

The registered serial build/consumer forecast is 896 MiB plus 5 GiB disk
reserve; native metadata build has a 192 MiB sublane. Source profiling/benchmarks
reuse primary tooling, with phase-owned scratch and separate retained evidence.
The primary installed native remains untouched. Build peak RSS/disk are not
inferred from net filesystem deltas or source-test RSS.

Terminal cleanup removes the exact completed build environment, wheel/sdist
consumers, extracted native overlay and phase-owned fixture/JIT scratch after
host-process/hash review. Five external temporary fixture roots are retired
after retaining all 239 regular payloads in a verified 1,714,986-byte archive;
symlinks are recorded, not followed. Scientific evidence and old/new artifact
bytes are not deleted. Immediate terminal free-space readback is
6,305,210,368 bytes, about 5.87 GiB. Private phase evidence occupies about
6.5 MiB and the retained current artifact/staging lane about 13 MiB; these are
not build peaks or a claimed overall disk/RSS reduction.

The [source/artifact/consumer seal](evidence/m5-12-release120.json) records final
privacy/docs/static checks, exact receipts and their hashes. Original owner
changes, alpha/guide/scientific evidence and all old/new artifacts remain
protected. Cleaned consumer environments require fresh installation to rerun;
their receipts describe actual completed execution, not a live installed env.

Remaining external gates are current-source Ubuntu 22.04/24.04 x CPython
3.11-3.13, release manylinux qualification, owner-approved merge/tag/publication
and eventual public consumer proof. Local manylinux_2_34 is not Ubuntu22.04
or the release manylinux matrix. There is no new endpoint, automatic routing,
default model/selector promotion or promise that all optimization is exhausted.

Reproduce the reporting comparison from a fresh output directory:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  .venv/bin/python -B -m tools.metrics.benchmark_reporting_120 \
  --baseline b98c59e77bac6ca50d088589e5cd295680fda406 --output <fresh-output-dir>/paired.json
.venv/bin/python -B -m tools.m5_12_source_guard --check
```

Rollback: revert the reporting optimization through a reviewed change or disable
the opt-in reporting path; use an independently approved compatible pair for
execution. Never mix old generated descriptors and new core metadata by forcing
version checks, or relabel old native wheel bytes as this new candidate.

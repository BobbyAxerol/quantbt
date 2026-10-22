# Local Debt Closure And Meta Effectiveness

## Status

Owner-approved local follow-up on `feat/meta-selection-samplers`, 2026-10-04;
completed 2026-10-05 (Asia/Saigon).
Four local gates are complete: prepared witness reuse, measured numeric
dispatch, observed thread telemetry and sequential W3 meta integration.
The protected Gradient RSI notebook, loader, alpha/data, account conventions,
methodology defaults and published `1.1.1/0.4.2` pair are unchanged.

No push, merge, tag, release, deployment or PyPI action was performed.
Owner review and remote/public qualification remain separate, unapproved gates.
Private qualification retains `1.1.1+qms08/0.4.3.dev4`; new artifact hashes bind
the changed Python source, not the archived QMS08 wheel bytes.

Read [the unified local plan](../../upgrade/implement.md#qms-local-debt-closure---owner-authorization-2026-10-04),
[verified aggregate evidence](../../benchmarks/optimization/meta_selection/qms_local_closure_evidence.json),
[integration contract](INTEGRATION.md) and [original pre-patch report](REAL_ALPHA_REVIEW.md).
Detailed guide sections [8](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
[10](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10)
and [14](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14)
remain authoritative.

## Correctness Before Performance

The new full-study off/active runs were compared against their pre-patch saved
outputs, without another optimizer or financial scorer in the verifier:

- 3,584 attempts per arm: 3,531 COMPLETE, 53 duplicate PRUNED, zero FAIL.
- Exactly the same trial params, objectives, resolved seeds and selected params.
- All 3,531 original IS metric witnesses and 459 forward labels are byte-exact.
- Candidate pools, frozen panels, label status, economic identity and input/
  result hashes are unchanged. No observations are dropped for speed.
- Positions, equity and returns have maximum absolute difference **0** for
  both off and active. All account report values also match exactly.
- Observer failures: zero. Existing future-suffix, as-of snapshot, no-current-
  OOS-selection, full-pool and original-account checks pass.
- Previously recorded off/shadow, active Rust/reference and independent 28-
  segment frozen replay proofs remain archived. This follow-up reran full off
  and active; it does not pretend all four full arms were rerun again.

Wall-derived computation/publication timestamps legitimately change when work
gets faster. They are checked for causality, not claimed to be identical wall
durations. The metric/result witness hashes, panel membership, labels, RNG
sequence and applied decisions are exactly preserved.

## Exact Prepared Reuse

The existing prepared WFO context owns one immutable market-row hash array and
bounded calendar/header SHA states. No result, account, strategy or RNG is
cached. Actual equity, return and position buffers are hashed on every observed
evaluation. Unknown/copied frames use the original reference signature path.

Volume, schema/order, dtype, timestamps, funding Series, economic/metric/input
identity and initial capital remain part of the relevant exact keys. Tests
cover timezone/nanosecond precision, integer-versus-float capital, incomplete
results, source/funding mutation, bounded eviction and success/error/cancel
cleanup. Mutation fails explicitly instead of reusing a stale result.

Measured active run: 7,493 header hits / 56 misses; 7,520 market hits / 29
misses; zero reference fallbacks and zero evictions. The finalization snapshot
has 85 entries / 50,996 counted retained bytes, plus 303,744 row-hash bytes.
Those counters precede release; `closed=false` in that snapshot is not a live
cache-retention claim. Separate lifecycle tests verify clearing arrays/entries
and closing the owner on success, cancellation and failure. Cache limits are
256 entries / 8 MB of retained key/hash material, not a whole-process RSS cap.

## Real-Alpha Cost

Registered protocol is unchanged: ETHUSDT 1h, 37,968 bars, 28 monthly folds
January 2022 through April 2024, rolling 365D IS, Mode 4 / `per_fold_causal`,
128 attempts/fold, seed 731, no early stopping or warm start. Native medoid,
top 10%, one IS subperiod and the original trade penalty are unchanged.
Meta retains minimum 12 matured origins, lambda 10 and Q floor -0.10.

Financial authority is **Numba**, identical in both arms. Qualified compiled
Rust handles meta transform/fit/rank under `require`; this is not an all-Rust
financial WFO speed claim. Legacy fee 0.0005 remains canonical one-way
0.00025. Funding remains the baseline constant, not historical venue funding.

| Full public study | Before | After | CPU after | Peak RSS after |
|---|---:|---:|---:|---:|
| Meta off | 391.024 s | 366.372 s | 365.187 s | 341.453 MiB |
| Meta active / Rust numerics | 1,086.556 s | 418.501 s | 417.920 s | 356.258 MiB |

Active elapsed time falls **61.48%**, a **2.60x** matched-work improvement.
Meta overhead over the corresponding off arm falls from 695.533 s / 177.87%
to **52.130 s / 14.23%**. After-patch meta adds **14.805 MiB** peak RSS to off.
Active peak RSS was 357.871 MiB before: the 1.613 MiB reduction is small and
is not advertised as a major memory optimization.

Both old and new full studies are one warm observation each, not repeated
medians or cross-platform certificates. Meta-off does not allocate witness
state; its 6.3% timing variation is not attributed to a disabled-feature
optimization. Imports/JIT warmup, input loading and cold JSON export are outside
the measured public execution span. Peak RSS includes retained execution
results, not later private evidence serialization or packaging disk space.

After-patch active fit/select totals **2.468 s** (0.59% of execution);
observer work totals **14.218 s**. Fit/select was 1.342 s before; qualified
telemetry/provenance costs remain charged, not hidden. Sampler time is
81.977 s active versus 79.947 s off. These spans do not explain every public
facade cost, and overlapping measurements must not be added as a partition.

## Does Meta Improve Decay?

Definitions use raw, comparable diagnostic Sharpe, not the trade-penalized
Optuna objective. Each candidate's forward diagnostic starts a fresh account;
these unweighted fold means are not continuous-account Sharpe.

$$
D_n = I_n-F_n,\qquad D_m = I_m-F_m
$$

$$
R = D_n-D_m = (I_n-I_m)+Q,\qquad Q = F_m-F_n
$$

| Mean diagnostic | All 28 folds: native | All 28: meta | 15 supported: native | 15 supported: meta |
|---|---:|---:|---:|---:|
| IS Sharpe | 2.506917 | 1.365583 | 2.517793 | 0.387302 |
| Forward Sharpe | 0.362435 | 0.898718 | -0.567341 | 0.433721 |
| Signed decay, IS minus forward | 2.144483 | 0.466865 | 3.085134 | -0.046419 |

All-fold mean decay decreases **78.23%**. There are 13 native fallback folds
and 15 supported learned folds with actual parameter switches. First learned
selection is February 2023, after 12 compatible matured origins; it does not
fit on that fold's current forward outcome.

On supported folds, mean R is **3.131554**, decomposed into lower IS Sharpe
**2.130491** plus forward improvement Q **1.001062**. Thus roughly 68% of the
decay change comes from accepting lower IS, not better forward performance.
Signed meta decay is slightly negative because forward exceeds IS. A ratio
above 100% here is a sign crossing, not a claim of more-than-perfect prediction.

The registered three-month Moving Block Bootstrap, 4,096 resamples / seed 731,
gives descriptive 95% intervals:

- R: **[1.865070, 4.773345]**.
- Q: **[-0.155061, 2.516381]**.

**Conclusion:** observed decay and forward means improve on this sample.
Q's interval includes zero, so durable forward edge is **not certified**.
ETH/this alpha was already research-exposed; this is not a pristine BTC cell,
independent market replication or live test. No meta policy was retuned after
these outcomes.

## Continuous Account

The existing scalar target account consumes stitched positions with its
unchanged carry semantics; counterfactual diagnostic equities are not joined.

| QuantBT account metric | Meta off | Meta active |
|---|---:|---:|
| Final equity | 29,600.73 | 34,812.73 |
| Total return | 48.00% | 74.06% |
| Sharpe | 0.889175 | 1.191361 |
| Max drawdown | 19.2936% | 14.2702% |
| Trades | 368 | 358 |

These values are exactly unchanged by the performance patch.

## W3 And Numeric Scope

W3 now supports typed Mode 4 / `per_fold_causal` meta on **inprocess,
certified sequential, exact-v2/isolated-v1/reset-flat** native windows. The
same native execution supplies its original streaming objective and retained
result buffers for raw witnesses; there is no second accounting replay.
Meta fit/history/panel/selection reuse the shared module. Selection seals before
current OOS, observer labels mature afterward, and accounts/strategies/RNG are
fresh at diagnostic boundaries. Ordinary meta-off W3 remains unchanged.

Synthetic conformance runs actually execute the installed Rust native engine
on CPython 3.11-3.13 and check objective/account parity, active applied switches,
future mutation, no-variance, failure/cancellation and cleanup. They certify
the software boundary, not profitable reactive-alpha market behavior.
The Delta RSI economic comparison above is the scalar route, not a W3 market
performance certificate. Process/batch/deadline meta transport and dynamic
cross-fold carry remain explicitly unsupported, not silent approximations.

Numeric crossover uses float64, actual native 0.4.3.dev4 and single-thread
OpenBLAS: nine warm repeats of ten calls, all coefficient/decision guards pass.

| Fit shape (N,d) | Rust | NumPy/BLAS | Faster measured fit |
|---|---:|---:|---|
| (180,8) | 0.01885 ms | 0.06805 ms | Rust, 3.61x |
| (4096,8) | 0.33430 ms | 0.25887 ms | BLAS, 1.29x |
| (4096,24) | 1.81528 ms | 0.61519 ms | BLAS, 2.95x |
| (512,64) | 1.49812 ms | 0.32980 ms | BLAS, 4.54x |
| (16384,8) | 1.21618 ms | 0.90255 ms | BLAS, 1.35x |

Auto probes only unfavorable geometry with a bounded eight-bucket disposition;
three same-input parity/timing probes must show >10% BLAS benefit before that
fit block changes. Require remains Rust; reference remains independent NumPy.
Transform/rank stay qualified Rust and near-boundary reference guards are
unchanged. Probe FFI/copy/time is separately charged. The real require run has
60 FFI calls / 1,174,823 copied input bytes, plus three qualification probes;
there is no zero-copy claim or per-candidate native call.

Actual loaded BLAS/OpenMP/Numba pools are observed lazily, independently of
configured caps. In the real run BLAS pools are 1 thread, Numba reports 4,
and the qualified serial meta numeric contract reports 1 native worker.
This is not a claim that every library/financial kernel uses one OS thread.
Missing inspection tools and configured/observed mismatches remain explicit.

## Qualification And Remaining Decisions

Current source, docs, generators, API inventory, benchmark governance, artifact
allowlist and secret gates pass. The fresh core wheel and sdist match staged
canonical Python source byte for byte. Existing native wheels are reused only
after exact staged Rust/product-source and artifact-hash verification; Rust
and ABI did not change. Four installed consumer lanes on each CPython
3.11/3.12/3.13 pass, plus independent installed W3 consumers.

All 64 required QMS IDs pass. The affected regression is **487 passed / 3
explicit POSIX-fork skips**, only where the multithreaded parent makes that
execution unsafe; those are not skipped meta requirements. The aggregate
evidence binds these counts to the actual JUnit and qualification receipts.
Additional expected-value/tamper tests separate economic decomposition and
current artifacts from historical seals. No tolerance or mathematical gate is
weakened to obtain a performance result.

Local approved software debts are closed within the declared routes.
Remote Ubuntu/manylinux qualification, public pair/version activation and
scientific/live acceptance still need owner approval. Unsupported W3 transports
or new account domains are future capabilities, not certified by this follow-up.
Further profiling can still find opportunities; completion does not mean all
possible optimization is exhausted.

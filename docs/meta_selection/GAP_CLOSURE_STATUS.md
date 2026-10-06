# QMS Gap Closure And Remaining Decisions

## Current Scope

Owner request on 2026-10-06 authorizes the bounded E03-G01 legacy-metric
compatibility repair. Read the [execution plan](../../upgrade/implement.md#qms-gap-closure-2026-10-06)
and unchanged guide sections [5](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[8](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8)
and [14](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14).

Correctness, economic effectiveness, domain availability, installed artifacts,
remote runners and publication are independent gates. A failed forward-Q
interval is not a software bug that can be repaired by retuning the study.

## E03-G01 Compatibility

The original array estimator includes zero returns where previous equity is
zero, including liquidation tails and zero-base recovery. The native default
skips those samples. `legacy_zero_base_v1` explicitly selects the original
sampling rule for public prepared endpoint scoring; native request defaults
retain `native_skip_zero_base_v1`. DDOF, annualization, financial execution,
sampler/RNG, penalty/objective formulas and Ridge are unchanged.

Policy is part of request/cache and metric identity. Incompatible installed
wheels fail `require` or produce observable `auto` fallback before scoring.
The repair needs fresh native/core artifacts; old successful small fixtures
and old native wheels cannot certify it. Preserve the failed full-study receipt.
**CLOSED_LOCAL_CORRECTNESS:** fresh native/core wheel/sdist and the full registered
unit replay PASS. Objective/Sharpe maximum difference is `5.773159728050814e-15`;
params/panels/raw labels match and accounting difference is zero. Read the
[executed closure](QMSE03_G01_CLOSURE.md); [the historical assessment](QMSE03_REPORT.md)
and negative economic outcomes remain unchanged. Prepared elapsed was 549.001
to 291.542 seconds (1.883x), with +7.480 MiB peak RSS in this single study.
Its final unit account is flat due to original margin rejection, not economic gain.

## E04 Economic Disposition

The [actual portfolio diagnostic](QMSE04_REAL_DIAGNOSTIC.md) is complete.
Original financial/selected-params replay is exact. Its forward-Q lower bound
is negative: **NOT_PROMOTED**. Better final equity and smaller decay do not
establish reliable forward improvement; 99.69% of the point decay reduction
comes from lower IS Sharpe. Keep the complete negative evidence.

Closing a software release does not require inventing positive performance.
Official route promotion under the owner's E-phase rule requires either a
separately preregistered, sufficiently supported locked evaluation and review,
or explicit owner-approved scope narrowing to software-qualified research.
Do not change the learner, thresholds, ranges, costs, alpha or sampler after
the result and label the new outcome the original test.

## E05 Delivery Basis And Data Admission

Bounded non-expiring basket/basis/stat-pair software and installed tests pass.
The real basis alpha instead needs quarterly delivery, expiry/settlement and
rollover/dynamic hedge semantics. Its reviewed 2025 archives do not provide
the required matured/development/locked origin coverage. No real E05 economic
study is certified. Read [the original E05 report](QMSE05_REPORT.md).

Before admitting quarterly data, record a versioned amendment covering exact
instrument identity/contract multiplier, expiry/settlement timestamp and price,
position and pending-order treatment, roll/cost/funding semantics, calendar
availability and dynamic hedge policy. Use an existing certified execution
authority where possible; no fabricated mark, deleted expiry or fake perp
substitution. Audit actual data coverage and missing outcomes before search.
An unavailable contract/data source keeps the gate **BLOCKED**, not PASS.

## Remote And Public Qualification

The candidate workflow includes installed repaired liquidation proof on both
wheel and sdist for Ubuntu 22.04/24.04 x CPython 3.11-3.13, together with prior
W3/sampler/continuation/scalar/portfolio/package consumers. Workflow wiring is
not a runner receipt. The owner approved feature-only push to `origin` for CI,
not merge/tag/publication. **6/6 PASS** on repair source `6901a66` in
[run 37447291412](https://github.com/BobbyAxerol/quantbt/actions/runs/37447291412).
Each job passed all eleven required steps, including installed G01 and W3.
The [separate API receipt](../../benchmarks/optimization/meta_selection/qms_g01_remote_qualification.json)
retains source/job IDs and uploaded bundle digests. Remote payloads were not
independently downloaded; six bundle uploads succeeded with seven-day retention.
The old `0970d55` receipt remains historical. Later changed source or final
publication artifacts require their own qualification, not automatic inheritance.
The final retention follow-up also archives the exact allowlisted wheel/sdist
binaries, not only proofs/logs, for seven days; its final-SHA gate is separate
from the source-bound API receipt above. No private alpha/data is in that bundle.

Pair remains **quantbt-engine 1.1.2 / quantbt-native 0.4.3**. Public consumer
proof cannot run against an unpublished pair. No merge, tag or upload is
authorized here; follow [release handoff](RELEASE_HANDOFF.md) after approval.

## Separate Capability Decisions

| Capability | Current boundary | Required next contract |
|---|---|---|
| C01 extra meta modes/schedules | Reviewed specs/tests; inactive | Approve native anchor, full-IS witnesses, history cohort and data roles per route |
| C05 conditional Sobol/mixed representatives | Reference/spec only | Approve latent layout, category RNG, admissibility and exact continuation |
| W3 continuous carry | Existing reset-flat route only | Orders/protection/state and parameter effect across fold boundaries |
| W3 shared multi-symbol | No certified financial carry runtime | Shared account, calendars, instruments and admission/margin semantics |
| Public meta batch | Not activated by sampler qualification | Batch seal/maturity/selection and worker ownership |
| W3 Mode 2 bootstrap | No faithful causal return-path bootstrap | Genuine reactive evaluator; never static signal/return proxy substitution |
| Automatic full-WFO recovery | C04 owned journal utility only | Atomic search/model/strategy/account checkpoints and exact failure recovery |

These are not switches to remove from preflight. Each needs explicit bounded
implementation approval and tests through the existing shared architecture.
E06/E07 adapters remain the next separately approved domain work, followed by
E08 integrated artifact/remote handoff. Cleanup remains mandatory after tests;
preserve private alpha, data, logs and scientific evidence.

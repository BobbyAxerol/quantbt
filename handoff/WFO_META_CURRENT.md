# WFO Meta Current Handoff

- Branch: `feat/meta-selection-samplers`; QMS-06 entry `3c69cb8`.
- Baseline: core 1.1.1, installed native 0.4.2; published pair unchanged.
- QMS-01..05 were completed; owner explicitly authorized each advancement.
  Their sealed owner-pending receipts remain immutable historical records.
- Current approved scope: QMS-06 prepared parity and portable handoff, COMPLETE.
- Technical: five gates PASS. Owner/W3-scope acceptance PENDING. Empirical NOT_ASSESSED.
- Performance: MEASURED_COST_ONLY; no whole-WFO speedup, edge or live claim.
- QMS-07/08 remain NOT_STARTED. Do not push, merge, retag, release, deploy
  or advance without separate approval.

## Delivered

Existing `QuantBTEndpoint.walk_forward` accepts optional strict static
`optimization_config["meta_selection"]` and keyword-only runtime
`backtest(meta_history=MetaHistoryContext(...))`. Supported route is Mode 4
`per_fold_causal`, scalar signal_notional/pct_equity, original-result endpoint
scoring or qualified prepared original-pass witnesses, exact aware calendar,
isolated lifecycle and carry-position accounting. QMS-06 qualifies scalar
W0/W1/W2 with existing off/auto/require and prepared-strategy policies.
Same-close is not relabelled next-open. Too-short daily score windows fail.

Actual private candidate 0.4.3.dev2 was compiled/executed without reinstalling
published 0.4.2. The latter lacks the prepared witness: auto records original-result
fallback; require fails. Meta numeric require is independent of financial native
resolution. W3 reactive/reset-flat meta is explicitly unsupported pending optional
scope acceptance; no new reactive account/capture machinery was added.

Complete task/pool/native-reason/decision/model/snapshot/revision handoff and
pure reviewed consumer preserve availability/basis/permissions and distinct
readiness/activation. Cached older model keeps its exact snapshot; a future model
cannot replay an earlier task. Export alone never resets state or sends orders.

Off is the old path. Shadow preserves native search, params, RNG and financial
accounting. Active actually feeds the learned/fallback winner into fold params,
OOS signals and the original continuous account. Full current eligible IS pools
are captured, including authoritative centroid evaluation when needed. Snapshot
is frozen before search; current OOS is never a fit/rank input.

Observer work occurs after seal in independent reset diagnostic accounts with
isolated strategy/RNG. Complete terminal revisions publish only after forward
end plus declared lag/measured completion; later snapshots alone may consume
them. Active same-anchor learned choices still report past-forward-adaptive
selection. Native fallback/shadow do not falsely claim actual historical usage.
Raw/native/meta/actual identities and computation/effect clocks remain distinct.

## Verification

436 checks passed, zero failures/errors/skips, including 46 QMS-06 checks
and actual private QMS-04/QMS-06 Rust candidate execution. Affected optimizer,
sampler, five-mode schedules, nested causal Mode 1, native WFO and research-audit
regressions pass. Forced-switch, future/late-label mutation, centroid/conditional
space/RNG, account fee/funding and result consumers are covered. Hourly/daily
metric, native witness validity, reset/clear ownership, cost/schema compatibility
and portable restore pass.

The public SMA example executes on synthetic 850 daily bars, six quarterly
studies, six trials each. Four learned models and 32 original observer outcomes
are exercised with explicit minimum-support-one engineering override. Native and
reference active runs have identical params/account signatures. Published default
stays twelve origins; these runs do not prove superior future Sharpe.

Coherent local QMS-06 commits: `4635663`, `6fc13b5`.
The documentation/evidence closure commit follows them in this branch.

## Read Next

- [Actual endpoint/config/history and information/accounting contract](../docs/meta_selection/INTEGRATION.md)
- [QMS-06 report](../docs/meta_selection/QMS06_REPORT.md)
- [Executed receipt](../benchmarks/optimization/meta_selection/qms06_gate_receipt.json)
- [Source/cost evidence](../benchmarks/optimization/meta_selection/qms06_prepared_evidence.json)
- [Executed JUnit](../benchmarks/optimization/meta_selection/qms06_tests.xml)
- [Runnable public example](../examples/wfo_meta_selection.py)
- [Portable host example](../examples/wfo_meta_handoff.py)
- [Handoff API and trust/readiness contract](../docs/meta_selection/HANDOFF.md)
- [Ridge/model artifacts](../docs/meta_selection/MODEL.md)
- [Sampler syntax](../docs/meta_selection/SAMPLERS.md)
- [Unified plan](../upgrade/implement.md#qms-06)

No mandatory scalar/prepared or portable-handoff functionality is deferred.
Optional W3 meta scope review is explicit, not a generic reactive success claim.
QMS-07 measured optimization and QMS-08 economic/installed-wheel/public-release
qualification remain separately approved phases. Published package and private
candidate proof must not be conflated; all old receipts remain historical.

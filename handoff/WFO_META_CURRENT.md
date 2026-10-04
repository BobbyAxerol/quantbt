# WFO Meta Current Handoff

- Branch: `feat/meta-selection-samplers`; QMS-05 entry `0be25c7`.
- Baseline: core 1.1.1, installed native 0.4.2; published pair unchanged.
- QMS-01..04 were completed; owner explicitly authorized each advancement.
  Their sealed owner-pending receipts remain immutable historical records.
- Current approved scope: QMS-05 public Mode-4 causal integration, COMPLETE.
- Technical: five gates PASS. Owner acceptance PENDING. Empirical NOT_ASSESSED.
- Performance: MEASURED_COST_ONLY; no whole-WFO speedup, edge or live claim.
- QMS-06/07/08 remain NOT_STARTED. Do not push, merge, retag, release, deploy
  or advance without separate approval.

## Delivered

Existing `QuantBTEndpoint.walk_forward` accepts optional strict static
`optimization_config["meta_selection"]` and keyword-only runtime
`backtest(meta_history=MetaHistoryContext(...))`. Supported route is Mode 4
`per_fold_causal`, scalar signal_notional/pct_equity, original-result endpoint
scoring, exact aware calendar, isolated lifecycle and carry-position accounting.
Prepared/native scalar and reactive qualifications remain QMS-06.

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

392 checks passed, zero failures/errors/skips, including 40 QMS-05 public checks
and actual private QMS-04 Rust numeric candidate execution. Affected optimizer,
sampler, five-mode schedules, nested causal Mode 1, native WFO and research-audit
regressions pass. Forced-switch, future/late-label mutation, centroid/conditional
space/RNG, account fee/funding and result consumers are covered.

The public SMA example executes on synthetic 850 daily bars, six quarterly
studies, six trials each. Four learned models and 32 original observer outcomes
are exercised with explicit minimum-support-one engineering override. Native and
reference active runs have identical params/account signatures. Published default
stays twelve origins; these runs do not prove superior future Sharpe.

Coherent local implementation commits: `ec73f43`, `980cec6`, `b6e8bfd`.
The documentation/evidence closure commit follows them in this branch.

## Read Next

- [Actual endpoint/config/history and information/accounting contract](../docs/meta_selection/INTEGRATION.md)
- [QMS-05 report](../docs/meta_selection/QMS05_REPORT.md)
- [Executed receipt](../benchmarks/optimization/meta_selection/qms05_gate_receipt.json)
- [Source/cost evidence](../benchmarks/optimization/meta_selection/qms05_public_evidence.json)
- [Executed JUnit](../benchmarks/optimization/meta_selection/qms05_tests.xml)
- [Runnable public example](../examples/wfo_meta_selection.py)
- [Ridge/model artifacts](../docs/meta_selection/MODEL.md)
- [Sampler syntax](../docs/meta_selection/SAMPLERS.md)
- [Unified plan](../upgrade/implement.md#qms-05)

No missing functional block remains in the registered QMS-05 route. Prepared
handoff, measured further optimization and final economic/installed-wheel gates
are explicit subsequent phases, not silent technical-debt deferrals.

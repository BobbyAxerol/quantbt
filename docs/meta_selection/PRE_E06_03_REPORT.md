# PRE-E06-03 Nested Mode 1 Runtime

## Scope And Source

Owner approved the reviewed C01 nested scalar cohort on 2026-10-06 (Asia/Saigon).
Entry `ca57fc3`, branch `feat/meta-selection-samplers`; initial runtime commit
`daa69a2`. No release/push, scientific replacement, C05 or broader-domain
activation is authorized. Read [the phase](../../upgrade/implement.md#qms-pre-e06-03),
[approved nested spec](ADDITIONAL_METHODS_REVIEW.md#proposal-a-nested-mode-1)
and unchanged guide [math](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[clock/family](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[ownership](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8).

## Implementation

Only `signal_notional`, `notional`, `unit`, `pct_equity`, signed structural
`dca_ladder` support Mode 1/per_fold_causal meta. Existing exact/isolated/
endpoint/carry guards remain. Default off and public endpoint names are unchanged.

`NestedISPoolCapture` acquires original full outer-IS witnesses after the original
inner study, while original candidate/state is still owned. It retains every
feasible completed adaptive trial plus any separate exact anchor. No auxiliary
observation enters Optuna ask/tell; its RNG is isolated. The native anchor is
the original final inner-decay winner, not highest raw Sharpe or an average
inner metric mislabeled as full outer-IS.

The existing shared runtime freezes history before search, fits/ranks unchanged
origin-sum Ridge, seals before outer forward and applies actual params through
the original continuous stitched account. Existing observer handles independent
reset counterfactuals and publication/maturity. Five exact reviewed runtime files
change; no new Rust symbol, account kernel, sampler or metric estimator.
The nested family binds all inner and decay policies; an executable comparison
against the original `ca57fc3` function verifies Mode 4 families stay exact.

Metadata distinguishes native search/inner decay, original raw outer IS,
prediction and selected params. Unvalidated full-pool choices have explicit
unavailable inner scores; they do not inherit the anchor's trial ID or scores.
Active table adds clear scope columns. Read [configuration/audit guide](NESTED_MODE1.md)
and [runnable example](../../examples/wfo_meta_nested.py).

## Registered Software Protocol

Same PRE02 synthetic daily OHLC/funding tape; no private alpha/data. Historical
tasks start 2020-04-01; outer rolling IS 90D/monthly forward; eight attempts,
seed 731, lambda 10, minimum 12 and Q floor -0.10. Inner monthly expanding folds
start after 30D and require at least two folds. Cutoffs stay 2022/2023/2024-04-30.
No post-outcome tuning or relaxed tolerance; prepared/reference uses 1e-10.

The public actual-runner corpus executes five routes at three cutoffs, with
14..48 VALID permitted origins and actual model fit/rank at all 15 decisions.
Three decisions select a non-anchor candidate; final original account replay
and actual params application match. This is software evidence, not economic gain.

No-leakage controls mutate future OHLCV/funding, future labels/candidate archive,
future model artifact, physical history/pool order and revisions published
during search. Earlier frozen decisions remain unchanged. Permitted correction
is a positive control; equality without proven publication order is excluded.
Original raw Sharpe, sample count/std, validity, activity and cash/equity/account
are checked independently. Off/shadow native ledgers/winners/RNG/account match;
Rust/reference, cached/uncached and prepared/original parity retain their profiles.

## Cost Check

Three fresh-process repeats per off/shadow/active, one identical financial off
warm-up per process; same frozen-history cutoff, eight attempts/seed 731 and
one numeric thread. Original unprepared pct-equity financial endpoint is unchanged;
existing compiled meta `require` uses Rust numeric blocks. Retain full observer
work and all requested diagnostics. This is a small software workload, not
production WFO throughput, real-alpha economics or a Mode 4-to-Mode 1 speedup.

| Arm | Whole public-run p50 | Process peak RSS p50 |
|---|---:|---:|
| Off | 189.61 ms | 229.883 MiB |
| Shadow | 388.25 ms | 229.883 MiB |
| Active | 376.27 ms | 229.883 MiB |

Shadow/active perform three extra full outer-IS evaluations and three observer
evaluations, while native attempted trials remain eight. Full-IS auxiliary is
about 40 ms; model fit/select about 47 ms; observer about 41 ms. Four actual batched
numeric FFI calls plus three independent runtime qualification probes, not
per-bar/model callbacks. Unchanged peak does not prove zero allocations.
Meta adds approximately 98.4% active runtime on this tiny fixture because the
approved method requires extra work. No claim of improved realized decay.

The retained cost-v1 receipt is cold/unverified-history diagnostic, **not** a
fitted cost certificate. The importer correctly refused to trust serialized
verification alone; cost-v2 supplies original output digests and reviewed IDs,
and requires actual fitted default-maturity support. No production guard was
weakened. Historical QMS06 `.dev2` artifact also fails the later G01 metric-policy
guard; regression explicitly binds current 0.4.3 extension/version instead.
Retain all failing harness/artifact logs; never rewrite them as PASS.

## Gate Receipts

Final source-bound counts and cleanup are recorded at phase closure below.
Raw logs/XML/history/cost JSON stay in `.maturin/qms08/pre-e06-03`. Old receipts,
scientific reports and exact artifacts remain unchanged. Fresh current-source
installed wheel/sdist proof belongs to PRE-E06-06; remote/public qualification
is deferred until owner approval. C05 and broader methods remain separate.

## Final Local Conclusion

**PASS_LOCAL_NESTED_SOURCE_CONFORMANCE:** 132 required conformance cells,
three explicit ladder scalar-prepared N/A skips, and 450 distinct scoped
regression/audit/example cases. Total **582 distinct PASS**, not a full-repository
suite claim and not a sum of repeated executions. Final conformance took 162.41 s;
scoped regression 202 PASS, prepared 46 PASS, core 100 PASS, audit 136 PASS and
example/docs 7 PASS overlap as deduplicated in the
[source-bound receipt](../../benchmarks/optimization/meta_selection/qms_pre_e06_03_closure.json).

Exact reviewed source guard covers five runtime files; all 318 runtime files and
verification owners are hashed. The combined 119 historical seal/artifact paths,
original guide and native financial source remain exact. No economic promotion,
new estimator or threshold tuning. Initial native-runtime commit is `daa69a2`;
final record provenance binds the selected trial, never the old anchor's IDs.

The [cost receipt](../../benchmarks/optimization/meta_selection/qms_pre_e06_03_cost.json)
retains every repeat, actual fitted support, FFI/copy/thread telemetry and whole
elapsed/peak values. Current-source installed proof is still PRE-E06-06, not a
new required task silently skipped inside this source phase. Remote/public gates
stay deferred. Read [cleanup](../maintenance/QMS_PRE_E06_03_CLEANUP.md) for retained
failures, resources and no broad deletion.

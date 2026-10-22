# QMS Phase Report - QMS-02

## Source And Scope

Date: 2026-10-03. Branch: `feat/meta-selection-samplers`; phase entry: `5f8a732`.
Released core/native baseline remains `1.1.1`/`0.4.2` at `v1.1.1`,
`2c811a7faaed3c274e93c60650e16207949f0a59`. Editable imports resolve canonical
`src/quantbt`; Optuna 4.8.0, native API 0.4, core ABI 0.5 are unchanged.
Installed optional cmaes 0.12.0 in QuantBT's environment only.

This report implements the approved [QMS-02 plan](../../upgrade/implement.md#qms-02)
and [detailed phase](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#qms-02--sampler-config-bridge-và-parameter-space-correctness),
including guide [section 3](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s3),
[section 4](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s4),
and [section 10](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10).
Guide bytes are unchanged. Measured source hashes and package versions are in
the [evidence](../../benchmarks/optimization/meta_selection/qms02_sampler_evidence.json).

## Actual Work

- Reused canonical `SamplerConfig` and `build_sampler`; no second factory.
  Four recipes resolve to actual Optuna TPE, CMA-ES or QMC objects.
- Added focused `parameter_space.py` and `wfo_study.py` modules. Thin WFO/endpoint
  plumbing leaves endpoint signatures, financial execution, metrics, objectives,
  schedules, bootstrap streams and native authority unchanged.
- Preserved legacy tuple/list/range/scalar syntax. Explicit mapping opts into
  log/step/conditional geometry, unordered categories and canonical identities.
  Numeric warm-seed scalar types cannot create duplicate effective identities.
- Parameter-only violations prune before expensive work; result violations keep
  actual evaluated objectives but cannot be selected. No fake COMPLETE/zero scores.
  Unsupported constrained proposals require explicit post-filter policy.
- Params-only warm starts validate availability/schema/strategy identity, re-score
  on current IS and consume the existing attempted budget. No old objectives,
  sampler covariance transfer, future seeds, extra trials or archive service.
- Recorded actual independent/relative sampling, study seeds/stages, attempted
  states, effective IDs, QMC consumption, timing and ask/tell digests without RNG
  draws or unstable private Optuna introspection.
- Locked cmaes only in optimization/all extras. All prior package versions remain
  unchanged. No Rust source/build/ABI, user alpha, released version or tag changed.

## Methodology And Identity

Eight valid legacy mode/schedule routes are tested, including nested Mode 1 and
Mode 2 proxy/bootstrap behavior. Proposal objects belong to their current study;
global/fold/stage seeds and sequential observation order retain existing contracts.
Omitted config matches the frozen pool, objectives, anchors, downstream params,
stitched signals, accepted positions, equity and financial reports exactly.
A separate 40-attempt TPE fixture exercises adaptive search beyond startup.

Sampler-only opt-in does not change native selection to raw-best, change final
continuous-account stitching, enable meta, or turn retrospective modes causal.
Warm availability is strictly before every participating IS cutoff. No historical
task, corpus revision, learned model, label panel or meta-decision was produced.
Different recipes have different proposal pools: this is not same-pool selector
evidence or observed OOS edge. See [usage and limitations](SAMPLERS.md).

## Tests And Gates

The [JUnit](../../benchmarks/optimization/meta_selection/qms02_tests.xml) records
**228 passed, zero skips/failures, 57.87 s**: 96 Q2 checks plus 132 prior/affected
checks. The [receipt](../../benchmarks/optimization/meta_selection/qms02_gate_receipt.json)
pins the actual JUnit groups and cost/source artifact, with owner acceptance pending.

| Gate | Actual evidence | Status |
|---|---|---|
| G2-SAMPLER4 | Actual installed four-recipe public/stage matrix and margin/dependency checks | PASS |
| G2-SPACE | Integer/log/step/category/conditional/fixed/identity and invalid-space guards | PASS |
| G2-LEGACY | Exact eight-route financial/search parity; adaptive TPE delegate parity | PASS |
| G2-REPRODUCIBILITY | Same-owned-study continuation, arm-independent warm pool, actual QMC consumption | PASS |
| G2-COST | Matched declared budget, repeated deterministic outcomes, public/proposal/evaluator costs | PASS |
| G2-OWNER | No review decision fabricated | PENDING |

Four-recipe native-versus-Python parity compares identical selected parameters,
accepted positions and equity (`rtol=1e-11`, `atol=1e-9`), with zero native fallback
rows. Unsupported configurations fail before strategy/financial evaluation.
Tests cover early pruning, formal and explicit post-filter constraints, failed
trials, warm provenance/budget, inactive duplicates and false test receipts.

Canonical source, docs links, benchmark governance, new-module lint, offline lock
and whitespace checks pass. Warnings are Optuna's exposed experimental-feature
warnings, not suppressed missing capabilities. No full repository suite, Rust
rebuild or wheel/remote-CI gate was claimed; QMS-08 owns final release qualification.

## Performance And Resources

Same public synthetic example: 547 daily input bars; two quarterly folds;
12 attempts per study; seed 731; one worker; reuse off; one warm-up and three
retained timings. Each run has 24 COMPLETE attempts, 26 strategy calls and 98
score calls. Timings include the public facade and final result adaptation.

| Recipe | Warm public median | Sampler methods, last run / two studies | Process peak RSS, last run |
|---|---:|---:|---:|
| tpe_legacy | 360.952 ms | 18.905 ms | 286.535 MiB |
| tpe_multivariate_group | 353.233 ms | 17.461 ms | 288.078 MiB |
| cmaes | 374.030 ms | 24.802 ms | 289.570 MiB |
| sobol | 359.537 ms | 17.840 ms | 294.574 MiB |

RSS is cumulative in one process and includes imports/JIT, not isolated sampler
memory or plateau certification. CPU, RSS/PSS snapshots, all repetitions and
strategy/score/preparation stage costs are retained in the evidence. These
12-attempt/two-dimensional observations do not certify production search quality
or an overhead percentage, and are not comparable to QMS-01's six-trial fixture.
No auxiliary meta evaluations, FFI bridge or numeric financial kernel was added.
Sampling remains Optuna-owned Python; existing financial/backend ownership stays.

## Upgrade Versus Parent

Current canonical WFO/optimizer source necessarily differs from QMS-01; new
evidence hashes it separately. The original baseline, JUnit and sealed receipt
were not regenerated or reclassified. QMS-01's historical verifier now checks
its captured source against the recorded Git entry, while QMS-02 locks current
financial files outside the explicit allowed plumbing/package changes.

Implementation probes exposed and corrected first-infeasible-trial logging,
conditional fixed-parent validation and noninvertible diagnostic centroids.
The final regression passes after these fixes. No old failed probe is represented
as a successful financial observation.

## Decision And Scope Limits

Implementation COMPLETE; technical PASS; performance MEASURED_COST_ONLY;
empirical NOT_ASSESSED; owner review PENDING. No open technical blocker remains
within the registered QMS-02 sampler-only scope.

Explicit unsupported contracts: Sobol conditional space; opt-in categorical,
conditional or constrained centroid selection; new persistent sampler checkpoints.
Medoid diagnostics use `centroid_params=None` where inversion is invalid.
Exact continuation is tested only for the same owned in-process study.
Reactive W3 and specialized fixed-batch qualification remain later adapter work;
no new endpoint/resume facility or unsafe pickle loader is exposed.

Next authorized action is owner review. QMS-03 through QMS-08 have not started;
there is no push, merge, retag, publish, deployment or automatic advancement.

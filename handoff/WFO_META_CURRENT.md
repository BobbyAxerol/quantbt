# WFO Meta Current Handoff

- Branch: `feat/meta-selection-samplers`; QMS-02 entry `5f8a732`.
- Baseline: core 1.1.1, native 0.4.2, tag `v1.1.1` unchanged.
- Current scope: QMS-02 shared sampler/search-space bridge, COMPLETE.
- Technical implementation complete; owner review PENDING.
- Empirical: NOT_ASSESSED. Performance: MEASURED_COST_ONLY, no speedup/edge claim.
- QMS-01 advancement was authorized by the user's explicit QMS-02 approval.
- Next authorized action: owner review of [QMS-02 report](../docs/meta_selection/QMS02_REPORT.md)
  and [sampler usage/limits](../docs/meta_selection/SAMPLERS.md).
- Do not start QMS-03, push, merge, retag, publish or deploy without approval.

## Sampler Delivery

Four recipes use the existing factory: legacy TPE, multivariate/group TPE,
CMA-ES and Sobol. cmaes 0.12.0 is installed/locked in the optimization extra;
Optuna and released core/native versions did not change. Defaults retain exact
legacy trajectories across eight routes. The final affected suite has 228 passes,
zero skips/failures, including all 96 QMS-02 checks and installed-native parity.

Opt-in normalized ranges preserve requested/effective identities, explicit
activity and log/step geometry. Warm seeds have pre-cutoff availability plus
schema/strategy provenance and are rescored within budget. Unsupported constraints
require explicit post-filtering; no fake successful scores are created.
Sobol conditional spaces and inadmissible centroids fail preflight. Resume means
the same owned in-process study, not a new persistent checkpoint facility.
The current sampler surface does not enable meta, qualify reactive W3, or prove
economic superiority. Financial ownership and methodology boundaries below remain.

## Boundaries To Carry Forward

Mode 4 causal native selection must remain exact. Capture full eligible search
records before compaction, and integrate the later meta decision before fold
params/OOS materialization. Raw IS Sharpe is not penalty-adjusted objective.
Centroid requires exact same-IS evaluation inside the still-live fold lifetime.
Scalar `volatility=0` and execution-success status do not establish valid labels.
Use train-end selection frontier, not the fold's output cutoff or wall time.
W3 reset-flat qualification is separate from the scalar target-series proof.

No existing financial defect was repaired or hidden. The mandatory metric
support and centroid integration work is explicitly owned by QMS-03/05/06,
not deferred outside this upgrade. No sealed meta history is available yet;
the primary economic study remains subject to QMS-08 budget/data approval.

## Evidence

- [Baseline manifest](../benchmarks/optimization/meta_selection/legacy_baseline_manifest.json)
- [QMS-01 historical receipt](../benchmarks/optimization/meta_selection/qms01_gate_receipt.json)
- [QMS-02 cost/source evidence](../benchmarks/optimization/meta_selection/qms02_sampler_evidence.json)
- [QMS-02 actual test receipt](../benchmarks/optimization/meta_selection/qms02_gate_receipt.json)
- [Reader guide](../docs/meta_selection.md)
- [Unified plan](../upgrade/implement.md#qms-02)

QMS-02 pins measured source/evidence and actual JUnit test groups. QMS-01 remains
an immutable historical snapshot reproducible at `5f8a732`, including its original
owner-pending receipt; it was not rewritten as current-source certification.
The QMS-02 owner gate is PENDING; technical PASS is not authorization to advance.

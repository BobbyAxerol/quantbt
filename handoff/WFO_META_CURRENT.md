# WFO Meta Current Handoff

- Branch: `feat/meta-selection-samplers`; phase entry `e2abce9`.
- Baseline: core 1.1.1, native 0.4.2, tag `v1.1.1` unchanged.
- Current scope: QMS-01 discovery/tooling/tests/evidence only.
- Technical implementation complete; owner review PENDING.
- Empirical: NOT_ASSESSED. Performance: measured baseline only, no speedup.
- Next authorized action: owner review of
  [source/boundary map](../docs/meta_selection/SOURCE_AND_SEAM_MAP.md).
- Do not start QMS-02, push, merge, retag, publish or deploy without approval.

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
- [Actual test receipt](../benchmarks/optimization/meta_selection/qms01_gate_receipt.json)
- [Reader guide](../docs/meta_selection.md)
- [Unified plan](../upgrade/implement.md#qms-01)

The receipt pins source/evidence bytes and actual JUnit test groups. The guide
and all 271 protected runtime/package files remain unchanged. Its owner gate
is intentionally PENDING; technical PASS is not authorization to advance.

# Meta-Selection And WFO Samplers

## Availability

QMS-01 froze source/boundaries/baselines. QMS-02 adds the shared WFO sampler
bridge on the feature branch; see [sampler usage and limits](meta_selection/SAMPLERS.md).
Released core `1.1.1` and native `0.4.2` remain unchanged: the new WFO sampler
field is not in the published release yet. `meta_selection` and `meta_history`
remain unimplemented; sampler configuration does not enable them.

- [Unified QMS plan](../upgrade/implement.md#qms-01)
- [QMS-02 technical report and tests](meta_selection/QMS02_REPORT.md)
- [Detailed methodology and implementation guide](../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md)
- [Verified source, boundaries, clocks and requirement owners](meta_selection/SOURCE_AND_SEAM_MAP.md)
- [Frozen host baseline](../benchmarks/optimization/meta_selection/legacy_baseline_manifest.json)
- [Actual executed tests and gate receipt](../benchmarks/optimization/meta_selection/qms01_gate_receipt.json)
- [Current handoff](../handoff/WFO_META_CURRENT.md)

## Existing Behavior

Mode 4 with `per_fold_causal` selects on each fold's IS and realizes that
fold's OOS after selection. One final account runs over the stitched OOS
signals. Independent fold diagnostic equities are not concatenated into a
portfolio curve. The final parameters represent the last completed fold.

The stock robust selector can select a plateau member rather than the highest
raw IS Sharpe. Its `mean_is_sharpe` is penalty-adjusted. Raw Sharpe and trade
penalties belong to original fold metrics, which compact trial tables drop.

The future meta module must retain the exact stock anchor, score the full
eligible current IS pool, and use only compatible past matured labels. Meta
will be opt-in, off by default, initially for qualified Mode 4 causal routes.
No new account engine, WFO mode or live order controller is planned.

## Reproduce The Lock

The commands below require the QMS-01 snapshot (`5f8a732`), not the later
approved source changes. Baseline and sealed receipt remain immutable historical
artifacts. On the new checkout, QMS-02 tests compare all scientific outputs with
the frozen manifest and check that unrelated financial/native bytes are unchanged.

From the repository root with the existing editable environment:

```bash
env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
  .venv/bin/python tools/qms01_baseline.py --output /tmp/qms01-replay.json
.venv/bin/python tools/qms01_baseline.py --verify
.venv/bin/python tools/qms01_baseline.py --verify \
  --receipt benchmarks/optimization/meta_selection/qms01_tests.xml
```

The manifest contains proposals, raw and adjusted metrics, candidate IDs,
selected parameters, stitched signal, accepted positions, equity, account
contract, evaluator traces and resources. Verification checks the actual source,
required route/budget membership and receipt hashes/test counts. A fresh replay
has different wall times and runtime IDs; compare scientific fields rather than
requiring its complete JSON bytes to match.

The representative strategy is the existing public SMA example on a synthetic
daily tape. Its results are engineering evidence only. There is no sealed meta
history or primary BTC economic acceptance result yet. QMS-08 still requires the
registered market dataset/budget and support counts; this smoke does not certify
edge, a superior sampler, live readiness or a new speedup.

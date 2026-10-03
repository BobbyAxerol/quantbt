# Meta-Selection And WFO Samplers

## Availability

QMS-01 is a source/boundary/baseline lock, not a new optimization feature.
Released core `1.1.1` and native `0.4.2` are unchanged. Do not pass the proposed
`sampler_config`, `meta_selection` or `meta_history` examples to this release:
the WFO runtime does not yet implement them. Generic `OptunaOptimizer` already
has its own sampler factory; that is not a WFO sampler-config bridge.

- [Unified QMS plan](../upgrade/implement.md#qms-01)
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

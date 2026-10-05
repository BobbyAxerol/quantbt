# Meta-Selection And WFO Samplers

## Availability

QMS-01 froze source/boundaries/baselines. QMS-02 adds the shared WFO sampler
bridge on the feature branch; see [sampler usage and limits](meta_selection/SAMPLERS.md).
Released core `1.1.1` and native `0.4.2` remain unchanged: the new WFO sampler
field is not in the published release yet. QMS-03/04 implement history, Ridge
and artifacts; QMS-05 now binds optional `meta_selection` and keyword-only
`meta_history` into the actual public Mode-4/per-fold-causal scalar route.
QMS-06 qualifies original-pass prepared witnesses and complete portable
handoff. Published 0.4.2 lacks this witness; fallback/require and W3 limitations
are explicit, not general reactive/native support claims.
Sampler configuration alone does not enable meta. Start with
[public integration, config and information/accounting contract](meta_selection/INTEGRATION.md).

QMS-07 closes exact reuse and chronological parity with scoped measured gains.
The owner-approved local debt closure adds exact prepared witness reuse,
qualified large-geometry Rust/BLAS dispatch, observed thread telemetry and a
bounded [W3 sequential meta adapter](meta_selection/INTEGRATION.md#w3-sequential-meta).
Sealed QMS-08 receipts remain historical, not a certificate for changed source.

QMS-08 adds [step-by-step usage](meta_selection/USAGE.md),
[software/artifact and economic boundaries](meta_selection/QUALIFICATION.md)
and [complete runnable cases](../examples/wfo_meta_contract.py). Private installed
candidate proof is distinct from public release approval or real-market edge.

- [Unified QMS plan](../upgrade/implement.md#qms-01)
- [Latest local debt closure, costs and real meta-off/on decay](meta_selection/LOCAL_DEBT_CLOSURE_REPORT.md)
- [QMS-02 technical report and tests](meta_selection/QMS02_REPORT.md)
- [QMS-05 public endpoint certification](meta_selection/QMS05_REPORT.md)
- [QMS-06 prepared parity and capability report](meta_selection/QMS06_REPORT.md)
- [QMS-08 final software/package report and debt ledger](meta_selection/QMS08_REPORT.md)
- [Portable decision, trusted restore and host responsibilities](meta_selection/HANDOFF.md)
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

The implemented optional meta module retains the exact stock anchor, scores the
full eligible current IS pool and uses only compatible past matured labels.
Off preserves native behavior; shadow exports a proposal but executes native;
active uses the actual selected candidate on the existing OOS/account path.
Active learned choices are past-forward-adaptive, even when choosing the anchor;
they are not mislabeled as stock IS-only. No current outer OOS enters selection.
There is no new account engine, WFO mode or live order controller.

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
daily tape. Its results and synthetic sealed histories are engineering evidence
only; there is no primary BTC economic acceptance result yet. QMS-08 still requires the
registered market dataset/budget and support counts; this smoke does not certify
edge, a superior sampler, live readiness or a new speedup.

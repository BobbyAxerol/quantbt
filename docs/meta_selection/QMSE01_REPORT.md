# QMS-E01: Audited Provenance And Installed-Proof Closure

## Scope And Authorization

Owner approved E01 only. Entry: `5fecad2`, clean feature branch
`feat/meta-selection-samplers`; prepared pair stays **1.1.2 / 0.4.3**.
Read [the E01 plan](../../upgrade/implement.md#qms-e01) and original guide:
[selection boundaries](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s3),
[native/prepared contracts](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
[reporting](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s12).
No new mathematical method, meta route, financial runtime, alpha research,
push/merge/tag/publication is authorized. C01/C05 activation stays separate.

## Reporting Correction

Global provenance now follows the selected record's actual stage and selector,
not a blanket Mode 2 exclusion. For an optimized global run:

| Actual final selection | Outer OOS selection flag |
|---|---|
| OOS candidate stage + robust_decay or mean_oos_sharpe | true |
| mean_is_sharpe / IS plateau / IS-only robust | false |
| Full-sample Mode 5 | false; full-sample calibration is not forward validation |
| Fixed params/no study | false; diagnostics are not parameter selection |

Mode 2 still searches synthetic bootstrap IS paths and ranks its final default
shortlist with real OOS. Nested Mode 1 uses inner validation within outer IS;
Mode 4/per_fold_causal freezes selection before current outer OOS. Global Mode 4
remains retrospective across its train folds even when direct OOS ranking is false.
No claim certifies arbitrary user-strategy causality.

The sole production edit is the reporting expression in `WalkForwardEngine.run`.
`tools/qms_e01_source_guard.py` restores only that exact expression before older
byte gates. Any other source change fails; no whole-file financial exemption.
Historical C01/R03/C02-C05 receipt bytes remain immutable and retain their
original discrepancy/status observations.

## Installed Proof Contract

`tools/qms_installed_consumers.py` is shared by candidate qualification,
`certify_native_release.py` and `verify_public_native_consumer.py`.
The exact QMS pair requires all four actual consumers, without skips:

1. `qms08_consumer.py`: scalar/prepared/reference/Rust, four recipes, off/shadow.
2. `qms_local_consumer.py --witness-transport`: original-pass process/pool/account
   witnesses, native cancellation tokens, zero per-task market IPC, child cleanup.
3. `qms_c03_consumer.py`: all four recipes, sequential/process/R3B/replay,
   original-pass shadow/active meta, exact pool/account lineage and actual Rust fit.
4. `qms_c04_consumer.py`: four-recipe owned exact continuation in a fresh process,
   including COMPLETE/FAIL/PRUNED states, without financial replay.

Every child uses `python -I` from an external working directory. Source-path
environment variables are removed; BLAS/OpenMP caps are set before imports for
the existing safe-fork contract. No accounting or scientific policy is altered.
Consumer/example/source hashes and full command/stdout/stderr logs are retained.
Nonzero exit, missing interpreter, timeout, invalid JSON, absent evidence,
wrong pair, missing matrix rows or failed parity cannot produce a PASS receipt.
Logs survive failure; immutable receipt/log directories require a fresh suffix.

Candidate CI retains nested proof logs and watches the consumer/example changes.
Exact-release and public workflows retain their new logs too. Candidate matrix
remains contents-read-only; no upload or OIDC permission is added.

## Local Reproduction

```bash
export PYTHONPATH=src:.
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export MPLCONFIGDIR=/tmp
PY=.maturin/qms08/release-regression-v1/bin/python
"$PY" -m tools.qms_e01_audit --output .maturin/qms08/e01-review/after-fresh.json \
  --baseline .maturin/qms08/e01-review/before.json
"$PY" -m tools.qms_e01_package --output .maturin/qms08/e01-package-fresh \
  --build-python .maturin/qms08/release-1.1.2-v2/cp312/build-env/bin/python \
  --python "$PY" --native-baseline .maturin/qms08/c04-package-v1
"$PY" tools/check_docs_links.py --check-anchors \
  --file handoff/WFO_META_CURRENT.md --file docs/meta_selection/QUALIFICATION.md \
  --file docs/meta_selection/RELEASE_HANDOFF.md \
  --file docs/meta_selection/RELEASE_GAP_REPORT.md --file docs/meta_selection/QMSE01_REPORT.md
```

The E01 local builder produces new canonical core wheel/sdist. Native reuse
requires the unchanged artifact hash and all tracked Rust bytes to match the
local C04 source seal. It does not claim a new manylinux build. Consumer imports
must originate from site-packages, not the repository or an editable install.
The regular candidate/release builder still builds fresh native release bytes.

## Gate And Remaining Scope

Local validation is IN_PROGRESS until the final receipt is sealed. Before/after
eight-route search/params/objective/account/RNG parity is exact; 89 focused
provenance/route/source checks pass. These are test costs, not a speed/RSS claim.
No new alpha/economic result is measured in E01.

Final-source Ubuntu matrix, manylinux and public-index qualification remain
pending and belong to E08/owner-controlled release. No earlier remote 6/6 or
private receipt substitutes for them. Domain route adapters/paired real-alpha
decay gates are E02-E07, not implementations hidden by a relaxed guard.
Carry/multi-symbol/public meta batching and additional C01/C05 activation remain
unsupported or unapproved. Scientific study replacement requires separate approval.

# Frozen Ridge V1 Research Comparator

## Authority And Status

Owner-requested freeze, 2026-10-17, Asia/Saigon. Baseline source commit:
`3370baf7b9f74441e8523f742b9c81489f5a5adf`.
Comparator ID: `m4_ridge_origin_sum_v1_l10_m12_qm010`.
The [machine freeze](../../benchmarks/optimization/meta_selection/model_research_v1/ridge_v1_freeze.json)
binds source SHA256, mathematical settings, numeric limits and existing evidence.
This is a baseline specification freeze, not a new fit, market study, binary
qualification or claim that Ridge is the best model. Existing optional overrides
and historical receipts retain their own identities; they are not rewritten.

The [research guide](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md)
and [five proposed phases](../../upgrade/implement.md#m4-ml-research) govern any
later model/calibration experiments. They require separate owner approval.

## Frozen Scientific Contract

| Component | Baseline |
|---|---|
| Learner | `ridge_origin_sum_v1`, no intercept |
| Target | `same_origin_signed_relative_decay_v1`: Y = (IS - FWD)candidate - (IS - FWD)anchor |
| Basis | `qms_anchor_contrast_origin_balanced_v1` |
| Descriptors | Existing effective parameter encoding, raw IS Sharpe, declared optional log1p activity; exact per-family schema retained |
| Scaler | `origin_balanced_zscore_v1`, fit from permitted historical IS records in matured tasks |
| Weights | `one_origin_sum_nonanchor_1_over_M_v1`; each valid contributing origin totals one |
| Loss | Sum of origin-average squared errors + 10 times squared L2 norm |
| Regularization | `lambda_reg=10`; equivalent mean-origin strength is 10/K, not 10 |
| Support | `min_matured_origins=12`; anchors/duplicates/invalid labels cannot manufacture support |
| Guard | Qhat = deltaIS - Yhat; Qhat >= -0.10 |
| Selection | `signed_min_y_predicted_q_floor_v1`; full eligible pool and existing exact anchor/tie/fallback rules |
| Ties | Minimum-based fixed tolerance `1e-10`, then existing distance/canonical-ID rules |
| OOD | `whole_pool_native_fallback_v1` |
| Numerics | Existing float64 Rust/reference policy, limits and whole-decision certification; no tolerance relaxation |
| Execution | Existing domain adapter, metric/account/clock contract and actual selected-parameter application |

Frozen means the learning and decision procedure is fixed, not that beta/scaler
are fitted once on all available history. The baseline still refits coefficients
and preprocessing at each permitted vintage, using only history available then.
The family ID continues to isolate strategy/schema/window/sampler/anchor/
economics/account/metric contracts. No cross-alpha raw-row pooling is authorized.
No future learned model is imported into an earlier decision.

## Reproduction And Comparison Rights

- Verify the manifest and source hashes before comparing. A changed implementation
  must use the archived Git source or a verified compatibility implementation;
  a new version cannot silently replace the baseline behind its old ID.
- Keep original candidate pools, native anchors, observer acquisition panels,
  histories/revisions and cutoff/ready/seal clocks. Baseline and challenger
  receive the same permitted information for their declared comparison.
- Preserve all original alpha routes, financial metrics, fee/sizing/lifecycle
  contracts. Monthly/730D original runs and quarterly/365D intrabar variants are
  separate cohorts, not interchangeable evidence or independent replications.
- Preserve shadow/off behavior and actual baseline decisions. Existing source-
  bound receipts are referenced, not rerun merely to obtain another PASS count.
- A different lambda convention, robust loss, feature map, calibration policy
  or learner requires a new ID. Do not patch `RidgeSettings` V1 to accept it.
- Beta/scaler/model snapshots and full raw dictionaries remain private. Public
  comparator metadata contains settings, code hashes and sanitized receipt refs.

Source freeze does not pin every future environment or qualify an installed
pair. Each executed experiment must bind exact core/native/dependency hashes
and its own source/runtime resolution. No dependency was installed, no model
was fitted, and no CI/release/publication was started to create this freeze.

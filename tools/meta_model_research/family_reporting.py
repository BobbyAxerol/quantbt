"""Cold report rendering from retained, sanitized model-research measurements."""

from __future__ import annotations

from .family_protocol import ROSTER
from .protocol import GROUPS


def number(value, digits=6):
    return "undefined" if value is None else f"{value:.{digits}f}"


def render_screen(summary, result, certificate, measurement):
    if (summary["required_rows"] != 480 or certificate["registered_cells"] != 480
            or any(r["nominees"] for panel in result["nominees"].values() for r in panel.values())):
        raise ValueError("renderer is bound to the registered no-nominee development closeout")
    primary = summary["summaries"]["base"]
    rows = []
    for group in GROUPS:
        base = primary["baseline"][group]["served_loss"]
        values = [
            number(primary["cells"][group][code]["served_loss"]["mean"])
            for code in ROSTER
        ]
        rows.append(
            f"| {group} | {base['n']}/12 | {number(base['mean'])} | "
            + " | ".join(values)
            + " |"
        )
    macro = []
    for code in ROSTER:
        item = primary["macro"][code]
        change = item["paired_vs_P0"]["relative_mse_change_percent_from_matched_means"]
        macro.append(f"| {code} | {number(item['served_loss']['mean'])} | "
                     f"{number(-change if change is not None else None, 3)}% |")
    return f"""# M4-ML-03 - Bounded Family Screening

## Decision

**COMPLETE_LOCAL_REGISTERED_RESEARCH / technical PASS / no qualified nominees.**
Retain V1. All five settings executed on the four original monthly groups;
none was silently dropped or replaced by a faster strategy/endpoint. This is
not a claim Bayesian, Huber or nonlinear models have no economic value.

The [guide](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md#mlr-s4),
[phase plan](../../upgrade/implement.md#m4-ml-03) and
[approved finite protocol](M4_ML_03_PROTOCOL.md) govern this study.
See the [measured aggregates](../../benchmarks/optimization/meta_selection/model_research_v1/ml03_development_results.json)
and [closure](../../benchmarks/optimization/meta_selection/model_research_v1/ml03_closure.json).

## Models And Information Rights

- B1: fixed N(0,I) prior and unit-noise mean-origin power likelihood; posterior
  mean is Ridge with sum penalty K. It is a shrinkage control, not empirical
  Bayes, nonlinear capacity or calibrated posterior certainty.
- H135/H200: existing sklearn 1.8 concomitant-scale Huber, no intercept,
  epsilon 1.35/2.0 and alpha K*10/12. Robustness also changes the loss; it is
  not a numerical optimization of V1's squared-loss solution.
- X2/X3: official CPU-only XGBoost 3.1.1, depth 2/3, 64 rounds, seed 731,
  one thread. Raw weighted-square-error f is trained; **all** served outputs
  are g(v)=f(v)-f(0). Raw training and centered served losses are different and
  retained separately. No claim raw training optimizes centered loss.

The existing origin-balanced scaler, candidate-minus-anchor basis, Y units,
minimum 12 matured contributing origins, Q floor -0.10 and geometry/ties are
unchanged. All current valid IS candidates are ranked, not only labeled ones.
Histories and coefficient fits remain family-compatible; raw feature columns
from unrelated strategy schemas are never pooled.

There are 480 development cells: two acquisition panels x four groups x 12
origins x five settings. Primary base-only and original winner-union sensitivity
are not independent replications. Twelve cost/train-only pilots precede scale;
their current forward outcomes do not select a model. Physical future records
in storage do not grant fit/calibration rights.

## Descriptive Development Loss

MSE is squared relative-Sharpe units, with one origin then equal group weight.
These are reviewed development summaries, **not** new evaluation OOS or full
continuous-account Sharpe. January outcomes remain excluded from nomination
when they were published after the 2024-01-31 23:00 UTC frontier.

| Group | Supported P0 origins | P0 | B1 | H135 | H200 | X2 | X3 |
|---|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

| Recipe | Four-group macro MSE | Reduction versus matched P0 |
|---|---:|---:|
{chr(10).join(macro)}

X2 has the strongest descriptive macro point here, but worsens HMA and has only
two supported VWAP origins. A favorable development mean is not a transferable
recipe certificate. Five tested settings add model-selection multiplicity;
no per-alpha best model is saved after reviewing outcomes. The JSON retains
group-specific MAE/rank/calibration/nulls, winner coverage and conditional
R/Q/IS decomposition. Missing new-winner outcomes are not zero and do not
constitute a full-pool regret oracle. Y/Q squared errors are algebraically the
same measurement, not two independent confirmations.

## Why There Are No Nominees

Strict common calibration excludes the held-out group and requires at least
three valid inner origins per training group plus three complete three-month
blocks with every group/month present. Available calibration support is
SC/HMA/HASH/VWAP=7/11/11/2. Including VWAP fails the origin rule; excluding it
leaves only two complete blocks. This holds for every model on both panels.

Consequently **zero nominees** pass the registered admission, not two forced
winners. Missing/partial blocks are not used to improve a score. M4-ML-04 must
record this scope disposition: no new-family evaluation economics or real
adaptive update is promoted from these data. More support is a future research
decision, not an unfinished implementation silently transferred to release.

## Qualification And Actual Work

The independent certificate verifies {certificate["registered_cells"]} cells,
full-pool candidate/guard/tie decisions and exact effective params. A separate
raw-label audit verifies {measurement["rows_checked"]} scored and
{measurement["undefined_rows_retained"]} undefined cells. Its metric maximum
absolute difference is {measurement["maximum_metric_difference"]}.

One post-screen cache correction adds numeric-limit identity and invalidates
preparation when its budget changes. It does not change mathematics. The
original registered source is archived; ten actual fixed HMA inputs reproduce
the full old artifact IDs on final source. This is a scoped compatibility proof,
not a claim all histories or all future cache configurations were replayed.
Failed synthetic receipts remain immutable; the final source test receipt
records repairs without turning an old FAIL into PASS.

Screen: **{result["fits"]} logical fits**, **{result["regression_fit_charge"]} counted
numeric/reference/qualification fits**, {result["failed_fits"]} failed fits;
{result["portable_restore_checks"]} portable checks. Wall
**{result["wall_seconds"]:.3f} s**, CPU **{result["cpu_seconds"]:.3f} s**,
peak RSS **{result["peak_rss_mib"]:.2f} MiB**. Fit/rank/report timers are
{result["fit_seconds"]:.3f}/{result["rank_seconds"]:.3f}/{result["report_seconds"]:.3f} s.
Cold ingestion/custody is additional real work, not hidden ML kernel time.
Compatibility controls and eight XGBoost backend-qualification fits are billed
separately in closure. Software-test oracles are not novel economic outcomes.

The exact CPU wheel/RECORD/build passed qualification; CUDA/NCCL are disabled.
Private dependency footprint is about 21.4 MiB including wheel and extraction.
The main environment, QuantBT dependencies and all frozen production sources
remain unchanged. No Rust build, optimizer, financial execution, CI, push or
publication occurred. New-library CPU fitting is not advertised as all-Rust.

Ranker and PCA/cluster/OOD controls are synthetic feasibility only: origin
queries must remain intact, rank scores need a separate calibrated magnitude
head for Q, and unsupervised states cannot authorize economic selection.
These alternatives remain deferred, not unfinished production features.
"""

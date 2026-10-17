"""Pure final model-research report, from sanitized retained measurements."""

from .family_protocol import ROSTER
from .family_reporting import number


def render_handoff(summary, screen, decisions):
    if (summary["schema"] != "m4.ml03.development-analysis.v1"
            or summary["required_rows"] != 480
            or screen["schema"] != "m4.ml03.closure.v1"
            or decisions["schema"] != "m4.ml04.closure.v1"
            or screen["decision"] != "KEEP_FROZEN_V1"
            or decisions["decision"] != "KEEP_FROZEN_V1"
            or screen["no_nominees"] is not True
            or decisions["public_activation"] is not False):
        raise ValueError("unsupported or unqualified final research disposition")
    macro = summary["summaries"]["base"]["macro"]
    descriptions = dict(B1="Fixed-prior linear shrinkage", H135="Huber epsilon 1.35",
                        H200="Huber epsilon 2.0", X2="CPU trees depth 2", X3="CPU trees depth 3")
    rows = []
    for code in ROSTER:
        item = macro[code]
        change = item["paired_vs_P0"]["relative_mse_change_percent_from_matched_means"]
        rows.append(f"| {code}: {descriptions[code]} | {number(item['served_loss']['mean'])} | "
                    f"{number(-change if change is not None else None, 3)} | "
                    f"{number(item['y_mae']['mean'])} | {number(item['y_spearman']['mean'])} | KEEP_V1 / insufficient common support |")
    bill = screen["screen_bill"]
    charge = screen["cumulative_research_numeric_fit_charge"] + decisions["numeric_reference_qualification_fit_charge"]
    return f"""# M4-ML-05 - Final Model And Hyperparameter Research Decision

## Decision

**COMPLETE_LOCAL_REGISTERED_RESEARCH / KEEP_FROZEN_V1.** No public learner,
loss, default, sampler, endpoint, accounting engine or native ABI is changed.
Research prototypes remain optional under `tools/meta_model_research`; they
are not new packaged QuantBT learner options. More complex models are neither
promoted nor declared incapable of helping.

The [five-phase plan](../../upgrade/implement.md#m4-ml-research) and
[research guide](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md)
govern this decision. Read the [frozen baseline](RIDGE_V1_FROZEN_BASELINE.md),
[ML-02 calibration](M4_ML_02_CALIBRATION_REPORT.md),
[ML-03 family screen](M4_ML_03_FAMILY_REPORT.md),
[ML-04 actual decision controls](M4_ML_04_DECISION_REPORT.md) and
[machine closure](../../benchmarks/optimization/meta_selection/model_research_v1/ml05_closure.json).

## Model Decision Matrix

Equal-origin, then equal-group primary development summaries; MSE is squared
relative-Sharpe units. Positive reduction is better. These are reviewed,
conditional summaries, not untouched OOS or independent four-alpha replications.

| Recipe | Served MSE | MSE reduction vs matched P0, % | Y MAE | Y rank association | Disposition |
|---|---:|---:|---:|---:|---|
{chr(10).join(rows)}

X2 reduces descriptive macro MSE about 2.59%, but worsens HMA; VWAP contributes
only two supported development origins. Its changed-winner outcomes are mostly
unobserved, so an apparent conditional Q/R gain is not a full-policy effect.
Five tested settings create multiplicity. No per-alpha winner lookup or new
confidence claim is inferred from this table. Full group-specific train/loss,
calibration, rank, nulls and witness counts remain in the
[sanitized measurement table](../../benchmarks/optimization/meta_selection/model_research_v1/ml03_development_results.json).

B1 is a fixed-prior mean-origin power-posterior mean, equivalent to a different
Ridge shrinkage; it does not supply calibrated posterior certainty. Huber changes
the loss and estimates scale. XGBoost trains raw weighted-square f while serving
g(v)=f(v)-f(0) on every row; its raw training surrogate is not its centered served
objective. All three distinctions are versioned/tested, not hidden optimizations.

## General Hyperparameter Semantics

| Procedure | Rule | Current decision |
|---|---|---|
| P0 retained V1 | Origin-sum lambda 10; causal beta refit at each origin; minimum 12 mature origins | KEEP_FROZEN_V1 |
| P1 normalization | Sum lambda K*10/12, fixed mean-origin regularization | Registered gain gate missed; no replacement |
| P2 common offline calibration | One shared leave-group-out lambda rule, frozen before evaluation | Complete-block support insufficient; retain P0 |
| Alternative fixed families | Common B1/H135/H200/X2/X3 recipes, schema-compatible separate fits | Research implementation qualified; no supported nominee |
| Periodic recipe update | Proposed quarterly boundary + new mature matched support + 2% hysteresis | Synthetic control only; no admitted real update |
| Ranker | Origin queries and a separately calibrated magnitude/Q head required | DEFER separate supervised study |
| PCA/cluster/OOD | Causal representation/description, not economic labels | Feasibility only; no unsupervised selector activation |

Fixed lambda does not mean frozen coefficients. Constant mean-origin penalty
does not equal fixed sum penalty. A shared procedure may fit separate compatible
schema models, but cannot choose hyperparameters by held-out alpha outcomes.
There is no silent online hyperparameter tuner, warm start, empirical Bayes,
early stopping or per-alpha adaptive recipe. A future learner needs explicit
target/loss, preprocessing, maturity, update/effective times, fallback, artifact,
validation and cache rights at the existing seam, not a separate account engine.
Nothing in this study claims lambda 10 is universally optimal.

## Evidence And Causal Boundary

Original ETHUSDT 1h monthly730D histories retain 13 acquisition + 12 development
+ 32 evaluation origins. Base-only acquisition is primary; winner union is a
sensitivity, not independent replication or randomized inclusion. January label
availability after the frozen 2024-01-31 23:00 UTC frontier is excluded.
Leave-group-out calibration needs three valid origins/group and three complete
three-month blocks/group. None of eight panel/group nominations meets it.
Partial blocks are not filled with favorable rows and evaluation losses do not
select a new model. Numerical economic family intervals are not fabricated.

Actual mature future/past controls exercise all five families at HMA K=24 and
late K=55. Future corrections cannot change the earlier fresh-fit decision;
allowed past corrections demonstrably change predictions without increasing K.
The existing origin scaler and native numeric path are reused. Exactly zero
anchor, Q floor -0.10, full valid-pool ranking, stable ties and cutoff clocks
remain binding. Y/Q MSE are the same algebraic error, not separate confirmation.

The final retained policy matches {decisions['frozen_P0_rows']} outer decisions
and {decisions['protected_account_files']} protected original account files;
{decisions['P0_non_native_rows']} decisions differ from native anchors. Keeping
P0 retains Ridge selection, not meta-off. No new family schedule, financial
account or actual adaptive update was executed. Zero targeted queries means no
nominee was admitted, not that missing winner labels were magically available.
R/Q decomposition is checked against raw observations; missing or undefined
winners remain explicit. Old positive RSI evidence and four-alpha negative or
inconclusive findings are preserved, not invalidated by another protocol.

## Cost And Compatibility

The finite screen uses {bill['logical_fits']} logical fits, {bill['numeric_reference_qualification_fits']}
numeric/reference/qualification charges, {bill['wall_seconds']:.3f} s wall,
{bill['cpu_seconds']:.3f} s CPU and {bill['peak_rss_mib']:.2f} MiB peak RSS.
Screen, compatibility, backend qualification and ML-04 controls total **{charge}**
counted research solves/fits. Software-test fits and small synthetic public WFO
fixtures are separate verification, not novel economic outcomes. Historical
ML-01/02 work is separately retained; this is not their total cumulative bill.

XGBoost CPU 3.1.1 is a verified private wheel/extraction (~21.4 MiB); CUDA/NCCL
are disabled. One-thread fitting is observed; no main-environment installation,
mandatory dependency or GPU download occurred. Normal source import/Ridge/off
must work without this optional wheel. Python orchestrates batch model calls;
the new library fits are not advertised as all-Rust. Screen time is not a new
full-WFO latency benchmark. Source/native financial bytes are unchanged.
Current source version 1.1.2 with a reused environment whose distribution
metadata is older is not an installed-pair or public-index certificate.

## Handoff

M5-11.7 may consume these fixed decisions/support/null explanations only after
its separate owner approval. M5-12 later qualifies final source/artifacts and
regressions; current research receipts are not its wheel/manylinux/remote proof.
No CI, push, merge, tag, build or publication is activated. Broader study design,
additional supporting origins, a calibrated ranker and unsupervised economic
selection remain explicit future research, not unfinished runtime defects.
All admitted code defects are closed; exact evidence-preserving cleanup and
final tests are recorded in closure. No claim of universally optimal speed,
hyperparameters or guaranteed decay improvement is made.
"""

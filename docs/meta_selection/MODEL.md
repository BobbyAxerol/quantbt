# QMS Ridge And Decision Contract

## Availability

QMS-04 is an internal branch module, not a released public `meta_selection`
endpoint. Public activation and WFO orchestration belong to QMS-05. This page
describes implemented mathematics, not a promise of forward alpha improvement.
The financial endpoint, sampler objective and account engine remain unchanged.

Read [history and descriptors](HISTORY.md) first. The authoritative requirements
are [guide section 5](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5)
and the [QMS-04 plan](../../upgrade/implement.md#qms-04).

## Target And Basis

Each historical origin has exactly one explicitly referenced native anchor.
Use qualified raw Sharpe from original financial reports, never penalized
objective or cluster-average metrics:

\[
D_{k\theta}=I_{k\theta}-O_{k\theta},\qquad
Y_{k\theta}=D_{k\theta}-D_{ka_k}.
\]

Fit the QMS-03 origin-balanced scaler on permitted historical IS candidates
and anchors with matured labels. No forward outcome fits the scaler. Freeze
schema, parameter range/log encoding, categorical vocabulary, conditional masks
and feature order. The minimum descriptor includes parameters, raw IS Sharpe,
and optionally `log1p` of the registered activity count.

\[
v_{k\theta}=\phi_t(x_{k\theta})-\phi_t(x_{ka_k}).
\]

The same vintage applies to historical and current candidates. Anchor contrast
is exactly zero. Categorical blocks retain their fixed weights; no rare-category
inverse-standard-deviation expansion is introduced. Constant or never-observed
numeric support violations produce the registered whole-pool native fallback.
Malformed schema, nonfinite inputs and unknown anchor IDs are errors, not OOD.

## Ridge Origin-Sum

`ridge_origin_sum_v1` has no intercept:

\[
\widehat\beta=\operatorname*{arg\,min}_{\beta}
\left[\sum_{k\in\mathcal A_t}\frac{1}{M_k}
\sum_{\theta\ne a_k}(Y_{k\theta}-v_{k\theta}^{\mathsf T}\beta)^2
+\lambda\lVert\beta\rVert_2^2\right].
\]

Only valid non-anchor labels enter the fit. Each contributing origin totals
one unit of weight, regardless of label count. A correction from one to ten
labels replaces the entire origin with weights `1/10`; it does not append nine
rows to old sufficient statistics. Anchors and failed outcomes cannot inflate
support. Zero-label revisions remain in the exact snapshot provenance but do
not count as matured model-support origins.

\[
G=\sum_iw_iv_iv_i^{\mathsf T}+\lambda I_d,\qquad
b=\sum_iw_iv_iY_i,\qquad G\widehat\beta=b.
\]

Defaults: `lambda_reg=10`, `min_matured_origins=12`. Overrides are explicit and
retained; twelve origins are not a statistical-power guarantee. The equivalent
mean-origin regularizer is `lambda/K`, not `lambda`. Changing to fixed-lambda
mean loss would require another learner version.

The independent reference uses whitened rows and `numpy.linalg.solve`. Native
uses serial float64 accumulation and Cholesky. Neither computes an inverse,
an N-by-N weight matrix, an intercept, silent jitter, or fast-math. Workspace
and shape preflight precede materialization; exceeding budget is an error, not
permission to drop features/origins/candidates.

Registered limits: condition `1e12`, relative residual `1e-10`; parity
`rtol=1e-9`, `atol=1e-10`. The reference Gram/b in the model retains the exact
fit basis as small sufficient statistics, not market paths or all training rows.

## Inference And Guard

Current candidates require only current IS records. There is no current
forward-label input at the inference boundary:

\[
\widehat Y_t(\theta)=v_{t\theta}^{\mathsf T}\widehat\beta,
\qquad \widehat Q_t(\theta)=I_{t\theta}-I_{ta_t}-\widehat Y_t(\theta).
\]

\[
\mathcal E_t=\{\theta:\widehat Q_t(\theta)\ge-\epsilon\},
\qquad \theta_t^*=\operatorname*{arg\,min}_{\theta\in\mathcal E_t}
\widehat Y_t(\theta).
\]

Default epsilon is `0.10` Sharpe points. This is a predicted-relative-quality
floor, not statistical noninferiority. The objective is signed minimum Y, not
minimum absolute gap and not maximum IS Sharpe. The valid anchor has exactly
`Yhat=Qhat=0`; an empty safe set is an implementation/input error.

Ties use a fixed minimum-based set with tolerance `1e-10`, then parameter
distance, canonical candidate digest and evaluation ID. No non-transitive
approximate-equality sorting comparator is used. Winner-only reduction is
linear; full ranking is explicitly requested. Complete numeric predictions and
IDs remain available. `rank_decision(decision)` builds a cold-path full ranking
without financial replay.

For native inference the entire reference fit is solved from retained Gram/b
and the whole current pool is reference-scored to certify the actual decision.
This cost is charged. A `1e-8` boundary band, eligibility/tie/winner disagreement
causes complete reference fallback, never a guessed top-K subset. Coefficient
allclose alone is not winner certification. A large prediction parity failure
raises rather than silently claiming a successful native decision.

## Fallbacks And Clocks

- Too few matured origins: explicit native-anchor proposal; no invented fit time.
- Registered descriptor OOD: whole-pool native-anchor fallback with affected IDs.
- Undefined native-anchor metric: `META_NOT_APPLICABLE_METRIC`, not a zero label.
- Corrupt/nonfinite/unknown identity or schema: typed error, not cold-start success.
- Model inputs after task cutoff or model completion after decision seal: error.

Information cutoff differs from computation completion. A fit can finish after
the cutoff using the previously frozen snapshot, provided it precedes seal.
Restore declares artifact availability separately from the information frontier.
Historical replay and observed-live clocks are distinct; a model built today
from past-only inputs is not proof it was deployed in the past.

QMS-04 `MetaSelector.propose` supports `proposal` or `shadow` only. Proposal
records no executed winner. Shadow retains the native anchor as actual choice;
it does not submit orders. Raw-best, native-anchor and meta-proposed IDs remain
separate. QMS-05 will bind actual choices into existing WFO/account execution.

## Artifacts And Restore

The immutable `MetaModelArtifact` retains coefficients, complete descriptor
schema/categories, scaler/constant/observed masks, basis/target/weight/lambda
versions, family/corpus/cohort permissions, exact revision and fit-row references,
information frontier, real fit completion, wall generation and numeric/support
diagnostics. Raw-unit coefficient slopes require division by this vintage's
scale; coefficients are initially in standardized coordinates.

`MetaSelectionDecision` retains IDs/params, raw IS, Yhat/Qhat, eligibility,
rejections, tie/ranking data, model/snapshot IDs and cutoff/seal/ready clocks.
Model and decision bundle imports use finite strict JSON with closed fields,
size limits, duplicate-key rejection and content digests. Restore requires a
caller-reviewed expected ID and explicit `available_as_of`; a self-hashed payload
does not authorize itself. Weights alone are not a model. Missing scaler,
vocabulary, basis, revisions or unknown winners fail.

## Numeric Backend Policy

`NumericRuntime(native_policy="auto" | "require" | "reference")` is internal
and independent of the financial backend or `native_prepared_wfo`.

The new `qms-numeric-v1` Rust block implements transform, Gram/solve and batch
Yhat/Qhat. Parameter-object encoding, historical scaler fit, diagnostic solves,
reference certification and cold artifact/report adaptation remain explicitly
NumPy/Python. Numeric require means those three declared native blocks are
qualified; it does not claim every orchestration operation runs in Rust.

The feature `qms-numeric-candidate` is off by default in the current crate.
`tools.build_qms04_candidate` stages a versioned `0.4.3.dev1` local wheel and
loads it in a private namespace for evidence. It does not overwrite the installed
0.4.2, alter the published registry, certify financial pairing of this candidate,
or publish a release. The local proof covers Linux x86_64 CPython 3.12 only.
QMS-08 owns final public version/feature/wheel coordination.

Installed baseline 0.4.2 has no QMS numeric capability: auto records NumPy fallback;
require fails. An injected candidate first passes a deterministic numerical
qualification probe. All used blocks, reasons, versions, FFI call counts and
owned input-copy bytes are recorded. Inputs are cloned before `Python.detach`;
this is owned isolation, not advertised zero-copy. Boolean-mask staging and
conversion time are included in wall measurements; owned-copy counters describe
Rust input buffers only, not total process memory.

One historical transform and one fit call cover all origins, not one PyO3 call
per candidate/origin. Current inference uses one transform and one scoring call.
No new Numba variant is added just to duplicate these small blocks; its unused
disposition is recorded. Native numeric performance remains candidate evidence,
not a promoted public optimization when the same-work reference is faster.

## Interpretation And Reproduction

`Y = deltaIS - deltaForward` contains the IS feature in its target. A positive
IS coefficient is not independent proof of forward predictability. Ridge does
not supply James-Stein guarantees, regime recognition, drawdown protection or
edge certification in this phase.

Repository example: `.venv/bin/python -m examples.wfo_meta_ridge`.
Tests and actual-block costs are in [QMS-04 report](QMS04_REPORT.md).
No phase completion implies the still-unapproved public WFO selector is active.

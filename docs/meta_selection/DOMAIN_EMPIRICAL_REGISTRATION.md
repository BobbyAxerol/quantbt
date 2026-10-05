# Domain Meta Paired Study Registration V1

**Template contract:** `qms-domain-empirical-registration-v1`; E02 freezes these
required fields, not outcome-dependent universal thresholds. A filled study
must be sealed and owner-approved before evaluation; later amendments are new
versions, never edits to a locked study.

Read [route admission](DOMAIN_ADAPTER_CONTRACT.md), the
[owner promotion contract](../../upgrade/implement.md#qms-endpoint-meta-extension)
and [original scientific scope](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14).

| Required Field | Registration Requirement |
|---|---|
| identity | Schema, study ID/revision, source commit/hash, sealed/approved clocks |
| alpha | Existing approved alpha semantic/source hashes; originals read-only |
| market | Data hash, source, instrument/venue/ordered universe, timeframe/calendar |
| domain | Exact endpoint/adapter ABI, intent/effect timing, evaluator/backend |
| financial | Initial/diagnostic/final account, costs/funding/margin/constraints |
| windows | IS/forward policy, warmup/purge/embargo, support/development/locked sets |
| methodology | Native mode/schedule/anchor, unchanged learner/basis/panel/guards |
| sampling | At most two preselected recipes for economics, seed/trials/stopping |
| permission | Corpus, outcome origin, exposure, label maturity/publication policy |
| matched work | Same full eligible IS pool/native anchor, ask/tell/RNG sequence |
| ablation | Off/shadow/active, charged observer/evaluation/fit/report work |
| estimands | Raw endpoint-metric decay R, IS contribution and forward Q |
| thresholds | Owner-approved R hurdle and forward noninferiority margin |
| uncertainty | Dependence-aware method, paired-valid counts and interval rule |
| resources | Same-worker/thread budget, wall/CPU/RSS/FFI/copy measurement method |
| integrity | No outcome retuning, rerun-until-success, alpha copy or private leak |
| decision | Software, empirical, installed/remote and owner gates independently |

Default economic support remains at least twelve matured origins; the original
guide's attempted-trial/development/locked-evaluation requirements still apply
when claiming its scientific acceptance. Reduced support is engineering smoke.
Insufficient, inconclusive or no-gain results remain visible and NOT_PROMOTED.

Use raw metrics from the actual domain account, never a penalized objective or
symbol-average Sharpe:

$$
D_{n,k}=I_{n,k}-F_{n,k},\qquad D_{m,k}=I_{m,k}-F_{m,k}
$$

$$
R_k=D_{n,k}-D_{m,k}=(I_{n,k}-I_{m,k})+Q_k,\qquad Q_k=F_{m,k}-F_{n,k}.
$$

Report valid/fallback/changed decisions, R/IS/Q and uncertainty, and actual
returns/drawdown/liquidation/costs. Lower IS alone does not prove better forward
performance. Segmented account equities cannot be compounded as continuous
equity. Promotion requires software PASS, the registered real-alpha economic
gate and explicit owner approval; synthetic fixtures cannot satisfy it.

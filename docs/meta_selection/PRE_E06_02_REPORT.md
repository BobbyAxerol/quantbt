# PRE-E06-02 Active-Matured Conformance

## Scope

Local source qualification for **Mode 4 / per_fold_causal**, opt-in meta, using
the existing public runners and original financial authorities. This phase does
not activate another methodology, promote economic effectiveness, rebuild the
native extension, certify a new installed artifact or authorize publication.
**Result: PASS_LOCAL_SOURCE_CONFORMANCE.** The
[source-bound receipt](../../benchmarks/optimization/meta_selection/qms_pre_e06_02_closure.json)
records 311 required conformance PASS and 312 distinct scoped regression PASS:
**623 distinct PASS**. The 27 scalar-scorer cells outside its four-target scope
are not applicable and are not counted as PASS. This is not `pytest -q` for the
entire repository. Initial failing receipts are retained separately.
Follow the [unified plan](../../upgrade/implement.md#qms-pre-e06-02) and original
guide sections [5](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[6](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[7](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7)
and [8](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8).

## Registered Protocol

The [PRE01 registration](PRE_E06_BASELINE.md#pre-e06-02-preregistered-software-fixtures)
is preserved. Initial pct-equity coverage supplied only **9 valid matured origins**
at 2022-04-30; that run remains a failure, not a reduced-support PASS.
Owner-approved **PRE02-A01** adds actual historical calibration from 2020-04-01,
instead of 2021-01-01. No seed, range, objective, estimator, lambda or maturity
threshold changed. The synthetic daily UTC tape still starts on 2020-01-01.

All three cutoffs remain 2022-04-30, 2023-04-30 and 2024-04-30. Each route uses
90D rolling IS, monthly forward windows, eight attempts, seed 731, one numeric
thread, lambda 10 and **at least 12 distinct permitted VALID-labeled origins**.
Original publication/completion timing is retained. A generated fold, anchor
zero row or invalid label is not counted as a valid training origin.

Historical labels come from actual original endpoint executions. Each current
comparison gets identical immutable revisions in a separate history owner.
The public synthetic strategies are frozen fixtures, not private alpha and not
market-gain evidence. The registered near-zero/flat/liquidation tests distinguish
valid zero Sharpe from undefined or censored outcomes.

## Required Route Matrix

Thirteen routes are exercised: `signal_notional`, `notional`, `unit`,
`pct_equity`, `dca_ladder`, `portfolio`, `basket`, `arbitrage`, `intrabar`,
`event_driven`, `order_commands`, `delivery_arbitrage` and W3 `reactive_reset`.
The same-close prepared scalar scorer is additionally compared on the first
four scalar targets only. Other routes keep their own timing/account contracts;
their scalar-scorer cells are explicitly **not applicable**, not financial skips.

For each route/cutoff the test requires an actual fitted model, nonempty ranking,
`META_MODEL_PROPOSAL`, past matured history and applied effective params. The
receipt must include at least one actual non-anchor selection/application.
No-model fallback cannot pass this qualification. Natural synthetic decisions
may retain the anchor; the method is not forced to change params in every fold.

| Route | Valid matured origins at the three cutoffs | Actual non-anchor applications |
|---|---|---|
| signal_notional | 23 / 35 / 47 | 0 |
| notional | 23 / 35 / 47 | 0 |
| unit | 23 / 35 / 47 | 0 |
| pct_equity | 15 / 23 / 29 | 0 |
| dca_ladder | 24 / 36 / 48 | 3 |
| portfolio | 24 / 36 / 48 | 0 |
| basket | 19 / 30 / 41 | 1 |
| arbitrage | 19 / 30 / 41 | 1 |
| intrabar | 24 / 35 / 47 | 2 |
| event_driven | 24 / 36 / 48 | 3 |
| order_commands | 24 / 36 / 48 | 1 |
| delivery_arbitrage | 24 / 36 / 48 | 3 |
| reactive_reset | 24 / 36 / 48 | 2 |

All **39** decisions actually fit/rank with default maturity; **16** apply a
different candidate. An unchanged winner is not cold start or ineffective code:
the model ran and retained the anchor under its original guard/selection policy.

## No-Leakage And Positive Controls

| Test | What the real runner must preserve/check |
|---|---|
| M01 | Future OHLCV and funding mutations leave captured history, current IS pool, scaler/model, predictions and selection unchanged |
| M02 | Future forward labels, re-anchored/reordered candidate archives and unavailable fitted artifacts cannot enter an earlier decision |
| M03 | A correction injected during search stays outside the captured snapshot; a later snapshot replaces the complete origin contribution |
| M03 positive | A permitted correction changes the actual fitted coefficients without adding another origin or doubling its weight |
| M04 | Physical history/current-pool order preserves logical membership, ranking and deterministic selection |
| M05 | Equal-time publication without proven order is excluded; seal/effect clocks stay explicit, never backdated |
| M06 | Original daily-first/hourly reduction, ddof=1, activity, valid zero, no variance, incomplete and liquidation dispositions reconcile |
| M07 | Eligible-prefix market/funding changes invalidate witnesses; economics mismatch cannot relabel original measurement |

The future mutation also changes the **actual forward observer's input signature**.
Profit need not change under scale-invariant sizing, flat signals or rejection;
requiring a profit difference would be an invalid positive-control assumption.
Synthetic archive corrections are fault/causal controls, not newly measured
financial labels or evidence of better forward performance.

Tests operate through public selection and original financial owners. They do
not establish causality for every arbitrary user indicator or callback. Caller
feature causality and truthful external history provenance remain requirements.

## Measurement And Accounting

Every panel candidate/anchor is independently regenerated on IS and forward
windows, then measured with the original aggregate account `full_report`.
Raw Sharpe, activity, sample count/std and typed validity are checked; penalized
objectives, predicted scores, symbol averages and fill counts are not substitutes.
Origin-sum Ridge, panel membership, Q floor and scientific guide remain unchanged.

Reset-flat diagnostics are compared on their own windows. The final ordinary
result is rebuilt from the full stitched payload in **one original continuous
account**, not by compounding diagnostic equities. Multi-fold rebuilds cover
the whole declared tape. W3 instead retains its original segmented reset-flat
accounts, each independently replayed. Legacy pct/ladder schemas do not expose
V2 fee/funding/margin arrays; these fields are not fabricated.

Available original equity, returns, positions, fees, funding and margin buffers
must reconcile. Off/shadow pools, trial objectives, selected params, RNG and
accounting are exact. Active cached/uncached witness comparisons are exact.
Prepared and Rust/reference numeric comparisons use the existing declared
`rtol=atol=1e-10` with identical logical decisions, not arbitrary artifact hashes.
The chronological Q-floor/tie corpus and liquidation compatibility regression
are separate tests, not additional valid origins for a public fixture.

## Repairs And Historical Evidence

Two minimal source defects were found and repaired:

1. Intrabar diagnostics passed a full-tape funding Series to an exact-window
   endpoint. Select the exact window; missing bars and duplicate funding indices
   still raise. Funding timing, rates, fees and the financial kernel do not change.
2. Common market binding could not serialize symbol-mapped funding Series.
   Bind the nominal `aligned_series` policy per symbol; eligible rates remain
   bound by the original exact market witness. Existing scalar policy hashes
   and execution compatibility families are preserved.

The quarterly fixture also scheduled a close after its leg's flatten boundary.
The financial rejection was correct. The fixture now chooses a catalog leg
tradable through the scheduled close; expiry guards are not relaxed. Quarterly
scope remains **pre-expiry flatten and explicit new-leg roll**, not real-venue
cash settlement or hold-through-expiry certification.

Initial maturity, fixture and test-tooling failures remain in the local evidence
lane. Older JSON/source seals, the original guide and referenced artifacts stay
unchanged. PRE01 regression verifies its archived commit; its inventory explicitly
cannot certify today's amended source. Exact later source guards reject any
unreviewed change beyond the two binding repairs.

## Remaining Gates

C01 nested Mode 1 runtime: PRE-E06-03. Conditional Sobol/finite-support runtime:
PRE-E06-04. Matched profiling/optimization: PRE-E06-05. Fresh final-source installed
wheel/sdist, package/privacy handoff: PRE-E06-06. E06/E07 scope acceptance and
final-source E08 remote/public evidence remain separate owner-approved steps.
Options/Nautilus meta, W3 continuous carry/shared multi-symbol/public meta batches
and bootstrap are not activated. Failed/inconclusive economic evidence stays
unchanged; no decay improvement is claimed from these software fixtures.

## Resources And Reproduction

Reuse the existing CPython 3.12 consumer/native toolchain, source-first imports
and one numeric thread. No fresh environment, wheel or Rust build is created.
Retain logs/XML/receipts in `.maturin/qms08/pre-e06-02`, including failed runs.
No new reproducible build scratch requires deletion; historical environments,
artifacts, source and private research remain protected. The exit receipt binds
actual disk use and retained-file hashes; it is not a speed/RSS benchmark.
See the [cleanup receipt](../maintenance/QMS_PRE_E06_02_CLEANUP.md). All 69
historical source/scientific seals, 50 retained artifacts and original guide
hashes are unchanged. No private alpha/notebook/data was accessed.

```bash
export PYTHONPATH=src:.
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1
PYTHON=.maturin/qms08/g01-package-v1/consumer/bin/python
$PYTHON -m pytest -q -o junit_family=xunit1 tests/meta_selection/test_pre_e06_02_conformance.py
$PYTHON -m pytest -q tests/meta_selection/test_pre_e06_02_measurement.py tests/meta_selection/test_pre_e06_02_gate.py
```

Source conformance is distinct from the compiled numeric dependency's existing
local qualification. Remote/public receipts are not inherited from a historical
artifact, and no CI, merge, tag, push or publication is performed by this phase.

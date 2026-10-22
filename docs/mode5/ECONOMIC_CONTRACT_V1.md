# Mode 5 Economic Evidence Contract

## Authority And Scope

This is a research measurement contract, not a financial engine or an automatic
deployment policy. Read the [M5-11 plan](../../upgrade/implement.md#mode5-m5-11),
[detailed guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-11--formal-calibration-pilot-independent-checks-và-economic-inference)
and [local findings](M5_11_ECONOMIC_REPORT.md). The public entry remains
[`QuantBTEndpoint.walk_forward`](PUBLIC_CALIBRATION_V1.md).

`tools.mode5_economics` is an offline research layer. It consumes actual qualified
account paths, accepted campaign ledgers and shared access witnesses; it is not
an installed endpoint dependency. Canonical daily reporting, moment/PSR and
tail reducers still live under `quantbt.mode5` and `quantbt.metrics.reporting`.
No new optimizer, account state machine or matching implementation is introduced.

## Preregister Before Outcomes

`EconomicProtocol` freezes duration, event support, origins, calendar, block
length, draws, seed, family confidence and the business hurdle. M5-11's approved
pilot uses 365 scored days per segment, 30 accepted fills / 20 closed campaigns
when measurable, three qualified origins for a transfer claim, seven-day paired
circular blocks, 1,024 draws and seed 731. Five primary alpha mean contrasts have
nominal 99% family confidence: Bonferroni marginal confidence is **99.8%**.

The 0.5 bps **net account/day** hurdle is a frozen decision preference, not a
new fee deduction or a result-dependent significance threshold. Actual net
returns already include original fees/funding/slippage. Cost-derived diagnostics
must normalize position turnover by allocation: `.001 * .064 * .1` is
`.0000064` account/day, or **0.064 bps/day**, not 0.64 bps/day.

Support shortfalls stay explicit; missing accepted-fill or campaign ledgers are
null, not zero and not signal-regime trade counts. No window/seed/range extension
is made to obtain a positive result. A new design needs a new prior registration.

## Measurement

`DailyAccount` owns immutable little-endian daily timestamps/return bytes.
Content identity survives copying and pickling. Calendars must match exactly,
with complete contiguous UTC daily buckets and an explicit original-capital
baseline; there is no implicit inner join or dropped bankrupt observation.

Annualized daily Sharpe is daily mean / sample standard deviation times
`sqrt(365)`. Classical PSR uses the **original-period** Sharpe and moments, not
the annualized ratio. Net account return, log growth, loss ES and hour-marked
drawdown remain distinct. No accepted campaign is inferred from price exposure.

For each actual fixed parameter vector, report development and forward quality
separately, then their differences in annual Sharpe, mean daily net return and
mean daily log growth. Finite positive campaign PF has raw gross profit/loss,
campaign count and currency; zero GP/GL or insufficient support is typed
undefined/insufficient. Log-PF decay is computed only for valid common-currency
PF on both segments. Sharpe-retention ratios near zero/negative IS are not used.

The paired report retains the IS and forward changes separately. A smaller
decay caused only by weaker IS does not establish improved forward quality.
`WHOLLY_HARMFUL_MEAN`, `EXCLUDES_REGISTERED_MEAN_HURDLE` and intervals crossing
the hurdle describe different primary effects. They do not override failed
support, unavailable Sharpe intervals or the joint inference gate.

## Inference And Rights

Baseline/challenger share block indices on common dates. Daily observations,
multiple vectors on the same tape, repeated engine passes and repeated seeds
do not become independent origins. The four-path reducer accepts exactly one
paired origin; it cannot certify three origins by changing an integer argument.

Positive scoped evidence requires adequate registered support, the primary mean
lower bound above the hurdle, nonnegative forward-Sharpe lower bound and negative
decay-change upper bound together. Otherwise retain a scoped negative or
`INCONCLUSIVE` result. Invalid SR draws are not discarded: their SR/decay interval
is unavailable while valid mean-return inference remains separately visible.

These are **fixed-path**, nominal block-bootstrap intervals, not uncertainty
over the whole candidate-discovery/sampler/recipe procedure. Seven-day blocks
assume a useful within-horizon dependence approximation, not proof of stationarity
across crypto regimes. With 1,024 draws at 99.8% marginal coverage, each endpoint
has only about one tail draw: tail resolution is weak. No finite-sample exact
99% family guarantee or universal invariance is claimed.

Static Mode 5 calibration keeps `none_full_sample_calibration`. Explicit sealed
selection rights may authorize reviewed coordinates discovered after historical
IS; sampler metadata distinguishes `is_cutoff`, `warm_start_cutoff` and
`cutoff_authority`. Legacy Mode 5 and causal schedules retain historical IS
cutoffs. The full data/dossier/domain/config binding and chronology still apply.

`prefix_rights` checks diagnostics, candidate discovery, recipe, market and any
preprocessing/labels at the actual origin. It verifies permission, not that a
new complete prefix experiment has been performed. New validation requires an
actual prior pipeline freeze. `cached_validation_rights` revalidates original
receipt/data rights and always labels reuse reviewed/exploratory; it does not
invent a new post-freeze financial execution or independent OOS confirmation.

## Stress And Reproduction

Stress invokes the original financial endpoint with fixed selected params and
the registered altered cost/execution policy. Reconcile its actual output;
fixed-fill fee arithmetic alone is not a dynamic-policy rerun. A public synthetic
equity-guard callback test demonstrates that higher fees can change later orders.
Private alpha stress may retain the same fills; report that actual result.

Focused source reproduction:

```bash
python -m pytest -q tests/mode5/test_economic_measurement.py \
  tests/mode5/test_economic_inference.py tests/mode5/test_economic_rights.py \
  tests/mode5/test_economic_execution.py \
  tests/mode5/test_economic_calibration_clock.py
```

Real research needs owner-supplied private inputs and exact registered receipts.
Examples/tests are not hidden trading presets. Publication, final package/platform
qualification and live deployment require separate approval.

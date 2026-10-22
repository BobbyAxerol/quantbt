# M5-03 - Metric Units And Statistical Primitives

## Status And Authority

**Technical:** `COMPLETE_LOCAL_STATISTICS / TECHNICALLY_VALID`.
**Scientific:** `DESCRIPTIVE_ONLY`; owner review pending.
All six [approved work packages](../../upgrade/implement.md#mode5-m5-03) and
M5T-021..030 pass on the registered scope, following the
[detailed guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-03--metrics-psr-units-tail-và-uncertainty-primitives).
The [dictionary](METRIC_CONTRACT_V1.md) fixes populations, formulas, units,
null dispositions and reuse boundaries. No endpoint, selector, WFO/QMS score,
accounting, execution clock, fee convention, default or package version changed.

## Implementation And Reuse

Focused opt-in research modules in `tools/mode5_statistics` add same-series
moments/classical PSR, versioned Sharpe-HAC, exact weighted tails and frozen
regret components, fixed-path block intervals and cold-path reconciliation.
Existing MET immutable observations/account/ledger reducers remain authoritative.
There is no new account simulator, fill matcher, prepared cache or Rust bridge.
Public SDK integration and new recipes remain separate approved phases.

Daily account returns include flat days and the first fee via scope-entry
equity. Closed campaigns use recorded net PnL once per completed position
episode; partial fills are not separate campaigns. Open campaigns stay in MTM,
not closed PF. Currency campaign PnL cannot feed return-series PSR.

## Correctness And Oracles

**883 tests PASS, 0 FAIL, 0 SKIP** in the final affected-source regression,
including **52 new statistical tests**, existing MET, plot, QuantStats 0.0.81,
baseline and privacy/package canaries. This is one suite count, not 883+52.
Exact guide Appendix C replay: **25/25** assertions, O01..O22 with four O17 spans.
Geometry/selector identities in that appendix are mathematical checks, not
implementation or market qualification of future M5 phases.

| Requirement | Actual positive and negative checks |
|---|---|
| M5T-021 | Original-period SR=1/sqrt(365), N=43 gives PSR **0.6326896240940183**; incorrectly annualized input gives approximately 1 and is rejected |
| M5T-022 | Explicit ordinary/excess conversion; higher kurtosis changes evidence under the frozen formula |
| M5T-023 | Small N, zero variance, NaN/Inf, infeasible moments, bad denominator, reference/interval overflow yield null + reason |
| M5T-024 | Actual synthetic account: three fills, 43 daily observations; N is 43, not three |
| M5T-025 | Independent raw-moment gradient/dense Bartlett matrix; identical marginals with different ordering; positive and negative dependence |
| M5T-026 | Actual constant-price first fee 0.8 for 2,000 executed notional; initial watermark, block money PnL and compounded returns |
| M5T-027 | Actual partial-exit campaign plus losing campaign; net campaign PF, open censoring, no-loss/zero/empty policies |
| M5T-028 | Weights [.2,.8], utilities [0,10], alpha=.5: true fractional-mass tail **6**, not a quantile |
| M5T-029 | UTC boundaries, unequal elapsed horizons, positive MDD, missing-day and cashflow rejection |
| M5T-030 | Raw scientific Sharpe and penalized objective remain separate; summaries cannot manufacture unavailable moments |

Decimal central-moment, Fraction tail and dense-matrix HAC references are
independent of production recurrences. Python/Numba parity includes extreme
finite scales; absolute tolerances are 1e-12 for fixtures, 1e-10 for matched
annual Sharpe, 1e-8 quote currency for cached ledger/account reconciliation.

## Estimator Calibration And Limitations

Classical plug-in PSR uses ddof=1 period SR, central population skew/ordinary
kurtosis and matching return N. It is neither an edge posterior nor a selection-
adjusted probability. HAC is separate population-SR inference: Bartlett H=5,
centered influence, N lag divisor, no small-sample correction, minimum N=32,
normal two-sided 95% interval. Negative dependence need not increase SE.

Registered null calibration: 128 seeds per model, N=512, AR(1) phi=.5 with
256 burn-in observations. Gates fixed before results: coverage >=.80 and
estimated/empirical SR variance ratio within [.65,1.35].

| Control | Coverage of true zero | Variance ratio | Gate |
|---|---:|---:|---|
| IID Gaussian | 96.09% | 0.9830 | PASS |
| AR(1) | 91.41% | 0.7503 | PASS |

AR(1) undercoverage and underestimated variance remain visible. This diagnostic
gate is not universal market calibration or a guarantee of nominal 95% coverage.
Moment intervals use circular 7-day blocks, 256 draws, seed 731 and 95%
percentiles. Invalid draws are counted and invalidate intervals rather than
conditioning on survivors. No automatic bandwidth tuning, ESS substitution,
selector resampling or Gaussian default replacement is introduced.

## Reanalysis And Availability

Five sealed M5-02 actual-market paths were reanalyzed without private alpha
imports, new market simulation or optimization: 2,184 hourly marks / 91 daily
observations each. Data is `EXPLORATORY_REVIEWED_2024`, not untouched validation.
Daily annual Sharpe agrees with existing MET and direct arithmetic; maximum
difference **3.553e-15**. Four recorded campaign ledgers reconcile account PnL
within **3.275e-11 USDT** and fees within **1.422e-14 USDT**. Legacy scientific
returns and scores are untouched, not silently replaced by daily sampling.

RSI's legacy target path lacks authoritative campaign and separate cost
streams: those additions are typed `UNAVAILABLE`. Baseline/T1/T2 summary-only
artifacts lack full qualified returns/campaigns: PSR, HAC and new tails remain
`REPLAY_REQUIRED`, not inferred from Sharpe/DD/fills. Later targeted replay needs
its own registered question, budget and owner-approved phase.

Private evidence contains per-alpha numeric panels, source/path identities,
support/masks, uncertainty and all unavailable reasons. No parameters, strategy
source, fills or private economic rankings are disclosed here. A 91-day admission
path cannot establish long-horizon tail stability or recipe superiority.

## Computation Bill

New moments only, matched five outputs, seed 731, one process/thread, seven warm
samples. NumPy reference uses centered vectorized moments; no engine/WFO work.

| Observations | NumPy p50 | Numba p50 | Python p50 |
|---:|---:|---:|---:|
| 91 | 0.105 ms | 0.040 ms | 0.212 ms |
| 10,000 | 1.812 ms | 0.174 ms | 18.721 ms |
| 1,000,000 | 200.946 ms | 21.435 ms | 1,613.723 ms |

At 1M, Numba is **9.37x** the matched NumPy reference, about **46.65M
observations/s**; p95 **21.741 ms**. Cold first moment JIT call **686.342 ms**;
benchmark subprocess peak RSS **188.5 MiB**. These are descriptive primitive
measurements, not a Rust/Numba core comparison or improved WFO latency.

Five-row cached reanalysis takes **5.537 s**, peak process RSS **271.977 MiB**.
First account analysis **4.596 s** includes MET/new Numba cold compilation;
the remaining warm account analyses including 256-draw uncertainty were single
observations of **13.743-14.792 ms** each, not repeated p50 claims. Wrapper/startup/
protected-hash verification are outside those component timings. No native,
wheel/sdist build or install ran; 128 MiB incremental disk / 5 GiB reserve.

## Failure Retention And Reproduction

Initial private harness import/fixture failures remain append-only. A new
campaign fixture omitted the MET-required valuation witness and was corrected;
core was not changed. Regression tooling lacked plotting/QuantStats dependencies;
the primary environment's older native correctly triggered its pair guard.
Final regression retains original numeric/native 0.4.3 imports and reads only
missing optional dependencies from the existing primary site-packages. Loaded
origins and hashes stay unchanged; neither environment was installed or altered.
These earlier runs are not relabeled PASS.

Public synthetic reproduction from a suitable development environment:

```bash
PYTHONPATH=src:. python -m pytest -q tests/mode5/test_statistics*.py
```

Full regression also requires the approved native pair, Matplotlib and pinned
QuantStats. Private append-only harness and registrations remain owner-local.
The [source-bound seal](evidence/m5-03.json) references successful/failing lanes,
the full private report, calibration, reconciliation and benchmark. Read the
[cleanup receipt](../maintenance/M5_03_CLEANUP.md) for exact reclaimed scratch.

No remaining in-scope numerical/accounting blocker is open. All 765 protected
hashes are unchanged. M5-04 still requires separate approval; no push, CI,
merge/tag, package version change or publication occurred.

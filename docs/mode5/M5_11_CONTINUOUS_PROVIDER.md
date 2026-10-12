# M5-11 Continuous Account And Recovery Admission

Status: **COLD REDUCER / ADMISSION QUALIFIED; PUBLIC DISPATCH NOT YET QUALIFIED**.
Authority: [ordered local completion](../../upgrade/implement.md#mode5-m5-11-ordered-execution-20261012),
[financial boundary](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#24-financial-boundary-và-route-qualification),
[causal permissions](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#72-computationoutput-plan-và-cache).

## Account Authority

The new typed reducer consumes one original, source-bound financial result.
It neither invokes a strategy nor creates another account engine. Calendar-year
views use the prior actual equity mark, without resetting capital or positions.
Annual monetary PnL and cost partitions reconcile to the same whole account.
Annual scope drawdown and carried-watermark drawdown remain separate estimands.
Whole-account Sharpe is not an average of annual Sharpe ratios.

The existing Mode5 metric policy still owns returns, utility, PSR, risk/support
gates and undefined conventions. An already computed whole observation may be
reused only after its account hashes, metric contract and components reconcile.
Bankrupt scope-entry equity stays undefined; a later liquidation cannot be
propagated backward into an earlier calendar view. Missing fill/campaign ledgers
remain unavailable, not inferred zero support.

One `financial_execution_count` is one original scorer invocation. It is not a
claim of one internal native pass: reactive feedback passes and selected audit
are distinct work. Actual internal counts are retained when supplied; otherwise
their status is `UNAVAILABLE`. These reducers do not certify backend dispatch.

## Recovery Consumers

Full-panel admission requires the original 128-point roster, exact source and
economic identities, complete original hourly calendar, source-reader outputs
and independently captured reader certifications. It produces four dependent
views per candidate, not four economic replications.

The selector now accepts the explicit admitted-panel envelope and validates its
rows. Raw recovery status, retrospective role, source limitations, actual call
counts and fresh-versus-inherited Python-oracle coverage are unchanged. Analysis
completion is a separate field, never a renamed financial PASS. Failures,
censored accounts, unknown schemas, forged oracle coverage and missing/null
metrics cannot enter by changing a status label.

Legacy selector rows remain stdlib-only. Admitted recovery rows lazily use the
shared cold metric/row validator. Neither path executes finance or opens an
alpha. Original annual utility thresholds and tie-breaking are unchanged.

## Local Verification

The corrected cold run passes **79 tests and 46 subtests**, with one public-study
test deliberately deselected because dispatch has not yet been wired. This
includes 52 reducer tests, 24 panel tests and three binding/geometry checks.
The separate legacy cold selector shard passes **42 tests**, still loading no
financial or numeric runtime on its legacy input path.

| Receipt | SHA256 |
| --- | --- |
| `continuous-cold04/result.json` | `d2376472b7c260949a85fd80c6c869e9fcfd8f679d0270b7f3eb4c760888b009` |
| `continuous-legacy05/result.json` | `0ab9e4de895282751bce0a89b3de06bd5ce0bf52a1e81a2932a251d0a7efd3b6` |

Receipts live under the ignored private M5-11.1 `attempt-01` evidence directory.
The earlier tuple/list round-trip and PSR assertion failures remain retained.
Corrected comparisons use canonical immutable records, without changing any
estimator or scientific threshold. Test wall times are 41.830 and 3.581 seconds;
these are software validation, not financial benchmark or economic evidence.

Each run reused the controlled environment, one numeric thread and a registered
32-MiB retained budget with a 5-GiB reserve. Cleanup records zero scratch or
deletions, source-pin checks and retained evidence. Filesystem changes from the
concurrent missing-panel workers are not claimed as cleanup savings.

## Remaining Gates

This checkpoint does not certify all 640 source accounts or finish M5-11.1.
Three older retained schemas still need explicit cold source admission; the
missing-only tranche, native probes, matrices and dossiers are separate gates.
Continuous public producer witnesses, original geometry telemetry, actual
256-query studies, prefix forward economics and final installed artifacts
remain qualified only by their subsequent receipts. Public V1 reset-flat
bindings, existing endpoint names and existing scientific formulas are unchanged.
No independent OOS, economic improvement, release or deployment is claimed.

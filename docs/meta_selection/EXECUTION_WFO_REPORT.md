# Local Execution WFO Qualification

## Source And Scope

Owner-approved local amendment to [E06/E07 and quarterly scope](../../upgrade/implement.md#qms-required-execution-routes).
Implementation commits `a139f35` and `7e8fefc`; core/native pair `1.1.2 / 0.4.3`
is prepared locally, not published. Detailed QMS guide SHA256 remains
`adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d`.
No Ridge, estimator, objective, fee convention or native financial kernel changes.
Explicit empty command windows now execute a valid flat original account.

Four opt-in typed routes: intrabar intent/session, generic Python callback,
command tape and explicit quarterly pre-expiry flatten/roll. See
[stable usage and exact limits](EXECUTION_WFO.md). The architecture extends the
existing domain adapter and `walk_forward(execution_endpoint=...)`; it does not
create a sixth mode, account engine or per-bar meta callback.

## Correctness

Original reset-flat IS/forward results supply raw metrics and full-pool witnesses.
Final OOS payloads execute in one continuous original account. Tests independently
check carried stop protection, pending limit orders across fold boundaries,
v2/v3 quarterly fills, each one-way fee, rejected insufficient close capacity,
empty windows, exact calendars, future-price mutation and original metric values.
Prepared/reference preserve all candidate/label witnesses, params and accounting.
Independent wall/publication timestamps legitimately give different historical
revision/snapshot IDs; tests do not erase them to force matching receipts.

Shadow/native pool, trial table and six accounting buffers match exactly. Active
final payload replay matches equity, returns, positions, fees, funding and margin
exactly. Existing explicit Rust financial owners match their reference accounts
within `rtol=1e-11, atol=1e-9`, with exact selected params on these fixtures.
Intrabar minimal/audit accounting is exact. Margin/cost witnesses use the original
V2 result buffers, not a legacy report projection that drops margin.

A follow-up test first exposed future funding-range identity instability on
orders/callback dictionaries. Nominal economics now normalize aligned Series
policy like portfolio; extending future funding history leaves family identity
and current-window witness unchanged. Changing funding inside the window changes
the actual market witness. Scientific/metric and financial execution are unchanged.

Final affected suite: **151 passed**, plus **2 funding follow-up tests passed**.
The initial four prepared-comparison harness failures and their exact passing
reruns remain archived; they were clock-bearing snapshot comparisons, not waived
tests. No full repository/remote matrix certification is claimed by this scope.

## Synthetic Study

Frozen before comparison: daily synthetic tape, 2021-01-01 through 2022-06-30,
16 monthly OOS folds, rolling 59-day IS, 8 logical trials/fold, seed 731,
one numeric thread, min 12 matured origins. The four basic domain alphas and their
parameter ranges are public in [the example](../../examples/wfo_meta_execution.py).
No private alpha/data/notebook was edited or published.

Each off/shadow/active run uses a fresh process, original financial execution
(Python event owner or Numba intrabar) and audit buffers. Meta auto resolves
qualified Rust transform/solve/rank; schema/scaler/diagnostics remain Python/NumPy.
Wall time includes preparation, studies, observer and final account construction,
but not the final standalone `full_report` rendering after the timer. These are
single-run measurements, not statistically established latency guarantees.

| Route | Off | Shadow | Active | Active cost vs off | Peak RSS off / active |
|---|---:|---:|---:|---:|---:|
| Intrabar intent/session | 4.424 s | 6.909 s | 6.987 s | +57.92% | 281.52 / 285.41 MiB |
| Generic callback | 12.965 s | 18.291 s | 18.258 s | +40.83% | 287.54 / 290.95 MiB |
| Command tape | 11.043 s | 15.000 s | 14.441 s | +30.78% | 288.95 / 292.61 MiB |
| Quarterly pre-expiry roll | 13.777 s | 19.548 s | 19.956 s | +44.85% | 289.86 / 294.43 MiB |

All twelve runs finish with **zero observer failures**. Meta fits three models
per enabled run after history matures. Shadow changes zero selections and keeps
native final accounting. Active changes one intrabar fold; the other routes
retain their native selections on this sample. It is not a defect to retain an
anchor when its allowed learned evidence does not justify another candidate.

| Route | Final equity off | Final equity active | Valid active R/Q pairs | Mean R | Mean Q |
|---|---:|---:|---:|---:|---:|
| Intrabar | 19,979.0684 | 19,980.0077 | 15 | 0 | 0 |
| Generic callback | 19,913.8222 | 19,913.8222 | 16 | 0 | 0 |
| Command tape | 20,018.8162 | 20,018.8162 | 16 | 0 | 0 |
| Quarterly roll | 19,992.5201 | 19,992.5201 | 16 | 0 | 0 |

Intrabar's changed fold has `NO_VARIANCE` forward disposition; its Sharpe 0 is
not a valid improvement label. R/Q require four original `VALID` observations.
The earlier v2 study receipt lacks that validity filter and is retained only as
superseded diagnostic evidence. Current [v3 raw study](../../benchmarks/optimization/meta_selection/qms_execution_synthetic_study_v3.json)
retains all included/excluded dispositions. No alpha/ranges/search or scientific
runtime was retuned after outcomes. No reliable decay improvement, real-market
confidence interval or economic promotion is established here.

## Artifacts And Cleanup

Fresh core wheel/sdist are source-exact and artifact-allowlisted. Both isolated
CPython 3.12 consumers execute all four routes with off/shadow/active, exact
shadow accounting and exact active original-account rebuild. The original native
artifact is reused by exact hash; native source did not change. Installed proof
is retained in `.maturin/qms08/execution-package-v4/proof.json`, not replaced by
a source-tree smoke test. Earlier failed/stale artifact lanes remain historical.
An installed native supplement additionally executes active meta on all four
explicit Rust financial routes: fitted models and Rust solve/rank are verified,
with 15-16 real numeric FFI calls per route and zero observer failures. Generic
callback alpha decisions remain Python. Its log/JSON is retained in that lane.

The [local closeout](../../benchmarks/optimization/meta_selection/qms_execution_closeout_v4.json)
binds source, native/core artifacts, consumer logs, test XMLs and cleanup hashes.
Only this run's inactive consumer/build scratch is eligible for removal. Source
staging, exact wheels/sdists, logs, negative scientific evidence and current G01
tooling stay retained. Cleaned proof environments require reinstallation for rerun.
Final cleanup frees 575,635,456 measured bytes (about 549 MiB) in the last lane;
prior cleanup receipts record their own observations and are not summed into a
whole-host storage claim. Available bytes at final cleanup are 27,059,539,968.

## Remaining Boundaries

- Software-qualified opt-in, not default/economic promotion or a PyPI release.
- Quarterly is executable pre-expiry flatten/explicit roll on a fixed priced
  calendar, not cash settlement, atomic all-or-none, a delivery provider or
  real venue/data certification. Unsupported cash settlement raises.
- Generic callback alpha state remains caller-owned Python; factories must be
  fresh and features causal. Existing numerical W3 carry/batch/multi-symbol
  approvals are not implied by this separate continuous event-account route.
- Meta remains Mode 4/per-fold-causal. C01/C05 local specifications are approved
  but their implementations remain pending; options/Nautilus meta and other
  previously listed capabilities remain separate.
- Remote matrix and public-index proofs wait for final owner approval. No push,
  workflow, merge, tag or publication was performed.

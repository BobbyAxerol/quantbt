# QMS-E08 Local Integrated Qualification

## Scope And Authorization

Owner authorized bracket diagnosis and local E08 closure on 2026-10-07.
The latest instruction is **local only; CI/release later**. No push, workflow
dispatch, merge, tag, PyPI upload or public consumer proof occurs in this phase.
Core/native preparation stays `1.1.2 / 0.4.3`; meta remains opt-in.

**Final local disposition:** COMPLETE_LOCAL_SOFTWARE_QUALIFIED_OPT_IN.
Implementation and the registered local technical/installed/privacy/cleanup
gates are complete. Economic promotion is **not granted**; owner review of
this handoff is pending. Remote qualification is DEFERRED_BY_OWNER_LOCAL_ONLY
and public proof is PENDING_OWNER_APPROVED_PUBLICATION, not missing local tests.

Read [E08's registered plan](../../upgrade/implement.md#qms-e08) and the detailed
guide [measurement/chronology](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
[reporting](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s12)
and [public contract/scientific scope](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s13).

Entry source is `0da632e`. The original guide SHA256 remains
`adad24b16024ec5d9f3bdaf3a4098a8c60305c1fc181f1c30a0ff0f648a8170d`.
The only runtime amendments are actual-clock reporting in `wfo_execution.py`
and requested/observed pool telemetry. No financial engine, native source, fee,
sizing contract, estimator, objective, tolerance, candidate pool or RNG changes.
The [exact reviewed source seal](../../benchmarks/optimization/meta_selection/qms_e08_reviewed_source.json)
and negative mutation tests enforce that scope. Historical E07/PRE06 receipts
retain their original identities; their artifacts are not current-source proof.

## Bracket Zero-Fill Incident

The reported portal adapter was not available in this workspace. Its
`NATIVE_ACCOUNT` and 13 private runs were not inspected or rerun. The following
is a direct QuantBT reproduction using a public synthetic signal, not a claim
that those production runs have already been repaired.

In legacy `fixed_notional` sizing, `entry_size` is a **multiplier**, not currency:

```text
requested_notional = fixed_notional * abs(entry_size)
fixed_notional = metadata override, otherwise alloc_per_trade
quantity = requested_notional / (actual_fill_price * contract_size)
```

With the endpoint's default allocation `100000` and `entry_size=2000`, the
attempted notional is **200,000,000**. A 20,000 account at leverage 3 rejects it.
Even allocation 2000 would request 4,000,000. Allocation 1 would instead make
the original weight valid. Inspect the actual resolved configuration before
attributing all production failures to the default allocation.

The portable correction preserves engine semantics:

```python
n = len(side)
intent = IntrabarIntentTape.from_arrays(
    entry_side=np.where(changed, side, 0),
    entry_size=np.ones(n),
    stop_value=np.full(n, slpercent / 100.0),
    take_profit_value=np.full(n, slpercent * 2.0 / 100.0),
    technical_exit=changed & (side == 0),
)
# Pass through the existing gateway without changing its route:
# intrabar_sizing_mode="fixed_notional", alloc_per_trade=2000.0
```

The direct public endpoint accepts that allocation through its unchanged
`QuantBTEndpoint.intrabar_bracket(..., alloc_per_trade=2000.0)` constructor.
Its `backtest(data=market, intent=intent, symbols=[symbol])` receives the signal-
bar tape. Check any `metadata["fixed_notional"]` override as well; do not shift
the intent or divide the currency notional by close twice.

Results on 92 days / 2,208 hourly bars, 11 synthetic entries:

| Declaration | Backends/symbols | Fills | Rejections | Fees | Final equity |
|---|---|---:|---:|---:|---:|
| Weight 2000, base 100000 | Python oracle/Numba/Rust x BTC/ETH/SOL-like | 0 | 11 | 0 | 20,000.00 |
| Weight 1, base 2000 | Same nine cells | 22 | 0 | 19.800064 | 19,973.492732 |
| Weight 2000, base 1 | Same nine cells | 22 | 0 | Same | Same |
| Callback or explicit commands, same side | Python/Rust x three symbols | 22 | Not compared as bracket | Separate contract | 19,973.492386 |

The 39-row diagnostic is retained in the ignored E08 evidence lane. Callback
quantity is frozen from signal close, while bracket notional is anchored at
the actual next-open fill. Therefore their tiny equity difference is expected;
it is not advertised as cross-domain accounting parity.

Timing is correct: intent on signal bar `t` activates at open `t+1`; do not
pre-shift it. Explicit order tapes instead use effective execution timestamps.
Flat-transition `technical_exit` does not cancel every entry. The literal
scalar `stop_value=0.013` in the question is also invalid for a multi-row
`from_arrays` tape: this constructor requires arrays and raises a length error,
not silent flat equity. The working adapter must have differed at that point.

The legacy `num_trades=1` on a flat single-symbol tape counts the initial
position regime. It does not certify a fill or completed round trip. No metric
estimator was changed here. Use `fill_count`, `fills_report`, positions and
`rejected_count` to diagnose execution. A transition-only adapter also does not
automatically re-enter after SL/TP while its signal side stays unchanged.

The 27 incident tests cover first/last/shifted bars, reversal, technical exit,
SL, TP, simultaneous SL/TP, gaps, entry suppression, liquidation, constraints,
fees and prepared/non-prepared oracle/Numba/Rust accounting/ledger parity.
See [the runnable diagnostic](../../examples/intrabar_bracket_diagnostic.py)
and [sizing documentation](../fast_intrabar.md#fixed-notional-units-and-zero-fill-diagnostics).

## Measurement, Chronology And Accounting

Existing E06/E07 proofs are rerun, not replaced by fallback-only tests. New
generic v3 tests cover Python and Rust with 26 historical monthly origins;
the active decision has **24 eligible mature origins**, above the 12-origin
minimum, and actually fits/ranks/applies a model proposal.

- Compare every candidate's raw IS and forward Sharpe, sample count, sample
  standard deviation, activity and validity/censoring to its original report.
- Seal before the first forward action; labels become available only after
  the relevant forward window and registered completion/maturity clock.
- Mutate future OHLCV and funding, late reconciliations and unavailable labels:
  earlier snapshots, full candidates, panel, predictions, model and selected
  params remain unchanged. Future-dated model artifacts must be rejected.
- Compare off/shadow search/trial tables and global RNG exactly; active params
  must be the actual executed candidate. Prepared/reference decisions and
  independent final account rebuilds reconcile equity, returns, positions,
  fees, funding and margin.
- Keep callback/command accounts continuous and W3 single-symbol reset-flat.
  Lifecycle coverage includes pending orders, amend/cancel, OCO, fill feedback
  and rejection. No report-induced financial replay is introduced.

These gates certify the declared QuantBT data/label/selection contracts and
registered causal fixtures. They cannot make an arbitrary caller's noncausal
indicator, external captured dataset or Python callback causal automatically.
Private alpha disclosure is not required for this software qualification.

`callback_boundary` now derives from the actual result contract:
v2 is `bar_close_next_bar_close`, v3 is `bar_close_next_open`; explicit command
tapes report `effective_bar` and callback boundary `not_applicable`.
Actual financial timing is unchanged. The combined `fit_select` timer remains
combined; splitting it later is observability, not a correctness blocker.

Telemetry preserves explicit requested controls or resolves valid environment
controls. A requested-one/observed-four Numba pool is reported as a mismatch,
not certified as one thread. Fresh qualification workers set BLAS/OpenMP/Numba
controls before import and reject mismatches/unresolved inspection. Observed
pool capacity is not active CPU-thread utilization. Caller thread policy is
not silently mutated.

## Exact Artifacts And Qualification Status

**Current local status:** integrated local gates PASS; no remote/public PASS.
The new local core wheel/sdist match all 260 canonical Python/typing members.
The sealed native `0.4.3` artifact is reused only after unchanged native-source
verification; there is no unnecessary native rebuild.

`tools.qms_installed_execution` preloads financial modules from site-packages
under `python -I`, then loads only public tests/examples/tools. It checks complete
core hashes, exact native extension hash, fixture hashes before/after, installed
origins, actual thread pools and zero failed/skipped cases. The groups are 65
intrabar and 84 event tests per artifact, including mature generic v3 coverage.

`tools.qms_e08_integrated` additionally reruns the existing four mandatory
consumers (scalar/W3, C02 process transport, four C03 scheduler recipes, C04
fresh-process exact continuation), eight scalar cells, two portfolio sizings,
three bounded package kinds and repaired liquidation score/compact/audit metrics.
It uses the same exact wheel and sdist, not historical consumer environments.
Conditional Sobol and nested Mode 1 are covered by the integrated source
regression rather than mislabelled as the original four default recipes.

| Evidence | Actual result | Disposition |
|---|---|---|
| Full meta regression v1 | 2,458 pass, 30 registered N/A, one historical privacy-scope failure | Original FAILED receipt retained |
| Complete affected verification modules v3 | 73 pass, zero skips | Actual narrow repair, including the failed case and 15 new negative/evidence checks |
| Reconciled meta cases | 2,474 distinct pass | XML-verified union; never turn v1 into PASS |
| Public WFO/sampler regression | 162 pass | PASS |
| Accounting/intrabar/event/portfolio/package regression | 160 pass | PASS |
| Plot regression | One pass | PASS |
| Combined source identities | **2,797 distinct pass**; 30 N/A reported separately | PASS for registered local scope |
| Installed intrabar/event tests | 65 + 84 per wheel/sdist = **298 rerun pass**, zero skips | Exact installed source/native identities |
| Existing integrated consumers | Eight per wheel/sdist = **16 executions pass** | Search/continuation and original domain accounts |

The full meta run took 2,238.15 seconds. Its one failure was PRE06's old phase
allowlist rejecting `.github/workflows/qms-candidate.yml`, not an execution,
metric or selection failure. Historical privacy now binds revision `b035d20`
and still rejects use against current source. E08's independent current-patch
scope/secret gate passes. The registered
[E08-R01 repair](../../upgrade/implement.md#qms-e08) permits only that exact
failed case after an actual rerun; negative tests reject financial failures,
unregistered skips, modified XML/logs, scope drift and self-attested counts.
The first repair attempt used a nonexistent test filename and collected no
tests; it remains failed, not waived or counted. Runtime bytes are unchanged
between the full regression and the successful scoped reruns.

No private full-unit research replay was rerun: that repaired scientific study
is already sealed separately. Current G01 liquidation/zero-base accounting and
score/compact/audit parity execute again in source and both installed artifacts.

The [tracked closure](../../benchmarks/optimization/meta_selection/qms_e08_closure.json)
binds original/rerun registrations, log/XML hashes, exact source and artifact
identities. Wheel SHA256 is
`c693003b8f9a070ffdb795784997bf1335f125722553acb2ebbb2b0989568620`;
sdist is `5f98bcb3ed453513a3bf4abd45f7b2a91be34474e244c68d8c54737ca17ee5c5`;
unchanged native wheel is
`f5fe1ec4d9268752733ba2c7023cc0e2548215986a8cd73fb6fafb285422a3b6`.
Its native extension hash is checked in each installed consumer, not inferred
from an importable version string.

CI wiring now includes the specialized installed execution proof for all six
Ubuntu 22.04/24.04 x CPython 3.11-3.13 rows and retains logs/XML/manifests.
**No CI job was dispatched or branch pushed.** Current-source remote and final
manylinux release certification are deferred by owner. Public index proof is
pending a separately approved publication.

Test wall times are qualification costs, not a new endpoint speed benchmark.
Historical PRE05 measured budgets/exceptions remain unchanged; no performance
gain or new all-route economic promotion is inferred from these tests.

## Remaining Boundaries

E03/E04 negative forward-Q evidence remains NOT_PROMOTED, not retuned to pass.
Bounded quarterly support means pre-expiry flatten/roll only, not hold-through
expiry cash settlement or real delivery-provider/data certification. Other
global/decay meta methods, W3 continuous carry/shared multi-symbol/public meta
batch/Mode 2 bootstrap, automatic financial checkpoint recovery, options and
Nautilus remain separately reviewed capabilities. Approved nested Mode 1 is
bounded to five scalar targets; original Mode 4 causal routing stays distinct.

Local receipts and [cleanup](../maintenance/QMS_E08_CLEANUP.md) are sealed:
four exact inactive scratch directories removed, **410 protected file hashes**
unchanged, **1,155.875 MiB** actual free-space improvement. Artifacts, staged
source, histories, successful/failed logs and tooling/cache remain available.
Deleted consumers require fresh installation before any rerun; stored receipts
do not mean those environments still exist.
[Release instructions](RELEASE_HANDOFF.md) remain owner-controlled and deferred.

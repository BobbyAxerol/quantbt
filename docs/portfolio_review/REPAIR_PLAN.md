# Portfolio Account Correctness Repair

Owner authorization: 2026-10-21, repair all reproducible findings in the
[account review](../PORTFOLIO_ACCOUNT_REVIEW_2026-10-21.md), then cross-check
other affected endpoints. Baseline commit `5927565`.

## Scope And Contracts

1. Reject unsupported account/fill options instead of silently applying cross
   netting/close execution. Keep the implemented gross-cross/one-net-position
   contract explicit. Full hedge/isolated/tiered/mark-price venue models remain
   distinct capabilities requiring actual state implementations.
2. Correct notional multipliers; reject nonfinite financial configuration; align
   missing marks without fake zero prices and prohibit stale entries.
3. Correct default eight-hour funding-event mapping across date boundaries and
   aggregate all events in coarse/gapped intervals. Declare the closing-price
   valuation approximation and retain explicit event APIs for finer contracts.
4. Admit solvent risk reductions below IM, maintain strict gates on increases,
   and enforce delta-order minimums consistently across Python/Rust targets.
5. Return accepted legacy positions; expose exact funding, per-leg fees and
   liquidation-loss attribution and validate the entire account timeline.
6. Correct timestamp units, per-symbol hit-rate timing and ledger coverage
   horizons. Describe legacy statistic populations explicitly; keep scientific
   optimizer compatibility and provide coherent additive account-period fields.
7. Correct buying-power labels for heterogeneous leverage. Keep actual available
   equity and symbol-specific additional-notional capacities distinguishable.

## Verification

Independent arithmetic tests cover every reproduced finding, both supported
controls and explicit rejected contracts, long/short/reversal/reduce/increase,
coarse funding calendars and rates, liquidation, missing prices, size filters,
ns/us timestamps, incomplete ledgers and report/source invariance. Cross-check
single-symbol vectorized, legacy multi-symbol, shared portfolio, event/reactive,
intrabar and prepared WFO consumers according to their existing domain clocks.
Use Rust unit tests and a fresh local native artifact for modified Rust code;
an older retained extension cannot certify the repair.

Historical source guards need exact reviewed amendments bound to this repair,
not arbitrary whitelists or rewritten historical evidence. Commit coherent
verified changes, preserve owner work, and record remaining unsupported domain
models without labelling them implemented. No CI/push/release is authorized.

## Resources And Cleanup

Reuse the project environment and current Cargo target/dependency caches.
One test/build worker, one numeric thread, available RAM >=512MiB. Registration
and failed/passing receipts remain under the ignored repair lane. Initial disk
available6,269,116,416 bytes; reserve >=5GiB beyond incremental forecast.
Retained receipts/artifacts <=128MiB, disposable test/build scratch <=512MiB;
review actual Cargo incremental growth before a build. Never purge evidence,
private alpha/data, global caches or active environments. Remove only registered
inactive scratch, verify protected inputs/artifacts, and retain a cleanup receipt.

## Exit Gate

All listed correctness fixes have independent expected-value coverage; affected
routes pass regression on declared contracts; Rust changes execute in the fresh
artifact; all source-guard changes are traceable; docs/migration and resource
cleanup receipts are complete. This gate certifies the repaired contracts,
not unsupported exchange account models or economic strategy performance.

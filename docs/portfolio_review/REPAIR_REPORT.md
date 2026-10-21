# Portfolio Account Correctness Repair

Baseline: `5927565`. Authorization: owner request to fix the reproduced
[review findings](../PORTFOLIO_ACCOUNT_REVIEW_2026-10-21.md) and cross-check
affected endpoints. [Repair contract](REPAIR_PLAN.md).

## Repaired Behavior

| Finding | Resolution |
| --- | --- |
| Unsupported account/fill options silently accepted | Generic portfolio supports gross CROSS + NETTING + CLOSE; unsupported isolated/hedging/cash/portfolio margin, alternate clocks, partial fills and ignored margin buffers now raise explicit errors. Event/vectorized/intrabar account boundaries also reject unsupported account modes. Intrabar retains its implemented margin-buffer semantics. |
| Contract multiplier omitted | Shared Series/Numba sizing, legacy classes, event-order signal compilation and prepared WFO target compilation divide currency allocation by price times contract size. DCA base/safety sizing receives the same repair. |
| Funding omitted across dates/gaps | UTC 8h event boundaries are compared by full timestamp. All default events in each carried interval are summed, using the rate available at each event. No first-row carried-position charge. |
| Partial risk reduction rejected below IM | Affordable pure reductions need not restore IM; increases retain strict margin gates. Subsequent symbols cannot spend fictitious buying power created by clipping an earlier IM deficit. Python/Numba and Rust policies covered. |
| Target minimums mistaken for order minimums | Increasing actual delta orders must meet minima after quantity rounding. Pure reductions/closes are explicitly exempt. Rust split-order/rebalance policies recheck their actual orders. |
| Missing marks/legacy constraints | Missing marks carry the last valid price for valuation; fresh orders require a tradable observation. Legacy facade forwards lot/minimum/slippage constraints; accepted units are returned instead of requested signals. |
| NaN config bypasses margin | Shared account, fee/instrument/execution and per-symbol inputs reject nonfinite numeric values before execution. |
| Phantom funding and incorrect leg costs | Kernel-owned funding, leg fee/slippage and liquidation adjustments feed reports. Whole-timeline audit includes liquidation and checks symbol cumulative PnL against the kernel. |
| Heterogeneous buying-power scalar | No mean-leverage notional budget is advertised for heterogeneous leverage. IM and available equity remain explicit; a single scalar buying-power field is unavailable for that case. |
| Timestamp/per-symbol hit-rate/ledger horizon defects | ns/us timestamps share the same statistics; per-symbol hits use carried-side net symbol PnL; closed-ledger completeness must cover the requested report end. |

## Independent Numerical Controls

- Allocation100, price100, multiplier10: entry0.1 contracts, profit1 when
  price rises to101. Native and legacy sizing, event target compilation and
  prepared WFO compilation checked separately.
- Short19 at100, capital2,000, leverage1, fee0.0004; reducing to short18 at110:
  equity1,809.196, closing fee0.044 and accepted position-18. Increase to-20
  remains rejected. Releasing part of a deficient position does not fund a new
  symbol until the actual free margin is positive.
- Daily closes100, rate0.01/event, position opened on row1: equity
  `[1000,1000,997,994]`, funding `[0,0,3,3]`. Gapped rates0.01/0.02/0.03 aggregate
  to0.06; a rate first observed at interval end is not applied retroactively.
- Intrabar liquidation at08:00 before funding: reported funding0, no invented
  close fee, explicit liquidation attribution and exact account reconciliation.
- Opposite100-notional legs, slippage1%, fee1%: actual entry fees1.01/0.99,
  matching kernel leg PnL-2.01/-1.99.
- Missing close100->NaN->100 does not produce a fake100 loss/recovery.
- At close100 and slippage1%, an increasing delta0.5 meets a minimum50,
  but not50.25, for both buy and sell. Admission uses the close mark, whereas
  fees/slippage use the actual fill; no side-dependent filter discrepancy.
- Same daily timestamps at ns/us resolution have identical DD duration and
  annualized statistics. A losing legacy round trip no longer reports100% wins.
- Ledger complete only through time10 cannot report valid closed populations
  for a requested horizon ending30.

These are arithmetic/software controls, not evidence that a strategy earns
money or that meta selection improves economic outcomes.

## Metric Migration

Default scalar aliases are retained for scientific/WFO compatibility. Their
actual populations are exposed in `metric_population`. The text report labels
them `Position State Count`, `Period Profit Factor`, `Mean Positive/Negative
Period Return`, `Long/Short State Hit Rate` and `Max Underwater Daily Closes`.
The displayed expectation is the coherent arithmetic `Mean Period Return`.
The old `expectancy_pct` value remains available as an explicitly described
`legacy_mixed` statistic; it is not labelled closed-trade expected payoff.

For actual closed trades/actions, use the existing `ReportingRequest` and an
authoritative outcome ledger/action roster covering the requested horizon.
Missing evidence remains UNAVAILABLE. No ledger is invented from signal changes.
The explicit reporting contract provides elapsed drawdown episodes; the legacy
underwater-close count is not presented as elapsed recovery time.

## Preserved Domain Limits

The repaired target account is linear quote-settled gross-cross netting.
It does not implement isolated wallets, dual same-symbol side inventories,
venue maintenance tiers or multi-currency collateral. The historical adverse
OHLC/zero-equity liquidation contract is named explicitly. It combines adverse
leg extremes and does not certify synchronous mark-price venue liquidation.
Coarse funding uses the carried position and closing-price proxy to value the
sum of default8h events; finer event/position/mark clocks require an explicit
event tape. These boundaries must not be inferred from enum availability.

The generic `native_portfolio` facade remains Numba-owned. Explicit Rust
shared-account helpers retain their separately declared admission policies.
No engine ownership promotion, optimizer model/default, market-regime method,
release version, CI workflow or publication is changed by this repair.

Historical E04/C02 source-only receipts retain their original claims and bytes.
The new current-source qualification explicitly records that financial Python
and Rust source **changed**, and checks exact committed source trees against
the approved repair manifest. It does not turn old financial-source-invariance
receipts into current certificates. Historical packaging tools assuming an
unchanged native artifact are not current repair qualifiers; source-final core
wheel/sdist, remote/public consumer proof and M5-12 remain separate gates.

## Verification And Cleanup

Local repair contract: **PASS**. Exact source baseline is `5927565`; repaired
financial source is pinned at `9c2bfd9`. Later test/docs commits do not change
those runtime bytes. The [terminal receipt](evidence/repair-qualification.json)
contains individual XML hashes, source identities, artifact hash, historical
failed-attempt dispositions and terminal cleanup measurements.

| Verification | Executed result |
| --- | --- |
| Focused account/metrics/fresh-native controls, final run | 222 passed |
| Cross-endpoint regression, final run | 320 passed; one existing legacy-slippage deprecation warning |
| Reporting, current qualification and negative source guards, final run | 1,040 passed |
| Distinct Python test IDs across all retained runs | 1,544 latest results passed; overlapping reruns are not added |
| Rust execution / portfolio unit tests | 25 / 15 passed |
| Fresh native arithmetic and Python/Numba parity | Included above; actual compatible extension hash checked before execution |
| Changed-document links and anchors | PASS |

Cross-endpoint coverage includes legacy single/multi-symbol, generic portfolio,
native close-target/vectorized, Rust shared-account policies, event lifecycle,
reactive accounting, intrabar reference/kernel/session and prepared/public WFO
contracts. It is focused regression, not a claim that every test in the entire
repository or every possible exchange account model was certified.

The offline CPython3.12 native wheel was built against the repaired Rust source.
Its extension SHA256 is
`9b7812525b008ec361919c3dd53ac0972b0b2f7830c8d95c090be6d318b688af`.
It was loaded process-locally alongside the current core checkout; the primary
environment and published packages were not replaced. Core wheel/sdist clean
installation, other Python/platform matrices and publication are **not** claimed.

Only the registered inactive repair scratch was removed: 17,231,872 observed
available bytes recovered, with 2,547 protected files rehashed unchanged.
Scientific evidence, historical failures, source, wheel, logs, environments,
Cargo/dependency caches and services were retained. A future rerun must extract
the retained wheel again because the disposable extraction was cleaned.

Historical review/test/research evidence remains intact. Source reconciliation
accepts only named committed blobs; mutated/unregistered source bytes are
rejected. No optimizer research, push, CI, merge, tag or release was performed.

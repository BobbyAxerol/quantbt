# MET-01 Contract And Oracle Report

## Status

Implementation: **COMPLETE_SPEC_ORACLE_LOCAL**. Technical gates T01..T08: **PASS**.
Owner phase implementation approval: 2026-10-07; reporting-definition
acceptance: **PENDING**. MET-02/MET-03 remain unapproved/not started.
Performance: **NOT_MEASURED**. Empirical: **NOT_ASSESSED**. No remote action,
artifact rebuild, financial replay, calibration, release or publication.

## Source And Work

Baseline parent `dc8edd8`, branch `feat/meta-selection-samplers`, clean on entry.
Schema/inventory commit `9e77c00`; qualified additions are separately hashed in
the [passing source receipt](evidence/met01/run-20261007T183109306830Z/receipt.json).
[Baseline](evidence/met01/baseline.json) protects **322 existing** Python,
Rust, mirror and packaging files. Every protected SHA256 is unchanged.
The [source census](evidence/met01/run-20261007T183109306830Z/source-census.json)
registers metric references in 60 existing source files. The
[inventory/dictionary](INVENTORY.md) maps producer, consumer, route/profile,
scope, raw completeness and compatibility/scientific units.

Added internal frozen reporting policy/coverage/value schemas with full-field
serialization and separate report identity. No public export, endpoint
parameter/default change, replacement `full_report`, WFO/Optuna/meta scorer
change or native accounting change. Independent reference arithmetic lives in
tests only; it observes marks and already-attributed outcomes, not financial
matching or reconstruction of execution. Expected fixture values are handwritten.

Testing uses CPython 3.12.13 with **current `src/quantbt`**, NumPy 2.2.6,
pandas 2.3.3, pytest 9.1.1 and pinned source-hashed QuantStats 0.0.81.
The reused tooling environment still has installed core 1.1.1/native 0.4.2;
these are recorded, not mislabeled as the source's prepared 1.1.2/0.4.3 pair.
Native execution is not invoked; its existing extension hash is recorded.
This is not installed-artifact/native/remote qualification. No new dependency.

## Qualification

Final numeric/schema source run: **452 passed, 0 failed, 0 skipped**, pytest
6.50 s. Of these, 322 check unchanged production hashes and **130** are
functional, schema, comparison, raw-boundary or existing regression tests.
Groups overlap intentionally; do not sum group counts as distinct tests.
Commands, stdout/stderr, JUnit, source/input hashes and runtime are retained.

| Gate | Result / covered interpretation |
|---|---|
| MET01-T01 | Producer/consumer/raw-field inventory; entire registered source unchanged |
| T02 | Full/scoped baseline, initial costs, partial short-run CAGR, bankruptcy, cashflow rejection, invalid inputs |
| T03 | Recovered/open DD, latest equal peak/earliest equal trough, deepest vs longest, gaps, UTC/DST/intraday/ns clocks, tolerance preserving raw depths |
| T04 | Manual period mean/geometric growth, variance/Sharpe, all/conditional downside, MAR, flat/all-win/all-loss/short/undefined cases |
| T05 | Opposite-leg action grouping, unrelated open position, partial closure/reversal identity, fee/funding credit/slippage no double count, ledger omissions, currency/scope/streak/tolerance |
| T06 | Pinned QS same-convention agreement and explicit legacy/QS differences |
| T07 | Immutable schema, every policy preserved in JSON, partial/unknown metadata rejected, missing/truncated vs empty coverage, finite/null/status distinction |
| T08 | No new production consumers/dependencies, exact raw-object/report/scientific identity preservation, docs/anchors/privacy/cleanup |

Retained earlier runs: [first failure](evidence/met01/run-20261007T182701901759Z/receipt.json),
[intermediate pass](evidence/met01/run-20261007T182807407279Z/receipt.json),
[oracle-extension failure](evidence/met01/run-20261007T183005354531Z/receipt.json).
The first test incorrectly assumed the historical metrics package imported no
backends: existing `core.__init__` already does. The corrected differential
check blocks actual native/reporting dependencies, proves the schema standalone
is stdlib-only and adds no backend beyond the unchanged legacy import graph.
The later failure caught a misplaced test-oracle payoff field; fixed in test
code, with no changed fixture arithmetic/tolerance/production code. Historical
FAIL receipts remain FAIL; no gate was waived to declare completion.

## Concrete Findings

- First retained equity 90 with recorded starting balance 100: report V1 sees
  -10% return/DD; legacy return is -10% but legacy DD/CAGR is zero. This is
  baseline interpretation, not a changed engine loss.
- Daily `100,90,95,100`: 2 observed underwater marks, 2 inclusive underwater
  days, **3 elapsed peak-to-recovery days**. Jan 1/4/7/8 gaps: still 2 marks,
  **4 inclusive days / 7 elapsed days**. Intraday recovery after 2 h is 2 h,
  not QS's 1-day floor or legacy daily-close zero count.
- Returns `[1%,2%,-1%,0]`: period PF 3, full-N Sortino 1 versus conditional
  0.5 (unannualized), account-period win rate 50% versus QS nonzero 66.67%.
- Net closed legs `+100,-80,-30,0`: trade win rate **25%**. Group the first
  two into one authoritative action: action results `+20,-30,0`, win rate
  **33.33%**. One unrelated open leg is excluded; it does not block the action.
- Flat two-symbol legacy report still counts 2 `num_trades`; keep that legacy
  scientific alias unchanged, never advertise it as two closed trades.
- QuantStats raw currency flat 20,000 produces -80% DD under its preparation
  heuristic; a prepared flat-return series correctly gives zero. QS's
  first-loss episode parser can omit an open episode. External agreement is
  not a substitute for an explicit baseline/time/population contract.

## Boundary, Dependencies And Next Approval

No new raw accounting defect was found by these reporting tests; this does not
re-certify all financial engines. Missing matching/net-cost/campaign/FX/risk/
path/calendar data are capability dependencies, explicitly **unavailable**,
not zero trades/actions or an implicit engine expansion. Existing scope slices
retain initial capital and unsliced ledgers; report V1 must use a recorded
scope-entry baseline and verified row/carry attribution in MET-02/03.

Please review the [V1 definitions/default proposal](REPORTING_CONTRACT_V1.md#coverage-and-review):
baseline-inclusive DD, exact elapsed/censored durations, separately named
period/closed-trade/closed-action statistics, proposed zero tolerance,
all-observation downside (with explicit conditional alternative), unavailable
short-run CAGR/undefined values and complete-ledger capability requirements.
No legacy/native scientific metric migration is requested. MET-02 may start
only after these definitions and that phase are separately accepted.

No performance improvement is claimed in this spec-only phase. Measured
read-only reducers/reporting latency, same-contract Rust/Numba parity, WFO
sentinels and exact wheel/sdist proof belong to later approved phases.

## Resources

See the [cleanup receipt](../maintenance/MET01_CLEANUP.md). Reused tooling only;
phase-owned scratch removed, all test/evidence/log hashes preserved. Final
numeric run retained 80,550 bytes before its receipt; observed free disk change
-102,400 bytes, not an optimization/reclamation claim.

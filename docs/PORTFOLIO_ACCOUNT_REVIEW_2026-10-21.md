# Portfolio Account And Metrics Review

Follow-up: the owner approved repairing these findings. Current implementation,
numerical controls and migration details are in the
[repair report](portfolio_review/REPAIR_REPORT.md). This original review and its
receipts remain historical evidence of the pre-repair behavior.

Date: 2026-10-21. Review baseline: `6e900b5`, branch
`feat/mode5-diagnostics-first`. This is an investigation, not a runtime repair,
new financial contract, release certificate or new research phase. No alpha,
optimizer, financial methodology, engine or metric reducer was changed.

## Conclusion

The implemented linear, quote-settled, one-net-position-per-symbol shared
account works on ordinary controls. It is **not a complete exchange account
simulator**, and several reproducible defects remain. In particular, accepting
an isolated/hedging configuration does not mean those account models execute.
Passing native-versus-legacy parity can preserve the same error on both paths.

Some findings affect financial execution and raw output, not just presentation.
Existing research evidence should be assessed against its exact contract;
these findings do not establish that every previous research result is wrong.

## Routes Actually Inspected

| Surface | Actual owner | Account/execution model |
| --- | --- | --- |
| `QuantBTEndpoint.portfolio(backend="native_portfolio")` / `PortfolioBacktestEngine` | Python preparation + Numba `_engine_portfolio` or equity-sizing kernel | One shared equity, signed net units per symbol, gross margin, atomic target rebalance at close |
| `backend="legacy_portfolio"` / `MultiSymbolPortfolio` | Legacy preparation + same Numba portfolio kernel | Same shared account, fewer input/report protections |
| Legacy `BacktestEngine` with symbol mappings | Numba unit/equity kernels through legacy wrapper | Shared equity; reported position history has a separate defect described below |
| `run_shared_portfolio_target_market` | Explicit typed Rust shared-account target executor | Linear gross-cross account; sequential, reduce-first, pro-rata, all-or-none admission |

`native_portfolio` does not mean Rust. The explicit Rust helper is not the
default generic portfolio endpoint. Both representations allow long A and
short B simultaneously. Neither represents simultaneous independent long and
short inventories in the **same symbol**, as required for exchange hedge mode.
`market_neutral` is an allocation transform, not hedge-mode accounting.

Entry points: [endpoint](../src/quantbt/endpoint.py),
[facade](../src/quantbt/engines.py),
[native portfolio](../src/quantbt/backends/native_portfolio.py),
[legacy portfolio](../src/quantbt/portfolio.py),
[Rust shared target](../src/quantbt/backends/native_portfolio_package.py).

## Independently Checked Correct Behavior

For linear quote-settled contracts, within this simulator's declared clock:

```text
signed_notional_s = q_s * mark_s * contract_size_s
mark_pnl_s       = carried_q_s * (close_now - close_previous) * contract_size_s
initial_margin   = sum(abs(notional_s) / leverage_s)
maintenance      = sum(abs(notional_s) * maintenance_ratio)
funding_cost_s   = carried_q_s * close_s * contract_size_s * event_rate_s
fee_s            = abs(delta_q_s) * execution_price_s * contract_size_s * fee_rate
slippage_cost_s  = abs(delta_q_s) * close_s * contract_size_s * slippage_fraction
```

Leverage controls admissible exposure; it does not multiply requested allocation
or multiply PnL again. Long/short legs do not cancel **gross** margin merely
because net notional is zero. Positive funding debits longs and credits shorts.
Funding is on carried positions before the current close rebalance. Reversal
turnover uses the full delta: `+1 -> -1` trades two units.

Independent two-symbol control: initial equity 1,000; long two units at 100 and
short three at 50; next closes 110/45; fee 0.001 one-way and one funding event
0.01. Expected and actual equity are exactly, to 1e-9:
`[1000, 999.65, 1033.8, 1033.445]`. Funding nets to 0.85; entry/exit fees are
0.35/0.355. This is a deterministic arithmetic check, not a trading result.

Other existing passing tests cover reversals, post-cost buying-power rejection,
equity sizing, missing-leading prices on native portfolio, full/minimal report
accounting parity and explicit Rust admission policies.

## Confirmed Findings

### F01: Account And Execution Options Silently Ignored (P1)

`AccountConfig` exposes `margin_mode`, `oms_mode`, `margin_buffer`; portfolio
execution never consumes them. Eight CASH/ISOLATED/CROSS/PORTFOLIO x
NETTING/HEDGING combinations all accept the same 1,500 notional against 1,000
equity at leverage two, even with `margin_buffer=0.5`.

Similarly, `ExecutionConfig(fill_price_policy=NEXT_OPEN/OPEN)` runs the same
close execution as CLOSE. A 100-notional order still fills with
`min_order_notional=1000`. Legacy facade also drops its execution slippage
configuration. Partial-fill/liquidity policy is not implemented here.

Sources: [schema](../src/quantbt/core/schema.py) lines145-192,
[native configuration use](../src/quantbt/backends/native_portfolio.py) lines137-167,
[legacy forwarding](../src/quantbt/engines.py) lines743-779.

Action: explicitly reject unsupported modes/options, or introduce separately
specified account/clock implementations. An isolated wallet per position and
two same-symbol side inventories cannot be obtained by changing a flag.

### F02: Contract Multiplier Missing In Some Notional Sizing (P1)

Allocation100, price100, contract_size10 requires 0.1 contracts. Native
`signal_notional` and legacy `signal_notional/notional/unit` request1 contract,
exposing1,000. Price100->101 produces profit10 rather than1. Native `notional`
and `unit` correctly produce profit1 in the same control.

Native `signal` shares the affected helper. Contract_size1 hides the defect.
Legacy stock defaults use contract_size100; that convention needs explicit
product interpretation and must not be confused with one-share stock units.

Sources: [native sizing](../src/quantbt/backends/native_portfolio.py) line400,
[fast sizing](../src/quantbt/sizing/fast.py) line36,
[legacy sizing](../src/quantbt/portfolio.py) line181.

### F03: Funding Clock Misses Events (P1)

`make_funding_mask` compares only hour values. A daily UTC index is always hour0,
so every mask value is false. Held positions with nonzero rate receive no funding.
12h and irregular grids miss events as well. One boolean per bar cannot express
several funding settlements inside a coarse bar. The docstring's claim of any
bar frequency is therefore too broad.

Hourly aligned default 00/08/16 funding works in the positive control. The
generic surface nevertheless has no per-symbol historical event calendar or
independent mark-price tape. Forward-filling rate observations is not a complete
funding-event policy. Direct facade/class defaults can also synthesize0.0001
when funding is enabled and no rate supplied; explicit endpoint config should
be distinguished from those defaults.

Source: [preprocessor](../src/quantbt/core/preprocessor.py) lines98-145.
Rust's typed helper accepts an explicit mask; callers still must construct the
correct events and rates. It uses close valuation in this contract.

### F04: Risk-Reducing Target Can Be Rejected Below Initial Margin (P1)

Capital2,000, leverage1, short19 at100, fee0.0004. At110, equity1,809.24 remains
far above maintenance10.45. Request reduction to short18: remaining IM1,980,
maintenance9.90, closing fee0.044. Native/legacy portfolio rejects it because
equity after costs is below remaining **initial** margin. Requested reduction
would reduce risk with resulting equity1,809.196.

Rust `sequential_legacy` reproduces rejection; Rust reduce-first, pro-rata and
all-or-none policies accept the reduction in tested controls. A full close is
not the same case: target IM is then zero. This finding is specifically partial
risk reduction while under IM but above MM.

Sources: [Numba gate](../src/quantbt/core/engine.py) lines740-765 and994-1018,
[Rust admission](../rust/crates/quantbt-execution/src/target.rs) lines1813-2075.
Repair should preserve stricter gates for increasing exposure and define mixed
reduce/increase atomic rebalance behavior explicitly.

### F05: Legacy Missing Marks And Dropped Constraints (P1)

Legacy `MultiSymbolPortfolio` converts an original NaN price to zero in its
kernel arrays. Holding one contract through `[100,100,NaN,100]` produces
equity `[1000,1000,900,1000]` without a genuine price loss. Its all-true tradable
mask also permits stale-price fills after absent timestamps are forward-filled.

The `legacy_portfolio` facade does not pass quantity constraints or execution
slippage to its underlying class. With allocation15 at price100, qty_step0.1,
min_notional200, it still fills0.15 contracts and charges no configured slippage.
Native portfolio rejects that same below-minimum entry.

Sources: [legacy array conversion](../src/quantbt/portfolio.py) lines268-313,
[legacy facade](../src/quantbt/engines.py) lines743-779.

### F06: Invalid Leverage Bypasses The Generic Margin Gate (P1)

`leverage=NaN` is accepted by the native per-symbol path; comparisons with NaN
margin are false, so the engine opens10,000 notional against1,000 equity and
reports NaN initial margin. Its portfolio contract audit still says PASS.
Simple positivity comparisons do not reject NaN in several shared config fields.

Sources: [array conversion](../src/quantbt/backends/native_portfolio.py) line899,
[schema validation](../src/quantbt/core/schema.py) line156,
[margin gate](../src/quantbt/core/engine.py) line764.
This needs fail-closed finite/positive validation before JIT execution.

### F07: Legacy Backtester Publishes Requested Signals As Positions (P1)

Legacy `BacktestEngine` with symbol mappings, capital50, leverage1 and a100
notional request rejects the entry financially. Equity remains50, but public
`Position_A` is `[0,1,1,1]`, and `num_trades=3` across A plus a flat B. The wrapper
publishes its input signals instead of accepted units. Do not conflate this
class with `MultiSymbolPortfolio`, which does receive accepted positions.

Source: [backtester](../src/quantbt/backtester.py) lines326-345.

### F08: Target Constraints Do Not Ensure Valid Delta Orders (P2)

Native and explicit Rust shared targets validate/quantize total target position.
Starting at1 contract and requesting1.1 creates a0.1-contract increase even with
min_qty0.5/min_notional50 at price100. Existing target-level semantics are not
equivalent to applying exchange order filters to the delta. Increasing exposure
below venue minimum is not explained by close-only exemptions.

Sources: [target quantization](../src/quantbt/backends/native_portfolio.py) line225,
[Rust target resolution](../rust/crates/quantbt-execution/src/target.rs) line1760.
This is a target-versus-order domain gap to resolve explicitly before claiming
exchange filter fidelity; do not silently change target contracts.

### F09: Reported Attribution Does Not Always Match Execution (P2)

On an intrabar-liquidated bar at08:00, the kernel exits before funding. The
report reconstructs funding from previous units and shows a10 debit anyway.
In the reproduced case equity loses100, reconstructed symbol PnL loses10 and
reconciliation residual is-90. The contract audit says PASS because it excludes
the liquidation bar. Rust's tested shared helper correctly reports zero funding
for this case and has an explicit liquidation-loss allocation.

Opposite-side legs with slippage provide another mismatch: two100-notional
legs, 1% slippage, 1% fee produce exact entry fees1.01/0.99. Native report splits
them1.00/1.00, while kernel per-symbol PnL is-2.01/-1.99. Aggregate equity remains
correct; leg attribution is wrong at that bar.

Sources: [funding reconstruction](../src/quantbt/backends/native_portfolio.py) line554,
[fee attribution](../src/quantbt/backends/native_portfolio.py) lines730-743,
[audit exclusion](../src/quantbt/reporting/portfolio_audit.py) lines62-67.

### F10: Buying Power Label Is Not An Available-Notional Budget (P2)

The report uses `equity * mean(leverage)`. For equity1,000 and leverages1/10,
it reports5,500. Equal-notional allocation actually permits gross1,818.18 before
costs, from `N/2 + N/20 <= 1000`. With100 notional on each symbol, IM is110 and
free equity890. Additional admissible notional depends on which leg is bought;
there is no allocation-independent5,500 allowance.

Source: [exposure report](../src/quantbt/backends/native_portfolio.py) lines776-797.
The actual kernel uses per-symbol IM correctly; the report's scalar is misleading.

## Metrics Findings And Interpretation

The default report deliberately preserves legacy aliases. They must not be read
as the new closed-trade/action metrics:

| Default field | Actual population | Verified consequence |
| --- | --- | --- |
| `num_trades` | Initial row per symbol plus quantity transitions | Two flat symbols yield2; one round trip on each of two symbols yields6 |
| long/short hit rate | Account-return sign masked by current symbol side, averaged across symbols | A losing short leg gets a positive hit-rate contribution when the other leg makes account PnL positive |
| `profit_factor` | Sum positive account-period returns / absolute negative returns | +10 long, -5 short has account PF infinity; closed-leg PF would be2 |
| `avg_win/loss` | Account-period returns | Not average currency profit/loss per trade |
| `expectancy_pct` | Side-hit-rate average mixed with period average win/loss | Not expected payoff of one consistent closed population |
| `max_dd_duration_days` | Count of observed underwater daily closes | Intraday DD16.67% can coexist with0 days; missing days are not elapsed calendar duration |

The mixed-population expectancy should not support a per-trade claim. These
compatibility behaviors were already documented; changing them requires a
version/label migration rather than silently altering optimizer statistics.

Three further defects were independently reproduced:

1. **Timestamp units:** identical daily timestamps as ns versus us change DD
   duration2->0. `_array_daily_equity` and annualization assume every raw integer
   index is nanoseconds. This is a representation bug, not a statistical convention.
2. **Legacy per-symbol hit rate:** prices100->200->100, position0->1->0,
   allocation100, capital1,000 end at900, but `hitrate_per_symbol()` reports100%
   long wins. It credits the move before entry and excludes the exit-bar loss.
3. **New closed-ledger completeness:** a ledger valued through time10 is accepted
   as complete for a report ending30. Closed_count1 and win_rate100% are marked
   valid. Coverage must cover the requested horizon, not merely declare the
   retained snapshot complete. The same early gate serves closed-action reduction.

Sources: [legacy metrics](../src/quantbt/metrics/performance.py) lines358,397,480-523;
[per-symbol hits](../src/quantbt/portfolio.py) line583;
[new ledger reducer](../src/quantbt/metrics/reporting/ledger.py) line93.

The opt-in `ReportingRequest` path correctly exposes account-period,
closed-trade, closed-action and execution groups separately. On an actual
portfolio result without outcome ledger, closed-trade/action and execution are
UNAVAILABLE, not invented from position differences. Its account/drawdown and
ledger arithmetic tests pass in the checked suite, but the stale-horizon defect
above remains. Empty `fills`/`trades` on generic portfolio means absent retained
event ledger, not evidence of zero executed trades.

## Model Fidelity Limits To Specify Separately

- **Cross versus isolated:** a gross-cross scalar account is implemented; separate
  isolated collateral, isolated liquidation and margin transfers are absent.
- **Net versus hedge:** signed net inventory per symbol; distinct side inventories,
  hedge-side fees/funding/margin and close-side flags are absent.
- **Liquidation:** worst long-low and short-high are combined across all symbols,
  potentially from different instants. A constructed synchronous pair with
  identical prices70..130, +5/-5, capital100 stays at equity100 with MM<=6.5;
  OHLC worst-case aggregation liquidates it to0. This is a conservative stress
  convention, not observed simultaneous portfolio liquidation.
- **Settlement:** liquidation forces entire account equity0. This historical
  convention is distinct from venue partial liquidation, residual collateral,
  liquidation fees, bankruptcy price and insurance/ADL handling.
- **Margin:** one fixed maintenance ratio; no per-symbol tier ladder, maintenance
  amount deduction, dynamic brackets, exchange portfolio-margin offsets or
  multi-currency collateral haircuts. Pending-order reserved buying power is not
  part of close target-matrix execution.
- **Fill model:** complete target fills at configured close-plus-slippage; no volume
  cap/order-book/partial-fill simulation on generic portfolio. Initial row is a
  frozen initial state; signals must be causal for that actual close clock.

Exchange reference only, not a claim of certification: Binance documents
[funding on marked position value and variable intervals](https://www.binance.com/en/support/faq/detail/360033525031),
[maintenance brackets and amount deductions](https://www.binance.com/en-PH/support/faq/detail/360033162192),
and [mark-price liquidation and hedge/cross behavior](https://www.binance.com/en/support/faq/detail/360033525271).
The current simplified simulator should be described accordingly.

## Verification And Remaining Gates

Reproducer: [tools/portfolio_account_review.py](../tools/portfolio_account_review.py).
All scenarios are public synthetic arithmetic examples; no private alpha/data.
Receipts are retained in the ignored `upgrade/private/portfolio_account_review/attempt-01/` lane.

1. Initial portfolio suite:97 PASS/1 FAIL. Failure is an incompatible default
   environment pair: core1.1.2 versus installed native metadata0.4.2.
2. Reused existing retained0.4.3 artifact with an explicit process-local import
   path; no environment mutation/install/rebuild. All36 Rust shared-portfolio
   tests pass. Combined follow-up suite:209 PASS/1 FAIL.
3. The remaining failure is a historical MET02 protected-source hash for
   `rust/crates/quantbt-engine/src/orders/aliases.rs`; current content predates
   this review (commit5c8e10a). No guard or old receipt was relaxed. This is an
   outstanding source-reconciliation gate, not an accounting test failure.
4. Across suites:272 distinct tests,271 pass on their applicable final execution,
   one source guard still fails. Original environment-failure receipt is retained.
5. Positive arithmetic control plus separate negative reproductions confirm the
   findings. Passing existing tests does not override those reproduced defects.

Native file hashes, structured synthetic outputs and terminal cleanup inventory
are linked in the [sanitized receipt](portfolio_review/evidence/2026-10-21.json).
The retained0.4.3 artifact is compatible local evidence, not a newly built
source-final wheel certification. No claim is made about an untested PyPI install.

## Recommended Repair Order

1. Fail-closed account/execution/finite-input capability validation; correct sizing
   multipliers, missing-data handling and legacy accepted-position outputs.
2. Explicit funding events and risk-reduction margin admission; distinguish target
   constraints from actual order constraints. Lock independent numerical oracles.
3. Authoritative funding/liquidation/per-leg cost attribution and valid buying-power
   labels; account-period versus closed-ledger metrics, timestamp normalization and
   ledger horizon checks. Preserve versioned scientific compatibility.
4. Reconcile accepted historical source receipts and qualify exact final artifacts.
   Exchange hedge/isolated/tiered/mark-price behavior is additional domain scope
   requiring explicit contracts, not merely turning on existing enum values.

This review does not activate those repairs or any CI/release workflow.

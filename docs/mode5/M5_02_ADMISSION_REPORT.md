# M5-02 - Five-Alpha Actual Execution Admission

## Scope And Status

Local binding admission under the
[approved plan](../../upgrade/implement.md#mode5-m5-02) and
[M502.01..06 guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-02--four-alpha-economics-admission-và-actual-quantbt-route).
All five registered bindings pass their declared contracts. This is not a
new selector, public endpoint, economic promotion or distribution certificate.
No QuantBT financial source, alpha original, methodology/default, package
version or installed native extension was changed.

Full private profiles, parameters, paths, fills/campaigns, commands and failed
attempts remain in ignored owner-local lanes. This report discloses technical
coverage only. Economic results and private schemas are not published here.

## Identity And Calendar

- Branch: `feat/mode5-diagnostics-first`; source core 1.1.2 / native 0.4.3
  in the retained tooling environment, not the primary environment.
- Guide SHA-256: `661a2a3d83eed2b2592bfb98e3b4f8e3aa34bcd9740ec6b50c812f73753b99fe`.
- Cache-first ETHUSDT 1h: 2,184 scored bars / 91 days with 8,760 causal preload
  bars. Financial accounts start fresh at the common scored boundary;
  preload initializes indicators, not account/orders/positions.
- Data role: `EXPLORATORY_REVIEWED_2024`, never untouched confirmation.
  One frozen admission candidate per row, no optimizer or outcome-based ranking.
  The common ETH pilot is not a replay or economic comparison of historical
  BTC cohorts in the supplied research bundles.
- Source/input/dependency origins, exact commands, hashes and retention policy
  are sealed privately. Original ZIP disposition remains the owner's accepted
  M5-01 guide/extracted-member baseline; no archive certificate is invented.

## Actual Route Matrix

| Alpha | Actual public route | Backend | Exercised coverage |
|---|---|---|---|
| A-SC | `event_driven(strategy=...)` | requested/resolved Python | Long-flat actual fill feedback; opposite signal exits without shorting |
| A-HMA | `event_driven(input_mode="orders")` | requested/resolved Python | Canonical adaptive features, actual-fill gap handling and bracket lifecycle |
| A-VWAP | `event_driven(input_mode="orders")` | requested/resolved Python | Closed HTF availability, actual-fill bracket, delayed amendments and time stop |
| A-HASH | `event_driven(input_mode="orders")` | requested/resolved Python | Three remaining-fraction rungs, venue constraints, partial inventory and flat-only cooldown |
| A-RSI | existing `pct_equity` | legacy target engine | Exact original signal/account route, prefix and future-mutation parity |

Four event bindings use `event_lifecycle_v3_next_open`. Quote size is requested
at observation close and executed next open; it is not a promise of exactly
the same quote notional after an opening gap. One-way fees use actual executed
notional. Terminal policy is mark-only, without hidden flattening.

RSI retains its existing close-based strategy state and established legacy
account contract. Wrapper versus direct-engine equity, positions, returns and
closes match exactly. This route does not export an order-fill ledger or
separate fee/funding/margin streams; unavailable fields stay unavailable, not
fabricated from position transitions. It is admitted only on that target scope.

## Repairs And Existing Capabilities

1. Existing public callbacks observe fills after the bar's execution; they do
   not expose an intrabar `on_fill` hook. SC needs only bar-close feedback.
2. Protection-dependent bindings use a bounded **offline actual-feedback
   compiler** on the existing static order lifecycle. Every pass gets actual
   QuantBT fills/rejections in engine event order and starts a fresh adapter
   and account. Parent activation supports same-bar fill-derived protection;
   close amendments activate next bar. No guessed fill or new matching engine.
3. Certification requires identical decisions/commands and full actual output,
   including fill price/quantity/fee, orders, event sequence/reasons, terminal
   state, equity, positions, costs, funding, margin and turnover. A second exact
   engine execution, independent ledger and causal prefix checks are mandatory.
   Cycles, unmapped feedback and the 256-run bound fail closed. Equality of
   exit bars or final equity alone is rejected.
4. The first VWAP candidate had insufficient market fills and remains a failed
   receipt. One separately registered higher-timeframe candidate exercises the
   binding on the same calendar. This is not evidence of parameter superiority.
5. Lot-size tests found duplicate quantity rounding in the new lab transport.
   The corrected binding submits raw quantities for the engine's single venue
   quantization, while the canonical ladder helper supplies the expected
   accepted-quantity witness. ALL exits use reduce-only parent capacity.
   Genuine residuals remain open; no tolerance-driven artificial flat/cooldown.
   Repair-induced changes in private pilot outcomes are recorded separately
   from methodology changes. Earlier paths and failures remain unchanged.

HMA canonical modes/aliases are verified-existing; no silent-default bug was
reintroduced. Internal HMA adaptation is retained. HASH is not collapsed to
one TP, and VWAP amendments are not discarded. Legacy guessed-fill golden
helpers remain outside the qualification path.

## Tests And Measurement

**55 PASS / 0 FAIL / 0 SKIP** in the final focused suite: 29 public synthetic
tests plus 26 private source/adapter integration tests. M5T-011..020 each have
executed assertions, not just a source-review label.

| Requirements | Executed checks |
|---|---|
| M5T-011/012 | Integer collisions, scalar/vectorized signals, explicit volume branches; actual long-flat opposite-signal exit |
| M5T-013/014 | Four HMA modes and aliases, unknown-mode rejection, ignored keys, active lower clamp; actual gap exit |
| M5T-015/016 | HTF prefix availability and span-dependent preload on one actual engine score calendar; time-stop toggle and next-bar amendment |
| M5T-017/018 | Actual 40% / 24% / 36% ladder, rounding and minimum constraints, remaining stop quantity, residual and cooldown |
| M5T-019 | Exact public constant-price 2,000-notional golden: 0.8 fee per one-way fill; MTM, reversals and rejection accounting |
| M5T-020 | Assumed fills/unsupported binding/no-fill support rejected; altered prices, fees, reasons and account paths invalidate full feedback |

Actual market qualification additionally checks all five bindings at a
1,092-bar prefix, then changes future OHLC and volume. Earlier decisions and
account paths remain exact. HMA/VWAP/HASH replay saved full tapes twice, rebuild
the original decisions/commands from actual feedback and independently replay
the prefix. SC reruns its actual callback; RSI reruns the unchanged target path.

Event binding reconciliation has maximum equity difference **0** in the
registered pilot. Independent checks also cover executed inventory, fees,
turnover, campaign PnL allocation, margin and the declared zero funding path.
Actual timestamps, OCO/parent ordering, amendments, gap priority, rejection and
terminal state remain engine-authoritative. Zero-fills cannot certify admission.

## Cost, Retention And Limits

The corrected five-row pilot took **560.962 s**, peak process RSS **359.789 MiB**.
Protection compilation used **242 / 73 / 115 actual engine runs** respectively;
this is certification/recompilation cost, **not** a single-run kernel benchmark
or a Rust speedup claim. Full/prefix verification reuses actual retained tapes,
not mutable account state. No baseline/T1/T2 search panel was rerun, and there
were zero optimizer trials, Rust rebuilds or distribution builds.

Earlier blocked/failed probes and the brief earlier test/pilot overlap remain
historical. Their timings are not a matched performance comparison. The final
pilot, final focused suite and final replay qualification ran sequentially.

This phase does not add an online intrabar fill-reaction callback, certify
arbitrary candidates/calendars/backends, recover missing legacy fill streams,
or establish long-horizon transfer/selector superiority. Those are explicit
scope boundaries, not silently replaced financial behavior. M5-04 preparation
and computation planning must retain the real replay cost when budgeting
later research; a non-converged candidate is blocked rather than approximated.

## Preservation And Handoff

The [sanitized seal](evidence/m5-02.json) binds final receipts and protected
identities; [cleanup](../maintenance/M5_02_CLEANUP.md) lists exact deleted scratch
and retained evidence. The full local report and private harness snapshot
retain effective schemas/readiness, unsuccessful attempts and economic values.
Privacy/source checks and public synthetic package canaries cover this source
change; no new wheel/sdist/native publication is claimed.

All in-scope admission gates are complete locally. No unresolved binding
correctness blocker remains in the registered scope. Owner review and separate
approval are required before M5-03. No push, CI, merge/tag or release occurred.

Public reproduction (no private inputs required):

```bash
PYTHONPATH=src python -m pytest -q tests/mode5/test_admission*.py
```

Owner-private reproduction uses `tools/run_mode5_admission.py` with a fresh
registered attempt and retained private scripts/configuration. Receipts are
append-only; do not overwrite a passing or failed lane to rerun it.

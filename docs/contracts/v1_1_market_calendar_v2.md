# V1.1 Canonical Market And Calendar V2

Machine contract: [`v1_1_market_instrument_v2_contract.json`](../../contracts/v1_1_market_instrument_v2_contract.json).

`CalendarPlanV2` is the only calendar contract for a route that claims V1.1
multi-symbol certification. It owns one canonical UTC clock and one explicit
`SymbolCalendarMapV2` for each lexicographically normalized symbol. A map
contains canonical-to-local and local-to-canonical offsets plus `observed`,
`stale`, and `tradable` flags. A source bar is tradable only when it is
observed; a stale mark is never implicitly executable.

## Policies

- `exact` is the certified default. Timestamp order and length must match
  exactly. The first divergent row and both timestamps are reported.
- `intersection` retains only timestamps observed by every symbol. Dropped row
  counts remain in calendar metadata.
- `union` retains every timestamp. Missing OHLCV remains `NaN`; it is not
  forward-filled into an observed bar.
- `primary_clock` uses the declared primary symbol clock and maps every other
  symbol to it without relabeling source rows.

`missing_policy` only changes the separate marking projection. `no_observation`
and `reject_intent` retain no inherited mark. `mark_to_last_no_execution` and
`forward_fill_quote_no_volume` may expose `mark_closes` after an observation,
but raw OHLCV remains missing and `tradable=False`.

## Handle Lifetime And Execution

```python
market = QuantBTEndpoint.prepare_market(
    data={"BTC": btc, "ETH": eth},
    calendar_policy="exact",
)
```

The returned `PreparedMarketHandleV2` is immutable, fingerprinted, reusable,
and context-manager compatible. `close()`/`release()` invalidate the handle;
`PreparedMarketCacheV2` is bounded and explicitly evicts/invalidates old
entries. Passing `cutoff_timestamp` freezes a causal view, so future source
rows cannot alter its map or fingerprint.

Current V1 static/target/package lowering accepts only an all-observed view
with a shared funding-event clock. `union`/`primary_clock` missing data fails
closed at lowering rather than fabricating OHLC. That is an explicit capability
boundary, not a fallback to legacy `fillna` behavior.

Historical WFO reproduction can request `calendar_contract="legacy_v1"`.
Certified WFO defaults to `exact_v2` and rejects equal-length shifted sources.

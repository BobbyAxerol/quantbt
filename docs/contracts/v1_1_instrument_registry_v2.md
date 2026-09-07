# V1.1 Instrument Registry V2

Machine contract: [`v1_1_market_instrument_v2_contract.json`](../../contracts/v1_1_market_instrument_v2_contract.json).

`InstrumentRegistryV2` is the canonical rule source for each normalized symbol.
It is an additive adapter over the public `InstrumentSpec` and legacy endpoint
fields, so existing names such as `contract_size`, `qty_step`, `min_qty`, and
`min_notional` remain valid. The resolved registry records a deterministic
fingerprint and owns:

- price tick and quantity step;
- minimum/maximum quantity and minimum notional;
- contract multiplier, leverage limit, settlement currency;
- fee/funding schedule IDs and canonical one-way fee;
- purpose-aware price and quantity rounding policy.

## Quantization

`limit_buy` rounds down to tick and `limit_sell` rounds up, preserving passive
price improvement. Stop, risk-increasing, risk-reducing, liquidation, and hedge
references round conservatively: buy up, sell down. Risk-increasing quantities
round down to the lot step. A risk-reducing order cannot exceed the current
position; an exact remaining close may retain a sub-step remainder so a
reduce-only close never reverses the position.

```python
instruments = QuantBTEndpoint.prepare_instruments(
    specs={"BTC": btc_spec, "ETH": eth_spec},
    leverage={"BTC": 3.0, "ETH": 2.0},
    fee_rate=0.0005,
)
plan = QuantBTEndpoint.prepare_execution_plan(
    market=market,
    instruments=instruments,
    timing_contract="event_lifecycle_v3_next_open",
)
```

The execution plan fails before a run if market and registry symbol layouts or
fingerprints are incompatible. The current static event and promoted Rust
market-package adapters can lower the registry through the compatibility table;
their multiplier/leverage/fee arrays therefore come from the same registry,
not separate per-workload inputs.

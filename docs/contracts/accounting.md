# Accounting Contract

QuantBT uses a canonical one-way fee convention: `fee_rate` is the fee charged
for each fill direction. Opening and closing a position each incur the declared
one-way rate. The legacy `fee` parameter remains a compatibility input and is
translated at the endpoint boundary before accounting begins.

For every accepted target change:

```text
delta_qty       = accepted_target_qty - previous_qty
traded_notional = abs(delta_qty) * fill_price * contract_size
fee             = traded_notional * canonical_one_way_fee_rate
slippage_cost   = execution-price effect of the accepted delta_qty
```

The same accepted delta is used for turnover, cash impact, fee, slippage, and
rebalance reporting. Leverage creates buying power from current equity; it does
not multiply a fixed allocation. Margin and liquidation checks use current
equity after accepted execution costs.

The certified native account model is linear quote-settled gross cross margin.
Inverse, quanto, venue-specific portfolio margin, and L2 fill models require a
separate declared contract before being represented as native-equivalent.

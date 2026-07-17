# `%_equity` Native vs Nautilus Smoke

Status: **pass**
Rows: `300`
Symbol: `ETHUSDT-PERP.BINANCE`

## aligned_fee_no_funding_no_slippage

- Native final equity: `20219.189036`
- Nautilus final equity: `20219.237180`
- Final equity diff: `0.048145`
- Native trades: `7`
- Nautilus trades: `7`
- Signal transitions: `6`
- Nautilus orders/fills: `6` / `6`
- Checks: `{'sizing_mode_is_pct_equity': True, 'orders_not_more_than_signal_transitions': True, 'fills_not_more_than_orders': True, 'fee_convention_matches_native': True, 'custom_fee_rate_applied_to_nautilus': False, 'funding_matches_native': True, 'slippage_matches_native': True, 'custom_slippage_applied_to_nautilus': False, 'has_lot_size_constraints': True}`
- Note: Native one-way fee approximates ETH taker fee; custom Nautilus fee_rate is not applied.

## user_like_mismatch

- Native final equity: `20209.303087`
- Nautilus final equity: `20219.237180`
- Final equity diff: `9.934093`
- Native trades: `7`
- Nautilus trades: `7`
- Signal transitions: `6`
- Nautilus orders/fills: `6` / `6`
- Checks: `{'sizing_mode_is_pct_equity': True, 'orders_not_more_than_signal_transitions': True, 'fills_not_more_than_orders': True, 'fee_convention_matches_native': False, 'custom_fee_rate_applied_to_nautilus': False, 'funding_matches_native': False, 'slippage_matches_native': False, 'custom_slippage_applied_to_nautilus': False, 'has_lot_size_constraints': True}`
- Note: Matches the observed notebook-style mismatch: fee convention, funding, and slippage differ.

## Conclusion

When fee/funding/slippage semantics are aligned as closely as the current adapters allow, the synthetic final-equity gap is only `0.048145` USD and order/fill counts match. The user-like setup intentionally differs: legacy `fee` is round-trip, Nautilus `fee_rate` is metadata today, native funding/slippage are applied while Nautilus signal validation does not apply custom funding/slippage. That scenario shows a larger synthetic gap of `9.934093` USD. Large real-alpha gaps should be audited with the diagnostic helper first; if transition counts match, the next production task is implementing custom fee/slippage/funding in the Nautilus signal adapter.

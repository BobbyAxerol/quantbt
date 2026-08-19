# Package Execution Contract

Package execution coordinates related legs under an explicit policy:

| Policy | Meaning |
|---|---|
| `all_or_none` | Reject the package if its declared acceptance requirement fails |
| `best_effort` | Allow independently accepted legs |
| `sequential` | Evaluate legs in declared order |
| `hedge_after_primary` | Size/submit a hedge only after the primary outcome |

This is deterministic simulated package semantics. It is not a claim of
exchange-native atomic matching, cross-venue atomicity, or live order routing.
For an audit, retain the package plan, order events, accepted/rejected legs, and
the account trace with the result.

Arbitrage, basket, and options workflows may compile package plans, but each
strategy remains responsible for its market-data quality and any venue-specific
contract details.

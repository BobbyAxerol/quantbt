# Native Portfolio Real-Parity Audit

Status: **pass**
Data source: `deterministic_mock_real`
Shape: `2000` bars x `4` symbols
Symbols: `BTC, ETH, SOL, BNB`

## Summary

- Legacy-compatible parity cases: `16`
- Legacy parity passed: `True`
- Native-only domain cases: `3`
- Native-only contract passed: `True`
- Unsupported sizing rejected: `True`
- Max abs equity diff: `0`
- Max abs position diff: `0`
- Max abs target units diff: `0`
- Max abs accepted notional diff: `0`

## Supported Surface

- Modes: `longshort, market_neutral, directional, equal_weight`
- Sizing: `fixed_notional, notional, signal, signal_notional, target_notional, target_units, unit`
- Explicitly rejected: `%_equity, pct_equity, target_weight, gross_exposure, net_exposure, dca_ladder`

## Legacy-Compatible Parity

| mode | sizing | legacy equity | native equity | max equity diff | max position diff | pass |
|---|---:|---:|---:|---:|---:|---:|
| longshort | signal_notional | 246117.317833 | 246117.317833 | 0 | 0 | True |
| longshort | signal | 246117.317833 | 246117.317833 | 0 | 0 | True |
| longshort | notional | 246079.118378 | 246079.118378 | 0 | 0 | True |
| longshort | unit | 246978.085561 | 246978.085561 | 0 | 0 | True |
| market_neutral | signal_notional | 246206.513038 | 246206.513038 | 0 | 0 | True |
| market_neutral | signal | 246206.513038 | 246206.513038 | 0 | 0 | True |
| market_neutral | notional | 246211.696643 | 246211.696643 | 0 | 0 | True |
| market_neutral | unit | 247369.134842 | 247369.134842 | 0 | 0 | True |
| directional | signal_notional | 254281.412722 | 254281.412722 | 0 | 0 | True |
| directional | signal | 254281.412722 | 254281.412722 | 0 | 0 | True |
| directional | notional | 254338.921449 | 254338.921449 | 0 | 0 | True |
| directional | unit | 253223.074157 | 253223.074157 | 0 | 0 | True |
| equal_weight | signal_notional | 245494.846037 | 245494.846037 | 0 | 0 | True |
| equal_weight | signal | 245494.846037 | 245494.846037 | 0 | 0 | True |
| equal_weight | notional | 245487.521893 | 245487.521893 | 0 | 0 | True |
| equal_weight | unit | 246640.978554 | 246640.978554 | 0 | 0 | True |

## Native-Only Contract Checks

| mode | sizing | final equity | max gross leverage | fee total | turnover total | pass |
|---|---:|---:|---:|---:|---:|---:|
| longshort | target_units | 249189.008288 | 0.317687 | 5774.331160 | 27321505.467896 | True |
| longshort | target_notional | 246079.118378 | 0.266752 | 5898.121478 | 28053245.268579 | True |
| longshort | fixed_notional | 246079.118378 | 0.266752 | 5898.121478 | 28053245.268579 | True |

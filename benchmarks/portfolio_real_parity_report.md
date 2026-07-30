# Native Portfolio Real-Parity Audit

Status: **pass**
Data source: `deterministic_mock_real`
Shape: `2000` bars x `4` symbols
Symbols: `BTC, ETH, SOL, BNB`

## Summary

- Legacy-compatible parity cases: `16`
- Legacy parity passed: `True`
- Native-only domain cases: `9`
- Native-only contract passed: `True`
- Unsupported sizing rejected: `True`
- Max abs equity diff: `5.82076609135e-11`
- Max abs position diff: `8.881784197e-16`
- Max abs target units diff: `8.881784197e-16`
- Max abs accepted notional diff: `1.09139364213e-11`

## Supported Surface

- Modes: `longshort, market_neutral, directional, equal_weight, risk_parity, beta_neutral`
- Sizing: `%_equity, fixed_notional, gross_exposure, net_exposure, notional, signal, signal_notional, target_notional, target_units, target_weight, unit`
- Explicitly rejected: `dca_ladder`

## Legacy-Compatible Parity

| mode | sizing | legacy equity | native equity | max equity diff | max position diff | pass |
|---|---:|---:|---:|---:|---:|---:|
| longshort | signal_notional | 240309.705645 | 240309.705645 | 0 | 0 | True |
| longshort | signal | 240309.705645 | 240309.705645 | 0 | 0 | True |
| longshort | notional | 240180.996901 | 240180.996901 | 5.82e-11 | 8.88e-16 | True |
| longshort | unit | 242140.980969 | 242140.980969 | 0 | 0 | True |
| market_neutral | signal_notional | 240381.245551 | 240381.245551 | 0 | 0 | True |
| market_neutral | signal | 240381.245551 | 240381.245551 | 0 | 0 | True |
| market_neutral | notional | 240313.579798 | 240313.579798 | 2.91e-11 | 8.88e-16 | True |
| market_neutral | unit | 242517.364307 | 242517.364307 | 0 | 0 | True |
| directional | signal_notional | 252290.342066 | 252290.342066 | 0 | 0 | True |
| directional | signal | 252290.342066 | 252290.342066 | 0 | 0 | True |
| directional | notional | 252316.731961 | 252316.731961 | 2.91e-11 | 8.88e-16 | True |
| directional | unit | 251658.368992 | 251658.368992 | 0 | 0 | True |
| equal_weight | signal_notional | 239658.452298 | 239658.452298 | 0 | 0 | True |
| equal_weight | signal | 239658.452298 | 239658.452298 | 0 | 0 | True |
| equal_weight | notional | 239589.587314 | 239589.587314 | 0 | 0 | True |
| equal_weight | unit | 241779.679400 | 241779.679400 | 0 | 0 | True |

## Native-Only Contract Checks

| mode | sizing | final equity | max gross leverage | fee total | turnover total | pass |
|---|---:|---:|---:|---:|---:|---:|
| longshort | target_units | 243414.677128 | 0.319084 | 11548.662320 | 28871655.800690 | True |
| longshort | target_notional | 240180.996901 | 0.273274 | 11796.242955 | 29490607.388077 | True |
| longshort | fixed_notional | 240180.996901 | 0.273274 | 11796.242955 | 29490607.388077 | True |
| longshort | %_equity | 177896.705250 | 2.379553 | 94175.050451 | 235437626.126740 | True |
| longshort | target_weight | 124232.212873 | 4.768284 | 166411.765000 | 416029412.501195 | True |
| longshort | gross_exposure | 217085.068890 | 1.000805 | 42620.428373 | 106551070.933575 | True |
| longshort | net_exposure | 123176.825452 | 1.000400 | 32710.583554 | 81776458.885242 | True |
| risk_parity | gross_exposure | 214412.011027 | 1.000805 | 42514.436663 | 106286091.656927 | True |
| beta_neutral | gross_exposure | 214788.803559 | 1.000805 | 42565.266333 | 106413165.832583 | True |

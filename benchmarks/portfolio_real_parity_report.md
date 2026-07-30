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
| longshort | signal_notional | 246117.317833 | 246117.317833 | 0 | 0 | True |
| longshort | signal | 246117.317833 | 246117.317833 | 0 | 0 | True |
| longshort | notional | 246079.118378 | 246079.118378 | 5.82e-11 | 8.88e-16 | True |
| longshort | unit | 246978.085561 | 246978.085561 | 0 | 0 | True |
| market_neutral | signal_notional | 246206.513038 | 246206.513038 | 0 | 0 | True |
| market_neutral | signal | 246206.513038 | 246206.513038 | 0 | 0 | True |
| market_neutral | notional | 246211.696643 | 246211.696643 | 0 | 8.88e-16 | True |
| market_neutral | unit | 247369.134842 | 247369.134842 | 0 | 0 | True |
| directional | signal_notional | 254281.412722 | 254281.412722 | 0 | 0 | True |
| directional | signal | 254281.412722 | 254281.412722 | 0 | 0 | True |
| directional | notional | 254338.921449 | 254338.921449 | 0 | 8.88e-16 | True |
| directional | unit | 253223.074157 | 253223.074157 | 0 | 0 | True |
| equal_weight | signal_notional | 245494.846037 | 245494.846037 | 0 | 0 | True |
| equal_weight | signal | 245494.846037 | 245494.846037 | 0 | 0 | True |
| equal_weight | notional | 245487.521893 | 245487.521893 | 0 | 0 | True |
| equal_weight | unit | 246640.978554 | 246640.978554 | 0 | 0 | True |

## Native-Only Contract Checks

| mode | sizing | final equity | max gross leverage | fee total | turnover total | pass |
|---|---:|---:|---:|---:|---:|---:|
| longshort | target_units | 249189.008288 | 0.317687 | 5774.331160 | 28871655.800690 | True |
| longshort | target_notional | 246079.118378 | 0.266752 | 5898.121478 | 29490607.388077 | True |
| longshort | fixed_notional | 246079.118378 | 0.266752 | 5898.121478 | 29490607.388077 | True |
| longshort | %_equity | 220319.733935 | 2.377274 | 52213.968934 | 261069844.671925 | True |
| longshort | target_weight | 190919.099065 | 4.759124 | 101695.474060 | 508477370.301819 | True |
| longshort | gross_exposure | 237508.951040 | 1.000403 | 22274.562174 | 111372810.869168 | True |
| longshort | net_exposure | 134066.981169 | 1.000200 | 17003.080363 | 85015401.815251 | True |
| risk_parity | gross_exposure | 234694.222802 | 1.000402 | 22221.381095 | 111106905.476062 | True |
| beta_neutral | gross_exposure | 234996.591395 | 1.000402 | 22243.220140 | 111216100.700714 | True |

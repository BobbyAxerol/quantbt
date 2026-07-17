# Phase 12B Benchmark And Nautilus Portfolio Certification

Status: **pass**

## Benchmark Follow-Up

- Bars: `2000`
- Symbols: `6`
- Repeats: `3`
- Full facade seconds: `0.131040`
- Array preparation seconds: `0.013697`
- Pure Numba kernel seconds: `0.000275`
- Report construction residual seconds: `0.117067`
- Pure kernel share: `0.21%`

## Nautilus Portfolio

- Status: `pass`
- Validation status: `pass`
- Equity tolerance profile: `1.0`
- Position tolerance profile: `0.005`
- Final equity diff: `0.00784839857078623`
- Max position diff: `0.004`

## All-Or-None Basket

- Status: `pass`
- Input orders: `2`
- Accepted orders: `0`
- Rejected orders: `2`
- Depth model: `ohlcv_volume_cap`

## Cython/C++ Decision

Cython/C++ is not justified yet; optimize cached array preparation and report construction first.

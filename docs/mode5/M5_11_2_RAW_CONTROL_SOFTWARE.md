# M5-11.2 Raw Whole-Account Control Checkpoint

**SOFTWARE PASS; FORMAL ALPHA STUDIES NOT RUN.**
Authority: [actual-study plan](../../upgrade/implement.md#mode5-m5-11-2), guide
[metric units](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#51-metriccontract-trước-công-thức-tối-ưu)
and [three comparison levels](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử).

## Contract And Implementation

`tools/mode5_research/raw_control.py` is a control ledger around the existing
sampler bridge and ordered ask/tell runner, not another optimizer or engine.
The provider must separately qualify actual typed continuous observations and
their exact source/role/contract/request. A source hash or control seal alone
does not qualify financial execution.

The score reads the original whole-account Sharpe without rescoring, annual
averaging, utility substitution or selection from the challenger's observations.
Finite whole Sharpe is the raw control's eligibility; common annual eligibility
is recorded separately, not silently imposed or relaxed. Undefined scores,
duplicates, failed calls and actual/effective trial identities remain visible.
Selected control output is not deployment authorization. Delivered immutable
accounts remain available after failures; metadata uses shared portable records.

## Actual Tests

`continuous-raw-control15` passes **10 tests in 8.19 s**, controller 9.650 s.
Synthetic original pct-equity dispatch checks original score identity, role/
request drift, immutability, effective duplicates, undefined retention, failures,
budget/seed guards and the independent control ledger. One query executes one
original account; no actual alpha calibration or 256-trial study ran here.

The earlier `continuous-raw-control14` had four metadata serialization failures
and six passing tests. It is retained. The correction uses the existing shared
wire normalizer; no metric, objective or financial formula changed.

| Private Receipt | SHA256 |
| --- | --- |
| `continuous-raw-control15/result.json` | `827962ecad32883ee31f46e29fb478affddd012534f49bc99b471e63733c0e1a` |
| `continuous-raw-control15/registration.json` | `2dd536f014d12b30f2d596d0d86f02cf62e8ea6c3c3d031cdd06b222d5a80235` |
| `continuous-raw-control15/tests.log` | `b21a099e8f65810b62c50092a52d104a0a51085b50a697138b70dc58623f4769` |
| `continuous-raw-control15/cleanup.json` | `f28d650281928913247f0995f06dfeb6eead0864857d00e0f758c31f9681ec74` |

## Resources, Validity And Next Gate

The registered single-thread software lane reused current tooling, created no
native build/environment/scratch, preserved source/receipt hashes and reaped its
worker. No deletion, remote or economic-improvement claim is made. Exact raw
control comparison still requires reviewed full diagnostics, approved sealed
recipes and independently qualified original-alpha providers before the actual
256-query studies. Raw-control software tests cannot close those gates.

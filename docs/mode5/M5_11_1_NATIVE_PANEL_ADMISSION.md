# M5-11.1 Native Panel Admission Checkpoint

**SOURCE ADMISSION PASS; FULL DIAGNOSTICS IN PROGRESS.**
Authority: [ordered local plan](../../upgrade/implement.md#mode5-m5-11-ordered-execution-20261012)
and guide [financial boundary](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#24-financial-boundary-và-route-qualification).

## Scope And Identity

Original 128-point designs, private alpha sources, economics, 2020 preload and
continuous 2021-2023 accounts remain unchanged. This is reviewed retrospective
development, not historically available or independent OOS. Current cold request
copies remain distinct from original witnesses; no ACCESS/snapshot is invented.

`early_admission.py` reads original early owner and qualified empty-access formats
with caller-approved inventories. `panel_admission.py` admits them alongside
original/recovery readers. Status, roles, oracle coverage and limitations survive
reduction/serialization. Restricted owner deserialization checks globals, pins
and trailing bytes; arbitrary pickle ingestion is not supported.

## Actual Checks And Results

`native-panel-cold02` admits all 384 accounts and 1,536 whole/annual rows, including
13 retained older cells / 52 views. Its 21 focused tests cover actual early
HMA/HASH controls and empty VWAP evidence. Additional
`native-admission-regression16`: **47 tests / 59 subtests PASS**, 108.39 s pytest,
109.644 s controller. Independent `native-main-review03` verifies 1,175 pins
(56,118,482 bytes), original candidate/request rosters and unchanged hashes in
1.358 s. Neither cold check executes finance or repeats math reductions.

| Alpha | Accounts | Annual Views | Profitable | Losing | No Trade |
| --- | ---: | ---: | ---: | ---: | ---: |
| HMA | 128 | 384 | 11 | 114 | 3 |
| HASH | 128 | 384 | 31 | 97 | 0 |
| VWAP | 128 | 384 | 17 | 36 | 75 |

Each has 125 recovery accounts, two original-reader accounts and one explicitly
admitted older account. Nine original/older rows retain limited source/terminal/
oracle coverage. Annual/full views are dependent, not separate experiments.
Source admission cannot supply missing historical witnesses or fresh per-candidate
Python oracles. Externally captured approval is mandatory; a hash alone is not
authorization. Losing/no-trade rows are not removed to create positive utility.

## Resources, Cleanup And Evidence

Actual cold reader: 17.25 min, peak 539.59 MiB, retained 53.68 MiB, free 20.08 GiB.
Workers reaped; only registered empty scratch removed. Focused regression adds
no environment/build/scratch/deletion. Sources, private data, failures and exact
artifacts remain. No large disk recovery or remote action is claimed.

| Private Receipt | SHA256 |
| --- | --- |
| `native-panel-cold02/consumer-proof.json` | `867da2a03e6c7e5b2bb67e3e97bdd215ca7ae582175c4c2fb2b784bdb46479bf` |
| `native-panel-cold02/consumer-parents.json` | `4802ba5893408e73293aaece32431253ac56aa938fb071172b2284fea746679b` |
| `native-main-review03/result.json` | `186088195126426ca4ca954c1026c19584479cb6adc0c299b1ffe92c81257414` |
| `native-admission-regression16/registration.json` | `391dcddc3321cb307233655b28ee8dff053a61e52c19d2823b063f88b8cb72b9` |
| `native-admission-regression16/tests.log` | `6c7420737a588f0e4569e2162c771aed73336d6bcd64f2fd4fd02280fbc3c971` |
| `native-admission-regression16/cleanup.json` | `354e53e8bd1dccbb2c0cffe8b1b7c5704f10036e1ded4eb075cc50aa6b4f9659` |

## Next Gate

All five discovery panels now contain 640 executed accounts. Registered probes,
stress cells, six matrices and dossiers remain before search. These descriptive
counts prove neither selector benefit nor absence of alpha edge. Forward and
deployment remain untested here; no phase exit is inferred from admission alone.

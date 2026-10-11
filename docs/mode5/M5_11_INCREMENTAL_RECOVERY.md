# M5-11 Incremental Research Runner Recovery

Current status: **RUNNER_AND_CONTROL_PARITY_PASS / CLOSED_PARTIAL_PANEL**.
The 45-minute execution tranche is closed, with every owned worker reaped.
Research panels and later scientific studies are not declared complete.

Authority: [registered performance-only scope](../../upgrade/implement.md#mode5-m5-11-incremental-recovery)
and guide [resource and retention procedure](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#73-resource-plan-và-tốc-độ-không-làm-hỏng-methodology).
This is an offline research harness improvement, not a public endpoint or Rust
kernel benchmark. Alpha sources, financial engine, parameter designs, sampling,
selection rules and economic thresholds are unchanged.

## Cause And Correction

The old certification loop rebuilt strategy decisions over the complete history
after each feedback update. Repeated compilation, full reports, source hashing
and feedback projection compounded that replay cost. Thousands of returned
account passes were not thousands of configurations, nor independent economics.

The replacement commits strategy decisions incrementally. Only the current bar
is rolled back when newly staged protective orders change its actual feedback.
The existing Rust engine still executes every financial tape from fresh account
state. Immutable numeric command rows are cached through the original quantity
and command compilers; IDs are remapped by their exact string identities.
Projection is lazy, and dense public reports are built at candidate completion.
Prepared market is shared inside one candidate; mutable state is never shared
between independent candidates. Full source and market hashing is performed at
candidate boundaries under the explicitly new `boundary_full_hash_v1` policy.

## Closed Controls

All controls score 26,280 hourly bars over 2021-2023, with 2020 preload.
The matched complete old controls come from
[native04](M5_11_1_NATIVE04_CLOSED_CHECKPOINTS.md).

| Control | Retained Old Wall | Recovery02 Wall | Runner Ratio | Recovery02 Peak RSS | Fills |
| --- | ---: | ---: | ---: | ---: | ---: |
| HMA1 | 20,191.936 s | 147.354 s | 137.03x | 653.887 MiB | 1,871 |
| HASH1 | No matched current-source old wall | 70.684 s | Not asserted | 604.566 MiB | 1,138 |
| VWAP2 | 1,253.506 s | 25.772 s | 48.64x | 590.461 MiB | 120 |

These are logical-work-matched worker observations, not randomized performance
replications: original source-validation cadence and concurrent host load differ.
They do not establish a public QuantBT acceleration ratio or a paired RSS gain.
Matched HMA1/VWAP2 economics remain unchanged; fixed-fill residuals are zero.

Recovery03 also closes previously missing HMA2 and HASH2 in **139.324 s** and
**195.290 s**, with **2,310** and **3,214** fills. Earlier censored HASH2 runs do
not provide a completed old-runtime denominator. Recovery04 HASH3 completes in
**30.644 s**, with 450 fills. VWAP3 completes in **19.772 s**, without commands
or fills: equity remains flat and Sharpe/PSR remain explicitly undefined. The
earlier empty-Python-event-schema checker failure stays retained; the corrected
empty-tape contract still checks all account paths and the clock.

## Correctness And Retention

Sixteen focused tests cover current-bar retry, immutable feature ownership,
quantity constraints, stable command ordering, parent/OCO, cancel/amend, expiry,
rollback, no-trade, full terminal comparison and strict absolute tolerance.
Every completed recovery candidate checks:

- Exact full command/decision equality against the unchanged original compiler.
- Unchanged committed equity, position, costs, margins and lifecycle prefixes,
  including fill reason, ambiguity and optional liquidity classification.
- Full typed-to-normal native account, fills, lifecycle, terminal slots,
  cancellation diagnostics and liquidation parity, using existing tolerances.
- Independently reconciled fixed-fill equity; this is accounting, not a second
  independent matching engine.
- Boundary source/data identity, actual lifecycle feedback coverage and resource
  limits before the PASS receipt is written.

Control cells additionally run the original Python financial owner and repeat
the normal native execution. Bulk receipts explicitly record zero Python-oracle
calls; that coverage is not misrepresented as per-candidate Python parity.
Daily paths and dated fills/campaigns are retained for every bulk row. Dense
owner pickles are control-only, as permitted by guide 7.3(7). Later source
revisions cannot silently requalify earlier receipts: current lanes retain source
snapshots alongside original pins. Earlier controls remain historical evidence.

## Operational Boundary

The missing-only tranche preserves the original 128 configurations per native
alpha. It has at most four isolated one-thread workers, a 900-second candidate
cap and a 45-minute tranche cap. Outcomes do not select replacement candidates;
failures are not economic losses or successful observations. Complete rows are
checkpointed individually. No queue may remain active after the turn.

No wheel, virtualenv or build is created. Data, artifacts, private alpha code,
failures and results remain ignored/private. Cleanup receipts record no
disposable scratch deletion; retained evidence is not "garbage". CI, push,
release and publication remain off. Completing financial rows alone does not
certify the six diagnostic matrices, held probes, actual sampler studies or
prefix-forward economics required by M5-11.2/11.3.

## Cold Evidence Reuse

The explicit `load_recovery_cell` adapter reads caller-sealed recovery receipts,
approved source identities from passed controls, retained source snapshots and
the original data/design/account contract. It imports no private alpha, loads
no owner pickle and runs no financial engine. Dated fills independently
reconstruct account marks and campaigns; existing official reducers verify
hourly/daily calendar and metric identity. Nineteen cold-reader tests PASS.

A sealed snapshot of **119 completed bulk rows** passes cold ingestion and the
unchanged annual reducers, producing **476 dependent views** in **114.476 s**
with **zero additional financial execution calls**. This retains exact recovery
schema and zero fresh Python-oracle coverage for bulk. It is not a new economic
replication, full diagnostic battery, selector promotion or independent OOS.
The scheduled account-bar bill is not native processed-bar telemetry.

Legacy selector/checkpoint consumers still require explicit status/role
admission before using these recovery rows. No legacy PASS file is forged;
current financial rows remain usable through the verified typed account views.

## Final Tranche Receipt

The missing-only tranche returned **155 completed candidates in 2,702.538 s**
(45-minute work budget plus shutdown). All score the original 2021-2023 hourly
account, with 2020 preload and the same 128-point effective design per alpha.

| Alpha | Newly Completed In Tranche02 | Total Reusable / Target | Median Worker Wall | Worker Wall Range | Maximum Worker Peak RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| HMA | 52 | 56 / 128 | 76.888 s | 38.867-182.090 s | 461.996 MiB |
| HASH | 52 | 56 / 128 | 34.777 s | 17.337-770.580 s | 508.516 MiB |
| VWAP | 51 | 56 / 128 | 14.075 s | 11.469-126.561 s | 443.316 MiB |

Totals deduplicate completed controls and prior native candidates. Thirteen
native candidates were already reusable before tranche02, including VWAP4 from
tranche01. There are now **168 / 384** completed native candidates. RSI and SC
remain **128 / 128** each and were not rerun. The missing-only inventory retains
**216** native configurations: 212 unstarted and four interrupted at the tranche
boundary. Their retained faults are `InterruptedError: owned worker stop`, not
financial parity failures or substituted economic observations.

All 155 completed bulk rows passed full original compiler/decision and
typed-to-normal lifecycle/terminal/accounting checks. Independent fixed-fill
accounting residual is **zero** for every row. Python financial-oracle runs are
explicitly control-only, not fresh oracle coverage for these 155 bulk rows.
Thirty of the 51 new VWAP rows have no fills; retain flat equity and undefined
zero-variance metrics rather than turn them into successful search outcomes.

The first tranche controller failed because its checkpoint directory was not
created. That failure and stopped workers remain retained. The corrected queue
used a new append-only tranche and reused its completed VWAP4, without changing
any financial request. No old failed or censored receipt was overwritten.

After queue closure, the current cold reader verified **all 155 bulk rows** and
produced **620 dependent annual/full-period views in 109.893 s**, with **zero**
additional financial executions. The earlier 119-row proof above is historical.
Closed HMA1/VWAP2 paths were also compared against retained native04: equity,
positions, fees, funding, margin, turnover, daily returns and timestamps are
**exactly equal**, not merely within a relative tolerance. The 16 runtime and
19 cold-reader tests remain PASS; no already-passed financial run was repeated
for this closeout.

Tranche02 retains 496.847 MiB of evidence, below its 2 GiB budget. No new build,
wheel, environment or disposable scratch was created. Cleanup verified **790**
retained pins, the exact native hash and the reused environment. No deletion
was warranted; free space after closeout is **20.96 GiB**, with 221,184 bytes
consumed during the cold closeout rather than a fictitious reclamation claim.

Private closeout result/cleanup SHA256:
`b579aac17690f76069bc91ecb08ea26041cfe153ef5448ce52f9b8af73621ab8` /
`1c9fa6f4faf7eaee0c90036b10fd6a56a38d98ce442a56feed6c20dc8380a879`.
The sealed missing-only inventory is the next-tranche authority; do not restart
the old queue at index 4 and repeat these completed configurations.

## Remaining Scientific Work

This closes the performance-only rerun, not M5-11 scientific qualification.
Complete the remaining 72 configurations per native alpha, explicitly admit
the recovery schema in diagnostic/selector consumers, and rebuild their full
matrices/probes from verified accounts before scientific promotion. M5-11.2
actual sampler/selector studies and M5-11.3 prefix-forward tests remain NOT_RUN;
M5-12 remains NOT_STARTED. No new edge, sampler winner or independent-OOS claim
is inferred from faster candidate evaluation. No queue, push, CI or publication
remains active.

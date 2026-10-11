# M5-11 Incremental Research Runner Recovery

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

# M5-11.6.1 Fast Intrabar Research Variant Design

## Status And Authority

**APPROVED / IMPLEMENTED / TIMING_ADMITTED / STUDY_PENDING**. Following the
recorded design-only closeout, the owner explicitly requests implementing and
continuing M5-11.6.1 now. Variant adapter/evaluator/policy implementation is
authorized; pilots and studies follow their already registered admission gates.
The [implementation/admission receipt](M5_11_6_1_IMPLEMENTATION_REPORT.md)
records executed tests and fixed controls. The source-sealed study follows
that admission; this document does not convert the
[original HMA non-admission](M5_11_6_1_ADMISSION_REPORT.md) into a passing run.

Scope: [Q01--Q08 in the unified plan](../../upgrade/implement.md#mode5-m5-11-6-1).
Authorities remain the Mode 5 guide's
[alpha contracts](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#chapter-3),
[effective geometry](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#45-trục-2--parameter-geometry-và-landscape),
[experiment separation](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử),
QMS [information rights](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[cost classification](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10)
and the [strategy/engine boundary](../adr/ADR-RP-002-strategy-engine-boundary.md).
Private alpha source, ranges, exact predicates and input snapshots stay private.

## Why A Variant

Eight fixed HMA controls cost 3.419--8.641 seconds per 365D IS, including
preparation/execution/reduction. They already use one Rust session with no
full-tape replay. The residual strategy/feedback work cannot be removed simply
by renaming the endpoint. Measured variant controls are recorded separately;
they are not original-alpha performance-only speedup claims.

The proposal retains the original indicator calculations, but replaces selected
fill-dependent strategy behavior with a documented static-intent research
contract. **This is a methodology/execution ablation, not a parity-preserving
performance patch.** Exact accounting and chronology remain mandatory. A
variant result may answer a Mode 4 research question under that variant; it
cannot establish improved performance on an original alpha that behaves
differently.

## Proposed Route Map

Each cell gets a new private strategy/space identity, with an explicit link to
its original source. The original alpha modules and original monthly studies
are immutable. These names describe proposed research identities, not public APIs.

| Cell / Proposed Identity | Preserve | Explicit Change Or Qualification Boundary |
|---|---|---|
| SC / `sc_intrabar_signals_research_v1` | Original causal indicators, warmup and long-flat opportunity rules; fixed-notional entries and technical exits | Native flat-only admission owns position gating. Freeze exit-over-entry priority for conflicting simultaneous signals. This is exact only where original priority is proved equivalent; conflicts are tested and reported, not silently labelled parity. No shorts or protective stops are invented. |
| HMA / `hma_intrabar_distance_research_v1` | Original recursive adaptive/minor HMA, length clamps, causal features, entry opportunities and side-specific observable technical-exit predicates | Remove the technical-exit gate depending on actual entry-price profit. Replace absolute staged brackets plus fill-gap handling with positive decision-time price distances anchored by the native engine to its actual fill. Remove strategy feedback/retry/staging, not engine fill/protection checks. |
| HASH / `hash_terminal_bracket_research_v1` | Original causal momentum/features and entry opportunities; original stop percentage and final reward/risk level | Replace the partial TP ladder with a single full-position terminal TP; remove intermediate rungs and fill-flat cooldown. This materially changes exposure/fees/campaign duration. It is not the original ladder, nor proof for its 40%/24%/36% remaining-fraction behavior. |
| VWAP / `vwap_static_bracket_research_v1` | Original daily VWAP/features, closed-HTF availability, readiness and entry opportunities; decision-time ATR risk distance and target multiple | Remove fill-age time-stop and dynamic VWAP amendment branches. Native protection is static after entry. Both removed branches and their dependent inputs are inactive in this variant, not optimizer dimensions. |
| RSI reference / `rsi_next_open_signal_research_v1` | Original causal signal-generation contract and its existing structural logic | Convert close-time signal transitions to next-open fixed-notional intents. Do not add another SL on top of signal-generation exits. This matches the new study economics, not the historical pct-equity/funding/fee recipe. |

For HMA, stop-mode geometry still affects the decision-time distance; it is not
automatically removed from the space. Invalid or nonpositive distances receive
an explicit disposition rather than absolute-value repair. The bridge must
expose the changed gap and profit-gating behavior.

For HASH, the single TP is the original terminal reward/risk level, not a
weighted-average guessed target or a favorable rung chosen from outcomes.
Intermediate-rung and cooldown parameters are recorded as removed/inactive;
unchanged entry/terminal-risk parameters retain their registered feasible
domains. No invented alpha logic or source thresholds are published here.

VWAP's original stop/TP distance may be representable faithfully by the existing
engine when its two removed exit branches are inactive. That limited claim
needs its own parity proof; it does not certify candidates where those branches
were enabled. HMA/HASH remain explicit ablations even if aggregate metrics look
close on a bounded bridge.

## Shared Execution Contract

1. Use existing `IntrabarIntentTape`, `IntrabarSessionTape` and
   `SessionExecutionPolicy`, with the public intrabar endpoint/prepared route.
   No new account engine, Rust bridge or imitation PnL loop is introduced.
2. Prepare immutable original features once per exact data/parameter/version
   key. Feature recursion uses the permitted prefix, including preload from
   2020; no truncation to just the scored IS is assumed equivalent.
3. Build an exogenous opportunity/exit tape from closed observations. Place
   intents at the signal bar; `ExecutionContract.intrabar_bracket()` owns the
   one-bar next-open activation. Do not pre-shift them or read the next open to
   choose entries, size or protection. The engine may use that open for fills.
4. Use `intrabar_sizing_mode="fixed_notional"`, entry budget 2,000, not 2,000
   contracts: `alloc_per_trade=2000` and `entry_size=1.0` (a dimensionless budget
   weight). Multiplying both by 2,000 would request 4,000,000 notional, not the
   registered exposure; reject this wiring before finance. Retain exact
   instrument constraints, quantization, fees, margin,
   liquidation, final-flat and same-bar policy from the sealed execution request.
5. Use existing flat-only position gating; ignore opportunities while invested.
   A new close-time opportunity may be taken after a protection exit, according
   to the frozen native policy. Reentry/priority differences from each original
   strategy belong in the variant manifest and bridge, not hidden adapter state.
6. HMA/VWAP use positive `PRICE_DISTANCE` levels known at decision time; HASH
   uses `PERCENT_DISTANCE` for its stop/terminal TP. Neither requires Python
   fill callbacks. Do not calculate absolute prices from a future fill in the
   tape compiler. SC/RSI add no arbitrary bracket levels.
7. All bars in one diagnostic account run through the same engine state. Derive
   daily returns and four IS attribution segments afterward; do not reset the
   account between attribution segments. Keep requested audit for controls and
   final proof, not verbose audit materialization in every trial.
8. A static tape should cross the boundary in one prepared execution request
   per account, with native engine-owned per-bar execution. Telemetry must show
   actual calls/bytes; this is a design target, not an achieved benchmark.

The selected existing intrabar contract flattens at the final **close**. It does
not inherit an event-runner option that reserves the final bar or flattens at
its open: a penultimate-close entry can still activate at the final open. This
terminal-phase difference is part of the named variant, tested separately and
reported in original-route bridges; retaining final-flat status is not proof
of equal terminal execution. All arms within the new study share this contract.

Current native StrategyIR only provides a small fixed set of strategy forms;
it is not a compiler for arbitrary Python/HMA or fill-age/cooldown state. The
existing intrabar session contract likewise does not supply a general
time-since-fill counter or remaining-fraction ladder. This design does not claim
those missing behaviors have been preserved by converting flags to arrays.

## Geometry, Identity And Diagnostic Reuse

- Produce a private per-key map: retained-active, fixed-structural,
  removed-by-variant, inactive-by-branch, coupled, or ignored-in-original.
  Preserve raw/effective representations and exact feasible constraints.
- Do not optimize removed HMA profit-gate, HASH rung/cooldown, or VWAP removed
  exit-branch knobs. Recomputing a variant's effective geometry is necessary;
  carrying their old coordinates would fabricate dimensions/duplicates.
- Both sampler arms for one variant use the same versioned effective schema
  and objective. Removing an ineffective dimension is not advertised as an
  unchanged original-space experiment. No categorical integer recoding is
  introduced to force CMA-ES compatibility.
- Existing pre-2022 pools may supply source-valid geometry records only where
  the variant map is exact. Their 730D scores/account paths are not new 365D
  variant observations. Do not reuse old forward labels or old meta models.
- Complete the declared 128-attempt prefix diagnostic design per variant; bill
  supplements and physical account executions separately. RSI's 48 matching
  records cannot be renamed a complete 128-point panel. Freeze the missing-work
  manifest, designs/seeds and any probes before financial diagnostics.
- Current evidence supports multivariate/group TPE as a compatible hypothesis,
  not a proven winner. Keep legacy TPE as baseline; freeze one challenger from
  the existing registry per alpha before search, using the permitted-prefix
  worksheet. No 4-sampler tournament or hindsight winner lookup is added.
- Include variant, schema, clock, constraints, account, sampler, selector,
  cutoff and metric versions in task/cache/family identities. Each
  sampler/native-anchor family owns its own history and model. Share exact raw
  financial observations only when identities permit; rebase labels separately.

## Work Unchanged From The Approved Quarterly Plan

- ETHUSDT 1h, existing verified snapshot; preload from 2020. Rolling 365D IS;
  19 complete OOS quarters, 2022-Q1--2026-Q3, with no partial October.
- 128 attempted slots per sampler/fold, seed 731/existing fold derivation,
  sequential ask/evaluate/tell, no early stopping or warm-start.
- 19,456 primary slots plus 2,432 RSI reference slots: 21,888. Two sampler pools
  yield the primary eight policy decisions; no eight duplicate optimizers.
- Original IS objective and native selector remain the baseline. Challenger
  selection uses the registered four-segment daily-Sharpe floor/mean on the
  same IS account, not a newly invented floor-search objective.
- Ridge origin-sum lambda 10, at least 12 mature compatible origins, Qhat floor
  -0.10 and original label/availability rules. No history borrowing from the
  original monthly or original-alpha families.
- Preserve separate anchor-first panels and deduplicated query unions. Allow
  up to 36 observer candidates per primary pool and 18 for RSI in forecasting.
- Nineteen quarterly origins still permit only about six actually learned
  decisions under current publication lag. Report cold-start and fit/rank
  separately. No new general meta-economic acceptance claim is implied.

## Implementation Order And Pre-Search Gates

Under the owner's subsequent implementation approval:

1. **V01: Freeze private variant manifests.** Record exact retained/removed
   logic, schema, engine contract, sizing, priority, readiness, terminal policy,
   invalid-intent policy and original-source hashes. Unsupported behavior is
   explicit. Keep all original/admission failure receipts unchanged.
2. **V02: Implement isolated adapters.** Small modules may prepare features and
   compile typed tapes; account execution/reduction remains shared. Reuse
   immutable market and original preparation helpers. No original alpha edit.
3. **V03: Same-contract fixtures.** Rust versus existing Python/Numba reference:
   signals/next-open shift, overlapping signals, flat-only admission, reentry,
   gap-through protection, simultaneous stop/TP, rejection, rounding, fees,
   margin/liquidation and final flatten. Compare raw positions/fills/equity and
   objective components, not merely similar final equity. No relaxed tolerance
   or new prune rule is approved by this design.
4. **V04: Bounded original bridges.** Reuse the eight original HMA controls;
   evaluate variants at exactly those parameters/cutoffs where the map exists.
   For other alphas, preregister original/variant low/high-activity and
   structural controls before finance, at early/late prefixes. Record all
   failures and ordering/activity/IS-metric differences. Reuse original results
   only at exact contract identity. Distortion is not a same-contract bug, but
   blocks transferring claims to the original alpha without explicit review.
5. **V05: Re-admit resources and whole work.** Measure full preparation,
   execution, daily reduction, observer, setup and final-account work, including
   cold/warm costs. Keep the 20-minute fixed-pilot cap and the 90-minute main
   financial-queue cap. Account for independent-study scheduling/contending
   workers; ideal division by four alone is not a sufficient forecast.
6. **V06: Only admitted studies proceed to Q04--Q08.** Produce actual shared-pool
   selector/meta decisions, chronology mutation proofs, matched R/Q and final
   recommendation. If the variant cannot express policy carry across folds,
   report reset-flat fold evidence only; never concatenate diagnostic equities.
   A continuous claim requires supported saved-schedule accounting/replay.

Same-contract parity and original/variant distortion are separate reports.
No requirement is added that the variant should earn more profit. No altered
threshold, extended sampler tournament or implicit new alpha search is used
to make it pass. A rejected timing or financial gate retains a useful terminal
receipt, not a fabricated full-phase PASS.

## Resources And Claim Boundaries

Retain the existing environment/native artifacts and current useful JIT cache.
At most four independent workers, one numeric thread per worker, aggregate
owned RSS <=3 GiB, host available RAM >=512 MiB. Incremental retained records
stay <=512 MiB, disposable scratch <=64 MiB; leave >=5 GiB disk free beyond
the remaining forecast. Recheck before each tranche; clean exact inactive
scratch afterward. No service stop, global cache purge or default new build.

Potential speed comes from removing Python strategy feedback, repeated packing
and transaction crossings, **not** from approximating native accounting. No
speedup factor or completion ETA is promised before V05. New per-cell variant
geometry, diagnostic/observer work and final proof remain real costs.

Expected completion is a clearly scoped quarterly research decision:
`KEEP_CURRENT_MODE4`, `RECOMMEND_VERSIONED_OPT_IN`,
`STANDARDIZE_SHARED_DIAGNOSTICS_ONLY`, or `INCONCLUSIVE_KEEP_DEFAULT`.
Variant results do not rewrite original-alpha economics, and software
correctness does not guarantee improved forward-Q. Scientific conclusions
remain conditional on exposed historical data, one registered seed and the
quarterly support limit. No public default, endpoint, original alpha, M5-11.7,
M5-12, CI, merge or publication changes through this design.

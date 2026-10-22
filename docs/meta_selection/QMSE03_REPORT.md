# QMS-E03 Scalar Sizing And Backend Coverage

## Current Conclusion

Assessment sealed on 2026-10-06. **E03 is not fully certified:** ordinary scalar
software checks and eight installed cells pass, but the real prepared-unit
study fails metric/selection parity. No cell passes the registered economic
improvement gate. Read the [sanitized executed evidence](../../benchmarks/optimization/meta_selection/qms_e03_assessment_evidence.json),
not an assumed completion percentage.

| Gate | Actual disposition |
|---|---|
| Ordinary scalar domain/compatibility regression | 1,193 distinct checks PASS; zero failures/errors/skips |
| Baseline search/RNG/account and historical receipts | Exact; financial/Rust/guide sources unchanged |
| Installed wheel/sdist | Eight scalar cells plus all prior mandatory consumers PASS locally |
| Eight real-data off/active pairs | Finished; same full IS search pools; original-account checks PASS |
| Prepared notional full study | Pool, selected params and account PASS |
| Prepared unit full study | FAIL: post-liquidation metric convention changes objective and selection |
| Registered R/Q economic gate | 0/8 pass; no default or empirical promotion |
| Overall phase exit | BLOCKED_PREPARED_METRIC_PARITY; owner economic review also pending |
| Current-source remote/public qualification | NOT_RUN; no push, merge, tag or publication |

Passing regression counts do not override the failed real prepared gate.
The receipt is explicitly `qms-e03-assessment-evidence-v1`, not a PASS certificate.

## Scope

E03 extends the existing E02 domain adapter, not the financial engine or Ridge
methodology. The approved guide remains authoritative:
[routes](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s3),
[raw mathematics](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[causal labels](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[prepared ownership](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8)
and [scientific scope](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14).
See the [phase plan](../../upgrade/implement.md#qms-e03) and
[scalar execution contract](DOMAIN_ADAPTER_CONTRACT.md#e03-scalar-amendment).

| Target | Financial backend exercised | Interpretation |
|---|---|---|
| `signal_notional` | Native vectorized, native event | Frozen units until signal transition |
| `notional` | Native vectorized, native event | Original constant-quote target rebalance |
| `unit` | Native vectorized, native event | Original window-start unit scaling |
| `pct_equity` | Legacy/Numba | Original equity sizing on transition |
| `dca_ladder` | Legacy/Numba | Original signed structural caps and high/low ladder |

`single_signal` and `%_equity` are canonical aliases when meta is enabled.
Methodology remains **Mode 4 / per_fold_causal / endpoint scoring**. New cells
are `SOFTWARE_VALIDATED_OPT_IN`, not economic promotion or changed defaults.
Native-event support here means signal-to-rebalance orders, not generic Python
callbacks, reactive grid, intrabar intent or package execution.

## Domain And Compatibility

Financial evaluators own accepted units, fees/slippage, margin, funding,
liquidation and account state. Each observation is reduced from its original
execution exactly once, with zero financial replay. Independent fold diagnostic
accounts supply IS/forward raw metrics; one original account processes stitched
OOS targets. Fold equities are not concatenated to manufacture an account.

The versioned scalar contract validates target/backend/timing/sizing. New family
IDs bind the E02 compatibility contract; old qualified family IDs stay exact.
Different ladder policies and event timing cannot share compatible history.
Market preparation remains owned by the existing run context, not a new cache.

Preflight rejects mismatched sizing and legacy overrides that the original
engine would not apply. Legacy `fee` is round-trip compatibility input, so its
canonical one-way fee is `fee / 2`; explicit conflicting one-way overrides
cannot label ignored economics. Prepared-required pct-equity errors retain
`NativePreparedPublicWfoUnsupported`. Ladder needs real high/low and signed
integer caps. Ladder/event rebalance cannot be shifted into a same-close
prepared scorer. Meta omitted/off proxy defaults and endpoint signatures stay.

## Correctness And Packaging

Independent expected-value tests cover fixed/frozen targets, reversals, accepted
trade deltas, fees/slippage, quantity steps/minima, buying power, rejection,
funding and liquidation. Ladder fixtures cover long/short safety fills, TP
priority, same-bar base-entry ordering and carried-position funding.
Off/shadow pools, RNG, params and continuous-account arrays are exact; future
suffix mutations cannot alter earlier decisions. Small same-close prepared
fixtures pass, as does the full prepared-notional study. The full prepared-unit
study exposes a separate post-liquidation metric mismatch described below;
small fixtures cannot certify this case. Financial/numeric Rust sources are
unchanged. Existing endpoint signatures, meta-off defaults and Ridge math stay.

Installed core `1.1.2` / native `0.4.3` wheel and sdist consumers run all eight
cells with compiled meta under `require`. Source inventories, artifact allowlist
and all prior mandatory consumers are checked; native wheel reuse is permitted
only by the unchanged source/artifact hash proof. This local CPython 3.12 Linux
proof is not Ubuntu 22/24 x CPython 3.11-3.13 or public-index certification.
The candidate matrix now includes the installed scalar proof; no push ran.

## Registered Study

Status: all 18 registered workers finished. The final queue exits nonzero because
prepared-unit parity fails, not because a worker was skipped or crashed.

- Gradient/Delta RSI on immutable research-exposed ETHUSDT 1h, 37,968 bars.
- 28 monthly origins, January 2022 through April 2024; rolling 365D IS.
- 128 attempts/fold, seed 731, one frozen `tpe_legacy` recipe, no early stop,
  warm start or outcome-driven retuning. Every arm has its own history/account.
- Original allocation: pct-equity 0.5; other scalar cells quote 10,000, quantity
  step 0.001. Initial capital 20,000, leverage 1, canonical one-way fee 0.00025,
  slippage 0.0001 and baseline constant funding 0.0001. This is not a claim of
  historical venue-exact funding.
- Ladder uses a simple causal mean-reversion signal on actual OHLC, with signed
  level caps. The owner authorized simulation; it is not a private real DCA alpha.
- At least 12 supported matured origins. Interval: 95% moving-block percentile,
  three monthly origins per block, 4,096 registered draws. No candidate/seed is
  counted as an independent market sample; undefined windows remain explicit.

Raw, original-account diagnostic Sharpe defines:

$$
D_n=I_n-F_n,\qquad D_m=I_m-F_m,\qquad R=D_n-D_m,
$$

$$
Q=F_m-F_n,\qquad R=(I_n-I_m)+Q.
$$

Registered gain needs mean supported $R>0$ and the lower interval bound of
forward $Q\geq0$. Lower IS alone is not forward improvement. Native versus
active must have the same full IS search pool. Final continuous-account Sharpe
is reported separately from these fold diagnostics. A threshold pass still
needs owner review; these data are not a new pristine holdout or live proof.

## Actual Decay And Forward Effects

The following are mean **raw diagnostic** Sharpe over supported valid origins,
not final stitched-account metrics. Seven cells have 15 supported valid origins.
Signal-notional/native-event has 14 (27/28 total diagnostic pairs valid);
undefined outcomes are excluded explicitly, not replaced with zero. The interval
rule requires contiguous supported valid origins; all reported intervals satisfy it.

| Target / backend | Native IS | Meta IS | Native FWD | Meta FWD | R | Q | Q 95% interval |
|---|---:|---:|---:|---:|---:|---:|---|
| signal-notional / vectorized | 2.518 | -0.331 | -1.232 | -2.532 | 1.549 | -1.300 | [-3.061, 0.541] |
| notional / vectorized | 2.632 | -0.724 | -0.768 | -0.523 | 3.602 | 0.246 | [-1.354, 1.619] |
| unit / vectorized | 2.412 | -0.568 | -1.717 | -2.371 | 2.325 | -0.654 | [-1.615, 0.753] |
| signal-notional / event | 2.699 | 0.669 | -0.877 | -1.303 | 1.604 | -0.426 | [-2.274, 1.502] |
| notional / event | 2.612 | -0.638 | -0.648 | -1.539 | 2.359 | -0.891 | [-2.518, 1.321] |
| unit / event | 2.535 | -0.390 | -0.815 | -0.957 | 2.783 | -0.142 | [-2.462, 1.569] |
| pct-equity / legacy | 2.518 | 0.387 | -0.567 | 0.434 | 3.132 | 1.001 | [-0.155, 2.516] |
| simulated ladder / legacy | -0.013 | -0.503 | -0.488 | -0.419 | 0.559 | 0.069 | [-0.549, 0.649] |

Every R point mean is positive, but **all Q lower bounds are negative**. Only
notional/vectorized, pct-equity and simulated ladder have positive Q point means.
For pct-equity, R = 3.131554 consists of lower IS contribution 2.130491 and
forward gain Q = 1.001062. Its R/Q values and intervals reproduce the earlier
local-closure evidence; that is reproducibility, not a new independent sample.
Some other cells reduce measured decay while actually worsening forward Sharpe.
No sampler/model/range/seed was reselected after seeing these outcomes.

## Original Continuous Accounts

Each result below executes the actual fold-selected targets in one original
account. Different endpoint timing/sizing contracts are not required to match
each other. Off/active are intentionally different selection policies; their
accounts are checked against their own independently reexecuted selected signals.

| Target / backend | Final equity off / meta | Sharpe off / meta | Max DD % off / meta |
|---|---|---|---|
| signal-notional / vectorized | 19,993.61 / 15,246.97 | 0.103 / -0.478 | 28.31 / 31.08 |
| notional / vectorized | 20,113.82 / 18,998.64 | 0.109 / -0.037 | 21.65 / 20.98 |
| unit / vectorized | 20,000.00 / 20,000.00 | 0.000 / 0.000 | 0.00 / 0.00 |
| signal-notional / event | 22,375.88 / 26,028.10 | 0.376 / 0.762 | 19.58 / 17.72 |
| notional / event | 32,511.50 / 23,030.16 | 1.397 / 0.457 | 12.95 / 26.44 |
| unit / event | 20,000.00 / 20,000.00 | 0.000 / 0.000 | 0.00 / 0.00 |
| pct-equity / legacy | 29,600.73 / 34,812.73 | 0.889 / 1.191 | 19.29 / 14.27 |
| simulated ladder / legacy | 4,973.18 / 4,631.45 | -1.371 / -1.312 | 75.75 / 78.74 |

Both unit accounts have **zero nonzero-position bars**. Original unit sizing
uses the evaluation tape's starting price: the final tape starts in 2020, whereas
the stitched OOS starts in 2022 at much higher prices. With the registered quote
allocation/leverage, margin rejects the resulting targets. Fresh IS/forward
diagnostics use their own window-start reference and can trade. These different
account-boundary policies are disclosed, not reset silently to improve results.
The legacy report's `num_trades=1` in these flat accounts is an activity-trace
convention, not proof of one accepted fill. Equal flat arrays cannot demonstrate
selection parity or economic usefulness of the unit configuration.

## Actual Cost And Retention

| Target / backend | Wall off / meta (s) | Added wall | CPU off / meta (s) | Peak RSS off / meta (MiB) |
|---|---|---:|---|---|
| signal-notional / vectorized | 333.706 / 375.282 | 12.46% | 331.725 / 374.188 | 354.95 / 368.53 |
| notional / vectorized | 518.989 / 565.944 | 9.05% | 518.101 / 564.199 | 352.91 / 367.28 |
| unit / vectorized | 510.022 / 552.067 | 8.24% | 508.734 / 551.395 | 351.38 / 366.58 |
| signal-notional / event | 608.585 / 665.538 | 9.36% | 608.013 / 664.028 | 347.92 / 362.03 |
| notional / event | 1,751.566 / 1,802.499 | 2.91% | 1,748.521 / 1,800.981 | 357.12 / 371.98 |
| unit / event | 580.633 / 628.825 | 8.30% | 580.067 / 627.416 | 348.91 / 362.99 |
| pct-equity / legacy | 372.692 / 430.409 | 15.49% | 372.571 / 429.542 | 344.21 / 358.18 |
| simulated ladder / legacy | 69.946 / 95.173 | 36.07% | 69.265 / 94.930 | 319.05 / 328.04 |

Across the eight pairs: **57,344 attempted, 51,016 completed, 6,328 duplicate
pruned, zero failed** trials; 3,664 separately charged observer evaluations.
Each arm attempts 3,584 trials. Ladder's small discrete search space produces
788 unique/completed proposals and 2,796 duplicate prunes per arm; a nominal
128-attempt budget is not 128 distinct evaluations. The receipt preserves each
cell's exact completed/pruned/unique counts and raw hashes.

Rust meta fit/select costs 1.432-2.400 s per full active study; observers cost
11.039-21.495 s. Total active overhead is larger because these nested spans do
not partition all Python orchestration, history/artifact handling and accounting.
RSS above is execution high-water, measured before cold export/account verification.
The evidence retains later export high-water separately. No RSS plateau or
general speed guarantee is inferred from a single fresh process per arm.

## Prepared Study And Parity Blocker

Two additional full active studies add **7,168 attempts**, not additional
independent market origins. Prepared notional/vectorized matches the ordinary
full candidate pool and exact selected params; equity/returns/positions maximum
absolute difference is **0**. Wall falls **565.944 to 297.551 s** (1.902x,
47.42% reduction); CPU falls 564.199 to 295.390 s. Peak execution RSS rises
367.281 to 372.121 MiB (+4.840 MiB), so this is not a memory improvement.
The original private Python/Numba alpha remains unchanged and Python-owned.

Its telemetry records 3,557 `execute_score` crossings and 3,557 separate metric
witness materializations, 7,086 native rows, 61,848,504 scored bars and 9.914 s
native score time. There are zero score-row Python objects or fallback rows.
The 618,711,792 transient request bytes are **cumulative traffic**, not retained
RSS. `native_boundary_calls` counts score calls only, not total meta/output FFI.
The immutable market has zero native ingress copies and 2,164,176 resident bytes.

**Prepared unit fails.** The first material objective difference is fold 0,
trial 27: ordinary -2.563493930 versus prepared -4.155442602, difference
1.591948671. Later proposals and selected params diverge. The raw 290.550 s
prepared timing is retained, but its comparison to the ordinary 552.067 s is
explicitly invalid as a same-work speed claim. Final account arrays happen to
match because both unit accounts are flat, not because the search is equivalent.

The frozen failing candidate was independently reexecuted without a new search:
Numba/Rust equity and returns match exactly; equity is zero on 5,838 hourly bars.
Legacy daily statistics retain 364 return samples; Rust retains only the 121
samples with a positive previous equity. Raw Sharpe is -2.118500209 versus
-3.710448881. The difference exactly explains the observed objective mismatch.

Root cause: [Rust reducer](../../rust/crates/quantbt-engine/src/metrics_v2.rs)
`observe_sample` returns early for previous equity <= 0, whereas the
[legacy metric](../../src/quantbt/metrics/performance.py)
`_array_returns_for_stats` emits return 0 when the previous equity is 0. This
is a **metric contract mismatch**, not financial-array drift or rounding noise.
It may affect other liquidation-capable prepared workloads, not just unit.
Censoring invalid meta labels does not repair the native Optuna objective/RNG.

Until a separately approved compatibility repair is qualified, use original
endpoint scoring with `native_prepared_wfo="off"` for this contract. Do not
assume current `auto`/`require` detects the mismatch: no new runtime guard has
been implemented. Do not raise tolerance or change the strategy/risk allocation.
The repair proposal [E03-G01](../../upgrade/implement.md#e03-g01) requires explicit
legacy-compatible zero-base semantics, fresh native artifacts and chronological
objective/params/account parity. It is not permission to change scientific math.

## Execution Integrity

Initial registration/package v1 stays archived. One completed native run failed
only during receipt export of a pruned infinite Optuna objective; its account
arrays were retained. A subsequent partial native run was stopped when the
full regression exposed the prepared exception compatibility issue. No active
outcome or economic threshold prompted these fixes. Corrected source/package
v2 has a new immutable registration and the same financial protocol.
Pruned nonfinite objectives are now explicit tokens, not fabricated zero labels.
Failed/aborted runs are not counted as successful origins or concealed retries.

Timing uses one fresh process per arm on a shared VPS, not repeated medians or
isolated performance certification. Public execution wall/CPU/RSS are separate
from cold evidence export and the independent final-account check. Fit/select
and observer spans can overlap other spans; they are not an additive partition.
Prepared study parity does not mean the private Python alpha has become Rust.

## Reproduction

Run the self-contained [scalar example](../../examples/wfo_meta_scalar.py)
without private inputs. Full private study requires the owner's immutable
alpha/data registration; neither source nor raw trial params enter artifacts.

```bash
python -m tools.qms_e03_study register --output data/local/qms-real-review/new-study
python -m tools.qms_e03_queue --output data/local/qms-real-review/new-study
```

The study interpreter must load the qualified installed pair, not repo source.
Queue resumes only matching sealed complete arms and never retries failures
automatically. Keep old receipts and use a fresh lane for a changed candidate.
`tools/qms_e03_report.py` verifies source, actual JUnit, artifacts, baseline
parity, all eight pairs and full prepared studies before sealing a public report.
Default certification still raises on the prepared failure. The explicit
`--assessment-only` option records `prepared_parity_gate=FAIL` and
`phase_exit_gate=BLOCKED_PREPARED_METRIC_PARITY`; it cannot create a PASS certificate.
The current assessment contains no private code, prices, or full trial params.

## Remaining Gates

Prepared post-liquidation compatibility is a real open blocker, not completed
work. Financial/Rust edits remain outside the currently approved E03 source
boundary; scope approval is requested before changing that metric implementation.
Official economic promotion, true real-DCA-alpha evidence, owner acceptance,
current-source remote matrix and public-index release are separate, pending gates.
C01/C05 activation remains unapproved. E04-E08, carry/multi-symbol/public-meta
batch and cross-domain methodology expansion are not implemented by this phase.
No commit here authorizes push, merge, tag, publishing or another phase.

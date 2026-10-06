# WFO Meta Domain Adapter Contract V1

## Authority And Scope

This is the owner-requested E02 route amendment, version `qms-domain-evaluation-v1`.
Read [the unified plan](../../upgrade/implement.md#qms-e02) and the original
[architecture](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s2),
[history/family contract](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s6),
[selection](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s7),
[prepared ownership](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8)
and [measurement](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10).
It extends adapter architecture, not Ridge mathematics or methodology permissions.
The original guide and historical receipts are not rewritten.

## Typed Boundary

`meta_selection/domains/` separates contracts, registry, scalar and reactive
adapters. An adapter delegates execution and reduction to the existing financial
owner. It does not own market arrays, strategy/account state, a second cache,
an engine or a Python/Rust bridge. Scalar signals, position matrices, package
specs, intrabar intent, command tapes and reactive windows have explicit tags;
dispatch never guesses the domain from their similar Python/array shapes.

- `DomainCompatibility`: ordered universe, nominal calendar policy, instruments,
  funding policy, canonical economics/metric IDs, timing, diagnostic/final
  account policies and witness ABI. Actual dates, fold seed and current pool
  are not compatibility-family keys.
- `MarketBinding`: exact run lifetime, source/calendar/instrument/funding
  signatures and the compatibility contract. A changed tape is not a reusable
  evaluation; history from the same economic policy may span different dates.
- `EvaluationBinding`: explicit input kind, actual params, stage, exact aware
  index, signature, information cutoff and decision seal. Current IS cannot
  cross its cutoff; forward work requires a seal before its first economic bar.
- `EvaluationEvidence`: the original result/native witness, unchanged metric
  observation and exact binding. Reducers remain in the existing result and
  prepared/reactive witness adapters, not in the learner or registry.

`evaluate` invokes the supplied financial callable exactly once. `observe`
reduces its original output, never replays it. `finalize` adds cold-path adapter
telemetry only when meta is on. Reset/cancel/clear delegate ownership to existing
runtime owners; clearing the adapter never clears caller-owned history.

## Compatibility And Admission

Existing qualified scalar/W0-W2 and reset-flat W3 scorer/family identities are
preserved byte-for-byte. Their existing economics, metric, timing, instrument,
window, sampler and account contracts remain authoritative. Their legacy IDs
are not general transfer permissions. The new compatibility object is additional
auditable binding, not a retrospective relabeling of archived tasks.

Every future adapter must use `DomainCompatibility.bind_family` (or an explicitly
reviewed migration) to namespace its scorer contract. Ordered universe,
calendar/instrument/funding policy, metric, costs and account/timing differences
then isolate history. Exact tape signatures belong to requests/witnesses, not
the learner family. Market/calendar witness reuse remains run-owned and bounded.

The registry records separate financial-domain and methodology axes. At E02, only the
previously qualified `signal_notional`, `pct_equity` and `reactive_reset` entries
are executable with meta; method remains Mode 4 / per_fold_causal. Other public
WFO targets have named pending gates. Options/Nautilus/intrabar/explicit commands
are not activated by registration. Unknown ABI/route/scorer/input kind fails
before search/evaluation. `walkforward_support_matrix` keeps its signature and
existing rows and gains additive meta fields; W3 remains a separate prepared
surface, not an invented target endpoint.

Future dispatch additions must pass inventory conformance: an actual adapter
with software/empirical/owner gates, or an explicit pending disposition. A final
OOS route is not proof of a native IS evaluator, observer or meta capability.

## Causal And Financial Invariants

Full eligible pool, exact native anchor and current IS metrics are captured
before compaction. Meta selection executes actual effective params; no second
raw-IS floor overrides a valid meta decision. Panels seal before forward
outcomes, and availability/revision filtering remains in `MetaHistory`.
Observers use independent RNG and existing isolated fresh strategy/account
lifecycle. Scalar final account remains continuous stitched targets; W3 remains
segmented reset-flat and never gains continuous equity by concatenating returns.
Prepared same-pass evidence is reused without replay. Missing evidence fails.
No C01/C05 method or geometry activation is implied.

## Empirical Promotion

Use the [frozen registration template](DOMAIN_EMPIRICAL_REGISTRATION.md) before
any E03-E07 study. The owner approves alpha/data and R/Q/uncertainty/budget
thresholds before outcomes. Engineering conformance is separate from economic
acceptance and remote/public artifact qualification. No new real-alpha study
is authorized or claimed by E02.

## E03 Scalar Amendment

E03 adds explicit `SOFTWARE_VALIDATED_OPT_IN` research admission for `notional`,
`unit` and structural `dca_ladder`, only Mode 4 / `per_fold_causal` with endpoint
scoring. Empirical/owner promotion is separate and pending; no default changes.
`single_signal` and `%_equity` resolve to their canonical scalar routes with meta.
Omitted/off calls preserve original proxy defaults. Native-event coverage means
existing signal-to-rebalance execution, not a reactive order or intrabar adapter.

`qms-scalar-execution-e03-v1` names each sizing/backend/timing and ladder policy.
New families bind the E02 `DomainCompatibility`; old qualified family IDs stay
exact. Notional resizes with price, unit scales at the evaluation-window start,
signal-notional freezes units until transitions, pct-equity uses the existing
equity-transition engine. Structural ladder consumes signed integer level caps
and actual high/low. Limits, base/flat close fills, TP priority, same-bar exits,
funding, quantity/margin checks remain owned by the original ladder kernel.

Meta rejects mismatched sizing, legacy fee/slippage overrides, missing ladder
high/low and incompatible prepared-required routes before financial work. For
legacy calls explicit one-way `fee_rate` must equal `fee / 2`; off behavior is
untouched. Prepared notional/unit remain bounded same-close targets; ladder and
event rebalance cannot substitute that timing. One final continuous account is
rebuilt from stitched signals, not summed/compounded fresh diagnostic accounts.

The [E03 assessment](QMSE03_REPORT.md#prepared-study-and-parity-blocker) reports
a real prepared-unit metric parity failure after liquidation, not an adapter
permission to change that metric or the financial arrays. Prepared notional's
matched study passes; unit's equal flat final arrays cannot certify its search.
The separately approved [E03-G01 closure](QMSE03_G01_CLOSURE.md) now passes fresh
artifacts and the unchanged full unit study with explicit `legacy_zero_base_v1`.
Old incompatible extensions fail required preparation or record auto fallback;
original prepared-off remains usable. Historical failed receipts are retained.
Software/metric admission is not blanket economic or remote/public certification.

## E04 Portfolio Amendment

E04 extends the shared adapter to existing `target_mode="portfolio"` on
Mode 4 / `per_fold_causal`. It is `SOFTWARE_VALIDATED_OPT_IN`; real-alpha R/Q,
owner promotion and final-source remote/public proofs remain separate gates.
It does not repair E03-G01, enable another methodology, or replace financial
execution with a scalar/Rust proxy. Read the [E04 plan](../../upgrade/implement.md#qms-e04),
[local report](QMSE04_REPORT.md), [example](../../examples/wfo_meta_portfolio.py)
and original [portfolio accounting guide](../portfolio_engine_v3.md).

- Financial authority is the original `native_portfolio` shared account
  (NumPy/Numba). Existing Rust-first meta fit/rank remains independent. Backend
  `auto` resolves to that original portfolio path; legacy, Nautilus and Rust
  portfolio substitutions are rejected with meta. Scalar prepared `require`
  does not qualify a shared account.
- Input is an exact aware, ordered, unique calendar with an explicit ordered
  universe and a mapping of OHLC DataFrames. Actual close/high/low are required.
  Caller-aligned asynchronous observations retain `NaN`; no union/resampling,
  forward-fill, new stale-price policy or instrument inference occurs here.
- Output is a finite position DataFrame in universe order, or ordered Series
  mapping, on the exact evaluation index. Wrong/extra/missing symbols, reordered
  targets and non-finite targets fail closed before financial evaluation.
- Mode, sizing, betas, risk lookback, account constraints, funding policy,
  economics, calendar policy and account/timing/witness ABI bind history families.
  Actual market/funding prefixes bind evaluation signatures, not future dates
  in a compatibility family. No scalar/W3 history is automatically transferred.
- Raw IS/forward metrics come from the original aggregate full-report reducer,
  never an average symbol Sharpe or summed symbol return ratio. Original accepted
  and requested quantities, fees, slippage, funding, margin, turnover and
  diagnostics enter the accounting witness. Missing buffers or a non-original
  result is rejected; there is no accounting replay to manufacture evidence.
- Each diagnostic uses a fresh reset-flat account and isolated strategy/RNG.
  Final OOS positions are stitched and executed once on the original continuous
  `carry_position` account. Fresh diagnostic equities are not concatenated.
  Timing remains close-to-close without an extra signal shift; rebalance,
  rounding, liquidation and Risk Parity warmup remain engine-owned.
- Immutable per-symbol row witnesses reuse the existing run-owned prepared WFO
  context and one bounded witness cache. No accounts/orders/RNG are cached.
  `optimization_config["metadata"]["use_prepared_meta_witness"]=False` disables
  witness reuse; `use_prepared_scoring_cache=False` disables market-array reuse.
  Original scientific observations/selection/account outputs must still match.
  Measured wall-generation clocks and their revision hashes need not match
  between separate runs; no availability is backdated to force byte equality.

The software corpus covers all 11 existing sizing aliases and six portfolio
modes, original off/shadow accounting, actual learned selection, independently
computed costs/margin and future/history isolation. This is not W3 multi-symbol
carry, a venue-exact portfolio-margin engine, an intrabar portfolio fill model
or evidence of positive forward economic gain. E04's synthetic example and
reduced-support fixtures are engineering tests only, not registered studies.

## E05 Package Amendment

Only Mode 4 / `per_fold_causal` with explicit endpoint scoring is admitted.
Meta-off basket/arbitrage proxy defaults are unchanged. Read the
[E05 plan](../../upgrade/implement.md#qms-e05),
[original pair/basket guide](../pair_basket_guide.md) and
[sanitized example](../../examples/wfo_meta_package.py).

- Original `native_event` owns all execution/accounting. Supported software
  cells are frozen best-effort `BasketSpec`, linear non-expiring
  `BasisArbitrageSpec` and `StatArbPairSpec` with frozen base-quantity hedges.
  Statistical pairs require target-gross-notional sizing. No new Rust package
  financial promotion is implied by Rust Ridge execution.
- Declare `symbols` in exact spec-leg order. Provide an aware OHLC mapping on
  one exact calendar and a finite scalar package-signal Series on the window
  index. Missing/unbound asynchronous tapes fail before search; the adapter
  does not interpolate, resample or invent a stale-price policy.
- The family binds the exact spec, execution/account, universe, metric, nominal
  funding policy and original package timing. Market/volume/funding prefixes
  reuse the same run-owned row witness as E04; no financial/RNG state is cached.
- IS and post-seal forward labels use original aggregate account full reports,
  not spread returns, average symbol Sharpe or simulated leg equity. Final
  stitched signals run once on the original continuous package account.
- Original accepted positions, fees, funding, margin, diagnostics, typed fills,
  target plan, rejection report and available leg/package PnL bind the witness.
  Targets are not assumed accepted: best-effort rejects can leave partial legs.
  Atomic margin admission is not an exchange-native atomic execution guarantee.
- Reject external dynamic hedge ratios, unsupported hedge/margin/carry/cost
  models, expiry/rolling/inverse/quanto/options, non-market/IOC execution and
  unbound endpoint instrument/quantity knobs. Basis planner leg quantity
  constraints remain original; statistical-pair leg rounding/tick constraints
  are not forwarded by its existing basket planner and therefore rejected.
- `scoring_backend="endpoint"`, `use_scalar_trial_scoring=False`,
  `native_prepared_wfo="off"` and an explicit meta history are required.
  `native_prepared_wfo="require"` cannot substitute a scalar Rust account.

Software/installed qualification is not empirical promotion. Each package
alpha needs a frozen study, original-account R/Q/decay evidence and owner review.
Quarterly delivery/provider, additional package specs and specialized engines
retain their own gates; private source/data must never enter wheel/sdist/Git.

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

# Native Companion Capabilities

Capability claims are generated from
`contracts/native_event_product_registry.json`; the generated table is the
authoritative release-facing view:

- [Generated Native Product Compatibility](../contracts/generated_product_compatibility.md)

The table specifies contract IDs, strategy mode, result profile, account model,
portfolio/package policy, maturity, supported platform evidence, and whether
automatic promotion is allowed. This is deliberately more precise than a flat
list of booleans such as “supports limit orders”.

## Reading maturity

- **Certified**: covered by the declared contract and its current conformance
  evidence. It is not automatically promoted unless the table says so.
- **Experimental**: available for explicit validation only. It must not be used
  to imply generic endpoint or venue support.
- **Promoted**: eligible for `native_backend="auto"` only when its generated
  row, installed-wheel handshake, scale threshold, and local rollback policy
  all pass.

The current Stage-B table promotes only the bounded E0/E3/E6 families: static
command tapes at 10,000 or more bars, and Native Strategy IR/batch requests at
2,000 or more bars. Arbitrary callbacks, reactive strategies, and generic
portfolio/package/arbitrage endpoints remain Python. Phase 54B.3 additionally
certifies explicit, bounded Rust helpers for `target_units` market targets and
same-bar all-or-none market packages. Phase 68 extends the latter with typed
Package V2 execution for `atomic_bar_simulation`, `sequential`, `best_effort`,
and `hedge_after_primary`. V2 derives dependent hedge quantity from the
committed primary fill, quantizes it after that calculation, and retains
residual/reservation accounting. Its scenario batch shares only immutable
market/template state, reset-flats every scalar scenario, and requires a
selected audit rerun for leg detail. These rows are intentionally not
auto-promoted until a generic endpoint route has an equally exact fallback
contract. The extension's raw feature map is an implementation probe; it is
normalized by the core's generated descriptor before public routing decisions
are made.

Native WFO Runtime V2 is a certified but explicit-only row: single-symbol
`strategy_ir_signal_target_v1`, W1/W2 prepared signal buffers, fresh reset-flat
OOS accounts, scalar score rows, and selected audit replay. It is not a generic
`walk_forward()` promotion. Phase 74 separately admits a narrow public scorer
below normal `walk_forward()` / `train_test_split()` orchestration: one scalar
OHLCV symbol, `signal_notional`/`single_signal`/`notional`/`unit`, 365-day
metrics, and fresh candidate/fold scoring. It preserves WFO selection and the
final stitched account, remains opt-in, and records its resolution/fallback.
`mode_2_sbb` preserves its proxy route; portfolio, package, and target-weight
WFO intents remain on their own fail-closed contracts. Stateful reactive WFO
has one separate explicit reset-flat W3 contract, while unsupported reactive
account boundaries still fail closed. See [Public prepared-native WFO
scoring](../native_prepared_wfo_public.md) and [Reactive WFO (W3)](../reactive_wfo.md).

Phase 66 adds an explicit direct-target family outside the event-lifecycle
promotion table: `rust_direct_target_v1` with separately advertised
`target_units`, `target_notional`, `target_weight`, and `equity_fraction`
capabilities, plus a typed static-DCA compiler and single-symbol prepared
target WFO score/audit companion. These routes use the distinct
`close_target_v2_same_close` target clock, never allocate a generic order
arena, and fail closed if the native wheel lacks the matching feature flag.
They are **not** auto-promoted, and they are not a claim that generic
portfolio, grid/DCA, or callback WFO is Rust-authoritative. See
[V1.1 Direct Target Execution Clock](../contracts/v1_1_target_execution_clock.md).

Phase 67 adds the separately explicit `rust_shared_portfolio_target_v1`
family. It executes one linear quote-settled gross-cross account across a
planned multi-symbol target matrix with a fingerprinted admission policy:
`sequential_legacy`, `reduce_first_then_increase`,
`pro_rata_to_available_margin`, or `all_or_none_rebalance`. Target units and
prepared multi-symbol target WFO are certified explicit rows; target notional,
weight, and equity-fraction stay experimental until their individual matrix is
expanded. This is not a promotion of `QuantBTEndpoint.portfolio()`: the
generic planner and its Python/Numba executor remain the rollback route and
record their planning/execution authority in result metadata.

Phase 68's `package_market_v2` and `package_market_v2_scenario_batch` rows are
also explicit-only. They accept typed same-account linear package intents under
`event_lifecycle_v2_next_bar_close`; they do not infer strategy hedge ratios,
create venue-native atomicity, or replace `basket()` / `arbitrage()`. Selected
basis, stat-pair, calendar, and index-basket plans can be lowered only when
their plan is already linear and same-account. Triangular and cross-exchange
plans fail closed because currency conservation, venue accounts, prefunding,
and independent clocks are outside this contract.

Phase 69 adds `intrabar_bracket_rust_v1` as a **certified explicit-only**
single-symbol OHLC row. Its authority is deliberately specialized rather than
being folded into the generic event engine: one typed request owns the
next-open intent clock, SL/TP, gaps, same-bar policy, trailing updates,
technical exits, optional session controls, funding, margin, liquidation, and
bounded audit SoA. The generated product table records only the shared
next-open entry-clock identifier; the full ordering and non-claims are frozen
in [`contracts/intrabar_contract_v1.json`](../../contracts/intrabar_contract_v1.json).
It does not auto-promote `intrabar_bracket()`, generic callbacks, grids/DCA,
portfolio cross-margin, or L2/order-book claims. `reject_ambiguous` and
`lower_timeframe_required` fail closed. Numba remains the documented rollback
comparator for one stable release after this route's A4 evidence.

## Public Installation Boundary

The public package pair is `quantbt-engine==1.1.0` and
`quantbt-native==0.4.1`. The core declares the companion directly only for
Linux x86_64 glibc / CPython 3.11-3.13. `pip install quantbt-engine` and
`poetry add quantbt-engine` therefore install a pre-built wheel on that matrix;
they do not build Rust locally. Other platforms retain the full Python/Numba
endpoint surface and record Python selection where a governed native route is
not available.

Public availability is certified by the native-first publish workflow and the
Ubuntu 22.04/24.04 Poetry consumer matrix. See the
[release checklist](../testpypi_release_checklist.md) for the immutable
artifact order and exact proof output.

## Performance Boundary

On the committed historical release fixtures, the explicitly certified Native Strategy IR score path
processed 2,000 bars in 0.741 ms (2.70M bars/s), versus 31.565 ms for the
Python oracle, with exact trace/accounting parity. A shared 64-scenario IR
batch processed 128,000 simulated bars in 11.379 ms (11.25M bars/s).

The explicit bounded portfolio-target and atomic-package helpers measured
3.594 ms and 3.512 ms on their 2,000-bar x 8-symbol fixtures, 9.3x and 5.6x
faster than the corresponding Python event oracles. These are score hot-path
results. They do not imply the same speedup for callback strategies or full
audit/report construction. Read [Benchmarking governance](../performance/benchmarking.md)
for evidence links and interpretation rules.

The prepared Native WFO V2 score fixture runs 64 candidates across 4 causal
folds of a 4,096-bar tape in 232.514 ms. Its four OOS windows total 3,414 bars,
so its corrected rate is 0.94M actual candidate-test-bar visits/s, 1.37x the
prior fold-batch oracle with exact metrics/counts. The earlier 4.51M value is
only logical input-volume/s. Strategy generation and the one controlled intent
ingest are reported separately; see [Native WFO Runtime V2](../native_wfo_runtime.md)
and the [measurement contract](../performance/measurement_contract_v1.md).

The separate Phase 74 public W0 WFO fixture uses 2,048 bars and 16 sequential
Mode 1 global trials. Post-warm median facade time was `431.730 ms` versus
`1.053 s` for the historical endpoint scorer (`2.44x`); the isolated
candidate-score stage was `166.156 ms` versus `800.033 ms` (`4.81x`) with
exact selection/final-account parity and a `0.008 MiB` RSS tail spread over
five repeats. It is one single-symbol scalar WFO matrix, not a generic
callback or all-WFO speed claim. See [Public prepared-native WFO scoring](../native_prepared_wfo_public.md).

The Phase 66 explicit direct target route has separate evidence for its frozen
single-symbol `close_target_v2_same_close` contract. On 20,000 bars, its typed
prepared score ran in 1.607 ms (12.45M bars/s) versus a 0.607 ms warmed Numba
kernel, while the public compact Rust route ran in 23.432 ms (853,549 bars/s)
versus 58.600 ms for the Numba compact facade. The difference is intentional:
typed score and public adaptation are separate workloads. Exact accounting and
position parity passed; score retained no paths and its warm steady-state RSS
delta was 3.01 MiB. This evidence does not promote `auto` or certify generic
portfolio, grid, or callback execution. See [Direct Target Execution Clock](../contracts/v1_1_target_execution_clock.md).

Phase 67 local evidence runs a 2,000-bar × 20-symbol shared-account fixture
with 16 prepared candidates over two causal folds. On the recorded smoke run,
prepared score processed 16.7M bar-symbols/s and prepared WFO processed 45.0M
bar-symbol-candidate-folds/s, with `market_copy_bytes=0`, score/compact
terminal parity, and selected audit parity. These are explicit contract
measurements, not a claim about generic portfolio or risk-parity performance.

Phase 68 local evidence uses a 2,000-bar partial-primary,
post-actual-fill-hedge fixture. The 20-leg prepared score median was `0.873 ms`
(`45.82M bar-symbols/s`); a batch of sixteen isolated 20-leg scenarios took
`13.114 ms` (`48.80M bar-symbols/s`) through one native entry with zero market
copy bytes. Score/compact/audit terminal parity and batch-vs-selected-single
parity pass. Process RSS was `149.84 MiB` at start, `168.07 MiB` after the
three profile requests, and `170.91 MiB` after the batch. This is a bounded
package measurement, not a generic arbitrage, callback WFO, L2, or venue
atomicity claim; see the [Phase 68 artifact](../../benchmarks/native_event/results/phase68_bounded_package.md).

Phase 69 source-branch evidence uses 2,000 one-hour bars with long/short
entries, SL/TP/trailing, technical exits, fee/slippage, and close-timestamp
funding. Its prepared scalar kernel measured `0.096 ms` (`20.90M bars/s`), its
prepared compact kernel `0.159 ms` (`12.60M bars/s`), and the public compact
adapter `2.538 ms` (`788,099 bars/s`) against the Numba standard/path
comparator at `2.053 ms` (`974,199 bars/s`). The difference is intentional:
the public adapter builds pandas-facing output on the cold path, while scalar
score retains no dense paths. Exact terminal/path parity and one-boundary,
zero-callback evidence pass. This is local development evidence for a matching
native build, not a claim about the already-published companion wheel; see the
[Phase 69 artifact](../../benchmarks/native_event/results/phase69_rust_intrabar.md).

Phase 77 adds a matched public result-level comparison for this same explicit
single-symbol intrabar authority. On 20,000 one-hour bars, both prepared
runners returned the ordinary `standard` result surface; Rust measured
`10.233 ms` (`1.95M bars/s`) and matching Numba measured `13.884 ms`
(`1.44M bars/s`), with exact path, fill, accounting, margin and liquidation
parity. Rust one-shot and Numba one-shot endpoints were effectively tied.
The improvement is only for the explicit prepared runner whose immutable market
has already been validated; it does not promote generic intrabar, callback,
grid/DCA, portfolio, or `auto` execution. The 96-run same-process RSS probe
plateaued after warm-up; read the [Phase 77 artifact](../../benchmarks/native_event/results/phase77_native_performance_closure.md)
for fixture, p95, and memory-scope details.

At native probe time QuantBT validates two distinct descriptors:

- the frozen API 0.4 semantic descriptor for event-clock, fill, and account
  behavior;
- the product descriptor for exact core/native versions, protocol, command and
  result ABI, trace schema, strategy IR, and registry fingerprints.

An explicit Rust request fails before market preparation if either descriptor
drifts. `backend="auto"` follows the generated promotion table and records a
structured fallback reason when a request is below its threshold, outside a
certified row, or has only historical measurement evidence. `QUANTBT_DISABLE_NATIVE=1` and
`QUANTBT_NATIVE_PROMOTION_MAX=explicit_only` deterministically force Python.

For the exact installed-wheel release gate, core-only fallback behavior,
rollback procedure, and release-owner checklist, read the
[native release handoff](../migration/native_release_handoff.md).

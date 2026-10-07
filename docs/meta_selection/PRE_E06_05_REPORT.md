# PRE-E06-05 Matched Cost And Shared Optimization

## Scope And Status

Local execution in progress on `feat/meta-selection-samplers`, entry `d0cd95a`.
This report is not yet an exit receipt. No release, workflow, push, economic
study or new route/method activation is authorized by this phase.

Read [the phase and registered budgets](../../upgrade/implement.md#qms-pre-e06-05),
[guide section 8](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8),
[section 10](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s10)
and [report discipline](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s12).

## Actual Change

Only `meta_selection/common.py::wire` changes runtime execution: exact built-in
portable values use a shorter dispatch before generic dataclass/Mapping/NumPy
handling. Enum and other subclasses retain the old dispatch. Independent tests
lock canonical bytes, SHA, negative zero, UTC conversion, immutable containers
and exact error strings. No float precision or invalid-value coercion changes.

Witness source/mutation/calendar checks, cache limits and closure remain on the
qualified implementation. A faster unchecked prefix test was not introduced.
No additional account, strategy, model, RNG, report or evaluation cache exists.
There is no new Rust ABI/build. The existing qualified Rust transform/Gram-solve/
rank batch remains unchanged; portable JSON/hash dispatch is not a numeric batch
worth replacing with per-scalar FFI. NumPy scaler/diagnostics remain observable.

Exact source normalization accepts only the one reviewed file/hash. It does not
re-seal old receipts, exempt whole files or waive financial/scientific guards.

## Measurement Contract

- 76 registered public synthetic cells: eight legacy five-mode/schedule cases,
  thirteen Mode 4 domain/accounts with off/shadow/active, four scalar prepared
  targets with all three states, five nested Mode 1 scalar targets with all
  three states, and two same-policy conditional Sobol/projection cases.
- Six/eight original trials, seed 731, lambda 10, original labels/panels and
  all retained outputs. Enabled cells require actual fit/rank with at least
  twelve mature origins. These small fixtures are not an economic acceptance study.
- 21 paired warm samples per cell, alternating arm order, one fresh worker per
  cell, one numeric thread. The single first cold sample is reported explicitly;
  the other warmup arm shares that worker and is not independent cold evidence.
- Frozen synthetic history is loaded once outside timing, then each run owns
  an independent history container, endpoint, account and strategy state.
  History-load and fixture preparation are recorded separately, not hidden as
  financial speedups. No source-alpha or market file is copied into public evidence.
- Ordinary endpoint construction is outside the timer. For W3 the constructor
  also prepares native market ownership; its per-run fixture/constructor cost
  is retained separately. W3 timing is the complete prepared public `backtest`
  call, not a fresh-data constructor-plus-backtest throughput certificate.
- Backtest timer includes normal preparation/scoring/meta/observer/final account
  and adaptation. Profiles are separate instrumented runs, not latency gates.
  Legitimate additional C01 raw outer-IS evaluations are retained and charged.
- Both arms bind equivalent exact portable/witness blocks outside timing;
  only reviewed implementation bodies differ. Financial execution, strategy,
  Optuna and model/numerical code are never replaced by the benchmark harness.

Budgets were owner-approved before results: disabled p50 +3%, p95 +5%.
Point failures are NOT_MET; uncertain timing remains INCONCLUSIVE. No selection
of favorable seeds, repetitions, samples, confidence bounds or relaxed budgets.
Twenty-one samples per cell are not a platform-wide tail-latency guarantee.

## Correctness And Causal Evidence

Every paired run compares original equity/returns/positions/cost/margin buffers,
liquidation state, orders/fills/trades/diagnostics, detailed report shape/labels,
final metrics, trial ledger, sampler trace, candidates, historical revisions,
training membership, descriptors, coefficients, selection/guards/ties and panels.
Unavailable legacy buffers remain explicitly absent, never fabricated as zeros.

Today's observer completion clock necessarily varies with wall time. The harness
checks exactly `actual availability = nominal maturity + measured observer time`
before comparing logical work. It preserves every historical eligibility clock
and identity used by the model. Physical task generation vintages are not logical
information. Raw physical telemetry is retained, not changed in runtime.

Separate Mode 4 and nested Mode 1 tests replay twelve complete chronological
folds each, including actual matured fit/rank and new labels feeding later
folds. Artifact identities that bind physical vintages are resolved to complete
logical payloads; financial measurements, permitted membership, model math and
decisions remain exact. Final stitched account is independently rebuilt.
Existing future/foreign/late-label/near-Q/tie and prepared-account regressions
remain required, not substituted by one final-equity comparison.

## Retained Exploratory Failures

A/A preparation revealed nonportable integer-key tooling output and physical
observer-clock differences; those failures are retained and corrected in the
harness, not the financial runtime. An exploratory write failed on mappingproxy
telemetry; subsequent evidence serializes before creating a receipt file.
The first guarded test run had two tooling failures (incorrect historical path
and a missing predecessor guard amendment); both have exact passing reruns.

The interrupted `matched-v1` remains exploratory. Its baseline subprocess/alias
setup was asymmetric outside the timer. Balanced `matched-v2` was stopped for
a portable type-dispatch edge case: custom metaclass equality cannot be used
as a test for exact built-in identity. Final `matched-v3` uses identity checks
and the same fixtures/repeats/budgets with balanced setup. New negative fixtures
initially required explicit class hashing to reach the intended dispatch test;
both failed fixture receipts are retained. All original files remain retained.
No failed run is rewritten as PASS.

`matched-v3` stopped after 44 complete ordinary cells because its untimed W3
reader used an ordinary metadata key instead of the typed result attribute.
The failed log is retained. Actual off/shadow/active W3 reader tests pass after
the schema correction, including segmented reset-flat accounts, fold/candidate
tables, selected params and task/state/metric provenance. Resume uses separate
attempt logs and does not overwrite completed timing cells or alter execution.

The first conditional cell stopped after 74 complete cells because the sampler
bridge exposes `sampler_wall_seconds`. Exact diff shows only that elapsed value
changes, not RNG/proposals/selection/account. Both actual conditional routes
pass reader parity after excluding that one physical diagnostic from logical
identity; it remains in per-sample raw telemetry and full-call latency. Failed
expected/actual JSON and logs remain retained; completed samples are unchanged.

## Remaining Gate

Final timing/retention disposition, full affected regression, source-bound
receipt, documentation checks and cleanup still need execution/closure.
Final-source installed wheel/sdist proof remains PRE-E06-06, with its own owner
approval. Economic/default and remote/public qualification remain separate.

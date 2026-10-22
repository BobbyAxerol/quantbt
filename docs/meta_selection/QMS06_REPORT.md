# QMS Phase Report - QMS-06

## Scope And Status

2026-10-04, branch `feat/meta-selection-samplers`, entry `3c69cb8`.
Implemented the approved [QMS-06 plan](../../upgrade/implement.md#qms-06)
and [detailed guide](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#qms-06--prepared-route-adapter-và-handoff-dùng-được-bởi-host).
Only prepared scalar parity, authoritative original-pass metric support,
capability/ownership proof and portable host handoff are in scope.

Mandatory scalar/handoff implementation is complete; five technical gates PASS.
Owner acceptance and optional W3 scope disposition remain PENDING; empirical
NOT_ASSESSED; performance MEASURED_COST_ONLY. No QMS-07/08, push, merge,
version change or publication is authorized. Core/native installed and released
versions remain **1.1.1 / 0.4.2**.

Implementation commit: `4635663`; hourly/cost/consumer-evidence lock: `6fc13b5`.
The documentation/evidence closure commit is separately visible in branch history.
Earlier QMS-01..05
receipts are unchanged historical artifacts, not regenerated on this source.

## Delivered

- Existing prepared execution/cache/runtime reused. No new financial bridge,
  engine, public backend override, sampling schedule or live controller.
- Feature-gated native score witness, ABI
  `same-pass-ddof1-daily-first-mark-v1`. Sample variance/count, first marked
  equity, liquidation and metric contract come from the **same original run**.
  No financial replay, placeholder-volatility inference or alternative Sharpe.
- Tiny additive first-mark retention in the existing reducer. All financial
  arithmetic and lifecycle bytes remain protected by strict source locks;
  witness getter/additions have an exact allowlist, not a broad source exemption.
- Existing Mode-4/per-fold-causal pool/selector hook works on original-result
  reference and compatible prepared scalar W0/W1/W2. Same-close timing,
  daily ddof-1 metric, quantity rules and fresh diagnostic accounts stay explicit.
  `%_equity` retains transition sizing and its existing economics guards.
- `off/auto/require` remains caller-controlled. Published 0.4.2 lacks the witness:
  auto records a compatible original-result fallback; require fails before search.
  Meta numeric require does not secretly replace the financial native wheel.
- Native output columns are detached/read-only; stale bindings fail after reset;
  outputs survive runtime close/cache clear. Candidate/run/account lifetime is
  the existing runtime's, not a mutable global cache shared between trials.
- Full immutable task/pool/anchor/reason/decision/model/snapshot/revision handoff.
  Restore verifies trusted IDs, external witness/revision authorization, family,
  permissions, basis/frontier and readiness. Future models cannot replay past
  decisions; cached older models retain their exact snapshot and readiness.
- Export and pure consumer do not refit, rerun execution, send broker orders,
  mutate account/indicator state or fill activation from a backtest fold start.
  Same params remain a read, not an implicit reset/deployment instruction.
- Endpoint/capability/methodology/discovery docs and runnable host demonstration.

See [integration and native policy](INTEGRATION.md) and
[portable API/host responsibilities](HANDOFF.md).

## Tests And Gates

[Executed JUnit](../../benchmarks/optimization/meta_selection/qms06_tests.xml):
**436 passed, zero failures/errors/skips**, 168.12 s, including **46 Q6 checks** and 390
prior/affected optimizer, sampler, WFO schedule, nested causal Mode 1,
native-prepared WFO and research-audit checks. This is a scoped regression,
not a claim that the entire repository or remote platform matrix was run.

| Gate | Executed proof | Result |
|---|---|---|
| G6-ADAPTER | Same public hook/full pool on W0/W1/W2; reference Numba/Rust and actual prepared Rust; original witnesses | PASS |
| G6-PREPARED_PARITY | Raw metrics, objectives, validity, anchor, prediction/eligibility, actual params, equity/returns/positions; V2 costs; accepted pct-equity units/costs against the ordinary native account | PASS |
| G6-CAPABILITY | off/auto/require; separate meta/financial policy; runtime, symbols, units, economics, same-close/next-open and insufficient-day guards | PASS |
| G6-HANDOFF | Full model/scaler/schema/snapshot restore, trusted permissions, distinct clocks, future/late-effect rejection; no broker/reset/replay | PASS |
| G6-NO_SCOPE_CREEP | Exact additive witness source locks, no version/published wheel change, W3 rejected before preparation, no alternate controller | PASS |
| G6-OWNER | No acceptance invented; optional W3 disposition explicitly awaits review | PENDING |

Q6-T01..08 counts: **8 / 14 / 2 / 6 / 2 / 10 / 2 / 2**.
Declared metric/account/inference tolerance is `rtol=atol=1e-10`;
logical identities, roles, anchors/actual params and permissions match exactly.
Implementation-specific terminal witness/evaluation hashes need not be byte
identical. Each remains tied to its original request/input/economics/output.

The matrix includes hourly and daily tapes, funding/cost/quantity constraints,
real zero-variance native runs, malformed witness ABI, reset/close lifetime,
strict restore failures and same-params consumer reads. Too-short scored windows
are rejected rather than replacing the reference's bar-return fallback with
daily native metrics. Existing off/shadow and future-data tests remain in the
affected regression; this adapter does not certify arbitrary callback causality.

Legacy `%_equity` `BacktestResult` intentionally exposes no standalone fees,
funding or accepted-unit paths. Its reference/prepared comparison covers the
existing equity/returns/weights and original raw metrics, under the same costs.
Where both results are V2, fee/funding paths are compared directly. A separate
ordinary public Rust `%_equity` run on the final frozen target tape proves
accepted-unit and per-cost parity with the prepared route's final account.
No missing legacy fields are fabricated or retrofitted in this phase.

Rust focused reducer/prepared tests also pass (3 engine cases and 1 binding
case). Actual native cases execute a compiled private candidate, not mocks or
missing-capability skips. Canonical-source, module/import, focused lint,
docs-link, whitespace and benchmark-governance gates are checked separately.

## Executed Cost And Ownership Evidence

[Evidence](../../benchmarks/optimization/meta_selection/qms06_prepared_evidence.json)
and [gate receipt](../../benchmarks/optimization/meta_selection/qms06_gate_receipt.json)
pin executed tests, source tree, guide and candidate binary hashes.

Existing synthetic public SMA rule: 850 daily bars, six quarterly studies,
six attempted trials per study, seed 731, one worker. Product support default
stays twelve independent origins; support-one is an explicit engineering override.
Each compared route captures the same full pool, four fitted models, 32 original
observer outcomes and the same actual params/account result.

All routes use declared historical search/fit/seal budgets of 10/20/30 seconds
after the frozen IS cutoff. These are replay clocks, not measured live readiness.
Actual wall costs remain recorded separately; labels keep measured observer
completion/publication. Current OOS never enters selection.

The prepared workload performs **134 native score rows over 12,004 scored bars**
in **38 execution batches**, plus 38 witness materializations and existing
output/diagnostic calls. Witness arrays add **4,690 output bytes**. Existing
prepared market residency is **48,450 bytes**; transient requests total
**124,328 bytes** over the run. These are specific buffer counters, not process RSS.
No claim of zero-copy or one total FFI per study is made.

The qualified meta Rust blocks use **16 calls plus 3 qualification probes**,
with **5,076 owned input-copy bytes**, across four fitted vintages rather than
per market bar. Encoding/scaler/diagnostics/reference verification remain
explicit NumPy/Python; financial and meta backends are independent.

Six full decision packages restore successfully, including two no-model
fallbacks and four fitted-model packages. Export activation is `None`; host
state mutations are zero. This is read/revalidation evidence, not live deployment.

Public wall timings, snapshot/fit/observer costs and cumulative same-process
RSS are in the receipt's evidence. These are single full-public cost samples
after warm-up, not isolated kernel medians, RSS savings or a speed-promotion gate.
QMS-07 owns measured further optimization; QMS-08 owns economic/public-wheel
qualification. No superior Sharpe, sampler or future robust edge is claimed.

| Full public cost sample | Total |
|---|---:|
| Original-result Numba, meta reference | 2.708 s |
| Original-result Rust, meta reference | 2.999 s |
| Prepared Rust, meta reference | 2.398 s |
| Prepared Rust, meta Rust | 2.383 s |

Same-process cumulative peak RSS is **289.91 MiB**, including imports/JIT,
warm-up and all four measured runs. It is not an isolated per-route RAM result,
retention plateau or certified speedup. Full component costs remain in JSON.

## Reproduction

From the repository root, with the existing Rust/maturin toolchain:

```bash
# Isolated candidate; does not reinstall native 0.4.2.
.venv/bin/python -m tools.build_qms06_candidate

env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
QMS04_NATIVE_EXTENSION="$PWD/.maturin/qms04/_quantbt_native.cpython-312-x86_64-linux-gnu.so" \
.venv/bin/python -m pytest -q tests/meta_selection \
  tests/test_optimization_core.py tests/test_optimization_samplers.py \
  tests/test_optimization_integration.py tests/test_optimization_phase33b.py \
  tests/test_phase49a_walkforward_schedules.py \
  tests/test_phase50_nested_mode1_causal.py \
  tests/test_phase74_public_wfo_native.py tests/test_perf_06_research_audit.py \
  --junitxml=benchmarks/optimization/meta_selection/qms06_tests.xml

env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
.venv/bin/python -m tools.qms06_prepared \
  --extension .maturin/qms06/_quantbt_native.cpython-312-x86_64-linux-gnu.so \
  --junit benchmarks/optimization/meta_selection/qms06_tests.xml
.venv/bin/python -m tools.qms06_prepared \
  --extension .maturin/qms06/_quantbt_native.cpython-312-x86_64-linux-gnu.so \
  --junit benchmarks/optimization/meta_selection/qms06_tests.xml --check
.venv/bin/python -m examples.wfo_meta_handoff --demo-support
```

Previous QMS-04 tests require their separately built isolated candidate;
`python -m tools.build_qms04_candidate` builds it when absent. Do not regenerate
historical phase receipts to make their source hashes match this later phase.

## Remaining Boundaries

No mandatory scalar/prepared or portable-handoff functionality is deferred.
W3's separate reactive reset-flat loop has no equivalent full-pool/original-metric
selection/label seam. Implementing it would require new reactive capture/account
integration, so active/shadow meta explicitly fail before evaluation under guide
section 8.4. Optional W3 scope acceptance remains an owner decision, not a success
claim. Ordinary reactive WFO is unchanged.

Local candidate is **0.4.3.dev2**, Linux x86_64 / CPython 3.12 only. Its off-by-default
features are not a published native wheel or multi-platform certification.
QMS-07/08 and automatic live permission are outside this phase; they have not
been silently started or substituted for missing required QMS-06 work.

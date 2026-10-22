# E03-G01 Prepared Liquidation Metric Compatibility Closure

## Current Conclusion

**CLOSED_LOCAL_CORRECTNESS** on 2026-10-06. The owner-approved repair preserves
the legacy objective rather than replacing its estimator. Ordinary/prepared
chronological search, labels, selection and original accounting pass on the
exact registered real unit-sizing study. Economic promotion, current-source
remote qualification and public publication are independent gates.

Read the [approved scope](../../upgrade/implement.md#qms-gap-closure-2026-10-06),
[exact eight-file amendment](../../benchmarks/optimization/meta_selection/qms_g01_reviewed_source.json)
and unchanged guide [raw metrics](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s5),
[prepared/chronological parity](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s8)
and [economic interpretation](../../upgrade/QUANTBT_1_1_1_META_SELECTION_AND_SAMPLER_MODULE_GUIDE_V1_1_VI.md#s14).
The [original E03 failure](QMSE03_REPORT.md#prepared-study-and-parity-blocker)
and its sealed receipt remain unchanged, not retrospectively relabelled PASS.

## Root Cause And Repair

Legacy array returns use `(equity_next - equity_previous) / equity_previous`,
with a zero sample when previous equity is zero. Native reduction skipped
zero-base samples. Liquidation tails therefore changed sample counts, daily
Sharpe and Optuna objectives despite identical execution arrays. The original
first divergent trial had an objective difference of approximately 1.592.

- `legacy_zero_base_v1` is the explicit prepared endpoint compatibility policy.
- `native_skip_zero_base_v1` remains the native request default, including its
  existing arithmetic. Existing default request identities remain stable.
- Metric policy is bound to request/cache/metric fingerprints. Old extensions
  cannot silently produce an incompatible score: `require` fails and `auto`
  records a compatible fallback. Unsupported policies fail explicitly.
- Reduction stays inside the existing Rust boundary. There is no Python account
  replay, truncation of bankrupt tails or post-hoc objective replacement.
- Fees, funding, positions, margin, liquidation, window-start unit sizing,
  annualization, DDOF, penalties, RNG, pools, Ridge and guide math are unchanged.

Only the exact reviewed production bytes are normalized for historical source
guards; a mutation of those bytes still fails. This is not a file-wide exemption.
No original notebook, alpha module or data loader was edited or published.

## Executed Local Gates

| Gate | Actual result |
|---|---|
| Independent zero-tail/recovery/daily metrics; policy and old-wheel guards | PASS |
| Direct/prepared score, compact and audit financial/metric parity | PASS |
| Full `tests/meta_selection` against fresh installed native | 1,356 PASS, zero skips/errors/failures |
| Affected native/profile/public-WFO regression | 50 PASS; union with QMS is 1,399 distinct tests |
| Rust engine / execution crates | 50 + 15 = 65 PASS |
| Fresh core wheel and sdist / native consumers | PASS; required repaired consumer has 3 checks and zero skips per artifact |
| Registered real unit ordinary/prepared replay | PASS, including logical panels and all raw IS/forward observations |
| Secret/source/docs guards and resource cleanup | PASS before feature-only push; 31 focused docs/report/installed-proof checks also PASS |
| Ubuntu 22.04/24.04 x CPython 3.11-3.13 | 6/6 PASS on repair source `6901a66`, including installed G01/W3/scalar/portfolio/package |

The first regression XML with five stale test-assumption failures is retained.
The assumptions were corrected explicitly; no estimator or tolerance was changed.
The final QMS XML records 792.152 seconds (pytest terminal: 792.40 seconds).

## Registered Real-Alpha Replay

Gradient/Delta RSI, ETHUSDT 1h, original unit-sizing contract: 28 monthly folds,
128 attempts per fold, seed 731, no post-outcome retuning. Registration is
byte-identical to the failed study. Each new arm has **3,584 attempted / 3,531
COMPLETE / 53 PRUNED**, and 458 original observer evaluations. The new ordinary
arm also matches the historical ordinary arm.

| Compared item | Maximum difference / disposition |
|---|---|
| Objective, mean IS Sharpe, paired raw Sharpe | `5.773159728050814e-15` |
| Equity, returns and positions | `0` |
| Trial/candidate identities, params, roles and selection | Exact |
| 28 tasks/revisions, ordered base panels, raw observations and maturity | Exact logical parity |
| Objective tolerance | Existing `rtol=1e-9`, `atol=1e-9` |
| Accounting tolerance | Existing `atol=1e-8`; observed difference is zero |

Physical output hashes and elapsed computation clocks differ across ordinary
result/native score routes. Each original payload hash/clock is retained and
validated; those physical representations are not falsely required to be equal.

**Flat-account caveat:** the unchanged final stitched unit account rejects all
targets under its unit-window/margin semantics. Both final equities are 20,000
and accepted positions remain zero. The reported activity count is not accepted
fills. This account is not economic evidence; the nontrivial IS liquidation
paths, metrics, complete search and labels are the correctness test.

## Matched Runtime And Memory

| Same registered full unit study | Ordinary | Prepared |
|---|---:|---:|
| Elapsed | 549.001 s | 291.542 s |
| Peak RSS | 367.023 MiB | 374.504 MiB |

Prepared was **1.883x** faster, elapsed **46.90%** lower, with **7.480 MiB**
additional peak RSS. These are single measured public studies on a shared VPS,
not repeated controlled estimates or a guarantee for every alpha/endpoint.
No trials, labels or requested outputs were dropped for the comparison.

## Exact Retained Evidence

Local evidence is ignored/private. It retains alpha/data, full params and raw
receipts without exposing them in Git. These hashes identify actual executed
files, not proposed commands:

| Evidence | SHA-256 |
|---|---|
| Original registration, reused byte-for-byte | `8208de5643b6d850fc1e269760a6859e13d9987124f44898b236ba1d70cd2f96` |
| New ordinary raw receipt | `5a4c9e0512ad480d4d5b106888961bdbb5541608acee5c0448c334f27372d13b` |
| New prepared raw receipt | `b4b133173419014ecfa5ec0c31cbcbee24fd69ea8bec89ed258c238e86386111` |
| Refreshed exact-artifact installed proof | `ac340a3b0fbf359eeb0e09359d4db56452a4cab73797ce2c6644190a9f79a116` |
| Actually loaded study / artifact-consumer extension | `e338a0f1549395211dc42332ed15eb43c0bb92f71728ca3181b0268f56a57aba` |

Retained lanes: `data/local/qms-real-review/e03-g01-replay-v1` and
`.maturin/qms08/g01-package-v1`. Final comparator receipt is
`g01-replay-proof-v2.json`; the earlier comparison receipt stays sealed.
Final installed reproof is `g01-refresh-proof.json`; the full fresh build and
prior mandatory W3/scalar/portfolio/package consumers are retained as well.

| Fresh local artifact | Bytes | SHA-256 |
|---|---:|---|
| `quantbt_engine-1.1.2-py3-none-any.whl` | 1,024,299 | `e76587f9efaf889885381679393ad340926949dc64c7d59d5eb52a752276a4d9` |
| `quantbt_engine-1.1.2.tar.gz` | 911,417 | `9221a711990c8bff600d30628c7b3da3f24d39725b86273587014195e6dfc98f` |
| `quantbt_native-0.4.3-cp312-cp312-manylinux_2_34_x86_64.whl` | 1,185,262 | `f5fe1ec4d9268752733ba2c7023cc0e2548215986a8cd73fb6fafb285422a3b6` |

This local native artifact is not a manylinux2014/public-index portability
certificate. Rebuilt final-source remote wheels have their own hashes.
Reproduction uses `tools.qms_g01_study compare` with a new receipt name and
`tools.qms_g01_package --reprove-retained`; neither overwrites sealed evidence.

## Remaining Decisions

- **E03 economics:** original eight-cell outcomes remain 0/8 economic PASS;
  repair parity does not authorize empirical/default promotion.
- **E04 economics:** original exact-account diagnostic remains NOT_PROMOTED;
  forward-Q interval includes zero. No retry-until-positive or scientific change.
- **E05:** real quarterly expiry/roll and required historical coverage remain
  DOMAIN/DATA_BLOCKED. Non-expiring bounded proof is not delivery parity.
- **Remote:** owner approved feature-only push; all six rows passed on
  `6901a66b29c4039b2522a1a6367431fcfe7016ad` in
  [run 37447291412](https://github.com/BobbyAxerol/quantbt/actions/runs/37447291412),
  including eleven mandatory steps per row. The
  [new API receipt](../../benchmarks/optimization/meta_selection/qms_g01_remote_qualification.json)
  preserves job IDs and uploaded artifact digests; payloads were not independently
  downloaded. This is a candidate Ubuntu gate, not final manylinux2014/public proof.
- **Public:** no merge, tag or publication is authorized. Pair 1.1.2 / 0.4.3 is
  prepared only; C01/C05/W3/new route activation remains a separate decision.

Read the [current gap ledger](GAP_CLOSURE_STATUS.md),
[release handoff](RELEASE_HANDOFF.md) and
[completed cleanup receipt](../maintenance/QMS_G01_CLEANUP_2026-10-06.md).

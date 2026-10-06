# QMS-E04 Portfolio Software Closure

Generated from exact local receipts, not handwritten economic outcomes.
Read the [unified plan](../../upgrade/implement.md#qms-e04),
[domain contract](DOMAIN_ADAPTER_CONTRACT.md#e04-portfolio-amendment)
and [example](../../examples/wfo_meta_portfolio.py).

## Scope And Authority

Mode 4 / `per_fold_causal`, `target_mode="portfolio"`, original
`native_portfolio` shared account. Exact ordered universe/calendar and positions
are required. IS and forward metrics come from the original aggregate full
report, never mean symbol Sharpe. Diagnostic accounts reset; final OOS positions
are stitched once into the existing continuous account. No financial replay,
new portfolio engine, Ridge mathematics or sampler changes.

## Gates

| Gate | Result |
|---|---|
| Scoped software | PASS: 122 distinct checks |
| Source/historical scalar/reactive/account locks | PASS |
| Installed wheel and sdist, pair 1.1.2 / 0.4.3 | PASS |
| Real portfolio alpha, paired R/Q/decay (T05) | NOT_RUN |
| Empirical promotion / owner review | PENDING |
| Remote / public release | NOT_RUN for current bytes / NOT_AUTHORIZED |

Earlier failed XML/build/install lanes remain unchanged. A software receipt
does not waive E03-G01 prepared-unit liquidation metric incompatibility.

## Matched Synthetic Performance

730 daily bars, two symbols, four folds, six attempts/fold, seed 731, one thread.
Each arm has its own fresh process/account; warm values use two full-study runs.

| Arm | Warm median (s) | Process peak RSS (MiB) |
|---|---:|---:|
| off | 1.183 | 282.0 |
| prepared | 2.527 | 287.1 |
| reference | 4.426 | 286.1 |

Prepared witness/reference speedup: 1.75x. Off and shadow have exact
account, selected params and trial identities; reference and prepared also
share the exact candidate pool. Meta still costs more than off, including
post-seal label observations. This fixture is synthetic, not evidence of lower
decay, economic edge, a universal speedup or Rust portfolio promotion.

## Invocation And Limitations

Use the existing `QuantBTEndpoint.walk_forward`, original `portfolio_mode` and
`sizing`, an explicit `symbols` list, `scoring_backend="endpoint"`,
`use_scalar_trial_scoring=False`, `native_prepared_wfo="off"` and an opt-in
`meta_selection` policy. Prepared portfolio arrays are a separate owner from
the scalar Rust scorer. Missing/stale observations retain caller policy;
unaligned source calendars are rejected, not resampled.

No W3 multi-symbol carry, options/venue-specific portfolio margin, additional
meta methodology or official empirical promotion is certified here. Real
alpha/universe/search/R/Q analysis must be frozen before results, with no
gain-driven retuning. NEXT: finish the separately approved real portfolio gate;
E05 requires its own authoritative package scorer and original-account proof.

## Reproduce And Cleanup

Run `python -m tools.qms_e04_package --help` for a fresh isolated offline
wheel/sdist lane, then `python -m tools.qms_e04_report --help` for receipt-bound
report generation. Reuse the repository build environment, not an alpha venv.
Retain dist/staging, native wheel, logs and receipts. Only inactive reproducible
consumer scratch may be removed after hash verification; reinstall it before
rerunning. Follow the [cleanup runbook](../BUILD_TEST_CLEANUP.md).

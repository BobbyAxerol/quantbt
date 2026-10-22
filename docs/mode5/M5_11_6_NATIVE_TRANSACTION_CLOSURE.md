# M5-11.6 Native Transaction Closure

## Disposition

**Local bounded runtime gate PASS. Long research is not started or complete.**
This follow-up closes the missing HMA feedback-session implementation from the
[previous performance pass](M5_11_6_PERFORMANCE_CLOSURE.md). It does not replace
the 57-fold, mature-meta, future-mutation or economic gates of
[M5-11.6](../../upgrade/implement.md#mode5-m5-11-6).

The owner authorized source changes and bounded verification, but requested a
readiness report before another optimizer/background queue. There are zero new
proposals, no repeated 128-trial study, no push/CI/release and no alpha changes.
The previous wheel/environment is retained and has not been overwritten.

## Shared Native Contract

`FullSession` now owns an optional current-bar transaction: begin, retry, commit
or abort. The checkpoint copies mutable account/live-order/alias/index/liquidity
and derived-cache state, not immutable market data or the full execution history.
The existing matching, fee, funding, margin, liquidation and lifecycle code runs
unchanged. Retry restores the pre-bar state; already committed bars cannot move.
Nested/skipped/stale transactions and incompatible static terminal capture fail
closed. Reset/close discard the checkpoint; errors cannot commit a partial bar.

The narrow private PyO3 `NativeFeedbackSessionCore` is constructed from the
existing typed execution template. Its typed fill/event columns preserve i64
identifiers, including values beyond exact f64 integer precision. This is not a
new Python accounting engine or a new public endpoint/API-version promotion.

`TransactionalTapeFeedback` opt-in uses the existing compiler's snapshot,
actual-fill feedback and stabilization loop, but advances one canonical native
session. Only the current bar is retried for added/changed protection. Appended
future commands do not replay the historical account. Unsupported extensions
reject the requested transaction capability; `replay_v1` remains an explicit
reference path. In the private binding, selection is `feedback_mode="transaction_v1"`;
no existing user notebook or default public endpoint is silently redirected.

Committed prefixes contain exact immutable account/lifecycle bytes plus the
referenced integer-ID/name pairs. Only the same native owner, matching stop and
the same certificate instance can reuse that prefix. Switching native owners
fails closed; different certificates/ordinary views use full field comparisons.
This is lossless sufficient-prefix reuse, not an approximate hash
or permission to reuse mutable accounts. Cold exports remain detached read-only
byte-backed arrays. Original decision checks and final audited execution remain.

## Matched Saved Controls

Same saved anchors, ETHUSDT 1h, 2020--2021 IS, 17,544 bars, original financial
configuration, original Mode 4 evaluator and metric witness. Both arms use the
already-qualified trial/account-path and exact full-IS reuse settings. The only
new comparison is full-tape feedback replay versus transactional feedback.
The separate final audit is outside the timed trial evaluation.

| Alpha | Replay median, s | Transaction median, s | Speedup | Replay peak RSS, MiB | Transaction peak RSS, MiB |
|---|---:|---:|---:|---:|---:|
| HMA | 32.755 | 16.551 | 1.98x | 444.74 | 443.69 |
| HASH | 3.991 | 3.213 | 1.24x | 419.94 | 429.24 |
| VWAP | 4.949 | 3.405 | 1.45x | 420.69 | 430.59 |

Two samples per arm, with ranges: HMA 32.460--33.049 / 16.457--16.645 s;
HASH 3.781--4.201 / 3.098--3.327 s; VWAP 4.478--5.419 / 3.318--3.492 s.
These are bounded whole-IS evaluations including compiler/output overhead, not
kernel-only times, whole-WFO forecasts, a p95 SLA or universal speedups. Some
controls overlapped another control/test and existing host services. The report
retains every sample and does not advertise a fully isolated serial ABBA run.

RSS is subprocess `ru_maxrss`, including imports, retained verification outputs
and the separate final audit, taking the larger repetition. HMA is approximately
flat; HASH/VWAP increase about 9--10 MiB (about 2.2--2.4%). The new prefix/session
ownership is not an across-the-board RSS win. Its allocation stays below the
registered 2-GiB process cap. Do not compare these absolute RSS values to another
harness that retains fewer verification outputs.

| Compiler | Prior full-tape runs | New sessions | New full-tape runs | New native bar steps | Same-bar re-steps |
|---|---:|---:|---:|---:|---:|
| HMA | 1,923 | 1 | 0 | 18,167 | 623 |
| HASH | 27 | 1 | 0 | 17,553 | 9 |
| VWAP | 113 | 1 | 0 | 17,558 | 14 |

HMA retains exactly 2,746 commands, 17,599 decision steps and 55 decision retries.
Logical compiler callbacks are not physical whole-tape executions. Native
same-bar re-steps also include command submission changes that do not require a
decision retry. Python strategy decisions still cross a per-bar boundary; this
is **not** one FFI call for an arbitrary reactive strategy. The final already
compiled command tape still executes through the normal native endpoint.

## Correctness

All 12 saved controls pass cold reconciliation across both arms/repetitions:

- Original objective and complete logical metrics/observations match exactly.
- Commands, decision-step/retry counts and decoded integer order IDs match.
- Every exported equity/position/fee/funding/turnover/margin path, event kind,
  status, rejection, target, fill quantity/price/fee/reason/ambiguity matches.
- An independent original final-audit execution reproduces equity, positions,
  fees and funding for every control. No alpha decision replay is used to invent
  an audit. Broader terminal and lifecycle fields are checked in the synthetic
  native differential corpus; those claims are not inferred from equity alone.

Disjoint focused shards: **63 Rust core tests**, **179 native/
compiler/lifecycle tests** and **119 private binding/guard/isolation unit tests**:
**361 passed**, no skips in these qualified shards. The 179 include 77 transaction
cases; reruns of those cases are not added to coverage. Tests cover clean versus
retry, initial bar, offsets, gap and same-bar SL/TP/OCO, partial ladder/residual,
amend/cancel/replace/expiry, stop-limit/IOC/FOK in both directions, funding,
margin/liquidation, reset/abort/close, malformed buffers, immutable prefixes and
foreign-certificate fallback. Private unit fixtures are not financial evidence.

The matched panel is bound to commit `b838d86`. The final guard in `ea96380`
additionally rejects switching native session owners between prefix views;
both same-name and different-name cross-owner negative tests pass. Its 179-case
regression covers the ordinary same-owner compiler. This does not change normal
accounting, commands or the hot-path algorithm. The original 12 control receipts
are retained under their original source pins, not relabelled as new runs.

An early synthetic protection fixture and an invocation missing the Cargo
workspace manifest failed and remain retained. Correcting the fixture's pending
entry timing did not change a financial rule. The first HMA transaction control
passed but took 23.127 s before immutable-prefix reuse; its source/result remain
historical, separate from the final matched panel. No sample was deleted.

## Artifact And Remaining Scope

One offline incremental local build produced the CPython 3.12 candidate:

```text
f74b5669dd6da58a80d292ad39b3ca150092b4775b7d0000459b37da2778ffbc
```

The original native SHA remains:

```text
2959f5388c6a8e57bdef5a6dafe76da3624ef57dba379f7ca686e9bf202ad26b
```

Private custody: `m5-11-6/attempt-01/transaction-v1`, including candidate/source
snapshots, registrations, failed/passing test logs, 12 control receipts and
`closeout-v3.json`. Its 426 source pins are checked before cold reconciliation.
`owner-guard-amendment.json` records the later targeted source change and test
without rewriting the matched panel's qualification. The Python feedback
projection remains a one-symbol research transport; its pre-existing rejection
of multiple same-order fills within one bar is not silently widened.
This is not an installed-wheel, manylinux, remote or public-release certificate.

SC keeps its already-qualified `event_driven` callback/cursor path; HMA/HASH/VWAP
keep `order_commands` and actual-fill semantics. Intrabar/vectorized execution
was not substituted for stateful gap/ladder/amendment behavior without parity.
Trial/final audit separation and exact deterministic duplicate-IS score reuse
remain as documented in the preceding pass.

The runtime fix is ready for the owner's bounded-launch decision. The long
57-fold research still needs a new prospective source/candidate registration,
then matured-meta/no-leakage, final continuous-account and R/Q measurements.
M5-11.7 and M5-12 are not started. No precise full-study ETA is inferred from
selected anchors. See [cleanup custody](../maintenance/M5_11_6_NATIVE_TRANSACTION_CLEANUP.md).

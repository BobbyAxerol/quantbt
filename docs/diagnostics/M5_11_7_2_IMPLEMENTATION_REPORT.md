# M5-11.7.2 Local Reporting Qualification

**Status:** COMPLETE_LOCAL_REGISTERED_REPORTING_SCOPE, 2026-10-18 UTC.
This is a source/readback qualification: REANALYZED_EXISTING_EVIDENCE and
DESCRIPTIVE_ONLY, not new economics, installed-wheel, remote or release proof.
Scope follows [the approved phase](../../upgrade/implement.md#mode5-m5-11-7-2),
[Mode 4 report rules](../../upgrade/QUANTBT_MODE4_META_LEARNER_RESEARCH_GUIDE_V1.md#mlr-r3)
and [Mode 5 report rules](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#78-rules-báo-cáo-áp-dụng-cho-mọi-phase).

## Product

The additive [ResearchDecisionReport API](FOLD_DECISION_REPORTS.md) reads original
typed observations, decision sidecars and witnessed evidence. Small modules
separate contracts, snapshots, validation, reductions, metadata adaptation and
rendering. Existing report defaults and endpoint signatures are unchanged.
The three original effect/opportunity reducers have one shared owner; their AST
bodies exactly match baseline `017b421`. The original Mode 5 `DecisionReport`
remains the owner of its scientific fields.

Available views include:

- Exact all-calendar, fallback, disabled, model-ready, proposed/applied-changed
  and registered cohort masks; missing slots stay in the roster.
- Signed D/R/Q/IS effects, own-metric masks and matched decomposition,
  help/harm/tie counts and magnitude, dispersion, quantiles and downside tails.
- Raw forward Sharpe separate from actual account return; original activity,
  exposure, DD and costs only when qualified source metrics exist, with units.
- Native/proposed/applied identity and parameters, clocks, model support,
  predictions, realized guard failures, ties, fallback, adjacent parameter
  turnover and retained execution-comparison witnesses.
- Acquired-label and selected prediction error; zero-Y and structural
  `Yhat=deltaIS` / `Qhat=0` losses on identical witnessed masks. These are error
  references, not new selected/executed policies. Y/Q errors are algebraically
  related and must not be presented as independent tests.
- Existing registered intervals only, fixed acquired-panel opportunity rather
  than full-pool regret, state/time attribution with its own permissions.
- Original continuous-account summaries with explicit result identity, units,
  exact calendar and matching/containing scope; no joining reset equity.
- Mode 5 fixed-dict, full-development objective/environment/probe views through
  its original reader, explicitly NOT_BACKDATABLE rather than causal OOS.

The normal WFO metadata adapter currently accepts Mode 4 / `per_fold_causal`
with retained typed observer revisions. It joins by task ID, not archive order.
Without those observations it fails explicitly, never executes an account or
fabricates counterfactual labels. Other convenience integration remains 11.7.3.

## Retained Evidence

Readback covers seven original Mode 4 families, **370 origin slots**, plus two
original continuous full-development Mode 5 decision snapshots. It imports the
eight retained native/active continuous accounts for the original four families.
No optimizer, financial research execution, model fitting or new bootstrap ran.

The table is the original registered four-operand paired mask, not every
calendar fold. Help/harm/tie is the sign of realized Q. Values are mean signed
raw-Sharpe differences, not percentage return or final account performance.

| Family | Calendar Slots | Paired | R | Q | IS Contribution | Help/Harm/Tie |
|---|---:|---:|---:|---:|---:|---|
| RSI | 28 | 15 | 3.131554 | 1.001062 | 2.130491 | 9/6/0 |
| SC | 57 | 20 | 0.964282 | 0.368399 | 0.595883 | 12/8/0 |
| HMA | 57 | 32 | 1.207537 | -0.607483 | 1.815020 | 13/19/0 |
| HASH | 57 | 32 | 1.928387 | 0.244878 | 1.683508 | 14/14/4 |
| VWAP | 57 | 11 | 1.647605 | -0.099803 | 1.747409 | 5/5/1 |
| N1 | 57 | 32 | 3.067949 | 1.158958 | 1.908991 | 22/10/0 |
| N2 | 57 | 24 | 1.783242 | -0.006975 | 1.790217 | 13/10/1 |

Original four-family ML-06 means reproduce exactly (maximum difference zero).
RSI all/supported masks reproduce within `4.44e-16`. N1/N2 reproduce the
retained ML-09 outcomes; this is not a fresh independent economic replication.
RSI uses its original 365D protocol, unlike the six monthly/730D families.
Their means are not pooled into a purported matched seven-alpha macro result.
Positive R with negative Q remains visible, with the IS contribution disclosed.

Original ML-06 interval policies and reserved family coordinates are preserved;
unsupported coordinates remain nonnumeric. The old raw/TPE Mode 5 research
control stays in its original inventory, not a fabricated diagnostics-first
decision snapshot. Five discovery dossiers, three existing formal RSI studies
and quarterly simplified variants retain their separate scope through the
[11.7.1 inventory](M5_11_7_1_IMPLEMENTATION_REPORT.md).

## Correctness And Rights

Final regression: **344 tests PASS**, 52.80 seconds. Coverage includes
hand-computable effects/control losses, own versus paired masks, undefined/flat
data, missing/partial calendars, native/shadow/active application, task-ID joins,
readiness and source cutoffs, future/state access denial, same-ID anomalies,
metric units/digests, account scope, original Mode 5 views and unchanged legacy
diagnostics. Copy/deepcopy/pickle/private JSON retain immutable identity;
tampered summaries, witnesses or masks fail. Public defaults redact private
params, source IDs and state labels. Existing synthetic integration fixtures
exercise their original toy engines; these are not new alpha research runs.

All **262 protected inputs** remain pinned, including financial/optimizer/metric/
backend/Rust owners, alpha sources, guides and the prior terminal receipt.
The frozen Ridge manifest still verifies **42 sources / 5 receipts**. Global RNG
states remain unchanged. Retained source failures stay failed: fixture import
setup, legacy partial-scope handling, an incorrect test anchor denominator and
archived RSI snapshot ordering were fixed without rewriting original data,
winner policies, economic gates or failed receipts.

## Measured Reporting Cost

Single observations on this host, not percentiles or comparative speedups:

| Synthetic Roster | Assembly | Private Full JSON | Public JSON |
|---|---:|---:|---:|
| 2 folds | 320.43 ms | 397,509 bytes | 253,131 bytes |
| 57 folds | 935.96 ms | 1,284,032 bytes | 465,415 bytes |

Source-proof process peak was **228.08 MiB**. The nine original-source readers
took **82.53 seconds** in serial, including imports/custody/adaptation/exports;
largest worker peak was **329.87 MiB**. Final-source projection from those sealed
payloads took **16.18 seconds**, peak **298.16 MiB**, without repeating finance,
history fitting or source study runs. Mode 5 assembly was approximately
1.69/1.71 seconds for the original TPE/CMA snapshots.

Latest scalar exports use deterministic gzip to avoid duplicating full matrices.
Original complete payloads and parent identities remain retained for reload;
compact/public summaries alone are not scientific reload snapshots. All workers
remain below 512 MiB; retained phase evidence is under 64 MiB. See the
[exact cleanup receipt](../maintenance/M5_11_7_2_CLEANUP.md).

## Exit And Remaining Boundaries

No blocking implementation gap remains in this registered cold-report scope.
Unretained per-candidate return/DD/cost/campaign fields stay explicitly missing;
a separate continuous account cannot fill reset diagnostic observations.
Source declarations are not authentication against a malicious producer.
Future methodology, learner/guard changes, new financial probes, wider endpoint
convenience accessors and installed artifacts require their own scope/approval.
M5-11.7.3 and M5-12 are not started. No push, CI, merge, tag or publication ran.

Private append-only qualification directory:
`upgrade/private/mode5_upgrade_v1/m5-11-7-2/attempt-01/`.
Current receipts are `terminal-qualification.json`, `exit-tests.xml`,
`current-source-proof.json`, `source-final-03-complete.json`,
`current-views-complete.json`, `operational-failures.json` and `cleanup.json`.
Exact reproduction starts with the retained original source pins and the
source-only `tools/qualify_decision_reporting.py`; the public
[synthetic example](../../examples/shared_decision_reporting.py) contains no
private strategy or economics source.

# M5-12 Installed Consumer Wiring

Status: wheel and sdist local consumer executions are complete and passing.
The [current summary](M5_12_LOCAL_QUALIFICATION_SUMMARY.md) and
[canonical report](M5_12_REPORT_R3.md) retain exact hashes and separate evidence
units. Phase status is TECHNICALLY_VALID within local scope after explicit owner
acceptance of the reconciled operational exceptions; final review remains.
Current local receipts, historical wiring and later remote qualification remain
separate. No default, workflow dispatch or publication is activated.

After separate admission, `tools.m5_12_installed_preflight --lane <cp-lane>`
consumes the existing `qms08_package --release-pair` proof and its `pair` and
`sdist` environments. It does not build or install. CI invokes it
after `qms_installed_execution`, which supplies pytest to those environments.
Default CI requires both kinds. Optional `--kind pair` or `--kind sdist` checks
only that existing environment and seals `installed-m5-12-<kind>-proof.json`
plus its matching directory. A single-kind receipt explicitly lists its kind,
`proof_scope=single_artifact_consumer` and `complete_pair=false`; it cannot
certify the pair. Callers may retire only reviewed terminal environments between
separately admitted installs; this tool neither installs nor removes them.
Current local M5-12 supplies `quantbt.m5_12.local_artifacts.v2`, verified by
the current source guard, exact packaging inputs and the approved fresh native
build receipt. The Python-only alias followup reuses that exact native build
after whole-Rust source/lock/config checks, not merely a version match.
The initial v1 ACC-reuse proof is historical after the parity repair.
This is not an old QMS installed certificate. A failed
consumer remains retained; `--attempt N` writes a fresh nonce and separate
append-only attempt without changing the 12-proposal cap.

| Required Feature | Bounded Public Synthetic Coverage |
|---|---|
| Shared diagnostics | Twelve fixed observations, rendering/identity, narrowed-rights rejection |
| Mode5 calibration | Cold compile/export/reload/prepare plus one bounded actual Mode4-to-Mode5 baseline/challenger execution, reconciled winner and explicitly applied fold-0 donor |
| Winner | Retained synthetic decision, exact dictionary, runner-up/risk/activity explanation, immutable reload, mismatch rejection |
| Donor | Explicit ordered coordinates, original validator, exact digest/current rights, no old scores or automatic ranking |
| ReportingV1 | Public fixed-signal example, endpoint/result read-only agreement, Python/Numba bankruptcy/ledger/drawdown groups |
| ACC accounts | Event/command/callback minimums, vectorized/package attribution, daily native-portfolio funding and executed liquidation/report-tamper controls |
| ACC options | Wallet mismatch/FX, fee currency/event clocks, margin buffer admission, unsupported nondefaults rejected |

The maintained roster is `tools/m5_12_consumer_matrix.py`: 44 cases, comprising
the original 41, one execution and two portfolio controls. Every selected
parametrization must complete setup/call/teardown successfully. Missing tests,
skips, xfails, collection drift and absent feature modules fail.
All 43 non-search cases forbid optimizer calls. Only the precisely named
`test_bounded_mode5_cross_mode_execution` call may run the staged public
`mode5_cross_mode_qualification.run_demo(..., donor_folds=(0,))` once.
Call-through wrappers cap actual `Study.ask` at 12. Four calls occur internally
inside the two Mode4 two-trial `Study.optimize` calls and eight are direct;
they are counted once, not as extra reserved slots. The protocol observes
twelve asks, four fresh studies, eight public tells
and three walk-forward runs, serially, without changing methodology or results.
Original summary counts must reconcile to exactly 12 proposals and at most 23
financial invocations, with actual donor application and reconciled winner/
baseline comparison. Missing/changed budgets, overruns and retries fail closed.
This is bounded operational coverage, not the complete ACC or M512.01..06 suite,
an open-ended study, economic superiority or independent OOS validation.

Only allowlisted, hashed public tests/examples and small harness files are staged
under a fresh external temporary directory. Examples are fixture code, never
represented as installed package modules. All QuantBT code is loaded from the
exact existing artifact environments using `-I`, a fresh bytecode location and
no checkout `PYTHONPATH`. Full canonical source/resource inventories must agree
across wheel, sdist and installed files. Resource reads, runtime/metadata pair,
loaded module paths and exact native extension bytes are checked before/after.
Before artifact qualification, `m5_12_source_guard.verify_current_source()` must
accept the committed extraction/current source tree. Its full provenance and
current commit are bound into requests/receipts and rechecked before sealing.
Financial source remains changed versus original QMS and source approval does
not qualify artifacts. QMS `verify_pair` additionally checks exact final staging
and native source identity, without using the old financial-unchanged validator.

Retained outputs: `installed-m5-12-proof.json`, the corresponding directory's
manifest, per-consumer JSON/XML/logs, scratch inventory, and CI preflight log.
The execution case records its actual retained summary/protocol, donor coordinates
and reconciliation through `record_property`; child and parent validate it.
Per-kind execution JSON and hashes retain those observations with measured
optimizer counters, rather than asserting that all optimizer calls were zero.
Fresh nonces bind child receipts to this invocation. Existing output or failed
scratch is rejected, never reused as PASS. Temporary harness/JIT/pytest scratch
is recorded for caller-reviewed cleanup; logs and artifact receipts are retained.
The Ubuntu 22.04/24.04 x CPython 3.11/3.12/3.13 matrix remains separately gated.

## Separate Pct And Alias Proof

`tools.m5_12_pct_installed --lane <cp-lane> --kind pair|sdist` executes19
additional cases from the current pct-equity and alias modules. It does not
change the44-case roster or its12-proposal budget. Pct controls cover accepted
quantities, rejected entry, ignored first bar, liquidation, score-only activity,
public WFO parity and the two supported spellings' activity-contract identity.
These cases contain their own bounded synthetic WFO calls, billed separately.

The tool accepts only the ordinary exact release-pair proof or current v2 local
provenance. It requires the accepted-quantity native capability, hashes all
loaded package/resources and the exact extension, requires19passed/zero skips,
and seals each artifact kind separately. An old same-version binary is not
accepted. Candidate CI is wired for both kinds; wiring is not a workflow run.

The full local matrix also includes the separate149-case intrabar/event proof,
eight integrated sampler/continuation/domain families, five external private
alpha mechanics controls and fresh-process report reconstruction. These are
different evidence units; do not add them into an economic sample count or
infer current certification from an older receipt.

The same bounded calibration case also checks copy/deepcopy/pickle4/pickle5
on actual baseline/challenger continuous account retention and direct two-column
margin snapshots. It preserves the44-case/12-proposal cap: no additional search
or financial execution. Missing or incomplete roundtrip telemetry is rejected.
The [snapshot repair](M5_12_SNAPSHOT_REPAIR.md) requires corrected V6 core
artifacts; the exact unchanged fresh native build is checked independently.

## Recorded V6 Local Results

| Evidence Unit | Wheel Consumer | Sdist Consumer |
| --- | ---: | ---: |
| Feature test cases | 44 passed, zero skips | 44 passed, zero skips |
| Intrabar/event test cases | 149 passed, zero skips | 149 passed, zero skips |
| Pct/alias test cases | 19 passed, zero skips | 19 passed, zero skips |
| Integrated consumer families | 8 complete | 8 complete |
| External private fixed-mechanics controls | 5 complete | 5 complete |
| Fresh-process representative report views | 4 reproduced | 4 reproduced |

Both actual absent-Optuna controls pass: fixed-account execution works without
the optional optimizer; requesting optimization raises the expected explicit
ImportError. These are real serial installations outside checkout using V6
core artifacts and the exact approved native extension, not source-path tests.
Each single-kind receipt still says complete_pair=false; the final handoff
reconciles both kinds rather than rewriting those receipts. Private controls
explicitly request Python and are not evidence of native strategy execution.
The four reproduced views do not mean twelve historical reports were rebuilt.
Both consumer environments are now retired; artifacts, logs and receipts remain.

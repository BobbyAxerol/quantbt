# M5-12 Installed Consumer Wiring

Status: implemented wiring, NOT_RUN. No artifact/platform/economic qualification
or M5-12 launch is asserted. No default, workflow, build or publication is activated.

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
Local M5-12 may instead supply `quantbt.m5_12.local_artifacts.v1`, verified by
the current source guard, exact packaging inputs and unchanged-Rust ACC native
artifact provenance. This is not an old QMS installed certificate. A failed
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

# QMS-C04 Report

## Source And Approved Scope

Phase entry `1a1f10d`; implementation scope/gates recorded first in `4016d24`.
The reviewed additive session implementation is `f3ab6cf`. The detailed guide
sections 4 and 6.9 remain unchanged. Financial Rust, sampler factory/math,
selection/accounting and public endpoints are unchanged. Prepared pair remains
**1.1.2 / 0.4.3**; no push, merge, tag, release or publication is authorized.

## Implementation

Read [the exact continuation contract and usage](EXACT_CONTINUATION.md).
Safe typed config, external binding/digest checks, ordered public-API event
reconstruction, proposal/pruning/final witnesses, duplicate and owned early-stop
state, barrier commits and POSIX atomic compare-and-swap are implemented.
Unsupported serializers fail explicitly. The module never invokes an evaluator
during restore and accepts no checkpoint pickle or Optuna storage system attrs.

## Tests And Evidence

Initial owned session/safety matrix: **96 PASS** with zero skips/errors. Includes
four-recipe fresh-process continuation, beyond-startup proposals, intermediate
Median pruning, COMPLETE/PRUNED/FAIL, ordered batches, warm-start/early-stop,
mixed/conditional supported spaces and CMA margin. Source guards remain exact
reviewed-byte gates, not expanded financial allowlists.

Final local gates PASS: **916 unique scoped checks, zero skips/errors**,
including **114 C04-specific**. Broad affected QMS/WFO/W3 regression886;
additional endpoint accounting4; evidence verifier8; release/package18.
The `%_equity` financial proof uses the existing shared report metric and actual
one-way fee/funding/slippage configuration. Objective/winner, equity/returns/
positions, metrics and order/fill/position reports remain exact. Monkeypatching
the endpoint to raise during restore proves accounting is not replayed.

Eight canonical/generated contract/API, architecture, benchmark, docs and
secret checks PASS. Ruff and whitespace checks PASS. The local
independent receipt `benchmarks/optimization/meta_selection/qms_c04_gate_receipt.json`
binds source, actual JUnit, artifact/log and raw cost digests. The added source
guard pins four exact reviewed new modules; older financial/math guards still
run and reject unapproved changes. No remote/public qualification is claimed.

## Installed Artifacts

Fresh source-exact core wheel and sdist consumers pass all four recipes with
`python -I`, site-packages imports, a new process at attempt23, continued
trial48 witnesses and COMPLETE/PRUNED/FAIL dispositions. The existing C02 native
wheel is reused: no financial Rust edit or unnecessary rebuild.

| Artifact | SHA-256 |
|---|---|
| Core 1.1.2 wheel | `7d3e8c329ab0c14f6303ed2efbf6ec895a0c0848a124511c7052a2bff681872e` |
| Core 1.1.2 sdist | `0af2c21c427280c3e2b94f9b220d1a230d5bfc071bbc1fa579eade297bca4552` |
| Reused native 0.4.3 CPython3.12/manylinux_2_34 wheel | `20a9a5116470ad0f385bdfe4ec902ea43ba580a6cdb208920caffda4b8d4ba7a` |

Ignored proof/log/JUnit bundles: `.maturin/qms08/c04-package-v1` and `c04-review`.
This is local Linux/CPython3.12 qualification, not the remote six-cell matrix or
public index proof. Installed binary identity and C02 transport consumers also
pass the reused package builder's original checks.

## Costs And Performance

[Raw retained costs](../../benchmarks/optimization/meta_selection/qms_c04_continuation_evidence.json)
use one warm-up + three retained runs/cell, seed731, one-thread numeric budget,
32/128 completed attempts and eight future-continuation checks. Same toy
numeric/pruner/constraint contract; no alpha backtest is timed. Local regression
and build work was concurrent: these are observed costs, not isolated SLAs.

| Recipe | History | Save + fsync (ms) | Restore (ms) | Journal bytes |
|---|---:|---:|---:|---:|
| Legacy TPE | 32 | 34.90 | 253.83 | 37,663 |
| Legacy TPE | 128 | 43.87 | 1,103.79 | 143,819 |
| TPE multivariate/group | 32 | 23.90 | 204.75 | 37,991 |
| TPE multivariate/group | 128 | 40.36 | 917.80 | 145,430 |
| CMA-ES | 32 | 20.10 | 148.52 | 38,061 |
| CMA-ES | 128 | 43.56 | 516.03 | 145,251 |
| Sobol | 32 | 32.66 | 177.35 | 38,163 |
| Sobol | 128 | 37.89 | 468.01 | 146,120 |

Replay is history-sized **sampler** work, not an O(1) RNG snapshot. Existing
endpoint loops pay no new continuation overhead because this session is opt-in.
No WFO speedup, RSS improvement, sampler superiority, decay reduction or new
scientific-method claim follows from these engineering fixtures.

## Review Corrections

Initial Median-pruner tests exposed a NumPy boolean at the JSON boundary;
the reviewed session now records a built-in boolean, and the full matrix passed.
The added financial test initially assumed V2-only fee/margin properties on the
legacy result; it was corrected to compare its actual account/report contract
and shared metric reader, without changing any engine. The initial docs check
found a link to a receipt not yet emitted; the final check uses the published
receipt path as a literal reference and passes. Failed initial logs/JUnit remain
in ignored local evidence; they are not included as passing certification.

Source tests do not depend on ignored VPS-specific package paths. Actual
installed-artifact proof is independently run and verified by the package gate,
while portable tests cover its fail-closed verifier and retained cost schema.

## Limits And Remaining Ledger

This closes the approved local C04 owned-session capability, not automatic
public WFO/W3/R3B checkpoint integration or arbitrary user strategy/account/model
state recovery. Exactness is under a matching pinned runtime and finite journal;
restore is history-sized sampler replay, not constant-cost state import.

Additional meta-mode activation/C01-D01 approval, carry/multi-symbol accounting,
public meta batch/deadline, C05 conditional Sobol/mixed centroid, current-source
remote matrix/public release and scientific acceptance remain separate items.
No scientific methodology, sampler superiority or improved decay is claimed.

# M5-11.6.1 Fast Variant Implementation And Admission

## Scope

Owner-approved continuation of the [quarterly phase](../../upgrade/implement.md#mode5-m5-11-6-1),
after the [original-route non-admission](M5_11_6_1_ADMISSION_REPORT.md).
The [named variant contract](M5_11_6_1_FAST_VARIANT_DESIGN.md) remains authoritative.
This receipt is operational admission, not a completed economic study or a
promotion of the original alphas. No public endpoint/default, original alpha,
M5-11.7, M5-12, CI or release is changed.

## Shared Architecture

- Existing `WalkForwardEngine` and shared sampler bridge produce each actual
  128-attempt IS pool. No cloned Optuna/WFO optimizer or account engine.
- Original feature code/bytecode uses isolated exact Numba/NumPy preparation.
  No alpha file/module-global mutation or mutable account/order-state reuse.
- The public native intrabar prepared runner executes fresh diagnostic
  accounts, one native execution call per account, no Python per-bar callbacks.
  Native and floor selectors observe the same IS account.
- Shared QMS owners retain separate sampler/anchor families, original Ridge
  mathematics, full-pool ranking and prospectively sealed observer unions.
- Saved schedules produce continuous final accounts plus independently rebuilt
  tape/account replay. Diagnostic equities are not concatenated. Original/variant
  lifecycle and terminal-phase differences remain explicit.

## Tests And Fixed Finance

| Component | Result |
|---|---:|
| Calendar, selector, admission, readback and policy contracts | 129 passed |
| Rust/Python/Numba same-contract intrabar accounting | 22 passed |
| Exact HMA preparation, including latest compiled ATR | 207 passed |
| Exact HASH/VWAP original-feature preparation | 209 passed |
| Exact SC preparation and prefix permissions | 117 passed |
| Private variant compiler and geometry | 43 passed |
| Registered quarterly R/Q reduction and inference | 39 passed |
| Latest helper-to-compiler integration | 4 passed |
| Original bridge helper unit contracts | 21 passed |

Five fixed public-WFO evaluator controls confirm one physical whole-IS account
when `is_subperiods=1`, objective/observation exactly matching direct evaluation.
These are not optimizer trials. A synthetic mature-history fixture separately
checks actual required Rust versus reference Ridge/rank with 12 origins per
family; selected IDs/ranking agree and coefficients meet existing NumericLimits.
The fixture is not economic evidence.

Eight preparation-inclusive IS controls per alpha span early/late 365D prefixes
and two saved activity cases. Forward and fixed-parameter long-account controls
are also retained. Post-optimization observations, fees, fill counts and final
equity agree exactly with prior same-variant controls; this is not original-alpha
equivalence.

The original bridge has **16 unique completed controls**, four per primary
alpha, using original callback/actual-feedback routes and full-path internal
checks. Prior HMA receipts supply existing scalars; missing canonical observations,
costs/fills/exposure require targeted runs, not new search. Original mark-only
and variant final-close flatten differ by design.

## Retained Failures

Initial wiring multiplied a 2,000 budget by `entry_size=2000`, requesting four
million notional and producing no fills. Controls remain retained with failed
admission. Correct wiring is budget 2,000 and dimensionless `entry_size=1`;
later controls check actual entry quantity times price against 2,000. No
optimizer consumed invalid controls.

The first bridge wrapper reimported an isolated original runtime twice in one
process; the external package was already loaded. The failed queue/interrupted
claims remain. A new one-case-per-process queue reuses the completed exact
control and supplies missing controls. No seed-based WFO recovery/buffer repair.

One SC test initially compared a future global first-seed index with the
prefix-only scalar. Its failed receipt remains. The corrected causal assertion
projects the scalar to the permitted prefix and compares all historical arrays
exactly; no financial logic changed.

## Whole-Work Admission

Work remains **21,888 proposal slots**, with nine independent sampler streams,
chronological/sequential internally. Up to four streams run concurrently with
one numeric thread each. Eight policy decisions do not mean eight optimizers.

The measured maximum-cost model includes eight controls, forward unions up to
36/18 candidates, bounded prefix probes, per-fold cold allowance, independently
compiled final schedule replay, setup and 25% contention/unmeasured overhead.
Initial SC/HMA/RSI JIT/loading is charged once **per fold**, not discarded or
charged on every candidate. Other control maxima remain charged per evaluation.
Scheduling models indivisible streams, not only ideal division by four.

Forecast: **4,878.86 seconds / 81.31 minutes**, below the 90-minute financial
queue cap. This small-control conditional model is not p95, a hard bound or a
completion promise. Cap/resource stops retain completed finance before rendering.

Limits: aggregate owned RSS 3 GiB, host available RAM 512 MiB, retained evidence
512 MiB, scratch 64 MiB, free disk 5 GiB beyond remaining forecast. The completed
bridge queue used about 1.64 GiB aggregate peak RSS. All sources, data, failed
receipts and current native environment remain; no new build/environment or
unrelated service stop occurred.

## Remaining Work

Execute admitted studies; verify actual decisions/no-leakage at stored
checkpoints; reconcile continuous saved-schedule accounts; reduce quarterly
contrasts and issue the component decision matrix. Negative/unsupported
economics does not authorize retuning. Quarterly meta permits at most six
actually learned decisions under current maturity/publication policy, not a
new general mature-meta economic promotion.

Source-bound private registrations, XML, controls and account evidence remain
under ignored `upgrade/private/mode5_upgrade_v1/m5-11-6-1/fast-v1`.
Alpha source, private predicates/ranges and market rows stay out of Git/package/
public reports. A terminal cleanup/hash receipt is required before phase exit.

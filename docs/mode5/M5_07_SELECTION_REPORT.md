# M5-07 Objectives And Selectors

## Scope

Owner-approved, local research implementation of the [M5-07 plan](../../upgrade/implement.md#mode5-m5-07)
and [detailed guide](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#phase-m5-07--canonical-objectives-four-selectors-và-formula-migration).
Three objective families, four selector slots and non-destructive migration.
No alpha optimization, new market simulation, public activation or release.

## Contracts And Changes

Read [Selection Contract V1](SELECTION_CONTRACT_V1.md). Small modules own typed
contracts, formula inventory, components, geometry handoff, Pareto reduction,
advisory governance, pure selection and immutable observation migration.
Shared M5-03 tails/reference and M5-06 geometry are reused; local downside now
has one canonical owner. Public financial/source files are not changed.

Intentional new versions distinguish quantile replay, exact lower tail and
true finite-panel maximum regret. Old objective values and decisions are never
updated in place. Public Mode 4/5 behavior stays unchanged; public selectors
remain an M5-10 task, not functionality advertised from these research tools.

## Acceptance Matrix

| Requirement | Executed control |
|---|---|
| M5T-061 | Frozen weighted average-regret identity versus floor plus mean minus common constant |
| M5T-062 | Moving reference or mixed-row version blocked; entire completed panel revised append-only |
| M5T-063 | Toy panel selects different candidates for floor and true max regret |
| M5T-064 | 0.6775 linear Q25 versus 0.01 lower-tail mass; unequal weights/fractional atom = 6 |
| M5T-065 | Gamma one equals observed center/probe minimum; failed probes cannot be removed |
| M5T-066 | +100 shift leaves absolute/frozen-reference downside unchanged |
| M5T-067 | PSR/raw-return/dollar unit mismatch rejected; explicit net utility has no second fee deduction |
| M5T-068 | Fixed directions, zero range, unknown environments, extrapolation and dominated-outlier stability |
| M5T-069 | QMC plus Pareto stays post-selection; generation provenance is separate |
| M5T-070 | Medoid 2 versus nearest mean 3; centroid 21.2 needs an actual evaluation |

Additional controls cover immature/holdout evidence, equal-weight legacy replay,
weighted-MAD tie differences, infeasible/risk/all-bad/no-support candidates,
incumbent margins, advisory override/dossier identity, immutable copying,
schema/covariance bridge, large finite weights and signed-drawdown rejection.
NumPy components/fronts are checked against independent scalar Python oracles.

## Evidence And Performance

Final numeric/source gates pass in the private `m5-07/attempt-01` lane:
**1,198 related tests**, including **65 new M5-07 tests**, no failures/errors/
skips; **25/25 guide math oracles**. Five warnings are the existing three Optuna
experimental warnings and two legacy plotting `tight_layout` warnings. The
scoped regression covers prior M5 phases, reporting/cache, native prepared
boundary/full-tape accounting, public privacy gates and legacy Mode 4/5/WFO
schedule/plot behavior. It is not a claim that the entire repository suite ran.

Recorded entry points reuse `.maturin/qms08/release-regression-v1/bin/python`
with `PYTHONPATH=src:.`, one worker/thread and bytecode disabled:

```bash
python upgrade/local/mode5_upgrade_v1/m5-07/attempt-01/check.py contracts contracts-audit-final
python upgrade/local/mode5_upgrade_v1/m5-07/attempt-01/check.py regression regression-final
python upgrade/local/mode5_upgrade_v1/m5-07/attempt-01/check.py guide guide-01
M5_M07_FINGERPRINTS=uncached python upgrade/local/mode5_upgrade_v1/m5-07/attempt-01/check.py benchmark benchmark-audit-uncached
python upgrade/local/mode5_upgrade_v1/m5-07/attempt-01/check.py benchmark benchmark-audit-cached
```

The receipt records the actual absolute interpreter/bootstrap command; `python`
above means that controlled interpreter, not a system Python install. Receipt
names are append-only; reruns need fresh names. Private helpers and historical
records stay outside Git and distributions.

Final matched panel: **128 synthetic candidates x 12 environments**, seed 731,
25 repeats plus one warm-up per workload, same channels/preferences/gates and
full requested audit. Cached/uncached decisions are equal byte-for-byte including
hashes; no numerical tolerance was needed for this optimization. This table is
generated from the two source-bound benchmark JSONs:

| Workload | Uncached P50 ms | Cached P50 ms | Cached P95 ms | P50 Ratio |
|---|---:|---:|---:|---:|
| Canonical Components | 49.780 | 40.240 | 42.752 | 1.24x |
| full_alpha_adaptive_invariant | 188.433 | 122.560 | 133.772 | 1.54x |
| full_dro_cvar | 186.600 | 118.562 | 129.797 | 1.57x |
| full_pareto_chebyshev | 149.018 | 78.829 | 81.163 | 1.89x |
| full_sam_basin | 226.199 | 113.759 | 124.837 | 1.99x |
| Typed Input Preparation | 95.592 | 38.469 | 40.004 | 2.48x |
| Objective And Gates | 61.195 | 55.909 | 62.219 | 1.09x |
| Scalar Oracle Components | 4.575 | 5.691 | 5.849 | 0.80x |

Full selector costs fall **1.54-1.99x** through immutable fingerprint reuse.
The unguarded scalar oracle is still faster than canonical components; it does
not perform their typed validation/provenance work and is not a drop-in public
runtime. Its observed ratio is noise/context, not an optimized algorithm or a
favorable speedup claim. These timings exclude execution/search and are not
WFO, Rust-kernel or per-trial speedup evidence.

Peak process RSS: **218.17 MiB uncached / 215.87 MiB cached**.
This is one fresh process per mode, includes imported libraries and does not
certify an incremental-memory or plateau improvement. Actual Numba threads=1;
core source **1.1.2**, tooling metadata **1.1.1**, installed native **0.4.3**
are explicitly distinguished. The actual native binary hash is retained;
there is no new installed-wheel/native certificate or compilation claim.

**Exit: COMPLETE_LOCAL_OBJECTIVES / MATHEMATICAL_ONLY.** Host review, source
checks and exact scratch cleanup PASS. **1,359 protected hashes / 21 current
source-harness hashes** verified; full matched benchmark decisions are equal.
No scoped implementation blocker remains. Read the
[source-bound seal](evidence/m5-07.json) and
[cleanup receipt](../maintenance/M5_07_CLEANUP.md).

The tested implementation head is `45f5a5a`; documentation/seal commits follow
without changing that numeric source. Native binary and financial/core source
are unchanged. Scientific market comparisons remain unperformed in this phase;
economic input tranches belong to M5-08/11. M5-08 has not started and needs
separate approval; public activation is M5-10. No rebuild/install, push/CI,
merge, tag, version change or publication occurred.

## Validity And Handoff

Arrays prove mathematical identities and guard behavior, not profitability,
decay improvement or superiority on five alphas. Five-alpha market paths and
T1/T2 remain protected; incomplete historical winner-only panels are not new
selector qualification. The next approved empirical battery must register
missing panels/probes, sufficient horizon and campaign support before outcomes.
No costs/accounting/RNG/strategy/financial source or parameter ranges are silently changed.

Initial failures are retained: advisory dossier changed the decision but not
the selection key; finite weight scaling invalidated a tail; signed legacy MDD
was accepted by net economic utility. Focused fail-before/pass-after receipts
record fixes. These are research-policy/handoff repairs, not financial engine
or scientific estimator changes. A later failed fixture incorrectly expected
direct and advisory plans to have the same plan ID; its expectation was corrected
to assert equal numeric components and distinct provenance. That failed receipt
also remains intact. All historical phase receipts remain unchanged.

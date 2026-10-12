# M5-11.1 Native Fixed-Panel Batteries

## Scope

This checkpoint implements source-bound, cold B1/B3 reductions using the shared
Mode 5 selectors and statistical authorities. It consumes all 128 discovery
accounts for each of HMA, HASH and VWAP, with 2020 preload and continuous
2021-2023 accounting. No financial simulation, alpha import or optimizer runs.
The [ordered plan](../../upgrade/implement.md#mode5-m5-11-ordered-execution-20261012)
and [guide section 4.9](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử)
govern the separate selector-only, sampler-only and whole-procedure comparisons.

## Actual Results

| Panel | Discovery Accounts | Common Annual-Eligible | Annual Floor/Tail/Pareto |
|---|---:|---:|---|
| HMA | 128 | 0 | NO_SUPPORTED_CONFIGURATION_ON_REGISTERED_PANEL |
| HASH | 128 | 0 | NO_SUPPORTED_CONFIGURATION_ON_REGISTERED_PANEL |
| VWAP | 128 | 0 | NO_SUPPORTED_CONFIGURATION_ON_REGISTERED_PANEL |

The original gates are unchanged: full daily support, drawdown at most 0.5,
strictly positive registered utility, and eligibility in all three years.
Finite whole-path raw-Sharpe selection is reported separately. A profitable
whole account does not imply passage of this common-annual mandate. Conversely,
failure of the mandate is not a conclusion that an alpha has no edge.

The reducer records canonical decisions/components, kept-environment-only
leave-out decisions with held gates disclosed afterward, fixed Pareto preferences,
and measured environment rank/regret/near-optimal membership. Shared annual views
are dependent observations of one account, not independent replications.

All 18 matrix containers verify. Their unavailable cells retain explicit masks:
container verification is not complete empirical coverage. B2 awaits admitted
selection/held probe views; bounded whole-path centers do not authorize annual
local robustness. B4 temporal transfer and B5 actual sampler response are NOT_RUN.
No recipe is automatically promoted and no deployment is authorized.

## Verification And Custody

The current reducer/test sources have SHA256:

```text
native_batteries.py       14defff949e089be2fb9cedb2d7ff1e6d47cf9d97d4eb1d0e3c32ef5d53c9f43
test_native_batteries.py  4a0d63f9822a6b86f1f2d8b91a8deda3255b15e6b1eb840a531ef3e67625b194
```

Software-03 passes all 29 tests in 324.64 seconds (controller 326.583 seconds).
Software-04 is only a focused one-test check, with 28 deselected; it does not
replace the full suite. Earlier failures remain retained.

The actual cold-01 reduction takes 227.506 seconds, peaks at 780.30 MiB and
retains 36,468,529 bytes, below its preregistered 600-second/64-MiB limits. All
owned workers are reaped and protected source pins remain unchanged. Only the
registered inactive test scratch is removed; no financial output, environment,
artifact or evidence is deleted. Concurrent financial-worker writes mean the
filesystem delta is not claimed as net cleanup savings.

Private receipt hashes, without publishing alpha code or parameters:

```text
software-03/tests.json     ec8d2ef5c45de6b798af25fb482e2e512dba1182f5dd55a980870f05d147cfe9
cold-01/registration.json d5fea1647e11eb70f10f099ea5ffb9aa2aabd243db8513ae655c40307725acf2
cold-01/summary.json      d63a94486c66949809ffc855233292fc66faaa8469d62702a07201e9f1f6633d
cold-01/cleanup.json      0b81f6e6b75564d71ace23cedbf085b5ccd951cc57ce3f2ce804df40264d7ccc
```

The private lane is `upgrade/local/mode5_upgrade_v1/m5-11-1/native-batteries01`.
This is local scientific/technical evidence, not an installed-package, remote,
independent-forward or release certificate.

## Probe Integration Checkpoint

All 348 native probes and 1,392 dependent views are now source-admitted, without
repeating finance. Actual dossier assembly still exposes a consumer mismatch:
net return, drawdown and utility carry bar sample counts; Sharpe and daily ES
carry daily sample counts. The battery consumer currently requires days for
all five, so assembly correctly remains incomplete rather than rewriting the
stored observations. This is input-schema integration, not a financial parity
failure or evidence that the alpha lacks edge. Focused sample-unit tests and a
source-qualified consumer correction are registered in the unified plan.

The first cold attempt also included a superseded sample receipt; the corrected
controller selects the exact admitted sample03 and preserves the old failure.
Both attempts are closed, original sources unchanged, zero financial execution
and no disposable scratch created/deleted. Actual B2/dossier gate remains open.

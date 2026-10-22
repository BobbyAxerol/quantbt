# M5-11.1 Native Fixed-Panel Batteries

## Scope

This report retains the original source-bound, cold B1/B3 checkpoint using the shared
Mode 5 selectors and statistical authorities. It consumes all 128 discovery
accounts for each of HMA, HASH and VWAP, with 2020 preload and continuous
2021-2023 accounting. The [current closure](#current-b2-and-dossier-closure)
also integrates their 348 retained probes into B2 and rebuilt bounded dossiers.
No financial simulation, alpha import or optimizer runs during these cold steps.
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

At the original B1/B3 checkpoint, all 18 matrix containers verify. Their
unavailable cells retain explicit masks: container verification is not complete
empirical coverage. B2 then awaited admitted
selection/held probe views; bounded whole-path centers do not authorize annual
local robustness. B4 temporal transfer and B5 actual sampler response are NOT_RUN.
No recipe is automatically promoted and no deployment is authorized.

## Historical Verification And Custody

The original B1/B3 checkpoint reducer/test sources have SHA256:

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

## Retained Probe Integration Failure

All 348 native probes and 1,392 dependent views are now source-admitted, without
repeating finance. The original dossier assembly exposed a consumer mismatch:
net return, drawdown and utility carry bar sample counts; Sharpe and daily ES
carry daily sample counts. That consumer required days for
all five, so assembly correctly remained incomplete rather than rewriting the
stored observations. This is input-schema integration, not a financial parity
failure or evidence that the alpha lacks edge. Focused sample-unit tests and a
source-qualified consumer correction were registered in the unified plan.

The first cold attempt also included a superseded sample receipt; the corrected
controller selects the exact admitted sample03 and preserves the old failure.
Both attempts are closed, original sources unchanged, zero financial execution
and no disposable scratch created/deleted. Those failures remain historical;
the corrected gate is recorded below, without relabelling them PASS.

## Current B2 And Dossier Closure

The count-only consumer correction follows [guide 5.1](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#51-metriccontract-trước-công-thức-tối-ưu)
and the [registered cold closure](../../upgrade/implement.md#mode5-two-gap-cold-closure).
It accepts the observation counts already produced by the admitted reader:

| Existing Metric | Observation Count | Whole 2021-2023 | Each Annual View |
|---|---|---:|---:|
| Net return, drawdown, economic utility | Actual hourly account bars | 26,280 | 8,760 |
| Sharpe, daily loss ES | UTC calendar daily observations | 1,095 | 365 |

Stored metrics, their values and original files are not rewritten. This is the
existing reader contract, not a universal change to utility definitions. The
365-day support and original utility/risk gates remain unchanged. Selection
and held probes retain separate rights; no annual-local authorization is added.

The 29 inherited fixtures and 42 bar/day/role cases pass: **71 tests**, 523.78
seconds pytest / 524.785 controller seconds, 230.875-MiB peak RSS. The first
revision retains its three fixture/harness failures and 68 passing cases.
The correction uses canonical JSON records for tuple/list comparison and the
original cold deny-import harness; it does not remove an assertion or relax a
metric gate. Its underestimated scratch budget is recorded rather than hidden;
the successful revision preregisters and enforces 512 MiB.

All three actual cold assemblies and dossier verifications PASS:

| Alpha | Reused Probes | Dependent Views | Selection / Held | Matrices | B2 | Local Decision | Controller Seconds | Peak MiB |
|---|---:|---:|---:|---:|---|---|---:|---:|
| HMA | 132 | 528 | 65 / 67 | 6 | MEASURED_BOUNDED_LOCAL | NO_SELECTION | 217.450 | 998.828 |
| HASH | 112 | 448 | 56 / 56 | 6 | MEASURED_BOUNDED_LOCAL | NO_SELECTION | 183.316 | 943.586 |
| VWAP | 104 | 416 | 52 / 52 | 6 | MEASURED_BOUNDED_LOCAL | NO_SELECTION | 173.718 | 937.027 |

B1/B3, their first three recipe assessments, raw-Sharpe control and preferences
match the previous qualified results exactly. Zero common annual-eligible
configurations and the nonquality-center decisions are retained, not rescued by
new thresholds. These mandate-specific results do not conclude the alphas have
no edge. All six matrix types retain their explicit unavailable-cell masks.
Annual-local is NOT_AUTHORIZED; whole-128 local is NOT_EVALUABLE; B4/B5 remain
NOT_RUN. This closes technical integration, not independent forward economics.

An independent stdlib-only readback checks the recovered challenger chain,
unit backing evidence, all 1,392 exported view records against their original
source files, unchanged B1/B3 and all 18 exported inventories/status/mask counts.
It PASSes 1,787 input pins in 8.197 seconds / 415.355-MiB peak. No account,
trial, RNG draw or financial runtime is executed. All timings above are cold
verification costs, not financial throughput or sampler improvement claims.

### Current Receipts

```text
native_batteries.py       6b0ec4dfe77767f12802192500de135d0fd2ad4c267399240999071a557a4e27
unit-closure02/result     ae55dffd3246f11971a1f25c52c217d91db71b0603533e5a164dad3e4ec8ace7
unit-closure02/cleanup    e7b9bac462a3e8097222c6a2d432f1c2adfa4379b7c54ea4c0e40246065c446c
controller-HMA03/result  af57a3bedf336e1ec230851c12e18f8e316cbeaa835a4de2bf637224d75846d9
controller-HASH01/result 196c938d0d6d3f58154dd59936034ae78c18fb56abc1079ddd2a9ce772478818
controller-VWAP01/result e531df48b0c2db02297e3e3fe304c0c068033ef077f191f63c23e102bb038cf7
HMA03/dossier             e98120c70c9acf9336a7ceee5f7dbbb10f97e2898d88a3e71966599759c9d313
HASH01/dossier            d0fa033872a2a7205e66492a6cc324beef30fb92547fcfe576d93de5309db6f8
VWAP01/dossier            1a7b15075f0178f80de631b5edd1ad70ccac27fc31d06df82ae193ece7c94f8c
cold-closeout01/result    6d144915988e5340a312983c8d265636a6a97dcaee4aa42400db32dfed23598c
cold-closeout01/cleanup   662cdde8dba383e40c0bd230ddfb3aa578871cc93289877eb1cd9440d13bcbe3
```

The private dossier lane is
`upgrade/local/mode5_upgrade_v1/m5-11-1/native-dossier-software01`;
the final readback is `m5-11-1/cold-closeout01`. All workers are reaped,
source/artifact hashes verify and every cleanup PASSes. Only registered inactive
pytest scratch is removed; original/failed evidence, source snapshots and
current tooling remain. Dossiers retain 163,162,614 bytes before terminal
receipts. Final free disk is 18,370,412,544 bytes, not a net-cleanup-savings claim.
No build, installed-artifact qualification, CI, push or publication occurs here.

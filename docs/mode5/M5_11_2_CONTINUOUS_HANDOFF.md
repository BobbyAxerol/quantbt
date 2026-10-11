# M5-11.2 Continuous Account Handoff

Status: **PASS_COLD_SOURCE_BOUND_HANDOFF / PUBLIC_PROVIDER_NOT_BOUND**.
Authority: [continuous handoff entry](../../upgrade/implement.md#mode5-m5-11-1),
[shared diagnostic contracts](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#74-core-evidence-schemas)
and [separate comparison levels](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử).

## Qualified Scope

A focused, ignored cold adapter prepares typed immutable requests and validates
caller-supplied retained views. It does not call a financial provider, change
the public V1 binding, or execute an optimizer. Original accounts, source,
geometry, metrics, preferences and active native workers remain unchanged.

The actual population is **256 original parent accounts: 128 RSI and 128 SC**.
Every parent contributes its whole 2021-2023 development path and the three
annual views, for **1,024 source-bound views**. Preload remains 2020. Annual
attribution is dependent reuse of one parent account, not annual account resets
or independent economic replications. All original candidates are included,
not only winners, eligible candidates or favorable paths.

Requests retain original raw/effective candidate and geometry identities,
source/request/path pins, clock/economics references, initial state, available
terminal metadata and actual returned-work fields. The original execution ID
remains opaque: unavailable ExecutionKey fields are not reconstructed. A typed
delivery must match the exact ordered source roster, parent and permissions.

The whole path and first annual view retain original initial capital; subsequent
annual views retain the prior actual close. Carried-watermark provenance is
separate and bound to the same account/path before the view starts. Admission
checks the sealed attribution, not a new numerical reconstruction of the path.
The whole view keeps `continuous_account`; annual views keep `annual_anchor`.
Both retain `CONTINUOUS_PATH_ATTRIBUTION`. Neither family name is an engine switch.

Preload, data cutoff, artifact readiness and current knowledge remain distinct.
Existing AccessPolicy/AccessWitness govern reviewed development access; stored
identity alone grants no permission. Held local-validation evidence cannot be
used for selection. Undefined metrics, unavailable RSI fill/campaign ledgers,
SC no-trade rows and negative results stay unchanged, without favorable filling.

## Verification

The first registered run failed four fixtures because it incorrectly required
`continuous_account` for annual rows. Its source, FAIL, logs and cleanup are
retained. A fresh revision binds the exact original environment family instead
of changing the old rows or accepting arbitrary reset semantics.

The corrected revision passes **35 focused cold tests**, including all 256
parent/1,024-view admissions, omitted/reordered rosters, wrong candidate/branch,
source/path, clock/economics, baseline/watermark, reset, cutoff and role faults.
Deepcopy, pickle and exported mutable-copy checks retain immutable identities.
Tests distinguish semantic rejection from merely detecting a changed outer hash.
There is no financial, numeric, sampler or RNG runtime import.

Main read-only review independently reconciles every original row pointer,
canonical row/request digest, candidate roster, family, parent/path and prior
valuation binding. **1,962 unique pins covering 202,441,104 bytes** verify
unchanged. Both full 128-point rosters are present. This review does not repeat
the financial execution or recompute numerical attribution from raw arrays.

Cold preparation/tests take **28.203 s**, peak RSS **143.746 MiB**. Main read-only
verification takes **2.994 s**. These are metadata/custody measurements, not
backtest or search benchmarks. Cleanup/reserve PASS: the corrected lane retains
5,561,881 bytes before its cleanup receipt, zero scratch and zero deletion,
within the registered 64-MiB retained/32-MiB scratch budget and 5-GiB reserve.
Prior failures, private inputs, exact artifacts and live environments remain.

The separately registered final supplement regenerates all 256 requests and
1,024 source views, then checks **512 delivery deepcopy/pickle round trips**
and mutable-export isolation. PASS in 16.247 s, without finance, sampler or RNG
calls. This supplements the 35 focused cases; it is not 512 new economic tests.
Final combined owned source/evidence is 6,206,227 bytes before final receipts,
within the unchanged 64-MiB budget; cleanup PASS, zero scratch/deletion.
Main verifies the final handoff and **1,968 unique pins / 202,973,435 bytes** in
1.296 s. The earlier 1,962-pin review remains its own historical scope.

| Corrected Artifact | SHA256 |
| --- | --- |
| Registration | `c2f6a633ddedee6020ba3fdd65a6c2ce359bf4dc96b7c2d237d15592bfec46c4` |
| Tests | `c33f48dcb11370fc2b590f3a68d1148618cb78b9dc6d30a8c9f8949ae94d8ec3` |
| Bundles | `c4bf09b387cfb1a5d8014dca05faaae8741df9e3a5c383d4b7da9e724cdef8ce` |
| Receipt | `fba5295d7e96249831d74b55395cf9b63827fc7a0a45a55de9b0777f5d182cd7` |
| Cleanup | `a6e12ebfcc59dd2c6d5e462eea464a949d45626c3537839067bf78bd36d38be9` |
| Final Handoff | `02dd58fd955f77493354cae650de2ed024fe5b4a726ea1fd66e80e8445523e66` |
| Final Verification | `1d543b73c1a0cdbd028eb55c7a5d588ed4e19ff0aa87024855b5f81383dfe5d3` |
| Final Cleanup | `3a8020c9122f26b758f749c786edd805dcabfffd257e152088981c0fa7c4010a` |

## Remaining Integration

This closes only cold source-bound delivery/admission. The original public V1
environment-reset contract remains unchanged. **Actual continuous financial
provider dispatch, raw whole-account Sharpe channel, adaptive ask/tell, original
effective/probe geometry, selected audit and prefix integration remain NOT_BOUND
or NOT_RUN.** No sealed CalibrationPlan or generated trial is claimed here.

The remaining three broad native panels, coverage-backed five-alpha dossiers,
matched sampler experiments, real 256-attempt baseline/challenger studies and
prefix-rebuilt forward economics still follow their registered gates. No
deployment, publication, account ownership transfer, cache or memory-lifetime
qualification is authorized by these cold immutable records.

The subsequent [continuous measurement proof](M5_11_2_CONTINUOUS_MEASUREMENT.md)
reduces the actual retained RSI/SC snapshots: 37 focused tests, 256 parents,
1,024 views and 45,056 exact field comparisons against pinned oracle/rows.
It exposes genuine whole-account Sharpe and preserves carried annual attribution.
This adds bounded numerical qualification; public provider/raw-Sharpe registry,
actual adaptive studies and shared storage source activation remain separate.
The shared snapshot prerequisite has subsequently closed in the
[actual source regression](M5_11_1_SNAPSHOT_STORAGE_STAGE.md#shared-source-closure).
Other public/provider/study gates remain open; the old handoff is not rewritten.

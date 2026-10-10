# M5-11.1 Selector-Only Checkpoint

Status: **COLD_REPLAY_COMPLETE / LOCAL_SCOPE_INCOMPLETE**. This bounded step-1
sidecar uses existing SHA-sealed development evidence. It launches no financial
work, optimizer, build, install or forward study. It does not close the ordered
full goal or authorize deployment, publication, push or release.

Authority: [ordered goal closure](../../upgrade/implement.md#mode5-m5-11-goal-closure),
[guide 4.5](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#45-trục-2--parameter-geometry-và-landscape),
[guide 4.9](../../upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md#49-multi-hypothesis-empirical-battery-giữ-năm-chiều-làm-rõ-mỗi-phép-thử),
guide chapters 5/6, and the [economics checkpoint](M5_11_1_ECONOMICS_CHECKPOINT.md).
Existing receipts and raw-Sharpe/floor/tail/Pareto results remain unchanged.

## Decisions

Each alpha retains its original 128 effective candidates and continuous
2021-2023 account, with 2020 preload. RSI is ETHUSDT; SC is BTCUSDT on the
original Python callback route. Different allocation/contracts forbid a
cross-alpha performance ranking. Annual views do not reset accounts.

| Recipe | Candidate Scope | RSI Original Index | SC Original Index |
| --- | --- | --- | --- |
| Raw whole-path Sharpe control | Original 128, defined Sharpe, unqualified | 10 | 33 |
| Annual floor + mean | Original 128, unchanged annual gates | 56 | NO_SELECTION |
| Annual lower-tail | Original 128, unchanged annual gates | 49 | NO_SELECTION |
| Annual Pareto/Chebyshev | Original 128, unchanged annual gates/front | 56 | NO_SELECTION |
| Whole-path local downside | Two registered centers only per alpha | NO_SELECTION | NO_SELECTION |

Frozen utility is net return minus MDD minus daily loss ES; actual costs are
already in net return. Annual gates remain DD <= 0.5, U > 0 and days >= 365.
Floor coefficient for mean is 0.25; tail coefficients are 1/0.5/0.2 with
alpha 0.25; Pareto ideal/worst are 0.25/-0.25, equal weights, rho 0.01,
and allow-and-report extrapolation. Ties use candidate-ID lexicographic order;
activity penalty/minimum improvement are zero, with no incumbent override.
With three equal-weight annual environments, the lower-tail term equals the
minimum. SC's eligible Pareto front is empty, not meaningful null agreement.
All original LORO decisions, held losses, failed gates and undefined/no-trade
metrics remain in the private output. The pooled utility winner is not the
raw-Sharpe control. No statistical superiority or chronological transfer claim.

## Limited Local

The additive local recipe is `local_downside_v1`, gamma 1, no activity penalty,
and the original whole-1095-day decimal-return reference with scale 1.
Center and probes use the same whole-path utility, not an annual aggregate.
The score reconciles with min(center, selection probes). The original
all-probe quality policy (U >= 0), plus unchanged DD/day gates, rejects every
registered center. Rejected numerical scores remain visible:

| Alpha / Center Index | Selection Probes | F_max | Local Score | Covariance |
| --- | ---: | ---: | ---: | --- |
| RSI / 56 | 29 | 1.958797299 | -0.273983524 | Explicit sparse-cloud schema-only |
| RSI / 66 | 47 | 0.847500562 | -0.198963145 | Supported regularized proposals |
| SC / 103 | 14 | 0.206695031 | -0.086211976 | Supported regularized proposals |
| SC / 62 | 15 | 0.043293780 | -0.001133563 | Supported regularized proposals |

These are actual evaluated centers, not invented centroids or certified basin
representatives. Selection uses `selection_probe` only; `local_validation`
metrics are appended after the decision. READY-coordinate overlap is 42 for
RSI and 13 for SC; distinct held coordinates are 37 and 16 respectively.
Producer support counts also include center/alias points and remain separately
reported. Overlaps are dependent repeatability checks; neither held tranche
is temporal OOS. Covariance is not a Hessian. Coverage, clipping, infeasible
and duplicate proposals are retained, not counted as new executions.

## Missing Evidence

The private request manifest does not authorize execution:

- **Annual probe views:** 465 RSI and 174 SC role-specific candidate/year
  requests, naming exact original requests and sealed cell/path pins. These
  639 views require reductions of retained continuous paths, not 639 new
  accounts. Center annual rows already exist. Until a producer seals the
  annual metrics and a common center/neighbor aggregate/reference is frozen,
  annual-local comparison is NOT_EVALUABLE, including on the existing centers.
- **Matched raw/robust winner controls:** old evidence lacks neighborhoods for
  RSI 10/49 and SC 33. Requests identify exact original effective candidates,
  parent schema/design/account provenance and required probe-role contracts.
  The new cold-run registration freezes a bounded schema-floor request recipe
  for those controls plus RSI 114. It generates exact feasible coordinates,
  candidate IDs, role-bound account requests and request SHA256s without finance.
- **Annual-gated local roster:** RSI's eligible originals are 49/56/114;
  measured neighborhoods for 49/114 are missing. SC has no annual-eligible candidates
  under unchanged gates, so more probes cannot rescue that annual selection.
- **Full original-panel local coverage:** 126 candidates per alpha have no
  registered neighborhood. Those are roster gaps, not permission to launch
  every candidate. Two centers cannot certify a 128-point local contest.

There are no missing executions within the existing registered probe rosters.
The bounded addition below is a new request design, not measured local evidence.
Sampler-only, end-to-end, inferential uncertainty and forward studies remain
outside this sidecar. This sidecar changes no alpha/financial source, parameter
range or scientific threshold.

### Bounded Requests

`missing_evidence_requests_08.json` in the private step-1 lane adds exact
schema-floor manifests. All input geometry IDs and original effective vectors
are sealed. Request serialization matches the original producers' deterministic
schema directions on all four existing centers and both roles, including aliases
and infeasible points. Unsupported conditional/log/coupled schemas reject.

| Missing Center | Selection READY | Validation READY | Raw Proposals / Role |
| --- | ---: | ---: | ---: |
| RSI 10 | 29 | 31 | 34 |
| RSI 49 | 29 | 31 | 34 |
| RSI 114 | 29 | 30 | 34 |
| SC 33 | 8 | 8 | 11 |

The recipe preserves signed axes, integer-adjacent moves, SC category flips
and RSI's three registered joint groups. Selection radius/seed are 0.10/732;
validation radius/seed are 0.12/733; minimum effective radius is 0.05.
Seeds do not randomize deterministic schema moves. Every clipped, infeasible
and center/within-role collision row stays in the ledger, without an execution
request. There are **195 feasible role-specific account requests** (179 RSI,
16 SC), with no existing role-compatible probe matches. Cross-role coordinates
remain dependent and cannot be relabeled as independent held evidence.

Covariance is **pending**, not an invented sparse-cloud fallback. Four explicit
fit/design requests use the existing same-branch, distance <=0.25, minimum-five,
full-rank policy; rho 0.2/tau 0.001 and the original generator/seeds. If supported,
register exact covariance directions and deduplicated union before execution;
otherwise seal the measured schema-only fallback reason. No new fitter/RNG.
Schema-floor requests alone do not establish the complete union contest.

Any eventual schema-floor executions also need **585 future annual views**,
derived from their actual continuous paths after execution, not available now.
The 639 retained-path annual-view requests remain separate. Financial resource,
source/data/account, constructor and exact-reuse gates must be registered before
any launch. This cold registration requests evidence; it launches nothing.

## Verification

The adapter and focused suite are stdlib-only. Direct unittest discovery
avoids the financial pytest/conftest surface:

Final attempt 08: **42 tests PASS**; **4,752 prior files** rechecked unchanged,
with zero size/SHA failures. Independent output verification checks 59 retained
step-1 records. Earlier passing suites overlap this count and are not added.

```sh
.maturin/qms08/release-regression-v1/bin/python -B -m unittest discover \
  -s tests -p test_mode5_selector_checkpoint.py -v
```

New evidence is ignored and append-only beneath the original private attempt's
`goal-step1/` lane: registration, cold-run registrations, comparisons, missing
requests, test logs, fixtures and cleanup receipts. Attempt 01's SC summary
schema rejection is retained as FAIL; recovery verifies the actual sealed
SC cell request instead of assuming the RSI summary schema. No financial rerun.
Attempt 04's synthetic-list-alias test failure is also retained, never rewritten
as PASS. Latest suite count is reported on its own, not added to older runs.
Public files expose no private vectors, paths, symbols' data or source code.

The registered budgets are <=32 MiB scratch, <=256 MiB retained and >=5 GiB
reserve. Small custody fixtures are retained; there is no scratch deletion.
Current native work and all shared environments/caches remain untouched.
Attempt 08 retains 81,014,292 bytes before its cleanup receipt (about 77.3 MiB
including all earlier passing/failed cold attempts), with zero scratch bytes
and zero deletion. Free bytes changed from 24,737,628,160 to 24,722,505,728;
free inodes from 5,584,564 to 5,583,978. This is an observed shared-filesystem
change, not reclaimed space or attribution to this sidecar. The 5 GiB reserve
and 256 MiB retained cap pass. Source/test/receipt pins and the final report
are retained in the private closeout, while private evidence remains ignored.

# QMS Release Gap Closure

## Current Status

2026-10-05; branch `feat/meta-selection-samplers`. Owner approved preparation
of **quantbt-engine 1.1.2 / quantbt-native 0.4.3**, not merge/tag/publication.
Current E01 debt closure and artifact receipts are in [the E01 report](QMSE01_REPORT.md).
The following R01-R03 table/artifact hashes are historical, source-bound seals,
not a current-C02-C05 or E01 remote certificate.

| Gate | Status |
|---|---|
| R01 current plan/status reconciliation | PASS; historical seals unchanged |
| R02 six-row installed-W3 qualification | 6/6 PASS remotely on source `0970d55` |
| R03 ordinary-build QMS feature activation/exact dependency | PASS |
| Fresh installed release pair and core sdist | PASS; four cold consumer lanes |
| Installed wheel and sdist W3 | PASS; original native pass, active lineage, no observer failures |
| QMS regression / required IDs | 490 PASS / 64 IDs; no skipped cases |
| Packaging, generated registry and release handoff regression | 34 PASS |
| Build-tool portability and fail-closed release gate follow-up | 37 focused checks PASS |
| Public-index consumer proof for new pair | PENDING_PUBLICATION, not substituted by private/local PASS |
| Scientific study/protocol replacement | NOT_AUTHORIZED; no changes/research in this scope |

The unchanged [real Delta RSI evidence](LOCAL_DEBT_CLOSURE_REPORT.md) remains
research-only. This release pass makes no new timing, market-alpha or economic
acceptance claim. C02 process/witness transport, C03 four-recipe W3/R3B and C04
owned exact continuation have separate local gates; C01/C05 method/geometry
activation remains closed. See the current capability roadmap in
[QMS-C01..C05](../../upgrade/implement.md#qms-capability-gap-roadmap---planning_only).

## Historical R03 Local Artifacts

Build: `.maturin/qms08/release-1.1.2-v2/cp312`, CPython 3.12.
Fresh native build uses no `--features` or candidate-only flag. Core wheel and
sdist match canonical Python modules byte for byte; staging has no version
rewrite. Artifact allowlist, financial-source lock, descriptor/pair checks,
generated inventories, architecture, docs links, benchmark governance and
tracked secret scanning pass. No protected alpha/data enters artifacts.

| Artifact | SHA-256 |
|---|---|
| Core wheel 1.1.2 | `c1ea461651a8f442af6e4742da6bd94620485381fcc31000a02b24ccc5d5202d` |
| Core sdist 1.1.2 | `a5a5e8bc45e3af36a1aaae003b0e0875f2a168e566a26c399b5bccca59c0fed7` |
| Native cp312 wheel 0.4.3 | `becab5f09bb506583a231fadc4b35c9754e7b33a883a7d82012bc01d965f8a4d` |
| Executed native `.so`, pair and sdist consumers | `f67ce9af5caffc23a5dc8cc406086ada2987b6873be72ad19d3c6ba49e652624` |

Local native wheel is **manylinux_2_34_x86_64**, not a manylinux2014 portability
certificate. The existing native publication workflow still builds its separate
manylinux2014 CPython 3.11-3.13 matrix and executes installed certification.

`proof.json` hashes artifact/build logs and four fresh consumer environments.
`installed-w3-proof-v2.json` binds both W3 consumers to that exact package
proof and consumer source. Separate receipt/log namespaces preserve old seals.
Regression JUnit files are `qms-final.xml` and `package.xml` under the ignored
release-regression venv. The ordinary installed IR/static/fallback/disabled-native
smoke also passes; no endpoint/backend promotion was widened.

## Remote And Publication Handoff

The feature-branch push runs the read-only six-row qualification workflow,
building the **release identities**, scalar/four-recipe consumers and installed
W3 on each actual Ubuntu/CPython row. Its JUnit, structured proofs and logs are
retained per runner; no OIDC token or upload action is granted. Record the actual
run SHA/URL and all six final conclusions before calling this gate PASS.

**Actual remote result:** [run 37225926548](https://github.com/BobbyAxerol/quantbt/actions/runs/37225926548)
completed SUCCESS on `0970d55ffbcdd0548989239652f8346b120f5773`.
All six rows passed release identities, fresh default-feature build, scalar
installed consumers, installed-W3 and proof retention:

| Runner | CPython | Job ID | Result |
|---|---|---|---|
| Ubuntu 22.04 | 3.11 | 111505439987 | PASS |
| Ubuntu 22.04 | 3.12 | 111505439935 | PASS |
| Ubuntu 22.04 | 3.13 | 111505439970 | PASS |
| Ubuntu 24.04 | 3.11 | 111505439807 | PASS |
| Ubuntu 24.04 | 3.12 | 111505439972 | PASS |
| Ubuntu 24.04 | 3.13 | 111505440017 | PASS |

The [remote API receipt](../../benchmarks/optimization/meta_selection/qms_release_remote_qualification.json)
retains job/source IDs and uploaded bundle digests. Proof payloads are retained
in six GitHub artifacts for seven days; the API receipt is not an independent
download of those payloads. The first run failed on CI build-tool lookup;
the follow-up uses the local venv executable or PATH, with captured failure
diagnostics. No financial/scientific source changed for this repair.
This Ubuntu proof does not certify a manylinux2014 publication wheel.

E01 connects installed C02 transport and actual C03/C04 consumers to the candidate,
exact-release and later Public Native Consumer Proof, in addition to scalar/W3.
Final-source remote/manylinux/public gates remain pending. Public consumers
first resolve `poetry add quantbt-engine`, then its exact optimization extra.
They execute outside checkout with `python -I`; local source cannot satisfy
that public-index proof. Follow the [owner-controlled runbook](RELEASE_HANDOFF.md)
only after a separate merge/tag/publish approval.

# QMS Release Gap Closure

## Current Status

2026-10-05; branch `feat/meta-selection-samplers`. Owner approved preparation
of **quantbt-engine 1.1.2 / quantbt-native 0.4.3**, not merge/tag/publication.

| Gate | Status |
|---|---|
| R01 current plan/status reconciliation | PASS; historical seals unchanged |
| R02 six-row installed-W3 workflow wiring | PASS locally; remote run pending |
| R03 ordinary-build QMS feature activation/exact dependency | PASS |
| Fresh installed release pair and core sdist | PASS; four cold consumer lanes |
| Installed wheel and sdist W3 | PASS; original native pass, active lineage, no observer failures |
| QMS regression / required IDs | 490 PASS / 64 IDs; no skipped cases |
| Packaging, generated registry and release handoff regression | 34 PASS |
| Public-index consumer proof for new pair | PENDING_PUBLICATION, not substituted by private/local PASS |
| Scientific study/protocol replacement | NOT_AUTHORIZED; no changes/research in this scope |

The unchanged [real Delta RSI evidence](LOCAL_DEBT_CLOSURE_REPORT.md) remains
research-only. This release pass makes no new timing, market-alpha or economic
acceptance claim. New capabilities remain planning-only in
[QMS-C01..C05](../../upgrade/implement.md#qms-capability-gap-roadmap---planning_only).

## Exact Local Artifacts

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

The installed release certifier and later Public Native Consumer Proof now
require QMS scalar/four-recipe and W3 checks for this pair. Public consumers
first resolve `poetry add quantbt-engine`, then its exact optimization extra.
They execute outside checkout with `python -I`; local source cannot satisfy
that public-index proof. Follow the [owner-controlled runbook](RELEASE_HANDOFF.md)
only after a separate merge/tag/publish approval.

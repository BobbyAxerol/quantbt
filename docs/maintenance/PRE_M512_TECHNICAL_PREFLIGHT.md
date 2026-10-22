# Pre-M5-12 Technical Preflight

Date: 2026-10-22 UTC. Prepared pair **1.1.2 / 0.4.3**, unchanged. This closes
the approved architecture/source/wiring/resource work, not M512.01..06.
No build, install, push, workflow dispatch, merge, tag or publication occurred.
The [machine receipt](evidence/pre-m512-technical-preflight.json) records actual
checks. The [initial audit](M5_12_PREPARATION.md) remains historical and unchanged.

## Architecture And Parity

| Facade | Before Lines | Current Lines | Extracted Responsibility |
|---|---:|---:|---|
| `native_option.py` | 1,040 | 956 | Validation in `option_validation.py` |
| `native_portfolio.py` | 1,006 | 811 | Cold reporting in `portfolio_reports.py` |

The 1,000-line trigger, ownership/import rules and exceptions are unchanged.
Architecture passes. Public classes stay in their original module; private
imports/static-method aliases and resolved type hints remain compatible.
Eight moved function bodies and retained engine AST match the entry source.
Differential controls compare complete original/current portfolio outputs across
four cases and three profiles, including actual liquidation. Option controls
cover validation/error precedence, identities and annotations. No Rust,
objective, selector, RNG or accounting formula changed in this extraction.

## Current Source

Runtime source is `77af917f4184e4061a908c68557420223434e2db`, refining repaired
ACC-01 `70fe9f7`, not original QMS finance. The separate
[amendment](evidence/pre-m512-source-amendment.json) pins exactly four files,
before/after commits, hashes and structural proofs. The current guard checks
466 source/contract files and rejects unapproved mutations/additions. Historical
receipts and financial-change disclosures remain unchanged; old
`qms08_gate.validate` is not current financial-invariance proof.

```bash
.venv/bin/python -B tools/check_module_architecture.py
.venv/bin/python -B -m tools.m5_12_source_guard --check
.venv/bin/python -B tools/check_endpoint_compatibility.py \
  --baseline v1.1.1 --baseline 8f7df9d
```

All 48 endpoint signatures remain identical versus pre-ACC. Additive changes
versus `v1.1.1` and 527 root exports are described in
[API compatibility](../mode5/M5_12_PREPARATION.md#endpoint-compatibility).
Source qualification does not certify final artifacts or platforms.

## Consumers And CI

The [maintained roster](../mode5/M5_12_CONSUMER_MATRIX.md) adds 44 cases for
diagnostics, calibration, winner/donor, ReportingV1, ACC accounts/options,
alongside existing W3/scalar/portfolio/package/execution proofs. Workflow filters
cover the current branch and affected source, tools, examples, tests, docs and
source amendments. No workflow was run.

One future-installed synthetic case exercises actual cross-mode calibration:
12 proposal slots, at most 23 financial invocations, explicit applied donors,
baseline/challenger reconciliation and exact winners. Other cases cannot start
an optimizer. Observed budgets, summary bytes, installed resources, module paths,
native hashes and complete pytest phases are required; skipped/stale/partial
output fails. Wheel and sdist are mandatory for complete coverage. Optional
`--kind pair` / `--kind sdist` produces explicitly partial receipts for serial
operation. This tool never installs/builds/removes environments. **The actual
installed roster and six-cell platform matrix remain NOT_RUN.**

## Focused Checks

Latest successful isolated receipts contain **732 passing invocations / 731
distinct pytest IDs**, with zero failures/errors/skips in those receipts:

| Group | Passed Invocations |
|---|---:|
| Portfolio extraction/account/report controls | 94 |
| Options extraction and affected contracts | 226 |
| Structural extraction oracle | 6 |
| Source/provenance/mutation guards | 246 |
| Resource policy | 8 |
| Consumer wiring/budgets/failure injection | 80 |
| Existing candidate/release/docs plumbing | 72 |

Architecture, generated API/product contracts, endpoint compatibility, benchmark
governance and historical promotion-certificate integrity pass. The latter
validates stored evidence, not a new benchmark/promotion. Final docs links,
anchors, privacy and staged whitespace are checked before the closing commit.
Initial failures remain retained: an ineffective synthetic liquidation fixture,
mixed root/options fixture discovery (isolated domain shards pass), and two
old CI branch/filter assertions. Corrections preserve financial checks, six
platform rows and restricted permissions; no acceptance threshold was relaxed.

## Resources And Cleanup

Host-use/hash review preceded deletion of ignored inactive Rust incremental
cache, seven superseded tooling/consumer environments and 17 superseded Rust
unit executables. Latest per-crate executables, native extensions/exact archives,
source/staging, scientific evidence, all receipts/logs, primary/referenced
environments and offline dependencies remain. Cleaned consumers need reinstall.

Two measured removals recovered **759,783,424 bytes** (724.6 MiB), distinct from
apparent hard-linked sizes. Terminal cleanup also retired 2,610 registered
synthetic fixture files. Its receipt writer failed after deletion/hash/source
verification; failure and recovered custody are retained. Exact terminal
free-space delta was not retained and is not invented or added to savings.
Current source and 137 protected historical/artifact hashes were rechecked.

The local estimate is 576 MiB for one consumer, 96 MiB for core build/artifacts,
128 MiB for fixtures/JIT and 96 MiB for logs/headroom: **896 MiB incremental
plus 5 GiB reserve**, with separate RAM admission. Post-cleanup observation
fits, with about 5.90 GiB free. Earlier resource rejection remains in its log.

```bash
.venv/bin/python -B tools/m5_12_resources.py --check
```

This covers one consumer at a time and conditional reuse of an independently
qualified exact native artifact. Fresh native compilation, parallel consumers
and the legacy four-retained-environment builder are excluded. Headroom is
close to the bound: recheck before launch; changed footprints need a new forecast.
No wheel is certified merely because it fits on disk.

## Next Gate

The four preflight items and README capability expansion are implemented and
locally checked. **M5-12 remains NOT_STARTED**: final artifacts, installed
consumers, broader qualification and handoff still need execution/cleanup
receipts. Remote, release and public-index proof require separate approval.
No unmeasured speedup, unchanged historical finance or universal economic claim
is made.

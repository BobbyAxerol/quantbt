# QMS 1.1.2 / 0.4.3 Release Handoff

## Authorization And Scope

Owner-approved pair: `quantbt-engine==1.1.2 / quantbt-native==0.4.3`.
Preparation and feature-branch qualification only; **no merge, tag or upload**
has been authorized in this scope. Meta selection remains opt-in. The default
native build includes existing `qms-numeric-v1` and original-pass prepared
metric witnesses without candidate-only build flags. Financial arithmetic,
native ABI, endpoints and scientific protocol are unchanged.

Read the [qualification boundary](QUALIFICATION.md),
[local evidence and limitations](LOCAL_DEBT_CLOSURE_REPORT.md) and
[unified release-gap plan](../../upgrade/implement.md#qms-release-gap-closure).
Private `1.1.1+qms08 / 0.4.3.dev4` seals remain historical; they cannot certify
the new public pair or imply public availability.

## Non-Publishing Qualification

From the feature branch, with QuantBT's own tooling installed:

```bash
.venv/bin/python -m tools.qms08_package --release-pair \
  --output "$PWD/.maturin/qms08/release-1.1.2-v1"
.venv/bin/python -m tools.qms_installed_w3 \
  --lane "$PWD/.maturin/qms08/release-1.1.2-v1/cp312"
```

Select the actual interpreter with `--python` for another lane. Never reuse an
existing sealed output; choose a new suffix. The release builder uses ordinary
Cargo defaults, copies tracked allowlisted source, and requires byte-identical
wheel/sdist modules and unchanged staged identities. Its four cold consumers
cover core-off, core-with-optimization, exact native pair and installed sdist;
the separate W3 v2 receipt binds both installed lanes to artifact hashes.
Each checks installed origin, exact pair, Rust numerics, off/shadow account
equality, active selection lineage, native-missing/require behavior and cleanup.
E01 requires actual C02 safe-process witness transport, C03 four recipes across
W3/sequential/process/R3B and C04 fresh-process exact continuation. Four isolated
consumer commands run per wheel/sdist lane; no successful capability skips.
Source, toy-example and command/log hashes are retained with each proof.
Read [E01 scope and reproduction](QMSE01_REPORT.md); its local native reuse is
not a fresh manylinux release or public-index certificate.
The [E02 adapter gate](QMSE02_REPORT.md) qualifies newer canonical wheel/sdist,
eight mandatory plus two adapter-specific consumers and exact scalar/W3 parity.
It opens no new domain. Final remote/public proof must use current bytes, not
the historical E01 or pre-C02 remote receipt.

E03's [scalar coverage and study](QMSE03_REPORT.md) adds eight installed scalar
cells on the current canonical wheel/sdist. The candidate matrix also invokes
`tools.qms_e03_installed` and archives `installed-scalar-proof.json` with its
exact lane/artifact/log hashes. This is research opt-in software admission;
per-cell R/Q, simulated-ladder limitations and owner promotion stay separate.
E04 and E05 additionally pass local installed wheel/sdist original shared-account
and bounded package consumers. Read [E04](QMSE04_REPORT.md) and [E05](QMSE05_REPORT.md).
The candidate matrix invokes both installed proofs; six actual current-source
runner successes are still required. Real-alpha economics are not certified by
the installed examples, and quarterly delivery/roll is not a non-expiring basis.
Its real prepared-unit study now fails objective/selection parity after
liquidation. **Do not release this candidate as a fully parity-certified
prepared scorer.** Read the [actual assessment](QMSE03_REPORT.md) and
[bounded repair gate](../../upgrade/implement.md#e03-g01). Small installed proof
PASS and reused-native hashes do not certify the failing liquidation contract;
an approved repair needs newly built, exactly qualified native artifacts.

`.github/workflows/qms-candidate.yml` runs both commands for Ubuntu 22.04/24.04
x CPython 3.11/3.12/3.13 on the pushed feature SHA. Permissions are contents-read
only. Require **six actual successes**, archive JSON/log receipts and record
the run URL/SHA. Local PASS is not remote or manylinux portability proof.

Completed remote gate: **six successes** on source `0970d55`,
[run 37225926548](https://github.com/BobbyAxerol/quantbt/actions/runs/37225926548).
See the [current gap report](RELEASE_GAP_REPORT.md) for exact jobs, local artifact
hashes and retained receipt links. Later release artifacts still require their
own manylinux/public-index gates; this is not permission to publish.

## Later Owner-Controlled Publication

These steps are instructions for a **later approved release**, not actions
performed by the qualification workflow:

1. Review exact-pair qualification and scientific limitations; create the
   feature-to-`dev` PR. Require CI, Native Event and QMS matrix success.
2. Merge `dev` to `main` after reviewing the final release diff. Require all
   release gates on that source. Do not retag or move a published release.
3. Create `v1.1.2` at the clean approved current `main` tip. For TestPyPI instead,
   prepare a matching RC core version and RC tag at `dev`; a final main tag is
   not a TestPyPI ref. Follow the [channel checklist](../testpypi_release_checklist.md).
4. Dispatch **Publish quantbt-native** with `ref=v1.1.2`, `index=pypi`.
   Its manylinux2014 CPython 3.11-3.13 matrix must contain QMS exports under
   ordinary build flags. The installed release certifier executes scalar meta,
   all four sampler recipes and installed W3 before the protected upload.
5. Confirm all native `0.4.3` wheels are publicly available. Only then publish
   the GitHub Release/core `1.1.2`; the core workflow resolves the exact native
   dependency before uploading. Never upload core first.
6. Dispatch **Public Native Consumer Proof** for `ref=v1.1.2`, `index=pypi`.
All six fresh Poetry projects first run `poetry add quantbt-engine`, then
   install its matching optimization extra and exercise scalar/W3, C02 transport,
   C03 samplers and C04 continuation from actual public artifacts.
   Archive the public-index receipts. Until then: `PENDING_PUBLICATION`.

No protected alpha, market history, `.venv`, cache, token or private receipt is
shipped in the artifacts. Package allowlist/secret guards remain mandatory.

## Rollback And Remaining Scope

Omit meta config to restore native selection; use reference numeric policy when
needed. Force Python/Numba through the existing backend controls, not replay of
native accounting. If a published artifact is wrong, stop downstream publication
and prepare a **new** version; never rewrite existing PyPI bytes or release tags.

QMS is currently Mode 4 / `per_fold_causal`. C02/C03 locally qualify original-pass
W3 process witness transport/deadlines and four-recipe W3/fixed-batch scheduling;
continuous carry, multi-symbol and public meta batching remain unsupported.
C04 locally qualifies a separate [owned exact continuation session](EXACT_CONTINUATION.md),
not automatic public WFO/financial state resume. Other mode/schedule activation,
conditional Sobol and admissible mixed-space centroids remain separately
reviewed work in [QMS-C01..C05](../../upgrade/implement.md#qms-capability-gap-roadmap---planning_only).
C05 reference geometry tests do not activate conditional Sobol or mixed centroids.
Current E03 source/artifacts still require remote matrix and public-index proof;
do not reuse the pre-C02 remote receipt or private local artifacts as release evidence.
The scientific study/protocol requires a separate owner decision before any
methodological replacement or additional research; software PASS does not
certify an economic edge.

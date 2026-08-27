# QuantBT Packaging And Release

This document records the Phase 48F final release contract for `quantbt-engine`.
The older Phase 42C rules remain valid unless this document explicitly updates
them.

## Phase 55B Public Native Pair

`quantbt-engine==1.0.10` declares `quantbt-native==0.4.1` as a direct runtime
dependency only on Linux x86_64 / glibc / CPython 3.11-3.13. The native package
is wheel-only: supported users receive a pre-built manylinux artifact from a
normal `pip install quantbt-engine` or `poetry add quantbt-engine`, while all
other platforms keep the Python/Numba core without a Rust compiler.

The release cannot be a one-step core upload. It is a protected sequence:

1. Build/certify the native CPython 3.11/3.12/3.13 manylinux matrix.
2. Publish `quantbt-native` to TestPyPI through `publish-native.yml`.
3. Publish the core to TestPyPI only after its native preflight passes.
4. Run the Ubuntu 22.04/24.04 Poetry consumer proof.
5. Repeat native-first on PyPI, then create the GitHub Release that publishes
   the core, then archive the PyPI consumer proof.

The exact OIDC configuration, manual dispatch inputs, consumer evidence, and
rollback boundary are in the [TestPyPI release checklist](testpypi_release_checklist.md).

## P3 Product Evidence

The shipped Python package is built from `src/quantbt`. The repository root
mirror is a temporary checked compatibility mirror and is never an independent
release source. Before a release candidate, run:

```bash
make test-contracts
make build-core-wheel
make verify-wheels
make supply-chain-report
make sbom
make release-manifest
```

`release-manifest.json` records artifact checksums, product/lifecycle registry
fingerprints, benchmark references, and hashes of the supply-chain report and
CycloneDX SBOM. The core remains usable without native code on platforms outside
the declared matrix. On the supported matrix, the exact pre-built companion
enables the bounded Stage-B `backend="auto"` policy only for certified static
command tapes and Native Strategy IR/batch rows; it does not promote callbacks,
reactive strategies, portfolio, or package/arbitrage execution.

The supply-chain report also records source/ref cleanliness, Python/Rust
toolchain and target metadata, native build profile/features, the Cargo lock
hash, and both contract fingerprints. It is release evidence, not a claim that
a locally built native wheel is portable or promoted.

To inspect a staged core/native pair locally:

```bash
make build-native-wheel
make verify-staged-wheels
make migration-audit
make certify-native-release
```

The staged verifier creates clean environments, checks source-to-wheel module
hashes, rejects source-tree import leakage, and requires an exact pair declared
by the generated product registry.

`make certify-native-release` adds the native release-candidate proof: it
creates a core-only environment and an exact core/native-pair environment,
checks the version/API handshake and generated promotion decisions, exercises
static/IR public routes plus the bounded target/package helpers, and writes a
checksum-bearing JSON certificate. It is prerequisite evidence rather than an
upload command; public publication additionally requires the native-first OIDC
workflow and consumer proof. See the [native release handoff](migration/native_release_handoff.md).

For a local evidence bundle containing both staged release artifacts, run:

```bash
make release-manifest-staged
```

The manifest records each distribution separately and accepts a native wheel
only when its exact version matches the product registry's declared companion.
This is local evidence only. Public release follows the native-first workflow:
publish the strict native wheel matrix, publish the matching core artifact, then
prove `poetry add quantbt-engine` from a clean consumer environment.

## Release-Preparation Checklist

Prepare every new core version in one small, reviewable release commit before
creating its tag. Do not reuse an existing PyPI version or Git tag.

1. Set the new version in `pyproject.toml`.
2. Update the core version and exact-pair mapping in
   `contracts/native_event_product_registry.json` when the staged native
   companion remains part of local certification.
3. Add the release entry to `CHANGELOG.md`.
4. Regenerate committed product artifacts:

   ```bash
   poetry run python tools/generate_product_contracts.py
   poetry run python tools/check_release_version.py
   poetry run python tools/check_docs_links.py
   ```

5. Run the clean release gate from that exact commit, merge it to `main`, then
   create the matching `vX.Y.Z` tag. The tag triggers **Native Release
   Certification**; create the GitHub Release and approve PyPI publishing only
   after its artifacts pass review.

The `1.0.10` release is the exact public-pair release line. A local certificate
does not by itself publish `quantbt-native`, enable generic endpoint auto
routing, or remove the Python oracle. The Phase 55B TestPyPI/PyPI consumer
proof is the additional release authorization.

## Package Contract

- PyPI distribution: `quantbt-engine`.
- Python import package: `quantbt`.
- Public import remains:

```python
from quantbt import QuantBTEndpoint
```

- Source layout is `src/quantbt`.
- Root source is retained during migration until later compatibility gates
  explicitly remove it.
- The current package release line is `1.0.x`, continuing the existing GitHub
  release series without changing the public Python import contract.
- Earlier `0.1.x` references belong to the pre-PyPI packaging plan and were not
  published.
- Phase 48F TestPyPI artifact and functional endpoint gates passed for the
  historical `1.0.7rc2` candidate. Phase 55B adds native-first public upload
  and Poetry consumer proof for the `1.0.10` governed-native patch release.
- Python is the canonical/full-featured implementation for the first release.
- `quantbt-native` is the exact wheel-only Linux x86_64 dependency for
  `1.0.10`; its native-first OIDC upload and consumer proof are mandatory
  before a release is represented as publicly available.

Phase 45C keeps the root source mirror temporarily for rollback and editable
compatibility. Distribution artifacts are built from `src/quantbt`, while the
SHA256 source-sync test prevents the two source locations from drifting.
Deleting the root mirror is a later, separately approved migration step.

## CI Contract

The main CI workflow runs on pull requests and pushes to `dev` and `main`.

Required checks:

- Python matrix: `3.11`, `3.12`, `3.13`.
- `uv sync --extra optimization --extra reports --extra viz --dev`.
- `.venv/bin/python tools/run_test_shards.py --profile ci-core`.
- The separate Native Event API 0.4 workflow runs the complete `tests/native_event` suite after installing the native wheel.
- `uv build`.
- Clean wheel install in a fresh virtual environment.
- Public import smoke from outside the repository root.
- Pool Alpha style import smoke.

CI must not rely on `PYTHONPATH` to pretend the package is installed.

Core CI intentionally tests the Python package separately from the native
wheel. It installs the optimization, report, and visualization extras needed
by the shared test suite, but omits the optional Nautilus validation stack.
The `native` extra is currently an empty reservation, so CI cannot accidentally
claim that a native PyPI distribution exists.

The two `tests/test_real*.py` files are notebook-style data scripts, not
portable unit tests: they read Pool Alpha data outside this repository and
execute a backtest during module import. Run them separately in the Pool
Alpha environment; do not include them in public package CI.

NautilusTrader validation is optional and only resolves on Python `>=3.12`
because `nautilus-trader==1.230.0` does not support Python 3.11. The core
QuantBT package remains import/testable on Python 3.11.

## Release Contract

Publishing is only allowed from a GitHub Release event:

```text
on:
  release:
    types: [published]
```

Normal pushes to `main` or `dev` must never publish to PyPI.

The intended branch flow is:

```text
feature branches -> dev -> release branch -> main -> GitHub Release -> PyPI
```

Do not tag from `dev`.

Do not publish from an uncommitted local tree.

The release workflow runs `pip check` after both wheel and sdist installation.
The package build source is `src/quantbt`; the root mirror is retained for
editable Pool Alpha compatibility and is protected by the source-sync tests.
It is not a second distribution source.

The exact handoff fields, artifact hashes, RC tag procedure, and post-upload
smoke steps are maintained in the
[`TestPyPI release checklist`](testpypi_release_checklist.md). CI creates a
`quantbt-release-manifest-v1` JSON artifact containing the release commit,
version, wheel/sdist SHA256 values, benchmark evidence hashes and backend
policy. The manifest is evidence only; it is never uploaded to PyPI.

For a tagged release candidate with a local native companion, trigger the
**Native Release Certification** workflow before creating a public native
claim. It builds Linux manylinux core/native artifacts for CPython 3.11, 3.12,
and 3.13, performs the installed-wheel gate per row, and archives certificates
and staged artifacts. Phase 55A keeps this as certification only; Phase 55B
will add the separate companion publication and public consumer-install proof.

## Trusted Publishing

The default publish path uses PyPI Trusted Publishing/OIDC.

Configure PyPI pending publisher:

```text
Project:      quantbt-engine
Owner:        BobbyAxerol
Repository:   quantbt
Workflow:     publish.yml
Environment:  pypi
```

The GitHub environment `pypi` should be protected by reviewer approval.

## Token Fallback

Long-lived PyPI tokens are not the normal release path.

Token fallback is only for:

- manual TestPyPI;
- debug publish;
- emergency fallback.

If a token is used:

- prefer project-scoped token;
- use username `__token__`;
- never commit the token;
- remove the GitHub secret after OIDC works;
- revoke the token on PyPI after use.

## Version Gate

`tools/check_release_version.py` compares `pyproject.toml` version with the
release tag.

Example:

```text
pyproject.toml version = 1.0.9
required release tag  = v1.0.9
```

The publish workflow fails if the tag does not match.

The same script validates an RC tag. To publish an RC, first commit an unused
version such as `1.0.9rc1`, create the matching `v1.0.9rc1` tag, and run the
manual TestPyPI workflow with that tag. Do not reuse final `1.0.9` for an RC.

## Local Release Gate

Run these commands from a clean feature/release commit. They use a temporary
artifact directory and do not remove the repository's existing `.venv`, `dist`,
or build directories:

```bash
poetry run python tools/check_release_version.py
.venv/bin/python tools/run_test_shards.py --profile release --max-files-per-shard 8
poetry run python tools/audit_phase50_wfo_causal.py \
  --output /tmp/quantbt-phase50-wfo-causal-audit.json
poetry run python -m build --no-isolation --outdir /tmp/quantbt-engine-dist
poetry run twine check /tmp/quantbt-engine-dist/*
poetry run python tools/check_release_artifacts.py --dist /tmp/quantbt-engine-dist
poetry run python tools/create_release_manifest.py \
  --dist /tmp/quantbt-engine-dist \
  --output /tmp/quantbt-release-manifest.json
```

Inspect the artifacts before installing them:

```bash
poetry run python -c "import zipfile, pathlib; p=next(pathlib.Path('/tmp/quantbt-engine-dist').glob('*.whl')); print(*zipfile.ZipFile(p).namelist(), sep='\\n')"
poetry run python -c "import tarfile, pathlib; p=next(pathlib.Path('/tmp/quantbt-engine-dist').glob('*.tar.gz')); print(*tarfile.open(p).getnames(), sep='\\n')"
```

Validate both formats outside the repository root. `--no-deps` makes this a
package-content smoke; the CI workflow additionally installs dependencies and
runs `pip check`:

```bash
python3 -m venv /tmp/quantbt-engine-wheel-smoke
/tmp/quantbt-engine-wheel-smoke/bin/python -m pip install --upgrade pip
/tmp/quantbt-engine-wheel-smoke/bin/python -m pip install --no-deps /tmp/quantbt-engine-dist/quantbt_engine-*.whl
smoke_dir="$(mktemp -d)"
(cd "$smoke_dir" && /tmp/quantbt-engine-wheel-smoke/bin/python -c "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)")

python3 -m venv /tmp/quantbt-engine-sdist-smoke
/tmp/quantbt-engine-sdist-smoke/bin/python -m pip install --upgrade pip
/tmp/quantbt-engine-sdist-smoke/bin/python -m pip install --no-deps /tmp/quantbt-engine-dist/quantbt_engine-*.tar.gz
smoke_dir="$(mktemp -d)"
(cd "$smoke_dir" && /tmp/quantbt-engine-sdist-smoke/bin/python -c "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)")
```

For a dependency-complete check, install the wheel without `--no-deps` in a
fresh environment and run `python3 -m pip check`. Never use a repository-root
`PYTHONPATH` as evidence that a wheel works.

Walk-forward parameter search is intentionally an optional dependency surface.
Use `quantbt-engine[optimization]` for every WFO release smoke, and verify that
both Optuna and the public WFO route import from the installed distribution:

```bash
wheel="$(find /tmp/quantbt-engine-dist -maxdepth 1 -name '*.whl' -print -quit)"
/tmp/quantbt-engine-wheel-smoke/bin/python -m pip install \
  "${wheel}[optimization]"
smoke_dir="$(mktemp -d)"
(cd "$smoke_dir" && /tmp/quantbt-engine-wheel-smoke/bin/python -c \
  "import optuna; from quantbt import QuantBTEndpoint; from quantbt.walkforward import WalkForwardConfig; print(QuantBTEndpoint, WalkForwardConfig)")
```

The Phase 50 audit is an additional deterministic behavior gate for strict
`mode_1_decay + per_fold_causal`. Its JSON confirms nested inner-OOS boundaries,
outer-OOS exclusion, completed-prefix invariance, fail-closed inner-history
validation, and prepared/reference account parity. It proves QuantBT's engine
boundary, not indicator causality inside arbitrary user strategy code.

## Pool Alpha Development

During local development, Pool Alpha can use editable/path install:

```bash
pip install -e /root/bobby/pool_alpha/quantbt
```

Or a Poetry path dependency:

```toml
quantbt = { path = "../quantbt", develop = true }
```

After the governed public-pair release:

```toml
quantbt-engine = "^1.0.10"
```

Alpha/notebook imports do not change:

```python
from quantbt import QuantBTEndpoint
```

## Native Package Note

`quantbt-native==0.4.1` is the exact wheel-only companion for core `1.0.10`;
its Rust distribution version and Native Event API version remain separate
contracts. The core declares it directly for Linux x86_64 CPython 3.11-3.13,
so normal supported installs resolve a pre-built wheel. `native_backend="auto"`
follows the generated Stage-B policy only for its governed static/IR rows;
`native_backend="rust"` remains explicit and fail-fast.

Historical Phase 46F rerun evidence retained for comparison is:

| Gate | Result |
|---|---|
| Python/Rust lifecycle and accounting parity | pass |
| Low/high churn score runtime | pass (`20.33/36.16 ms` Python; `0.109/0.140 ms` Rust) |
| Low/high churn throughput | pass (`98,385/55,308` Python bars/s; `18.30M/14.33M` Rust bars/s) |
| Absolute peak RSS | pass (`184.11 MB < 512 MB`) |
| 100-run RSS plateau | pass |
| Prepared RSS reduction >= 40% | fail (`-26.1%` / `-7.6%`) |
| Automatic Rust routing | governed Stage-B static/IR/batch rows only with the exact supported public pair |
| Native dependency contract | direct Linux x86_64 CPython 3.11-3.13 requirement, published native-first with Poetry consumer proof |

The core package still has a full Python fallback, while the native wheel stays
behind its own manylinux CPython 3.11-3.13, parity, fallback, and consumer
certification gate.

## Native Event Rust API 0.4

The governed `quantbt-native` companion implements the public Native Event V2
contract certified by the shared Python/replay/Rust conformance suite. Its
distribution version is `0.4.1` and its executable native API is `0.4`; these
are separate version contracts.

`native_backend="rust"` is explicit and fail-fast. It does not silently
downgrade to Python. With a matching API-0.4 companion,
`native_backend="auto"` uses the generated Stage-B static/IR/batch policy;
without that companion, the core fallback remains Python. The public pair is
only released after Phase 55B's native-first and Poetry consumer gates.

The API 0.4 capability contract covers:

```text
Native Event V2 full contract
single- and multi-symbol execution
funding, margin and liquidation
PLACE/CANCEL/CANCEL_ALL/AMEND/REPLACE
MARKET/LIMIT/STOP_MARKET/STOP_LIMIT
GTC/GTD/IOC/FOK
reduce-only, quantity preflight, parent/group/OCO and expiry
```

See:

- [`native_event_rust_full_contract.md`](native_event_rust_full_contract.md)
- [`grid_native_event_phase47c.md`](grid_native_event_phase47c.md)
- [`endpoint.md`](endpoint.md)

For local Rust validation once the Rust toolchain and Maturin are installed:

```bash
cd rust/native_event
cargo fmt --check
cargo clippy -- -D warnings
cargo test
maturin build --release
```

`QUANTBT_NATIVE_BACKEND=python` forces the existing Python Native Event
implementation. `auto` follows the generated Stage-B policy only when the
matching local companion is installed; otherwise it remains Python. `rust` is
explicit and capability-gated at API 0.4 before execution. A missing or
incomplete native wheel fails clearly for an explicit Rust request; automatic
fallback records a structured reason. Public native installation remains a
separate manylinux CPython 3.11-3.13 release gate.

Native publishing must wait until the API 0.4 package builds for every
advertised wheel target, installs beside the matching `quantbt-engine` wheel,
and passes Python/replay/Rust parity, Grid integration, and performance/RSS
gates. Native CI builds both distributions from the same ref, installs them in
a clean environment, verifies API 0.4 capabilities, and runs parity/RSS smoke.

### Historical R0/R1/R2 scaffold

The earlier R0/R1/R2 milestones remain useful engineering history. They
covered the initial local PyO3 import, single-symbol reactive execution, and
the early explicit-order subset. They are not the current public Rust
contract, and their restrictions must not be used as the release policy for
API 0.4.

## Repository Mirror And Artifact Safety

The Python wheel source of truth is `src/quantbt`. The root-level Python tree
is a temporary compatibility mirror for local Pool Alpha imports. Its scope is
explicitly limited by `tools/source_mirror_manifest.py`; benchmark scripts,
tests, and tools are not package mirror entries.

Check or synchronize one direction at a time:

```bash
poetry run python tools/sync_source_mirror.py --check
poetry run python tools/sync_source_mirror.py --src-to-root
poetry run python tools/sync_source_mirror.py --root-to-src
```

The sync tool never merges both trees automatically and never deletes an
unknown root-only file. A missing, extra, or byte-different Python file is a
reviewable failure. `src/quantbt` remains the wheel source until the mirror is
formally retired.

Before a public release, CI verifies that `upgrade/implement.md` remains
tracked and visible, scans tracked files for high-confidence credential
patterns, and inspects wheel/sdist members. Generic words such as `token`,
`password`, or the PyPI publish action are documented terms and are not leaks
by themselves; credential-like matches still require manual review.

The core wheel allowlist is `quantbt/**` plus its own
`quantbt_engine-*.dist-info/**`. `MANIFEST.in` controls sdist content only;
it is not a substitute for removing a secret from Git history. Private data,
credentials, compiler output, profiler traces, and local benchmark output are
ignored by path-specific rules, while public plans, tests, tools, docs, and
accepted benchmark evidence remain trackable.

## TestPyPI To PyPI Workflow

### TestPyPI release candidate

1. Update the package version to an unused RC version such as `1.0.9rc1`.
2. Commit the version and changelog on a release candidate ref.
3. Create the matching tag, for example `v1.0.9rc1`.
4. Configure the pending TestPyPI publisher for repository `BobbyAxerol/quantbt`,
   workflow `publish-testpypi.yml`, and GitHub environment `testpypi`.
5. Push the matching RC tag to trigger **Publish quantbt-engine to TestPyPI**,
   or run it manually with the exact tag. The workflow runs the clean
   wheel/sdist installation gate before the publish job and uploads the release
   manifest separately for review.
6. Install and smoke-test the RC from both TestPyPI and the Pool Alpha
   environment:

```bash
python3 -m venv /tmp/quantbt-testpypi-smoke
/tmp/quantbt-testpypi-smoke/bin/python -m pip install --upgrade pip
/tmp/quantbt-testpypi-smoke/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  "quantbt-engine[optimization]==1.0.9rc1"
/tmp/quantbt-testpypi-smoke/bin/python -c "import optuna; from quantbt import QuantBTEndpoint; from quantbt.walkforward import WalkForwardConfig; print(QuantBTEndpoint, WalkForwardConfig)"
/tmp/quantbt-testpypi-smoke/bin/python -m pip check
```

### Production PyPI release

1. Merge the verified release commit to protected `main`.
2. Set the final version, for example `1.0.9`, and add the changelog entry.
3. Create and push the matching protected tag `v1.0.9`.
4. Run **Native Release Certification** for the matching tag and archive its
   artifacts. This is required before any native capability claim; it does not
   publish `quantbt-native`.
5. Create a GitHub Release from that tag and mark it published.
6. The production workflow runs the matrix regression, builds the core wheel
   and sdist, runs metadata and clean-install checks, then pauses at the
   protected `pypi` environment reviewer gate.
7. Approve only after the artifact name, version, and release notes have been
   checked. The workflow publishes through OIDC; no long-lived API token is
   needed.
8. Verify `pip install quantbt-engine==1.0.9` from a fresh environment and
   archive the wheel, sdist, test output, and release manifest.

This numbered flow documents the historical core-only release process. Do not
reuse it for pending `1.0.10`: Phase 55B publishes the validated native wheel
matrix first, then the core wheel that declares its exact platform-marked
dependency. Until that separate public consumer proof completes, PyPI `1.0.9`
uses Python; the local exact-pair Stage-B policy is documented in the generated
compatibility table. The [native release handoff](migration/native_release_handoff.md)
lists the bounded E4/E5 helper scope and rollback requirements.

## Benchmark Evidence And Open Optimization Scope

The committed benchmark evidence distinguishes score throughput from full
facade/report runtime. The Phase 46F Rust batched score rerun reports `182.2x`
low-churn and `251.3x` high-churn speedup against the Python score path, with
full parity and an absolute `184.11 MB` peak RSS. The prepared RSS threshold
did not pass, so these numbers do not justify automatic Rust selection. The
prior Phase 46E snapshot (`155.6x` / `218.4x`) remains available for historical
comparison.

Phase 45F's isolated end-to-end reference reported a `42.08x` median speedup
and an `18.3%` minimum peak-RSS reduction across its workload. These snapshots
are evidence for different benchmark contracts, not interchangeable claims;
always cite the JSON artifact and workload when comparing runs.

The next optimization scope remains deliberately open and domain-preserving:
Python scalar/object reduction and Rust batched paths may later be extended to
portfolio, arbitrage, options, vectorized, intrabar, and Nautilus adapter
workloads. Such work requires a separate parity/RSS gate for each domain and
must not change the core PyPI release or silently change backend selection.

### Local Native Evidence Gate

Phase 45B.1 ran the native evidence gate on Linux x86_64 with CPython 3.12 and
Rust stable 1.97.1. The core and native wheels built from one commit, installed
cleanly, and the installed R1/R2 parity suite passed for every advertised Rust
capability. This is a correctness result, not an automatic performance claim.

Repeated warmed 25,000-bar R1 workloads put the historical PyO3 path at
roughly `0.69x-0.83x` Python throughput, with no RSS reduction. The historical
adapter crossed the Python boundary once per bar and created Python result
payloads, so prepared market data could not amortize that cost. The later
batched Stage-B work supersedes that performance conclusion for its bounded
routes; Phase 55A still does not publish a companion until the public wheel
matrix and Phase 55B consumer proof pass.

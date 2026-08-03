# QuantBT Packaging And Release

This document records the Phase 48F final release contract for `quantbt-engine`.
The older Phase 42C rules remain valid unless this document explicitly updates
them.

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
- Phase 48F release candidate: `1.0.7rc1` for TestPyPI; final target `1.0.7`.
- Phase 48F local artifact gate: complete for the core Python distribution;
  TestPyPI publication remains an explicit operator action.
- Python is the canonical/full-featured implementation for the first release.
- `quantbt-native` is experimental and is not a dependency of the core wheel.

Phase 45C keeps the root source mirror temporarily for rollback and editable
compatibility. Distribution artifacts are built from `src/quantbt`, while the
SHA256 source-sync test prevents the two source locations from drifting.
Deleting the root mirror is a later, separately approved migration step.

## CI Contract

The main CI workflow runs on pull requests and pushes to `dev` and `main`.

Required checks:

- Python matrix: `3.11`, `3.12`, `3.13`.
- `uv sync --extra optimization --extra reports --extra viz --dev`.
- `.venv/bin/python -m pytest -q --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py`.
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
pyproject.toml version = 1.0.7
required release tag  = v1.0.7
```

The publish workflow fails if the tag does not match.

The same script validates an RC tag. To publish `1.0.7rc1`, first commit
`version = "1.0.7rc1"`, create `v1.0.7rc1`, and run the manual TestPyPI
workflow with that tag. Do not reuse the final `1.0.7` version for an RC.

## Local Release Gate

Run these commands from a clean feature/release commit. They use a temporary
artifact directory and do not remove the repository's existing `.venv`, `dist`,
or build directories:

```bash
poetry run python tools/check_release_version.py
.venv/bin/python -m pytest -q --ignore=tests/test_real.py --ignore=tests/test_real_endpoints.py
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
(cd /tmp && /tmp/quantbt-engine-wheel-smoke/bin/python -c "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)")

python3 -m venv /tmp/quantbt-engine-sdist-smoke
/tmp/quantbt-engine-sdist-smoke/bin/python -m pip install --upgrade pip
/tmp/quantbt-engine-sdist-smoke/bin/python -m pip install --no-deps /tmp/quantbt-engine-dist/quantbt_engine-*.tar.gz
(cd /tmp && /tmp/quantbt-engine-sdist-smoke/bin/python -c "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)")
```

For a dependency-complete check, install the wheel without `--no-deps` in a
fresh environment and run `python3 -m pip check`. Never use a repository-root
`PYTHONPATH` as evidence that a wheel works.

## Pool Alpha Development

During local development, Pool Alpha can use editable/path install:

```bash
pip install -e /root/bobby/pool_alpha/quantbt
```

Or a Poetry path dependency:

```toml
quantbt = { path = "../quantbt", develop = true }
```

After release:

```toml
quantbt-engine = "^1.0.7"
```

Alpha/notebook imports do not change:

```python
from quantbt import QuantBTEndpoint
```

## Native Package Note

`quantbt-native` is not published in the current Phase 48F core release. Its current Rust crate version
and native API version are separate from the core package version. Rust remains
available only through an explicitly installed local wheel and an explicit
`native_backend="rust"` request.

Historical Phase 46F rerun evidence retained for comparison is:

| Gate | Result |
|---|---|
| Python/Rust lifecycle and accounting parity | pass |
| Low/high churn score runtime | pass (`20.33/36.16 ms` Python; `0.109/0.140 ms` Rust) |
| Low/high churn throughput | pass (`98,385/55,308` Python bars/s; `18.30M/14.33M` Rust bars/s) |
| Absolute peak RSS | pass (`184.11 MB < 512 MB`) |
| 100-run RSS plateau | pass |
| Prepared RSS reduction >= 40% | fail (`-26.1%` / `-7.6%`) |
| Automatic Rust routing | disabled |
| Non-empty `quantbt-engine[native]` extra | not released |

Consequently the core package can be released independently, while the native
wheel remains behind its own manylinux CPython 3.11-3.13, parity, fallback,
and incremental-RSS certification gate.

## Native Event Rust API 0.4

The optional `quantbt-native` package implements the public Native Event V2
contract certified by the shared Python/replay/Rust conformance suite. Its
distribution version is currently `0.4.0` and its executable native API is
`0.4`; these are separate version contracts.

`native_backend="rust"` is explicit and fail-fast. It does not silently
downgrade to Python. `native_backend="auto"` remains Python in
`quantbt-engine 1.0.7` until the public wheel matrix and release gates pass.

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

`QUANTBT_NATIVE_BACKEND=auto` and `python` continue using the existing Python
Native Event implementation. `rust` is explicit and is capability-gated at
API 0.4 before execution. A missing or incomplete native wheel fails clearly;
it never falls back silently. Public native installation remains a separate
manylinux CPython 3.11–3.13 release gate.

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

1. Update the package version to an unused RC version such as `1.0.7rc1`.
2. Commit the version and changelog on a release candidate ref.
3. Create the matching tag, for example `v1.0.7rc1`.
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
  quantbt-engine==1.0.7rc1
/tmp/quantbt-testpypi-smoke/bin/python -c "from quantbt import QuantBTEndpoint; print(QuantBTEndpoint)"
/tmp/quantbt-testpypi-smoke/bin/python -m pip check
```

### Production PyPI release

1. Merge the verified release commit to protected `main`.
2. Set the final version, for example `1.0.7`, and add the changelog entry.
3. Create and push the matching protected tag `v1.0.7`.
4. Create a GitHub Release from that tag and mark it published.
5. The production workflow runs the matrix regression, builds the core wheel
   and sdist, runs metadata and clean-install checks, then pauses at the
   protected `pypi` environment reviewer gate.
6. Approve only after the artifact name, version, and release notes have been
   checked. The workflow publishes through OIDC; no long-lived API token is
   needed.
7. Verify `pip install quantbt-engine==1.0.7` from a fresh environment and
   archive the wheel, sdist, test output, and release manifest.

Do not publish `quantbt-native` in this flow. It has a separate future release
when its wheel matrix and RSS gates pass. Until then, `auto` remains Python and
the native extra remains empty.

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

Repeated warmed 25,000-bar R1 workloads put the current PyO3 path at roughly
`0.69x-0.83x` Python throughput, with no RSS reduction. The current adapter
crosses the Python boundary once per bar and creates Python result payloads, so
prepared market data alone cannot amortize that cost. Therefore `auto` remains
Python and `quantbt-native` remains unpublished and experimental. A future
native rollout requires a batched or compiled-strategy boundary and a fresh
parity plus throughput/RSS certification run.

# QuantBT Public Core/Native Release Checklist

This is the release-owner handoff for the governed public pair:

```text
quantbt-engine==1.1.0
quantbt-native==0.4.1
```

The core remains a complete Python package. On Linux x86_64 with CPython
3.11-3.13, its direct platform marker resolves a pre-built native wheel. No
consumer compiles Rust. Other platforms resolve the Python/Numba core only.

The release channels are deliberately separate:

| Channel | Branch tip | Tag shape | Index |
| --- | --- | --- | --- |
| Research candidate | `dev` | `vX.Y.ZrcN` | TestPyPI |
| Public release | `main` | `vX.Y.Z` | PyPI |

The workflows enforce this provenance. A final main tag does not go through
TestPyPI, and an RC tag cannot publish to PyPI. Within either channel, publish
`quantbt-native` first, prove the consumer, then publish `quantbt-engine`.

## One-Time Trusted Publishing Setup

Configure two pending publishers on **TestPyPI**, then repeat the same setup on
**PyPI**. No API token is needed.

| Distribution | GitHub repository | Workflow | Environment |
| --- | --- | --- | --- |
| `quantbt-native` | `BobbyAxerol/quantbt` | `publish-native.yml` | `testpypi` or `pypi` |
| `quantbt-engine` | `BobbyAxerol/quantbt` | `publish-testpypi.yml` on TestPyPI; `publish.yml` on PyPI | `testpypi` or `pypi` |

Protect the GitHub `pypi` environment with reviewer approval. The native
workflow is dispatch-only, so creating a Git tag cannot accidentally upload a
binary wheel.

## TestPyPI Sequence

1. Work from the clean current `dev` commit and create a matching RC tag, for
   example `v1.1.0rc1`. The RC tag must equal `project.version` and point to
   the exact current `dev` tip.
2. Run **Publish quantbt-native** manually with:

   ```text
   ref:   v1.1.0rc1
   index: testpypi
   ```

   It builds wheel-only `manylinux2014` artifacts for CPython 3.11, 3.12 and
   3.13, validates their tags and exact core dependency metadata, then runs an
   installed-pair certificate before the OIDC upload job.
3. Inspect the uploaded certification artifact and confirm all three native
   wheels exist. Do not continue if a wheel is missing or an sdist appears.
4. Run **Publish quantbt-engine to TestPyPI** manually with `ref: v1.1.0rc1`.
   Its preflight resolves `quantbt-native==0.4.1` from TestPyPI before it can
   publish the core wheel/sdist.
5. Run **Public Native Consumer Proof** with:

   ```text
   ref:   v1.1.0rc1
   index: testpypi
   ```

   The six isolated jobs cover Ubuntu 22.04 and 24.04 across CPython
   3.11-3.13. Each creates an empty Poetry project and runs exactly:

   ```bash
   poetry add quantbt-engine
   ```

   The proof requires the matching native distribution, validates the native
   descriptor, confirms a governed 10,000-bar static route selects Rust, then
   proves forced Python, disabled-native fallback, and explicit-Rust
   fail-closed behavior.
6. Download and archive the native wheel matrix, installed-pair certificate,
   core release manifest, and all six consumer JSON artifacts with the release
   notes.

## Manual Poetry Smoke

The workflow is the release gate; this is a short human-readable repeat of the
same consumer behavior. Use it only after both TestPyPI artifacts are visible:

```bash
smoke_dir="$(mktemp -d)"
cd "$smoke_dir"
poetry init --name quantbt-public-smoke --python '>=3.11,<3.14' --no-interaction
poetry source add --priority=primary testpypi https://test.pypi.org/simple/
poetry source add --priority=supplemental PyPI
poetry add quantbt-engine
poetry run python - <<'PY'
import importlib.metadata as metadata
import _quantbt_native
from quantbt.backends._native_event_rust import probe_native_event_rust_extension

assert metadata.version("quantbt-engine") == "1.1.0"
assert metadata.version("quantbt-native") == "0.4.1"
status = probe_native_event_rust_extension()
assert status.compatible and status.executable, status.reason
print(status)
PY
```

For normal PyPI, omit the two `poetry source add` commands and run the same
`poetry add quantbt-engine` command.

## Production Sequence

1. Work from the final clean current `main` commit and create the matching
   final tag, for example `v1.1.0`. The tag must equal `project.version` and
   point to the exact current `main` tip.
2. Run **Publish quantbt-native** with `ref: v1.1.0`, `index: pypi`; approve
   its protected `pypi` environment only after checking the wheel names and
   certificate.
3. Verify `quantbt-native==0.4.1` is visible on PyPI for CPython 3.11-3.13.
4. Create and publish the GitHub Release for `v1.1.0`. The existing
   **Publish quantbt-engine** workflow preflights the public companion,
   performs core regression/build/install gates, and then waits for the
   protected PyPI approval before upload.
5. Run **Public Native Consumer Proof** again with `index: pypi` and archive
   its six reports. This is the final public-install evidence.

## Release Boundaries

- `backend="auto"` stays Python until the exact route has fresh
  current-candidate measurement evidence; static/IR historical evidence alone
  cannot promote Rust.
- `backend="python"` remains the oracle and always forces Python.
- `backend="rust"` is explicit and fails before execution if the companion or
  capability contract is unavailable.
- Callback/reactive strategies and generic portfolio, basket, arbitrage, and
  options endpoints remain Python routes. Installing the companion does not
  expand their domain contract.
- `QUANTBT_DISABLE_NATIVE=1` and
  `QUANTBT_NATIVE_PROMOTION_MAX=explicit_only` are deterministic local
  rollback controls.

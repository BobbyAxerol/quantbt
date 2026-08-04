# QuantBT TestPyPI RC Checklist

This checklist is the final handoff for `quantbt-engine`. It is deliberately
separate from the native wheel decision: the core Python package can be tested
and released while `quantbt-native` remains experimental.

## Before The Workflow

1. Work from a release commit, not `dev`.
2. Set `project.version` in `pyproject.toml` to an unused RC version, for
   example `1.0.7rc2`.
3. Keep `CHANGELOG.md` and the release notes aligned with that version.
4. Create the matching tag, for example `v1.0.7rc2`.
5. Configure the pending TestPyPI publisher:
   `BobbyAxerol/quantbt`, workflow `publish-testpypi.yml`, environment
   `testpypi`.

The workflow refuses a tag that does not equal `v{project.version}`. Do not
upload a final `1.0.7` artifact under an RC tag.

## Workflow Gate

Push the matching `v*rc*` tag to trigger **Publish quantbt-engine to TestPyPI**
automatically, or run the same workflow manually with the exact tag in the
`ref` input. Before upload, CI performs:

- Python regression and package build (the two external-data `test_real*.py`
  scripts are intentionally excluded from portable CI);
- `twine check`;
- tracked-secret scan and archive allowlist scan;
- clean wheel install, import from `/tmp`, and `pip check`;
- clean sdist install, import from `/tmp`, and `pip check`;
- release manifest creation with commit SHA and artifact SHA256 values.

The workflow uploads the distributions and the manifest as separate artifacts.
Only `.whl` and `.tar.gz` files are sent to TestPyPI.

## Record The Evidence

Archive the downloaded `release-manifest.json` and record:

```text
git_sha:
git_ref:
distribution:
version:
wheel name + sha256:
sdist name + sha256:
Python matrix:
portable pytest result (excluding `test_real*.py`):
native-event parity result:
RSS/benchmark artifact:
auto backend policy: Python
native extra policy: empty
```

## Install From TestPyPI

Use a fresh environment and the public PyPI index as a dependency fallback:

```bash
python3 -m venv /tmp/quantbt-testpypi-smoke
/tmp/quantbt-testpypi-smoke/bin/python -m pip install --upgrade pip
/tmp/quantbt-testpypi-smoke/bin/python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  quantbt-engine==1.0.7rc2
(cd /tmp && /tmp/quantbt-testpypi-smoke/bin/python -c \
  "import quantbt; print(quantbt.__file__)")
/tmp/quantbt-testpypi-smoke/bin/python -m pip check
```

Verify that `quantbt.__file__` points into the temporary environment's
`site-packages`, not the repository checkout. Run one representative endpoint
smoke and compare its metadata/config with the local artifact run.

## Production Handoff

Only after the RC is inspected:

1. Set the final version and changelog entry.
2. Merge the verified commit to protected `main`.
3. Create the matching final tag and GitHub Release.
4. Let `publish.yml` build and test the exact release ref.
5. Approve the protected `pypi` environment only after reviewing the artifact
   manifest and release notes.

Do not publish `quantbt-native` from this flow. `backend="auto"` remains
Python and explicit Rust remains an opt-in local/CI capability until its public
wheel matrix and native release gate are separately approved.

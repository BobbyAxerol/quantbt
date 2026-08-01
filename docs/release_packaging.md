# QuantBT Packaging And Release

This document records the Phase 42C release contract for `quantbt-engine`.

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
- The first package release line is `0.1.x`, meaning Python behavior unchanged.

## CI Contract

The main CI workflow runs on pull requests and pushes to `dev` and `main`.

Required checks:

- Python matrix: `3.11`, `3.12`, `3.13`.
- `uv sync --all-extras --dev`.
- `uv run pytest -q`.
- `uv build`.
- Clean wheel install in a fresh virtual environment.
- Public import smoke from outside the repository root.
- Pool Alpha style import smoke.

CI must not rely on `PYTHONPATH` to pretend the package is installed.

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
pyproject.toml version = 0.1.0
required release tag  = v0.1.0
```

The publish workflow fails if the tag does not match.

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
quantbt-engine = "^0.1.0"
```

Alpha/notebook imports do not change:

```python
from quantbt import QuantBTEndpoint
```

## Native Package Note

`quantbt-native` is not published in Phase 42C.

## Native R0 Scaffold

Phase 44A adds a local `rust/native_event` PyO3 crate named
`quantbt-native`. Its module, `_quantbt_native`, is deliberately import-only:
it publishes version and capability metadata but does not execute orders.

For local Rust validation once the Rust toolchain and Maturin are installed:

```bash
cd rust/native_event
cargo fmt --check
cargo clippy -- -D warnings
cargo test
maturin build --release
```

`QUANTBT_NATIVE_BACKEND=auto` and `python` continue using the existing Python
Native Event implementation. `rust` is explicit and fails clearly until a
future certified Rust execution slice is available; it is never auto-enabled
by this R0 scaffold.

Native publishing must wait until the Phase 44 PyO3 package exists, builds, and
passes Python/Rust parity. The native workflow must either build/install
`quantbt-engine` from the same release tag or download a verified core wheel
artifact before testing native wheels.

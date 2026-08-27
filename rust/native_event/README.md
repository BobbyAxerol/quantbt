# quantbt-native

`quantbt-native` is the PyO3/Rust accelerator companion to `quantbt-engine`.
Phase 55A prepares its first public Linux wheel release; it is not published
until the Phase 55B TestPyPI/PyPI consumer gate passes.

## Scope

The current wheel supports the certified single-symbol static explicit-order
tape path used by `native_backend="rust"`. Python remains the canonical
full-featured and default backend. Unsupported features fail fast rather than
silently falling back:

- multi-symbol execution;
- funding and liquidation;
- unsupported quantity and lifecycle policies;
- reactive per-bar strategy callbacks.

The Rust distribution version and native API version are separate contracts.
The release-candidate distribution is `0.4.1` and advertises Native Event API
`0.4`. It targets pre-built `manylinux_2_17_x86_64` wheels for CPython 3.11,
3.12, and 3.13 only. It never asks an end user to compile Rust locally.

## Local build

From the repository root:

```bash
cargo fmt --check --manifest-path rust/native_event/Cargo.toml
cargo test --manifest-path rust/native_event/Cargo.toml
maturin build --release --manifest-path rust/native_event/Cargo.toml
```

Install the resulting wheel together with the matching local `quantbt-engine`
wheel, then run the focused Rust/Python parity and RSS tests. Do not enable a
native extra or `native_backend="auto"` based on a local build alone.

## Release gate

A future native release requires CPython 3.11, 3.12, and 3.13 manylinux wheels,
installed-wheel parity, fallback checks, and incremental RSS certification.
Until Phase 55B publishes the companion, the current public core release stays
on Python. The pending next core patch will declare the matching native wheel
as a Linux x86_64 runtime dependency; unsupported platforms remain Python.

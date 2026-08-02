# quantbt-native

`quantbt-native` is the experimental PyO3/Rust accelerator companion to
`quantbt-engine`. It is not part of the core package release yet.

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
The current crate distribution is `0.4.0` and advertises Native Event API
`0.4`; this does not imply that a `quantbt-native` PyPI release is available.

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
Until all gates pass, the core PyPI package intentionally leaves its `native`
extra empty and keeps `auto` on Python.

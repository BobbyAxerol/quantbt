"""Exact additive witness allowlist; remaining financial Rust stays locked."""


def without_qms06_witness(source, name):
    additions = {
        "rust/crates/quantbt-engine/src/metrics_v2.rs": (
            (b"    pub initial_mark_equity: f64,\n", 1),
            (b"    initial_mark_equity: Option<f64>,\n", 1),
            (b"            initial_mark_equity: None,\n", 1),
            (b"        self.initial_mark_equity.get_or_insert(equity);\n", 1),
            (
                b"            initial_mark_equity: self.initial_mark_equity.unwrap_or(f64::NAN),\n",
                1,
            ),
        ),
        "rust/native_event/Cargo.toml": (
            (b"qms-prepared-witness-candidate = []\n", 1),
        ),
        "rust/native_event/src/lib.rs": (
            (
                b'    #[cfg(feature = "qms-prepared-witness-candidate")]\n'
                b'    module.add(\n        "QMS_PREPARED_METRIC_SUPPORT_V1",\n'
                b'        "same-pass-ddof1-daily-first-mark-v1",\n    )?;\n',
                1,
            ),
        ),
        "rust/native_event/src/prepared_evaluation.rs": (
            (b"    sample_variance: f64,\n    initial_mark_equity: f64,\n", 1),
            (
                b"            sample_variance: f64::NAN,\n            initial_mark_equity: f64::NAN,\n",
                1,
            ),
            (
                b"        sample_variance: metrics.variance,\n        initial_mark_equity: metrics.initial_mark_equity,\n",
                2,
            ),
        ),
    }
    for text, count in additions.get(name, ()):
        if source.count(text) != count:
            raise AssertionError(f"unregistered witness-source change: {name}")
        source = source.replace(text, b"")
    if name == "rust/native_event/src/prepared_evaluation.rs":
        start = source.index(
            b'    #[cfg(feature = "qms-prepared-witness-candidate")]\n'
        )
        stop = source.index(b"    fn errors(&self)", start)
        method = source[start:stop]
        # Only the reviewed detached getter, never arbitrary hidden execution.
        from hashlib import sha256

        if (
            sha256(method).hexdigest()
            != "ef3d8908115083932cecdb58374d08c667a07381c0f7db6d93d69669299c59ea"
        ):
            raise AssertionError("unregistered prepared witness getter change")
        source = source[:start] + source[stop:]
    return source

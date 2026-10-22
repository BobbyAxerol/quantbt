"""Exact additive witness allowlist; remaining financial Rust stays locked."""


def without_qms06_witness(source, name):
    if name == "src/quantbt/backends/native_event.py":
        additions = (
            b"        retain_score_metrics: bool = False,\n",
            b"            retain_score_metrics=bool(retain_score_metrics),\n",
            b"        metric_witness_trading_days: int | None = None,\n",
            b"            retain_score_metrics=metric_witness_trading_days is not None,\n",
            b"            score_trading_days=metric_witness_trading_days or 365,\n",
            b"        _metric_witness_trading_days: int | None = None,\n",
            b"                metric_witness_trading_days=_metric_witness_trading_days,\n",
            b'        if metric_witness_trading_days is not None:\n'
            b'            runtime_metadata["same_pass_score"] = {\n'
            b'                key: value for key, value in payload.items()\n'
            b'                if key.startswith("score_") or key == "total_turnover"\n'
            b'            }\n',
        )
        if additions[0] in source:
            for addition in additions:
                if source.count(addition) != 1:
                    raise AssertionError("unregistered W3 native boundary change")
                source = source.replace(addition, b"")
    if name == "src/quantbt/backends/_native_event_rust.py":
        # Authorized local W3 plumbing enables the existing same-pass reducer;
        # no matcher, lifecycle or accounting arithmetic is exempted.
        additions = b"        retain_score_metrics: bool = False,\n"
        old = b"            scalar_metrics=self.scalar_score,\n"
        new = b"            scalar_metrics=self.scalar_score or bool(retain_score_metrics),\n"
        if additions in source or new in source:
            if source.count(additions) != 1 or source.count(new) != 1:
                raise AssertionError("unregistered W3 same-pass reducer change")
            source = source.replace(additions, b"").replace(new, old)
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

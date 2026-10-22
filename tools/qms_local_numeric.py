"""Matched float64 geometry measurements; no alpha, market or release actions."""

import json
from pathlib import Path
from statistics import median
from time import perf_counter

import numpy as np
import _quantbt_native as native

from quantbt.optimization.meta_selection.numerics import reference_fit
from quantbt.optimization.meta_selection.telemetry import observed_threads


def run():
    rows = []
    rng = np.random.default_rng(731)
    for n, d in ((180, 8), (4096, 8), (4096, 24), (512, 64), (16384, 8)):
        v = rng.normal(size=(n, d))
        y, w = rng.normal(size=n), np.ones(n) / n
        expected = reference_fit(v, y, w, 10.)
        actual = native.qms_fit_v1(v, y, w, 10.)
        for a, b in zip(actual, expected):
            np.testing.assert_allclose(np.asarray(a).reshape(b.shape), b, rtol=1e-9, atol=1e-10)
        times = {}
        for name, f in (("rust", lambda: native.qms_fit_v1(v, y, w, 10.)),
                        ("numpy_blas", lambda: reference_fit(v, y, w, 10.))):
            f()
            samples = []
            for _ in range(9):
                start = perf_counter()
                for _ in range(10):
                    f()
                samples.append((perf_counter() - start) / 10)
            times[name] = median(samples)
        rows.append(dict(n=n, d=d, parity=True, warm_median_seconds=times,
                         rust_over_numpy=times["rust"] / times["numpy_blas"]))
    return dict(schema="qms-local-numeric-v1", native_version=native.version(),
                threads=observed_threads(configured=dict(blas_threads=1, openmp_threads=1), native_serial=True),
                repetitions=9, calls_per_repetition=10, rows=rows)


if __name__ == "__main__":
    value = run()
    path = Path("data/local/qms-real-review/debt-closure/numeric.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value, indent=2))

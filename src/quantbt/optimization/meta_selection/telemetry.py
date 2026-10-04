"""Observe loaded math runtimes without equating requests with observations."""

import os
import sys


def observed_threads(*, configured=None, native_serial=None):
    observed, reasons = {}, []
    try:
        from threadpoolctl import threadpool_info

        observed["libraries"] = [{k: row.get(k) for k in
            ("user_api", "internal_api", "num_threads", "version", "prefix")}
            for row in threadpool_info()]
    except ImportError:
        observed["libraries"] = None
        reasons.append("THREADPOOLCTL_NOT_INSTALLED")
    module = sys.modules.get("numba")
    observed["numba_threads"] = module.get_num_threads() if module is not None else None
    observed["native_workers"] = 1 if native_serial is True else None
    observed["native_worker_basis"] = "qualified_serial_numeric_contract" if native_serial else "not_observed"
    configured = dict(configured or {})
    mismatches = []
    for row in observed["libraries"] or ():
        key = "blas_threads" if row["user_api"] == "blas" else "openmp_threads"
        if key in configured and row["num_threads"] != configured[key]:
            mismatches.append(dict(runtime=row["prefix"], configured=configured[key], observed=row["num_threads"]))
    if "numba_threads" in configured and observed["numba_threads"] is not None:
        if configured["numba_threads"] != observed["numba_threads"]:
            mismatches.append(dict(runtime="numba", configured=configured["numba_threads"],
                                   observed=observed["numba_threads"]))
    return dict(configured=configured, observed=observed, mismatches=mismatches,
                inspection_limits=reasons, environment={key: os.environ.get(key) for key in
                    ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMBA_NUM_THREADS")})

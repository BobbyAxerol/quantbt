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
    if configured is None:
        configured = {}
        for key, variables in (("blas_threads", ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")),
                ("openmp_threads", ("OMP_NUM_THREADS",)), ("numba_threads", ("NUMBA_NUM_THREADS",))):
            values = [os.environ[v] for v in variables if v in os.environ]
            if values and all(v.isdecimal() and int(v) > 0 for v in values):
                if len({int(v) for v in values}) == 1:
                    configured[key] = int(values[0])
                else:
                    reasons.append("CONFLICTING_" + key.upper() + "_ENVIRONMENT")
            elif values:
                reasons.append("UNRESOLVED_" + key.upper() + "_ENVIRONMENT")
    configured = dict(configured)
    mismatches = []
    for row in observed["libraries"] or ():
        key = "blas_threads" if row["user_api"] == "blas" else "openmp_threads"
        if key in configured and row["num_threads"] != configured[key]:
            mismatches.append(dict(runtime=row["prefix"], configured=configured[key], observed=row["num_threads"]))
    if "numba_threads" in configured and observed["numba_threads"] is not None:
        if configured["numba_threads"] != observed["numba_threads"]:
            mismatches.append(dict(runtime="numba", configured=configured["numba_threads"],
                                   observed=observed["numba_threads"]))
    observed["pool_measurement"] = "pool_capacity_not_active_thread_utilization"
    return dict(configured=configured, observed=observed, mismatches=mismatches,
                inspection_limits=reasons, environment={key: os.environ.get(key) for key in
                    ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMBA_NUM_THREADS")})

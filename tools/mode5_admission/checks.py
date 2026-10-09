"""Retain real subprocess results, including failed admission checks."""

import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from tools.mode5_baseline.isolation import file_identity, write_json


def check(root, output: Path, sources, name, *, env=None, timeout=600):
    if Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("check name must be a single new path component")
    scratch = root / ".maturin/mode5-m502/jit" / output.name
    scratch.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "pytest", "-q", *map(str, sources),
               "-p", "no:cacheprovider", f"--basetemp={scratch / name}",
               f"--junitxml={output / (name + '.xml')}"]
    return run_retained(root, output, command, sources, name, env=env, timeout=timeout)


def run_retained(root, output, command, sources, name, *, env=None, timeout=600):
    if Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("check name must be a single new path component")
    if (output / (name + ".json")).exists():
        raise ValueError("check receipt already exists")
    scratch = root / ".maturin/mode5-m502/jit" / output.name
    scratch.mkdir(parents=True, exist_ok=True)
    private = root / "upgrade/local/mode5_upgrade_v1/m5-02"
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root), str(private))),
        "NUMBA_CACHE_DIR": str(scratch / "numba"), "OPENBLAS_NUM_THREADS": "1",
        "NUMBA_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "M5_ATTEMPT": output.name,
        "M5_PILOT_RUN": name,
        **(env or {})}
    start = perf_counter()
    identities = [file_identity(Path(source)) for source in sources]
    try:
        result = subprocess.run(command, cwd=root, env=environment, capture_output=True,
                                text=True, timeout=timeout)
        receipt = dict(command=command, exit_code=result.returncode, stdout=result.stdout,
                       stderr=result.stderr, wall_seconds=perf_counter()-start,
                       sources=identities,
                       sources_unchanged=identities == [file_identity(Path(source)) for source in sources])
    except subprocess.TimeoutExpired as exc:
        receipt = dict(command=command, exit_code=None, wall_seconds=perf_counter()-start,
                       stdout=str(exc.stdout), stderr=str(exc.stderr), status="TIMED_OUT", sources=identities)
    if receipt.get("sources_unchanged") is False:
        receipt["status"] = "SOURCE_CHANGED_DURING_RUN"
        receipt["exit_code"] = 1
    write_json(output / (name + ".json"), receipt)
    return receipt

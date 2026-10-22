"""Current-source E08 regression, retaining historical failures and exact N/A cells."""

import argparse
import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET

from tools.qms_pre06_regression import ACCOUNT, EXTERNAL, EXTENSION, PLOT, PYTHON
from tools.qms_pre05_qualification import REGISTERED_NA, passed_cases
from tools.qms_e08_source_guard import ROOT, verify
from tools.qms_e08_package import LANE as PACKAGE
from tools.qms_installed_execution import digest

LANE = PACKAGE.parents[1]


def commands():
    return {
        "meta": [PYTHON, "-m", "pytest", "-q", "tests/meta_selection",
            "--ignore=tests/meta_selection/test_g01_study_replay.py"],
        "meta-repair": [PYTHON, "-m", "pytest", "-q", *("tests/meta_selection/"+n for n in (
            "test_pre_e06_06_exit.py", "test_pre_e06_06_artifacts.py", "test_e08_cleanup.py",
            "test_e08_closure.py", "test_e08_source_guard.py", "test_pre_e06_05_guard.py"))],
        "wfo": [PYTHON, "-m", "pytest", "-q", *("tests/"+n+".py" for n in EXTERNAL), "-k", "not "+PLOT],
        "account": [PYTHON, "-m", "pytest", "-q", *("tests/"+n+".py" for n in ACCOUNT)],
        "plot": [ROOT/".venv/bin/python", "-m", "pytest", "-q", "tests/test_walkforward_phase1.py::"+PLOT],
    }


def run(shards, attempt):
    if not attempt.isalnum() or len(shards) != len(set(shards)):
        raise ValueError("unique shards and fresh alphanumeric attempt required")
    guard = verify()
    for label in shards:
        command = commands()[label]
        stem = LANE/(label+"-regression-"+attempt)
        paths = [stem.with_suffix(s) for s in (".xml", ".log", ".json")]
        if any(p.exists() for p in paths):
            raise ValueError("refuse regression evidence overwrite")
        registration = dict(command=list(map(str, command)), source_guard=guard,
            admitted_na=sorted(REGISTERED_NA) if label == "meta" else [],
            private_study_excluded="test_g01_study_replay.py", publication=False)
        with stem.with_suffix(".registration.json").open("x") as stream:
            json.dump(registration, stream, indent=2, sort_keys=True)
        environment = dict(os.environ, PYTHONPATH="src:.", OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMBA_NUM_THREADS="1", MPLBACKEND="Agg",
            QMS06_NATIVE_EXTENSION=str(EXTENSION), QMS06_NATIVE_VERSION="0.4.3")
        start = time.perf_counter()
        with paths[1].open("x") as stream:
            stream.write("$ "+" ".join(map(str, command))+"\n")
            stream.flush()
            process = subprocess.run([*map(str, command), "--junitxml="+str(paths[0])],
                cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        receipt = dict(returncode=process.returncode, elapsed_seconds=time.perf_counter()-start,
            log_sha256=digest(paths[1]), xml_sha256=digest(paths[0]) if paths[0].exists() else None,
            publication=False)
        if not process.returncode:
            cases = passed_cases(paths[0], admitted_na=REGISTERED_NA if label == "meta" else frozenset())
            receipt.update(distinct_pass=len(cases), cases=sorted(cases),
                admitted_skips=sum(c.find("skipped") is not None for c in ET.parse(paths[0]).iter("testcase")))
        with paths[2].open("x") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
        if process.returncode:
            raise ValueError(f"failed regression retained: {paths[1]}")
        if guard != verify():
            raise ValueError("runtime changed during regression")
        print(json.dumps(dict(shard=label, distinct_pass=receipt["distinct_pass"],
            admitted_skips=receipt["admitted_skips"], publication=False)), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards", nargs="+", choices=tuple(commands()), default=list(commands()))
    parser.add_argument("--attempt", required=True)
    args = parser.parse_args()
    run(args.shards, args.attempt)

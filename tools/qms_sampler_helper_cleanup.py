"""Reclaim only this phase's reviewed inactive environments; retain all evidence."""

import argparse
from hashlib import sha256
import json
import os
import shutil
import subprocess

from tools.qms_pre06_contract import core_inventory, native_reuse, write_once
from tools.qms_pre06_package import NATIVE
from tools.qms_sampler_helper_diagnostic import LANE, PRIVATE, ROOT, registration


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main(host_checked):
    if not host_checked:
        raise ValueError("host process inspection required; sandbox ps is insufficient")
    registration()
    output = LANE / "cleanup.json"
    if output.exists():
        raise ValueError("refuse cleanup receipt overwrite")
    paths = []
    for version in ("package-v1", "package-v2"):
        for name in ("build-env", "pair", "sdist", "stage/build"):
            path = LANE / version / "cp312" / name
            if not path.exists():
                continue
            if path.is_symlink() or path.resolve() != path:
                raise ValueError("symlinked cleanup path")
            subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=ROOT, check=True)
            if name != "stage/build" and not (path / "pyvenv.cfg").is_file():
                raise ValueError("cleanup root is not a registered virtualenv")
            paths.append(path)
    source = core_inventory(ROOT / "src/quantbt")
    reuse = native_reuse(NATIVE)
    protected = {p.relative_to(ROOT).as_posix(): digest(p)
                 for root in (LANE, PRIVATE) for p in root.rglob("*")
                 if p.is_file() and not any(path in p.parents for path in paths)}
    protected[NATIVE.relative_to(ROOT).as_posix()] = digest(NATIVE)
    before = os.statvfs(ROOT)
    for path in paths:
        shutil.rmtree(path)
    for name, expected in protected.items():
        if digest(ROOT / name) != expected:
            raise ValueError("protected scientific evidence changed during cleanup")
    if core_inventory(ROOT / "src/quantbt") != source or native_reuse(NATIVE) != reuse:
        raise ValueError("source/native changed during cleanup")
    registration()
    after = os.statvfs(ROOT)
    free_before, free_after = before.f_bavail * before.f_frsize, after.f_bavail * after.f_frsize
    receipt = dict(schema="qms-sampler-helper-cleanup-v1", status="PASS", host_inactivity_checked=True,
                   host_check="2026-10-07 ps -eo pid,ppid,comm,args; no helper build/consumer process remained",
                   removed=[p.relative_to(ROOT).as_posix() for p in paths],
                   protected_sha256=protected, protected_files=len(protected), core_modules=len(source),
                   core_and_native_unchanged=True, free_bytes_before=free_before, free_bytes_after=free_after,
                   reclaimed_bytes=free_after - free_before, free_inodes_after=after.f_favail,
                   original_budget_bytes=1024**3,
                   operational_variance="~1.70 GiB observed filesystem increase across failed and successful lanes; UV hardlink failure caused copies",
                   future_package_budget_bytes=2 * 1024**3, safety_headroom_bytes=5 * 1024**3,
                   retained="all failed/successful logs, registrations, source stages, raw scientific arrays, exact artifacts, main tooling and offline cache",
                   reinstall_required="package-v1/v2 build and consumer environments; historical proof stays valid, rerun requires new lane",
                   publication=False)
    write_once(output, receipt)
    print(json.dumps(dict(status="PASS", protected=len(protected), reclaimed_mib=(free_after - free_before) / 1024**2)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-inactivity-checked", action="store_true")
    main(parser.parse_args().host_inactivity_checked)

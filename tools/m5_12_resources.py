"""Bounded resource admission for a serial local M5-12 consumer plan."""

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path


MIB = 1024**2
GIB = 1024**3


@dataclass(frozen=True)
class LocalQualificationBudget:
    consumer_environment_bytes: int = 576*MIB
    core_build_and_artifacts_bytes: int = 96*MIB
    fixture_and_jit_bytes: int = 128*MIB
    logs_and_incremental_headroom_bytes: int = 96*MIB
    disk_reserve_bytes: int = 5*GIB
    memory_reserve_bytes: int = 512*MIB
    consumer_peak_rss_bytes: int = 640*MIB
    max_owned_consumers: int = 1
    fresh_native_build: bool = False

    def __post_init__(self):
        for key,value in asdict(self).items():
            if key not in {"fresh_native_build", "max_owned_consumers"} and (type(value) is not int or value<=0):
                raise ValueError("resource byte budgets must be positive integers")
        if self.max_owned_consumers != 1 or self.fresh_native_build is not False:
            raise ValueError("this admission covers one consumer and no fresh native build only")
        if self.disk_reserve_bytes < 5*GIB:
            raise ValueError("the shared 5 GiB disk reserve cannot be reduced")

    @property
    def peak_incremental_bytes(self):
        return (self.consumer_environment_bytes+self.core_build_and_artifacts_bytes+
                self.fixture_and_jit_bytes+self.logs_and_incremental_headroom_bytes)

    def assess(self, *, available_bytes, available_memory_bytes):
        disk_ok = available_bytes >= self.disk_reserve_bytes+self.peak_incremental_bytes
        memory_ok = available_memory_bytes >= self.memory_reserve_bytes+self.consumer_peak_rss_bytes
        return dict(schema="quantbt.m5-12.resource_admission.v1", budget=asdict(self),
                    peak_incremental_bytes=self.peak_incremental_bytes, available_bytes=available_bytes,
                    available_memory_bytes=available_memory_bytes, disk_fits=disk_ok, memory_fits=memory_ok,
                    resource_budget_fits=disk_ok and memory_ok, full_m5_12_launch_authorized=False,
                    scope="serial core build/one consumer at a time; exact retained native reuse requires independent artifact qualification",
                    exclusions=["fresh native compilation", "legacy four retained consumers", "parallel consumers", "new research optimization"])


def inspect(root, budget=None):
    budget = budget or LocalQualificationBudget()
    stat = os.statvfs(root)
    mem = {row.split(":",1)[0]:row.split(":",1)[1].strip().split() for row in Path("/proc/meminfo").read_text().splitlines()}
    if "MemAvailable" not in mem or mem["MemAvailable"][1] != "kB":
        raise ValueError("Linux MemAvailable in kB is required; do not infer available RAM from total memory")
    result = budget.assess(available_bytes=stat.f_bavail*stat.f_frsize,
                           available_memory_bytes=int(mem["MemAvailable"][0])*1024)
    result["available_inodes"] = stat.f_favail
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args()
    result = inspect(args.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(not result["resource_budget_fits"])


if __name__ == "__main__":
    raise SystemExit(main())

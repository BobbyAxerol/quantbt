"""Fresh native receipts cannot borrow old source, binary or build identities."""
from copy import deepcopy
from hashlib import sha256
from zipfile import ZipFile

import pytest

from tools import m5_12_native_build as build


@pytest.mark.parametrize("defect", (None, "source", "after", "wheel", "extension", "log", "exit",
                                  "jobs", "features", "flags", "toolchain", "promoted"))
def test_fresh_native_build_requires_exact_successful_source_and_artifact(tmp_path, monkeypatch, defect):
    lane = tmp_path / "lane"
    lane.mkdir()
    wheel = lane / "quantbt_native.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("_quantbt_native/extension.so", b"SYNTHETIC_NOT_EXECUTED")
    log = lane / "native-build.log"
    log.write_bytes(b"synthetic successful build log")
    sources = {"rust/Cargo.lock": "a" * 64}
    monkeypatch.setattr(build, "ROOT", tmp_path)
    monkeypatch.setattr(build, "native_sources", lambda: sources)
    value = dict(schema="quantbt.m5_12.fresh_native_build.v1",
        policy="FRESH_APPROVED_ACCEPTED_POSITION_PARITY", sources=sources, source_after=deepcopy(sources),
        command=["/tool/maturin", "build", "--release", "--locked", "--offline", "--manifest-path", "Cargo.toml"],
        jobs=1, features="cargo_default", publication=False, returncode=0,
        wheel_sha256=sha256(wheel.read_bytes()).hexdigest(),
        extension_sha256=sha256(b"SYNTHETIC_NOT_EXECUTED").hexdigest(),
        log="lane/native-build.log", log_sha256=sha256(log.read_bytes()).hexdigest(),
        rustc="synthetic rustc", maturin="synthetic maturin", python="synthetic python")
    if defect == "source": value["sources"] = {}
    elif defect == "after": value["source_after"] = {}
    elif defect == "wheel": value["wheel_sha256"] = "0" * 64
    elif defect == "extension": value["extension_sha256"] = "0" * 64
    elif defect == "log": value["log_sha256"] = "0" * 64
    elif defect == "exit": value["returncode"] = 1
    elif defect == "jobs": value["jobs"] = 4
    elif defect == "features": value["features"] = "custom"
    elif defect == "flags": value["command"].append("--all-features")
    elif defect == "toolchain": value["rustc"] = ""
    elif defect == "promoted": value["publication"] = True
    if defect:
        with pytest.raises(ValueError): build.verify_native_build(value, wheel, lane)
    else:
        assert build.verify_native_build(value, wheel, lane)

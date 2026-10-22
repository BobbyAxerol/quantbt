from hashlib import sha256
from pathlib import Path
import zipfile

import pytest
import yaml

from tools.ci_native_identity import verify


@pytest.fixture
def wheel(tmp_path):
    path = tmp_path / "quantbt_native-0.4.3-cp312-cp312-manylinux_2_17_x86_64.whl"
    payload = b"synthetic native fixture"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("_quantbt_native/_quantbt_native.cpython-312-x86_64-linux-gnu.so", payload)
        archive.writestr("quantbt_native-0.4.3.dist-info/METADATA", "Name: quantbt-native\nVersion: 0.4.3\n")
    prefix = tmp_path / "env"
    loaded = prefix / "lib/python3.12/site-packages/_quantbt_native/native.so"
    loaded.parent.mkdir(parents=True)
    loaded.write_bytes(payload)
    return path, loaded, prefix, payload


def test_fresh_wheel_hash_not_a_tautology_of_loaded_extension(wheel):
    path, loaded, prefix, payload = wheel
    result = verify(path, loaded_path=loaded, loaded_version="0.4.3", expected_version="0.4.3", prefix=prefix)
    assert result["extension_sha256"] == sha256(payload).hexdigest()
    assert result["wheel_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert not result["publication"]
    loaded.write_bytes(b"stale same-version extension")
    with pytest.raises(ValueError, match="differs from workflow-built"):
        verify(path, loaded_path=loaded, loaded_version="0.4.3", expected_version="0.4.3", prefix=prefix)


@pytest.mark.parametrize("mutation", ("version", "declaration", "prefix", "metadata", "extension_count"))
def test_mismatched_or_unqualified_identity_fails_closed(wheel, mutation):
    path, loaded, prefix, _ = wheel
    version, declared = "0.4.3", "0.4.3"
    if mutation == "version":
        version = "0.4.2"
    elif mutation == "declaration":
        declared = "0.4.4"
    elif mutation == "prefix":
        prefix = prefix / "different"
    else:
        with zipfile.ZipFile(path, "a") as archive:
            if mutation == "metadata":
                archive.writestr("quantbt_native-0.4.3.dist-info/second.dist-info/METADATA", "Version: 0.4.3")
            else:
                archive.writestr("_quantbt_native/_quantbt_native.extra.so", b"extra")
    with pytest.raises(ValueError):
        verify(path, loaded_path=loaded, loaded_version=version, expected_version=declared, prefix=prefix)


def test_workflow_builds_default_native_before_core_tests_and_pins_its_bytes():
    workflow = yaml.safe_load((Path(__file__).parents[1] / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["package"]["steps"]
    names = [step.get("name") for step in steps]
    build = names.index("Build local native companion for dependency smoke")
    pin = names.index("Install and pin workflow-built native for core parity tests")
    assert build < pin < names.index("Test")
    assert names.count("Build local native companion for dependency smoke") == 1
    assert "--locked" in steps[build]["with"]["args"]
    assert "--features" not in steps[build]["with"]["args"]
    assert "tools.ci_native_identity" in steps[pin]["run"]


@pytest.mark.parametrize("filename,job,test_name,build_name", [
    ("publish.yml", "test", "Test", "Build local native companion for release regression"),
    ("native-release.yml", "certify-native-pair", "Full source regression and certified workload benchmarks", "Build native wheel"),
])
def test_release_regression_keeps_fresh_native_and_host_custody_contract(filename, job, test_name, build_name):
    path = Path(__file__).parents[1] / ".github/workflows" / filename
    steps = yaml.safe_load(path.read_text())["jobs"][job]["steps"]
    names = [step.get("name") for step in steps]
    pin_name = "Install and pin workflow-built native for release regression"
    pin = names.index(pin_name)
    assert names.index(build_name) < pin < names.index(test_name)
    assert names.index("Build isolated QMS regression fixtures") < pin
    assert "--locked" in steps[names.index(build_name)]["with"]["args"]
    assert "--reinstall --no-deps" in steps[pin]["run"]
    assert "tools.ci_native_identity" in steps[pin]["run"]
    assert '--github-env "$GITHUB_ENV"' in steps[pin]["run"]
    assert "--sudo-host-tests" in steps[names.index(test_name)]["run"]
    assert "--keep-going" in steps[names.index(test_name)]["run"]
    if filename == "native-release.yml":
        assert steps[pin]["if"] == steps[names.index(test_name)]["if"]


def test_identity_cli_exports_only_verified_wheel_hash(wheel, tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from tools import ci_native_identity as tool

    path, loaded, prefix, payload = wheel
    env, output = tmp_path / "github-env", tmp_path / "identity.json"
    monkeypatch.setitem(sys.modules, "_quantbt_native", SimpleNamespace(__file__=str(loaded)))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(tool.metadata, "version", lambda name: "0.4.3")
    monkeypatch.setattr(sys, "argv", ["ci_native_identity", "--wheel-dir", str(path.parent),
        "--github-env", str(env), "--output", str(output)])
    tool.main()
    assert env.read_text() == "QUANTBT_REPAIR_NATIVE_SHA256=" + sha256(payload).hexdigest() + "\n"
    import json
    assert json.loads(output.read_text())["extension_sha256"] == sha256(payload).hexdigest()
    with pytest.raises(FileExistsError):
        tool.main()

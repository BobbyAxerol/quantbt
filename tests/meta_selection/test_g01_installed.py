"""Exact installed metrics evidence must bind the rebuilt extension bytes."""

from hashlib import sha256
import json
import subprocess
from zipfile import ZipFile

import pytest

from tools import qms_g01_installed as installed


def lane(tmp_path, monkeypatch):
    wheel = tmp_path/"quantbt_native-0.4.3.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("_quantbt_native/_quantbt_native.so", b"rebuilt-native")
    proof = dict(core="1.1.2", native="0.4.3", artifact_refs=[dict(path=str(wheel))])
    (tmp_path/"proof.json").write_text(json.dumps(proof))
    monkeypatch.setattr(installed, "verify_pair", lambda p: None)
    return dict(schema="qms-g01-installed-metric-v1", checks=3, skipped=0,
        core_version="1.1.2", native_version="0.4.3", financial_profile_parity=True,
        sample_policy="legacy_zero_base_v1", publication=False,
        core_origin="/consumer/site-packages/quantbt/__init__.py",
        native_origin="/consumer/site-packages/_quantbt_native/_quantbt_native.so",
        native_sha256=sha256(b"rebuilt-native").hexdigest())


def test_g01_installed_both_lanes_bind_exact_extension_and_isolate_imports(tmp_path, monkeypatch):
    row = lane(tmp_path, monkeypatch)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        assert "-I" in command and "PYTHONPATH" not in kwargs["env"]
        return subprocess.CompletedProcess(command, 0, json.dumps(row), "")

    monkeypatch.setattr(installed.subprocess, "run", run)
    result = installed.qualify(tmp_path)
    assert len(commands) == 2 and set(result["consumers"]) == {"pair", "sdist"}
    assert result["package_proof_sha256"] and result["consumer_source_sha256"]
    with pytest.raises(ValueError, match="sealed"):
        installed.qualify(tmp_path)


@pytest.mark.parametrize("change", [dict(native_version="0.4.2"), dict(checks=0), dict(skipped=1),
    dict(sample_policy="native_skip_zero_base_v1"), dict(core_origin="/source/quantbt/__init__.py"),
    dict(native_sha256="unmatched")])
def test_g01_bad_consumer_never_seals_a_receipt(tmp_path, monkeypatch, change):
    row = {**lane(tmp_path, monkeypatch), **change}
    monkeypatch.setattr(installed.subprocess, "run", lambda command, **kwargs:
        subprocess.CompletedProcess(command, 0, json.dumps(row), ""))
    with pytest.raises(ValueError):
        installed.qualify(tmp_path)
    assert not (tmp_path/"installed-g01-proof.json").exists()
    assert (tmp_path/"installed-g01-proof/pair.log").is_file()


def test_g01_timeout_keeps_output_and_never_seals(tmp_path, monkeypatch):
    lane(tmp_path, monkeypatch)

    def timed_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 120, output=b"partial proof\n", stderr=b"unfinished\n")

    monkeypatch.setattr(installed.subprocess, "run", timed_out)
    with pytest.raises(ValueError, match="timed out"):
        installed.qualify(tmp_path)
    log = (tmp_path/"installed-g01-proof/pair.log").read_text()
    assert "partial proof" in log and "unfinished" in log and "TIMEOUT" in log
    assert not (tmp_path/"installed-g01-proof.json").exists()

"""Preflight, private input copies and immutable admission registration."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

from tools.mode5_baseline.isolation import (
    canonical_digest, copy_python_tree, copy_reviewed_files, file_identity,
    private_output, write_json,
)
from tools.mode5_baseline.runner import protected_snapshot


def prepare(root: Path, config_path: Path, attempt: str) -> dict:
    if Path(attempt).name != attempt or attempt in {"", ".", ".."}:
        raise ValueError("attempt must be one new path component")
    if subprocess.check_output(["git", "branch", "--show-current"], cwd=root, text=True).strip() == "main":
        raise ValueError("main is protected")
    free = shutil.disk_usage(root).free
    budget = 256 * 1024**2
    if free < 5 * 1024**3 + budget:
        raise ValueError("insufficient admission disk reserve")
    config = json.loads(config_path.read_text())
    outputs = root / "upgrade/private/mode5_upgrade_v1/m5-02"
    locals_ = root / "upgrade/local/mode5_upgrade_v1/m5-02"
    output = private_output(outputs / attempt, [outputs])
    copies = private_output(locals_ / attempt, [locals_])
    scratch = root / ".maturin/mode5-m502/jit" / attempt
    if scratch.exists() or scratch.is_symlink():
        raise ValueError("scratch must be a fresh registered lane")
    originals = sorted((root / "upgrade/alphas").rglob("*.py"))
    rsi = root / "data/local/qms-real-review/alpha.py"
    market = root / config["market"]
    tracked = subprocess.check_output(
        ["git", "ls-files", "--", "src", "rust", "contracts"], cwd=root, text=True
    ).splitlines()
    protected = [root / name for name in tracked if (root / name).is_file()]
    protected += originals + [rsi, market, config_path,
        root / "upgrade/QUANTBT_MODE5_UPGRADE_V1_DIAGNOSTICS_FIRST_GUIDE_VI.md"]
    snapshot = protected_snapshot(protected)
    output.mkdir(parents=True)
    write_json(output / "protected_before.json", snapshot)
    resources = dict(filesystem_free_bytes=free, free_inodes=os.statvfs(root).f_favail,
                     incremental_budget_bytes=budget, minimum_free_bytes=5 * 1024**3,
                     scratch=str(scratch), workers=1, threads=1, rebuild=False)
    write_json(output / "resource_registration.json", resources)
    copy_python_tree(root / "upgrade/alphas", copies / "alphas",
                     allowed_roots=[locals_], protected_roots=[root / "upgrade/alphas"])
    copy_reviewed_files([rsi], copies / "rsi", allowed_roots=[locals_], protected_roots=[rsi.parent])
    copy_reviewed_files([config_path], copies / "config", allowed_roots=[locals_])
    registration = dict(config=config, config_identity=file_identity(config_path),
                        market_identity=file_identity(market),
                        copies=str(copies), output=str(output), resources=resources,
                        source_sha=subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                          cwd=root, text=True).strip())
    registration["registration_id"] = canonical_digest(registration)
    write_json(output / "registration.json", registration)
    return registration

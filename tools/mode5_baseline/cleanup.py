"""Retain receipts and reclaim only an invocation's registered pytest scratch."""

from pathlib import Path
import shutil

from .isolation import file_identity, write_json


def verify_snapshot(snapshot: dict) -> None:
    for name, digest in snapshot.items():
        if file_identity(Path(name))["sha256"] != digest:
            raise ValueError(f"protected source changed: {name}")


def cleanup_workspace(output: Path, copies: Path, scratch: Path, snapshot: dict,
                      resource_plan: dict) -> dict:
    if str(scratch) != resource_plan["scratch"]:
        raise ValueError("scratch differs from registered ownership")
    if any(path.is_symlink() for path in (scratch, *scratch.parents)):
        raise ValueError("symlink scratch is forbidden")
    verify_snapshot(snapshot)
    receipts = {str(path): file_identity(path)["sha256"]
                for root in (output, copies) for path in root.rglob("*") if path.is_file()}
    cleanup = {"deleted": [], "retained": [str(output), str(copies)],
               "protected_hashes_verified": len(snapshot), "retained_receipts_verified": len(receipts)}
    if scratch.is_dir():
        if not shutil.rmtree.avoids_symlink_attacks:
            raise ValueError("safe scratch cleanup unsupported on this platform")
        cleanup["scratch_bytes"] = sum(path.stat().st_size for path in scratch.rglob("*")
                                       if path.is_file() and not path.is_symlink())
        cleanup["synthetic_symlinks_unlinked_not_followed"] = sum(path.is_symlink() for path in scratch.rglob("*"))
        shutil.rmtree(scratch)
        cleanup["deleted"] = [str(scratch)]
    verify_snapshot(snapshot)
    verify_snapshot(receipts)
    after = shutil.disk_usage(output)
    retained_bytes = sum(path.stat().st_size for root in (output, copies)
                         for path in root.rglob("*") if path.is_file())
    cleanup.update(free_bytes_before=resource_plan["filesystem_free_bytes"], free_bytes_after=after.free,
                   retained_payload_bytes=retained_bytes,
                   observed_free_change_bytes=after.free-resource_plan["filesystem_free_bytes"],
                   source_unchanged=True, receipts_unchanged=True)
    write_json(output / "cleanup_receipt.json", cleanup)
    if (retained_bytes > resource_plan["incremental_budget_bytes"]
            or after.free < resource_plan["minimum_free_bytes"]):
        raise ValueError("phase resource budget exceeded; cleanup receipt retained")
    return cleanup

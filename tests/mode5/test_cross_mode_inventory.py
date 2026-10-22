"""Independent integrity/retention counterexamples for cold archive readers."""

from dataclasses import asdict
import gzip
import json

import pytest

from tools.mode5_research.cross_mode.inventory import ArchiveReader, SnapshotWriter, coverage
from tools.mode5_research.cross_mode.join import join_task_revisions


def test_pinned_read_is_rechecked_after_source_replacement(tmp_path):
    path = tmp_path / "source.json"
    path.write_text('{"count": 3}')
    reader = ArchiveReader(tmp_path)
    assert reader.read(path) == {"count": 3}
    path.write_text('{"count": 7}')
    with pytest.raises(ValueError, match="changed within"):
        reader.read(path)


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"value":NaN}', '{"value":1e999}'])
def test_ambiguous_or_nonfinite_sources_fail(tmp_path, raw):
    (tmp_path / "source.json").write_text(raw)
    with pytest.raises(ValueError):
        ArchiveReader(tmp_path).read("source.json")


def test_gzip_decoded_budget_prevents_small_file_expansion(tmp_path):
    path = tmp_path / "source.json.gz"
    path.write_bytes(gzip.compress(json.dumps({"payload": "x" * 4000}).encode()))
    with pytest.raises(MemoryError, match="decoded-byte"):
        ArchiveReader(tmp_path, max_document_bytes=128).read(path)


def test_expected_receipt_hash_and_path_checked(tmp_path):
    (tmp_path / "a.json").write_text('{"n":3}')
    (tmp_path / "b.json").write_text('{"n":3}')
    reader = ArchiveReader(tmp_path)
    pin = asdict(reader.pin("a.json"))
    assert reader.read("a.json", expected=pin) == {"n": 3}
    with pytest.raises(ValueError, match="different file"):
        reader.read("b.json", expected=pin)
    with pytest.raises(ValueError, match="retained receipt"):
        reader.read("a.json", expected={**pin, "sha256": "0" * 64})


def test_reader_cannot_follow_source_symlink_outside_root(tmp_path):
    root = tmp_path / "inside"
    root.mkdir()
    outside = tmp_path / "external.json"
    outside.write_text('{}')
    (root / "alias.json").symlink_to(outside)
    with pytest.raises(ValueError, match="inside its root"):
        ArchiveReader(root).read("alias.json")


def test_decoded_bytes_bound_to_hash_even_if_two_pin_reads_report_old_payload(tmp_path, monkeypatch):
    path = tmp_path / 'source.json'
    path.write_text('{"n":1}')
    reader = ArchiveReader(tmp_path)
    original = reader.pin(path)
    path.write_text('{"n":2}')
    monkeypatch.setattr(reader, 'pin', lambda _: original)
    with pytest.raises(ValueError, match='decoded source bytes'):
        reader.read(path)


def test_outputs_are_append_only_and_budgeted(tmp_path):
    writer = SnapshotWriter(tmp_path, max_bytes=32)
    pin = writer.save("receipt.json", {"count": 3})
    assert pin.bytes == len(b'{"count":3}')
    with pytest.raises(FileExistsError):
        writer.save("receipt.json", {"count": 3})
    with pytest.raises(MemoryError):
        writer.save("huge.json", {"payload": "x" * 64})
    with pytest.raises(ValueError, match="outside"):
        writer.save("../escape.json", {})


def test_snapshot_verify_and_coverage_preserve_missingness(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text('{"status":"PENDING"}')
    reader = ArchiveReader(tmp_path)
    reader.read(path)
    assert reader.verify() == 1
    result = coverage([{"cell_id": "a", "status": "VALID", "value": 0.0},
                       {"cell_id": "b", "status": "MISSING", "value": None},
                       {"cell_id": "c", "status": "NO_TRADE", "value": None}])
    assert result == {"total": 3, "dispositions": {"VALID": 1, "MISSING": 1, "NO_TRADE": 1},
                      "independent_repetitions": None}
    with pytest.raises(ValueError, match="sentinel"):
        coverage([{"cell_id": "x", "status": "MISSING", "value": 0}])
    with pytest.raises(ValueError, match="distinct"):
        coverage([{"cell_id": "a", "status": "MISSING"}] * 2)
    with pytest.raises(ValueError, match='finite value'):
        coverage([{'cell_id': 'unmeasured', 'status': 'VALID'}])


def test_original_task_join_uses_identity_instead_of_source_list_order():
    tasks = [{'origin': '2022-01', 'source': 'a'}, {'origin': '2022-02', 'source': 'a'}]
    revisions = [{'task': tasks[1], 'label': 2}, {'task': tasks[0], 'label': 1}]
    assert [r['label'] for _,r in join_task_revisions(tasks, revisions)] == [1, 2]
    with pytest.raises(ValueError, match='missing'):
        join_task_revisions(tasks, revisions[:1])
    with pytest.raises(ValueError, match='multiple revisions'):
        join_task_revisions(tasks, revisions + revisions[:1])
    with pytest.raises(ValueError, match='no identical'):
        join_task_revisions(tasks, [{'task': {**tasks[0], 'source': 'altered'}}])

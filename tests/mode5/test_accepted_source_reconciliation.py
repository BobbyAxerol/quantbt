"""Exact already-approved source reconciliation; no engine/math amendment."""

from hashlib import sha256
import json
import subprocess

import pytest

from tools.mode5_accepted_source_guard import MANIFEST, ROOT, without_accepted_research_source
from tools.mode5_public_source_guard import without_continuous


MANIFEST_DATA = json.loads(MANIFEST.read_bytes())


@pytest.mark.parametrize('name', tuple(MANIFEST_DATA['sources']))
def test_only_exact_owner_accepted_source_normalizes_to_its_known_parent(name):
    item = MANIFEST_DATA['sources'][name]
    original = (ROOT / name).read_bytes()
    accepted = subprocess.check_output(['git', 'show', MANIFEST_DATA['owner_disposition']['commit'] + ':' + name], cwd=ROOT)
    parent = subprocess.check_output(['git', 'show', item['before_commit'] + ':' + name], cwd=ROOT)
    assert original == accepted
    assert without_accepted_research_source(original, name) == parent
    assert without_accepted_research_source(parent, name) == parent
    for invalid in (original + b'\n# unapproved\n', b'unrelated-source'):
        assert without_accepted_research_source(invalid, name) == invalid
    assert sha256(original).hexdigest() == item['accepted_sha256']


@pytest.mark.parametrize('name', ('src/quantbt/endpoint.py', 'src/quantbt/walkforward.py'))
def test_original_mode5_guard_still_rejects_arbitrary_mutation(name):
    with pytest.raises(AssertionError, match='unreviewed Mode5 public bytes'):
        without_continuous((ROOT / name).read_bytes() + b'\n# unapproved\n', name)


def test_unknown_paths_are_not_a_whitelist():
    source = b'unknown-source'
    assert without_accepted_research_source(source, 'not-an-admitted-path') == source


def test_metrics_guards_preserve_all_four_original_accessor_owner_paths():
    from tests.metrics.source_guard import assert_protected_bytes
    baseline = json.loads((ROOT / 'docs/metrics/evidence/met01/baseline.json').read_bytes())
    for name in MANIFEST_DATA['sources']:
        assert_protected_bytes(name, baseline['protected_sources'][name], (ROOT / name).read_bytes())

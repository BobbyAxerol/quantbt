"""Normalize exact already-accepted blobs for historical guards, not new code."""

from hashlib import sha256
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/diagnostics/evidence/m5-11-15-accepted-source.json'
MANIFEST_SHA256 = '03d3b35f729a7c0b670a84231e84de2b943961021517876b436128b08c056c3a'


def without_accepted_research_source(source, name):
    raw = MANIFEST.read_bytes()
    assert sha256(raw).hexdigest() == MANIFEST_SHA256, 'accepted-source manifest digest'
    manifest = json.loads(raw)
    item = manifest['sources'].get(name)
    if item is None:
        return source
    owner = manifest['owner_disposition']
    accepted = subprocess.check_output(['git', 'show', owner['commit'] + ':' + name], cwd=ROOT)
    before = subprocess.check_output(['git', 'show', item['before_commit'] + ':' + name], cwd=ROOT)
    assert sha256(accepted).hexdigest() == item['accepted_sha256'], 'accepted committed source bytes'
    assert sha256(before).hexdigest() == item['before_sha256'], 'accepted-source historical parent'
    approval = subprocess.check_output(['git', 'show', owner['commit'] + ':' + owner['path']], cwd=ROOT)
    assert sha256(approval).hexdigest() == owner['sha256'], 'committed owner scope acceptance'
    assert sha256((ROOT / owner['path']).read_bytes()).hexdigest() == owner['sha256'], 'current owner receipt changed'
    # Unknown/older bytes still go through the original strict guard. A suffix
    # or arbitrary newer blob is never repaired or accepted by AST similarity.
    return before if source == accepted else source

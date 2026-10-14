"""Exact reviewed public integration; older receipts are never rewritten."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/mode5/evidence/m5-10-source-amendment.json"
CONTINUOUS = ROOT / "docs/mode5/evidence/m5-11-continuous-event-source-amendment.json"
DECISION_REPORT = ROOT / "docs/mode5/evidence/m5-11-5-decision-report-source-amendment.json"
REPORT_HARDENING = ROOT / "docs/mode5/evidence/m5-11-5-decision-report-hardening-source-amendment.json"


def without_decision_report(source, name):
    hardening = json.loads(REPORT_HARDENING.read_text())
    prior = hardening["prior_amendment"]
    if sha256((ROOT / prior["path"]).read_bytes()).hexdigest() != prior["sha256"]:
        raise AssertionError("report hardening parent amendment changed")
    if name in hardening["existing"]:
        before = subprocess.check_output(["git", "show", hardening["entry"]+":"+name], cwd=ROOT)
        if source != before:
            if sha256(source).hexdigest() != hardening["existing"][name]:
                raise AssertionError("unreviewed Mode5 public bytes: "+name)
            source = before
    m = json.loads(DECISION_REPORT.read_text())
    prior = m["prior_amendment"]
    if sha256((ROOT / prior["path"]).read_bytes()).hexdigest() != prior["sha256"]:
        raise AssertionError("decision report parent amendment changed")
    if name in m["existing"]:
        before = subprocess.check_output(["git", "show", m["entry"]+":"+name], cwd=ROOT)
        if source == before:
            return source
        if sha256(source).hexdigest() != m["existing"][name]:
            raise AssertionError("unreviewed Mode5 public bytes: "+name)
        return before
    if name in m["new"]:
        if sha256(source).hexdigest() != m["new"][name]:
            raise AssertionError("unreviewed Mode5 public bytes: "+name)
        return b""
    return source


def without_continuous(source, name):
    m = json.loads(CONTINUOUS.read_text())
    if name in m["existing"]:
        before = subprocess.check_output(["git", "show", m["entry"]+":"+name], cwd=ROOT)
        if source == before:
            return source
        source = without_decision_report(source, name)
        if sha256(source).hexdigest() != m["existing"][name]:
            raise AssertionError("unreviewed Mode5 public bytes: "+name)
        return before
    source = without_decision_report(source, name)
    if name in m["new"]:
        if sha256(source).hexdigest() != m["new"][name]:
            raise AssertionError("unreviewed Mode5 public bytes: "+name)
        return b""
    return source


def without_mode5_public(source, name):
    m = json.loads(MANIFEST.read_text())
    if name not in m["mode5"]:
        return source
    old = subprocess.run(["git", "show", m["mode5_entry"]+":"+name], cwd=ROOT, capture_output=True)
    before = old.stdout if old.returncode == 0 else b""
    if source == before:
        return source
    if sha256(source).hexdigest() != m["mode5"][name]:
        raise AssertionError("unreviewed Mode5 public bytes: "+name)
    return before


def without_reporting(source, name):
    from tests.metrics.source_guard import ADMITTED, normalized
    m = json.loads(MANIFEST.read_text())
    if name not in ADMITTED and name not in m["reporting"]:
        return source
    old = subprocess.run(["git", "show", m["reporting_entry"]+":"+name], cwd=ROOT, capture_output=True)
    parent = old.stdout if old.returncode == 0 else b""
    if source == parent:
        return source
    if name == "src/quantbt/__init__.py":
        released = subprocess.check_output(["git", "show", "b8f167f:"+name], cwd=ROOT)
        if source == released:
            return source
    if name not in ADMITTED:
        if sha256(source).hexdigest() != m["reporting"][name]:
            raise AssertionError("unreviewed reporting module: "+name)
        return parent
    if normalized(source.decode(), name, changed=True) != normalized(parent.decode(), name, changed=False):
        raise AssertionError("unreviewed reporting addition: "+name)
    return parent


def without_public_additions(source, name):
    source = without_continuous(source, name)
    if not source:
        return source
    source = without_reporting(without_mode5_public(source, name), name)
    m = json.loads(MANIFEST.read_text())
    if name in m["sampler_helper"]:
        old = subprocess.run(["git", "show", m["sampler_helper_entry"]+":"+name], cwd=ROOT, capture_output=True)
        before = old.stdout if old.returncode == 0 else b""
        if source != before:
            if sha256(source).hexdigest() != m["sampler_helper"][name]:
                raise AssertionError("unreviewed sampler helper: "+name)
            source = before
    return source


def prior_names(names, entry):
    m = json.loads(MANIFEST.read_text())
    continuous = json.loads(CONTINUOUS.read_text())
    reports = json.loads(DECISION_REPORT.read_text())
    result = set(names)
    new = set(m["new_mode5"]) | {n for n in m["reporting"] if n.startswith("src/quantbt/metrics/")} | {"src/quantbt/optimization/sampler_space.py"}
    for name in set(names) & (set(m["mode5"]) | set(m["reporting"]) | set(m["sampler_helper"])
            | set(continuous["existing"]) | set(continuous["new"])
            | set(reports["existing"]) | set(reports["new"])):
        source = (ROOT / name).read_bytes()
        if name in reports["new"]:
            without_decision_report(source, name)
            old = subprocess.run(["git", "show", entry+":"+name], cwd=ROOT, capture_output=True)
            if old.returncode != 0:
                result.remove(name)
                continue
        if name in continuous["new"]:
            without_continuous(source, name)
            old = subprocess.run(["git", "show", entry+":"+name], cwd=ROOT, capture_output=True)
            if old.returncode != 0:
                result.remove(name)
                continue
        if name in new:
            if sha256(source).hexdigest() != (m["mode5"].get(name) or m["reporting"].get(name) or m["sampler_helper"].get(name)):
                raise AssertionError("unreviewed additive module: "+name)
            old = subprocess.run(["git", "show", entry+":"+name], cwd=ROOT, capture_output=True)
            if old.returncode != 0:
                result.remove(name)
                continue
        normalized = without_public_additions(source, name)
        old = subprocess.run(["git", "show", entry+":"+name], cwd=ROOT, capture_output=True)
        if old.returncode == 0 and normalized == old.stdout:
            result.remove(name)
    return result

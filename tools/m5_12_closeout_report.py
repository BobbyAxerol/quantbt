"""Render a hash-bound canonical M5-12 phase JSON without executing research."""

import argparse
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re

from tools.m5_12_traceability import MAX_BYTES, validate_phase_report


SECTIONS = (
    ("Status", ("schema", "phase_id", "status", "scientific_status", "next_phase_ready")),
    ("Source And Artifacts", ("source_identity", "input_artifacts", "protected_sources_unchanged")),
    ("Research Scope", ("alpha_scope", "hypotheses_tested", "data_roles")),
    ("Requirements And Traceability", ("requirements", "reuse_dispositions")),
    ("Test Runs", ("test_runs",)),
    ("Numeric Results And Matrices", ("numeric_results", "matrices")),
    ("Economic Interpretation", ("economic_interpretation",)),
    ("Proof Capability", ("proof_capability",)),
    ("Potential And Limitations", ("potential_assessment", "blocking_issues")),
    ("Performance", ("performance",)),
    ("Review And Reproduction", ("review", "reproduction")),
)
CONSUMER_COLUMNS = (
    ("kind", "Kind"),
    ("feature_cases", "Feature Cases"),
    ("execution_cases", "Execution Cases"),
    ("pct_cases", "Pct-Equity Cases"),
    ("integrated_families", "Integrated Families"),
    ("private_alpha_controls", "Private Alpha Controls"),
    ("representative_reports", "Representative Reports"),
    ("status", "Recorded Status"),
)


def _strict_json(raw):
    def unique(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError("duplicate JSON key: " + key)
            values[key] = value
        return values

    def invalid(value):
        raise ValueError("nonfinite JSON constant: " + value)

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    # Reject exponent overflow too, which parse_constant alone cannot detect.
    json.dumps(value, allow_nan=False)
    return value


def _block(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2, allow_nan=False)
    longest = max((len(run) for run in re.findall(r"`+", payload)), default=0)
    fence = "`" * max(3, longest + 1)
    return fence + "json\n" + payload + "\n" + fence


def _cell(value):
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)
    text = escape(text, quote=False).replace("\\", "\\\\")
    for marker in "`*_[]()!":
        text = text.replace(marker, "\\" + marker)
    return text.replace("|", "&#124;").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def _recorded_summary(report):
    rows = [("Phase Status", report["status"]), ("Scientific Status", report["scientific_status"]),
            ("Next Phase Ready", report["next_phase_ready"])]
    source = report["source_identity"]
    source_rows = [("source_identity." + key, source[key]) for key in (
        "source_commit", "runtime_source_commit", "current_source_commit", "tested_source_commit",
        "guard_source_commit", "branch") if isinstance(source, dict) and key in source]
    rows.extend(source_rows or [("source_identity", source)])
    lines = ["", "## Recorded Summary", "", "| Field | Recorded Value |", "| --- | --- |"]
    lines.extend("| " + _cell(key) + " | " + _cell(value) + " |" for key, value in rows)
    matrices = report["matrices"]
    consumers = matrices.get("installed_consumers") if isinstance(matrices, dict) else None
    if isinstance(consumers, list) and consumers:
        fields = {key for key, _ in CONSUMER_COLUMNS}
        if any(not isinstance(row, dict) or not fields <= row.keys() for row in consumers):
            raise ValueError("installed consumer table requires every recorded column")
        lines.extend(("", "## Installed Consumers", "",
            "| " + " | ".join(label for _, label in CONSUMER_COLUMNS) + " |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |"))
        lines.extend("| " + " | ".join(_cell(row[key]) for key, _ in CONSUMER_COLUMNS) + " |"
                     for row in consumers)
    return lines


def render_closeout(raw, *, expected_sha256):
    """Validate exact input bytes, then reproduce every recorded JSON field.

    No referenced receipt or artifact is opened. Counts, nulls, statuses and
    claim limits remain supplied observations, not renderer certifications.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ValueError("bounded canonical phase JSON bytes required")
    if not isinstance(expected_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise ValueError("expected SHA256 must be 64 lowercase hexadecimal characters")
    if sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("canonical phase JSON SHA256 mismatch")
    report = _strict_json(raw)
    if not isinstance(report, dict):
        raise ValueError("canonical phase JSON must be an object")
    validate_phase_report(report)
    if report["phase_id"] != "M5-12":
        raise ValueError("closeout renderer requires phase M5-12")
    for key in ("status", "scientific_status"):
        if not isinstance(report[key], str) or not report[key].strip():
            raise ValueError("explicit recorded status required: " + key)
    lines = [
        "# M5-12 Closeout",
        "",
        "Canonical input SHA256: `" + expected_sha256 + "`",
        "",
        "Recorded values and dispositions are reproduced without recomputation. "
        "Rendering does not certify artifacts, scientific success or release authority.",
    ]
    lines.extend(_recorded_summary(report))
    covered = set()
    for title, fields in SECTIONS:
        payload = {key: report[key] for key in fields}
        covered.update(fields)
        lines.extend(("", "## " + title, "", _block(payload)))
    additional = {key: report[key] for key in sorted(set(report) - covered)}
    if additional:
        lines.extend(("", "## Additional Recorded Evidence", "", _block(additional)))
    return "\n".join(lines) + "\n"


def _regular_path(path):
    path = Path(path).absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("symlink input/output paths are forbidden")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    source = _regular_path(args.input)
    if not source.is_file() or source.stat().st_size > MAX_BYTES:
        raise ValueError("bounded regular canonical phase JSON required")
    with source.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    rendered = render_closeout(raw, expected_sha256=args.expected_sha256).encode("utf-8")
    destination = _regular_path(args.output)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(destination, flags, 0o600), "wb") as stream:
        stream.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

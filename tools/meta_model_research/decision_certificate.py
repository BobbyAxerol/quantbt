"""Cold ML-06 verification: source custody, original outcomes and renderer."""

from __future__ import annotations

from collections import Counter
import ast
import os
import random
import time
from unittest.mock import patch
import xml.etree.ElementTree as ET

import numpy as np

from quantbt.optimization.meta_selection.common import digest
from .admission import (
    PUBLIC,
    ROOT,
    ROOTS,
    pin,
    read,
    read_verified,
    save_new,
    verify_freeze,
    load_corpus,
)
from .decision_policy import query_queue
from .decision_reporting import build_summary, markdown
from .decision_value import DEFAULT, verify_inputs
from .learners import FamilyResearch
from .linear import LinearResearch
from .fallback_audit import _account_refs, BASE, READBACK_SHA256


def verify(output=DEFAULT):
    start = time.process_time()
    verify_inputs(output)
    freeze = verify_freeze()
    seal, controls, analysis, diagnostics = [
        read(output / n)
        for n in ("sealed.json", "controls.json", "analysis.json", "diagnostics.json")
    ]
    rows = seal["rows"]
    expected = {(g, f, p) for g in ROOTS for f in range(57) for p in ("N", "R")}
    expected |= {
        (g, f, p) for g in ROOTS for f in range(25, 57) for p in ("X", "G", "F")
    }
    if {(r["group"], r["fold"], r["policy"]) for r in rows} != expected or len(
        rows
    ) != len(expected):
        raise ValueError("sealed decision matrix incomplete")
    roster = read(output / "query-roster.json")
    if (
        query_queue(rows) != roster["rows"]
        or roster["rows"][:128] != roster["admitted"]
    ):
        raise ValueError("query roster changed")
    queries = [read(p) for p in sorted((output / "queries").glob("*.json"))]
    by_id = {
        q["request"]["query_id"]: q
        for q in queries
        if q["request"]["kind"] == "missing"
    }
    if (
        len(queries) != 132
        or len(by_id) != 128
        or {r["query_id"] for r in roster["admitted"]} != set(by_id)
    ):
        raise ValueError("query count/identity differs")
    if sum(q["known_witness_exact"] is True for q in queries) != 4:
        raise ValueError("four exact original controls required")
    for g in ROOTS:
        corpus = load_corpus(g)
        for r in rows:
            if r["group"] != g:
                continue
            task = corpus.revisions[r["fold"]].task
            candidates = {c.evaluation_id: c for c in task.candidates}
            if r["policy"] in ("N", "R"):
                saved = corpus.selections[r["fold"]]["record"]
                key = (
                    "native_selected_evaluation_id"
                    if r["policy"] == "N"
                    else "selected_evaluation_id"
                )
                if r["winner"] != saved[key] or r["params_digest"] != digest(
                    candidates[r["winner"]].effective_params
                ):
                    raise ValueError("retained actual params differ")
            if r["query_id"] in by_id:
                q = by_id[r["query_id"]]
                if (
                    q["request"]["winner"] != r["winner"]
                    or q["request"]["fold"] != r["fold"]
                ):
                    raise ValueError("witness not bound to selected candidate")
                o = q["observation"]
                if (
                    o["window_start"] != task.forward_start.isoformat()
                    or o["window_end"] != task.forward_end.isoformat()
                    or o["economics_id"] != task.family.economics_id
                    or o["metric_contract_id"] != task.family.metric_contract_id
                    or q["entered_training"] is not False
                    or q["evaluation_only"] is not True
                ):
                    raise ValueError("witness rights/economics mismatch")
    old = read_verified(
        BASE / "four-alpha-closeout-v1/readback.json", expected_sha256=READBACK_SHA256
    )
    accounts = _account_refs(old)
    source_schemas = [
        read(output / n)["source_pins"]
        for n in (
            "registration.json",
            "analysis-registration.json",
            "diagnostics-02-registration.json",
        )
    ]
    source_refs = {r["path"]: r for refs in source_schemas for r in refs}
    for name in ("controls.json", "quarterly.json"):
        r = read(output / name)["source"]
        source_refs[r["path"]] = r
    archived_sources = []
    for r in source_refs.values():
        if pin(r["path"]) != r:
            archive = (
                output
                / "source-before-renderer-fix/tools/meta_model_research/decision_reporting.py"
            )
            if r["path"] != str(
                ROOT / "tools/meta_model_research/decision_reporting.py"
            ):
                raise ValueError("executed source changed: " + r["path"])
            archived = pin(archive)
            if (archived["bytes"], archived["sha256"]) != (r["bytes"], r["sha256"]):
                raise ValueError("executed source archive differs")

            def body(path):
                tree = ast.parse(path.read_text())
                return ast.dump(
                    next(
                        n
                        for n in tree.body
                        if isinstance(n, ast.FunctionDef) and n.name == "auxiliary"
                    ),
                    include_attributes=False,
                )

            if body(archive) != body(
                ROOT / "tools/meta_model_research/decision_reporting.py"
            ):
                raise ValueError("executed auxiliary AST changed")
            archived_sources.append(
                dict(original=r, archive=archived, auxiliary_AST_unchanged=True)
            )
    state = random.getstate()
    np_state = np.random.get_state()

    def forbidden(*args, **kwargs):
        raise AssertionError("cold report attempted execution")

    with (
        patch.object(FamilyResearch, "fit", forbidden),
        patch.object(LinearResearch, "fit", forbidden),
    ):
        first = build_summary(output)
        second = build_summary(output)
        rendered = markdown(first)
    if first != second or first != read(PUBLIC / "ml06_summary.json"):
        raise ValueError("cold summary regeneration differs")
    if (
        rendered
        != (ROOT / "docs/meta_selection/M4_ML_06_DECISION_VALUE_REPORT.md").read_text()
    ):
        raise ValueError("cold Markdown regeneration differs")
    after = np.random.get_state()
    if (
        random.getstate() != state
        or np_state[0] != after[0]
        or not np.array_equal(np_state[1], after[1])
        or np_state[2:] != after[2:]
    ):
        raise ValueError("report advanced global RNG")
    xml = PUBLIC / "ml06_final_tests.xml"
    root = ET.parse(xml).getroot()
    cases = root.findall(".//testcase")
    if (
        len(cases) != 482
        or root.findall(".//failure")
        or root.findall(".//error")
        or root.findall(".//skipped")
    ):
        raise ValueError("source-final regression not clean")
    if len({(c.get("classname"), c.get("name")) for c in cases}) != len(cases):
        raise ValueError("duplicate source test count")
    reporting_xml = PUBLIC / "ml06_reporting_tests.xml"
    reporting = ET.parse(reporting_xml).getroot()
    report_cases = reporting.findall(".//testcase")
    if (
        len(report_cases) != 3
        or reporting.findall(".//failure")
        or reporting.findall(".//error")
        or reporting.findall(".//skipped")
    ):
        raise ValueError("reporting source-final tests not clean")
    work = first["work"]
    if (
        work["logical_fits"] > 160
        or work["numeric_reference_qualification_charge"] > 160
        or work["financial_calls"] > 132
    ):
        raise ValueError("research work ceiling exceeded")
    # Even charging every host CPU over the whole earlier preparation interval
    # bounds the untimed pre-finance setup failure conservatively.
    approval = output.parent / "owner-approval.json"
    failure = output / "pilot-setup-failure-01.json"
    interval = max(0.0, failure.stat().st_mtime - approval.stat().st_mtime)
    upper = interval * os.cpu_count()
    if (
        work["financial_stage_cpu_seconds"] + upper > 7200
        or work["cold_measured_cpu_seconds"] > 1200
    ):
        raise ValueError("conservative measured resource ceiling exceeded")
    result = dict(
        schema="m4.ml06.cold-certificate.v1",
        status="PASS_REGISTERED_LOCAL_SCOPE",
        baseline=freeze,
        decision_rows=len(rows),
        native_decisions=228,
        ridge_decisions=228,
        evaluation_policy_rows=analysis["evaluation_rows"],
        new_outcome_statuses=dict(Counter(q["observation"]["status"] for q in queries)),
        exact_original_controls=4,
        protected_original_account_files=len(accounts),
        account_refs=accounts,
        all_query_windows_economics_metrics_rights_verified=True,
        controls=pin(output / "controls.json"),
        source_tests=pin(xml),
        distinct_source_tests=len(cases) + len(report_cases),
        additional_reporting_tests=pin(reporting_xml),
        archived_executed_sources=archived_sources,
        report_regeneration_exact=True,
        global_RNG_unchanged=True,
        logical_research_fits=work["logical_fits"],
        numeric_reference_charge=work["numeric_reference_qualification_charge"],
        setup_failure_actual_cpu_seconds=None,
        setup_failure_conservative_cpu_upper_bound=upper,
        upper_bound_method="all4 host CPUs over approval-to-failed-setup-receipt wall interval; bound only, not measured work",
        financial_cpu_with_setup_upper_bound=work["financial_stage_cpu_seconds"]
        + upper,
        source_refs=list(source_refs.values()),
        cpu_seconds=time.process_time() - start,
        scientific_disposition="EXPLORATORY_HETEROGENEOUS_KEEP_FROZEN_V1_NO_DEFAULT_CHANGE",
        qualified_scope="source/local registered finite decisions and original witnesses; not installed-wheel, remote, public or self-consistent acquisition rollout",
        new_fits=0,
        new_optimizer_proposals=0,
        new_financial_calls=0,
    )
    if verify_freeze() != freeze:
        raise ValueError("baseline changed")
    return save_new(output / "certificate.json", result)

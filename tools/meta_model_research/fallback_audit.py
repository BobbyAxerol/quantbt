"""Cold ML-04 retention audit: no nominees means frozen Ridge P0, not native.

The pure reducer does not fit, score, execute accounts or read files. The
explicit wrapper verifies retained input/account bytes; it never replays ML-02.
"""

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from quantbt.optimization.meta_selection.common import digest, utc

from .admission import (
    BASE,
    PUBLIC,
    ROOT,
    ROOTS,
    READBACK_SHA256,
    load_corpus,
    pin,
    read_verified,
    verify_freeze,
)
from .protocol import GROUPS


VERSION = "m4.ml04.fallback-audit.v1"
FOLDS = tuple(range(25, 57))
BASELINE_PATH = (
    ROOT / "upgrade/private/meta_model_research_v1/ml02/replay-02/result.json"
)
SCREEN_PATH = ROOT / "upgrade/private/meta_model_research_v1/ml03/screen-01/result.json"
ACCOUNT_NAMES = ("paths.npz", "fills.json.gz", "metrics.json.gz")


def _fail(reason):
    raise ValueError("MLR04_FALLBACK_" + reason)


def _no_nominees(nominees):
    if not isinstance(nominees, Mapping) or set(nominees) != {"base", "union"}:
        _fail("NOMINEE_ROSTER_INVALID")
    for panel in ("base", "union"):
        if not isinstance(nominees[panel], Mapping) or set(nominees[panel]) != set(
            GROUPS
        ):
            _fail("NOMINEE_ROSTER_INVALID")
        for item in nominees[panel].values():
            if (
                not isinstance(item, Mapping)
                or not isinstance(item.get("nominees"), (list, tuple))
                or item["nominees"]
                or item.get("policy") != "P0"
            ):
                _fail("NO_NOMINEE_SCOPE_REQUIRED")


def audit_fallback_rows(baseline_result, corpora, nominees):
    """Check exactly 128 outer union/P0 decisions; return counts and opaque digest.

    Legacy ML-02 rows have no parameter digest: derive it from the selected
    task candidate and compare the retained selected_params/proposal payload.
    """
    _no_nominees(nominees)
    if (
        not isinstance(baseline_result, Mapping)
        or baseline_result.get("schema") != "m4.ml02.fixed-pool-replay.v1"
        or baseline_result.get("status") != "REPLAY_COMPLETE_ANALYSIS_PENDING"
    ):
        _fail("BASELINE_VERSION_OR_COMPLETION_INVALID")
    if not isinstance(corpora, Mapping) or set(corpora) != set(GROUPS):
        _fail("CORPUS_ROSTER_INVALID")
    for key in ("new_optimizer_proposals", "new_financial_calls"):
        if key in baseline_result and baseline_result[key] != 0:
            _fail("BASELINE_WORK_SCOPE_INVALID")
    source_rows = baseline_result.get("rows")
    if not isinstance(source_rows, (list, tuple)):
        _fail("ROWS_INVALID")
    rows = {}
    for row in source_rows:
        if not isinstance(row, Mapping):
            _fail("ROW_INVALID")
        if row.get("panel") != "union" or row.get("policy") != "P0":
            continue
        fold = row.get("fold")
        if type(fold) is not int or not 0 <= fold < 57:
            _fail("FOLD_INVALID")
        if fold not in FOLDS:
            continue
        key = (row.get("group"), fold)
        if key[0] not in GROUPS:
            _fail("GROUP_INVALID")
        if key in rows:
            _fail("DUPLICATE_ROW")
        rows[key] = row
    if set(rows) != {(g, f) for g in GROUPS for f in FOLDS}:
        _fail("INCOMPLETE_OUTER_ROSTER")
    bindings, counts = [], {}
    for group in GROUPS:
        corpus = corpora[group]
        if corpus.group != group:
            _fail("CORPUS_GROUP_MISMATCH")
        changed_ids = changed_params = 0
        for fold in FOLDS:
            row = rows[group, fold]
            revision, saved = corpus.revisions[fold], corpus.selections[fold]
            task, record = revision.task, saved["record"]
            candidates = {c.evaluation_id: c for c in task.candidates}
            selected = row.get("winner")
            anchor = task.anchor_candidate_evaluation_id
            if (
                selected not in candidates
                or selected != record["selected_evaluation_id"]
                or row.get("status") != record["final_selection_reason"]
            ):
                _fail("SELECTED_ID_OR_REASON_MISMATCH")
            if (
                row.get("anchor") != anchor
                or record["native_selected_evaluation_id"] != anchor
                or record.get("current_outer_oos_used_for_selection") is not False
            ):
                _fail("ANCHOR_OR_CAUSAL_RIGHTS_MISMATCH")
            if row.get("resolved_policy", "P0") != "P0":
                _fail("FROZEN_P0_REQUIRED")
            if "task" in saved and digest(saved["task"]) != digest(task):
                _fail("SAVED_TASK_MISMATCH")
            snapshot = corpus.snapshot(fold)
            if (
                row.get("snapshot_id") != snapshot.snapshot_id
                or type(row.get("K")) is not int
                or row["K"] != snapshot.origin_count
                or snapshot.information_as_of > task.data_cutoff
            ):
                _fail("SNAPSHOT_OR_PREFIX_MISMATCH")
            clocks = dict(
                cutoff=task.data_cutoff,
                label_available_at=max(o.label_available_at for o in revision.outcomes),
                revision_available_at=revision.revision_available_at,
            )
            for name, expected in clocks.items():
                if name not in row or utc(row[name]) != expected:
                    _fail("CLOCK_MISMATCH:" + name)
            for name, expected in (
                ("information_as_of", task.data_cutoff),
                ("decision_sealed_at", task.decision_sealed_at),
            ):
                if name in record and utc(record[name]) != expected:
                    _fail("RETAINED_CLOCK_MISMATCH")
            params = candidates[selected].effective_params
            params_hash = digest(params)
            if (
                not isinstance(record.get("selected_params"), Mapping)
                or digest(record["selected_params"]) != params_hash
            ):
                _fail("SELECTED_PARAMS_DIGEST_MISMATCH")
            if "native_selected_params" in record and digest(
                record["native_selected_params"]
            ) != digest(task.anchor.effective_params):
                _fail("NATIVE_PARAMS_DIGEST_MISMATCH")
            proposal = record.get("proposal")
            if (
                proposal is not None
                and proposal.get("proposed_evaluation_id") == selected
                and digest(proposal["proposed_params"]) != params_hash
            ):
                _fail("PROPOSAL_PARAMS_DIGEST_MISMATCH")
            # Some newer callers carry this field; never require or invent it for ML-02.
            if (
                "proposed_params_digest" in row
                and row["proposed_params_digest"] != params_hash
            ):
                _fail("ROW_PARAMS_DIGEST_MISMATCH")
            changed_ids += selected != anchor
            changed_params += params_hash != digest(task.anchor.effective_params)
            bindings.append(
                dict(
                    group=group,
                    fold=fold,
                    cutoff=task.data_cutoff,
                    snapshot=snapshot.snapshot_id,
                    selected=selected,
                    anchor=anchor,
                    reason=row["status"],
                    params_digest=params_hash,
                )
            )
        counts[group] = dict(
            outer_rows=32,
            P0_differs_from_native_anchor=changed_ids,
            P0_parameter_changes_from_native_anchor=changed_params,
        )
    return dict(
        schema=VERSION,
        status="PASS",
        policy="FROZEN_RIDGE_P0",
        scope="retained_outer_union_P0_decisions_not_new_challenger_economics",
        checked_rows=len(bindings),
        per_group=counts,
        nominee_cells_checked=8,
        selected_params_hashes_checked=len(bindings),
        audit_digest=digest(bindings),
        model_fits=0,
        financial_calls=0,
        optimizer_proposals=0,
        public_activation=False,
        economic_improvement_claim=False,
    )


def _verified(ref):
    return read_verified(
        ref["path"], expected_sha256=ref["sha256"], expected_bytes=ref["bytes"]
    )


def _bound_ref(document, key, path):
    matches = [r for r in document[key] if r["path"] == str(path)]
    if len(matches) != 1 or pin(path) != matches[0]:
        _fail("CLOSED_INPUT_PIN_MISMATCH")
    return matches[0]


def _account_refs(readback):
    refs, counts, seen = [], {g: Counter() for g in GROUPS}, set()
    for ref in readback["input_pins"]:
        path = Path(ref["path"])
        if path.name not in ACCOUNT_NAMES:
            continue
        if not path.is_absolute() or ".." in path.parts:
            _fail("ACCOUNT_PATH_INVALID")
        groups = [g for g in GROUPS if path.is_relative_to(ROOTS[g])]
        if not groups:
            continue
        if len(groups) != 1 or str(path) in seen:
            _fail("ACCOUNT_PIN_DUPLICATE_OR_ROOT_MISMATCH")
        if pin(path) != ref:
            _fail("ACCOUNT_PIN_MISMATCH")
        seen.add(str(path))
        refs.append(ref)
        counts[groups[0]][path.name] += 1
    if len(refs) != 24 or any(
        counts[g][name] != 2 for g in GROUPS for name in ACCOUNT_NAMES
    ):
        _fail("INCOMPLETE_ORIGINAL_ACCOUNT_PINS")
    return refs


def run_fallback_audit():
    """Read existing closed evidence and verify pins, with no fits or new writes.

    Not executed by the synthetic tests against a real corpus. Financial files
    are hashed only, never decoded or re-executed. The caller owns persistence.
    """
    sources = [
        pin(Path(__file__).with_name(name))
        for name in ("fallback_audit.py", "admission.py", "protocol.py")
    ]
    freeze = verify_freeze()
    ml02_ref, ml03_ref = (
        pin(PUBLIC / name) for name in ("ml02_closure.json", "ml03_closure.json")
    )
    ml02, ml03 = _verified(ml02_ref), _verified(ml03_ref)
    if (
        ml02.get("schema") != "m4.ml02.closure.v1"
        or ml02.get("technical_gate") != "PASS"
        or ml03.get("schema") != "m4.ml03.closure.v1"
        or ml03.get("technical_gate") != "PASS"
        or ml03.get("no_nominees") is not True
    ):
        _fail("CLOSED_PREDECESSOR_GATES_REQUIRED")
    baseline_ref = _bound_ref(ml02, "input_pins", BASELINE_PATH)
    screen_ref = _bound_ref(ml03, "inputs", SCREEN_PATH)
    baseline, screen = _verified(baseline_ref), _verified(screen_ref)
    if screen.get("schema") != "m4.ml03.finite-screen.v1":
        _fail("SCREEN_VERSION_INVALID")
    corpora = {g: load_corpus(g) for g in GROUPS}
    result = audit_fallback_rows(baseline, corpora, screen["nominees"])
    readback_ref = pin(BASE / "four-alpha-closeout-v1/readback.json")
    if readback_ref["sha256"] != READBACK_SHA256:
        _fail("READBACK_AUTHORITY_CHANGED")
    refs = _account_refs(_verified(readback_ref))
    protected = (
        sources + [ml02_ref, ml03_ref, baseline_ref, screen_ref, readback_ref] + refs
    )
    if any(pin(ref["path"]) != ref for ref in protected) or verify_freeze() != freeze:
        _fail("INPUT_OR_SOURCE_CHANGED_DURING_AUDIT")

    def compact(ref):
        return dict(bytes=ref["bytes"], sha256=ref["sha256"])

    return dict(
        result,
        baseline_freeze=freeze,
        protected_account_files=len(refs),
        account_pins_digest=digest(sorted(refs, key=lambda r: r["path"])),
        input_pins={
            name: compact(ref)
            for name, ref in zip(
                ("ml02_closure", "ml03_closure", "baseline", "screen", "readback"),
                (ml02_ref, ml03_ref, baseline_ref, screen_ref, readback_ref),
            )
        },
        source_pins={Path(ref["path"]).name: compact(ref) for ref in sources},
    )

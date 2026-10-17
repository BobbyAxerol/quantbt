"""Source freeze and immutable evidence admission before model outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import gzip
import json
from pathlib import Path

from quantbt.optimization.meta_selection.common import canonical, digest
from quantbt.optimization.meta_selection.history import MetaHistory
from quantbt.optimization.meta_selection.model import schema_from_payload
from quantbt.optimization.meta_selection.persistence import loads_revision


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "benchmarks/optimization/meta_selection/model_research_v1"
BASE = ROOT / "upgrade/private/mode5_upgrade_v1/m5-11-6/attempt-01"
ROOTS = {
    "A-SC": BASE / "sc57-finalization-v3-02/A-SC/run/A-SC",
    "A-HMA": BASE / "hma-accounts-finalization-v4/A-HMA",
    "A-HASH": BASE / "hash54-continuation-v3/A-HASH/run/A-HASH",
    "A-VWAP": BASE / "long-rolling-monthly-v1/A-VWAP",
}
FREEZE_ID = "43b8c86475ef0922fbaf2ccec6fccb6f10d59e2d6ffc913b66b912d93ea070ea"
TERMINAL_SHA256 = "988cc74149c6d5c9c3e9207c4784299de7ea5e21838f374ce8a4478f91368cd8"
READBACK_SHA256 = "2a9ea034cffcb52284d9ed1400754236ae02b05422e115b464a8c416fd91d0b8"
FAMILY_SCHEMAS = {
    "A-SC": ("f541e32727ab00d4b372110a66aaddff1152be441feafeca503bfc7c64ed9b34",
             "f9284c3e12795671105db036567b5c11bb63cbebd31efccf16d7a97c97768581"),
    "A-HMA": ("c1da5ad72d5f632bc2bf8489a51f4c236b0f8b9592767344300e691401adf216",
              "688a84e9eb61d788223ccdd7df313fdcf97cc9f7e7b55e15c514ee9679df7aa6"),
    "A-HASH": ("d2b328e391510bf6b6532aa1002ee595ff3f1f9b4cad6670dca56a95d88b35e4",
               "7d649473317e3180815e498b75010d7c668ab1baeb3edd95d5fe3cb0e58b8e1d"),
    "A-VWAP": ("c889ee26239c74330f7dcce99fbf3fa5612ed29e0268e80d86ca06275fcb2fb5",
               "6f9578a465084197020f0a3d00d8eaf977d9f7f5edb05ac23417c54f400d3ab6"),
}


def pin(path):
    path = Path(path).resolve()
    return dict(path=str(path), bytes=path.stat().st_size,
                sha256=sha256(path.read_bytes()).hexdigest())


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def read_verified(path, *, expected_sha256, expected_bytes=None, max_bytes=16_000_000):
    """Verify and decode the same bounded bytes, including uncompressed size."""
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError("evidence byte budget exceeded")
    raw = path.read_bytes()
    if ((expected_bytes is not None and len(raw) != expected_bytes) or
            sha256(raw).hexdigest() != expected_sha256):
        raise ValueError("evidence hash/size mismatch")
    if path.suffix == ".gz":
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("decoded evidence byte budget exceeded")
    return json.loads(raw)


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value).encode())
    return pin(path)


def verify_freeze(root=ROOT, manifest=None):
    manifest = manifest or read(PUBLIC / "ridge_v1_freeze.json")
    payload = {k: v for k, v in manifest.items() if k != "freeze_id"}
    actual = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                               allow_nan=False).encode()).hexdigest()
    if manifest["freeze_id"] != FREEZE_ID or actual != FREEZE_ID:
        raise ValueError("frozen comparator content/settings changed")
    for field in ("source_sha256", "existing_evidence_sha256"):
        for relative, expected in manifest[field].items():
            if sha256((root / relative).read_bytes()).hexdigest() != expected:
                raise ValueError(f"frozen comparator input changed: {relative}")
    return dict(freeze_id=FREEZE_ID, source_files=len(manifest["source_sha256"]),
                receipts=len(manifest["existing_evidence_sha256"]), verified=True)


@dataclass(frozen=True)
class Corpus:
    group: str
    revisions: tuple
    selections: tuple
    schema: object
    history: MetaHistory
    pins: tuple

    def snapshot(self, fold):
        saved = self.selections[fold]["snapshot"]
        result = self.history.snapshot(
            family_id=saved["family_id"], authorized_corpora=saved["authorized_corpora"],
            outcome_origins=saved["outcome_origins"],
            research_exposures=saved["research_exposures"],
            information_as_of=saved["information_as_of"],
        )
        if (result.snapshot_id != saved["snapshot_id"] or
                tuple(r.revision_id for r in result.revisions) != tuple(saved["revision_ids"])):
            raise ValueError("retained history/correction availability mismatch")
        return result


def load_corpus(group, *, roots=ROOTS):
    """Require source-bound custody, never trust a checkpoint verification flag."""
    verify_freeze()
    if group not in FAMILY_SCHEMAS or Path(roots[group]).resolve() != ROOTS[group].resolve():
        raise ValueError("unapproved related-alpha group/root substitution")
    terminal_path = BASE / "four-alpha-closeout-v1/final-closeout.json"
    terminal = read_verified(terminal_path, expected_sha256=TERMINAL_SHA256)
    if terminal["status"] != "PASS_APPROVED_LOCAL_HISTORY_ACCOUNTING_QUALIFICATION_SCOPE":
        raise ValueError("original qualified custody required")
    authority_ref = next(p for p in terminal["input_pins"]
                         if p["path"].endswith("/four-alpha-closeout-v1/readback.json"))
    if authority_ref["sha256"] != READBACK_SHA256:
        raise ValueError("cold custody authority changed")
    authority = read_verified(authority_ref["path"], expected_sha256=READBACK_SHA256,
                              expected_bytes=authority_ref["bytes"])
    allowed = {p["path"]: p for p in authority["input_pins"]}
    witnesses, revision_ids, selections, documents, pins = {}, [], [], [], []
    for fold in range(57):
        directory = roots[group] / f"folds/{fold:02d}"
        values = {}
        for name in ("revision", "selection"):
            path = directory / f"{name}.json.gz"
            ref = pin(path)
            if allowed.get(ref["path"]) != ref:
                raise ValueError("input is not a qualified corrected-history member")
            pins.append(ref)
            values[name] = read_verified(path, expected_sha256=ref["sha256"],
                                         expected_bytes=ref["bytes"])
        document, selected = values["revision"], values["selection"]
        payload = document["payload"]
        if (digest(payload) != document["content_digest"] or
                payload["task"] != selected["task"] or payload["panel"] != selected["panel"]):
            raise ValueError("revision/decision task or panel differs")
        if (selected["record"]["current_outer_oos_used_for_selection"] is not False or
                selected["record"]["native_selected_evaluation_id"] !=
                payload["task"]["anchor_candidate_evaluation_id"]):
            raise ValueError("native anchor or causal selection identity differs")
        revision_ids.append(digest(dict(schema="qms-revision-v1", record=payload)))
        observations = [c["observation"] for c in payload["task"]["candidates"]]
        observations += [o["observation"] for o in payload["outcomes"]]
        for observation in observations:
            if observation["verification"] != "original_result":
                raise ValueError("original observation witness required")
            oid, value = observation["output_ref"], digest(observation)
            if witnesses.setdefault(oid, value) != value:
                raise ValueError("conflicting output observation")
        documents.append(document)
        selections.append(selected)
    revisions = tuple(loads_revision(canonical(d), verified_output_witnesses=witnesses,
                                     reviewed_revision_ids=revision_ids) for d in documents)
    history = MetaHistory()
    for revision in revisions:
        history.append(revision)
    if len({r.task.family.family_id for r in revisions}) != 1:
        raise ValueError("incompatible families cannot be pooled")
    model = next(s["model"] for s in selections if s["model"] is not None)
    schema = schema_from_payload(model["schema"])
    if (revisions[0].task.family.family_id, schema.schema_id) != FAMILY_SCHEMAS[group]:
        raise ValueError("unapproved related-alpha family/schema substitution")
    corpus = Corpus(group, revisions, tuple(selections), schema, history, tuple(pins))
    for fold in range(57):
        corpus.snapshot(fold)
    return corpus


def inventory(corpus):
    from collections import Counter

    rows, statuses, counts = [], Counter(), Counter()
    for fold, revision in enumerate(corpus.revisions):
        task, panel = revision.task, revision.panel
        base = set(panel.base_members)
        training = revision.training_rows
        statuses.update(o.observation.status.value for o in revision.outcomes)
        counts.update(dict(pool=len(task.candidates), base=len(base),
                           union_only=len(set(panel.members) - base),
                           labels=len(panel.members), training_rows=len(training),
                           valid_base=sum(r.candidate_evaluation_id in base for r in training),
                           valid_union=sum(r.candidate_evaluation_id not in base for r in training)))
        snapshot = corpus.snapshot(fold)
        rows.append(dict(fold=fold, origin=task.origin.isoformat(),
                         cutoff=task.data_cutoff.isoformat(), K=snapshot.origin_count,
                         N=len(snapshot.training_rows), d=len(corpus.schema.feature_names),
                         valid_rows=len(training), pool=len(task.candidates),
                         base=len(base), union_only=len(set(panel.members)-base),
                         revision_id=revision.revision_id,
                         revision_available_at=revision.revision_available_at.isoformat()))
    return dict(group=corpus.group, stratum="original_monthly_730D", folds=57,
                family_id=corpus.revisions[0].task.family.family_id,
                schema_id=corpus.schema.schema_id, d=len(corpus.schema.feature_names),
                counts=dict(counts), label_statuses=dict(statuses), rows=rows,
                preforward_panel_clocks_checked=True, saved_asof_snapshots_exact=True,
                outcome_role="REVIEWED_EXPLORATORY_NOT_NEW_EXTERNAL_OOS",
                acquisition="feature-dependent base16 plus prior-winner union; propensities unknown",
                full_pool_oracle=False, missing_outcomes_are_zero=False)

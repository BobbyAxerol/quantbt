"""Stored synthetic metadata only; no private corpus, finance or optimizer work."""

import builtins
from copy import deepcopy
from dataclasses import FrozenInstanceError
import gzip
from hashlib import sha256
import json
from pathlib import Path

import pytest

from quantbt.mode5.dossier.records import Record

from tools.mode5_research import handoff_readback as h
from tools.mode5_research.cross_mode.disposition import (
    GateDisposition, MethodDisposition, no_finance_handoff,
)
from tools.mode5_research.cross_mode.inventory import FilePin


SAVED_SCORES = {
    "A-SC": (-0.03802456885881951, 0.0005356984176495026, 0.00039868385521659225),
    "A-HASH": (-0.046387995583714085, -0.04665077038920563, -0.06199858422020491),
    "A-VWAP": (-102.48992105294259, -143.73285744625394, -137.04168269992365),
}
FORMULAS = {
    "A-RSI": "environment_floor_mean_v1", "A-SC": "environment_floor_mean_v1",
    "A-HASH": "environment_lower_tail_v2", "A-VWAP": "pareto_chebyshev_v1",
    "N1": "environment_floor_mean_v1", "N2": "pareto_chebyshev_v1",
}
PRUNES = {("A-HASH", "raw-tpe"): 6, ("A-HASH", "recipe-tpe"): 3,
          ("A-HASH", "recipe-challenger"): 21, ("A-VWAP", "raw-tpe"): 25,
          ("A-VWAP", "recipe-challenger"): 1}
PREFIX = {
    "N1": ((0.007066178229284681, -1.2778213033206969, -1.2848874815499816),
           (0.3054992599779798, -0.12778673557494802, -0.4332859955529278),
           (-0.521160146729954, 10.914255382967461, 11.435415529697416)),
    "N2": ((0.03896986548570336, None, None),
           (-0.6504079348124585, 1.8173804325596954, 2.4677883673721537),
           (-0.08947603877988497, None, None)),
}


def metric(value=0.02):
    return dict(value=value, status="VALID" if value is not None else "UNDEFINED",
                reason=None if value is not None else "synthetic missing observation",
                unit="decimal_return", metric_id="synthetic.utility.v1", sample_count=365)


def account(year="whole", days=365):
    return dict(account_identity="synthetic-continuous", environment_id=year,
                initial_capital=20000, final_equity=22000, net_return=0.1,
                raw_sharpe=1.5, max_drawdown=0.05, daily_loss_es=0.03,
                daily_count=days, partial_days=0, utility=metric(),
                metric_contract="synthetic-metric-v1", quality_pass=True,
                risk_pass=True, support_pass=True)


def snapshot():
    annual = [account(str(year), 300 if year == 2026 else 365) for year in range(2020, 2027)]
    return dict(whole=account(days=sum(row["daily_count"] for row in annual)), annual=annual,
                activity=dict(fills=20, closed_campaigns=10, open_campaigns=0,
                              fee_sum=15.0, exposure_fraction=0.25),
                common_eligible=True, positive_years=7, positive_year_denominator=7,
                annual_floor_return=0.1, annual_floor_utility=0.02, worst_annual_dd=0.05,
                undefined_annual_returns=0, undefined_annual_utilities=0,
                partial_calendar_environments=["2026"])


def winner(candidate):
    return dict(status="QUALIFIED_REGISTERED_FINITE_WINNER_CHECKS", candidate_id=candidate,
                basin_certified=False, center=snapshot(), double_fee=snapshot(),
                evidence={}, held_whole_utility=dict(status="INSUFFICIENT_COVERAGE",
                    expected_unique_probes=3, valid_probes=3, center_utility=0.02,
                    quality_survival_fraction=1., empirical_worst_utility=-0.02, lower_tail_utility=-0.01),
                geometric_coverage=dict(status="INSUFFICIENT_COVERAGE", raw_rows=3,
                                        unique_effective=3, infeasible=0), full_mandate_survival=1.)


def observation(value):
    return dict(status="VALID" if value is not None else "NO_VARIANCE", raw_sharpe=0 if value is None else value,
                sample_count=30, activity_count=0 if value is None else 5,
                window_start="synthetic-start", window_end="synthetic-end",
                metric_contract_id="synthetic-sharpe", economics_id="synthetic-economics")


def study(alpha, direction, arm, fold=None):
    return dict(alpha=alpha, direction=direction, arm=arm, fold=fold, attempts=256,
                counts={"COMPLETE": 256, "PRUNED": 0},
                unique=245, duplicate_attempts=11, branches_observed=2,
                warm_start_slots=0 if arm == "baseline" else 64,
                sampled_startup_slots=128 if arm == "baseline" else 64,
                physical_search_account_calls=245, financial_receipt_reuses=11)


def documents():
    c05 = dict(schema="quantbt.mode5_upgrade.phase_report.v1",
        status="COMPLETE_REGISTERED_SEVEN_ALPHA_COLD_SYNTHESIS", independent_oos=False,
        original_winners_changed=False, alpha_scope=list(h.ALPHAS), numeric_results={},
        limitations=["Synthetic full-development evidence, not independent OOS."])
    formal = dict(status="PASS_COLD_SEALED_FORMAL_SUMMARY_AND_RECIPE_ARITHMETIC",
                  attempts=2304, complete=2248, pruned=56, financial_executions=0,
                  optimizer_proposals=0, changed_winners=0, rows=[])
    inventory = dict(schema="m51110.inventory.v2", mode4={}, exclusions={},
                     m5119_tail_completion=False, m5119_formal_snapshot=[])
    for alpha in h.ALPHAS:
        row = dict(status="COMPLETE_REGISTERED_DIAGNOSTIC_FORMAL_WINNER_JOIN",
            scope=dict(symbol="ETHUSDT" if alpha in ("A-RSI", "N1", "N2") else "BTCUSDT",
                       timeframe="1h", start="2020-01-01T00:00:00+00:00",
                       stop_exclusive="2026-10-01T00:00:00+00:00" if alpha in ("N1", "N2")
                       else "2026-10-06T00:00:00+00:00", economic_contract="synthetic original account"),
            diagnostics=dict(registered_cells=128), studies={}, arms={}, regimes={})
        alias = "A-" + alpha if alpha in ("N1", "N2") else alpha
        inventory["mode4"][alias] = dict(origins=28 if alpha == "A-RSI" else 57,
            candidates=128, acquired_forward=16, unique_recorded_coordinates=128,
            forward_dispositions={"VALID": 15, "NO_VARIANCE": 1})
        if alpha == "A-HMA":
            row.update(status="NO_SELECTION", common_eligible=0,
                       formal_disposition="NO_ELIGIBLE_COHORT_NO_NEW_SEARCH",
                       limitation="No eligible formal cohort; do not fabricate a winner.")
            del row["studies"]
        else:
            arms = ("raw-tpe", "floor-tpe", "floor-cma") if alpha == "A-RSI" else h.ARMS
            for arm in arms:
                pruned = PRUNES.get((alpha, arm), 0)
                row["studies"][arm] = dict(attempts=256, states={"COMPLETE": 256-pruned, "PRUNED": pruned},
                    candidate_id=alpha + ":" + arm, objective="raw_whole_daily_sharpe" if arm == "raw-tpe"
                    else FORMULAS[alpha], sampler="synthetic-sampler", complete={})
                row["arms"][arm] = winner(alpha + ":" + arm)
        c05["numeric_results"][alpha] = row
    for alpha in SAVED_SCORES:
        for arm, score in zip(h.ARMS, SAVED_SCORES[alpha]):
            formal["rows"].append(dict(alpha=alpha, arm=arm, formula=FORMULAS[alpha],
                frozen_recipe_cold_score=score, recorded_objective=1.5 if arm == "raw-tpe" else score,
                states=deepcopy(c05["numeric_results"][alpha]["studies"][arm]["states"]), winner_unchanged=True))
    assistance = dict(status="COMPLETE_FINANCIAL_READBACK_QUALIFICATION_SEPARATE", studies=[], pairs=[],
                      scope="Synthetic matched candidate generation only; meta OFF.",
                      inference="Descriptive screen, not whole-procedure inference.")
    for alpha in ("N1", "N2"):
        objectives = (-0.08349, -0.1113931922912) if alpha == "N1" else (-222.90917, -270.58151886564736)
        floors = (-0.07405, -0.10647756798541206) if alpha == "N1" else (-0.39131, -0.5201548515741009)
        for index, arm in enumerate(("baseline", "treatment")):
            row = study(alpha, "MODE4_TO_MODE5", arm)
            row["selected"] = dict(objective=objectives[index], min_annual_utility=floors[index],
                                   candidate_id=alpha+":"+arm, fixed_dictionary=True, whole=account())
            assistance["studies"].append(row)
        assistance["pairs"].append(dict(alpha=alpha, direction="MODE4_TO_MODE5", fold=None,
            status="COMPLETE_MATCHED_PAIR", delta_objective=objectives[1]-objectives[0],
            delta_min_annual_utility=floors[1]-floors[0]))
        for fold, (delta, q, r) in zip((0, 28, 56), PREFIX[alpha]):
            for arm in ("baseline", "treatment"):
                row = study(alpha, "MODE5_TO_MODE4", arm, fold)
                row["is_observation"] = observation(1. if arm == "baseline" else 1.+delta)
                row["forward_observation"] = observation(None if q is None else 2. if arm == "baseline" else 2.+q)
                row.update(fills=0 if q is None else 5, forward_exposure=0. if q is None else 0.25)
                assistance["studies"].append(row)
            valid = q is not None
            assistance["pairs"].append(dict(alpha=alpha, direction="MODE5_TO_MODE4", fold=fold,
                status="COMPLETE_MATCHED_PAIR", measurement_status="VALID_PAIRED_SHARPE" if valid else "UNDEFINED_PAIRED_SHARPE",
                IS_supported=True, Q_supported=valid, R_supported=valid, delta_IS=delta, Q=q, R=r,
                statuses=["VALID", "VALID", "VALID" if valid else "NO_VARIANCE", "VALID" if valid else "NO_VARIANCE"]))
    pin = FilePin("synthetic/never-follow-this.json", 1, "a" * 64)
    disposition = no_finance_handoff(snapshot_id="b"*64, approval=pin,
        gates=tuple(GateDisposition(f"XMR-{i:03d}", "NEW_WHOLE_PROCEDURE" if i < 37 else "COLD_DISPOSITION",
            "DEFERRED_APPROVED" if i < 37 else "VERIFIED_COLD", "Synthetic bounded disposition.", (pin,))
            for i in range(31, 41)),
        methods=tuple(MethodDisposition(alpha, method, "KEEP_BASELINE", "INCONCLUSIVE",
            "Synthetic descriptive evidence only.", (pin,)) for alpha in ("N1", "N2")
            for method in ("archive_seeded_mode5", "prefix_seeded_mode4", "regret_static_selector")),
        upstream_blockers=("Historical snapshot, not a current completion override.",))
    return dict(c05=c05, formal=formal, inventory=inventory, disposition=disposition,
        c06=dict(status="COMPLETE_REGISTERED_M5119_RESEARCH_SCOPE",
                 formal_work=dict(attempts=2304, complete=2248, pruned=56, unique_within_study=2273)),
        assistance=assistance,
        assistance_final=dict(status="COMPLETE_LOCAL_REGISTERED_RESEARCH_SCOPE", model_fits=0,
            public_default_changes=False, next_phase_authorized=False, remote_or_release=False,
            studies=[dict(path="synthetic/not-followed", bytes=1, sha256="c"*64) for _ in range(16)]),
        assistance_work=dict(status="COMPLETE_ACTUAL_WORK_LEDGER", logical_study_slots=4096,
            prefix_diagnostic_distinct_accounts=768, total_actual_owner_financial_invocations=4241,
            optimizer_reruns_of_completed_studies=0, account_count_convention="Owner invocations, not native calls.",
            wall_time_warning="Do not sum concurrent wall times.", inherited_archive=dict(
                origins_per_alpha=57, attempted_source_pool_slots_per_alpha=7296,
                acquisition_cost="Historical acquisition is additional work.")))


class Stored:
    def __init__(self, root):
        self.root = root
        self.docs = documents()
        self.save()

    def path(self, key):
        return self.root / h.SOURCES[key][0]

    def write(self, key, raw=None):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw is None:
            raw = json.dumps(self.docs[key], allow_nan=False).encode()
        if path.suffix == ".gz":
            raw = gzip.compress(raw, mtime=0)
        path.write_bytes(raw)

    def save(self):
        for key in self.docs:
            if key != "assistance_final":
                self.write(key)
        for field, key in (("readback", "assistance"), ("work", "assistance_work")):
            raw = self.path(key).read_bytes()
            self.docs["assistance_final"][field] = dict(path=h.SOURCES[key][0], bytes=len(raw), sha256=sha256(raw).hexdigest())
        self.write("assistance_final")


@pytest.fixture
def stored(tmp_path):
    return Stored(tmp_path)


def at(value, pointer):
    for part in pointer[1:].split("/") if pointer else ():
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if type(value) is list else value[part]
    return value


def test_seven_contexts_hma_and_final_formal_completion(stored):
    result = h.readback(stored.root).data
    assert set(result["alphas"]) == set(h.ALPHAS)
    hma = result["alphas"]["A-HMA"]
    assert hma["status"]["value"] == "NO_SELECTION" and hma["winners"] == hma["studies"] == {}
    assert sum(len(row["winners"]) for row in result["alphas"].values()) == 18
    assert {key: value["value"] for key, value in result["formal"]["counts"].items()} == {
        "attempts": 2304, "complete": 2248, "pruned": 56, "unique_within_study": 2273}
    assert result["archive_authority"] == "NOT_ASSESSED" and not result["independent_validation"]
    assert all(row["winner_unchanged"]["value"] for row in result["formal"]["rows"])
    assert result["disposition"]["whole_procedure"]["value"] == "NOT_EVALUATED"


def test_saved_formula_counterexamples_keep_original_winners(stored):
    result = h.readback(stored.root).data
    for alpha in ("A-HASH", "A-VWAP"):
        example = result["formal"]["counterexamples"][alpha]
        assert tuple(example["scores"][arm]["value"] for arm in h.ARMS) == SAVED_SCORES[alpha]
        assert all(value["value"] for value in example["raw_exceeds_recipe"].values())
        assert result["alphas"][alpha]["winners"]["recipe-tpe"]["candidate_id"]["value"] == alpha+":recipe-tpe"
    assert result["formal"]["counterexamples"]["A-HASH"]["scores"]["raw-tpe"]["unit"] == "decimal_return"
    assert result["formal"]["counterexamples"]["A-VWAP"]["scores"]["raw-tpe"]["unit"] == "reference_normalized_utility"


def test_pairs_preserve_signed_sharpe_differences_and_null_masks(stored):
    result = h.readback(stored.root).data["assistance"]
    assert len(result["studies"]) == 16 and len(result["pairs"]) == 8
    for pair in result["pairs"]:
        if pair["direction"] == "MODE4_TO_MODE5":
            assert pair["delta_objective"]["value"] < 0
            continue
        index = (0, 28, 56).index(pair["fold"])
        delta, q, r = PREFIX[pair["alpha"]][index]
        assert (pair["delta_IS"]["value"], pair["Q"]["value"], pair["R"]["value"]) == (delta, q, r)
        assert pair["Q_supported"]["value"] is (q is not None)
        assert pair["R_supported"]["value"] is (r is not None)
        assert pair["Q"]["status"] == ("VALID" if q is not None else "UNDEFINED")
    flat = next(row for row in result["studies"] if row["alpha"] == "N2" and row["fold"] == 0)
    assert flat["forward"]["raw_sharpe"]["value"] == 0
    assert flat["forward"]["raw_sharpe"]["status"] == "NO_VARIANCE"


def test_facts_resolve_to_exact_source_values_and_pins(stored):
    result = h.readback(stored.root).data
    pins = {pin["source_id"]: pin for pin in result["sources"]}
    assert set(pins) == set(h.SOURCES)
    for key, pin in pins.items():
        raw = stored.path(key).read_bytes()
        assert pin["sha256"] == sha256(raw).hexdigest() and pin["bytes"] == len(raw)

    def visit(value):
        if type(value) is dict:
            if "ref" in value:
                ref = value["ref"]
                assert ref["sha256"] == pins[ref["source"]]["sha256"]
                original = at(stored.docs[ref["source"]], ref["pointer"])
                if "value" in value:
                    assert type(original) is type(value["value"]) and original == value["value"]
            for item in value.values():
                visit(item)
        elif type(value) is list:
            for item in value:
                visit(item)
    visit(result)


def test_no_archive_does_not_discard_alpha_context(stored):
    del stored.docs["inventory"]["mode4"]["A-SC"]
    stored.save()
    result = h.readback(stored.root).data
    sc = result["alphas"]["A-SC"]
    assert sc["archive"]["status"] == "NO_ARCHIVE" and not result["archive_required"]
    assert len(sc["studies"]) == len(sc["winners"]) == 3
    assert sc["scope"]["symbol"]["value"] == "BTCUSDT"


def test_missing_ledgers_remain_null_and_partial_year_is_named(stored):
    center = stored.docs["c05"]["numeric_results"]["A-RSI"]["arms"]["raw-tpe"]["center"]
    center["activity"].update(fills=None, closed_campaigns=None, fee_sum=None,
                              cost_ledger="UNAVAILABLE_LEGACY_NOT_ZERO")
    center["annual"][0]["utility"] = metric(None)
    stored.save()
    result = h.readback(stored.root).data["alphas"]["A-RSI"]["winners"]["raw-tpe"]["center"]
    assert result["activity"]["fee_sum"]["value"] is None
    assert result["annual"][0]["utility"]["value"]["status"] == "UNDEFINED"
    assert result["partial_calendar_environments"][0]["value"] == "2026"


def test_projection_does_not_export_private_dictionaries_or_source(stored):
    marker = "SYNTHETIC_PRIVATE_MARKER_NEVER_EXPORT"
    stored.docs["c05"]["numeric_results"]["A-SC"]["params"] = {marker: 7}
    stored.docs["assistance"]["studies"][0]["private_alpha_source"] = marker
    stored.docs["inventory"]["private_parameter_dictionary"] = {marker: 9}
    stored.save()
    assert marker not in h.readback(stored.root).payload


def test_valid_zero_contrast_is_not_confused_with_flat_undefined(stored):
    doc = stored.docs["assistance"]
    pair = doc["pairs"][1]
    pair.update(delta_IS=0., Q=0., R=0.)
    for row in doc["studies"]:
        if row["alpha"] == "N1" and row["direction"] == "MODE5_TO_MODE4" and row["fold"] == 0:
            row["is_observation"] = observation(1.)
            row["forward_observation"] = observation(2.)
    stored.save()
    result = h.readback(stored.root).data["assistance"]["pairs"][1]
    assert result["Q"]["value"] == result["R"]["value"] == 0.
    assert result["Q"]["status"] == "VALID" and result["R_supported"]["value"] is True


def test_record_is_deterministic_immutable_and_read_only(stored):
    before = {path: path.read_bytes() for path in stored.root.rglob("*") if path.is_file()}
    record = h.readback(stored.root)
    assert h.Record is Record and type(record) is Record
    assert record == h.readback(stored.root) and record.identity == h.Record(record.payload).identity
    with pytest.raises(FrozenInstanceError):
        record.payload = "{}"
    data = record.data
    data["work"]["financial_invocations"] = 1
    assert record.data["work"]["financial_invocations"] == 0
    assert before == {path: path.read_bytes() for path in stored.root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("raw", [b'{"n":1,"n":2}', b'{"x":NaN}', b'{"x":Infinity}',
                                 b'{"x":1e999}', b'{"x":-1e999}', b'[]', b'null'])
def test_duplicate_nonfinite_or_scalar_document_rejected(stored, raw):
    stored.write("inventory", raw)
    with pytest.raises(ValueError):
        h.readback(stored.root)


@pytest.mark.parametrize("source,pointer,value", [
    ("formal", "/attempts", True), ("formal", "/complete", 2248.0),
    ("c06", "/formal_work/pruned", False), ("c05", "/independent_oos", 0),
    ("c05", "/numeric_results/A-HASH/studies/raw-tpe/attempts", "256"),
    ("assistance_final", "/next_phase_authorized", 0),
    ("assistance_work", "/logical_study_slots", 4096.0),
    ("assistance", "/studies/0/fold", False),
    ("assistance", "/pairs/5/Q_supported", 0),
])
def test_consumed_scalar_types_are_exact(stored, source, pointer, value):
    parent, key = pointer.rsplit("/", 1)
    at(stored.docs[source], parent)[key] = value
    stored.save()
    with pytest.raises(ValueError):
        h.readback(stored.root)


@pytest.mark.parametrize("source", ["c05", "formal", "c06", "assistance", "disposition"])
def test_missing_required_source_is_not_successful_missingness(stored, source):
    stored.path(source).unlink()
    with pytest.raises(FileNotFoundError):
        h.readback(stored.root)


@pytest.mark.parametrize("mutation", ["missing_alpha", "missing_arm", "duplicate_formal", "changed_count",
                                     "changed_winner", "extra_hma_arm", "mismatched_candidate"])
def test_incomplete_or_conflicting_retained_rosters_fail_closed(stored, mutation):
    c05, formal = stored.docs["c05"], stored.docs["formal"]
    if mutation == "missing_alpha":
        del c05["numeric_results"]["N1"]
    elif mutation == "missing_arm":
        del c05["numeric_results"]["N1"]["studies"]["recipe-tpe"]
    elif mutation == "duplicate_formal":
        formal["rows"][-1] = deepcopy(formal["rows"][0])
    elif mutation == "changed_count":
        formal["rows"][0]["states"]["COMPLETE"] = 255
    elif mutation == "changed_winner":
        formal["rows"][0]["winner_unchanged"] = False
    elif mutation == "extra_hma_arm":
        c05["numeric_results"]["A-HMA"]["arms"]["invented"] = {}
    else:
        c05["numeric_results"]["N1"]["arms"]["raw-tpe"]["candidate_id"] = "different-candidate"
    stored.save()
    with pytest.raises(ValueError):
        h.readback(stored.root)


@pytest.mark.parametrize("mutation", ["missing_pair", "duplicate_pair", "missing_study", "numeric_null",
                                     "mask", "wrong_R", "wrong_delta", "wrong_static_delta"])
def test_pair_coverage_algebra_and_missingness_are_not_imputed(stored, mutation):
    doc = stored.docs["assistance"]
    if mutation == "missing_pair":
        doc["pairs"].pop()
    elif mutation == "duplicate_pair":
        doc["pairs"][-1] = deepcopy(doc["pairs"][0])
    elif mutation == "missing_study":
        doc["studies"].pop()
    elif mutation == "numeric_null":
        doc["pairs"][5]["Q"] = 0.
    elif mutation == "mask":
        doc["pairs"][5]["Q_supported"] = True
    elif mutation == "wrong_R":
        doc["pairs"][1]["R"] += 1.
    elif mutation == "wrong_delta":
        doc["pairs"][1]["delta_IS"] += 1.
    else:
        doc["pairs"][0]["delta_objective"] += 1.
    stored.save()
    with pytest.raises(ValueError):
        h.readback(stored.root)


@pytest.mark.parametrize("field", ["path", "bytes", "sha256"])
def test_final_assistance_links_pin_the_actual_decoded_sources(stored, field):
    pin = stored.docs["assistance_final"]["readback"]
    pin[field] = {"path": "upgrade/private/mode5_upgrade_v1/m5-11-11/attempt-01/N1/summary.json.gz",
                  "bytes": True, "sha256": "0"*64}[field]
    stored.write("assistance_final")
    with pytest.raises(ValueError):
        h.readback(stored.root)


def test_rehashed_disposition_cannot_claim_whole_procedure_or_authority(stored):
    doc = stored.docs["disposition"]
    doc["whole_procedure_qualification"] = "PASS"
    doc["disposition_id"] = sha256(h._canonical({k: v for k, v in doc.items() if k != "disposition_id"}).encode()).hexdigest()
    stored.save()
    with pytest.raises(ValueError):
        h.readback(stored.root)


def test_reader_opens_only_eight_allowlisted_metadata_files(stored, monkeypatch):
    opened, original = [], h.os.open

    def track(path, *args, **kwargs):
        opened.append(Path(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(h.os, "open", track)
    h.readback(stored.root)
    assert opened == [stored.root / source[0] for source in h.SOURCES.values()]
    assert all("m5-11-11" not in str(path) for path in opened)


def test_symlinked_source_even_inside_root_is_rejected(stored):
    path = stored.path("formal")
    replacement = path.with_name("alias.json")
    path.rename(replacement)
    path.symlink_to(replacement)
    with pytest.raises(ValueError, match="symlink"):
        h.readback(stored.root)


def test_mid_read_source_replacement_is_rejected(stored, monkeypatch):
    original = h._Reader.load

    def replace_after_load(reader, key):
        result = original(reader, key)
        if key == "formal":
            stored.path(key).write_bytes(b"{}")
        return result
    monkeypatch.setattr(h._Reader, "load", replace_after_load)
    with pytest.raises(ValueError, match="changed"):
        h.readback(stored.root)


def test_stored_cap_is_checked_before_open_or_hash(stored, monkeypatch):
    caps = dict(h.SOURCES)
    path, _, decoded = caps["c05"]
    caps["c05"] = (path, 1, decoded)
    monkeypatch.setattr(h, "SOURCES", caps)

    def forbidden(*args, **kwargs):
        raise AssertionError("oversized source was opened")
    monkeypatch.setattr(h.os, "open", forbidden)
    with pytest.raises(MemoryError, match="stored"):
        h.readback(stored.root)


def test_gzip_decoded_cap_and_aggregate_caps_are_explicit(stored, monkeypatch):
    caps = dict(h.SOURCES)
    path, stored_cap, _ = caps["c05"]
    caps["c05"] = (path, stored_cap, 128)
    monkeypatch.setattr(h, "SOURCES", caps)
    with pytest.raises(MemoryError, match="decoded"):
        h.readback(stored.root)
    monkeypatch.setattr(h, "SOURCES", dict(caps, c05=(path, stored_cap, 4*h.MIB)))
    monkeypatch.setattr(h, "MAX_STORED_BYTES", 1)
    with pytest.raises(MemoryError, match="aggregate stored"):
        h.readback(stored.root)


def test_aggregate_decoded_and_output_caps_are_enforced(stored, monkeypatch):
    monkeypatch.setattr(h, "MAX_DECODED_BYTES", 1)
    with pytest.raises(MemoryError, match="decoded"):
        h.readback(stored.root)
    monkeypatch.setattr(h, "MAX_DECODED_BYTES", 10*h.MIB)
    monkeypatch.setattr(h, "MAX_RECORD_BYTES", 1)
    with pytest.raises(MemoryError, match="record"):
        h.readback(stored.root)


def test_limitation_roster_cannot_amplify_output_without_bound(stored):
    stored.docs["c05"]["limitations"] = ["synthetic limit"] * (h.MAX_LIMITS+1)
    stored.save()
    with pytest.raises(MemoryError, match="limitation"):
        h.readback(stored.root)


def test_explicit_path_required_and_cli_has_no_default_root():
    with pytest.raises(TypeError, match="Path"):
        h.readback(".")
    with pytest.raises(SystemExit) as error:
        h.main([])
    assert error.value.code == 2


def test_readback_does_not_import_runtime_owners_after_shared_contract_import(stored, monkeypatch):
    original = builtins.__import__

    def cold_import(name, *args, **kwargs):
        if name.split(".")[0] in {"quantbt", "optuna", "numpy", "pandas", "_quantbt_native"}:
            raise AssertionError("runtime import during metadata readback: " + name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", cold_import)
    record = h.readback(stored.root)
    assert type(record) is Record
    assert record.data["work"]["financial_invocations"] == record.data["work"]["optimizer_proposals"] == 0

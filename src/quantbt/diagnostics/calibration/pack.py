"""Portable recipe metadata with explicit external evidence and execution inputs.

No alpha, account paths, callbacks or mutable RNG are serialized. Importing a
pack is not permission to execute it; current source/access preflight is required.
"""
from dataclasses import dataclass
from pathlib import Path
import json

from quantbt.mode5.artifacts import write_json
from quantbt.mode5.continuous_binding import ContinuousMode5Calibration
from quantbt.mode5.dossier.governance import GovernanceLog
from quantbt.mode5.dossier.records import Record
from quantbt.optimization import SamplerConfig

from .worksheet import CalibrationRecipe, CalibrationWorksheet, selection_access, verify_sources


RUNNER = '''"""Explicit caller-supplied original inputs; no automatic data or alpha import."""
from quantbt.diagnostics import Mode5RunPack
from quantbt.mode5.runtime import Mode5NoSelectionError


def run(pack_path, *, expected_identity, dossier, catalog, journal, access,
        data, strategy, param_ranges, account_kwargs=None, execution_endpoint=None,
        target_mode="pct_equity", archive_access=None):
    pack = Mode5RunPack.read(pack_path, expected_identity=expected_identity)
    endpoint = pack.prepare(dossier=dossier, catalog=catalog, journal=journal,
        access=access, data=data, strategy=strategy, param_ranges=param_ranges,
        account_kwargs=account_kwargs, execution_endpoint=execution_endpoint,
        target_mode=target_mode, archive_access=archive_access)
    try:
        result = endpoint.backtest(data=data, param_ranges=param_ranges)
    except Mode5NoSelectionError as error:
        result = error
    report = pack.reconcile(result)
    return endpoint, result, report
'''


def _regular(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("symlinked run-pack path forbidden")
    return path


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate run-pack JSON key")
        result[name] = value
    return result


def _market_contract(data):
    import pandas as pd
    if not isinstance(data.index, pd.DatetimeIndex) or data.index.tz is None:
        raise ValueError("explicit timezone-aware market clock required; naive time is not inferred as UTC")
    if data.attrs:
        raise NotImplementedError("run-pack market attrs need an explicit manifest extension; do not strip financial attrs to bypass it")


@dataclass(frozen=True)
class _RunPackCalibration(ContinuousMode5Calibration):
    """Cold execution-time validation, delegating all financial work unchanged."""
    run_pack: object
    archive_access: object = None

    def preflight(self, engine, data, index, param_ranges):
        # The shared calendar can normalize naive timestamps before preflight;
        # validate the original scorer input as well as that aligned view.
        original = getattr(engine.scorer, "market_data", None)
        if original is None:
            raise NotImplementedError("run-pack preflight requires the original endpoint market witness")
        _market_contract(original)
        _market_contract(data)
        self.run_pack.verify(dossier=self.dossier, catalog=self.catalog,
            access=self.access, archive_access=self.archive_access)
        super().preflight(engine, data, index, param_ranges)


@dataclass(frozen=True)
class Mode5RunPack:
    record: Record

    @classmethod
    def compile(cls, worksheet, *, dossier, catalog, access, archive_access=None):
        """Compile a selected recipe without touching a strategy or journal."""
        worksheet.verify(dossier=dossier, catalog=catalog, archive_access=archive_access)
        selected = worksheet.record.data["selection"]
        if selected is None:
            raise PermissionError("explicit researcher choice required before compilation")
        option = next(c for c in worksheet.record.data["cards"]
                      if c["recipe"]["option_id"] == selected["option_id"])
        if option["readiness"] != "READY_FOR_PREFLIGHT":
            raise NotImplementedError("NOT_EXECUTABLE: " + "; ".join(option["missing_contracts"]))
        recipe = CalibrationRecipe(Record.of(option["recipe"]))
        plan, binding = recipe.resolve(dossier)
        from .donor_binding import verify_recipe_donors
        verify_recipe_donors(recipe, dossier=dossier, binding=binding, catalog=catalog, access=access)
        from quantbt.mode5.dossier.plans import CalibrationPlan
        # Scientific fields stay identical; each researcher revision gets a
        # distinct plan seal and cannot inherit an earlier choice's chronology.
        reason = Record.of(dict(worksheet_id=worksheet.identity,
            researcher=selected["researcher"], choice_reason=selected["reason"],
            recipe_rationale=recipe.record.data["reason"])).payload
        plan = CalibrationPlan.search(dossier, recipe.record.data["spec"], reason)
        declared = selection_access(plan.record.data["recipe"]["reuse"]["selection_policy"])
        if access != declared:
            raise PermissionError("changed selection rights require a revised choice/plan")
        verify_sources(catalog, access)
        diagnostic = worksheet.record.data["diagnostic"]
        if diagnostic is not None:
            for witness in catalog.require_ref(diagnostic["ref"])["source_witnesses"]:
                from quantbt.mode5.diagnostics.access import AccessWitness
                access.require(AccessWitness(**witness))
        sources = [{k: v for k, v in source.items() if k != "path"}
                   for source in catalog.manifest.data["sources"]]
        return cls(Record.of(dict(schema="quantbt.mode5.run_pack.v1",
            worksheet=worksheet.record.data, worksheet_id=worksheet.identity,
            plan=plan.record.data, plan_id=plan.record.identity,
            binding=binding.data, binding_id=binding.identity,
            external_sources=sources, state="COMPILED_REQUIRES_CURRENT_PREFLIGHT",
            automatic_routing=False, deployment_authorized=False)))

    def __post_init__(self):
        d = self.record.data
        if (set(d) != {"schema", "worksheet", "worksheet_id", "plan", "plan_id", "binding",
                       "binding_id", "external_sources", "state", "automatic_routing", "deployment_authorized"}
                or d["schema"] != "quantbt.mode5.run_pack.v1"
                or d["state"] != "COMPILED_REQUIRES_CURRENT_PREFLIGHT"
                or d["automatic_routing"] is not False or d["deployment_authorized"] is not False
                or Record.of(d["worksheet"]).identity != d["worksheet_id"]
                or Record.of(d["plan"]).identity != d["plan_id"]
                or Record.of(d["binding"]).identity != d["binding_id"]):
            raise ValueError("complete content-bound non-promoting run pack required")
        worksheet = CalibrationWorksheet(Record.of(d["worksheet"]))
        choice = worksheet.record.data["selection"]
        if not isinstance(choice, dict) or set(choice) != {
                "option_id", "researcher", "reason", "parent_worksheet_id", "previous_choice", "applies_configuration"}:
            raise ValueError("complete explicit researcher choice required")
        from quantbt.mode5.dossier.records import require_text
        for name in ("option_id", "researcher", "reason", "parent_worksheet_id"):
            require_text(choice[name])
        if choice["applies_configuration"] is not False:
            raise ValueError("a worksheet choice is not execution authority")
        if len(self.record.payload.encode()) > 8 * 1024 * 1024:
            raise ValueError("run pack exceeds 8 MiB; external evidence must not be bundled")

    @property
    def identity(self):
        return self.record.identity

    def verify(self, *, dossier, catalog, access, archive_access=None):
        rebuilt = self.compile(CalibrationWorksheet(Record.of(self.record.data["worksheet"])),
            dossier=dossier, catalog=catalog, access=access, archive_access=archive_access)
        if rebuilt.record != self.record:
            raise ValueError("stale or altered run pack; recompile from current evidence")
        return self

    def export(self, directory, *, private=False):
        if private is not True:
            raise PermissionError("run-pack export contains private configuration; require private=True")
        directory = _regular(directory)
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        write_json(directory / "run_pack.json", self.record.data)
        write_json(directory / "manifest.json", dict(schema="quantbt.mode5.run_pack_manifest.v1",
            identity=self.identity, source_files_bundled=False, evidence_paths_bundled=False,
            requires_external_dossier_catalog_strategy_market=True))
        with (directory / "run_mode5.py").open("x", encoding="ascii") as stream:
            stream.write(RUNNER)
        return directory / "run_pack.json"

    @classmethod
    def read(cls, path, *, expected_identity):
        path = _regular(path)
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("run-pack input byte budget exceeded")
        payload = path.read_text(encoding="utf-8")
        result = cls(Record.of(json.loads(payload, object_pairs_hook=_unique)))
        if result.identity != expected_identity:
            raise ValueError("run-pack identity differs from independently retained expected identity")
        return result

    def prepare(self, *, dossier, catalog, journal, access, data, strategy, param_ranges,
                account_kwargs=None, execution_endpoint=None, target_mode="pct_equity",
                archive_access=None, prepared=True):
        """Return the existing endpoint only after its actual data/config preflight.

        Strategy invocation and optimizer search happen only on backtest(). A
        fresh journal seals an imported choice now, never at a historical time.
        """
        self.verify(dossier=dossier, catalog=catalog, access=access, archive_access=archive_access)
        _market_contract(data)
        if not isinstance(journal, GovernanceLog):
            raise TypeError("explicit existing GovernanceLog required")
        from quantbt.mode5.dossier.plans import CalibrationPlan
        plan = CalibrationPlan(Record.of(self.record.data["plan"]))
        binding = Record.of(self.record.data["binding"])
        calibration = _RunPackCalibration(dossier, plan, catalog, journal, binding, self, archive_access)
        account = dict(account_kwargs or {})
        if execution_endpoint is not None:
            if account:
                raise ValueError("supply original execution endpoint or account kwargs, not both")
            account["execution_endpoint"] = execution_endpoint
        b = binding.data
        from quantbt import QuantBTEndpoint
        endpoint = QuantBTEndpoint.walk_forward(strategy_class=strategy, target_mode=target_mode,
            optimization_mode="mode_5_full_robust", optimization_schedule="global",
            split_frequency="single",
            optuna_trials=plan.record.data["search_budget"],
            random_seed=plan.record.data["recipe"]["sampler"]["seeds"][0],
            optimization_config=dict(scoring_backend="endpoint", is_subperiods=1,
                fold_account_policy="carry_position",
                native_prepared_wfo="off", use_prepared_scoring_cache=prepared,
                sampler_config=SamplerConfig(**b["sampler"]), sampler_warm_start=b["warm_start"],
                mode5_calibration=calibration), **account)
        from quantbt.endpoint import _WalkForwardEndpointScorer
        from quantbt.walkforward import WalkForwardEngine
        scorer = _WalkForwardEndpointScorer(endpoint.config, target_mode,
            wf_config=endpoint.config.walkforward_config, market_data=data)
        engine = WalkForwardEngine(strategy=strategy, config=endpoint.config.walkforward_config, scorer=scorer)
        try:
            calibration.preflight(engine, data, data.index, param_ranges)
            from quantbt.mode5.continuous_producer import qualify_producer
            qualify_producer(scorer, strategy, calibration.continuous_contract)
            from quantbt.optimization.wfo_study import prepare_wfo_studies
            from quantbt.core.wfo_contracts import strategy_fingerprint
            prepare_wfo_studies(endpoint.config.walkforward_config, param_ranges,
                [(0, engine.build_folds(data.index))], strategy_identity=strategy_fingerprint(strategy),
                derive_seed=None)
            for start in binding.data["warm_start"]:
                calibration.continuous_contract.geometry.resolve(start["params"])
        finally:
            scorer.release_prepared_state()
        history = journal.history()
        if any(event.data["kind"] == "FORMAL_SEARCH_STARTED" for event in history):
            raise PermissionError("run pack cannot resume or reseal an already started study")
        if not history:
            choice = self.record.data["worksheet"]["selection"]
            journal.seal_dossier(dossier, catalog)
            journal.seal_plan(dossier, plan, catalog, researcher=choice["researcher"], reason=choice["reason"])
        elif (history[-1].data["kind"] != "PLAN_SEALED"
                or history[-1].data["payload"]["plan_id"] != plan.record.identity):
            raise PermissionError("journal does not end at this explicitly sealed plan")
        return endpoint

    def reconcile(self, result):
        from .reconcile import reconcile
        return reconcile(self, result)

    def winner_report(self, result, *, access, witness, source_ref, request=None):
        """Same opt-in report owner as result.research_report, after reconciliation."""
        from ..winner import WinnerQualificationReport
        from quantbt.mode5.decision_report import DecisionReport
        retained = self.reconcile(result)
        data = retained.record.data
        if data['status'] not in {'RECONCILED_RETAINED_RUN', 'NO_SELECTION'}:
            raise ValueError('winner report needs this pack\'s reconciled original outcome')
        return WinnerQualificationReport.build(DecisionReport(Record.of(data['actual_decision'])),
            access=access, witness=witness, source_ref=source_ref, request=request,
            result=None if data['status'] == 'NO_SELECTION' else result)

    def to_dict(self, *, report=None, private=False):
        if type(private) is not bool:
            raise ValueError("private disclosure requires an explicit boolean")
        if report is not None and report.record.data["pack_id"] != self.identity:
            raise ValueError("post-run report belongs to another run pack")
        return dict(schema="quantbt.mode5.handoff_report.v1",
            pack_id=self.identity if private else "REDACTED",
            worksheet=CalibrationWorksheet(Record.of(self.record.data["worksheet"])).to_dict(private=private),
            post_run=report.to_dict(private=private) if report is not None else dict(status="NOT_RUN"))

    def to_json(self, *, report=None, private=False):
        return Record.of(self.to_dict(report=report, private=private)).payload

    def to_markdown(self, *, report=None, private=False):
        self.to_dict(report=report, private=private)
        from .render import render_worksheet
        return render_worksheet(CalibrationWorksheet(Record.of(self.record.data["worksheet"])),
            private=private, run_report=report)

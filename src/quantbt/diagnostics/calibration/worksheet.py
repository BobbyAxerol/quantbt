"""Researcher-owned recipe choices over existing evidence, never auto routing."""
from dataclasses import asdict, dataclass
import json

from quantbt.mode5.continuous_binding import ContinuousMode5Calibration
from quantbt.mode5.diagnostics.access import AccessPolicy, AccessWitness
from quantbt.mode5.diagnostics.identity import digest
from quantbt.mode5.dossier.dossier import Dossier
from quantbt.mode5.dossier.plans import CalibrationPlan, FIELDS
from quantbt.mode5.dossier.records import Record, require_text
from quantbt.mode5.selection.contracts import Formula
from quantbt.optimization import SamplerConfig
from quantbt.optimization.parameter_space import NormalizedSearchSpace
from quantbt.optimization.samplers import validate_sampler_geometry


def selection_access(value):
    return AccessPolicy(**{**value, "roles": tuple(value["roles"]),
                          "manifests": tuple(value["manifests"])})


def verify_sources(catalog, access):
    """Current access is checked even when a catalog was assembled earlier."""
    catalog.verify_current()
    for source in catalog.manifest.data["sources"]:
        access.require(AccessWitness(**source["witness"]))


@dataclass(frozen=True)
class CalibrationRecipe:
    record: Record

    @classmethod
    def continuous(cls, dossier, *, option_id, binding, param_ranges, formula,
                   selector_id, search_budget, seed, access, validation,
                   failure_policy, reason):
        """Resolve identifiers mechanically; numeric preferences stay explicit.

        The caller's diagnostic producer supplies its original continuous
        binding. This helper neither diagnoses an alpha nor chooses preferences.
        """
        if not isinstance(formula, Formula) or not isinstance(access, AccessPolicy):
            raise TypeError("explicit formula and selection access required")
        if access.purpose != "selection" or type(seed) is not int:
            raise ValueError("selection policy and exact integer seed required")
        require_text(failure_policy)
        require_text(reason)
        b = binding.data
        spec = {name: {"contract_id": "diagnostics_handoff_v1/" + name} for name in FIELDS}
        spec.update(search_budget=search_budget,
            sampler=dict(name=b["sampler"]["name"], seeds=[seed],
                schedule="sequential_exact" if b["batch_size"] == 1 else "fixed_batch",
                fallback=failure_policy),
            objective=dict(version=formula.version, channel=asdict(formula.channel),
                coefficients=dict(formula.coefficients), reference_id=b["reference"]["reference_id"]),
            selector=dict(id=selector_id, tie_break="candidate_id_lexicographic_v1"),
            domain=dict(schema_id=dossier.record.data["context"]["schema"],
                ranges=NormalizedSearchSpace(param_ranges).portable_ranges()))
        from quantbt.mode5.continuous_binding import restore_geometry
        spec["domain"]["effective_geometry_identity"] = restore_geometry(b["continuous"]["geometry"]).identity
        spec["retention"].update(contract_id="continuous_account_observation_v1",
            runtime_binding_identity=binding.identity)
        spec["probes"].update(design="schema_numeric_offsets_v1" if b["local_offsets"] else "no_local_probes_v1",
            budget=len(b["local_offsets"]) * search_budget)
        spec["validation"].update(validation)
        spec["reuse"]["selection_policy"] = asdict(access)
        return cls.from_spec(option_id=option_id, binding=binding, spec=spec, reason=reason,
            field_origins={name: "researcher-supplied binding/formula/policy; identifiers mechanically resolved"
                           for name in (*FIELDS, "search_budget")})

    @classmethod
    def from_spec(cls, *, option_id, binding, spec, reason, field_origins):
        require_text(option_id)
        require_text(reason)
        if not isinstance(binding, Record):
            raise TypeError("immutable binding required")
        if set(field_origins) != set(FIELDS) | {"search_budget"}:
            raise ValueError("every resolved recipe field needs an explicit origin")
        for value in field_origins.values():
            require_text(value)
        return cls(Record.of(dict(option_id=option_id, kind="CONTINUOUS_MODE5",
            binding=binding.data, spec=spec, reason=reason, field_origins=field_origins,
            missing_contracts=[], economic_superiority="NOT_QUALIFIED")))

    @classmethod
    def research_only(cls, *, option_id, reason, missing_contracts):
        require_text(option_id)
        require_text(reason)
        if not missing_contracts:
            raise ValueError("unsupported research option needs named missing contracts")
        for value in missing_contracts:
            require_text(value)
        return cls(Record.of(dict(option_id=option_id, kind="RESEARCH_ONLY", binding=None,
            spec=None, reason=reason, field_origins={}, missing_contracts=list(missing_contracts),
            economic_superiority="NOT_QUALIFIED")))

    def __post_init__(self):
        d = self.record.data
        if set(d) != {"option_id", "kind", "binding", "spec", "reason", "field_origins",
                       "missing_contracts", "economic_superiority"} or d["economic_superiority"] != "NOT_QUALIFIED":
            raise ValueError("complete non-promoting recipe required")
        require_text(d["option_id"])
        require_text(d["reason"])
        if d["kind"] == "RESEARCH_ONLY":
            if d["binding"] is not None or d["spec"] is not None or not d["missing_contracts"] or d["field_origins"]:
                raise ValueError("research-only recipe cannot contain executable fields")
        elif d["kind"] != "CONTINUOUS_MODE5" or not isinstance(d["binding"], dict) or not isinstance(d["spec"], dict):
            raise ValueError("explicit supported or research-only recipe required")

    def resolve(self, dossier):
        d = self.record.data
        if d["kind"] != "CONTINUOUS_MODE5":
            raise NotImplementedError("NOT_EXECUTABLE: " + "; ".join(d["missing_contracts"]))
        if set(d["field_origins"]) != set(FIELDS) | {"search_budget"}:
            raise ValueError("complete field origins required")
        for value in d["field_origins"].values():
            require_text(value)
        plan = CalibrationPlan.search(dossier, d["spec"], d["reason"])
        binding = Record.of(d["binding"])
        if dossier.record.data["context"]["scope"] != binding.identity:
            raise ValueError("binding change requires a revised diagnostic context")
        # Construction validates the existing contract but never reads the journal.
        calibration = ContinuousMode5Calibration(dossier, plan, None, None, binding)
        incumbent = binding.data["selection"]["incumbent_params"]
        starts = binding.data["warm_start"]
        if incumbent is not None and (not starts or calibration.continuous_contract.geometry.resolve(
                starts[0]["params"]).params != incumbent):
            raise ValueError("incumbent requires the first in-budget warm-start coordinate")
        ranges = {s.name: d["spec"]["domain"]["ranges"][s.name]
                  for s in calibration.continuous_contract.geometry.specs}
        validate_sampler_geometry(SamplerConfig(**binding.data["sampler"]), ranges)
        return plan, binding


@dataclass(frozen=True)
class CalibrationWorksheet:
    record: Record

    @classmethod
    def create(cls, *, dossier, catalog, options, findings=(), archive=None,
               archive_access=None, diagnostic_report=None):
        if not isinstance(dossier, Dossier) or not options:
            raise TypeError("verified dossier and explicit recipe options required")
        verify_sources(catalog, catalog.policy)
        dossier.verify(catalog)
        if len({o.record.data["option_id"] for o in options}) != len(options):
            raise ValueError("distinct recipe options required")
        cards = []
        for option in options:
            try:
                option.resolve(dossier)
                readiness, missing = "READY_FOR_PREFLIGHT", []
            except (ValueError, TypeError, KeyError, NotImplementedError) as error:
                readiness, missing = "NOT_EXECUTABLE", [str(error)]
            cards.append(dict(recipe=option.record.data, readiness=readiness, missing_contracts=missing))
        rows = []
        for finding in findings:
            finding.verify(catalog)
            rows.append(finding.record.data)
        diagnostic = None
        if diagnostic_report is not None:
            diagnostic_report.authorize(catalog.policy)
            original = diagnostic_report.record.data
            context = dossier.record.data["context"]
            if any(original["context"][key] != context[target] for key, target in
                   (("alpha_id", "alpha"), ("market_id", "data"), ("economics_id", "economics"))):
                raise ValueError("shared diagnostic report context differs from dossier")
            diagnostic = dict(identity=diagnostic_report.identity, coverage=original["coverage"],
                activity=original["activity"], sampler_compatibility=original["sampler_compatibility"])
        archive_data = None
        if archive is not None:
            if archive.record.data["context_id"] != digest(dossier.record.data["context"]):
                raise ValueError("archive context differs from calibration context")
            archive.verify(catalog=catalog, access=archive_access)
            archive_data = archive.record.data
        result = cls(Record.of(dict(schema="quantbt.calibration_worksheet.v1",
            dossier_id=dossier.record.identity, context=dossier.record.data["context"],
            catalog_id=catalog.manifest.identity, diagnostic=diagnostic, archive=archive_data,
            cards=cards, findings=rows, selection=None,
            authority=dict(automatic_routing=False, optimizer_started=False, deployment_authorized=False))))
        if len(result.record.payload.encode()) > 4 * 1024 * 1024:
            raise ValueError("worksheet exceeds 4 MiB; reference evidence instead of copying paths")
        return result

    def __post_init__(self):
        d = self.record.data
        if set(d) != {"schema", "dossier_id", "context", "catalog_id", "diagnostic", "archive",
                       "cards", "findings", "selection", "authority"} or d["schema"] != "quantbt.calibration_worksheet.v1":
            raise ValueError("complete versioned worksheet required")
        if d["authority"] != dict(automatic_routing=False, optimizer_started=False, deployment_authorized=False):
            raise ValueError("worksheet cannot authorize automatic execution or promotion")
        if not d["cards"] or len({c["recipe"]["option_id"] for c in d["cards"]}) != len(d["cards"]):
            raise ValueError("distinct nonempty recipe cards required")
        for card in d["cards"]:
            CalibrationRecipe(Record.of(card["recipe"]))
            if card["readiness"] not in {"READY_FOR_PREFLIGHT", "NOT_EXECUTABLE"}:
                raise ValueError("explicit technical readiness required")
        previous = d["selection"]
        for _ in range(64):
            if previous is None:
                break
            if (not isinstance(previous, dict) or set(previous) != {"option_id", "researcher", "reason",
                    "parent_worksheet_id", "previous_choice", "applies_configuration"}
                    or previous["option_id"] not in {c["recipe"]["option_id"] for c in d["cards"]}
                    or previous["applies_configuration"] is not False):
                raise ValueError("complete non-executing choice chain required")
            for key in ("researcher", "reason", "parent_worksheet_id"):
                require_text(previous[key])
            old = {**d, "selection": previous["previous_choice"]}
            if Record.of(old).identity != previous["parent_worksheet_id"]:
                raise ValueError("choice parent differs from retained prior worksheet")
            previous = previous["previous_choice"]
        else:
            raise ValueError("choice history exceeds 64 revisions; start a referenced new worksheet")

    @classmethod
    def from_json(cls, payload):
        return cls(Record.of(json.loads(payload)))

    @property
    def identity(self):
        return self.record.identity

    def choose(self, option_id, *, researcher, reason):
        require_text(researcher)
        require_text(reason)
        d = self.record.data
        if option_id not in {c["recipe"]["option_id"] for c in d["cards"]}:
            raise ValueError("choice outside worksheet requires a revised worksheet")
        d["selection"] = dict(option_id=option_id, researcher=researcher, reason=reason,
            parent_worksheet_id=self.identity, previous_choice=d["selection"], applies_configuration=False)
        return type(self)(Record.of(d))

    def verify(self, *, dossier, catalog, archive_access=None):
        if self.record.data["dossier_id"] != dossier.record.identity:
            raise ValueError("worksheet belongs to another dossier")
        if self.record.data["context"] != dossier.record.data["context"]:
            raise ValueError("worksheet context differs from original dossier")
        verify_sources(catalog, catalog.policy)
        dossier.verify(catalog)
        if self.record.data["catalog_id"] != catalog.manifest.identity:
            raise ValueError("catalog revision requires a new worksheet")
        from quantbt.mode5.dossier.researcher_report import Finding
        for value in self.record.data["findings"]:
            Finding(Record.of(value)).verify(catalog)
        if self.record.data["archive"] is not None:
            from ..archive import ArchiveReview
            ArchiveReview(Record.of(self.record.data["archive"])).verify(catalog=catalog, access=archive_access)
        for card in self.record.data["cards"]:
            if card["readiness"] == "READY_FOR_PREFLIGHT":
                CalibrationRecipe(Record.of(card["recipe"])).resolve(dossier)
        return self

    def to_dict(self, *, private=False):
        if type(private) is not bool:
            raise ValueError("private disclosure requires an explicit boolean")
        if private:
            return self.record.data
        d = self.record.data
        return dict(schema="quantbt.calibration_worksheet.public.v1",
            options=[dict(index=i, readiness=c["readiness"], kind=c["recipe"]["kind"],
                          economic_superiority="NOT_QUALIFIED") for i, c in enumerate(d["cards"])],
            finding_count=len(d["findings"]), archive_supplied=d["archive"] is not None,
            choice_supplied=d["selection"] is not None, authority=d["authority"])

    def to_json(self, *, private=False):
        return Record.of(self.to_dict(private=private)).payload

    def to_markdown(self, *, private=False):
        from .render import render_worksheet
        return render_worksheet(self, private=private)

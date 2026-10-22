"""Bounded local M5-11.14 qualification; no private-alpha optimizer or build.

The synthetic endpoint checks are explicitly requested, counted and guarded.
Existing private economic results are cold-read separately, never rerun here.
"""
import argparse
from contextlib import contextmanager
from copy import copy, deepcopy
import json
from pathlib import Path
import resource
import shutil
import time
import traceback


@contextmanager
def counted_work(work):
    import optuna
    from quantbt import QuantBTEndpoint
    original_account = QuantBTEndpoint._run_single
    original_ask = optuna.study.Study.ask

    def account(self, *args, **kwargs):
        if work["financial_invocations"] >= 24:
            raise RuntimeError("synthetic financial budget exhausted before invocation")
        work["financial_invocations"] += 1
        return original_account(self, *args, **kwargs)

    def ask(self, *args, **kwargs):
        if work["proposal_slots"] >= 16:
            raise RuntimeError("synthetic proposal budget exhausted before ask")
        work["proposal_slots"] += 1
        return original_ask(self, *args, **kwargs)

    QuantBTEndpoint._run_single, optuna.study.Study.ask = account, ask
    try:
        yield
    finally:
        QuantBTEndpoint._run_single, optuna.study.Study.ask = original_account, original_ask


def _write(path, value):
    from quantbt.mode5.artifacts import write_json
    write_json(path, value)


def qualify(directory, *, prior_work=None):
    from examples.mode5_diagnostic_handoff import run_demo
    from quantbt import QuantBTEndpoint
    import numpy as np
    import pandas as pd

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    disk_before = shutil.disk_usage(directory).free
    if disk_before < 5 * 1024**3 + 128 * 1024**2:
        raise RuntimeError("5 GiB disk reserve beyond forecast is unavailable")
    prior = dict(proposal_slots=0, financial_invocations=0, private_alpha_optimizers=0, model_fits=0)
    if prior_work is not None:
        previous = json.loads(Path(prior_work).read_text())
        for key in prior:
            value = previous["work"][key]
            if type(value) is not int or value < 0:
                raise ValueError("exact nonnegative prior-work counters required")
            prior[key] = value
    work = dict(prior)
    report = dict(schema="quantbt.m5_11_14.synthetic_qualification.v1", status="RUNNING",
        work=work, prior_work=prior, cases=[], mutation_checks=[])
    try:
        with counted_work(work):
            retained = []
            for optional in (False, True):
                case = run_demo(directory / ("archive" if optional else "no-archive"), optional_archive=optional)
                actual = case["report"].record.data
                _write(directory / ("archive-initial-result.json" if optional else "no-archive-initial-result.json"), actual)
                if actual["status"] != "RECONCILED_RETAINED_RUN":
                    raise AssertionError("actual end-to-end handoff not reconciled: " + str(actual["mismatches"]))
                pack = case["pack"]
                _write(directory / ("archive-report.json" if optional else "no-archive-report.json"),
                    pack.to_dict(report=case["report"], private=True))
                with (directory / ("archive-report.md" if optional else "no-archive-report.md")).open("x") as stream:
                    stream.write(pack.to_markdown(report=case["report"], private=True))
                report["cases"].append(dict(optional_archive=optional, status=actual["status"],
                    pack_id=pack.identity, selected_params_digest=actual["actual_decision"]["runtime"]["selected_params_digest"],
                    attempts=actual["actual_decision"]["summary"]["attempts"],
                    states=actual["actual_decision"]["summary"]["trial_states"],
                    final_account=actual["final_account"],
                    archive_dispositions=[r["disposition"] for r in case["inputs"]["archive"].record.data["rows"]]
                        if optional else []))
                retained.append(case)

            first = retained[0]
            params = first["result"].metadata["walk_forward"]["best_trial"]["params"]
            inputs = first["inputs"]
            direct = QuantBTEndpoint.pct_equity(**inputs["account_kwargs"])
            signal = inputs["strategy"](inputs["data"], params, inputs["data"].index, inputs["data"].index, None)
            control = direct.backtest(data=inputs["data"], signal=signal)
            for name in ("equity", "positions", "fees", "funding", "margin"):
                left, right = getattr(control, name, None), getattr(first["result"], name, None)
                if left is not None or right is not None:
                    np.testing.assert_array_equal(np.asarray(left), np.asarray(right))
            report["direct_original_account_control"] = "EXACT_ARRAY_EQUALITY"

            def changed_result():
                candidate = copy(first["result"])
                candidate.metadata = deepcopy(first["result"].metadata)
                return candidate

            candidate = changed_result()
            candidate.equity = candidate.equity.copy()
            candidate.equity.index = candidate.equity.index + pd.Timedelta(days=1)
            report["mutation_checks"].append(dict(kind="shifted_account_calendar", status=first["pack"].reconcile(candidate).record.data["status"]))
            candidate = changed_result()
            candidate.equity = candidate.equity.copy()
            candidate.equity.iloc[-1] += 1
            report["mutation_checks"].append(dict(kind="changed_final_mark", status=first["pack"].reconcile(candidate).record.data["status"]))
            for kind in ("sampler_seed", "warm_source", "selection_margin", "reference", "plan"):
                candidate = changed_result()
                metadata = candidate.metadata["walk_forward"]["mode5_diagnostics_first"]
                if kind == "sampler_seed":
                    metadata["sampler"]["kwargs"]["seed"] += 1
                elif kind == "warm_source":
                    metadata["sampler"]["rows"][0]["source"] = "warm_start"
                elif kind == "selection_margin":
                    metadata["decision"]["minimum_improvement"] += 1
                    from quantbt.mode5.diagnostics.identity import digest
                    metadata["selection_decision_id"] = digest(metadata["decision"])
                elif kind == "reference":
                    metadata["decision"]["reference"]["revision"] = "forged"
                else:
                    metadata["calibration_plan_id"] = "f" * 64
                report["mutation_checks"].append(dict(kind=kind, status=first["pack"].reconcile(candidate).record.data["status"]))
            if any(row["status"] != "MISMATCH" for row in report["mutation_checks"]):
                raise AssertionError("counterfeit actual-run control escaped mismatch detection")
            report["status"] = "PASS_SYNTHETIC_INTEGRATION_ONLY"
    except BaseException as error:
        report.update(status="FAIL_RETAINED", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
        raise
    finally:
        report.update(wall_seconds=time.perf_counter()-started, cpu_seconds=time.process_time()-cpu,
            process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            disk_free_before=disk_before, disk_free_after=shutil.disk_usage(directory).free)
        report["new_work"] = {k: work[k]-prior[k] for k in prior}
        report["rss_budget_pass"] = report["process_peak_rss_kib"] <= 512 * 1024
        if not report["rss_budget_pass"]:
            report["status"] = "FAIL_RESOURCE_RETAINED"
        _write(directory / "qualification.json", report)
    if not report["rss_budget_pass"]:
        raise RuntimeError("registered process RSS cap exceeded")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--directory", type=Path)
    choice.add_argument("--benchmark-directory", type=Path)
    choice.add_argument("--final-directory", type=Path)
    parser.add_argument("--prior-work", type=Path)
    args = parser.parse_args(argv)
    if args.benchmark_directory:
        report = benchmark(args.benchmark_directory)
        print(json.dumps(report, indent=2))
    elif args.final_directory:
        if args.prior_work is None:
            parser.error("--final-directory requires cumulative --prior-work")
        print(json.dumps(final_smoke(args.final_directory, args.prior_work), indent=2))
    else:
        report = qualify(args.directory, prior_work=args.prior_work)
        print(json.dumps({key: report[key] for key in ("status", "work", "wall_seconds", "cpu_seconds", "process_peak_rss_kib")}, indent=2))


def benchmark(directory):
    """Fresh cold-layer assemblies after import; no claim of cold OS caches."""
    from examples.mode5_diagnostic_handoff import build_inputs, OPTION_ID
    from quantbt.diagnostics import Mode5RunPack
    from quantbt import QuantBTEndpoint
    import optuna
    import numpy as np
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    inputs = build_inputs(directory / "inputs", optional_archive=True)
    chosen = inputs["worksheet"].choose(OPTION_ID, researcher="benchmark", reason="Mechanical cold-path measurement only")
    old_backtest, old_ask = QuantBTEndpoint.backtest, optuna.study.Study.ask
    def forbidden(*args, **kwargs):
        raise AssertionError("cold compiler/render attempted execution or an optimizer trial")
    samples, sizes = [], []
    QuantBTEndpoint.backtest, optuna.study.Study.ask = forbidden, forbidden
    try:
        for _ in range(7):
            before = time.perf_counter()
            pack = Mode5RunPack.compile(chosen, dossier=inputs["dossier"], catalog=inputs["catalog"],
                access=inputs["access"], archive_access=inputs["archive_access"])
            compiled = time.perf_counter()
            markdown, payload = pack.to_markdown(private=True), pack.to_json(private=True)
            rendered = time.perf_counter()
            samples.append(dict(compile_ms=1000*(compiled-before), render_ms=1000*(rendered-compiled),
                                combined_ms=1000*(rendered-before)))
            sizes.append(len(markdown.encode())+len(payload.encode()))
    finally:
        QuantBTEndpoint.backtest, optuna.study.Study.ask = old_backtest, old_ask
    report = dict(schema="quantbt.m5_11_14.cold_benchmark.v1", status="PASS_COLD_SYNTHETIC_ONLY",
        samples=samples, repeats=len(samples), financial_invocations=0, optimizer_proposals=0, model_fits=0,
        maximum_json_plus_markdown_bytes=max(sizes),
        process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        p50_ms=float(np.percentile([r["combined_ms"] for r in samples],50)),
        p95_ms=float(np.percentile([r["combined_ms"] for r in samples],95)),
        limitations=["Seven repeats; p95 is a low-precision descriptive statistic.",
            "Imports and input construction excluded from timings; full process RSS includes imports.",
            "No matched old-vs-new or whole-WFO speedup is measured; filesystem cache is not forced cold.",
            "Small synthetic metadata workload, not a seven-alpha full-history study benchmark."])
    _write(directory / "benchmark.json", report)
    return report


def final_smoke(directory, prior_work):
    """Two-attempt source-final control; preserve cumulative failed work."""
    from examples.mode5_diagnostic_handoff import build_inputs, OPTION_ID
    from quantbt.diagnostics import Mode5RunPack
    from quantbt.mode5.dossier.governance import GovernanceLog
    from quantbt.mode5.runtime import Mode5NoSelectionError
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    previous = json.loads(Path(prior_work).read_text())
    work = dict(previous["work"])
    if any(type(v) is not int or v < 0 for v in work.values()):
        raise ValueError("exact prior cumulative counters required")
    prior = dict(work)
    if work["proposal_slots"] + 2 > 16 or work["financial_invocations"] + 4 > 24:
        raise RuntimeError("source-final control does not fit the original cumulative budget")
    started, cpu = time.perf_counter(), time.process_time()
    report = dict(schema="quantbt.m5_11_14.final_smoke.v1", status="RUNNING", work=work,
        prior_work=prior, private_alpha_optimizers=0, model_fits=0)
    try:
        with counted_work(work):
            inputs = build_inputs(directory / "inputs", trials=2)
            chosen = inputs["worksheet"].choose(OPTION_ID, researcher="source-final-qualification",
                reason="Registered two-attempt final-source mechanical proof, not economic research")
            pack = Mode5RunPack.compile(chosen, dossier=inputs["dossier"], catalog=inputs["catalog"], access=inputs["access"])
            path = pack.export(directory / "run-pack", private=True)
            pack = Mode5RunPack.read(path, expected_identity=pack.identity)
            endpoint = pack.prepare(dossier=inputs["dossier"], catalog=inputs["catalog"],
                journal=GovernanceLog(directory / "journal"), access=inputs["access"], data=inputs["data"],
                strategy=inputs["strategy"], param_ranges=inputs["param_ranges"], account_kwargs=inputs["account_kwargs"])
            try:
                outcome = endpoint.backtest(data=inputs["data"], param_ranges=inputs["param_ranges"])
            except Mode5NoSelectionError as error:
                outcome = error
            actual = pack.reconcile(outcome)
            _write(directory / "actual-report.json", actual.record.data)
            with (directory / "handoff.md").open("x") as stream:
                stream.write(pack.to_markdown(report=actual, private=True))
            if actual.record.data["status"] != "RECONCILED_RETAINED_RUN":
                raise AssertionError("source-final endpoint result did not reconcile")
            report.update(status="PASS_SOURCE_FINAL_SYNTHETIC_ONLY", pack_id=pack.identity,
                reconciliation=actual.record.data["status"], annual_account_resets=0)
    except BaseException as error:
        report.update(status="FAIL_RETAINED", error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
        raise
    finally:
        report.update(wall_seconds=time.perf_counter()-started, cpu_seconds=time.process_time()-cpu,
            process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            new_work={k: work[k]-prior[k] for k in work})
        report["rss_budget_pass"] = report["process_peak_rss_kib"] <= 512 * 1024
        if not report["rss_budget_pass"]:
            report["status"] = "FAIL_RESOURCE_RETAINED"
        _write(directory / "qualification.json", report)
    if not report["rss_budget_pass"]:
        raise RuntimeError("registered process RSS cap exceeded")
    return report


if __name__ == "__main__":
    main()

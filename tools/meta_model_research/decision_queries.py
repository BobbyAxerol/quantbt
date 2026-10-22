"""Bounded original-route winner witnesses; no optimizer or training mutation."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import replace
import importlib
import importlib.util
from pathlib import Path
import resource
import signal
import sys
import time
from types import SimpleNamespace

import numpy as np

from quantbt.optimization.meta_selection.common import digest, wire
from .admission import BASE, load_corpus, pin, read, save_new
from .decision_value import DEFAULT, PRIVATE, guard, verify_inputs
from .protocol import GROUPS


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def independent_daily(result, observation):
    daily = result.equity.resample("D").last()
    values = np.asarray(daily, dtype=float)
    r = np.array(
        [(b - a) / a if a != 0 else 0.0 for a, b in zip(values[:-1], values[1:])]
    )
    r = r[np.isfinite(r)]
    std = float(np.std(r, ddof=1)) if len(r) > 1 else None
    expected = (
        float(np.mean(r) / std * np.sqrt(365)) if std is not None and std > 0 else None
    )
    if len(r) != observation.sample_count or (
        expected is not None
        and not np.isclose(expected, observation.raw_sharpe, rtol=1e-12, atol=1e-12)
    ):
        raise ValueError("independent daily raw metric disagrees")
    return dict(
        days=[t.isoformat() for t in daily.index],
        equity=list(values),
        sample_count=len(r),
        sample_std=std,
        raw_sharpe=expected,
    )


class OriginalQueries:
    def __init__(self, output):
        self.output = output
        self.stack = ExitStack()
        sys.path.insert(0, str(PRIVATE))
        self.private = importlib.import_module("admission")
        if Path(self.private.__file__).resolve() != PRIVATE / "admission.py":
            raise ValueError("foreign private admission import")
        self.driver = load_module(self.private.DRIVER, "ml06_original_driver")
        transaction = importlib.import_module("transaction_control")
        execution_registration = read(
            BASE / "long-rolling-monthly-v1/registration.json"
        )
        if (
            pin(execution_registration["binary"]["path"])
            != execution_registration["binary"]
        ):
            raise ValueError("original financial binary changed")
        self.runtime = self.stack.enter_context(
            transaction.loaded(
                self.driver, dict(binary=execution_registration["binary"])
            )
        )
        self.contexts = {}
        self.corpora = {}

    def close(self):
        self.stack.close()

    def run(self, request):
        from quantbt.endpoint import _make_walkforward_endpoint_scorer
        from quantbt.walkforward import WalkForwardEngine, PreparedWalkForwardContext
        from quantbt.optimization.meta_selection.domains.execution import (
            ExecutionDomainAdapter,
        )
        from wfo_provider import WfoProvider
        import first_origin_v2
        from price_guard import guarded_binding

        alpha, fold_id = request["group"], request["fold"]
        cpu, wall = time.process_time(), time.perf_counter()
        if alpha not in self.contexts:
            profile = read(BASE / "registration01.json")["profiles"][alpha]
            self.contexts[alpha] = self.driver.PreparedFullResearch(
                profile, request={"stop": "2026-10-01T00:00:00+00:00"}
            )
            self.corpora[alpha] = load_corpus(alpha)
        context, corpus = self.contexts[alpha], self.corpora[alpha]
        task = corpus.revisions[fold_id].task
        candidate = next(
            c for c in task.candidates if c.evaluation_id == request["winner"]
        )
        with self.driver._bindings(
            self.runtime, context, context.request(0), self.output, context.config
        ):
            geometry = importlib.import_module("private_inputs").schema(alpha)
            provider = WfoProvider(
                alpha,
                context.history,
                runtime=self.runtime,
                config=context.config,
                feedback_mode="transaction_v1",
                safe_point=lambda: guard(self.output),
            )
            endpoint = first_origin_v2.make_endpoint(provider, context.config, geometry)
            base = endpoint.config.walkforward_config
            wf = replace(
                base,
                window_mode="rolling",
                train_window="730D",
                metadata={
                    **base.metadata,
                    "execution_trial_output": "account_paths_v1",
                    "deterministic_is_shard_reuse": "no_rng_v1",
                },
            )
            endpoint.config = replace(endpoint.config, walkforward_config=wf)
            scorer = _make_walkforward_endpoint_scorer(
                endpoint.config,
                provider.route,
                symbols=["ETHUSDT"],
                wf_config=wf,
                market_data=provider.history,
                meta_metric_support=True,
            )
            engine = WalkForwardEngine(provider, config=wf, scorer=scorer)
            folds = engine.build_folds(provider.history.index)
            fold = folds[fold_id]
            if (
                fold.test_index[0] != task.forward_start
                or fold.test_index[-1] != task.forward_end
                or fold.train_index[0] != task.is_start
                or fold.train_index[-1] != task.is_end
            ):
                raise ValueError("query calendar differs from original task")
            engine._prepared_context = PreparedWalkForwardContext.prepare(
                data=provider.history,
                datetime_index=provider.history.index,
                folds=folds,
                config=wf,
            )
            scorer.bind_walkforward_context(engine._prepared_context)
            owner = SimpleNamespace(
                engine=engine,
                context=SimpleNamespace(instrument_id="ETHUSDT"),
                config=wf.meta_selection,
            )
            domain = ExecutionDomainAdapter(owner)
            try:
                evaluator, lifecycle = domain.observer_evaluator(
                    provider.history, fold, task
                )
                with guarded_binding():
                    evaluated = evaluator(candidate)
                observed = domain.observe(
                    evaluated.binding,
                    evaluated.original_result,
                    metric_adapter=scorer._meta_adapter,
                    economics_id=task.family.economics_id,
                    prepared_witness=scorer._meta_witness,
                ).observation
                result = evaluated.original_result
                oracle = independent_daily(result, observed)
                financial = dict(
                    final_equity=float(result.equity.iloc[-1]),
                    fees=float(np.asarray(result.fees).sum()),
                    funding=float(np.asarray(result.funding).sum()),
                    fills=len(result.fills),
                    exposed_bars=int(np.count_nonzero(np.asarray(result.positions))),
                    bars=len(result.equity),
                    liquidated=bool(result.liquidated),
                    paths_digest=digest(
                        {
                            k: np.asarray(getattr(result, k)).tolist()
                            for k in (
                                "equity",
                                "returns",
                                "positions",
                                "fees",
                                "funding",
                                "margin",
                            )
                        }
                    ),
                )
                expected = next(
                    (
                        o.observation
                        for o in corpus.revisions[fold_id].outcomes
                        if o.evaluation_id == candidate.evaluation_id
                    ),
                    None,
                )
                control_match = None
                if request["kind"] == "control":
                    if expected is None or wire(observed) != wire(expected):
                        raise ValueError(
                            "known original forward metric/account witness differs"
                        )
                    control_match = True
                context.verify()
                return dict(
                    schema="m4.ml06.original-forward.v1",
                    status="PASS_ORIGINAL_FORWARD",
                    request=request,
                    observation=wire(observed),
                    daily_oracle=oracle,
                    financial=financial,
                    known_witness_exact=control_match,
                    lifecycle_records=len(lifecycle),
                    domain_telemetry=wire(domain.metadata),
                    evaluation_only=True,
                    entered_training=False,
                    cpu_seconds=time.process_time() - cpu,
                    wall_seconds=time.perf_counter() - wall,
                    peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    / 1024,
                )
            finally:
                scorer.release_prepared_state()
                provider.close()
                domain.clear()


def roster(output):
    rows = read(output / "sealed.json")["rows"]
    queue = read(output / "query-roster.json")["admitted"]
    controls = []
    for group in GROUPS:
        row = next(
            r
            for r in rows
            if r["group"] == group
            and r["fold"] >= 25
            and r["policy"] == "N"
            and r["witness_status"] == "VALID"
        )
        controls.append(
            {k: row[k] for k in ("group", "fold", "policy", "winner", "query_id")}
            | dict(kind="control")
        )
    missing = [dict(r, kind="missing") for r in queue]
    pilot = controls[:]
    for group in GROUPS:
        item = next(
            (r for r in missing if r["group"] == group and r["policy"] == "X"), None
        )
        if item is not None:
            pilot.append(item)
    return pilot, missing


def execute(output, stage):
    verify_inputs(output)
    code = pin(Path(__file__))
    attempt = 1
    while (output / f"queries-{stage}-{attempt:02d}-registration.json").exists():
        attempt += 1
    registration = save_new(
        output / f"queries-{stage}-{attempt:02d}-registration.json",
        dict(
            schema="m4.ml06.query-stage-registration.v1",
            source=code,
            execution_registration=pin(
                BASE / "long-rolling-monthly-v1/registration.json"
            ),
            execution_binary=read(BASE / "long-rolling-monthly-v1/registration.json")[
                "binary"
            ],
            replay_source=pin(output / "sealed.json"),
            queue=pin(output / "query-roster.json"),
            stage=stage,
            max_cpu_seconds=7200,
            max_calls=132,
        ),
    )
    pilot, missing = roster(output)
    if stage == "pilot":
        planned = pilot
    else:
        gate = read(output / "pilot-forecast.json")
        if gate["status"] != "ADMITTED":
            raise ValueError("financial continuation not admitted by pilot")
        planned = missing
    existing = (
        list((output / "queries").glob("*.json"))
        if (output / "queries").exists()
        else []
    )
    spent = sum(read(p)["cpu_seconds"] for p in existing)
    if len(existing) > 132 or spent > 7200:
        raise RuntimeError("query budget exhausted")
    started, wall = time.process_time(), time.perf_counter()
    runner = OriginalQueries(output)
    try:
        for request in planned:
            path = output / "queries" / f"{request['kind']}-{request['query_id']}.json"
            if path.exists():
                previous = read(path)
                if (
                    previous["request"] != request
                    or previous["status"] != "PASS_ORIGINAL_FORWARD"
                ):
                    raise ValueError("incompatible or failed retained query")
                continue
            guard(output)
            completed = (
                list((output / "queries").glob("*.json"))
                if (output / "queries").exists()
                else []
            )
            if len(completed) >= 132 or spent + time.process_time() - started >= 7200:
                raise RuntimeError("query resource ceiling")
            if request["kind"] == "missing":
                control = next(
                    x
                    for x in pilot
                    if x["group"] == request["group"] and x["kind"] == "control"
                )
                proof = read(output / "queries" / f"control-{control['query_id']}.json")
                if proof.get("known_witness_exact") is not True:
                    raise ValueError("alpha lacks exact control")
            try:
                signal.signal(
                    signal.SIGALRM,
                    lambda *_: (_ for _ in ()).throw(
                        TimeoutError("ML06 query CPU/wall guard")
                    ),
                )
                signal.setitimer(
                    signal.ITIMER_REAL,
                    max(1.0, min(900.0, 7200 - spent - time.process_time() + started)),
                )
                result = runner.run(request)
                save_new(path, result)
                print(
                    dict(
                        group=request["group"],
                        fold=request["fold"],
                        kind=request["kind"],
                        seconds=round(result["wall_seconds"], 3),
                        status=result["observation"]["status"],
                    ),
                    flush=True,
                )
            except BaseException as error:
                save_new(
                    output
                    / "query-failures"
                    / f"{request['kind']}-{request['query_id']}.json",
                    dict(
                        request=request,
                        status="FAIL_RETAINED",
                        type=type(error).__name__,
                        error=str(error),
                        cpu_seconds=time.process_time() - started,
                    ),
                )
                raise
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
        if pin(Path(__file__)) != code:
            raise ValueError("query source changed during execution")
    finally:
        runner.close()
    result = dict(
        schema="m4.ml06.query-stage.v1",
        status="PASS",
        stage=stage,
        registration=registration,
        cpu_seconds=time.process_time() - started,
        wall_seconds=time.perf_counter() - wall,
        calls=len(list((output / "queries").glob("*.json"))),
        new_optimizer_proposals=0,
    )
    save_new(output / f"queries-{stage}-result.json", result)
    if stage == "pilot":
        outcomes = [
            read(output / "queries" / f"{r['kind']}-{r['query_id']}.json")
            for r in pilot
        ]
        remaining = len(missing) - sum(r["kind"] == "missing" for r in pilot)
        maximum = max(r["cpu_seconds"] for r in outcomes)
        projected = result["cpu_seconds"] + maximum * remaining
        save_new(
            output / "pilot-forecast.json",
            dict(
                status="ADMITTED" if projected <= 7200 else "NOT_ADMITTED",
                pilot_calls=len(outcomes),
                remaining_calls=remaining,
                max_call_cpu_seconds=maximum,
                median_call_cpu_seconds=float(
                    np.median([r["cpu_seconds"] for r in outcomes])
                ),
                projected_cpu_seconds=projected,
                maximum_cpu_seconds=7200,
                method="worst observed including initial setup times remaining; bound not ETA",
            ),
        )
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("stage", choices=("pilot", "remaining"))
    p.add_argument("--output", type=Path, default=DEFAULT)
    a = p.parse_args()
    print(execute(a.output, a.stage))


if __name__ == "__main__":
    main()

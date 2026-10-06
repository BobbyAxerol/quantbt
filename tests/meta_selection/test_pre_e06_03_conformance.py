"""The PRE02 public-runner conformance corpus on the approved C01 cohort."""

from dataclasses import replace

import optuna
import pytest

from tests.meta_selection import test_pre_e06_02_conformance as corpus
from tests.meta_selection import pre_e06_02_support as original
from tests.meta_selection.pre_e06_03_support import ROUTES, CUTOFFS, run

optuna.logging.set_verbosity(optuna.logging.WARNING)


@pytest.fixture(scope="module", params=ROUTES)
def history_run(request):
    return run(request.param)


@pytest.fixture(scope="module")
def matured(history_run):
    return {cutoff: run(history_run.route, "active", data=original.current(history_run.data, cutoff),
        start=str((cutoff+original.pd.Timedelta(days=1)).date()),
        history=original.clone_history(history_run.context.history)) for cutoff in CUTOFFS}


@pytest.fixture(autouse=True)
def actual_nested_runner(monkeypatch):
    # Reuse the invariant corpus, not its Mode 4 endpoint factory. No financial
    # scorer/selector is replaced; every run goes through the real nested seam.
    monkeypatch.setattr(corpus, "run", run)


class TestNestedConformance:
    test_pre03_matured_actual_fit_rank_and_applied_params = staticmethod(corpus.test_pre02_matured_actual_fit_rank_and_applied_params)
    test_pre03_m01_future_ohlcv_funding_real_active_runner = staticmethod(corpus.test_pre02_m01_future_ohlcv_funding_real_active_runner)
    test_pre03_original_raw_is_forward_and_final_account = staticmethod(corpus.test_pre02_original_raw_is_forward_and_final_account)
    test_pre03_full_multifold_continuous_original_account = staticmethod(corpus.test_pre02_full_multifold_continuous_original_account)
    test_pre03_off_shadow_exact_search_rng_and_original_account = staticmethod(corpus.test_pre02_off_shadow_exact_search_rng_and_original_account)
    test_pre03_m04_physical_history_order_same_active_decision = staticmethod(corpus.test_pre02_m04_physical_history_order_same_active_decision)
    test_pre03_m02_future_labels_and_candidate_archive_excluded = staticmethod(corpus.test_pre02_m02_future_labels_and_candidate_archive_excluded)
    test_pre03_m02_fitted_future_artifact_fail_closed = staticmethod(corpus.test_pre02_m02_fitted_future_artifact_fail_closed)
    test_pre03_m03_labels_published_during_search_do_not_enter_frozen_fit = staticmethod(corpus.test_pre02_m03_labels_published_during_search_do_not_enter_frozen_fit)
    test_pre03_m03_permitted_correction_changes_real_fit_positive_control = staticmethod(corpus.test_pre02_m03_permitted_correction_changes_real_fit_positive_control)
    test_pre03_m05_equal_availability_without_proven_publication_is_excluded = staticmethod(corpus.test_pre02_m05_equal_availability_without_proven_publication_is_excluded)
    test_pre03_m07_in_window_market_funding_invalidates_witness = staticmethod(corpus.test_pre02_m07_in_window_market_funding_invalidates_witness)
    test_pre03_matured_rust_reference_fit_rank_account = staticmethod(corpus.test_pre02_matured_rust_reference_fit_rank_account)
    test_pre03_matured_cached_uncached_witness_exact = staticmethod(corpus.test_pre02_matured_cached_uncached_witness_exact)
    test_pre03_matured_scalar_prepared_reference = staticmethod(corpus.test_pre02_matured_scalar_prepared_reference)

    def test_pre03_actual_selected_inner_diagnostics_are_not_anchor_copies(self, matured):
        import math
        for value in matured.values():
            wf = value.result.metadata["walk_forward"]
            sidecar = value.meta["records"][0]
            table = wf["fold_selection_table"]
            assert table.iloc[0]["selected_outer_is_raw_sharpe"] == sidecar["selected_outer_is_raw_sharpe"]
            assert table.iloc[0]["legacy_is_metric_scope"] == "native_inner_train_aggregate"
            assert table.iloc[0]["legacy_oos_metric_scope"] == "post_selection_outer_forward_penalized"
            inner = sidecar["native_inner_diagnostics"]
            assert all(r["fold_metrics"] and r["trial_id"] is not None for r in inner)
            if not sidecar["selected_inner_validation_evaluated"]:
                assert sidecar["selected_inner_validation_objective"] is None
                assert sidecar["selected_inner_validation_score"] is None
                assert math.isnan(wf["best_trial"]["mean_oos_sharpe"])
                assert math.isnan(wf["best_trial"]["mean_decay"])

    def test_pre03_current_pool_order_total_tie_rule(self, history_run, matured, monkeypatch):
        from quantbt.optimization.meta_selection.nested import NestedISPoolCapture
        capture = NestedISPoolCapture.capture

        def reordered(self, **kwargs):
            capture(self, **kwargs)
            self.pools[-1] = replace(self.pools[-1], candidates=tuple(reversed(self.pools[-1].candidates)))

        monkeypatch.setattr(NestedISPoolCapture, "capture", reordered)
        cutoff=CUTOFFS[0]
        b=run(history_run.route, "active", data=original.current(history_run.data, cutoff),
              start=str((cutoff+original.pd.Timedelta(days=1)).date()),
              history=original.clone_history(history_run.context.history))
        a=matured[cutoff]
        for field in ("selected_params", "selected_evaluation_id", "panel_members", "training_snapshot_id"):
            assert a.meta["records"][0][field] == b.meta["records"][0][field]
        assert a.meta["records"][0]["proposal"].predictions == b.meta["records"][0]["proposal"].predictions

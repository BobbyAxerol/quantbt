//! One current-bar checkpoint of mutable state, never a market/history clone.

use super::{
    DerivedAccountCacheV1, DerivedAccountVersionsV1, ExternalOrderAliases, FullSession,
    LifecycleIndexes, LiquidityLedgerV1, MarginCache, OrderArena, OrderState,
};

pub(super) struct BarTransaction {
    bar: usize,
    checkpoint: MutableBarCheckpoint,
}

struct MutableBarCheckpoint {
    positions: Vec<f64>,
    equity: f64,
    liquidated: bool,
    liquidation_bar: i64,
    liquidation_reason: i64,
    orders: OrderArena<OrderState>,
    order_aliases: ExternalOrderAliases,
    lifecycle_indexes: LifecycleIndexes,
    next_order_sequence: u64,
    liquidity_ledger: LiquidityLedgerV1,
    margin_cache: MarginCache,
    derived_account_cache: DerivedAccountCacheV1,
    derived_account_versions: DerivedAccountVersionsV1,
    derived_account_cache_hits: u64,
    derived_account_recomputes: u64,
    session_reset_count: u64,
    margin_recompute_count: u64,
    expiry_scan_count: u64,
    matching_scan_count: u64,
    relationship_scan_count: u64,
    last_bar: Option<usize>,
    compaction_count: u64,
    terminal_orders_removed: u64,
}

impl MutableBarCheckpoint {
    fn capture(session: &FullSession) -> Self {
        Self {
            positions: session.positions.clone(),
            equity: session.equity,
            liquidated: session.liquidated,
            liquidation_bar: session.liquidation_bar,
            liquidation_reason: session.liquidation_reason,
            orders: session.orders.clone(),
            order_aliases: session.order_aliases.clone(),
            lifecycle_indexes: session.lifecycle_indexes.clone(),
            next_order_sequence: session.next_order_sequence,
            liquidity_ledger: session.liquidity_ledger.clone(),
            margin_cache: session.margin_cache,
            derived_account_cache: session.derived_account_cache,
            derived_account_versions: session.derived_account_versions,
            derived_account_cache_hits: session.derived_account_cache_hits,
            derived_account_recomputes: session.derived_account_recomputes,
            session_reset_count: session.session_reset_count,
            margin_recompute_count: session.margin_recompute_count,
            expiry_scan_count: session.expiry_scan_count,
            matching_scan_count: session.matching_scan_count,
            relationship_scan_count: session.relationship_scan_count,
            last_bar: session.last_bar,
            compaction_count: session.compaction_count,
            terminal_orders_removed: session.terminal_orders_removed,
        }
    }

    fn restore(&self, session: &mut FullSession) {
        session.positions.clone_from(&self.positions);
        session.equity = self.equity;
        session.liquidated = self.liquidated;
        session.liquidation_bar = self.liquidation_bar;
        session.liquidation_reason = self.liquidation_reason;
        session.orders.clone_from(&self.orders);
        session.order_aliases.clone_from(&self.order_aliases);
        session
            .lifecycle_indexes
            .clone_from(&self.lifecycle_indexes);
        session.next_order_sequence = self.next_order_sequence;
        session.liquidity_ledger.clone_from(&self.liquidity_ledger);
        session.margin_cache = self.margin_cache;
        session.derived_account_cache = self.derived_account_cache;
        session.derived_account_versions = self.derived_account_versions;
        session.derived_account_cache_hits = self.derived_account_cache_hits;
        session.derived_account_recomputes = self.derived_account_recomputes;
        session.session_reset_count = self.session_reset_count;
        session.margin_recompute_count = self.margin_recompute_count;
        session.expiry_scan_count = self.expiry_scan_count;
        session.matching_scan_count = self.matching_scan_count;
        session.relationship_scan_count = self.relationship_scan_count;
        session.last_bar = self.last_bar;
        session.compaction_count = self.compaction_count;
        session.terminal_orders_removed = self.terminal_orders_removed;
        session.matching_candidates.clear();
        session.lifecycle_candidates.clear();
        session.bar_volumes.fill(0.0);
        session.step_buffers.clear();
    }
}

impl FullSession {
    /// Checkpoint only the next local bar. Static terminal capture is not
    /// rewindable and cannot coexist with an interactive transaction.
    pub fn begin_bar_transaction(&mut self, bar: usize) -> Result<(), String> {
        self.ensure_no_bar_transaction()?;
        if self.terminal_capture.is_some() {
            return Err("bar transaction cannot overlap static terminal capture".to_owned());
        }
        if bar >= self.n_bars() || bar != self.next_bar() {
            return Err("bar transaction must begin at the next canonical bar".to_owned());
        }
        self.bar_transaction = Some(Box::new(BarTransaction {
            bar,
            checkpoint: MutableBarCheckpoint::capture(self),
        }));
        Ok(())
    }

    /// Restore the same pre-bar state after a tentative step or failed step.
    /// The checkpoint stays open; neither prior bars nor market ownership move.
    pub fn retry_bar_transaction(&mut self) -> Result<(), String> {
        let transaction = self
            .bar_transaction
            .take()
            .ok_or_else(|| "no active bar transaction to retry".to_owned())?;
        transaction.checkpoint.restore(self);
        self.bar_transaction = Some(transaction);
        Ok(())
    }

    pub fn commit_bar_transaction(&mut self) -> Result<(), String> {
        let transaction = self
            .bar_transaction
            .as_ref()
            .ok_or_else(|| "no active bar transaction to commit".to_owned())?;
        if self.last_bar != Some(transaction.bar) {
            return Err("bar transaction must be stepped before commit".to_owned());
        }
        self.bar_transaction = None;
        Ok(())
    }

    pub fn abort_bar_transaction(&mut self) -> Result<(), String> {
        let transaction = self
            .bar_transaction
            .take()
            .ok_or_else(|| "no active bar transaction to abort".to_owned())?;
        transaction.checkpoint.restore(self);
        Ok(())
    }

    #[must_use]
    pub fn active_bar_transaction(&self) -> Option<usize> {
        self.bar_transaction
            .as_ref()
            .map(|transaction| transaction.bar)
    }

    pub(super) fn ensure_no_bar_transaction(&self) -> Result<(), String> {
        if self.bar_transaction.is_some() {
            return Err("a bar transaction is already active".to_owned());
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::execution_model::{CostModelV1, ExecutionModelPlanV1};
    use crate::session::{
        ACTION_AMEND, ACTION_CANCEL, ACTION_PLACE, ACTION_REPLACE, ACTIVATION_ON_PARENT_FIRST_FILL,
        CODE_WIDTH, EVENT_CANCEL, EVENT_EXPIRE, FullMarketData, FullStepResult, ORDER_LIMIT,
        ORDER_MARKET, ORDER_STOP_MARKET, OUTPUT_EVENTS, OUTPUT_FILLS, OUTPUT_POSITIONS, SIDE_BUY,
        SIDE_SELL, STATUS_PENDING, StaticTerminalCaptureV1, StepBuffers, TIF_GTC, TIF_GTD,
        VALUE_WIDTH,
    };
    use quantbt_domain::commands::CommandTapeV5;
    use std::sync::Arc;

    type Command = ([i64; CODE_WIDTH], [f64; VALUE_WIDTH], i64);
    type Outcome = (FullStepResult, StepBuffers);

    fn session() -> FullSession {
        let market = FullMarketData::new(
            vec![0, 1, 2, 3],
            vec![100.0; 4],
            vec![110.0; 4],
            vec![90.0; 4],
            vec![100.0; 4],
            vec![1.0; 4],
            vec![0.0, 0.0, 0.001, 0.0],
            vec![false, false, true, false],
            1,
        )
        .unwrap();
        let mut session = FullSession::new(
            Arc::new(market),
            vec![1.0],
            vec![5.0],
            vec![0.0002],
            10_000.0,
            0.005,
            0.0,
            true,
        )
        .unwrap();
        session
            .set_event_contract(crate::generated_contracts::CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();
        session
    }

    fn place(id: i64, side: i64, kind: i64, qty: f64, price: f64, trigger: f64) -> Command {
        let mut code = [0; CODE_WIDTH];
        code[0] = ACTION_PLACE;
        code[2] = side;
        code[3] = kind;
        code[4] = TIF_GTC;
        code[6] = id;
        code[7] = -1;
        code[8] = -1;
        code[9] = -1;
        code[10] = -1;
        (code, [qty, price, trigger], -1)
    }

    fn run(session: &mut FullSession, bar: usize, commands: &[Command]) -> Outcome {
        let codes = commands.iter().flat_map(|c| c.0).collect::<Vec<_>>();
        let values = commands.iter().flat_map(|c| c.1).collect::<Vec<_>>();
        let expiry = commands.iter().map(|c| c.2).collect::<Vec<_>>();
        let mut buffers = StepBuffers::default();
        let step = session
            .step_with_buffers(
                bar,
                &codes,
                &values,
                &expiry,
                commands.len(),
                OUTPUT_FILLS | OUTPUT_EVENTS | OUTPUT_POSITIONS,
                false,
                &mut buffers,
            )
            .unwrap();
        assert!(step.fills.is_empty() && step.events.is_empty() && step.active_orders.is_empty());
        (step, buffers)
    }

    fn assert_outcome(actual: &Outcome, expected: &Outcome) {
        let (a, ab) = actual;
        let (e, eb) = expected;
        assert_eq!(
            (
                a.equity,
                a.fee,
                a.turnover,
                a.funding,
                a.initial_margin,
                a.maintenance_margin
            ),
            (
                e.equity,
                e.fee,
                e.turnover,
                e.funding,
                e.initial_margin,
                e.maintenance_margin
            )
        );
        assert_eq!(a.positions, e.positions);
        assert_eq!(
            (a.liquidated, a.liquidation_bar, a.liquidation_reason),
            (e.liquidated, e.liquidation_bar, e.liquidation_reason)
        );
        assert_eq!(
            (
                a.fill_count,
                a.event_count,
                a.rejected_count,
                a.canceled_count,
                a.canceled_event_count,
                a.replace_count
            ),
            (
                e.fill_count,
                e.event_count,
                e.rejected_count,
                e.canceled_count,
                e.canceled_event_count,
                e.replace_count
            )
        );
        assert_eq!(ab.fills.order_id, eb.fills.order_id);
        assert_eq!(ab.fills.symbol, eb.fills.symbol);
        assert_eq!(ab.fills.side, eb.fills.side);
        assert_eq!(ab.fills.order_type, eb.fills.order_type);
        assert_eq!(ab.fills.qty, eb.fills.qty);
        assert_eq!(ab.fills.price, eb.fills.price);
        assert_eq!(ab.fills.fee, eb.fills.fee);
        assert_eq!(ab.fills.reason, eb.fills.reason);
        assert_eq!(ab.fills.ambiguity, eb.fills.ambiguity);
        assert_eq!(ab.events.kind, eb.events.kind);
        assert_eq!(ab.events.status, eb.events.status);
        assert_eq!(ab.events.order_id, eb.events.order_id);
        assert_eq!(ab.events.target_id, eb.events.target_id);
        assert_eq!(ab.events.symbol, eb.events.symbol);
        assert_eq!(ab.events.reject_code, eb.events.reject_code);
    }

    fn assert_state(actual: &FullSession, expected: &FullSession) {
        assert_eq!(actual.positions, expected.positions);
        assert_eq!(actual.equity, expected.equity);
        assert_eq!(actual.liquidated, expected.liquidated);
        assert_eq!(actual.last_bar, expected.last_bar);
        assert_eq!(actual.orders.stats(), expected.orders.stats());
        assert_eq!(
            actual.terminal_active_order_rows(),
            expected.terminal_active_order_rows()
        );
        assert_eq!(actual.order_aliases.len(), expected.order_aliases.len());
        assert_eq!(actual.next_order_sequence, expected.next_order_sequence);
        assert_eq!(actual.liquidity_ledger, expected.liquidity_ledger);
        assert_eq!(
            actual.derived_account_versions,
            expected.derived_account_versions
        );
        assert_eq!(
            actual.derived_account_cache.snapshot,
            expected.derived_account_cache.snapshot
        );
        assert_eq!(
            actual.derived_account_cache_hits,
            expected.derived_account_cache_hits
        );
        assert_eq!(
            actual.derived_account_recomputes,
            expected.derived_account_recomputes
        );
        assert_eq!(
            actual.margin_recompute_count,
            expected.margin_recompute_count
        );
        assert_eq!(
            actual.engine_scan_counters(),
            expected.engine_scan_counters()
        );
        assert_eq!(
            actual.terminal_orders_removed,
            expected.terminal_orders_removed
        );
        assert_eq!(actual.compaction_count, expected.compaction_count);
        actual.validate_lifecycle_indexes().unwrap();
        expected.validate_lifecycle_indexes().unwrap();
    }

    #[test]
    fn transaction_rejects_nested_stale_out_of_order_and_unstepped_commit() {
        let mut engine = session();
        assert!(engine.retry_bar_transaction().is_err());
        assert!(engine.commit_bar_transaction().is_err());
        assert!(engine.abort_bar_transaction().is_err());
        assert!(engine.begin_bar_transaction(1).is_err());
        assert!(engine.begin_bar_transaction(engine.n_bars()).is_err());
        engine.begin_bar_transaction(0).unwrap();
        assert!(engine.begin_bar_transaction(0).is_err());
        assert!(engine.commit_bar_transaction().is_err());
        assert!(engine.begin_fresh_at(0).is_err());
        assert!(
            engine
                .set_event_contract(engine.event_contract_code)
                .is_err()
        );
        assert!(engine.set_execution_model(engine.execution_model).is_err());
        assert!(engine.set_metric_contract(engine.metric_contract).is_err());
        assert!(engine.step(1, &[], &[], &[], 0).is_err());
        run(&mut engine, 0, &[]);
        assert!(engine.step(1, &[], &[], &[], 0).is_err());
        engine.commit_bar_transaction().unwrap();
        assert!(engine.begin_bar_transaction(0).is_err());
        assert!(engine.commit_bar_transaction().is_err());
        engine.begin_bar_transaction(1).unwrap();
        engine.abort_bar_transaction().unwrap();
        assert_eq!(engine.next_bar(), 1);
    }

    #[test]
    fn transaction_cannot_overlap_static_capture_or_static_execution() {
        let mut engine = session();
        let tape = CommandTapeV5::new(vec![0; engine.n_bars() + 1], vec![]).unwrap();
        engine.terminal_capture = Some(Box::new(StaticTerminalCaptureV1::new(&tape)));
        assert!(engine.begin_bar_transaction(0).is_err());
        engine.terminal_capture = None;
        engine.begin_bar_transaction(0).unwrap();
        assert!(engine.run_typed_audit_v1(&tape).is_err());
        assert!(engine.run_static_audit(&[0; 5], &[], &[], &[], 0).is_err());
        assert!(engine.terminal_capture.is_none());
        assert_eq!(engine.next_bar(), 0);
        engine.abort_bar_transaction().unwrap();
    }

    #[test]
    fn retry_restores_aliases_indexes_caches_funding_and_sequence_exactly() {
        let mut actual = session();
        let mut expected = session();
        let entry = place(1, SIDE_BUY, ORDER_MARKET, 2.0, 0.0, 0.0);
        let mut pending = place(2, SIDE_BUY, ORDER_LIMIT, 1.0, 50.0, 0.0);
        pending.0[4] = TIF_GTD;
        pending.2 = 3;
        for engine in [&mut actual, &mut expected] {
            run(engine, 0, &[]);
            run(engine, 1, &[entry, pending]);
        }
        let market = actual.market.clone();
        actual.begin_bar_transaction(2).unwrap();
        assert!(Arc::ptr_eq(&actual.market, &market));
        let mut replacement = place(3, SIDE_BUY, ORDER_LIMIT, 1.0, 50.0, 0.0);
        replacement.0[0] = ACTION_REPLACE;
        replacement.0[7] = 2;
        replacement.0[4] = TIF_GTD;
        replacement.2 = 3;
        let mut amend = place(-1, SIDE_BUY, ORDER_LIMIT, 3.0, 50.0, 0.0);
        amend.0[0] = ACTION_AMEND;
        amend.0[7] = 2;
        let mut cancel = amend;
        cancel.0[0] = ACTION_CANCEL;
        cancel.0[7] = 3;
        let mut reject = amend;
        reject.0[7] = 999;
        let tentative = run(&mut actual, 2, &[replacement, amend, cancel, reject]);
        assert!(tentative.0.rejected_count > 0);
        actual.post_execution_account_snapshot(2).unwrap();
        actual.retry_bar_transaction().unwrap();
        assert_state(&actual, &expected);
        let mut exit = place(4, SIDE_SELL, ORDER_MARKET, 1.0, 0.0, 0.0);
        exit.0[5] = 1;
        let chosen = run(&mut actual, 2, &[exit]);
        let clean = run(&mut expected, 2, &[exit]);
        assert!(chosen.0.funding > 0.0 && chosen.0.fee > 0.0);
        assert_outcome(&chosen, &clean);
        actual.commit_bar_transaction().unwrap();
        assert_state(&actual, &expected);
        let next = run(&mut actual, 3, &[]);
        let next_clean = run(&mut expected, 3, &[]);
        assert!(next.1.events.kind.contains(&EVENT_EXPIRE));
        assert_outcome(&next, &next_clean);
        assert_state(&actual, &expected);
        assert!(Arc::ptr_eq(&actual.market, &market));
    }

    #[test]
    fn repeated_partial_liquidity_retry_matches_one_clean_step() {
        let mut actual = session();
        let mut expected = session();
        let model =
            ExecutionModelPlanV1::Cost(CostModelV1::new(0.0, 0.0, 0.0, 0.0, Some(0.5)).unwrap());
        for engine in [&mut actual, &mut expected] {
            engine.set_execution_model(model).unwrap();
            run(engine, 0, &[]);
        }
        let commands = [
            place(1, SIDE_BUY, ORDER_MARKET, 2.0, 0.0, 0.0),
            place(2, SIDE_BUY, ORDER_MARKET, 2.0, 0.0, 0.0),
        ];
        actual.begin_bar_transaction(1).unwrap();
        for _ in 0..3 {
            let tentative = run(&mut actual, 1, &commands);
            assert_eq!(tentative.1.fills.qty, vec![0.5]);
            actual.retry_bar_transaction().unwrap();
            assert_state(&actual, &expected);
        }
        let chosen = run(&mut actual, 1, &commands);
        let clean = run(&mut expected, 1, &commands);
        assert_outcome(&chosen, &clean);
        actual.commit_bar_transaction().unwrap();
        assert_state(&actual, &expected);
    }

    #[test]
    fn same_bar_fill_relative_stop_and_oco_retry_matches_clean_execution() {
        let mut actual = session();
        let mut expected = session();
        for engine in [&mut actual, &mut expected] {
            run(engine, 0, &[]);
        }
        let entry = place(1, SIDE_BUY, ORDER_MARKET, 2.0, 0.0, 0.0);
        let mut stop = place(2, SIDE_SELL, ORDER_STOP_MARKET, 2.0, 0.0, 95.0);
        stop.0[5] = 1;
        stop.0[8] = 1;
        stop.0[10] = 7;
        stop.0[11] = ACTIVATION_ON_PARENT_FIRST_FILL;
        let mut target = place(3, SIDE_SELL, ORDER_LIMIT, 2.0, 105.0, 0.0);
        target.0[5] = 1;
        target.0[8] = 1;
        target.0[10] = 7;
        target.0[11] = ACTIVATION_ON_PARENT_FIRST_FILL;
        actual.begin_bar_transaction(1).unwrap();
        let tentative = run(&mut actual, 1, &[entry]);
        assert_eq!(tentative.0.positions, vec![2.0]);
        actual.retry_bar_transaction().unwrap();
        let chosen = run(&mut actual, 1, &[entry, stop, target]);
        let clean = run(&mut expected, 1, &[entry, stop, target]);
        assert_eq!(chosen.0.positions, vec![0.0]);
        assert_eq!(chosen.1.fills.order_id, vec![1, 2]);
        assert!(chosen.1.events.kind.contains(&EVENT_CANCEL));
        assert_outcome(&chosen, &clean);
        actual.commit_bar_transaction().unwrap();
        assert_state(&actual, &expected);
    }

    #[test]
    fn abort_liquidation_preserves_prior_inventory_and_reset_discards_checkpoint() {
        let mut engine = session();
        engine.initial_capital = 100.0;
        engine.equity = 100.0;
        engine.leverages[0] = 100.0;
        engine.fee_rates[0] = 0.0;
        run(&mut engine, 0, &[]);
        run(
            &mut engine,
            1,
            &[place(1, SIDE_BUY, ORDER_MARKET, 50.0, 0.0, 0.0)],
        );
        let held_equity = engine.equity;
        assert_eq!(engine.positions, vec![50.0]);
        engine.begin_bar_transaction(2).unwrap();
        assert!(run(&mut engine, 2, &[]).0.liquidated);
        engine.abort_bar_transaction().unwrap();
        assert!(!engine.liquidated);
        assert_eq!(engine.positions, vec![50.0]);
        assert_eq!(engine.equity, held_equity);
        assert_eq!(engine.next_bar(), 2);
        engine.begin_bar_transaction(2).unwrap();
        assert!(run(&mut engine, 2, &[]).0.liquidated);
        engine.reset();
        assert_eq!(engine.active_bar_transaction(), None);
        assert_eq!(engine.next_bar(), 0);
        assert_eq!(engine.positions, vec![0.0]);
        assert_eq!(engine.equity, engine.initial_capital);
        assert!(engine.retry_bar_transaction().is_err());
        engine.begin_bar_transaction(0).unwrap();
        engine.abort_bar_transaction().unwrap();
    }

    #[test]
    fn rollback_preserves_integer_ids_beyond_float_precision() {
        let mut engine = session();
        run(&mut engine, 0, &[]);
        let id = (1_i64 << 53) + 1;
        let entry = place(id, SIDE_BUY, ORDER_MARKET, 1.0, 0.0, 0.0);
        engine.begin_bar_transaction(1).unwrap();
        let tentative = run(&mut engine, 1, &[entry]);
        assert_eq!(tentative.1.fills.order_id, vec![id]);
        engine.retry_bar_transaction().unwrap();
        let chosen = run(&mut engine, 1, &[entry]);
        assert_eq!(chosen.1.fills.order_id, vec![id]);
        assert_eq!(chosen.1.fills.order_type, vec![ORDER_MARKET]);
        assert!(!chosen.1.fills.reason.is_empty());
        assert_eq!(chosen.1.events.order_id[0], id);
        assert_outcome(&chosen, &tentative);
        engine.commit_bar_transaction().unwrap();
        assert!(
            engine
                .orders
                .iter()
                .all(|(_, order)| order.status == STATUS_PENDING)
        );
    }
}

//! Specialized bounded OHLC intrabar execution authority.
//!
//! This module deliberately does not route brackets through [`FullSession`].
//! The public contract has a fixed next-open decision clock and a branch-heavy
//! deterministic OHLC path policy; keeping that state machine here makes the
//! ordering auditable without inventing a second generic order lifecycle.

use std::sync::Arc;

use quantbt_engine::{
    ExecutionModelPlanV1, FullMarketData, MetricContractV2, MetricFinishInputV2,
    NativeMetricSnapshotV2, OnlineMetricReducerV2,
};

pub const INTRABAR_LEVEL_ABSOLUTE_PRICE: u8 = 1;
pub const INTRABAR_LEVEL_PRICE_DISTANCE: u8 = 2;
pub const INTRABAR_LEVEL_PERCENT_DISTANCE: u8 = 3;

pub const INTRABAR_SAME_BAR_CONSERVATIVE: u8 = 1;
pub const INTRABAR_SAME_BAR_STOP_FIRST: u8 = 2;
pub const INTRABAR_SAME_BAR_TP_FIRST: u8 = 3;
pub const INTRABAR_SAME_BAR_OHLC_PATH: u8 = 4;
pub const INTRABAR_SAME_BAR_OLHC_PATH: u8 = 5;
pub const INTRABAR_SAME_BAR_REJECT_AMBIGUOUS: u8 = 6;

pub const INTRABAR_TP_LIMIT_CONSERVATIVE: u8 = 1;
pub const INTRABAR_TP_OPEN_PRICE_IMPROVEMENT: u8 = 2;

pub const INTRABAR_FILL_ENTRY: i16 = 1;
pub const INTRABAR_FILL_TECHNICAL_EXIT: i16 = 2;
pub const INTRABAR_FILL_REVERSAL_EXIT: i16 = 3;
pub const INTRABAR_FILL_REVERSAL_ENTRY: i16 = 4;
pub const INTRABAR_FILL_STOP_LOSS: i16 = 5;
pub const INTRABAR_FILL_TAKE_PROFIT: i16 = 6;
pub const INTRABAR_FILL_LIQUIDATION: i16 = 7;
pub const INTRABAR_FILL_FINAL_CLOSE: i16 = 8;
pub const INTRABAR_FILL_SESSION_FORCED_EXIT: i16 = 9;

pub const INTRABAR_FLAG_ENTRY_FILLED: u32 = 1 << 0;
pub const INTRABAR_FLAG_EXIT_FILLED: u32 = 1 << 1;
pub const INTRABAR_FLAG_STOP_FILLED: u32 = 1 << 2;
pub const INTRABAR_FLAG_TP_FILLED: u32 = 1 << 3;
pub const INTRABAR_FLAG_TECH_EXIT: u32 = 1 << 4;
pub const INTRABAR_FLAG_REVERSAL: u32 = 1 << 5;
pub const INTRABAR_FLAG_AMBIGUOUS: u32 = 1 << 6;
pub const INTRABAR_FLAG_FUNDING: u32 = 1 << 7;
pub const INTRABAR_FLAG_LIQUIDATION: u32 = 1 << 8;
pub const INTRABAR_FLAG_REJECTED: u32 = 1 << 9;
pub const INTRABAR_FLAG_ENTRY_SUPPRESSED: u32 = 1 << 10;
pub const INTRABAR_FLAG_SESSION_RESET: u32 = 1 << 11;
pub const INTRABAR_FLAG_SESSION_FORCED_EXIT: u32 = 1 << 12;
pub const INTRABAR_FLAG_ENTRY_WINDOW_BLOCKED: u32 = 1 << 13;
pub const INTRABAR_FLAG_ENTRY_QUOTA_BLOCKED: u32 = 1 << 14;
pub const INTRABAR_FLAG_FLAT_ONLY_BLOCKED: u32 = 1 << 15;
pub const INTRABAR_FLAG_STALE_SESSION_SIGNAL: u32 = 1 << 16;
pub const INTRABAR_FLAG_PROTECTIVE_REENTRY_BLOCKED: u32 = 1 << 17;

pub const INTRABAR_SIZING_UNITS: u8 = 1;
pub const INTRABAR_SIZING_FIXED_NOTIONAL: u8 = 2;
pub const INTRABAR_SIZING_PCT_EQUITY: u8 = 3;
pub const INTRABAR_SIZING_RISK_PER_TRADE: u8 = 4;

pub const INTRABAR_BAR_TIMESTAMP_CLOSE: u8 = 1;
pub const INTRABAR_BAR_TIMESTAMP_OPEN: u8 = 2;

pub const INTRABAR_SESSION_ENTRY_CURRENT: u8 = 1;
pub const INTRABAR_SESSION_ENTRY_FLAT_ONLY: u8 = 2;
pub const INTRABAR_SESSION_ENTRY_REVERSE: u8 = 3;
pub const INTRABAR_SESSION_COUNTER_FILLED: u8 = 1;
pub const INTRABAR_SESSION_COUNTER_ACCEPTED: u8 = 2;
pub const INTRABAR_SESSION_REENTRY_ALLOW: u8 = 1;
pub const INTRABAR_SESSION_REENTRY_SUPPRESS_SIGNAL_BAR: u8 = 2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[repr(u8)]
pub enum IntrabarOutputProfileV1 {
    Score = 0,
    Compact = 1,
    Audit = 2,
}

impl TryFrom<u8> for IntrabarOutputProfileV1 {
    type Error = String;

    fn try_from(value: u8) -> Result<Self, Self::Error> {
        match value {
            0 => Ok(Self::Score),
            1 => Ok(Self::Compact),
            2 => Ok(Self::Audit),
            _ => Err("unsupported intrabar output profile".to_owned()),
        }
    }
}

impl IntrabarOutputProfileV1 {
    #[must_use]
    pub const fn name(self) -> &'static str {
        match self {
            Self::Score => "score",
            Self::Compact => "compact",
            Self::Audit => "audit",
        }
    }
}

#[derive(Clone, Debug)]
pub struct IntrabarIntentV1 {
    pub entry_side: Box<[i8]>,
    pub entry_size: Box<[f64]>,
    pub stop_value: Box<[f64]>,
    pub take_profit_value: Box<[f64]>,
    pub trailing_value: Box<[f64]>,
    pub exit_long: Box<[bool]>,
    pub exit_short: Box<[bool]>,
    pub level_mode: u8,
}

impl IntrabarIntentV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        entry_side: Vec<i8>,
        entry_size: Vec<f64>,
        stop_value: Vec<f64>,
        take_profit_value: Vec<f64>,
        trailing_value: Vec<f64>,
        exit_long: Vec<bool>,
        exit_short: Vec<bool>,
        level_mode: u8,
    ) -> Result<Self, String> {
        let n = entry_side.len();
        if n == 0
            || entry_size.len() != n
            || stop_value.len() != n
            || take_profit_value.len() != n
            || trailing_value.len() != n
            || exit_long.len() != n
            || exit_short.len() != n
            || !matches!(
                level_mode,
                INTRABAR_LEVEL_ABSOLUTE_PRICE
                    | INTRABAR_LEVEL_PRICE_DISTANCE
                    | INTRABAR_LEVEL_PERCENT_DISTANCE
            )
            || entry_side.iter().any(|value| !matches!(*value, -1..=1))
            || entry_size.iter().any(|value| !value.is_finite())
            || stop_value
                .iter()
                .chain(take_profit_value.iter())
                .chain(trailing_value.iter())
                .any(|value| !value.is_finite() && !value.is_nan())
        {
            return Err("intrabar intent has an invalid shape or value".to_owned());
        }
        Ok(Self {
            entry_side: entry_side.into_boxed_slice(),
            entry_size: entry_size.into_boxed_slice(),
            stop_value: stop_value.into_boxed_slice(),
            take_profit_value: take_profit_value.into_boxed_slice(),
            trailing_value: trailing_value.into_boxed_slice(),
            exit_long: exit_long.into_boxed_slice(),
            exit_short: exit_short.into_boxed_slice(),
            level_mode,
        })
    }
}

#[derive(Clone, Copy, Debug)]
pub struct IntrabarAccountConfigV1 {
    pub initial_capital: f64,
    pub leverage: f64,
    pub maintenance_ratio: f64,
    pub margin_buffer: f64,
    pub contract_size: f64,
    pub fee_rate: f64,
    pub slippage_rate: f64,
    pub sizing_mode: u8,
    pub fixed_notional: f64,
    pub equity_fraction: f64,
    pub risk_fraction: f64,
    pub qty_step: f64,
    pub min_qty: f64,
    pub min_notional: f64,
    pub tick_size: f64,
}

impl IntrabarAccountConfigV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        initial_capital: f64,
        leverage: f64,
        maintenance_ratio: f64,
        margin_buffer: f64,
        contract_size: f64,
        fee_rate: f64,
        slippage_rate: f64,
        sizing_mode: u8,
        fixed_notional: f64,
        equity_fraction: f64,
        risk_fraction: f64,
        qty_step: f64,
        min_qty: f64,
        min_notional: f64,
        tick_size: f64,
    ) -> Result<Self, String> {
        if !initial_capital.is_finite()
            || initial_capital <= 0.0
            || !leverage.is_finite()
            || leverage <= 0.0
            || [
                maintenance_ratio,
                margin_buffer,
                fee_rate,
                slippage_rate,
                qty_step,
                min_qty,
                min_notional,
                tick_size,
            ]
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
            || !contract_size.is_finite()
            || contract_size <= 0.0
            || !fixed_notional.is_finite()
            || !equity_fraction.is_finite()
            || !risk_fraction.is_finite()
            || !matches!(
                sizing_mode,
                INTRABAR_SIZING_UNITS
                    | INTRABAR_SIZING_FIXED_NOTIONAL
                    | INTRABAR_SIZING_PCT_EQUITY
                    | INTRABAR_SIZING_RISK_PER_TRADE
            )
        {
            return Err("intrabar account/execution config is invalid".to_owned());
        }
        Ok(Self {
            initial_capital,
            leverage,
            maintenance_ratio,
            margin_buffer,
            contract_size,
            fee_rate,
            slippage_rate,
            sizing_mode,
            fixed_notional,
            equity_fraction,
            risk_fraction,
            qty_step,
            min_qty,
            min_notional,
            tick_size,
        })
    }
}

#[derive(Clone, Copy, Debug)]
pub struct IntrabarContractConfigV1 {
    pub bar_timestamp_semantics: u8,
    pub same_bar_policy: u8,
    pub take_profit_gap_policy: u8,
    pub close_on_last_bar: bool,
}

impl IntrabarContractConfigV1 {
    pub fn new(
        bar_timestamp_semantics: u8,
        same_bar_policy: u8,
        take_profit_gap_policy: u8,
        close_on_last_bar: bool,
    ) -> Result<Self, String> {
        if !matches!(
            bar_timestamp_semantics,
            INTRABAR_BAR_TIMESTAMP_CLOSE | INTRABAR_BAR_TIMESTAMP_OPEN
        ) {
            return Err("intrabar bar_timestamp_semantics must be close or open".to_owned());
        }
        if same_bar_policy == INTRABAR_SAME_BAR_REJECT_AMBIGUOUS {
            return Err(
                "intrabar Rust route rejects same_bar_policy=reject_ambiguous; use the Python oracle for diagnostic rejection"
                    .to_owned(),
            );
        }
        if !matches!(
            same_bar_policy,
            INTRABAR_SAME_BAR_CONSERVATIVE
                | INTRABAR_SAME_BAR_STOP_FIRST
                | INTRABAR_SAME_BAR_TP_FIRST
                | INTRABAR_SAME_BAR_OHLC_PATH
                | INTRABAR_SAME_BAR_OLHC_PATH
        ) || !matches!(
            take_profit_gap_policy,
            INTRABAR_TP_LIMIT_CONSERVATIVE | INTRABAR_TP_OPEN_PRICE_IMPROVEMENT
        ) {
            return Err("intrabar same-bar or take-profit gap policy is unsupported".to_owned());
        }
        Ok(Self {
            bar_timestamp_semantics,
            same_bar_policy,
            take_profit_gap_policy,
            close_on_last_bar,
        })
    }
}

#[derive(Clone, Debug)]
pub struct IntrabarSessionConfigV1 {
    pub session_id: Box<[i64]>,
    pub entry_allowed_at_open: Box<[bool]>,
    pub force_flat_at_open: Box<[bool]>,
    pub entry_position_policy: u8,
    pub counter_basis: u8,
    pub protective_reentry_policy: u8,
    pub max_long_entries_per_session: i64,
    pub max_short_entries_per_session: i64,
    pub cancel_pending_on_session_change: bool,
    pub suppress_entry_on_force_flat_bar: bool,
}

impl IntrabarSessionConfigV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        session_id: Vec<i64>,
        entry_allowed_at_open: Vec<bool>,
        force_flat_at_open: Vec<bool>,
        entry_position_policy: u8,
        counter_basis: u8,
        protective_reentry_policy: u8,
        max_long_entries_per_session: i64,
        max_short_entries_per_session: i64,
        cancel_pending_on_session_change: bool,
        suppress_entry_on_force_flat_bar: bool,
    ) -> Result<Self, String> {
        let n = session_id.len();
        if n == 0
            || entry_allowed_at_open.len() != n
            || force_flat_at_open.len() != n
            || !matches!(
                entry_position_policy,
                INTRABAR_SESSION_ENTRY_CURRENT
                    | INTRABAR_SESSION_ENTRY_FLAT_ONLY
                    | INTRABAR_SESSION_ENTRY_REVERSE
            )
            || !matches!(
                counter_basis,
                INTRABAR_SESSION_COUNTER_FILLED | INTRABAR_SESSION_COUNTER_ACCEPTED
            )
            || !matches!(
                protective_reentry_policy,
                INTRABAR_SESSION_REENTRY_ALLOW | INTRABAR_SESSION_REENTRY_SUPPRESS_SIGNAL_BAR
            )
            || max_long_entries_per_session < -1
            || max_short_entries_per_session < -1
        {
            return Err("intrabar session config is invalid".to_owned());
        }
        Ok(Self {
            session_id: session_id.into_boxed_slice(),
            entry_allowed_at_open: entry_allowed_at_open.into_boxed_slice(),
            force_flat_at_open: force_flat_at_open.into_boxed_slice(),
            entry_position_policy,
            counter_basis,
            protective_reentry_policy,
            max_long_entries_per_session,
            max_short_entries_per_session,
            cancel_pending_on_session_change,
            suppress_entry_on_force_flat_bar,
        })
    }
}

#[derive(Clone)]
pub struct IntrabarRequestV1 {
    market: Arc<FullMarketData>,
    intent: IntrabarIntentV1,
    account: IntrabarAccountConfigV1,
    contract: IntrabarContractConfigV1,
    session: Option<IntrabarSessionConfigV1>,
    output: IntrabarOutputProfileV1,
    audit_detail_limit: usize,
    execution_model: ExecutionModelPlanV1,
    fingerprint: [u8; 32],
}

impl IntrabarRequestV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        market: Arc<FullMarketData>,
        intent: IntrabarIntentV1,
        account: IntrabarAccountConfigV1,
        contract: IntrabarContractConfigV1,
        session: Option<IntrabarSessionConfigV1>,
        output: IntrabarOutputProfileV1,
        audit_detail_limit: usize,
    ) -> Result<Self, String> {
        if market.n_symbols != 1 || market.n_bars == 0 || intent.entry_side.len() != market.n_bars {
            return Err(
                "intrabar Rust route requires one prepared symbol and matching intent bars"
                    .to_owned(),
            );
        }
        if session
            .as_ref()
            .is_some_and(|value| value.session_id.len() != market.n_bars)
        {
            return Err("intrabar session tape must match prepared market bars".to_owned());
        }
        let execution_model = ExecutionModelPlanV1::legacy(account.slippage_rate)
            .map_err(|error| format!("intrabar execution model is invalid: {error}"))?;
        let fingerprint = intrabar_fingerprint(
            &market,
            &intent,
            account,
            contract,
            session.as_ref(),
            output,
            audit_detail_limit,
        );
        Ok(Self {
            market,
            intent,
            account,
            contract,
            session,
            output,
            audit_detail_limit,
            execution_model,
            fingerprint,
        })
    }

    #[must_use]
    pub fn fingerprint_hex(&self) -> String {
        self.fingerprint
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect()
    }

    #[must_use]
    pub const fn output_profile(&self) -> IntrabarOutputProfileV1 {
        self.output
    }

    #[must_use]
    pub const fn audit_detail_limit(&self) -> usize {
        self.audit_detail_limit
    }

    #[must_use]
    pub fn source_market_bytes(&self) -> usize {
        self.market.timestamps_ns.len() * std::mem::size_of::<i64>()
            + self.market.opens.len() * std::mem::size_of::<f64>()
            + self.market.highs.len() * std::mem::size_of::<f64>()
            + self.market.lows.len() * std::mem::size_of::<f64>()
            + self.market.closes.len() * std::mem::size_of::<f64>()
            + self.market.volumes.len() * std::mem::size_of::<f64>()
            + self.market.funding.len() * std::mem::size_of::<f64>()
            + self.market.funding_mask.len() * std::mem::size_of::<bool>()
    }

    #[must_use]
    pub fn bar_count(&self) -> usize {
        self.market.n_bars
    }

    #[must_use]
    pub const fn session_enabled(&self) -> bool {
        self.session.is_some()
    }

    pub fn execute(&self) -> IntrabarExecutionResultV1 {
        let n = self.market.n_bars;
        let mut result = IntrabarExecutionResultV1::new(self.output, n, self.audit_detail_limit);
        let mut state = IntrabarStateV1::new(self.account.initial_capital);
        let mut metric_reducer =
            OnlineMetricReducerV2::new(result.metric_contract, self.account.initial_capital)
                .expect("static intrabar metric contract and account are valid");
        let mut session_state = self.session.as_ref().map(|session| IntrabarSessionStateV1 {
            current_session_id: session.session_id[0],
            ..IntrabarSessionStateV1::default()
        });

        result.snapshot(
            self.output,
            state.equity,
            state.position,
            state.average_entry,
            state.active_stop,
            state.active_take_profit,
            0.0,
            0.0,
            0,
            0.0,
            0.0,
        );

        for t in 1..n {
            // The state entering bar `t` is the finalized close state of
            // bar `t - 1`. Delaying observation by one bar lets the final
            // close/flatten amend the last sample before it is observed.
            self.observe_metric(&mut metric_reducer, t - 1, state.equity, state.position)
                .expect("intrabar accounting must yield valid metric observations");
            if state.liquidated {
                result.snapshot(
                    self.output,
                    0.0,
                    0.0,
                    0.0,
                    f64::NAN,
                    f64::NAN,
                    0.0,
                    0.0,
                    0,
                    0.0,
                    0.0,
                );
                continue;
            }

            let open_ref = self.open(t);
            let close_ref = self.close(t);
            let mut last_ref = open_ref;
            let mut flags = 0_u32;
            let mut bar_fee = 0.0;
            let mut bar_funding = 0.0;
            let mut sequence = 0_i64;

            if state.position != 0.0 {
                state.equity +=
                    state.position * (open_ref - self.close(t - 1)) * self.account.contract_size;
            }

            let mut reentry_block_from_previous_bar = false;
            if let (Some(session), Some(session_state)) =
                (self.session.as_ref(), session_state.as_mut())
            {
                if session.session_id[t] != session_state.current_session_id {
                    session_state.current_session_id = session.session_id[t];
                    session_state.long_entry_count = 0;
                    session_state.short_entry_count = 0;
                    session_state.protective_exit_on_previous_bar = false;
                    flags |= INTRABAR_FLAG_SESSION_RESET;
                    session_state.session_reset_count += 1;
                }
                reentry_block_from_previous_bar = session_state.protective_exit_on_previous_bar;
                session_state.protective_exit_on_previous_bar = false;
            }

            if state.position != 0.0
                && self.maintenance_breached(state.equity, state.position, open_ref)
            {
                let side = exit_side(state.position);
                let price = self.market_price(open_ref, side);
                let qty = state.position.abs();
                let fee = self.fee(qty, price);
                state.equity +=
                    state.position * (price - open_ref) * self.account.contract_size - fee;
                bar_fee += fee;
                result.total_fee += fee;
                result.record_fill(
                    IntrabarFillV1::new(
                        t,
                        sequence,
                        side,
                        qty,
                        price,
                        fee,
                        INTRABAR_FILL_LIQUIDATION,
                        false,
                        self.contract.same_bar_policy,
                    ),
                    self.account.contract_size,
                );
                result.fill_count += 1;
                flags |= INTRABAR_FLAG_EXIT_FILLED | INTRABAR_FLAG_LIQUIDATION;
                state.liquidated = true;
                state.liquidation_bar = t as i64;
                state.equity = 0.0;
                state.clear_position();
                result.snapshot(
                    self.output,
                    0.0,
                    0.0,
                    0.0,
                    f64::NAN,
                    f64::NAN,
                    bar_fee,
                    0.0,
                    flags,
                    0.0,
                    0.0,
                );
                continue;
            }

            if self.contract.bar_timestamp_semantics == INTRABAR_BAR_TIMESTAMP_OPEN
                && state.position != 0.0
                && self.market.funding_mask[t]
            {
                let cost =
                    state.position * open_ref * self.account.contract_size * self.market.funding[t];
                state.equity -= cost;
                bar_funding += cost;
                result.total_funding += cost;
                flags |= INTRABAR_FLAG_FUNDING;
            }

            let mut pending_side = self.intent.entry_side[t - 1];
            let mut pending_size = self.intent.entry_size[t - 1];
            let pending_exit = (state.position > 0.0 && self.intent.exit_long[t - 1])
                || (state.position < 0.0 && self.intent.exit_short[t - 1]);
            let mut force_flat_bar = false;

            if let (Some(session), Some(session_state)) =
                (self.session.as_ref(), session_state.as_mut())
            {
                force_flat_bar = session.force_flat_at_open[t];
                if force_flat_bar && state.position != 0.0 {
                    let side = exit_side(state.position);
                    let price = self.market_price(open_ref, side);
                    let qty = state.position.abs();
                    let fee = self.fee(qty, price);
                    state.equity +=
                        state.position * (price - open_ref) * self.account.contract_size - fee;
                    bar_fee += fee;
                    result.total_fee += fee;
                    result.record_fill(
                        IntrabarFillV1::new(
                            t,
                            sequence,
                            side,
                            qty,
                            price,
                            fee,
                            INTRABAR_FILL_SESSION_FORCED_EXIT,
                            false,
                            self.contract.same_bar_policy,
                        ),
                        self.account.contract_size,
                    );
                    result.fill_count += 1;
                    sequence += 1;
                    flags |= INTRABAR_FLAG_EXIT_FILLED | INTRABAR_FLAG_SESSION_FORCED_EXIT;
                    session_state.session_forced_exit_count += 1;
                    state.clear_position();
                }
                if session.cancel_pending_on_session_change
                    && pending_side != 0
                    && session.session_id[t - 1] != session.session_id[t]
                {
                    pending_side = 0;
                    pending_size = 0.0;
                    flags |= INTRABAR_FLAG_STALE_SESSION_SIGNAL | INTRABAR_FLAG_ENTRY_SUPPRESSED;
                    session_state.stale_session_signal_count += 1;
                }
                if pending_side != 0
                    && state.position != 0.0
                    && session.entry_position_policy == INTRABAR_SESSION_ENTRY_FLAT_ONLY
                {
                    pending_side = 0;
                    pending_size = 0.0;
                    flags |= INTRABAR_FLAG_FLAT_ONLY_BLOCKED | INTRABAR_FLAG_ENTRY_SUPPRESSED;
                    session_state.flat_only_blocked_count += 1;
                }
            }

            let exit_same_side_conflict = pending_exit
                && pending_side != 0
                && state.position != 0.0
                && sign(state.position) == pending_side;
            let reversal_allowed = self.session.as_ref().is_none_or(|session| {
                session.entry_position_policy != INTRABAR_SESSION_ENTRY_FLAT_ONLY
            });

            if state.position != 0.0
                && (pending_exit
                    || (reversal_allowed
                        && pending_side != 0
                        && sign(state.position) != pending_side))
            {
                let reason = if pending_side != 0 && sign(state.position) != pending_side {
                    INTRABAR_FILL_REVERSAL_EXIT
                } else {
                    INTRABAR_FILL_TECHNICAL_EXIT
                };
                let side = exit_side(state.position);
                let price = self.market_price(open_ref, side);
                let qty = state.position.abs();
                let fee = self.fee(qty, price);
                state.equity +=
                    state.position * (price - open_ref) * self.account.contract_size - fee;
                bar_fee += fee;
                result.total_fee += fee;
                result.record_fill(
                    IntrabarFillV1::new(
                        t,
                        sequence,
                        side,
                        qty,
                        price,
                        fee,
                        reason,
                        false,
                        self.contract.same_bar_policy,
                    ),
                    self.account.contract_size,
                );
                result.fill_count += 1;
                sequence += 1;
                flags |= INTRABAR_FLAG_EXIT_FILLED;
                flags |= if reason == INTRABAR_FILL_TECHNICAL_EXIT {
                    INTRABAR_FLAG_TECH_EXIT
                } else {
                    INTRABAR_FLAG_REVERSAL
                };
                state.clear_position();
            }

            if pending_side != 0 && pending_size > 0.0 && state.position == 0.0 {
                let side = if pending_side > 0 { 1 } else { -1 };
                let price = self.market_price(open_ref, side);
                let mut entry_blocked = false;
                if let (Some(session), Some(session_state)) =
                    (self.session.as_ref(), session_state.as_mut())
                {
                    if force_flat_bar && session.suppress_entry_on_force_flat_bar {
                        entry_blocked = true;
                        flags |= INTRABAR_FLAG_SESSION_FORCED_EXIT | INTRABAR_FLAG_ENTRY_SUPPRESSED;
                    } else if !session.entry_allowed_at_open[t] {
                        entry_blocked = true;
                        session_state.entry_window_blocked_count += 1;
                        flags |=
                            INTRABAR_FLAG_ENTRY_WINDOW_BLOCKED | INTRABAR_FLAG_ENTRY_SUPPRESSED;
                    } else if session.protective_reentry_policy
                        == INTRABAR_SESSION_REENTRY_SUPPRESS_SIGNAL_BAR
                        && reentry_block_from_previous_bar
                    {
                        entry_blocked = true;
                        session_state.reentry_suppressed_count += 1;
                        flags |= INTRABAR_FLAG_PROTECTIVE_REENTRY_BLOCKED
                            | INTRABAR_FLAG_ENTRY_SUPPRESSED;
                    } else if side > 0
                        && session.max_long_entries_per_session >= 0
                        && session_state.long_entry_count >= session.max_long_entries_per_session
                    {
                        entry_blocked = true;
                        session_state.long_quota_blocked_count += 1;
                        flags |= INTRABAR_FLAG_ENTRY_QUOTA_BLOCKED | INTRABAR_FLAG_ENTRY_SUPPRESSED;
                    } else if side < 0
                        && session.max_short_entries_per_session >= 0
                        && session_state.short_entry_count >= session.max_short_entries_per_session
                    {
                        entry_blocked = true;
                        session_state.short_quota_blocked_count += 1;
                        flags |= INTRABAR_FLAG_ENTRY_QUOTA_BLOCKED | INTRABAR_FLAG_ENTRY_SUPPRESSED;
                    }
                }
                if exit_same_side_conflict || entry_blocked {
                    flags |= INTRABAR_FLAG_ENTRY_SUPPRESSED;
                    let (initial_margin, maintenance_margin) = if self.session.is_some() {
                        self.margin_at(state.position, close_ref)
                    } else {
                        (0.0, 0.0)
                    };
                    result.snapshot(
                        self.output,
                        state.equity,
                        state.position,
                        state.average_entry,
                        state.active_stop,
                        state.active_take_profit,
                        bar_fee,
                        bar_funding,
                        flags,
                        initial_margin,
                        maintenance_margin,
                    );
                    continue;
                }
                let mut qty = self.compile_entry_quantity(
                    pending_size,
                    price,
                    state.equity,
                    self.intent.stop_value[t - 1],
                    side,
                );
                qty = self.quantize_quantity(qty, price).abs();
                if qty <= 0.0 || !self.has_initial_margin(state.equity, qty, price) {
                    flags |= INTRABAR_FLAG_REJECTED;
                    result.rejected_count += 1;
                    result.snapshot(
                        self.output,
                        state.equity,
                        state.position,
                        state.average_entry,
                        state.active_stop,
                        state.active_take_profit,
                        bar_fee,
                        bar_funding,
                        flags,
                        0.0,
                        0.0,
                    );
                    continue;
                }
                let fee = self.fee(qty, price);
                state.equity -= fee;
                bar_fee += fee;
                result.total_fee += fee;
                state.position = qty * f64::from(side);
                state.average_entry = price;
                last_ref = price;
                (state.active_stop, state.active_take_profit) =
                    self.initial_bracket(t - 1, side, price);
                let reason = if flags & INTRABAR_FLAG_REVERSAL != 0 {
                    INTRABAR_FILL_REVERSAL_ENTRY
                } else {
                    INTRABAR_FILL_ENTRY
                };
                result.record_fill(
                    IntrabarFillV1::new(
                        t,
                        sequence,
                        side,
                        qty,
                        price,
                        fee,
                        reason,
                        false,
                        self.contract.same_bar_policy,
                    ),
                    self.account.contract_size,
                );
                result.fill_count += 1;
                sequence += 1;
                flags |= INTRABAR_FLAG_ENTRY_FILLED;
                if let Some(session_state) = session_state.as_mut() {
                    if side > 0 {
                        session_state.long_entry_count += 1;
                    } else {
                        session_state.short_entry_count += 1;
                    }
                }
            }

            if state.position != 0.0
                && let Some(exit) = self.resolve_intrabar_exit(
                    sign(state.position),
                    open_ref,
                    self.high(t),
                    self.low(t),
                    state.active_stop,
                    state.active_take_profit,
                )
            {
                if exit.ambiguous {
                    flags |= INTRABAR_FLAG_AMBIGUOUS;
                    result.ambiguity_count += 1;
                    result.record_ambiguity(t as i64, self.contract.same_bar_policy);
                }
                let qty = state.position.abs();
                let fee = self.fee(qty, exit.price);
                state.equity +=
                    state.position * (exit.price - last_ref) * self.account.contract_size - fee;
                bar_fee += fee;
                result.total_fee += fee;
                result.record_fill(
                    IntrabarFillV1::new(
                        t,
                        sequence,
                        exit.side,
                        qty,
                        exit.price,
                        fee,
                        exit.reason,
                        exit.ambiguous,
                        self.contract.same_bar_policy,
                    ),
                    self.account.contract_size,
                );
                result.fill_count += 1;
                sequence += 1;
                flags |= INTRABAR_FLAG_EXIT_FILLED;
                if exit.reason == INTRABAR_FILL_STOP_LOSS {
                    flags |= INTRABAR_FLAG_STOP_FILLED;
                } else {
                    flags |= INTRABAR_FLAG_TP_FILLED;
                }
                if let Some(session_state) = session_state.as_mut() {
                    session_state.protective_exit_on_previous_bar = true;
                }
                state.clear_position();
            }

            if state.position != 0.0 {
                if self.maintenance_breached_worst(
                    state.equity,
                    state.position,
                    last_ref,
                    self.high(t),
                    self.low(t),
                ) {
                    let side = exit_side(state.position);
                    let worst = if state.position > 0.0 {
                        self.low(t)
                    } else {
                        self.high(t)
                    };
                    let price = self.market_price(worst, side);
                    let qty = state.position.abs();
                    let fee = self.fee(qty, price);
                    state.equity +=
                        state.position * (price - last_ref) * self.account.contract_size - fee;
                    bar_fee += fee;
                    result.total_fee += fee;
                    result.record_fill(
                        IntrabarFillV1::new(
                            t,
                            sequence,
                            side,
                            qty,
                            price,
                            fee,
                            INTRABAR_FILL_LIQUIDATION,
                            false,
                            self.contract.same_bar_policy,
                        ),
                        self.account.contract_size,
                    );
                    result.fill_count += 1;
                    flags |= INTRABAR_FLAG_EXIT_FILLED | INTRABAR_FLAG_LIQUIDATION;
                    state.liquidated = true;
                    state.liquidation_bar = t as i64;
                    state.equity = 0.0;
                    state.clear_position();
                } else {
                    state.equity +=
                        state.position * (close_ref - last_ref) * self.account.contract_size;
                    state.active_stop =
                        self.update_trailing(t, state.position, close_ref, state.active_stop);
                }
            }

            if state.liquidated {
                result.snapshot(
                    self.output,
                    0.0,
                    0.0,
                    0.0,
                    f64::NAN,
                    f64::NAN,
                    bar_fee,
                    bar_funding,
                    flags,
                    0.0,
                    0.0,
                );
                continue;
            }

            if self.contract.bar_timestamp_semantics == INTRABAR_BAR_TIMESTAMP_CLOSE
                && state.position != 0.0
                && self.market.funding_mask[t]
            {
                let cost = state.position
                    * close_ref
                    * self.account.contract_size
                    * self.market.funding[t];
                state.equity -= cost;
                bar_funding += cost;
                result.total_funding += cost;
                flags |= INTRABAR_FLAG_FUNDING;
            }
            let (initial_margin, maintenance_margin) = self.margin_at(state.position, close_ref);
            result.snapshot(
                self.output,
                state.equity,
                state.position,
                state.average_entry,
                state.active_stop,
                state.active_take_profit,
                bar_fee,
                bar_funding,
                flags,
                initial_margin,
                maintenance_margin,
            );
        }

        if self.contract.close_on_last_bar && state.position != 0.0 && !state.liquidated {
            let t = n - 1;
            let side = exit_side(state.position);
            let price = self.market_price(self.close(t), side);
            let qty = state.position.abs();
            let fee = self.fee(qty, price);
            state.equity +=
                state.position * (price - self.close(t)) * self.account.contract_size - fee;
            result.total_fee += fee;
            result.add_final_fee(fee);
            result.record_fill(
                IntrabarFillV1::new(
                    t,
                    99,
                    side,
                    qty,
                    price,
                    fee,
                    INTRABAR_FILL_FINAL_CLOSE,
                    false,
                    self.contract.same_bar_policy,
                ),
                self.account.contract_size,
            );
            result.fill_count += 1;
            state.clear_position();
            result.overwrite_last(
                self.output,
                state.equity,
                0.0,
                0.0,
                f64::NAN,
                f64::NAN,
                0.0,
                0.0,
            );
        }

        result.final_equity = state.equity;
        result.final_position = state.position;
        result.liquidated = state.liquidated;
        result.liquidation_bar = state.liquidation_bar;
        self.observe_metric(&mut metric_reducer, n - 1, state.equity, state.position)
            .expect("intrabar accounting must yield valid final metric observation");
        let event_count = result.fill_count.saturating_add(result.rejected_count);
        result.metrics = metric_reducer.finish(MetricFinishInputV2 {
            final_equity: result.final_equity,
            turnover: result.total_turnover,
            total_fee: result.total_fee,
            total_funding: result.total_funding,
            fill_count: result.fill_count.min(i64::MAX as u64) as i64,
            event_count: event_count.min(i64::MAX as u64) as i64,
            rejected_count: result.rejected_count.min(i64::MAX as u64) as i64,
            canceled_count: 0,
            liquidated: result.liquidated,
        });
        result.execution_model_id = self.execution_model.id();
        result.request_fingerprint = self.fingerprint;
        if let Some(session_state) = session_state {
            result.session = Some(session_state);
        }
        result.terminal_fingerprint = terminal_fingerprint(&result);
        result
    }

    fn observe_metric(
        &self,
        reducer: &mut OnlineMetricReducerV2,
        bar: usize,
        equity: f64,
        position: f64,
    ) -> Result<(), String> {
        let gross_exposure = if equity > 0.0 {
            position.abs() * self.close(bar) * self.account.contract_size / equity
        } else {
            0.0
        };
        reducer.observe(self.market.timestamps_ns[bar], equity, gross_exposure)
    }

    fn open(&self, bar: usize) -> f64 {
        self.market.opens[bar]
    }
    fn high(&self, bar: usize) -> f64 {
        self.market.highs[bar]
    }
    fn low(&self, bar: usize) -> f64 {
        self.market.lows[bar]
    }
    fn close(&self, bar: usize) -> f64 {
        self.market.closes[bar]
    }

    fn market_price(&self, price: f64, side: i8) -> f64 {
        let raw = if side > 0 {
            price * (1.0 + self.account.slippage_rate)
        } else {
            price * (1.0 - self.account.slippage_rate)
        };
        quantize_price(raw, side, self.account.tick_size)
    }

    fn fee(&self, qty: f64, price: f64) -> f64 {
        qty * price * self.account.contract_size * self.account.fee_rate
    }

    fn has_initial_margin(&self, equity: f64, qty: f64, price: f64) -> bool {
        let required = qty.abs() * price * self.account.contract_size / self.account.leverage;
        equity >= required * (1.0 + self.account.margin_buffer)
    }

    fn maintenance_breached(&self, equity: f64, position: f64, price: f64) -> bool {
        let maintenance =
            position.abs() * price * self.account.contract_size * self.account.maintenance_ratio;
        maintenance > 0.0 && equity <= maintenance
    }

    fn maintenance_breached_worst(
        &self,
        equity: f64,
        position: f64,
        reference: f64,
        high: f64,
        low: f64,
    ) -> bool {
        let worst = if position > 0.0 { low } else { high };
        let worst_equity = equity + position * (worst - reference) * self.account.contract_size;
        let maintenance =
            position.abs() * worst * self.account.contract_size * self.account.maintenance_ratio;
        maintenance > 0.0 && worst_equity <= maintenance
    }

    fn margin_at(&self, position: f64, price: f64) -> (f64, f64) {
        (
            position.abs() * price * self.account.contract_size / self.account.leverage,
            position.abs() * price * self.account.contract_size * self.account.maintenance_ratio,
        )
    }

    fn compile_entry_quantity(
        &self,
        size_weight: f64,
        fill_price: f64,
        equity: f64,
        stop_value: f64,
        side: i8,
    ) -> f64 {
        let weight = size_weight.abs();
        match self.account.sizing_mode {
            INTRABAR_SIZING_UNITS => weight,
            INTRABAR_SIZING_FIXED_NOTIONAL => {
                self.account.fixed_notional * weight / (fill_price * self.account.contract_size)
            }
            INTRABAR_SIZING_PCT_EQUITY => {
                equity * self.account.equity_fraction * weight
                    / (fill_price * self.account.contract_size)
            }
            INTRABAR_SIZING_RISK_PER_TRADE => {
                if !stop_value.is_finite() || stop_value <= 0.0 {
                    return 0.0;
                }
                let stop = level_price(
                    fill_price,
                    side,
                    stop_value,
                    self.intent.level_mode,
                    true,
                    self.account.tick_size,
                );
                let distance = (fill_price - stop).abs();
                if distance <= 0.0 {
                    0.0
                } else {
                    equity * self.account.risk_fraction * weight
                        / (distance * self.account.contract_size)
                }
            }
            _ => 0.0,
        }
    }

    fn quantize_quantity(&self, qty: f64, price: f64) -> f64 {
        if qty == 0.0 {
            return 0.0;
        }
        let sign = if qty > 0.0 { 1.0 } else { -1.0 };
        let mut absolute = qty.abs();
        if self.account.qty_step > 0.0 {
            absolute = ((absolute / self.account.qty_step) + 1e-12).floor() * self.account.qty_step;
        }
        if absolute <= 0.0
            || (self.account.min_qty > 0.0 && absolute + 1e-12 < self.account.min_qty)
            || (self.account.min_notional > 0.0
                && absolute * price * self.account.contract_size + 1e-12
                    < self.account.min_notional)
        {
            0.0
        } else {
            sign * absolute
        }
    }

    fn initial_bracket(&self, signal_bar: usize, side: i8, fill_price: f64) -> (f64, f64) {
        let stop_value = self.intent.stop_value[signal_bar];
        let tp_value = self.intent.take_profit_value[signal_bar];
        let trailing_value = self.intent.trailing_value[signal_bar];
        let mut stop = if stop_value.is_finite() && stop_value > 0.0 {
            level_price(
                fill_price,
                side,
                stop_value,
                self.intent.level_mode,
                true,
                self.account.tick_size,
            )
        } else {
            f64::NAN
        };
        let tp = if tp_value.is_finite() && tp_value > 0.0 {
            level_price(
                fill_price,
                side,
                tp_value,
                self.intent.level_mode,
                false,
                self.account.tick_size,
            )
        } else {
            f64::NAN
        };
        if trailing_value.is_finite() && trailing_value > 0.0 {
            let trailing = level_price(
                fill_price,
                side,
                trailing_value,
                self.intent.level_mode,
                true,
                self.account.tick_size,
            );
            stop = if !stop.is_finite() {
                trailing
            } else if side > 0 {
                stop.max(trailing)
            } else {
                stop.min(trailing)
            };
        }
        (stop, tp)
    }

    fn update_trailing(&self, bar: usize, position: f64, close: f64, current_stop: f64) -> f64 {
        let value = self.intent.trailing_value[bar];
        if !value.is_finite() || value <= 0.0 {
            return current_stop;
        }
        let side = sign(position);
        let candidate = level_price(
            close,
            side,
            value,
            self.intent.level_mode,
            true,
            self.account.tick_size,
        );
        if !current_stop.is_finite() {
            candidate
        } else if side > 0 {
            current_stop.max(candidate)
        } else {
            current_stop.min(candidate)
        }
    }

    fn resolve_intrabar_exit(
        &self,
        side: i8,
        open: f64,
        high: f64,
        low: f64,
        stop: f64,
        tp: f64,
    ) -> Option<IntrabarExitV1> {
        let has_stop = stop.is_finite() && stop > 0.0;
        let has_tp = tp.is_finite() && tp > 0.0;
        let (stop_hit, tp_hit, stop_gap, tp_gap, exit_side) = if side > 0 {
            (
                has_stop && low <= stop,
                has_tp && high >= tp,
                has_stop && open <= stop,
                has_tp && open >= tp,
                -1,
            )
        } else {
            (
                has_stop && high >= stop,
                has_tp && low <= tp,
                has_stop && open >= stop,
                has_tp && open <= tp,
                1,
            )
        };
        if !stop_hit && !tp_hit {
            return None;
        }
        let ambiguous = stop_hit && tp_hit;
        let stop_first = self.contract.same_bar_policy == INTRABAR_SAME_BAR_CONSERVATIVE
            || self.contract.same_bar_policy == INTRABAR_SAME_BAR_STOP_FIRST
            || (side > 0 && self.contract.same_bar_policy == INTRABAR_SAME_BAR_OLHC_PATH)
            || (side < 0 && self.contract.same_bar_policy == INTRABAR_SAME_BAR_OHLC_PATH);
        if stop_hit && (!tp_hit || stop_first) {
            let raw = if stop_gap { open } else { stop };
            return Some(IntrabarExitV1 {
                side: exit_side,
                price: self.market_price(raw, exit_side),
                reason: INTRABAR_FILL_STOP_LOSS,
                ambiguous,
            });
        }
        let raw = if tp_gap
            && self.contract.take_profit_gap_policy == INTRABAR_TP_OPEN_PRICE_IMPROVEMENT
        {
            open
        } else {
            tp
        };
        Some(IntrabarExitV1 {
            side: exit_side,
            price: quantize_price(raw, exit_side, self.account.tick_size),
            reason: INTRABAR_FILL_TAKE_PROFIT,
            ambiguous,
        })
    }
}

#[derive(Clone, Copy, Debug)]
struct IntrabarExitV1 {
    side: i8,
    price: f64,
    reason: i16,
    ambiguous: bool,
}

#[derive(Clone, Copy, Debug)]
struct IntrabarStateV1 {
    equity: f64,
    position: f64,
    average_entry: f64,
    active_stop: f64,
    active_take_profit: f64,
    liquidated: bool,
    liquidation_bar: i64,
}

impl IntrabarStateV1 {
    fn new(equity: f64) -> Self {
        Self {
            equity,
            position: 0.0,
            average_entry: 0.0,
            active_stop: f64::NAN,
            active_take_profit: f64::NAN,
            liquidated: false,
            liquidation_bar: -1,
        }
    }
    fn clear_position(&mut self) {
        self.position = 0.0;
        self.average_entry = 0.0;
        self.active_stop = f64::NAN;
        self.active_take_profit = f64::NAN;
    }
}

#[derive(Clone, Debug, Default)]
pub struct IntrabarSessionStateV1 {
    pub current_session_id: i64,
    pub long_entry_count: i64,
    pub short_entry_count: i64,
    pub protective_exit_on_previous_bar: bool,
    pub session_reset_count: u64,
    pub session_forced_exit_count: u64,
    pub entry_window_blocked_count: u64,
    pub long_quota_blocked_count: u64,
    pub short_quota_blocked_count: u64,
    pub flat_only_blocked_count: u64,
    pub stale_session_signal_count: u64,
    pub reentry_suppressed_count: u64,
}

#[derive(Clone, Debug)]
pub struct IntrabarFillV1 {
    pub bar: i64,
    pub sequence: i64,
    pub side: i8,
    pub qty: f64,
    pub price: f64,
    pub fee: f64,
    pub reason: i16,
    pub ambiguity: bool,
    pub same_bar_policy: u8,
}

impl IntrabarFillV1 {
    #[allow(clippy::too_many_arguments)]
    fn new(
        bar: usize,
        sequence: i64,
        side: i8,
        qty: f64,
        price: f64,
        fee: f64,
        reason: i16,
        ambiguity: bool,
        same_bar_policy: u8,
    ) -> Self {
        Self {
            bar: bar as i64,
            sequence,
            side,
            qty,
            price,
            fee,
            reason,
            ambiguity,
            same_bar_policy,
        }
    }
}

#[derive(Clone, Debug)]
pub struct IntrabarPathsV1 {
    pub equity: Vec<f64>,
    pub position: Vec<f64>,
    pub average_entry: Vec<f64>,
    pub active_stop: Vec<f64>,
    pub active_take_profit: Vec<f64>,
    pub fees: Vec<f64>,
    pub funding: Vec<f64>,
    pub event_flags: Vec<u32>,
    pub initial_margin: Vec<f64>,
    pub maintenance_margin: Vec<f64>,
}

impl IntrabarPathsV1 {
    fn with_capacity(n: usize) -> Self {
        Self {
            equity: Vec::with_capacity(n),
            position: Vec::with_capacity(n),
            average_entry: Vec::with_capacity(n),
            active_stop: Vec::with_capacity(n),
            active_take_profit: Vec::with_capacity(n),
            fees: Vec::with_capacity(n),
            funding: Vec::with_capacity(n),
            event_flags: Vec::with_capacity(n),
            initial_margin: Vec::with_capacity(n),
            maintenance_margin: Vec::with_capacity(n),
        }
    }
    #[allow(clippy::too_many_arguments)]
    fn push(
        &mut self,
        equity: f64,
        position: f64,
        average_entry: f64,
        stop: f64,
        tp: f64,
        fee: f64,
        funding: f64,
        flags: u32,
        initial_margin: f64,
        maintenance_margin: f64,
    ) {
        self.equity.push(equity);
        self.position.push(position);
        self.average_entry.push(average_entry);
        self.active_stop
            .push(if stop.is_finite() { stop } else { 0.0 });
        self.active_take_profit
            .push(if tp.is_finite() { tp } else { 0.0 });
        self.fees.push(fee);
        self.funding.push(funding);
        self.event_flags.push(flags);
        self.initial_margin.push(initial_margin);
        self.maintenance_margin.push(maintenance_margin);
    }
    #[allow(clippy::too_many_arguments)]
    fn overwrite_last(
        &mut self,
        equity: f64,
        position: f64,
        average_entry: f64,
        stop: f64,
        tp: f64,
        initial_margin: f64,
        maintenance_margin: f64,
    ) {
        let index = self.equity.len().saturating_sub(1);
        self.equity[index] = equity;
        self.position[index] = position;
        self.average_entry[index] = average_entry;
        self.active_stop[index] = if stop.is_finite() { stop } else { 0.0 };
        self.active_take_profit[index] = if tp.is_finite() { tp } else { 0.0 };
        self.initial_margin[index] = initial_margin;
        self.maintenance_margin[index] = maintenance_margin;
    }
}

#[derive(Clone, Debug, Default)]
pub struct IntrabarAuditV1 {
    pub fills: Vec<IntrabarFillV1>,
    pub ambiguity_bar: Vec<i64>,
    pub ambiguity_policy: Vec<u8>,
    pub retained_rows: usize,
    pub dropped_rows: usize,
    detail_limit: usize,
}

impl IntrabarAuditV1 {
    fn with_limit(detail_limit: usize) -> Self {
        Self {
            detail_limit,
            ..Self::default()
        }
    }
    fn retain(&mut self) -> bool {
        if self.retained_rows < self.detail_limit {
            self.retained_rows += 1;
            true
        } else {
            self.dropped_rows += 1;
            false
        }
    }
}

#[derive(Clone, Debug)]
pub struct IntrabarExecutionResultV1 {
    pub output_profile: IntrabarOutputProfileV1,
    pub final_equity: f64,
    pub final_position: f64,
    pub total_fee: f64,
    pub total_turnover: f64,
    pub total_funding: f64,
    pub fill_count: u64,
    pub ambiguity_count: u64,
    pub rejected_count: u64,
    pub liquidated: bool,
    pub liquidation_bar: i64,
    pub paths: Option<IntrabarPathsV1>,
    pub audit: IntrabarAuditV1,
    pub session: Option<IntrabarSessionStateV1>,
    pub execution_model_id: &'static str,
    pub metric_contract: MetricContractV2,
    pub metrics: NativeMetricSnapshotV2,
    pub request_fingerprint: [u8; 32],
    pub terminal_fingerprint: [u8; 32],
}

impl IntrabarExecutionResultV1 {
    fn new(profile: IntrabarOutputProfileV1, n: usize, audit_limit: usize) -> Self {
        Self {
            output_profile: profile,
            final_equity: 0.0,
            final_position: 0.0,
            total_fee: 0.0,
            total_turnover: 0.0,
            total_funding: 0.0,
            fill_count: 0,
            ambiguity_count: 0,
            rejected_count: 0,
            liquidated: false,
            liquidation_bar: -1,
            paths: (profile != IntrabarOutputProfileV1::Score)
                .then(|| IntrabarPathsV1::with_capacity(n)),
            audit: if profile == IntrabarOutputProfileV1::Audit {
                IntrabarAuditV1::with_limit(audit_limit)
            } else {
                IntrabarAuditV1::with_limit(0)
            },
            session: None,
            execution_model_id: "bar_touch_v1",
            metric_contract: MetricContractV2::crypto_daily(),
            metrics: NativeMetricSnapshotV2::default(),
            request_fingerprint: [0; 32],
            terminal_fingerprint: [0; 32],
        }
    }
    #[allow(clippy::too_many_arguments)]
    fn snapshot(
        &mut self,
        profile: IntrabarOutputProfileV1,
        equity: f64,
        position: f64,
        average_entry: f64,
        stop: f64,
        tp: f64,
        fee: f64,
        funding: f64,
        flags: u32,
        initial_margin: f64,
        maintenance_margin: f64,
    ) {
        if profile != IntrabarOutputProfileV1::Score
            && let Some(paths) = self.paths.as_mut()
        {
            paths.push(
                equity,
                position,
                average_entry,
                stop,
                tp,
                fee,
                funding,
                flags,
                initial_margin,
                maintenance_margin,
            );
        }
    }
    #[allow(clippy::too_many_arguments)]
    fn overwrite_last(
        &mut self,
        profile: IntrabarOutputProfileV1,
        equity: f64,
        position: f64,
        average_entry: f64,
        stop: f64,
        tp: f64,
        initial_margin: f64,
        maintenance_margin: f64,
    ) {
        if profile != IntrabarOutputProfileV1::Score
            && let Some(paths) = self.paths.as_mut()
        {
            paths.overwrite_last(
                equity,
                position,
                average_entry,
                stop,
                tp,
                initial_margin,
                maintenance_margin,
            );
        }
    }
    fn add_final_fee(&mut self, fee: f64) {
        if let Some(paths) = self.paths.as_mut()
            && let Some(value) = paths.fees.last_mut()
        {
            *value += fee;
        }
    }
    fn record_fill(&mut self, fill: IntrabarFillV1, contract_size: f64) {
        self.total_turnover += fill.qty.abs() * fill.price.abs() * contract_size;
        if self.output_profile == IntrabarOutputProfileV1::Audit && self.audit.retain() {
            self.audit.fills.push(fill);
        }
    }
    fn record_ambiguity(&mut self, bar: i64, policy: u8) {
        if self.output_profile == IntrabarOutputProfileV1::Audit && self.audit.retain() {
            self.audit.ambiguity_bar.push(bar);
            self.audit.ambiguity_policy.push(policy);
        }
    }
}

fn sign(value: f64) -> i8 {
    if value > 0.0 {
        1
    } else if value < 0.0 {
        -1
    } else {
        0
    }
}
fn exit_side(position: f64) -> i8 {
    if position > 0.0 { -1 } else { 1 }
}

fn quantize_price(price: f64, side: i8, tick_size: f64) -> f64 {
    if tick_size <= 0.0 || !price.is_finite() {
        return price;
    }
    if side > 0 {
        ((price / tick_size) - 1e-12).ceil() * tick_size
    } else {
        ((price / tick_size) + 1e-12).floor() * tick_size
    }
}

fn level_price(
    price: f64,
    side: i8,
    value: f64,
    level_mode: u8,
    is_stop: bool,
    tick_size: f64,
) -> f64 {
    let direction = if (side > 0 && is_stop) || (side < 0 && !is_stop) {
        -1.0
    } else {
        1.0
    };
    let raw = match level_mode {
        INTRABAR_LEVEL_ABSOLUTE_PRICE => value,
        INTRABAR_LEVEL_PRICE_DISTANCE => price + direction * value,
        _ => price * (1.0 + direction * value),
    };
    quantize_price(raw, -side, tick_size)
}

fn fnv_mix(mut state: u64, bytes: &[u8]) -> u64 {
    for byte in bytes {
        state ^= u64::from(*byte);
        state = state.wrapping_mul(0x100000001b3);
    }
    state
}

fn fingerprint_push(state: &mut [u64; 4], bytes: &[u8]) {
    for (index, value) in state.iter_mut().enumerate() {
        *value = fnv_mix(*value, bytes);
        *value = value.rotate_left((index as u32 + 5) * 7);
    }
}

fn intrabar_fingerprint(
    market: &FullMarketData,
    intent: &IntrabarIntentV1,
    account: IntrabarAccountConfigV1,
    contract: IntrabarContractConfigV1,
    session: Option<&IntrabarSessionConfigV1>,
    output: IntrabarOutputProfileV1,
    audit_limit: usize,
) -> [u8; 32] {
    let mut state = [
        0xcbf29ce484222325,
        0x84222325cbf29ce4,
        0x9e3779b185ebca87,
        0xd6e8feb86659fd93,
    ];
    fingerprint_push(&mut state, b"quantbt-intrabar-request-v1");
    for value in &market.timestamps_ns {
        fingerprint_push(&mut state, &value.to_le_bytes());
    }
    for values in [
        &market.opens[..],
        &market.highs[..],
        &market.lows[..],
        &market.closes[..],
        &market.funding[..],
        &intent.entry_size[..],
        &intent.stop_value[..],
        &intent.take_profit_value[..],
        &intent.trailing_value[..],
    ] {
        for value in values {
            fingerprint_push(&mut state, &value.to_bits().to_le_bytes());
        }
    }
    fingerprint_push(&mut state, &i8_bytes(&intent.entry_side));
    fingerprint_push(&mut state, &bool_bytes(&market.funding_mask));
    fingerprint_push(&mut state, &bool_bytes(&intent.exit_long));
    fingerprint_push(&mut state, &bool_bytes(&intent.exit_short));
    for value in [
        account.initial_capital,
        account.leverage,
        account.maintenance_ratio,
        account.margin_buffer,
        account.contract_size,
        account.fee_rate,
        account.slippage_rate,
        account.fixed_notional,
        account.equity_fraction,
        account.risk_fraction,
        account.qty_step,
        account.min_qty,
        account.min_notional,
        account.tick_size,
    ] {
        fingerprint_push(&mut state, &value.to_bits().to_le_bytes());
    }
    fingerprint_push(
        &mut state,
        &[
            account.sizing_mode,
            intent.level_mode,
            contract.bar_timestamp_semantics,
            contract.same_bar_policy,
            contract.take_profit_gap_policy,
            u8::from(contract.close_on_last_bar),
            output as u8,
        ],
    );
    fingerprint_push(&mut state, &(audit_limit as u64).to_le_bytes());
    if let Some(value) = session {
        for id in &value.session_id {
            fingerprint_push(&mut state, &id.to_le_bytes());
        }
        fingerprint_push(&mut state, &bool_bytes(&value.entry_allowed_at_open));
        fingerprint_push(&mut state, &bool_bytes(&value.force_flat_at_open));
        fingerprint_push(
            &mut state,
            &[
                value.entry_position_policy,
                value.counter_basis,
                value.protective_reentry_policy,
                u8::from(value.cancel_pending_on_session_change),
                u8::from(value.suppress_entry_on_force_flat_bar),
            ],
        );
        fingerprint_push(
            &mut state,
            &value.max_long_entries_per_session.to_le_bytes(),
        );
        fingerprint_push(
            &mut state,
            &value.max_short_entries_per_session.to_le_bytes(),
        );
    }
    let mut out = [0_u8; 32];
    for (index, value) in state.iter().enumerate() {
        out[index * 8..index * 8 + 8].copy_from_slice(&value.to_le_bytes());
    }
    out
}

fn terminal_fingerprint(result: &IntrabarExecutionResultV1) -> [u8; 32] {
    let mut state = [
        0xcbf29ce484222325,
        0x84222325cbf29ce4,
        0x9e3779b185ebca87,
        0xd6e8feb86659fd93,
    ];
    fingerprint_push(&mut state, b"quantbt-intrabar-terminal-v1");
    for value in [
        result.final_equity,
        result.final_position,
        result.total_fee,
        result.total_turnover,
        result.total_funding,
    ] {
        fingerprint_push(&mut state, &value.to_bits().to_le_bytes());
    }
    for value in [
        result.fill_count,
        result.ambiguity_count,
        result.rejected_count,
    ] {
        fingerprint_push(&mut state, &value.to_le_bytes());
    }
    fingerprint_push(&mut state, &[u8::from(result.liquidated)]);
    fingerprint_push(&mut state, &result.liquidation_bar.to_le_bytes());
    let mut out = [0_u8; 32];
    for (index, value) in state.iter().enumerate() {
        out[index * 8..index * 8 + 8].copy_from_slice(&value.to_le_bytes());
    }
    out
}

fn i8_bytes(values: &[i8]) -> Vec<u8> {
    values.iter().map(|value| *value as u8).collect()
}
fn bool_bytes(values: &[bool]) -> Vec<u8> {
    values.iter().map(|value| u8::from(*value)).collect()
}

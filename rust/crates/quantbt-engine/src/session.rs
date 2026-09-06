//! Full Native Event V2 contract engine.
//!
//! This module deliberately mirrors the ordering in ``core.event._engine_event_v2``.
//! It is a compact, allocation-light Rust implementation of the public command
//! tape contract.  The older ``session`` module remains intact for ABI
//! compatibility with pre-47 wheels; the PyO3 layer exposes this module under a
//! versioned full-contract class.

use std::collections::HashMap;
use std::sync::Arc;

use crate::execution_model::{
    ExecutionClockStateV1, ExecutionModelPlanV1, ExecutionModelV1, FillCostInputV1, FillDecisionV1,
    LiquidityLedgerV1, MarketBarViewV1, OrderTouchViewV1,
};
use crate::generated_contracts::{
    CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN,
};
use crate::metrics_v2::{MetricContractV2, MetricFinishInputV2, OnlineMetricReducerV2};
use crate::orders::{IndexOrderState, LifecycleIndexes, OrderArena};
use crate::output::{
    AuditRetentionV1, NativeAuditOutputV1, NativeCompactOutputV1, NativeEventOutputV1,
    NativeExecutionOutputV1, NativeFillOutputV1, NativePathOutputV1, NativeScoreOutputV1,
    OutputRequirementsV1, StaticOutputProfile, StaticTapeOutput,
};
use quantbt_domain::commands::{CommandTapeV5, OrderCommandV5};
use quantbt_domain::ids::{ExternalOrderId, OrderHandle, SymbolId};

const STATUS_PENDING: i64 = 0;
const STATUS_FILLED: i64 = 1;
const STATUS_CANCELED: i64 = 2;
const STATUS_REJECTED: i64 = 3;

const ACTION_PLACE: i64 = 0;
const ACTION_CANCEL: i64 = 1;
const ACTION_REPLACE: i64 = 2;
const ACTION_AMEND: i64 = 3;
const ACTION_CANCEL_ALL: i64 = 4;

const ORDER_MARKET: i64 = 0;
const ORDER_LIMIT: i64 = 1;
const ORDER_STOP_MARKET: i64 = 2;
const ORDER_STOP_LIMIT: i64 = 3;
const TIF_GTC: i64 = 0;
#[allow(dead_code)]
const TIF_IOC: i64 = 1;
#[allow(dead_code)]
const TIF_FOK: i64 = 2;
const TIF_GTD: i64 = 3;
const SIDE_BUY: i64 = 1;
const SIDE_SELL: i64 = -1;

const ACTIVATION_IMMEDIATE: i64 = 0;
const ACTIVATION_ON_PARENT_FIRST_FILL: i64 = 1;
const ACTIVATION_ON_PARENT_FULL_FILL: i64 = 2;
const FLAG_REDUCE_ONLY: u16 = 1 << 0;
const DEFAULT_MAX_LIVE_ORDERS: usize = 1_000_000;
const DEFAULT_MAX_TOTAL_ORDERS: u64 = 10_000_000;

pub use crate::execution_model::{
    FILL_AMBIGUITY_NONE_V1 as FILL_AMBIGUITY_NONE,
    FILL_AMBIGUITY_STOP_LIMIT_PATH_UNKNOWN_V1 as FILL_AMBIGUITY_STOP_LIMIT_PATH_UNKNOWN,
    FILL_AMBIGUITY_UNORDERED_OHLC_RANGE_V1 as FILL_AMBIGUITY_UNORDERED_OHLC_RANGE,
    FILL_REASON_LIMIT_OPEN_IMPROVEMENT_V1 as FILL_REASON_LIMIT_OPEN_IMPROVEMENT,
    FILL_REASON_LIMIT_TRIGGER_V1 as FILL_REASON_LIMIT_TRIGGER,
    FILL_REASON_NEXT_BAR_CLOSE_V1 as FILL_REASON_NEXT_BAR_CLOSE,
    FILL_REASON_NEXT_OPEN_V1 as FILL_REASON_NEXT_OPEN, FILL_REASON_NONE_V1 as FILL_REASON_NONE,
    FILL_REASON_STOP_LIMIT_AFTER_OPEN_TRIGGER_V1 as FILL_REASON_STOP_LIMIT_AFTER_OPEN_TRIGGER,
    FILL_REASON_STOP_LIMIT_LEGACY_V1 as FILL_REASON_STOP_LIMIT_LEGACY,
    FILL_REASON_STOP_LIMIT_OPEN_IMPROVEMENT_V1 as FILL_REASON_STOP_LIMIT_OPEN_IMPROVEMENT,
    FILL_REASON_STOP_OPEN_WORSE_V1 as FILL_REASON_STOP_OPEN_WORSE,
    FILL_REASON_STOP_TRIGGER_LEGACY_V1 as FILL_REASON_STOP_TRIGGER_LEGACY,
    FILL_REASON_STOP_TRIGGER_V1 as FILL_REASON_STOP_TRIGGER,
    FILL_REASON_TRIGGERED_AWAIT_NEXT_BAR_V1 as FILL_REASON_TRIGGERED_AWAIT_NEXT_BAR,
    FILL_REASON_TRIGGERED_LIMIT_NOT_TOUCHED_V1 as FILL_REASON_TRIGGERED_LIMIT_NOT_TOUCHED,
};

/// Frozen pre-Phase-60 touch implementation retained only as an in-crate test
/// oracle. Production execution calls `ExecutionModelPlanV1` below.
#[cfg(test)]
#[derive(Clone, Copy, Debug, PartialEq)]
struct LegacyFillDecision {
    price: Option<f64>,
    triggered: bool,
    reason: i64,
    ambiguity: i64,
}

#[cfg(test)]
impl LegacyFillDecision {
    #[inline]
    const fn no_fill(triggered: bool, reason: i64, ambiguity: i64) -> Self {
        Self {
            price: None,
            triggered,
            reason,
            ambiguity,
        }
    }

    #[inline]
    const fn fill(price: f64, triggered: bool, reason: i64, ambiguity: i64) -> Self {
        Self {
            price: Some(price),
            triggered,
            reason,
            ambiguity,
        }
    }
}

#[cfg(test)]
type FillDecision = LegacyFillDecision;

#[repr(u8)]
#[derive(Clone, Copy)]
enum InternalOrderType {
    Market = ORDER_MARKET as u8,
    Limit = ORDER_LIMIT as u8,
    StopMarket = ORDER_STOP_MARKET as u8,
    StopLimit = ORDER_STOP_LIMIT as u8,
}

impl TryFrom<i64> for InternalOrderType {
    type Error = ();

    fn try_from(value: i64) -> Result<Self, Self::Error> {
        match value {
            ORDER_MARKET => Ok(Self::Market),
            ORDER_LIMIT => Ok(Self::Limit),
            ORDER_STOP_MARKET => Ok(Self::StopMarket),
            ORDER_STOP_LIMIT => Ok(Self::StopLimit),
            _ => Err(()),
        }
    }
}

#[repr(u8)]
#[derive(Clone, Copy)]
enum InternalTimeInForce {
    Gtc = TIF_GTC as u8,
    Ioc = TIF_IOC as u8,
    Fok = TIF_FOK as u8,
    Gtd = TIF_GTD as u8,
}

impl TryFrom<i64> for InternalTimeInForce {
    type Error = ();

    fn try_from(value: i64) -> Result<Self, Self::Error> {
        match value {
            TIF_GTC => Ok(Self::Gtc),
            TIF_IOC => Ok(Self::Ioc),
            TIF_FOK => Ok(Self::Fok),
            TIF_GTD => Ok(Self::Gtd),
            _ => Err(()),
        }
    }
}

#[repr(i8)]
#[derive(Clone, Copy)]
enum InternalSide {
    Sell = SIDE_SELL as i8,
    Buy = SIDE_BUY as i8,
}

impl TryFrom<i64> for InternalSide {
    type Error = ();

    fn try_from(value: i64) -> Result<Self, Self::Error> {
        match value {
            SIDE_BUY => Ok(Self::Buy),
            SIDE_SELL => Ok(Self::Sell),
            _ => Err(()),
        }
    }
}

pub const EVENT_PLACE: i64 = 0;
pub const EVENT_CANCEL: i64 = 1;
pub const EVENT_REPLACE: i64 = 2;
pub const EVENT_AMEND: i64 = 3;
pub const EVENT_FILL: i64 = 4;
pub const EVENT_EXPIRE: i64 = 5;
pub const EVENT_ACTIVATE: i64 = 6;
pub const EVENT_REJECT: i64 = 7;

#[allow(dead_code)]
pub const REJECT_NONE: i64 = 0;
pub const REJECT_INSUFFICIENT_MARGIN: i64 = 1;
pub const REJECT_UNSUPPORTED_ORDER_TYPE: i64 = 2;
pub const REJECT_UNKNOWN_ORDER: i64 = 3;
#[allow(dead_code)]
pub const REJECT_INVALID_AMEND: i64 = 4;
pub const REJECT_REDUCE_ONLY_NO_POSITION: i64 = 5;
pub const REJECT_UNSUPPORTED_ACTION: i64 = 6;

pub const LIQ_NONE: i64 = 0;
pub const LIQ_INTRABAR: i64 = 1;
pub const LIQ_AFTER_FUNDING: i64 = 2;
pub const LIQ_AFTER_ORDER: i64 = 3;

pub const CODE_WIDTH: usize = 16;
pub const VALUE_WIDTH: usize = 3;

// Per-step projection mask.  Accounting and lifecycle state are always
// computed; these bits only control which transient vectors cross the PyO3
// boundary for reactive callbacks.
pub const OUTPUT_POSITIONS: u8 = 1;
pub const OUTPUT_FILLS: u8 = 2;
pub const OUTPUT_EVENTS: u8 = 4;
pub const OUTPUT_ACTIVE_ORDERS: u8 = 8;
pub const OUTPUT_ALL: u8 = OUTPUT_POSITIONS | OUTPUT_FILLS | OUTPUT_EVENTS | OUTPUT_ACTIVE_ORDERS;

/// Scalar lifecycle counters are kept separately from projected detail rows.
/// This is the count-only sink used by score runs, so a score never needs to
/// allocate a nested row just to report a fill or event count.
#[derive(Clone, Copy, Default)]
pub struct StepCounters {
    pub fill_count: i64,
    pub event_count: i64,
    /// Kept separate from generic event count so a legacy compatibility
    /// projection can retain its historical two-row REPLACE artifact without
    /// reconstructing lifecycle state outside the engine.
    pub replace_count: i64,
    pub rejected_count: i64,
    pub canceled_count: i64,
}

#[derive(Default)]
pub struct FillBuffer {
    pub order_id: Vec<i64>,
    pub symbol: Vec<i64>,
    pub side: Vec<i64>,
    pub qty: Vec<f64>,
    pub price: Vec<f64>,
    pub fee: Vec<f64>,
    pub reason: Vec<i64>,
    pub ambiguity: Vec<i64>,
}

impl FillBuffer {
    #[inline]
    pub fn clear(&mut self) {
        self.order_id.clear();
        self.symbol.clear();
        self.side.clear();
        self.qty.clear();
        self.price.clear();
        self.fee.clear();
        self.reason.clear();
        self.ambiguity.clear();
    }

    #[inline]
    #[allow(clippy::too_many_arguments)]
    pub fn push(
        &mut self,
        order_id: i64,
        symbol: i64,
        side: i64,
        qty: f64,
        price: f64,
        fee: f64,
        reason: i64,
        ambiguity: i64,
    ) {
        self.order_id.push(order_id);
        self.symbol.push(symbol);
        self.side.push(side);
        self.qty.push(qty);
        self.price.push(price);
        self.fee.push(fee);
        self.reason.push(reason);
        self.ambiguity.push(ambiguity);
    }

    pub fn rows(&self) -> Vec<Vec<f64>> {
        (0..self.order_id.len())
            .map(|i| {
                vec![
                    self.order_id[i] as f64,
                    self.symbol[i] as f64,
                    self.side[i] as f64,
                    self.qty[i],
                    self.price[i],
                    self.fee[i],
                ]
            })
            .collect()
    }
}

#[derive(Default)]
pub struct EventBuffer {
    pub kind: Vec<i64>,
    pub status: Vec<i64>,
    pub order_id: Vec<i64>,
    pub target_id: Vec<i64>,
    pub symbol: Vec<i64>,
    pub reject_code: Vec<i64>,
}

impl EventBuffer {
    #[inline]
    pub fn clear(&mut self) {
        self.kind.clear();
        self.status.clear();
        self.order_id.clear();
        self.target_id.clear();
        self.symbol.clear();
        self.reject_code.clear();
    }

    #[inline]
    pub fn push(
        &mut self,
        kind: i64,
        status: i64,
        order_id: i64,
        target_id: i64,
        symbol: i64,
        reject_code: i64,
    ) {
        self.kind.push(kind);
        self.status.push(status);
        self.order_id.push(order_id);
        self.target_id.push(target_id);
        self.symbol.push(symbol);
        self.reject_code.push(reject_code);
    }

    pub fn rows(&self) -> Vec<Vec<i64>> {
        (0..self.kind.len())
            .map(|i| {
                vec![
                    self.kind[i],
                    self.status[i],
                    self.order_id[i],
                    self.target_id[i],
                    self.symbol[i],
                    self.reject_code[i],
                ]
            })
            .collect()
    }
}

#[derive(Default)]
pub struct ActiveOrderBuffer {
    pub order_id: Vec<i64>,
    pub symbol: Vec<i64>,
    pub side: Vec<i64>,
    pub order_type: Vec<i64>,
    pub qty: Vec<f64>,
    pub price: Vec<f64>,
    pub trigger: Vec<f64>,
    pub tif: Vec<i64>,
    pub flags: Vec<i64>,
    pub parent_id: Vec<i64>,
    pub group_id: Vec<i64>,
    pub oco_id: Vec<i64>,
    pub activation: Vec<i64>,
    pub waiting_parent: Vec<i64>,
}

impl ActiveOrderBuffer {
    #[inline]
    pub fn clear(&mut self) {
        self.order_id.clear();
        self.symbol.clear();
        self.side.clear();
        self.order_type.clear();
        self.qty.clear();
        self.price.clear();
        self.trigger.clear();
        self.tif.clear();
        self.flags.clear();
        self.parent_id.clear();
        self.group_id.clear();
        self.oco_id.clear();
        self.activation.clear();
        self.waiting_parent.clear();
    }

    #[inline]
    fn push(&mut self, order: &OrderState) {
        self.order_id.push(order.order_id);
        self.symbol.push(order.symbol as i64);
        self.side.push(order.side as i64);
        self.order_type.push(order.order_type as i64);
        self.qty.push(order.qty);
        self.price.push(order.price);
        self.trigger.push(order.trigger);
        self.tif.push(order.tif as i64);
        self.flags.push(if order.reduce_only() {
            FLAG_REDUCE_ONLY as i64
        } else {
            0
        });
        self.parent_id.push(order.parent_id);
        self.group_id.push(order.group_id);
        self.oco_id.push(order.oco_id);
        self.activation.push(order.activation as i64);
        self.waiting_parent
            .push(if order.waiting_parent { 1 } else { 0 });
    }

    pub fn rows(&self) -> Vec<Vec<f64>> {
        (0..self.order_id.len())
            .map(|i| {
                vec![
                    self.order_id[i] as f64,
                    self.symbol[i] as f64,
                    self.side[i] as f64,
                    self.order_type[i] as f64,
                    self.qty[i],
                    self.price[i],
                    self.trigger[i],
                    self.tif[i] as f64,
                    self.flags[i] as f64,
                    self.parent_id[i] as f64,
                    self.group_id[i] as f64,
                    self.oco_id[i] as f64,
                    self.activation[i] as f64,
                    self.waiting_parent[i] as f64,
                ]
            })
            .collect()
    }
}

#[derive(Default)]
pub struct StepBuffers {
    pub fills: FillBuffer,
    pub events: EventBuffer,
    pub active_orders: ActiveOrderBuffer,
}

/// Reusable ABI-0.5 to lifecycle-buffer adapter.
///
/// Typed strategy, portfolio, and package drivers own this scratch object for
/// the duration of a run.  It keeps their commands on the certified engine
/// path without allocating a Python-visible whole-tape representation.
#[derive(Default)]
pub struct TypedCommandScratch {
    codes: Vec<i64>,
    values: Vec<f64>,
    expiry: Vec<i64>,
}

impl TypedCommandScratch {
    #[must_use]
    pub fn with_capacity(max_commands_per_bar: usize) -> Self {
        Self {
            codes: Vec::with_capacity(max_commands_per_bar * CODE_WIDTH),
            values: Vec::with_capacity(max_commands_per_bar * VALUE_WIDTH),
            expiry: Vec::with_capacity(max_commands_per_bar),
        }
    }

    fn encode(&mut self, commands: &[OrderCommandV5]) {
        self.codes.clear();
        self.values.clear();
        self.expiry.clear();
        for command in commands {
            encode_typed_command(command, &mut self.codes, &mut self.values, &mut self.expiry);
        }
    }
}

impl StepBuffers {
    #[inline]
    pub fn clear(&mut self) {
        self.fills.clear();
        self.events.clear();
        self.active_orders.clear();
    }

    /// Release only deliberately excessive capacity during service
    /// maintenance. The execution loop never shrinks its working buffers.
    pub fn release_excess_capacity(&mut self, max_capacity: usize) {
        for capacity in [
            self.fills.order_id.capacity(),
            self.events.kind.capacity(),
            self.active_orders.order_id.capacity(),
        ] {
            if capacity > max_capacity {
                self.fills.order_id.shrink_to(max_capacity);
                self.fills.symbol.shrink_to(max_capacity);
                self.fills.side.shrink_to(max_capacity);
                self.fills.qty.shrink_to(max_capacity);
                self.fills.price.shrink_to(max_capacity);
                self.fills.fee.shrink_to(max_capacity);
                self.events.kind.shrink_to(max_capacity);
                self.events.status.shrink_to(max_capacity);
                self.events.order_id.shrink_to(max_capacity);
                self.events.target_id.shrink_to(max_capacity);
                self.events.symbol.shrink_to(max_capacity);
                self.events.reject_code.shrink_to(max_capacity);
                self.active_orders.order_id.shrink_to(max_capacity);
                self.active_orders.symbol.shrink_to(max_capacity);
                self.active_orders.side.shrink_to(max_capacity);
                self.active_orders.order_type.shrink_to(max_capacity);
                self.active_orders.qty.shrink_to(max_capacity);
                self.active_orders.price.shrink_to(max_capacity);
                self.active_orders.trigger.shrink_to(max_capacity);
                self.active_orders.tif.shrink_to(max_capacity);
                self.active_orders.flags.shrink_to(max_capacity);
                self.active_orders.parent_id.shrink_to(max_capacity);
                self.active_orders.group_id.shrink_to(max_capacity);
                self.active_orders.oco_id.shrink_to(max_capacity);
                self.active_orders.activation.shrink_to(max_capacity);
                self.active_orders.waiting_parent.shrink_to(max_capacity);
                break;
            }
        }
    }

    pub fn capacity_signature(&self) -> (usize, usize, usize) {
        (
            self.fills.order_id.capacity(),
            self.events.kind.capacity(),
            self.active_orders.order_id.capacity(),
        )
    }
}

pub enum DetailSink<'a> {
    CountOnly(&'a mut StepCounters),
    Collect {
        counters: &'a mut StepCounters,
        buffers: &'a mut StepBuffers,
    },
}

impl DetailSink<'_> {
    #[inline]
    pub fn event(
        &mut self,
        kind: i64,
        status: i64,
        order_id: i64,
        target_id: i64,
        symbol: i64,
        reject_code: i64,
    ) {
        match self {
            Self::CountOnly(counters) => {
                counters.event_count += 1;
                if kind == EVENT_REPLACE {
                    counters.replace_count += 1;
                }
            }
            Self::Collect { counters, buffers } => {
                counters.event_count += 1;
                if kind == EVENT_REPLACE {
                    counters.replace_count += 1;
                }
                buffers
                    .events
                    .push(kind, status, order_id, target_id, symbol, reject_code);
            }
        }
    }

    #[inline]
    #[allow(clippy::too_many_arguments)]
    pub fn fill(
        &mut self,
        order_id: i64,
        symbol: i64,
        side: i64,
        qty: f64,
        price: f64,
        fee: f64,
        reason: i64,
        ambiguity: i64,
    ) {
        match self {
            Self::CountOnly(counters) => counters.fill_count += 1,
            Self::Collect { counters, buffers } => {
                counters.fill_count += 1;
                buffers
                    .fills
                    .push(order_id, symbol, side, qty, price, fee, reason, ambiguity);
            }
        }
    }
}

#[allow(dead_code)]
#[derive(Clone)]
pub struct FullMarketData {
    pub timestamps_ns: Box<[i64]>,
    pub opens: Box<[f64]>,
    pub highs: Box<[f64]>,
    pub lows: Box<[f64]>,
    pub closes: Box<[f64]>,
    pub volumes: Box<[f64]>,
    pub funding: Box<[f64]>,
    pub funding_mask: Box<[bool]>,
    pub n_bars: usize,
    pub n_symbols: usize,
}

impl FullMarketData {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        timestamps_ns: Vec<i64>,
        opens: Vec<f64>,
        highs: Vec<f64>,
        lows: Vec<f64>,
        closes: Vec<f64>,
        volumes: Vec<f64>,
        funding: Vec<f64>,
        funding_mask: Vec<bool>,
        n_symbols: usize,
    ) -> Result<Self, String> {
        if n_symbols == 0 || timestamps_ns.is_empty() {
            return Err("full market tape must contain bars and symbols".to_owned());
        }
        let n_bars = timestamps_ns.len();
        let width = n_bars
            .checked_mul(n_symbols)
            .ok_or_else(|| "market dimensions overflow".to_owned())?;
        if opens.len() != width
            || highs.len() != width
            || lows.len() != width
            || closes.len() != width
            || volumes.len() != width
            || funding.len() != width
            || funding_mask.len() != n_bars
        {
            return Err("full market arrays have inconsistent shapes".to_owned());
        }
        Ok(Self {
            timestamps_ns: timestamps_ns.into_boxed_slice(),
            opens: opens.into_boxed_slice(),
            highs: highs.into_boxed_slice(),
            lows: lows.into_boxed_slice(),
            closes: closes.into_boxed_slice(),
            volumes: volumes.into_boxed_slice(),
            funding: funding.into_boxed_slice(),
            funding_mask: funding_mask.into_boxed_slice(),
            n_bars,
            n_symbols,
        })
    }

    /// Materialize a contiguous execution window for compatibility callers or
    /// reference comparisons. New prepared/batch paths should prefer
    /// [`FullSession::new_window`], which preserves identical local bar-zero
    /// semantics while retaining one shared immutable source tape.
    pub fn window(&self, start: usize, end: usize) -> Result<Self, String> {
        if start >= end || end > self.n_bars {
            return Err("prepared market window is outside source tape".to_owned());
        }
        let width_start = start * self.n_symbols;
        let width_end = end * self.n_symbols;
        Self::new(
            self.timestamps_ns[start..end].to_vec(),
            self.opens[width_start..width_end].to_vec(),
            self.highs[width_start..width_end].to_vec(),
            self.lows[width_start..width_end].to_vec(),
            self.closes[width_start..width_end].to_vec(),
            self.volumes[width_start..width_end].to_vec(),
            self.funding[width_start..width_end].to_vec(),
            self.funding_mask[start..end].to_vec(),
            self.n_symbols,
        )
    }

    #[inline]
    fn at(&self, array: &[f64], bar: usize, symbol: usize) -> f64 {
        array[bar * self.n_symbols + symbol]
    }
}

#[derive(Clone, Copy)]
struct OrderState {
    #[allow(dead_code)]
    command_index: usize,
    order_id: i64,
    symbol: u32,
    side: i8,
    order_type: u8,
    tif: u8,
    flags: u16,
    qty: f64,
    price: f64,
    trigger: f64,
    parent_id: i64,
    group_id: i64,
    oco_id: i64,
    activation: u8,
    expires_bar: i64,
    active: bool,
    waiting_parent: bool,
    status: i64,
    trigger_armed: bool,
    sequence: u64,
}

impl OrderState {
    #[inline]
    fn reduce_only(&self) -> bool {
        self.flags & FLAG_REDUCE_ONLY != 0
    }
}

#[derive(Clone, Default)]
pub struct FullStepResult {
    pub equity: f64,
    pub positions: Vec<f64>,
    pub fee: f64,
    pub turnover: f64,
    pub funding: f64,
    pub initial_margin: f64,
    pub maintenance_margin: f64,
    pub liquidated: bool,
    pub liquidation_bar: i64,
    pub liquidation_reason: i64,
    pub fills: Vec<Vec<f64>>,
    pub events: Vec<Vec<i64>>,
    pub active_orders: Vec<Vec<f64>>,
    pub rejected_count: i64,
    pub canceled_count: i64,
    pub fill_count: i64,
    pub event_count: i64,
    pub replace_count: i64,
}

/// Read-only account state immediately before the command phase of one bar.
///
/// A dynamic workload (for example a target-units portfolio or an atomic
/// package) must make its acceptance decision against this exact state rather
/// than against a stale Python-side account snapshot.  The projection mirrors
/// the canonical bar ordering in [`FullSession::step_with_buffers`]:
/// mark-to-close PnL, intrabar liquidation, funding, then maintenance-margin
/// liquidation.  It deliberately performs no mutation; the subsequent
/// `step_*` call remains the only execution/accounting owner.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PreCommandAccountProjectionV1 {
    pub equity: f64,
    pub funding: f64,
    pub initial_margin: f64,
    pub maintenance_margin: f64,
    pub liquidated: bool,
    pub liquidation_reason: i64,
}

/// Version vector attached to the cached post-bar account snapshot.
///
/// The full event session does not retain package reservations or mutable
/// instrument definitions between bars, but those dimensions stay explicit in
/// the contract so a future shared-account implementation cannot silently
/// reuse this cache under broader semantics.  Every mutation also invalidates
/// the cache directly; the version vector is provenance and a debug oracle,
/// not the only protection against stale data.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct DerivedAccountVersionsV1 {
    pub mark: u64,
    pub position: u64,
    pub wallet: u64,
    pub reservation: u64,
    pub fee: u64,
    pub funding: u64,
    pub risk: u64,
    pub instrument: u64,
}

/// Coherent account values after one fully committed bar.
///
/// This snapshot is deliberately post-execution only. Dynamic portfolio and
/// package admission uses [`PreCommandAccountProjectionV1`] because it must
/// value the account before command acceptance; conflating the two phases
/// would introduce a same-bar look-ahead error.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DerivedAccountSnapshotV1 {
    pub bar: usize,
    pub equity: f64,
    pub available_equity: f64,
    pub initial_margin: f64,
    pub maintenance_margin: f64,
    pub liquidated: bool,
    pub versions: DerivedAccountVersionsV1,
}

#[derive(Clone, Copy, Default)]
struct DerivedAccountCacheV1 {
    snapshot: Option<DerivedAccountSnapshotV1>,
}

/// Named invalidation dimensions keep mutation call sites auditable. A
/// positional boolean list would be both error-prone and opaque as the shared
/// account contract grows.
#[derive(Clone, Copy, Debug, Default)]
struct DerivedAccountInvalidationV1 {
    mark: bool,
    position: bool,
    wallet: bool,
    fee: bool,
    funding: bool,
    risk: bool,
    instrument: bool,
}

#[derive(Clone, Copy, Default)]
struct MarginCache {
    bar: usize,
    initial_margin: f64,
    maintenance_margin: f64,
    valid: bool,
}

pub struct FullSession {
    /// Immutable market ownership is shared by every reset/session created
    /// from one prepared PyO3 market object. Account and order state remain
    /// session-local.
    pub market: Arc<FullMarketData>,
    // A session may execute a local causal window over one immutable prepared
    // market tape. The underlying arrays stay shared through `Arc`; local bar
    // zero is still the frozen account snapshot for that window.
    market_start: usize,
    market_end: usize,
    pub contract_sizes: Box<[f64]>,
    pub leverages: Box<[f64]>,
    pub fee_rates: Box<[f64]>,
    pub initial_capital: f64,
    pub maintenance_ratio: f64,
    pub slippage: f64,
    /// Immutable execution semantics resolved before a run. Account state is
    /// deliberately not embedded in this plan.
    pub execution_model: ExecutionModelPlanV1,
    pub metric_contract: MetricContractV2,
    pub use_funding: bool,
    pub event_contract_code: i64,
    pub output_mask: u8,
    pub positions: Vec<f64>,
    pub equity: f64,
    pub liquidated: bool,
    pub liquidation_bar: i64,
    pub liquidation_reason: i64,
    // Generation-safe arena removes terminal slots immediately after their
    // final event has reached the selected sink. It replaces the legacy
    // Vec<OrderState> + hot compaction path.
    orders: OrderArena<OrderState>,
    // The Python oracle resolves target_order_id through the latest command
    // slot, including the alias created by REPLACE. Keep that indirection
    // explicit so a later CANCEL/AMEND using the replaced target has the same
    // lifecycle result without changing insertion priority.
    id_to_handle: HashMap<i64, OrderHandle>,
    lifecycle_indexes: LifecycleIndexes,
    next_order_sequence: u64,
    matching_candidates: Vec<OrderHandle>,
    /// Reused per-bar scratch; no market-volume allocation occurs in the
    /// matching loop.
    bar_volumes: Vec<f64>,
    liquidity_ledger: LiquidityLedgerV1,
    step_buffers: StepBuffers,
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
    pub compaction_count: u64,
    pub terminal_orders_removed: u64,
}

impl FullSession {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        market: Arc<FullMarketData>,
        contract_sizes: Vec<f64>,
        leverages: Vec<f64>,
        fee_rates: Vec<f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage: f64,
        use_funding: bool,
    ) -> Result<Self, String> {
        let market_end = market.n_bars;
        Self::new_window(
            market,
            0,
            market_end,
            contract_sizes,
            leverages,
            fee_rates,
            initial_capital,
            maintenance_ratio,
            slippage,
            use_funding,
        )
    }

    /// Create one stateful session over `market_start..market_end` without
    /// copying OHLCV/funding arrays. The execution clock is local to the
    /// window, so bar zero retains the same frozen-snapshot semantics as a
    /// standalone market tape.
    #[allow(clippy::too_many_arguments)]
    pub fn new_window(
        market: Arc<FullMarketData>,
        market_start: usize,
        market_end: usize,
        contract_sizes: Vec<f64>,
        leverages: Vec<f64>,
        fee_rates: Vec<f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage: f64,
        use_funding: bool,
    ) -> Result<Self, String> {
        let n_symbols = market.n_symbols;
        if market_start >= market_end
            || market_end > market.n_bars
            || contract_sizes.len() != n_symbols
            || leverages.len() != n_symbols
            || fee_rates.len() != n_symbols
            || initial_capital <= 0.0
            || maintenance_ratio < 0.0
            || slippage < 0.0
            || contract_sizes.iter().any(|v| *v <= 0.0)
            || leverages.iter().any(|v| *v <= 0.0)
            || fee_rates.iter().any(|v| *v < 0.0)
        {
            return Err("invalid full-contract account or execution parameters".to_owned());
        }
        Ok(Self {
            market,
            market_start,
            market_end,
            contract_sizes: contract_sizes.into_boxed_slice(),
            leverages: leverages.into_boxed_slice(),
            fee_rates: fee_rates.into_boxed_slice(),
            initial_capital,
            maintenance_ratio,
            slippage,
            execution_model: ExecutionModelPlanV1::legacy(slippage)?,
            metric_contract: MetricContractV2::default(),
            use_funding,
            event_contract_code: CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE,
            output_mask: OUTPUT_ALL,
            positions: vec![0.0; n_symbols],
            equity: initial_capital,
            liquidated: false,
            liquidation_bar: -1,
            liquidation_reason: LIQ_NONE,
            orders: OrderArena::new(DEFAULT_MAX_LIVE_ORDERS, DEFAULT_MAX_TOTAL_ORDERS),
            id_to_handle: HashMap::new(),
            lifecycle_indexes: LifecycleIndexes::with_symbols(n_symbols),
            next_order_sequence: 0,
            matching_candidates: Vec::new(),
            bar_volumes: vec![0.0; n_symbols],
            liquidity_ledger: LiquidityLedgerV1::unlimited(n_symbols),
            step_buffers: StepBuffers::default(),
            margin_cache: MarginCache::default(),
            derived_account_cache: DerivedAccountCacheV1::default(),
            derived_account_versions: DerivedAccountVersionsV1::default(),
            derived_account_cache_hits: 0,
            derived_account_recomputes: 0,
            session_reset_count: 0,
            margin_recompute_count: 0,
            expiry_scan_count: 0,
            matching_scan_count: 0,
            relationship_scan_count: 0,
            last_bar: None,
            compaction_count: 0,
            terminal_orders_removed: 0,
        })
    }

    /// Number of local bars visible to this session. A windowed session does
    /// not expose or execute bars outside this range.
    #[must_use]
    pub const fn n_bars(&self) -> usize {
        self.market_end - self.market_start
    }

    /// Immutable source-tape range used by this session. This is provenance,
    /// not a mutable cursor or account state.
    #[must_use]
    pub const fn market_range(&self) -> (usize, usize) {
        (self.market_start, self.market_end)
    }

    pub fn reset(&mut self) {
        self.positions.fill(0.0);
        self.equity = self.initial_capital;
        self.liquidated = false;
        self.liquidation_bar = -1;
        self.liquidation_reason = LIQ_NONE;
        self.orders.clear();
        self.id_to_handle.clear();
        self.lifecycle_indexes.clear();
        self.next_order_sequence = 0;
        self.matching_candidates.clear();
        self.bar_volumes.fill(0.0);
        self.liquidity_ledger.reset_unlimited();
        self.step_buffers.clear();
        self.margin_cache = MarginCache::default();
        self.bump_derived_versions(DerivedAccountInvalidationV1 {
            mark: true,
            position: true,
            wallet: true,
            fee: true,
            funding: true,
            risk: true,
            instrument: true,
        });
        self.invalidate_derived_account_cache();
        self.derived_account_cache_hits = 0;
        self.derived_account_recomputes = 0;
        self.margin_recompute_count = 0;
        self.expiry_scan_count = 0;
        self.matching_scan_count = 0;
        self.relationship_scan_count = 0;
        self.last_bar = None;
        self.compaction_count = 0;
        self.terminal_orders_removed = 0;
        self.session_reset_count = self.session_reset_count.saturating_add(1);
    }

    /// Start one fresh account at an absolute bar of the immutable market.
    ///
    /// This is intentionally narrower than a continuation seek: the account
    /// must still be pristine, there can be no active order or prior account
    /// state, and the next step remains consecutive on the original prepared
    /// market clock. It lets a reset-flat WFO fold retain absolute timestamps
    /// and callback coordinates without copying or replaying the tape prefix
    /// whose zero-position accounting cannot affect the fresh account.
    pub fn begin_fresh_at(&mut self, bar: usize) -> Result<(), String> {
        if bar >= self.n_bars() {
            return Err("fresh session start is outside the full prepared market tape".to_owned());
        }
        if self.last_bar.is_some()
            || self.liquidated
            || self.orders_len() != 0
            || self.positions.iter().any(|position| *position != 0.0)
            || self.equity != self.initial_capital
        {
            return Err(
                "fresh session start requires a pristine account and no prior execution".to_owned(),
            );
        }
        if bar > 0 {
            self.last_bar = Some(bar - 1);
        }
        Ok(())
    }

    /// Return the next canonical bar accepted by the stateful session.
    ///
    /// Compatibility adapters may retain a caller-visible continuation cursor,
    /// but the execution clock itself remains owned by this session. Keeping
    /// the accessor here prevents a second lifecycle implementation from
    /// reconstructing the cursor outside the engine.
    #[inline]
    pub fn next_bar(&self) -> usize {
        self.last_bar.map(|bar| bar + 1).unwrap_or(0)
    }

    /// Materialize only the terminal active-order artifact requested by a
    /// public standard/audit report. This stays outside the per-bar hot path.
    pub fn terminal_active_order_rows(&self) -> Vec<Vec<f64>> {
        let mut buffer = ActiveOrderBuffer::default();
        for handle in self.lifecycle_indexes.live_priority_handles() {
            if let Some(order) = self.orders.get(handle) {
                buffer.push(order);
            }
        }
        buffer.rows()
    }

    pub fn set_event_contract(&mut self, contract_code: i64) -> Result<(), String> {
        if contract_code != CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE
            && contract_code != CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN
        {
            return Err(format!(
                "unsupported native-event contract code {contract_code}"
            ));
        }
        if self.last_bar.is_some() {
            return Err("event contract cannot change after execution has started".to_owned());
        }
        self.event_contract_code = contract_code;
        self.bump_derived_versions(DerivedAccountInvalidationV1 {
            risk: true,
            ..DerivedAccountInvalidationV1::default()
        });
        self.invalidate_derived_account_cache();
        Ok(())
    }

    /// Replace the immutable execution plan before a scenario starts. This is
    /// intentionally rejected mid-run so one account trace can never mix
    /// cost/liquidity semantics across bars.
    pub fn set_execution_model(&mut self, model: ExecutionModelPlanV1) -> Result<(), String> {
        if self.last_bar.is_some() {
            return Err("execution model cannot change after execution has started".to_owned());
        }
        self.execution_model = model;
        self.bump_derived_versions(DerivedAccountInvalidationV1 {
            risk: true,
            instrument: true,
            ..DerivedAccountInvalidationV1::default()
        });
        self.invalidate_derived_account_cache();
        Ok(())
    }

    /// Freeze the standard metric policy before execution. Report formatting
    /// remains outside the session; this only controls native online scalars.
    pub fn set_metric_contract(&mut self, contract: MetricContractV2) -> Result<(), String> {
        if self.last_bar.is_some() {
            return Err("metric contract cannot change after execution has started".to_owned());
        }
        // Reconstruct through the validated constructor so literal callers
        // cannot bypass the numeric policy checks.
        self.metric_contract = MetricContractV2::new(
            contract.return_frequency,
            contract.annualization_factor,
            contract.risk_free_rate,
            contract.variance_ddof,
            contract.zero_variance_policy,
            contract.short_run_policy,
            contract.trade_count_definition,
        )?;
        Ok(())
    }

    pub fn orders_len(&self) -> usize {
        self.orders.len()
    }

    pub fn orders_capacity(&self) -> usize {
        self.orders.slot_capacity()
    }

    #[must_use]
    pub fn order_arena_retired_slots(&self) -> usize {
        self.orders.stats().retired
    }

    #[must_use]
    pub fn matching_candidate_capacity(&self) -> usize {
        self.matching_candidates.capacity()
    }

    pub fn release_step_buffer_capacity(&mut self, max_capacity: usize) {
        self.step_buffers.release_excess_capacity(max_capacity);
    }

    /// Release capacity held only by resettable per-scenario scratch.
    ///
    /// This operation is intentionally narrower than a runner rebuild: it
    /// never changes the immutable market template or account semantics. A
    /// caller may use it after a reset/close to shed a high-water matching
    /// candidate vector; order-arena storage remains owned by the explicit
    /// full-rebuild path because its handle generations are lifecycle state.
    pub fn release_resettable_scratch_capacity(&mut self, max_capacity: usize) {
        self.step_buffers.release_excess_capacity(max_capacity);
        if self.matching_candidates.capacity() > max_capacity {
            self.matching_candidates.shrink_to(max_capacity);
        }
    }

    pub fn step_buffer_capacities(&self) -> (usize, usize, usize) {
        self.step_buffers.capacity_signature()
    }

    pub fn engine_scan_counters(&self) -> (u64, u64, u64) {
        (
            self.expiry_scan_count,
            self.matching_scan_count,
            self.relationship_scan_count,
        )
    }

    pub fn margin_recompute_count(&self) -> u64 {
        self.margin_recompute_count
    }

    #[must_use]
    pub const fn session_reset_count(&self) -> u64 {
        self.session_reset_count
    }

    #[must_use]
    pub const fn derived_account_cache_hits(&self) -> u64 {
        self.derived_account_cache_hits
    }

    #[must_use]
    pub const fn derived_account_recomputes(&self) -> u64 {
        self.derived_account_recomputes
    }

    #[must_use]
    pub const fn derived_account_versions(&self) -> DerivedAccountVersionsV1 {
        self.derived_account_versions
    }

    #[inline]
    fn close(&self, bar: usize, symbol: usize) -> f64 {
        self.market
            .at(&self.market.closes, self.market_start + bar, symbol)
    }

    #[inline]
    fn open(&self, bar: usize, symbol: usize) -> f64 {
        self.market
            .at(&self.market.opens, self.market_start + bar, symbol)
    }

    #[inline]
    fn high(&self, bar: usize, symbol: usize) -> f64 {
        self.market
            .at(&self.market.highs, self.market_start + bar, symbol)
    }

    #[inline]
    fn low(&self, bar: usize, symbol: usize) -> f64 {
        self.market
            .at(&self.market.lows, self.market_start + bar, symbol)
    }

    #[inline]
    fn volume(&self, bar: usize, symbol: usize) -> f64 {
        self.market
            .at(&self.market.volumes, self.market_start + bar, symbol)
    }

    #[inline]
    fn timestamp_ns(&self, bar: usize) -> i64 {
        self.market.timestamps_ns[self.market_start + bar]
    }

    fn gross_exposure(&self, bar: usize, equity: f64) -> f64 {
        if equity <= 0.0 {
            return 0.0;
        }
        let mut gross_notional = 0.0;
        for symbol in 0..self.market.n_symbols {
            gross_notional += self.positions[symbol].abs()
                * self.close(bar, symbol)
                * self.contract_sizes[symbol];
        }
        gross_notional / equity
    }

    #[inline]
    fn funding(&self, bar: usize, symbol: usize) -> f64 {
        self.market
            .at(&self.market.funding, self.market_start + bar, symbol)
    }

    #[inline]
    fn has_funding_event(&self, bar: usize) -> bool {
        self.market.funding_mask[self.market_start + bar]
    }

    /// Return one close used by the canonical local-bar clock.
    ///
    /// This intentionally exposes valuation only.  Dynamic workload planners
    /// cannot mutate the market or bypass the session's fill logic through
    /// this accessor.
    pub fn close_price_at(&self, bar: usize, symbol: usize) -> Result<f64, String> {
        if bar >= self.n_bars() || symbol >= self.market.n_symbols {
            return Err("native execution close projection is outside prepared market".to_owned());
        }
        Ok(self.close(bar, symbol))
    }

    /// Return one declared OHLCV field from the immutable market tape.
    ///
    /// Reactive co-runtimes use this read-only projection while the session
    /// keeps exclusive ownership of execution/accounting state.  The numeric
    /// field codes intentionally mirror the Python strategy requirements:
    /// `0=open`, `1=high`, `2=low`, `3=close`, `4=volume`.
    pub fn market_value_at(&self, field: u8, bar: usize, symbol: usize) -> Result<f64, String> {
        if bar >= self.n_bars() || symbol >= self.market.n_symbols {
            return Err("native execution market projection is outside prepared market".to_owned());
        }
        match field {
            0 => Ok(self.open(bar, symbol)),
            1 => Ok(self.high(bar, symbol)),
            2 => Ok(self.low(bar, symbol)),
            3 => Ok(self.close(bar, symbol)),
            4 => Ok(self.volume(bar, symbol)),
            _ => Err("native execution market projection field is unsupported".to_owned()),
        }
    }

    /// Return the canonical local-bar timestamp for a reactive projection.
    pub fn timestamp_ns_at(&self, bar: usize) -> Result<i64, String> {
        if bar >= self.n_bars() {
            return Err(
                "native execution timestamp projection is outside prepared market".to_owned(),
            );
        }
        Ok(self.timestamp_ns(bar))
    }

    /// Return whether the canonical local bar carries a funding boundary.
    ///
    /// Reactive sparse scheduling uses the same immutable funding mask as the
    /// accounting kernel.  A zero funding rate can still be an exchange
    /// funding event, so callers must not infer this from the cash amount.
    pub fn has_funding_event_at(&self, bar: usize) -> Result<bool, String> {
        if bar >= self.n_bars() {
            return Err(
                "native execution funding projection is outside prepared market".to_owned(),
            );
        }
        Ok(self.has_funding_event(bar))
    }

    /// Resolve an exact timestamp on this session's local execution window.
    ///
    /// There is deliberately no nearest-bar fallback: a sparse wake timestamp
    /// that is not a bar boundary must request a finer market tape instead.
    pub fn bar_for_timestamp_ns(&self, timestamp_ns: i64) -> Result<usize, String> {
        let start = self.market_start;
        let end = self.market_end;
        let values = &self.market.timestamps_ns[start..end];
        values.binary_search(&timestamp_ns).map_err(|_| {
            "reactive wake timestamp must match an exact prepared market bar".to_owned()
        })
    }

    /// Project the account immediately before commands for `bar` without
    /// changing position, cash, order, cursor, or margin-cache state.
    ///
    /// The caller must invoke this only from a consecutive dynamic runner. A
    /// separate caller cannot use the projection to skip the event clock.
    pub fn project_pre_command_account_v1(
        &self,
        bar: usize,
    ) -> Result<PreCommandAccountProjectionV1, String> {
        if bar >= self.n_bars() {
            return Err("bar_index is outside the full prepared market tape".to_owned());
        }
        if self
            .last_bar
            .map(|last| bar != last + 1)
            .unwrap_or(bar != 0)
        {
            return Err(
                "pre-command projection must follow the native consecutive bar clock".to_owned(),
            );
        }
        if self.liquidated {
            return Ok(PreCommandAccountProjectionV1 {
                equity: 0.0,
                funding: 0.0,
                initial_margin: 0.0,
                maintenance_margin: 0.0,
                liquidated: true,
                liquidation_reason: self.liquidation_reason,
            });
        }

        let mut equity = self.equity;
        if bar > 0 {
            for symbol in 0..self.market.n_symbols {
                equity += self.positions[symbol]
                    * (self.close(bar, symbol) - self.close(bar - 1, symbol))
                    * self.contract_sizes[symbol];
            }
        }
        let mut worst_equity = equity;
        let mut worst_maintenance = 0.0;
        for symbol in 0..self.market.n_symbols {
            let position = self.positions[symbol];
            if position == 0.0 {
                continue;
            }
            let worst_price = if position > 0.0 {
                self.low(bar, symbol)
            } else {
                self.high(bar, symbol)
            };
            worst_equity +=
                position * (worst_price - self.close(bar, symbol)) * self.contract_sizes[symbol];
            worst_maintenance +=
                position.abs() * worst_price * self.contract_sizes[symbol] * self.maintenance_ratio;
        }
        if worst_maintenance > 0.0 && worst_equity <= worst_maintenance {
            return Ok(PreCommandAccountProjectionV1 {
                equity: 0.0,
                funding: 0.0,
                initial_margin: 0.0,
                maintenance_margin: 0.0,
                liquidated: true,
                liquidation_reason: LIQ_INTRABAR,
            });
        }

        let mut funding_total = 0.0;
        if self.use_funding && self.has_funding_event(bar) {
            for symbol in 0..self.market.n_symbols {
                let cost = self.positions[symbol]
                    * self.close(bar, symbol)
                    * self.contract_sizes[symbol]
                    * self.funding(bar, symbol);
                equity -= cost;
                funding_total += cost;
            }
        }
        let (initial_margin, maintenance_margin) = self.compute_close_margin(bar);
        if maintenance_margin > 0.0 && equity <= maintenance_margin {
            return Ok(PreCommandAccountProjectionV1 {
                equity: 0.0,
                funding: funding_total,
                initial_margin: 0.0,
                maintenance_margin: 0.0,
                liquidated: true,
                liquidation_reason: LIQ_AFTER_FUNDING,
            });
        }
        Ok(PreCommandAccountProjectionV1 {
            equity,
            funding: funding_total,
            initial_margin,
            maintenance_margin,
            liquidated: false,
            liquidation_reason: LIQ_NONE,
        })
    }

    /// Return the account valuation after a bar has completed all lifecycle,
    /// funding, fill, fee, and liquidation work.
    ///
    /// The cache is valid only for the exact committed bar and version vector.
    /// Reads never mutate positions, wallet, orders, or metric state. The
    /// separate `recompute_post_execution_account_snapshot` method is kept as
    /// a parity oracle for tests and debug certification.
    pub fn post_execution_account_snapshot(
        &mut self,
        bar: usize,
    ) -> Result<DerivedAccountSnapshotV1, String> {
        if self.last_bar != Some(bar) {
            return Err(
                "post-execution account snapshot requires the completed current bar".to_owned(),
            );
        }
        if let Some(snapshot) = self.derived_account_cache.snapshot
            && snapshot.bar == bar
            && snapshot.versions == self.derived_account_versions
        {
            self.derived_account_cache_hits = self.derived_account_cache_hits.saturating_add(1);
            return Ok(snapshot);
        }
        let (equity, initial_margin, maintenance_margin) = if self.liquidated {
            (0.0, 0.0, 0.0)
        } else {
            let (initial_margin, maintenance_margin) = self.close_margin(bar);
            (self.equity, initial_margin, maintenance_margin)
        };
        let snapshot = DerivedAccountSnapshotV1 {
            bar,
            equity,
            available_equity: equity - initial_margin,
            initial_margin,
            maintenance_margin,
            liquidated: self.liquidated,
            versions: self.derived_account_versions,
        };
        self.derived_account_cache.snapshot = Some(snapshot);
        self.derived_account_recomputes = self.derived_account_recomputes.saturating_add(1);
        Ok(snapshot)
    }

    /// Exact non-cached account valuation for debug and differential tests.
    /// It intentionally does not use incremental assumptions for future
    /// nonlinear margin/offset models.
    pub fn recompute_post_execution_account_snapshot(
        &self,
        bar: usize,
    ) -> Result<DerivedAccountSnapshotV1, String> {
        if self.last_bar != Some(bar) {
            return Err(
                "post-execution account recomputation requires the completed current bar"
                    .to_owned(),
            );
        }
        let (equity, initial_margin, maintenance_margin) = if self.liquidated {
            (0.0, 0.0, 0.0)
        } else {
            let (initial_margin, maintenance_margin) = self.compute_close_margin(bar);
            (self.equity, initial_margin, maintenance_margin)
        };
        Ok(DerivedAccountSnapshotV1 {
            bar,
            equity,
            available_equity: equity - initial_margin,
            initial_margin,
            maintenance_margin,
            liquidated: self.liquidated,
            versions: self.derived_account_versions,
        })
    }

    #[inline]
    fn invalidate_derived_account_cache(&mut self) {
        self.derived_account_cache.snapshot = None;
    }

    #[inline]
    fn bump_derived_versions(&mut self, invalidation: DerivedAccountInvalidationV1) {
        if invalidation.mark {
            self.derived_account_versions.mark = self.derived_account_versions.mark.wrapping_add(1);
        }
        if invalidation.position {
            self.derived_account_versions.position =
                self.derived_account_versions.position.wrapping_add(1);
        }
        if invalidation.wallet {
            self.derived_account_versions.wallet =
                self.derived_account_versions.wallet.wrapping_add(1);
        }
        if invalidation.fee {
            self.derived_account_versions.fee = self.derived_account_versions.fee.wrapping_add(1);
        }
        if invalidation.funding {
            self.derived_account_versions.funding =
                self.derived_account_versions.funding.wrapping_add(1);
        }
        if invalidation.risk {
            self.derived_account_versions.risk = self.derived_account_versions.risk.wrapping_add(1);
        }
        if invalidation.instrument {
            self.derived_account_versions.instrument =
                self.derived_account_versions.instrument.wrapping_add(1);
        }
    }

    fn compute_close_margin(&self, bar: usize) -> (f64, f64) {
        let mut initial = 0.0;
        let mut maintenance = 0.0;
        for symbol in 0..self.market.n_symbols {
            let notional = self.positions[symbol].abs()
                * self.close(bar, symbol)
                * self.contract_sizes[symbol];
            initial += notional / self.leverages[symbol];
            maintenance += notional * self.maintenance_ratio;
        }
        (initial, maintenance)
    }

    /// Return margin at the bar-close valuation without scanning symbols more
    /// than once per bar. A fill updates the cached symbol contribution in
    /// O(1); liquidation invalidates the cache because all positions reset.
    fn close_margin(&mut self, bar: usize) -> (f64, f64) {
        if self.margin_cache.valid && self.margin_cache.bar == bar {
            return (
                self.margin_cache.initial_margin,
                self.margin_cache.maintenance_margin,
            );
        }
        let (initial_margin, maintenance_margin) = self.compute_close_margin(bar);
        self.margin_cache = MarginCache {
            bar,
            initial_margin,
            maintenance_margin,
            valid: true,
        };
        self.margin_recompute_count += 1;
        (initial_margin, maintenance_margin)
    }

    fn update_margin_cache_after_fill(
        &mut self,
        bar: usize,
        symbol: usize,
        old_position: f64,
        new_position: f64,
    ) {
        if !(self.margin_cache.valid && self.margin_cache.bar == bar) {
            let (initial_margin, maintenance_margin) = self.compute_close_margin(bar);
            self.margin_cache = MarginCache {
                bar,
                initial_margin,
                maintenance_margin,
                valid: true,
            };
            self.margin_recompute_count += 1;
            return;
        }
        let close = self.close(bar, symbol);
        let contract_size = self.contract_sizes[symbol];
        let leverage = self.leverages[symbol];
        let old_notional = old_position.abs() * close * contract_size;
        let new_notional = new_position.abs() * close * contract_size;
        self.margin_cache.initial_margin += (new_notional - old_notional) / leverage;
        self.margin_cache.maintenance_margin +=
            (new_notional - old_notional) * self.maintenance_ratio;
    }

    fn intrabar_liquidated(&self, bar: usize) -> bool {
        let mut worst_equity = self.equity;
        let mut worst_maintenance = 0.0;
        for symbol in 0..self.market.n_symbols {
            let position = self.positions[symbol];
            if position == 0.0 {
                continue;
            }
            let worst_price = if position > 0.0 {
                self.low(bar, symbol)
            } else {
                self.high(bar, symbol)
            };
            worst_equity +=
                position * (worst_price - self.close(bar, symbol)) * self.contract_sizes[symbol];
            worst_maintenance +=
                position.abs() * worst_price * self.contract_sizes[symbol] * self.maintenance_ratio;
        }
        worst_maintenance > 0.0 && worst_equity <= worst_maintenance
    }

    fn liquidate(&mut self, bar: usize, reason: i64) {
        self.liquidated = true;
        self.liquidation_bar = bar as i64;
        self.liquidation_reason = reason;
        self.equity = 0.0;
        self.positions.fill(0.0);
        self.margin_cache.valid = false;
        self.bump_derived_versions(DerivedAccountInvalidationV1 {
            position: true,
            wallet: true,
            risk: true,
            ..DerivedAccountInvalidationV1::default()
        });
        self.invalidate_derived_account_cache();
    }

    fn find_pending(&self, order_id: i64) -> Option<OrderHandle> {
        let handle = *self.id_to_handle.get(&order_id)?;
        let order = self.orders.get(handle)?;
        if (order.active || order.waiting_parent) && order.status == STATUS_PENDING {
            Some(handle)
        } else {
            None
        }
    }

    fn order_index_state(order: &OrderState) -> IndexOrderState {
        IndexOrderState {
            symbol: SymbolId(order.symbol),
            active: order.active && order.status == STATUS_PENDING,
            waiting_parent: order.waiting_parent && order.status == STATUS_PENDING,
            sequence: order.sequence,
            parent_id: ExternalOrderId(order.parent_id),
            oco_id: order.oco_id,
            expire_bar: (order.expires_bar >= 0).then_some(order.expires_bar as u32),
        }
    }

    fn insert_order(
        &mut self,
        mut order: OrderState,
        aliases: &[i64],
    ) -> Result<OrderHandle, String> {
        let sequence = self.next_order_sequence;
        self.next_order_sequence = self
            .next_order_sequence
            .checked_add(1)
            .ok_or_else(|| "native order sequence exhausted; rebuild the session".to_owned())?;
        order.sequence = sequence;
        let handle = self
            .orders
            .insert(order)
            .map_err(|error| error.to_string())?;
        let state = self
            .orders
            .get(handle)
            .map(Self::order_index_state)
            .ok_or_else(|| "arena lost freshly inserted order".to_owned())?;
        self.lifecycle_indexes.insert(handle, state);
        for &alias in aliases {
            if alias >= 0 {
                self.id_to_handle.insert(alias, handle);
            }
        }
        Ok(handle)
    }

    /// Terminal records are emitted before this function. Releasing a slot is
    /// O(1), updates every lifecycle index, and invalidates stale handles by
    /// incrementing its generation. There is no hot compaction pass.
    fn release_order(&mut self, handle: OrderHandle) -> Option<OrderState> {
        let order = self.orders.remove(handle).ok()?;
        self.lifecycle_indexes.remove(handle);
        self.id_to_handle.retain(|_, mapped| *mapped != handle);
        self.terminal_orders_removed += 1;
        Some(order)
    }

    /// Test/debug-only invariant validator. It is intentionally absent from
    /// the hot path but is run by the pure Rust arena/index tests.
    pub fn validate_lifecycle_indexes(&self) -> Result<(), String> {
        self.lifecycle_indexes
            .validate(|handle| self.orders.get(handle).map(Self::order_index_state))
            .map_err(str::to_owned)?;
        for handle in self.id_to_handle.values() {
            if !self.orders.contains(*handle) {
                return Err("external order ID resolves to a stale handle".to_owned());
            }
        }
        Ok(())
    }

    fn valid_order(code: &[i64], values: &[f64]) -> bool {
        let side = code[2];
        let order_type = code[3];
        let qty = values[0];
        if InternalSide::try_from(side).is_err()
            || InternalOrderType::try_from(order_type).is_err()
            || InternalTimeInForce::try_from(code[4]).is_err()
            || qty <= 0.0
        {
            return false;
        }
        match order_type {
            ORDER_MARKET => true,
            ORDER_LIMIT => values[1] > 0.0,
            ORDER_STOP_MARKET => values[2] > 0.0,
            ORDER_STOP_LIMIT => values[1] > 0.0 && values[2] > 0.0,
            _ => false,
        }
    }

    fn build_order(code: &[i64], values: &[f64], expires_bar: i64) -> OrderState {
        let active = code[11] == ACTIVATION_IMMEDIATE;
        OrderState {
            command_index: code[12].max(0) as usize,
            order_id: code[6],
            symbol: code[1] as u32,
            side: code[2] as i8,
            order_type: code[3] as u8,
            tif: code[4] as u8,
            flags: if code[5] != 0 { FLAG_REDUCE_ONLY } else { 0 },
            qty: values[0],
            price: values[1],
            trigger: values[2],
            parent_id: code[8],
            group_id: code[9],
            oco_id: code[10],
            activation: code[11] as u8,
            expires_bar,
            active,
            waiting_parent: !active,
            status: STATUS_PENDING,
            trigger_armed: false,
            sequence: 0,
        }
    }

    fn add_event(
        sink: &mut DetailSink<'_>,
        kind: i64,
        status: i64,
        order: i64,
        target: i64,
        symbol: i64,
    ) {
        sink.event(kind, status, order, target, symbol, 0);
    }

    fn add_event_with_reject(
        sink: &mut DetailSink<'_>,
        kind: i64,
        status: i64,
        order: i64,
        target: i64,
        symbol: i64,
        reject_code: i64,
    ) {
        sink.event(kind, status, order, target, symbol, reject_code);
    }

    /// Production bar-touch dispatch. The common execution plan owns this
    /// decision; account/lifecycle code only consumes its typed outcome.
    fn fill_decision(&self, order: &OrderState, bar: usize) -> FillDecisionV1 {
        let clock = ExecutionClockStateV1::new(self.event_contract_code)
            .expect("FullSession validates the event contract before execution");
        self.execution_model.evaluate_order(
            OrderTouchViewV1 {
                side: order.side,
                order_type: i64::from(order.order_type),
                limit_price: order.price,
                stop_price: order.trigger,
                trigger_armed: order.trigger_armed,
            },
            MarketBarViewV1 {
                open: self.open(bar, order.symbol as usize),
                high: self.high(bar, order.symbol as usize),
                low: self.low(bar, order.symbol as usize),
                close: self.close(bar, order.symbol as usize),
                volume: self.volume(bar, order.symbol as usize),
            },
            clock,
        )
    }

    /// Frozen pre-Phase-60 implementation retained as a test-only parity
    /// oracle while `ExecutionModelPlanV1` becomes the production authority.
    #[cfg(test)]
    fn legacy_fill_decision(&self, order: &OrderState, bar: usize) -> FillDecision {
        let open = self.open(bar, order.symbol as usize);
        let high = self.high(bar, order.symbol as usize);
        let low = self.low(bar, order.symbol as usize);
        let close = self.close(bar, order.symbol as usize);
        let side = order.side as i64;
        let slipped = |price: f64| {
            price
                * if side == SIDE_BUY {
                    1.0 + self.slippage
                } else {
                    1.0 - self.slippage
                }
        };
        if self.event_contract_code == CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE {
            return match order.order_type as i64 {
                ORDER_MARKET => FillDecision::fill(
                    slipped(close),
                    order.trigger_armed,
                    FILL_REASON_NEXT_BAR_CLOSE,
                    FILL_AMBIGUITY_NONE,
                ),
                ORDER_LIMIT if side == SIDE_BUY && low <= order.price => FillDecision::fill(
                    order.price,
                    order.trigger_armed,
                    FILL_REASON_LIMIT_TRIGGER,
                    FILL_AMBIGUITY_NONE,
                ),
                ORDER_LIMIT if side == SIDE_SELL && high >= order.price => FillDecision::fill(
                    order.price,
                    order.trigger_armed,
                    FILL_REASON_LIMIT_TRIGGER,
                    FILL_AMBIGUITY_NONE,
                ),
                ORDER_STOP_MARKET if side == SIDE_BUY && high >= order.trigger => {
                    FillDecision::fill(
                        slipped(order.trigger),
                        true,
                        FILL_REASON_STOP_TRIGGER_LEGACY,
                        FILL_AMBIGUITY_NONE,
                    )
                }
                ORDER_STOP_MARKET if side == SIDE_SELL && low <= order.trigger => {
                    FillDecision::fill(
                        slipped(order.trigger),
                        true,
                        FILL_REASON_STOP_TRIGGER_LEGACY,
                        FILL_AMBIGUITY_NONE,
                    )
                }
                ORDER_STOP_LIMIT
                    if side == SIDE_BUY && high >= order.trigger && low <= order.price =>
                {
                    FillDecision::fill(
                        order.price,
                        true,
                        FILL_REASON_STOP_LIMIT_LEGACY,
                        FILL_AMBIGUITY_UNORDERED_OHLC_RANGE,
                    )
                }
                ORDER_STOP_LIMIT
                    if side == SIDE_SELL && low <= order.trigger && high >= order.price =>
                {
                    FillDecision::fill(
                        order.price,
                        true,
                        FILL_REASON_STOP_LIMIT_LEGACY,
                        FILL_AMBIGUITY_UNORDERED_OHLC_RANGE,
                    )
                }
                _ => FillDecision::no_fill(
                    order.trigger_armed,
                    FILL_REASON_NONE,
                    FILL_AMBIGUITY_NONE,
                ),
            };
        }

        match order.order_type as i64 {
            ORDER_MARKET => FillDecision::fill(
                slipped(open),
                order.trigger_armed,
                FILL_REASON_NEXT_OPEN,
                FILL_AMBIGUITY_NONE,
            ),
            ORDER_LIMIT => {
                let favorable_gap = if side == SIDE_BUY {
                    open <= order.price
                } else {
                    open >= order.price
                };
                let touched = if side == SIDE_BUY {
                    low <= order.price
                } else {
                    high >= order.price
                };
                if favorable_gap {
                    FillDecision::fill(
                        open,
                        order.trigger_armed,
                        FILL_REASON_LIMIT_OPEN_IMPROVEMENT,
                        FILL_AMBIGUITY_NONE,
                    )
                } else if touched {
                    FillDecision::fill(
                        order.price,
                        order.trigger_armed,
                        FILL_REASON_LIMIT_TRIGGER,
                        FILL_AMBIGUITY_NONE,
                    )
                } else {
                    FillDecision::no_fill(
                        order.trigger_armed,
                        FILL_REASON_NONE,
                        FILL_AMBIGUITY_NONE,
                    )
                }
            }
            ORDER_STOP_MARKET => {
                let gap_trigger = if side == SIDE_BUY {
                    open >= order.trigger
                } else {
                    open <= order.trigger
                };
                let trigger_touched = if side == SIDE_BUY {
                    high >= order.trigger
                } else {
                    low <= order.trigger
                };
                if gap_trigger {
                    FillDecision::fill(
                        slipped(open),
                        true,
                        FILL_REASON_STOP_OPEN_WORSE,
                        FILL_AMBIGUITY_NONE,
                    )
                } else if trigger_touched {
                    FillDecision::fill(
                        slipped(order.trigger),
                        true,
                        FILL_REASON_STOP_TRIGGER,
                        FILL_AMBIGUITY_NONE,
                    )
                } else {
                    FillDecision::no_fill(false, FILL_REASON_NONE, FILL_AMBIGUITY_NONE)
                }
            }
            ORDER_STOP_LIMIT if order.trigger_armed => {
                let favorable_gap = if side == SIDE_BUY {
                    open <= order.price
                } else {
                    open >= order.price
                };
                let limit_touched = if side == SIDE_BUY {
                    low <= order.price
                } else {
                    high >= order.price
                };
                if favorable_gap {
                    FillDecision::fill(
                        open,
                        true,
                        FILL_REASON_STOP_LIMIT_OPEN_IMPROVEMENT,
                        FILL_AMBIGUITY_NONE,
                    )
                } else if limit_touched {
                    FillDecision::fill(
                        order.price,
                        true,
                        FILL_REASON_LIMIT_TRIGGER,
                        FILL_AMBIGUITY_NONE,
                    )
                } else {
                    FillDecision::no_fill(
                        true,
                        FILL_REASON_TRIGGERED_LIMIT_NOT_TOUCHED,
                        FILL_AMBIGUITY_NONE,
                    )
                }
            }
            ORDER_STOP_LIMIT => {
                let gap_trigger = if side == SIDE_BUY {
                    open >= order.trigger
                } else {
                    open <= order.trigger
                };
                let trigger_touched = if side == SIDE_BUY {
                    high >= order.trigger
                } else {
                    low <= order.trigger
                };
                let limit_touched = if side == SIDE_BUY {
                    low <= order.price
                } else {
                    high >= order.price
                };
                if !trigger_touched {
                    FillDecision::no_fill(false, FILL_REASON_NONE, FILL_AMBIGUITY_NONE)
                } else if gap_trigger {
                    let favorable_gap = if side == SIDE_BUY {
                        open <= order.price
                    } else {
                        open >= order.price
                    };
                    if favorable_gap {
                        FillDecision::fill(
                            open,
                            true,
                            FILL_REASON_STOP_LIMIT_OPEN_IMPROVEMENT,
                            FILL_AMBIGUITY_NONE,
                        )
                    } else if limit_touched {
                        FillDecision::fill(
                            order.price,
                            true,
                            FILL_REASON_STOP_LIMIT_AFTER_OPEN_TRIGGER,
                            FILL_AMBIGUITY_NONE,
                        )
                    } else {
                        FillDecision::no_fill(
                            true,
                            FILL_REASON_TRIGGERED_LIMIT_NOT_TOUCHED,
                            FILL_AMBIGUITY_NONE,
                        )
                    }
                } else if limit_touched {
                    FillDecision::no_fill(
                        true,
                        FILL_REASON_TRIGGERED_AWAIT_NEXT_BAR,
                        FILL_AMBIGUITY_STOP_LIMIT_PATH_UNKNOWN,
                    )
                } else {
                    FillDecision::no_fill(
                        true,
                        FILL_REASON_TRIGGERED_LIMIT_NOT_TOUCHED,
                        FILL_AMBIGUITY_NONE,
                    )
                }
            }
            _ => FillDecision::no_fill(order.trigger_armed, FILL_REASON_NONE, FILL_AMBIGUITY_NONE),
        }
    }

    fn activate_children(&mut self, parent_id: i64, sink: &mut DetailSink<'_>) -> Vec<OrderHandle> {
        let handles = self
            .lifecycle_indexes
            .children_of(ExternalOrderId(parent_id));
        self.relationship_scan_count += handles.len() as u64;
        let mut activated = Vec::with_capacity(handles.len());
        for handle in handles {
            let Some(child) = self.orders.get(handle).copied() else {
                continue;
            };
            if child.waiting_parent
                && child.parent_id == parent_id
                && (child.activation as i64 == ACTIVATION_ON_PARENT_FIRST_FILL
                    || child.activation as i64 == ACTIVATION_ON_PARENT_FULL_FILL)
            {
                if let Some(child_mut) = self.orders.get_mut(handle) {
                    child_mut.waiting_parent = false;
                    child_mut.active = true;
                }
                self.lifecycle_indexes.set_activation(handle, true, false);
                Self::add_event(
                    sink,
                    EVENT_ACTIVATE,
                    STATUS_PENDING,
                    child.order_id,
                    parent_id,
                    child.symbol as i64,
                );
                activated.push(handle);
            }
        }
        activated
    }

    fn cancel_oco_siblings(
        &mut self,
        oco_id: i64,
        filled_order_id: i64,
        sink: &mut DetailSink<'_>,
    ) -> i64 {
        if oco_id < 0 {
            return 0;
        }
        let handles = self.lifecycle_indexes.oco_members(oco_id);
        self.relationship_scan_count += handles.len() as u64;
        let mut canceled = 0;
        for handle in handles {
            let Some(sibling) = self.orders.get(handle).copied() else {
                continue;
            };
            if sibling.order_id != filled_order_id
                && sibling.oco_id == oco_id
                && sibling.status == STATUS_PENDING
                && (sibling.active || sibling.waiting_parent)
            {
                self.release_order(handle);
                canceled += 1;
                Self::add_event(
                    sink,
                    EVENT_CANCEL,
                    STATUS_CANCELED,
                    sibling.order_id,
                    filled_order_id,
                    sibling.symbol as i64,
                );
            }
        }
        canceled
    }

    #[allow(dead_code)]
    #[allow(clippy::too_many_arguments)]
    pub fn step(
        &mut self,
        bar: usize,
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
    ) -> Result<FullStepResult, String> {
        self.step_with_output(bar, codes, values, expiry, command_count, true)
    }

    /// Execute one bar while optionally suppressing per-step vectors.
    ///
    /// Score callers still receive scalar counts/accounting, but do not pay
    /// for positions/fill/event/active-order vectors that are discarded at
    /// the Python boundary. The default `step()` path remains full/audit
    /// compatible for reactive callbacks.
    #[allow(clippy::too_many_arguments)]
    pub fn step_with_output(
        &mut self,
        bar: usize,
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
        include_details: bool,
    ) -> Result<FullStepResult, String> {
        self.step_with_mask(
            bar,
            codes,
            values,
            expiry,
            command_count,
            if include_details { OUTPUT_ALL } else { 0 },
        )
    }

    /// Execute one bar with independent projection requirements.
    ///
    /// The engine never skips accounting or lifecycle transitions.  The mask
    /// only avoids allocating vectors which the callback cannot observe.
    #[allow(clippy::too_many_arguments)]
    pub fn step_with_mask(
        &mut self,
        bar: usize,
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
        output_mask: u8,
    ) -> Result<FullStepResult, String> {
        let mut buffers = std::mem::take(&mut self.step_buffers);
        let result = self.step_with_buffers(
            bar,
            codes,
            values,
            expiry,
            command_count,
            output_mask,
            true,
            &mut buffers,
        );
        self.step_buffers = buffers;
        result
    }

    /// Core lifecycle implementation. `materialize_rows` is true only for
    /// the compatibility/reactive dict surface. Static tape execution keeps
    /// the reusable SoA buffers and consumes them directly, so it never builds
    /// nested per-row vectors in the hot loop.
    #[allow(clippy::too_many_arguments)]
    pub fn step_with_buffers(
        &mut self,
        bar: usize,
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
        output_mask: u8,
        materialize_rows: bool,
        buffers: &mut StepBuffers,
    ) -> Result<FullStepResult, String> {
        buffers.clear();
        let mut counters = StepCounters::default();
        let collect_details = output_mask & (OUTPUT_FILLS | OUTPUT_EVENTS) != 0;
        let mut sink = if collect_details {
            DetailSink::Collect {
                counters: &mut counters,
                buffers,
            }
        } else {
            DetailSink::CountOnly(&mut counters)
        };
        if bar >= self.n_bars() {
            return Err("bar_index is outside the full prepared market tape".to_owned());
        }
        if self
            .last_bar
            .map(|last| bar != last + 1)
            .unwrap_or(bar != 0)
        {
            return Err(
                "FullReactiveSessionCore.step must be called once per consecutive bar".to_owned(),
            );
        }
        if codes.len() != command_count * CODE_WIDTH
            || values.len() != command_count * VALUE_WIDTH
            || expiry.len() != command_count
        {
            return Err("full command buffers do not match command count".to_owned());
        }
        // A new bar changes mark inputs even when no order is accepted. Any
        // post-bar snapshot from the previous mark must not cross this clock
        // boundary.
        self.bump_derived_versions(DerivedAccountInvalidationV1 {
            mark: true,
            ..DerivedAccountInvalidationV1::default()
        });
        self.invalidate_derived_account_cache();
        if self.liquidated {
            self.last_bar = Some(bar);
            return Ok(FullStepResult {
                equity: 0.0,
                positions: if output_mask & OUTPUT_POSITIONS != 0 {
                    vec![0.0; self.market.n_symbols]
                } else {
                    Vec::new()
                },
                liquidated: true,
                liquidation_bar: self.liquidation_bar,
                liquidation_reason: self.liquidation_reason,
                ..Default::default()
            });
        }
        if bar > 0 {
            for symbol in 0..self.market.n_symbols {
                self.equity += self.positions[symbol]
                    * (self.close(bar, symbol) - self.close(bar - 1, symbol))
                    * self.contract_sizes[symbol];
            }
            self.bump_derived_versions(DerivedAccountInvalidationV1 {
                wallet: true,
                ..DerivedAccountInvalidationV1::default()
            });
        }
        if self.intrabar_liquidated(bar) {
            self.liquidate(bar, LIQ_INTRABAR);
            self.last_bar = Some(bar);
            return Ok(FullStepResult {
                equity: 0.0,
                positions: if output_mask & OUTPUT_POSITIONS != 0 {
                    vec![0.0; self.market.n_symbols]
                } else {
                    Vec::new()
                },
                liquidated: true,
                liquidation_bar: self.liquidation_bar,
                liquidation_reason: self.liquidation_reason,
                ..Default::default()
            });
        }
        let mut funding_total = 0.0;
        if self.use_funding && self.has_funding_event(bar) {
            for symbol in 0..self.market.n_symbols {
                let cost = self.positions[symbol]
                    * self.close(bar, symbol)
                    * self.contract_sizes[symbol]
                    * self.funding(bar, symbol);
                self.equity -= cost;
                funding_total += cost;
            }
            self.bump_derived_versions(DerivedAccountInvalidationV1 {
                wallet: true,
                funding: true,
                ..DerivedAccountInvalidationV1::default()
            });
        }
        let (_, close_mm) = self.close_margin(bar);
        if close_mm > 0.0 && self.equity <= close_mm {
            self.liquidate(bar, LIQ_AFTER_FUNDING);
            self.last_bar = Some(bar);
            return Ok(FullStepResult {
                equity: 0.0,
                funding: funding_total,
                positions: if output_mask & OUTPUT_POSITIONS != 0 {
                    vec![0.0; self.market.n_symbols]
                } else {
                    Vec::new()
                },
                liquidated: true,
                liquidation_bar: self.liquidation_bar,
                liquidation_reason: self.liquidation_reason,
                ..Default::default()
            });
        }

        let mut rejected = 0_i64;
        let mut canceled = 0_i64;

        // GTD expiry precedes commands at the current bar. The timing index
        // visits due handles only; historical terminal orders are not scanned.
        let due_expiry = self.lifecycle_indexes.due_expiry_handles(bar as u32);
        self.expiry_scan_count += due_expiry.len() as u64;
        for handle in due_expiry {
            let Some(order) = self.orders.get(handle).copied() else {
                continue;
            };
            if order.status == STATUS_PENDING
                && (order.active || order.waiting_parent)
                && order.expires_bar >= 0
                && bar as i64 >= order.expires_bar
            {
                self.release_order(handle);
                canceled += 1;
                Self::add_event(
                    &mut sink,
                    EVENT_EXPIRE,
                    STATUS_CANCELED,
                    order.order_id,
                    -1,
                    order.symbol as i64,
                );
            }
        }

        for command_index in 0..command_count {
            let code = &codes[command_index * CODE_WIDTH..(command_index + 1) * CODE_WIDTH];
            let value = &values[command_index * VALUE_WIDTH..(command_index + 1) * VALUE_WIDTH];
            let action = code[0];
            let order_id = code[6];
            let target_id = code[7];
            match action {
                ACTION_PLACE => {
                    if !Self::valid_order(code, value)
                        || code[1] < 0
                        || code[1] >= self.market.n_symbols as i64
                    {
                        rejected += 1;
                        Self::add_event_with_reject(
                            &mut sink,
                            EVENT_REJECT,
                            STATUS_REJECTED,
                            order_id,
                            -1,
                            code[1],
                            REJECT_UNSUPPORTED_ORDER_TYPE,
                        );
                        continue;
                    }
                    match self.insert_order(
                        Self::build_order(code, value, expiry[command_index]),
                        &[order_id],
                    ) {
                        Ok(_) => Self::add_event(
                            &mut sink,
                            EVENT_PLACE,
                            STATUS_PENDING,
                            order_id,
                            -1,
                            code[1],
                        ),
                        Err(_) => {
                            rejected += 1;
                            Self::add_event_with_reject(
                                &mut sink,
                                EVENT_REJECT,
                                STATUS_REJECTED,
                                order_id,
                                -1,
                                code[1],
                                REJECT_INSUFFICIENT_MARGIN,
                            );
                        }
                    }
                }
                ACTION_CANCEL => {
                    if let Some(handle) = self.find_pending(target_id) {
                        let Some(order) = self.release_order(handle) else {
                            continue;
                        };
                        canceled += 1;
                        Self::add_event(
                            &mut sink,
                            EVENT_CANCEL,
                            STATUS_FILLED,
                            -1,
                            order.order_id,
                            order.symbol as i64,
                        );
                    } else {
                        rejected += 1;
                        Self::add_event_with_reject(
                            &mut sink,
                            EVENT_REJECT,
                            STATUS_REJECTED,
                            -1,
                            target_id,
                            code[1],
                            REJECT_UNKNOWN_ORDER,
                        );
                    }
                }
                ACTION_AMEND => {
                    if let Some(handle) = self.find_pending(target_id) {
                        let (resolved_target_id, symbol) = {
                            let order = self.orders.get_mut(handle).ok_or_else(|| {
                                "order handle became stale during amend".to_owned()
                            })?;
                            if value[0] > 0.0 {
                                order.qty = value[0];
                            }
                            if value[1] > 0.0 {
                                order.price = value[1];
                            }
                            if value[2] > 0.0 {
                                order.trigger = value[2];
                            }
                            (order.order_id, order.symbol as i64)
                        };
                        Self::add_event(
                            &mut sink,
                            EVENT_AMEND,
                            STATUS_FILLED,
                            -1,
                            resolved_target_id,
                            symbol,
                        );
                    } else {
                        rejected += 1;
                        Self::add_event_with_reject(
                            &mut sink,
                            EVENT_REJECT,
                            STATUS_REJECTED,
                            -1,
                            target_id,
                            code[1],
                            REJECT_UNKNOWN_ORDER,
                        );
                    }
                }
                ACTION_REPLACE => {
                    if let Some(handle) = self.find_pending(target_id) {
                        // Preserve every historical external ID resolving to
                        // the target before terminal release removes stale
                        // map entries. Replacement chains therefore retain
                        // `a -> b -> c` alias semantics without keeping a
                        // second order table or a Python-side resolver.
                        let mut aliases = self
                            .id_to_handle
                            .iter()
                            .filter_map(|(alias, mapped)| (*mapped == handle).then_some(*alias))
                            .collect::<Vec<_>>();
                        if !aliases.contains(&target_id) {
                            aliases.push(target_id);
                        }
                        if !aliases.contains(&order_id) {
                            aliases.push(order_id);
                        }
                        self.release_order(handle);
                        if !Self::valid_order(code, value)
                            || code[1] < 0
                            || code[1] >= self.market.n_symbols as i64
                        {
                            rejected += 1;
                            Self::add_event_with_reject(
                                &mut sink,
                                EVENT_REJECT,
                                STATUS_REJECTED,
                                order_id,
                                target_id,
                                code[1],
                                REJECT_UNSUPPORTED_ORDER_TYPE,
                            );
                        } else {
                            match self.insert_order(
                                Self::build_order(code, value, expiry[command_index]),
                                &aliases,
                            ) {
                                Ok(_) => Self::add_event(
                                    &mut sink,
                                    EVENT_REPLACE,
                                    STATUS_PENDING,
                                    order_id,
                                    target_id,
                                    code[1],
                                ),
                                Err(_) => {
                                    rejected += 1;
                                    Self::add_event_with_reject(
                                        &mut sink,
                                        EVENT_REJECT,
                                        STATUS_REJECTED,
                                        order_id,
                                        target_id,
                                        code[1],
                                        REJECT_INSUFFICIENT_MARGIN,
                                    );
                                }
                            }
                        }
                    } else {
                        rejected += 1;
                        Self::add_event_with_reject(
                            &mut sink,
                            EVENT_REJECT,
                            STATUS_REJECTED,
                            order_id,
                            target_id,
                            code[1],
                            REJECT_UNKNOWN_ORDER,
                        );
                    }
                }
                ACTION_CANCEL_ALL => {
                    let handles = self.lifecycle_indexes.live_priority_handles();
                    self.relationship_scan_count += handles.len() as u64;
                    let mut to_cancel = Vec::new();
                    for handle in handles {
                        let Some(order) = self.orders.get(handle) else {
                            continue;
                        };
                        let matches = (order.active || order.waiting_parent)
                            && order.status == STATUS_PENDING
                            && (code[1] < 0 || code[1] == order.symbol as i64)
                            && (code[2] == 0 || code[2] == order.side as i64)
                            && (code[3] < 0 || code[3] == order.order_type as i64)
                            && (code[8] < 0 || code[8] == order.parent_id)
                            && (code[9] < 0 || code[9] == order.group_id)
                            && (code[10] < 0 || code[10] == order.oco_id);
                        if matches {
                            to_cancel.push(handle);
                        }
                    }
                    for handle in to_cancel {
                        if self.release_order(handle).is_some() {
                            canceled += 1;
                        }
                    }
                    Self::add_event(
                        &mut sink,
                        EVENT_CANCEL,
                        STATUS_FILLED,
                        order_id,
                        -1,
                        code[1],
                    );
                }
                _ => {
                    rejected += 1;
                    Self::add_event_with_reject(
                        &mut sink,
                        EVENT_REJECT,
                        STATUS_REJECTED,
                        order_id,
                        target_id,
                        code[1],
                        REJECT_UNSUPPORTED_ACTION,
                    );
                }
            }
        }

        let mut fee_total = 0.0;
        let mut turnover = 0.0;
        // The ledger is reset once for the whole canonical bar. All matching
        // candidates, including siblings and package-emitted orders, consume
        // the same declared synthetic liquidity budget.
        for symbol in 0..self.market.n_symbols {
            self.bar_volumes[symbol] = self.volume(bar, symbol);
        }
        self.execution_model
            .begin_bar(&self.bar_volumes, &mut self.liquidity_ledger)?;
        // Stable monotonic sequence is priority. The index contains only
        // active orders; terminal history never participates in matching.
        self.matching_candidates = self.lifecycle_indexes.active_priority_handles();
        let mut cursor = 0;
        while cursor < self.matching_candidates.len() {
            let handle = self.matching_candidates[cursor];
            self.matching_scan_count += 1;
            let Some(order) = self.orders.get(handle).copied() else {
                cursor += 1;
                continue;
            };
            if !order.active || order.status != STATUS_PENDING {
                cursor += 1;
                continue;
            }
            let decision = self.fill_decision(&order, bar);
            if let Some(order_mut) = self.orders.get_mut(handle) {
                order_mut.trigger_armed = decision.triggered;
            }
            let Some(raw_price) = decision.raw_price else {
                if order.tif as i64 != TIF_GTC && order.tif as i64 != TIF_GTD {
                    self.release_order(handle);
                    canceled += 1;
                    Self::add_event(
                        &mut sink,
                        EVENT_CANCEL,
                        STATUS_CANCELED,
                        order.order_id,
                        -1,
                        order.symbol as i64,
                    );
                }
                cursor += 1;
                continue;
            };
            let mut qty = order.qty;
            let current = self.positions[order.symbol as usize];
            if order.reduce_only() {
                if current == 0.0
                    || (current > 0.0 && order.side as i64 == SIDE_BUY)
                    || (current < 0.0 && order.side as i64 == SIDE_SELL)
                {
                    self.release_order(handle);
                    canceled += 1;
                    Self::add_event_with_reject(
                        &mut sink,
                        EVENT_CANCEL,
                        STATUS_CANCELED,
                        order.order_id,
                        -1,
                        order.symbol as i64,
                        REJECT_REDUCE_ONLY_NO_POSITION,
                    );
                    cursor += 1;
                    continue;
                }
                qty = qty.min(current.abs());
            }
            let symbol = order.symbol as usize;
            let cs = self.contract_sizes[symbol];
            let close = self.close(bar, symbol);
            let Some(fill) = self.execution_model.preview_fill(
                FillCostInputV1 {
                    symbol,
                    side: order.side,
                    raw_price,
                    requested_qty: qty,
                    bar_volume: self.bar_volumes[symbol],
                    contract_multiplier: cs,
                    one_way_fee_rate: self.fee_rates[symbol],
                    apply_price_cost: decision.apply_price_cost,
                },
                &self.liquidity_ledger,
            )?
            else {
                if order.tif as i64 != TIF_GTC && order.tif as i64 != TIF_GTD {
                    self.release_order(handle);
                    canceled += 1;
                    Self::add_event(
                        &mut sink,
                        EVENT_CANCEL,
                        STATUS_CANCELED,
                        order.order_id,
                        -1,
                        order.symbol as i64,
                    );
                }
                cursor += 1;
                continue;
            };
            // FOK must not reserve/consume partial synthetic liquidity.
            if order.tif as i64 == TIF_FOK && fill.partial {
                self.release_order(handle);
                canceled += 1;
                Self::add_event(
                    &mut sink,
                    EVENT_CANCEL,
                    STATUS_CANCELED,
                    order.order_id,
                    -1,
                    order.symbol as i64,
                );
                cursor += 1;
                continue;
            }
            let qty = fill.quantity;
            let delta = qty * order.side as f64;
            let exec_price = fill.price;
            let notional = fill.turnover;
            let fee = fill.fee;
            let (cur_initial, _) = self.close_margin(bar);
            let old_initial = current.abs() * close * cs / self.leverages[symbol];
            let new_initial = (current + delta).abs() * exec_price * cs / self.leverages[symbol];
            let required = fee + (new_initial - old_initial).max(0.0);
            if required > self.equity - cur_initial {
                self.release_order(handle);
                rejected += 1;
                Self::add_event_with_reject(
                    &mut sink,
                    EVENT_REJECT,
                    STATUS_REJECTED,
                    order.order_id,
                    -1,
                    order.symbol as i64,
                    REJECT_INSUFFICIENT_MARGIN,
                );
                cursor += 1;
                continue;
            }
            self.equity += delta * (close - exec_price) * cs - fee;
            let new_position = current + delta;
            self.positions[symbol] = new_position;
            self.update_margin_cache_after_fill(bar, symbol, current, new_position);
            self.bump_derived_versions(DerivedAccountInvalidationV1 {
                position: true,
                wallet: true,
                fee: true,
                ..DerivedAccountInvalidationV1::default()
            });
            self.execution_model
                .commit_fill(fill, symbol, &mut self.liquidity_ledger)?;
            fee_total += fee;
            turnover += notional;
            sink.fill(
                order.order_id,
                order.symbol as i64,
                order.side as i64,
                qty,
                exec_price,
                fee,
                decision.reason,
                decision.ambiguity,
            );
            Self::add_event(
                &mut sink,
                EVENT_FILL,
                STATUS_FILLED,
                order.order_id,
                -1,
                order.symbol as i64,
            );
            let activated = self.activate_children(order.order_id, &mut sink);
            canceled += self.cancel_oco_siblings(order.oco_id, order.order_id, &mut sink);
            if fill.partial {
                if order.tif as i64 == TIF_IOC {
                    self.release_order(handle);
                    canceled += 1;
                    Self::add_event(
                        &mut sink,
                        EVENT_CANCEL,
                        STATUS_CANCELED,
                        order.order_id,
                        -1,
                        order.symbol as i64,
                    );
                } else if let Some(order_mut) = self.orders.get_mut(handle) {
                    order_mut.qty = (order_mut.qty - qty).max(0.0);
                    order_mut.trigger_armed = decision.triggered;
                }
            } else {
                self.release_order(handle);
            }
            self.matching_candidates.extend(activated);
            cursor += 1;
        }

        let (_initial_margin, maintenance_margin) = self.close_margin(bar);
        if maintenance_margin > 0.0 && self.equity <= maintenance_margin {
            self.liquidate(bar, LIQ_AFTER_ORDER);
        }
        if output_mask & OUTPUT_ACTIVE_ORDERS != 0 {
            for handle in self.lifecycle_indexes.live_priority_handles() {
                if let Some(order) = self.orders.get(handle) {
                    buffers.active_orders.push(order);
                }
            }
        }
        counters.rejected_count = rejected;
        counters.canceled_count = canceled;
        let fill_rows = if materialize_rows && output_mask & OUTPUT_FILLS != 0 {
            buffers.fills.rows()
        } else {
            Vec::new()
        };
        let event_rows = if materialize_rows && output_mask & OUTPUT_EVENTS != 0 {
            buffers.events.rows()
        } else {
            Vec::new()
        };
        let active_rows = if materialize_rows && output_mask & OUTPUT_ACTIVE_ORDERS != 0 {
            buffers.active_orders.rows()
        } else {
            Vec::new()
        };
        let fill_count = counters.fill_count;
        let event_count = counters.event_count;
        self.last_bar = Some(bar);
        let account_snapshot = self.post_execution_account_snapshot(bar)?;
        Ok(FullStepResult {
            equity: account_snapshot.equity,
            positions: if output_mask & OUTPUT_POSITIONS != 0 {
                self.positions.clone()
            } else {
                Vec::new()
            },
            fee: fee_total,
            turnover,
            funding: funding_total,
            initial_margin: account_snapshot.initial_margin,
            maintenance_margin: account_snapshot.maintenance_margin,
            liquidated: self.liquidated,
            liquidation_bar: self.liquidation_bar,
            liquidation_reason: self.liquidation_reason,
            fills: fill_rows,
            events: event_rows,
            active_orders: active_rows,
            rejected_count: rejected,
            canceled_count: canceled,
            fill_count,
            event_count,
            replace_count: counters.replace_count,
        })
    }

    /// Submit a bounded ABI-0.5 command slice for one canonical bar.
    ///
    /// This is intentionally the only typed-command entry point used by the
    /// strategy IR, portfolio target, and package drivers.  It preserves the
    /// same event clock, fill model, fee/slippage, margin, liquidation and
    /// lifecycle indexes as the API-0.4 compatibility path.
    #[allow(clippy::too_many_arguments)]
    pub fn step_typed_with_buffers(
        &mut self,
        bar: usize,
        commands: &[OrderCommandV5],
        output_mask: u8,
        materialize_rows: bool,
        buffers: &mut StepBuffers,
        scratch: &mut TypedCommandScratch,
    ) -> Result<FullStepResult, String> {
        scratch.encode(commands);
        self.step_with_buffers(
            bar,
            &scratch.codes,
            &scratch.values,
            &scratch.expiry,
            scratch.expiry.len(),
            output_mask,
            materialize_rows,
            buffers,
        )
    }

    /// Run a prepared static command tape without constructing Python objects.
    /// Audit positions are written directly into one bar-major flat buffer;
    /// score mode leaves all path/detail buffers empty by contract.
    pub fn run_static_tape(
        &mut self,
        ptr: &[i64],
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
        audit: bool,
    ) -> Result<StaticTapeOutput, String> {
        let profile = if audit {
            StaticOutputProfile::Audit
        } else {
            StaticOutputProfile::Score
        };
        self.run_static_profile(ptr, codes, values, expiry, command_count, profile)
    }

    /// Score entry point: retain only scalar terminal accounting.
    pub fn run_static_score(
        &mut self,
        ptr: &[i64],
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
    ) -> Result<StaticTapeOutput, String> {
        self.run_static_profile(
            ptr,
            codes,
            values,
            expiry,
            command_count,
            StaticOutputProfile::Score,
        )
    }

    /// Compact entry point: retain dense accounting paths without detail rows.
    pub fn run_static_compact(
        &mut self,
        ptr: &[i64],
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
    ) -> Result<StaticTapeOutput, String> {
        self.run_static_profile(
            ptr,
            codes,
            values,
            expiry,
            command_count,
            StaticOutputProfile::Compact,
        )
    }

    /// Audit entry point: retain dense accounting and typed fill/event columns.
    pub fn run_static_audit(
        &mut self,
        ptr: &[i64],
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
    ) -> Result<StaticTapeOutput, String> {
        self.run_static_profile(
            ptr,
            codes,
            values,
            expiry,
            command_count,
            StaticOutputProfile::Audit,
        )
    }

    fn run_static_profile(
        &mut self,
        ptr: &[i64],
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
        profile: StaticOutputProfile,
    ) -> Result<StaticTapeOutput, String> {
        if ptr.len() != self.n_bars() + 1
            || ptr.first().copied().unwrap_or(-1) != 0
            || ptr.last().copied().unwrap_or(-1) != command_count as i64
            || ptr
                .windows(2)
                .any(|pair| pair[1] < pair[0] || pair[1] > command_count as i64)
            || codes.len() != command_count * CODE_WIDTH
            || values.len() != command_count * VALUE_WIDTH
            || expiry.len() != command_count
        {
            return Err("invalid full command tape ABI 0.4 input".to_owned());
        }
        let n_bars = self.n_bars();
        let n_symbols = self.market.n_symbols;
        let retain_paths = profile.retains_paths();
        let retain_detail = profile.retains_detail();
        let path_capacity = if retain_paths { n_bars } else { 0 };
        let mut output = StaticTapeOutput {
            equity: Vec::with_capacity(path_capacity),
            positions: Vec::with_capacity(path_capacity * n_symbols),
            fees: Vec::with_capacity(path_capacity),
            turnover: Vec::with_capacity(path_capacity),
            funding: Vec::with_capacity(path_capacity),
            initial_margin: Vec::with_capacity(path_capacity),
            maintenance_margin: Vec::with_capacity(path_capacity),
            final_equity: self.equity,
            final_positions: self.positions.clone(),
            liquidation_bar: -1,
            liquidation_reason: LIQ_NONE,
            ..StaticTapeOutput::default()
        };
        let mut step_buffers = StepBuffers::default();
        for bar in 0..n_bars {
            // Bar zero is the initial snapshot. Commands mapped there are
            // intentionally outside the executable event tape, matching P0.
            let (start, end) = if bar == 0 {
                let after_bar_zero = ptr[1] as usize;
                (after_bar_zero, after_bar_zero)
            } else {
                (ptr[bar] as usize, ptr[bar + 1] as usize)
            };
            let step = self.step_with_buffers(
                bar,
                &codes[start * CODE_WIDTH..end * CODE_WIDTH],
                &values[start * VALUE_WIDTH..end * VALUE_WIDTH],
                &expiry[start..end],
                end - start,
                if retain_detail {
                    OUTPUT_FILLS | OUTPUT_EVENTS
                } else {
                    0
                },
                false,
                &mut step_buffers,
            )?;
            if retain_paths {
                output.equity.push(step.equity);
                output.positions.extend_from_slice(&self.positions);
                output.fees.push(step.fee);
                output.turnover.push(step.turnover);
                output.funding.push(step.funding);
                output.initial_margin.push(step.initial_margin);
                output.maintenance_margin.push(step.maintenance_margin);
            }
            output.final_equity = step.equity;
            output.final_positions.clone_from(&self.positions);
            output.total_fee += step.fee;
            output.total_turnover += step.turnover;
            output.total_funding += step.funding;
            output.rejected_count += step.rejected_count;
            output.canceled_count += step.canceled_count;
            output.fill_count += step.fill_count;
            output.event_count += step.event_count;
            if retain_detail {
                for index in 0..step_buffers.fills.order_id.len() {
                    output.fill_bar.push(bar as i64);
                    output
                        .fill_order_id
                        .push(step_buffers.fills.order_id[index]);
                    output.fill_symbol.push(step_buffers.fills.symbol[index]);
                    output.fill_side.push(step_buffers.fills.side[index]);
                    output.fill_qty.push(step_buffers.fills.qty[index]);
                    output.fill_price.push(step_buffers.fills.price[index]);
                    output.fill_fee.push(step_buffers.fills.fee[index]);
                    output.fill_reason.push(step_buffers.fills.reason[index]);
                    output
                        .fill_ambiguity
                        .push(step_buffers.fills.ambiguity[index]);
                }
                for index in 0..step_buffers.events.kind.len() {
                    output.event_bar.push(bar as i64);
                    output.event_kind.push(step_buffers.events.kind[index]);
                    output.event_status.push(step_buffers.events.status[index]);
                    output
                        .event_order_id
                        .push(step_buffers.events.order_id[index]);
                    output
                        .event_target_id
                        .push(step_buffers.events.target_id[index]);
                    output.event_symbol.push(step_buffers.events.symbol[index]);
                    output
                        .event_reject_code
                        .push(step_buffers.events.reject_code[index]);
                }
            }
            output.max_initial_margin = output.max_initial_margin.max(step.initial_margin);
            output.max_maintenance_margin =
                output.max_maintenance_margin.max(step.maintenance_margin);
            output.liquidated = step.liquidated;
            output.liquidation_bar = step.liquidation_bar;
            output.liquidation_reason = step.liquidation_reason;
        }
        Ok(output)
    }

    /// Compatibility score entry point. ABI-0.5 callers should prefer
    /// [`Self::run_typed_score_v1`] so their hot path retains the typed scalar
    /// result rather than adapting it to the API-0.4 static shape.
    pub fn run_typed_score(&mut self, tape: &CommandTapeV5) -> Result<StaticTapeOutput, String> {
        self.run_typed_score_v1(tape)
            .map(|output| StaticTapeOutput::from(NativeExecutionOutputV1::Score(output)))
    }

    /// Compatibility compact entry point. It moves typed buffers into the
    /// legacy static shape without replaying execution.
    pub fn run_typed_compact(&mut self, tape: &CommandTapeV5) -> Result<StaticTapeOutput, String> {
        self.run_typed_compact_v1(tape).map(|output| {
            StaticTapeOutput::from(NativeExecutionOutputV1::Compact(Box::new(output)))
        })
    }

    /// Compatibility audit entry point. The native audit trace remains the
    /// production artifact; this method only adapts its flat columns.
    pub fn run_typed_audit(&mut self, tape: &CommandTapeV5) -> Result<StaticTapeOutput, String> {
        self.run_typed_audit_v1(tape)
            .map(|output| StaticTapeOutput::from(NativeExecutionOutputV1::Audit(Box::new(output))))
    }

    /// Score-only ABI-0.5 execution. It retains scalar accounting and final
    /// positions only; neither paths nor audit columns are allocated.
    pub fn run_typed_score_v1(
        &mut self,
        tape: &CommandTapeV5,
    ) -> Result<NativeScoreOutputV1, String> {
        match self.run_typed_output_v1(tape, StaticOutputProfile::Score)? {
            NativeExecutionOutputV1::Score(output) => Ok(output),
            output => Err(format!(
                "typed score output profile mismatch: {:?}",
                output.profile()
            )),
        }
    }

    /// Compact ABI-0.5 execution. It retains the dense account paths but no
    /// fill/event trace.
    pub fn run_typed_compact_v1(
        &mut self,
        tape: &CommandTapeV5,
    ) -> Result<NativeCompactOutputV1, String> {
        match self.run_typed_output_v1(tape, StaticOutputProfile::Compact)? {
            NativeExecutionOutputV1::Compact(output) => Ok(*output),
            output => Err(format!(
                "typed compact output profile mismatch: {:?}",
                output.profile()
            )),
        }
    }

    /// Audit ABI-0.5 execution. It retains the compact account output plus
    /// typed fill/event columns in the same authoritative pass.
    pub fn run_typed_audit_v1(
        &mut self,
        tape: &CommandTapeV5,
    ) -> Result<NativeAuditOutputV1, String> {
        match self.run_typed_output_v1(tape, StaticOutputProfile::Audit)? {
            NativeExecutionOutputV1::Audit(output) => Ok(*output),
            output => Err(format!(
                "typed audit output profile mismatch: {:?}",
                output.profile()
            )),
        }
    }

    /// Execute a validated ABI-0.5 typed tape through the canonical lifecycle
    /// and accounting loop. Output retention is resolved once before the loop;
    /// no profile replays the tape or invokes Python while executing.
    pub fn run_typed_output_v1(
        &mut self,
        tape: &CommandTapeV5,
        profile: StaticOutputProfile,
    ) -> Result<NativeExecutionOutputV1, String> {
        self.run_typed_output_with_requirements_v1(tape, OutputRequirementsV1::resolve(profile))
    }

    /// Execute a typed tape with an already-resolved bounded retention plan.
    /// This is an output-only extension: matching, accounting, and lifecycle
    /// are identical to [`Self::run_typed_output_v1`].
    pub fn run_typed_output_with_requirements_v1(
        &mut self,
        tape: &CommandTapeV5,
        requirements: OutputRequirementsV1,
    ) -> Result<NativeExecutionOutputV1, String> {
        requirements.validate()?;
        if tape.bars() != self.n_bars() {
            return Err("typed command tape bars do not match prepared market".to_owned());
        }
        let n_bars = self.n_bars();
        let n_symbols = self.market.n_symbols;
        let mut score = NativeScoreOutputV1::new(self.equity);
        let mut metric_reducer = OnlineMetricReducerV2::new(self.metric_contract, self.equity)?;
        let mut paths = requirements
            .retain_paths
            .then(|| NativePathOutputV1::with_capacity(n_bars, n_symbols));
        let mut fills = requirements.retain_detail.then(NativeFillOutputV1::default);
        let mut events = requirements
            .retain_detail
            .then(NativeEventOutputV1::default);
        let mut detail_retention = requirements
            .retain_detail
            .then(|| AuditRetentionV1::new(requirements.detail_row_limit.unwrap_or(0)));
        let mut step_buffers = StepBuffers::default();
        let mut typed_scratch = TypedCommandScratch::with_capacity(8);

        for bar in 0..n_bars {
            // Preserve the frozen P0 bar-zero behavior: it is an initial
            // snapshot, not an executable command phase.
            let commands = if bar > 0 { tape.commands_at(bar) } else { &[] };
            let step = self.step_typed_with_buffers(
                bar,
                commands,
                if requirements.retain_detail {
                    OUTPUT_FILLS | OUTPUT_EVENTS
                } else {
                    0
                },
                false,
                &mut step_buffers,
                &mut typed_scratch,
            )?;
            if let Some(paths) = paths.as_mut() {
                paths.equity.push(step.equity);
                paths.positions.extend_from_slice(&self.positions);
                paths.fees.push(step.fee);
                paths.turnover.push(step.turnover);
                paths.funding.push(step.funding);
                paths.initial_margin.push(step.initial_margin);
                paths.maintenance_margin.push(step.maintenance_margin);
            }
            score.final_equity = step.equity;
            score.total_fee += step.fee;
            score.total_turnover += step.turnover;
            score.total_funding += step.funding;
            score.rejected_count += step.rejected_count;
            score.canceled_count += step.canceled_count;
            score.fill_count += step.fill_count;
            score.event_count += step.event_count;
            if let (Some(fills), Some(events), Some(retention)) =
                (fills.as_mut(), events.as_mut(), detail_retention.as_mut())
            {
                append_step_details_v1(fills, events, retention, &step_buffers, bar);
            }
            score.max_initial_margin = score.max_initial_margin.max(step.initial_margin);
            score.max_maintenance_margin =
                score.max_maintenance_margin.max(step.maintenance_margin);
            score.liquidated = step.liquidated;
            score.liquidation_bar = step.liquidation_bar;
            score.liquidation_reason = step.liquidation_reason;
            metric_reducer.observe(
                self.timestamp_ns(bar),
                step.equity,
                self.gross_exposure(bar, step.equity),
            )?;
        }
        // This is the only final-position copy in a typed run. In particular,
        // score workloads no longer clone position state once per bar.
        score.final_positions = self.positions.clone();
        score.metric_contract = self.metric_contract;
        score.metrics_v2 = Box::new(metric_reducer.finish(MetricFinishInputV2 {
            final_equity: score.final_equity,
            turnover: score.total_turnover,
            total_fee: score.total_fee,
            total_funding: score.total_funding,
            fill_count: score.fill_count,
            event_count: score.event_count,
            rejected_count: score.rejected_count,
            canceled_count: score.canceled_count,
            liquidated: score.liquidated,
        }));
        match requirements.profile {
            StaticOutputProfile::Score => Ok(NativeExecutionOutputV1::Score(score)),
            StaticOutputProfile::Compact => Ok(NativeExecutionOutputV1::Compact(Box::new(
                NativeCompactOutputV1 {
                    score,
                    paths: paths.expect("compact output requires dense paths"),
                },
            ))),
            StaticOutputProfile::Audit => Ok(NativeExecutionOutputV1::Audit(Box::new(
                NativeAuditOutputV1 {
                    compact: NativeCompactOutputV1 {
                        score,
                        paths: paths.expect("audit output requires dense paths"),
                    },
                    fills: fills.expect("audit output requires fill columns"),
                    events: events.expect("audit output requires event columns"),
                    detail_retention: detail_retention
                        .expect("audit output requires bounded detail retention"),
                },
            ))),
        }
    }

    /// Execute a typed workload whose command slice is resolved causally by
    /// Rust immediately before each bar's canonical command phase.
    ///
    /// This is deliberately additive to the static tape route.  It retains
    /// the same output profile, `step_typed_with_buffers` lifecycle, fee,
    /// funding, margin, liquidation and trace sink; only command *planning*
    /// varies per bar.  The closure is Rust-only and receives a read-only
    /// session, so no Python callback or duplicate mutable ledger can enter
    /// the hot loop.
    pub fn run_typed_dynamic_output_v1<F>(
        &mut self,
        profile: StaticOutputProfile,
        command_provider: F,
    ) -> Result<(NativeExecutionOutputV1, usize), String>
    where
        F: FnMut(usize, &FullSession, &mut Vec<OrderCommandV5>) -> Result<(), String>,
    {
        self.run_typed_dynamic_output_with_requirements_v1(
            OutputRequirementsV1::resolve(profile),
            command_provider,
        )
    }

    /// Dynamic counterpart to
    /// [`Self::run_typed_output_with_requirements_v1`]. The command provider
    /// remains Rust-only; the supplied requirements can only change retained
    /// output buffers and never the lifecycle/accounting pass.
    pub fn run_typed_dynamic_output_with_requirements_v1<F>(
        &mut self,
        requirements: OutputRequirementsV1,
        mut command_provider: F,
    ) -> Result<(NativeExecutionOutputV1, usize), String>
    where
        F: FnMut(usize, &FullSession, &mut Vec<OrderCommandV5>) -> Result<(), String>,
    {
        requirements.validate()?;
        let n_bars = self.n_bars();
        let n_symbols = self.market.n_symbols;
        let mut score = NativeScoreOutputV1::new(self.equity);
        let mut metric_reducer = OnlineMetricReducerV2::new(self.metric_contract, self.equity)?;
        let mut paths = requirements
            .retain_paths
            .then(|| NativePathOutputV1::with_capacity(n_bars, n_symbols));
        let mut fills = requirements.retain_detail.then(NativeFillOutputV1::default);
        let mut events = requirements
            .retain_detail
            .then(NativeEventOutputV1::default);
        let mut detail_retention = requirements
            .retain_detail
            .then(|| AuditRetentionV1::new(requirements.detail_row_limit.unwrap_or(0)));
        let mut step_buffers = StepBuffers::default();
        let mut typed_scratch = TypedCommandScratch::with_capacity(8);
        let mut commands = Vec::with_capacity(8);
        let mut command_count = 0_usize;

        for bar in 0..n_bars {
            commands.clear();
            if bar > 0 {
                command_provider(bar, self, &mut commands)?;
                command_count = command_count
                    .checked_add(commands.len())
                    .ok_or_else(|| "dynamic native command count overflow".to_owned())?;
            }
            let step = self.step_typed_with_buffers(
                bar,
                &commands,
                if requirements.retain_detail {
                    OUTPUT_FILLS | OUTPUT_EVENTS
                } else {
                    0
                },
                false,
                &mut step_buffers,
                &mut typed_scratch,
            )?;
            if let Some(paths) = paths.as_mut() {
                paths.equity.push(step.equity);
                paths.positions.extend_from_slice(&self.positions);
                paths.fees.push(step.fee);
                paths.turnover.push(step.turnover);
                paths.funding.push(step.funding);
                paths.initial_margin.push(step.initial_margin);
                paths.maintenance_margin.push(step.maintenance_margin);
            }
            score.final_equity = step.equity;
            score.total_fee += step.fee;
            score.total_turnover += step.turnover;
            score.total_funding += step.funding;
            score.rejected_count += step.rejected_count;
            score.canceled_count += step.canceled_count;
            score.fill_count += step.fill_count;
            score.event_count += step.event_count;
            if let (Some(fills), Some(events), Some(retention)) =
                (fills.as_mut(), events.as_mut(), detail_retention.as_mut())
            {
                append_step_details_v1(fills, events, retention, &step_buffers, bar);
            }
            score.max_initial_margin = score.max_initial_margin.max(step.initial_margin);
            score.max_maintenance_margin =
                score.max_maintenance_margin.max(step.maintenance_margin);
            score.liquidated = step.liquidated;
            score.liquidation_bar = step.liquidation_bar;
            score.liquidation_reason = step.liquidation_reason;
            metric_reducer.observe(
                self.timestamp_ns(bar),
                step.equity,
                self.gross_exposure(bar, step.equity),
            )?;
        }
        score.final_positions = self.positions.clone();
        score.metric_contract = self.metric_contract;
        score.metrics_v2 = Box::new(metric_reducer.finish(MetricFinishInputV2 {
            final_equity: score.final_equity,
            turnover: score.total_turnover,
            total_fee: score.total_fee,
            total_funding: score.total_funding,
            fill_count: score.fill_count,
            event_count: score.event_count,
            rejected_count: score.rejected_count,
            canceled_count: score.canceled_count,
            liquidated: score.liquidated,
        }));
        let output = match requirements.profile {
            StaticOutputProfile::Score => NativeExecutionOutputV1::Score(score),
            StaticOutputProfile::Compact => {
                NativeExecutionOutputV1::Compact(Box::new(NativeCompactOutputV1 {
                    score,
                    paths: paths.expect("compact output requires dense paths"),
                }))
            }
            StaticOutputProfile::Audit => {
                NativeExecutionOutputV1::Audit(Box::new(NativeAuditOutputV1 {
                    compact: NativeCompactOutputV1 {
                        score,
                        paths: paths.expect("audit output requires dense paths"),
                    },
                    fills: fills.expect("audit output requires fill columns"),
                    events: events.expect("audit output requires event columns"),
                    detail_retention: detail_retention
                        .expect("audit output requires bounded detail retention"),
                }))
            }
        };
        Ok((output, command_count))
    }
}

fn encode_typed_command(
    command: &OrderCommandV5,
    codes: &mut Vec<i64>,
    values: &mut Vec<f64>,
    expiry: &mut Vec<i64>,
) {
    let code_start = codes.len();
    codes.resize(code_start + CODE_WIDTH, -1);
    let value_start = values.len();
    values.resize(value_start + VALUE_WIDTH, 0.0);
    let code = &mut codes[code_start..code_start + CODE_WIDTH];
    let value = &mut values[value_start..value_start + VALUE_WIDTH];
    code[0] = command.action as u8 as i64;
    code[1] = command.symbol.map_or(-1, |symbol| i64::from(symbol.0));
    code[2] = command.side.map_or(0, |side| side as i8 as i64);
    code[3] = command
        .order_type
        .map_or(-1, |order_type| order_type as u8 as i64);
    code[4] = command.tif.map_or(TIF_GTC, |tif| tif as u8 as i64);
    code[5] = if command.reduce_only { 1 } else { 0 };
    code[6] = command.external_id.0;
    code[7] = command.target_id.0;
    code[8] = command.parent_id.0;
    code[9] = command.group_id;
    code[10] = command.oco_id;
    code[11] = command
        .activation
        .map_or(ACTIVATION_IMMEDIATE, |policy| policy as u8 as i64);
    code[12] = i64::from(command.command_index);
    value[0] = command.qty;
    value[1] = command.limit_price;
    value[2] = command.stop_price;
    expiry.push(command.expire_bar.map_or(-1, i64::from));
}

fn append_step_details_v1(
    fills: &mut NativeFillOutputV1,
    events: &mut NativeEventOutputV1,
    retention: &mut AuditRetentionV1,
    buffers: &StepBuffers,
    bar: usize,
) {
    for index in 0..buffers.fills.order_id.len() {
        if !retention.retain_next() {
            continue;
        }
        fills.bar.push(bar as i64);
        fills.order_id.push(buffers.fills.order_id[index]);
        fills.symbol.push(buffers.fills.symbol[index]);
        fills.side.push(buffers.fills.side[index]);
        fills.qty.push(buffers.fills.qty[index]);
        fills.price.push(buffers.fills.price[index]);
        fills.fee.push(buffers.fills.fee[index]);
        fills.reason.push(buffers.fills.reason[index]);
        fills.ambiguity.push(buffers.fills.ambiguity[index]);
    }
    for index in 0..buffers.events.kind.len() {
        if !retention.retain_next() {
            continue;
        }
        events.bar.push(bar as i64);
        events.kind.push(buffers.events.kind[index]);
        events.status.push(buffers.events.status[index]);
        events.order_id.push(buffers.events.order_id[index]);
        events.target_id.push(buffers.events.target_id[index]);
        events.symbol.push(buffers.events.symbol[index]);
        events.reject_code.push(buffers.events.reject_code[index]);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn session(open: f64, high: f64, low: f64, close: f64) -> FullSession {
        let market = FullMarketData::new(
            vec![0],
            vec![open],
            vec![high],
            vec![low],
            vec![close],
            vec![1_000.0],
            vec![0.0],
            vec![false],
            1,
        )
        .unwrap();
        FullSession::new(
            Arc::new(market),
            vec![1.0],
            vec![5.0],
            vec![0.0],
            10_000.0,
            0.005,
            0.001,
            false,
        )
        .unwrap()
    }

    fn order(order_type: i64, side: i64, price: f64, trigger: f64) -> OrderState {
        OrderState {
            command_index: 0,
            order_id: 1,
            symbol: 0,
            side: side as i8,
            order_type: order_type as u8,
            tif: TIF_GTC as u8,
            flags: 0,
            qty: 1.0,
            price,
            trigger,
            parent_id: -1,
            group_id: -1,
            oco_id: -1,
            activation: ACTIVATION_IMMEDIATE as u8,
            expires_bar: -1,
            active: true,
            waiting_parent: false,
            status: STATUS_PENDING,
            trigger_armed: false,
            sequence: 0,
        }
    }

    fn multi_bar_session(n_bars: usize) -> FullSession {
        let prices: Vec<f64> = (0..n_bars).map(|index| 100.0 + index as f64).collect();
        let market = FullMarketData::new(
            (0..n_bars as i64).collect(),
            prices.clone(),
            prices.iter().map(|price| price + 1.0).collect(),
            prices.iter().map(|price| price - 1.0).collect(),
            prices,
            vec![1_000.0; n_bars],
            vec![0.0; n_bars],
            vec![false; n_bars],
            1,
        )
        .unwrap();
        FullSession::new(
            Arc::new(market),
            vec![1.0],
            vec![5.0],
            vec![0.0002],
            10_000.0,
            0.005,
            0.0001,
            false,
        )
        .unwrap()
    }

    fn funded_multi_bar_session(n_bars: usize) -> FullSession {
        assert!(n_bars >= 3, "funded fixture needs an entry and funding bar");
        let prices: Vec<f64> = (0..n_bars).map(|index| 100.0 + index as f64).collect();
        let mut funding = vec![0.0; n_bars];
        let mut funding_mask = vec![false; n_bars];
        funding[1] = 0.0001;
        funding_mask[1] = true;
        let market = FullMarketData::new(
            (0..n_bars as i64).collect(),
            prices.clone(),
            prices.iter().map(|price| price + 1.0).collect(),
            prices.iter().map(|price| price - 1.0).collect(),
            prices,
            vec![1_000.0; n_bars],
            funding,
            funding_mask,
            1,
        )
        .unwrap();
        FullSession::new(
            Arc::new(market),
            vec![1.0],
            vec![5.0],
            vec![0.0002],
            10_000.0,
            0.005,
            0.0001,
            true,
        )
        .unwrap()
    }

    fn limited_liquidity_session() -> FullSession {
        let market = FullMarketData::new(
            vec![0, 1],
            vec![100.0, 101.0],
            vec![101.0, 102.0],
            vec![99.0, 100.0],
            vec![100.0, 101.0],
            vec![1.0, 1.0],
            vec![0.0, 0.0],
            vec![false, false],
            1,
        )
        .unwrap();
        let mut engine = FullSession::new(
            Arc::new(market),
            vec![1.0],
            vec![5.0],
            vec![0.0],
            10_000.0,
            0.005,
            0.0,
            false,
        )
        .unwrap();
        engine
            .set_execution_model(ExecutionModelPlanV1::Cost(
                crate::execution_model::CostModelV1::new(0.0, 0.0, 0.0, 0.0, Some(0.5)).unwrap(),
            ))
            .unwrap();
        engine
    }

    fn place_market(order_id: i64, side: i64) -> ([i64; CODE_WIDTH], [f64; VALUE_WIDTH]) {
        let mut code = [0_i64; CODE_WIDTH];
        code[0] = ACTION_PLACE;
        code[1] = 0;
        code[2] = side;
        code[3] = ORDER_MARKET;
        code[4] = TIF_GTC;
        code[6] = order_id;
        code[11] = ACTIVATION_IMMEDIATE;
        (code, [1.0, 0.0, 0.0])
    }

    #[test]
    fn zero_copy_market_window_matches_materialized_fold_reference() {
        let parent = Arc::new(
            FullMarketData::new(
                vec![0, 1, 2, 3, 4],
                vec![100.0, 101.0, 102.0, 103.0, 104.0],
                vec![101.0, 102.0, 103.0, 104.0, 105.0],
                vec![99.0, 100.0, 101.0, 102.0, 103.0],
                vec![100.0, 101.0, 102.0, 103.0, 104.0],
                vec![10.0; 5],
                vec![0.0, 0.0, 0.0, 0.0, 0.0001],
                vec![false, false, false, false, true],
                1,
            )
            .unwrap(),
        );
        let copied = Arc::new(parent.window(2, 5).unwrap());
        let mut copied_session = FullSession::new(
            copied,
            vec![1.0],
            vec![5.0],
            vec![0.0002],
            10_000.0,
            0.005,
            0.0001,
            true,
        )
        .unwrap();
        let mut shared_session = FullSession::new_window(
            parent.clone(),
            2,
            5,
            vec![1.0],
            vec![5.0],
            vec![0.0002],
            10_000.0,
            0.005,
            0.0001,
            true,
        )
        .unwrap();
        copied_session
            .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();
        shared_session
            .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();

        let (codes, values) = place_market(42, SIDE_BUY);
        let ptr = [0_i64, 0, 1, 1];
        let expiry = [-1_i64];
        let copied_output = copied_session
            .run_static_audit(&ptr, &codes, &values, &expiry, 1)
            .unwrap();
        let shared_output = shared_session
            .run_static_audit(&ptr, &codes, &values, &expiry, 1)
            .unwrap();

        assert_eq!(shared_session.n_bars(), 3);
        assert_eq!(shared_session.market_range(), (2, 5));
        assert!(Arc::ptr_eq(&shared_session.market, &parent));
        assert_eq!(shared_output.final_equity, copied_output.final_equity);
        assert_eq!(shared_output.final_positions, copied_output.final_positions);
        assert_eq!(shared_output.total_fee, copied_output.total_fee);
        assert_eq!(shared_output.total_turnover, copied_output.total_turnover);
        assert_eq!(shared_output.total_funding, copied_output.total_funding);
        assert_ne!(shared_output.total_funding, 0.0);
        assert_eq!(shared_output.fill_count, copied_output.fill_count);
        assert_eq!(shared_output.event_count, copied_output.event_count);
        assert_eq!(shared_output.rejected_count, copied_output.rejected_count);
        assert_eq!(shared_output.canceled_count, copied_output.canceled_count);
        assert_eq!(
            shared_output.max_initial_margin,
            copied_output.max_initial_margin
        );
        assert_eq!(
            shared_output.max_maintenance_margin,
            copied_output.max_maintenance_margin
        );
        assert_eq!(shared_output.liquidated, copied_output.liquidated);
        assert_eq!(shared_output.liquidation_bar, copied_output.liquidation_bar);
        assert_eq!(
            shared_output.liquidation_reason,
            copied_output.liquidation_reason
        );
        assert_eq!(shared_output.equity, copied_output.equity);
        assert_eq!(shared_output.positions, copied_output.positions);
        assert_eq!(shared_output.fees, copied_output.fees);
        assert_eq!(shared_output.turnover, copied_output.turnover);
        assert_eq!(shared_output.funding, copied_output.funding);
        assert_eq!(shared_output.initial_margin, copied_output.initial_margin);
        assert_eq!(
            shared_output.maintenance_margin,
            copied_output.maintenance_margin
        );
        assert_eq!(shared_output.fill_bar, copied_output.fill_bar);
        assert_eq!(shared_output.fill_order_id, copied_output.fill_order_id);
        assert_eq!(shared_output.fill_symbol, copied_output.fill_symbol);
        assert_eq!(shared_output.fill_side, copied_output.fill_side);
        assert_eq!(shared_output.fill_qty, copied_output.fill_qty);
        assert_eq!(shared_output.fill_price, copied_output.fill_price);
        assert_eq!(shared_output.fill_fee, copied_output.fill_fee);
        assert_eq!(shared_output.fill_reason, copied_output.fill_reason);
        assert_eq!(shared_output.fill_ambiguity, copied_output.fill_ambiguity);
        assert_eq!(shared_output.event_bar, copied_output.event_bar);
        assert_eq!(shared_output.event_kind, copied_output.event_kind);
        assert_eq!(shared_output.event_status, copied_output.event_status);
        assert_eq!(shared_output.event_order_id, copied_output.event_order_id);
        assert_eq!(shared_output.event_target_id, copied_output.event_target_id);
        assert_eq!(shared_output.event_symbol, copied_output.event_symbol);
        assert_eq!(
            shared_output.event_reject_code,
            copied_output.event_reject_code
        );
    }

    #[test]
    fn v2_market_is_frozen_at_next_bar_close() {
        let engine = session(100.0, 115.0, 95.0, 110.0);
        let decision = engine.fill_decision(&order(ORDER_MARKET, SIDE_BUY, 0.0, 0.0), 0);
        assert_eq!(decision.raw_price, Some(110.0));
        assert!(decision.apply_price_cost);
        assert_eq!(decision.reason, FILL_REASON_NEXT_BAR_CLOSE);
    }

    #[test]
    fn common_execution_model_matches_frozen_touch_and_cost_oracle() {
        let engine = session(100.0, 115.0, 95.0, 110.0);
        let order = order(ORDER_MARKET, SIDE_BUY, 0.0, 0.0);
        let legacy = engine.legacy_fill_decision(&order, 0);
        let decision = engine.fill_decision(&order, 0);
        assert_eq!(decision.triggered, legacy.triggered);
        assert_eq!(decision.reason, legacy.reason);
        assert_eq!(decision.ambiguity, legacy.ambiguity);

        let mut ledger = LiquidityLedgerV1::unlimited(1);
        engine
            .execution_model
            .begin_bar(&[1_000.0], &mut ledger)
            .unwrap();
        let fill = engine
            .execution_model
            .preview_fill(
                FillCostInputV1 {
                    symbol: 0,
                    side: order.side,
                    raw_price: decision.raw_price.unwrap(),
                    requested_qty: 1.0,
                    bar_volume: 1_000.0,
                    contract_multiplier: 1.0,
                    one_way_fee_rate: 0.0,
                    apply_price_cost: decision.apply_price_cost,
                },
                &ledger,
            )
            .unwrap()
            .unwrap();
        assert_eq!(legacy.price, Some(fill.price));
    }

    #[test]
    fn partial_fill_tif_paths_share_one_liquidity_ledger_without_accounting_drift() {
        // At 50% participation on one unit of OHLCV volume, one market order
        // for one unit can only fill 0.5 per bar. The lifecycle outcome differs
        // by TIF; cash/position changes must equal committed fills only.
        for (tif, expected_position, expected_live_orders, expected_canceled) in [
            (TIF_GTC, 1.0, 0, 0),
            (TIF_IOC, 0.5, 0, 1),
            (TIF_FOK, 0.0, 0, 1),
        ] {
            let mut engine = limited_liquidity_session();
            let (mut code, values) = place_market(42, SIDE_BUY);
            code[4] = tif;
            let first = engine
                .step_with_output(0, &code, &values, &[-1], 1, false)
                .unwrap();
            let second = engine.step_with_output(1, &[], &[], &[], 0, false).unwrap();

            match tif {
                TIF_GTC => {
                    assert_eq!(first.fill_count, 1);
                    assert_eq!(second.fill_count, 1);
                }
                TIF_IOC => {
                    assert_eq!(first.fill_count, 1);
                    assert_eq!(second.fill_count, 0);
                }
                TIF_FOK => {
                    assert_eq!(first.fill_count, 0);
                    assert_eq!(second.fill_count, 0);
                }
                _ => unreachable!(),
            }
            assert!((engine.positions[0] - expected_position).abs() < 1e-12);
            assert_eq!(engine.orders_len(), expected_live_orders);
            assert_eq!(
                first.canceled_count + second.canceled_count,
                expected_canceled
            );
            assert!(engine.equity.is_finite());
        }
    }

    #[test]
    fn derived_account_snapshot_matches_recompute_after_mark_fill_fee_funding_and_reset() {
        let mut engine = funded_multi_bar_session(4);
        let (entry_codes, entry_values) = place_market(77, SIDE_BUY);
        let first = engine
            .step_with_output(0, &entry_codes, &entry_values, &[-1], 1, false)
            .unwrap();
        let first_snapshot = engine.post_execution_account_snapshot(0).unwrap();
        assert_eq!(
            first_snapshot,
            engine.recompute_post_execution_account_snapshot(0).unwrap()
        );
        assert_eq!(first.equity, first_snapshot.equity);
        assert_eq!(first.initial_margin, first_snapshot.initial_margin);
        assert!(first_snapshot.versions.mark > 0);
        assert!(first_snapshot.versions.position > 0);
        assert!(first_snapshot.versions.wallet > 0);
        assert!(first_snapshot.versions.fee > 0);
        assert_eq!(engine.derived_account_recomputes(), 1);

        let hits_before_repeat_read = engine.derived_account_cache_hits();
        assert_eq!(
            engine.post_execution_account_snapshot(0).unwrap(),
            first_snapshot
        );
        assert_eq!(
            engine.derived_account_cache_hits(),
            hits_before_repeat_read + 1
        );

        let second = engine.step_with_output(1, &[], &[], &[], 0, false).unwrap();
        let second_snapshot = engine.post_execution_account_snapshot(1).unwrap();
        assert_eq!(
            second_snapshot,
            engine.recompute_post_execution_account_snapshot(1).unwrap()
        );
        assert_eq!(second.equity, second_snapshot.equity);
        assert!(second.funding.abs() > 0.0);
        assert!(second_snapshot.versions.mark > first_snapshot.versions.mark);
        assert!(second_snapshot.versions.wallet > first_snapshot.versions.wallet);
        assert!(second_snapshot.versions.funding > first_snapshot.versions.funding);
        assert_eq!(engine.derived_account_recomputes(), 2);

        let versions_before_reset = engine.derived_account_versions();
        engine.reset();
        let versions_after_reset = engine.derived_account_versions();
        assert_eq!(engine.session_reset_count(), 1);
        assert!(engine.positions.iter().all(|position| *position == 0.0));
        assert_eq!(engine.equity, engine.initial_capital);
        assert!(versions_after_reset.mark > versions_before_reset.mark);
        assert!(versions_after_reset.position > versions_before_reset.position);
        assert!(versions_after_reset.wallet > versions_before_reset.wallet);
        assert!(versions_after_reset.fee > versions_before_reset.fee);
        assert!(versions_after_reset.funding > versions_before_reset.funding);
        assert!(versions_after_reset.risk > versions_before_reset.risk);
        assert!(versions_after_reset.instrument > versions_before_reset.instrument);
        assert!(engine.post_execution_account_snapshot(1).is_err());
    }

    #[test]
    fn derived_account_snapshot_matches_recompute_after_intrabar_liquidation() {
        let market = FullMarketData::new(
            vec![0, 1],
            vec![100.0, 100.0],
            vec![101.0, 101.0],
            vec![99.0, 1.0],
            vec![100.0, 100.0],
            vec![1_000.0, 1_000.0],
            vec![0.0, 0.0],
            vec![false, false],
            1,
        )
        .unwrap();
        let mut engine = FullSession::new(
            Arc::new(market),
            vec![1.0],
            vec![5.0],
            vec![0.0002],
            1_000.0,
            0.005,
            0.0,
            false,
        )
        .unwrap();
        let (entry_codes, mut entry_values) = place_market(78, SIDE_BUY);
        entry_values[0] = 20.0;
        engine
            .step_with_output(0, &entry_codes, &entry_values, &[-1], 1, false)
            .unwrap();
        let before_liquidation = engine.post_execution_account_snapshot(0).unwrap();

        let liquidation = engine.step_with_output(1, &[], &[], &[], 0, false).unwrap();
        assert!(liquidation.liquidated);
        let snapshot = engine.post_execution_account_snapshot(1).unwrap();
        assert_eq!(
            snapshot,
            engine.recompute_post_execution_account_snapshot(1).unwrap()
        );
        assert!(snapshot.liquidated);
        assert_eq!(snapshot.equity, 0.0);
        assert_eq!(snapshot.initial_margin, 0.0);
        assert_eq!(snapshot.maintenance_margin, 0.0);
        assert!(snapshot.versions.risk > before_liquidation.versions.risk);
        assert!(snapshot.versions.position > before_liquidation.versions.position);
        assert!(snapshot.versions.wallet > before_liquidation.versions.wallet);
    }

    #[test]
    fn v3_market_uses_actual_open() {
        let mut engine = session(100.0, 115.0, 95.0, 110.0);
        engine
            .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();
        let decision = engine.fill_decision(&order(ORDER_MARKET, SIDE_BUY, 0.0, 0.0), 0);
        assert_eq!(decision.raw_price, Some(100.0));
        assert!(decision.apply_price_cost);
        assert_eq!(decision.reason, FILL_REASON_NEXT_OPEN);
    }

    #[test]
    fn v3_limit_gap_improves_to_open() {
        let mut engine = session(95.0, 101.0, 94.0, 99.0);
        engine
            .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();
        let decision = engine.fill_decision(&order(ORDER_LIMIT, SIDE_BUY, 100.0, 0.0), 0);
        assert_eq!(decision.raw_price, Some(95.0));
        assert!(!decision.apply_price_cost);
        assert_eq!(decision.reason, FILL_REASON_LIMIT_OPEN_IMPROVEMENT);
    }

    #[test]
    fn v3_adverse_stop_gap_uses_open() {
        let mut engine = session(110.0, 112.0, 107.0, 109.0);
        engine
            .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();
        let decision = engine.fill_decision(&order(ORDER_STOP_MARKET, SIDE_BUY, 0.0, 105.0), 0);
        assert_eq!(decision.raw_price, Some(110.0));
        assert!(decision.apply_price_cost);
        assert_eq!(decision.reason, FILL_REASON_STOP_OPEN_WORSE);
    }

    #[test]
    fn v3_stop_limit_unknown_path_arms_without_fill() {
        let mut engine = session(100.0, 110.0, 99.0, 108.0);
        engine
            .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();
        let decision = engine.fill_decision(&order(ORDER_STOP_LIMIT, SIDE_BUY, 104.0, 105.0), 0);
        assert!(decision.raw_price.is_none());
        assert!(decision.triggered);
        assert_eq!(decision.ambiguity, FILL_AMBIGUITY_STOP_LIMIT_PATH_UNKNOWN);
    }

    #[test]
    fn contract_cannot_change_mid_run() {
        let mut engine = session(100.0, 101.0, 99.0, 100.0);
        engine.last_bar = Some(0);
        assert!(
            engine
                .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
                .is_err()
        );
    }

    #[test]
    fn arena_and_indexes_release_high_churn_orders_without_hot_compaction() {
        let mut engine = multi_bar_session(96);
        for bar in 0..96 {
            let (codes, values) = place_market(
                bar as i64 + 1,
                if bar % 2 == 0 { SIDE_BUY } else { SIDE_SELL },
            );
            engine
                .step_with_output(bar, &codes, &values, &[-1], 1, false)
                .unwrap();
            engine.validate_lifecycle_indexes().unwrap();
        }
        assert_eq!(engine.orders_len(), 0);
        assert_eq!(engine.compaction_count, 0);
        assert_eq!(engine.terminal_orders_removed, 96);
        assert!(engine.orders_capacity() <= 4);
        assert!(engine.matching_scan_count <= 96);
    }

    #[test]
    fn parent_index_activates_child_and_releases_it_by_cancel() {
        let mut engine = multi_bar_session(3);
        let (parent_code, parent_values) = place_market(1, SIDE_BUY);
        let mut child_code = [0_i64; CODE_WIDTH];
        child_code[0] = ACTION_PLACE;
        child_code[1] = 0;
        child_code[2] = SIDE_SELL;
        child_code[3] = ORDER_LIMIT;
        child_code[4] = TIF_GTC;
        child_code[6] = 2;
        child_code[8] = 1;
        child_code[10] = 17;
        child_code[11] = ACTIVATION_ON_PARENT_FIRST_FILL;
        let mut codes = Vec::from(parent_code);
        codes.extend_from_slice(&child_code);
        let mut values = Vec::from(parent_values);
        values.extend_from_slice(&[1.0, 10_000.0, 0.0]);
        engine
            .step_with_output(0, &codes, &values, &[-1, -1], 2, false)
            .unwrap();
        engine.validate_lifecycle_indexes().unwrap();
        assert_eq!(engine.orders_len(), 1);
        assert_eq!(engine.terminal_active_order_rows().len(), 1);

        let mut cancel_code = [0_i64; CODE_WIDTH];
        cancel_code[0] = ACTION_CANCEL;
        cancel_code[1] = 0;
        cancel_code[7] = 2;
        engine
            .step_with_output(1, &cancel_code, &[0.0; VALUE_WIDTH], &[-1], 1, false)
            .unwrap();
        engine.validate_lifecycle_indexes().unwrap();
        assert_eq!(engine.orders_len(), 0);
    }

    #[test]
    fn replacement_chain_preserves_all_external_aliases() {
        let mut engine = multi_bar_session(4);
        let mut place = [0_i64; CODE_WIDTH];
        place[0] = ACTION_PLACE;
        place[1] = 0;
        place[2] = SIDE_BUY;
        place[3] = ORDER_LIMIT;
        place[4] = TIF_GTC;
        place[6] = 11;
        place[11] = ACTIVATION_IMMEDIATE;
        engine
            .step_with_output(0, &place, &[1.0, 50.0, 0.0], &[-1], 1, false)
            .unwrap();

        for (bar, order_id, target_id, price) in [(1, 12, 11, 51.0), (2, 13, 12, 52.0)] {
            let mut replace = [0_i64; CODE_WIDTH];
            replace[0] = ACTION_REPLACE;
            replace[1] = 0;
            replace[2] = SIDE_BUY;
            replace[3] = ORDER_LIMIT;
            replace[4] = TIF_GTC;
            replace[6] = order_id;
            replace[7] = target_id;
            replace[11] = ACTIVATION_IMMEDIATE;
            engine
                .step_with_output(bar, &replace, &[1.0, price, 0.0], &[-1], 1, false)
                .unwrap();
            engine.validate_lifecycle_indexes().unwrap();
        }

        // `11` must still resolve to the most recent replacement `13`.
        let mut cancel = [0_i64; CODE_WIDTH];
        cancel[0] = ACTION_CANCEL;
        cancel[1] = 0;
        cancel[7] = 11;
        let result = engine
            .step_with_output(3, &cancel, &[0.0; VALUE_WIDTH], &[-1], 1, false)
            .unwrap();
        assert_eq!(result.canceled_count, 1);
        assert_eq!(engine.orders_len(), 0);
        engine.validate_lifecycle_indexes().unwrap();
    }

    #[test]
    fn static_tape_audit_positions_are_flat_bar_major_columns() {
        let mut engine = multi_bar_session(2);
        let (codes, values) = place_market(1, SIDE_BUY);
        let output = engine
            .run_static_tape(&[0, 0, 1], &codes, &values, &[-1], 1, true)
            .unwrap();
        assert_eq!(output.equity.len(), 2);
        assert_eq!(output.positions.len(), 2);
        assert_eq!(output.positions[0], 0.0);
        assert_eq!(output.positions[1], 1.0);
        assert_eq!(output.fill_count, 1);
    }

    #[test]
    fn static_tape_compact_keeps_paths_but_not_detail_rows() {
        let mut compact_engine = multi_bar_session(2);
        let mut audit_engine = multi_bar_session(2);
        let (codes, values) = place_market(1, SIDE_BUY);
        let compact = compact_engine
            .run_static_compact(&[0, 0, 1], &codes, &values, &[-1], 1)
            .unwrap();
        let audit = audit_engine
            .run_static_audit(&[0, 0, 1], &codes, &values, &[-1], 1)
            .unwrap();
        assert_eq!(compact.equity, audit.equity);
        assert_eq!(compact.positions, audit.positions);
        assert_eq!(compact.final_equity, audit.final_equity);
        assert!(compact.fill_bar.is_empty());
        assert!(compact.event_bar.is_empty());
        assert_eq!(compact.fill_count, audit.fill_count);
        assert_eq!(compact.event_count, audit.event_count);
    }

    #[test]
    fn output_requirements_reject_inconsistent_score_detail_retention_before_execution() {
        let mut engine = multi_bar_session(2);
        let (codes, values) = place_market(1, SIDE_BUY);
        let tape = CommandTapeV5::new(
            vec![0, 0, 1],
            vec![OrderCommandV5 {
                action: quantbt_domain::enums::CommandAction::Place,
                symbol: Some(SymbolId(0)),
                side: Some(quantbt_domain::enums::Side::Buy),
                order_type: Some(quantbt_domain::enums::OrderType::Market),
                tif: Some(quantbt_domain::enums::TimeInForce::Gtc),
                reduce_only: false,
                external_id: ExternalOrderId(1),
                target_id: ExternalOrderId(-1),
                parent_id: ExternalOrderId(-1),
                group_id: -1,
                oco_id: -1,
                activation: Some(quantbt_domain::enums::ActivationPolicy::Immediate),
                command_index: 0,
                qty: values[0],
                limit_price: values[1],
                stop_price: values[2],
                expire_bar: None,
            }],
        )
        .unwrap();
        let invalid = OutputRequirementsV1 {
            profile: StaticOutputProfile::Score,
            retain_paths: false,
            retain_detail: true,
            detail_row_limit: Some(1),
        };
        assert!(
            engine
                .run_typed_output_with_requirements_v1(&tape, invalid)
                .is_err()
        );
        assert_eq!(engine.equity, engine.initial_capital);
        let valid = OutputRequirementsV1::audit_with_detail_limit(1);
        let output = engine
            .run_typed_output_with_requirements_v1(&tape, valid)
            .unwrap();
        assert!(output.detail_retention().retained_rows <= 1);
        let _ = codes;
    }
}

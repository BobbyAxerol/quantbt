//! Full Native Event V2 contract engine.
//!
//! This module deliberately mirrors the ordering in ``core.event._engine_event_v2``.
//! It is a compact, allocation-light Rust implementation of the public command
//! tape contract.  The older ``session`` module remains intact for ABI
//! compatibility with pre-47 wheels; the PyO3 layer exposes this module under a
//! versioned full-contract class.

use std::collections::HashMap;
use std::sync::Arc;

use crate::generated_contracts::{
    CONTRACT_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE, CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN,
};
use crate::orders::{IndexOrderState, LifecycleIndexes, OrderArena};
use crate::output::{StaticOutputProfile, StaticTapeOutput};
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

pub const FILL_REASON_NONE: i64 = 0;
pub const FILL_REASON_NEXT_BAR_CLOSE: i64 = 1;
pub const FILL_REASON_NEXT_OPEN: i64 = 2;
pub const FILL_REASON_LIMIT_TRIGGER: i64 = 3;
pub const FILL_REASON_LIMIT_OPEN_IMPROVEMENT: i64 = 4;
pub const FILL_REASON_STOP_TRIGGER_LEGACY: i64 = 5;
pub const FILL_REASON_STOP_TRIGGER: i64 = 6;
pub const FILL_REASON_STOP_OPEN_WORSE: i64 = 7;
pub const FILL_REASON_STOP_LIMIT_LEGACY: i64 = 8;
pub const FILL_REASON_STOP_LIMIT_OPEN_IMPROVEMENT: i64 = 9;
pub const FILL_REASON_STOP_LIMIT_AFTER_OPEN_TRIGGER: i64 = 10;
pub const FILL_REASON_TRIGGERED_LIMIT_NOT_TOUCHED: i64 = 11;
pub const FILL_REASON_TRIGGERED_AWAIT_NEXT_BAR: i64 = 12;

pub const FILL_AMBIGUITY_NONE: i64 = 0;
pub const FILL_AMBIGUITY_UNORDERED_OHLC_RANGE: i64 = 1;
pub const FILL_AMBIGUITY_STOP_LIMIT_PATH_UNKNOWN: i64 = 2;

#[derive(Clone, Copy, Debug, PartialEq)]
struct FillDecision {
    price: Option<f64>,
    triggered: bool,
    reason: i64,
    ambiguity: i64,
}

impl FillDecision {
    #[inline]
    fn no_fill(triggered: bool, reason: i64, ambiguity: i64) -> Self {
        Self {
            price: None,
            triggered,
            reason,
            ambiguity,
        }
    }

    #[inline]
    fn fill(price: f64, triggered: bool, reason: i64, ambiguity: i64) -> Self {
        Self {
            price: Some(price),
            triggered,
            reason,
            ambiguity,
        }
    }
}

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

    /// Materialize one contiguous execution window once per fold, never once
    /// per scenario. The source tape remains immutable and can therefore be
    /// shared by ordinary batch runs; this explicit copy is reserved for a
    /// fold that needs its own bar-zero/account reset semantics.
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
    pub contract_sizes: Box<[f64]>,
    pub leverages: Box<[f64]>,
    pub fee_rates: Box<[f64]>,
    pub initial_capital: f64,
    pub maintenance_ratio: f64,
    pub slippage: f64,
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
    step_buffers: StepBuffers,
    margin_cache: MarginCache,
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
        let n_symbols = market.n_symbols;
        if contract_sizes.len() != n_symbols
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
            contract_sizes: contract_sizes.into_boxed_slice(),
            leverages: leverages.into_boxed_slice(),
            fee_rates: fee_rates.into_boxed_slice(),
            initial_capital,
            maintenance_ratio,
            slippage,
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
            step_buffers: StepBuffers::default(),
            margin_cache: MarginCache::default(),
            margin_recompute_count: 0,
            expiry_scan_count: 0,
            matching_scan_count: 0,
            relationship_scan_count: 0,
            last_bar: None,
            compaction_count: 0,
            terminal_orders_removed: 0,
        })
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
        self.step_buffers.clear();
        self.margin_cache = MarginCache::default();
        self.margin_recompute_count = 0;
        self.expiry_scan_count = 0;
        self.matching_scan_count = 0;
        self.relationship_scan_count = 0;
        self.last_bar = None;
        self.compaction_count = 0;
        self.terminal_orders_removed = 0;
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
        Ok(())
    }

    pub fn orders_len(&self) -> usize {
        self.orders.len()
    }

    pub fn orders_capacity(&self) -> usize {
        self.orders.slot_capacity()
    }

    pub fn release_step_buffer_capacity(&mut self, max_capacity: usize) {
        self.step_buffers.release_excess_capacity(max_capacity);
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

    #[inline]
    fn close(&self, bar: usize, symbol: usize) -> f64 {
        self.market.at(&self.market.closes, bar, symbol)
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
                self.market.at(&self.market.lows, bar, symbol)
            } else {
                self.market.at(&self.market.highs, bar, symbol)
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
        order.sequence = self.next_order_sequence;
        self.next_order_sequence = self.next_order_sequence.wrapping_add(1);
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

    fn fill_decision(&self, order: &OrderState, bar: usize) -> FillDecision {
        let open = self
            .market
            .at(&self.market.opens, bar, order.symbol as usize);
        let high = self
            .market
            .at(&self.market.highs, bar, order.symbol as usize);
        let low = self
            .market
            .at(&self.market.lows, bar, order.symbol as usize);
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
        if bar >= self.market.n_bars {
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
        if self.use_funding && self.market.funding_mask[bar] {
            for symbol in 0..self.market.n_symbols {
                let cost = self.positions[symbol]
                    * self.close(bar, symbol)
                    * self.contract_sizes[symbol]
                    * self.market.at(&self.market.funding, bar, symbol);
                self.equity -= cost;
                funding_total += cost;
            }
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
            let Some(exec_price) = decision.price else {
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
            let delta = qty * order.side as f64;
            let symbol = order.symbol as usize;
            let cs = self.contract_sizes[symbol];
            let close = self.close(bar, symbol);
            let notional = delta.abs() * exec_price * cs;
            let fee = notional * self.fee_rates[symbol];
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
            self.release_order(handle);
            self.matching_candidates.extend(activated);
            cursor += 1;
        }

        let (initial_margin, maintenance_margin) = self.close_margin(bar);
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
        Ok(FullStepResult {
            equity: self.equity,
            positions: if output_mask & OUTPUT_POSITIONS != 0 {
                self.positions.clone()
            } else {
                Vec::new()
            },
            fee: fee_total,
            turnover,
            funding: funding_total,
            initial_margin: if self.liquidated { 0.0 } else { initial_margin },
            maintenance_margin: if self.liquidated {
                0.0
            } else {
                maintenance_margin
            },
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
        if ptr.len() != self.market.n_bars + 1
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
        let n_bars = self.market.n_bars;
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

    /// Execute a validated ABI-0.5 typed tape through the same lifecycle and
    /// accounting loop as the API-0.4 static path. The small raw scratch
    /// buffers are reused per bar: typed commands never need a Python-owned
    /// whole-tape conversion and no behavior is delegated to a second engine.
    pub fn run_typed_score(&mut self, tape: &CommandTapeV5) -> Result<StaticTapeOutput, String> {
        self.run_typed_profile(tape, StaticOutputProfile::Score)
    }

    /// Typed ABI-0.5 compact run with dense account paths and no detail rows.
    pub fn run_typed_compact(&mut self, tape: &CommandTapeV5) -> Result<StaticTapeOutput, String> {
        self.run_typed_profile(tape, StaticOutputProfile::Compact)
    }

    /// Typed ABI-0.5 audit run with the same typed fill/event columns as the
    /// API-0.4 static audit sink.
    pub fn run_typed_audit(&mut self, tape: &CommandTapeV5) -> Result<StaticTapeOutput, String> {
        self.run_typed_profile(tape, StaticOutputProfile::Audit)
    }

    fn run_typed_profile(
        &mut self,
        tape: &CommandTapeV5,
        profile: StaticOutputProfile,
    ) -> Result<StaticTapeOutput, String> {
        if tape.bars() != self.market.n_bars {
            return Err("typed command tape bars do not match prepared market".to_owned());
        }
        let n_bars = self.market.n_bars;
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
        let mut typed_scratch = TypedCommandScratch::with_capacity(8);

        for bar in 0..n_bars {
            // Preserve the frozen P0 bar-zero behavior: it is an initial
            // snapshot, not an executable command phase.
            let commands = if bar > 0 { tape.commands_at(bar) } else { &[] };
            let step = self.step_typed_with_buffers(
                bar,
                commands,
                if retain_detail {
                    OUTPUT_FILLS | OUTPUT_EVENTS
                } else {
                    0
                },
                false,
                &mut step_buffers,
                &mut typed_scratch,
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
                append_step_details(&mut output, &step_buffers, bar);
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

fn append_step_details(output: &mut StaticTapeOutput, buffers: &StepBuffers, bar: usize) {
    for index in 0..buffers.fills.order_id.len() {
        output.fill_bar.push(bar as i64);
        output.fill_order_id.push(buffers.fills.order_id[index]);
        output.fill_symbol.push(buffers.fills.symbol[index]);
        output.fill_side.push(buffers.fills.side[index]);
        output.fill_qty.push(buffers.fills.qty[index]);
        output.fill_price.push(buffers.fills.price[index]);
        output.fill_fee.push(buffers.fills.fee[index]);
        output.fill_reason.push(buffers.fills.reason[index]);
        output.fill_ambiguity.push(buffers.fills.ambiguity[index]);
    }
    for index in 0..buffers.events.kind.len() {
        output.event_bar.push(bar as i64);
        output.event_kind.push(buffers.events.kind[index]);
        output.event_status.push(buffers.events.status[index]);
        output.event_order_id.push(buffers.events.order_id[index]);
        output.event_target_id.push(buffers.events.target_id[index]);
        output.event_symbol.push(buffers.events.symbol[index]);
        output
            .event_reject_code
            .push(buffers.events.reject_code[index]);
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
    fn v2_market_is_frozen_at_next_bar_close() {
        let engine = session(100.0, 115.0, 95.0, 110.0);
        let decision = engine.fill_decision(&order(ORDER_MARKET, SIDE_BUY, 0.0, 0.0), 0);
        assert!((decision.price.unwrap() - 110.11).abs() <= 1e-12);
        assert_eq!(decision.reason, FILL_REASON_NEXT_BAR_CLOSE);
    }

    #[test]
    fn v3_market_uses_actual_open() {
        let mut engine = session(100.0, 115.0, 95.0, 110.0);
        engine
            .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();
        let decision = engine.fill_decision(&order(ORDER_MARKET, SIDE_BUY, 0.0, 0.0), 0);
        assert_eq!(decision.price, Some(100.1));
        assert_eq!(decision.reason, FILL_REASON_NEXT_OPEN);
    }

    #[test]
    fn v3_limit_gap_improves_to_open() {
        let mut engine = session(95.0, 101.0, 94.0, 99.0);
        engine
            .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();
        let decision = engine.fill_decision(&order(ORDER_LIMIT, SIDE_BUY, 100.0, 0.0), 0);
        assert_eq!(decision.price, Some(95.0));
        assert_eq!(decision.reason, FILL_REASON_LIMIT_OPEN_IMPROVEMENT);
    }

    #[test]
    fn v3_adverse_stop_gap_uses_open() {
        let mut engine = session(110.0, 112.0, 107.0, 109.0);
        engine
            .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();
        let decision = engine.fill_decision(&order(ORDER_STOP_MARKET, SIDE_BUY, 0.0, 105.0), 0);
        assert!((decision.price.unwrap() - 110.11).abs() <= 1e-12);
        assert_eq!(decision.reason, FILL_REASON_STOP_OPEN_WORSE);
    }

    #[test]
    fn v3_stop_limit_unknown_path_arms_without_fill() {
        let mut engine = session(100.0, 110.0, 99.0, 108.0);
        engine
            .set_event_contract(CONTRACT_EVENT_LIFECYCLE_V3_NEXT_OPEN)
            .unwrap();
        let decision = engine.fill_decision(&order(ORDER_STOP_LIMIT, SIDE_BUY, 104.0, 105.0), 0);
        assert!(decision.price.is_none());
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
}

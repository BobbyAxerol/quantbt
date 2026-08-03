//! Full Native Event V2 contract engine.
//!
//! This module deliberately mirrors the ordering in ``core.event._engine_event_v2``.
//! It is a compact, allocation-light Rust implementation of the public command
//! tape contract.  The older ``session`` module remains intact for ABI
//! compatibility with pre-47 wheels; the PyO3 layer exposes this module under a
//! versioned full-contract class.

use std::collections::HashMap;
use std::sync::Arc;

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
    }

    #[inline]
    pub fn push(&mut self, order_id: i64, symbol: i64, side: i64, qty: f64, price: f64, fee: f64) {
        self.order_id.push(order_id);
        self.symbol.push(symbol);
        self.side.push(side);
        self.qty.push(qty);
        self.price.push(price);
        self.fee.push(fee);
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
            Self::CountOnly(counters) => counters.event_count += 1,
            Self::Collect { counters, buffers } => {
                counters.event_count += 1;
                buffers
                    .events
                    .push(kind, status, order_id, target_id, symbol, reject_code);
            }
        }
    }

    #[inline]
    pub fn fill(&mut self, order_id: i64, symbol: i64, side: i64, qty: f64, price: f64, fee: f64) {
        match self {
            Self::CountOnly(counters) => counters.fill_count += 1,
            Self::Collect { counters, buffers } => {
                counters.fill_count += 1;
                buffers.fills.push(order_id, symbol, side, qty, price, fee);
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
    pub output_mask: u8,
    pub positions: Vec<f64>,
    pub equity: f64,
    pub liquidated: bool,
    pub liquidation_bar: i64,
    pub liquidation_reason: i64,
    orders: Vec<OrderState>,
    // The Python oracle resolves target_order_id through the latest command
    // slot, including the alias created by REPLACE. Keep that indirection
    // explicit so a later CANCEL/AMEND using the replaced target has the same
    // lifecycle result without changing insertion priority.
    id_to_slot: HashMap<i64, usize>,
    step_buffers: StepBuffers,
    margin_cache: MarginCache,
    margin_recompute_count: u64,
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
            output_mask: OUTPUT_ALL,
            positions: vec![0.0; n_symbols],
            equity: initial_capital,
            liquidated: false,
            liquidation_bar: -1,
            liquidation_reason: LIQ_NONE,
            orders: Vec::new(),
            id_to_slot: HashMap::new(),
            step_buffers: StepBuffers::default(),
            margin_cache: MarginCache::default(),
            margin_recompute_count: 0,
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
        self.id_to_slot.clear();
        self.step_buffers.clear();
        self.margin_cache = MarginCache::default();
        self.margin_recompute_count = 0;
        self.last_bar = None;
        self.compaction_count = 0;
        self.terminal_orders_removed = 0;
    }

    pub fn orders_len(&self) -> usize {
        self.orders.len()
    }

    pub fn orders_capacity(&self) -> usize {
        self.orders.capacity()
    }

    pub fn release_step_buffer_capacity(&mut self, max_capacity: usize) {
        self.step_buffers.release_excess_capacity(max_capacity);
    }

    pub fn step_buffer_capacities(&self) -> (usize, usize, usize) {
        self.step_buffers.capacity_signature()
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

    fn find_pending(&self, order_id: i64) -> Option<usize> {
        let slot = *self.id_to_slot.get(&order_id)?;
        let order = self.orders.get(slot)?;
        if (order.active || order.waiting_parent) && order.status == STATUS_PENDING {
            Some(slot)
        } else {
            None
        }
    }

    /// Drop terminal lifecycle records once they dominate the order arena.
    ///
    /// Active insertion order and every replacement alias are preserved. The
    /// conservative threshold keeps short tapes cheap while preventing a
    /// long reactive/Grid tape from retaining one heap record per command.
    fn compact_terminal_orders(&mut self) {
        let old_len = self.orders.len();
        if old_len < 64 {
            return;
        }
        let active_len = self
            .orders
            .iter()
            .filter(|order| {
                order.status == STATUS_PENDING && (order.active || order.waiting_parent)
            })
            .count();
        let terminal_len = old_len.saturating_sub(active_len);
        if terminal_len < 64 || terminal_len * 2 < old_len {
            return;
        }

        let old_orders = std::mem::take(&mut self.orders);
        let old_map = std::mem::take(&mut self.id_to_slot);
        let mut remap = vec![usize::MAX; old_len];
        let mut orders = Vec::with_capacity(active_len);
        for (old_slot, order) in old_orders.into_iter().enumerate() {
            if order.status == STATUS_PENDING && (order.active || order.waiting_parent) {
                remap[old_slot] = orders.len();
                orders.push(order);
            }
        }
        let mut id_to_slot = HashMap::with_capacity(old_map.len());
        for (order_id, old_slot) in old_map {
            let new_slot = remap.get(old_slot).copied().unwrap_or(usize::MAX);
            if new_slot != usize::MAX {
                id_to_slot.insert(order_id, new_slot);
            }
        }
        self.orders = orders;
        self.id_to_slot = id_to_slot;
        self.compaction_count += 1;
        self.terminal_orders_removed += terminal_len as u64;
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

    fn fill_price(&self, order: &OrderState, bar: usize) -> Option<f64> {
        let high = self
            .market
            .at(&self.market.highs, bar, order.symbol as usize);
        let low = self
            .market
            .at(&self.market.lows, bar, order.symbol as usize);
        let close = self.close(bar, order.symbol as usize);
        match order.order_type as i64 {
            ORDER_MARKET => Some(
                close
                    * if order.side as i64 == SIDE_BUY {
                        1.0 + self.slippage
                    } else {
                        1.0 - self.slippage
                    },
            ),
            ORDER_LIMIT if order.side as i64 == SIDE_BUY && low <= order.price => Some(order.price),
            ORDER_LIMIT if order.side as i64 == SIDE_SELL && high >= order.price => {
                Some(order.price)
            }
            ORDER_STOP_MARKET if order.side as i64 == SIDE_BUY && high >= order.trigger => {
                Some(order.trigger * (1.0 + self.slippage))
            }
            ORDER_STOP_MARKET if order.side as i64 == SIDE_SELL && low <= order.trigger => {
                Some(order.trigger * (1.0 - self.slippage))
            }
            ORDER_STOP_LIMIT
                if order.side as i64 == SIDE_BUY && high >= order.trigger && low <= order.price =>
            {
                Some(order.price)
            }
            ORDER_STOP_LIMIT
                if order.side as i64 == SIDE_SELL
                    && low <= order.trigger
                    && high >= order.price =>
            {
                Some(order.price)
            }
            _ => None,
        }
    }

    fn activate_children(&mut self, parent_id: i64, sink: &mut DetailSink<'_>) {
        for child in &mut self.orders {
            if child.waiting_parent
                && child.parent_id == parent_id
                && (child.activation as i64 == ACTIVATION_ON_PARENT_FIRST_FILL
                    || child.activation as i64 == ACTIVATION_ON_PARENT_FULL_FILL)
            {
                child.waiting_parent = false;
                child.active = true;
                Self::add_event(
                    sink,
                    EVENT_ACTIVATE,
                    STATUS_PENDING,
                    child.order_id,
                    parent_id,
                    child.symbol as i64,
                );
            }
        }
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
        let mut canceled = 0;
        for sibling in &mut self.orders {
            if sibling.order_id != filled_order_id
                && sibling.oco_id == oco_id
                && sibling.status == STATUS_PENDING
                && (sibling.active || sibling.waiting_parent)
            {
                sibling.active = false;
                sibling.waiting_parent = false;
                sibling.status = STATUS_CANCELED;
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

        // GTD expiry precedes commands at the current bar.
        for order in &mut self.orders {
            if order.status == STATUS_PENDING
                && (order.active || order.waiting_parent)
                && order.expires_bar >= 0
                && bar as i64 >= order.expires_bar
            {
                order.active = false;
                order.waiting_parent = false;
                order.status = STATUS_CANCELED;
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
                    let active = code[11] == ACTIVATION_IMMEDIATE;
                    self.orders.push(OrderState {
                        command_index: code[12].max(0) as usize,
                        order_id,
                        symbol: code[1] as u32,
                        side: code[2] as i8,
                        order_type: code[3] as u8,
                        tif: code[4] as u8,
                        flags: if code[5] != 0 { FLAG_REDUCE_ONLY } else { 0 },
                        qty: value[0],
                        price: value[1],
                        trigger: value[2],
                        parent_id: code[8],
                        group_id: code[9],
                        oco_id: code[10],
                        activation: code[11] as u8,
                        expires_bar: expiry[command_index],
                        active,
                        waiting_parent: !active,
                        status: STATUS_PENDING,
                    });
                    if order_id >= 0 {
                        self.id_to_slot.insert(order_id, self.orders.len() - 1);
                    }
                    Self::add_event(
                        &mut sink,
                        EVENT_PLACE,
                        STATUS_PENDING,
                        order_id,
                        -1,
                        code[1],
                    );
                }
                ACTION_CANCEL => {
                    if let Some(slot) = self.find_pending(target_id) {
                        let symbol = self.orders[slot].symbol as i64;
                        let resolved_target_id = self.orders[slot].order_id;
                        self.orders[slot].active = false;
                        self.orders[slot].waiting_parent = false;
                        self.orders[slot].status = STATUS_CANCELED;
                        canceled += 1;
                        Self::add_event(
                            &mut sink,
                            EVENT_CANCEL,
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
                ACTION_AMEND => {
                    if let Some(slot) = self.find_pending(target_id) {
                        let resolved_target_id = self.orders[slot].order_id;
                        if value[0] > 0.0 {
                            self.orders[slot].qty = value[0];
                        }
                        if value[1] > 0.0 {
                            self.orders[slot].price = value[1];
                        }
                        if value[2] > 0.0 {
                            self.orders[slot].trigger = value[2];
                        }
                        Self::add_event(
                            &mut sink,
                            EVENT_AMEND,
                            STATUS_FILLED,
                            -1,
                            resolved_target_id,
                            self.orders[slot].symbol as i64,
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
                    if let Some(slot) = self.find_pending(target_id) {
                        self.orders[slot].active = false;
                        self.orders[slot].waiting_parent = false;
                        self.orders[slot].status = STATUS_CANCELED;
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
                            let active = code[11] == ACTIVATION_IMMEDIATE;
                            self.orders.push(OrderState {
                                command_index: code[12].max(0) as usize,
                                order_id,
                                symbol: code[1] as u32,
                                side: code[2] as i8,
                                order_type: code[3] as u8,
                                tif: code[4] as u8,
                                flags: if code[5] != 0 { FLAG_REDUCE_ONLY } else { 0 },
                                qty: value[0],
                                price: value[1],
                                trigger: value[2],
                                parent_id: code[8],
                                group_id: code[9],
                                oco_id: code[10],
                                activation: code[11] as u8,
                                expires_bar: expiry[command_index],
                                active,
                                waiting_parent: !active,
                                status: STATUS_PENDING,
                            });
                            let new_slot = self.orders.len() - 1;
                            if target_id >= 0 {
                                self.id_to_slot.insert(target_id, new_slot);
                            }
                            if order_id >= 0 {
                                self.id_to_slot.insert(order_id, new_slot);
                            }
                            Self::add_event(
                                &mut sink,
                                EVENT_REPLACE,
                                STATUS_PENDING,
                                order_id,
                                target_id,
                                code[1],
                            );
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
                    for order in &mut self.orders {
                        let matches = (order.active || order.waiting_parent)
                            && order.status == STATUS_PENDING
                            && (code[1] < 0 || code[1] == order.symbol as i64)
                            && (code[2] == 0 || code[2] == order.side as i64)
                            && (code[3] < 0 || code[3] == order.order_type as i64)
                            && (code[8] < 0 || code[8] == order.parent_id)
                            && (code[9] < 0 || code[9] == order.group_id)
                            && (code[10] < 0 || code[10] == order.oco_id);
                        if matches {
                            order.active = false;
                            order.waiting_parent = false;
                            order.status = STATUS_CANCELED;
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
        // Stable insertion order is the priority order. Children activated by
        // an earlier fill are appended before the next scan reaches them.
        let mut cursor = 0;
        while cursor < self.orders.len() {
            if !self.orders[cursor].active || self.orders[cursor].status != STATUS_PENDING {
                cursor += 1;
                continue;
            }
            let order = self.orders[cursor];
            let Some(exec_price) = self.fill_price(&order, bar) else {
                if order.tif as i64 != TIF_GTC && order.tif as i64 != TIF_GTD {
                    self.orders[cursor].active = false;
                    self.orders[cursor].status = STATUS_CANCELED;
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
                    self.orders[cursor].active = false;
                    self.orders[cursor].status = STATUS_CANCELED;
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
                self.orders[cursor].active = false;
                self.orders[cursor].status = STATUS_REJECTED;
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
            self.orders[cursor].active = false;
            self.orders[cursor].status = STATUS_FILLED;
            fee_total += fee;
            turnover += notional;
            sink.fill(
                order.order_id,
                order.symbol as i64,
                order.side as i64,
                qty,
                exec_price,
                fee,
            );
            Self::add_event(
                &mut sink,
                EVENT_FILL,
                STATUS_FILLED,
                order.order_id,
                -1,
                order.symbol as i64,
            );
            self.activate_children(order.order_id, &mut sink);
            canceled += self.cancel_oco_siblings(order.oco_id, order.order_id, &mut sink);
            cursor += 1;
        }

        let (initial_margin, maintenance_margin) = self.close_margin(bar);
        if maintenance_margin > 0.0 && self.equity <= maintenance_margin {
            self.liquidate(bar, LIQ_AFTER_ORDER);
        }
        self.compact_terminal_orders();
        if output_mask & OUTPUT_ACTIVE_ORDERS != 0 {
            for order in self
                .orders
                .iter()
                .filter(|o| o.status == STATUS_PENDING && (o.active || o.waiting_parent))
            {
                buffers.active_orders.push(order);
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
        })
    }
}

//! Full Native Event V2 contract engine.
//!
//! This module deliberately mirrors the ordering in ``core.event._engine_event_v2``.
//! It is a compact, allocation-light Rust implementation of the public command
//! tape contract.  The older ``session`` module remains intact for ABI
//! compatibility with pre-47 wheels; the PyO3 layer exposes this module under a
//! versioned full-contract class.

use std::collections::HashMap;

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

#[allow(dead_code)]
#[derive(Clone)]
pub struct FullMarketData {
    pub timestamps_ns: Vec<i64>,
    pub opens: Vec<f64>,
    pub highs: Vec<f64>,
    pub lows: Vec<f64>,
    pub closes: Vec<f64>,
    pub volumes: Vec<f64>,
    pub funding: Vec<f64>,
    pub funding_mask: Vec<bool>,
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
            timestamps_ns,
            opens,
            highs,
            lows,
            closes,
            volumes,
            funding,
            funding_mask,
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
    symbol: i64,
    side: i64,
    order_type: i64,
    tif: i64,
    reduce_only: bool,
    qty: f64,
    price: f64,
    trigger: f64,
    parent_id: i64,
    group_id: i64,
    oco_id: i64,
    activation: i64,
    expires_bar: i64,
    active: bool,
    waiting_parent: bool,
    status: i64,
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
}

pub struct FullSession {
    pub market: FullMarketData,
    pub contract_sizes: Vec<f64>,
    pub leverages: Vec<f64>,
    pub fee_rates: Vec<f64>,
    pub initial_capital: f64,
    pub maintenance_ratio: f64,
    pub slippage: f64,
    pub use_funding: bool,
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
    last_bar: Option<usize>,
}

impl FullSession {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        market: FullMarketData,
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
            contract_sizes,
            leverages,
            fee_rates,
            initial_capital,
            maintenance_ratio,
            slippage,
            use_funding,
            positions: vec![0.0; n_symbols],
            equity: initial_capital,
            liquidated: false,
            liquidation_bar: -1,
            liquidation_reason: LIQ_NONE,
            orders: Vec::new(),
            id_to_slot: HashMap::new(),
            last_bar: None,
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
        self.last_bar = None;
    }

    #[inline]
    fn close(&self, bar: usize, symbol: usize) -> f64 {
        self.market.at(&self.market.closes, bar, symbol)
    }

    fn close_margin(&self, bar: usize) -> (f64, f64) {
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

    fn valid_order(code: &[i64], values: &[f64]) -> bool {
        let side = code[2];
        let order_type = code[3];
        let qty = values[0];
        if side != SIDE_BUY && side != SIDE_SELL || qty <= 0.0 {
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
        events: &mut Vec<Vec<i64>>,
        kind: i64,
        status: i64,
        order: i64,
        target: i64,
        symbol: i64,
    ) {
        events.push(vec![kind, status, order, target, symbol]);
    }

    fn add_event_with_reject(
        events: &mut Vec<Vec<i64>>,
        kind: i64,
        status: i64,
        order: i64,
        target: i64,
        symbol: i64,
        reject_code: i64,
    ) {
        events.push(vec![kind, status, order, target, symbol, reject_code]);
    }

    fn fill_price(&self, order: &OrderState, bar: usize) -> Option<f64> {
        let high = self
            .market
            .at(&self.market.highs, bar, order.symbol as usize);
        let low = self
            .market
            .at(&self.market.lows, bar, order.symbol as usize);
        let close = self.close(bar, order.symbol as usize);
        match order.order_type {
            ORDER_MARKET => Some(
                close
                    * if order.side == SIDE_BUY {
                        1.0 + self.slippage
                    } else {
                        1.0 - self.slippage
                    },
            ),
            ORDER_LIMIT if order.side == SIDE_BUY && low <= order.price => Some(order.price),
            ORDER_LIMIT if order.side == SIDE_SELL && high >= order.price => Some(order.price),
            ORDER_STOP_MARKET if order.side == SIDE_BUY && high >= order.trigger => {
                Some(order.trigger * (1.0 + self.slippage))
            }
            ORDER_STOP_MARKET if order.side == SIDE_SELL && low <= order.trigger => {
                Some(order.trigger * (1.0 - self.slippage))
            }
            ORDER_STOP_LIMIT
                if order.side == SIDE_BUY && high >= order.trigger && low <= order.price =>
            {
                Some(order.price)
            }
            ORDER_STOP_LIMIT
                if order.side == SIDE_SELL && low <= order.trigger && high >= order.price =>
            {
                Some(order.price)
            }
            _ => None,
        }
    }

    fn activate_children(&mut self, parent_id: i64, events: &mut Vec<Vec<i64>>) {
        for child in &mut self.orders {
            if child.waiting_parent
                && child.parent_id == parent_id
                && (child.activation == ACTIVATION_ON_PARENT_FIRST_FILL
                    || child.activation == ACTIVATION_ON_PARENT_FULL_FILL)
            {
                child.waiting_parent = false;
                child.active = true;
                Self::add_event(
                    events,
                    EVENT_ACTIVATE,
                    STATUS_PENDING,
                    child.order_id,
                    parent_id,
                    child.symbol,
                );
            }
        }
    }

    fn cancel_oco_siblings(
        &mut self,
        oco_id: i64,
        filled_order_id: i64,
        events: &mut Vec<Vec<i64>>,
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
                    events,
                    EVENT_CANCEL,
                    STATUS_CANCELED,
                    sibling.order_id,
                    filled_order_id,
                    sibling.symbol,
                );
            }
        }
        canceled
    }

    #[allow(clippy::too_many_arguments)]
    pub fn step(
        &mut self,
        bar: usize,
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
    ) -> Result<FullStepResult, String> {
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
                positions: vec![0.0; self.market.n_symbols],
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
                positions: vec![0.0; self.market.n_symbols],
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
                positions: vec![0.0; self.market.n_symbols],
                liquidated: true,
                liquidation_bar: self.liquidation_bar,
                liquidation_reason: self.liquidation_reason,
                ..Default::default()
            });
        }

        let mut events = Vec::new();
        let mut fills = Vec::new();
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
                    &mut events,
                    EVENT_EXPIRE,
                    STATUS_CANCELED,
                    order.order_id,
                    -1,
                    order.symbol,
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
                            &mut events,
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
                        symbol: code[1],
                        side: code[2],
                        order_type: code[3],
                        tif: code[4],
                        reduce_only: code[5] != 0,
                        qty: value[0],
                        price: value[1],
                        trigger: value[2],
                        parent_id: code[8],
                        group_id: code[9],
                        oco_id: code[10],
                        activation: code[11],
                        expires_bar: expiry[command_index],
                        active,
                        waiting_parent: !active,
                        status: STATUS_PENDING,
                    });
                    if order_id >= 0 {
                        self.id_to_slot.insert(order_id, self.orders.len() - 1);
                    }
                    Self::add_event(
                        &mut events,
                        EVENT_PLACE,
                        STATUS_PENDING,
                        order_id,
                        -1,
                        code[1],
                    );
                }
                ACTION_CANCEL => {
                    if let Some(slot) = self.find_pending(target_id) {
                        let symbol = self.orders[slot].symbol;
                        let resolved_target_id = self.orders[slot].order_id;
                        self.orders[slot].active = false;
                        self.orders[slot].waiting_parent = false;
                        self.orders[slot].status = STATUS_CANCELED;
                        canceled += 1;
                        Self::add_event(
                            &mut events,
                            EVENT_CANCEL,
                            STATUS_FILLED,
                            -1,
                            resolved_target_id,
                            symbol,
                        );
                    } else {
                        rejected += 1;
                        Self::add_event_with_reject(
                            &mut events,
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
                            &mut events,
                            EVENT_AMEND,
                            STATUS_FILLED,
                            -1,
                            resolved_target_id,
                            self.orders[slot].symbol,
                        );
                    } else {
                        rejected += 1;
                        Self::add_event_with_reject(
                            &mut events,
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
                                &mut events,
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
                                symbol: code[1],
                                side: code[2],
                                order_type: code[3],
                                tif: code[4],
                                reduce_only: code[5] != 0,
                                qty: value[0],
                                price: value[1],
                                trigger: value[2],
                                parent_id: code[8],
                                group_id: code[9],
                                oco_id: code[10],
                                activation: code[11],
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
                                &mut events,
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
                            &mut events,
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
                            && (code[1] < 0 || code[1] == order.symbol)
                            && (code[2] == 0 || code[2] == order.side)
                            && (code[3] < 0 || code[3] == order.order_type)
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
                        &mut events,
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
                        &mut events,
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
                if order.tif != TIF_GTC && order.tif != TIF_GTD {
                    self.orders[cursor].active = false;
                    self.orders[cursor].status = STATUS_CANCELED;
                    canceled += 1;
                    Self::add_event(
                        &mut events,
                        EVENT_CANCEL,
                        STATUS_CANCELED,
                        order.order_id,
                        -1,
                        order.symbol,
                    );
                }
                cursor += 1;
                continue;
            };
            let mut qty = order.qty;
            let current = self.positions[order.symbol as usize];
            if order.reduce_only {
                if current == 0.0
                    || (current > 0.0 && order.side == SIDE_BUY)
                    || (current < 0.0 && order.side == SIDE_SELL)
                {
                    self.orders[cursor].active = false;
                    self.orders[cursor].status = STATUS_CANCELED;
                    canceled += 1;
                    Self::add_event_with_reject(
                        &mut events,
                        EVENT_CANCEL,
                        STATUS_CANCELED,
                        order.order_id,
                        -1,
                        order.symbol,
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
                    &mut events,
                    EVENT_REJECT,
                    STATUS_REJECTED,
                    order.order_id,
                    -1,
                    order.symbol,
                    REJECT_INSUFFICIENT_MARGIN,
                );
                cursor += 1;
                continue;
            }
            self.equity += delta * (close - exec_price) * cs - fee;
            self.positions[symbol] += delta;
            self.orders[cursor].active = false;
            self.orders[cursor].status = STATUS_FILLED;
            fee_total += fee;
            turnover += notional;
            fills.push(vec![
                order.order_id as f64,
                order.symbol as f64,
                order.side as f64,
                qty,
                exec_price,
                fee,
            ]);
            Self::add_event(
                &mut events,
                EVENT_FILL,
                STATUS_FILLED,
                order.order_id,
                -1,
                order.symbol,
            );
            self.activate_children(order.order_id, &mut events);
            canceled += self.cancel_oco_siblings(order.oco_id, order.order_id, &mut events);
            cursor += 1;
        }

        let (initial_margin, maintenance_margin) = self.close_margin(bar);
        if maintenance_margin > 0.0 && self.equity <= maintenance_margin {
            self.liquidate(bar, LIQ_AFTER_ORDER);
        }
        let active_orders = self
            .orders
            .iter()
            .filter(|o| o.status == STATUS_PENDING && (o.active || o.waiting_parent))
            .map(|o| {
                vec![
                    o.order_id as f64,
                    o.symbol as f64,
                    o.side as f64,
                    o.order_type as f64,
                    o.qty,
                    o.price,
                    o.trigger,
                    o.tif as f64,
                    if o.reduce_only { 1.0 } else { 0.0 },
                    o.parent_id as f64,
                    o.group_id as f64,
                    o.oco_id as f64,
                    o.activation as f64,
                    if o.waiting_parent { 1.0 } else { 0.0 },
                ]
            })
            .collect();
        self.last_bar = Some(bar);
        Ok(FullStepResult {
            equity: self.equity,
            positions: self.positions.clone(),
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
            fills,
            events,
            active_orders,
            rejected_count: rejected,
            canceled_count: canceled,
        })
    }
}

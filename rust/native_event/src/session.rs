use std::collections::HashMap;
use std::sync::Arc;

use crate::accounting::{initial_margin, maintenance_margin, required_margin};
use crate::matching::execution_price;
use crate::types::{
    ACTION_AMEND, ACTION_CANCEL, ACTION_PLACE, ACTION_REPLACE, ActiveOrder, EVENT_AMEND,
    EVENT_CANCEL, EVENT_FILL, EVENT_PLACE, EVENT_REJECT, EVENT_REPLACE, FLAG_REDUCE_ONLY,
    MUTATE_PRICE, MUTATE_QTY, MUTATE_TRIGGER, ORDER_LIMIT, ORDER_MARKET, ORDER_STOP_LIMIT,
    ORDER_STOP_MARKET, SIDE_BUY, SIDE_SELL, STATUS_CANCELED, STATUS_FILLED, STATUS_PENDING,
    STATUS_REJECTED, StepResult,
};

pub struct PreparedMarketData {
    pub _timestamps_ns: Vec<i64>,
    pub _opens: Vec<f64>,
    pub highs: Vec<f64>,
    pub lows: Vec<f64>,
    pub closes: Vec<f64>,
    pub _volumes: Vec<f64>,
    pub _funding: Vec<f64>,
    pub _funding_mask: Vec<bool>,
}

impl PreparedMarketData {
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
    ) -> Result<Self, String> {
        let n = closes.len();
        if n == 0
            || timestamps_ns.len() != n
            || opens.len() != n
            || highs.len() != n
            || lows.len() != n
            || volumes.len() != n
            || funding.len() != n
            || funding_mask.len() != n
        {
            return Err("all market arrays must be non-empty and share one length".to_owned());
        }
        Ok(Self {
            _timestamps_ns: timestamps_ns,
            _opens: opens,
            highs,
            lows,
            closes,
            _volumes: volumes,
            _funding: funding,
            _funding_mask: funding_mask,
        })
    }

    pub fn len(&self) -> usize {
        self.closes.len()
    }
}

pub struct ReactiveSession {
    market: Arc<PreparedMarketData>,
    contract_size: f64,
    leverage: f64,
    fee_rate: f64,
    maintenance_ratio: f64,
    slippage_rate: f64,
    _use_funding: bool,
    position: f64,
    equity: f64,
    active_orders: Vec<ActiveOrder>,
    order_alias: HashMap<i64, i64>,
    last_bar: Option<usize>,
}

impl ReactiveSession {
    pub fn market_len(&self) -> usize {
        self.market.len()
    }

    #[allow(clippy::too_many_arguments)]
    pub fn new(
        market: Arc<PreparedMarketData>,
        contract_size: f64,
        leverage: f64,
        fee_rate: f64,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> Result<Self, String> {
        if contract_size <= 0.0
            || leverage <= 0.0
            || fee_rate < 0.0
            || initial_capital <= 0.0
            || maintenance_ratio < 0.0
            || slippage_rate < 0.0
        {
            return Err("invalid R1 account or execution parameter".to_owned());
        }
        if use_funding {
            return Err("Rust R1 does not support funding".to_owned());
        }
        Ok(Self {
            market,
            contract_size,
            leverage,
            fee_rate,
            maintenance_ratio,
            slippage_rate,
            _use_funding: use_funding,
            position: 0.0,
            equity: initial_capital,
            active_orders: Vec::new(),
            order_alias: HashMap::new(),
            last_bar: None,
        })
    }

    pub fn step(
        &mut self,
        bar: usize,
        codes: &[i64],
        values: &[f64],
        _expiry: &[i64],
        command_count: usize,
    ) -> Result<StepResult, String> {
        if bar >= self.market.closes.len() {
            return Err("bar_index is outside the prepared market tape".to_owned());
        }
        if self
            .last_bar
            .map(|last| bar != last + 1)
            .unwrap_or(bar != 0)
        {
            return Err(
                "ReactiveSessionCore.step must be called exactly once per consecutive bar"
                    .to_owned(),
            );
        }
        if codes.len() != command_count * 8 || values.len() != command_count * 3 {
            return Err("command batch buffer shape does not match command count".to_owned());
        }
        if bar > 0 {
            self.equity += self.position
                * (self.market.closes[bar] - self.market.closes[bar - 1])
                * self.contract_size;
        }
        let mut fee_total = 0.0;
        let mut turnover = 0.0;
        let mut events = Vec::new();
        for index in 0..command_count {
            let code = &codes[index * 8..(index + 1) * 8];
            let value = &values[index * 3..(index + 1) * 3];
            match code[0] {
                ACTION_PLACE => {
                    let side = code[1];
                    let order_type = code[2];
                    if !valid_order(side, order_type, value[0], value[1], value[2]) {
                        events.push(vec![EVENT_REJECT, STATUS_REJECTED, code[4], -1]);
                        continue;
                    }
                    self.active_orders.push(ActiveOrder {
                        order_id: code[4],
                        side,
                        order_type,
                        qty: value[0],
                        price: value[1],
                        trigger: value[2],
                        reduce_only: (code[3] & FLAG_REDUCE_ONLY) != 0,
                    });
                    events.push(vec![EVENT_PLACE, STATUS_PENDING, code[4], -1]);
                }
                ACTION_CANCEL => {
                    let target = self.resolve_order_id(code[5]);
                    if let Some(position) = self
                        .active_orders
                        .iter()
                        .position(|order| order.order_id == target)
                    {
                        self.active_orders.remove(position);
                        events.push(vec![EVENT_CANCEL, STATUS_FILLED, -1, code[5]]);
                    } else {
                        events.push(vec![EVENT_REJECT, STATUS_REJECTED, -1, code[5]]);
                    }
                }
                ACTION_AMEND => {
                    let target = self.resolve_order_id(code[5]);
                    if let Some(order) = self
                        .active_orders
                        .iter_mut()
                        .find(|order| order.order_id == target)
                    {
                        let mask = code[6];
                        if (mask & MUTATE_QTY) != 0 && value[0] > 0.0 {
                            order.qty = value[0];
                        }
                        if (mask & MUTATE_PRICE) != 0 && value[1] > 0.0 {
                            order.price = value[1];
                        }
                        if (mask & MUTATE_TRIGGER) != 0 && value[2] > 0.0 {
                            order.trigger = value[2];
                        }
                        events.push(vec![EVENT_AMEND, STATUS_FILLED, -1, code[5]]);
                    } else {
                        events.push(vec![EVENT_REJECT, STATUS_REJECTED, -1, code[5]]);
                    }
                }
                ACTION_REPLACE => {
                    let target = self.resolve_order_id(code[5]);
                    if let Some(position) = self
                        .active_orders
                        .iter()
                        .position(|order| order.order_id == target)
                    {
                        self.active_orders.remove(position);
                        events.push(vec![EVENT_REPLACE, STATUS_CANCELED, code[4], code[5]]);
                        let side = code[1];
                        let order_type = code[2];
                        if !valid_order(side, order_type, value[0], value[1], value[2]) {
                            events.push(vec![EVENT_REJECT, STATUS_REJECTED, code[4], code[5]]);
                            continue;
                        }
                        self.active_orders.push(ActiveOrder {
                            order_id: code[4],
                            side,
                            order_type,
                            qty: value[0],
                            price: value[1],
                            trigger: value[2],
                            reduce_only: (code[3] & FLAG_REDUCE_ONLY) != 0,
                        });
                        self.order_alias.insert(code[5], code[4]);
                        events.push(vec![EVENT_REPLACE, STATUS_PENDING, code[4], code[5]]);
                    } else {
                        events.push(vec![EVENT_REJECT, STATUS_REJECTED, code[4], code[5]]);
                    }
                }
                _ => events.push(vec![EVENT_REJECT, STATUS_REJECTED, code[4], code[5]]),
            }
        }

        let mut fills = Vec::new();
        let mut retained = Vec::with_capacity(self.active_orders.len());
        for order in self.active_orders.drain(..) {
            let Some(price) = execution_price(
                &order,
                self.market.highs[bar],
                self.market.lows[bar],
                self.market.closes[bar],
                self.slippage_rate,
            ) else {
                retained.push(order);
                continue;
            };
            let mut qty = order.qty;
            if order.reduce_only {
                if self.position == 0.0
                    || (self.position > 0.0 && order.side == SIDE_BUY)
                    || (self.position < 0.0 && order.side == SIDE_SELL)
                {
                    events.push(vec![EVENT_CANCEL, STATUS_CANCELED, order.order_id, -1]);
                    continue;
                }
                qty = qty.min(self.position.abs());
            }
            let delta = qty * order.side as f64;
            let notional = delta.abs() * price * self.contract_size;
            let fee = notional * self.fee_rate;
            let (required, current_margin) = required_margin(
                self.position,
                delta,
                self.market.closes[bar],
                price,
                self.contract_size,
                self.leverage,
                fee,
            );
            if required > self.equity - current_margin {
                events.push(vec![EVENT_REJECT, STATUS_REJECTED, order.order_id, -1]);
                continue;
            }
            self.equity += delta * (self.market.closes[bar] - price) * self.contract_size - fee;
            self.position += delta;
            fee_total += fee;
            turnover += notional;
            fills.push(vec![
                order.order_id as f64,
                order.side as f64,
                qty,
                price,
                fee,
            ]);
            events.push(vec![EVENT_FILL, STATUS_FILLED, order.order_id, -1]);
        }
        self.active_orders = retained;
        self.last_bar = Some(bar);
        let initial_margin = initial_margin(
            self.position,
            self.market.closes[bar],
            self.contract_size,
            self.leverage,
        );
        let maintenance_margin = maintenance_margin(
            self.position,
            self.market.closes[bar],
            self.contract_size,
            self.maintenance_ratio,
        );
        let active_orders = self
            .active_orders
            .iter()
            .map(|order| {
                vec![
                    order.order_id as f64,
                    order.side as f64,
                    order.order_type as f64,
                    order.qty,
                    order.price,
                    order.trigger,
                    if order.reduce_only {
                        FLAG_REDUCE_ONLY as f64
                    } else {
                        0.0
                    },
                ]
            })
            .collect();
        Ok(StepResult {
            equity: self.equity,
            position: self.position,
            fee: fee_total,
            turnover,
            initial_margin,
            maintenance_margin,
            fills,
            events,
            active_orders,
        })
    }

    fn resolve_order_id(&self, order_id: i64) -> i64 {
        let mut resolved = order_id;
        // A replacement can itself be replaced. The depth is bounded by the
        // number of lifecycle commands and the guard prevents malformed
        // command tapes from creating an infinite alias cycle.
        for _ in 0..64 {
            let Some(next) = self.order_alias.get(&resolved) else {
                break;
            };
            if *next == resolved {
                break;
            }
            resolved = *next;
        }
        resolved
    }
}

fn valid_order(side: i64, order_type: i64, qty: f64, price: f64, trigger: f64) -> bool {
    if (side != SIDE_BUY && side != SIDE_SELL) || qty <= 0.0 {
        return false;
    }
    match order_type {
        ORDER_MARKET => true,
        ORDER_LIMIT => price > 0.0,
        ORDER_STOP_MARKET => trigger > 0.0,
        ORDER_STOP_LIMIT => price > 0.0 && trigger > 0.0,
        _ => false,
    }
}

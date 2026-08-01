use crate::accounting::{initial_margin, maintenance_margin, required_margin};
use crate::matching::execution_price;
use crate::types::{
    ActiveOrder, StepResult, ACTION_CANCEL, ACTION_PLACE, EVENT_CANCEL, EVENT_FILL, EVENT_PLACE, EVENT_REJECT,
    ORDER_LIMIT, SIDE_BUY, SIDE_SELL, STATUS_CANCELED, STATUS_FILLED, STATUS_PENDING, STATUS_REJECTED,
};

pub struct ReactiveSession {
    _timestamps_ns: Vec<i64>,
    _opens: Vec<f64>,
    highs: Vec<f64>,
    lows: Vec<f64>,
    closes: Vec<f64>,
    _volumes: Vec<f64>,
    _funding: Vec<f64>,
    _funding_mask: Vec<bool>,
    contract_size: f64,
    leverage: f64,
    fee_rate: f64,
    maintenance_ratio: f64,
    slippage_rate: f64,
    _use_funding: bool,
    position: f64,
    equity: f64,
    active_orders: Vec<ActiveOrder>,
    last_bar: Option<usize>,
}

impl ReactiveSession {
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
        contract_size: f64,
        leverage: f64,
        fee_rate: f64,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> Result<Self, String> {
        let n = closes.len();
        if n == 0 || timestamps_ns.len() != n || opens.len() != n || highs.len() != n || lows.len() != n || volumes.len() != n || funding.len() != n || funding_mask.len() != n {
            return Err("all market arrays must be non-empty and share one length".to_owned());
        }
        if contract_size <= 0.0 || leverage <= 0.0 || fee_rate < 0.0 || initial_capital <= 0.0 || maintenance_ratio < 0.0 || slippage_rate < 0.0 {
            return Err("invalid R1 account or execution parameter".to_owned());
        }
        if use_funding {
            return Err("Rust R1 does not support funding".to_owned());
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
            contract_size,
            leverage,
            fee_rate,
            maintenance_ratio,
            slippage_rate,
            _use_funding: use_funding,
            position: 0.0,
            equity: initial_capital,
            active_orders: Vec::new(),
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
        if bar >= self.closes.len() {
            return Err("bar_index is outside the prepared market tape".to_owned());
        }
        if self.last_bar.map(|last| bar != last + 1).unwrap_or(bar != 0) {
            return Err("ReactiveSessionCore.step must be called exactly once per consecutive bar".to_owned());
        }
        if codes.len() != command_count * 8 || values.len() != command_count * 3 {
            return Err("command batch buffer shape does not match command count".to_owned());
        }
        if bar > 0 {
            self.equity += self.position * (self.closes[bar] - self.closes[bar - 1]) * self.contract_size;
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
                    if (side != SIDE_BUY && side != SIDE_SELL) || (order_type != 0 && order_type != ORDER_LIMIT) || value[0] <= 0.0 {
                        events.push(vec![EVENT_REJECT, STATUS_REJECTED, code[4], -1]);
                        continue;
                    }
                    self.active_orders.push(ActiveOrder {
                        order_id: code[4],
                        side,
                        order_type,
                        qty: value[0],
                        price: value[1],
                    });
                    events.push(vec![EVENT_PLACE, STATUS_PENDING, code[4], -1]);
                }
                ACTION_CANCEL => {
                    if let Some(position) = self.active_orders.iter().position(|order| order.order_id == code[5]) {
                        self.active_orders.remove(position);
                        events.push(vec![EVENT_CANCEL, STATUS_FILLED, -1, code[5]]);
                    } else {
                        events.push(vec![EVENT_REJECT, STATUS_REJECTED, -1, code[5]]);
                    }
                }
                _ => events.push(vec![EVENT_REJECT, STATUS_REJECTED, code[4], code[5]]),
            }
        }

        let mut fills = Vec::new();
        let mut retained = Vec::with_capacity(self.active_orders.len());
        for order in self.active_orders.drain(..) {
            let Some(price) = execution_price(&order, self.highs[bar], self.lows[bar], self.closes[bar], self.slippage_rate) else {
                retained.push(order);
                continue;
            };
            let delta = order.qty * order.side as f64;
            let notional = delta.abs() * price * self.contract_size;
            let fee = notional * self.fee_rate;
            let (required, current_margin) = required_margin(
                self.position,
                delta,
                self.closes[bar],
                price,
                self.contract_size,
                self.leverage,
                fee,
            );
            if required > self.equity - current_margin {
                events.push(vec![EVENT_REJECT, STATUS_REJECTED, order.order_id, -1]);
                continue;
            }
            self.equity += delta * (self.closes[bar] - price) * self.contract_size - fee;
            self.position += delta;
            fee_total += fee;
            turnover += notional;
            fills.push(vec![order.order_id as f64, order.side as f64, order.qty, price, fee]);
            events.push(vec![EVENT_FILL, STATUS_FILLED, order.order_id, -1]);
        }
        self.active_orders = retained;
        self.last_bar = Some(bar);
        let initial_margin = initial_margin(self.position, self.closes[bar], self.contract_size, self.leverage);
        let maintenance_margin = maintenance_margin(self.position, self.closes[bar], self.contract_size, self.maintenance_ratio);
        let active_orders = self
            .active_orders
            .iter()
            .map(|order| vec![order.order_id as f64, order.side as f64, order.order_type as f64, order.qty, order.price])
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
}

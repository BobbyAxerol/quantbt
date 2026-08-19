use std::collections::HashMap;
use std::hash::{BuildHasherDefault, Hasher};
use std::sync::Arc;

use super::accounting::{initial_margin, maintenance_margin, required_margin};
use super::matching::execution_price;
use super::types::{
    ACTION_AMEND, ACTION_CANCEL, ACTION_PLACE, ACTION_REPLACE, ActiveOrder, EVENT_AMEND,
    EVENT_CANCEL, EVENT_FILL, EVENT_PLACE, EVENT_REJECT, EVENT_REPLACE, FLAG_REDUCE_ONLY,
    MUTATE_PRICE, MUTATE_QTY, MUTATE_TRIGGER, ORDER_LIMIT, ORDER_MARKET, ORDER_STOP_LIMIT,
    ORDER_STOP_MARKET, SIDE_BUY, SIDE_SELL, STATUS_CANCELED, STATUS_FILLED, STATUS_PENDING,
    STATUS_REJECTED, StepResult,
};

pub struct PreparedMarketData {
    pub _timestamps_ns: Box<[i64]>,
    pub _opens: Box<[f64]>,
    pub highs: Box<[f64]>,
    pub lows: Box<[f64]>,
    pub closes: Box<[f64]>,
    pub _volumes: Box<[f64]>,
    pub _funding: Box<[f64]>,
    pub _funding_mask: Box<[bool]>,
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
            _timestamps_ns: timestamps_ns.into_boxed_slice(),
            _opens: opens.into_boxed_slice(),
            highs: highs.into_boxed_slice(),
            lows: lows.into_boxed_slice(),
            closes: closes.into_boxed_slice(),
            _volumes: volumes.into_boxed_slice(),
            _funding: funding.into_boxed_slice(),
            _funding_mask: funding_mask.into_boxed_slice(),
        })
    }

    pub fn len(&self) -> usize {
        self.closes.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.closes.is_empty()
    }
}

#[derive(Default)]
struct I64IdentityHasher(u64);

impl Hasher for I64IdentityHasher {
    fn finish(&self) -> u64 {
        self.0
    }

    fn write(&mut self, bytes: &[u8]) {
        let mut value = [0_u8; 8];
        let width = bytes.len().min(value.len());
        value[..width].copy_from_slice(&bytes[..width]);
        self.0 = u64::from_ne_bytes(value);
    }

    fn write_i64(&mut self, value: i64) {
        self.0 = value as u64;
    }
}

type OrderIdMap = HashMap<i64, usize, BuildHasherDefault<I64IdentityHasher>>;
const ORDER_INDEX_THRESHOLD: usize = 8;

struct OrderSlot {
    active: bool,
    order: ActiveOrder,
}

struct OrderTable {
    slots: Vec<OrderSlot>,
    id_to_slot: OrderIdMap,
    active_sequence: Vec<usize>,
    free_slots: Vec<usize>,
    tombstones: usize,
    active_count: usize,
}

impl OrderTable {
    fn new() -> Self {
        Self {
            slots: Vec::new(),
            id_to_slot: OrderIdMap::default(),
            active_sequence: Vec::new(),
            free_slots: Vec::new(),
            tombstones: 0,
            active_count: 0,
        }
    }

    fn insert(&mut self, order: ActiveOrder) {
        // A slot cannot be reused while its old sequence entry is still a
        // tombstone: replacement in the same bar must not appear twice in
        // priority order. Slots become reusable after compaction clears all
        // tombstones.
        let slot = if self.tombstones == 0 {
            self.free_slots.pop().unwrap_or_else(|| {
                let slot = self.slots.len();
                self.slots.push(OrderSlot {
                    active: false,
                    order,
                });
                slot
            })
        } else {
            let slot = self.slots.len();
            self.slots.push(OrderSlot {
                active: false,
                order,
            });
            slot
        };
        self.slots[slot] = OrderSlot {
            active: true,
            order,
        };
        if self.active_count == ORDER_INDEX_THRESHOLD {
            self.rebuild_index();
        }
        self.active_sequence.push(slot);
        self.active_count += 1;
        // Very small books use the priority sequence directly. This avoids a
        // hash allocation for the common one-order market/reduce-only path;
        // larger books keep O(1) ID lookup.
        if self.active_count > ORDER_INDEX_THRESHOLD {
            self.id_to_slot.entry(order.order_id).or_insert(slot);
        }
    }

    fn rebuild_index(&mut self) {
        self.id_to_slot.clear();
        for slot in self.active_sequence.iter().copied() {
            if let Some(order) = self.get_slot(slot) {
                self.id_to_slot.entry(order.order_id).or_insert(slot);
            }
        }
    }

    fn lookup_slot(&self, order_id: i64) -> Option<usize> {
        if self.active_count <= ORDER_INDEX_THRESHOLD {
            return self.active_sequence.iter().copied().find(|slot| {
                self.get_slot(*slot)
                    .is_some_and(|order| order.order_id == order_id)
            });
        }
        self.id_to_slot.get(&order_id).copied()
    }

    fn get_mut(&mut self, order_id: i64) -> Option<&mut ActiveOrder> {
        let slot = self.lookup_slot(order_id)?;
        self.slots.get_mut(slot).and_then(|slot| {
            if slot.active {
                Some(&mut slot.order)
            } else {
                None
            }
        })
    }

    fn get_slot(&self, slot: usize) -> Option<&ActiveOrder> {
        self.slots
            .get(slot)
            .and_then(|slot| if slot.active { Some(&slot.order) } else { None })
    }

    fn remove_by_id(&mut self, order_id: i64) -> Option<ActiveOrder> {
        let slot = self.lookup_slot(order_id)?;
        self.remove_slot(slot)
    }

    fn remove_slot(&mut self, slot: usize) -> Option<ActiveOrder> {
        let slot_state = self.slots.get_mut(slot)?;
        if !slot_state.active {
            return None;
        }
        slot_state.active = false;
        self.tombstones += 1;
        let order = slot_state.order;
        if self.id_to_slot.get(&order.order_id).copied() == Some(slot) {
            self.id_to_slot.remove(&order.order_id);
        }
        self.free_slots.push(slot);
        self.active_count = self.active_count.saturating_sub(1);
        Some(order)
    }

    fn compact_if_needed(&mut self) {
        // Compact a small live book earlier: market/reduce-only orders often
        // fill in the same bar, so scanning dozens of dead sequence entries
        // is slower than a bounded retain. Large live books still use the
        // original 25% tombstone ratio to avoid disturbing priority order too
        // often.
        if self.tombstones < 8 && self.tombstones.saturating_mul(4) < self.active_sequence.len() {
            return;
        }
        self.active_sequence.retain(|slot| {
            self.slots
                .get(*slot)
                .map(|slot_state| slot_state.active)
                .unwrap_or(false)
        });
        self.tombstones = 0;
    }

    fn reset(&mut self) {
        for slot in &mut self.slots {
            slot.active = false;
        }
        self.id_to_slot.clear();
        self.active_sequence.clear();
        self.free_slots.clear();
        self.free_slots.extend(0..self.slots.len());
        self.tombstones = 0;
        self.active_count = 0;
    }

    fn snapshot(&self) -> Vec<Vec<f64>> {
        self.active_sequence
            .iter()
            .filter_map(|slot| self.get_slot(*slot))
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
            .collect()
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
    initial_capital: f64,
    position: f64,
    equity: f64,
    active_orders: OrderTable,
    order_alias: HashMap<i64, i64>,
    last_bar: Option<usize>,
}

impl ReactiveSession {
    pub fn market_len(&self) -> usize {
        self.market.len()
    }

    pub fn next_bar(&self) -> usize {
        self.last_bar.map(|bar| bar + 1).unwrap_or(0)
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
            initial_capital,
            position: 0.0,
            equity: initial_capital,
            active_orders: OrderTable::new(),
            order_alias: HashMap::new(),
            last_bar: None,
        })
    }

    pub fn reset(&mut self) {
        self.active_orders.reset();
        self.order_alias.clear();
        self.position = 0.0;
        self.equity = self.initial_capital;
        self.last_bar = None;
    }

    pub fn step(
        &mut self,
        bar: usize,
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
        command_count: usize,
    ) -> Result<StepResult, String> {
        self.step_with_output(bar, codes, values, expiry, command_count, true)
    }

    pub fn step_with_output(
        &mut self,
        bar: usize,
        codes: &[i64],
        values: &[f64],
        _expiry: &[i64],
        command_count: usize,
        materialize: bool,
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
        let mut event_count = 0_i64;
        let mut rejected_count = 0_i64;
        let mut canceled_count = 0_i64;
        let mut record_event = |kind: i64, status: i64, order_id: i64, target_id: i64| {
            event_count += 1;
            if kind == EVENT_REJECT {
                rejected_count += 1;
            }
            if kind == EVENT_CANCEL {
                canceled_count += 1;
            }
            if materialize {
                events.push(vec![kind, status, order_id, target_id]);
            }
        };
        for index in 0..command_count {
            let code = &codes[index * 8..(index + 1) * 8];
            let value = &values[index * 3..(index + 1) * 3];
            match code[0] {
                ACTION_PLACE => {
                    let side = code[1];
                    let order_type = code[2];
                    if !valid_order(side, order_type, value[0], value[1], value[2]) {
                        record_event(EVENT_REJECT, STATUS_REJECTED, code[4], -1);
                        continue;
                    }
                    self.active_orders.insert(ActiveOrder {
                        order_id: code[4],
                        side,
                        order_type,
                        qty: value[0],
                        price: value[1],
                        trigger: value[2],
                        reduce_only: (code[3] & FLAG_REDUCE_ONLY) != 0,
                    });
                    record_event(EVENT_PLACE, STATUS_PENDING, code[4], -1);
                }
                ACTION_CANCEL => {
                    let target = self.resolve_order_id(code[5]);
                    if self.active_orders.remove_by_id(target).is_some() {
                        record_event(EVENT_CANCEL, STATUS_FILLED, -1, code[5]);
                    } else {
                        record_event(EVENT_REJECT, STATUS_REJECTED, -1, code[5]);
                    }
                }
                ACTION_AMEND => {
                    let target = self.resolve_order_id(code[5]);
                    if let Some(order) = self.active_orders.get_mut(target) {
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
                        record_event(EVENT_AMEND, STATUS_FILLED, -1, code[5]);
                    } else {
                        record_event(EVENT_REJECT, STATUS_REJECTED, -1, code[5]);
                    }
                }
                ACTION_REPLACE => {
                    let target = self.resolve_order_id(code[5]);
                    if self.active_orders.remove_by_id(target).is_some() {
                        record_event(EVENT_REPLACE, STATUS_CANCELED, code[4], code[5]);
                        let side = code[1];
                        let order_type = code[2];
                        if !valid_order(side, order_type, value[0], value[1], value[2]) {
                            record_event(EVENT_REJECT, STATUS_REJECTED, code[4], code[5]);
                            continue;
                        }
                        self.active_orders.insert(ActiveOrder {
                            order_id: code[4],
                            side,
                            order_type,
                            qty: value[0],
                            price: value[1],
                            trigger: value[2],
                            reduce_only: (code[3] & FLAG_REDUCE_ONLY) != 0,
                        });
                        self.order_alias.insert(code[5], code[4]);
                        record_event(EVENT_REPLACE, STATUS_PENDING, code[4], code[5]);
                    } else {
                        record_event(EVENT_REJECT, STATUS_REJECTED, code[4], code[5]);
                    }
                }
                _ => record_event(EVENT_REJECT, STATUS_REJECTED, code[4], code[5]),
            }
        }

        let mut fills = Vec::new();
        let mut fill_count = 0_i64;
        let active_sequence_len = self.active_orders.active_sequence.len();
        for sequence_index in 0..active_sequence_len {
            let slot = self.active_orders.active_sequence[sequence_index];
            let Some(order) = self.active_orders.get_slot(slot).copied() else {
                continue;
            };
            let Some(price) = execution_price(
                &order,
                self.market.highs[bar],
                self.market.lows[bar],
                self.market.closes[bar],
                self.slippage_rate,
            ) else {
                continue;
            };
            let mut qty = order.qty;
            if order.reduce_only {
                if self.position == 0.0
                    || (self.position > 0.0 && order.side == SIDE_BUY)
                    || (self.position < 0.0 && order.side == SIDE_SELL)
                {
                    self.active_orders.remove_slot(slot);
                    record_event(EVENT_CANCEL, STATUS_CANCELED, order.order_id, -1);
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
                self.active_orders.remove_slot(slot);
                record_event(EVENT_REJECT, STATUS_REJECTED, order.order_id, -1);
                continue;
            }
            self.equity += delta * (self.market.closes[bar] - price) * self.contract_size - fee;
            self.position += delta;
            fee_total += fee;
            turnover += notional;
            fill_count += 1;
            if materialize {
                fills.push(vec![
                    order.order_id as f64,
                    order.side as f64,
                    qty,
                    price,
                    fee,
                ]);
            }
            self.active_orders.remove_slot(slot);
            record_event(EVENT_FILL, STATUS_FILLED, order.order_id, -1);
        }
        self.active_orders.compact_if_needed();
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
        let active_orders = if materialize {
            self.active_orders.snapshot()
        } else {
            Vec::new()
        };
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
            fill_count,
            event_count,
            rejected_count,
            canceled_count,
        })
    }

    fn resolve_order_id(&mut self, order_id: i64) -> i64 {
        let mut resolved = order_id;
        let mut path = [0_i64; 64];
        let mut path_len = 0;
        // A replacement can itself be replaced. The fixed stack path keeps
        // normal alias resolution allocation-free and the guard prevents a
        // malformed tape from creating an infinite alias cycle.
        for _ in 0..64 {
            if path_len < path.len() {
                path[path_len] = resolved;
                path_len += 1;
            }
            let Some(next) = self.order_alias.get(&resolved) else {
                break;
            };
            if *next == resolved {
                break;
            }
            if path[..path_len].contains(next) {
                break;
            }
            resolved = *next;
        }
        for old_id in path[..path_len].iter().copied() {
            if old_id != resolved {
                self.order_alias.insert(old_id, resolved);
            }
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

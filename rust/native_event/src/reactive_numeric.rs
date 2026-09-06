//! Numeric Python/Rust reactive co-runtime (R1).
//!
//! This module deliberately keeps the strategy decision in Python while the
//! canonical market clock, order lifecycle, account state, and dense result
//! buffers remain Rust-owned for the whole run.  It is an explicit R1 route:
//! every bar still calls Python, but it does not return to Python between the
//! engine transition and the next callback boundary.

use std::collections::{BTreeMap, HashSet};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use numpy::{PyArray1, PyReadonlyArray1};
use pyo3::exceptions::{PyAttributeError, PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyDict, PyList, PyType};

use quantbt_engine as full;
use quantbt_engine::{FullMarketData, FullSession};

use crate::FullPreparedMarketCore;
use crate::reactive_hot_loop::ReusableWakeObservationV1;
use crate::reactive_score::{ReactiveOnlineScoreV1, ReactiveScoreSnapshotV1};

const MARKET_OPEN: u8 = 1 << 0;
const MARKET_HIGH: u8 = 1 << 1;
const MARKET_LOW: u8 = 1 << 2;
const MARKET_CLOSE: u8 = 1 << 3;
const MARKET_VOLUME: u8 = 1 << 4;

const ACCOUNT_EQUITY: u8 = 1 << 0;
const ACCOUNT_AVAILABLE_EQUITY: u8 = 1 << 1;
const ACCOUNT_INITIAL_MARGIN: u8 = 1 << 2;
const ACCOUNT_MAINTENANCE_MARGIN: u8 = 1 << 3;
const ACCOUNT_LIQUIDATED: u8 = 1 << 4;

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
const ACTIVATION_IMMEDIATE: i64 = 0;

const FLAG_REDUCE_ONLY: i64 = 1;

const WAKE_INITIAL: i64 = 1 << 0;
const WAKE_TIME: i64 = 1 << 1;
const WAKE_FILL: i64 = 1 << 2;
const WAKE_ORDER_EVENT: i64 = 1 << 3;
const WAKE_LIQUIDATION: i64 = 1 << 4;
const WAKE_FUNDING: i64 = 1 << 5;
const WAKE_PRICE_CROSS: i64 = 1 << 6;
const WAKE_POSITION_THRESHOLD: i64 = 1 << 7;
const WAKE_EQUITY_THRESHOLD: i64 = 1 << 8;
const WAKE_MARGIN_THRESHOLD: i64 = 1 << 9;
const WAKE_BLOCK_INVALIDATED: i64 = 1 << 10;

const CALLBACK_INITIALIZE: i64 = 0;
const CALLBACK_FINALIZE: i64 = 2;
const CALLBACK_WAKE: i64 = 3;
const CALLBACK_BLOCK: i64 = 4;

/// Bounded cooperative check interval for a detached native reactive gap.
/// It is a bar-clock limit, never a data-dependent optimization shortcut.
const REACTIVE_CANCEL_CHECK_INTERVAL_BARS: usize = 64;

const REACTIVE_CANCELLED_MESSAGE: &str =
    "reactive native execution canceled at a certified bar boundary";
const REACTIVE_DEADLINE_MESSAGE: &str =
    "reactive native execution deadline exceeded at a certified bar boundary";

fn stale_context_error() -> PyErr {
    PyRuntimeError::new_err(
        "ReactiveContextBufferV1 is ephemeral and is no longer valid; copy primitive values inside the callback",
    )
}

fn stale_command_error() -> PyErr {
    PyRuntimeError::new_err(
        "ReactiveCommandBufferV2 is only writable during its active strategy callback",
    )
}

/// Thread-safe cancellation handle for one prepared reactive runner.
///
/// The token owns no market, account, command, or strategy state.  A caller
/// may retain it past a run/reset without being able to mutate an earlier
/// result.  The runner checks it only at deterministic native bar intervals
/// and aborts before publishing a partial score.
#[pyclass(name = "ReactiveCancellationTokenV1", module = "_quantbt_native")]
pub(crate) struct ReactiveCancellationTokenCore {
    requested: Arc<AtomicBool>,
}

#[pymethods]
impl ReactiveCancellationTokenCore {
    fn cancel(&self) {
        self.requested.store(true, Ordering::Release);
    }

    fn clear(&self) {
        self.requested.store(false, Ordering::Release);
    }

    #[getter]
    fn canceled(&self) -> bool {
        self.requested.load(Ordering::Acquire)
    }
}

fn numeric_enum(
    value: &Bound<'_, PyAny>,
    label: &str,
    accepted: &[(&str, i64)],
    numeric_values: &[i64],
) -> PyResult<i64> {
    if let Ok(code) = value.extract::<i64>()
        && numeric_values.contains(&code)
    {
        return Ok(code);
    }
    let raw = value
        .extract::<String>()
        .or_else(|_| value.getattr("value")?.extract::<String>())
        .map_err(|_| {
            PyValueError::new_err(format!(
                "{label} must be a supported numeric code or string"
            ))
        })?;
    let normalized = raw.to_ascii_lowercase();
    accepted
        .iter()
        .find_map(|(name, code)| (*name == normalized).then_some(*code))
        .ok_or_else(|| PyValueError::new_err(format!("unsupported {label}={raw:?}")))
}

fn optional_enum(
    value: Option<&Bound<'_, PyAny>>,
    default: i64,
    label: &str,
    accepted: &[(&str, i64)],
    numeric_values: &[i64],
) -> PyResult<i64> {
    match value {
        Some(value) => numeric_enum(value, label, accepted, numeric_values),
        None => Ok(default),
    }
}

#[pyclass]
pub(crate) struct ReactiveContextBufferV1 {
    market: Arc<FullMarketData>,
    generation: u64,
    active: bool,
    bar_index: usize,
    timestamp_ns: i64,
    wake_reason_mask: i64,
    market_mask: u8,
    account_mask: u8,
    positions_enabled: bool,
    need_fills: bool,
    need_events: bool,
    need_active_orders: bool,
    equity: f64,
    initial_margin: f64,
    maintenance_margin: f64,
    liquidated: bool,
    positions: Vec<f64>,
    fill_order_id: Vec<i64>,
    fill_symbol: Vec<i64>,
    fill_side: Vec<i64>,
    fill_qty: Vec<f64>,
    fill_price: Vec<f64>,
    fill_fee: Vec<f64>,
    event_kind: Vec<i64>,
    event_status: Vec<i64>,
    event_order_id: Vec<i64>,
    event_target_id: Vec<i64>,
    event_symbol: Vec<i64>,
    event_reject_code: Vec<i64>,
    active_order_id: Vec<i64>,
    active_symbol: Vec<i64>,
    active_side: Vec<i64>,
    active_order_type: Vec<i64>,
    active_qty: Vec<f64>,
    active_price: Vec<f64>,
    active_trigger: Vec<f64>,
}

impl ReactiveContextBufferV1 {
    #[allow(clippy::too_many_arguments)]
    fn new_internal(
        market: Arc<FullMarketData>,
        market_mask: u8,
        account_mask: u8,
        positions_enabled: bool,
        need_fills: bool,
        need_events: bool,
        need_active_orders: bool,
    ) -> Self {
        Self {
            positions: vec![0.0; market.n_symbols],
            market,
            generation: 0,
            active: false,
            bar_index: 0,
            timestamp_ns: 0,
            wake_reason_mask: 0,
            market_mask,
            account_mask,
            positions_enabled,
            need_fills,
            need_events,
            need_active_orders,
            equity: 0.0,
            initial_margin: 0.0,
            maintenance_margin: 0.0,
            liquidated: false,
            fill_order_id: Vec::new(),
            fill_symbol: Vec::new(),
            fill_side: Vec::new(),
            fill_qty: Vec::new(),
            fill_price: Vec::new(),
            fill_fee: Vec::new(),
            event_kind: Vec::new(),
            event_status: Vec::new(),
            event_order_id: Vec::new(),
            event_target_id: Vec::new(),
            event_symbol: Vec::new(),
            event_reject_code: Vec::new(),
            active_order_id: Vec::new(),
            active_symbol: Vec::new(),
            active_side: Vec::new(),
            active_order_type: Vec::new(),
            active_qty: Vec::new(),
            active_price: Vec::new(),
            active_trigger: Vec::new(),
        }
    }

    fn check(&self) -> PyResult<()> {
        if !self.active {
            return Err(stale_context_error());
        }
        Ok(())
    }

    fn require_market(&self, bit: u8, name: &str) -> PyResult<()> {
        self.check()?;
        if self.market_mask & bit == 0 {
            return Err(PyAttributeError::new_err(format!(
                "strategy did not declare market field {name:?}"
            )));
        }
        Ok(())
    }

    fn require_account(&self, bit: u8, name: &str) -> PyResult<()> {
        self.check()?;
        if self.account_mask & bit == 0 {
            return Err(PyAttributeError::new_err(format!(
                "strategy did not declare account field {name:?}"
            )));
        }
        Ok(())
    }

    fn market_value(&self, field: u8, symbol_id: usize, name: &str) -> PyResult<f64> {
        let bit = match field {
            0 => MARKET_OPEN,
            1 => MARKET_HIGH,
            2 => MARKET_LOW,
            3 => MARKET_CLOSE,
            4 => MARKET_VOLUME,
            _ => return Err(PyValueError::new_err("unsupported numeric market field")),
        };
        self.require_market(bit, name)?;
        if symbol_id >= self.market.n_symbols {
            return Err(PyValueError::new_err(
                "symbol_id is outside the prepared market",
            ));
        }
        let offset = self.bar_index * self.market.n_symbols + symbol_id;
        let value = match field {
            0 => self.market.opens[offset],
            1 => self.market.highs[offset],
            2 => self.market.lows[offset],
            3 => self.market.closes[offset],
            4 => self.market.volumes[offset],
            _ => unreachable!(),
        };
        Ok(value)
    }

    #[allow(clippy::too_many_arguments)]
    fn refresh(
        &mut self,
        session: &FullSession,
        bar: usize,
        wake_reason_mask: i64,
        step: &full::FullStepResult,
        buffers: &full::StepBuffers,
    ) -> PyResult<usize> {
        self.generation = self.generation.wrapping_add(1);
        self.active = true;
        self.bar_index = bar;
        self.wake_reason_mask = wake_reason_mask;
        self.timestamp_ns = session
            .timestamp_ns_at(bar)
            .map_err(PyValueError::new_err)?;
        self.equity = step.equity;
        self.initial_margin = step.initial_margin;
        self.maintenance_margin = step.maintenance_margin;
        self.liquidated = step.liquidated;
        let mut copied = 0_usize;
        if self.positions_enabled {
            self.positions.clone_from(&session.positions);
            copied += self.positions.len() * std::mem::size_of::<f64>();
        } else {
            self.positions.clear();
        }
        if self.need_fills {
            self.fill_order_id.clone_from(&buffers.fills.order_id);
            self.fill_symbol.clone_from(&buffers.fills.symbol);
            self.fill_side.clone_from(&buffers.fills.side);
            self.fill_qty.clone_from(&buffers.fills.qty);
            self.fill_price.clone_from(&buffers.fills.price);
            self.fill_fee.clone_from(&buffers.fills.fee);
            copied += self.fill_order_id.len()
                * (3 * std::mem::size_of::<i64>() + 3 * std::mem::size_of::<f64>());
        } else {
            self.fill_order_id.clear();
            self.fill_symbol.clear();
            self.fill_side.clear();
            self.fill_qty.clear();
            self.fill_price.clear();
            self.fill_fee.clear();
        }
        if self.need_events {
            self.event_kind.clone_from(&buffers.events.kind);
            self.event_status.clone_from(&buffers.events.status);
            self.event_order_id.clone_from(&buffers.events.order_id);
            self.event_target_id.clone_from(&buffers.events.target_id);
            self.event_symbol.clone_from(&buffers.events.symbol);
            self.event_reject_code
                .clone_from(&buffers.events.reject_code);
            copied += self.event_kind.len() * 6 * std::mem::size_of::<i64>();
        } else {
            self.event_kind.clear();
            self.event_status.clear();
            self.event_order_id.clear();
            self.event_target_id.clear();
            self.event_symbol.clear();
            self.event_reject_code.clear();
        }
        if self.need_active_orders {
            self.active_order_id
                .clone_from(&buffers.active_orders.order_id);
            self.active_symbol.clone_from(&buffers.active_orders.symbol);
            self.active_side.clone_from(&buffers.active_orders.side);
            self.active_order_type
                .clone_from(&buffers.active_orders.order_type);
            self.active_qty.clone_from(&buffers.active_orders.qty);
            self.active_price.clone_from(&buffers.active_orders.price);
            self.active_trigger
                .clone_from(&buffers.active_orders.trigger);
            copied += self.active_order_id.len()
                * (4 * std::mem::size_of::<i64>() + 3 * std::mem::size_of::<f64>());
        } else {
            self.active_order_id.clear();
            self.active_symbol.clear();
            self.active_side.clear();
            self.active_order_type.clear();
            self.active_qty.clear();
            self.active_price.clear();
            self.active_trigger.clear();
        }
        Ok(copied)
    }

    fn invalidate_internal(&mut self) {
        self.active = false;
    }
}

#[pymethods]
impl ReactiveContextBufferV1 {
    #[getter]
    fn generation(&self) -> u64 {
        self.generation
    }

    #[getter]
    fn bar_index(&self) -> PyResult<usize> {
        self.check()?;
        Ok(self.bar_index)
    }

    #[getter]
    fn timestamp_ns(&self) -> PyResult<i64> {
        self.check()?;
        Ok(self.timestamp_ns)
    }

    #[getter]
    fn wake_reason_mask(&self) -> PyResult<i64> {
        self.check()?;
        Ok(self.wake_reason_mask)
    }

    fn has_wake_reason(&self, reason_mask: i64) -> PyResult<bool> {
        self.check()?;
        Ok(self.wake_reason_mask & reason_mask != 0)
    }

    #[getter]
    fn symbol_count(&self) -> usize {
        self.market.n_symbols
    }

    fn open(&self, symbol_id: usize) -> PyResult<f64> {
        self.market_value(0, symbol_id, "open")
    }

    fn high(&self, symbol_id: usize) -> PyResult<f64> {
        self.market_value(1, symbol_id, "high")
    }

    fn low(&self, symbol_id: usize) -> PyResult<f64> {
        self.market_value(2, symbol_id, "low")
    }

    fn close(&self, symbol_id: usize) -> PyResult<f64> {
        self.market_value(3, symbol_id, "close")
    }

    fn volume(&self, symbol_id: usize) -> PyResult<f64> {
        self.market_value(4, symbol_id, "volume")
    }

    fn position_qty(&self, symbol_id: usize) -> PyResult<f64> {
        self.check()?;
        if !self.positions_enabled {
            return Err(PyAttributeError::new_err(
                "strategy did not declare positions",
            ));
        }
        self.positions
            .get(symbol_id)
            .copied()
            .ok_or_else(|| PyValueError::new_err("symbol_id is outside the prepared market"))
    }

    #[getter]
    fn equity(&self) -> PyResult<f64> {
        self.require_account(ACCOUNT_EQUITY, "equity")?;
        Ok(self.equity)
    }

    #[getter]
    fn available_equity(&self) -> PyResult<f64> {
        self.require_account(ACCOUNT_AVAILABLE_EQUITY, "available_equity")?;
        Ok(self.equity - self.initial_margin)
    }

    #[getter]
    fn initial_margin(&self) -> PyResult<f64> {
        self.require_account(ACCOUNT_INITIAL_MARGIN, "initial_margin")?;
        Ok(self.initial_margin)
    }

    #[getter]
    fn maintenance_margin(&self) -> PyResult<f64> {
        self.require_account(ACCOUNT_MAINTENANCE_MARGIN, "maintenance_margin")?;
        Ok(self.maintenance_margin)
    }

    #[getter]
    fn liquidated(&self) -> PyResult<bool> {
        self.require_account(ACCOUNT_LIQUIDATED, "liquidated")?;
        Ok(self.liquidated)
    }

    #[getter]
    fn new_fill_count(&self) -> PyResult<usize> {
        self.check()?;
        Ok(self.fill_order_id.len())
    }

    #[getter]
    fn new_event_count(&self) -> PyResult<usize> {
        self.check()?;
        Ok(self.event_kind.len())
    }

    #[getter]
    fn active_order_count(&self) -> PyResult<usize> {
        self.check()?;
        Ok(self.active_order_id.len())
    }

    fn fill_order_handle(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.fill_order_id
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("fill index is outside the current delta"))
    }

    fn fill_symbol_id(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.fill_symbol
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("fill index is outside the current delta"))
    }

    fn fill_side(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.fill_side
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("fill index is outside the current delta"))
    }

    fn fill_qty(&self, index: usize) -> PyResult<f64> {
        self.check()?;
        self.fill_qty
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("fill index is outside the current delta"))
    }

    fn fill_price(&self, index: usize) -> PyResult<f64> {
        self.check()?;
        self.fill_price
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("fill index is outside the current delta"))
    }

    fn fill_fee(&self, index: usize) -> PyResult<f64> {
        self.check()?;
        self.fill_fee
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("fill index is outside the current delta"))
    }

    fn event_kind(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.event_kind
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("event index is outside the current delta"))
    }

    fn event_status(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.event_status
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("event index is outside the current delta"))
    }

    fn event_order_handle(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.event_order_id
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("event index is outside the current delta"))
    }

    fn event_target_handle(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.event_target_id
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("event index is outside the current delta"))
    }

    fn event_symbol_id(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.event_symbol
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("event index is outside the current delta"))
    }

    fn event_reject_code(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.event_reject_code
            .get(index)
            .copied()
            .ok_or_else(|| PyValueError::new_err("event index is outside the current delta"))
    }

    fn active_order_handle(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.active_order_id.get(index).copied().ok_or_else(|| {
            PyValueError::new_err("active-order index is outside the current snapshot")
        })
    }

    fn active_order_symbol_id(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.active_symbol.get(index).copied().ok_or_else(|| {
            PyValueError::new_err("active-order index is outside the current snapshot")
        })
    }

    fn active_order_side(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.active_side.get(index).copied().ok_or_else(|| {
            PyValueError::new_err("active-order index is outside the current snapshot")
        })
    }

    fn active_order_type(&self, index: usize) -> PyResult<i64> {
        self.check()?;
        self.active_order_type.get(index).copied().ok_or_else(|| {
            PyValueError::new_err("active-order index is outside the current snapshot")
        })
    }

    fn active_order_qty(&self, index: usize) -> PyResult<f64> {
        self.check()?;
        self.active_qty.get(index).copied().ok_or_else(|| {
            PyValueError::new_err("active-order index is outside the current snapshot")
        })
    }

    fn active_order_price(&self, index: usize) -> PyResult<f64> {
        self.check()?;
        self.active_price.get(index).copied().ok_or_else(|| {
            PyValueError::new_err("active-order index is outside the current snapshot")
        })
    }

    fn active_order_trigger_price(&self, index: usize) -> PyResult<f64> {
        self.check()?;
        self.active_trigger.get(index).copied().ok_or_else(|| {
            PyValueError::new_err("active-order index is outside the current snapshot")
        })
    }
}

#[pyclass]
pub(crate) struct ReactiveCommandBufferV2 {
    generation: u64,
    active: bool,
    hard_limit: usize,
    capacity: usize,
    length: usize,
    growth_count: u64,
    high_water_mark: usize,
    next_handle: i64,
    seen_place_handles: HashSet<i64>,
    action: Vec<i64>,
    symbol_id: Vec<i64>,
    side: Vec<i64>,
    order_type: Vec<i64>,
    tif: Vec<i64>,
    flags: Vec<i64>,
    order_handle: Vec<i64>,
    target_handle: Vec<i64>,
    parent_handle: Vec<i64>,
    group_handle: Vec<i64>,
    oco_handle: Vec<i64>,
    activation: Vec<i64>,
    effective_bar: Vec<i64>,
    qty: Vec<f64>,
    price: Vec<f64>,
    trigger_price: Vec<f64>,
}

impl ReactiveCommandBufferV2 {
    fn with_limits(initial_capacity: usize, hard_limit: usize) -> PyResult<Self> {
        if initial_capacity == 0 || hard_limit == 0 || initial_capacity > hard_limit {
            return Err(PyValueError::new_err(
                "ReactiveCommandBufferV2 requires 0 < initial_capacity <= hard_limit",
            ));
        }
        Ok(Self {
            generation: 0,
            active: false,
            hard_limit,
            capacity: initial_capacity,
            length: 0,
            growth_count: 0,
            high_water_mark: 0,
            next_handle: 1,
            seen_place_handles: HashSet::new(),
            action: Vec::with_capacity(initial_capacity),
            symbol_id: Vec::with_capacity(initial_capacity),
            side: Vec::with_capacity(initial_capacity),
            order_type: Vec::with_capacity(initial_capacity),
            tif: Vec::with_capacity(initial_capacity),
            flags: Vec::with_capacity(initial_capacity),
            order_handle: Vec::with_capacity(initial_capacity),
            target_handle: Vec::with_capacity(initial_capacity),
            parent_handle: Vec::with_capacity(initial_capacity),
            group_handle: Vec::with_capacity(initial_capacity),
            oco_handle: Vec::with_capacity(initial_capacity),
            activation: Vec::with_capacity(initial_capacity),
            effective_bar: Vec::with_capacity(initial_capacity),
            qty: Vec::with_capacity(initial_capacity),
            price: Vec::with_capacity(initial_capacity),
            trigger_price: Vec::with_capacity(initial_capacity),
        })
    }

    fn check_active(&self) -> PyResult<()> {
        if !self.active {
            return Err(stale_command_error());
        }
        Ok(())
    }

    fn begin_callback(&mut self) {
        self.length = 0;
        self.action.clear();
        self.symbol_id.clear();
        self.side.clear();
        self.order_type.clear();
        self.tif.clear();
        self.flags.clear();
        self.order_handle.clear();
        self.target_handle.clear();
        self.parent_handle.clear();
        self.group_handle.clear();
        self.oco_handle.clear();
        self.activation.clear();
        self.effective_bar.clear();
        self.qty.clear();
        self.price.clear();
        self.trigger_price.clear();
        self.generation = self.generation.wrapping_add(1);
        self.active = true;
    }

    fn end_callback(&mut self) {
        self.active = false;
    }

    fn reset_session(&mut self) {
        self.begin_callback();
        self.end_callback();
        self.next_handle = 1;
        self.seen_place_handles.clear();
    }

    fn reserve_row(&mut self) -> PyResult<()> {
        self.check_active()?;
        if self.length >= self.hard_limit {
            return Err(PyRuntimeError::new_err(format!(
                "ReactiveCommandBufferV2 command capacity exceeded: {}",
                self.hard_limit
            )));
        }
        if self.length >= self.capacity {
            let target = (self.capacity.saturating_mul(2))
                .max(self.length + 1)
                .min(self.hard_limit);
            let additional = target.saturating_sub(self.capacity);
            for values in [
                &mut self.action,
                &mut self.symbol_id,
                &mut self.side,
                &mut self.order_type,
                &mut self.tif,
                &mut self.flags,
                &mut self.order_handle,
                &mut self.target_handle,
                &mut self.parent_handle,
                &mut self.group_handle,
                &mut self.oco_handle,
                &mut self.activation,
                &mut self.effective_bar,
            ] {
                values.reserve(additional);
            }
            for values in [&mut self.qty, &mut self.price, &mut self.trigger_price] {
                values.reserve(additional);
            }
            self.capacity = target;
            self.growth_count = self.growth_count.saturating_add(1);
        }
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    fn push(
        &mut self,
        action: i64,
        symbol_id: i64,
        side: i64,
        order_type: i64,
        qty: f64,
        price: f64,
        trigger_price: f64,
        tif: i64,
        reduce_only: bool,
        order_handle: i64,
        target_handle: i64,
        parent_handle: i64,
        group_handle: i64,
        oco_handle: i64,
        activation: i64,
        effective_bar: i64,
    ) -> PyResult<i64> {
        self.reserve_row()?;
        if matches!(action, ACTION_PLACE | ACTION_REPLACE) {
            if symbol_id < 0 || !matches!(side, 1 | -1) || !matches!(order_type, 0..=3) {
                return Err(PyValueError::new_err(
                    "PLACE/REPLACE requires valid symbol_id, side, and order_type",
                ));
            }
            if !qty.is_finite() || qty <= 0.0 {
                return Err(PyValueError::new_err("PLACE/REPLACE requires qty > 0"));
            }
            if !self.seen_place_handles.insert(order_handle) {
                return Err(PyValueError::new_err(format!(
                    "duplicate numeric order_handle={order_handle}"
                )));
            }
        }
        self.action.push(action);
        self.symbol_id.push(symbol_id);
        self.side.push(side);
        self.order_type.push(order_type);
        self.tif.push(tif);
        self.flags
            .push(if reduce_only { FLAG_REDUCE_ONLY } else { 0 });
        self.order_handle.push(order_handle);
        self.target_handle.push(target_handle);
        self.parent_handle.push(parent_handle);
        self.group_handle.push(group_handle);
        self.oco_handle.push(oco_handle);
        self.activation.push(activation);
        self.effective_bar.push(effective_bar);
        self.qty.push(qty);
        self.price.push(price);
        self.trigger_price.push(trigger_price);
        self.length += 1;
        self.high_water_mark = self.high_water_mark.max(self.length);
        Ok(order_handle)
    }

    fn next_order_handle(&mut self, supplied: Option<i64>) -> PyResult<i64> {
        let handle = supplied.unwrap_or_else(|| {
            let value = self.next_handle;
            self.next_handle = self.next_handle.saturating_add(1);
            value
        });
        if handle < 0 {
            return Err(PyValueError::new_err("order_handle must be >= 0"));
        }
        Ok(handle)
    }
}

#[pymethods]
impl ReactiveCommandBufferV2 {
    #[new]
    #[pyo3(signature = (initial_capacity=8, hard_limit=65_536))]
    fn new(initial_capacity: usize, hard_limit: usize) -> PyResult<Self> {
        Self::with_limits(initial_capacity, hard_limit)
    }

    #[getter]
    fn generation(&self) -> u64 {
        self.generation
    }

    #[getter]
    fn length(&self) -> usize {
        self.length
    }

    #[getter]
    fn capacity(&self) -> usize {
        self.capacity
    }

    #[getter]
    fn growth_count(&self) -> u64 {
        self.growth_count
    }

    #[getter]
    fn high_water_mark(&self) -> usize {
        self.high_water_mark
    }

    // This flat signature is the stable Python command surface; grouping it
    // would be a breaking API change, so the arity is intentional.
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (symbol_id, side, qty, *, order_handle=None, tif=None, reduce_only=false, parent_handle=None, group_handle=None, oco_handle=None, activation=None, effective_bar=None))]
    fn market(
        &mut self,
        symbol_id: i64,
        side: &Bound<'_, PyAny>,
        qty: f64,
        order_handle: Option<i64>,
        tif: Option<&Bound<'_, PyAny>>,
        reduce_only: bool,
        parent_handle: Option<i64>,
        group_handle: Option<i64>,
        oco_handle: Option<i64>,
        activation: Option<&Bound<'_, PyAny>>,
        effective_bar: Option<i64>,
    ) -> PyResult<i64> {
        let side = numeric_enum(side, "side", &[("buy", 1), ("sell", -1)], &[1, -1])?;
        let tif = optional_enum(
            tif,
            TIF_GTC,
            "tif",
            &[("gtc", 0), ("ioc", 1), ("fok", 2), ("gtd", 3)],
            &[0, 1, 2, 3],
        )?;
        let activation = optional_enum(
            activation,
            ACTIVATION_IMMEDIATE,
            "activation",
            &[
                ("immediate", 0),
                ("on_parent_first_fill", 1),
                ("on_parent_full_fill", 2),
            ],
            &[0, 1, 2],
        )?;
        let handle = self.next_order_handle(order_handle)?;
        self.push(
            ACTION_PLACE,
            symbol_id,
            side,
            ORDER_MARKET,
            qty,
            f64::NAN,
            f64::NAN,
            tif,
            reduce_only,
            handle,
            -1,
            parent_handle.unwrap_or(-1),
            group_handle.unwrap_or(-1),
            oco_handle.unwrap_or(-1),
            activation,
            effective_bar.unwrap_or(-1),
        )
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (symbol_id, side, qty, price, *, order_handle=None, tif=None, reduce_only=false, parent_handle=None, group_handle=None, oco_handle=None, activation=None, effective_bar=None))]
    fn limit(
        &mut self,
        symbol_id: i64,
        side: &Bound<'_, PyAny>,
        qty: f64,
        price: f64,
        order_handle: Option<i64>,
        tif: Option<&Bound<'_, PyAny>>,
        reduce_only: bool,
        parent_handle: Option<i64>,
        group_handle: Option<i64>,
        oco_handle: Option<i64>,
        activation: Option<&Bound<'_, PyAny>>,
        effective_bar: Option<i64>,
    ) -> PyResult<i64> {
        if !price.is_finite() || price <= 0.0 {
            return Err(PyValueError::new_err("LIMIT requires price > 0"));
        }
        let side = numeric_enum(side, "side", &[("buy", 1), ("sell", -1)], &[1, -1])?;
        let tif = optional_enum(
            tif,
            TIF_GTC,
            "tif",
            &[("gtc", 0), ("ioc", 1), ("fok", 2), ("gtd", 3)],
            &[0, 1, 2, 3],
        )?;
        let activation = optional_enum(
            activation,
            ACTIVATION_IMMEDIATE,
            "activation",
            &[
                ("immediate", 0),
                ("on_parent_first_fill", 1),
                ("on_parent_full_fill", 2),
            ],
            &[0, 1, 2],
        )?;
        let handle = self.next_order_handle(order_handle)?;
        self.push(
            ACTION_PLACE,
            symbol_id,
            side,
            ORDER_LIMIT,
            qty,
            price,
            f64::NAN,
            tif,
            reduce_only,
            handle,
            -1,
            parent_handle.unwrap_or(-1),
            group_handle.unwrap_or(-1),
            oco_handle.unwrap_or(-1),
            activation,
            effective_bar.unwrap_or(-1),
        )
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (symbol_id, side, qty, trigger_price, *, order_handle=None, tif=None, reduce_only=false, parent_handle=None, group_handle=None, oco_handle=None, activation=None, effective_bar=None))]
    fn stop_market(
        &mut self,
        symbol_id: i64,
        side: &Bound<'_, PyAny>,
        qty: f64,
        trigger_price: f64,
        order_handle: Option<i64>,
        tif: Option<&Bound<'_, PyAny>>,
        reduce_only: bool,
        parent_handle: Option<i64>,
        group_handle: Option<i64>,
        oco_handle: Option<i64>,
        activation: Option<&Bound<'_, PyAny>>,
        effective_bar: Option<i64>,
    ) -> PyResult<i64> {
        if !trigger_price.is_finite() || trigger_price <= 0.0 {
            return Err(PyValueError::new_err(
                "STOP_MARKET requires trigger_price > 0",
            ));
        }
        let side = numeric_enum(side, "side", &[("buy", 1), ("sell", -1)], &[1, -1])?;
        let tif = optional_enum(
            tif,
            TIF_GTC,
            "tif",
            &[("gtc", 0), ("ioc", 1), ("fok", 2), ("gtd", 3)],
            &[0, 1, 2, 3],
        )?;
        let activation = optional_enum(
            activation,
            ACTIVATION_IMMEDIATE,
            "activation",
            &[
                ("immediate", 0),
                ("on_parent_first_fill", 1),
                ("on_parent_full_fill", 2),
            ],
            &[0, 1, 2],
        )?;
        let handle = self.next_order_handle(order_handle)?;
        self.push(
            ACTION_PLACE,
            symbol_id,
            side,
            ORDER_STOP_MARKET,
            qty,
            f64::NAN,
            trigger_price,
            tif,
            reduce_only,
            handle,
            -1,
            parent_handle.unwrap_or(-1),
            group_handle.unwrap_or(-1),
            oco_handle.unwrap_or(-1),
            activation,
            effective_bar.unwrap_or(-1),
        )
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (symbol_id, side, qty, price, trigger_price, *, order_handle=None, tif=None, reduce_only=false, parent_handle=None, group_handle=None, oco_handle=None, activation=None, effective_bar=None))]
    fn stop_limit(
        &mut self,
        symbol_id: i64,
        side: &Bound<'_, PyAny>,
        qty: f64,
        price: f64,
        trigger_price: f64,
        order_handle: Option<i64>,
        tif: Option<&Bound<'_, PyAny>>,
        reduce_only: bool,
        parent_handle: Option<i64>,
        group_handle: Option<i64>,
        oco_handle: Option<i64>,
        activation: Option<&Bound<'_, PyAny>>,
        effective_bar: Option<i64>,
    ) -> PyResult<i64> {
        if !price.is_finite() || price <= 0.0 || !trigger_price.is_finite() || trigger_price <= 0.0
        {
            return Err(PyValueError::new_err(
                "STOP_LIMIT requires price and trigger_price > 0",
            ));
        }
        let side = numeric_enum(side, "side", &[("buy", 1), ("sell", -1)], &[1, -1])?;
        let tif = optional_enum(
            tif,
            TIF_GTC,
            "tif",
            &[("gtc", 0), ("ioc", 1), ("fok", 2), ("gtd", 3)],
            &[0, 1, 2, 3],
        )?;
        let activation = optional_enum(
            activation,
            ACTIVATION_IMMEDIATE,
            "activation",
            &[
                ("immediate", 0),
                ("on_parent_first_fill", 1),
                ("on_parent_full_fill", 2),
            ],
            &[0, 1, 2],
        )?;
        let handle = self.next_order_handle(order_handle)?;
        self.push(
            ACTION_PLACE,
            symbol_id,
            side,
            ORDER_STOP_LIMIT,
            qty,
            price,
            trigger_price,
            tif,
            reduce_only,
            handle,
            -1,
            parent_handle.unwrap_or(-1),
            group_handle.unwrap_or(-1),
            oco_handle.unwrap_or(-1),
            activation,
            effective_bar.unwrap_or(-1),
        )
    }

    #[pyo3(signature = (target_handle, *, effective_bar=None))]
    fn cancel(&mut self, target_handle: i64, effective_bar: Option<i64>) -> PyResult<()> {
        self.push(
            ACTION_CANCEL,
            -1,
            0,
            -1,
            f64::NAN,
            f64::NAN,
            f64::NAN,
            TIF_GTC,
            false,
            -1,
            target_handle,
            -1,
            -1,
            -1,
            ACTIVATION_IMMEDIATE,
            effective_bar.unwrap_or(-1),
        )?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (*, symbol_id=-1, side=None, order_type=None, parent_handle=None, group_handle=None, oco_handle=None, effective_bar=None))]
    fn cancel_all(
        &mut self,
        symbol_id: i64,
        side: Option<&Bound<'_, PyAny>>,
        order_type: Option<&Bound<'_, PyAny>>,
        parent_handle: Option<i64>,
        group_handle: Option<i64>,
        oco_handle: Option<i64>,
        effective_bar: Option<i64>,
    ) -> PyResult<()> {
        let side = optional_enum(side, 0, "side", &[("buy", 1), ("sell", -1)], &[0, 1, -1])?;
        let order_type = optional_enum(
            order_type,
            -1,
            "order_type",
            &[
                ("market", 0),
                ("limit", 1),
                ("stop_market", 2),
                ("stop_limit", 3),
            ],
            &[-1, 0, 1, 2, 3],
        )?;
        self.push(
            ACTION_CANCEL_ALL,
            symbol_id,
            side,
            order_type,
            f64::NAN,
            f64::NAN,
            f64::NAN,
            TIF_GTC,
            false,
            -1,
            -1,
            parent_handle.unwrap_or(-1),
            group_handle.unwrap_or(-1),
            oco_handle.unwrap_or(-1),
            ACTIVATION_IMMEDIATE,
            effective_bar.unwrap_or(-1),
        )?;
        Ok(())
    }

    #[pyo3(signature = (target_handle, *, qty=None, price=None, trigger_price=None, effective_bar=None))]
    fn amend(
        &mut self,
        target_handle: i64,
        qty: Option<f64>,
        price: Option<f64>,
        trigger_price: Option<f64>,
        effective_bar: Option<i64>,
    ) -> PyResult<()> {
        if qty.is_none() && price.is_none() && trigger_price.is_none() {
            return Err(PyValueError::new_err(
                "AMEND requires qty, price, or trigger_price",
            ));
        }
        self.push(
            ACTION_AMEND,
            -1,
            0,
            -1,
            qty.unwrap_or(f64::NAN),
            price.unwrap_or(f64::NAN),
            trigger_price.unwrap_or(f64::NAN),
            TIF_GTC,
            false,
            -1,
            target_handle,
            -1,
            -1,
            -1,
            ACTIVATION_IMMEDIATE,
            effective_bar.unwrap_or(-1),
        )?;
        Ok(())
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (target_handle, symbol_id, side, qty, *, order_handle=None, order_type=None, price=None, trigger_price=None, tif=None, reduce_only=false, parent_handle=None, group_handle=None, oco_handle=None, activation=None, effective_bar=None))]
    fn replace(
        &mut self,
        target_handle: i64,
        symbol_id: i64,
        side: &Bound<'_, PyAny>,
        qty: f64,
        order_handle: Option<i64>,
        order_type: Option<&Bound<'_, PyAny>>,
        price: Option<f64>,
        trigger_price: Option<f64>,
        tif: Option<&Bound<'_, PyAny>>,
        reduce_only: bool,
        parent_handle: Option<i64>,
        group_handle: Option<i64>,
        oco_handle: Option<i64>,
        activation: Option<&Bound<'_, PyAny>>,
        effective_bar: Option<i64>,
    ) -> PyResult<i64> {
        let side = numeric_enum(side, "side", &[("buy", 1), ("sell", -1)], &[1, -1])?;
        let order_type = optional_enum(
            order_type,
            ORDER_MARKET,
            "order_type",
            &[
                ("market", 0),
                ("limit", 1),
                ("stop_market", 2),
                ("stop_limit", 3),
            ],
            &[0, 1, 2, 3],
        )?;
        let tif = optional_enum(
            tif,
            TIF_GTC,
            "tif",
            &[("gtc", 0), ("ioc", 1), ("fok", 2), ("gtd", 3)],
            &[0, 1, 2, 3],
        )?;
        let activation = optional_enum(
            activation,
            ACTIVATION_IMMEDIATE,
            "activation",
            &[
                ("immediate", 0),
                ("on_parent_first_fill", 1),
                ("on_parent_full_fill", 2),
            ],
            &[0, 1, 2],
        )?;
        let handle = self.next_order_handle(order_handle)?;
        self.push(
            ACTION_REPLACE,
            symbol_id,
            side,
            order_type,
            qty,
            price.unwrap_or(f64::NAN),
            trigger_price.unwrap_or(f64::NAN),
            tif,
            reduce_only,
            handle,
            target_handle,
            parent_handle.unwrap_or(-1),
            group_handle.unwrap_or(-1),
            oco_handle.unwrap_or(-1),
            activation,
            effective_bar.unwrap_or(-1),
        )
    }
}

/// Ephemeral numeric projection for one coalesced R3B callback.
///
/// Rows are ordered by candidate id and contain only candidates whose declared
/// wake condition fired on the current shared market bar.  Arrays are copied
/// once per batch callback; Rust remains owner of all session/account state.
#[pyclass]
pub(crate) struct ReactiveCandidateBatchContextV1 {
    generation: u64,
    active: bool,
    bar_index: usize,
    timestamp_ns: i64,
    n_symbols: usize,
    candidate_ids: Vec<i64>,
    equities: Vec<f64>,
    positions: Vec<f64>,
    fill_counts: Vec<i64>,
    event_counts: Vec<i64>,
    wake_reason_masks: Vec<i64>,
}

impl ReactiveCandidateBatchContextV1 {
    fn new_internal(n_symbols: usize) -> Self {
        Self {
            generation: 0,
            active: false,
            bar_index: 0,
            timestamp_ns: 0,
            n_symbols,
            candidate_ids: Vec::new(),
            equities: Vec::new(),
            positions: Vec::new(),
            fill_counts: Vec::new(),
            event_counts: Vec::new(),
            wake_reason_masks: Vec::new(),
        }
    }

    fn check(&self) -> PyResult<()> {
        if self.active {
            Ok(())
        } else {
            Err(PyRuntimeError::new_err(
                "ReactiveCandidateBatchContextV1 is ephemeral and is no longer valid; copy primitive values inside the callback",
            ))
        }
    }

    fn refresh(
        &mut self,
        bar_index: usize,
        timestamp_ns: i64,
        candidate_ids: &[usize],
        runtimes: &[CandidateRuntimeState],
    ) -> PyResult<usize> {
        self.generation = self.generation.saturating_add(1);
        self.active = true;
        self.bar_index = bar_index;
        self.timestamp_ns = timestamp_ns;
        self.candidate_ids.clear();
        self.equities.clear();
        self.positions.clear();
        self.fill_counts.clear();
        self.event_counts.clear();
        self.wake_reason_masks.clear();
        for &candidate in candidate_ids {
            let runtime = runtimes.get(candidate).ok_or_else(|| {
                PyValueError::new_err(
                    "candidate batch context candidate index is outside the runtime",
                )
            })?;
            self.candidate_ids.push(candidate as i64);
            self.equities.push(runtime.current.equity);
            self.positions
                .extend_from_slice(&runtime.core.inner.positions);
            self.fill_counts.push(runtime.current.fill_count);
            self.event_counts.push(runtime.current.event_count);
            self.wake_reason_masks.push(runtime.wake_reason_mask);
            // Account values plus the position row are the only per-candidate
            // payload transferred to Python at the decision boundary.
        }
        Ok(self.candidate_ids.len()
            * (3 * std::mem::size_of::<i64>()
                + std::mem::size_of::<f64>()
                + self.n_symbols * std::mem::size_of::<f64>()))
    }

    fn invalidate_internal(&mut self) {
        self.active = false;
    }

    fn candidate_row(&self, candidate_id: i64) -> PyResult<usize> {
        self.check()?;
        self.candidate_ids
            .iter()
            .position(|value| *value == candidate_id)
            .ok_or_else(|| {
                PyValueError::new_err("candidate_id is not active in this batch callback")
            })
    }
}

#[pymethods]
impl ReactiveCandidateBatchContextV1 {
    #[getter]
    fn generation(&self) -> u64 {
        self.generation
    }

    #[getter]
    fn bar_index(&self) -> PyResult<usize> {
        self.check()?;
        Ok(self.bar_index)
    }

    #[getter]
    fn timestamp_ns(&self) -> PyResult<i64> {
        self.check()?;
        Ok(self.timestamp_ns)
    }

    #[getter]
    fn candidate_count(&self) -> PyResult<usize> {
        self.check()?;
        Ok(self.candidate_ids.len())
    }

    #[getter]
    fn symbol_count(&self) -> usize {
        self.n_symbols
    }

    #[getter]
    fn candidate_ids<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray1<i64>>> {
        self.check()?;
        Ok(PyArray1::from_vec(py, self.candidate_ids.clone()))
    }

    #[getter]
    fn equity<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray1<f64>>> {
        self.check()?;
        Ok(PyArray1::from_vec(py, self.equities.clone()))
    }

    #[getter]
    fn positions_flat<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray1<f64>>> {
        self.check()?;
        Ok(PyArray1::from_vec(py, self.positions.clone()))
    }

    #[getter]
    fn fill_counts<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray1<i64>>> {
        self.check()?;
        Ok(PyArray1::from_vec(py, self.fill_counts.clone()))
    }

    #[getter]
    fn event_counts<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray1<i64>>> {
        self.check()?;
        Ok(PyArray1::from_vec(py, self.event_counts.clone()))
    }

    #[getter]
    fn wake_reason_masks<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyArray1<i64>>> {
        self.check()?;
        Ok(PyArray1::from_vec(py, self.wake_reason_masks.clone()))
    }

    fn position_qty(&self, candidate_id: i64, symbol_id: usize) -> PyResult<f64> {
        let row = self.candidate_row(candidate_id)?;
        if symbol_id >= self.n_symbols {
            return Err(PyValueError::new_err(
                "symbol_id is outside the prepared market",
            ));
        }
        Ok(self.positions[row * self.n_symbols + symbol_id])
    }
}

/// Candidate-scoped command writer for one R3B callback.
///
/// The writer returns the preallocated primitive writer owned by a candidate.
/// This keeps the candidate id in the native ownership mapping rather than
/// allocating a Python command object for every row.  Results retain the
/// candidate id beside each output tape, so no command can cross sessions.
#[pyclass]
pub(crate) struct ReactiveCandidateCommandBatchV1 {
    writers: Vec<Py<ReactiveCommandBufferV2>>,
    active_candidates: HashSet<usize>,
    failed_codes: BTreeMap<usize, i64>,
    active: bool,
}

impl ReactiveCandidateCommandBatchV1 {
    fn new_internal(writers: Vec<Py<ReactiveCommandBufferV2>>) -> Self {
        Self {
            writers,
            active_candidates: HashSet::new(),
            failed_codes: BTreeMap::new(),
            active: false,
        }
    }

    fn begin_callback(&mut self, py: Python<'_>, candidates: &[usize]) {
        self.active = true;
        self.active_candidates.clear();
        self.failed_codes.clear();
        for &candidate in candidates {
            self.active_candidates.insert(candidate);
            self.writers[candidate]
                .bind(py)
                .borrow_mut()
                .begin_callback();
        }
    }

    fn end_candidate(&mut self, py: Python<'_>, candidate: usize) {
        self.writers[candidate].bind(py).borrow_mut().end_callback();
    }

    fn invalidate_internal(&mut self) {
        self.active = false;
        self.active_candidates.clear();
    }
}

#[pymethods]
impl ReactiveCandidateCommandBatchV1 {
    fn writer(&self, py: Python<'_>, candidate_id: i64) -> PyResult<Py<ReactiveCommandBufferV2>> {
        if !self.active {
            return Err(PyRuntimeError::new_err(
                "ReactiveCandidateCommandBatchV1 is only writable during its active strategy callback",
            ));
        }
        let candidate = usize::try_from(candidate_id)
            .map_err(|_| PyValueError::new_err("candidate_id must be >= 0"))?;
        if !self.active_candidates.contains(&candidate) {
            return Err(PyValueError::new_err(
                "candidate_id is not active in this batch callback",
            ));
        }
        let _ = py;
        Ok(self.writers[candidate].clone_ref(py))
    }

    fn fail_candidate(&mut self, candidate_id: i64, code: i64) -> PyResult<()> {
        if !self.active {
            return Err(PyRuntimeError::new_err(
                "ReactiveCandidateCommandBatchV1 is only writable during its active strategy callback",
            ));
        }
        let candidate = usize::try_from(candidate_id)
            .map_err(|_| PyValueError::new_err("candidate_id must be >= 0"))?;
        if !self.active_candidates.contains(&candidate) {
            return Err(PyValueError::new_err(
                "candidate_id is not active in this batch callback",
            ));
        }
        if !(1..=4).contains(&code) {
            return Err(PyValueError::new_err("candidate error code must be 1..4"));
        }
        self.failed_codes.insert(candidate, code);
        Ok(())
    }
}

#[derive(Clone, Copy, Debug)]
struct ReactiveRetentionProfileV1 {
    account_paths: bool,
    command_rows: bool,
    callback_trace: bool,
    terminal_active_orders: bool,
    scalar_metrics: bool,
    trading_days: i64,
    bar_annualization: f64,
}

impl Default for ReactiveRetentionProfileV1 {
    fn default() -> Self {
        Self {
            account_paths: true,
            command_rows: true,
            callback_trace: true,
            terminal_active_orders: true,
            scalar_metrics: false,
            trading_days: 365,
            bar_annualization: 365.0,
        }
    }
}

#[derive(Default)]
struct ReactiveRunData {
    equity: Vec<f64>,
    positions: Vec<f64>,
    fees: Vec<f64>,
    turnover: Vec<f64>,
    funding: Vec<f64>,
    initial_margin: Vec<f64>,
    maintenance_margin: Vec<f64>,
    fill_bar: Vec<i64>,
    fill_order_id: Vec<i64>,
    fill_symbol: Vec<i64>,
    fill_side: Vec<i64>,
    fill_qty: Vec<f64>,
    fill_price: Vec<f64>,
    fill_fee: Vec<f64>,
    fill_reason: Vec<i64>,
    fill_ambiguity: Vec<i64>,
    event_bar: Vec<i64>,
    event_kind: Vec<i64>,
    event_status: Vec<i64>,
    event_order_id: Vec<i64>,
    event_target_id: Vec<i64>,
    event_symbol: Vec<i64>,
    event_reject_code: Vec<i64>,
    command_bar: Vec<i64>,
    command_effective_bar: Vec<i64>,
    command_action: Vec<i64>,
    command_symbol: Vec<i64>,
    command_side: Vec<i64>,
    command_order_type: Vec<i64>,
    command_tif: Vec<i64>,
    command_flags: Vec<i64>,
    command_order_id: Vec<i64>,
    command_target_id: Vec<i64>,
    command_parent_id: Vec<i64>,
    command_group_id: Vec<i64>,
    command_oco_id: Vec<i64>,
    command_activation: Vec<i64>,
    command_qty: Vec<f64>,
    command_price: Vec<f64>,
    command_trigger: Vec<f64>,
    command_accepted: Vec<bool>,
    command_outside_tape: Vec<bool>,
    command_invalidated: Vec<bool>,
    callback_kind: Vec<i64>,
    callback_bar: Vec<i64>,
    callback_timestamp_ns: Vec<i64>,
    callback_equity: Vec<f64>,
    callback_position_0: Vec<f64>,
    wake_bar: Vec<i64>,
    wake_reason_mask: Vec<i64>,
    terminal_active_order_id: Vec<i64>,
    terminal_active_symbol: Vec<i64>,
    terminal_active_side: Vec<i64>,
    terminal_active_order_type: Vec<i64>,
    terminal_active_qty: Vec<f64>,
    terminal_active_price: Vec<f64>,
    terminal_active_trigger: Vec<f64>,
    final_positions: Vec<f64>,
    final_equity: f64,
    final_initial_margin: f64,
    final_maintenance_margin: f64,
    total_fee: f64,
    total_turnover: f64,
    total_funding: f64,
    fill_count: i64,
    event_count: i64,
    rejected_count: i64,
    canceled_count: i64,
    max_initial_margin: f64,
    max_maintenance_margin: f64,
    liquidated: bool,
    liquidation_bar: i64,
    liquidation_reason: i64,
    bars_processed: usize,
    python_callback_calls: usize,
    callback_ns: u128,
    context_projection_ns: u128,
    context_copy_bytes: usize,
    command_ingest_ns: u128,
    command_ingest_bytes: usize,
    command_rows: usize,
    command_rows_dropped: usize,
    command_rows_quantized: usize,
    native_entry_calls: usize,
    gil_acquisitions: usize,
    wake_observation_refreshes: usize,
    wake_observation_buffer_allocations: usize,
    native_gap_runs: usize,
    native_gap_bars: usize,
    native_cancellation_checks: usize,
    native_deadline_checks: usize,
    engine_ns: u128,
    result_materialization_ns: u128,
    gil_policy: String,
    runtime_class: String,
    retention: ReactiveRetentionProfileV1,
    score_reducer: Option<ReactiveOnlineScoreV1>,
    score_snapshot: Option<ReactiveScoreSnapshotV1>,
}

#[pyclass(name = "ReactiveNumericRunOutputV1", module = "_quantbt_native")]
pub(crate) struct ReactiveNumericRunOutputCore {
    data: Option<ReactiveRunData>,
}

fn put_i64(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    name: &str,
    values: Vec<i64>,
) -> PyResult<()> {
    payload.set_item(name, PyArray1::from_vec(py, values))
}

fn put_f64(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    name: &str,
    values: Vec<f64>,
) -> PyResult<()> {
    payload.set_item(name, PyArray1::from_vec(py, values))
}

fn put_bool(
    py: Python<'_>,
    payload: &Bound<'_, PyDict>,
    name: &str,
    values: Vec<bool>,
) -> PyResult<()> {
    payload.set_item(name, PyArray1::from_vec(py, values))
}

#[pymethods]
impl ReactiveNumericRunOutputCore {
    #[getter]
    fn consumed(&self) -> bool {
        self.data.is_none()
    }

    /// Transfer Rust-owned SoA buffers once to NumPy for cold-path adaptation.
    /// A second call is rejected so callers cannot accidentally retain a
    /// duplicated result tape while believing the handoff is zero-copy.
    fn consume(&mut self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let materialization_started = Instant::now();
        let data = self.data.take().ok_or_else(|| {
            PyRuntimeError::new_err("ReactiveNumericRunOutputV1 was already consumed")
        })?;
        let score_snapshot = data.score_snapshot;
        let payload = PyDict::new(py);
        put_f64(py, &payload, "equity", data.equity)?;
        put_f64(py, &payload, "positions", data.positions)?;
        put_f64(py, &payload, "fees", data.fees)?;
        put_f64(py, &payload, "turnover", data.turnover)?;
        put_f64(py, &payload, "funding", data.funding)?;
        put_f64(py, &payload, "initial_margin", data.initial_margin)?;
        put_f64(py, &payload, "maintenance_margin", data.maintenance_margin)?;
        put_i64(py, &payload, "fill_bar", data.fill_bar)?;
        put_i64(py, &payload, "fill_order_id", data.fill_order_id)?;
        put_i64(py, &payload, "fill_symbol", data.fill_symbol)?;
        put_i64(py, &payload, "fill_side", data.fill_side)?;
        put_f64(py, &payload, "fill_qty", data.fill_qty)?;
        put_f64(py, &payload, "fill_price", data.fill_price)?;
        put_f64(py, &payload, "fill_fee", data.fill_fee)?;
        put_i64(py, &payload, "fill_reason", data.fill_reason)?;
        put_i64(py, &payload, "fill_ambiguity", data.fill_ambiguity)?;
        put_i64(py, &payload, "event_bar", data.event_bar)?;
        put_i64(py, &payload, "event_kind", data.event_kind)?;
        put_i64(py, &payload, "event_status", data.event_status)?;
        put_i64(py, &payload, "event_order_id", data.event_order_id)?;
        put_i64(py, &payload, "event_target_id", data.event_target_id)?;
        put_i64(py, &payload, "event_symbol", data.event_symbol)?;
        put_i64(py, &payload, "event_reject_code", data.event_reject_code)?;
        put_i64(py, &payload, "command_bar", data.command_bar)?;
        put_i64(
            py,
            &payload,
            "command_effective_bar",
            data.command_effective_bar,
        )?;
        put_i64(py, &payload, "command_action", data.command_action)?;
        put_i64(py, &payload, "command_symbol", data.command_symbol)?;
        put_i64(py, &payload, "command_side", data.command_side)?;
        put_i64(py, &payload, "command_order_type", data.command_order_type)?;
        put_i64(py, &payload, "command_tif", data.command_tif)?;
        put_i64(py, &payload, "command_flags", data.command_flags)?;
        put_i64(py, &payload, "command_order_id", data.command_order_id)?;
        put_i64(py, &payload, "command_target_id", data.command_target_id)?;
        put_i64(py, &payload, "command_parent_id", data.command_parent_id)?;
        put_i64(py, &payload, "command_group_id", data.command_group_id)?;
        put_i64(py, &payload, "command_oco_id", data.command_oco_id)?;
        put_i64(py, &payload, "command_activation", data.command_activation)?;
        put_f64(py, &payload, "command_qty", data.command_qty)?;
        put_f64(py, &payload, "command_price", data.command_price)?;
        put_f64(py, &payload, "command_trigger", data.command_trigger)?;
        put_bool(py, &payload, "command_accepted", data.command_accepted)?;
        put_bool(
            py,
            &payload,
            "command_outside_tape",
            data.command_outside_tape,
        )?;
        put_bool(
            py,
            &payload,
            "command_invalidated",
            data.command_invalidated,
        )?;
        put_i64(py, &payload, "callback_kind", data.callback_kind)?;
        put_i64(py, &payload, "callback_bar", data.callback_bar)?;
        put_i64(
            py,
            &payload,
            "callback_timestamp_ns",
            data.callback_timestamp_ns,
        )?;
        put_f64(py, &payload, "callback_equity", data.callback_equity)?;
        put_f64(
            py,
            &payload,
            "callback_position_0",
            data.callback_position_0,
        )?;
        put_i64(py, &payload, "wake_bar", data.wake_bar)?;
        put_i64(py, &payload, "wake_reason_mask", data.wake_reason_mask)?;
        put_i64(
            py,
            &payload,
            "terminal_active_order_id",
            data.terminal_active_order_id,
        )?;
        put_i64(
            py,
            &payload,
            "terminal_active_symbol",
            data.terminal_active_symbol,
        )?;
        put_i64(
            py,
            &payload,
            "terminal_active_side",
            data.terminal_active_side,
        )?;
        put_i64(
            py,
            &payload,
            "terminal_active_order_type",
            data.terminal_active_order_type,
        )?;
        put_f64(
            py,
            &payload,
            "terminal_active_qty",
            data.terminal_active_qty,
        )?;
        put_f64(
            py,
            &payload,
            "terminal_active_price",
            data.terminal_active_price,
        )?;
        put_f64(
            py,
            &payload,
            "terminal_active_trigger",
            data.terminal_active_trigger,
        )?;
        put_f64(py, &payload, "final_positions", data.final_positions)?;
        payload.set_item("final_equity", data.final_equity)?;
        payload.set_item("total_fee", data.total_fee)?;
        payload.set_item("total_turnover", data.total_turnover)?;
        payload.set_item("total_funding", data.total_funding)?;
        payload.set_item("fill_count", data.fill_count)?;
        payload.set_item("event_count", data.event_count)?;
        payload.set_item("rejected_count", data.rejected_count)?;
        payload.set_item("canceled_count", data.canceled_count)?;
        payload.set_item("max_initial_margin", data.max_initial_margin)?;
        payload.set_item("max_maintenance_margin", data.max_maintenance_margin)?;
        payload.set_item("liquidated", data.liquidated)?;
        payload.set_item("liquidation_bar", data.liquidation_bar)?;
        payload.set_item("liquidation_reason", data.liquidation_reason)?;
        payload.set_item("bars_processed", data.bars_processed)?;
        payload.set_item("python_callback_calls", data.python_callback_calls)?;
        payload.set_item("python_callback_ns", data.callback_ns)?;
        payload.set_item("context_projection_ns", data.context_projection_ns)?;
        payload.set_item("context_copy_bytes", data.context_copy_bytes)?;
        payload.set_item("command_ingest_ns", data.command_ingest_ns)?;
        payload.set_item("command_ingest_bytes", data.command_ingest_bytes)?;
        payload.set_item("command_rows", data.command_rows)?;
        payload.set_item("command_rows_dropped", data.command_rows_dropped)?;
        payload.set_item("command_rows_quantized", data.command_rows_quantized)?;
        payload.set_item("native_entry_calls", data.native_entry_calls)?;
        payload.set_item("gil_acquisitions", data.gil_acquisitions)?;
        payload.set_item(
            "wake_observation_refreshes",
            data.wake_observation_refreshes,
        )?;
        payload.set_item(
            "wake_observation_buffer_allocations",
            data.wake_observation_buffer_allocations,
        )?;
        payload.set_item("native_gap_runs", data.native_gap_runs)?;
        payload.set_item("native_gap_bars", data.native_gap_bars)?;
        payload.set_item(
            "native_cancellation_checks",
            data.native_cancellation_checks,
        )?;
        payload.set_item("native_deadline_checks", data.native_deadline_checks)?;
        payload.set_item("engine_ns", data.engine_ns)?;
        payload.set_item(
            "result_materialization_ns",
            data.result_materialization_ns
                .saturating_add(materialization_started.elapsed().as_nanos()),
        )?;
        payload.set_item("gil_policy", data.gil_policy)?;
        payload.set_item("runtime_class", data.runtime_class)?;
        payload.set_item("retention_account_paths", data.retention.account_paths)?;
        payload.set_item("retention_command_rows", data.retention.command_rows)?;
        payload.set_item("retention_callback_trace", data.retention.callback_trace)?;
        payload.set_item(
            "retention_terminal_active_orders",
            data.retention.terminal_active_orders,
        )?;
        payload.set_item("score_metrics_present", score_snapshot.is_some())?;
        let score = score_snapshot.unwrap_or_default();
        payload.set_item("score_initial_capital", score.initial_capital)?;
        payload.set_item("score_final_equity", score.final_equity)?;
        payload.set_item("score_total_return_pct", score.total_return_pct)?;
        payload.set_item("score_cagr_pct", score.cagr_pct)?;
        payload.set_item("score_sharpe", score.sharpe)?;
        payload.set_item("score_sortino", score.sortino)?;
        payload.set_item("score_calmar", score.calmar)?;
        payload.set_item("score_omega", score.omega)?;
        payload.set_item("score_max_drawdown_pct", score.max_drawdown_pct)?;
        payload.set_item("score_avg_drawdown_pct", score.avg_drawdown_pct)?;
        payload.set_item("score_max_dd_duration_days", score.max_dd_duration_days)?;
        payload.set_item("score_avg_dd_duration_days", score.avg_dd_duration_days)?;
        payload.set_item("score_profit_factor", score.profit_factor)?;
        payload.set_item("score_long_hitrate_pct", score.long_hitrate_pct)?;
        payload.set_item("score_short_hitrate_pct", score.short_hitrate_pct)?;
        payload.set_item("score_avg_win_pct", score.avg_win_pct)?;
        payload.set_item("score_avg_loss_pct", score.avg_loss_pct)?;
        payload.set_item("score_expectancy_pct", score.expectancy_pct)?;
        payload.set_item("score_num_trades", score.num_trades)?;
        payload.set_item("score_max_initial_margin", score.max_initial_margin)?;
        payload.set_item("score_max_maintenance_margin", score.max_maintenance_margin)?;
        payload.set_item("fully_native", false)?;
        Ok(payload.unbind())
    }
}

#[pyclass]
pub(crate) struct ReactiveNumericRunnerCore {
    inner: FullSession,
    context: Py<ReactiveContextBufferV1>,
    writer: Py<ReactiveCommandBufferV2>,
    step_buffers: full::StepBuffers,
    scheduled_commands: BTreeMap<usize, ScheduledCommandBatch>,
    output_mask: u8,
    retain_fills: bool,
    retain_events: bool,
    retention: ReactiveRetentionProfileV1,
    qty_step: Vec<f64>,
    min_qty: Vec<f64>,
    min_notional: Vec<f64>,
    cancel_requested: Arc<AtomicBool>,
    deadline_after: Option<Duration>,
    active_deadline: Option<Instant>,
    started: bool,
    poisoned: bool,
    run_count: u64,
    reset_count: u64,
    last_callback_name: String,
    last_callback_bar: i64,
}

#[derive(Default)]
struct ScheduledCommandBatch {
    codes: Vec<i64>,
    values: Vec<f64>,
    expiry: Vec<i64>,
    command_rows: Vec<usize>,
}

impl ScheduledCommandBatch {
    #[allow(clippy::too_many_arguments)]
    fn push(
        &mut self,
        action: i64,
        symbol: i64,
        side: i64,
        order_type: i64,
        tif: i64,
        flags: i64,
        order_handle: i64,
        target_handle: i64,
        parent_handle: i64,
        group_handle: i64,
        oco_handle: i64,
        activation: i64,
        command_index: i64,
        qty: f64,
        price: f64,
        trigger: f64,
    ) {
        self.codes.extend_from_slice(&[
            action,
            symbol,
            side,
            order_type,
            tif,
            flags,
            order_handle,
            target_handle,
            parent_handle,
            group_handle,
            oco_handle,
            activation,
            command_index,
            -1,
            -1,
            -1,
        ]);
        self.values.extend_from_slice(&[qty, price, trigger]);
        self.expiry.push(-1);
        self.command_rows.push(command_index as usize);
    }

    fn command_count(&self) -> usize {
        self.expiry.len()
    }
}

#[derive(Clone, Copy)]
struct PriceCrossCondition {
    symbol: usize,
    level: f64,
    direction: i64,
}

#[derive(Clone, Copy)]
struct PositionThresholdCondition {
    symbol: usize,
    level: f64,
    direction: i64,
}

#[derive(Clone, Copy)]
struct ScalarThresholdCondition {
    level: f64,
    direction: i64,
}

#[derive(Clone, Copy)]
struct MarginThresholdCondition {
    metric: i64,
    level: f64,
    direction: i64,
}

#[derive(Clone, Default)]
struct WakePlanInternal {
    next_bar: Option<usize>,
    next_timestamp_bar: Option<usize>,
    on_fill: bool,
    on_order_event: bool,
    on_liquidation: bool,
    on_funding: bool,
    price_crosses: Vec<PriceCrossCondition>,
    position_thresholds: Vec<PositionThresholdCondition>,
    equity_thresholds: Vec<ScalarThresholdCondition>,
    margin_thresholds: Vec<MarginThresholdCondition>,
}

/// Immutable primitive transport emitted by ``WakePlanV1.as_native_wire``.
/// It deliberately has no mapping/string keys on the optimized R2/R3 path.
type WakePlanWireV1 = (
    Option<i64>,
    Option<i64>,
    bool,
    bool,
    bool,
    bool,
    Vec<(i64, f64, i64)>,
    Vec<(i64, f64, i64)>,
    Vec<(f64, i64)>,
    Vec<(i64, f64, i64)>,
);

type CandidateWakePlanWireV1 = Vec<(i64, WakePlanWireV1)>;

#[derive(Clone, Copy)]
struct BlockPlanInternal {
    stop_bar: usize,
    invalidate_on_fill: bool,
    invalidate_on_reject: bool,
    invalidate_on_margin_change: bool,
}

impl ReactiveNumericRunnerCore {
    fn normalize_gil_policy(value: &str) -> PyResult<bool> {
        match value.to_ascii_lowercase().as_str() {
            "held" | "held_for_session" => Ok(false),
            "release" | "release_between_callbacks" => Ok(true),
            _ => Err(PyValueError::new_err(
                "gil_policy must be held_for_session or release_between_callbacks",
            )),
        }
    }

    /// Check an interrupt only at a completed/native bar boundary. A deadline
    /// deliberately does not asynchronously interrupt a Rust accounting step
    /// or a Python callback: either would publish an unverifiable half-step.
    fn check_native_interrupt(
        cancel_requested: &AtomicBool,
        active_deadline: Option<Instant>,
    ) -> Result<(), String> {
        if cancel_requested.load(Ordering::Acquire) {
            return Err(REACTIVE_CANCELLED_MESSAGE.to_owned());
        }
        if active_deadline.is_some_and(|deadline| Instant::now() >= deadline) {
            return Err(REACTIVE_DEADLINE_MESSAGE.to_owned());
        }
        Ok(())
    }

    fn required_payload<'py>(
        payload: &Bound<'py, PyDict>,
        key: &str,
    ) -> PyResult<Bound<'py, PyAny>> {
        payload
            .get_item(key)?
            .ok_or_else(|| PyValueError::new_err(format!("reactive plan is missing {key:?}")))
    }

    fn optional_i64(payload: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<i64>> {
        let Some(value) = payload.get_item(key)? else {
            return Ok(None);
        };
        if value.is_none() {
            return Ok(None);
        }
        value.extract::<i64>().map(Some)
    }

    fn payload_bool(payload: &Bound<'_, PyDict>, key: &str) -> PyResult<bool> {
        Self::required_payload(payload, key)?.extract::<bool>()
    }

    fn validate_direction(direction: i64, label: &str) -> PyResult<i64> {
        if matches!(direction, -1..=1) {
            Ok(direction)
        } else {
            Err(PyValueError::new_err(format!(
                "{label} direction must be -1, 0, or 1"
            )))
        }
    }

    fn parse_wake_plan(
        &self,
        value: &Bound<'_, PyAny>,
        current_bar: usize,
    ) -> PyResult<WakePlanInternal> {
        match value.call_method0("as_native_wire") {
            Ok(wire_value) => {
                let wire = wire_value.extract::<WakePlanWireV1>().map_err(|_| {
                    PyTypeError::new_err(
                        "WakePlanV1.as_native_wire() must return the quantbt wake wire v1 tuple",
                    )
                })?;
                return self.parse_wake_wire(&wire, current_bar);
            }
            Err(error) if error.is_instance_of::<PyAttributeError>(value.py()) => {}
            Err(error) => return Err(error),
        }
        let payload_value = value.call_method0("as_native_payload").map_err(|_| {
            PyTypeError::new_err(
                "numeric sparse on_wake must return WakePlanV1, not None or an untyped mapping",
            )
        })?;
        let payload = payload_value.cast::<PyDict>().map_err(|_| {
            PyTypeError::new_err("WakePlanV1.as_native_payload() must return a dict")
        })?;
        self.parse_wake_payload(payload, current_bar)
    }

    fn parse_wake_payload(
        &self,
        payload: &Bound<'_, PyDict>,
        current_bar: usize,
    ) -> PyResult<WakePlanInternal> {
        let schema = Self::required_payload(payload, "schema")?.extract::<String>()?;
        if schema != "quantbt-wake-plan-v1" {
            return Err(PyValueError::new_err(
                "unsupported reactive wake plan schema",
            ));
        }
        let wire = (
            Self::optional_i64(payload, "next_bar")?,
            Self::optional_i64(payload, "next_timestamp_ns")?,
            Self::payload_bool(payload, "on_fill")?,
            Self::payload_bool(payload, "on_order_event")?,
            Self::payload_bool(payload, "on_liquidation")?,
            Self::payload_bool(payload, "on_funding")?,
            Self::required_payload(payload, "price_crosses")?.extract::<Vec<(i64, f64, i64)>>()?,
            Self::required_payload(payload, "position_thresholds")?
                .extract::<Vec<(i64, f64, i64)>>()?,
            Self::required_payload(payload, "equity_thresholds")?.extract::<Vec<(f64, i64)>>()?,
            Self::required_payload(payload, "margin_thresholds")?
                .extract::<Vec<(i64, f64, i64)>>()?,
        );
        self.parse_wake_wire(&wire, current_bar)
    }

    fn parse_wake_wire(
        &self,
        wire: &WakePlanWireV1,
        current_bar: usize,
    ) -> PyResult<WakePlanInternal> {
        let (
            raw_next_bar,
            raw_next_timestamp_ns,
            on_fill,
            on_order_event,
            on_liquidation,
            on_funding,
            raw_price_crosses,
            raw_position_thresholds,
            raw_equity_thresholds,
            raw_margin_thresholds,
        ) = wire;
        let n_bars = self.inner.n_bars();
        let next_bar = match *raw_next_bar {
            Some(value) if value < 0 => {
                return Err(PyValueError::new_err("wake next_bar must be >= 0"));
            }
            Some(value) => {
                let bar = value as usize;
                if bar <= current_bar || bar >= n_bars {
                    return Err(PyValueError::new_err(
                        "wake next_bar must be after the callback bar and inside the prepared market",
                    ));
                }
                Some(bar)
            }
            None => None,
        };
        let next_timestamp_bar = match *raw_next_timestamp_ns {
            Some(timestamp_ns) => {
                let bar = self
                    .inner
                    .bar_for_timestamp_ns(timestamp_ns)
                    .map_err(PyValueError::new_err)?;
                if bar <= current_bar {
                    return Err(PyValueError::new_err(
                        "wake next_timestamp_ns must be after the callback bar",
                    ));
                }
                Some(bar)
            }
            None => None,
        };
        let parse_symbol_rows =
            |rows: &[(i64, f64, i64)], label: &str| -> PyResult<Vec<(usize, f64, i64)>> {
                rows.iter()
                    .copied()
                    .map(|(symbol, level, direction)| {
                        if symbol < 0 || symbol as usize >= self.inner.market.n_symbols {
                            return Err(PyValueError::new_err(format!(
                                "{label} symbol_id is outside the prepared market"
                            )));
                        }
                        if !level.is_finite() {
                            return Err(PyValueError::new_err(format!(
                                "{label} level must be finite"
                            )));
                        }
                        Ok((
                            symbol as usize,
                            level,
                            Self::validate_direction(direction, label)?,
                        ))
                    })
                    .collect()
            };
        let price_crosses = parse_symbol_rows(raw_price_crosses, "price-cross")?
            .into_iter()
            .map(|(symbol, level, direction)| PriceCrossCondition {
                symbol,
                level,
                direction,
            })
            .collect();
        let position_thresholds = parse_symbol_rows(raw_position_thresholds, "position-threshold")?
            .into_iter()
            .map(|(symbol, level, direction)| PositionThresholdCondition {
                symbol,
                level,
                direction,
            })
            .collect();
        let equity_thresholds = raw_equity_thresholds
            .iter()
            .copied()
            .map(|(level, direction)| {
                if !level.is_finite() {
                    return Err(PyValueError::new_err(
                        "equity-threshold level must be finite",
                    ));
                }
                Ok(ScalarThresholdCondition {
                    level,
                    direction: Self::validate_direction(direction, "equity-threshold")?,
                })
            })
            .collect::<PyResult<Vec<_>>>()?;
        let margin_thresholds = raw_margin_thresholds
            .iter()
            .copied()
            .map(|(metric, level, direction)| {
                if !matches!(metric, 0..=2) || !level.is_finite() {
                    return Err(PyValueError::new_err(
                        "margin threshold requires metric 0..2 and a finite level",
                    ));
                }
                Ok(MarginThresholdCondition {
                    metric,
                    level,
                    direction: Self::validate_direction(direction, "margin-threshold")?,
                })
            })
            .collect::<PyResult<Vec<_>>>()?;
        Ok(WakePlanInternal {
            next_bar,
            next_timestamp_bar,
            on_fill: *on_fill,
            on_order_event: *on_order_event,
            on_liquidation: *on_liquidation,
            on_funding: *on_funding,
            price_crosses,
            position_thresholds,
            equity_thresholds,
            margin_thresholds,
        })
    }

    fn parse_block_plan(
        &self,
        value: &Bound<'_, PyAny>,
        start_bar: usize,
        max_stop_bar: usize,
    ) -> PyResult<BlockPlanInternal> {
        let payload_value = value.call_method0("as_native_payload").map_err(|_| {
            PyTypeError::new_err(
                "numeric block next_block must return BlockPlanV1, not None or an untyped mapping",
            )
        })?;
        let payload = payload_value.cast::<PyDict>().map_err(|_| {
            PyTypeError::new_err("BlockPlanV1.as_native_payload() must return a dict")
        })?;
        let schema = Self::required_payload(payload, "schema")?.extract::<String>()?;
        if schema != "quantbt-block-plan-v1" {
            return Err(PyValueError::new_err(
                "unsupported reactive block plan schema",
            ));
        }
        let stop = Self::required_payload(payload, "stop_bar")?.extract::<i64>()?;
        if stop <= start_bar as i64 || stop > max_stop_bar as i64 {
            return Err(PyValueError::new_err(format!(
                "block stop_bar must satisfy {start_bar} < stop_bar <= {max_stop_bar}",
            )));
        }
        Ok(BlockPlanInternal {
            stop_bar: stop as usize,
            invalidate_on_fill: Self::payload_bool(payload, "invalidate_on_fill")?,
            invalidate_on_reject: Self::payload_bool(payload, "invalidate_on_reject")?,
            invalidate_on_margin_change: Self::payload_bool(
                payload,
                "invalidate_on_margin_change",
            )?,
        })
    }

    fn refresh_wake_observation(
        &self,
        bar: usize,
        step: &full::FullStepResult,
        observation: &mut ReusableWakeObservationV1,
    ) -> PyResult<()> {
        observation
            .refresh(&self.inner, bar, step)
            .map_err(PyValueError::new_err)
    }

    fn crossed(previous: f64, current: f64, level: f64, direction: i64) -> bool {
        match direction {
            1 => previous < level && current >= level,
            -1 => previous > level && current <= level,
            _ => (previous < level && current >= level) || (previous > level && current <= level),
        }
    }

    fn wake_reasons(
        &self,
        plan: &WakePlanInternal,
        bar: usize,
        step: &full::FullStepResult,
        previous: &ReusableWakeObservationV1,
        current: &ReusableWakeObservationV1,
    ) -> PyResult<i64> {
        Self::wake_reasons_native(&self.inner, plan, bar, step, previous, current)
            .map_err(PyValueError::new_err)
    }

    fn wake_reasons_native(
        inner: &FullSession,
        plan: &WakePlanInternal,
        bar: usize,
        step: &full::FullStepResult,
        previous: &ReusableWakeObservationV1,
        current: &ReusableWakeObservationV1,
    ) -> Result<i64, String> {
        let mut mask = 0_i64;
        if plan.next_bar == Some(bar) || plan.next_timestamp_bar == Some(bar) {
            mask |= WAKE_TIME;
        }
        if plan.on_fill && step.fill_count > 0 {
            mask |= WAKE_FILL;
        }
        if plan.on_order_event && step.event_count > 0 {
            mask |= WAKE_ORDER_EVENT;
        }
        if plan.on_liquidation && current.liquidated && !previous.liquidated {
            mask |= WAKE_LIQUIDATION;
        }
        if plan.on_funding && inner.has_funding_event_at(bar)? {
            mask |= WAKE_FUNDING;
        }
        for condition in &plan.price_crosses {
            let high = inner.market_value_at(1, bar, condition.symbol)?;
            let low = inner.market_value_at(2, bar, condition.symbol)?;
            let previous_close = previous.closes[condition.symbol];
            let crossed = match condition.direction {
                1 => previous_close < condition.level && high >= condition.level,
                -1 => previous_close > condition.level && low <= condition.level,
                _ => {
                    (previous_close < condition.level && high >= condition.level)
                        || (previous_close > condition.level && low <= condition.level)
                }
            };
            if crossed {
                mask |= WAKE_PRICE_CROSS;
                break;
            }
        }
        if plan.position_thresholds.iter().any(|condition| {
            Self::crossed(
                previous.positions[condition.symbol],
                current.positions[condition.symbol],
                condition.level,
                condition.direction,
            )
        }) {
            mask |= WAKE_POSITION_THRESHOLD;
        }
        if plan.equity_thresholds.iter().any(|condition| {
            Self::crossed(
                previous.equity,
                current.equity,
                condition.level,
                condition.direction,
            )
        }) {
            mask |= WAKE_EQUITY_THRESHOLD;
        }
        if plan.margin_thresholds.iter().any(|condition| {
            let (previous_value, current_value) = match condition.metric {
                0 => (previous.initial_margin, current.initial_margin),
                1 => (previous.maintenance_margin, current.maintenance_margin),
                _ => (
                    previous.equity - previous.initial_margin,
                    current.equity - current.initial_margin,
                ),
            };
            Self::crossed(
                previous_value,
                current_value,
                condition.level,
                condition.direction,
            )
        }) {
            mask |= WAKE_MARGIN_THRESHOLD;
        }
        Ok(mask)
    }

    fn invalidate_scheduled_from(&mut self, start_bar: usize, output: &mut ReactiveRunData) {
        let stale = self.scheduled_commands.split_off(&start_bar);
        for batch in stale.into_values() {
            for row in batch.command_rows {
                if let Some(value) = output.command_invalidated.get_mut(row) {
                    *value = true;
                }
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn record_step_native(
        inner: &FullSession,
        step_buffers: &full::StepBuffers,
        retain_fills: bool,
        retain_events: bool,
        output: &mut ReactiveRunData,
        bar: usize,
        step: &full::FullStepResult,
    ) -> Result<(), String> {
        if output.retention.account_paths {
            output.equity.push(step.equity);
            output.positions.extend_from_slice(&inner.positions);
            output.fees.push(step.fee);
            output.turnover.push(step.turnover);
            output.funding.push(step.funding);
            output.initial_margin.push(step.initial_margin);
            output.maintenance_margin.push(step.maintenance_margin);
        }
        output.final_equity = step.equity;
        output.final_positions.clone_from(&inner.positions);
        output.final_initial_margin = step.initial_margin;
        output.final_maintenance_margin = step.maintenance_margin;
        output.total_fee += step.fee;
        output.total_turnover += step.turnover;
        output.total_funding += step.funding;
        output.fill_count += step.fill_count;
        output.event_count += step.event_count;
        output.rejected_count += step.rejected_count;
        output.canceled_count += step.canceled_count;
        output.max_initial_margin = output.max_initial_margin.max(step.initial_margin);
        output.max_maintenance_margin = output.max_maintenance_margin.max(step.maintenance_margin);
        output.liquidated = step.liquidated;
        output.liquidation_bar = step.liquidation_bar;
        output.liquidation_reason = step.liquidation_reason;
        // `bar` is absolute to the immutable prepared market. A WFO
        // window may begin after bar zero, so public/accounting output must
        // report the number of bars processed by this fresh session rather
        // than its absolute terminal market coordinate.
        output.bars_processed = output.bars_processed.saturating_add(1);
        if let Some(reducer) = output.score_reducer.as_mut() {
            let timestamp_ns = inner.timestamp_ns_at(bar)?;
            reducer.observe(
                timestamp_ns,
                step.equity,
                &inner.positions,
                step.initial_margin,
                step.maintenance_margin,
            )?;
        }
        if retain_fills {
            for row in 0..step_buffers.fills.order_id.len() {
                output.fill_bar.push(bar as i64);
                output.fill_order_id.push(step_buffers.fills.order_id[row]);
                output.fill_symbol.push(step_buffers.fills.symbol[row]);
                output.fill_side.push(step_buffers.fills.side[row]);
                output.fill_qty.push(step_buffers.fills.qty[row]);
                output.fill_price.push(step_buffers.fills.price[row]);
                output.fill_fee.push(step_buffers.fills.fee[row]);
                output.fill_reason.push(step_buffers.fills.reason[row]);
                output
                    .fill_ambiguity
                    .push(step_buffers.fills.ambiguity[row]);
            }
        }
        if retain_events {
            for row in 0..step_buffers.events.kind.len() {
                output.event_bar.push(bar as i64);
                output.event_kind.push(step_buffers.events.kind[row]);
                output.event_status.push(step_buffers.events.status[row]);
                output
                    .event_order_id
                    .push(step_buffers.events.order_id[row]);
                output
                    .event_target_id
                    .push(step_buffers.events.target_id[row]);
                output.event_symbol.push(step_buffers.events.symbol[row]);
                output
                    .event_reject_code
                    .push(step_buffers.events.reject_code[row]);
            }
        }
        Ok(())
    }

    fn record_step(
        &self,
        output: &mut ReactiveRunData,
        bar: usize,
        step: &full::FullStepResult,
    ) -> PyResult<()> {
        Self::record_step_native(
            &self.inner,
            &self.step_buffers,
            self.retain_fills,
            self.retain_events,
            output,
            bar,
            step,
        )
        .map_err(PyValueError::new_err)
    }

    #[allow(clippy::too_many_arguments)]
    fn run_sparse_gap_native(
        inner: &mut FullSession,
        step_buffers: &mut full::StepBuffers,
        scheduled_commands: &mut BTreeMap<usize, ScheduledCommandBatch>,
        output_mask: u8,
        retain_fills: bool,
        retain_events: bool,
        cancel_requested: &AtomicBool,
        active_deadline: Option<Instant>,
        start_bar: usize,
        end_bar: usize,
        plan: &WakePlanInternal,
        previous: &mut ReusableWakeObservationV1,
        current: &mut ReusableWakeObservationV1,
        output: &mut ReactiveRunData,
    ) -> Result<(usize, full::FullStepResult, i64), String> {
        debug_assert!(start_bar < end_bar);
        output.native_gap_runs = output.native_gap_runs.saturating_add(1);
        for bar in start_bar..end_bar {
            if (bar - start_bar).is_multiple_of(REACTIVE_CANCEL_CHECK_INTERVAL_BARS) {
                output.native_cancellation_checks =
                    output.native_cancellation_checks.saturating_add(1);
                output.native_deadline_checks = output
                    .native_deadline_checks
                    .saturating_add(usize::from(active_deadline.is_some()));
                Self::check_native_interrupt(cancel_requested, active_deadline)?;
            }
            let scheduled = scheduled_commands.remove(&bar).unwrap_or_default();
            let command_count = scheduled.command_count();
            let step = inner.step_with_buffers(
                bar,
                &scheduled.codes,
                &scheduled.values,
                &scheduled.expiry,
                command_count,
                output_mask,
                false,
                step_buffers,
            )?;
            Self::record_step_native(
                inner,
                step_buffers,
                retain_fills,
                retain_events,
                output,
                bar,
                &step,
            )?;
            current.refresh(inner, bar, &step)?;
            output.wake_observation_refreshes = output.wake_observation_refreshes.saturating_add(1);
            output.native_gap_bars = output.native_gap_bars.saturating_add(1);
            let wake_reason_mask =
                Self::wake_reasons_native(inner, plan, bar, &step, previous, current)?;
            if wake_reason_mask != 0 || step.liquidated || bar + 1 == end_bar {
                output.native_deadline_checks = output
                    .native_deadline_checks
                    .saturating_add(usize::from(active_deadline.is_some()));
                Self::check_native_interrupt(cancel_requested, active_deadline)?;
                return Ok((bar, step, wake_reason_mask));
            }
            std::mem::swap(previous, current);
        }
        unreachable!("non-empty native sparse gap must return from its bar loop")
    }

    #[allow(clippy::too_many_arguments)]
    fn advance_sparse_gap(
        &mut self,
        py: Python<'_>,
        start_bar: usize,
        end_bar: usize,
        plan: &WakePlanInternal,
        previous: &mut ReusableWakeObservationV1,
        current: &mut ReusableWakeObservationV1,
        release_between_callbacks: bool,
        output: &mut ReactiveRunData,
    ) -> PyResult<(usize, full::FullStepResult, i64)> {
        let started = Instant::now();
        let output_mask = self.output_mask;
        let retain_fills = self.retain_fills;
        let retain_events = self.retain_events;
        let cancel_requested = Arc::clone(&self.cancel_requested);
        let active_deadline = self.active_deadline;
        let result = if release_between_callbacks {
            py.detach(|| {
                Self::run_sparse_gap_native(
                    &mut self.inner,
                    &mut self.step_buffers,
                    &mut self.scheduled_commands,
                    output_mask,
                    retain_fills,
                    retain_events,
                    cancel_requested.as_ref(),
                    active_deadline,
                    start_bar,
                    end_bar,
                    plan,
                    previous,
                    current,
                    output,
                )
            })
        } else {
            Self::run_sparse_gap_native(
                &mut self.inner,
                &mut self.step_buffers,
                &mut self.scheduled_commands,
                output_mask,
                retain_fills,
                retain_events,
                cancel_requested.as_ref(),
                active_deadline,
                start_bar,
                end_bar,
                plan,
                previous,
                current,
                output,
            )
        };
        output.engine_ns = output
            .engine_ns
            .saturating_add(started.elapsed().as_nanos());
        result.map_err(PyRuntimeError::new_err)
    }

    fn advance_bar(
        &mut self,
        py: Python<'_>,
        bar: usize,
        release_between_callbacks: bool,
        output: &mut ReactiveRunData,
    ) -> PyResult<full::FullStepResult> {
        output.native_cancellation_checks = output.native_cancellation_checks.saturating_add(1);
        output.native_deadline_checks = output
            .native_deadline_checks
            .saturating_add(usize::from(self.active_deadline.is_some()));
        Self::check_native_interrupt(self.cancel_requested.as_ref(), self.active_deadline)
            .map_err(PyRuntimeError::new_err)?;
        let scheduled = self.scheduled_commands.remove(&bar).unwrap_or_default();
        let command_count = scheduled.command_count();
        let started = Instant::now();
        let result = {
            let inner = &mut self.inner;
            let step_buffers = &mut self.step_buffers;
            let codes = &scheduled.codes;
            let values = &scheduled.values;
            let expiry = &scheduled.expiry;
            let mut execute = || {
                inner.step_with_buffers(
                    bar,
                    codes,
                    values,
                    expiry,
                    command_count,
                    self.output_mask,
                    false,
                    step_buffers,
                )
            };
            if release_between_callbacks {
                py.detach(execute)
            } else {
                execute()
            }
        }
        .map_err(PyValueError::new_err)?;
        output.engine_ns += started.elapsed().as_nanos();
        self.record_step(output, bar, &result)?;
        Ok(result)
    }

    fn project_context(
        &mut self,
        py: Python<'_>,
        bar: usize,
        wake_reason_mask: i64,
        step: &full::FullStepResult,
        output: &mut ReactiveRunData,
    ) -> PyResult<()> {
        let started = Instant::now();
        let copied = self.context.bind(py).borrow_mut().refresh(
            &self.inner,
            bar,
            wake_reason_mask,
            step,
            &self.step_buffers,
        )?;
        output.context_projection_ns += started.elapsed().as_nanos();
        output.context_copy_bytes += copied;
        Ok(())
    }

    fn quantize_qty(
        &self,
        bar: usize,
        symbol: usize,
        qty: f64,
        price: f64,
    ) -> PyResult<Option<f64>> {
        let step = self.qty_step[symbol];
        let mut quantity = qty;
        if step > 0.0 {
            quantity = ((quantity / step) + 1e-12).floor() * step;
        }
        if !quantity.is_finite() || quantity <= 0.0 || quantity + 1e-12 < self.min_qty[symbol] {
            return Ok(None);
        }
        let reference_price = if price.is_finite() && price > 0.0 {
            price
        } else {
            self.inner
                .close_price_at(bar, symbol)
                .map_err(PyValueError::new_err)?
        };
        let notional = quantity * reference_price * self.inner.contract_sizes[symbol];
        if notional + 1e-12 < self.min_notional[symbol] {
            return Ok(None);
        }
        Ok(Some(quantity))
    }

    fn ingest_writer(
        &mut self,
        py: Python<'_>,
        source_bar: usize,
        default_effective_bar: usize,
        allow_future: bool,
        block_range: Option<(usize, usize)>,
        output: &mut ReactiveRunData,
    ) -> PyResult<()> {
        let started = Instant::now();
        let mut writer = self.writer.bind(py).borrow_mut();
        for row in 0..writer.length {
            let action = writer.action[row];
            let symbol = writer.symbol_id[row];
            let mut qty = writer.qty[row];
            let price = writer.price[row];
            let trigger = writer.trigger_price[row];
            let requested = writer.effective_bar[row];
            let effective_bar = if requested < 0 {
                default_effective_bar
            } else {
                usize::try_from(requested).map_err(|_| {
                    PyValueError::new_err("reactive command effective_bar must be >= 0")
                })?
            };
            if effective_bar <= source_bar {
                return Err(PyValueError::new_err(
                    "reactive command effective_bar must be after its callback bar",
                ));
            }
            if !allow_future && effective_bar != default_effective_bar {
                return Err(PyValueError::new_err(
                    "this reactive runtime only accepts commands effective on the next bar",
                ));
            }
            if let Some((start_bar, stop_bar)) = block_range
                && (effective_bar < start_bar || effective_bar >= stop_bar)
            {
                return Err(PyValueError::new_err(format!(
                    "block command effective_bar={effective_bar} is outside [{start_bar}, {stop_bar})",
                )));
            }
            let executable = effective_bar < self.inner.n_bars();
            let place_like = matches!(action, ACTION_PLACE | ACTION_REPLACE);
            let mut accepted = executable;
            if place_like && executable {
                if symbol < 0 || symbol as usize >= self.inner.market.n_symbols {
                    accepted = false;
                } else {
                    let original = qty;
                    match self.quantize_qty(effective_bar, symbol as usize, qty, price)? {
                        Some(quantized) => {
                            if (quantized - original).abs() > 1e-12 {
                                output.command_rows_quantized += 1;
                            }
                            qty = quantized;
                        }
                        None => {
                            accepted = false;
                            output.command_rows_dropped += 1;
                        }
                    }
                }
            }
            if output.retention.command_rows {
                output.command_bar.push(source_bar as i64);
                output.command_effective_bar.push(effective_bar as i64);
                output.command_action.push(action);
                output.command_symbol.push(symbol);
                output.command_side.push(writer.side[row]);
                output.command_order_type.push(writer.order_type[row]);
                output.command_tif.push(writer.tif[row]);
                output.command_flags.push(writer.flags[row]);
                output.command_order_id.push(writer.order_handle[row]);
                output.command_target_id.push(writer.target_handle[row]);
                output.command_parent_id.push(writer.parent_handle[row]);
                output.command_group_id.push(writer.group_handle[row]);
                output.command_oco_id.push(writer.oco_handle[row]);
                output.command_activation.push(writer.activation[row]);
                output.command_qty.push(qty);
                output.command_price.push(price);
                output.command_trigger.push(trigger);
                output.command_accepted.push(accepted);
                output.command_outside_tape.push(!executable);
                output.command_invalidated.push(false);
            }
            let command_index = output.command_rows as i64;
            output.command_rows += 1;
            if accepted {
                self.scheduled_commands
                    .entry(effective_bar)
                    .or_default()
                    .push(
                        action,
                        symbol,
                        writer.side[row],
                        writer.order_type[row],
                        writer.tif[row],
                        writer.flags[row],
                        writer.order_handle[row],
                        writer.target_handle[row],
                        writer.parent_handle[row],
                        writer.group_handle[row],
                        writer.oco_handle[row],
                        writer.activation[row],
                        command_index,
                        if qty.is_finite() { qty } else { 0.0 },
                        if price.is_finite() { price } else { 0.0 },
                        if trigger.is_finite() { trigger } else { 0.0 },
                    );
                output.command_ingest_bytes += full::CODE_WIDTH * std::mem::size_of::<i64>()
                    + full::VALUE_WIDTH * std::mem::size_of::<f64>()
                    + std::mem::size_of::<i64>();
            }
        }
        writer.end_callback();
        drop(writer);
        self.context.bind(py).borrow_mut().invalidate_internal();
        output.command_ingest_ns += started.elapsed().as_nanos();
        Ok(())
    }

    fn invoke_callback(
        &mut self,
        py: Python<'_>,
        strategy: &Py<PyAny>,
        callback: &str,
        callback_kind: i64,
        bar: usize,
        output: &mut ReactiveRunData,
    ) -> PyResult<bool> {
        let callable = match strategy.bind(py).getattr(callback) {
            Ok(callable) => callable,
            Err(error) if error.is_instance_of::<PyAttributeError>(py) => return Ok(false),
            Err(error) => return Err(error),
        };
        self.last_callback_name = callback.to_owned();
        self.last_callback_bar = bar as i64;
        self.writer.bind(py).borrow_mut().begin_callback();
        let context = self.context.bind(py);
        let writer = self.writer.bind(py);
        if output.retention.callback_trace {
            output.callback_kind.push(callback_kind);
            output.callback_bar.push(bar as i64);
            output
                .callback_timestamp_ns
                .push(context.borrow().timestamp_ns);
            output.callback_equity.push(context.borrow().equity);
            output
                .callback_position_0
                .push(context.borrow().positions.first().copied().unwrap_or(0.0));
        }
        let started = Instant::now();
        let response = callable.call1((context, writer));
        output.callback_ns += started.elapsed().as_nanos();
        output.python_callback_calls += 1;
        match response {
            Ok(value) => {
                if !value.is_none() {
                    self.writer.bind(py).borrow_mut().end_callback();
                    self.context.bind(py).borrow_mut().invalidate_internal();
                    return Err(PyTypeError::new_err(
                        "numeric strategy callbacks must write to ReactiveCommandBufferV2 and return None",
                    ));
                }
            }
            Err(error) => {
                self.poisoned = true;
                self.writer.bind(py).borrow_mut().end_callback();
                self.context.bind(py).borrow_mut().invalidate_internal();
                return Err(error);
            }
        }
        self.ingest_writer(py, bar, bar + 1, false, None, output)?;
        Ok(true)
    }

    fn invoke_sparse_wake(
        &mut self,
        py: Python<'_>,
        strategy: &Py<PyAny>,
        bar: usize,
        wake_reason_mask: i64,
        output: &mut ReactiveRunData,
    ) -> PyResult<WakePlanInternal> {
        let callable = strategy.bind(py).getattr("on_wake").map_err(|error| {
            if error.is_instance_of::<PyAttributeError>(py) {
                PyTypeError::new_err(
                    "numeric sparse strategies must implement on_wake(context, out) -> WakePlanV1",
                )
            } else {
                error
            }
        })?;
        self.last_callback_name = "on_wake".to_owned();
        self.last_callback_bar = bar as i64;
        self.writer.bind(py).borrow_mut().begin_callback();
        let context = self.context.bind(py);
        let writer = self.writer.bind(py);
        if output.retention.callback_trace {
            output.callback_kind.push(CALLBACK_WAKE);
            output.callback_bar.push(bar as i64);
            output
                .callback_timestamp_ns
                .push(context.borrow().timestamp_ns);
            output.callback_equity.push(context.borrow().equity);
            output
                .callback_position_0
                .push(context.borrow().positions.first().copied().unwrap_or(0.0));
            output.wake_bar.push(bar as i64);
            output.wake_reason_mask.push(wake_reason_mask);
        }
        let started = Instant::now();
        let response = callable.call1((context, writer));
        output.callback_ns += started.elapsed().as_nanos();
        output.python_callback_calls += 1;
        let plan = match response {
            Ok(value) => self.parse_wake_plan(&value, bar),
            Err(error) => {
                self.poisoned = true;
                self.writer.bind(py).borrow_mut().end_callback();
                self.context.bind(py).borrow_mut().invalidate_internal();
                return Err(error);
            }
        };
        let plan = match plan {
            Ok(plan) => plan,
            Err(error) => {
                self.writer.bind(py).borrow_mut().end_callback();
                self.context.bind(py).borrow_mut().invalidate_internal();
                return Err(error);
            }
        };
        self.ingest_writer(py, bar, bar + 1, false, None, output)?;
        Ok(plan)
    }

    #[allow(clippy::too_many_arguments)]
    fn invoke_block_provider(
        &mut self,
        py: Python<'_>,
        strategy: &Py<PyAny>,
        bar: usize,
        start_bar: usize,
        max_stop_bar: usize,
        wake_reason_mask: i64,
        output: &mut ReactiveRunData,
    ) -> PyResult<BlockPlanInternal> {
        let callable = strategy.bind(py).getattr("next_block").map_err(|error| {
            if error.is_instance_of::<PyAttributeError>(py) {
                PyTypeError::new_err(
                    "numeric block strategies must implement next_block(context, start_bar, max_stop_bar, out) -> BlockPlanV1",
                )
            } else {
                error
            }
        })?;
        self.last_callback_name = "next_block".to_owned();
        self.last_callback_bar = bar as i64;
        self.writer.bind(py).borrow_mut().begin_callback();
        let context = self.context.bind(py);
        let writer = self.writer.bind(py);
        if output.retention.callback_trace {
            output.callback_kind.push(CALLBACK_BLOCK);
            output.callback_bar.push(bar as i64);
            output
                .callback_timestamp_ns
                .push(context.borrow().timestamp_ns);
            output.callback_equity.push(context.borrow().equity);
            output
                .callback_position_0
                .push(context.borrow().positions.first().copied().unwrap_or(0.0));
            output.wake_bar.push(bar as i64);
            output.wake_reason_mask.push(wake_reason_mask);
        }
        let started = Instant::now();
        let response = callable.call1((context, start_bar, max_stop_bar, writer));
        output.callback_ns += started.elapsed().as_nanos();
        output.python_callback_calls += 1;
        let plan = match response {
            Ok(value) => self.parse_block_plan(&value, start_bar, max_stop_bar),
            Err(error) => {
                self.poisoned = true;
                self.writer.bind(py).borrow_mut().end_callback();
                self.context.bind(py).borrow_mut().invalidate_internal();
                return Err(error);
            }
        };
        let plan = match plan {
            Ok(plan) => plan,
            Err(error) => {
                self.writer.bind(py).borrow_mut().end_callback();
                self.context.bind(py).borrow_mut().invalidate_internal();
                return Err(error);
            }
        };
        self.ingest_writer(
            py,
            bar,
            start_bar,
            true,
            Some((start_bar, plan.stop_bar)),
            output,
        )?;
        Ok(plan)
    }

    fn new_run_output(
        &self,
        release_between_callbacks: bool,
        runtime_class: &str,
        start_bar: usize,
        end_bar: usize,
    ) -> PyResult<ReactiveRunData> {
        if start_bar >= end_bar || end_bar > self.inner.n_bars() {
            return Err(PyValueError::new_err(
                "reactive execution window must satisfy 0 <= start_bar < end_bar <= market bars",
            ));
        }
        let n_symbols = self.inner.market.n_symbols;
        let score_reducer = if self.retention.scalar_metrics {
            Some(
                ReactiveOnlineScoreV1::new(
                    self.inner.initial_capital,
                    n_symbols,
                    self.retention.trading_days,
                    self.retention.bar_annualization,
                    self.inner
                        .timestamp_ns_at(start_bar)
                        .map_err(PyValueError::new_err)?,
                    self.inner
                        .timestamp_ns_at(end_bar.saturating_sub(1))
                        .map_err(PyValueError::new_err)?,
                )
                .map_err(PyValueError::new_err)?,
            )
        } else {
            None
        };
        Ok(ReactiveRunData {
            final_positions: vec![0.0; n_symbols],
            native_entry_calls: 1,
            gil_acquisitions: if release_between_callbacks { 0 } else { 1 },
            gil_policy: if release_between_callbacks {
                "release_between_callbacks".to_owned()
            } else {
                "held_for_session".to_owned()
            },
            runtime_class: runtime_class.to_owned(),
            retention: self.retention,
            score_reducer,
            ..ReactiveRunData::default()
        })
    }

    fn final_step(&self, output: &ReactiveRunData) -> full::FullStepResult {
        full::FullStepResult {
            equity: output.final_equity,
            initial_margin: output.final_initial_margin,
            maintenance_margin: output.final_maintenance_margin,
            liquidated: self.inner.liquidated,
            liquidation_bar: self.inner.liquidation_bar,
            liquidation_reason: self.inner.liquidation_reason,
            ..full::FullStepResult::default()
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn create_from_parts(
        py: Python<'_>,
        market: Arc<FullMarketData>,
        contract_sizes: Vec<f64>,
        leverages: Vec<f64>,
        fee_rates: Vec<f64>,
        qty_step: Vec<f64>,
        min_qty: Vec<f64>,
        min_notional: Vec<f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
        market_mask: u8,
        account_mask: u8,
        positions_enabled: bool,
        need_context_fills: bool,
        need_context_events: bool,
        need_context_active_orders: bool,
        retain_fills: bool,
        retain_events: bool,
        command_initial_capacity: usize,
        command_hard_limit: usize,
        retention: ReactiveRetentionProfileV1,
    ) -> PyResult<Self> {
        let n_symbols = market.n_symbols;
        let vectors = [
            &contract_sizes,
            &leverages,
            &fee_rates,
            &qty_step,
            &min_qty,
            &min_notional,
        ];
        if vectors.iter().any(|values| values.len() != n_symbols) {
            return Err(PyValueError::new_err(
                "reactive numeric instrument arrays must match prepared symbol count",
            ));
        }
        if [&qty_step, &min_qty, &min_notional]
            .iter()
            .any(|values| values.iter().any(|value| *value < 0.0))
        {
            return Err(PyValueError::new_err(
                "reactive numeric quantity constraints must be >= 0",
            ));
        }
        let mut inner = FullSession::new(
            market.clone(),
            contract_sizes,
            leverages,
            fee_rates,
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        )
        .map_err(PyValueError::new_err)?;
        let output_mask = (if need_context_fills || retain_fills {
            full::OUTPUT_FILLS
        } else {
            0
        }) | (if need_context_events || retain_events {
            full::OUTPUT_EVENTS
        } else {
            0
        }) | (if need_context_active_orders {
            full::OUTPUT_ACTIVE_ORDERS
        } else {
            0
        });
        inner.output_mask = output_mask;
        let context = Py::new(
            py,
            ReactiveContextBufferV1::new_internal(
                market,
                market_mask,
                account_mask,
                positions_enabled,
                need_context_fills,
                need_context_events,
                need_context_active_orders,
            ),
        )?;
        let writer = Py::new(
            py,
            ReactiveCommandBufferV2::with_limits(command_initial_capacity, command_hard_limit)?,
        )?;
        Ok(Self {
            inner,
            context,
            writer,
            step_buffers: full::StepBuffers::default(),
            scheduled_commands: BTreeMap::new(),
            output_mask,
            retain_fills,
            retain_events,
            retention,
            qty_step,
            min_qty,
            min_notional,
            cancel_requested: Arc::new(AtomicBool::new(false)),
            deadline_after: None,
            active_deadline: None,
            started: false,
            poisoned: false,
            run_count: 0,
            reset_count: 0,
            last_callback_name: String::new(),
            last_callback_bar: -1,
        })
    }

    fn capture_terminal_active_orders(&self, output: &mut ReactiveRunData) {
        if !output.retention.terminal_active_orders {
            return;
        }
        for row in self.inner.terminal_active_order_rows() {
            if row.len() < 7 {
                continue;
            }
            output.terminal_active_order_id.push(row[0] as i64);
            output.terminal_active_symbol.push(row[1] as i64);
            output.terminal_active_side.push(row[2] as i64);
            output.terminal_active_order_type.push(row[3] as i64);
            output.terminal_active_qty.push(row[4]);
            output.terminal_active_price.push(row[5]);
            output.terminal_active_trigger.push(row[6]);
        }
    }

    fn finish_run_output(&self, output: &mut ReactiveRunData) {
        if let Some(mut reducer) = output.score_reducer.take() {
            output.score_snapshot = Some(reducer.finish());
        }
        self.capture_terminal_active_orders(output);
    }

    fn validate_window(
        &self,
        start_bar: usize,
        end_bar: Option<usize>,
    ) -> PyResult<(usize, usize)> {
        let end = end_bar.unwrap_or_else(|| self.inner.n_bars());
        if start_bar >= end || end > self.inner.n_bars() {
            return Err(PyValueError::new_err(
                "reactive execution window must satisfy 0 <= start_bar < end_bar <= market bars",
            ));
        }
        Ok((start_bar, end))
    }

    fn begin_fresh_window(&mut self, start_bar: usize) -> PyResult<()> {
        self.inner
            .begin_fresh_at(start_bar)
            .map_err(PyValueError::new_err)
    }

    fn begin_runtime_deadline(&mut self) {
        self.active_deadline = self
            .deadline_after
            .and_then(|duration| Instant::now().checked_add(duration));
    }

    fn run_every_bar_window(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        start_bar: usize,
        end_bar: Option<usize>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveNumericRunOutputCore>> {
        if self.started {
            return Err(PyRuntimeError::new_err(
                "ReactiveNumericRunnerCore must be reset before a second run",
            ));
        }
        if self.poisoned {
            return Err(PyRuntimeError::new_err(
                "ReactiveNumericRunnerCore is poisoned after a prior callback failure",
            ));
        }
        let (start_bar, end_bar) = self.validate_window(start_bar, end_bar)?;
        let release_between_callbacks = Self::normalize_gil_policy(gil_policy)?;
        self.started = true;
        self.run_count = self.run_count.saturating_add(1);
        self.begin_fresh_window(start_bar)?;
        self.begin_runtime_deadline();
        let mut output = self.new_run_output(
            release_between_callbacks,
            "numeric_every_bar_v1",
            start_bar,
            end_bar,
        )?;

        let first = self.advance_bar(py, start_bar, release_between_callbacks, &mut output)?;
        self.project_context(py, start_bar, 0, &first, &mut output)?;
        let _ = self.invoke_callback(py, &strategy, "initialize", 0, start_bar, &mut output)?;
        if !first.liquidated {
            self.project_context(py, start_bar, 0, &first, &mut output)?;
            let _ =
                self.invoke_callback(py, &strategy, "on_bar_close", 1, start_bar, &mut output)?;
        }

        for bar in start_bar.saturating_add(1)..end_bar {
            let step = self.advance_bar(py, bar, release_between_callbacks, &mut output)?;
            if step.liquidated {
                continue;
            }
            self.project_context(py, bar, 0, &step, &mut output)?;
            let _ = self.invoke_callback(py, &strategy, "on_bar_close", 1, bar, &mut output)?;
        }

        if !self.inner.liquidated {
            let last_bar = end_bar.saturating_sub(1);
            let step = self.final_step(&output);
            self.project_context(py, last_bar, 0, &step, &mut output)?;
            let _ = self.invoke_callback(
                py,
                &strategy,
                "finalize",
                CALLBACK_FINALIZE,
                last_bar,
                &mut output,
            )?;
        }
        if release_between_callbacks {
            output.gil_acquisitions = output.python_callback_calls.saturating_add(1);
        }
        self.finish_run_output(&mut output);
        Py::new(py, ReactiveNumericRunOutputCore { data: Some(output) })
    }

    fn run_sparse_range(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        start_bar: usize,
        end_bar: Option<usize>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveNumericRunOutputCore>> {
        if self.started {
            return Err(PyRuntimeError::new_err(
                "ReactiveNumericRunnerCore must be reset before a second run",
            ));
        }
        if self.poisoned {
            return Err(PyRuntimeError::new_err(
                "ReactiveNumericRunnerCore is poisoned after a prior callback failure",
            ));
        }
        let (start_bar, end_bar) = self.validate_window(start_bar, end_bar)?;
        let release_between_callbacks = Self::normalize_gil_policy(gil_policy)?;
        self.started = true;
        self.run_count = self.run_count.saturating_add(1);
        self.begin_fresh_window(start_bar)?;
        self.begin_runtime_deadline();
        let mut output = self.new_run_output(
            release_between_callbacks,
            "numeric_sparse_wake_v1",
            start_bar,
            end_bar,
        )?;

        let first = self.advance_bar(py, start_bar, release_between_callbacks, &mut output)?;
        self.project_context(py, start_bar, 0, &first, &mut output)?;
        let _ = self.invoke_callback(
            py,
            &strategy,
            "initialize",
            CALLBACK_INITIALIZE,
            start_bar,
            &mut output,
        )?;
        let mut previous = ReusableWakeObservationV1::with_symbols(self.inner.market.n_symbols);
        let mut current = ReusableWakeObservationV1::with_symbols(self.inner.market.n_symbols);
        output.wake_observation_buffer_allocations = 2;
        self.refresh_wake_observation(start_bar, &first, &mut previous)?;
        output.wake_observation_refreshes = output.wake_observation_refreshes.saturating_add(1);
        let mut active_plan = if first.liquidated {
            WakePlanInternal::default()
        } else {
            self.project_context(py, start_bar, WAKE_INITIAL, &first, &mut output)?;
            self.invoke_sparse_wake(py, &strategy, start_bar, WAKE_INITIAL, &mut output)?
        };

        let mut bar = start_bar.saturating_add(1);
        while bar < end_bar {
            let (processed_bar, step, wake_reason_mask) = self.advance_sparse_gap(
                py,
                bar,
                end_bar,
                &active_plan,
                &mut previous,
                &mut current,
                release_between_callbacks,
                &mut output,
            )?;
            if wake_reason_mask != 0 {
                self.project_context(py, processed_bar, wake_reason_mask, &step, &mut output)?;
                active_plan = self.invoke_sparse_wake(
                    py,
                    &strategy,
                    processed_bar,
                    wake_reason_mask,
                    &mut output,
                )?;
            }
            std::mem::swap(&mut previous, &mut current);
            if step.liquidated {
                break;
            }
            if processed_bar.saturating_add(1) >= end_bar {
                break;
            }
            bar = processed_bar.saturating_add(1);
        }

        if !self.inner.liquidated {
            let last_bar = end_bar.saturating_sub(1);
            let step = self.final_step(&output);
            self.project_context(py, last_bar, 0, &step, &mut output)?;
            let _ = self.invoke_callback(
                py,
                &strategy,
                "finalize",
                CALLBACK_FINALIZE,
                last_bar,
                &mut output,
            )?;
        }
        if release_between_callbacks {
            output.gil_acquisitions = output.python_callback_calls.saturating_add(1);
        }
        self.finish_run_output(&mut output);
        Py::new(py, ReactiveNumericRunOutputCore { data: Some(output) })
    }

    fn run_block_range(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        start_bar: usize,
        end_bar: Option<usize>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveNumericRunOutputCore>> {
        if self.started {
            return Err(PyRuntimeError::new_err(
                "ReactiveNumericRunnerCore must be reset before a second run",
            ));
        }
        if self.poisoned {
            return Err(PyRuntimeError::new_err(
                "ReactiveNumericRunnerCore is poisoned after a prior callback failure",
            ));
        }
        let (start_bar, end_bar) = self.validate_window(start_bar, end_bar)?;
        let release_between_callbacks = Self::normalize_gil_policy(gil_policy)?;
        self.started = true;
        self.run_count = self.run_count.saturating_add(1);
        self.begin_fresh_window(start_bar)?;
        self.begin_runtime_deadline();
        let mut output = self.new_run_output(
            release_between_callbacks,
            "numeric_block_intent_v1",
            start_bar,
            end_bar,
        )?;

        let first = self.advance_bar(py, start_bar, release_between_callbacks, &mut output)?;
        self.project_context(py, start_bar, 0, &first, &mut output)?;
        let _ = self.invoke_callback(
            py,
            &strategy,
            "initialize",
            CALLBACK_INITIALIZE,
            start_bar,
            &mut output,
        )?;
        let mut previous = ReusableWakeObservationV1::with_symbols(self.inner.market.n_symbols);
        let mut current = ReusableWakeObservationV1::with_symbols(self.inner.market.n_symbols);
        output.wake_observation_buffer_allocations = 2;
        self.refresh_wake_observation(start_bar, &first, &mut previous)?;
        output.wake_observation_refreshes = output.wake_observation_refreshes.saturating_add(1);
        let mut active_block = if first.liquidated || end_bar <= start_bar.saturating_add(1) {
            None
        } else {
            self.project_context(py, start_bar, WAKE_INITIAL, &first, &mut output)?;
            Some(self.invoke_block_provider(
                py,
                &strategy,
                start_bar,
                start_bar.saturating_add(1),
                end_bar,
                WAKE_INITIAL,
                &mut output,
            )?)
        };

        for bar in start_bar.saturating_add(1)..end_bar {
            let step = self.advance_bar(py, bar, release_between_callbacks, &mut output)?;
            self.refresh_wake_observation(bar, &step, &mut current)?;
            output.wake_observation_refreshes = output.wake_observation_refreshes.saturating_add(1);
            let Some(block) = active_block else {
                std::mem::swap(&mut previous, &mut current);
                if step.liquidated {
                    break;
                }
                continue;
            };
            let margin_changed = (current.initial_margin - previous.initial_margin).abs()
                > 1e-12
                    * current
                        .initial_margin
                        .abs()
                        .max(previous.initial_margin.abs())
                        .max(1.0);
            let invalidated = (block.invalidate_on_fill && step.fill_count > 0)
                || (block.invalidate_on_reject && step.rejected_count > 0)
                || (block.invalidate_on_margin_change && margin_changed);
            let reached_stop = bar.saturating_add(1) >= block.stop_bar;
            let next_start = bar.saturating_add(1);
            if invalidated {
                self.invalidate_scheduled_from(next_start, &mut output);
            }
            if !step.liquidated && next_start < end_bar && (invalidated || reached_stop) {
                let mut wake_reason_mask = 0;
                if invalidated {
                    wake_reason_mask |= WAKE_BLOCK_INVALIDATED;
                }
                if reached_stop {
                    wake_reason_mask |= WAKE_TIME;
                }
                self.project_context(py, bar, wake_reason_mask, &step, &mut output)?;
                active_block = Some(self.invoke_block_provider(
                    py,
                    &strategy,
                    bar,
                    next_start,
                    end_bar,
                    wake_reason_mask,
                    &mut output,
                )?);
            }
            std::mem::swap(&mut previous, &mut current);
            if step.liquidated {
                break;
            }
        }

        if !self.inner.liquidated {
            let last_bar = end_bar.saturating_sub(1);
            let step = self.final_step(&output);
            self.project_context(py, last_bar, 0, &step, &mut output)?;
            let _ = self.invoke_callback(
                py,
                &strategy,
                "finalize",
                CALLBACK_FINALIZE,
                last_bar,
                &mut output,
            )?;
        }
        if release_between_callbacks {
            output.gil_acquisitions = output.python_callback_calls.saturating_add(1);
        }
        self.finish_run_output(&mut output);
        Py::new(py, ReactiveNumericRunOutputCore { data: Some(output) })
    }
}

#[pymethods]
impl ReactiveNumericRunnerCore {
    #[classmethod]
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        prepared,
        contract_sizes,
        leverages,
        fee_rates,
        qty_step,
        min_qty,
        min_notional,
        initial_capital,
        maintenance_ratio,
        slippage_rate,
        use_funding,
        market_mask,
        account_mask,
        positions_enabled,
        need_context_fills,
        need_context_events,
        need_context_active_orders,
        retain_fills,
        retain_events,
        command_initial_capacity,
        command_hard_limit,
        retain_account_paths=true,
        retain_command_rows=true,
        retain_callback_trace=true,
        retain_terminal_active_orders=true,
        scalar_metrics=false,
        score_trading_days=365,
        score_bar_annualization=365.0
    ))]
    fn from_prepared(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        prepared: Py<FullPreparedMarketCore>,
        contract_sizes: PyReadonlyArray1<'_, f64>,
        leverages: PyReadonlyArray1<'_, f64>,
        fee_rates: PyReadonlyArray1<'_, f64>,
        qty_step: PyReadonlyArray1<'_, f64>,
        min_qty: PyReadonlyArray1<'_, f64>,
        min_notional: PyReadonlyArray1<'_, f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
        market_mask: u8,
        account_mask: u8,
        positions_enabled: bool,
        need_context_fills: bool,
        need_context_events: bool,
        need_context_active_orders: bool,
        retain_fills: bool,
        retain_events: bool,
        command_initial_capacity: usize,
        command_hard_limit: usize,
        retain_account_paths: bool,
        retain_command_rows: bool,
        retain_callback_trace: bool,
        retain_terminal_active_orders: bool,
        scalar_metrics: bool,
        score_trading_days: i64,
        score_bar_annualization: f64,
    ) -> PyResult<Self> {
        let market = prepared.borrow(py).inner.clone();
        let retention = ReactiveRetentionProfileV1 {
            account_paths: retain_account_paths,
            command_rows: retain_command_rows,
            callback_trace: retain_callback_trace,
            terminal_active_orders: retain_terminal_active_orders,
            scalar_metrics,
            trading_days: score_trading_days,
            bar_annualization: score_bar_annualization,
        };
        if retention.scalar_metrics
            && (retention.trading_days <= 0
                || !retention.bar_annualization.is_finite()
                || retention.bar_annualization <= 0.0)
        {
            return Err(PyValueError::new_err(
                "reactive scalar score needs positive trading_days and bar annualization",
            ));
        }
        Self::create_from_parts(
            py,
            market,
            contract_sizes.as_slice()?.to_vec(),
            leverages.as_slice()?.to_vec(),
            fee_rates.as_slice()?.to_vec(),
            qty_step.as_slice()?.to_vec(),
            min_qty.as_slice()?.to_vec(),
            min_notional.as_slice()?.to_vec(),
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
            market_mask,
            account_mask,
            positions_enabled,
            need_context_fills,
            need_context_events,
            need_context_active_orders,
            retain_fills,
            retain_events,
            command_initial_capacity,
            command_hard_limit,
            retention,
        )
    }

    fn set_event_contract(&mut self, contract_code: i64) -> PyResult<()> {
        self.inner
            .set_event_contract(contract_code)
            .map_err(PyValueError::new_err)
    }

    #[getter]
    fn last_callback_name(&self) -> String {
        self.last_callback_name.clone()
    }

    #[getter]
    fn last_callback_bar(&self) -> i64 {
        self.last_callback_bar
    }

    #[getter]
    fn poisoned(&self) -> bool {
        self.poisoned
    }

    #[getter]
    fn run_count(&self) -> u64 {
        self.run_count
    }

    #[getter]
    fn reset_count(&self) -> u64 {
        self.reset_count
    }

    /// Return an independent, thread-safe token for cooperative cancellation.
    /// It does not retain or expose account/session state.
    fn cancellation_token(&self, py: Python<'_>) -> PyResult<Py<ReactiveCancellationTokenCore>> {
        Py::new(
            py,
            ReactiveCancellationTokenCore {
                requested: Arc::clone(&self.cancel_requested),
            },
        )
    }

    fn request_cancel(&self) {
        self.cancel_requested.store(true, Ordering::Release);
    }

    fn clear_cancellation(&self) {
        self.cancel_requested.store(false, Ordering::Release);
    }

    /// Set a native wall-clock deadline for each subsequent run. The deadline
    /// starts only after the fresh account/window has been initialized.
    #[pyo3(signature = (deadline_ms=None))]
    fn set_deadline_ms(&mut self, deadline_ms: Option<u64>) -> PyResult<()> {
        if self.started {
            return Err(PyRuntimeError::new_err(
                "ReactiveNumericRunnerCore deadline cannot change during an active run",
            ));
        }
        if matches!(deadline_ms, Some(0)) {
            return Err(PyValueError::new_err(
                "reactive native deadline_ms must be > 0 or None",
            ));
        }
        self.deadline_after = deadline_ms.map(Duration::from_millis);
        self.active_deadline = None;
        Ok(())
    }

    #[pyo3(signature = (strategy, gil_policy="held_for_session"))]
    fn run(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveNumericRunOutputCore>> {
        self.run_every_bar_window(py, strategy, 0, None, gil_policy)
    }

    #[pyo3(signature = (strategy, start_bar=0, end_bar=None, gil_policy="held_for_session"))]
    fn run_window(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        start_bar: usize,
        end_bar: Option<usize>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveNumericRunOutputCore>> {
        self.run_every_bar_window(py, strategy, start_bar, end_bar, gil_policy)
    }

    #[pyo3(signature = (strategy, gil_policy="held_for_session"))]
    fn run_sparse(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveNumericRunOutputCore>> {
        self.run_sparse_range(py, strategy, 0, None, gil_policy)
    }

    #[pyo3(signature = (strategy, start_bar=0, end_bar=None, gil_policy="held_for_session"))]
    fn run_sparse_window(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        start_bar: usize,
        end_bar: Option<usize>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveNumericRunOutputCore>> {
        self.run_sparse_range(py, strategy, start_bar, end_bar, gil_policy)
    }

    #[pyo3(signature = (strategy, gil_policy="held_for_session"))]
    fn run_block(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveNumericRunOutputCore>> {
        self.run_block_range(py, strategy, 0, None, gil_policy)
    }

    #[pyo3(signature = (strategy, start_bar=0, end_bar=None, gil_policy="held_for_session"))]
    fn run_block_window(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        start_bar: usize,
        end_bar: Option<usize>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveNumericRunOutputCore>> {
        self.run_block_range(py, strategy, start_bar, end_bar, gil_policy)
    }

    fn reset(&mut self, py: Python<'_>) -> PyResult<()> {
        self.inner.reset();
        self.step_buffers.clear();
        self.scheduled_commands.clear();
        self.context.bind(py).borrow_mut().invalidate_internal();
        self.writer.bind(py).borrow_mut().reset_session();
        self.started = false;
        self.poisoned = false;
        self.cancel_requested.store(false, Ordering::Release);
        self.active_deadline = None;
        self.last_callback_name.clear();
        self.last_callback_bar = -1;
        self.reset_count = self.reset_count.checked_add(1).ok_or_else(|| {
            PyRuntimeError::new_err("reactive session reset generation exhausted; recreate runner")
        })?;
        Ok(())
    }

    fn release_excess_capacity(&mut self, max_capacity: usize) {
        self.inner.release_resettable_scratch_capacity(max_capacity);
        self.step_buffers.release_excess_capacity(max_capacity);
        self.scheduled_commands.clear();
    }

    /// Cold-path reuse observability. The result is scalar metadata only and
    /// never exposes mutable account, command, or scratch buffers.
    fn session_diagnostics(&self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let payload = PyDict::new(py);
        let versions = self.inner.derived_account_versions();
        let (fills, events, active) = self.step_buffers.capacity_signature();
        payload.set_item("reset_manifest", "quantbt-native-reset-manifest-v1")?;
        payload.set_item("retained_output_policy", "owned_transfer_no_lease_v1")?;
        payload.set_item("run_count", self.run_count)?;
        payload.set_item("reset_count", self.reset_count)?;
        payload.set_item("session_reset_count", self.inner.session_reset_count())?;
        payload.set_item(
            "derived_account_cache_hits",
            self.inner.derived_account_cache_hits(),
        )?;
        payload.set_item(
            "derived_account_recomputes",
            self.inner.derived_account_recomputes(),
        )?;
        payload.set_item("mark_version", versions.mark)?;
        payload.set_item("position_version", versions.position)?;
        payload.set_item("wallet_version", versions.wallet)?;
        payload.set_item("reservation_version", versions.reservation)?;
        payload.set_item("fee_version", versions.fee)?;
        payload.set_item("funding_version", versions.funding)?;
        payload.set_item("risk_version", versions.risk)?;
        payload.set_item("instrument_version", versions.instrument)?;
        payload.set_item("local_step_fill_buffer_capacity", fills)?;
        payload.set_item("local_step_event_buffer_capacity", events)?;
        payload.set_item("local_step_active_order_buffer_capacity", active)?;
        payload.set_item(
            "matching_candidate_capacity",
            self.inner.matching_candidate_capacity(),
        )?;
        payload.set_item(
            "order_arena_retired_slots",
            self.inner.order_arena_retired_slots(),
        )?;
        payload.set_item("scheduled_command_buckets", self.scheduled_commands.len())?;
        payload.set_item("poisoned", self.poisoned)?;
        Ok(payload.unbind())
    }
}

const MAX_REACTIVE_CANDIDATE_BATCH: usize = 64;

struct CandidateRuntimeState {
    core: ReactiveNumericRunnerCore,
    active: bool,
    plan: WakePlanInternal,
    previous: ReusableWakeObservationV1,
    current_observation: ReusableWakeObservationV1,
    has_previous_observation: bool,
    current: full::FullStepResult,
    wake_reason_mask: i64,
    error_code: i64,
}

#[pyclass(name = "ReactiveCandidateBatchRunOutputV1", module = "_quantbt_native")]
pub(crate) struct ReactiveCandidateBatchRunOutputCore {
    data: Option<Vec<ReactiveRunData>>,
    candidate_ids: Vec<i64>,
    candidate_error_codes: Vec<i64>,
    batch_callback_count: usize,
    batch_callback_bar: Vec<i64>,
    batch_callback_candidate_count: Vec<i64>,
}

#[pymethods]
impl ReactiveCandidateBatchRunOutputCore {
    #[getter]
    fn consumed(&self) -> bool {
        self.data.is_none()
    }

    /// Transfer one result payload per candidate after the shared Rust tape
    /// has completed. No Python execution replay is performed here.
    fn consume(&mut self, py: Python<'_>) -> PyResult<Py<PyDict>> {
        let data = self.data.take().ok_or_else(|| {
            PyRuntimeError::new_err("ReactiveCandidateBatchRunOutputV1 was already consumed")
        })?;
        let candidates = PyList::empty(py);
        for candidate_data in data {
            let mut output = ReactiveNumericRunOutputCore {
                data: Some(candidate_data),
            };
            candidates.append(output.consume(py)?)?;
        }
        let payload = PyDict::new(py);
        payload.set_item(
            "candidate_ids",
            PyArray1::from_vec(py, self.candidate_ids.clone()),
        )?;
        payload.set_item(
            "candidate_error_codes",
            PyArray1::from_vec(py, self.candidate_error_codes.clone()),
        )?;
        payload.set_item("batch_callback_count", self.batch_callback_count)?;
        payload.set_item(
            "batch_callback_bar",
            PyArray1::from_vec(py, self.batch_callback_bar.clone()),
        )?;
        payload.set_item(
            "batch_callback_candidate_count",
            PyArray1::from_vec(py, self.batch_callback_candidate_count.clone()),
        )?;
        payload.set_item("candidate_outputs", candidates)?;
        Ok(payload.unbind())
    }
}

/// One shared immutable market tape with independent Rust-owned candidate
/// sessions. Python receives one batch callback per coalesced wake bar.
#[pyclass]
pub(crate) struct ReactiveCandidateBatchRunnerCore {
    candidates: Vec<CandidateRuntimeState>,
    context: Py<ReactiveCandidateBatchContextV1>,
    writer: Py<ReactiveCandidateCommandBatchV1>,
    started: bool,
    poisoned: bool,
    run_count: u64,
    last_callback_name: String,
    last_callback_bar: i64,
}

impl ReactiveCandidateBatchRunnerCore {
    fn candidate_error(&mut self, py: Python<'_>, candidate: usize, code: i64) {
        let runtime = &mut self.candidates[candidate];
        runtime.active = false;
        runtime.error_code = code;
        runtime.core.writer.bind(py).borrow_mut().end_callback();
        runtime
            .core
            .context
            .bind(py)
            .borrow_mut()
            .invalidate_internal();
    }

    #[allow(clippy::too_many_arguments)]
    fn invoke_batch_callback(
        &mut self,
        py: Python<'_>,
        strategy: &Py<PyAny>,
        bar: usize,
        candidates: &[usize],
        outputs: &mut [ReactiveRunData],
        batch_callback_bar: &mut Vec<i64>,
        batch_callback_candidate_count: &mut Vec<i64>,
    ) -> PyResult<()> {
        if candidates.is_empty() {
            return Ok(());
        }
        let callable = strategy.bind(py).getattr("on_wake_batch").map_err(|error| {
            if error.is_instance_of::<PyAttributeError>(py) {
                PyTypeError::new_err(
                    "numeric candidate batch strategies must implement on_wake_batch(context_batch, out_batch) -> CandidateWakePlansV1",
                )
            } else {
                error
            }
        })?;
        let timestamp_ns = self.candidates[candidates[0]]
            .core
            .inner
            .timestamp_ns_at(bar)
            .map_err(PyValueError::new_err)?;
        let projection_started = Instant::now();
        let copied = self.context.bind(py).borrow_mut().refresh(
            bar,
            timestamp_ns,
            candidates,
            &self.candidates,
        )?;
        let projection_ns = projection_started.elapsed().as_nanos();
        for &candidate in candidates {
            outputs[candidate].context_projection_ns += projection_ns;
            outputs[candidate].context_copy_bytes += copied;
            if outputs[candidate].retention.callback_trace {
                outputs[candidate].callback_kind.push(CALLBACK_WAKE);
                outputs[candidate].callback_bar.push(bar as i64);
                outputs[candidate].callback_timestamp_ns.push(timestamp_ns);
                outputs[candidate]
                    .callback_equity
                    .push(self.candidates[candidate].current.equity);
                outputs[candidate].callback_position_0.push(
                    self.candidates[candidate]
                        .core
                        .inner
                        .positions
                        .first()
                        .copied()
                        .unwrap_or(0.0),
                );
                outputs[candidate].wake_bar.push(bar as i64);
                outputs[candidate]
                    .wake_reason_mask
                    .push(self.candidates[candidate].wake_reason_mask);
            }
        }
        self.writer
            .bind(py)
            .borrow_mut()
            .begin_callback(py, candidates);
        self.last_callback_name = "on_wake_batch".to_owned();
        self.last_callback_bar = bar as i64;
        let context = self.context.bind(py);
        let writer = self.writer.bind(py);
        let started = Instant::now();
        let response = callable.call1((context, writer));
        let callback_ns = started.elapsed().as_nanos();
        batch_callback_bar.push(bar as i64);
        batch_callback_candidate_count.push(candidates.len() as i64);
        for &candidate in candidates {
            outputs[candidate].callback_ns += callback_ns;
            outputs[candidate].python_callback_calls += 1;
        }
        let response = match response {
            Ok(value) => value,
            Err(error) => {
                self.poisoned = true;
                for &candidate in candidates {
                    self.writer
                        .bind(py)
                        .borrow_mut()
                        .end_candidate(py, candidate);
                    self.candidates[candidate]
                        .core
                        .context
                        .bind(py)
                        .borrow_mut()
                        .invalidate_internal();
                }
                self.writer.bind(py).borrow_mut().invalidate_internal();
                self.context.bind(py).borrow_mut().invalidate_internal();
                return Err(error);
            }
        };
        let typed_wires = match response.call_method0("as_native_wire") {
            Ok(value) => Some(value.extract::<CandidateWakePlanWireV1>().map_err(|_| {
                self.poisoned = true;
                for &candidate in candidates {
                    self.writer
                        .bind(py)
                        .borrow_mut()
                        .end_candidate(py, candidate);
                    self.candidates[candidate]
                        .core
                        .context
                        .bind(py)
                        .borrow_mut()
                        .invalidate_internal();
                }
                self.writer.bind(py).borrow_mut().invalidate_internal();
                self.context.bind(py).borrow_mut().invalidate_internal();
                PyTypeError::new_err(
                    "CandidateWakePlansV1.as_native_wire() must return typed candidate wake rows",
                )
            })?),
            Err(error) if error.is_instance_of::<PyAttributeError>(py) => None,
            Err(_) => {
                self.poisoned = true;
                for &candidate in candidates {
                    self.writer
                        .bind(py)
                        .borrow_mut()
                        .end_candidate(py, candidate);
                    self.candidates[candidate]
                        .core
                        .context
                        .bind(py)
                        .borrow_mut()
                        .invalidate_internal();
                }
                self.writer.bind(py).borrow_mut().invalidate_internal();
                self.context.bind(py).borrow_mut().invalidate_internal();
                return Err(PyTypeError::new_err(
                    "numeric candidate batch on_wake_batch must return CandidateWakePlansV1",
                ));
            }
        };
        let payload_value = if typed_wires.is_none() {
            Some(response.call_method0("as_native_payload").map_err(|_| {
                PyTypeError::new_err(
                    "numeric candidate batch on_wake_batch must return CandidateWakePlansV1",
                )
            })?)
        } else {
            None
        };
        let payload = if let Some(payload_value) = payload_value.as_ref() {
            Some(payload_value.cast::<PyDict>().map_err(|_| {
                PyTypeError::new_err("CandidateWakePlansV1.as_native_payload() must return a dict")
            })?)
        } else {
            None
        };
        let failed_codes = self.writer.bind(py).borrow().failed_codes.clone();
        for &candidate in candidates {
            if let Some(code) = failed_codes.get(&candidate).copied() {
                self.candidate_error(py, candidate, code);
                continue;
            }
            let plan = if let Some(wires) = typed_wires.as_ref() {
                match wires
                    .iter()
                    .find(|(candidate_id, _)| *candidate_id == candidate as i64)
                {
                    Some((_, wire)) => self.candidates[candidate].core.parse_wake_wire(wire, bar),
                    None => Err(PyValueError::new_err(
                        "candidate batch wake response omitted an active candidate plan",
                    )),
                }
            } else {
                let payload = payload
                    .as_ref()
                    .expect("legacy payload is required without typed wire");
                let plan_value = payload.get_item(candidate as i64)?;
                let Some(plan_value) = plan_value else {
                    self.candidate_error(py, candidate, 2);
                    continue;
                };
                let plan_payload = match plan_value.cast::<PyDict>() {
                    Ok(value) => value,
                    Err(_) => {
                        self.candidate_error(py, candidate, 2);
                        continue;
                    }
                };
                self.candidates[candidate]
                    .core
                    .parse_wake_payload(plan_payload, bar)
            };
            let plan = match plan {
                Ok(plan) => plan,
                Err(_) => {
                    self.candidate_error(py, candidate, 2);
                    continue;
                }
            };
            let ingest = self.candidates[candidate].core.ingest_writer(
                py,
                bar,
                bar + 1,
                false,
                None,
                &mut outputs[candidate],
            );
            if ingest.is_err() {
                self.candidate_error(py, candidate, 2);
                continue;
            }
            self.candidates[candidate].plan = plan;
        }
        self.writer.bind(py).borrow_mut().invalidate_internal();
        self.context.bind(py).borrow_mut().invalidate_internal();
        Ok(())
    }

    fn run_range(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        start_bar: usize,
        end_bar: Option<usize>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveCandidateBatchRunOutputCore>> {
        if self.started {
            return Err(PyRuntimeError::new_err(
                "ReactiveCandidateBatchRunnerCore must be reset before a second run",
            ));
        }
        if self.poisoned {
            return Err(PyRuntimeError::new_err(
                "ReactiveCandidateBatchRunnerCore is poisoned after a prior callback failure",
            ));
        }
        let (start_bar, end_bar) = self.candidates[0]
            .core
            .validate_window(start_bar, end_bar)?;
        let release_between_callbacks =
            ReactiveNumericRunnerCore::normalize_gil_policy(gil_policy)?;
        self.started = true;
        self.run_count = self.run_count.saturating_add(1);
        // WFO windows retain absolute prepared-market coordinates while every
        // candidate account starts flat.  The single-candidate R1/R2/R3
        // runners establish this cursor before their first step; R3B must do
        // the identical operation for every isolated account rather than
        // attempting to replay the zero-position prefix.
        for candidate in &mut self.candidates {
            candidate.core.begin_fresh_window(start_bar)?;
            candidate.core.begin_runtime_deadline();
        }
        let mut outputs = self
            .candidates
            .iter()
            .map(|candidate| {
                candidate.core.new_run_output(
                    release_between_callbacks,
                    "numeric_candidate_batch_v1",
                    start_bar,
                    end_bar,
                )
            })
            .collect::<PyResult<Vec<_>>>()?;
        for output in &mut outputs {
            // One previous/current pair is owned per isolated account. It is
            // reused for the full candidate window and never shared across
            // candidates or folds.
            output.wake_observation_buffer_allocations = 2;
        }
        let mut batch_callback_bar = Vec::new();
        let mut batch_callback_candidate_count = Vec::new();

        for bar in start_bar..end_bar {
            let mut wakes = Vec::new();
            for (candidate, output) in outputs.iter_mut().enumerate() {
                if !self.candidates[candidate].active {
                    continue;
                }
                let runtime = &mut self.candidates[candidate];
                let step = runtime
                    .core
                    .advance_bar(py, bar, release_between_callbacks, output)?;
                runtime.core.refresh_wake_observation(
                    bar,
                    &step,
                    &mut runtime.current_observation,
                )?;
                output.wake_observation_refreshes =
                    output.wake_observation_refreshes.saturating_add(1);
                let reason = if !runtime.has_previous_observation {
                    WAKE_INITIAL
                } else {
                    runtime.core.wake_reasons(
                        &runtime.plan,
                        bar,
                        &step,
                        &runtime.previous,
                        &runtime.current_observation,
                    )?
                };
                runtime.current = step;
                std::mem::swap(&mut runtime.previous, &mut runtime.current_observation);
                runtime.has_previous_observation = true;
                runtime.wake_reason_mask = reason;
                if reason != 0 {
                    wakes.push(candidate);
                }
            }
            if !wakes.is_empty() {
                self.invoke_batch_callback(
                    py,
                    &strategy,
                    bar,
                    &wakes,
                    &mut outputs,
                    &mut batch_callback_bar,
                    &mut batch_callback_candidate_count,
                )?;
            }
            for candidate in 0..self.candidates.len() {
                if self.candidates[candidate].current.liquidated {
                    self.candidates[candidate].active = false;
                }
            }
        }

        for (candidate, output) in self.candidates.iter_mut().zip(outputs.iter_mut()) {
            if release_between_callbacks {
                output.gil_acquisitions = output.python_callback_calls.saturating_add(1);
            }
            candidate.core.finish_run_output(output);
        }
        let candidate_error_codes = self
            .candidates
            .iter()
            .map(|candidate| candidate.error_code)
            .collect();
        let candidate_ids = (0..self.candidates.len())
            .map(|value| value as i64)
            .collect();
        Py::new(
            py,
            ReactiveCandidateBatchRunOutputCore {
                data: Some(outputs),
                candidate_ids,
                candidate_error_codes,
                batch_callback_count: batch_callback_bar.len(),
                batch_callback_bar,
                batch_callback_candidate_count,
            },
        )
    }
}

#[pymethods]
impl ReactiveCandidateBatchRunnerCore {
    #[classmethod]
    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        prepared,
        candidate_count,
        contract_sizes,
        leverages,
        fee_rates,
        qty_step,
        min_qty,
        min_notional,
        initial_capital,
        maintenance_ratio,
        slippage_rate,
        use_funding,
        market_mask,
        account_mask,
        positions_enabled,
        need_context_fills,
        need_context_events,
        need_context_active_orders,
        retain_fills,
        retain_events,
        command_initial_capacity,
        command_hard_limit,
        retain_account_paths=true,
        retain_command_rows=true,
        retain_callback_trace=true,
        retain_terminal_active_orders=true,
        scalar_metrics=false,
        score_trading_days=365,
        score_bar_annualization=365.0
    ))]
    fn from_prepared(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        prepared: Py<FullPreparedMarketCore>,
        candidate_count: usize,
        contract_sizes: PyReadonlyArray1<'_, f64>,
        leverages: PyReadonlyArray1<'_, f64>,
        fee_rates: PyReadonlyArray1<'_, f64>,
        qty_step: PyReadonlyArray1<'_, f64>,
        min_qty: PyReadonlyArray1<'_, f64>,
        min_notional: PyReadonlyArray1<'_, f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
        market_mask: u8,
        account_mask: u8,
        positions_enabled: bool,
        need_context_fills: bool,
        need_context_events: bool,
        need_context_active_orders: bool,
        retain_fills: bool,
        retain_events: bool,
        command_initial_capacity: usize,
        command_hard_limit: usize,
        retain_account_paths: bool,
        retain_command_rows: bool,
        retain_callback_trace: bool,
        retain_terminal_active_orders: bool,
        scalar_metrics: bool,
        score_trading_days: i64,
        score_bar_annualization: f64,
    ) -> PyResult<Self> {
        if candidate_count == 0 || candidate_count > MAX_REACTIVE_CANDIDATE_BATCH {
            return Err(PyValueError::new_err(format!(
                "candidate_count must be in 1..={MAX_REACTIVE_CANDIDATE_BATCH}",
            )));
        }
        let market = prepared.borrow(py).inner.clone();
        let contract_sizes = contract_sizes.as_slice()?.to_vec();
        let leverages = leverages.as_slice()?.to_vec();
        let fee_rates = fee_rates.as_slice()?.to_vec();
        let qty_step = qty_step.as_slice()?.to_vec();
        let min_qty = min_qty.as_slice()?.to_vec();
        let min_notional = min_notional.as_slice()?.to_vec();
        let retention = ReactiveRetentionProfileV1 {
            account_paths: retain_account_paths,
            command_rows: retain_command_rows,
            callback_trace: retain_callback_trace,
            terminal_active_orders: retain_terminal_active_orders,
            scalar_metrics,
            trading_days: score_trading_days,
            bar_annualization: score_bar_annualization,
        };
        if retention.scalar_metrics
            && (retention.trading_days <= 0
                || !retention.bar_annualization.is_finite()
                || retention.bar_annualization <= 0.0)
        {
            return Err(PyValueError::new_err(
                "reactive scalar score needs positive trading_days and bar annualization",
            ));
        }
        let mut candidates = Vec::with_capacity(candidate_count);
        for _ in 0..candidate_count {
            let core = ReactiveNumericRunnerCore::create_from_parts(
                py,
                market.clone(),
                contract_sizes.clone(),
                leverages.clone(),
                fee_rates.clone(),
                qty_step.clone(),
                min_qty.clone(),
                min_notional.clone(),
                initial_capital,
                maintenance_ratio,
                slippage_rate,
                use_funding,
                market_mask,
                account_mask,
                positions_enabled,
                need_context_fills,
                need_context_events,
                need_context_active_orders,
                retain_fills,
                retain_events,
                command_initial_capacity,
                command_hard_limit,
                retention,
            )?;
            candidates.push(CandidateRuntimeState {
                core,
                active: true,
                plan: WakePlanInternal::default(),
                previous: ReusableWakeObservationV1::with_symbols(market.n_symbols),
                current_observation: ReusableWakeObservationV1::with_symbols(market.n_symbols),
                has_previous_observation: false,
                current: full::FullStepResult::default(),
                wake_reason_mask: WAKE_INITIAL,
                error_code: 0,
            });
        }
        let writers = candidates
            .iter()
            .map(|candidate| candidate.core.writer.clone_ref(py))
            .collect();
        Ok(Self {
            candidates,
            context: Py::new(
                py,
                ReactiveCandidateBatchContextV1::new_internal(market.n_symbols),
            )?,
            writer: Py::new(py, ReactiveCandidateCommandBatchV1::new_internal(writers))?,
            started: false,
            poisoned: false,
            run_count: 0,
            last_callback_name: String::new(),
            last_callback_bar: -1,
        })
    }

    fn set_event_contract(&mut self, contract_code: i64) -> PyResult<()> {
        for candidate in &mut self.candidates {
            candidate.core.set_event_contract(contract_code)?;
        }
        Ok(())
    }

    #[getter]
    fn last_callback_name(&self) -> String {
        self.last_callback_name.clone()
    }

    #[getter]
    fn last_callback_bar(&self) -> i64 {
        self.last_callback_bar
    }

    #[getter]
    fn candidate_count(&self) -> usize {
        self.candidates.len()
    }

    /// Cooperative cancellation is shared only as a stop request. Candidate
    /// accounts remain isolated and no partial candidate score is emitted.
    fn request_cancel(&self) {
        for candidate in &self.candidates {
            candidate.core.request_cancel();
        }
    }

    fn clear_cancellation(&self) {
        for candidate in &self.candidates {
            candidate.core.clear_cancellation();
        }
    }

    #[pyo3(signature = (deadline_ms=None))]
    fn set_deadline_ms(&mut self, deadline_ms: Option<u64>) -> PyResult<()> {
        if self.started {
            return Err(PyRuntimeError::new_err(
                "ReactiveCandidateBatchRunnerCore deadline cannot change during an active run",
            ));
        }
        for candidate in &mut self.candidates {
            candidate.core.set_deadline_ms(deadline_ms)?;
        }
        Ok(())
    }

    #[pyo3(signature = (strategy, gil_policy="held_for_session"))]
    fn run(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveCandidateBatchRunOutputCore>> {
        self.run_range(py, strategy, 0, None, gil_policy)
    }

    #[pyo3(signature = (strategy, start_bar=0, end_bar=None, gil_policy="held_for_session"))]
    fn run_window(
        &mut self,
        py: Python<'_>,
        strategy: Py<PyAny>,
        start_bar: usize,
        end_bar: Option<usize>,
        gil_policy: &str,
    ) -> PyResult<Py<ReactiveCandidateBatchRunOutputCore>> {
        self.run_range(py, strategy, start_bar, end_bar, gil_policy)
    }

    fn reset(&mut self, py: Python<'_>) -> PyResult<()> {
        for candidate in &mut self.candidates {
            candidate.core.reset(py)?;
            candidate.active = true;
            candidate.plan = WakePlanInternal::default();
            candidate.has_previous_observation = false;
            candidate.current = full::FullStepResult::default();
            candidate.wake_reason_mask = WAKE_INITIAL;
            candidate.error_code = 0;
        }
        self.context.bind(py).borrow_mut().invalidate_internal();
        self.writer.bind(py).borrow_mut().invalidate_internal();
        self.started = false;
        self.poisoned = false;
        self.last_callback_name.clear();
        self.last_callback_bar = -1;
        Ok(())
    }
}

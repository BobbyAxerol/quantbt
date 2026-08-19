mod accounting;
mod full;
mod generated_contracts;
mod matching;
mod session;
mod types;

use numpy::{PyArray1, PyReadonlyArray1, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyType};
use std::sync::Arc;

use full::{FullMarketData, FullSession};
use session::{PreparedMarketData, ReactiveSession};

const VERSION: &str = "0.4.0";
const API_VERSION: &str = "0.4";

#[pyfunction]
fn version() -> &'static str {
    VERSION
}

#[pyfunction]
fn api_version() -> &'static str {
    API_VERSION
}

#[pyfunction]
fn contract_registry_fingerprint() -> &'static str {
    generated_contracts::CONTRACT_REGISTRY_FINGERPRINT
}

#[pyfunction]
fn event_contract_ids() -> Vec<&'static str> {
    vec![
        generated_contracts::CONTRACT_ID_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE,
        generated_contracts::CONTRACT_ID_EVENT_LIFECYCLE_V3_NEXT_OPEN,
    ]
}

#[pyfunction]
fn capabilities(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let values = PyDict::new(py);
    values.set_item("r0_import_smoke", true)?;
    values.set_item("reactive_session", true)?;
    values.set_item("r1_single_symbol", true)?;
    values.set_item("r1_place_cancel_market_limit_gtc", true)?;
    values.set_item("r2_stop_amend_replace_reduce_only_constraints", true)?;
    values.set_item("prepared_market_core", true)?;
    values.set_item("rust_batched_tape", true)?;
    values.set_item("rust_batched_tape_score", true)?;
    values.set_item("rust_batched_tape_audit", true)?;
    values.set_item("rust_batched_tape_sparse", true)?;
    values.set_item("native_event_v2_full_contract", true)?;
    values.set_item("native_event_v2_multisymbol", true)?;
    values.set_item("native_event_v2_funding", true)?;
    values.set_item("native_event_v2_liquidation", true)?;
    values.set_item("native_event_v2_cancel_all_oco", true)?;
    values.set_item("native_event_v2_tif_expiry", true)?;
    values.set_item("native_event_v2_relationships", true)?;
    values.set_item("native_event_v2_quantity_preflight", true)?;
    values.set_item("event_contract_registry_v1", true)?;
    values.set_item("event_lifecycle_v2_next_bar_close", true)?;
    values.set_item("event_lifecycle_v3_next_open", true)?;
    values.set_item("bar_fill_reason_v1", true)?;
    values.set_item("lifecycle_transition_schema_v1", true)?;
    values.set_item("semantic_descriptor_v1", true)?;
    values.set_item("deterministic_quantization_v1", true)?;
    Ok(values)
}

#[pyfunction]
fn semantic_descriptor(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let descriptor = PyDict::new(py);
    descriptor.set_item("descriptor_version", "native-event-semantics-v1")?;
    descriptor.set_item("native_api", API_VERSION)?;
    descriptor.set_item("core_protocol_min", 1)?;
    descriptor.set_item("core_protocol_max", 1)?;
    descriptor.set_item(
        "contract_registry_fingerprint",
        generated_contracts::CONTRACT_REGISTRY_FINGERPRINT,
    )?;
    descriptor.set_item("trace_schema", "canonical-execution-trace-v1")?;
    descriptor.set_item("command_abi", "full-command-v1")?;
    descriptor.set_item(
        "contracts",
        vec![
            generated_contracts::CONTRACT_ID_EVENT_LIFECYCLE_V2_NEXT_BAR_CLOSE,
            generated_contracts::CONTRACT_ID_EVENT_LIFECYCLE_V3_NEXT_OPEN,
        ],
    )?;

    let orders = PyDict::new(py);
    orders.set_item(
        "types",
        vec!["market", "limit", "stop_market", "stop_limit"],
    )?;
    orders.set_item("partial_fill", false)?;
    orders.set_item("volume_model", "infinite_bar_liquidity")?;
    orders.set_item(
        "gap_policy",
        vec!["legacy_trigger", "open_worse_than_trigger"],
    )?;
    descriptor.set_item("orders", orders)?;

    let account = PyDict::new(py);
    account.set_item("pnl_models", vec!["linear_quote_settled"])?;
    account.set_item("margin_models", vec!["gross_cross"])?;
    account.set_item("liquidation_models", vec!["zero_equity_legacy"])?;
    descriptor.set_item("account", account)?;

    let portfolio = PyDict::new(py);
    portfolio.set_item("target_execution", false)?;
    portfolio.set_item("package_atomicity", "python_reference_only")?;
    descriptor.set_item("portfolio", portfolio)?;
    Ok(descriptor)
}

fn integer_units(value: f64, increment: f64, ceil_mode: bool) -> i64 {
    if increment <= 0.0 {
        return 0;
    }
    let scaled = value / increment;
    if ceil_mode {
        (scaled - 1e-12).ceil() as i64
    } else {
        (scaled + 1e-12).floor() as i64
    }
}

#[pyfunction]
fn quantize_price_v1(
    price: f64,
    tick_size: f64,
    side: i64,
    order_type: i64,
) -> PyResult<(f64, i64)> {
    if !price.is_finite() || !tick_size.is_finite() || price <= 0.0 || tick_size < 0.0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "price/tick_size are invalid",
        ));
    }
    if tick_size == 0.0 {
        return Ok((price, 0));
    }
    let is_limit_price = order_type == types::ORDER_LIMIT || order_type == types::ORDER_STOP_LIMIT;
    let ceil_mode = if is_limit_price { side < 0 } else { side > 0 };
    let ticks = integer_units(price, tick_size, ceil_mode);
    Ok((ticks as f64 * tick_size, ticks))
}

#[pyfunction]
#[pyo3(signature = (qty, price, qty_step, min_qty=0.0, max_qty=0.0, min_notional=0.0, contract_size=1.0))]
fn quantize_quantity_v1(
    qty: f64,
    price: f64,
    qty_step: f64,
    min_qty: f64,
    max_qty: f64,
    min_notional: f64,
    contract_size: f64,
) -> PyResult<(f64, i64, i64)> {
    let values = [
        qty,
        price,
        qty_step,
        min_qty,
        max_qty,
        min_notional,
        contract_size,
    ];
    if values.iter().any(|value| !value.is_finite())
        || qty <= 0.0
        || price <= 0.0
        || qty_step < 0.0
        || contract_size <= 0.0
    {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "quantity constraint values are invalid",
        ));
    }
    Ok(quantize_quantity_values(
        qty,
        price,
        qty_step,
        min_qty,
        max_qty,
        min_notional,
        contract_size,
    ))
}

#[pyfunction]
#[pyo3(signature = (price, qty, tick_size, qty_step, side, order_type, min_qty=0.0, max_qty=0.0, min_notional=0.0, contract_size=1.0))]
fn quantize_order_value_v1(
    price: f64,
    qty: f64,
    tick_size: f64,
    qty_step: f64,
    side: i64,
    order_type: i64,
    min_qty: f64,
    max_qty: f64,
    min_notional: f64,
    contract_size: f64,
) -> (f64, f64, i64, i64, i64) {
    let values = [
        price,
        qty,
        tick_size,
        qty_step,
        min_qty,
        max_qty,
        min_notional,
        contract_size,
    ];
    if values.iter().any(|value| !value.is_finite())
        || price <= 0.0
        || qty <= 0.0
        || tick_size < 0.0
        || qty_step < 0.0
        || contract_size <= 0.0
    {
        return (0.0, 0.0, 0, 0, 1);
    }
    let is_limit_price = order_type == types::ORDER_LIMIT || order_type == types::ORDER_STOP_LIMIT;
    let ceil_mode = if is_limit_price { side < 0 } else { side > 0 };
    let ticks = integer_units(price, tick_size, ceil_mode);
    let quantized_price = if tick_size > 0.0 {
        ticks as f64 * tick_size
    } else {
        price
    };
    let (quantized_qty, lots, mut reject_code) = quantize_quantity_values(
        qty,
        quantized_price.max(f64::MIN_POSITIVE),
        qty_step,
        min_qty,
        max_qty,
        min_notional,
        contract_size,
    );
    if quantized_price <= 0.0 {
        reject_code = 1;
    }
    (quantized_price, quantized_qty, ticks, lots, reject_code)
}

fn quantize_quantity_values(
    qty: f64,
    price: f64,
    qty_step: f64,
    min_qty: f64,
    max_qty: f64,
    min_notional: f64,
    contract_size: f64,
) -> (f64, i64, i64) {
    let lots = integer_units(qty, qty_step, false);
    let quantized = if qty_step > 0.0 {
        lots as f64 * qty_step
    } else {
        qty
    };
    let reject_code = if quantized <= 0.0 || quantized + 1e-12 < min_qty {
        2
    } else if max_qty > 0.0 && quantized - 1e-12 > max_qty {
        3
    } else if min_notional > 0.0 && quantized * price * contract_size + 1e-12 < min_notional {
        4
    } else {
        0
    };
    (quantized, lots, reject_code)
}

#[pyclass]
struct PreparedMarketCore {
    inner: Arc<PreparedMarketData>,
}

#[pyclass(frozen)]
struct BatchedScoreResultCore {
    #[pyo3(get)]
    final_equity: f64,
    #[pyo3(get)]
    final_position: f64,
    #[pyo3(get)]
    total_fee: f64,
    #[pyo3(get)]
    total_turnover: f64,
    #[pyo3(get)]
    fill_count: i64,
    #[pyo3(get)]
    event_count: i64,
    #[pyo3(get)]
    rejected_count: i64,
    #[pyo3(get)]
    canceled_count: i64,
    #[pyo3(get)]
    max_initial_margin: f64,
    #[pyo3(get)]
    max_maintenance_margin: f64,
    #[pyo3(get)]
    bars: usize,
}

impl PreparedMarketCore {
    #[allow(clippy::too_many_arguments)]
    fn from_arrays(
        timestamps_ns: PyReadonlyArray1<'_, i64>,
        opens: PyReadonlyArray1<'_, f64>,
        highs: PyReadonlyArray1<'_, f64>,
        lows: PyReadonlyArray1<'_, f64>,
        closes: PyReadonlyArray1<'_, f64>,
        volumes: PyReadonlyArray1<'_, f64>,
        funding: PyReadonlyArray1<'_, f64>,
        funding_mask: PyReadonlyArray1<'_, bool>,
    ) -> PyResult<Self> {
        let market = PreparedMarketData::new(
            timestamps_ns.as_slice()?.to_vec(),
            opens.as_slice()?.to_vec(),
            highs.as_slice()?.to_vec(),
            lows.as_slice()?.to_vec(),
            closes.as_slice()?.to_vec(),
            volumes.as_slice()?.to_vec(),
            funding.as_slice()?.to_vec(),
            funding_mask.as_slice()?.to_vec(),
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(market),
        })
    }
}

#[pymethods]
impl PreparedMarketCore {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        timestamps_ns: PyReadonlyArray1<'_, i64>,
        opens: PyReadonlyArray1<'_, f64>,
        highs: PyReadonlyArray1<'_, f64>,
        lows: PyReadonlyArray1<'_, f64>,
        closes: PyReadonlyArray1<'_, f64>,
        volumes: PyReadonlyArray1<'_, f64>,
        funding: PyReadonlyArray1<'_, f64>,
        funding_mask: PyReadonlyArray1<'_, bool>,
    ) -> PyResult<Self> {
        Self::from_arrays(
            timestamps_ns,
            opens,
            highs,
            lows,
            closes,
            volumes,
            funding,
            funding_mask,
        )
    }
}

#[pyclass]
struct ReactiveSessionCore {
    inner: ReactiveSession,
}

#[pymethods]
impl ReactiveSessionCore {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        timestamps_ns: PyReadonlyArray1<'_, i64>,
        opens: PyReadonlyArray1<'_, f64>,
        highs: PyReadonlyArray1<'_, f64>,
        lows: PyReadonlyArray1<'_, f64>,
        closes: PyReadonlyArray1<'_, f64>,
        volumes: PyReadonlyArray1<'_, f64>,
        funding: PyReadonlyArray1<'_, f64>,
        funding_mask: PyReadonlyArray1<'_, bool>,
        contract_size: f64,
        leverage: f64,
        fee_rate: f64,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> PyResult<Self> {
        let prepared = PreparedMarketCore::from_arrays(
            timestamps_ns,
            opens,
            highs,
            lows,
            closes,
            volumes,
            funding,
            funding_mask,
        )?;
        let inner = ReactiveSession::new(
            prepared.inner,
            contract_size,
            leverage,
            fee_rate,
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self { inner })
    }

    #[classmethod]
    #[allow(clippy::too_many_arguments)]
    fn from_prepared(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        prepared: Py<PreparedMarketCore>,
        contract_size: f64,
        leverage: f64,
        fee_rate: f64,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> PyResult<Self> {
        let market = prepared.borrow(py).inner.clone();
        let inner = ReactiveSession::new(
            market,
            contract_size,
            leverage,
            fee_rate,
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self { inner })
    }

    fn step(
        &mut self,
        py: Python<'_>,
        bar_index: usize,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let codes_shape = command_codes.shape();
        let values_shape = command_values.shape();
        if codes_shape.len() != 2 || codes_shape[1] != types::COMMAND_CODE_WIDTH {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "command_codes must have shape (n, 8)",
            ));
        }
        if values_shape.len() != 2
            || values_shape[0] != codes_shape[0]
            || values_shape[1] != types::COMMAND_VALUE_WIDTH
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "command_values must have shape (n, 3)",
            ));
        }
        if command_expiry.len() != codes_shape[0] {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "command_expiry must have length n",
            ));
        }
        let result = self
            .inner
            .step(
                bar_index,
                command_codes.as_slice()?,
                command_values.as_slice()?,
                command_expiry.as_slice()?,
                codes_shape[0],
            )
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("equity", result.equity)?;
        payload.set_item("position", result.position)?;
        payload.set_item("fee", result.fee)?;
        payload.set_item("turnover", result.turnover)?;
        payload.set_item("initial_margin", result.initial_margin)?;
        payload.set_item("maintenance_margin", result.maintenance_margin)?;
        payload.set_item("fills", result.fills)?;
        payload.set_item("events", result.events)?;
        payload.set_item("active_orders", result.active_orders)?;
        Ok(payload.unbind())
    }

    fn reset(&mut self) {
        self.inner.reset();
    }

    fn run_tape_score(
        &mut self,
        py: Python<'_>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<BatchedScoreResultCore>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let values = command_values.as_slice()?;
        let expiry = command_expiry.as_slice()?;
        let _count = validate_tape_arrays(
            self.inner.market_len(),
            ptr,
            codes,
            command_codes.shape(),
            values,
            command_values.shape(),
            expiry,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let output = py
            .detach(|| run_tape(&mut self.inner, ptr, codes, values, expiry, false))
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Py::new(
            py,
            BatchedScoreResultCore {
                final_equity: output.final_equity,
                final_position: output.final_position,
                total_fee: output.total_fee,
                total_turnover: output.total_turnover,
                fill_count: output.fill_count,
                event_count: output.event_count,
                rejected_count: output.rejected_count,
                canceled_count: output.canceled_count,
                max_initial_margin: output.max_initial_margin,
                max_maintenance_margin: output.max_maintenance_margin,
                bars: self.inner.market_len(),
            },
        )
    }

    fn run_tape_audit(
        &mut self,
        py: Python<'_>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let values = command_values.as_slice()?;
        let expiry = command_expiry.as_slice()?;
        let _count = validate_tape_arrays(
            self.inner.market_len(),
            ptr,
            codes,
            command_codes.shape(),
            values,
            command_values.shape(),
            expiry,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let output = py
            .detach(|| run_tape(&mut self.inner, ptr, codes, values, expiry, true))
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("equity", PyArray1::from_vec(py, output.equity))?;
        payload.set_item("positions", PyArray1::from_vec(py, output.positions))?;
        payload.set_item("fees", PyArray1::from_vec(py, output.fees))?;
        payload.set_item("turnover", PyArray1::from_vec(py, output.turnover))?;
        payload.set_item(
            "initial_margin",
            PyArray1::from_vec(py, output.initial_margin),
        )?;
        payload.set_item(
            "maintenance_margin",
            PyArray1::from_vec(py, output.maintenance_margin),
        )?;
        payload.set_item("fill_bar", PyArray1::from_vec(py, output.fill_bar))?;
        payload.set_item(
            "fill_order_id",
            PyArray1::from_vec(py, output.fill_order_id),
        )?;
        payload.set_item("fill_side", PyArray1::from_vec(py, output.fill_side))?;
        payload.set_item("fill_qty", PyArray1::from_vec(py, output.fill_qty))?;
        payload.set_item("fill_price", PyArray1::from_vec(py, output.fill_price))?;
        payload.set_item("fill_fee", PyArray1::from_vec(py, output.fill_fee))?;
        payload.set_item("event_bar", PyArray1::from_vec(py, output.event_bar))?;
        payload.set_item("event_kind", PyArray1::from_vec(py, output.event_kind))?;
        payload.set_item("event_status", PyArray1::from_vec(py, output.event_status))?;
        payload.set_item(
            "event_order_id",
            PyArray1::from_vec(py, output.event_order_id),
        )?;
        payload.set_item(
            "event_target_id",
            PyArray1::from_vec(py, output.event_target_id),
        )?;
        payload.set_item("total_fee", output.total_fee)?;
        payload.set_item("total_turnover", output.total_turnover)?;
        payload.set_item("fill_count", output.fill_count)?;
        payload.set_item("event_count", output.event_count)?;
        payload.set_item("rejected_count", output.rejected_count)?;
        payload.set_item("canceled_count", output.canceled_count)?;
        payload.set_item("max_initial_margin", output.max_initial_margin)?;
        payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
        Ok(payload.unbind())
    }

    #[allow(clippy::too_many_arguments)]
    fn run_until(
        &mut self,
        py: Python<'_>,
        stop_bar: usize,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
        wake_on_fill: bool,
        wake_on_order_event: bool,
        _wake_on_liquidation: bool,
    ) -> PyResult<Py<PyDict>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let values = command_values.as_slice()?;
        let expiry = command_expiry.as_slice()?;
        validate_tape_arrays(
            self.inner.market_len(),
            ptr,
            codes,
            command_codes.shape(),
            values,
            command_values.shape(),
            expiry,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        if stop_bar >= self.inner.market_len() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "stop_bar is outside the prepared market tape",
            ));
        }
        let start_bar = self.inner.next_bar();
        if start_bar > stop_bar {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "run_until must advance to a bar after the previous chunk",
            ));
        }
        let output = py
            .detach(|| {
                run_sparse_range(
                    &mut self.inner,
                    start_bar,
                    stop_bar,
                    ptr,
                    codes,
                    values,
                    expiry,
                    wake_on_fill,
                    wake_on_order_event,
                )
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("start_bar", output.start_bar)?;
        payload.set_item("stop_bar", output.stop_bar)?;
        payload.set_item("final_equity", output.final_equity)?;
        payload.set_item("final_position", output.final_position)?;
        payload.set_item("total_fee", output.total_fee)?;
        payload.set_item("total_turnover", output.total_turnover)?;
        payload.set_item("fill_count", output.fill_count)?;
        payload.set_item("event_count", output.event_count)?;
        payload.set_item("rejected_count", output.rejected_count)?;
        payload.set_item("canceled_count", output.canceled_count)?;
        payload.set_item("max_initial_margin", output.max_initial_margin)?;
        payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
        payload.set_item("liquidation_seen", output.liquidation_seen)?;
        payload.set_item("wake_bar", PyArray1::from_vec(py, output.wake_bar))?;
        payload.set_item("wake_kind", PyArray1::from_vec(py, output.wake_kind))?;
        payload.set_item("fill_bar", PyArray1::from_vec(py, output.fill_bar))?;
        payload.set_item(
            "fill_order_id",
            PyArray1::from_vec(py, output.fill_order_id),
        )?;
        payload.set_item("fill_side", PyArray1::from_vec(py, output.fill_side))?;
        payload.set_item("fill_qty", PyArray1::from_vec(py, output.fill_qty))?;
        payload.set_item("fill_price", PyArray1::from_vec(py, output.fill_price))?;
        payload.set_item("fill_fee", PyArray1::from_vec(py, output.fill_fee))?;
        payload.set_item("event_bar", PyArray1::from_vec(py, output.event_bar))?;
        payload.set_item("event_kind", PyArray1::from_vec(py, output.event_kind))?;
        payload.set_item("event_status", PyArray1::from_vec(py, output.event_status))?;
        payload.set_item(
            "event_order_id",
            PyArray1::from_vec(py, output.event_order_id),
        )?;
        payload.set_item(
            "event_target_id",
            PyArray1::from_vec(py, output.event_target_id),
        )?;
        Ok(payload.unbind())
    }
}

fn validate_tape_arrays(
    market_len: usize,
    command_ptr: &[i64],
    codes: &[i64],
    codes_shape: &[usize],
    values: &[f64],
    values_shape: &[usize],
    expiry: &[i64],
) -> Result<usize, String> {
    if command_ptr.len() != market_len + 1 {
        return Err("command_ptr must have length n_bars + 1".to_owned());
    }
    if codes_shape.len() != 2 || codes_shape[1] != types::COMMAND_CODE_WIDTH {
        return Err("command_codes must have shape (n, 8)".to_owned());
    }
    if values_shape.len() != 2
        || values_shape[0] != codes_shape[0]
        || values_shape[1] != types::COMMAND_VALUE_WIDTH
    {
        return Err("command_values must have shape (n, 3)".to_owned());
    }
    if expiry.len() != codes_shape[0] {
        return Err("command_expiry must have length n".to_owned());
    }
    if expiry.iter().any(|value| *value != -1) {
        return Err("Rust batched tape does not support expiry".to_owned());
    }
    if command_ptr.first().copied().unwrap_or(-1) != 0 {
        return Err("command_ptr must start at zero".to_owned());
    }
    let command_count = codes_shape[0] as i64;
    let mut previous = 0_i64;
    for &value in command_ptr {
        if value < previous || value > command_count {
            return Err("command_ptr must be monotonic and bounded by command count".to_owned());
        }
        previous = value;
    }
    if command_ptr.last().copied().unwrap_or(-1) != command_count {
        return Err("command_ptr last value must equal command count".to_owned());
    }
    if codes.len() != codes_shape[0] * types::COMMAND_CODE_WIDTH
        || values.len() != values_shape[0] * types::COMMAND_VALUE_WIDTH
    {
        return Err("command buffers are not contiguous with their declared shapes".to_owned());
    }
    Ok(codes_shape[0])
}

fn run_tape(
    session: &mut ReactiveSession,
    command_ptr: &[i64],
    codes: &[i64],
    values: &[f64],
    expiry: &[i64],
    audit: bool,
) -> Result<BatchedTapeOutput, String> {
    let n_bars = session.market_len();
    let mut equity = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut positions = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut fees = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut turnover = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut initial_margin = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut maintenance_margin = if audit {
        Vec::with_capacity(n_bars)
    } else {
        Vec::new()
    };
    let mut fill_bar = Vec::new();
    let mut fill_order_id = Vec::new();
    let mut fill_side = Vec::new();
    let mut fill_qty = Vec::new();
    let mut fill_price = Vec::new();
    let mut fill_fee = Vec::new();
    let mut event_bar = Vec::new();
    let mut event_kind = Vec::new();
    let mut event_status = Vec::new();
    let mut event_order_id = Vec::new();
    let mut event_target_id = Vec::new();
    let mut total_fee = 0.0;
    let mut total_turnover = 0.0;
    let mut fill_count = 0_i64;
    let mut event_count = 0_i64;
    let mut rejected_count = 0_i64;
    let mut canceled_count = 0_i64;
    let mut final_equity = 0.0;
    let mut final_position = 0.0;
    let mut max_initial_margin: f64 = 0.0;
    let mut max_maintenance_margin: f64 = 0.0;

    for bar in 0..n_bars {
        let start = command_ptr[bar] as usize;
        let end = command_ptr[bar + 1] as usize;
        let step = session.step_with_output(
            bar,
            &codes[start * types::COMMAND_CODE_WIDTH..end * types::COMMAND_CODE_WIDTH],
            &values[start * types::COMMAND_VALUE_WIDTH..end * types::COMMAND_VALUE_WIDTH],
            &expiry[start..end],
            end - start,
            audit,
        )?;
        if audit {
            equity.push(step.equity);
            positions.push(step.position);
            fees.push(step.fee);
            turnover.push(step.turnover);
            initial_margin.push(step.initial_margin);
            maintenance_margin.push(step.maintenance_margin);
        }
        final_equity = step.equity;
        final_position = step.position;
        max_initial_margin = max_initial_margin.max(step.initial_margin);
        max_maintenance_margin = max_maintenance_margin.max(step.maintenance_margin);
        total_fee += step.fee;
        total_turnover += step.turnover;
        fill_count += step.fill_count;
        event_count += step.event_count;
        rejected_count += step.rejected_count;
        canceled_count += step.canceled_count;
        for fill in step.fills {
            if audit {
                fill_bar.push(bar as i64);
                fill_order_id.push(fill[0] as i64);
                fill_side.push(fill[1] as i64);
                fill_qty.push(fill[2]);
                fill_price.push(fill[3]);
                fill_fee.push(fill[4]);
            }
        }
        for event in step.events {
            if audit {
                event_bar.push(bar as i64);
                event_kind.push(event[0]);
                event_status.push(event[1]);
                event_order_id.push(event[2]);
                event_target_id.push(event[3]);
            }
        }
    }
    Ok(BatchedTapeOutput {
        equity,
        positions,
        fees,
        turnover,
        initial_margin,
        maintenance_margin,
        total_fee,
        total_turnover,
        fill_count,
        event_count,
        rejected_count,
        canceled_count,
        fill_bar,
        fill_order_id,
        fill_side,
        fill_qty,
        fill_price,
        fill_fee,
        event_bar,
        event_kind,
        event_status,
        event_order_id,
        event_target_id,
        final_equity,
        final_position,
        max_initial_margin,
        max_maintenance_margin,
    })
}

#[allow(clippy::too_many_arguments)]
fn run_sparse_range(
    session: &mut ReactiveSession,
    start_bar: usize,
    stop_bar: usize,
    command_ptr: &[i64],
    codes: &[i64],
    values: &[f64],
    expiry: &[i64],
    wake_on_fill: bool,
    wake_on_order_event: bool,
) -> Result<SparseTapeOutput, String> {
    let mut output = SparseTapeOutput {
        start_bar,
        stop_bar,
        final_equity: 0.0,
        final_position: 0.0,
        total_fee: 0.0,
        total_turnover: 0.0,
        fill_count: 0,
        event_count: 0,
        rejected_count: 0,
        canceled_count: 0,
        max_initial_margin: 0.0,
        max_maintenance_margin: 0.0,
        liquidation_seen: false,
        wake_bar: Vec::new(),
        wake_kind: Vec::new(),
        fill_bar: Vec::new(),
        fill_order_id: Vec::new(),
        fill_side: Vec::new(),
        fill_qty: Vec::new(),
        fill_price: Vec::new(),
        fill_fee: Vec::new(),
        event_bar: Vec::new(),
        event_kind: Vec::new(),
        event_status: Vec::new(),
        event_order_id: Vec::new(),
        event_target_id: Vec::new(),
    };

    for bar in start_bar..=stop_bar {
        let start = command_ptr[bar] as usize;
        let end = command_ptr[bar + 1] as usize;
        let materialize = wake_on_fill || wake_on_order_event;
        let step = session.step_with_output(
            bar,
            &codes[start * types::COMMAND_CODE_WIDTH..end * types::COMMAND_CODE_WIDTH],
            &values[start * types::COMMAND_VALUE_WIDTH..end * types::COMMAND_VALUE_WIDTH],
            &expiry[start..end],
            end - start,
            materialize,
        )?;
        output.final_equity = step.equity;
        output.final_position = step.position;
        output.max_initial_margin = output.max_initial_margin.max(step.initial_margin);
        output.max_maintenance_margin = output.max_maintenance_margin.max(step.maintenance_margin);
        output.total_fee += step.fee;
        output.total_turnover += step.turnover;
        output.fill_count += step.fill_count;
        output.event_count += step.event_count;
        output.rejected_count += step.rejected_count;
        output.canceled_count += step.canceled_count;
        for fill in step.fills {
            if wake_on_fill {
                output.wake_bar.push(bar as i64);
                output.wake_kind.push(0);
            }
            output.fill_bar.push(bar as i64);
            output.fill_order_id.push(fill[0] as i64);
            output.fill_side.push(fill[1] as i64);
            output.fill_qty.push(fill[2]);
            output.fill_price.push(fill[3]);
            output.fill_fee.push(fill[4]);
        }
        for event in step.events {
            if wake_on_order_event {
                output.wake_bar.push(bar as i64);
                output.wake_kind.push(1);
            }
            output.event_bar.push(bar as i64);
            output.event_kind.push(event[0]);
            output.event_status.push(event[1]);
            output.event_order_id.push(event[2]);
            output.event_target_id.push(event[3]);
        }
    }
    // Kind 2 means end-of-chunk. It is always emitted so a caller can make
    // progress without reconstructing a dense per-bar result path.
    output.wake_bar.push(stop_bar as i64);
    output.wake_kind.push(2);
    Ok(output)
}

struct BatchedTapeOutput {
    equity: Vec<f64>,
    positions: Vec<f64>,
    fees: Vec<f64>,
    turnover: Vec<f64>,
    initial_margin: Vec<f64>,
    maintenance_margin: Vec<f64>,
    total_fee: f64,
    total_turnover: f64,
    fill_count: i64,
    event_count: i64,
    rejected_count: i64,
    canceled_count: i64,
    fill_bar: Vec<i64>,
    fill_order_id: Vec<i64>,
    fill_side: Vec<i64>,
    fill_qty: Vec<f64>,
    fill_price: Vec<f64>,
    fill_fee: Vec<f64>,
    event_bar: Vec<i64>,
    event_kind: Vec<i64>,
    event_status: Vec<i64>,
    event_order_id: Vec<i64>,
    event_target_id: Vec<i64>,
    final_equity: f64,
    final_position: f64,
    max_initial_margin: f64,
    max_maintenance_margin: f64,
}

struct SparseTapeOutput {
    start_bar: usize,
    stop_bar: usize,
    final_equity: f64,
    final_position: f64,
    total_fee: f64,
    total_turnover: f64,
    fill_count: i64,
    event_count: i64,
    rejected_count: i64,
    canceled_count: i64,
    max_initial_margin: f64,
    max_maintenance_margin: f64,
    liquidation_seen: bool,
    wake_bar: Vec<i64>,
    wake_kind: Vec<i64>,
    fill_bar: Vec<i64>,
    fill_order_id: Vec<i64>,
    fill_side: Vec<i64>,
    fill_qty: Vec<f64>,
    fill_price: Vec<f64>,
    fill_fee: Vec<f64>,
    event_bar: Vec<i64>,
    event_kind: Vec<i64>,
    event_status: Vec<i64>,
    event_order_id: Vec<i64>,
    event_target_id: Vec<i64>,
}

#[pyclass(frozen, skip_from_py_object)]
struct FullStepResultCore {
    #[pyo3(get)]
    equity: f64,
    #[pyo3(get)]
    fee: f64,
    #[pyo3(get)]
    turnover: f64,
    #[pyo3(get)]
    funding: f64,
    #[pyo3(get)]
    initial_margin: f64,
    #[pyo3(get)]
    maintenance_margin: f64,
    #[pyo3(get)]
    total_fee: f64,
    #[pyo3(get)]
    total_turnover: f64,
    #[pyo3(get)]
    total_funding: f64,
    #[pyo3(get)]
    total_rejected: i64,
    #[pyo3(get)]
    total_canceled: i64,
    #[pyo3(get)]
    fill_count: i64,
    #[pyo3(get)]
    event_count: i64,
    #[pyo3(get)]
    rejected_count: i64,
    #[pyo3(get)]
    canceled_count: i64,
    #[pyo3(get)]
    liquidated: bool,
    #[pyo3(get)]
    liquidation_bar: i64,
    #[pyo3(get)]
    liquidation_reason: i64,
    #[pyo3(get)]
    positions: Option<Vec<f64>>,
    #[pyo3(get)]
    fills: Option<Vec<Vec<f64>>>,
    #[pyo3(get)]
    events: Option<Vec<Vec<i64>>>,
    #[pyo3(get)]
    active_orders: Option<Vec<Vec<f64>>>,
    #[pyo3(get)]
    fill_begin: u64,
    #[pyo3(get)]
    fill_end: u64,
    #[pyo3(get)]
    event_begin: u64,
    #[pyo3(get)]
    event_end: u64,
    #[pyo3(get)]
    order_delta_begin: u64,
    #[pyo3(get)]
    order_delta_end: u64,
    #[pyo3(get)]
    position_delta_begin: u64,
    #[pyo3(get)]
    position_delta_end: u64,
}

impl FullStepResultCore {
    #[allow(clippy::too_many_arguments)]
    fn from_result(
        result: full::FullStepResult,
        output_mask: u8,
        total_fee: f64,
        total_turnover: f64,
        total_funding: f64,
        total_rejected: i64,
        total_canceled: i64,
        fill_begin: u64,
        event_begin: u64,
        order_delta_begin: u64,
        position_delta_begin: u64,
        position_delta_count: u64,
    ) -> Self {
        let fill_end = fill_begin + result.fill_count.max(0) as u64;
        let event_end = event_begin + result.event_count.max(0) as u64;
        let order_delta_end = order_delta_begin + result.event_count.max(0) as u64;
        Self {
            equity: result.equity,
            fee: result.fee,
            turnover: result.turnover,
            funding: result.funding,
            initial_margin: result.initial_margin,
            maintenance_margin: result.maintenance_margin,
            total_fee,
            total_turnover,
            total_funding,
            total_rejected,
            total_canceled,
            fill_count: result.fill_count,
            event_count: result.event_count,
            rejected_count: result.rejected_count,
            canceled_count: result.canceled_count,
            liquidated: result.liquidated,
            liquidation_bar: result.liquidation_bar,
            liquidation_reason: result.liquidation_reason,
            positions: (output_mask & full::OUTPUT_POSITIONS != 0).then_some(result.positions),
            fills: (output_mask & full::OUTPUT_FILLS != 0).then_some(result.fills),
            events: (output_mask & full::OUTPUT_EVENTS != 0).then_some(result.events),
            active_orders: (output_mask & full::OUTPUT_ACTIVE_ORDERS != 0)
                .then_some(result.active_orders),
            fill_begin,
            fill_end,
            event_begin,
            event_end,
            order_delta_begin,
            order_delta_end,
            position_delta_begin,
            position_delta_end: position_delta_begin + position_delta_count,
        }
    }
}

#[pyclass]
struct FullPreparedMarketCore {
    inner: Arc<FullMarketData>,
}

#[pymethods]
impl FullPreparedMarketCore {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        timestamps_ns: PyReadonlyArray1<'_, i64>,
        opens: PyReadonlyArray2<'_, f64>,
        highs: PyReadonlyArray2<'_, f64>,
        lows: PyReadonlyArray2<'_, f64>,
        closes: PyReadonlyArray2<'_, f64>,
        volumes: PyReadonlyArray2<'_, f64>,
        funding: PyReadonlyArray2<'_, f64>,
        funding_mask: PyReadonlyArray1<'_, bool>,
    ) -> PyResult<Self> {
        let shapes = [
            opens.shape(),
            highs.shape(),
            lows.shape(),
            closes.shape(),
            volumes.shape(),
            funding.shape(),
        ];
        if shapes
            .iter()
            .any(|shape| shape.len() != 2 || *shape != closes.shape())
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full OHLCV/funding arrays must share shape (n_bars, n_symbols)",
            ));
        }
        let market = FullMarketData::new(
            timestamps_ns.as_slice()?.to_vec(),
            opens.as_slice()?.to_vec(),
            highs.as_slice()?.to_vec(),
            lows.as_slice()?.to_vec(),
            closes.as_slice()?.to_vec(),
            volumes.as_slice()?.to_vec(),
            funding.as_slice()?.to_vec(),
            funding_mask.as_slice()?.to_vec(),
            closes.shape()[1],
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self {
            inner: Arc::new(market),
        })
    }

    #[getter]
    fn bars(&self) -> usize {
        self.inner.n_bars
    }

    #[getter]
    fn symbols(&self) -> usize {
        self.inner.n_symbols
    }
}

#[pyclass]
struct FullReactiveSessionCore {
    inner: FullSession,
    total_fee: f64,
    total_turnover: f64,
    total_funding: f64,
    total_rejected: i64,
    total_canceled: i64,
    fill_cursor: u64,
    event_cursor: u64,
    order_delta_cursor: u64,
    position_delta_cursor: u64,
    last_positions: Vec<f64>,
}

impl FullReactiveSessionCore {
    fn wrap(inner: FullSession) -> Self {
        let last_positions = vec![0.0; inner.market.n_symbols];
        Self {
            inner,
            total_fee: 0.0,
            total_turnover: 0.0,
            total_funding: 0.0,
            total_rejected: 0,
            total_canceled: 0,
            fill_cursor: 0,
            event_cursor: 0,
            order_delta_cursor: 0,
            position_delta_cursor: 0,
            last_positions,
        }
    }
}

#[pymethods]
impl FullReactiveSessionCore {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        timestamps_ns: PyReadonlyArray1<'_, i64>,
        opens: PyReadonlyArray2<'_, f64>,
        highs: PyReadonlyArray2<'_, f64>,
        lows: PyReadonlyArray2<'_, f64>,
        closes: PyReadonlyArray2<'_, f64>,
        volumes: PyReadonlyArray2<'_, f64>,
        funding: PyReadonlyArray2<'_, f64>,
        funding_mask: PyReadonlyArray1<'_, bool>,
        contract_sizes: PyReadonlyArray1<'_, f64>,
        leverages: PyReadonlyArray1<'_, f64>,
        fee_rates: PyReadonlyArray1<'_, f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> PyResult<Self> {
        let prepared = FullPreparedMarketCore::new(
            timestamps_ns,
            opens,
            highs,
            lows,
            closes,
            volumes,
            funding,
            funding_mask,
        )?;
        let inner = FullSession::new(
            prepared.inner.clone(),
            contract_sizes.as_slice()?.to_vec(),
            leverages.as_slice()?.to_vec(),
            fee_rates.as_slice()?.to_vec(),
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self::wrap(inner))
    }

    #[classmethod]
    #[allow(clippy::too_many_arguments)]
    fn from_prepared(
        _cls: &Bound<'_, PyType>,
        py: Python<'_>,
        prepared: Py<FullPreparedMarketCore>,
        contract_sizes: PyReadonlyArray1<'_, f64>,
        leverages: PyReadonlyArray1<'_, f64>,
        fee_rates: PyReadonlyArray1<'_, f64>,
        initial_capital: f64,
        maintenance_ratio: f64,
        slippage_rate: f64,
        use_funding: bool,
    ) -> PyResult<Self> {
        let market = prepared.borrow(py).inner.clone();
        let inner = FullSession::new(
            market,
            contract_sizes.as_slice()?.to_vec(),
            leverages.as_slice()?.to_vec(),
            fee_rates.as_slice()?.to_vec(),
            initial_capital,
            maintenance_ratio,
            slippage_rate,
            use_funding,
        )
        .map_err(pyo3::exceptions::PyValueError::new_err)?;
        Ok(Self::wrap(inner))
    }

    fn set_event_contract(&mut self, contract_code: i64) -> PyResult<()> {
        self.inner
            .set_event_contract(contract_code)
            .map_err(pyo3::exceptions::PyValueError::new_err)
    }

    #[getter]
    fn event_contract_code(&self) -> i64 {
        self.inner.event_contract_code
    }

    fn step(
        &mut self,
        py: Python<'_>,
        bar_index: usize,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let codes_shape = command_codes.shape();
        let values_shape = command_values.shape();
        if codes_shape.len() != 2 || codes_shape[1] != full::CODE_WIDTH {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full command_codes must have shape (n, 16)",
            ));
        }
        if values_shape.len() != 2
            || values_shape[0] != codes_shape[0]
            || values_shape[1] != full::VALUE_WIDTH
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full command_values must have shape (n, 3)",
            ));
        }
        if command_expiry.len() != codes_shape[0] {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "command_expiry must have length n",
            ));
        }
        let result = self
            .inner
            .step_with_mask(
                bar_index,
                command_codes.as_slice()?,
                command_values.as_slice()?,
                command_expiry.as_slice()?,
                codes_shape[0],
                self.inner.output_mask,
            )
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        full_step_payload(py, result)
    }

    /// Typed per-bar result for API 0.4 reactive callers. Scalar accounting is
    /// always present; projected vectors are `None` unless requested by the
    /// session output mask. The legacy dict-returning `step()` remains stable.
    fn step_typed(
        &mut self,
        py: Python<'_>,
        bar_index: usize,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<FullStepResultCore>> {
        let codes_shape = command_codes.shape();
        let values_shape = command_values.shape();
        if codes_shape.len() != 2 || codes_shape[1] != full::CODE_WIDTH {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full command_codes must have shape (n, 16)",
            ));
        }
        if values_shape.len() != 2
            || values_shape[0] != codes_shape[0]
            || values_shape[1] != full::VALUE_WIDTH
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full command_values must have shape (n, 3)",
            ));
        }
        if command_expiry.len() != codes_shape[0] {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "command_expiry must have length n",
            ));
        }
        let mask = self.inner.output_mask;
        let result = self
            .inner
            .step_with_mask(
                bar_index,
                command_codes.as_slice()?,
                command_values.as_slice()?,
                command_expiry.as_slice()?,
                codes_shape[0],
                mask,
            )
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let changed_positions = self
            .inner
            .positions
            .iter()
            .zip(self.last_positions.iter())
            .filter(|(current, previous)| (*current - *previous).abs() > 1e-15)
            .count() as u64;
        self.last_positions.clone_from(&self.inner.positions);
        self.total_fee += result.fee;
        self.total_turnover += result.turnover;
        self.total_funding += result.funding;
        self.total_rejected += result.rejected_count;
        self.total_canceled += result.canceled_count;
        let projected = FullStepResultCore::from_result(
            result,
            mask,
            self.total_fee,
            self.total_turnover,
            self.total_funding,
            self.total_rejected,
            self.total_canceled,
            self.fill_cursor,
            self.event_cursor,
            self.order_delta_cursor,
            self.position_delta_cursor,
            changed_positions,
        );
        self.fill_cursor = projected.fill_end;
        self.event_cursor = projected.event_end;
        self.order_delta_cursor = projected.order_delta_end;
        self.position_delta_cursor = projected.position_delta_end;
        Py::new(py, projected)
    }

    /// Set reactive projection requirements without changing the stable
    /// constructor ABI.  Unknown bits are rejected instead of silently
    /// falling back to a wider allocation profile.
    fn set_output_mask(&mut self, output_mask: u8) -> PyResult<()> {
        if output_mask & !full::OUTPUT_ALL != 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "full output mask contains unsupported bits",
            ));
        }
        self.inner.output_mask = output_mask;
        Ok(())
    }

    fn reset(&mut self) {
        self.inner.reset();
        self.total_fee = 0.0;
        self.total_turnover = 0.0;
        self.total_funding = 0.0;
        self.total_rejected = 0;
        self.total_canceled = 0;
        self.fill_cursor = 0;
        self.event_cursor = 0;
        self.order_delta_cursor = 0;
        self.position_delta_cursor = 0;
        self.last_positions.fill(0.0);
    }

    fn order_arena_counters(&self) -> (usize, usize, u64, u64) {
        (
            self.inner.orders_len(),
            self.inner.orders_capacity(),
            self.inner.compaction_count,
            self.inner.terminal_orders_removed,
        )
    }

    fn release_step_buffer_capacity(&mut self, max_capacity: usize) {
        self.inner.release_step_buffer_capacity(max_capacity);
    }

    fn step_buffer_capacities(&self) -> (usize, usize, usize) {
        self.inner.step_buffer_capacities()
    }

    fn margin_recompute_count(&self) -> u64 {
        self.inner.margin_recompute_count()
    }

    fn engine_scan_counters(&self) -> (u64, u64, u64) {
        self.inner.engine_scan_counters()
    }

    fn run_tape_score(
        &mut self,
        py: Python<'_>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let code_shape = command_codes.shape();
        let values = command_values.as_slice()?;
        let value_shape = command_values.shape();
        let expiry = command_expiry.as_slice()?;
        let output = py
            .detach(|| {
                run_full_tape(
                    &mut self.inner,
                    ptr,
                    codes,
                    code_shape,
                    values,
                    value_shape,
                    expiry,
                    false,
                )
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("final_equity", output.final_equity)?;
        payload.set_item("final_positions", output.final_positions)?;
        payload.set_item("total_fee", output.total_fee)?;
        payload.set_item("total_turnover", output.total_turnover)?;
        payload.set_item("total_funding", output.total_funding)?;
        payload.set_item("fill_count", output.fill_count)?;
        payload.set_item("event_count", output.event_count)?;
        payload.set_item("rejected_count", output.rejected_count)?;
        payload.set_item("canceled_count", output.canceled_count)?;
        payload.set_item("max_initial_margin", output.max_initial_margin)?;
        payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
        payload.set_item("liquidated", output.liquidated)?;
        payload.set_item("liquidation_bar", output.liquidation_bar)?;
        payload.set_item("liquidation_reason", output.liquidation_reason)?;
        payload.set_item("bars", self.inner.market.n_bars)?;
        Ok(payload.unbind())
    }

    fn run_tape_audit(
        &mut self,
        py: Python<'_>,
        command_ptr: PyReadonlyArray1<'_, i64>,
        command_codes: PyReadonlyArray2<'_, i64>,
        command_values: PyReadonlyArray2<'_, f64>,
        command_expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Py<PyDict>> {
        let ptr = command_ptr.as_slice()?;
        let codes = command_codes.as_slice()?;
        let code_shape = command_codes.shape();
        let values = command_values.as_slice()?;
        let value_shape = command_values.shape();
        let expiry = command_expiry.as_slice()?;
        let output = py
            .detach(|| {
                run_full_tape(
                    &mut self.inner,
                    ptr,
                    codes,
                    code_shape,
                    values,
                    value_shape,
                    expiry,
                    true,
                )
            })
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        let payload = PyDict::new(py);
        payload.set_item("equity", output.equity)?;
        payload.set_item("positions", output.positions)?;
        payload.set_item("fees", output.fees)?;
        payload.set_item("turnover", output.turnover)?;
        payload.set_item("funding", output.funding)?;
        payload.set_item("initial_margin", output.initial_margin)?;
        payload.set_item("maintenance_margin", output.maintenance_margin)?;
        payload.set_item("fill_bar", output.fill_bar)?;
        payload.set_item("fill_order_id", output.fill_order_id)?;
        payload.set_item("fill_symbol", output.fill_symbol)?;
        payload.set_item("fill_side", output.fill_side)?;
        payload.set_item("fill_qty", output.fill_qty)?;
        payload.set_item("fill_price", output.fill_price)?;
        payload.set_item("fill_fee", output.fill_fee)?;
        payload.set_item("fill_reason", output.fill_reason)?;
        payload.set_item("fill_ambiguity", output.fill_ambiguity)?;
        payload.set_item("event_bar", output.event_bar)?;
        payload.set_item("event_kind", output.event_kind)?;
        payload.set_item("event_status", output.event_status)?;
        payload.set_item("event_order_id", output.event_order_id)?;
        payload.set_item("event_target_id", output.event_target_id)?;
        payload.set_item("event_symbol", output.event_symbol)?;
        payload.set_item("event_reject_code", output.event_reject_code)?;
        payload.set_item("total_fee", output.total_fee)?;
        payload.set_item("total_turnover", output.total_turnover)?;
        payload.set_item("total_funding", output.total_funding)?;
        payload.set_item("fill_count", output.fill_count)?;
        payload.set_item("event_count", output.event_count)?;
        payload.set_item("rejected_count", output.rejected_count)?;
        payload.set_item("canceled_count", output.canceled_count)?;
        payload.set_item("max_initial_margin", output.max_initial_margin)?;
        payload.set_item("max_maintenance_margin", output.max_maintenance_margin)?;
        payload.set_item("liquidated", output.liquidated)?;
        payload.set_item("liquidation_bar", output.liquidation_bar)?;
        payload.set_item("liquidation_reason", output.liquidation_reason)?;
        payload.set_item("bars", self.inner.market.n_bars)?;
        Ok(payload.unbind())
    }
}

fn full_step_payload(py: Python<'_>, result: full::FullStepResult) -> PyResult<Py<PyDict>> {
    let payload = PyDict::new(py);
    payload.set_item("equity", result.equity)?;
    payload.set_item("positions", result.positions)?;
    payload.set_item("fee", result.fee)?;
    payload.set_item("turnover", result.turnover)?;
    payload.set_item("funding", result.funding)?;
    payload.set_item("initial_margin", result.initial_margin)?;
    payload.set_item("maintenance_margin", result.maintenance_margin)?;
    payload.set_item("liquidated", result.liquidated)?;
    payload.set_item("liquidation_bar", result.liquidation_bar)?;
    payload.set_item("liquidation_reason", result.liquidation_reason)?;
    payload.set_item("fills", result.fills)?;
    payload.set_item("events", result.events)?;
    payload.set_item("active_orders", result.active_orders)?;
    payload.set_item("rejected_count", result.rejected_count)?;
    payload.set_item("canceled_count", result.canceled_count)?;
    payload.set_item("fill_count", result.fill_count)?;
    payload.set_item("event_count", result.event_count)?;
    Ok(payload.unbind())
}

struct FullTapeOutput {
    equity: Vec<f64>,
    positions: Vec<Vec<f64>>,
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
    final_equity: f64,
    final_positions: Vec<f64>,
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
}

#[allow(clippy::too_many_arguments)]
fn run_full_tape(
    session: &mut FullSession,
    ptr: &[i64],
    codes: &[i64],
    codes_shape: &[usize],
    values: &[f64],
    values_shape: &[usize],
    expiry: &[i64],
    audit: bool,
) -> Result<FullTapeOutput, String> {
    if ptr.len() != session.market.n_bars + 1
        || codes_shape.len() != 2
        || codes_shape[1] != full::CODE_WIDTH
        || values_shape.len() != 2
        || values_shape[0] != codes_shape[0]
        || values_shape[1] != full::VALUE_WIDTH
        || expiry.len() != codes_shape[0]
    {
        return Err("invalid full tape shapes".to_owned());
    }
    let n_commands = codes_shape[0] as i64;
    if ptr.first().copied().unwrap_or(-1) != 0
        || ptr.last().copied().unwrap_or(-1) != n_commands
        || ptr
            .windows(2)
            .any(|pair| pair[1] < pair[0] || pair[1] > n_commands)
    {
        return Err("command_ptr must be monotonic and bounded".to_owned());
    }
    if codes.len() != codes_shape[0] * full::CODE_WIDTH
        || values.len() != values_shape[0] * full::VALUE_WIDTH
    {
        return Err("full command buffers are not contiguous".to_owned());
    }
    let n_bars = session.market.n_bars;
    let mut output = FullTapeOutput {
        equity: if audit {
            Vec::with_capacity(n_bars)
        } else {
            Vec::new()
        },
        positions: if audit {
            Vec::with_capacity(n_bars)
        } else {
            Vec::new()
        },
        fees: if audit {
            Vec::with_capacity(n_bars)
        } else {
            Vec::new()
        },
        turnover: if audit {
            Vec::with_capacity(n_bars)
        } else {
            Vec::new()
        },
        funding: if audit {
            Vec::with_capacity(n_bars)
        } else {
            Vec::new()
        },
        initial_margin: if audit {
            Vec::with_capacity(n_bars)
        } else {
            Vec::new()
        },
        maintenance_margin: if audit {
            Vec::with_capacity(n_bars)
        } else {
            Vec::new()
        },
        fill_bar: Vec::new(),
        fill_order_id: Vec::new(),
        fill_symbol: Vec::new(),
        fill_side: Vec::new(),
        fill_qty: Vec::new(),
        fill_price: Vec::new(),
        fill_fee: Vec::new(),
        fill_reason: Vec::new(),
        fill_ambiguity: Vec::new(),
        event_bar: Vec::new(),
        event_kind: Vec::new(),
        event_status: Vec::new(),
        event_order_id: Vec::new(),
        event_target_id: Vec::new(),
        event_symbol: Vec::new(),
        event_reject_code: Vec::new(),
        final_equity: session.equity,
        final_positions: session.positions.clone(),
        total_fee: 0.0,
        total_turnover: 0.0,
        total_funding: 0.0,
        fill_count: 0,
        event_count: 0,
        rejected_count: 0,
        canceled_count: 0,
        max_initial_margin: 0.0,
        max_maintenance_margin: 0.0,
        liquidated: false,
        liquidation_bar: -1,
        liquidation_reason: full::LIQ_NONE,
    };
    let mut step_buffers = full::StepBuffers::default();
    for bar in 0..n_bars {
        // Bar zero is the immutable initial-state snapshot in the Python
        // oracle. Explicit commands mapped to bar zero are outside the
        // executable tape and must not mutate Rust state either.
        let (start, end) = if bar == 0 {
            let after_bar_zero = ptr[1] as usize;
            (after_bar_zero, after_bar_zero)
        } else {
            (ptr[bar] as usize, ptr[bar + 1] as usize)
        };
        let step = session.step_with_buffers(
            bar,
            &codes[start * full::CODE_WIDTH..end * full::CODE_WIDTH],
            &values[start * full::VALUE_WIDTH..end * full::VALUE_WIDTH],
            &expiry[start..end],
            end - start,
            if audit {
                full::OUTPUT_POSITIONS | full::OUTPUT_FILLS | full::OUTPUT_EVENTS
            } else {
                0
            },
            false,
            &mut step_buffers,
        )?;
        if audit {
            output.equity.push(step.equity);
            output.positions.push(step.positions.clone());
            output.fees.push(step.fee);
            output.turnover.push(step.turnover);
            output.funding.push(step.funding);
            output.initial_margin.push(step.initial_margin);
            output.maintenance_margin.push(step.maintenance_margin);
        }
        output.final_equity = step.equity;
        output.final_positions = session.positions.clone();
        output.total_fee += step.fee;
        output.total_turnover += step.turnover;
        output.total_funding += step.funding;
        output.rejected_count += step.rejected_count;
        output.canceled_count += step.canceled_count;
        output.fill_count += step.fill_count;
        output.event_count += step.event_count;
        if audit {
            for n in 0..step_buffers.fills.order_id.len() {
                output.fill_bar.push(bar as i64);
                output.fill_order_id.push(step_buffers.fills.order_id[n]);
                output.fill_symbol.push(step_buffers.fills.symbol[n]);
                output.fill_side.push(step_buffers.fills.side[n]);
                output.fill_qty.push(step_buffers.fills.qty[n]);
                output.fill_price.push(step_buffers.fills.price[n]);
                output.fill_fee.push(step_buffers.fills.fee[n]);
                output.fill_reason.push(step_buffers.fills.reason[n]);
                output.fill_ambiguity.push(step_buffers.fills.ambiguity[n]);
            }
            for n in 0..step_buffers.events.kind.len() {
                output.event_bar.push(bar as i64);
                output.event_kind.push(step_buffers.events.kind[n]);
                output.event_status.push(step_buffers.events.status[n]);
                output.event_order_id.push(step_buffers.events.order_id[n]);
                output
                    .event_target_id
                    .push(step_buffers.events.target_id[n]);
                output.event_symbol.push(step_buffers.events.symbol[n]);
                output
                    .event_reject_code
                    .push(step_buffers.events.reject_code[n]);
            }
        }
        output.max_initial_margin = output.max_initial_margin.max(step.initial_margin);
        output.max_maintenance_margin = output.max_maintenance_margin.max(step.maintenance_margin);
        output.liquidated = step.liquidated;
        output.liquidation_bar = step.liquidation_bar;
        output.liquidation_reason = step.liquidation_reason;
    }
    Ok(output)
}

#[pymodule]
fn _quantbt_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", VERSION)?;
    module.add_function(wrap_pyfunction!(version, module)?)?;
    module.add_function(wrap_pyfunction!(api_version, module)?)?;
    module.add_function(wrap_pyfunction!(capabilities, module)?)?;
    module.add_function(wrap_pyfunction!(semantic_descriptor, module)?)?;
    module.add_function(wrap_pyfunction!(quantize_price_v1, module)?)?;
    module.add_function(wrap_pyfunction!(quantize_quantity_v1, module)?)?;
    module.add_function(wrap_pyfunction!(quantize_order_value_v1, module)?)?;
    module.add_function(wrap_pyfunction!(contract_registry_fingerprint, module)?)?;
    module.add_function(wrap_pyfunction!(event_contract_ids, module)?)?;
    module.add_class::<PreparedMarketCore>()?;
    module.add_class::<BatchedScoreResultCore>()?;
    module.add_class::<ReactiveSessionCore>()?;
    module.add_class::<FullStepResultCore>()?;
    module.add_class::<FullPreparedMarketCore>()?;
    module.add_class::<FullReactiveSessionCore>()?;
    Ok(())
}

#[cfg(test)]
mod phase51b_property_tests {
    use super::{integer_units, quantize_quantity_values};
    use proptest::prelude::*;

    proptest! {
        #[test]
        fn quantity_quantization_never_increases_requested_lots(
            raw_qty in 1u64..1_000_000u64,
            step_code in 1u64..10_000u64,
        ) {
            let qty = raw_qty as f64 / 1_000.0;
            let step = step_code as f64 / 1_000_000.0;
            let lots = integer_units(qty, step, false);
            let quantized = lots as f64 * step;
            prop_assert!(quantized <= qty + 1e-12);
            prop_assert!(quantized >= 0.0);
        }

        #[test]
        fn quantity_preflight_is_deterministic(
            raw_qty in 1u64..100_000u64,
            raw_price in 1u64..10_000_000u64,
        ) {
            let qty = raw_qty as f64 / 10_000.0;
            let price = raw_price as f64 / 100.0;
            let left = quantize_quantity_values(qty, price, 0.001, 0.001, 1_000.0, 5.0, 1.0);
            let right = quantize_quantity_values(qty, price, 0.001, 0.001, 1_000.0, 5.0, 1.0);
            prop_assert_eq!(left, right);
        }
    }
}

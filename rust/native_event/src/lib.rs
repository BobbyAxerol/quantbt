mod accounting;
mod matching;
mod session;
mod types;

use numpy::{PyArray1, PyReadonlyArray1, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyType};
use std::sync::Arc;

use session::{PreparedMarketData, ReactiveSession};

const VERSION: &str = "0.3.0";
const API_VERSION: &str = "0.3";

#[pyfunction]
fn version() -> &'static str {
    VERSION
}

#[pyfunction]
fn api_version() -> &'static str {
    API_VERSION
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
    Ok(values)
}

#[pyclass]
struct PreparedMarketCore {
    inner: Arc<PreparedMarketData>,
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
        let payload = PyDict::new(py);
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
        payload.set_item("bars", output.equity.len())?;
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
        let step = session.step(
            bar,
            &codes[start * types::COMMAND_CODE_WIDTH..end * types::COMMAND_CODE_WIDTH],
            &values[start * types::COMMAND_VALUE_WIDTH..end * types::COMMAND_VALUE_WIDTH],
            &expiry[start..end],
            end - start,
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
        fill_count += step.fills.len() as i64;
        event_count += step.events.len() as i64;
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
            if event[0] == types::EVENT_REJECT {
                rejected_count += 1;
            }
            if event[0] == types::EVENT_CANCEL {
                canceled_count += 1;
            }
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

#[pymodule]
fn _quantbt_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", VERSION)?;
    module.add_function(wrap_pyfunction!(version, module)?)?;
    module.add_function(wrap_pyfunction!(api_version, module)?)?;
    module.add_function(wrap_pyfunction!(capabilities, module)?)?;
    module.add_class::<PreparedMarketCore>()?;
    module.add_class::<ReactiveSessionCore>()?;
    Ok(())
}

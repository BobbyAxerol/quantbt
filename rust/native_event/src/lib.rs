mod accounting;
mod matching;
mod session;
mod types;

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyType};
use numpy::{PyReadonlyArray1, PyReadonlyArray2};
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
        Ok(Self { inner: Arc::new(market) })
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
        Self::from_arrays(timestamps_ns, opens, highs, lows, closes, volumes, funding, funding_mask)
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
            timestamps_ns, opens, highs, lows, closes, volumes, funding, funding_mask,
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
            return Err(pyo3::exceptions::PyValueError::new_err("command_codes must have shape (n, 8)"));
        }
        if values_shape.len() != 2 || values_shape[0] != codes_shape[0] || values_shape[1] != types::COMMAND_VALUE_WIDTH {
            return Err(pyo3::exceptions::PyValueError::new_err("command_values must have shape (n, 3)"));
        }
        if command_expiry.len() != codes_shape[0] {
            return Err(pyo3::exceptions::PyValueError::new_err("command_expiry must have length n"));
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

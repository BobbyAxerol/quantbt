use pyo3::prelude::*;
use pyo3::types::PyDict;

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
    values.set_item("reactive_session", false)?;
    Ok(values)
}

#[pymodule]
fn _quantbt_native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", VERSION)?;
    module.add_function(wrap_pyfunction!(version, module)?)?;
    module.add_function(wrap_pyfunction!(api_version, module)?)?;
    module.add_function(wrap_pyfunction!(capabilities, module)?)?;
    Ok(())
}

//! Private same-bar feedback binding over the canonical FullSession kernel.

use numpy::{PyReadonlyArray1, PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyType;
use quantbt_engine::{
    CODE_WIDTH, FullSession, FullStepResult, OUTPUT_EVENTS, OUTPUT_FILLS, StepBuffers, VALUE_WIDTH,
};

use crate::NativeExecutionTemplateCore;

#[pyclass(frozen, get_all, skip_from_py_object)]
#[derive(Debug, PartialEq)]
pub(crate) struct FeedbackStepCore {
    equity: f64,
    positions: Vec<f64>,
    fee: f64,
    turnover: f64,
    funding: f64,
    initial_margin: f64,
    maintenance_margin: f64,
    liquidated: bool,
    liquidation_bar: i64,
    liquidation_reason: i64,
    fill_order_id: Vec<i64>,
    fill_symbol: Vec<i64>,
    fill_side: Vec<i64>,
    fill_order_type: Vec<i64>,
    fill_reason: Vec<i64>,
    fill_ambiguity: Vec<i64>,
    fill_qty: Vec<f64>,
    fill_price: Vec<f64>,
    fill_fee: Vec<f64>,
    event_kind: Vec<i64>,
    event_status: Vec<i64>,
    event_order_id: Vec<i64>,
    event_target_id: Vec<i64>,
    event_symbol: Vec<i64>,
    event_reject_code: Vec<i64>,
}

impl FeedbackStepCore {
    fn from_buffers(result: FullStepResult, positions: Vec<f64>, buffers: &StepBuffers) -> Self {
        Self {
            equity: result.equity,
            positions,
            fee: result.fee,
            turnover: result.turnover,
            funding: result.funding,
            initial_margin: result.initial_margin,
            maintenance_margin: result.maintenance_margin,
            liquidated: result.liquidated,
            liquidation_bar: result.liquidation_bar,
            liquidation_reason: result.liquidation_reason,
            fill_order_id: buffers.fills.order_id.clone(),
            fill_symbol: buffers.fills.symbol.clone(),
            fill_side: buffers.fills.side.clone(),
            fill_order_type: buffers.fills.order_type.clone(),
            fill_reason: buffers.fills.reason.clone(),
            fill_ambiguity: buffers.fills.ambiguity.clone(),
            fill_qty: buffers.fills.qty.clone(),
            fill_price: buffers.fills.price.clone(),
            fill_fee: buffers.fills.fee.clone(),
            event_kind: buffers.events.kind.clone(),
            event_status: buffers.events.status.clone(),
            event_order_id: buffers.events.order_id.clone(),
            event_target_id: buffers.events.target_id.clone(),
            event_symbol: buffers.events.symbol.clone(),
            event_reject_code: buffers.events.reject_code.clone(),
        }
    }
}

#[pyclass]
pub(crate) struct NativeFeedbackSessionCore {
    session: Option<FullSession>,
    buffers: StepBuffers,
}

impl NativeFeedbackSessionCore {
    fn wrap(session: FullSession) -> Self {
        Self {
            session: Some(session),
            buffers: StepBuffers::default(),
        }
    }

    fn open_mut(&mut self) -> PyResult<&mut FullSession> {
        self.session
            .as_mut()
            .ok_or_else(|| PyRuntimeError::new_err("feedback session is closed"))
    }

    fn execute_step(
        &mut self,
        codes: &[i64],
        values: &[f64],
        expiry: &[i64],
    ) -> Result<FeedbackStepCore, String> {
        if expiry.len().checked_mul(CODE_WIDTH) != Some(codes.len())
            || expiry.len().checked_mul(VALUE_WIDTH) != Some(values.len())
        {
            return Err("feedback command buffers do not match command count".to_owned());
        }
        let session = self
            .session
            .as_mut()
            .ok_or_else(|| "feedback session is closed".to_owned())?;
        let bar = session
            .active_bar_transaction()
            .ok_or_else(|| "begin a bar transaction before step".to_owned())?;
        if session.next_bar() != bar {
            session.retry_bar_transaction()?;
        }
        self.buffers.clear();
        // P0 is the initial account snapshot, just as in the static tape runner.
        let (codes, values, expiry) = if bar == 0 {
            (&[][..], &[][..], &[][..])
        } else {
            (codes, values, expiry)
        };
        let result = session.step_with_buffers(
            bar,
            codes,
            values,
            expiry,
            expiry.len(),
            OUTPUT_FILLS | OUTPUT_EVENTS,
            false,
            &mut self.buffers,
        );
        match result {
            Ok(result) => Ok(FeedbackStepCore::from_buffers(
                result,
                session.positions.clone(),
                &self.buffers,
            )),
            Err(error) => {
                session.retry_bar_transaction()?;
                self.buffers.clear();
                Err(error)
            }
        }
    }
}

#[pymethods]
impl NativeFeedbackSessionCore {
    #[classmethod]
    fn from_template(
        _cls: &Bound<'_, PyType>,
        template: PyRef<'_, NativeExecutionTemplateCore>,
    ) -> PyResult<Self> {
        template
            .inner
            .fresh_session()
            .map(Self::wrap)
            .map_err(PyValueError::new_err)
    }

    fn begin(&mut self, bar: usize) -> PyResult<()> {
        self.open_mut()?
            .begin_bar_transaction(bar)
            .map_err(PyValueError::new_err)?;
        self.buffers.clear();
        Ok(())
    }

    fn step(
        &mut self,
        codes: PyReadonlyArray2<'_, i64>,
        values: PyReadonlyArray2<'_, f64>,
        expiry: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<FeedbackStepCore> {
        self.open_mut()?;
        let code_shape = codes.shape();
        let value_shape = values.shape();
        if code_shape[1] != CODE_WIDTH
            || value_shape[1] != VALUE_WIDTH
            || value_shape[0] != code_shape[0]
            || expiry.len() != code_shape[0]
        {
            return Err(PyValueError::new_err(
                "feedback commands require codes (n, 16), values (n, 3), expiry (n,)",
            ));
        }
        self.execute_step(codes.as_slice()?, values.as_slice()?, expiry.as_slice()?)
            .map_err(PyValueError::new_err)
    }

    fn commit(&mut self) -> PyResult<()> {
        self.open_mut()?
            .commit_bar_transaction()
            .map_err(PyValueError::new_err)?;
        self.buffers.clear();
        Ok(())
    }

    fn abort(&mut self) -> PyResult<()> {
        self.open_mut()?
            .abort_bar_transaction()
            .map_err(PyValueError::new_err)?;
        self.buffers.clear();
        Ok(())
    }

    fn reset(&mut self) -> PyResult<()> {
        self.open_mut()?.reset();
        self.buffers.clear();
        Ok(())
    }

    fn close(&mut self) {
        self.session = None;
        self.buffers = StepBuffers::default();
    }

    #[getter]
    fn next_bar(&self) -> PyResult<usize> {
        self.session
            .as_ref()
            .map(FullSession::next_bar)
            .ok_or_else(|| PyRuntimeError::new_err("feedback session is closed"))
    }
}

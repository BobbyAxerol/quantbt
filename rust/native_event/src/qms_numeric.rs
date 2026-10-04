//! QMS numeric ABI v1: owned float64 batches, deterministic serial reduction.
use numpy::{PyArray1, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

fn error(message: &str) -> PyErr {
    PyValueError::new_err(message.to_owned())
}

fn fit(
    v: &[f64],
    y: &[f64],
    w: &[f64],
    d: usize,
    lambda: f64,
) -> Result<(Vec<f64>, Vec<f64>, Vec<f64>), String> {
    if d == 0
        || y.is_empty()
        || y.len().checked_mul(d) != Some(v.len())
        || w.len() != y.len()
        || !lambda.is_finite()
        || lambda <= 0.0
        || !v.iter().chain(y).chain(w).all(|x| x.is_finite())
        || w.iter().any(|x| *x <= 0.0)
    {
        return Err("META_NUMERIC_INPUT_INVALID".into());
    }
    let work = d
        .checked_mul(d)
        .and_then(|size| size.checked_mul(48))
        .and_then(|size| size.checked_add(v.len().saturating_mul(24)))
        .ok_or("META_RESOURCE_LIMIT")?;
    if work > 256_000_000 {
        return Err("META_RESOURCE_LIMIT".into());
    }
    let mut g = vec![0.0; d * d];
    let mut b = vec![0.0; d];
    for (i, row) in v.chunks_exact(d).enumerate() {
        for j in 0..d {
            b[j] += w[i] * row[j] * y[i];
            for k in 0..=j {
                g[j * d + k] += w[i] * row[j] * row[k];
            }
        }
    }
    for j in 0..d {
        g[j * d + j] += lambda;
        for k in 0..j {
            g[k * d + j] = g[j * d + k];
        }
    }
    // Cholesky without inverse/jitter. The host independently checks conditioning/residual.
    let mut l = vec![0.0; d * d];
    for j in 0..d {
        for k in 0..=j {
            let mut sum = g[j * d + k];
            for m in 0..k {
                sum -= l[j * d + m] * l[k * d + m];
            }
            if j == k {
                if !sum.is_finite() || sum <= 0.0 {
                    return Err("META_SOLVE_NOT_SPD_NO_JITTER".into());
                }
                l[j * d + k] = sum.sqrt();
            } else {
                l[j * d + k] = sum / l[k * d + k];
            }
        }
    }
    let mut z = vec![0.0; d];
    for j in 0..d {
        let mut sum = b[j];
        for k in 0..j {
            sum -= l[j * d + k] * z[k];
        }
        z[j] = sum / l[j * d + j];
    }
    let mut beta = vec![0.0; d];
    for j in (0..d).rev() {
        let mut sum = z[j];
        for k in j + 1..d {
            sum -= l[k * d + j] * beta[k];
        }
        beta[j] = sum / l[j * d + j];
    }
    if !g.iter().chain(&b).chain(&beta).all(|x| x.is_finite()) {
        return Err("META_SOLVE_NONFINITE".into());
    }
    Ok((g, b, beta))
}

#[pyfunction]
pub fn qms_numeric_descriptor_v1(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let output = PyDict::new(py);
    output.set_item("abi", "qms-numeric-v1")?;
    output.set_item("dtype", "float64")?;
    output.set_item("fast_math", false)?;
    output.set_item("owned_inputs", true)?;
    output.set_item("blocks", ["transform", "gram_solve", "rank"])?;
    Ok(output)
}

#[pyfunction]
pub fn qms_fit_v1<'py>(
    py: Python<'py>,
    v: PyReadonlyArray2<'py, f64>,
    y: PyReadonlyArray1<'py, f64>,
    weights: PyReadonlyArray1<'py, f64>,
    lambda_reg: f64,
) -> PyResult<(
    Bound<'py, PyArray1<f64>>,
    Bound<'py, PyArray1<f64>>,
    Bound<'py, PyArray1<f64>>,
)> {
    let shape = v.as_array().shape().to_vec();
    let rows = v.as_slice()?.to_vec();
    let y = y.as_slice()?.to_vec();
    let weights = weights.as_slice()?.to_vec();
    let (g, b, beta) = py
        .detach(move || fit(&rows, &y, &weights, shape[1], lambda_reg))
        .map_err(|e| error(&e))?;
    Ok((
        PyArray1::from_vec(py, g),
        PyArray1::from_vec(py, b),
        PyArray1::from_vec(py, beta),
    ))
}

#[pyfunction]
pub fn qms_rank_v1<'py>(
    py: Python<'py>,
    v: PyReadonlyArray2<'py, f64>,
    beta: PyReadonlyArray1<'py, f64>,
    delta_is: PyReadonlyArray1<'py, f64>,
) -> PyResult<(Bound<'py, PyArray1<f64>>, Bound<'py, PyArray1<f64>>)> {
    let shape = v.as_array().shape().to_vec();
    let rows = v.as_slice()?.to_vec();
    let beta = beta.as_slice()?.to_vec();
    let delta = delta_is.as_slice()?.to_vec();
    if shape[1] == 0
        || shape[1] != beta.len()
        || shape[0] != delta.len()
        || !rows
            .iter()
            .chain(&beta)
            .chain(&delta)
            .all(|x| x.is_finite())
    {
        return Err(error("META_RANK_INPUT_INVALID"));
    }
    let (y, q) = py.detach(move || {
        let y: Vec<f64> = rows
            .chunks_exact(beta.len())
            .map(|row| row.iter().zip(&beta).map(|(a, b)| a * b).sum())
            .collect();
        let q: Vec<f64> = delta.iter().zip(&y).map(|(a, b)| a - b).collect();
        (y, q)
    });
    if !y.iter().chain(&q).all(|x| x.is_finite()) {
        return Err(error("META_RANK_NONFINITE"));
    }
    Ok((PyArray1::from_vec(py, y), PyArray1::from_vec(py, q)))
}

#[pyfunction]
#[allow(clippy::too_many_arguments)]
pub fn qms_transform_v1<'py>(
    py: Python<'py>,
    values: PyReadonlyArray2<'py, f64>,
    active: PyReadonlyArray2<'py, u8>,
    valid: PyReadonlyArray1<'py, u8>,
    numeric: PyReadonlyArray1<'py, u8>,
    mean: PyReadonlyArray1<'py, f64>,
    scale: PyReadonlyArray1<'py, f64>,
    constant: PyReadonlyArray1<'py, u8>,
    observed: PyReadonlyArray1<'py, u8>,
    tolerance: f64,
) -> PyResult<(Bound<'py, PyArray1<f64>>, Bound<'py, PyArray1<u8>>)> {
    let shape = values.as_array().shape().to_vec();
    if active.as_array().shape() != shape {
        return Err(error("META_DESCRIPTOR_SHAPE"));
    }
    let mut x = values.as_slice()?.to_vec();
    let active = active.as_slice()?.to_vec();
    let valid = valid.as_slice()?.to_vec();
    let numeric = numeric.as_slice()?.to_vec();
    let mean = mean.as_slice()?.to_vec();
    let scale = scale.as_slice()?.to_vec();
    let constant = constant.as_slice()?.to_vec();
    let observed = observed.as_slice()?.to_vec();
    let d = shape[1];
    if d == 0
        || valid.len() != shape[0]
        || [
            numeric.len(),
            mean.len(),
            scale.len(),
            constant.len(),
            observed.len(),
        ]
        .iter()
        .any(|n| *n != d)
        || !mean.iter().chain(&scale).all(|x| x.is_finite())
        || scale.iter().any(|x| *x <= 0.)
        || !tolerance.is_finite()
        || tolerance < 0.
        || active
            .iter()
            .chain(&valid)
            .chain(&numeric)
            .chain(&constant)
            .chain(&observed)
            .any(|x| *x > 1)
        || x.chunks_exact(d)
            .zip(&valid)
            .any(|(row, flag)| *flag == 1 && !row.iter().all(|x| x.is_finite()))
    {
        return Err(error("META_TRANSFORM_INPUT_INVALID"));
    }
    let (x, unsupported) = py.detach(move || {
        let mut unsupported: Vec<u8> = valid.iter().map(|v| 1 - v).collect();
        for (i, row) in x.chunks_exact_mut(d).enumerate() {
            for j in 0..d {
                if numeric[j] == 0 {
                    continue;
                }
                if active[i * d + j] == 0 {
                    row[j] = 0.;
                } else if valid[i] == 1 {
                    if constant[j] == 1 {
                        if observed[j] == 0 || (row[j] - mean[j]).abs() > tolerance {
                            unsupported[i] = 1;
                        }
                        row[j] = 0.;
                    } else {
                        row[j] = (row[j] - mean[j]) / scale[j];
                    }
                }
            }
        }
        (x, unsupported)
    });
    Ok((
        PyArray1::from_vec(py, x),
        PyArray1::from_vec(py, unsupported),
    ))
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(qms_numeric_descriptor_v1, module)?)?;
    module.add_function(wrap_pyfunction!(qms_fit_v1, module)?)?;
    module.add_function(wrap_pyfunction!(qms_rank_v1, module)?)?;
    module.add_function(wrap_pyfunction!(qms_transform_v1, module)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn independent_one_dimension_and_zero_labels() {
        let (g, b, beta) = fit(&[1., 2.], &[3., 4.], &[0.5, 0.5], 1, 10.).unwrap();
        assert_eq!(g, vec![12.5]);
        assert_eq!(b, vec![5.5]);
        assert_eq!(beta, vec![0.44]);
        assert_eq!(
            fit(&[1., 2.], &[0., 0.], &[0.5, 0.5], 1, 10.).unwrap().2,
            vec![0.]
        );
    }
    #[test]
    fn strict_invalid_inputs_and_overflow() {
        for (v, w, l) in [
            (vec![f64::NAN], vec![1.], 10.),
            (vec![1.], vec![0.], 10.),
            (vec![1.], vec![1.], 0.),
            (vec![1e300], vec![1.], 10.),
        ] {
            assert!(fit(&v, &[1.], &w, 1, l).is_err());
        }
    }
}

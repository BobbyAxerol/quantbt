"""Independent Decimal moments and raw-moment-gradient HAC matrix oracle."""

from decimal import Decimal, localcontext
import math

import numpy as np


def central_reference(values, ddof=1):
    with localcontext() as context:
        context.prec = 60
        data = [Decimal(str(value)) for value in values]
        n = Decimal(len(data))
        mean = sum(data)/n
        sums = [sum((x-mean)**power for x in data) for power in (2, 3, 4)]
        v = sums[0]/n
        sample = sums[0]/(n-ddof)
        return tuple(float(x) for x in (mean, sample, mean/sample.sqrt(),
            sums[1]/n/v/v.sqrt(), sums[2]/n/v**2))


def hac_matrix_reference(values, bandwidth):
    x = np.asarray(values, dtype=float)
    n = len(x)
    mean, second = float(x.mean()), float(np.mean(x*x))
    variance = second-mean*mean
    # Delta method on the raw moments (E[X], E[X^2]), not the production IF.
    gradient = np.array([second/variance**1.5, -mean/(2*variance**1.5)])
    raw = np.column_stack((x-mean, x*x-second))
    influence = raw @ gradient
    influence -= influence.mean()
    distances = np.abs(np.arange(n)[:, None]-np.arange(n)[None, :])
    weights = np.maximum(1-distances/(bandwidth+1), 0)
    long_run = float(influence @ weights @ influence/n)
    return mean/math.sqrt(variance), math.sqrt(long_run/n), long_run

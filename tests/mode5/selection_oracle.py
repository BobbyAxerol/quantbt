"""Independent scalar math reference; no imports from candidate implementations."""
import math


def weighted_tail(values, weights, alpha):
    total_weight = math.fsum(weights)
    left, total = alpha, 0.0
    for value, weight in sorted(zip(values, weights, strict=True)):
        take = min(left, weight / total_weight)
        total += take * value
        left -= take
        if left <= 0:
            break
    return total / alpha


def median(values, weights):
    left = math.fsum(weights) / 2
    for value, weight in sorted(zip(values, weights, strict=True)):
        left -= weight
        if left <= 0:
            return value
    return max(values)


def components(values, weights, benchmark):
    mean = math.fsum(x*w for x, w in zip(values, weights, strict=True)) / math.fsum(weights)
    mid = median(values, weights)
    return dict(floor=min(values), mean=mean,
        sd=math.sqrt(math.fsum(w*(x-mean)**2 for x, w in zip(values, weights, strict=True))/math.fsum(weights)),
        mad=median([abs(x-mid) for x in values], weights),
        mean_regret=math.fsum(w*(b-x) for b, x, w in zip(benchmark, values, weights, strict=True))/math.fsum(weights),
        max_regret=max(b-x for b, x in zip(benchmark, values, strict=True)))


def nondominated(rows, directions):
    out = []
    for i, row in enumerate(rows):
        dominated = False
        for j, other in enumerate(rows):
            if i == j:
                continue
            differences = [(b-a) * d for a, b, d in zip(row, other, directions, strict=True)]
            if all(x >= 0 for x in differences) and any(x > 0 for x in differences):
                dominated = True
        if not dominated:
            out.append(i)
    return out


def chebyshev(row, ideal, worst, directions, weights, rho):
    normalized = [0 if b == a else d*(a-x)/abs(a-b)
                  for x, a, b, d in zip(row, ideal, worst, directions, strict=True)]
    gaps = [w*a for w, a in zip(weights, normalized, strict=True)]
    return max(gaps) + rho*sum(gaps)

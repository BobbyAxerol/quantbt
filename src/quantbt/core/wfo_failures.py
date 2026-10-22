"""Explicit candidate failures; unknown strategy exceptions remain fatal."""

from datetime import datetime
from math import isfinite
from numbers import Real


class NonPositiveExecutionPrice(ValueError):
    """A strategy adapter explicitly identified a finite non-positive price.

    This does not repair or execute an invalid order. Only an opted-in IS
    optimizer can prune it; forward realization and other exceptions retain
    their existing failure handling. NaN/inf are deliberately not this signal.
    """

    reason = "NON_POSITIVE_EXECUTION_PRICE"

    def __init__(self, price, *, field, order_type, timestamp):
        kind = str(getattr(order_type, "value", order_type)).lower()
        if (isinstance(price, bool) or not isinstance(price, Real)
                or not isfinite(price) or price > 0
                or field not in {"price", "trigger_price"}
                or kind not in {"limit", "stop_market", "stop_limit", "amend"}
                or not isinstance(timestamp, datetime) or timestamp.utcoffset() is None):
            raise ValueError("explicit finite non-positive execution price and aware timestamp required")
        self.price, self.field, self.order_type = float(price), field, kind
        self.timestamp = timestamp
        super().__init__(f"{self.reason}: {kind}.{field}={price} at {timestamp.isoformat()}")

    def metadata(self):
        return dict(schema="quantbt-invalid-execution-intent-v1", reason=self.reason,
            price=self.price, field=self.field, order_type=self.order_type,
            timestamp=self.timestamp.isoformat())


def nonpositive_price_cause(error):
    """Follow explicit cause wrappers only, never message-match a ValueError."""
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, NonPositiveExecutionPrice):
            return error
        seen.add(id(error))
        error = error.__cause__
    return None

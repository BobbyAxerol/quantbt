"""Object-owned derived values; never part of a portable record or its digest."""

from functools import wraps
from types import MappingProxyType


class ImmutableMemo:
    # A fixed set of decorated properties lives only as long as its immutable
    # owner. replace()/deserialization constructs a new owner with empty slots.
    __slots__ = ("_derived",)


def derived_property(function):
    name = function.__name__

    @wraps(function)
    def get(owner):
        values = getattr(owner, "_derived", {})
        if name in values:
            return values[name]
        value = function(owner)
        object.__setattr__(
            owner,
            "_derived",
            MappingProxyType(
                {
                    **getattr(owner, "_derived", {}),
                    name: value,
                }
            ),
        )
        return value

    return property(get)

"""Object-owned derived values; never part of a portable record or its digest."""

from functools import wraps


class ImmutableMemo:
    # A fixed set of decorated properties lives only as long as its immutable
    # owner. replace()/deserialization constructs a new owner with empty slots.
    __slots__ = ("_derived",)


def derived_property(function):
    name = function.__name__

    @wraps(function)
    def get(owner):
        try:
            values = owner._derived
        except AttributeError:
            values = {}
            object.__setattr__(owner, "_derived", values)
        if name not in values:
            values[name] = function(owner)
        return values[name]

    return property(get)

"""Helpers."""

from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from datetime import datetime, time
import logging

import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)


def convert_datetime[T: MutableMapping[str, object]](
    items: list[T] | None,
) -> list[T] | None:
    """Convert the 'start'/'end' strings of each item to datetimes, in place."""
    if items is None:
        return None

    def apply(item: T) -> T:
        start = item.get("start")
        end = item.get("end")
        if isinstance(start, str):
            item["start"] = from_str_to_datetime(start)
        if isinstance(end, str):
            item["end"] = from_str_to_datetime(end)
        return item

    return [apply(item) for item in items]


def from_str_to_time(value: str | time | None) -> time | None:
    """Convert time str to time."""
    if value is None:
        return None

    parsed = dt_util.parse_time(value) if isinstance(value, str) else value
    if parsed is None:
        return None

    return datetime.combine(datetime.today(), parsed).timetz()


def from_str_to_datetime(value: object) -> datetime | None:
    """Convert a str (or an existing datetime) to a datetime."""
    if isinstance(value, str):
        return dt_util.parse_datetime(value)
    if isinstance(value, datetime):
        return value
    return None


def as_float(value: object) -> float:
    """Return a numeric value (or numeric string) from untyped data as float."""
    if isinstance(value, bool):
        raise ValueError(f"Expected a number, got {value!r}")
    if isinstance(value, (int, float, str)):
        return float(value)
    raise ValueError(f"Expected a number, got {value!r}")


def time_in_between(now: time, start: time, end: time) -> bool:
    """Check if time is in between two values."""
    if start <= end:
        return start <= now < end
    # over midnight e.g., 23:30-04:15
    return start <= now or now < end


def merge_two_dicts[K, V](x: Mapping[K, V], y: Mapping[K, V]) -> dict[K, V]:
    """Merge two dictionaries."""
    return {**x, **y}


def get_first[T](iterable: Iterable[T] | None, default: T | None = None) -> T | None:
    """Get first item of array."""
    if iterable:
        for item in iterable:
            return item
    return default


def get_last[T](iterable: Sequence[T] | None) -> T | None:
    """Get last item of array."""
    if not iterable:
        return None
    return iterable[-1]

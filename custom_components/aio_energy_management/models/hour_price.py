"""Defines a cheapest hours model."""

from collections.abc import Mapping
import datetime
from typing import Self

from ..enums import HourPriceType  # noqa: TID252
from ..helpers import as_float, from_str_to_datetime  # noqa: TID252


def _required_datetime(value: object) -> datetime.datetime:
    """Parse a timestamp that must be present in the price data."""
    parsed = from_str_to_datetime(value)
    if parsed is None:
        raise ValueError(f"Invalid or missing timestamp in price data: {value!r}")
    return parsed


class HourPrice:
    """Cheapest hour model."""

    start: datetime.datetime
    end: datetime.datetime
    value: float
    type: HourPriceType

    def __init__(
        self,
        value: float,
        start: datetime.datetime,
        end: datetime.datetime | None = None,
        type: HourPriceType = HourPriceType.NORDPOOL,  # noqa: A002
    ) -> None:
        """Initialize HourPrice with value, start time, end time, type, and length.

        Args:
            value (float): The price value.
            start (datetime): The start time of the price item.
            end (datetime): The end time of the price item. If None, it will be set to start + 1 hour.
            type (HourPriceType): The type of the hour price (default: NORDPOOL).

        """
        self.start = start
        self.end = end if end is not None else start + datetime.timedelta(hours=1)
        self.value = value
        self.type = type

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, object],
        mtu: int,
        type: HourPriceType = HourPriceType.NORDPOOL,  # noqa: A002
    ) -> Self:
        """Init Hour Price model with selected type. Single item."""
        # Entsoe
        if type is HourPriceType.ENTSOE:
            start = _required_datetime(data["time"])
            return cls(
                as_float(data["price"]),
                start,
                start + datetime.timedelta(minutes=mtu),
                type,
            )
        # Nord pool official and Strømligning
        if type in (HourPriceType.NORDPOOL_OFFICIAL, HourPriceType.STROMLIGNING):
            return cls(
                as_float(data["price"]),
                _required_datetime(data["start"]),
                _required_datetime(data["end"]),
                type,
            )
        # Nord pool custom (HACS)
        return cls(
            as_float(data["value"]),
            _required_datetime(data["start"]),
            _required_datetime(data["end"]),
            type,
        )

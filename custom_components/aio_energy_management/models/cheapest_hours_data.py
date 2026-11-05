"""Typed shapes of the data a cheapest hours sensor keeps in the coordinator.

The data is persisted as JSON. The coordinator converts the stored datetime
strings back to datetime objects when loading, so at runtime the fields below
hold the types declared here.

The field ``list`` shadows the builtin inside a class body, so every field type
is written through a module-level alias instead of ``list[...]``.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TypedDict


class TimeSlot(TypedDict):
    """A selected period in which the sensor is on."""

    start: datetime
    end: datetime


class PricedSlot(TypedDict):
    """A price slot inside the calculation window."""

    start: datetime
    end: datetime
    price: float


class PriceExtra(TypedDict):
    """Price statistics of the selected slots."""

    mean_price: float | None
    max_price: float | None
    min_price: float | None


class CalculationResult(TypedDict):
    """Result of a cheapest hours calculation."""

    list: TimeSlots
    extra: PriceExtra


class Failsafe(TypedDict):
    """Failsafe period; times are strings after a reload from storage."""

    start: time | str
    end: time | str


type TimeSlots = list[TimeSlot]


class NextData(TypedDict, total=False):
    """Calculation that becomes active when the current one expires."""

    list: TimeSlots
    expiration: datetime | None
    extra: PriceExtra


class CheapestHoursData(TypedDict, total=False):
    """Everything a cheapest hours sensor stores in the coordinator."""

    # Current calculation
    list: TimeSlots
    expiration: datetime | None
    extra: PriceExtra
    updated_at: datetime
    next: NextData
    today_only: bool
    fetch_date: date | None
    failsafe: Failsafe | None

    # Values resolved from configuration or helper entities
    active_number_of_slots: int | None
    active_trigger_hour: int | None
    active_price_limit: float | None
    active_max_number_of_slots: int | None
    active_flexible_price_limit: float | None
    active_max_price_delta: float | None
    active_min_seq_slots: int | None
    active_number_of_blocks: int | None

    # Bookkeeping added by the coordinator
    name: str | None
    type: str
    calendar: bool
    archived: TimeSlots

    # 'extra' flattened into the state attributes
    mean_price: float | None
    max_price: float | None
    min_price: float | None

    # Deprecated since 0.3.3, only removed when found
    list_next: object

"""Tests for offset overlap scenarios in the cheapest hours binary sensor.

These exercise _add_offset and _set_next of the real sensor.
"""

from datetime import datetime, timedelta
import logging
from unittest.mock import MagicMock

import pytest

from homeassistant.core import HomeAssistant

from custom_components.aio_energy_management.cheapest_hours import (
    CheapestHoursBinarySensor,
)
from custom_components.aio_energy_management.cheapest_hours.binary_sensor import (
    OffsetConfig,
)
from custom_components.aio_energy_management.coordinator import (
    EnergyManagementCoordinator,
)
from custom_components.aio_energy_management.models.cheapest_hours_data import (
    PriceExtra,
    TimeSlot,
)

NO_EXTRA: PriceExtra = {"mean_price": None, "max_price": None, "min_price": None}


def _make_sensor(
    hass: HomeAssistant, sequential: bool, offset: OffsetConfig
) -> CheapestHoursBinarySensor:
    coordinator = MagicMock(spec=EnergyManagementCoordinator)
    coordinator.get_data.return_value = {"list": []}
    return CheapestHoursBinarySensor(
        hass=hass,
        unique_id="test_sensor",
        name="Test Sensor",
        first_hour=0,
        last_hour=23,
        starting_today=False,
        sequential=sequential,
        number_of_slots=1,
        offset=offset,
        coordinator=coordinator,
    )


def _slot(start: datetime, end: datetime) -> list[TimeSlot]:
    return [{"start": start, "end": end}]


async def test_end_offset_extends_beyond_expiration(hass: HomeAssistant) -> None:
    """End offset extends the expiration when it exceeds the original one."""
    sensor = _make_sensor(hass, True, {"end": {"hours": 1}})
    expiration = datetime(2024, 7, 15, 0, 0)

    result, new_expiration = sensor._add_offset(
        _slot(datetime(2024, 7, 14, 23, 0), datetime(2024, 7, 15, 0, 0)), expiration
    )

    assert result[0]["end"] == datetime(2024, 7, 15, 1, 0)
    assert new_expiration == datetime(2024, 7, 15, 1, 0)


async def test_start_offset_pulls_back_start_time(hass: HomeAssistant) -> None:
    """A negative start offset pulls the start time back."""
    sensor = _make_sensor(hass, True, {"start": {"minutes": -30}})
    expiration = datetime(2024, 7, 15, 1, 0)

    result, new_expiration = sensor._add_offset(
        _slot(datetime(2024, 7, 15, 0, 0), datetime(2024, 7, 15, 1, 0)), expiration
    )

    assert result[0]["start"] == datetime(2024, 7, 14, 23, 30)
    assert new_expiration == expiration


async def test_add_offset_does_not_modify_input(hass: HomeAssistant) -> None:
    """The caller's list is left untouched."""
    sensor = _make_sensor(hass, True, {"start": {"minutes": -30}, "end": {"hours": 1}})
    original = _slot(datetime(2024, 7, 15, 0, 0), datetime(2024, 7, 15, 1, 0))

    sensor._add_offset(original, datetime(2024, 7, 16, 0, 0))

    assert original == _slot(datetime(2024, 7, 15, 0, 0), datetime(2024, 7, 15, 1, 0))


async def test_overlap_scenario_current_end_offset_next_start_offset(
    hass: HomeAssistant,
) -> None:
    """The current slot's end offset overlaps the next slot's start offset.

    - Current slot: 23:00-00:00 with end offset +1h -> ends at 01:00
    - Next slot: 00:00-01:00 with start offset -30min -> starts at 23:30
    """
    sensor = _make_sensor(hass, True, {"start": {"minutes": -30}, "end": {"hours": 1}})

    current, current_expiration = sensor._add_offset(
        _slot(datetime(2024, 7, 14, 23, 0), datetime(2024, 7, 15, 0, 0)),
        datetime(2024, 7, 15, 0, 0),
    )
    assert current[0]["start"] == datetime(2024, 7, 14, 22, 30)
    assert current[0]["end"] == datetime(2024, 7, 15, 1, 0)
    assert current_expiration == datetime(2024, 7, 15, 1, 0)

    nxt, _ = sensor._add_offset(
        _slot(datetime(2024, 7, 15, 0, 0), datetime(2024, 7, 15, 1, 0)),
        datetime(2024, 7, 16, 0, 0),
    )
    assert nxt[0]["start"] == datetime(2024, 7, 14, 23, 30)
    assert nxt[0]["end"] == datetime(2024, 7, 15, 2, 0)

    # The next slot starts (23:30) 1.5 hours before the current one ends (01:00).
    assert current[0]["end"] - nxt[0]["start"] == timedelta(hours=1, minutes=30)


async def test_non_sequential_ignores_offset(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Non-sequential sensors ignore the offset and log why."""
    sensor = _make_sensor(hass, False, {"start": {"minutes": -30}, "end": {"hours": 1}})
    slots = _slot(datetime(2024, 7, 15, 0, 0), datetime(2024, 7, 15, 1, 0))
    expiration = datetime(2024, 7, 15, 1, 0)

    result, new_expiration = sensor._add_offset(slots, expiration)

    assert result == slots
    assert new_expiration == expiration
    assert "offsets are only supported for sequential sensors" in caplog.text


async def test_offset_resulting_in_invalid_duration_is_ignored(
    hass: HomeAssistant,
) -> None:
    """An offset that makes a slot end before it starts is not applied."""
    sensor = _make_sensor(hass, True, {"start": {"hours": 2}})
    slots = _slot(datetime(2024, 7, 15, 0, 0), datetime(2024, 7, 15, 1, 0))
    expiration = datetime(2024, 7, 16, 0, 0)

    assert sensor._add_offset(slots, expiration) == (slots, expiration)


async def test_large_end_offset_creates_significant_overlap(
    hass: HomeAssistant,
) -> None:
    """A large end offset pushes both the end and the expiration out."""
    sensor = _make_sensor(hass, True, {"end": {"hours": 3}})

    result, new_expiration = sensor._add_offset(
        _slot(datetime(2024, 7, 14, 22, 0), datetime(2024, 7, 14, 23, 0)),
        datetime(2024, 7, 15, 0, 0),
    )

    assert result[0]["end"] == datetime(2024, 7, 15, 2, 0)
    assert new_expiration == datetime(2024, 7, 15, 3, 0)  # expiration + 3h offset


async def test_overlap_warning_logged_when_set_next_detects_overlap(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """_set_next warns when the next slot starts before the current one ends."""
    sensor = _make_sensor(hass, True, {"start": {"minutes": -30}, "end": {"hours": 1}})
    # Current slot with offsets already applied: 22:30-01:00
    sensor._data = {
        "list": _slot(datetime(2024, 7, 14, 22, 30), datetime(2024, 7, 15, 1, 0)),
        "expiration": datetime(2024, 7, 15, 1, 0),
    }

    # Next slot 00:00-01:00 becomes 23:30-02:00 with the offsets.
    with caplog.at_level(logging.WARNING):
        sensor._set_next(
            _slot(datetime(2024, 7, 15, 0, 0), datetime(2024, 7, 15, 1, 0)),
            datetime(2024, 7, 16, 0, 0),
            NO_EXTRA,
        )

    assert "Offset overlap detected for test_sensor" in caplog.text
    nxt = sensor._data.get("next")
    assert nxt is not None
    assert nxt.get("list") == _slot(
        datetime(2024, 7, 14, 23, 30), datetime(2024, 7, 15, 2, 0)
    )


async def test_no_warning_when_no_overlap(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """No warning is logged when the next slot starts after the current one."""
    sensor = _make_sensor(hass, True, {"start": {"minutes": 15}})
    sensor._data = {
        "list": _slot(datetime(2024, 7, 14, 10, 15), datetime(2024, 7, 14, 11, 0)),
        "expiration": datetime(2024, 7, 15, 0, 0),
    }

    with caplog.at_level(logging.WARNING):
        sensor._set_next(
            _slot(datetime(2024, 7, 14, 12, 0), datetime(2024, 7, 14, 13, 0)),
            datetime(2024, 7, 15, 0, 0),
            NO_EXTRA,
        )

    assert "Offset overlap detected" not in caplog.text

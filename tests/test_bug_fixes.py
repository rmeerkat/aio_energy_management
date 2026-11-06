"""Regression tests for crashes and wrong values in the cheapest hours sensor."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from freezegun import freeze_time
import pytest

from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util

from custom_components.aio_energy_management.binary_sensor import (
    CheapestHoursBinarySensor,
)
from custom_components.aio_energy_management.coordinator import (
    EnergyManagementCoordinator,
)
from custom_components.aio_energy_management.exceptions import (
    SystemConfigurationError,
)
from custom_components.aio_energy_management.helpers import from_str_to_time


def _coordinator(data: dict | None = None) -> MagicMock:
    coordinator = MagicMock(spec=EnergyManagementCoordinator)
    coordinator.get_data.return_value = data if data is not None else {"list": []}
    return coordinator


def _sensor(hass: HomeAssistant, **kwargs) -> CheapestHoursBinarySensor:
    defaults = {
        "hass": hass,
        "unique_id": "test",
        "name": "Test",
        "first_hour": 0,
        "last_hour": 23,
        "starting_today": False,
        "number_of_slots": 3,
        "sequential": False,
        "coordinator": _coordinator(),
    }
    return CheapestHoursBinarySensor(**{**defaults, **kwargs})


def _hourly(day: datetime, key: str, value_key: str, with_end: bool) -> list[dict]:
    items = []
    for h in range(24):
        item = {key: (day + timedelta(hours=h)).isoformat(), value_key: float(h)}
        if with_end:
            item["end"] = (day + timedelta(hours=h + 1)).isoformat()
        items.append(item)
    return items


async def test_no_price_source_does_not_crash(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A sensor without a price source logs an error instead of crashing."""
    sensor = _sensor(hass)

    await sensor.async_update()

    assert "No price source configured for Test" in caplog.text
    assert sensor.is_on is False


@freeze_time("2026-11-05 10:00+02:00")
async def test_nordpool_without_raw_today_does_not_crash(hass: HomeAssistant) -> None:
    """A Nord Pool entity without raw_today is treated as 'no prices yet'."""
    hass.states.async_set(
        "sensor.nordpool", "1.0", {"today": [1.0] * 24, "raw_tomorrow": []}
    )
    sensor = _sensor(hass, nordpool_entity="sensor.nordpool")

    await sensor.async_update()

    assert sensor.extra_state_attributes["list"] == []


async def test_clear_archived_skips_items_without_valid_end(
    hass: HomeAssistant,
) -> None:
    """Archived items with a missing or invalid end are dropped, not crashed on."""
    coordinator = EnergyManagementCoordinator(hass)
    recent = (dt_util.now() - timedelta(hours=1)).isoformat()
    coordinator.data = {
        "sensor": {
            "archived": [
                {"start": recent, "end": None},
                {"start": recent, "end": "not a time"},
                {"start": recent},
                {"start": recent, "end": recent},
            ]
        }
    }

    coordinator.clear_archived("sensor", retention_days=1)

    assert coordinator.data["sensor"]["archived"] == [
        {"start": recent, "end": recent}
    ]


def test_from_str_to_time_with_invalid_string() -> None:
    """An invalid time string gives None instead of a TypeError."""
    assert from_str_to_time("not a time") is None
    assert from_str_to_time("22:30:00") is not None


async def test_failsafe_with_invalid_stored_times(hass: HomeAssistant) -> None:
    """Invalid failsafe times in storage switch the failsafe off, not crash."""
    sensor = _sensor(
        hass,
        nordpool_entity="sensor.nordpool",
        coordinator=_coordinator(
            {"list": [], "failsafe": {"start": "invalid", "end": "invalid"}}
        ),
    )

    assert sensor.is_on is False


async def test_invalid_trigger_time_is_ignored(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """An invalid trigger_time is reported and ignored."""
    sensor = _sensor(hass, nordpool_entity="sensor.nordpool", trigger_time="25:99")

    assert sensor._trigger_time is None
    assert "Invalid trigger_time '25:99'" in caplog.text


async def test_number_of_hours_entity_with_15_min_mtu(hass: HomeAssistant) -> None:
    """An entity id for number_of_hours is not repeated four times."""
    sensor = _sensor(
        hass,
        nordpool_entity="sensor.nordpool",
        number_of_slots=None,
        number_of_hours="input_number.hours",
        mtu=15,
    )

    assert sensor.extra_state_attributes["number_of_slots"] == "input_number.hours"


async def test_number_of_hours_value_with_15_min_mtu(hass: HomeAssistant) -> None:
    """A fixed number_of_hours is still converted to 15 minute slots."""
    sensor = _sensor(
        hass,
        nordpool_entity="sensor.nordpool",
        number_of_slots=None,
        number_of_hours=2,
        mtu=15,
    )

    assert sensor.extra_state_attributes["number_of_slots"] == 8


@freeze_time("2026-11-05 10:00+02:00")
async def test_mtu_error_names_nordpool_integration(hass: HomeAssistant) -> None:
    """The MTU mismatch error of the Nord Pool source names that integration."""
    today = dt_util.start_of_local_day()
    hass.states.async_set(
        "sensor.nordpool",
        "1.0",
        {
            "today": [1.0] * 24,
            "raw_today": _hourly(today, "start", "value", True),
            "raw_tomorrow": _hourly(today + timedelta(days=1), "start", "value", True),
        },
    )
    sensor = _sensor(hass, nordpool_entity="sensor.nordpool", mtu=15)

    with pytest.raises(SystemConfigurationError, match="used by nord pool integration"):
        sensor._update_from_nordpool(requested_mtu=15)


@freeze_time("2026-11-05 10:00+02:00")
async def test_mtu_error_names_entsoe_integration(hass: HomeAssistant) -> None:
    """The MTU mismatch error of the Entso-e source names that integration."""
    today = dt_util.start_of_local_day()
    hass.states.async_set(
        "sensor.entsoe",
        "1.0",
        {
            "prices_today": _hourly(today, "time", "price", False),
            "prices_tomorrow": _hourly(today + timedelta(days=1), "time", "price", False),
        },
    )
    sensor = _sensor(hass, entsoe_entity="sensor.entsoe", mtu=15)

    with pytest.raises(SystemConfigurationError, match="used by Entso-e integration"):
        sensor._update_from_entsoe(requested_mtu=15)


async def test_reading_attributes_keeps_stored_data(hass: HomeAssistant) -> None:
    """extra_state_attributes flattens 'extra' without changing the stored data."""
    extra = {"mean_price": 10.0, "max_price": 12.0, "min_price": 8.0}
    data = {"list": [], "extra": dict(extra)}
    sensor = _sensor(
        hass, nordpool_entity="sensor.nordpool", coordinator=_coordinator(data)
    )

    attributes = sensor.extra_state_attributes

    assert attributes["mean_price"] == 10.0
    assert "extra" not in attributes
    assert data == {"list": [], "extra": extra}

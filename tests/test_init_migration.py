"""Tests for config entry migration in aio_energy_management."""

from collections.abc import Coroutine
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.aio_energy_management import (
    _async_migrate_legacy_calendar_entry,
    async_migrate_entry,
)
from custom_components.aio_energy_management.coordinator import (
    EnergyManagementCoordinator,
)
from custom_components.aio_energy_management.const import (
    CONF_ENTITY_CALENDAR,
    CONF_ENTITY_EXCESS_SOLAR,
    COORDINATOR,
    DOMAIN,
)
from custom_components.aio_energy_management.runtime_data import (
    ConfigEntryRuntimeData,
    SharedRuntimeData,
    get_coordinator,
)

from pytest_homeassistant_custom_component.common import MockConfigEntry


def _close_coroutine(coro: Coroutine[object, object, object], *args, **kwargs) -> None:
    """Stand-in for hass.async_create_task that discards the scheduled coroutine."""
    coro.close()


@pytest.fixture
def legacy_calendar_entry() -> MockConfigEntry:
    """Create a legacy calendar config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Energy Management Calendar",
        data={
            "entry_type": CONF_ENTITY_CALENDAR,
            "name": "Test Calendar",
        },
        options={"calendar": True},
    )


@pytest.fixture
def other_entry() -> MockConfigEntry:
    """Create another config entry (not a calendar)."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Cheapest Hours",
        data={
            "entry_type": "cheapest_hours",
        },
    )


async def test_migration_schedules_removal_without_blocking(
    hass: HomeAssistant,
    legacy_calendar_entry: MockConfigEntry,
    other_entry: MockConfigEntry,
) -> None:
    """Test that migration schedules entry removal via async_create_task instead of awaiting.

    This prevents deadlock during bootstrap when multiple entries are set up
    concurrently and their setup_locks would block each other.
    """
    legacy_calendar_entry.add_to_hass(hass)
    other_entry.add_to_hass(hass)

    entries = hass.config_entries.async_entries(DOMAIN)

    created_tasks: list[Coroutine[object, object, object]] = []

    def track_create_task(coro: Coroutine[object, object, object], *args, **kwargs):
        created_tasks.append(coro)
        coro.close()  # Only scheduling is under test; never run the removal.
        return AsyncMock()

    with (
        patch.object(hass, "async_create_task", side_effect=track_create_task),
        patch.object(
            hass.config_entries, "async_remove", new_callable=AsyncMock
        ) as mock_remove,
    ):
        removed_ids, migrated_data = await _async_migrate_legacy_calendar_entry(
            hass, entries
        )

    assert legacy_calendar_entry.entry_id in removed_ids
    assert migrated_data is not None
    assert migrated_data["name"] == "Test Calendar"

    assert len(created_tasks) == 1, (
        "Expected async_create_task to be called exactly once for scheduling removal"
    )

    mock_remove.assert_called_once_with(legacy_calendar_entry.entry_id)


async def test_migration_returns_empty_when_no_legacy_entries(
    hass: HomeAssistant,
    other_entry: MockConfigEntry,
) -> None:
    """Test migration returns empty results when no legacy calendar entries exist."""
    other_entry.add_to_hass(hass)

    entries = hass.config_entries.async_entries(DOMAIN)

    removed_ids, migrated_data = await _async_migrate_legacy_calendar_entry(
        hass, entries
    )

    assert removed_ids == []
    assert migrated_data is None


async def test_migration_extracts_correct_data(
    hass: HomeAssistant,
    legacy_calendar_entry: MockConfigEntry,
) -> None:
    """Test migration extracts the correct data from legacy calendar entry."""
    legacy_calendar_entry.add_to_hass(hass)

    entries = hass.config_entries.async_entries(DOMAIN)

    with patch.object(hass, "async_create_task", side_effect=_close_coroutine):
        _, migrated_data = await _async_migrate_legacy_calendar_entry(
            hass, entries
        )

    assert migrated_data is not None
    assert migrated_data.get("enable_calendar") is True
    assert migrated_data["name"] == "Test Calendar"


def test_get_coordinator_from_config_entry_runtime_data(
    hass: HomeAssistant,
    other_entry: MockConfigEntry,
) -> None:
    """The config-entry runtime data provides the shared coordinator."""
    coordinator = MagicMock()
    other_entry.add_to_hass(hass)
    other_entry.runtime_data = ConfigEntryRuntimeData(
        shared=SharedRuntimeData(coordinator)
    )

    assert get_coordinator(hass, other_entry) is coordinator
    assert get_coordinator(hass) is coordinator


def test_get_coordinator_uses_yaml_runtime_fallback(hass: HomeAssistant) -> None:
    """The legacy YAML runtime remains available without config entries."""
    coordinator = MagicMock(spec=EnergyManagementCoordinator)
    hass.data[DOMAIN] = {COORDINATOR: coordinator}

    assert get_coordinator(hass) is coordinator


def _excess_solar_entry(minor_version: int = 1) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Excess Solar",
        version=1,
        minor_version=minor_version,
        data={
            "entry_type": CONF_ENTITY_EXCESS_SOLAR,
            "name": "Excess Solar",
            "sensor": "sensor.grid_power",
            "power_devices": [{"name": "Boiler", "consumption": 1000}],
        },
    )


async def test_migrate_excess_solar_unique_ids(hass: HomeAssistant) -> None:
    """Device entities get an entry-scoped unique id and keep user changes."""
    entry = _excess_solar_entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old_ids = {
        "binary_sensor": "excess_solar_boiler",
        "number": "excess_solar_boiler_priority",
        "switch": "excess_solar_boiler_enabled",
    }
    for platform, unique_id in old_ids.items():
        registry.async_get_or_create(platform, DOMAIN, unique_id, config_entry=entry)
    sensor = registry.async_get_or_create(
        "binary_sensor", DOMAIN, "excess_solar_boiler", config_entry=entry
    )
    registry.async_update_entity(sensor.entity_id, name="My boiler")
    master_id = f"excess_solar_master_switch_{entry.entry_id}"
    registry.async_get_or_create("switch", DOMAIN, master_id, config_entry=entry)

    assert await async_migrate_entry(hass, entry)

    prefix = f"excess_solar_{entry.entry_id}"
    for platform, old_id in old_ids.items():
        assert registry.async_get_entity_id(platform, DOMAIN, old_id) is None
        new_id = prefix + old_id.removeprefix("excess_solar")
        assert registry.async_get_entity_id(platform, DOMAIN, new_id) is not None
    migrated_sensor = registry.async_get(sensor.entity_id)
    assert migrated_sensor is not None
    assert migrated_sensor.name == "My boiler"
    assert registry.async_get_entity_id("switch", DOMAIN, master_id) is not None
    assert entry.minor_version == 2


async def test_migrate_other_entries_only_bumps_version(
    hass: HomeAssistant, other_entry: MockConfigEntry
) -> None:
    """Entries that are not excess solar keep their entities untouched."""
    other_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "binary_sensor", DOMAIN, "excess_solar_like_id", config_entry=other_entry
    )

    assert await async_migrate_entry(hass, other_entry)

    assert other_entry.minor_version == 2
    assert (
        registry.async_get_entity_id("binary_sensor", DOMAIN, "excess_solar_like_id")
        is not None
    )


async def test_migrate_refuses_newer_major_version(hass: HomeAssistant) -> None:
    """Entries from a newer major version are not downgraded."""
    entry = MockConfigEntry(domain=DOMAIN, version=2, data={})
    entry.add_to_hass(hass)

    assert not await async_migrate_entry(hass, entry)

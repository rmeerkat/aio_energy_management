"""Tests for setting up entities from config entries and legacy YAML."""

from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.template import Template

from custom_components.aio_energy_management import _async_setup_excess_solar_entry
from custom_components.aio_energy_management.binary_sensor import (
    async_setup_entry as binary_sensor_async_setup_entry,
    async_setup_platform as binary_sensor_async_setup_platform,
)
from custom_components.aio_energy_management.cheapest_hours import (
    CheapestHoursBinarySensor,
)
from custom_components.aio_energy_management.const import (
    CONF_ENTITY_CHEAPEST_HOURS,
    CONF_ENTITY_EXCESS_SOLAR,
    CONF_PRICE_MODIFICATIONS,
    COORDINATOR,
    DOMAIN,
)
from custom_components.aio_energy_management.coordinator import (
    EnergyManagementCoordinator,
)
from custom_components.aio_energy_management.runtime_data import (
    ConfigEntryRuntimeData,
    SharedRuntimeData,
)

PRICE_MODIFICATIONS = "{{ price * 1.21 }}"


def _coordinator() -> MagicMock:
    return MagicMock(spec=EnergyManagementCoordinator)


def _cheapest_hours_entry(**overrides: object) -> MockConfigEntry:
    """Cheapest-hours entry as the config flow stores it (NumberSelector -> float)."""
    data: dict[str, object] = {
        "entry_type": CONF_ENTITY_CHEAPEST_HOURS,
        "nordpool_entity": "sensor.nordpool",
        "unique_id": "cheapest_ui",
        "name": "Cheapest UI",
        "first_hour": 0.0,
        "last_hour": 23.0,
        "sequential": False,
        "number_of_slots": 3.0,
        **overrides,
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Cheapest UI", data=data)
    entry.runtime_data = ConfigEntryRuntimeData(
        shared=SharedRuntimeData(_coordinator())
    )
    return entry


def _yaml_cheapest_hours_config(**overrides: object) -> dict[str, object]:
    return {
        "entry_type": CONF_ENTITY_CHEAPEST_HOURS,
        "nordpool_entity": "sensor.nordpool",
        "unique_id": "cheapest_yaml",
        "name": "Cheapest YAML",
        "first_hour": 0,
        "last_hour": 23,
        "sequential": False,
        "number_of_slots": 3,
        **overrides,
    }


def _added_entities(async_add_entities: MagicMock) -> list[object]:
    async_add_entities.assert_called_once()
    return list(async_add_entities.call_args.args[0])


def _single_cheapest_hours_entity(
    async_add_entities: MagicMock,
) -> CheapestHoursBinarySensor:
    (entity,) = _added_entities(async_add_entities)
    assert isinstance(entity, CheapestHoursBinarySensor)
    return entity


async def test_excess_solar_entry_setup_accepts_read_only_entry_data(
    hass: HomeAssistant,
) -> None:
    """ConfigEntry.data is a MappingProxyType; setup must not reject it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Excess Solar",
        data={
            "entry_type": CONF_ENTITY_EXCESS_SOLAR,
            "name": "Excess Solar",
            "sensor": "sensor.grid_power",
            "power_devices": [{"name": "Boiler", "consumption": 1000}],
        },
    )
    entry.add_to_hass(hass)
    entry.runtime_data = ConfigEntryRuntimeData(
        shared=SharedRuntimeData(_coordinator())
    )

    with patch.object(
        hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
    ):
        await _async_setup_excess_solar_entry(hass, entry)

    excess_solar = entry.runtime_data.excess_solar
    assert excess_solar is not None
    assert len(excess_solar.sensors) == 1
    # Device entities are scoped to the entry, so two entries can share a device name.
    prefix = f"excess_solar_{entry.entry_id}"
    assert excess_solar.sensors[0].unique_id == f"{prefix}_boiler"
    assert excess_solar.number_entities[0].unique_id == f"{prefix}_boiler_priority"
    assert excess_solar.enabled_switches[0].unique_id == f"{prefix}_boiler_enabled"
    await excess_solar.manager.async_stop()


async def test_cheapest_hours_entry_with_float_values_creates_entity(
    hass: HomeAssistant,
) -> None:
    """Float hours/slots from the config flow must not be rejected by the YAML schema."""
    async_add_entities = MagicMock()

    await binary_sensor_async_setup_entry(
        hass, _cheapest_hours_entry(), async_add_entities
    )

    entities = _added_entities(async_add_entities)
    assert len(entities) == 1
    assert isinstance(entities[0], CheapestHoursBinarySensor)
    # The sensor is the main entity of its entry's device and takes its name.
    sensor = entities[0]
    assert sensor.has_entity_name
    assert sensor.name is None
    assert sensor.device_info is not None
    assert sensor.device_info.get("name") == "Cheapest UI"


async def test_cheapest_hours_entry_with_price_modifications(
    hass: HomeAssistant,
) -> None:
    """A price_modifications template from the UI ends up as a Template."""
    async_add_entities = MagicMock()

    await binary_sensor_async_setup_entry(
        hass,
        _cheapest_hours_entry(**{CONF_PRICE_MODIFICATIONS: PRICE_MODIFICATIONS}),
        async_add_entities,
    )

    entity = _single_cheapest_hours_entity(async_add_entities)
    assert isinstance(entity._price_modifications, Template)
    assert entity._price_modifications.template == PRICE_MODIFICATIONS


async def test_yaml_cheapest_hours_with_price_modifications(
    hass: HomeAssistant,
) -> None:
    """The YAML schema turns the template into a Template; it must not be converted twice."""
    hass.data[DOMAIN] = {COORDINATOR: _coordinator()}
    async_add_entities = MagicMock()

    await binary_sensor_async_setup_platform(
        hass,
        {},
        async_add_entities,
        _yaml_cheapest_hours_config(**{CONF_PRICE_MODIFICATIONS: PRICE_MODIFICATIONS}),
    )

    entity = _single_cheapest_hours_entity(async_add_entities)
    assert isinstance(entity._price_modifications, Template)
    assert entity._price_modifications.template == PRICE_MODIFICATIONS


async def test_yaml_cheapest_hours_invalid_config_creates_no_entity(
    hass: HomeAssistant,
) -> None:
    """The YAML schema is still enforced for legacy configuration."""
    hass.data[DOMAIN] = {COORDINATOR: _coordinator()}
    async_add_entities = MagicMock()

    await binary_sensor_async_setup_platform(
        hass,
        {},
        async_add_entities,
        _yaml_cheapest_hours_config(first_hour="not a number"),
    )

    assert _added_entities(async_add_entities) == []


async def test_excess_solar_entities_are_named_after_their_device(
    hass: HomeAssistant,
) -> None:
    """Entities use has_entity_name; HA composes '<device> <entity>' names."""
    hass.states.async_set("sensor.grid_power", "0")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Excess Solar",
        version=1,
        minor_version=2,
        data={
            "entry_type": CONF_ENTITY_EXCESS_SOLAR,
            "name": "Excess Solar",
            "sensor": "sensor.grid_power",
            "power_devices": [{"name": "Boiler", "consumption": 1000}],
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert device is not None
    assert device.name == "Excess Solar"

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {e.device_id for e in entities} == {device.id}
    friendly_names = {
        state.name
        for e in entities
        if (state := hass.states.get(e.entity_id)) is not None
    }
    assert friendly_names == {
        "Excess Solar",
        "Excess Solar Boiler",
        "Excess Solar Boiler Priority",
        "Excess Solar Boiler Enabled",
    }

    assert await hass.config_entries.async_unload(entry.entry_id)

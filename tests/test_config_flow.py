"""End-to-end tests for the config and options flows."""

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.aio_energy_management.const import (
    CONF_ADD_FLEXIBLE,
    CONF_BUFFER,
    CONF_CALENDAR,
    CONF_CONSUMPTION,
    CONF_DATA_PROVIDER_TYPE,
    CONF_ENABLE_CALENDAR,
    CONF_ENTITY_EXCESS_SOLAR,
    CONF_ENTSOE_ENTITY,
    CONF_FAILSAFE_STARTING_HOUR,
    CONF_FIRST_HOUR,
    CONF_FLEXIBLE_PRICE_LIMIT,
    CONF_GRID_POWER_SENSOR,
    CONF_INVERSED,
    CONF_LAST_HOUR,
    CONF_MAX_NUMBER_OF_SLOTS,
    CONF_MAX_PRICE_DELTA,
    CONF_MTU,
    CONF_NAME,
    CONF_NORDPOOL_ENTITY,
    CONF_NORDPOOL_OFFICIAL_CONFIG_ENTRY,
    CONF_NUMBER_OF_SLOTS,
    CONF_NUMBER_OF_SLOTS_ENTITY,
    CONF_OFFSET,
    CONF_POWER_DEVICES,
    CONF_PRICE_LIMIT,
    CONF_PRIORITY,
    CONF_SEQUENTIAL,
    CONF_STROMLIGNING_ENTITY,
    CONF_STROMLIGNING_TOMORROW_ENTITY,
    CONF_UNIQUE_ID,
    DATA_PROVIDER_ENTSOE,
    DATA_PROVIDER_NORDPOOL,
    DATA_PROVIDER_NORDPOOL_OFFICIAL,
    DATA_PROVIDER_STROMLIGNING,
    DOMAIN,
)

ENTRY_TYPE = "entry_type"
GLOBAL_SETTINGS = "global_settings"
CHEAPEST_HOURS = "cheapest_hours"


@pytest.fixture(autouse=True)
def mock_setup_entry() -> Generator[AsyncMock]:
    """Only test the flows; entry setup is covered by test_entry_setup."""
    with patch(
        "custom_components.aio_energy_management.async_setup_entry",
        return_value=True,
    ) as mock:
        yield mock


@pytest.fixture
def global_settings(hass: HomeAssistant) -> MockConfigEntry:
    """The Global Settings entry that exists after the first installation."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="⚙️ Global Settings",
        unique_id=GLOBAL_SETTINGS,
        minor_version=2,
        data={CONF_UNIQUE_ID: GLOBAL_SETTINGS, ENTRY_TYPE: GLOBAL_SETTINGS},
    )
    entry.add_to_hass(hass)
    return entry


def _basic_input(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        CONF_NAME: "Cheap Boiler",
        CONF_NUMBER_OF_SLOTS: 3,
        CONF_FIRST_HOUR: 0,
        CONF_LAST_HOUR: 23,
        CONF_SEQUENTIAL: False,
        CONF_CALENDAR: True,
        CONF_INVERSED: False,
        "dynamic_section": {},
    }
    data.update(overrides)
    return data


def _cheapest_hours_entry(**data: object) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Cheap Boiler",
        unique_id="cheap_boiler",
        minor_version=2,
        data={
            ENTRY_TYPE: CHEAPEST_HOURS,
            CONF_UNIQUE_ID: "cheap_boiler",
            CONF_NAME: "Cheap Boiler",
            CONF_DATA_PROVIDER_TYPE: DATA_PROVIDER_NORDPOOL,
            CONF_NORDPOOL_ENTITY: "sensor.nordpool",
            CONF_MTU: 60,
            CONF_NUMBER_OF_SLOTS: 3,
            CONF_FIRST_HOUR: 0,
            CONF_LAST_HOUR: 23,
            CONF_SEQUENTIAL: False,
            CONF_CALENDAR: True,
            CONF_INVERSED: False,
            **data,
        },
    )


def _excess_solar_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Excess Solar",
        unique_id="excess_solar",
        minor_version=2,
        data={
            ENTRY_TYPE: CONF_ENTITY_EXCESS_SOLAR,
            CONF_UNIQUE_ID: "excess_solar",
            CONF_NAME: "Excess Solar",
            CONF_GRID_POWER_SENSOR: "sensor.grid_power",
            CONF_BUFFER: 0,
            CONF_POWER_DEVICES: [
                {CONF_NAME: "Boiler", CONF_CONSUMPTION: 2000, CONF_PRIORITY: 1},
                {CONF_NAME: "Car", CONF_CONSUMPTION: 7400, CONF_PRIORITY: 2},
            ],
        },
    )


async def _start_cheapest_hours_flow(hass: HomeAssistant, provider: str) -> str:
    """Walk the flow up to the price source step and return its flow id."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {ENTRY_TYPE: CHEAPEST_HOURS}
    )
    assert result["step_id"] == "cheapest_hours_data_provider"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DATA_PROVIDER_TYPE: provider}
    )
    assert result["step_id"] == f"cheapest_hours_{provider}"
    return result["flow_id"]


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------


async def test_first_installation_creates_global_settings(hass: HomeAssistant) -> None:
    """Without Global Settings, the first flow creates that entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_UNIQUE_ID: GLOBAL_SETTINGS,
        ENTRY_TYPE: GLOBAL_SETTINGS,
    }
    assert result["result"].unique_id == GLOBAL_SETTINGS


@pytest.mark.usefixtures("global_settings")
async def test_create_cheapest_hours_entry(hass: HomeAssistant) -> None:
    """A complete cheapest hours flow creates a sanitised entry."""
    flow_id = await _start_cheapest_hours_flow(hass, DATA_PROVIDER_NORDPOOL)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NORDPOOL_ENTITY: "sensor.nordpool", CONF_MTU: "60"}
    )
    assert result["step_id"] == "cheapest_hours_basic"

    result = await hass.config_entries.flow.async_configure(flow_id, _basic_input())

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Cheap Boiler"
    data = result["data"]
    assert data[ENTRY_TYPE] == CHEAPEST_HOURS
    assert data[CONF_UNIQUE_ID] == "cheap_boiler"
    assert data[CONF_NORDPOOL_ENTITY] == "sensor.nordpool"
    assert data[CONF_MTU] == 60
    # NumberSelector values are stored as ints
    assert data[CONF_NUMBER_OF_SLOTS] == 3
    assert isinstance(data[CONF_NUMBER_OF_SLOTS], int)
    assert result["result"].unique_id == "cheap_boiler"


@pytest.mark.parametrize(
    ("provider", "source_input"),
    [
        (DATA_PROVIDER_ENTSOE, {CONF_ENTSOE_ENTITY: "sensor.entsoe", CONF_MTU: "60"}),
        (
            DATA_PROVIDER_STROMLIGNING,
            {
                CONF_STROMLIGNING_ENTITY: "sensor.stromligning",
                CONF_STROMLIGNING_TOMORROW_ENTITY: "binary_sensor.stromligning",
                CONF_MTU: "15",
            },
        ),
    ],
)
@pytest.mark.usefixtures("global_settings")
async def test_create_cheapest_hours_entry_other_sources(
    hass: HomeAssistant, provider: str, source_input: dict[str, object]
) -> None:
    """Every price source leads to the basic settings and an entry."""
    flow_id = await _start_cheapest_hours_flow(hass, provider)

    result = await hass.config_entries.flow.async_configure(flow_id, source_input)
    assert result["step_id"] == "cheapest_hours_basic"
    result = await hass.config_entries.flow.async_configure(flow_id, _basic_input())

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DATA_PROVIDER_TYPE] == provider


@pytest.mark.usefixtures("global_settings")
async def test_create_cheapest_hours_entry_nordpool_official(
    hass: HomeAssistant,
) -> None:
    """The official Nord Pool source offers the existing nordpool entries."""
    nordpool = MockConfigEntry(domain="nordpool", title="Nord Pool")
    nordpool.add_to_hass(hass)
    flow_id = await _start_cheapest_hours_flow(hass, DATA_PROVIDER_NORDPOOL_OFFICIAL)

    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {CONF_NORDPOOL_OFFICIAL_CONFIG_ENTRY: nordpool.entry_id, CONF_MTU: "60"},
    )
    result = await hass.config_entries.flow.async_configure(flow_id, _basic_input())

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NORDPOOL_OFFICIAL_CONFIG_ENTRY] == nordpool.entry_id


@pytest.mark.parametrize(
    ("basic_input", "error"),
    [
        (_basic_input(**{CONF_NUMBER_OF_SLOTS: 0}), "no_slots_configured"),
        (
            _basic_input(
                dynamic_section={CONF_NUMBER_OF_SLOTS_ENTITY: "sensor.slots"}
            ),
            "both_slots_configured",
        ),
    ],
)
@pytest.mark.usefixtures("global_settings")
async def test_cheapest_hours_basic_recovers_from_errors(
    hass: HomeAssistant, basic_input: dict[str, object], error: str
) -> None:
    """Invalid basic settings show the form again; valid input then succeeds."""
    flow_id = await _start_cheapest_hours_flow(hass, DATA_PROVIDER_NORDPOOL)
    await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NORDPOOL_ENTITY: "sensor.nordpool", CONF_MTU: "60"}
    )

    result = await hass.config_entries.flow.async_configure(flow_id, basic_input)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cheapest_hours_basic"
    assert result["errors"] == {"base": error}

    result = await hass.config_entries.flow.async_configure(flow_id, _basic_input())
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.usefixtures("global_settings")
async def test_cheapest_hours_entry_with_slots_entity(hass: HomeAssistant) -> None:
    """A helper entity instead of a fixed number of slots is accepted."""
    flow_id = await _start_cheapest_hours_flow(hass, DATA_PROVIDER_NORDPOOL)
    await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NORDPOOL_ENTITY: "sensor.nordpool", CONF_MTU: "60"}
    )

    result = await hass.config_entries.flow.async_configure(
        flow_id,
        _basic_input(
            **{CONF_NUMBER_OF_SLOTS: 0},
            dynamic_section={CONF_NUMBER_OF_SLOTS_ENTITY: "input_number.slots"},
        ),
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NUMBER_OF_SLOTS_ENTITY] == "input_number.slots"
    assert CONF_NUMBER_OF_SLOTS not in result["data"]


@pytest.mark.usefixtures("global_settings")
async def test_cheapest_hours_duplicate_name_aborts(hass: HomeAssistant) -> None:
    """A second sensor with the same name is not created."""
    _cheapest_hours_entry().add_to_hass(hass)
    flow_id = await _start_cheapest_hours_flow(hass, DATA_PROVIDER_NORDPOOL)
    await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NORDPOOL_ENTITY: "sensor.nordpool", CONF_MTU: "60"}
    )

    result = await hass.config_entries.flow.async_configure(flow_id, _basic_input())

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _start_excess_solar_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {ENTRY_TYPE: CONF_ENTITY_EXCESS_SOLAR}
    )
    assert result["step_id"] == "excess_solar_global"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Excess Solar",
            CONF_GRID_POWER_SENSOR: "sensor.grid_power",
            CONF_BUFFER: 50.0,
        },
    )
    assert result["step_id"] == "excess_solar_device"
    return result["flow_id"]


@pytest.mark.usefixtures("global_settings")
async def test_create_excess_solar_entry(hass: HomeAssistant) -> None:
    """Global settings, two devices and a created entry."""
    flow_id = await _start_excess_solar_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NAME: " Boiler ", CONF_CONSUMPTION: 2000.0, CONF_PRIORITY: 1.0}
    )
    assert result["step_id"] == "excess_solar_another_device"
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"add_another": True}
    )
    assert result["step_id"] == "excess_solar_device"
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_NAME: "Car",
            CONF_CONSUMPTION: 0.0,
            "consumption_entity": "sensor.car_power",
        },
    )
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"add_another": False}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Excess Solar"
    data = result["data"]
    assert data[ENTRY_TYPE] == CONF_ENTITY_EXCESS_SOLAR
    assert data[CONF_BUFFER] == 50
    devices = data[CONF_POWER_DEVICES]
    assert [d[CONF_NAME] for d in devices] == ["Boiler", "Car"]
    assert devices[0][CONF_CONSUMPTION] == 2000
    assert devices[1]["consumption_entity"] == "sensor.car_power"


@pytest.mark.usefixtures("global_settings")
async def test_excess_solar_device_requires_name(hass: HomeAssistant) -> None:
    """A device without a name is rejected and can then be corrected."""
    flow_id = await _start_excess_solar_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NAME: "  ", CONF_CONSUMPTION: 2000.0}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_NAME: "device_name_required"}

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NAME: "Boiler", CONF_CONSUMPTION: 2000.0}
    )
    assert result["step_id"] == "excess_solar_another_device"


@pytest.mark.usefixtures("global_settings")
async def test_excess_solar_duplicate_name_aborts(hass: HomeAssistant) -> None:
    """A second excess solar entry with the same name is not created."""
    _excess_solar_entry().add_to_hass(hass)
    flow_id = await _start_excess_solar_flow(hass)
    await hass.config_entries.flow.async_configure(
        flow_id, {CONF_NAME: "Boiler", CONF_CONSUMPTION: 2000.0}
    )

    result = await hass.config_entries.flow.async_configure(
        flow_id, {"add_another": False}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


async def test_options_global_settings(
    hass: HomeAssistant, global_settings: MockConfigEntry
) -> None:
    """The calendar can be enabled and renamed."""
    result = await hass.config_entries.options.async_init(global_settings.entry_id)
    assert result["step_id"] == "global_settings_options"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ENABLE_CALENDAR: True, CONF_NAME: "Energy"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert global_settings.options == {CONF_ENABLE_CALENDAR: True, CONF_NAME: "Energy"}


async def _open_cheapest_hours_menu_step(
    hass: HomeAssistant, entry: MockConfigEntry, step: str
) -> dict[str, object]:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == step
    return dict(result)


async def test_options_menu_offers_offset_for_sequential_only(
    hass: HomeAssistant,
) -> None:
    """The offset step only appears for sequential sensors."""
    non_sequential = _cheapest_hours_entry()
    non_sequential.add_to_hass(hass)
    sequential = MockConfigEntry(
        domain=DOMAIN,
        unique_id="sequential",
        data={**non_sequential.data, CONF_SEQUENTIAL: True},
    )
    sequential.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(non_sequential.entry_id)
    assert "cheapest_hours_offset" not in result["menu_options"]
    result = await hass.config_entries.options.async_init(sequential.entry_id)
    assert "cheapest_hours_offset" in result["menu_options"]


async def test_options_cheapest_hours_basic(hass: HomeAssistant) -> None:
    """Basic settings are saved to the entry data and the title follows the name."""
    entry = _cheapest_hours_entry()
    entry.add_to_hass(hass)
    result = await _open_cheapest_hours_menu_step(hass, entry, "cheapest_hours_basic")

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]),
        _basic_input(**{CONF_NAME: "Cheap Heater", CONF_NUMBER_OF_SLOTS: 5}),
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.title == "Cheap Heater"
    assert entry.data[CONF_NUMBER_OF_SLOTS] == 5
    assert entry.data[CONF_NUMBER_OF_SLOTS_ENTITY] is None


async def test_options_cheapest_hours_basic_error(hass: HomeAssistant) -> None:
    """Invalid basic settings in the options flow show an error."""
    entry = _cheapest_hours_entry()
    entry.add_to_hass(hass)
    result = await _open_cheapest_hours_menu_step(hass, entry, "cheapest_hours_basic")

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]), _basic_input(**{CONF_NUMBER_OF_SLOTS: 0})
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_slots_configured"}
    assert entry.data[CONF_NUMBER_OF_SLOTS] == 3


async def test_options_cheapest_hours_data_provider(hass: HomeAssistant) -> None:
    """The price source can be changed in the options flow."""
    entry = _cheapest_hours_entry()
    entry.add_to_hass(hass)
    result = await _open_cheapest_hours_menu_step(
        hass, entry, "cheapest_hours_data_provider"
    )

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]), {CONF_DATA_PROVIDER_TYPE: DATA_PROVIDER_ENTSOE}
    )
    assert result["step_id"] == "cheapest_hours_entsoe"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ENTSOE_ENTITY: "sensor.entsoe", CONF_MTU: "15"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_ENTSOE_ENTITY] == "sensor.entsoe"
    assert entry.data[CONF_MTU] == 15


async def test_options_cheapest_hours_advanced(hass: HomeAssistant) -> None:
    """Advanced settings are saved and cleared optional keys are stored as None."""
    entry = _cheapest_hours_entry(**{CONF_PRICE_LIMIT: 0.5})
    entry.add_to_hass(hass)
    result = await _open_cheapest_hours_menu_step(
        hass, entry, "cheapest_hours_advanced"
    )

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]),
        {CONF_FAILSAFE_STARTING_HOUR: 22.0, "dynamic_section": {}},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_FAILSAFE_STARTING_HOUR] == 22
    assert entry.data[CONF_PRICE_LIMIT] is None


async def test_options_cheapest_hours_advanced_error(hass: HomeAssistant) -> None:
    """A fixed price limit and a price limit entity are mutually exclusive."""
    entry = _cheapest_hours_entry()
    entry.add_to_hass(hass)
    result = await _open_cheapest_hours_menu_step(
        hass, entry, "cheapest_hours_advanced"
    )

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]),
        {
            CONF_PRICE_LIMIT: 0.5,
            "dynamic_section": {"price_limit_entity": "input_number.limit"},
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "both_price_limit_configured"}


async def test_options_cheapest_hours_flexible(hass: HomeAssistant) -> None:
    """Flexible slot settings are nested under add_flexible."""
    entry = _cheapest_hours_entry()
    entry.add_to_hass(hass)
    result = await _open_cheapest_hours_menu_step(
        hass, entry, "cheapest_hours_flexible"
    )

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]),
        {
            CONF_MAX_NUMBER_OF_SLOTS: 6.0,
            CONF_FLEXIBLE_PRICE_LIMIT: 0.1,
            "dynamic_section": {},
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_ADD_FLEXIBLE] == {
        CONF_MAX_NUMBER_OF_SLOTS: 6,
        CONF_PRICE_LIMIT: 0.1,
    }


async def test_options_cheapest_hours_flexible_error(hass: HomeAssistant) -> None:
    """A fixed flexible limit and a relative delta are mutually exclusive."""
    entry = _cheapest_hours_entry()
    entry.add_to_hass(hass)
    result = await _open_cheapest_hours_menu_step(
        hass, entry, "cheapest_hours_flexible"
    )

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]),
        {
            CONF_MAX_NUMBER_OF_SLOTS: 6.0,
            CONF_FLEXIBLE_PRICE_LIMIT: 0.1,
            CONF_MAX_PRICE_DELTA: 0.05,
            "dynamic_section": {},
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "flexible_limit_and_delta_exclusive"}
    assert CONF_ADD_FLEXIBLE not in entry.data


async def test_options_cheapest_hours_offset(hass: HomeAssistant) -> None:
    """Offsets of a sequential sensor are stored as a nested structure."""
    entry = _cheapest_hours_entry(**{CONF_SEQUENTIAL: True})
    entry.add_to_hass(hass)
    result = await _open_cheapest_hours_menu_step(hass, entry, "cheapest_hours_offset")

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]),
        {"start_minutes": -30.0, "end_hours": 1.0, "dynamic_section": {}},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_OFFSET] == {"start": {"minutes": -30}, "end": {"hours": 1}}


async def test_options_cheapest_hours_offset_error(hass: HomeAssistant) -> None:
    """Offset minutes outside -59..59 are rejected."""
    entry = _cheapest_hours_entry(**{CONF_SEQUENTIAL: True})
    entry.add_to_hass(hass)
    result = await _open_cheapest_hours_menu_step(hass, entry, "cheapest_hours_offset")

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]), {"start_minutes": 90.0, "dynamic_section": {}}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"start_minutes": "start_minutes_out_of_range"}


async def _open_excess_solar_menu(
    hass: HomeAssistant, entry: MockConfigEntry, action: str
) -> dict[str, object]:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "excess_solar_menu"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"devices_action": action}
    )
    return dict(result)


async def test_options_excess_solar_edit_settings(hass: HomeAssistant) -> None:
    """The grid sensor and buffer can be changed."""
    entry = _excess_solar_entry()
    entry.add_to_hass(hass)
    result = await _open_excess_solar_menu(hass, entry, "edit_settings")
    assert result["step_id"] == "excess_solar_edit_settings"

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]),
        {CONF_GRID_POWER_SENSOR: "sensor.other_grid", CONF_BUFFER: 100.0},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_GRID_POWER_SENSOR] == "sensor.other_grid"
    assert entry.data[CONF_BUFFER] == 100
    assert len(entry.data[CONF_POWER_DEVICES]) == 2


async def test_options_excess_solar_add_device(hass: HomeAssistant) -> None:
    """A device is appended to the existing devices."""
    entry = _excess_solar_entry()
    entry.add_to_hass(hass)
    result = await _open_excess_solar_menu(hass, entry, "add_device")
    assert result["step_id"] == "excess_solar_device"

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]), {CONF_NAME: "Pool pump", CONF_CONSUMPTION: 800.0}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"add_another": False}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [d[CONF_NAME] for d in entry.data[CONF_POWER_DEVICES]] == [
        "Boiler",
        "Car",
        "Pool pump",
    ]


async def test_options_excess_solar_remove_devices(hass: HomeAssistant) -> None:
    """Selected devices are removed."""
    entry = _excess_solar_entry()
    entry.add_to_hass(hass)
    result = await _open_excess_solar_menu(hass, entry, "remove_devices")
    assert result["step_id"] == "excess_solar_remove_devices"

    result = await hass.config_entries.options.async_configure(
        str(result["flow_id"]), {"devices_to_remove": ["Car"]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [d[CONF_NAME] for d in entry.data[CONF_POWER_DEVICES]] == ["Boiler"]


async def test_options_excess_solar_remove_without_devices_aborts(
    hass: HomeAssistant,
) -> None:
    """Removing devices from an entry without devices aborts."""
    entry = _excess_solar_entry()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_POWER_DEVICES: []}
    )

    result = await _open_excess_solar_menu(hass, entry, "remove_devices")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_to_remove"


@pytest.mark.usefixtures("global_settings")
async def test_excess_solar_device_optional_fields(hass: HomeAssistant) -> None:
    """Schedule entity and minimum off time are stored when given."""
    flow_id = await _start_excess_solar_flow(hass)

    await hass.config_entries.flow.async_configure(
        flow_id,
        {
            CONF_NAME: "Boiler",
            CONF_CONSUMPTION: 2000.0,
            "is_on_schedule": "binary_sensor.boiler_schedule",
            "minimum_on_time": 10.0,
            "minimum_off_time": 15.0,
        },
    )
    result = await hass.config_entries.flow.async_configure(
        flow_id, {"add_another": False}
    )

    device = result["data"][CONF_POWER_DEVICES][0]
    assert device["is_on_schedule"] == "binary_sensor.boiler_schedule"
    assert device["minimum_on_time"] == 10
    assert device["minimum_off_time"] == 15


async def test_options_unknown_entry_type_aborts(hass: HomeAssistant) -> None:
    """An entry of an unknown type has no options."""
    entry = MockConfigEntry(domain=DOMAIN, data={ENTRY_TYPE: "unknown"})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unknown_entry_type"

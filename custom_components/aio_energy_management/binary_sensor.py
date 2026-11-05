"""Binary sensor(s) for aio energy management."""

from __future__ import annotations

import logging
from typing import Required, TypedDict, cast

import probatio as vol
from probatio import ALLOW_EXTRA, Invalid, Schema

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.template import Template
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .cheapest_hours import CheapestHoursBinarySensor
from .cheapest_hours.binary_sensor import FlexibleConfig, OffsetConfig
from .coordinator import EnergyManagementCoordinator
from .entity import entry_device_info
from .const import (
    CONF_ADD_FLEXIBLE,
    CONF_AREA,
    CONF_CALENDAR,
    CONF_END,
    CONF_ENTITY_CHEAPEST_HOURS,
    CONF_ENTITY_EXCESS_SOLAR,
    CONF_ENTSOE_ENTITY,
    CONF_FAILSAFE_STARTING_HOUR,
    CONF_FIRST_HOUR,
    CONF_HOURS,
    CONF_INVERSED,
    CONF_LAST_HOUR,
    CONF_MAX_NUMBER_OF_SLOTS,
    CONF_MAX_NUMBER_OF_SLOTS_ENTITY,
    CONF_MAX_PRICE,
    CONF_MAX_PRICE_DELTA,
    CONF_MIN_SEQ_SLOTS,
    CONF_MINUTES,
    CONF_MTU,
    CONF_NAME,
    CONF_NORDPOOL_ENTITY,
    CONF_NORDPOOL_OFFICIAL_CONFIG_ENTRY,
    CONF_NUMBER_OF_BLOCKS,
    CONF_NUMBER_OF_HOURS,
    CONF_NUMBER_OF_SLOTS,
    CONF_NUMBER_OF_SLOTS_ENTITY,
    CONF_OFFSET,
    CONF_PRICE_LIMIT,
    CONF_PRICE_LIMIT_ENTITY,
    CONF_PRICE_MODIFICATIONS,
    CONF_RETENTION_DAYS,
    CONF_SEQUENTIAL,
    CONF_START,
    CONF_STARTING_TODAY,
    CONF_STROMLIGNING_ENTITY,
    CONF_STROMLIGNING_TOMORROW_ENTITY,
    CONF_TRIGGER_HOUR,
    CONF_TRIGGER_HOUR_ENTITY,
    CONF_TRIGGER_TIME,
    CONF_UNIQUE_ID,
    YAML_EXCESS_SOLAR_INSTANCE_KEY,
)
from .runtime_data import (
    AIOEnergyManagementConfigEntry,
    get_coordinator,
    get_entry_runtime_data,
    get_yaml_excess_solar_runtime_data,
)

_LOGGER = logging.getLogger(__name__)

CHEAPEST_HOURS_PLATFORM_SCHEMA = Schema(
    {
        vol.Optional(CONF_NORDPOOL_ENTITY): cv.entity_id,
        vol.Optional(CONF_NORDPOOL_OFFICIAL_CONFIG_ENTRY): vol.All(vol.Coerce(str)),
        vol.Optional(CONF_ENTSOE_ENTITY): cv.entity_id,
        vol.Optional(CONF_STROMLIGNING_ENTITY): cv.entity_id,
        vol.Optional(CONF_STROMLIGNING_TOMORROW_ENTITY): cv.entity_id,
        vol.Required(CONF_UNIQUE_ID): vol.All(vol.Coerce(str)),
        vol.Required(CONF_NAME): vol.All(vol.Coerce(str)),
        vol.Optional(CONF_STARTING_TODAY): bool,
        vol.Required(CONF_FIRST_HOUR): int,
        vol.Required(CONF_LAST_HOUR): int,
        vol.Required(CONF_SEQUENTIAL): bool,
        vol.Optional(CONF_NUMBER_OF_HOURS): vol.Any(int, cv.entity_id),
        vol.Optional(CONF_NUMBER_OF_SLOTS): vol.Any(int, cv.entity_id),
        vol.Optional(CONF_MIN_SEQ_SLOTS): vol.Any(int, cv.entity_id),
        vol.Optional(CONF_NUMBER_OF_BLOCKS): vol.Any(int, cv.entity_id),
        vol.Optional(CONF_FAILSAFE_STARTING_HOUR): int,
        vol.Optional(CONF_INVERSED): bool,
        vol.Optional(CONF_TRIGGER_TIME): vol.All(vol.Coerce(str)),
        vol.Optional(CONF_TRIGGER_HOUR): vol.Any(int, cv.entity_id),
        vol.Optional(CONF_MAX_PRICE): vol.Any(float, cv.entity_id),
        vol.Optional(CONF_PRICE_LIMIT): vol.Any(float, cv.entity_id),
        vol.Optional(CONF_ADD_FLEXIBLE): {
            vol.Optional(CONF_MAX_NUMBER_OF_SLOTS): vol.Any(int, cv.entity_id),
            vol.Optional(CONF_MAX_NUMBER_OF_SLOTS_ENTITY): cv.entity_id,
            vol.Optional(CONF_PRICE_LIMIT): vol.Any(float, cv.entity_id),
            vol.Optional(CONF_PRICE_LIMIT_ENTITY): cv.entity_id,
            vol.Optional(CONF_MAX_PRICE_DELTA): vol.Any(float, cv.entity_id),
        },
        vol.Optional(CONF_CALENDAR): bool,
        vol.Optional(CONF_RETENTION_DAYS): int,
        vol.Optional(CONF_OFFSET): {
            vol.Optional(CONF_START): {
                vol.Optional(CONF_HOURS): vol.Any(int, cv.entity_id),
                vol.Optional(CONF_MINUTES): vol.Any(int, cv.entity_id),
            },
            vol.Optional(CONF_END): {
                vol.Optional(CONF_HOURS): vol.Any(int, cv.entity_id),
                vol.Optional(CONF_MINUTES): vol.Any(int, cv.entity_id),
            },
        },
        vol.Optional(CONF_MTU): vol.Any(15, 60),
        vol.Optional(CONF_PRICE_MODIFICATIONS): cv.template,
    },
    extra=ALLOW_EXTRA,
)


class CheapestHoursConfig(TypedDict, total=False):
    """Validated configuration fields used to create a cheapest-hours sensor."""

    unique_id: Required[str]
    name: Required[str]
    first_hour: Required[int]
    last_hour: Required[int]
    sequential: Required[bool]
    nordpool_entity: str
    nordpool_official_config_entry: str
    entsoe_entity: str
    stromligning_entity: str
    stromligning_tomorrow_entity: str
    starting_today: bool
    number_of_hours: int | str
    number_of_slots: int | str
    number_of_slots_entity: str
    min_seq_slots: int | str
    number_of_blocks: int | str
    failsafe_starting_hour: int
    inversed: bool
    trigger_time: str
    trigger_hour: int | str
    trigger_hour_entity: str
    max_price: float | str
    price_limit: float | str
    price_limit_entity: str
    add_flexible: FlexibleConfig
    calendar: bool
    retention_days: int
    offset: OffsetConfig
    mtu: int
    area: str
    price_modifications: Template | str


def _validate_cheapest_hours_config(data: object) -> CheapestHoursConfig:
    """Validate legacy YAML data and expose its known fields to the type checker.

    The schema output is only used as a check: the original data is returned,
    because the schema converts values (e.g. ``price_modifications`` into a
    ``Template``) that ``_create_cheapest_hours_entity`` converts itself.
    """
    if not isinstance(data, dict):
        raise vol.Invalid("Expected a mapping")
    CHEAPEST_HOURS_PLATFORM_SCHEMA(data)
    return cast(CheapestHoursConfig, cast(object, data))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AIOEnergyManagementConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up binary sensor from a config entry."""
    entry_type = entry.data.get("entry_type")

    if entry_type == CONF_ENTITY_EXCESS_SOLAR:
        excess_solar = get_entry_runtime_data(entry).excess_solar
        if excess_solar is not None:
            async_add_entities(excess_solar.sensors)
        return

    try:
        # Merge data and options to make sure changes via UI are taking into account
        # Config-flow data is validated by the flow itself; the YAML schema does
        # not apply here (e.g. NumberSelector stores hours as floats).
        config_data = cast(
            CheapestHoursConfig, cast(object, {**entry.data, **entry.options})
        )
        entity = _create_cheapest_hours_entity(
            hass,
            config_data,
            coordinator=get_entry_runtime_data(entry).shared.coordinator,
            entry_id=entry.entry_id,
        )
        async_add_entities([entity])
    except Exception as e:
        _LOGGER.error(
            "Error setting up cheapest hours sensor from config entry: %s",
            e,
        )


async def async_setup_platform(
    hass: HomeAssistant,
    _config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Sensor containing amount of cheapest hours marked in the configuration (YAML legacy)."""
    if discovery_info is None:
        return

    discovery_data = cast(dict[str, object], discovery_info)
    entry_type = discovery_data.get("entry_type")

    entities: list[BinarySensorEntity] = []
    # Configure cheapest hours binary sensor
    if entry_type == CONF_ENTITY_CHEAPEST_HOURS:
        try:
            validated_config = _validate_cheapest_hours_config(discovery_data)
            entities.append(_create_cheapest_hours_entity(hass, validated_config))
        except Invalid as e:
            _LOGGER.error(
                "Configuration validation error for nord pool cheapest hours sensor: %s",
                e,
            )

    elif entry_type == CONF_ENTITY_EXCESS_SOLAR:
        storage_key = discovery_data.get(CONF_UNIQUE_ID)
        if not isinstance(storage_key, str):
            storage_key = YAML_EXCESS_SOLAR_INSTANCE_KEY
        excess_solar = get_yaml_excess_solar_runtime_data(hass, storage_key)
        if excess_solar is None or not excess_solar.sensors:
            _LOGGER.warning(
                "Excess solar platform loaded but no sensors found in hass.data"
            )
        else:
            entities.extend(excess_solar.sensors)

    async_add_entities(entities)


# Cheapest hours
def _create_cheapest_hours_entity(
    hass: HomeAssistant,
    discovery_info: CheapestHoursConfig,
    coordinator: EnergyManagementCoordinator | None = None,
    entry_id: str | None = None,
) -> CheapestHoursBinarySensor:
    nordpool_entity = discovery_info.get(CONF_NORDPOOL_ENTITY)
    nordpool_official_config_entry = discovery_info.get(
        CONF_NORDPOOL_OFFICIAL_CONFIG_ENTRY
    )
    entsoe_entity = discovery_info.get(CONF_ENTSOE_ENTITY)
    stromligning_entity = discovery_info.get(CONF_STROMLIGNING_ENTITY)
    stromligning_tomorrow_entity = discovery_info.get(CONF_STROMLIGNING_TOMORROW_ENTITY)
    unique_id = discovery_info[CONF_UNIQUE_ID]
    name = discovery_info[CONF_NAME]
    first_hour = discovery_info[CONF_FIRST_HOUR]
    last_hour = discovery_info[CONF_LAST_HOUR]
    starting_today = discovery_info.get(CONF_STARTING_TODAY)
    sequential = discovery_info[CONF_SEQUENTIAL]
    number_of_hours = discovery_info.get(CONF_NUMBER_OF_HOURS)
    number_of_slots = discovery_info.get(
        CONF_NUMBER_OF_SLOTS_ENTITY
    ) or discovery_info.get(CONF_NUMBER_OF_SLOTS)
    min_seq_slots = discovery_info.get(CONF_MIN_SEQ_SLOTS)
    number_of_blocks = discovery_info.get(CONF_NUMBER_OF_BLOCKS)
    failsafe_starting_hour = discovery_info.get(CONF_FAILSAFE_STARTING_HOUR)
    inversed = discovery_info.get(CONF_INVERSED) or False
    trigger_time = discovery_info.get(CONF_TRIGGER_TIME)
    price_limit = discovery_info.get(
        CONF_MAX_PRICE
    )  # DEPRECATED: replaced by price_limit. Keep here for few releases.
    trigger_hour = discovery_info.get(CONF_TRIGGER_HOUR_ENTITY) or discovery_info.get(
        CONF_TRIGGER_HOUR
    )
    add_flexible = discovery_info.get(CONF_ADD_FLEXIBLE)
    calendar = discovery_info.get(CONF_CALENDAR)
    retention_days = discovery_info.get(CONF_RETENTION_DAYS) or 1
    offset = discovery_info.get(CONF_OFFSET)
    mtu = discovery_info.get(CONF_MTU) or 60
    area = discovery_info.get(CONF_AREA) or None
    price_modifications = None
    if calendar is None:
        calendar = True
    pl = discovery_info.get(CONF_PRICE_LIMIT_ENTITY) or discovery_info.get(
        CONF_PRICE_LIMIT
    )
    if pl is not None:  # price_limit 0 is a valid limit
        price_limit = pl
    if pm := discovery_info.get(CONF_PRICE_MODIFICATIONS):
        price_modifications = cv.template(pm)

    if coordinator is None:
        coordinator = get_coordinator(hass)
    if coordinator is None:
        raise RuntimeError("Coordinator not initialized")

    return CheapestHoursBinarySensor(
        hass=hass,
        entsoe_entity=entsoe_entity,
        nordpool_entity=nordpool_entity,
        nordpool_official_config_entry=nordpool_official_config_entry,
        stromligning_entity=stromligning_entity,
        stromligning_tomorrow_entity=stromligning_tomorrow_entity,
        unique_id=unique_id,
        name=name,
        first_hour=first_hour,
        last_hour=last_hour,
        starting_today=starting_today,
        number_of_hours=number_of_hours,
        number_of_slots=number_of_slots,
        min_seq_slots=min_seq_slots,
        number_of_blocks=number_of_blocks,
        coordinator=coordinator,
        sequential=sequential,
        failsafe_starting_hour=failsafe_starting_hour,
        inversed=inversed,
        trigger_time=trigger_time,
        trigger_hour=trigger_hour,
        price_limit=price_limit,
        add_flexible=add_flexible,
        calendar=calendar,
        offset=offset,
        mtu=mtu,
        price_modifications=price_modifications,
        retention_days=retention_days,
        area=area,
        device_info=(
            entry_device_info(entry_id, name) if entry_id is not None else None
        ),
    )

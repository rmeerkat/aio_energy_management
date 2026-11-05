"""Factories for Excess Solar runtime entities and manager."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from ..const import (
    CONF_BUFFER,
    CONF_CONSUMPTION,
    CONF_GRID_POWER_SENSOR,
    CONF_IS_ON_SCHEDULE,
    CONF_MINIMUM_OFF_TIME,
    CONF_MINIMUM_ON_TIME,
    CONF_NAME,
    CONF_PRIORITY,
)
from .binary_sensor import DEFAULT_MINIMUM_OFF_TIME, ExcessSolarBinarySensor
from .manager import ExcessSolarConfig, ExcessSolarManager
from .number import ExcessSolarPriorityNumber
from .switch import ExcessSolarDeviceEnabledSwitch


YAML_UNIQUE_ID_PREFIX = "excess_solar"


def entry_unique_id_prefix(entry_id: str) -> str:
    """Return the unique id prefix of the device entities of a config entry."""
    return f"{YAML_UNIQUE_ID_PREFIX}_{entry_id}"


def build_sensors_from_config(
    hass: HomeAssistant,
    config: ExcessSolarConfig,
    manager: ExcessSolarManager | None = None,
    *,
    unique_id_prefix: str = YAML_UNIQUE_ID_PREFIX,
    device_info: DeviceInfo | None = None,
) -> tuple[
    list[ExcessSolarBinarySensor],
    list[ExcessSolarPriorityNumber],
    list[ExcessSolarDeviceEnabledSwitch],
]:
    """Build sensors, priority number entities, and enabled switches from config."""
    sensors: list[ExcessSolarBinarySensor] = []
    number_entities: list[ExcessSolarPriorityNumber] = []
    enabled_switches: list[ExcessSolarDeviceEnabledSwitch] = []

    entry_name = config.get(CONF_NAME, "Excess Solar")
    for device_config in config["power_devices"]:
        device_name = device_config[CONF_NAME]
        full_name = f"{entry_name} {device_name}"
        # With a device, entity names are relative to it (has_entity_name).
        display_name = device_name if device_info is not None else full_name
        slug = device_name.replace(" ", "_").lower()
        unique_id = f"{unique_id_prefix}_{slug}"
        initial_priority = device_config.get(CONF_PRIORITY, 100)

        priority_number = ExcessSolarPriorityNumber(
            hass=hass,
            device_name=display_name,
            unique_id=unique_id,
            initial_priority=initial_priority,
            on_priority_change_callback=(
                manager.on_priority_changed if manager else None
            ),
            device_info=device_info,
        )
        number_entities.append(priority_number)

        enabled_switch = ExcessSolarDeviceEnabledSwitch(
            unique_id=f"{unique_id}_enabled",
            name=f"{display_name} Enabled",
            device_info=device_info,
        )
        enabled_switches.append(enabled_switch)

        configured_consumption = device_config[CONF_CONSUMPTION]
        if isinstance(configured_consumption, str):
            consumption = 0
            consumption_entity = device_config.get(
                "consumption_entity", configured_consumption
            )
        else:
            consumption = configured_consumption
            consumption_entity = device_config.get("consumption_entity")

        minimum_off = device_config.get(CONF_MINIMUM_OFF_TIME)
        minimum_off_time = (
            int(minimum_off) if minimum_off is not None else DEFAULT_MINIMUM_OFF_TIME
        )

        sensor = ExcessSolarBinarySensor(
            hass=hass,
            device_entity_id=full_name,
            consumption=consumption,
            consumption_entity=consumption_entity,
            unique_id=unique_id,
            name=display_name,
            priority=initial_priority,
            is_on_schedule_entity=device_config.get(CONF_IS_ON_SCHEDULE),
            enabled_switch=enabled_switch,
            minimum_on_time=device_config.get(CONF_MINIMUM_ON_TIME, 0),
            minimum_off_time=minimum_off_time,
            priority_number_entity=priority_number,
            device_info=device_info,
        )
        sensors.append(sensor)

    return sensors, number_entities, enabled_switches


def create_manager_from_config(
    hass: HomeAssistant,
    config: ExcessSolarConfig,
    sensors: list[ExcessSolarBinarySensor],
) -> ExcessSolarManager:
    """Create an Excess Solar manager from validated config."""
    return ExcessSolarManager(
        hass=hass,
        grid_sensor=config[CONF_GRID_POWER_SENSOR],
        sensors=sensors,
        buffer=config.get(CONF_BUFFER, 0),
    )

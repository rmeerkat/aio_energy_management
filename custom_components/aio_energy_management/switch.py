"""Excess Solar switch platform setup."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_ENTITY_EXCESS_SOLAR,
    CONF_UNIQUE_ID,
    YAML_EXCESS_SOLAR_INSTANCE_KEY,
)
from .runtime_data import (
    AIOEnergyManagementConfigEntry,
    get_entry_runtime_data,
    get_yaml_excess_solar_runtime_data,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: AIOEnergyManagementConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up excess solar switches from a config entry."""
    if entry.data.get("entry_type") != CONF_ENTITY_EXCESS_SOLAR:
        return

    excess_solar = get_entry_runtime_data(entry).excess_solar
    if excess_solar is None:
        _LOGGER.warning(
            "Excess solar runtime data not found for entry '%s'",
            entry.title,
        )
        return

    async_add_entities([excess_solar.master_switch, *excess_solar.enabled_switches])


async def async_setup_platform(
    hass: HomeAssistant,
    _config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up excess solar switches from discovery (YAML legacy path)."""
    if discovery_info is None:
        return
    if discovery_info.get("entry_type") != CONF_ENTITY_EXCESS_SOLAR:
        return

    storage_key = discovery_info.get(CONF_UNIQUE_ID)
    if not isinstance(storage_key, str):
        storage_key = YAML_EXCESS_SOLAR_INSTANCE_KEY
    excess_solar = get_yaml_excess_solar_runtime_data(hass, storage_key)
    if excess_solar is None:
        _LOGGER.warning(
            "Excess solar switch platform loaded but no master switch found in hass.data"
        )
        return

    async_add_entities(
        [excess_solar.master_switch, *excess_solar.enabled_switches]
    )

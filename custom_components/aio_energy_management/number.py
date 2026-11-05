"""Number platform for AIO Energy Management."""

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
    """Set up number entities from a config entry."""
    if entry.data.get("entry_type") != CONF_ENTITY_EXCESS_SOLAR:
        return

    excess_solar = get_entry_runtime_data(entry).excess_solar
    if excess_solar is not None and excess_solar.number_entities:
        async_add_entities(excess_solar.number_entities)
        _LOGGER.debug(
            "Added %d excess solar priority number entities for entry '%s'",
            len(excess_solar.number_entities),
            entry.title,
        )


async def async_setup_platform(
    hass: HomeAssistant,
    _config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up number entities from discovery info."""
    if discovery_info is None:
        return

    entry_type = discovery_info.get("entry_type")

    if entry_type == CONF_ENTITY_EXCESS_SOLAR:
        storage_key = discovery_info.get(CONF_UNIQUE_ID)
        if not isinstance(storage_key, str):
            storage_key = YAML_EXCESS_SOLAR_INSTANCE_KEY
        excess_solar = get_yaml_excess_solar_runtime_data(hass, storage_key)
        if excess_solar is not None and excess_solar.number_entities:
            async_add_entities(excess_solar.number_entities)
            _LOGGER.info(
                "Added %d excess solar priority number entities",
                len(excess_solar.number_entities),
            )

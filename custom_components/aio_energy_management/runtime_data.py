"""Runtime data for AIO Energy Management config entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias, cast

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import COORDINATOR, DOMAIN
from .coordinator import EnergyManagementCoordinator

if TYPE_CHECKING:
    from .excess_solar import (
        ExcessSolarBinarySensor,
        ExcessSolarDeviceEnabledSwitch,
        ExcessSolarManager,
        ExcessSolarMasterSwitch,
        ExcessSolarPriorityNumber,
    )


@dataclass(slots=True)
class ExcessSolarRuntimeData:
    """Runtime entities and manager for one Excess Solar configuration."""

    manager: ExcessSolarManager
    sensors: list[ExcessSolarBinarySensor]
    number_entities: list[ExcessSolarPriorityNumber]
    enabled_switches: list[ExcessSolarDeviceEnabledSwitch]
    master_switch: ExcessSolarMasterSwitch


@dataclass(slots=True)
class SharedRuntimeData:
    """Runtime data shared by config entries of this integration."""

    coordinator: EnergyManagementCoordinator
    global_migration_done: bool = False


@dataclass(slots=True)
class ConfigEntryRuntimeData:
    """Runtime data attached to each config entry."""

    shared: SharedRuntimeData
    excess_solar: ExcessSolarRuntimeData | None = None


AIOEnergyManagementConfigEntry: TypeAlias = ConfigEntry[ConfigEntryRuntimeData]


def get_entry_runtime_data(
    entry: AIOEnergyManagementConfigEntry,
) -> ConfigEntryRuntimeData:
    """Return this integration's runtime data for a config entry."""
    return entry.runtime_data


def find_shared_runtime_data(hass: HomeAssistant) -> SharedRuntimeData | None:
    """Find runtime data shared by another loaded config entry."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        # runtime_data is unset before setup and removed again after unload.
        runtime_data = cast(object, getattr(entry, "runtime_data", None))
        if isinstance(runtime_data, ConfigEntryRuntimeData):
            return runtime_data.shared
    return None


def get_legacy_domain_data(
    hass: HomeAssistant, *, create: bool = False
) -> dict[str, object] | None:
    """Get the legacy YAML domain bucket after validating its runtime shape."""
    domain_data = cast(object, hass.data.get(DOMAIN))
    if isinstance(domain_data, dict):
        return cast(dict[str, object], domain_data)
    if not create:
        return None

    new_domain_data: dict[str, object] = {}
    hass.data[DOMAIN] = new_domain_data
    return new_domain_data


def get_coordinator(
    hass: HomeAssistant, entry: AIOEnergyManagementConfigEntry | None = None
) -> EnergyManagementCoordinator | None:
    """Get the coordinator from config-entry runtime data or the YAML runtime."""
    if entry is not None:
        return entry.runtime_data.shared.coordinator

    if shared_runtime_data := find_shared_runtime_data(hass):
        return shared_runtime_data.coordinator

    legacy_data = get_legacy_domain_data(hass)
    if legacy_data is None:
        return None

    coordinator = legacy_data.get(COORDINATOR)
    if isinstance(coordinator, EnergyManagementCoordinator):
        return coordinator
    return None


def get_yaml_excess_solar_runtime_data(
    hass: HomeAssistant, storage_key: str
) -> ExcessSolarRuntimeData | None:
    """Get validated Excess Solar runtime data from the legacy YAML bucket."""
    domain_data = get_legacy_domain_data(hass)
    if domain_data is None:
        return None

    runtime_data = domain_data.get(storage_key)
    if isinstance(runtime_data, ExcessSolarRuntimeData):
        return runtime_data
    return None
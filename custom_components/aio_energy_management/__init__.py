"""Energy management component init."""

from __future__ import annotations

import contextlib
import logging
from typing import TypedDict, cast

import probatio as vol

from homeassistant import core
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SERVICE_RELOAD, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.reload import (
    async_integration_yaml_config,
    async_reload_integration_platforms,
)
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_BUFFER,
    CONF_CALENDAR,
    CONF_CONSUMPTION,
    CONF_ENABLE_CALENDAR,
    CONF_ENTITY_CALENDAR,
    CONF_ENTITY_CHEAPEST_HOURS,
    CONF_ENTITY_EXCESS_SOLAR,
    CONF_EXCESS_SOLAR,
    CONF_GRID_POWER_SENSOR,
    CONF_IS_ON_SCHEDULE,
    CONF_MINIMUM_OFF_TIME,
    CONF_MINIMUM_ON_TIME,
    CONF_NAME,
    CONF_POWER_DEVICES,
    CONF_PRIORITY,
    CONF_UNIQUE_ID,
    COORDINATOR,
    DOMAIN,
    EXCESS_SOLAR_ENABLED_SWITCHES,
    EXCESS_SOLAR_MANAGER,
    EXCESS_SOLAR_SWITCH,
    YAML_EXCESS_SOLAR_INSTANCE_KEY,
)
from .coordinator import EnergyManagementCoordinator
from .excess_solar import (
    ExcessSolarConfig,
    ExcessSolarManager,
    ExcessSolarMasterSwitch,
    build_sensors_from_config,
    create_manager_from_config,
    validate_excess_solar_config,
)
from .entity import entry_device_info
from .excess_solar.factory import YAML_UNIQUE_ID_PREFIX, entry_unique_id_prefix
from .services import async_setup_services
from .runtime_data import (
    AIOEnergyManagementConfigEntry,
    ConfigEntryRuntimeData,
    ExcessSolarRuntimeData,
    SharedRuntimeData,
    find_shared_runtime_data,
    get_legacy_domain_data,
    get_entry_runtime_data,
)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.NUMBER,
    Platform.SWITCH,
]

_LOGGER = logging.getLogger(__name__)


class LegacyCalendarMigrationData(TypedDict):
    """Validated values migrated from the former calendar config entry."""

    enable_calendar: bool
    name: str
    unique_id: str | None

# YAML configuration schema for backward compatibility
CALENDAR_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_UNIQUE_ID): cv.string,
        vol.Optional(CONF_NAME): cv.string,
    }
)

# Excess solar YAML schema
POWER_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_CONSUMPTION): vol.Any(vol.Coerce(int), cv.entity_id),
        vol.Optional(CONF_PRIORITY, default=100): cv.positive_int,
        vol.Optional(CONF_IS_ON_SCHEDULE): cv.entity_id,
        vol.Optional(CONF_MINIMUM_ON_TIME, default=0): cv.positive_int,
        vol.Optional(CONF_MINIMUM_OFF_TIME): cv.positive_int,
    },
    extra=vol.REMOVE_EXTRA,
)

EXCESS_SOLAR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_GRID_POWER_SENSOR): cv.entity_id,
        vol.Required(CONF_POWER_DEVICES): vol.All(
            cv.ensure_list, [POWER_DEVICE_SCHEMA]
        ),
        vol.Optional(CONF_BUFFER, default=0): cv.positive_int,
    },
    extra=vol.REMOVE_EXTRA,
)


async def async_setup(hass: core.HomeAssistant, config: ConfigType) -> bool:
    """Set up the Energy Management component from YAML (legacy support)."""
    # Keep hass.data only for the legacy YAML configuration path.
    if DOMAIN in config:
        domain_data = get_legacy_domain_data(hass, create=True)
        assert domain_data is not None
        if COORDINATOR not in domain_data:
            coordinator = EnergyManagementCoordinator(hass)
            await coordinator.async_load_data()
            domain_data[COORDINATOR] = coordinator

    async def reload_service_handler(_service: ServiceCall) -> None:
        """Remove all user-defined groups and load new ones from config."""
        conf = None
        with contextlib.suppress(HomeAssistantError):
            conf = await async_integration_yaml_config(hass, DOMAIN)
        if conf is None:
            return
        # Stop existing excess solar manager if any before reload
        await _async_stop_excess_solar(hass)
        await async_reload_integration_platforms(hass, DOMAIN, PLATFORMS)
        domain_data = get_legacy_domain_data(hass, create=True)
        assert domain_data is not None
        coordinator = domain_data.get(COORDINATOR)
        if not isinstance(coordinator, EnergyManagementCoordinator) and (
            shared_runtime_data := find_shared_runtime_data(hass)
        ):
            coordinator = shared_runtime_data.coordinator
        if not isinstance(coordinator, EnergyManagementCoordinator):
            coordinator = EnergyManagementCoordinator(hass)
        domain_data[COORDINATOR] = coordinator
        await coordinator.async_load_data()
        if conf.get(DOMAIN):
            await _async_process_config(hass, conf)

    # Services
    await async_setup_services(hass)
    hass.services.async_register(  # pyright: ignore[reportUnknownMemberType]  # HA's VolSchemaType leaves All untyped
        DOMAIN,
        SERVICE_RELOAD,
        reload_service_handler,
        schema=vol.Schema({}),
    )

    # Process YAML config if present (legacy support)
    if DOMAIN in config:
        return await _async_process_config(hass, config)

    return True


async def _async_get_shared_runtime_data(hass: HomeAssistant) -> SharedRuntimeData:
    """Get or initialize runtime data shared by config entries."""
    if shared_runtime_data := find_shared_runtime_data(hass):
        return shared_runtime_data

    legacy_data = get_legacy_domain_data(hass)
    coordinator = legacy_data.get(COORDINATOR) if legacy_data is not None else None
    if not isinstance(coordinator, EnergyManagementCoordinator):
        coordinator = EnergyManagementCoordinator(hass)
        await coordinator.async_load_data()
    return SharedRuntimeData(coordinator)


async def async_setup_entry(
    hass: HomeAssistant, entry: AIOEnergyManagementConfigEntry
) -> bool:
    """Set up AIO Energy Management from a config entry."""
    entry.runtime_data = ConfigEntryRuntimeData(
        shared=await _async_get_shared_runtime_data(hass)
    )

    # Creates Global Settings and runs the one-time calendar migration if needed.
    entries = hass.config_entries.async_entries(DOMAIN)
    shared_runtime_data = get_entry_runtime_data(entry).shared
    migration_done = shared_runtime_data.global_migration_done
    has_global_settings = any(
        e.data.get("entry_type") == "global_settings" for e in entries
    )

    if not has_global_settings and not migration_done:
        shared_runtime_data.global_migration_done = True

        removed_entry_ids, migrated_data = await _async_migrate_legacy_calendar_entry(
            hass, entries
        )
        await _async_ensure_global_settings(hass, migrated_data)

        if entry.entry_id in removed_entry_ids:
            return True

    # Legacy standalone calendar entries are superseded by Global Settings.
    # Never let this entry set up its own platform; it will be removed by
    # the migration logic below (possibly from a different entry's call).
    if entry.data.get("entry_type") == CONF_ENTITY_CALENDAR:
        _LOGGER.debug(
            "Skipping setup of legacy calendar entry %s; superseded by Global Settings",
            entry.entry_id,
        )
        return True

    # Determine which platform to set up based on entry type
    entry_type = entry.data.get("entry_type")

    if entry_type == CONF_ENTITY_CHEAPEST_HOURS:
        await hass.config_entries.async_forward_entry_setups(
            entry, [Platform.BINARY_SENSOR]
        )
    elif entry_type in (CONF_ENTITY_CALENDAR, "global_settings"):
        if entry.options.get(CONF_CALENDAR, entry.data.get(CONF_CALENDAR, True)):
            await hass.config_entries.async_forward_entry_setups(
                entry, [Platform.CALENDAR]
            )
    elif entry_type == CONF_ENTITY_EXCESS_SOLAR:
        await _async_setup_excess_solar_entry(hass, entry)
    else:
        _LOGGER.error("Unknown entry type: %s", entry_type)
        return False

    # Register update listener to reload when options change
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def _async_ensure_global_settings(
    hass: HomeAssistant,
    migrated_data: LegacyCalendarMigrationData | None = None,
) -> None:
    """Create the Global Settings entry if it doesn't exist yet.

    Runs for every installation (new or upgraded) since exactly one Global
    Settings entry must always exist. When ``migrated_data`` is provided
    (carried over from a legacy calendar entry), the new entry is seeded
    with those values; otherwise defaults are used.
    """
    unique_id = migrated_data[CONF_UNIQUE_ID] if migrated_data else None

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
        data={
            "entry_type": "global_settings",
            CONF_UNIQUE_ID: unique_id,
        },
    )

    result_type = cast(object, result.get("type"))
    created_entry = cast(object, result.get("result"))
    if result_type != "create_entry" or not isinstance(created_entry, ConfigEntry):
        _LOGGER.error("Error creating Global Settings entry: %s", result)
        return
    typed_entry = cast(AIOEnergyManagementConfigEntry, created_entry)

    if migrated_data:
        hass.config_entries.async_update_entry(
            typed_entry,
            options={
                CONF_ENABLE_CALENDAR: migrated_data[CONF_ENABLE_CALENDAR],
                CONF_NAME: migrated_data[CONF_NAME],
            },
        )


async def _async_migrate_legacy_calendar_entry(
    hass: HomeAssistant, entries: list[ConfigEntry]
) -> tuple[list[str], LegacyCalendarMigrationData | None]:
    """Find and remove a legacy standalone calendar entry, if any.

    Returns:
        A tuple of (removed_entry_ids, migrated_data). migrated_data is
        None if no legacy calendar entry was found; otherwise a dict with
        the enable-state, name and unique_id to seed Global Settings with.

    TODO: Remove this migration (and the CONF_ENTITY_CALENDAR handling it
    depends on, including the guard at the top of async_setup_entry) once
    users have had time to upgrade.
    """
    entries_to_remove: list[str] = []
    migrated_data: LegacyCalendarMigrationData | None = None

    for existing_entry in entries:
        old_options = existing_entry.options
        old_data = existing_entry.data

        if old_data.get("entry_type") == CONF_ENTITY_CALENDAR:
            entries_to_remove.append(existing_entry.entry_id)
            calendar_enabled_value = cast(
                object,
                old_options.get(
                    CONF_CALENDAR, old_data.get(CONF_CALENDAR, True)
                ),
            )
            calendar_name_value = cast(
                object,
                old_options.get(CONF_NAME)
                or old_data.get(CONF_NAME)
                or old_options.get("name")
                or old_data.get("name"),
            )
            unique_id_value = cast(object, old_data.get(CONF_UNIQUE_ID))
            migrated_data = {
                CONF_ENABLE_CALENDAR: (
                    calendar_enabled_value
                    if isinstance(calendar_enabled_value, bool)
                    else True
                ),
                CONF_NAME: (
                    calendar_name_value
                    if isinstance(calendar_name_value, str)
                    else "Energy Management"
                ),
                CONF_UNIQUE_ID: (
                    unique_id_value if isinstance(unique_id_value, str) else None
                ),
            }

    for entry_id in entries_to_remove:
        _LOGGER.info("Scheduling removal of old calendar entry: %s", entry_id)
        hass.async_create_task(
            hass.config_entries.async_remove(entry_id),
            eager_start=True,
        )

    return entries_to_remove, migrated_data


async def _async_setup_excess_solar_from_entry_data(
    hass: HomeAssistant,
    entry_data: ExcessSolarConfig,
    *,
    master_switch_unique_id: str,
    device_unique_id_prefix: str,
    device_info: DeviceInfo | None = None,
) -> ExcessSolarRuntimeData:
    """Prepare excess solar manager and entities for an entry or YAML config."""
    config = entry_data
    manager = create_manager_from_config(hass, config, [])
    sensors, number_entities, enabled_switches = build_sensors_from_config(
        hass,
        config,
        manager,
        unique_id_prefix=device_unique_id_prefix,
        device_info=device_info,
    )
    manager.sensors = sensors
    manager.sort_sensors()

    master_switch = ExcessSolarMasterSwitch(
        manager=manager,
        unique_id=master_switch_unique_id,
        name=config.get(CONF_NAME, "Excess Solar"),
        device_info=device_info,
    )

    return ExcessSolarRuntimeData(
        manager=manager,
        sensors=sensors,
        number_entities=number_entities,
        enabled_switches=enabled_switches,
        master_switch=master_switch,
    )


async def _async_setup_excess_solar_entry(
    hass: HomeAssistant, entry: AIOEnergyManagementConfigEntry
) -> None:
    """Set up excess solar from a config entry."""
    runtime_data = get_entry_runtime_data(entry)
    # entry.data is a read-only MappingProxyType; copy it into a mutable dict.
    config = validate_excess_solar_config(dict(entry.data))
    excess_solar = await _async_setup_excess_solar_from_entry_data(
        hass,
        config,
        master_switch_unique_id=f"excess_solar_master_switch_{entry.entry_id}",
        device_unique_id_prefix=entry_unique_id_prefix(entry.entry_id),
        device_info=entry_device_info(
            entry.entry_id, config.get(CONF_NAME, "Excess Solar")
        ),
    )
    runtime_data.excess_solar = excess_solar

    await hass.config_entries.async_forward_entry_setups(
        entry, [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SWITCH]
    )
    manager = excess_solar.manager
    await manager.async_start()
    _LOGGER.info(
        "Excess solar entry '%s' started with %d device(s)",
        entry.data.get(CONF_NAME),
        len(excess_solar.sensors),
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries to the current version."""
    if entry.version > 1:
        # Created by a newer version of the integration.
        return False

    if entry.minor_version < 2:
        # 1.2: excess solar device entities include the entry id in their unique id.
        if entry.data.get("entry_type") == CONF_ENTITY_EXCESS_SOLAR:
            await _async_migrate_excess_solar_unique_ids(hass, entry)
        hass.config_entries.async_update_entry(entry, minor_version=2)

    return True


async def _async_migrate_excess_solar_unique_ids(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Move device entities from 'excess_solar_<device>' to an entry-scoped id."""
    new_prefix = entry_unique_id_prefix(entry.entry_id)
    master_switch_unique_id = f"excess_solar_master_switch_{entry.entry_id}"

    @core.callback
    def migrate(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
        unique_id = entity_entry.unique_id
        if (
            unique_id == master_switch_unique_id
            or unique_id.startswith(f"{new_prefix}_")
            or not unique_id.startswith(f"{YAML_UNIQUE_ID_PREFIX}_")
        ):
            return None
        new_unique_id = new_prefix + unique_id.removeprefix(YAML_UNIQUE_ID_PREFIX)
        _LOGGER.debug("Migrating unique id %s to %s", unique_id, new_unique_id)
        return {"new_unique_id": new_unique_id}

    await er.async_migrate_entries(hass, entry.entry_id, migrate)


async def async_unload_entry(
    hass: HomeAssistant, entry: AIOEnergyManagementConfigEntry
) -> bool:
    """Unload a config entry."""
    entry_type = entry.data.get("entry_type")

    if entry_type == CONF_ENTITY_CHEAPEST_HOURS:
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry, [Platform.BINARY_SENSOR]
        )
    elif entry_type == "global_settings":
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry, [Platform.CALENDAR]
        )
    elif entry_type == CONF_ENTITY_EXCESS_SOLAR:
        excess_solar = get_entry_runtime_data(entry).excess_solar
        if excess_solar is not None:
            await excess_solar.manager.async_stop()
        unload_ok = await hass.config_entries.async_unload_platforms(
            entry, [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SWITCH]
        )
    else:
        unload_ok = True

    return unload_ok


async def async_reload_entry(
    hass: HomeAssistant, entry: AIOEnergyManagementConfigEntry
) -> None:
    """Reload config entry."""
    # Clear coordinator data for cheapest hours entities when config changes
    entry_type = entry.data.get("entry_type")
    if entry_type == CONF_ENTITY_CHEAPEST_HOURS:
        unique_id = cast(object, entry.data.get(CONF_UNIQUE_ID))
        if isinstance(unique_id, str) and unique_id:
            coordinator = get_entry_runtime_data(entry).shared.coordinator
            await coordinator.async_clear_data(unique_id)
            _LOGGER.debug("Configuration modified and data cleared for %s", unique_id)

    await hass.config_entries.async_reload(entry.entry_id)


async def _async_process_config(hass: HomeAssistant, config: ConfigType) -> bool:
    """Process YAML configuration (legacy support)."""
    domain_data = get_legacy_domain_data(hass, create=True)
    assert domain_data is not None
    raw_domain_config = cast(object, config.get(DOMAIN))
    if not isinstance(raw_domain_config, dict):
        return True
    yaml_config = cast(dict[str, object], raw_domain_config)

    # Cheapest hours
    cheapest_hours_entries = yaml_config.get(CONF_ENTITY_CHEAPEST_HOURS)
    if isinstance(cheapest_hours_entries, list):
        for raw_entry in cast(list[object], cheapest_hours_entries):
            if not isinstance(raw_entry, dict):
                continue
            entry = cast(dict[str, object], raw_entry)
            entry["entry_type"] = CONF_ENTITY_CHEAPEST_HOURS
            hass.async_create_task(
                async_load_platform(
                    hass,
                    Platform.BINARY_SENSOR,
                    DOMAIN,
                    cast(DiscoveryInfoType, entry),
                    config,
                )
            )

    # Calendar
    calendar_entry = yaml_config.get(CONF_ENTITY_CALENDAR)
    if isinstance(calendar_entry, dict):
        typed_calendar_entry = cast(dict[str, object], calendar_entry)
        typed_calendar_entry["entry_type"] = CONF_ENTITY_CALENDAR
        hass.async_create_task(
            async_load_platform(
                hass,
                Platform.CALENDAR,
                DOMAIN,
                cast(DiscoveryInfoType, typed_calendar_entry),
                config,
            )
        )

    # Excess solar
    excess_solar_config = yaml_config.get(CONF_EXCESS_SOLAR)
    if excess_solar_config is not None:
        try:
            if not isinstance(excess_solar_config, dict):
                raise vol.Invalid("Excess Solar configuration must be a mapping")
            validated_config = cast(
                object,
                EXCESS_SOLAR_SCHEMA(cast(dict[str, object], excess_solar_config)),
            )
            excess_entry = validate_excess_solar_config(validated_config)
            excess_entry["entry_type"] = CONF_ENTITY_EXCESS_SOLAR
            excess_entry[CONF_NAME] = excess_entry.get(CONF_NAME, "Excess Solar")
            excess_entry[CONF_UNIQUE_ID] = YAML_EXCESS_SOLAR_INSTANCE_KEY

            bucket = await _async_setup_excess_solar_from_entry_data(
                hass,
                excess_entry,
                master_switch_unique_id="excess_solar_master_switch",
                device_unique_id_prefix=YAML_UNIQUE_ID_PREFIX,
            )
            domain_data[YAML_EXCESS_SOLAR_INSTANCE_KEY] = bucket

            for platform in (
                Platform.BINARY_SENSOR,
                Platform.NUMBER,
                Platform.SWITCH,
            ):
                hass.async_create_task(
                    async_load_platform(
                        hass,
                        platform,
                        DOMAIN,
                        cast(DiscoveryInfoType, cast(object, excess_entry)),
                        config,
                    )
                )

            await bucket.manager.async_start()
            _LOGGER.info(
                "Excess solar manager started with %d sensor(s), %d number entities, "
                "%d enabled switches, and master switch",
                len(bucket.sensors),
                len(bucket.number_entities),
                len(bucket.enabled_switches),
            )
        except (vol.Invalid, ValueError) as err:
            _LOGGER.error(
                "Failed to set up excess solar (invalid configuration): %s", err
            )
        except Exception:
            _LOGGER.exception("Failed to set up excess solar")

    return True


async def _async_stop_excess_solar(hass: HomeAssistant) -> None:
    """Stop and remove the excess solar manager if running."""
    domain_data = get_legacy_domain_data(hass)
    if domain_data is None:
        return

    bucket = domain_data.pop(YAML_EXCESS_SOLAR_INSTANCE_KEY, None)
    if isinstance(bucket, ExcessSolarRuntimeData):
        await bucket.manager.async_stop()
    elif isinstance(bucket, dict):
        legacy_bucket = cast(dict[str, object], bucket)
        manager = legacy_bucket.get(EXCESS_SOLAR_MANAGER)
        if isinstance(manager, ExcessSolarManager):
            await manager.async_stop()

    # Legacy layout before per-instance buckets
    manager = domain_data.pop(EXCESS_SOLAR_MANAGER, None)
    if isinstance(manager, ExcessSolarManager):
        await manager.async_stop()
    domain_data.pop("excess_solar_sensors", None)
    domain_data.pop("excess_solar_number_entities", None)
    domain_data.pop(EXCESS_SOLAR_ENABLED_SWITCHES, None)
    domain_data.pop(EXCESS_SOLAR_SWITCH, None)

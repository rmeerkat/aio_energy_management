"""Calendar component for aio energy management platform."""

from __future__ import annotations

from datetime import datetime
import logging
from collections.abc import Mapping
from typing import cast, override, TYPE_CHECKING, TypedDict

import probatio as vol
from probatio import ALLOW_EXTRA, Invalid, Schema

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import homeassistant.util.dt as dt_util

from .const import (
    CONF_ENABLE_CALENDAR,
    CONF_ENTITY_CALENDAR,
    CONF_NAME,
    CONF_UNIQUE_ID,
)
from .coordinator import EnergyManagementCoordinator
from .entity import entry_device_info
from .runtime_data import (
    AIOEnergyManagementConfigEntry,
    get_coordinator,
    get_entry_runtime_data,
)

if TYPE_CHECKING:
    from .entity import EntityDeviceInfo

_LOGGER = logging.getLogger(__name__)

ENERGY_MANAGEMENT_CALENDAR_PLATFORM_SCHEMA = Schema(
    {
        vol.Required(CONF_UNIQUE_ID): vol.All(vol.Coerce(str)),
        vol.Required(CONF_NAME): vol.All(vol.Coerce(str)),
    },
    extra=ALLOW_EXTRA,
)


class CalendarConfig(TypedDict):
    """Validated legacy YAML fields required to create the calendar entity."""

    unique_id: str
    name: str


def _validate_calendar_config(data: object) -> CalendarConfig:
    """Validate untyped platform data before using its calendar fields."""
    if not isinstance(data, dict):
        raise vol.Invalid("Expected a mapping")
    validated = cast(object, ENERGY_MANAGEMENT_CALENDAR_PLATFORM_SCHEMA(data))
    return cast(CalendarConfig, validated)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AIOEnergyManagementConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up calendar from a config entry."""

    # Check if calendar is activated
    enable_calendar = cast(
        object,
        entry.options.get(
            CONF_ENABLE_CALENDAR, entry.data.get(CONF_ENABLE_CALENDAR, False)
        ),
    )
    if not isinstance(enable_calendar, bool) or not enable_calendar:
        _LOGGER.debug(
            "Calendar is disabled in global settings, skipping calendar creation"
        )
        return
    _LOGGER.debug("Create energy management calendar entity from config entry")

    try:
        # Receive name and unique ID
        name_value = cast(
            object,
            entry.options.get(
                CONF_NAME,
                entry.data.get(CONF_NAME, "Energy Management Calendar"),
            ),
        )
        name = (
            name_value
            if isinstance(name_value, str)
            else "Energy Management Calendar"
        )
        unique_id_value = cast(
            object, entry.data.get(CONF_UNIQUE_ID, entry.entry_id)
        )
        unique_id = (
            unique_id_value if isinstance(unique_id_value, str) else entry.entry_id
        )
        async_add_entities(
            [
                EnergyManagementCalendar(
                    hass=hass,
                    unique_id=unique_id,
                    name=name,
                    coordinator=get_entry_runtime_data(entry).shared.coordinator,
                    device_info=entry_device_info(entry.entry_id, name),
                )
            ]
        )
    except Exception as e:
        _LOGGER.error(
            "Error setting up calendar from config entry: %s",
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
    if entry_type == CONF_ENTITY_CALENDAR:
        _LOGGER.debug("Create energy management calendar entity")

        try:
            calendar_config = _validate_calendar_config(discovery_data)
            coordinator = get_coordinator(hass)
            if coordinator is None:
                raise RuntimeError("Coordinator not initialized")
            async_add_entities(
                [
                    EnergyManagementCalendar(
                        hass=hass,
                        unique_id=calendar_config[CONF_UNIQUE_ID],
                        name=calendar_config[CONF_NAME],
                        coordinator=coordinator,
                    )
                ]
            )
        except Invalid as e:
            _LOGGER.error(
                "Configuration validation error for nord pool cheapest hours sensor: %s",
                e,
            )


class EnergyManagementCalendar(CalendarEntity):
    """Calendar entity."""

    hass: HomeAssistant
    _attr_unique_id: str | None
    _attr_has_entity_name: bool = True
    _attr_device_info: EntityDeviceInfo
    _attr_name: str | None
    _coordinator: EnergyManagementCoordinator
    _events: list[CalendarEvent]

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        name: str,
        coordinator: EnergyManagementCoordinator,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Init."""
        self.hass = hass
        self._attr_unique_id = unique_id.replace(" ", "_")
        # With a device the calendar is its device's main entity and takes its name.
        self._attr_name = None if device_info is not None else name
        self._attr_device_info = device_info
        self._coordinator = coordinator
        self._events = []

    @property
    @override
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming event."""
        now = dt_util.now()

        # First check for current event
        for event in self._events:
            if event.start <= now <= event.end:
                return event

        # If no current event, find the next upcoming event
        future_events = [event for event in self._events if event.start > now]
        if not future_events:
            return None

        # Return the earliest upcoming event
        return min(future_events, key=lambda x: x.start)

    @override
    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        return [
            event
            for event in self._events
            if event.start <= end_date and event.end >= start_date
        ]

    async def async_update(self) -> None:
        """Update loop of calendar. Only update when data is changed."""
        if self._coordinator.requires_calendar_update is True:
            self._events = self._get_all_events()
            self._coordinator.requires_calendar_update = False

    def _get_all_events(
        self,
    ) -> list[CalendarEvent]:
        """Get calendar events within a datetime range."""
        events: list[CalendarEvent] = []
        coordinator_data = cast(object, self._coordinator.data)
        if not isinstance(coordinator_data, dict):
            return events

        typed_data = cast(dict[object, object], coordinator_data)
        for entity_key, raw_data in typed_data.items():
            if not isinstance(entity_key, str):
                continue
            data = self._as_mapping(raw_data)
            if data is None or data.get("calendar") is False:
                continue

            name = data.get("name")
            summary = name if isinstance(name, str) else entity_key
            event_records = self._get_event_records(data.get("list"))
            event_records.extend(self._get_event_records(data.get("archived")))

            next_data = self._as_mapping(data.get("next"))
            if next_data is not None:
                event_records.extend(self._get_event_records(next_data.get("list")))

            for record in event_records:
                event = self._create_calendar_event(entity_key, summary, record)
                if event is not None:
                    events.append(event)

        # Sort events by start time
        events.sort(key=lambda x: x.start)

        return events

    @staticmethod
    def _as_mapping(value: object) -> Mapping[str, object] | None:
        """Return a string-keyed view of mapping-shaped coordinator data."""
        if isinstance(value, dict):
            return cast(Mapping[str, object], value)
        return None

    @classmethod
    def _get_event_records(cls, value: object) -> list[Mapping[str, object]]:
        """Return valid event-record mappings from coordinator data."""
        if not isinstance(value, list):
            return []
        typed_values = cast(list[object], value)
        return [
            record
            for item in typed_values
            if (record := cls._as_mapping(item)) is not None
        ]

    def _create_calendar_event(
        self,
        entity_key: str,
        summary: str,
        record: Mapping[str, object],
    ) -> CalendarEvent | None:
        """Create a calendar event when its stored start and end are valid."""
        start = self._parse_event_datetime(record.get("start"))
        end = self._parse_event_datetime(record.get("end"))
        if start is None or end is None:
            return None

        return CalendarEvent(
            summary=summary,
            start=start,
            end=end,
            uid=self._uid(entity_key, start, end),
            description="",
        )

    @staticmethod
    def _parse_event_datetime(value: object) -> datetime | None:
        """Parse an event timestamp from restored or in-memory coordinator data."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return dt_util.parse_datetime(value)
        return None

    def _uid(
        self, unqiue_id: str, event_start_time: datetime, event_end_time: datetime
    ) -> str:
        """Generate a deterministic unique id for an event.

        The uid is generated from the event start and end times converted to
        UTC and formatted as YYYYmmddTHHMMSSZ for compactness and stability.
        """
        # Ensure we work with timezone-aware UTC datetimes for stability
        start_utc = dt_util.as_utc(event_start_time)
        end_utc = dt_util.as_utc(event_end_time)

        start_str = start_utc.strftime("%Y%m%dT%H%M%SZ")
        end_str = end_utc.strftime("%Y%m%dT%H%M%SZ")

        return f"{unqiue_id}_{start_str}_{end_str}"

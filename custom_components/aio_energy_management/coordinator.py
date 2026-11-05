"""Data coordinator. Owns all the data."""

from collections.abc import MutableMapping
from datetime import timedelta
import logging
from typing import cast

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util

from .helpers import convert_datetime, from_str_to_datetime
from .models.cheapest_hours_data import CheapestHoursData, TimeSlot

STORAGE_VERSION = 1
STORAGE_KEY = "aio_energy_management.storage"
_LOGGER = logging.getLogger(__name__)

type CoordinatorData = dict[str, CheapestHoursData]


# TODO: .. version migration
class EnergyManagementCoordinator:
    """Common coordinator for Energy Management component. Owner of the data."""

    _store: Store[CoordinatorData]
    data: CoordinatorData
    requires_calendar_update: bool

    def __init__(self, hass: HomeAssistant) -> None:
        """Init persistent store."""
        self._store = Store[CoordinatorData](hass, STORAGE_VERSION, STORAGE_KEY)
        self.data = {}
        self.requires_calendar_update = False

    async def _async_save_data(self) -> None:
        """Save data to store."""
        _LOGGER.debug("Request to save data: %s", self.data)
        await self._store.async_save(self.data)

    async def async_clear_store(self) -> None:
        """Clear store."""
        _LOGGER.debug("Request to clear all values from the store")
        await self._store.async_save({})

    async def async_clear_data(self, unique_id: str) -> None:
        """Clear entity data by unique_id."""
        _LOGGER.debug("Request to clear data for %s", unique_id)
        if self.data.get(unique_id) is not None:
            self.data.pop(unique_id, None)
            await self._async_save_data()

    async def async_load_data(self) -> None:
        """Load data from store."""
        stored = await self._store.async_load()
        if stored:
            _LOGGER.debug("Load data from store: %s", stored)
            self.data = self.convert_datetimes(stored)
            self.requires_calendar_update = True

    async def async_set_data(
        self,
        entity_id: str,
        name: str | None,
        calendar: bool,
        module: str,
        data: CheapestHoursData,  # Data that is currently active or upcoming
        archived: list[TimeSlot] | None,  # Data that is to be moved on the archive
    ) -> None:
        """Set entity data."""
        prev_archived: list[TimeSlot] | None = None

        # Check if previous
        if entity := self.data.get(entity_id):
            prev_archived = entity.get("archived")

        data["name"] = name
        data["type"] = module
        data["calendar"] = calendar
        data["archived"] = self._update_archived(prev_archived, archived)
        self.data[entity_id] = data

        _LOGGER.debug(
            "Set new data for %s. Archive is = %s",
            entity_id,
            [data["archived"]],
        )

        self.requires_calendar_update = True
        await self._async_save_data()

    def _update_archived(
        self,
        existing_archive: list[TimeSlot] | None,
        new_data: list[TimeSlot] | None,
    ) -> list[TimeSlot]:
        """Merge archived lists by 'start' key, preferring existing values on conflict."""
        # Build dicts keyed by 'start' for fast lookup
        current_by_start = {
            item["start"]: item for item in existing_archive or [] if "start" in item
        }
        new_by_start = {item["start"]: item for item in new_data or [] if "start" in item}

        # Merge keys: use current if exists, else new
        return [
            current_by_start.get(start) or new_by_start[start]
            for start in sorted(set(current_by_start) | set(new_by_start))
        ]

    def clear_archived(self, entity_id: str, retention_days: int) -> None:
        """Clear archived data older than retention days."""
        oldest_end = dt_util.now() - timedelta(days=retention_days)
        if entity_data := self.data.get(entity_id):
            filtered_archived: list[TimeSlot] = []
            for item in entity_data.get("archived", []):
                end = from_str_to_datetime(item.get("end"))
                if end is not None and end >= oldest_end:
                    filtered_archived.append(item)
            entity_data["archived"] = filtered_archived
            _LOGGER.debug(
                "After clearing, archived for %s is %s",
                entity_id,
                filtered_archived,
            )

    def get_data(self, entity_id: str) -> CheapestHoursData:
        """Get entity data, always containing a 'list'."""
        _LOGGER.debug("Query data from store for %s", entity_id)
        data: CheapestHoursData = self.data.get(entity_id) or {}
        if data.get("list") is None:
            data["list"] = []  # Always contain list
        return data

    def convert_datetimes(self, stored: CoordinatorData) -> CoordinatorData:
        """Convert stored datetime items back to data."""
        for key, value in stored.items():
            stored[key] = self._convert_datetimes_of_item(
                cast(MutableMapping[str, object], cast(object, value))
            )
        return stored

    def _convert_datetimes_of_item(
        self, item: MutableMapping[str, object]
    ) -> CheapestHoursData:
        """Convert stored datetime strings back to datetime/date objects."""
        for field in ("expiration", "updated_at"):
            if isinstance(value := item.get(field), str):
                item[field] = from_str_to_datetime(value)

        if isinstance(value := item.get("fetch_date"), str):
            item["fetch_date"] = dt_util.parse_date(value)

        for field in ("list", "archived"):
            if isinstance(value := item.get(field), list) and value:
                item[field] = convert_datetime(
                    cast(list[MutableMapping[str, object]], value)
                )

        if isinstance(data_next := item.get("next"), dict):
            next_item = cast(MutableMapping[str, object], data_next)
            if isinstance(list_next := next_item.get("list"), list) and list_next:
                next_item["list"] = convert_datetime(
                    cast(list[MutableMapping[str, object]], list_next)
                )
            if isinstance(expiration_next := next_item.get("expiration"), str):
                next_item["expiration"] = from_str_to_datetime(expiration_next)

        return cast(CheapestHoursData, cast(object, item))

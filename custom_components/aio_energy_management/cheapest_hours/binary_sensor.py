"""Nord pool cheapet hours binary sensor."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
import logging
import random
from typing import cast, override, TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, ServiceResponse, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.template import Template
import homeassistant.util.dt as dt_util

from ..const import (
    CONF_MAX_NUMBER_OF_SLOTS,
    CONF_MAX_NUMBER_OF_SLOTS_ENTITY,
    CONF_MAX_PRICE_DELTA,
    CONF_PRICE_LIMIT,
    CONF_PRICE_LIMIT_ENTITY,
    INTERNAL_CHEAPEST_HOURS_MINIMUM_VALID_SLOTS,
)
from ..coordinator import EnergyManagementCoordinator
from ..enums import HourPriceType
from ..exceptions import (
    InvalidEntityState,
    InvalidInput,
    SystemConfigurationError,
    ValueNotFound,
)
from ..helpers import (
    as_float,
    from_str_to_datetime,
    from_str_to_time,
    get_first,
    get_last,
    time_in_between,
)
from ..models.cheapest_hours_data import (
    CheapestHoursData,
    Failsafe,
    NextData,
    PriceExtra,
    TimeSlot,
)
from ..models.hour_price import HourPrice
from .math import (
    calculate_non_sequential_cheapest_hours,
    calculate_sequential_cheapest_hours,
)

if TYPE_CHECKING:
    from ..entity import EntityDeviceInfo

_LOGGER = logging.getLogger(__name__)
FETCH_INTERVAL = timedelta(minutes=5)

# A configured number may be a fixed value or the entity id of a helper.
type NumberOrEntity = int | float | str
type OffsetConfig = Mapping[str, Mapping[str, NumberOrEntity]]
type FlexibleConfig = Mapping[str, NumberOrEntity]
type RawPrices = list[Mapping[str, object]]
type Prices = tuple[list[HourPrice], list[HourPrice], int]


class CheapestHoursBinarySensor(BinarySensorEntity):
    """Cheapest hours sensor."""

    _attr_has_entity_name: bool = True
    _attr_device_info: EntityDeviceInfo

    hass: HomeAssistant
    _attr_unique_id: str | None
    _attr_name: str | None
    _attr_icon: str | None
    _name: str
    _nordpool_entity: str | None
    _nordpool_official_config_entry: str | None
    _entsoe_entity: str | None
    _stromligning_entity: str | None
    _stromligning_tomorrow_entity: str | None
    _unique_id: str
    _coordinator: EnergyManagementCoordinator
    _first_hour: int
    _last_hour: int
    _starting_today: bool
    _sequential: bool
    _failsafe_starting_hour: int | None
    _number_of_hours: NumberOrEntity | None
    _number_of_slots: NumberOrEntity | None
    _min_seq_slots: NumberOrEntity | None
    _number_of_blocks: NumberOrEntity | None
    _inversed: bool
    _trigger_hour: NumberOrEntity | None
    _price_limit: NumberOrEntity | None
    _add_flexible: FlexibleConfig
    _calendar: bool
    _last_known_day: date | None
    _retention_days: int
    _area: str | None
    _archived: list[TimeSlot] | None
    _last_fetch_attempt: datetime | None
    _fetch_interval: timedelta
    _price_modifications: Template | None
    _mtu: int
    _offset: OffsetConfig
    _trigger_time: time | None
    _data: CheapestHoursData

    def __init__(
        self,
        hass: HomeAssistant,
        unique_id: str,
        name: str,
        first_hour: int,
        last_hour: int,
        starting_today: bool | None,
        sequential: bool,
        coordinator: EnergyManagementCoordinator,
        number_of_hours: NumberOrEntity | None = None,
        number_of_slots: NumberOrEntity | None = None,
        min_seq_slots: NumberOrEntity | None = None,
        number_of_blocks: NumberOrEntity | None = None,
        failsafe_starting_hour: int | None = None,
        inversed: bool = False,
        entsoe_entity: str | None = None,
        nordpool_entity: str | None = None,
        nordpool_official_config_entry: str | None = None,
        stromligning_entity: str | None = None,
        stromligning_tomorrow_entity: str | None = None,
        trigger_time: str | time | None = None,
        trigger_hour: NumberOrEntity | None = None,
        price_limit: NumberOrEntity | None = None,
        add_flexible: FlexibleConfig | None = None,
        calendar: bool = True,
        offset: OffsetConfig | None = None,
        mtu: int | None = 60,
        price_modifications: Template | None = None,
        retention_days: int = 1,
        area: str | None = None,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Init sensor."""
        self._nordpool_entity = nordpool_entity
        self._nordpool_official_config_entry = nordpool_official_config_entry
        self._entsoe_entity = entsoe_entity
        self._stromligning_entity = stromligning_entity
        self._stromligning_tomorrow_entity = stromligning_tomorrow_entity
        self._unique_id = unique_id.replace(" ", "_")
        self._attr_unique_id = self._unique_id
        self._name = name
        # With a device the sensor is its device's main entity and takes its name.
        self._attr_name = None if device_info is not None else name
        self._attr_device_info = device_info
        self._attr_icon = "mdi:clock"
        self._coordinator = coordinator
        self._first_hour = first_hour
        self._last_hour = last_hour

        # Initialize starting_today if not provided
        self._starting_today = (
            last_hour < first_hour if starting_today is None else starting_today
        )

        self._sequential = sequential
        self._failsafe_starting_hour = failsafe_starting_hour
        self._number_of_hours = number_of_hours
        self._number_of_slots = number_of_slots
        self._min_seq_slots = min_seq_slots
        self._number_of_blocks = number_of_blocks
        self._inversed = inversed
        self._trigger_hour = trigger_hour
        self._price_limit = price_limit
        self._add_flexible = add_flexible or {}
        self._calendar = calendar
        self._last_known_day = None
        self._retention_days = retention_days
        self._area = area
        self._archived = None
        self._last_fetch_attempt = None
        self._fetch_interval = FETCH_INTERVAL + timedelta(
            seconds=random.uniform(0, 300)
        )
        self._price_modifications = price_modifications
        self._mtu = 60 if mtu is None else mtu

        # Expose the configured hours as slots. An entity id is resolved later.
        if number_of_hours:
            self._number_of_slots = (
                number_of_hours * 4
                if mtu == 15 and isinstance(number_of_hours, int)
                else number_of_hours
            )

        self._offset = offset or {}
        self._trigger_time = (
            from_str_to_time(trigger_time) if trigger_time is not None else None
        )

        self.hass = hass
        self._data = self._coordinator.get_data(self._unique_id)

    async def async_update(self) -> None:
        """Update sensor."""
        await self._async_operate()

    @property
    @override
    def extra_state_attributes(self) -> dict[str, object]:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return all the data."""
        return {
            **self._construct_data_attributes(),
            **self._construct_static_attributes(),
        }

    @property
    @override
    def is_on(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return true if the binary sensor is on."""
        items = self._data.get("list")
        if not items:
            # No valid data, check failsafe
            _LOGGER.debug("No valid data found. Check failsafe")
            return self._is_failsafe()

        # We got valid data, check the actual list of items
        now = dt_util.now()
        for item in items:
            start = from_str_to_datetime(item.get("start"))
            end = from_str_to_datetime(item.get("end"))
            if start is None or end is None:
                continue
            if dt_util.as_local(start) <= now <= dt_util.as_local(end):
                return True

        return False

    async def _async_operate(self) -> None:
        # Always get new data from coordinator as other components might have modified the data
        self._data = self._coordinator.get_data(self._unique_id)

        await self._swap_list_if_needed()

        # Check for day change
        current_day = dt_util.start_of_local_day().date()
        if current_day != self._last_known_day:
            self._last_known_day = current_day
            self._coordinator.clear_archived(self._unique_id, self._retention_days)

        # Don't update values if we are already on failsafe as we don't want to interrupt it
        if self._is_failsafe():
            _LOGGER.debug("Failsafe on. Don't interrupt the operation")
            return

        # Check if our data is valid and we do not need to do anything
        if self._is_fetched_today() and not self._is_expired():
            _LOGGER.debug("Data complete for %s, no fetch needed", self._unique_id)
            return

        # Update number of hours.. this actually needs to be stored in the data..
        try:
            self._update_entity_variables()
        except InvalidEntityState:
            _LOGGER.error("Failed to get values from external entities!")
            return

        # Check if update is allowed by local rules (trigger time)
        if self._is_allowed_to_update() is False:
            _LOGGER.debug("Update not allowed by set rules")
            return

        # Create entity failsafe from configuration
        self._data["failsafe"] = self._create_failsafe()

        prices = await self._async_fetch_prices()
        if prices is None:
            if self._is_expired():
                self._data["list"] = []
            return
        today, tomorrow, _active_mtu = prices

        # Apply possible price modifications from template
        if price_modifications := self._price_modifications:
            today = self._apply_price_modifications(today, price_modifications)
            tomorrow = self._apply_price_modifications(tomorrow, price_modifications)

        # Skip calculations if prices are not known yet for tomorrow
        if (
            len(tomorrow) < INTERNAL_CHEAPEST_HOURS_MINIMUM_VALID_SLOTS
            and self._data.get("today_only")
            and not self._is_expired()
            and self._data.get("list")
        ):
            _LOGGER.debug(
                "Skipping calculation for %s: tomorrow prices not available yet and today's calculation is still valid",
                self._unique_id,
            )
            return

        number_of_slots = self._data.get("active_number_of_slots")
        if number_of_slots is None:
            _LOGGER.error(
                "No number of hours or slots configured for %s", self._unique_id
            )
            return

        # Use proper method if sequential or non-sequential
        try:
            if self._sequential:
                (cheapest, today_only) = calculate_sequential_cheapest_hours(
                    today,
                    tomorrow,
                    number_of_slots,
                    self._starting_today,
                    self._first_hour,
                    self._last_hour,
                    self._inversed,
                    self._data.get("active_price_limit"),
                    self._mtu,
                    self._data.get("active_max_number_of_slots"),
                    self._data.get("active_flexible_price_limit"),
                    max_price_delta=self._data.get("active_max_price_delta"),
                )
            else:
                (cheapest, today_only) = calculate_non_sequential_cheapest_hours(
                    today,
                    tomorrow,
                    number_of_slots,
                    self._starting_today,
                    self._first_hour,
                    self._last_hour,
                    self._inversed,
                    self._data.get("active_price_limit"),
                    self._mtu,
                    self._data.get("active_max_number_of_slots"),
                    self._data.get("active_flexible_price_limit"),
                    # make sure it defaults to 1
                    self._data.get("active_min_seq_slots") or 1,
                    self._data.get("active_number_of_blocks"),
                    max_price_delta=self._data.get("active_max_price_delta"),
                )
        except (InvalidInput, ValueNotFound):  # fmt: skip
            # math.py already logged the reason (e.g. invalid input, or an
            # overnight window without tomorrow's prices yet). These signal that
            # no calculation should happen right now, so skip this update and
            # keep the current data/calendar events intact.
            return

        # Construct new data from calculated hours
        if self._is_expired():
            self._set_list(
                cheapest["list"],
                self._create_expiration(today_only=today_only),
                cheapest["extra"],
            )
        elif self._data.get("list") == cheapest["list"]:
            # Data is the same. Do nothing
            return
        else:  # Not expired, but data is not the same. Set to list_next
            self._set_next(
                cheapest["list"],
                self._create_expiration(today_only=today_only),
                cheapest["extra"],
            )

        self._data["today_only"] = today_only
        self._data["fetch_date"] = self._create_fetch_date(today_only=today_only)

        # Finally store the data
        await self._store_data()

    async def _async_fetch_prices(self) -> Prices | None:
        """Fetch today's and tomorrow's prices from the configured source.

        Returns None when no (valid) prices are available right now.
        """
        # Update from nordpool official
        if self._nordpool_official_config_entry is not None:
            # Throttle: don't hit the price API more often than FETCH_INTERVAL
            now = dt_util.utcnow()
            if (
                self._last_fetch_attempt is not None
                and now - self._last_fetch_attempt < self._fetch_interval
            ):
                _LOGGER.debug(
                    "Waiting for new prices for %s, next fetch in %s",
                    self._unique_id,
                    self._fetch_interval - (now - self._last_fetch_attempt),
                )
                return None
            self._last_fetch_attempt = now

            # No valid data found from store either, try get new
            _LOGGER.debug(
                "Fetching prices for %s (data expired or tomorrow's prices not yet received)",
                self._unique_id,
            )
            try:
                return await self._update_from_nordpool_official(self._mtu)
            except (ServiceValidationError, ValueNotFound) as e:
                _LOGGER.debug(
                    "No values for tomorrow in nord pool official integration %s", e
                )
            except (SystemConfigurationError, InvalidEntityState) as e:
                _LOGGER.error(
                    "Could not get the latest data from official nord pool integration: %s",
                    e,
                )
            return None

        # Update from nordpool custom component
        if self._nordpool_entity is not None:
            try:
                return self._update_from_nordpool(requested_mtu=self._mtu)
            except ValueNotFound:
                _LOGGER.debug("Could not get the latest data from nordpool integration")
            except SystemConfigurationError as e:
                _LOGGER.error("Invalid configuration or mismatch of data: %s", e)
            return None

        # Update from entsoe
        if self._entsoe_entity is not None:
            try:
                return self._update_from_entsoe(requested_mtu=self._mtu)
            except ValueNotFound:
                _LOGGER.debug("Could not get the latest data from entsoe integration")
            except SystemConfigurationError:
                _LOGGER.error(
                    "Failed to get enough data from Entso-e integration using %s. Ensure your system timezone and Entso-e integration region is correct!",
                    self._entsoe_entity,
                )
            return None

        # Update from stromligning
        if self._stromligning_entity is not None:
            try:
                return self._update_from_stromligning(requested_mtu=self._mtu)
            except ValueNotFound:
                _LOGGER.debug(
                    "Could not get the latest data from Strømligning integration"
                )
            except SystemConfigurationError as e:
                _LOGGER.error("Failed to get data from Strømligning integration: %s", e)
            return None

        _LOGGER.error("No price source configured for %s", self._unique_id)
        return None

    async def _store_data(self) -> None:
        await self._coordinator.async_set_data(
            self._unique_id,
            self._name,
            self._calendar,
            self.__class__.__name__,
            self._data,
            self._archived,
        )

    async def _swap_list_if_needed(self) -> bool:
        """Swap the list_next to list if needed. Returns true if list was swapped."""
        if self._is_expired():  # Data is expired
            if nxt := self._data.get("next"):
                self._set_list(
                    nxt.get("list") or [],
                    nxt.get("expiration"),
                    nxt.get("extra"),
                    is_swap=True,
                )
                # Clear previous next data as it's transferred to parent now
                self._data.pop("next", None)

                # Remove deprecated list_next. List next was used prior version 0.3.3
                self._data.pop("list_next", None)

                await self._store_data()
                return True

            self._data["list"] = []

        return False

    def _set_list(
        self,
        list_data: list[TimeSlot],
        expiration: datetime | None,
        attributes: PriceExtra | None,
        is_swap: bool = False,
    ) -> None:
        """Set list data."""
        # Archive previous
        self._archived = self._data.get("list")

        if is_swap is False and expiration is not None:
            list_data, expiration = self._add_offset(list_data, expiration)
        self._data["list"] = list_data
        self._data["expiration"] = expiration
        if attributes is not None:
            self._data["extra"] = attributes
        else:
            self._data.pop("extra", None)
        self._data["updated_at"] = dt_util.now()

    def _set_next(
        self, list_data: list[TimeSlot], expiration: datetime, attributes: PriceExtra
    ) -> None:
        lst, exp = self._add_offset(list_data, expiration)

        # Check for overlap with current slot
        if (current := self._data.get("list")) and lst:
            current_end = current[-1].get("end")
            next_start = lst[0].get("start")
            if current_end and next_start and next_start < current_end:
                _LOGGER.warning(
                    "Offset overlap detected for %s: next slot starts at %s but "
                    "current slot (with offset) ends at %s. The sensor will remain "
                    "in current state until %s, potentially missing 'on' time for "
                    "the next slot",
                    self._unique_id,
                    next_start,
                    current_end,
                    self._data.get("expiration"),
                )

        nxt: NextData = {"list": lst, "expiration": exp, "extra": attributes}
        self._data["next"] = nxt

    def _add_offset(
        self, slots: list[TimeSlot], expiration: datetime
    ) -> tuple[list[TimeSlot], datetime]:
        new_expiration = expiration
        # Offset is only supported for sequential sensors
        if not self._sequential:
            if self._offset:
                _LOGGER.error(
                    "Offset is configured for %s but offsets are only supported for "
                    "sequential sensors. The offset will be ignored",
                    self._unique_id,
                )
            return (slots, new_expiration)

        # Prevent a crash if the list is empty for whatever reason.
        if not slots:
            return (slots, new_expiration)

        # Make a copy to make dure original input is unchanged.
        modified_list: list[TimeSlot] = [
            {"start": item["start"], "end": item["end"]} for item in slots
        ]

        if (first := get_first(modified_list)) and (
            offset := self._offset.get("start")
        ):
            first["start"] = first["start"] + self._offset_delta(offset)

        if (last := get_last(modified_list)) and (offset := self._offset.get("end")):
            end_offset = self._offset_delta(offset)
            new_end = last["end"] + end_offset
            last["end"] = new_end

            # if added end is greater than expiration, extend the expiration as well
            if new_end > expiration:
                new_expiration = expiration + end_offset

        # Validation: Check whether all time blocks have a valid duration (start < end).
        for item in modified_list:
            if item["end"] <= item["start"]:
                _LOGGER.error(
                    "Applying offset for %s resulted in an invalid duration "
                    "(start: %s, end: %s). The offset will be ignored.",
                    self._unique_id,
                    item["start"],
                    item["end"],
                )
                # Ignore the offset and return the original, unmodified list.
                return (slots, expiration)

        return (modified_list, new_expiration)

    def _offset_delta(self, offset: Mapping[str, NumberOrEntity]) -> timedelta:
        """Return the configured start or end offset as timedelta."""
        hours = self._int_from_entity(offset.get("hours"))
        minutes = self._int_from_entity(offset.get("minutes"))
        return timedelta(hours=hours or 0, minutes=minutes or 0)

    def _is_expired(self) -> bool:
        """Check if data is expired."""
        if self._data.get("list") is None:
            return True

        expiration = from_str_to_datetime(self._data.get("expiration"))
        if expiration is None:
            return True

        expires = dt_util.as_local(expiration)
        _LOGGER.debug(
            "Checking expiration. Expiration as local = %s, now = %s",
            expires,
            dt_util.now(),
        )
        return expires <= dt_util.now()

    def _is_allowed_to_update(self) -> bool:
        """Check if update is allowed by local rules."""
        if self._trigger_time is not None:
            if dt_util.now().time() < self._trigger_time:
                return False
        if trigger_hour := self._data.get("active_trigger_hour"):
            if dt_util.now().hour < trigger_hour:
                return False
        return True

    def _is_fetched_today(self) -> bool:
        fetch_date = self._data.get("fetch_date")
        return fetch_date is not None and fetch_date == dt_util.start_of_local_day().date()

    def _create_failsafe(self) -> Failsafe | None:
        """Construct failsafe dictionary."""
        if self._failsafe_starting_hour is None:
            return None

        start = dt_util.now().replace(
            hour=self._failsafe_starting_hour, minute=0, second=0, microsecond=0
        )
        number_of_slots = self._data.get("active_number_of_slots") or 0
        end = start + timedelta(minutes=number_of_slots * self._mtu)

        return {"start": start.time(), "end": end.time()}

    def _create_expiration(self, today_only: bool = False) -> datetime:
        """Calculate value expiration."""
        return dt_util.start_of_local_day() + timedelta(
            hours=(0 if today_only else 24) + 1 + self._last_hour
        )

    def _create_fetch_date(self, today_only: bool = False) -> date:
        """Return fetch date."""
        # If today_only is True, return yesterdays date (mock the fetch for previous day), otherwise return today's date
        return (
            (dt_util.start_of_local_day() + timedelta(days=-1)).date()
            if today_only
            else dt_util.start_of_local_day().date()
        )

    def _get_state(self, entity_id: str | None) -> State | None:
        """Return the state of a source entity, if configured and present."""
        if entity_id is None:
            return None
        return self.hass.states.get(entity_id)

    def _update_from_nordpool(self, requested_mtu: int = 60) -> Prices:
        np = self._get_state(self._nordpool_entity)

        if np is None:
            _LOGGER.debug(
                "Got empty data from Norpool entity %s ", self._nordpool_entity
            )
            raise ValueNotFound
        if _attribute(np, "today") is None:
            _LOGGER.debug(
                "No values for today in Norpool entity %s ", self._nordpool_entity
            )
            raise ValueNotFound
        if _attribute(np, "tomorrow_valid") is False:
            _LOGGER.debug(
                "No values for tomorrow_valid in Norpool entity %s ",
                self._nordpool_entity,
            )
            raise ValueNotFound

        raw_today = _as_price_list(_attribute(np, "raw_today"))
        if not raw_today:
            _LOGGER.debug(
                "No raw values for today in Norpool entity %s ", self._nordpool_entity
            )
            raise ValueNotFound

        # Ensure raw_today first value is actually today as we might get old values
        # if Home Assistant event loop has not reached nord pool yet")
        if first := from_str_to_datetime(raw_today[0].get("start")):
            if first.date() != dt_util.start_of_local_day().date():
                _LOGGER.debug("Nord pool provided old data: Ignore")
                raise ValueNotFound

        raw_tomorrow = _as_price_list(_attribute(np, "raw_tomorrow"))
        if raw_tomorrow is None:
            _LOGGER.warning(
                "No values for tomorrow in Norpool entity %s ", self._nordpool_entity
            )
            raise ValueNotFound

        return self._to_prices(
            raw_today,
            raw_tomorrow,
            requested_mtu,
            HourPriceType.NORDPOOL,
            "nord pool integration",
        )

    def _update_from_entsoe(self, requested_mtu: int = 60) -> Prices:
        """Update from entsoe integration."""
        entsoe = self._get_state(self._entsoe_entity)
        if entsoe is None:
            _LOGGER.debug("Got empty data from Entso-e entity %s ", self._entsoe_entity)
            raise ValueNotFound

        raw_today = _as_price_list(_attribute(entsoe, "prices_today"))
        if raw_today is None:
            _LOGGER.debug(
                "No values for today in Entso-e entity %s ", self._entsoe_entity
            )
            raise ValueNotFound

        raw_tomorrow = _as_price_list(_attribute(entsoe, "prices_tomorrow"))
        if (
            raw_tomorrow is None
            or len(raw_tomorrow) < INTERNAL_CHEAPEST_HOURS_MINIMUM_VALID_SLOTS
        ):
            _LOGGER.debug(
                "Not enough values for tomorrow in Entso-e entity %s (probably prices not yet published) ",
                self._entsoe_entity,
            )
            raise ValueNotFound

        return self._to_prices(
            raw_today,
            raw_tomorrow,
            requested_mtu,
            HourPriceType.ENTSOE,
            "Entso-e integration",
        )

    def _update_from_stromligning(self, requested_mtu: int = 60) -> Prices:
        """Update from Strømligning integration.

        Strømligning provides energy prices for Danish users including
        spot price, transport tariffs, system tariffs, and VAT.
        Depending on the Strømligning configuration, data can be provided
        in either 60-minute or 15-minute intervals.

        Today prices come from the main sensor entity (e.g.,
        sensor.stromligning_current_price_vat) via the 'prices' attribute.
        Tomorrow prices come from a separate binary_sensor entity (e.g.,
        binary_sensor.stromligning_tomorrow_available_vat) via the 'prices'
        attribute, only available when the entity state is 'on'.

        Data format: list of dicts with keys 'price', 'start', 'end' where
        start/end are ISO 8601 datetime strings.
        """
        stromligning = self._get_state(self._stromligning_entity)
        if stromligning is None:
            _LOGGER.debug(
                "Got empty data from Strømligning entity %s",
                self._stromligning_entity,
            )
            raise ValueNotFound

        raw_today = _as_price_list(_attribute(stromligning, "prices"))
        if not raw_today:
            _LOGGER.debug(
                "No price values for today in Strømligning entity %s",
                self._stromligning_entity,
            )
            raise ValueNotFound

        # Validate that today data is actually for today
        first_start = from_str_to_datetime(raw_today[0].get("start"))
        if first_start and first_start.date() != dt_util.start_of_local_day().date():
            _LOGGER.debug("Strømligning provided old data: Ignore")
            raise ValueNotFound

        # Get tomorrow prices from the separate tomorrow entity
        raw_tomorrow: RawPrices = []
        tomorrow_entity = self._get_state(self._stromligning_tomorrow_entity)
        if tomorrow_entity is not None and tomorrow_entity.state == "on":
            tomorrow_prices = _as_price_list(_attribute(tomorrow_entity, "prices"))
            if (
                tomorrow_prices is not None
                and len(tomorrow_prices) >= INTERNAL_CHEAPEST_HOURS_MINIMUM_VALID_SLOTS
            ):
                raw_tomorrow = tomorrow_prices

        if len(raw_tomorrow) == 0:
            _LOGGER.debug(
                "No values for tomorrow in Strømligning (prices not yet published)"
            )
            raise ValueNotFound

        return self._to_prices(
            raw_today,
            raw_tomorrow,
            requested_mtu,
            HourPriceType.STROMLIGNING,
            "Strømligning integration",
        )

    async def _update_from_nordpool_official(self, requested_mtu: int = 60) -> Prices:
        # Depending on the timezone, today data might have more or less values required for today.
        # Therefore we need to fetch yesterday, today and tomorrow to be sure we have all values
        def service_data(day: datetime) -> dict[str, str | None]:
            """Return service data for nord pool official service call."""
            data: dict[str, str | None] = {
                "config_entry": self._nordpool_official_config_entry,
                "date": day.strftime("%Y-%m-%d"),
                "resolution": str(self._mtu),
            }
            if self._area:
                data["areas"] = self._area
            return data

        async def fetch(day: datetime) -> ServiceResponse:
            return await self.hass.services.async_call(
                domain="nordpool",
                service="get_price_indices_for_date",
                service_data=service_data(day),
                return_response=True,
                blocking=True,
            )

        now = dt_util.now()
        yesterday_data = await fetch(now + timedelta(days=-1))
        today_data = await fetch(now)
        try:
            # Get data for tomorrow if present
            tomorrow_data = await fetch(now + timedelta(days=1))
        except Exception as e:  # noqa: BLE001
            # If not present, log this and return empty list
            _LOGGER.debug("Could not fetch tomorrow's prices: %s", e)
            tomorrow_data = None

        # Combine all periods into a single list
        combined = (
            _first_area_prices(yesterday_data)
            + _first_area_prices(today_data)
            + _first_area_prices(tomorrow_data)
        )

        # Use local-midnight boundaries for filtering to correctly handle DST
        # transitions. On spring-forward days, the last UTC entries of the 23-hour
        # day convert to the following local day, so date-equality checks would
        # incorrectly exclude them.
        midnight_today = dt_util.start_of_local_day()
        midnight_tomorrow = midnight_today + timedelta(days=1)
        midnight_day_after = midnight_today + timedelta(days=2)

        def in_range(item: Mapping[str, object], start: datetime, end: datetime) -> bool:
            item_start = from_str_to_datetime(item.get("start"))
            return (
                item_start is not None
                and start <= dt_util.as_local(item_start) < end
            )

        today_prices = [
            item for item in combined if in_range(item, midnight_today, midnight_tomorrow)
        ]
        tomorrow_prices = [
            item
            for item in combined
            if in_range(item, midnight_tomorrow, midnight_day_after)
        ]

        today, tomorrow, active_mtu = self._to_prices(
            today_prices,
            tomorrow_prices,
            requested_mtu,
            HourPriceType.NORDPOOL_OFFICIAL,
            "nord pool official integration",
            check_mtu=False,
        )
        if len(today) < INTERNAL_CHEAPEST_HOURS_MINIMUM_VALID_SLOTS:
            raise ValueNotFound

        if len(tomorrow) < INTERNAL_CHEAPEST_HOURS_MINIMUM_VALID_SLOTS:
            _LOGGER.debug(
                "Tomorrow's prices are not yet available. "
                "Calculations will proceed using today's data only."
            )

        self._check_mtu(active_mtu, "nord pool official integration")
        return (today, tomorrow, active_mtu)

    def _to_prices(
        self,
        raw_today: RawPrices,
        raw_tomorrow: RawPrices,
        requested_mtu: int,
        price_type: HourPriceType,
        source_name: str,
        check_mtu: bool = True,
    ) -> Prices:
        """Convert raw price data to HourPrice lists in the requested resolution."""
        active_mtu = 60
        if self._is_15min_period_in_use(raw_today):
            if requested_mtu == 60:
                raw_today = combine_to_hourly(raw_today, price_type)
            else:
                active_mtu = 15
        if self._is_15min_period_in_use(raw_tomorrow) and requested_mtu == 60:
            raw_tomorrow = combine_to_hourly(raw_tomorrow, price_type)

        today = [
            HourPrice.from_dict(item, mtu=active_mtu, type=price_type)
            for item in raw_today
        ]
        tomorrow = [
            HourPrice.from_dict(item, mtu=active_mtu, type=price_type)
            for item in raw_tomorrow
        ]
        if check_mtu:
            self._check_mtu(active_mtu, source_name)
        return (today, tomorrow, active_mtu)

    def _check_mtu(self, active_mtu: int, source_name: str) -> None:
        if active_mtu != self._mtu:
            raise SystemConfigurationError(
                f"MTU value {self._mtu} does not match the actual data MTU {active_mtu} used by {source_name}. Please correct the configuration"
            )

    def _is_failsafe(self) -> bool:
        if self._is_expired() is False:
            return False  # Data not expired yet.

        if failsafe := self._data.get("failsafe"):
            start = from_str_to_time(failsafe.get("start"))
            end = from_str_to_time(failsafe.get("end"))
            if start is None or end is None:
                return False
            failsafe_on = time_in_between(dt_util.now().time(), start, end)
            _LOGGER.debug("Running on failsafe: %s", failsafe_on)
            return failsafe_on

        return False

    def _construct_data_attributes(self) -> dict[str, object]:
        # Make some manipulation of the data stucture returned to the user
        attributes: dict[str, object] = dict(self._data)

        # Move extra data from 'extra' to root
        if extras := self._data.get("extra"):
            attributes["max_price"] = extras.get("max_price")
            attributes["min_price"] = extras.get("min_price")
            attributes["mean_price"] = extras.get("mean_price")
            del attributes["extra"]
        return attributes

    def _construct_static_attributes(self) -> dict[str, object]:
        attrs: dict[str, object] = {
            "first_hour": self._first_hour,
            "last_hour": self._last_hour,
            "starting_today": self._starting_today,
            "number_of_slots": self._number_of_slots,
            "failsafe_starting_hour": self._failsafe_starting_hour,
            "is_sequential": self._sequential,
            "failsafe_active": self._is_failsafe(),
            "inversed": self._inversed,
            "unique_id": self._unique_id,
        }

        if self._price_limit is not None:
            attrs["price_limit"] = self._price_limit
        if trigger_time := self._trigger_time:
            attrs["trigger_time"] = trigger_time
        if trigger_hour := self._trigger_hour:
            attrs["trigger_hour"] = trigger_hour
        if self._add_flexible:
            max_slots, flexible_price_limit, max_price_delta = self._flexible_config()
            if max_slots is not None:
                attrs["max_number_of_slots"] = max_slots
            if flexible_price_limit is not None:
                attrs["flexible_price_limit"] = flexible_price_limit
            if max_price_delta is not None:
                attrs["max_price_delta"] = max_price_delta
        if min_seq_slots := self._min_seq_slots:
            attrs["min_seq_slots"] = min_seq_slots
        if number_of_blocks := self._number_of_blocks:
            attrs["number_of_blocks"] = number_of_blocks

        return attrs

    def _flexible_config(
        self,
    ) -> tuple[NumberOrEntity | None, NumberOrEntity | None, NumberOrEntity | None]:
        """Return (max slots, flexible price limit, max price delta) of add_flexible."""
        add_flexible = self._add_flexible
        max_slots = add_flexible.get(CONF_MAX_NUMBER_OF_SLOTS_ENTITY) or add_flexible.get(
            CONF_MAX_NUMBER_OF_SLOTS
        )
        flexible_price_limit = add_flexible.get(
            CONF_PRICE_LIMIT_ENTITY
        ) or add_flexible.get(CONF_PRICE_LIMIT)
        return (max_slots, flexible_price_limit, add_flexible.get(CONF_MAX_PRICE_DELTA))

    def _update_entity_variables(self) -> None:
        if number_of_hours := self._number_of_hours:
            hours = self._int_from_entity(number_of_hours)
            # 15min mtu is 4 times more granular than 60min
            self._data["active_number_of_slots"] = (
                hours * 4 if hours is not None and self._mtu == 15 else hours
            )
        else:
            self._data["active_number_of_slots"] = self._int_from_entity(
                self._number_of_slots
            )
        if trigger_hour := self._trigger_hour:
            self._data["active_trigger_hour"] = self._int_from_entity(trigger_hour)
        if self._price_limit is not None:
            self._data["active_price_limit"] = self._float_from_entity(
                self._price_limit
            )

        if self._add_flexible:
            max_slots, flexible_price_limit, max_price_delta = self._flexible_config()
            self._data["active_max_number_of_slots"] = self._int_from_entity(max_slots)
            self._data["active_flexible_price_limit"] = self._float_from_entity(
                flexible_price_limit
            )
            self._data["active_max_price_delta"] = self._float_from_entity(
                max_price_delta
            )
        if min_seq_slots := self._min_seq_slots:
            self._data["active_min_seq_slots"] = self._int_from_entity(min_seq_slots)

        if number_of_blocks := self._number_of_blocks:
            self._data["active_number_of_blocks"] = self._int_from_entity(
                number_of_blocks
            )

    def _entity_state_value(self, entity_id: str) -> str:
        """Return the state of a helper entity, raising if it is not usable."""
        state = self.hass.states.get(entity_id)
        value = state.state if state is not None else None
        if value is None or value in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.error("Could not get entity state for %s", entity_id)
            raise InvalidEntityState
        return value

    def _float_from_entity(self, entity_id: NumberOrEntity | None) -> float | None:
        """Get float value from another entity."""
        if entity_id is None:
            return None

        if isinstance(entity_id, (int, float)):
            # Whole numbers in YAML (e.g. 20 instead of 20.0) arrive as int
            return float(entity_id)

        value = self._entity_state_value(entity_id)
        try:
            return float(value)
        except ValueError as err:
            _LOGGER.error(
                "Entity %s has non-numeric state %r: %s", entity_id, value, err
            )
            raise InvalidEntityState from err

    def _int_from_entity(self, entity_id: NumberOrEntity | None) -> int | None:
        """Get int value from another entity."""
        if entity_id is None:
            return None
        if isinstance(entity_id, int):
            return entity_id
        if isinstance(entity_id, float):
            return int(entity_id)

        value = self._entity_state_value(entity_id)
        try:
            return int(float(value))
        except ValueError as err:
            _LOGGER.error(
                "Entity %s has non-numeric state %r: %s", entity_id, value, err
            )
            raise InvalidEntityState from err

    def _is_15min_period_in_use(self, data: RawPrices) -> bool:
        """Check if data mtu is 15min."""
        return len(data) > 40

    def _apply_price_modifications(
        self, hour_prices: list[HourPrice], template: Template
    ) -> list[HourPrice]:
        """Apply price modifications to each HourPrice using a Jinja2 template.

        Args:
            self: self reference
            hour_prices: List of HourPrice objects.
            template: Jinja2 template. Variables: 'price', 'time' (datetime).

        Returns:
            List of HourPrice objects with updated price.
        """
        updated: list[HourPrice] = []
        for hp in hour_prices:
            # Use start time for 'time' variable
            context = {"price": hp.value, "time": dt_util.as_local(hp.start)}
            try:
                new_price = as_float(cast(object, template.async_render(context)))
            except Exception as ex:  # noqa: BLE001
                _LOGGER.error("Failed to render price modifications template: %s", ex)
                new_price = hp.value
            # Create a new HourPrice object with updated price
            updated.append(
                HourPrice(start=hp.start, end=hp.end, value=new_price, type=hp.type)
            )
        return updated


def _attribute(state: State, key: str) -> object:
    """Return a state attribute without leaking Any into the caller."""
    return cast(object, state.attributes.get(key))


def _as_price_list(value: object) -> RawPrices | None:
    """Return the price items of an attribute, or None if it is not a list."""
    if not isinstance(value, list):
        return None
    return [
        cast(Mapping[str, object], item)
        for item in cast(list[object], value)
        if isinstance(item, Mapping)
    ]


def _first_area_prices(response: ServiceResponse) -> RawPrices:
    """Return the prices of the first area in a nord pool service response."""
    if not response:
        return []
    return _as_price_list(cast(object, next(iter(response.values()), None))) or []


# TODO: Refactor this to use HourPrice model
def combine_to_hourly(data: RawPrices, type: HourPriceType) -> RawPrices:  # noqa: A002
    """Combine a list of 15-minute price data into hourly averages.

    Args:
        data: A list of dictionaries, where each dictionary has 'start', 'end'
              (ISO 8601 strings), and 'price' (float).
        type: The type of HourPrice (e.g., NORDPOOL, NORDPOOL_OFFICIAL).

    Returns:
        A list of dictionaries, each representing an hour with 'start', 'end',
        and 'price' (hourly average).

    """
    start_key = "time" if type == HourPriceType.ENTSOE else "start"
    price_key = "value" if type == HourPriceType.NORDPOOL else "price"

    hourly_data: RawPrices = []
    i = 0
    # Ensure we have at least 4 items for a full hour
    while i + 3 < len(data):
        # Check if the current item's start minute is :00
        start_dt = from_str_to_datetime(data[i][start_key])
        if start_dt is None or start_dt.minute != 0:
            i += 1  # Move to next 15-min block if not starting at :00
            continue

        # Collect the next four 15-minute blocks and average their price
        current_block = data[i : i + 4]
        average_price = round(
            sum(as_float(item[price_key]) for item in current_block) / 4, 2
        )
        hourly_start = current_block[0][start_key]

        if type == HourPriceType.ENTSOE:
            hourly_data.append({"time": hourly_start, "price": average_price})
        else:  # NORDPOOL (value), NORDPOOL_OFFICIAL and STROMLIGNING (price)
            hourly_data.append(
                {
                    "start": hourly_start,
                    "end": current_block[-1]["end"],
                    price_key: average_price,
                }
            )

        i += 4  # Move to the next hour block
    return hourly_data

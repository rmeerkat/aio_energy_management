"""Excess Solar Manager.

Architecture
------------
One ``ExcessSolarBinarySensor`` is created per configured ``power_device``.
The sensor's state is **on** when the manager decides that excess solar should
be pushed into that device, and **off** otherwise.

The manager does NOT directly control any device.  Instead, users create HA
automations that listen to these binary sensors and turn actual devices on/off
accordingly.

Short-cycling protection, schedule awareness, enabled checks, and priority
queue logic all live in this module.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Required, TypedDict, cast

from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from ..const import (
    CONF_CONSUMPTION,
    CONF_GRID_POWER_SENSOR,
    CONF_NAME,
)
from .binary_sensor import ExcessSolarBinarySensor

_LOGGER = logging.getLogger(__name__)


class ExcessSolarDeviceConfig(TypedDict, total=False):
    """Validated configuration for one managed power device."""

    name: Required[str]
    consumption: Required[int | str]
    consumption_entity: str
    priority: int
    is_on_schedule: str
    minimum_on_time: int
    minimum_off_time: int


class ExcessSolarConfig(TypedDict, total=False):
    """Validated global Excess Solar configuration."""

    sensor: Required[str]
    power_devices: Required[list[ExcessSolarDeviceConfig]]
    buffer: int
    name: str
    unique_id: str
    entry_type: str


def validate_excess_solar_config(data: object) -> ExcessSolarConfig:
    """Check the shape of validated config-flow or YAML data."""
    if not isinstance(data, dict):
        raise ValueError("Excess Solar configuration must be a mapping")

    raw_config = cast(dict[str, object], data)
    if not isinstance(raw_config.get(CONF_GRID_POWER_SENSOR), str):
        raise ValueError("Excess Solar requires a grid power sensor")

    raw_devices = raw_config.get("power_devices")
    if not isinstance(raw_devices, list):
        raise ValueError("Excess Solar requires a list of power devices")

    for raw_device in cast(list[object], raw_devices):
        if not isinstance(raw_device, dict):
            raise ValueError("Each Excess Solar device must be a mapping")
        device = cast(dict[str, object], raw_device)
        if not isinstance(device.get(CONF_NAME), str):
            raise ValueError("Each Excess Solar device requires a name")
        if not isinstance(device.get(CONF_CONSUMPTION), (int, str)):
            raise ValueError("Each Excess Solar device requires consumption")

    return cast(ExcessSolarConfig, cast(object, raw_config))

# Default delays
DEFAULT_ON_OFF_DEBOUNCE = 30  # seconds: debounce solar power transients


class ExcessSolarManager:
    """Manages excess solar distribution across registered binary sensors.

    Subscribes to grid power sensor state changes.  On each update (debounced):
    - If excess solar available (grid_power < -buffer) → activates the next
      eligible sensor in priority order.
    - If importing (grid_power > +buffer) → deactivates the lowest-priority
      currently active sensor.
    """

    _hass: HomeAssistant
    _grid_sensor: str
    _buffer: int
    _sensors: list[ExcessSolarBinarySensor]
    _cancel_listener: Callable[[], None] | None
    _pending_handle: Callable[[], None] | None
    _last_grid_power: float | None
    _enabled: bool

    def __init__(
        self,
        hass: HomeAssistant,
        grid_sensor: str,
        sensors: list[ExcessSolarBinarySensor],
        buffer: int = 0,
    ) -> None:
        """Initialise the manager."""
        self._hass = hass
        self._grid_sensor = grid_sensor
        self._buffer = buffer
        self._sensors = sensors
        self.sort_sensors()
        self._cancel_listener = None
        self._pending_handle = None
        self._last_grid_power = None  # most recent reading
        self._enabled = True  # master switch state

    @property
    def enabled(self) -> bool:
        """Return True if the manager is enabled by the master switch."""
        return self._enabled

    @property
    def sensors(self) -> list[ExcessSolarBinarySensor]:
        """Return the list of sensors."""
        return self._sensors

    @sensors.setter
    def sensors(self, value: list[ExcessSolarBinarySensor]) -> None:
        """Set the list of sensors."""
        self._sensors = value

    def sort_sensors(self) -> None:
        """Sort sensors by priority (lower number = higher priority)."""
        self._sensors.sort(key=lambda s: s.priority)
        _LOGGER.debug(
            "Sensors sorted by priority: %s",
            [(s.name, s.priority) for s in self._sensors],
        )

    @callback
    def on_priority_changed(self) -> None:
        """Handle priority change - re-sort sensors."""
        _LOGGER.info("Priority changed, re-sorting sensors")
        self.sort_sensors()

    async def async_start(self) -> None:
        """Subscribe to grid sensor state changes."""
        _LOGGER.debug(
            "ExcessSolarManager starting – monitoring %s, %d device(s), buffer=%dW",
            self._grid_sensor,
            len(self._sensors),
            self._buffer,
        )
        self._cancel_listener = async_track_state_change_event(
            self._hass,
            [self._grid_sensor],
            self._async_grid_sensor_changed,
        )

    async def async_stop(self) -> None:
        """Stop listening and cancel pending debounce."""
        if self._cancel_listener is not None:
            self._cancel_listener()
            self._cancel_listener = None
        if self._pending_handle is not None:
            self._pending_handle()  # async_call_later returns a cancel callable
            self._pending_handle = None
        _LOGGER.debug("ExcessSolarManager stopped")

    def async_enable(self) -> None:
        """Enable the manager (master switch on)."""
        self._enabled = True
        _LOGGER.info("ExcessSolarManager enabled")

    async def async_disable(self) -> None:
        """Disable the manager (master switch off) and deactivate all sensors."""
        self._enabled = False
        _LOGGER.info("ExcessSolarManager disabled – deactivating all sensors")
        for sensor in self._sensors:
            if sensor.is_on:
                sensor.deactivate()

    @callback
    def _async_grid_sensor_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle grid power sensor state change (debounced)."""
        new_state: State | None = event.data.get("new_state")
        if new_state is None:
            return
        state_value = new_state.state
        if state_value in ("unknown", "unavailable"):
            return
        try:
            grid_power = float(state_value)
        except ValueError:
            _LOGGER.warning(
                "Cannot parse grid power from %s: '%s'",
                self._grid_sensor,
                state_value,
            )
            return

        _LOGGER.debug("Grid power: %.1fW (buffer ±%dW)", grid_power, self._buffer)

        # Always store the latest reading so the evaluation uses fresh data
        self._last_grid_power = grid_power

        # Leading throttle: if a timer is already scheduled, let it run.
        # The timer will pick up _last_grid_power when it fires, so we don't
        # need to cancel/reschedule on every sensor update.  This ensures
        # _async_evaluate fires reliably even when the sensor updates every
        # few seconds (which would cause a trailing-edge debounce to never fire).
        if self._pending_handle is not None:
            return

        @callback
        def _fire(_now: datetime) -> None:
            self._pending_handle = None
            if self._last_grid_power is not None:
                self._hass.async_create_task(
                    self._async_evaluate(self._last_grid_power)
                )

        self._pending_handle = async_call_later(
            self._hass, DEFAULT_ON_OFF_DEBOUNCE, _fire
        )

    async def _async_evaluate(self, grid_power: float) -> None:
        """Evaluate grid power and update binary sensor states."""
        if not self._enabled:
            _LOGGER.debug("ExcessSolarManager is disabled – skipping evaluation")
            return
        available_solar = -grid_power  # positive → exporting (solar excess)

        _LOGGER.debug(
            "Evaluate: grid=%.1fW, available=%.1fW, buffer=%dW",
            grid_power,
            available_solar,
            self._buffer,
        )

        if available_solar > self._buffer:
            await self._activate_next(available_solar)
        elif available_solar < -self._buffer:
            await self._deactivate_last()
        else:
            _LOGGER.debug(
                "Grid power %.1fW within buffer ±%dW – no action",
                grid_power,
                self._buffer,
            )

    async def _activate_next(self, available_solar: float) -> None:
        """Activate the highest-priority eligible sensor.

        If the best candidate does not fit within the current solar surplus,
        check whether deactivating lower-priority active devices would free
        enough power for a swap.  Only the minimum number of lower-priority
        devices needed are deactivated.
        """
        for sensor in self._sensors:
            # Already active → skip
            if sensor.is_on:
                continue
            # Schedule or not enabled guard
            if sensor.is_on_schedule():
                _LOGGER.debug("%s is on schedule, skipping", sensor.name)
                continue
            if not sensor.is_enabled():
                _LOGGER.debug("%s is disabled, skipping", sensor.name)
                continue
            # Short-cycle guard
            if not sensor.can_turn_on():
                _LOGGER.debug("%s is not allowed to turn on, skipping", sensor.name)      
                continue

            consumption = sensor.get_expected_consumption()
            if consumption == 0:
                # Consumption failed, continue to next sensor
                continue

            # Direct fit: enough solar without touching anything else
            if available_solar >= (consumption - self._buffer):
                _LOGGER.info(
                    "Excess solar %.1fW: activating sensor for %s"
                    " (priority %d, %.1fW)",
                    available_solar,
                    sensor.device_entity_id,
                    sensor.priority,
                    consumption,
                )
                sensor.activate()
                break

            # Swap check: deactivate lower-priority devices to free power
            swap_candidates = self._find_swap_candidates(
                sensor, available_solar, consumption
            )
            if swap_candidates:
                freed = sum(s.get_consumption() for s in swap_candidates)
                _LOGGER.info(
                    "Swap: freeing %.1fW from %d lower-priority device(s) to"
                    " activate %s (priority %d, %.1fW)",
                    freed,
                    len(swap_candidates),
                    sensor.device_entity_id,
                    sensor.priority,
                    consumption,
                )
                for s in swap_candidates:
                    s.deactivate()
                sensor.activate()
                break

            _LOGGER.debug(
                "Not enough solar (%.1fW) for %s (%.1fW) and no valid swap",
                available_solar,
                sensor.name,
                consumption,
            )

    def _find_swap_candidates(
        self,
        candidate: ExcessSolarBinarySensor,
        available_solar: float,
        consumption: float,
    ) -> list[ExcessSolarBinarySensor]:
        """Return the minimum set of lower-priority sensors to deactivate for a swap.

        Iterates active sensors from lowest priority upward, accumulating freed
        power until the candidate's consumption can be covered.  Returns an
        empty list when a valid swap is not possible (e.g. guarded by
        ``minimum_on_time`` or ``is_on_schedule``).
        """
        # Collect eligible lower-priority active sensors, lowest priority first
        lower_active = [
            s
            for s in reversed(self._sensors)
            if s.is_on
            and s.priority > candidate.priority
            and not s.is_on_schedule()
            and s.can_turn_off()
        ]

        net_available = available_solar
        to_deactivate: list[ExcessSolarBinarySensor] = []
        for s in lower_active:
            net_available += s.get_consumption()
            to_deactivate.append(s)
            if net_available >= (consumption - self._buffer):
                return to_deactivate

        return []  # not enough even with all lower-priority sensors off

    async def _deactivate_last(self) -> None:
        """Deactivate the lowest-priority currently active sensor."""
        for sensor in reversed(self._sensors):
            if not sensor.is_on:
                continue
            # Don't interfere with schedule-controlled devices
            if sensor.is_on_schedule():
                _LOGGER.debug("%s is on schedule, not deactivating", sensor.name)
                continue
            # Minimum period guard
            if not sensor.can_turn_off():
                continue

            _LOGGER.info(
                "Grid importing: deactivating sensor for %s (priority %d)",
                sensor.device_entity_id,
                sensor.priority,
            )
            sensor.deactivate()
            break

    @property
    def diagnostic_info(self) -> dict[str, object]:
        """Return diagnostic snapshot."""
        return {
            "grid_sensor": self._grid_sensor,
            "buffer": self._buffer,
            "sensors": [
                {
                    "name": s.name,
                    "device_entity": s.device_entity_id,
                    "priority": s.priority,
                    "is_on": s.is_on,
                }
                for s in self._sensors
            ],
        }


__all__ = [
    "ExcessSolarConfig",
    "ExcessSolarDeviceConfig",
    "ExcessSolarManager",
    "validate_excess_solar_config",
]

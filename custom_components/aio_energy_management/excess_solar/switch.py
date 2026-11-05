"""Excess Solar switch entities.

Provides two switch types:
- ``ExcessSolarMasterSwitch``: one per excess-solar entry, enables/disables the
  entire manager.
- ``ExcessSolarDeviceEnabledSwitch``: one per configured power device, allows
  individual devices to be included or excluded from solar management.

Both switches use ``RestoreEntity`` so their state survives HA restarts.
"""

from __future__ import annotations

import logging
from typing import override, TYPE_CHECKING

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .manager import ExcessSolarManager

if TYPE_CHECKING:
    from ..entity import EntityDeviceInfo

_LOGGER = logging.getLogger(__name__)


class ExcessSolarMasterSwitch(RestoreEntity, SwitchEntity):
    """Master on/off switch for the Excess Solar manager.

    Turning this switch **off** immediately deactivates all managed binary
    sensors and prevents the manager from taking any further actions until
    the switch is turned **on** again.

    State is automatically restored from Home Assistant's last known state
    across reboots.
    """

    _attr_has_entity_name: bool = True
    _attr_device_info: EntityDeviceInfo

    _manager: ExcessSolarManager
    _attr_unique_id: str | None
    _attr_name: str | None
    _attr_icon: str | None
    _attr_is_on: bool | None

    def __init__(
        self,
        manager: ExcessSolarManager,
        unique_id: str,
        name: str,
        device_info: DeviceInfo | None = None,
    ) -> None:
        """Initialise the master switch."""
        self._manager = manager
        self._attr_unique_id = unique_id
        # With a device the master switch is its device's main entity.
        self._attr_name = None if device_info is not None else name
        self._attr_device_info = device_info
        self._attr_icon = "mdi:solar-power"
        self._attr_is_on = True  # enabled by default

    @override
    async def async_added_to_hass(self) -> None:
        """Restore state from the last known state on startup."""
        await super().async_added_to_hass()

        if last_state := await self.async_get_last_state():
            is_on = last_state.state == "on"
            if is_on:
                self._manager.async_enable()
            else:
                await self._manager.async_disable()
            _LOGGER.info(
                "Excess Solar master switch restored to %s",
                "ON" if is_on else "OFF",
            )
        else:
            self._manager.async_enable()
            _LOGGER.info(
                "Excess Solar master switch initialized to ON (no previous state)"
            )

    @property
    @override
    def is_on(self) -> bool:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return True if the manager is enabled."""
        return self._manager.enabled

    @override
    async def async_turn_on(self, **_kwargs: object) -> None:
        """Enable the excess solar manager."""
        self._manager.async_enable()
        self.async_write_ha_state()
        _LOGGER.info("Excess Solar master switch turned ON")

    @override
    async def async_turn_off(self, **_kwargs: object) -> None:
        """Disable the excess solar manager and deactivate all sensors."""
        await self._manager.async_disable()
        self.async_write_ha_state()
        _LOGGER.info("Excess Solar master switch turned OFF")


class ExcessSolarDeviceEnabledSwitch(RestoreEntity, SwitchEntity):
    """Per-device enabled/disabled switch for excess solar management.

    When turned **off**, the associated power device is excluded from solar
    excess management until the switch is turned **on** again.

    State is automatically restored from Home Assistant's last known state
    across reboots.
    """

    _attr_has_entity_name: bool = True
    _attr_device_info: EntityDeviceInfo

    _attr_unique_id: str | None
    _attr_name: str | None
    _attr_icon: str | None
    _attr_is_on: bool | None

    def __init__(
        self, unique_id: str, name: str, device_info: DeviceInfo | None = None
    ) -> None:
        """Initialise the device enabled switch."""
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._attr_device_info = device_info
        self._attr_icon = "mdi:solar-power-variant"
        self._attr_is_on = True  # enabled by default

    @override
    async def async_added_to_hass(self) -> None:
        """Restore previous state on startup."""
        await super().async_added_to_hass()

        if last_state := await self.async_get_last_state():
            self._attr_is_on = last_state.state == "on"
            _LOGGER.debug(
                "Device enabled switch '%s' restored to %s",
                self.name,
                "ON" if self._attr_is_on else "OFF",
            )

    @override
    async def async_turn_on(self, **_kwargs: object) -> None:
        """Enable this device for solar management."""
        self._attr_is_on = True
        self.async_write_ha_state()
        _LOGGER.debug("Device enabled switch '%s' turned ON", self.name)

    @override
    async def async_turn_off(self, **_kwargs: object) -> None:
        """Disable this device from solar management."""
        self._attr_is_on = False
        self.async_write_ha_state()
        _LOGGER.debug("Device enabled switch '%s' turned OFF", self.name)

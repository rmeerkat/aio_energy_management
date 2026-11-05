"""Shared entity helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.helpers.device_registry import ChildDeviceInfo

    # The type of Entity._attr_device_info; ChildDeviceInfo only exists in
    # newer Home Assistant versions, so it is imported for type checking only.
    type EntityDeviceInfo = DeviceInfo | ChildDeviceInfo | None


def entry_device_info(entry_id: str, name: str) -> DeviceInfo:
    """Return the service device that groups the entities of a config entry.

    Entities use has_entity_name, so their name is relative to this device.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=name,
        entry_type=DeviceEntryType.SERVICE,
        manufacturer="AIO Energy Management",
    )

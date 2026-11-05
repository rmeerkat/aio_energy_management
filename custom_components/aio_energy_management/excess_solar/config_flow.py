"""Excess solar config flow handlers and helpers."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import cast

import probatio as vol

from homeassistant.config_entries import ConfigFlowResult
import homeassistant.helpers.config_validation as cv

from ..const import (
    CONF_BUFFER,
    CONF_CONSUMPTION,
    CONF_ENTITY_EXCESS_SOLAR,
    CONF_GRID_POWER_SENSOR,
    CONF_IS_ON_SCHEDULE,
    CONF_MINIMUM_OFF_TIME,
    CONF_MINIMUM_ON_TIME,
    CONF_NAME,
    CONF_POWER_DEVICES,
    CONF_PRIORITY,
    CONF_UNIQUE_ID,
)
from ..flow_types import FlowInput, FlowMixinBase, SchemaDict
from ..selectors import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

_LOGGER = logging.getLogger(__name__)

# UI-only config keys (not stored in config entry data)
CONF_CONSUMPTION_ENTITY = "consumption_entity"
CONF_ADD_ANOTHER = "add_another"
CONF_DEVICES_ACTION = "devices_action"
CONF_DEVICES_TO_REMOVE = "devices_to_remove"

# Options-flow action values
ACTION_EDIT_SETTINGS = "edit_settings"
ACTION_ADD_DEVICE = "add_device"
ACTION_REMOVE_DEVICES = "remove_devices"


def _to_int(value: object, default: int = 0) -> int:
    """Return a numeric form value (number or numeric string) as int."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _device_list(value: object) -> list[FlowInput]:
    """Return the power devices stored in config data."""
    if not isinstance(value, list):
        return []
    return [
        cast(FlowInput, device)
        for device in cast(list[object], value)
        if isinstance(device, dict)
    ]


def _device_name(device: Mapping[str, object]) -> str:
    return str(device.get(CONF_NAME, ""))


def _get_excess_solar_global_schema(
    user_input: FlowInput | None = None,
) -> vol.Schema:
    """Get global excess solar configuration schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME,
                default=(user_input.get(CONF_NAME) if user_input else "Excess Solar"),
            ): cv.string,
            vol.Required(
                CONF_GRID_POWER_SENSOR,
                description={
                    "suggested_value": (
                        user_input.get(CONF_GRID_POWER_SENSOR) if user_input else None
                    )
                },
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_BUFFER,
                default=(user_input.get(CONF_BUFFER, 0) if user_input else 0),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=10000,
                    step=10,
                    unit_of_measurement="W",
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _get_excess_solar_edit_settings_schema(
    entry_data: FlowInput,
) -> vol.Schema:
    """Get global excess solar edit settings schema prefilled from config entry."""
    return vol.Schema(
        {
            vol.Required(
                CONF_GRID_POWER_SENSOR,
                description={"suggested_value": entry_data.get(CONF_GRID_POWER_SENSOR)},
            ): EntitySelector(EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_BUFFER,
                default=_to_int(entry_data.get(CONF_BUFFER)),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=10000,
                    step=10,
                    unit_of_measurement="W",
                    mode=NumberSelectorMode.BOX,
                )
            ),
        }
    )


def _build_device_schema_defaults(
    user_input: FlowInput | None,
) -> FlowInput:
    """Extract form defaults for the device schema from user_input or empty."""
    if not user_input:
        return {
            "name": "",
            "consumption": 0,
            "consumption_entity": None,
            "priority": 100,
            "is_on_schedule": None,
            "minimum_on_time": 0,
            "minimum_off_time": None,
        }

    # When consumption is an entity string from a previous submission
    consumption = user_input.get(CONF_CONSUMPTION, 0)
    consumption_entity = user_input.get(CONF_CONSUMPTION_ENTITY)
    if isinstance(consumption, str) and not consumption.lstrip("-").isdigit():
        consumption_entity = consumption
        consumption = 0

    return {
        "name": user_input.get(CONF_NAME, ""),
        "consumption": _to_int(consumption) if consumption else 0,
        "consumption_entity": consumption_entity,
        "priority": _to_int(user_input.get(CONF_PRIORITY, 100), 100),
        "is_on_schedule": user_input.get(CONF_IS_ON_SCHEDULE),
        "minimum_on_time": _to_int(user_input.get(CONF_MINIMUM_ON_TIME, 0)),
        "minimum_off_time": user_input.get(CONF_MINIMUM_OFF_TIME),
    }


def _get_excess_solar_device_schema(
    user_input: FlowInput | None = None,
) -> vol.Schema:
    """Get power device configuration schema."""
    d = _build_device_schema_defaults(user_input)

    schema_dict: SchemaDict = {
        vol.Required(CONF_NAME, default=d["name"]): cv.string,
        vol.Required(
            CONF_CONSUMPTION,
            default=d["consumption"],
        ): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=100000,
                step=10,
                unit_of_measurement="W",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_CONSUMPTION_ENTITY,
            description={"suggested_value": d["consumption_entity"]},
        ): EntitySelector(EntitySelectorConfig(domain="sensor")),
        vol.Optional(
            CONF_PRIORITY,
            default=d["priority"],
        ): NumberSelector(
            NumberSelectorConfig(
                min=1,
                max=999,
                step=1,
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_IS_ON_SCHEDULE,
            description={"suggested_value": d["is_on_schedule"]},
        ): EntitySelector(
            EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
        ),
        vol.Optional(
            CONF_MINIMUM_ON_TIME,
            default=d["minimum_on_time"],
        ): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=1440,
                step=1,
                unit_of_measurement="min",
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_MINIMUM_OFF_TIME,
            description={"suggested_value": d["minimum_off_time"]},
        ): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=1440,
                step=1,
                unit_of_measurement="min",
                mode=NumberSelectorMode.BOX,
            )
        ),
    }

    return vol.Schema(schema_dict)


def _process_device_input(
    user_input: FlowInput,
) -> tuple[FlowInput, dict[str, str]]:
    """Validate and clean device user input.

    Returns:
        Tuple of (cleaned_device_dict, errors_dict).
    """
    errors: dict[str, str] = {}
    device: FlowInput = {}

    name = user_input.get(CONF_NAME, "")
    device[CONF_NAME] = name.strip() if isinstance(name, str) else ""
    if not device[CONF_NAME]:
        errors[CONF_NAME] = "device_name_required"
        return device, errors

    consumption_watts = user_input.get(CONF_CONSUMPTION, 0)
    consumption_entity = user_input.get(CONF_CONSUMPTION_ENTITY)

    device[CONF_CONSUMPTION] = _to_int(consumption_watts) if consumption_watts else 0
    if consumption_entity:
        device[CONF_CONSUMPTION_ENTITY] = consumption_entity

    device[CONF_PRIORITY] = _to_int(user_input.get(CONF_PRIORITY, 100), 100)
    device[CONF_MINIMUM_ON_TIME] = _to_int(user_input.get(CONF_MINIMUM_ON_TIME, 0))

    if is_on_schedule := user_input.get(CONF_IS_ON_SCHEDULE):
        device[CONF_IS_ON_SCHEDULE] = is_on_schedule

    minimum_off_time = user_input.get(CONF_MINIMUM_OFF_TIME)
    if minimum_off_time is not None:
        device[CONF_MINIMUM_OFF_TIME] = _to_int(minimum_off_time)

    return device, errors


class ExcessSolarConfigFlowMixin(FlowMixinBase):
    """Mixin providing excess solar config flow steps.

    Works for both the initial config flow and the options flow.
    """

    def _power_devices(self) -> list[FlowInput]:
        """Return the devices being configured, stored in the flow's config data."""
        devices = _device_list(self._config_data.get(CONF_POWER_DEVICES))
        self._config_data[CONF_POWER_DEVICES] = devices
        return devices

    # ------------------------------------------------------------------
    # Initial config flow: global settings → device(s) → create entry
    # ------------------------------------------------------------------

    async def async_step_excess_solar_global(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Configure global excess solar settings (first step for new entries)."""
        if user_input is not None:
            user_input[CONF_BUFFER] = _to_int(user_input.get(CONF_BUFFER, 0))
            self._config_data.update(user_input)
            self._config_data[CONF_POWER_DEVICES] = []
            return await self.async_step_excess_solar_device()

        return self.async_show_form(
            step_id="excess_solar_global",
            data_schema=_get_excess_solar_global_schema(user_input),
        )

    async def async_step_excess_solar_device(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Configure a power device to manage with excess solar."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device, errors = _process_device_input(user_input)
            if not errors:
                self._power_devices().append(device)
                return await self.async_step_excess_solar_another_device()

        device_number = len(self._power_devices()) + 1
        return self.async_show_form(
            step_id="excess_solar_device",
            data_schema=_get_excess_solar_device_schema(user_input if errors else None),
            errors=errors,
            description_placeholders={"device_number": str(device_number)},
        )

    async def async_step_excess_solar_another_device(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Ask whether to add another device."""
        is_options_flow = self._options_entry() is not None

        if user_input is not None:
            if user_input.get(CONF_ADD_ANOTHER):
                return await self.async_step_excess_solar_device()
            if is_options_flow:
                return await self._async_finish_excess_solar_add_device()
            return await self._async_finish_excess_solar_new()

        devices = self._power_devices()
        device_names = ", ".join(_device_name(d) for d in devices)
        return self.async_show_form(
            step_id="excess_solar_another_device",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADD_ANOTHER, default=False): cv.boolean}
            ),
            description_placeholders={
                "device_count": str(len(devices)),
                "device_names": device_names,
            },
        )

    async def _async_finish_excess_solar_new(self) -> ConfigFlowResult:
        """Finalise a new excess solar config entry."""
        name = str(self._config_data[CONF_NAME])
        unique_id = name.lower().replace(" ", "_")
        self._config_data[CONF_UNIQUE_ID] = unique_id
        self._config_data["entry_type"] = CONF_ENTITY_EXCESS_SOLAR
        self._config_data.pop(CONF_MINIMUM_OFF_TIME, None)

        return await self._async_create_unique_entry(
            unique_id, name, self._config_data
        )

    # ------------------------------------------------------------------
    # Options flow: main menu → edit settings / add device / remove devices
    # ------------------------------------------------------------------

    async def async_step_excess_solar_menu(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Show main options menu for excess solar."""
        entry_data = self._entry_data()
        if user_input is not None:
            action = user_input.get(CONF_DEVICES_ACTION)
            if action == ACTION_EDIT_SETTINGS:
                return await self.async_step_excess_solar_edit_settings()
            if action == ACTION_ADD_DEVICE:
                # _config_data starts as a copy of the entry data, devices included.
                return await self.async_step_excess_solar_device()
            if action == ACTION_REMOVE_DEVICES:
                return await self.async_step_excess_solar_remove_devices()

        devices = _device_list(entry_data.get(CONF_POWER_DEVICES))
        return self.async_show_form(
            step_id="excess_solar_menu",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICES_ACTION): vol.In(
                        {
                            ACTION_EDIT_SETTINGS: "Edit global settings",
                            ACTION_ADD_DEVICE: "Add a device",
                            ACTION_REMOVE_DEVICES: "Remove device(s)",
                        }
                    )
                }
            ),
            description_placeholders={
                "device_count": str(len(devices)),
                "device_names": (", ".join(_device_name(d) for d in devices) or "none"),
            },
        )

    async def async_step_excess_solar_edit_settings(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Edit global excess solar settings (options flow)."""
        entry = self._require_options_entry()
        if user_input is not None:
            new_data = self._entry_data()
            new_data[CONF_GRID_POWER_SENSOR] = user_input[CONF_GRID_POWER_SENSOR]
            new_data[CONF_BUFFER] = _to_int(user_input.get(CONF_BUFFER, 0))
            new_data.pop(CONF_MINIMUM_OFF_TIME, None)

            self.hass.config_entries.async_update_entry(entry, data=new_data)
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="excess_solar_edit_settings",
            data_schema=_get_excess_solar_edit_settings_schema(self._entry_data()),
        )

    async def async_step_excess_solar_remove_devices(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Remove one or more devices from the options flow."""
        entry = self._require_options_entry()
        entry_data = self._entry_data()
        existing_devices = _device_list(entry_data.get(CONF_POWER_DEVICES))

        if not existing_devices:
            return self.async_abort(reason="no_devices_to_remove")

        if user_input is not None:
            selected = user_input.get(CONF_DEVICES_TO_REMOVE)
            names_to_remove = (
                {str(name) for name in cast(list[object], selected)}
                if isinstance(selected, list)
                else set[str]()
            )
            updated_devices = [
                d for d in existing_devices if _device_name(d) not in names_to_remove
            ]
            new_data = {**entry_data, CONF_POWER_DEVICES: updated_devices}
            new_data.pop(CONF_MINIMUM_OFF_TIME, None)
            self.hass.config_entries.async_update_entry(entry, data=new_data)
            return self.async_create_entry(title="", data={})

        device_options = [
            SelectOptionDict(value=_device_name(d), label=_device_name(d))
            for d in existing_devices
        ]
        return self.async_show_form(
            step_id="excess_solar_remove_devices",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICES_TO_REMOVE): SelectSelector(
                        SelectSelectorConfig(
                            options=device_options,
                            multiple=True,
                        )
                    )
                }
            ),
        )

    async def _async_finish_excess_solar_add_device(self) -> ConfigFlowResult:
        """Finalise adding a device in the options flow."""
        entry = self._require_options_entry()
        new_data = {**self._entry_data(), CONF_POWER_DEVICES: self._power_devices()}
        new_data.pop(CONF_MINIMUM_OFF_TIME, None)
        self.hass.config_entries.async_update_entry(entry, data=new_data)
        return self.async_create_entry(title="", data={})

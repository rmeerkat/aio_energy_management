"""Config flow for AIO Energy Management integration."""

from __future__ import annotations

import logging
from typing import override

import probatio as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback

from .cheapest_hours import ENTRY_TYPE_CHEAPEST_HOURS, CheapestHoursConfigFlowMixin
from .const import (
    CONF_DATA_PROVIDER_TYPE,
    CONF_ENABLE_CALENDAR,
    CONF_ENTITY_EXCESS_SOLAR,
    CONF_SEQUENTIAL,
    CONF_UNIQUE_ID,
    DOMAIN,
)
from .excess_solar.config_flow import ExcessSolarConfigFlowMixin
from .flow_types import FlowInput
from .selectors import (
    BooleanSelector,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)

_LOGGER = logging.getLogger(__name__)

CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_GLOBAL_SETTINGS = "global_settings"


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


# Configuration flow
# HA's ConfigFlow narrows FlowHandler.async_create_entry (title is required);
# the mixins see the FlowHandler signature, which pyright reports as a conflict.
class AIOEnergyManagementConfigFlow(  # pyright: ignore[reportIncompatibleMethodOverride]
    ConfigFlow,
    CheapestHoursConfigFlowMixin,
    ExcessSolarConfigFlowMixin,
    domain=DOMAIN,
):
    """Handle a config flow for AIO Energy Management."""

    VERSION: int = 1
    MINOR_VERSION: int = 2

    _entry_type: str | None
    _data_provider_type: str | None
    _config_data: FlowInput

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._entry_type = None
        self._data_provider_type = None
        self._config_data = {}

    @staticmethod
    @callback
    @override
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> AIOEnergyManagementOptionsFlow:
        """Get the options flow for this handler."""
        return AIOEnergyManagementOptionsFlow(config_entry)

    @override
    async def async_step_user(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step - select entry type."""
        # Check if Global Settings already exists
        has_global_settings = any(
            entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_GLOBAL_SETTINGS
            for entry in self._async_current_entries()
        )

        # Create Global Settings for new installations
        if not has_global_settings:
            return await self.async_step_global_settings()

        if user_input is not None:
            self._entry_type = _optional_str(user_input.get(CONF_ENTRY_TYPE))

            if self._entry_type == ENTRY_TYPE_CHEAPEST_HOURS:
                return await self.async_step_cheapest_hours_data_provider()
            if self._entry_type == CONF_ENTITY_EXCESS_SOLAR:
                return await self.async_step_excess_solar_global()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENTRY_TYPE): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                ENTRY_TYPE_CHEAPEST_HOURS,
                                CONF_ENTITY_EXCESS_SOLAR,
                            ],
                            translation_key="entry_type",
                        )
                    ),
                }
            ),
        )

    async def async_step_global_settings(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Create global settings entry."""
        await self.async_set_unique_id(ENTRY_TYPE_GLOBAL_SETTINGS)
        self._abort_if_unique_id_configured()

        migrated_unique_id = (user_input or {}).get(CONF_UNIQUE_ID)

        return self.async_create_entry(
            title="⚙️ Global Settings",
            data={
                CONF_UNIQUE_ID: migrated_unique_id or ENTRY_TYPE_GLOBAL_SETTINGS,
                CONF_ENTRY_TYPE: ENTRY_TYPE_GLOBAL_SETTINGS,
            },
        )


# Options flow (modify existing configuration)
class AIOEnergyManagementOptionsFlow(
    OptionsFlow,
    CheapestHoursConfigFlowMixin,
    ExcessSolarConfigFlowMixin,
):
    """Handle options flow for AIO Energy Management."""

    _config_entry: ConfigEntry
    _entry_type: str | None
    _data_provider_type: str | None
    _config_data: FlowInput

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry
        self._config_data = dict(config_entry.data)
        self._entry_type = _optional_str(self._config_data.get(CONF_ENTRY_TYPE))
        self._data_provider_type = _optional_str(
            self._config_data.get(CONF_DATA_PROVIDER_TYPE)
        )

    async def async_step_init(
        self, _user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Manage the options flow based on entry type."""
        if self._entry_type == ENTRY_TYPE_CHEAPEST_HOURS:
            return await self.async_step_cheapest_hours_menu()
        if self._entry_type == ENTRY_TYPE_GLOBAL_SETTINGS:
            return await self.async_step_global_settings_options()
        if self._entry_type == CONF_ENTITY_EXCESS_SOLAR:
            return await self.async_step_excess_solar_menu()

        return self.async_abort(reason="unknown_entry_type")

    async def async_step_global_settings_options(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Manage global settings."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_options: FlowInput = {
            **self._config_entry.data,
            **self._config_entry.options,
        }
        current_enable_calendar = current_options.get(CONF_ENABLE_CALENDAR, False)
        current_name = current_options.get(CONF_NAME, "Energy Management")

        return self.async_show_form(
            step_id="global_settings_options",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLE_CALENDAR,
                        default=current_enable_calendar,
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_NAME,
                        default=current_name,
                    ): TextSelector(),
                }
            ),
        )

    async def async_step_cheapest_hours_menu(
        self, _user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Show the cheapest hours settings menu."""
        menu_options = [
            "cheapest_hours_data_provider",
            "cheapest_hours_basic",
            "cheapest_hours_advanced",
            "cheapest_hours_flexible",
        ]
        # Retrive sequential value from sensor and add it to menu if true
        current: FlowInput = {**self.config_entry.data, **self.config_entry.options}
        if current.get(CONF_SEQUENTIAL) is True:
            menu_options.append("cheapest_hours_offset")

        return self.async_show_menu(
            step_id="cheapest_hours_menu",
            menu_options=menu_options,
        )

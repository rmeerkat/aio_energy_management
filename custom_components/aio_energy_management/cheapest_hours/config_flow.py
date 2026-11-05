"""Cheapest hours config flow handlers."""

from __future__ import annotations

import logging
from typing import cast
from collections.abc import Callable
import probatio as vol

from homeassistant.config_entries import ConfigFlowResult

from ..flow_types import FlowInput, FlowMixinBase, as_int, as_number

from custom_components.aio_energy_management.const import (
    CONF_ADD_FLEXIBLE,
    CONF_DATA_PROVIDER_TYPE,
    CONF_END_HOURS_ENTITY,
    CONF_END_MINUTES_ENTITY,
    CONF_FAILSAFE_STARTING_HOUR,
    CONF_MAX_NUMBER_OF_SLOTS,
    CONF_MAX_NUMBER_OF_SLOTS_ENTITY,
    CONF_MIN_SEQ_SLOTS,
    CONF_MTU,
    CONF_NAME,
    CONF_NUMBER_OF_BLOCKS,
    CONF_NUMBER_OF_SLOTS,
    CONF_NUMBER_OF_SLOTS_ENTITY,
    CONF_MAX_PRICE_DELTA,
    CONF_OFFSET,
    CONF_PRICE_LIMIT,
    CONF_PRICE_LIMIT_ENTITY,
    CONF_PRICE_MODIFICATIONS,
    CONF_RETENTION_DAYS,
    CONF_SEQUENTIAL,
    CONF_START_HOURS_ENTITY,
    CONF_START_MINUTES_ENTITY,
    CONF_TRIGGER_HOUR,
    CONF_TRIGGER_HOUR_ENTITY,
    CONF_UNIQUE_ID,
    DATA_PROVIDER_ENTSOE,
    DATA_PROVIDER_NORDPOOL,
    DATA_PROVIDER_NORDPOOL_OFFICIAL,
    DATA_PROVIDER_STROMLIGNING,
)
from .helpers import (
    coerce_mtu,
    normalize_optional_keys,
    process_offset_input,
    clean_sequential_basic_fields,
    sanitize_cheapest_hours_input,
    validate_and_clean_advanced_fields,
    validate_and_clean_number_of_slots,
    validate_and_clean_offset_fields,
    validate_and_build_add_flexible,
    validate_basic_integer_fields,
    validate_offset_integer_fields,
)
from .schemas import (
    get_cheapest_hours_advanced_schema,
    get_cheapest_hours_basic_schema,
    get_data_provider_type_schema,
    get_entsoe_schema,
    get_nordpool_official_schema,
    get_nordpool_schema,
    get_offset_schema,
    get_flexible_schema,
    get_stromligning_schema,
)

_LOGGER = logging.getLogger(__name__)

CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_CHEAPEST_HOURS = "cheapest_hours"


class CheapestHoursConfigFlowMixin(FlowMixinBase):
    """Mixin for cheapest hours config flow steps."""

    _data_provider_type: str | None

    def _save_options_entry(self, user_input: FlowInput) -> ConfigFlowResult:
        """Helper to save updated data directly during Options Flow."""
        entry = self._require_options_entry()
        cleaned_input = sanitize_cheapest_hours_input(user_input)

        new_data = {**entry.data, **cleaned_input}
        name = new_data.get(CONF_NAME)
        self.hass.config_entries.async_update_entry(
            entry,
            title=name if isinstance(name, str) else entry.title,
            data=new_data,
        )
        return self.async_create_entry(title="", data={})

    async def async_step_cheapest_hours_data_provider(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Select data provider type for cheapest hours."""
        if user_input is not None:
            provider = user_input.get(CONF_DATA_PROVIDER_TYPE)
            self._data_provider_type = provider if isinstance(provider, str) else None
            self._config_data[CONF_DATA_PROVIDER_TYPE] = self._data_provider_type

            if self._data_provider_type == DATA_PROVIDER_NORDPOOL:
                return await self.async_step_cheapest_hours_nordpool()
            if self._data_provider_type == DATA_PROVIDER_NORDPOOL_OFFICIAL:
                return await self.async_step_cheapest_hours_nordpool_official()
            if self._data_provider_type == DATA_PROVIDER_ENTSOE:
                return await self.async_step_cheapest_hours_entsoe()
            if self._data_provider_type == DATA_PROVIDER_STROMLIGNING:
                return await self.async_step_cheapest_hours_stromligning()

        default = None
        if (entry := self._options_entry()) is not None:
            default = entry.data.get(CONF_DATA_PROVIDER_TYPE)

        return self.async_show_form(
            step_id="cheapest_hours_data_provider",
            data_schema=get_data_provider_type_schema(default=default),
        )

    async def _async_handle_price_source_step(
        self,
        step_id: str,
        schema_factory: Callable[[FlowInput | None], vol.Schema],
        user_input: FlowInput | None = None,
    ) -> ConfigFlowResult:
        """Generic handler for price source provider configuration steps."""
        if user_input is not None:
            coerce_mtu(user_input)

            # Options Flow: Save entry directly
            if self._options_entry() is not None:
                return self._save_options_entry(user_input)

            # Config Flow: forward towards basic settings
            self._config_data.update(user_input)
            return await self.async_step_cheapest_hours_basic()

        entry = self._options_entry()
        existing_data = dict(entry.data) if entry is not None else None

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema_factory(existing_data or user_input),
        )

    async def async_step_cheapest_hours_nordpool(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Configure Nord Pool entity for cheapest hours."""
        return await self._async_handle_price_source_step(
            step_id="cheapest_hours_nordpool",
            schema_factory=get_nordpool_schema,
            user_input=user_input,
        )

    async def async_step_cheapest_hours_nordpool_official(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Configure Nord Pool official config entry for cheapest hours."""
        return await self._async_handle_price_source_step(
            step_id="cheapest_hours_nordpool_official",
            schema_factory=lambda data: get_nordpool_official_schema(self.hass, data),
            user_input=user_input,
        )

    async def async_step_cheapest_hours_entsoe(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Configure Entso-E entity for cheapest hours."""
        return await self._async_handle_price_source_step(
            step_id="cheapest_hours_entsoe",
            schema_factory=get_entsoe_schema,
            user_input=user_input,
        )

    async def async_step_cheapest_hours_stromligning(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Configure Strømligning entities for cheapest hours."""
        return await self._async_handle_price_source_step(
            step_id="cheapest_hours_stromligning",
            schema_factory=get_stromligning_schema,
            user_input=user_input,
        )

    async def async_step_cheapest_hours_basic(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Configure basic cheapest hours settings."""

        # Validate and process form input
        errors: dict[str, str] = {}

        if user_input is not None:
            self._flatten_dynamic_section(user_input)
            errors = validate_basic_integer_fields(user_input)
            slot_errors = validate_and_clean_number_of_slots(user_input)
            errors.update(slot_errors)

            if not errors:
                # Options flow
                if self._options_entry() is not None:
                    normalize_optional_keys(
                        user_input,
                        [CONF_NUMBER_OF_SLOTS, CONF_NUMBER_OF_SLOTS_ENTITY],
                    )
                    clean_sequential_basic_fields(user_input)
                    return self._save_options_entry(user_input)

                # Config flow
                self._config_data.update(user_input)

                name = str(self._config_data[CONF_NAME])
                unique_id = name.lower().replace(" ", "_")
                self._config_data[CONF_UNIQUE_ID] = unique_id
                self._config_data[CONF_ENTRY_TYPE] = ENTRY_TYPE_CHEAPEST_HOURS
                cleaned_data = sanitize_cheapest_hours_input(self._config_data)

                return await self._async_create_unique_entry(
                    unique_id, name, cleaned_data
                )

        # Show form
        entry = self._options_entry()
        merged_input = {**(entry.data if entry else {}), **(user_input or {})}

        return self.async_show_form(
            step_id="cheapest_hours_basic",
            data_schema=get_cheapest_hours_basic_schema(merged_input),
            errors=errors,
        )

    async def async_step_cheapest_hours_advanced(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Configure advanced cheapest hours settings (Options Flow only)."""

        # Validate and process form input
        errors: dict[str, str] = {}
        entry_data = self._entry_data()
        sequential = entry_data.get(CONF_SEQUENTIAL) is True

        if user_input is not None:
            self._flatten_dynamic_section(user_input)
            errors = validate_and_clean_advanced_fields(
                user_input,
                sequential=sequential,
                config_data=self._config_data,
            )

            if not errors:
                # Options flow (no config flow supported yet)
                normalize_optional_keys(
                    user_input,
                    [
                        CONF_FAILSAFE_STARTING_HOUR,
                        CONF_TRIGGER_HOUR,
                        CONF_TRIGGER_HOUR_ENTITY,
                        CONF_PRICE_LIMIT,
                        CONF_PRICE_LIMIT_ENTITY,
                        CONF_MIN_SEQ_SLOTS,
                        CONF_NUMBER_OF_BLOCKS,
                        CONF_PRICE_MODIFICATIONS,
                        CONF_RETENTION_DAYS,
                    ],
                )
                return self._save_options_entry(user_input)

        merged_input = {**entry_data, **(user_input or {})}

        return self.async_show_form(
            step_id="cheapest_hours_advanced",
            data_schema=get_cheapest_hours_advanced_schema(merged_input, sequential),
            errors=errors,
        )

    async def async_step_cheapest_hours_offset(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Configure offset settings for cheapest hours (Options Flow only)."""

        # Validate and process form input
        errors: dict[str, str] = {}

        if user_input is not None:
            self._flatten_dynamic_section(user_input)

            errors = validate_offset_integer_fields(user_input)
            offset_errors = validate_and_clean_offset_fields(user_input)
            errors.update(offset_errors)

            if not errors:
                # Options flow (no config flow supported yet)
                offset, entities = process_offset_input(user_input)

                save_data = {
                    CONF_OFFSET: offset if offset else None,
                    CONF_START_HOURS_ENTITY: entities.get(CONF_START_HOURS_ENTITY),
                    CONF_START_MINUTES_ENTITY: entities.get(CONF_START_MINUTES_ENTITY),
                    CONF_END_HOURS_ENTITY: entities.get(CONF_END_HOURS_ENTITY),
                    CONF_END_MINUTES_ENTITY: entities.get(CONF_END_MINUTES_ENTITY),
                }
                return self._save_options_entry(save_data)

        entry_data = self._entry_data()
        stored_offset = entry_data.get(CONF_OFFSET)
        offset_data: FlowInput = {
            **(cast(FlowInput, stored_offset) if isinstance(stored_offset, dict) else {}),
            **entry_data,
        }
        merged_input = {**offset_data, **(user_input or {})}

        return self.async_show_form(
            step_id="cheapest_hours_offset",
            data_schema=get_offset_schema(merged_input),
            errors=errors,
        )

    async def async_step_cheapest_hours_flexible(
        self, user_input: FlowInput | None = None
    ) -> ConfigFlowResult:
        """Configure flexible slot settings for cheapest hours (Options Flow only)."""

        errors: dict[str, str] = {}
        entry_data = self._entry_data()

        if user_input is not None:
            self._flatten_dynamic_section(user_input)

            errors = validate_and_build_add_flexible(
                user_input,
                mtu=as_int(entry_data.get(CONF_MTU)) or 60,
                stored_price_limit=as_number(entry_data.get(CONF_PRICE_LIMIT)),
            )

            if not errors:
                normalize_optional_keys(
                    user_input,
                    [
                        CONF_ADD_FLEXIBLE,
                        CONF_MAX_NUMBER_OF_SLOTS,
                        CONF_MAX_NUMBER_OF_SLOTS_ENTITY,
                        CONF_MAX_PRICE_DELTA,
                    ],
                )
                return self._save_options_entry(user_input)

        merged_input = {**entry_data, **(user_input or {})}
        if user_input:
            # Show what the user just typed, not the previously stored values.
            merged_input.pop(CONF_ADD_FLEXIBLE, None)

        return self.async_show_form(
            step_id="cheapest_hours_flexible",
            data_schema=get_flexible_schema(merged_input),
            errors=errors,
        )

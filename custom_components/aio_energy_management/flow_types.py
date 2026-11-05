"""Types and base class shared by the config and options flow mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import probatio as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult

# Form input as Home Assistant passes it to flow steps (HA types it as
# dict[str, Any]). Values come from selectors and are narrowed where used.
type FlowInput = dict[str, object]

# Schema definitions: keys are Required/Optional markers; values are
# selectors, validators or sections.
type SchemaDict = dict[vol.Marker, object]


def as_number(value: object) -> float | None:
    """Return a numeric form value, or None if it is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def as_int(value: object) -> int | None:
    """Return a whole-number form value (selectors return floats), or None."""
    number = as_number(value)
    return int(number) if number is not None else None


if TYPE_CHECKING:
    # ConfigFlow and OptionsFlow both derive from ConfigEntryBaseFlow, so that is
    # what the mixins can rely on. At runtime the mixins are plain classes.
    from homeassistant.config_entries import ConfigEntryBaseFlow as _FlowBase
else:
    _FlowBase = object


class FlowMixinBase(_FlowBase):
    """Base of the flow mixins, mixed into both ConfigFlow and OptionsFlow."""

    if TYPE_CHECKING:
        # Initialised by the flow classes' __init__.
        _config_data: FlowInput

    def _options_entry(self) -> ConfigEntry | None:
        """Return the entry being edited, or None in the initial config flow."""
        return cast("ConfigEntry | None", getattr(self, "_config_entry", None))

    def _require_options_entry(self) -> ConfigEntry:
        """Return the entry being edited by a step that only exists in the options flow."""
        if (entry := self._options_entry()) is None:
            raise RuntimeError("This step is only available in the options flow")
        return entry

    def _entry_data(self) -> FlowInput:
        """Return a copy of the data of the entry being edited (options flow)."""
        return dict(self._require_options_entry().data)

    @staticmethod
    def _flatten_dynamic_section(user_input: FlowInput) -> None:
        """Move the fields of the collapsible 'dynamic_section' to the top level."""
        if isinstance(section := user_input.get("dynamic_section"), dict):
            user_input.pop("dynamic_section")
            user_input.update(cast(FlowInput, section))

    async def _async_create_unique_entry(
        self, unique_id: str, title: str, data: FlowInput
    ) -> ConfigFlowResult:
        """Create a new config entry, aborting if the unique id already exists."""
        # Unique ids only exist in the config flow, which is the only caller.
        if not isinstance(self, ConfigFlow):
            raise TypeError("A config entry can only be created by the config flow")
        await self.async_set_unique_id(unique_id)
        # Protected by name only; this is HA's documented way to abort duplicates.
        self._abort_if_unique_id_configured()  # pyright: ignore[reportPrivateUsage]
        return self.async_create_entry(title=title, data=data)

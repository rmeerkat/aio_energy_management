"""AIO Energy Management Service utility."""

import logging

import probatio as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .runtime_data import get_coordinator

_LOGGER = logging.getLogger(__name__)

ATTR_UNIQUE_ID = "unique_id"

SERVICE_CLEAR_DATA_SCHEMA = {
    vol.Required(ATTR_UNIQUE_ID): cv.string,
}

SERVICE_CLEAR_DATA = "clear_data"
SERVICES = [SERVICE_CLEAR_DATA]


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register the AIO Energy Management services."""
    _LOGGER.debug("Register services")

    if hass.services.has_service(DOMAIN, SERVICE_CLEAR_DATA):
        return

    async def clear_data(service_call: ServiceCall) -> None:
        unique_id: object = service_call.data.get(ATTR_UNIQUE_ID)
        if isinstance(unique_id, str) and unique_id:
            coordinator = get_coordinator(hass)
            if coordinator is None:
                _LOGGER.error("Cannot clear data before the integration is set up")
                return
            await coordinator.async_clear_data(unique_id)
        else:
            _LOGGER.error("Failed to clear data: no unique_id provided")

    hass.services.async_register(  # pyright: ignore[reportUnknownMemberType]  # HA's VolSchemaType leaves All untyped
        DOMAIN,
        SERVICE_CLEAR_DATA,
        clear_data,
        schema=vol.Schema(SERVICE_CLEAR_DATA_SCHEMA),
        supports_response=SupportsResponse.NONE,
    )

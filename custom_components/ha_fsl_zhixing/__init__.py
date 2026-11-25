"""The FSL integration."""

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CLIENT_MAC,
    CONF_GATEWAY_MAC,
    DEFAULT_CLIENT_MAC,
    DEFAULT_UDP_PORT,
    DOMAIN,
    SERVICE_RELOAD_DEVICES,
)
from .coordinator import FSLDataUpdateCoordinator
from .transport import FSLTransportError

_LOGGER = logging.getLogger(__name__)

type FSLConfigEntry = ConfigEntry[FSLDataUpdateCoordinator]

PLATFORMS = [Platform.LIGHT]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
ATTR_ENTRY_ID = "entry_id"
RELOAD_DEVICES_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): str})


def _async_register_services(hass: HomeAssistant) -> None:
    """Register FSL domain services once."""
    if hass.services.has_service(DOMAIN, SERVICE_RELOAD_DEVICES):
        return

    async def _async_handle_reload_devices(call: ServiceCall) -> None:
        entry_id: str | None = call.data.get(ATTR_ENTRY_ID)
        if entry_id is not None:
            entry = hass.config_entries.async_get_entry(entry_id)
            if (
                entry is None
                or entry.domain != DOMAIN
                or entry.state is not ConfigEntryState.LOADED
            ):
                raise ServiceValidationError(
                    f"FSL config entry {entry_id} is not loaded"
                )
            entries = [entry]
        else:
            entries = hass.config_entries.async_loaded_entries(DOMAIN)

        for entry in entries:
            coordinator: FSLDataUpdateCoordinator = entry.runtime_data
            try:
                await coordinator.async_sync_manifest()
            except FSLTransportError as err:
                raise HomeAssistantError(
                    f"Failed to reload FSL devices for {entry.title}: {err}"
                ) from err
            try:
                await coordinator.async_poll_device_statuses(schedule_retry=True)
            except FSLTransportError as err:
                _LOGGER.debug("Post-reload Type 17 poll failed: %s", err)

    hass.services.async_register(
        DOMAIN,
        SERVICE_RELOAD_DEVICES,
        _async_handle_reload_devices,
        schema=RELOAD_DEVICES_SCHEMA,
    )


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up FSL domain services."""
    _async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: FSLConfigEntry) -> bool:
    """Set up FSL from a config entry."""
    _async_register_services(hass)
    coordinator = FSLDataUpdateCoordinator(
        hass,
        entry,
        async_get_clientsession(hass),
    )
    await coordinator.async_start()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FSLConfigEntry) -> bool:
    """Unload an FSL config entry and shut down its UDP session."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate FSL config entries to version 2 (local UDP gateway)."""
    if config_entry.version > 2:
        return False
    if config_entry.version == 1:
        if CONF_HOST not in config_entry.data:
            _LOGGER.warning(
                "Legacy v1 FSL cloud config entry %s cannot be migrated automatically "
                "without a local gateway host; please remove and re-add FSL",
                config_entry.entry_id,
            )
            return False
        new_data = {
            CONF_HOST: config_entry.data[CONF_HOST],
            CONF_PORT: int(config_entry.data.get(CONF_PORT, DEFAULT_UDP_PORT)),
            CONF_CLIENT_MAC: config_entry.data.get(CONF_CLIENT_MAC, DEFAULT_CLIENT_MAC),
            CONF_GATEWAY_MAC: config_entry.data.get(CONF_GATEWAY_MAC, ""),
        }
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)
    return True

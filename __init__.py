"""The FSL integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEVICE_TYPE_SPOTLIGHT, DOMAIN
from .coordinator import FSLDataUpdateCoordinator

type FSLConfigEntry = ConfigEntry[FSLDataUpdateCoordinator]

PLATFORMS = [Platform.INFRARED, Platform.LIGHT, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: FSLConfigEntry) -> bool:
    """Set up FSL from a config entry."""
    coordinator = FSLDataUpdateCoordinator(
        hass,
        entry,
        async_get_clientsession(hass),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    entity_registry = er.async_get(hass)
    for device_id, device in coordinator.data.items():
        if str(device["devType"]) != DEVICE_TYPE_SPOTLIGHT:
            continue
        if entity_id := entity_registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, str(device_id)
        ):
            entity_registry.async_remove(entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FSLConfigEntry) -> bool:
    """Unload an FSL config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

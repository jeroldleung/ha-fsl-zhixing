"""Infrared platform for the FSL integration."""

from typing import override

from homeassistant.components.infrared import InfraredCommand, InfraredEmitterEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FSLConfigEntry
from .const import DEVICE_TYPE_INFRARED_CONTROLLER, DEVICE_TYPES, DOMAIN
from .coordinator import FSLDataUpdateCoordinator, FSLDevice

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FSLConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FSL infrared controllers."""
    coordinator = entry.runtime_data
    known_device_ids: set[int] = set()

    @callback
    def async_add_new_devices() -> None:
        """Add newly discovered infrared controllers."""
        entities: list[FSLInfraredController] = []
        for device_id, device in coordinator.data.items():
            if (
                device_id not in known_device_ids
                and str(device["devType"]) == DEVICE_TYPE_INFRARED_CONTROLLER
            ):
                known_device_ids.add(device_id)
                entities.append(FSLInfraredController(coordinator, device_id))
        if entities:
            async_add_entities(entities)

    async_add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_devices))


class FSLInfraredController(
    CoordinatorEntity[FSLDataUpdateCoordinator], InfraredEmitterEntity
):
    """Representation of an FSL Smart Infrared Controller."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        coordinator: FSLDataUpdateCoordinator,
        device_id: int,
    ) -> None:
        """Initialize an FSL infrared controller."""
        super().__init__(coordinator)
        self._device_id = device_id
        device = coordinator.data[device_id]
        self._fallback_device = device
        self._attr_unique_id = str(device_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            manufacturer="FSL",
            model=DEVICE_TYPES[DEVICE_TYPE_INFRARED_CONTROLLER],
            name=device.get("devName") or f"FSL {device_id}",
            sw_version=device.get("devVersion") or None,
        )

    @property
    def device(self) -> FSLDevice:
        """Return the latest device data."""
        return self.coordinator.data.get(self._device_id, self._fallback_device)

    @property
    @override
    def available(self) -> bool:
        """Return whether the controller is present and enabled in the cloud."""
        return (
            super().available
            and self._device_id in self.coordinator.data
            and self.device.get("isValid") == 1
            and self.device.get("isUse") == 1
        )

    @override
    async def async_send_command(self, command: InfraredCommand) -> None:
        """Report that FSL infrared transmission needs its cloud API mapping."""
        raise HomeAssistantError(
            "FSL infrared transmission is not implemented; "
            "the infrared control API is required"
        )

"""Sensor platform for the FSL integration."""

from typing import Any, override

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FSLConfigEntry
from .const import DEVICE_TYPE_GATEWAY, DEVICE_TYPES, DOMAIN
from .coordinator import FSLDataUpdateCoordinator, FSLDevice


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FSLConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FSL device sensors."""
    async_add_entities(
        FSLDeviceSensor(entry.runtime_data, device_id)
        for device_id, device in entry.runtime_data.data.items()
        if str(device["devType"]) == DEVICE_TYPE_GATEWAY
    )


class FSLDeviceSensor(CoordinatorEntity[FSLDataUpdateCoordinator], SensorEntity):
    """Representation of an FSL cloud device."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        coordinator: FSLDataUpdateCoordinator,
        device_id: int,
    ) -> None:
        """Initialize an FSL device sensor."""
        super().__init__(coordinator)
        self._device_id = device_id
        device = coordinator.data[device_id]
        self._fallback_device = device
        device_type = str(device["devType"])

        self._attr_unique_id = str(device_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            manufacturer="FSL",
            model=DEVICE_TYPES[device_type],
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
        """Return whether the device is available."""
        return (
            super().available
            and self._device_id in self.coordinator.data
            and self.device.get("isValid") == 1
            and self.device.get("isUse") == 1
        )

    @property
    @override
    def native_value(self) -> str:
        """Return the FSL device type."""
        return DEVICE_TYPES[str(self.device["devType"])]

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return useful cloud metadata."""
        device = self.device
        return {
            "device_type": device["devType"],
            "room_id": device.get("roomId"),
            "network_lock": device.get("networkLock"),
            "power_disturb": device.get("powerDisturb"),
        }

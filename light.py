"""Light platform for the FSL integration."""

from typing import Any, override

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    DEFAULT_MAX_KELVIN,
    DEFAULT_MIN_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FSLConfigEntry
from .const import DEVICE_TYPE_SPOTLIGHT, DOMAIN
from .coordinator import FSLControlConfig, FSLDataUpdateCoordinator, FSLDevice


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FSLConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FSL spotlights."""
    async_add_entities(
        FSLSpotlight(entry.runtime_data, device_id)
        for device_id, device in entry.runtime_data.data.items()
        if str(device["devType"]) == DEVICE_TYPE_SPOTLIGHT
    )


def brightness_to_percentage(brightness: int) -> int:
    """Convert Home Assistant brightness to an FSL percentage."""
    return round(brightness * 100 / 255)


def kelvin_to_fsl_temperature(kelvin: int) -> str:
    """Convert Kelvin to the FSL temperature channel format."""
    clamped_kelvin = min(max(kelvin, DEFAULT_MIN_KELVIN), DEFAULT_MAX_KELVIN)
    second_channel = round(
        (clamped_kelvin - DEFAULT_MIN_KELVIN)
        * 255
        / (DEFAULT_MAX_KELVIN - DEFAULT_MIN_KELVIN)
    )
    return f"{255 - second_channel},{second_channel}"


class FSLSpotlight(CoordinatorEntity[FSLDataUpdateCoordinator], LightEntity):
    """Representation of an FSL spotlight."""

    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_has_entity_name = True
    _attr_is_on = None
    _attr_max_color_temp_kelvin = DEFAULT_MAX_KELVIN
    _attr_min_color_temp_kelvin = DEFAULT_MIN_KELVIN
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP}

    def __init__(
        self,
        coordinator: FSLDataUpdateCoordinator,
        device_id: int,
    ) -> None:
        """Initialize an FSL spotlight."""
        super().__init__(coordinator)
        self._device_id = device_id
        device = coordinator.data[device_id]
        self._fallback_device = device

        self._attr_unique_id = str(device_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            manufacturer="FSL",
            model="Spotlight",
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
        """Return whether the spotlight is available."""
        return (
            super().available
            and self._device_id in self.coordinator.data
            and self.device.get("isValid") == 1
            and self.device.get("isUse") == 1
        )

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the spotlight and apply light attributes."""
        config: list[FSLControlConfig] = [{"CF_OnOff": True}]

        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            config.append({"CF_Bright": brightness_to_percentage(brightness)})

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            color_temp_kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            config.append(
                {"CF_Temperature": kelvin_to_fsl_temperature(color_temp_kelvin)}
            )

        await self.coordinator.async_control_light(self._device_id, config)

        self._attr_is_on = True
        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            self._attr_color_temp_kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the spotlight."""
        await self.coordinator.async_control_light(
            self._device_id, [{"CF_OnOff": False}]
        )
        self._attr_is_on = False
        self.async_write_ha_state()

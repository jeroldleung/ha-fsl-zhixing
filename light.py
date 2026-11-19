"""Light platform for the FSL integration."""

from typing import Any, override

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FSLConfigEntry
from .catalog import (
    FSLLightDevice,
    FSLLightSpec,
    FSLLightState,
    bl_brightness_to_ha,
    ha_brightness_to_bl,
    kelvin_to_wc,
    wc_to_kelvin,
)
from .const import DOMAIN, FADE_SUPPORTED_MIN_FW, MAX_KELVIN, MIN_KELVIN
from .coordinator import FSLDataUpdateCoordinator

__all__ = [
    "FSLLightEntity",
    "async_setup_entry",
    "bl_brightness_to_ha",
    "build_light_control_payload",
    "ha_brightness_to_bl",
    "kelvin_to_wc",
    "wc_to_kelvin",
]


def build_light_control_payload(
    *,
    is_on: bool,
    spec: FSLLightSpec,
    brightness: int | None = None,
    color_temp_kelvin: int | None = None,
    rgb_color: tuple[int, int, int] | None = None,
    cached_state: FSLLightState | None = None,
    transition: float | None = None,
    fw_version: int | None = None,
    fade_enabled: bool = True,
) -> bytes:
    """Encode a BroadLink 1-byte or 6-byte [Bri/Power, B, R, G, W, C] payload."""
    prefix = b""
    if (
        transition is not None
        and fw_version is not None
        and fw_version >= FADE_SUPPORTED_MIN_FW
    ):
        prefix = b"\x80" if (transition > 0 and fade_enabled) else b"\x00"

    if not is_on:
        # BroadLink lights require single-byte 0x00 to turn off rather than six 0x00 bytes.
        return prefix + b"\x00"

    if brightness is None and color_temp_kelvin is None and rgb_color is None:
        return prefix + b"\x80"

    if brightness is not None:
        byte0 = 0x80 | ha_brightness_to_bl(brightness)
    elif cached_state is not None and cached_state.brightness_ha is not None:
        byte0 = 0x80 | ha_brightness_to_bl(cached_state.brightness_ha)
    else:
        byte0 = 0x80

    b_val = r_val = g_val = w_val = c_val = 0

    if spec.lighting_class == "CW":
        target_kelvin = color_temp_kelvin or (
            cached_state.color_temp_kelvin if cached_state else None
        )
        if target_kelvin is not None:
            w_val, c_val = kelvin_to_wc(target_kelvin)
    elif spec.lighting_class == "RGB":
        target_rgb = rgb_color or (cached_state.rgb_color if cached_state else None)
        if target_rgb is not None:
            r_val, g_val, b_val = target_rgb
    elif spec.lighting_class == "RGBCW":
        if rgb_color is not None:
            r_val, g_val, b_val = rgb_color
        elif color_temp_kelvin is not None:
            w_val, c_val = kelvin_to_wc(color_temp_kelvin)
        elif cached_state is not None:
            if (
                cached_state.color_mode == ColorMode.RGB
                and cached_state.rgb_color is not None
            ):
                r_val, g_val, b_val = cached_state.rgb_color
            elif cached_state.color_temp_kelvin is not None:
                w_val, c_val = kelvin_to_wc(cached_state.color_temp_kelvin)

    return prefix + bytes([byte0, b_val, r_val, g_val, w_val, c_val])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FSLConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FSL lights and dynamically register lights added on reload."""
    coordinator = entry.runtime_data
    known_sdids: set[str] = set()

    @callback
    def async_add_new_lights() -> None:
        entities: list[FSLLightEntity] = []
        for short_addr, device in coordinator.data.items():
            if device.sdid not in known_sdids:
                known_sdids.add(device.sdid)
                entities.append(FSLLightEntity(coordinator, short_addr))
        if entities:
            async_add_entities(entities)

    async_add_new_lights()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_lights))


class FSLLightEntity(CoordinatorEntity[FSLDataUpdateCoordinator], LightEntity):
    """Representation of a local FSL lighting sub-device."""

    _attr_has_entity_name = True
    _attr_max_color_temp_kelvin = MAX_KELVIN
    _attr_min_color_temp_kelvin = MIN_KELVIN
    _attr_name = None

    def __init__(
        self,
        coordinator: FSLDataUpdateCoordinator,
        short_addr: int,
    ) -> None:
        """Initialize an FSL light entity."""
        super().__init__(coordinator)
        self._short_addr = short_addr
        device = coordinator.data[short_addr]
        self._fallback_device = device

        self._attr_unique_id = device.sdid
        self._attr_supported_color_modes = set(device.spec.supported_color_modes)
        via_device = (DOMAIN, coordinator.gateway.mac) if coordinator.gateway.mac else None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.sdid)},
            manufacturer="FSL",
            model=device.spec.model,
            name=device.name,
            sw_version=device.version or None,
            hw_version=device.dev_version,
            via_device=via_device,
            suggested_area=device.room_name or None,
        )

    @property
    def device(self) -> FSLLightDevice:
        """Return the latest device metadata from the coordinator."""
        return self.coordinator.data.get(self._short_addr, self._fallback_device)

    @property
    @override
    def available(self) -> bool:
        """Return whether the gateway session and light device are active."""
        return (
            super().available
            and self.coordinator.gateway_available
            and self._short_addr in self.coordinator.data
        )

    @property
    @override
    def supported_features(self) -> LightEntityFeature:
        """Advertise transition support for FW >= 58 lights when enabled."""
        fw_version = self.device.fw_version
        if (
            fw_version is not None
            and fw_version >= FADE_SUPPORTED_MIN_FW
            and self.coordinator.fade_transition
        ):
            return LightEntityFeature.TRANSITION
        return LightEntityFeature(0)

    @property
    @override
    def color_mode(self) -> ColorMode:
        """Return the active color mode."""
        state = self.coordinator.states.get(self._short_addr)
        if state is not None and state.color_mode in self._attr_supported_color_modes:
            return state.color_mode
        if ColorMode.COLOR_TEMP in self._attr_supported_color_modes:
            return ColorMode.COLOR_TEMP
        return next(iter(self._attr_supported_color_modes))

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the light is currently on."""
        state = self.coordinator.states.get(self._short_addr)
        return state.is_on if state is not None else None

    @property
    @override
    def brightness(self) -> int | None:
        """Return the current Home Assistant brightness (0-255)."""
        state = self.coordinator.states.get(self._short_addr)
        return state.brightness_ha if state is not None else None

    @property
    @override
    def color_temp_kelvin(self) -> int | None:
        """Return the current color temperature in Kelvin."""
        state = self.coordinator.states.get(self._short_addr)
        return state.color_temp_kelvin if state is not None else None

    @property
    @override
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the current RGB color tuple."""
        state = self.coordinator.states.get(self._short_addr)
        return state.rgb_color if state is not None else None

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light and apply brightness, CCT, RGB, or transition."""
        brightness: int | None = kwargs.get(ATTR_BRIGHTNESS)
        kelvin: int | None = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        rgb: tuple[int, int, int] | None = kwargs.get(ATTR_RGB_COLOR)
        transition: float | None = kwargs.get(ATTR_TRANSITION)

        device = self.device
        payload = build_light_control_payload(
            is_on=True,
            spec=device.spec,
            brightness=brightness,
            color_temp_kelvin=kelvin,
            rgb_color=rgb,
            cached_state=self.coordinator.states.get(self._short_addr),
            transition=transition,
            fw_version=device.fw_version,
            fade_enabled=self.coordinator.fade_transition,
        )
        await self.coordinator.async_control_light(self._short_addr, payload)

        next_mode: ColorMode | None = None
        if rgb is not None:
            next_mode = ColorMode.RGB
        elif kelvin is not None:
            next_mode = ColorMode.COLOR_TEMP

        self.coordinator.update_optimistic_state(
            self._short_addr,
            is_on=True,
            brightness_ha=brightness,
            color_temp_kelvin=kelvin,
            rgb_color=rgb,
            color_mode=next_mode,
        )
        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light using single-byte 0x00 or transition-prefixed payload."""
        transition: float | None = kwargs.get(ATTR_TRANSITION)
        device = self.device
        payload = build_light_control_payload(
            is_on=False,
            spec=device.spec,
            transition=transition,
            fw_version=device.fw_version,
            fade_enabled=self.coordinator.fade_transition,
        )
        await self.coordinator.async_control_light(self._short_addr, payload)
        self.coordinator.update_optimistic_state(self._short_addr, is_on=False)
        self.async_write_ha_state()

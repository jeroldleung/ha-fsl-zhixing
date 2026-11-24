"""Data coordinator for the local-first FSL integration."""

import asyncio
import base64
from datetime import timedelta
import json
import logging
from typing import Any

import aiohttp

from homeassistant.components.light import ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .catalog import (
    FSLGatewayInfo,
    FSLLightDevice,
    FSLLightState,
    decode_light_state,
    parse_gateway_device,
    parse_light_device,
)
from .const import (
    CONF_CLIENT_MAC,
    CONF_FADE_TRANSITION,
    CONF_FILTER_IGNORED,
    CONF_GATEWAY_MAC,
    CONF_POLL_INTERVAL,
    DEFAULT_CLIENT_MAC,
    DEFAULT_FADE_TRANSITION,
    DEFAULT_FILTER_IGNORED,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_UDP_PORT,
    DOMAIN,
    MANIFEST_FETCH_MAX_RETRIES,
    POLL_CHUNK_COOLDOWN,
)
from .transport import FSLTransportError, FSLUdpClient, build_status_trigger_payloads

_LOGGER = logging.getLogger(__name__)


def _decode_b64_json(encoded: str) -> Any:
    """Base64-decode a UTF-8 JSON string from the gateway family manifest."""
    raw = base64.b64decode(encoded).decode("utf-8")
    return json.loads(raw)


def _merge_light_state(
    prev: FSLLightState | None, incoming: FSLLightState
) -> FSLLightState:
    """Merge an incoming state snapshot with cached attributes."""
    if prev is None:
        return incoming
    return FSLLightState(
        is_on=incoming.is_on,
        brightness_ha=(
            incoming.brightness_ha
            if incoming.brightness_ha is not None
            else prev.brightness_ha
        ),
        color_temp_kelvin=(
            incoming.color_temp_kelvin
            if incoming.color_temp_kelvin is not None
            else prev.color_temp_kelvin
        ),
        rgb_color=(
            incoming.rgb_color if incoming.rgb_color is not None else prev.rgb_color
        ),
        color_mode=(
            incoming.color_mode if incoming.color_mode is not None else prev.color_mode
        ),
    )


class FSLDataUpdateCoordinator(DataUpdateCoordinator[dict[int, FSLLightDevice]]):
    """Coordinate local UDP transport, manifest sync, and Type 15/17 states."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the FSL local coordinator."""
        poll_interval = int(
            config_entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=(
                timedelta(seconds=poll_interval) if poll_interval > 0 else None
            ),
        )
        self._entry = config_entry
        self._session = session
        self.host: str = config_entry.data[CONF_HOST]
        self.port: int = int(config_entry.data.get(CONF_PORT, DEFAULT_UDP_PORT))
        self.client_mac: str = config_entry.data.get(CONF_CLIENT_MAC, DEFAULT_CLIENT_MAC)
        self.gateway_mac: str = config_entry.data.get(CONF_GATEWAY_MAC, "")

        self.fade_transition: bool = bool(
            config_entry.options.get(CONF_FADE_TRANSITION, DEFAULT_FADE_TRANSITION)
        )
        self.filter_ignored: bool = bool(
            config_entry.options.get(CONF_FILTER_IGNORED, DEFAULT_FILTER_IGNORED)
        )
        self.poll_interval: int = poll_interval

        self.data: dict[int, FSLLightDevice] = {}
        self.states: dict[int, FSLLightState] = {}
        self.gateway = FSLGatewayInfo(
            mac=self.gateway_mac,
            ip=self.host,
            port=self.port,
        )
        self._gateway_available = True
        self._poll_lock = asyncio.Lock()
        self._recovery_task: asyncio.Task[None] | None = None

        self.client = FSLUdpClient(
            hass.loop,
            self.host,
            self.port,
            self.client_mac,
            on_telemetry=self._handle_telemetry,
            on_availability_changed=self._handle_availability_changed,
        )

    @property
    def gateway_available(self) -> bool:
        """Return whether the gateway keep-alive session is currently reachable."""
        return self._gateway_available

    async def async_start(self) -> None:
        """Connect to the gateway, synchronize manifest, and run initial poll."""
        try:
            await self.client.async_connect()
            mac = await self.client.async_heartbeat()
        except FSLTransportError as err:
            await self.client.async_close()
            raise ConfigEntryNotReady(
                f"Unable to reach FSL gateway at {self.host}:{self.port}: {err}"
            ) from err

        if mac and not self.gateway_mac:
            self.gateway_mac = mac
            self.gateway.mac = mac

        self.client.start_heartbeat()

        try:
            await self.async_sync_manifest()
        except FSLTransportError as err:
            await self.client.async_close()
            raise ConfigEntryNotReady(
                f"Failed to download FSL device manifest: {err}"
            ) from err

        try:
            await self.async_poll_device_statuses()
        except FSLTransportError as err:
            _LOGGER.debug("Initial Type 17 status poll incomplete: %s", err)

    async def async_shutdown(self) -> None:
        """Cancel background tasks and close the UDP client."""
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            self._recovery_task = None
        await self.client.async_close()
        await super().async_shutdown()

    async def _async_update_data(self) -> dict[int, FSLLightDevice]:
        """Run periodic Type 17 status polling when enabled in options."""
        if not self._gateway_available:
            raise UpdateFailed("FSL gateway heartbeat timed out")
        try:
            await self.async_poll_device_statuses()
        except FSLTransportError as err:
            raise UpdateFailed(f"Failed to poll FSL devices: {err}") from err
        return self.data

    async def _async_fetch_manifest_json(self) -> dict[str, Any]:
        """Request a single-use Type 6 URL and download its JSON, retrying up to 3x."""
        last_err: Exception | None = None
        for attempt in range(1, MANIFEST_FETCH_MAX_RETRIES + 1):
            try:
                url = await self.client.async_get_device_url()
                async with self._session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
            except (
                FSLTransportError,
                aiohttp.ClientError,
                TimeoutError,
                ValueError,
            ) as err:
                last_err = err
                _LOGGER.debug(
                    "Type 5/6 manifest fetch attempt %d/%d failed: %s",
                    attempt,
                    MANIFEST_FETCH_MAX_RETRIES,
                    err,
                )
                continue

            if isinstance(payload, dict) and payload.get("status", 0) == 0:
                return payload
            last_err = FSLTransportError("Gateway returned invalid manifest payload")

        raise FSLTransportError(
            f"Exhausted {MANIFEST_FETCH_MAX_RETRIES} attempts fetching manifest: {last_err}"
        )

    async def async_sync_manifest(self) -> dict[int, FSLLightDevice]:
        """Fetch Type 5/6 manifest, sync areas & gateway, and update light inventory."""
        manifest = await self._async_fetch_manifest_json()

        tags: dict[str, str] = {}
        data_entries = manifest.get("data")
        if isinstance(data_entries, list):
            for family in data_entries:
                if not isinstance(family, dict):
                    continue
                for item in family.get("dataList") or []:
                    if isinstance(item, dict) and isinstance(item.get("mtag"), str):
                        if isinstance(item.get("data"), str):
                            tags[item["mtag"]] = item["data"]

        raw_devlist: list[dict[str, Any]] = []
        if "devlist" in tags:
            try:
                decoded_devs = _decode_b64_json(tags["devlist"])
            except (ValueError, UnicodeDecodeError) as err:
                raise FSLTransportError(f"Invalid devlist encoding: {err}") from err
            if isinstance(decoded_devs, list):
                raw_devlist = [d for d in decoded_devs if isinstance(d, dict)]

        family_info: dict[str, Any] = {}
        if "familyInfo" in tags:
            try:
                decoded_family = _decode_b64_json(tags["familyInfo"])
            except (ValueError, UnicodeDecodeError) as err:
                raise FSLTransportError(f"Invalid familyInfo encoding: {err}") from err
            if isinstance(decoded_family, dict):
                family_info = decoded_family

        room_map = self._sync_areas(family_info)

        gateway_mac = self.gateway_mac or self.client.gateway_mac or ""
        self.gateway = parse_gateway_device(
            raw_devlist,
            gateway_mac=gateway_mac,
            host=self.host,
            port=self.port,
        )
        self._register_gateway_device()

        devices: dict[int, FSLLightDevice] = {}
        for raw_dev in raw_devlist:
            light = parse_light_device(
                raw_dev, room_map, filter_ignored=self.filter_ignored
            )
            if light is not None:
                devices[light.short_addr] = light

        self.states = {
            short_addr: state
            for short_addr, state in self.states.items()
            if short_addr in devices
        }
        self.async_set_updated_data(devices)
        return devices

    def _sync_areas(self, family_info: dict[str, Any]) -> dict[int, str]:
        """Synchronize FSL rooms to Home Assistant Areas and return id->name map."""
        room_map: dict[int, str] = {}
        area_reg = ar.async_get(self.hass)
        for room in family_info.get("roomlist") or []:
            if not isinstance(room, dict):
                continue
            room_id = room.get("roomId")
            room_name = str(room.get("roomName") or "").strip()
            if isinstance(room_id, int) and room_name:
                room_map[room_id] = room_name
                if room_id != 0:
                    area_reg.async_get_or_create(room_name)
        return room_map

    def _register_gateway_device(self) -> None:
        """Register the parent FSL gateway in the Home Assistant Device Registry."""
        if not self.gateway.mac:
            return
        dev_reg = dr.async_get(self.hass)
        dev_reg.async_get_or_create(
            config_entry_id=self._entry.entry_id,
            identifiers={(DOMAIN, self.gateway.mac)},
            connections={(dr.CONNECTION_NETWORK_MAC, self.gateway.mac)},
            manufacturer="FSL",
            model=self.gateway.model,
            name=self.gateway.name,
            sw_version=self.gateway.version or None,
        )

    async def async_poll_device_statuses(
        self, short_addrs: list[int] | None = None
    ) -> None:
        """Send rate-limited Type 17 status queries across up to 104 devices per chunk."""
        targets = short_addrs if short_addrs is not None else list(self.data)
        payloads = build_status_trigger_payloads(targets)
        if not payloads:
            return

        async with self._poll_lock:
            for idx, payload in enumerate(payloads):
                if idx > 0:
                    await asyncio.sleep(POLL_CHUNK_COOLDOWN)
                await self.client.async_trigger_status_report(payload)

    async def async_control_light(self, short_addr: int, payload: bytes) -> None:
        """Send a Type 9 unicast lighting control payload to a sub-device."""
        try:
            await self.client.async_send_short_control(short_addr, payload)
        except FSLTransportError as err:
            raise HomeAssistantError(
                f"Failed to send command to FSL light {short_addr}: {err}"
            ) from err

    def update_optimistic_state(
        self,
        short_addr: int,
        *,
        is_on: bool,
        brightness_ha: int | None = None,
        color_temp_kelvin: int | None = None,
        rgb_color: tuple[int, int, int] | None = None,
        color_mode: ColorMode | None = None,
    ) -> None:
        """Update cached state optimistically after a confirmed Type 10 ACK."""
        self.states[short_addr] = _merge_light_state(
            self.states.get(short_addr),
            FSLLightState(
                is_on=is_on,
                brightness_ha=brightness_ha,
                color_temp_kelvin=color_temp_kelvin,
                rgb_color=rgb_color,
                color_mode=color_mode,
            ),
        )

    @callback
    def _handle_telemetry(self, chunks: list[tuple[int, bytes]]) -> None:
        """Apply parsed Type 15 telemetry updates and notify entity listeners."""
        updated = False
        for short_addr, dev_payload in chunks:
            device = self.data.get(short_addr)
            if device is None:
                continue
            decoded = decode_light_state(dev_payload, device.spec)
            if decoded is None:
                continue
            self.states[short_addr] = _merge_light_state(
                self.states.get(short_addr), decoded
            )
            updated = True

        if updated:
            self.async_update_listeners()

    @callback
    def _handle_availability_changed(self, available: bool) -> None:
        """Mark entities unavailable after 5 missed heartbeats and resync on recovery."""
        self._gateway_available = available
        self.async_update_listeners()
        if available and (self._recovery_task is None or self._recovery_task.done()):
            self._recovery_task = self.hass.async_create_task(
                self._async_recover_statuses()
            )

    async def _async_recover_statuses(self) -> None:
        """Refresh light statuses once the gateway recovers from a timeout."""
        try:
            await self.async_poll_device_statuses()
        except FSLTransportError as err:
            _LOGGER.debug("Post-recovery Type 17 status poll failed: %s", err)

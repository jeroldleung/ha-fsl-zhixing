"""Data coordinator for the FSL integration."""

import asyncio
import logging
from typing import Any, Literal

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CODE, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .auth import CannotConnect, InvalidAuth, async_login
from .const import (
    DEVICE_TYPE_GATEWAY,
    DEVICE_TYPES,
    DEVICES_URL,
    DOMAIN,
    HOME_ID,
    LIGHT_CONTROL_URL,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type FSLDevice = dict[str, Any]
type FSLControlConfig = dict[str, bool | int | str]


class FSLDataUpdateCoordinator(DataUpdateCoordinator[dict[int, FSLDevice]]):
    """Fetch device data from the FSL IoT cloud."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._entry = config_entry
        self._session = session
        self._token = config_entry.data[CONF_TOKEN]
        self._refresh_lock = asyncio.Lock()

    async def _async_refresh_token(self, rejected_token: str) -> None:
        """Renew and persist credentials once for concurrent expired requests."""
        async with self._refresh_lock:
            if self._token != rejected_token:
                return
            if not (code := self._entry.data.get(CONF_CODE)):
                raise InvalidAuth(
                    "Sign in once to save the code for automatic FSL token renewal"
                )
            token = await async_login(self._session, code)
            self.hass.config_entries.async_update_entry(
                self._entry, data={**self._entry.data, CONF_TOKEN: token}
            )
            self._token = token

    async def _async_request(
        self, method: Literal["get", "post"], url: str, **kwargs: Any
    ) -> Any:
        """Retry an explicitly rejected request once after renewing the token."""
        token = self._token
        try:
            return await self._async_request_once(method, url, token, **kwargs)
        except InvalidAuth:
            await self._async_refresh_token(token)
        return await self._async_request_once(method, url, self._token, **kwargs)

    async def _async_request_once(
        self, method: Literal["get", "post"], url: str, token: str, **kwargs: Any
    ) -> Any:
        """Send one request and distinguish expired credentials from cloud errors."""
        request = self._session.get if method == "get" else self._session.post
        async with request(
            url,
            headers={"Authorization": token},
            timeout=aiohttp.ClientTimeout(total=30),
            **kwargs,
        ) as response:
            if response.status in (401, 403):
                raise InvalidAuth("FSL rejected the access token")
            response.raise_for_status()
            try:
                result = await response.json(content_type=None)
            except ValueError:
                if method == "post":
                    return None
                raise
            if isinstance(result, dict) and result.get("code") == 1002:
                raise InvalidAuth("FSL rejected the access token")
            return result

    async def _async_update_data(self) -> dict[int, FSLDevice]:
        """Fetch supported devices from the FSL IoT cloud."""
        try:
            result = await self._async_request(
                "get", DEVICES_URL, params={"homeId": HOME_ID}
            )
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (CannotConnect, aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(
                f"Error communicating with the FSL IoT cloud: {err}"
            ) from err

        if (
            not isinstance(result, dict)
            or result.get("code") != 200
            or result.get("success") is False
            or not isinstance(result.get("data"), list)
        ):
            raise UpdateFailed("FSL IoT cloud returned an unsuccessful response")

        devices: dict[int, FSLDevice] = {}
        for device in result["data"]:
            if (
                not isinstance(device, dict)
                or str(device.get("devType")) not in DEVICE_TYPES
                or not isinstance(device.get("devId"), int)
            ):
                continue
            devices[device["devId"]] = device

        return devices

    async def async_control_light(
        self, device_id: int, config: list[FSLControlConfig]
    ) -> None:
        """Send a control command for a spotlight."""
        device = self.data[device_id]
        gateway = next(
            (
                candidate
                for candidate in self.data.values()
                if str(candidate.get("devType")) == DEVICE_TYPE_GATEWAY
                and candidate.get("roomId") == device.get("roomId")
            ),
            None,
        )
        if gateway is None:
            gateway = next(
                (
                    candidate
                    for candidate in self.data.values()
                    if str(candidate.get("devType")) == DEVICE_TYPE_GATEWAY
                ),
                None,
            )

        gateway_id = gateway.get("devD") if gateway else None
        light_id = device.get("devA")
        if not gateway_id or light_id is None:
            raise HomeAssistantError("FSL spotlight is missing gateway information")

        payload = {
            "action": "device",
            "gatewayId": gateway_id,
            "param": {
                "id": str(light_id),
                "config": config,
            },
        }

        try:
            result = await self._async_request("post", LIGHT_CONTROL_URL, json=payload)
        except InvalidAuth as err:
            self.async_set_update_error(err)
            self._entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                "FSL authentication failed; sign in again in the integration settings"
            ) from err
        except (CannotConnect, aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                f"Error communicating with the FSL IoT cloud: {err}"
            ) from err

        if isinstance(result, dict) and (
            result.get("success") is False or result.get("code") not in (None, 200)
        ):
            raise HomeAssistantError("FSL IoT cloud rejected the light command")

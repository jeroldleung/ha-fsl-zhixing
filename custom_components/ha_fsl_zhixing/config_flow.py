"""Config and options flows for the FSL integration."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr

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
)
from .transport import (
    FSLDiscoveredGateway,
    FSLTimeoutError,
    FSLTransportError,
    FSLUdpClient,
    async_discover_gateways,
    format_mac_bytes,
    parse_mac_bytes,
)

_LOGGER = logging.getLogger(__name__)


def _derive_probe_mac(client_mac: str) -> str:
    """Derive a distinct locally-administered MAC for config-flow validation."""
    raw = bytearray(parse_mac_bytes(client_mac))
    raw[0] = (raw[0] | 0x02) & 0xFE
    raw[5] ^= 0xFF
    return format_mac_bytes(bytes(raw))

CONF_GATEWAY = "gateway"
MANUAL_CHOICE = "manual"

MANUAL_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_UDP_PORT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Optional(CONF_CLIENT_MAC, default=DEFAULT_CLIENT_MAC): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_FADE_TRANSITION, default=DEFAULT_FADE_TRANSITION): bool,
        vol.Optional(CONF_FILTER_IGNORED, default=DEFAULT_FILTER_IGNORED): bool,
        vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): vol.All(
            vol.Coerce(int), vol.Any(0, vol.Range(min=30, max=86400))
        ),
    }
)


class FSLConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FSL."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize discovery state."""
        self._discovered_gateways: dict[str, FSLDiscoveredGateway] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FSLOptionsFlow:
        """Return the options flow handler."""
        return FSLOptionsFlow()

    async def _async_validate_connection(
        self, host: str, port: int, client_mac: str
    ) -> tuple[str, str]:
        """Verify UDP connectivity with the gateway and return (gateway_mac, client_mac).

        Uses a distinct locally-administered probe MAC so config-flow validation never
        registers or overwrites the real client_mac on a throwaway ephemeral UDP port.
        Tries unicast Type 1 Probe first and falls back to Type 3 Heartbeat on timeout.
        """
        normalized_client_mac = format_mac_bytes(parse_mac_bytes(client_mac))
        probe_mac = _derive_probe_mac(normalized_client_mac)
        client = FSLUdpClient(self.hass.loop, host, port, probe_mac)
        try:
            await client.async_connect()
            try:
                raw_gateway_mac = await client.async_probe()
            except FSLTimeoutError:
                _LOGGER.debug(
                    "Unicast Type 1 probe timed out for %s:%s; falling back to Type 3",
                    host,
                    port,
                )
                raw_gateway_mac = await client.async_heartbeat()
        finally:
            await client.async_close()
        return dr.format_mac(raw_gateway_mac), normalized_client_mac

    def _build_user_schema(self) -> vol.Schema:
        """Build gateway selection schema from discovered LAN gateways."""
        choices = {
            mac: f"{gw.ip} ({mac})" for mac, gw in self._discovered_gateways.items()
        }
        choices[MANUAL_CHOICE] = "Enter gateway manually"
        return vol.Schema({vol.Required(CONF_GATEWAY): vol.In(choices)})

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Discover FSL gateways over UDP broadcast or fall back to manual setup."""
        if user_input is None:
            gateways = await async_discover_gateways(self.hass.loop)
            if not gateways:
                return await self.async_step_manual()
            self._discovered_gateways = {gw.mac: gw for gw in gateways}
            return self.async_show_form(
                step_id="user",
                data_schema=self._build_user_schema(),
            )

        selected = user_input.get(CONF_GATEWAY)
        if selected == MANUAL_CHOICE or CONF_HOST in user_input:
            manual_input = user_input if CONF_HOST in user_input else None
            return await self.async_step_manual(manual_input)

        gw = self._discovered_gateways[selected]
        errors: dict[str, str] = {}
        try:
            gateway_mac, client_mac = await self._async_validate_connection(
                gw.ip, gw.port, DEFAULT_CLIENT_MAC
            )
        except FSLTransportError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error connecting to discovered FSL gateway")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(gateway_mac)
            self._abort_if_unique_id_configured(
                updates={
                    CONF_HOST: gw.ip,
                    CONF_PORT: gw.port,
                    CONF_CLIENT_MAC: client_mac,
                }
            )
            return self.async_create_entry(
                title="FSL",
                data={
                    CONF_HOST: gw.ip,
                    CONF_PORT: gw.port,
                    CONF_CLIENT_MAC: client_mac,
                    CONF_GATEWAY_MAC: gateway_mac,
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_user_schema(),
            errors=errors,
        )

    async def _async_handle_manual_form(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        suggested: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Validate manual gateway settings for setup or reconfiguration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            raw_client_mac = user_input.get(CONF_CLIENT_MAC) or DEFAULT_CLIENT_MAC
            try:
                gateway_mac, client_mac = await self._async_validate_connection(
                    host, port, raw_client_mac
                )
            except ValueError:
                errors[CONF_CLIENT_MAC] = "invalid_mac"
            except FSLTransportError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error connecting to FSL gateway")
                errors["base"] = "unknown"
            else:
                data = {
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_CLIENT_MAC: client_mac,
                    CONF_GATEWAY_MAC: gateway_mac,
                }
                await self.async_set_unique_id(gateway_mac)
                if step_id == "reconfigure":
                    self._abort_if_unique_id_mismatch(reason="unique_id_mismatch")
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(), data_updates=data
                    )
                self._abort_if_unique_id_configured(updates=data)
                return self.async_create_entry(title="FSL", data=data)

        schema = self.add_suggested_values_to_schema(
            MANUAL_DATA_SCHEMA, user_input or suggested
        )
        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual gateway IP, UDP port, and client MAC entry."""
        return await self._async_handle_manual_form("manual", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle updating gateway connection parameters."""
        return await self._async_handle_manual_form(
            "reconfigure",
            user_input,
            suggested=dict(self._get_reconfigure_entry().data),
        )


class FSLOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for FSL."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage FSL integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, self.config_entry.options
            ),
        )

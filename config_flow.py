"""Config flow for the FSL integration."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_CODE, CONF_TOKEN
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import CannotConnect, InvalidAuth, async_login
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_CODE): str})


class ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FSL."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        return await self._async_step_login("user", user_input)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Recover an expired session without replacing the config entry."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Save the code needed for future automatic token renewal."""
        return await self._async_step_login("reauth_confirm", user_input)

    async def _async_step_login(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Validate credentials for setup or reauthentication."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                token = await async_login(
                    async_get_clientsession(self.hass), user_input[CONF_CODE]
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                data = {CONF_CODE: user_input[CONF_CODE], CONF_TOKEN: token}
                if step_id == "reauth_confirm":
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates=data
                    )
                return self.async_create_entry(title="FSL", data=data)

        return self.async_show_form(
            step_id=step_id, data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

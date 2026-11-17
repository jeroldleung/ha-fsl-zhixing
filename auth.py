"""Authentication helpers for the FSL IoT cloud."""

import aiohttp

from .const import LOGIN_URL


class CannotConnect(Exception):
    """The FSL IoT cloud could not be reached."""


class InvalidAuth(Exception):
    """The FSL IoT cloud rejected the credentials."""


async def async_login(session: aiohttp.ClientSession, code: str) -> str:
    """Exchange the saved sign-in code for a new access token."""
    try:
        async with session.get(
            LOGIN_URL,
            params={"code": code},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status in (401, 403):
                raise InvalidAuth("FSL rejected the sign-in code")
            response.raise_for_status()
            result = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise CannotConnect("Could not refresh the FSL access token") from err

    if not isinstance(result, dict):
        raise CannotConnect("FSL returned an invalid login response")
    if result.get("code") in (1002, 5001):
        raise InvalidAuth("FSL rejected the sign-in code")
    if result.get("success") is False or result.get("code") != 200:
        raise CannotConnect("FSL login is temporarily unavailable")
    data = result.get("data")
    if not isinstance(data, dict):
        raise CannotConnect("FSL returned an invalid login response")
    token = data.get("token")
    if not isinstance(token, str) or not token:
        raise CannotConnect("FSL did not return an access token")
    return token

from __future__ import annotations

import asyncio
import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL, default="http://ha-intent-router.local:8000"): str,
        vol.Required(CONF_API_KEY): str,
    }
)


class HAIntentRouterConversationConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            api_key = user_input[CONF_API_KEY]

            error = await _validate_connection(self.hass, base_url, api_key)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title="HA Intent Router",
                    data={CONF_BASE_URL: base_url, CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


async def _validate_connection(hass, base_url: str, api_key: str) -> str | None:
    """Return an error key string on failure, or None on success.

    GET /health requires no auth on the router side, but we still pass the
    bearer token so the call is consistent with runtime requests and so that
    a 401 is surfaced immediately if the endpoint is ever protected.
    """
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{base_url}/health",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 401:
                return "invalid_auth"
            if resp.status != 200:
                _LOGGER.debug(
                    "ha-intent-router /health returned HTTP %s", resp.status
                )
                return "cannot_connect"
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _LOGGER.debug("ha-intent-router connection error: %s", err)
        return "cannot_connect"
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Unexpected error validating ha-intent-router: %s", err)
        return "unknown"
    return None

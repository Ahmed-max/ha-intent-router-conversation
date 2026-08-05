from __future__ import annotations

import asyncio
import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Behind verify_token (not require_admin_api): API-key auth resolves to
# role "service", which satisfies verify_token but would not satisfy
# require_admin_api. That makes this endpoint suitable for validating that
# a key authenticates at all, without requiring an admin-scoped key.
_AUTH_PROBE_PATH = "/entities/meta/areas"


def _schema_with_defaults(base_url: str = "http://ha-intent-router.local:8000", api_key: str = "") -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_BASE_URL, default=base_url): str,
            vol.Required(CONF_API_KEY, default=api_key): str,
        }
    )


STEP_USER_DATA_SCHEMA = _schema_with_defaults()


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/").lower()


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

            await self.async_set_unique_id(_normalize_base_url(base_url))
            self._abort_if_unique_id_configured()

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

    async def async_step_reconfigure(
        self, user_input: dict | None = None
    ) -> config_entries.FlowResult:
        reconfigure_entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            api_key = user_input[CONF_API_KEY]

            # Legacy entries created before unique_id support have none yet, so
            # there is nothing to mismatch-check against — backfill instead of
            # aborting. Entries that already have one are guarded so reconfigure
            # can't be repointed at an unrelated router.
            await self.async_set_unique_id(_normalize_base_url(base_url))
            if reconfigure_entry.unique_id is not None:
                self._abort_if_unique_id_mismatch()

            error = await _validate_connection(self.hass, base_url, api_key)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates={CONF_BASE_URL: base_url, CONF_API_KEY: api_key},
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema_with_defaults(
                reconfigure_entry.data[CONF_BASE_URL],
                reconfigure_entry.data[CONF_API_KEY],
            ),
            errors=errors,
        )


async def _validate_connection(hass, base_url: str, api_key: str) -> str | None:
    """Return an error key string on failure, or None on success.

    Two probes, so unreachable-router and bad-API-key stay distinguishable:
      1. GET /health, unauthenticated — confirms the router is reachable and
         is actually this service. /health has no auth on the router side, so
         it can never validate the key; a failure here means "cannot_connect".
      2. GET /entities/meta/areas, authenticated — behind verify_token, so a
         401 here means the key itself is bad ("invalid_auth"), not that the
         service is unreachable (already ruled out by step 1).
    """
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{base_url}/health",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
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

    try:
        async with session.get(
            f"{base_url}{_AUTH_PROBE_PATH}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 401:
                return "invalid_auth"
            if resp.status != 200:
                _LOGGER.debug(
                    "ha-intent-router %s returned HTTP %s", _AUTH_PROBE_PATH, resp.status
                )
                return "cannot_connect"
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        _LOGGER.debug("ha-intent-router connection error: %s", err)
        return "cannot_connect"
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Unexpected error validating ha-intent-router: %s", err)
        return "unknown"
    return None

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_CONTINUE_ON_CLARIFICATION,
    DEFAULT_CONTINUE_ON_CLARIFICATION,
    DOMAIN,
)

PLATFORMS = ["conversation"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        CONF_BASE_URL: entry.data[CONF_BASE_URL],
        CONF_API_KEY: entry.data[CONF_API_KEY],
        CONF_CONTINUE_ON_CLARIFICATION: entry.options.get(
            CONF_CONTINUE_ON_CLARIFICATION, DEFAULT_CONTINUE_ON_CLARIFICATION
        ),
    }
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload so a changed option reaches the conversation entity."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False

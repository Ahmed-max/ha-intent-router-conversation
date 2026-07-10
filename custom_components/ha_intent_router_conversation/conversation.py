from __future__ import annotations

import asyncio
import logging

import aiohttp

from homeassistant.components import conversation, intent
from homeassistant.components.conversation import MATCH_ALL
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN
from ._util import build_query_payload, parse_response_text, resolve_area

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    agent = HAIntentRouterConversationEntity(hass, config_entry)
    async_add_entities([agent])


class HAIntentRouterConversationEntity(conversation.ConversationEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass = hass
        self._config_entry = config_entry
        self._config: dict = hass.data[DOMAIN][config_entry.entry_id]
        self._attr_unique_id = config_entry.entry_id
        self._attr_name = config_entry.title

    @property
    def supported_languages(self) -> list[str] | str:
        return MATCH_ALL

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        conversation.async_set_agent(self.hass, self._config_entry, self)

    async def async_will_remove_from_hass(self) -> None:
        conversation.async_unset_agent(self.hass, self._config_entry)
        await super().async_will_remove_from_hass()

    async def _async_handle_message(
        self,
        user_input: conversation.ConversationInput,
        chat_log: conversation.ChatLog,
    ) -> conversation.ConversationResult:
        dev_reg = dr.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        area_id, area_name = resolve_area(user_input.device_id, dev_reg, area_reg)

        payload = build_query_payload(
            utterance=user_input.text,
            conversation_id=user_input.conversation_id,
            device_id=user_input.device_id,
            area_id=area_id,
            area_name=area_name,
        )

        base_url: str = self._config[CONF_BASE_URL]
        api_key: str = self._config[CONF_API_KEY]
        session = async_get_clientsession(self.hass)

        try:
            async with session.post(
                f"{base_url}/query",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("Error communicating with ha-intent-router: %s", err)
            return _error_result(
                user_input,
                "Unable to reach the intent router. Please check your connection.",
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Unexpected error from ha-intent-router: %s", err)
            return _error_result(user_input, "An unexpected error occurred.")

        reply_text = parse_response_text(data)

        try:
            # async_add_assistant_content_without_tools is a synchronous @callback
            # in HA — no await, no async for.
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id,
                    content=reply_text,
                )
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Error adding assistant content to chat log: %s", err)
            return _error_result(user_input, "An unexpected error occurred.")

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(reply_text)
        return conversation.ConversationResult(
            response=response,
            conversation_id=user_input.conversation_id,
            continue_conversation=False,
        )


def _error_result(
    user_input: conversation.ConversationInput,
    message: str,
) -> conversation.ConversationResult:
    response = intent.IntentResponse(language=user_input.language)
    response.async_set_error(
        intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
        message,
    )
    return conversation.ConversationResult(
        response=response,
        conversation_id=user_input.conversation_id,
        continue_conversation=False,
    )

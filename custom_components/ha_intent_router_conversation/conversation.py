from __future__ import annotations

import asyncio
import logging

import aiohttp

from homeassistant.components import conversation
from homeassistant.components.conversation import MATCH_ALL
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr, intent
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN
from ._util import (
    _reject_non_local_intent,
    build_query_payload,
    parse_response_text,
    parse_sse_data_line,
    resolve_area,
)

_LOGGER = logging.getLogger(__name__)


def _map_error_code(code: str | None) -> intent.IntentResponseErrorCode:
    """Map the router's error_code string to a real HA error code.

    Falls back to FAILED_TO_HANDLE for None or any unrecognized value, so a
    future router-side addition to the vocabulary doesn't crash this
    integration — it just degrades to the previous generic behavior.
    """
    if code is None:
        return intent.IntentResponseErrorCode.FAILED_TO_HANDLE
    try:
        return intent.IntentResponseErrorCode(code)
    except ValueError:
        return intent.IntentResponseErrorCode.FAILED_TO_HANDLE


# No total cap — a long streamed completion legitimately takes longer than any
# fixed total to finish generating. connect/sock_connect bound connection setup;
# sock_read is a per-chunk idle timeout that resets on every byte received, so it
# only fires on a genuine stall, not on total stream duration.
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(
    total=None,
    connect=10,
    sock_connect=10,
    sock_read=30,
)


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
        # Let HA's native intent system handle timers and media-transport first.
        # _reject_non_local_intent returns True (reject) for everything outside the
        # allowlist, so only those 17 intents ever execute here; everything else
        # falls through (local_response is None) and continues to the router below.
        local_response = await conversation.async_handle_intents(
            self.hass, user_input, chat_log,
            intent_filter=_reject_non_local_intent,
        )
        if local_response is not None:
            return conversation.ConversationResult(
                response=local_response,
                conversation_id=user_input.conversation_id,
                continue_conversation=False,
            )

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

        full_response = ""
        stream_error: str | None = None
        stream_error_code: str | None = None
        done_error_code: str | None = None

        try:
            async with session.post(
                f"{base_url}/query/stream",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=_REQUEST_TIMEOUT,
            ) as resp:
                resp.raise_for_status()

                async def _delta_stream():
                    """Yield AssistantContentDeltaDict items for each SSE "token" event.

                    "stage" events are logged at debug and never yielded/spoken.
                    "done" captures the router's full response text as the
                    source of truth (covers both the chat and non-chat done
                    shapes, which both carry a "response" key), plus its
                    optional "error_code" for soft semantic failures (e.g.
                    no_intent_match) — absent on an older router or on the
                    CHAT path, which never carries error_code by design.
                    "error" stops the stream and carries its own "code";
                    the outer handler checks stream_error after the
                    async-for completes.
                    """
                    nonlocal full_response, stream_error, stream_error_code, done_error_code
                    async for raw_line in resp.content:
                        event = parse_sse_data_line(raw_line.decode("utf-8"))
                        if event is None:
                            continue
                        event_type = event.get("type")
                        if event_type == "token":
                            text = event.get("text", "")
                            if text:
                                full_response += text
                                yield {"role": "assistant", "content": text}
                        elif event_type == "done":
                            full_response = parse_response_text(event) or full_response
                            done_error_code = event.get("error_code")
                        elif event_type == "error":
                            stream_error = event.get("message") or "Unknown stream error"
                            stream_error_code = event.get("code")
                            return
                        elif event_type == "stage":
                            _LOGGER.debug("ha-intent-router stage event: %s", event)

                # async_add_delta_content_stream is itself an async generator in
                # HA — must be consumed with "async for", not awaited.
                async for _ in chat_log.async_add_delta_content_stream(
                    user_input.agent_id, _delta_stream()
                ):
                    pass
        except aiohttp.ClientResponseError as err:
            if err.status in (401, 403):
                _LOGGER.error(
                    "ha-intent-router rejected our credentials: HTTP %s", err.status
                )
                return _error_result(
                    user_input,
                    "The intent router rejected my credentials. Please check the "
                    "API key in the integration settings.",
                )
            _LOGGER.error("Error communicating with ha-intent-router: %s", err)
            return _error_result(
                user_input,
                "Unable to reach the intent router. Please check your connection.",
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("Error communicating with ha-intent-router: %s", err)
            return _error_result(
                user_input,
                "Unable to reach the intent router. Please check your connection.",
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Unexpected error from ha-intent-router: %s", err)
            return _error_result(user_input, "An unexpected error occurred.")

        if stream_error:
            _LOGGER.error("ha-intent-router stream error: %s", stream_error)
            return _error_result(
                user_input,
                "Unable to reach the intent router. Please check your connection.",
                error_code=_map_error_code(stream_error_code),
            )

        if done_error_code:
            _LOGGER.debug("ha-intent-router soft failure: %s", done_error_code)
            response = intent.IntentResponse(language=user_input.language)
            response.async_set_error(_map_error_code(done_error_code), full_response)
            return conversation.ConversationResult(
                response=response,
                conversation_id=user_input.conversation_id,
                continue_conversation=False,
            )

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(full_response)
        return conversation.ConversationResult(
            response=response,
            conversation_id=user_input.conversation_id,
            continue_conversation=False,
        )


def _error_result(
    user_input: conversation.ConversationInput,
    message: str,
    error_code: intent.IntentResponseErrorCode = intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
) -> conversation.ConversationResult:
    response = intent.IntentResponse(language=user_input.language)
    response.async_set_error(
        error_code,
        message,
    )
    return conversation.ConversationResult(
        response=response,
        conversation_id=user_input.conversation_id,
        continue_conversation=False,
    )

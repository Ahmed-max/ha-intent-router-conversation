"""Unit tests for conversation.py: error-code mapping and NATIVE intent delegation.

conversation.py needs a real (HA import) `intent` module, so conftest.py stubs
homeassistant.helpers.intent with a StrEnum matching the real
IntentResponseErrorCode values exactly, rather than a MagicMock that would
never raise ValueError on an unrecognized value.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import IntentHandleError, IntentResponseErrorCode, MatchFailedError
from custom_components.ha_intent_router_conversation.const import CONF_API_KEY, CONF_BASE_URL
from custom_components.ha_intent_router_conversation.conversation import (
    _map_error_code,
)


def test_map_error_code_none_falls_back_to_failed_to_handle():
    assert _map_error_code(None) is IntentResponseErrorCode.FAILED_TO_HANDLE


@pytest.mark.parametrize(
    "code,expected",
    [
        ("no_intent_match", IntentResponseErrorCode.NO_INTENT_MATCH),
        ("no_valid_targets", IntentResponseErrorCode.NO_VALID_TARGETS),
        ("failed_to_handle", IntentResponseErrorCode.FAILED_TO_HANDLE),
        ("unknown", IntentResponseErrorCode.UNKNOWN),
    ],
)
def test_map_error_code_recognized_values(code, expected):
    assert _map_error_code(code) is expected


def test_map_error_code_unrecognized_value_falls_back_to_failed_to_handle():
    """An unrecognized string must degrade gracefully, not raise."""
    assert _map_error_code("garbage_unknown_value") is IntentResponseErrorCode.FAILED_TO_HANDLE


def test_map_error_code_empty_string_falls_back_to_failed_to_handle():
    assert _map_error_code("") is IntentResponseErrorCode.FAILED_TO_HANDLE


# ---------------------------------------------------------------------------
# NATIVE intent delegation (_async_handle_message end-to-end, HA stubbed)
# ---------------------------------------------------------------------------

class _Lines:
    def __init__(self, events):
        self._lines = [f"data: {json.dumps(e)}\n".encode() for e in events]

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for line in self._lines:
            yield line


class _StreamResponse:
    def __init__(self, events):
        self.content = _Lines(events)

    def raise_for_status(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeSession:
    def __init__(self, events):
        self._events = events

    def post(self, *args, **kwargs):
        return _StreamResponse(self._events)


class _FakeChatLog:
    """Records what the stream and the handler add, like HA's ChatLog would.

    Like the real async_add_delta_content_stream, zero deltas add nothing.
    """

    def __init__(self):
        self.streamed_deltas = []
        self.added = []

    async def async_add_delta_content_stream(self, agent_id, stream):
        async for delta in stream:
            self.streamed_deltas.append(delta)
            yield delta

    def async_add_assistant_content_without_tools(self, content):
        self.added.append(content)


class _AssistantContent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _intent_response(speech):
    response = MagicMock()
    response.speech = {"plain": {"speech": speech, "extra_data": None}}
    return response


def _make_async_handle(result=None, raises=None, with_satellite_id=True):
    """A stand-in with the real upstream keyword signature (so inspect.signature
    sees exactly what the installed HA would expose), recording each call."""
    calls = []

    if with_satellite_id:
        async def async_handle(hass, platform, intent_type, slots=None, text_input=None,
                               context=None, language=None, assistant=None,
                               device_id=None, satellite_id=None,
                               conversation_agent_id=None):
            calls.append(dict(locals()))
            if raises:
                raise raises
            return result
    else:
        async def async_handle(hass, platform, intent_type, slots=None, text_input=None,
                               context=None, language=None, assistant=None,
                               device_id=None, conversation_agent_id=None):
            calls.append(dict(locals()))
            if raises:
                raise raises
            return result

    return async_handle, calls


def _run(conv_mod, events, async_handle):
    entity = object.__new__(conv_mod.HAIntentRouterConversationEntity)
    entity.hass = MagicMock()
    entity._config = {CONF_BASE_URL: "http://router.local:8000", CONF_API_KEY: "sekret"}

    user_input = MagicMock()
    user_input.text = "set a timer for an hour and a half"
    user_input.conversation_id = "conv-1"
    user_input.device_id = "satellite-device-1"
    user_input.satellite_id = "assist_satellite.kitchen"
    user_input.language = "en"
    user_input.agent_id = "agent-1"

    chat_log = _FakeChatLog()

    async def run():
        with patch.object(
            conv_mod.conversation, "async_handle_intents", new=AsyncMock(return_value=None)
        ), patch.object(
            conv_mod, "async_get_clientsession", return_value=_FakeSession(events)
        ), patch.object(
            conv_mod.conversation, "AssistantContent", new=_AssistantContent
        ), patch.object(
            conv_mod, "resolve_area", return_value=(None, None)
        ), patch.object(conv_mod.intent, "async_handle", new=async_handle, create=True):
            return await entity._async_handle_message(user_input, chat_log)

    return asyncio.run(run()), user_input, chat_log


_NATIVE_DONE = {
    "type": "done",
    "response": "Handing to Home Assistant: start timer.",
    "error_code": None,
    "native_intent": {"intent": "HassStartTimer", "slots": {"hours": 1, "minutes": 30}},
}


def test_native_intent_executed_with_device_and_slots(conv_mod):
    ha_response = _intent_response("Timer started for 1 hour and 30 minutes")
    async_handle, calls = _make_async_handle(result=ha_response)

    result, user_input, _ = _run(
        conv_mod, [{"type": "stage", "stage": "native"}, _NATIVE_DONE], async_handle
    )

    assert len(calls) == 1
    call = calls[0]
    assert call["platform"] == conv_mod.DOMAIN
    assert call["intent_type"] == "HassStartTimer"
    assert call["slots"] == {"hours": {"value": 1}, "minutes": {"value": 30}}
    assert call["device_id"] == "satellite-device-1"
    assert call["satellite_id"] == "assist_satellite.kitchen"
    assert call["text_input"] == user_input.text
    assert call["context"] is user_input.context
    assert call["language"] == "en"
    assert call["assistant"] == conv_mod.conversation.DOMAIN
    assert call["conversation_agent_id"] == "agent-1"

    assert result.response is ha_response
    assert result.conversation_id == "conv-1"
    assert result.continue_conversation is False


def test_native_intent_chat_log_gets_exactly_one_assistant_message(conv_mod):
    async_handle, _ = _make_async_handle(result=_intent_response("Timer started"))

    _, _, chat_log = _run(conv_mod, [_NATIVE_DONE], async_handle)

    assert chat_log.streamed_deltas == []
    assert len(chat_log.added) == 1
    assert chat_log.added[0].content == "Timer started"
    assert chat_log.added[0].agent_id == "agent-1"


def test_native_intent_fallback_text_is_never_spoken(conv_mod):
    async_handle, _ = _make_async_handle(result=_intent_response("Timer started"))

    with patch.object(conv_mod.intent, "IntentResponse") as response_cls:
        result, _, chat_log = _run(conv_mod, [_NATIVE_DONE], async_handle)

    response_cls.assert_not_called()
    assert "Handing to Home Assistant" not in chat_log.added[0].content


def test_native_intent_omits_satellite_id_when_ha_signature_lacks_it(conv_mod):
    async_handle, calls = _make_async_handle(
        result=_intent_response("ok"), with_satellite_id=False
    )

    _run(conv_mod, [_NATIVE_DONE], async_handle)

    assert len(calls) == 1
    assert "satellite_id" not in calls[0]
    assert calls[0]["device_id"] == "satellite-device-1"


@pytest.mark.parametrize(
    "err,expected_speech",
    [
        (IntentHandleError("Device does not support timers: device_id=x", "no_timer_support"),
         "Timers aren't supported on this device."),
        (IntentHandleError("Timer not found", "timer_not_found"), "I couldn't find that timer."),
        (MatchFailedError(), "Sorry, I couldn't do that."),
    ],
)
def test_native_intent_errors_become_error_results(conv_mod, err, expected_speech):
    async_handle, _ = _make_async_handle(raises=err)

    with patch.object(conv_mod.intent, "IntentResponse") as response_cls:
        response = response_cls.return_value
        response.speech = {"plain": {"speech": expected_speech}}
        result, _, chat_log = _run(conv_mod, [_NATIVE_DONE], async_handle)

    response.async_set_error.assert_called_once_with(
        IntentResponseErrorCode.FAILED_TO_HANDLE, expected_speech
    )
    assert result.response is response
    assert [c.content for c in chat_log.added] == [expected_speech]


def test_disallowed_native_intent_is_never_executed(conv_mod):
    """Router isn't trusted: an intent outside _LOCAL_INTENTS falls back to normal handling."""
    async_handle, calls = _make_async_handle(result=_intent_response("x"))
    done = dict(_NATIVE_DONE, native_intent={"intent": "HassTurnOn", "slots": {}})

    with patch.object(conv_mod.intent, "IntentResponse") as response_cls:
        _run(conv_mod, [done], async_handle)

    assert calls == []
    response_cls.return_value.async_set_speech.assert_called_once_with(done["response"])


@pytest.mark.parametrize("extra", [{}, {"native_intent": None}])
def test_no_native_intent_keeps_existing_behavior(conv_mod, extra):
    async_handle, calls = _make_async_handle(result=_intent_response("x"))
    events = [
        {"type": "token", "text": "Hello"},
        {"type": "token", "text": " there"},
        {"type": "done", "response": "Hello there", "error_code": None, **extra},
    ]

    with patch.object(conv_mod.intent, "IntentResponse") as response_cls:
        _, _, chat_log = _run(conv_mod, events, async_handle)

    assert calls == []
    assert chat_log.added == []
    assert len(chat_log.streamed_deltas) == 2
    response_cls.return_value.async_set_speech.assert_called_once_with("Hello there")


def test_tokens_stream_as_one_chat_log_message(conv_mod):
    """Only the first delta carries "role" — HA's ChatLog starts a new message on
    every delta that has one, so a role per token split replies per token."""
    async_handle, _ = _make_async_handle(result=_intent_response("x"))
    events = [
        {"type": "token", "text": "Hello"},
        {"type": "token", "text": " there"},
        {"type": "token", "text": "!"},
        {"type": "done", "response": "Hello there!", "error_code": None},
    ]

    _, _, chat_log = _run(conv_mod, events, async_handle)

    assert chat_log.streamed_deltas == [
        {"role": "assistant", "content": "Hello"},
        {"content": " there"},
        {"content": "!"},
    ]


def test_stream_error_wins_over_native_intent(conv_mod):
    """A stream error still short-circuits before any native execution."""
    async_handle, calls = _make_async_handle(result=_intent_response("x"))
    events = [_NATIVE_DONE, {"type": "error", "message": "boom", "code": None}]

    _run(conv_mod, events, async_handle)

    assert calls == []

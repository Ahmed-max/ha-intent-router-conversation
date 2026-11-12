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
from custom_components.ha_intent_router_conversation.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_CONTINUE_ON_CLARIFICATION,
)
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
        self.posted_json = []

    def post(self, *args, json=None, **kwargs):
        self.posted_json.append(json)
        return _StreamResponse(self._events)


# HA assigns the ChatLog's id before the agent runs (a ULID on a fresh
# conversation), even while ConversationInput.conversation_id is still None.
CHAT_LOG_ID = "01JCHATLOGCONVERSATIONID00"


class _FakeChatLog:
    """Records what the stream and the handler add, like HA's ChatLog would.

    Like the real async_add_delta_content_stream, zero deltas add nothing.
    """

    def __init__(self, conversation_id=None):
        self.conversation_id = conversation_id or CHAT_LOG_ID
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


def _run(conv_mod, events, async_handle, *, config=None, input_conversation_id=None,
         session=None):
    entity = object.__new__(conv_mod.HAIntentRouterConversationEntity)
    entity.hass = MagicMock()
    entity._config = {
        CONF_BASE_URL: "http://router.local:8000",
        CONF_API_KEY: "sekret",
        **(config or {}),
    }
    session = session or _FakeSession(events)

    user_input = MagicMock()
    user_input.text = "set a timer for an hour and a half"
    # None by default, as HA before core PR #188909 passes on a first turn.
    user_input.conversation_id = input_conversation_id
    user_input.device_id = "satellite-device-1"
    user_input.satellite_id = "assist_satellite.kitchen"
    user_input.language = "en"
    user_input.agent_id = "agent-1"

    chat_log = _FakeChatLog()

    async def run():
        with patch.object(
            conv_mod.conversation, "async_handle_intents", new=AsyncMock(return_value=None)
        ), patch.object(
            conv_mod, "async_get_clientsession", return_value=session
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
    assert result.conversation_id == CHAT_LOG_ID
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


class _SilentIntentResponse:
    """Like the real IntentResponse a timer handler returns: no speech, maybe speech_slots."""

    def __init__(self, speech_slots=None):
        self.speech = {}
        self.speech_slots = speech_slots or {}

    def async_set_speech(self, speech):
        self.speech = {"plain": {"speech": speech, "extra_data": None}}


def test_native_intent_without_ha_speech_gets_spoken_confirmation(conv_mod):
    ha_response = _SilentIntentResponse()
    async_handle, _ = _make_async_handle(result=ha_response)

    result, _, chat_log = _run(conv_mod, [_NATIVE_DONE], async_handle)

    expected = "Timer set for 1 hour and 30 minutes."
    assert result.response is ha_response
    assert result.response.speech["plain"]["speech"] == expected
    assert [c.content for c in chat_log.added] == [expected]


def test_native_intent_keeps_speech_ha_already_provided(conv_mod):
    ha_response = _intent_response("Timer started")
    async_handle, _ = _make_async_handle(result=ha_response)

    _, _, chat_log = _run(conv_mod, [_NATIVE_DONE], async_handle)

    ha_response.async_set_speech.assert_not_called()
    assert [c.content for c in chat_log.added] == ["Timer started"]


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


# ---------------------------------------------------------------------------
# session_id contract: the ChatLog's conversation_id, sent and returned
# ---------------------------------------------------------------------------

_CHAT_DONE = [
    {"type": "token", "text": "Hi"},
    {"type": "done", "response": "Hi", "error_code": None, "intent_type": "CHAT"},
]


@pytest.mark.parametrize("input_conversation_id", [None, CHAT_LOG_ID])
def test_session_id_is_chat_log_conversation_id(conv_mod, input_conversation_id):
    async_handle, _ = _make_async_handle()
    session = _FakeSession(_CHAT_DONE)

    result, _, _ = _run(
        conv_mod, _CHAT_DONE, async_handle,
        input_conversation_id=input_conversation_id, session=session,
    )

    assert [p["session_id"] for p in session.posted_json] == [CHAT_LOG_ID]
    assert result.conversation_id == CHAT_LOG_ID


def test_local_intent_result_returns_chat_log_conversation_id(conv_mod):
    entity = object.__new__(conv_mod.HAIntentRouterConversationEntity)
    entity.hass = MagicMock()
    entity._config = {CONF_BASE_URL: "http://router.local:8000", CONF_API_KEY: "sekret"}
    user_input = MagicMock()
    user_input.conversation_id = None
    local_response = MagicMock()

    async def run():
        with patch.object(
            conv_mod.conversation, "async_handle_intents",
            new=AsyncMock(return_value=local_response),
        ):
            return await entity._async_handle_message(user_input, _FakeChatLog())

    result = asyncio.run(run())

    assert result.response is local_response
    assert result.conversation_id == CHAT_LOG_ID
    assert result.continue_conversation is False


def test_stream_error_result_returns_chat_log_conversation_id(conv_mod):
    async_handle, _ = _make_async_handle()
    events = [{"type": "error", "message": "boom", "code": None}]

    result, _, _ = _run(conv_mod, events, async_handle)

    assert result.conversation_id == CHAT_LOG_ID


def test_native_intent_error_returns_chat_log_conversation_id(conv_mod):
    async_handle, _ = _make_async_handle(raises=MatchFailedError())

    with patch.object(conv_mod.intent, "IntentResponse") as response_cls:
        response_cls.return_value.speech = {"plain": {"speech": "x"}}
        result, _, _ = _run(conv_mod, [_NATIVE_DONE], async_handle)

    assert result.conversation_id == CHAT_LOG_ID


# ---------------------------------------------------------------------------
# continue_conversation on a router clarification (opt-in)
# ---------------------------------------------------------------------------

def _clarification_done(intent_type, error_code=None):
    return {
        "type": "done",
        "response": "Which light do you mean?",
        "error_code": error_code,
        "intent_type": intent_type,
    }


@pytest.mark.parametrize(
    "done",
    [
        _clarification_done("ambiguous_target"),
        _clarification_done("ambiguous"),
        _clarification_done("low_confidence", error_code="no_intent_match"),
    ],
)
def test_clarification_continues_conversation_when_enabled(conv_mod, done):
    async_handle, _ = _make_async_handle()

    result, _, _ = _run(
        conv_mod, [done], async_handle, config={CONF_CONTINUE_ON_CLARIFICATION: True}
    )

    assert result.continue_conversation is True
    assert result.conversation_id == CHAT_LOG_ID


@pytest.mark.parametrize("config", [{}, {CONF_CONTINUE_ON_CLARIFICATION: False}])
def test_clarification_does_not_continue_by_default(conv_mod, config):
    async_handle, _ = _make_async_handle()

    result, _, _ = _run(
        conv_mod, [_clarification_done("ambiguous_target")], async_handle, config=config
    )

    assert result.continue_conversation is False


def test_answered_turn_never_continues_even_when_enabled(conv_mod):
    async_handle, _ = _make_async_handle()

    result, _, _ = _run(
        conv_mod, _CHAT_DONE, async_handle, config={CONF_CONTINUE_ON_CLARIFICATION: True}
    )

    assert result.continue_conversation is False


def test_clarification_soft_error_still_reports_error(conv_mod):
    async_handle, _ = _make_async_handle()
    done = _clarification_done("low_confidence", error_code="no_intent_match")

    with patch.object(conv_mod.intent, "IntentResponse") as response_cls:
        result, _, _ = _run(
            conv_mod, [done], async_handle, config={CONF_CONTINUE_ON_CLARIFICATION: True}
        )

    response_cls.return_value.async_set_error.assert_called_once_with(
        IntentResponseErrorCode.NO_INTENT_MATCH, done["response"]
    )
    response_cls.return_value.async_set_speech.assert_not_called()
    assert result.continue_conversation is True

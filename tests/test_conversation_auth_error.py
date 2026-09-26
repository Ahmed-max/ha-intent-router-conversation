"""Unit test for conversation.py's HTTP 401/403 branch (commit 2 of AUDIT_2026-08-04.md #15).

The entity class body executes `class HAIntentRouterConversationEntity(conversation.ConversationEntity)`
at import time. conftest.py stubs `homeassistant.components.conversation` as a bare
MagicMock(), and a MagicMock *instance* used as a base class collapses the whole
class statement into another MagicMock instead of a real type — so the module's
own instance of that class can't be built normally. To exercise the real
`_async_handle_message` method body, this test swaps in a plain subclassable stand-in
for `ConversationEntity` and reloads the module fresh, then builds the entity with
`object.__new__` (skipping `__init__`, which needs a full config-entry/hass setup this
test doesn't need) and sets only the attributes `_async_handle_message` actually reads.
The reload itself lives in conftest.py's `conv_mod` fixture.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.ha_intent_router_conversation.const import CONF_API_KEY, CONF_BASE_URL


class _RaisingResponse:
    def __init__(self, status: int):
        self.status = status

    def raise_for_status(self):
        raise aiohttp.ClientResponseError(
            request_info=MagicMock(), history=(), status=self.status, message="boom"
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeSession:
    def __init__(self, status: int):
        self._status = status

    def post(self, *args, **kwargs):
        return _RaisingResponse(self._status)


def _make_entity(conv_mod, session):
    entity = object.__new__(conv_mod.HAIntentRouterConversationEntity)
    entity.hass = MagicMock()
    entity._config = {CONF_BASE_URL: "http://router.local:8000", CONF_API_KEY: "sekret"}

    user_input = MagicMock()
    user_input.text = "turn on the lights"
    user_input.conversation_id = "conv-1"
    user_input.device_id = None
    user_input.language = "en"
    user_input.agent_id = "agent-1"

    chat_log = MagicMock()

    async def run():
        with patch.object(
            conv_mod.conversation, "async_handle_intents", new=AsyncMock(return_value=None)
        ), patch.object(conv_mod, "async_get_clientsession", return_value=session):
            return await entity._async_handle_message(user_input, chat_log)

    return asyncio.run(run())


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_gets_its_own_message_and_error_code(conv_mod, status):
    result = _make_entity(conv_mod, _FakeSession(status))

    assert (
        result.response.async_set_error.call_args.args[0]
        is conv_mod.intent.IntentResponseErrorCode.FAILED_TO_HANDLE
    )
    message = result.response.async_set_error.call_args.args[1]
    assert "credentials" in message
    assert "API key" in message
    assert "connection" not in message.lower()


def test_other_client_errors_still_get_connectivity_message(conv_mod):
    result = _make_entity(conv_mod, _FakeSession(500))

    message = result.response.async_set_error.call_args.args[1]
    assert "connection" in message.lower()
    assert "credentials" not in message.lower()

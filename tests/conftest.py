"""Stub out homeassistant before any custom_component module is imported."""
import enum
import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_HA_MODULES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.conversation",
    "homeassistant.components.intent",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.area_registry",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.restore_state",
]

for _mod in _HA_MODULES:
    sys.modules.setdefault(_mod, MagicMock())


class IntentResponseErrorCode(str, enum.Enum):
    """Mirrors the real homeassistant.helpers.intent.IntentResponseErrorCode
    StrEnum values exactly (verified against the installed/upstream HA source),
    so _map_error_code's real-vs-fallback behavior is exercised faithfully
    instead of against a MagicMock that would never raise ValueError."""

    NO_INTENT_MATCH = "no_intent_match"
    NO_VALID_TARGETS = "no_valid_targets"
    FAILED_TO_HANDLE = "failed_to_handle"
    UNKNOWN = "unknown"


_fake_intent_module = ModuleType("homeassistant.helpers.intent")
_fake_intent_module.IntentResponseErrorCode = IntentResponseErrorCode
_fake_intent_module.IntentResponse = MagicMock()


# Real exception hierarchy (mirrors homeassistant/helpers/intent.py) so
# conversation.py's `except intent.IntentError` clause is exercised faithfully.
class IntentError(Exception):
    pass


class IntentHandleError(IntentError):
    def __init__(self, message: str = "", response_key: str | None = None) -> None:
        super().__init__(message)
        self.response_key = response_key


class MatchFailedError(IntentError):
    pass


_fake_intent_module.IntentError = IntentError
_fake_intent_module.IntentHandleError = IntentHandleError
_fake_intent_module.MatchFailedError = MatchFailedError

# A MagicMock parent ("homeassistant.helpers") auto-generates its own `.intent`
# attribute on getattr, ignoring whatever's registered under the dotted key in
# sys.modules — so the attribute must be set explicitly on the parent too.
sys.modules["homeassistant.helpers.intent"] = _fake_intent_module
sys.modules["homeassistant.helpers"].intent = _fake_intent_module


@pytest.fixture
def conv_mod():
    """Reload conversation.py with a real, subclassable ConversationEntity stand-in."""
    # conversation.py does `from homeassistant.components import conversation`. Since
    # `homeassistant.components` is itself a MagicMock, that IMPORT_FROM binds to the
    # auto-vivified `.conversation` *attribute* of that mock (getattr never raises
    # AttributeError on a MagicMock, so Python's import machinery never falls back to
    # sys.modules["homeassistant.components.conversation"] — that sys.modules entry is
    # a decoy nothing actually reads). So the object to patch is the attribute, not the
    # sys.modules entry.
    components_pkg = sys.modules["homeassistant.components"]
    conversation_attr = components_pkg.conversation
    original_entity_base = conversation_attr.ConversationEntity
    original_result = conversation_attr.ConversationResult

    class _RealConversationEntityBase:
        pass

    class _RealConversationResult:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    conversation_attr.ConversationEntity = _RealConversationEntityBase
    conversation_attr.ConversationResult = _RealConversationResult
    sys.modules.pop("custom_components.ha_intent_router_conversation.conversation", None)
    try:
        module = importlib.import_module(
            "custom_components.ha_intent_router_conversation.conversation"
        )
        yield module
    finally:
        conversation_attr.ConversationEntity = original_entity_base
        conversation_attr.ConversationResult = original_result
        sys.modules.pop("custom_components.ha_intent_router_conversation.conversation", None)

"""Stub out homeassistant before any custom_component module is imported."""
import enum
import sys
from types import ModuleType
from unittest.mock import MagicMock

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

# A MagicMock parent ("homeassistant.helpers") auto-generates its own `.intent`
# attribute on getattr, ignoring whatever's registered under the dotted key in
# sys.modules — so the attribute must be set explicitly on the parent too.
sys.modules["homeassistant.helpers.intent"] = _fake_intent_module
sys.modules["homeassistant.helpers"].intent = _fake_intent_module

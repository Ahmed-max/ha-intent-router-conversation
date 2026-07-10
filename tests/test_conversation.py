"""Unit tests for conversation.py's pure error-code mapping logic.

conversation.py needs a real (HA import) `intent` module, so conftest.py stubs
homeassistant.helpers.intent with a StrEnum matching the real
IntentResponseErrorCode values exactly, rather than a MagicMock that would
never raise ValueError on an unrecognized value.
"""
import pytest

from tests.conftest import IntentResponseErrorCode
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

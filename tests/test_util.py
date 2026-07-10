"""Unit tests for _util.py — no HA imports, plain pytest."""
from unittest.mock import MagicMock

import pytest

from custom_components.ha_intent_router_conversation._util import (
    build_query_payload,
    parse_response_text,
    resolve_area,
)


# ---------------------------------------------------------------------------
# build_query_payload
# ---------------------------------------------------------------------------

def test_payload_text_medium_when_no_device():
    payload = build_query_payload(
        utterance="what is the temperature",
        conversation_id="sess-abc",
        device_id=None,
        area_id=None,
        area_name=None,
    )
    assert payload["utterance"] == "what is the temperature"
    assert payload["session_id"] == "sess-abc"
    assert payload["medium"] == "text"
    assert payload["source"] == "text"
    assert payload["satellite_id"] is None
    assert payload["satellite_area_id"] is None
    assert payload["satellite_area_name"] is None


def test_payload_voice_medium_when_device_present():
    payload = build_query_payload(
        utterance="turn on the lights",
        conversation_id="sess-xyz",
        device_id="media_player.bedroom_speaker",
        area_id="area_bedroom",
        area_name="Bedroom",
    )
    assert payload["medium"] == "voice"
    assert payload["source"] == "voice"
    assert payload["satellite_id"] == "media_player.bedroom_speaker"
    assert payload["satellite_area_id"] == "area_bedroom"
    assert payload["satellite_area_name"] == "Bedroom"


def test_payload_voice_medium_no_area():
    """Device present but area not resolved — area fields must be None."""
    payload = build_query_payload(
        utterance="dim the lights",
        conversation_id="sess-1",
        device_id="some_device_id",
        area_id=None,
        area_name=None,
    )
    assert payload["medium"] == "voice"
    assert payload["satellite_id"] == "some_device_id"
    assert payload["satellite_area_id"] is None
    assert payload["satellite_area_name"] is None


def test_payload_session_id_none():
    """None conversation_id is passed through (router accepts null session_id)."""
    payload = build_query_payload(
        utterance="hello",
        conversation_id=None,
        device_id=None,
        area_id=None,
        area_name=None,
    )
    assert payload["session_id"] is None


# ---------------------------------------------------------------------------
# parse_response_text
# ---------------------------------------------------------------------------

def test_parse_response_text_happy_path():
    data = {
        "mode": "ha_control",
        "response": "Done! The bedroom light is now on.",
        "entities_used": ["light.bedroom"],
        "confidence": 1.0,
        "clarification_needed": False,
        "latency_ms": 240,
        "slots": {},
    }
    assert parse_response_text(data) == "Done! The bedroom light is now on."


def test_parse_response_text_empty_string():
    assert parse_response_text({"response": ""}) == ""


def test_parse_response_text_missing_key():
    """Missing 'response' key falls back to empty string — never raises."""
    assert parse_response_text({}) == ""
    assert parse_response_text({"mode": "chat"}) == ""


def test_parse_response_text_ignores_other_fields():
    data = {"response": "hello", "mode": "chat", "confidence": 0.9}
    assert parse_response_text(data) == "hello"


# ---------------------------------------------------------------------------
# resolve_area
# ---------------------------------------------------------------------------

def test_resolve_area_no_device():
    hass = MagicMock()
    result = resolve_area(None, hass, hass)
    assert result == (None, None)


def test_resolve_area_device_not_found():
    dev_reg = MagicMock()
    dev_reg.async_get.return_value = None
    area_reg = MagicMock()

    result = resolve_area("ghost_device", dev_reg, area_reg)
    assert result == (None, None)
    area_reg.async_get_area.assert_not_called()


def test_resolve_area_device_has_no_area():
    dev_reg = MagicMock()
    device = MagicMock()
    device.area_id = None
    dev_reg.async_get.return_value = device
    area_reg = MagicMock()

    result = resolve_area("device_123", dev_reg, area_reg)
    assert result == (None, None)
    area_reg.async_get_area.assert_not_called()


def test_resolve_area_area_not_found_in_registry():
    """Device has area_id but the area is absent from the registry — return area_id, None."""
    dev_reg = MagicMock()
    device = MagicMock()
    device.area_id = "area_orphan"
    dev_reg.async_get.return_value = device

    area_reg = MagicMock()
    area_reg.async_get_area.return_value = None

    area_id, area_name = resolve_area("device_abc", dev_reg, area_reg)
    assert area_id == "area_orphan"
    assert area_name is None


def test_resolve_area_full_resolution():
    dev_reg = MagicMock()
    device = MagicMock()
    device.area_id = "area_living_room"
    dev_reg.async_get.return_value = device

    area_reg = MagicMock()
    area = MagicMock()
    area.id = "area_living_room"
    area.name = "Living Room"
    area_reg.async_get_area.return_value = area

    area_id, area_name = resolve_area("device_satellite_lr", dev_reg, area_reg)
    assert area_id == "area_living_room"
    assert area_name == "Living Room"
    dev_reg.async_get.assert_called_once_with("device_satellite_lr")
    area_reg.async_get_area.assert_called_once_with("area_living_room")

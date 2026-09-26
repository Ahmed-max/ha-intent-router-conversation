"""Pure utility functions with no HA dependencies — easy to unit-test."""
from __future__ import annotations

import json

# Timer intents: homeassistant/helpers/intent.py (INTENT_START_TIMER et al.)
# Media transport intents: homeassistant/components/media_player/const.py
# (INTENT_MEDIA_PAUSE et al.)
# Keep these as literal strings — the HA constants map 1:1 and this avoids
# an import-time HA dependency in test and production alike.
_LOCAL_INTENTS: frozenset[str] = frozenset({
    "HassStartTimer",
    "HassCancelTimer",
    "HassCancelAllTimers",
    "HassIncreaseTimer",
    "HassDecreaseTimer",
    "HassPauseTimer",
    "HassUnpauseTimer",
    "HassTimerStatus",
    "HassMediaPause",
    "HassMediaUnpause",
    "HassMediaNext",
    "HassMediaPrevious",
    "HassMediaPlayerMute",
    "HassMediaPlayerUnmute",
    "HassSetVolume",
    "HassSetVolumeRelative",
    "HassMediaSearchAndPlay",
    # Date/time intents:
    "HassGetCurrentDate",
    "HassGetCurrentTime",
})


def _reject_non_local_intent(result) -> bool:
    """Return True to reject (exclude) intents that should fall through to the router.

    async_handle_intents uses an exclude-filter polarity: True = no match (reject),
    False = proceed with native HA execution (accept). We only allow the timer and
    media-transport intents listed in _LOCAL_INTENTS to execute natively.
    """
    return result.intent.name not in _LOCAL_INTENTS


def build_query_payload(
    utterance: str,
    conversation_id: str | None,
    device_id: str | None,
    area_id: str | None,
    area_name: str | None,
) -> dict:
    """Build the JSON payload for POST /query.

    medium/source follows the router's convention: "voice" for satellite-originated
    requests (device_id is set), "text" for everything else.
    """
    medium = "voice" if device_id is not None else "text"
    return {
        "utterance": utterance,
        "session_id": conversation_id,
        "source": medium,
        "medium": medium,
        "satellite_id": device_id,
        "satellite_area_id": area_id,
        "satellite_area_name": area_name,
    }


def parse_response_text(data: dict) -> str:
    """Extract the spoken reply from a QueryResponse dict.

    The router returns {"response": "<text>", ...}; fall back to empty string
    so callers always get a str.
    """
    return data.get("response", "")


def parse_sse_data_line(line: str) -> dict | None:
    """Parse one line of an SSE stream, returning the decoded JSON payload.

    ha-intent-router's /query/stream emits events as "data: {json}\\n\\n" with no
    "event:" line — the event type is a "type" key inside the JSON payload itself.
    Returns None for blank lines, non-"data:" lines, or a payload that isn't valid
    JSON/isn't a JSON object, so callers can skip them without special-casing.
    """
    line = line.strip()
    if not line.startswith("data:"):
        return None
    payload = line[len("data:"):].strip()
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def parse_native_intent(event: dict) -> tuple[str, dict] | None:
    """Extract a router-delegated native intent from a "done" event / QueryResponse.

    The router returns "native_intent": null | {"intent": str, "slots": {str: int|str}}
    for requests it classified as HA-native (timers, date/time) but deliberately did
    not execute. Returns (intent_name, slots) with slots already in HA's intent slot
    format ({"hours": {"value": 1}}), or None when the key is missing (older router),
    null, or malformed.

    The intent name is re-checked against _LOCAL_INTENTS here — defense in depth,
    the router is not trusted to gate which HA intents this integration executes.
    Individual slot entries with a non-str key or a non-int/str value are dropped;
    bool is rejected explicitly since it's an int subclass.
    """
    native = event.get("native_intent")
    if not isinstance(native, dict):
        return None
    intent_name = native.get("intent")
    if not isinstance(intent_name, str) or intent_name not in _LOCAL_INTENTS:
        return None
    raw_slots = native.get("slots", {})
    if not isinstance(raw_slots, dict):
        return None
    slots = {
        key: {"value": value}
        for key, value in raw_slots.items()
        if isinstance(key, str)
        and isinstance(value, (int, str))
        and not isinstance(value, bool)
    }
    return intent_name, slots


# English speech for IntentHandleError.response_key values raised by HA's timer
# intents (homeassistant/components/intent/timers.py). HA's default agent renders
# these from its per-language intent responses, which this agent doesn't load; the
# exception message itself is developer-facing (e.g. "Device does not support
# timers: device_id=..."), so it's never spoken.
_NATIVE_ERROR_SPEECH: dict[str, str] = {
    "timer_not_found": "I couldn't find that timer.",
    "multiple_timers_matched": "More than one timer matched. Please be more specific.",
    "no_timer_support": "Timers aren't supported on this device.",
}
NATIVE_ERROR_FALLBACK_SPEECH = "Sorry, I couldn't do that."


def native_intent_error_speech(err: Exception) -> str:
    """Return the user-facing speech for an error raised by intent.async_handle."""
    return _NATIVE_ERROR_SPEECH.get(
        getattr(err, "response_key", None) or "", NATIVE_ERROR_FALLBACK_SPEECH
    )


def resolve_area(
    device_id: str | None,
    dev_reg,
    area_reg,
) -> tuple[str | None, str | None]:
    """Return (area_id, area_name) for the HA device that originated the request.

    Both registries are passed in so this function has no HA imports and is easy
    to unit-test with plain MagicMock objects.
    """
    if not device_id:
        return None, None
    device = dev_reg.async_get(device_id)
    if device is None or device.area_id is None:
        return None, None
    area = area_reg.async_get_area(device.area_id)
    if area is None:
        return device.area_id, None
    return area.id, area.name

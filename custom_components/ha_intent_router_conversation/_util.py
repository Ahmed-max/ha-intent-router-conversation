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


# HA's timer and date/time intent handlers return a response with no speech (at most
# speech_slots); the default agent renders "Timer started" etc. from its per-language
# responses, which intent.async_handle never applies. Same gap as the error path above.
NATIVE_SUCCESS_FALLBACK_SPEECH = "Done."


def _format_duration(hours: int = 0, minutes: int = 0, seconds: int = 0) -> str:
    """'1 hour and 30 minutes', '2 minutes', '' when every part is zero."""
    parts = [
        f"{n} {unit}{'' if n == 1 else 's'}"
        for n, unit in ((hours, "hour"), (minutes, "minute"), (seconds, "second"))
        if n
    ]
    if len(parts) > 1:
        return ", ".join(parts[:-1]) + " and " + parts[-1]
    return parts[0] if parts else ""


def _slot_int(slots: dict, key: str) -> int:
    value = (slots.get(key) or {}).get("value")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _timer_label(name) -> str:
    return f"{name.capitalize()} timer" if isinstance(name, str) and name else "Timer"


def native_intent_success_speech(
    intent_name: str, slots: dict, speech_slots: dict | None
) -> str:
    """English speech for a native intent that succeeded without speech of its own.

    slots is the HA-format dict sent to intent.async_handle ({"hours": {"value": 1}});
    speech_slots is the handler's response.speech_slots (keys per HA's
    components/intent/timers.py and intent/__init__.py). Unknown shapes degrade to
    NATIVE_SUCCESS_FALLBACK_SPEECH rather than raising.
    """
    speech_slots = speech_slots if isinstance(speech_slots, dict) else {}
    duration = _format_duration(
        _slot_int(slots, "hours"), _slot_int(slots, "minutes"), _slot_int(slots, "seconds")
    )
    name = (slots.get("name") or {}).get("value")

    if intent_name == "HassStartTimer" and duration:
        return f"{_timer_label(name)} set for {duration}."
    if intent_name == "HassCancelTimer":
        return f"{_timer_label(name)} cancelled."
    if intent_name == "HassCancelAllTimers":
        canceled = speech_slots.get("canceled")
        if canceled == 0:
            return "There were no timers to cancel."
        if canceled == 1:
            return "Timer cancelled."
        return "All timers cancelled."
    if intent_name == "HassIncreaseTimer" and duration:
        return f"Added {duration}."
    if intent_name == "HassDecreaseTimer" and duration:
        return f"Removed {duration}."
    if intent_name == "HassPauseTimer":
        return f"{_timer_label(name)} paused."
    if intent_name == "HassUnpauseTimer":
        return f"{_timer_label(name)} resumed."
    if intent_name == "HassTimerStatus":
        return _timer_status_speech(speech_slots.get("timers"))
    if intent_name == "HassGetCurrentTime":
        time = speech_slots.get("time")
        if hasattr(time, "hour") and hasattr(time, "minute"):
            hour12 = time.hour % 12 or 12
            return f"It's {hour12}:{time.minute:02d} {'AM' if time.hour < 12 else 'PM'}."
    if intent_name == "HassGetCurrentDate":
        date = speech_slots.get("date")
        if hasattr(date, "strftime") and hasattr(date, "day"):
            return f"Today is {date.strftime('%A, %B')} {date.day}, {date.year}."
    return NATIVE_SUCCESS_FALLBACK_SPEECH


def _timer_status_speech(timers) -> str:
    if not isinstance(timers, list):
        return NATIVE_SUCCESS_FALLBACK_SPEECH
    if not timers:
        return "There are no timers."
    first = timers[0] if isinstance(timers[0], dict) else {}
    left = _format_duration(
        first.get("rounded_hours_left") or 0,
        first.get("rounded_minutes_left") or 0,
        first.get("rounded_seconds_left") or 0,
    )
    status = f"{left} left" if left else "almost done"
    if first.get("is_active") is False:
        status += ", paused"
    label = _timer_label(first.get("name"))
    if len(timers) == 1:
        return f"{label}: {status}." if first.get("name") else f"{status[0].upper()}{status[1:]}."
    return f"You have {len(timers)} timers. {label}: {status}."


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

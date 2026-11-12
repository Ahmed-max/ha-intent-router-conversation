# ha-intent-router-conversation

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/Ahmed-max/ha-intent-router-conversation)](https://github.com/Ahmed-max/ha-intent-router-conversation/releases)

A Home Assistant custom component that bridges the HA Assist pipeline to the
[ha-intent-router](https://github.com/maxrouter/ha-intent-router) FastAPI service.
Once installed, Assist uses ha-intent-router for entity resolution, intent classification,
and response generation instead of the built-in conversation agent.

## Features

- Routes voice and text queries to ha-intent-router with full satellite area context
- Passes HA device/area metadata so the router can apply per-room defaults
- Sends HA's conversation id as the router's `session_id`, so follow-ups ("turn it off",
  "and the kitchen?") resolve against the earlier turns — see [Session id contract](#session-id-contract)
- Optionally keeps the satellite listening after the router asks a clarifying question

## Session id contract

The router keeps session memory and dialogue state per `session_id` and trusts the value
it is sent. It has no device lookup of its own, so this integration has to send one
stable, non-empty id for every turn of a conversation.

**What is sent.** `session_id` is the `conversation_id` of the turn's `ChatLog`
(`chat_log.conversation_id`), and the same id is returned as the
`ConversationResult.conversation_id` on every path: router answers, local timer and media
intents, native intents delegated by the router, and errors.
`ConversationInput.conversation_id` is not used. In HA releases before
[core #188909](https://github.com/home-assistant/core/pull/188909) (merged 2026-10-28) it
is `None` on a conversation's first turn, which gave the router `session_id=""` and no
memory of that turn. The `ChatLog` id is never empty, because HA creates the chat session
(and assigns its id) before it calls the agent.

**How long an id lives.** This was checked against HA core `dev` at
[`596e597`](https://github.com/home-assistant/core/tree/596e597e5aeb2c2a26ef8f8f4f009b0d7b3800f2):

- A voice satellite stores the id between wake-word runs. `AssistSatelliteEntity` keeps
  `_conversation_id`. Each new pipeline run calls
  `chat_session.async_get_chat_session(hass, self._conversation_id, ...)`, stores the
  session's id back, and passes it to the pipeline as `conversation_id`
  ([`assist_satellite/entity.py` L508–L531](https://github.com/home-assistant/core/blob/596e597e5aeb2c2a26ef8f8f4f009b0d7b3800f2/homeassistant/components/assist_satellite/entity.py#L508-L531)).
- The session behind that id survives about **5 minutes of idle time**.
  `CONVERSATION_TIMEOUT = timedelta(minutes=5)`
  ([`helpers/chat_session.py` L32](https://github.com/home-assistant/core/blob/596e597e5aeb2c2a26ef8f8f4f009b0d7b3800f2/homeassistant/helpers/chat_session.py#L32)).
  `SessionCleanup` drops a session that is not in use and whose `last_updated` is older
  than that (L101–L112). `last_updated` is refreshed when every turn ends (L204).
- Within that window, a known id returns the same session (L171–L172), so separate
  wake-word runs share one `ChatLog` and one router `session_id`.
- After the window, the expired ULID is replaced with a fresh `ulid_now()` (L174–L183). A
  new router session starts. The satellite stores the new id, so the next turns share it.
- `async_get_chat_log` keys the log on `session.conversation_id`
  ([`conversation/chat_log.py` L72–L115](https://github.com/home-assistant/core/blob/596e597e5aeb2c2a26ef8f8f4f009b0d7b3800f2/homeassistant/components/conversation/chat_log.py#L72-L115)),
  so `chat_log.conversation_id` is always that session's id.
- A satellite announcement or `start_conversation` deliberately starts a new session
  (L303–L308 of `assist_satellite/entity.py`). The next wake-word run continues from it.

Text clients (the Assist dialog, the `conversation.process` action) keep a conversation
only if they send back the `conversation_id` from the previous result. The same 5-minute
window applies to them.

### Listening for the answer to a clarification (optional)

When the router can't tell what you meant, it asks ("Which light do you mean?"). Its
stream ends with `intent_type` set to `ambiguous`, `ambiguous_target` or `low_confidence`.
Turn on **Listen for the answer to a clarifying question** in the integration's options
(**Settings → Devices & Services → HA Intent Router → Configure**). The result then sets
`continue_conversation=True` for those turns, and the satellite listens again without the
wake word. The option is off by default; every other turn returns
`continue_conversation=False`.

## Requirements

- Home Assistant 2024.6 or later
- A running [ha-intent-router](https://github.com/maxrouter/ha-intent-router) instance
- An API key created in ha-intent-router's **Settings → Authentication → API Keys** panel

## Installation

### Via HACS (recommended)

1. In HACS, go to **Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/Ahmed-max/ha-intent-router-conversation` as an
   **Integration** repository.
3. Find **HA Intent Router** in HACS and install it.
4. Restart Home Assistant.

### Manual

This component can also be distributed as source — copy it manually into your HA config directory.

1. Clone (or download) this repository:
   ```bash
   git clone https://github.com/Ahmed-max/ha-intent-router-conversation.git
   ```
2. Copy the component directory into your HA configuration:
   ```bash
   cp -r ha-intent-router-conversation/custom_components/ha_intent_router_conversation \
         <your HA config dir>/custom_components/
   ```
   Your config directory is the folder that contains `configuration.yaml`.
3. Restart Home Assistant.

## Configuration

Once HA has restarted with the component in place, add the integration:

1. Go to **Settings → Devices & Services → Add Integration**, search for
   **HA Intent Router**, and select it. Or use the badge below to jump there directly:

   [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=ha_intent_router_conversation)

2. Enter:
   - **Base URL** — the root URL of your ha-intent-router service,
     e.g. `http://ha-intent-router.local:8000`
   - **API Key** — a key minted from ha-intent-router's
     **Settings → Authentication → API Keys** panel
3. Click **Submit**. HA will verify connectivity to `/health` before saving.

## Using as the default Assist agent

After configuration, go to **Settings → Voice assistants**, open your Assist pipeline,
and set **Conversation agent** to **HA Intent Router**.

## Development

```bash
pip install pytest
pytest
```

Tests in `tests/test_util.py` cover payload construction and response parsing with
no HA installation required.

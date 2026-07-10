# ha-intent-router-conversation

A Home Assistant custom component that bridges the HA Assist pipeline to the
[ha-intent-router](https://github.com/maxrouter/ha-intent-router) FastAPI service.
Once installed, Assist uses ha-intent-router for entity resolution, intent classification,
and response generation instead of the built-in conversation agent.

## Features

- Routes voice and text queries to ha-intent-router with full satellite area context
- Passes HA device/area metadata so the router can apply per-room defaults
- Preserves HA's multi-turn `conversation_id` as the router's `session_id` for pronoun memory

## Requirements

- Home Assistant 2024.6 or later
- A running [ha-intent-router](https://github.com/maxrouter/ha-intent-router) instance
- An API key created in ha-intent-router's **Settings → Authentication → API Keys** panel

## Installation via HACS

1. In HACS, go to **Integrations** → **⋮** → **Custom repositories**.
2. Add `https://github.com/maxrouter/ha-intent-router-conversation` as an
   **Integration** repository.
3. Search for **HA Intent Router** in HACS and install it.
4. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **HA Intent Router** and select it.
3. Enter:
   - **Base URL** — the root URL of your ha-intent-router service,
     e.g. `http://ha-intent-router.local:8000`
   - **API Key** — a key minted from ha-intent-router's
     **Settings → Authentication → API Keys** panel
4. Click **Submit**. HA will test connectivity to `/health` before saving.

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

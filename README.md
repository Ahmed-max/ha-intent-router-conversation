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

## Installation

This component is distributed as source — copy it manually into your HA config directory.

1. Clone (or download) this repository:
   ```bash
   git clone ssh://git@192.168.178.130/max/ha-intent-router-conversation.git
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

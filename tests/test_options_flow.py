"""Unit tests for config_flow.py's options flow (continue_on_clarification).

Same approach as test_config_flow_reconfigure.py: conftest.py stubs homeassistant
with MagicMocks, so real stand-ins for config_entries.ConfigFlow/OptionsFlow and
homeassistant.core.callback are swapped in and config_flow.py is reloaded fresh.
"""
import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest
import voluptuous as vol

from custom_components.ha_intent_router_conversation.const import (
    CONF_CONTINUE_ON_CLARIFICATION,
)


class _FakeConfigFlowBase:
    def __init_subclass__(cls, domain=None, **kwargs):
        cls._domain = domain


class _FakeOptionsFlowBase:
    """HA (2024.11+) sets config_entry on the flow; the handler never does."""

    config_entry = None

    def async_show_form(self, *, step_id, data_schema=None, errors=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}


@pytest.fixture
def conf_mod():
    config_entries_attr = sys.modules["homeassistant"].config_entries
    core_mod = sys.modules["homeassistant.core"]
    saved = (config_entries_attr.ConfigFlow, config_entries_attr.OptionsFlow, core_mod.callback)

    config_entries_attr.ConfigFlow = _FakeConfigFlowBase
    config_entries_attr.OptionsFlow = _FakeOptionsFlowBase
    core_mod.callback = lambda func: func
    sys.modules.pop("custom_components.ha_intent_router_conversation.config_flow", None)
    try:
        yield importlib.import_module(
            "custom_components.ha_intent_router_conversation.config_flow"
        )
    finally:
        (config_entries_attr.ConfigFlow, config_entries_attr.OptionsFlow,
         core_mod.callback) = saved
        sys.modules.pop("custom_components.ha_intent_router_conversation.config_flow", None)


def _options_flow(conf_mod, options):
    flow = conf_mod.HAIntentRouterConversationConfigFlow.async_get_options_flow(None)
    flow.config_entry = SimpleNamespace(options=options)
    return flow


def _default_of(schema, key):
    for marker in schema.schema:
        if marker == key:
            return marker.default()
    raise KeyError(key)


def test_options_flow_defaults_to_off(conf_mod):
    result = asyncio.run(_options_flow(conf_mod, {}).async_step_init())

    assert result["type"] == "form"
    assert result["step_id"] == "init"
    assert _default_of(result["data_schema"], CONF_CONTINUE_ON_CLARIFICATION) is False
    assert result["data_schema"]({}) == {CONF_CONTINUE_ON_CLARIFICATION: False}


def test_options_flow_shows_current_value(conf_mod):
    flow = _options_flow(conf_mod, {CONF_CONTINUE_ON_CLARIFICATION: True})

    result = asyncio.run(flow.async_step_init())

    assert _default_of(result["data_schema"], CONF_CONTINUE_ON_CLARIFICATION) is True


def test_options_flow_saves_choice(conf_mod):
    flow = _options_flow(conf_mod, {})

    result = asyncio.run(flow.async_step_init({CONF_CONTINUE_ON_CLARIFICATION: True}))

    assert result == {
        "type": "create_entry",
        "title": "",
        "data": {CONF_CONTINUE_ON_CLARIFICATION: True},
    }


def test_options_flow_rejects_non_bool(conf_mod):
    result = asyncio.run(_options_flow(conf_mod, {}).async_step_init())

    with pytest.raises(vol.Invalid):
        result["data_schema"]({CONF_CONTINUE_ON_CLARIFICATION: "yes please"})

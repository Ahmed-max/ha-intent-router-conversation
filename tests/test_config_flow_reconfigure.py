"""Unit tests for config_flow.py's async_step_reconfigure.

`class HAIntentRouterConversationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN)`
executes at import time. conftest.py stubs `homeassistant` as a bare MagicMock(), and
using a MagicMock *instance* as a base class collapses the whole class statement into
another MagicMock instead of a real type (getattr on a MagicMock never raises
AttributeError, so `from homeassistant import config_entries` binds to an
auto-vivified attribute of the `homeassistant` mock, not the sys.modules entry
registered for "homeassistant.config_entries" — that entry is never actually read).

To exercise the real method body, this file swaps in a minimal real stand-in for
config_entries.ConfigFlow (recording enough of the real HA config-flow contract:
async_show_form/async_abort/async_create_entry/async_update_reload_and_abort,
async_entry_for_domain_unique_id, _get_reconfigure_entry via context["entry_id"])
and reloads config_flow.py fresh against it.
"""
import asyncio
import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeConfigEntry:
    def __init__(self, entry_id, unique_id, data):
        self.entry_id = entry_id
        self.unique_id = unique_id
        self.data = dict(data)


class _FakeConfigEntries:
    def __init__(self, entries):
        self._entries = list(entries)

    def async_entry_for_domain_unique_id(self, domain, unique_id):
        for entry in self._entries:
            if entry.unique_id == unique_id:
                return entry
        return None

    def async_get_known_entry(self, entry_id):
        for entry in self._entries:
            if entry.entry_id == entry_id:
                return entry
        raise KeyError(entry_id)


class _FakeConfigFlowBase:
    """Just enough of homeassistant.config_entries.ConfigFlow to run async_step_reconfigure."""

    def __init_subclass__(cls, domain=None, **kwargs):
        cls._domain = domain

    def async_show_form(self, *, step_id, data_schema=None, errors=None):
        return {"type": "form", "step_id": step_id, "errors": errors or {}}

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_update_reload_and_abort(self, entry, *, unique_id=None, data_updates=None, **kwargs):
        if unique_id is not None:
            entry.unique_id = unique_id
        if data_updates:
            entry.data.update(data_updates)
        return {"type": "abort", "reason": "reconfigure_successful", "entry": entry}

    async def async_set_unique_id(self, unique_id):
        self.context["unique_id"] = unique_id

    def _abort_if_unique_id_configured(self):
        raise AssertionError("_abort_if_unique_id_configured should not be called from reconfigure")

    def _abort_if_unique_id_mismatch(self, **kwargs):
        raise AssertionError(
            "_abort_if_unique_id_mismatch assumes unique_id is immutable identity; "
            "it must not be used when unique_id is the mutable base_url"
        )

    def _get_reconfigure_entry(self):
        return self.hass.config_entries.async_get_known_entry(self.context["entry_id"])


@pytest.fixture
def conf_mod():
    homeassistant_pkg = sys.modules["homeassistant"]
    config_entries_attr = homeassistant_pkg.config_entries
    original_base = config_entries_attr.ConfigFlow

    config_entries_attr.ConfigFlow = _FakeConfigFlowBase
    sys.modules.pop("custom_components.ha_intent_router_conversation.config_flow", None)
    try:
        module = importlib.import_module(
            "custom_components.ha_intent_router_conversation.config_flow"
        )
        yield module
    finally:
        config_entries_attr.ConfigFlow = original_base
        sys.modules.pop("custom_components.ha_intent_router_conversation.config_flow", None)


def _make_flow(conf_mod, entries, reconfiguring_entry_id):
    flow = object.__new__(conf_mod.HAIntentRouterConversationConfigFlow)
    flow.hass = MagicMock()
    flow.hass.config_entries = _FakeConfigEntries(entries)
    flow.handler = "ha_intent_router_conversation"
    flow.context = {"source": "reconfigure", "entry_id": reconfiguring_entry_id}
    return flow


def _run_reconfigure(conf_mod, flow, user_input):
    with patch.object(conf_mod, "_validate_connection", new=AsyncMock(return_value=None)):
        return asyncio.run(flow.async_step_reconfigure(user_input))


def test_reconfigure_changing_only_api_key_succeeds(conf_mod):
    entry = _FakeConfigEntry(
        entry_id="entry-a",
        unique_id="http://router.local:8000",
        data={"base_url": "http://router.local:8000", "api_key": "old-key"},
    )
    flow = _make_flow(conf_mod, [entry], "entry-a")

    result = _run_reconfigure(
        conf_mod, flow, {"base_url": "http://router.local:8000", "api_key": "new-key"}
    )

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["api_key"] == "new-key"
    assert entry.unique_id == "http://router.local:8000"


def test_reconfigure_changing_base_url_succeeds_and_updates_unique_id(conf_mod):
    entry = _FakeConfigEntry(
        entry_id="entry-a",
        unique_id="http://old-router.local:8000",
        data={"base_url": "http://old-router.local:8000", "api_key": "the-key"},
    )
    flow = _make_flow(conf_mod, [entry], "entry-a")

    result = _run_reconfigure(
        conf_mod, flow, {"base_url": "http://new-router.local:8000", "api_key": "the-key"}
    )

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["base_url"] == "http://new-router.local:8000"
    assert entry.unique_id == "http://new-router.local:8000"


def test_reconfigure_onto_another_entrys_url_aborts(conf_mod):
    entry_a = _FakeConfigEntry(
        entry_id="entry-a",
        unique_id="http://router-a.local:8000",
        data={"base_url": "http://router-a.local:8000", "api_key": "key-a"},
    )
    entry_b = _FakeConfigEntry(
        entry_id="entry-b",
        unique_id="http://router-b.local:8000",
        data={"base_url": "http://router-b.local:8000", "api_key": "key-b"},
    )
    flow = _make_flow(conf_mod, [entry_a, entry_b], "entry-a")

    result = _run_reconfigure(
        conf_mod, flow, {"base_url": "http://router-b.local:8000", "api_key": "key-a"}
    )

    assert result == {"type": "abort", "reason": "already_configured"}
    # entry_a must be untouched — the abort must happen before any update
    assert entry_a.data["base_url"] == "http://router-a.local:8000"
    assert entry_a.unique_id == "http://router-a.local:8000"

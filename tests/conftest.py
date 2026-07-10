"""Stub out homeassistant before any custom_component module is imported."""
from unittest.mock import MagicMock
import sys

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

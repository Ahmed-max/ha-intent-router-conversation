"""Unit tests for config_flow.py's _validate_connection two-probe logic.

_validate_connection is a plain module-level async function (not a method on
the ConfigFlow class), so it can be exercised directly against a fake
aiohttp session without needing a real Home Assistant instance.
"""
import asyncio
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from custom_components.ha_intent_router_conversation import config_flow


class _FakeResponse:
    def __init__(self, status: int):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class _FakeSession:
    """Fake aiohttp session with independently scriptable /health and auth-probe replies."""

    def __init__(self, health_status=200, health_exc=None, auth_status=200, auth_exc=None):
        self._health_status = health_status
        self._health_exc = health_exc
        self._auth_status = auth_status
        self._auth_exc = auth_exc
        self.requests = []

    def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if url.endswith(config_flow._AUTH_PROBE_PATH):
            if self._auth_exc:
                raise self._auth_exc
            return _FakeResponse(self._auth_status)
        if self._health_exc:
            raise self._health_exc
        return _FakeResponse(self._health_status)


def _validate(session):
    with patch.object(config_flow, "async_get_clientsession", return_value=session):
        return asyncio.run(
            config_flow._validate_connection(MagicMock(), "http://router.local:8000", "sekret")
        )


def test_valid_key_passes_both_probes():
    session = _FakeSession(health_status=200, auth_status=200)
    assert _validate(session) is None
    # both probes were actually issued
    urls = [u for u, _ in session.requests]
    assert any(u.endswith("/health") for u in urls)
    assert any(u.endswith(config_flow._AUTH_PROBE_PATH) for u in urls)


def test_bad_key_fails_only_auth_probe():
    session = _FakeSession(health_status=200, auth_status=401)
    assert _validate(session) == "invalid_auth"


def test_unreachable_router_fails_health_probe_before_auth_probe():
    session = _FakeSession(health_exc=aiohttp.ClientConnectionError("refused"))
    assert _validate(session) == "cannot_connect"
    # auth probe must never fire once /health already failed
    assert not any(
        u.endswith(config_flow._AUTH_PROBE_PATH) for u, _ in session.requests
    )


def test_health_probe_timeout_is_cannot_connect():
    session = _FakeSession(health_exc=asyncio.TimeoutError())
    assert _validate(session) == "cannot_connect"


def test_health_probe_non_200_is_cannot_connect():
    session = _FakeSession(health_status=503)
    assert _validate(session) == "cannot_connect"


def test_auth_probe_non_200_non_401_is_cannot_connect():
    session = _FakeSession(health_status=200, auth_status=500)
    assert _validate(session) == "cannot_connect"


def test_health_probe_sends_no_auth_header():
    session = _FakeSession()
    with patch.object(config_flow, "async_get_clientsession", return_value=session):
        asyncio.run(
            config_flow._validate_connection(MagicMock(), "http://router.local:8000", "sekret")
        )
    health_call = next(
        kwargs for u, kwargs in session.requests if u.endswith("/health")
    )
    assert "headers" not in health_call


def test_auth_probe_sends_bearer_header():
    session = _FakeSession()
    with patch.object(config_flow, "async_get_clientsession", return_value=session):
        asyncio.run(
            config_flow._validate_connection(MagicMock(), "http://router.local:8000", "sekret")
        )
    auth_call = next(
        kwargs
        for u, kwargs in session.requests
        if u.endswith(config_flow._AUTH_PROBE_PATH)
    )
    assert auth_call["headers"]["Authorization"] == "Bearer sekret"

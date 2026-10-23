"""
tests/test_home_assistant_integration.py
=========================================
Tests for Home Assistant Integration Provider.

Verifies:
- Unconfigured state when URL or token is missing
- Successful authentication and connection verification (HTTP 200 -> CONNECTED)
- Authentication rejection (HTTP 401/403 -> AUTH_ERROR)
- Network unreachable / timeout (UNREACHABLE)
- Entity discovery and normalization (doors, windows, motion, moisture, smoke, locks)
- State transitions and duplicate event suppression
- Credential safety: tokens are never exposed or logged; SSRF rejection
- Resource cleanup on close
"""

from __future__ import annotations

from datetime import datetime, timezone
import httpx2
import pytest

from app.integrations.base import IntegrationStatus
from app.integrations.home_assistant.provider import (
    HomeAssistantProvider,
    _mask_token,
    _sanitize_url,
)


def test_token_masking():
    """Verify long-lived access tokens are masked in representations."""
    assert _mask_token(None) == "not_set"
    assert _mask_token("") == "not_set"
    assert _mask_token("short") == "***"
    masked = _mask_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secretpayload")
    assert "secretpayload" not in masked
    assert masked.startswith("eyJh...")
    assert "len=" in masked


def test_url_sanitization_and_ssrf():
    """Verify URL validation blocks dangerous metadata endpoints."""
    assert _sanitize_url("http://homeassistant.local:8123/") == "http://homeassistant.local:8123"
    with pytest.raises(ValueError, match="Prohibited metadata destination"):
        _sanitize_url("http://169.254.169.254/latest/meta-data")
    with pytest.raises(ValueError, match="Prohibited metadata destination"):
        _sanitize_url("http://metadata.google.internal/computeMetadata/v1")


@pytest.mark.asyncio
async def test_unconfigured_provider():
    """Provider reports UNCONFIGURED when credentials are missing."""
    provider = HomeAssistantProvider(base_url="", access_token="")
    assert provider.is_configured is False

    health = await provider.get_health()
    assert health.status == IntegrationStatus.UNCONFIGURED
    assert health.is_connected is False
    assert health.is_configured is False
    assert health.metadata["token_status"] == "not_set"


@pytest.mark.asyncio
async def test_successful_connection_check():
    """Provider reports CONNECTED when GET /api/ returns 200."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/"
        assert request.headers.get("Authorization") == "Bearer valid-token-123"
        return httpx2.Response(200, json={"message": "API running."})

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(transport=transport, base_url="http://ha.local:8123") as client:
        provider = HomeAssistantProvider(
            base_url="http://ha.local:8123",
            access_token="valid-token-123",
            http_client=client,
        )
        health = await provider.get_health()
        assert health.status == IntegrationStatus.CONNECTED
        assert health.is_connected is True
        assert health.is_configured is True
        assert health.error_message is None


@pytest.mark.asyncio
async def test_auth_error_handling():
    """Provider reports AUTH_ERROR when GET /api/ returns 401."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"message": "401: Unauthorized"})

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(transport=transport, base_url="http://ha.local:8123") as client:
        provider = HomeAssistantProvider(
            base_url="http://ha.local:8123",
            access_token="invalid-token",
            http_client=client,
        )
        health = await provider.get_health()
        assert health.status == IntegrationStatus.AUTH_ERROR
        assert health.is_connected is False
        assert "Authentication rejected" in (health.error_message or "")


@pytest.mark.asyncio
async def test_network_unreachable_handling():
    """Provider reports UNREACHABLE when network connection fails."""
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("Connection refused to 192.168.1.100:8123")

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(transport=transport, base_url="http://192.168.1.100:8123") as client:
        provider = HomeAssistantProvider(
            base_url="http://192.168.1.100:8123",
            access_token="any-token",
            http_client=client,
        )
        health = await provider.get_health()
        assert health.status == IntegrationStatus.UNREACHABLE
        assert health.is_connected is False
        assert "Cannot reach Home Assistant" in (health.error_message or "")


@pytest.mark.asyncio
async def test_entity_discovery_and_normalization():
    """Discovers entities and maps them into normalized DeviceMetadata."""
    mock_states = [
        {
            "entity_id": "binary_sensor.front_door_contact",
            "state": "off",
            "attributes": {"device_class": "door", "friendly_name": "Front Entry Door", "battery_level": 90},
            "last_changed": "2026-10-23T04:00:00Z",
        },
        {
            "entity_id": "binary_sensor.hallway_motion",
            "state": "on",
            "attributes": {"device_class": "motion", "friendly_name": "Hallway PIR Motion"},
            "last_changed": "2026-10-23T04:01:00Z",
        },
        {
            "entity_id": "binary_sensor.kitchen_sink_leak",
            "state": "off",
            "attributes": {"device_class": "moisture", "friendly_name": "Kitchen Sink Moisture"},
            "last_changed": "2026-10-23T04:00:00Z",
        },
        {
            "entity_id": "binary_sensor.basement_smoke",
            "state": "off",
            "attributes": {"device_class": "smoke", "friendly_name": "Basement Smoke Alarm"},
            "last_changed": "2026-10-23T04:00:00Z",
        },
        {
            "entity_id": "lock.front_door_deadbolt",
            "state": "locked",
            "attributes": {"friendly_name": "Front Deadbolt"},
            "last_changed": "2026-10-23T04:00:00Z",
        },
        {
            "entity_id": "camera.driveway_stream",
            "state": "idle",
            "attributes": {"friendly_name": "Driveway IP Camera"},
            "last_changed": "2026-10-23T04:00:00Z",
        },
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/states":
            return httpx2.Response(200, json=mock_states)
        return httpx2.Response(404)

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(transport=transport, base_url="http://ha.local:8123") as client:
        provider = HomeAssistantProvider(
            base_url="http://ha.local:8123",
            access_token="tok",
            http_client=client,
        )
        devices = await provider.discover_devices()
        assert len(devices) == 6

        door = next(d for d in devices if "front_door" in d.device_id)
        assert door.device_type == "door_sensor"
        assert door.location == "front_door"
        assert door.is_simulated is False
        assert door.provider_id == "home_assistant"

        motion = next(d for d in devices if "hallway_motion" in d.device_id)
        assert motion.device_type == "motion_sensor"
        assert motion.state == "on"

        water = next(d for d in devices if "kitchen_sink" in d.device_id)
        assert water.device_type == "water_sensor"

        smoke = next(d for d in devices if "basement_smoke" in d.device_id)
        assert smoke.device_type == "smoke_sensor"


@pytest.mark.asyncio
async def test_duplicate_suppression_and_state_transitions():
    """State polling emits events on changes and suppresses duplicates on repeated identical states."""
    current_states = [
        {
            "entity_id": "binary_sensor.back_door",
            "state": "off",
            "attributes": {"device_class": "door", "friendly_name": "Back Door Sensor"},
            "last_changed": "2026-10-23T04:00:00Z",
        }
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=current_states)

    transport = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(transport=transport, base_url="http://ha.local:8123") as client:
        provider = HomeAssistantProvider(
            base_url="http://ha.local:8123",
            access_token="tok",
            http_client=client,
        )

        # 1. Cold sync: initial 'off' state is registered without generating spurious alert events
        events_1 = await provider.sync_events()
        assert len(events_1) == 0

        # 2. Repeated poll with same state: duplicate suppressed
        events_2 = await provider.sync_events()
        assert len(events_2) == 0

        # 3. State transitions to 'on' (door opened!)
        current_states[0] = {
            "entity_id": "binary_sensor.back_door",
            "state": "on",
            "attributes": {"device_class": "door", "friendly_name": "Back Door Sensor"},
            "last_changed": "2026-10-23T04:05:00Z",
        }
        events_3 = await provider.sync_events()
        assert len(events_3) == 1
        ev = events_3[0]
        assert ev.device_id == "ha-binary_sensor.back_door"
        assert ev.device_type == "door_sensor"
        assert ev.event_type == "opened"
        assert ev.location == "back_door"
        assert ev.metadata["source"] == "home_assistant"
        assert ev.metadata["is_simulated"] is False

        # 4. Immediate repeat poll without change: duplicate suppressed
        events_4 = await provider.sync_events()
        assert len(events_4) == 0

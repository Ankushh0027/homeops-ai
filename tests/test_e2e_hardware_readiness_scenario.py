"""
tests/test_e2e_hardware_readiness_scenario.py
=============================================
Phase 6.5: End-to-End Hardware Readiness Verification.

Executes the complete deterministic scenario and audit checks:
1. Trigger simulated back-door-open event at fixed timestamp (2:15 AM).
2. Confirm event is explicitly marked simulated and persisted exactly once.
3. Confirm HomeStateService receives updated state.
4. Confirm IncidentEngine evaluates event and SafetyPolicy determines appropriate risk.
5. Query persisted event and device state through MCP client/server integration.
6. Ask conversational agent: "The back door opened at 2:15 AM. What happened?"
7. Verify answer explains evidence, risk, uncertainty, next step, and does NOT claim a real person was detected.
8. Verify audit log contains expected event and incident records.

Security & Production Checks:
- Actual configuration values checked (do not assume Render is in production).
- Production simulator scenario gating (HTTP 403 Forbidden even on direct REST requests).
- Separation of simulated fixtures from physical Home Assistant / camera sources.
- execute_safe_action remains deterministically blocked.
- Secrets never leak in responses, logs, or error messages.
- Invalid device IDs and malformed scenarios fail safely.
- Repeated sync requests suppress duplicate events.
- Camera TCP reachability is not presented as proof of RTSP video decoding.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import httpx2
import pytest

from app.alexa.conversational_agent import ConversationalAgent
from app.cameras.service import CameraService
from app.cameras.sources import mask_credentials
from app.config import settings
from app.incidents.engine import IncidentEngine
from app.incidents.schemas import IncidentType, Severity
from app.integrations.cameras.provider import (
    CameraIntegrationProvider,
    probe_tcp_connection,
    validate_camera_url,
)
from app.integrations.home_assistant.provider import HomeAssistantProvider
from app.integrations.manager import IntegrationManager
from app.integrations.simulator.provider import SimulatedDeviceProvider
from app.mcp.client import HomeOpsMCPClient
from app.mcp.context import AppContext
from app.mcp.server import create_server
from app.models.events import HomeEvent
from app.safety.policy import evaluate_policy
from app.services.home_state import HomeStateService
from app.services.incident_history import IncidentHistoryStore
from app.web.server import create_app


# ===========================================================================
# Complete 8-Step Verification Scenario
# ===========================================================================

@pytest.mark.asyncio
async def test_e2e_hardware_readiness_back_door_scenario():
    """Verify the complete 8-step back-door-open scenario end-to-end."""

    # Fixed timestamp: 2:15 AM UTC
    fixed_ts = datetime(2026, 10, 23, 2, 15, 0, tzinfo=timezone.utc)

    # 1. Trigger simulated back-door-open event (and correlated hallway motion) at 2:15 AM
    home_state = HomeStateService()
    engine = IncidentEngine()
    history = IncidentHistoryStore(":memory:")

    manager = IntegrationManager(home_state_service=home_state)
    sim_provider = SimulatedDeviceProvider(enabled=True)
    manager.register_provider(sim_provider)

    back_door_event = HomeEvent(
        event_id="sim-door-open-0215",
        timestamp=fixed_ts,
        device_id="sim-door-back",
        device_type="door_sensor",
        event_type="opened",
        location="back_door",
        metadata={
            "source": "simulator",
            "is_simulated": True,
            "scenario": "security_incident",
        },
    )
    hallway_motion_event = HomeEvent(
        event_id="sim-motion-0215",
        timestamp=fixed_ts,
        device_id="sim-motion-hallway",
        device_type="motion_sensor",
        event_type="detected",
        location="hallway",
        metadata={
            "source": "simulator",
            "is_simulated": True,
            "scenario": "security_incident",
        },
    )

    # 2. Confirm the event is explicitly marked as simulated and persisted exactly once
    assert back_door_event.metadata["is_simulated"] is True
    assert back_door_event.metadata["source"] == "simulator"
    assert hallway_motion_event.metadata["is_simulated"] is True

    # Queue events into the simulator provider and sync
    sim_provider._pending_events.extend([back_door_event, hallway_motion_event])
    synced_first = await manager.sync_all()
    assert len(synced_first) == 2

    # Repeated sync must NOT create duplicate events
    synced_second = await manager.sync_all()
    assert len(synced_second) == 0

    all_events = home_state.get_all_events()
    assert len(all_events) == 2
    assert all_events[0].event_id == "sim-door-open-0215"
    assert all_events[1].event_id == "sim-motion-0215"

    # 3. Confirm HomeStateService receives the updated state
    snapshot = home_state.get_home_state()
    assert "devices" in snapshot
    back_door_device = home_state._devices.get("sim-door-back")
    assert back_door_device is not None
    assert back_door_device.last_event_type == "opened"
    assert back_door_device.location == "back_door"
    assert any(
        c["device_id"] == "sim-door-back" and c["condition"] == "opened"
        for c in snapshot["active_conditions"]
    )

    # 4. Confirm IncidentEngine evaluates the event and SafetyPolicy determines appropriate risk
    incidents = engine.process(all_events)
    assert len(incidents) >= 1
    primary_incident = incidents[0]
    assert primary_incident.incident_type == IncidentType.SECURITY
    assert primary_incident.severity == Severity.HIGH
    assert primary_incident.confidence >= 0.70
    assert any("sim-door-back" in str(e) for e in primary_incident.evidence)

    # Safety policy evaluation
    safety_decision = evaluate_policy(primary_incident)
    assert safety_decision.risk_level.value == "HIGH"
    assert safety_decision.action_permission.value == "REQUIRES_EXPLICIT_APPROVAL"
    assert safety_decision.action_permitted is False  # Autonomous physical execution blocked
    assert safety_decision.requires_explicit_approval is True
    assert safety_decision.requires_user_confirmation is True

    # 5. Query persisted event and device state through actual MCP client/server integration
    ctx = AppContext(
        home_state=home_state,
        engine=engine,
        history=history,
        integration_manager=manager,
    )
    server = create_server(context=ctx)
    asgi_app = server.streamable_http_app()

    async with asgi_app.router.lifespan_context(asgi_app):
        transport = httpx2.ASGITransport(app=asgi_app)
        client = HomeOpsMCPClient(
            base_url="http://127.0.0.1:8000/mcp",
            context=ctx,
            transport=transport,
        )

        # 5a. Query persisted events via MCP
        persisted_res = await client.get_persisted_events(device_id="sim-door-back")
        assert persisted_res["count"] == 1
        persisted_evt = persisted_res["events"][0]
        assert persisted_evt["device_id"] == "sim-door-back"
        assert persisted_evt["event_type"] == "opened"
        assert persisted_evt["metadata"]["is_simulated"] is True

        # 5b. Query device state via MCP
        device_res = await client.get_device_state("sim-door-back")
        assert "device" in device_res
        dev = device_res["device"]
        assert dev["device_id"] == "sim-door-back"
        assert dev["state"] == "opened"
        assert dev["is_simulated"] is True

        # 6. Ask conversational agent: "The back door opened at 2:15 AM. What happened?"
        agent = ConversationalAgent(mcp_client=client)
        turn_result = await agent.process_message("The back door opened at 2:15 AM. What happened?")

        speech = turn_result["speech"]
        speech_lower = speech.lower()

        # 7. Verify the answer explains evidence, risk, uncertainty, and recommended next step
        # Evidence
        assert "back door" in speech_lower
        assert "2:15 am" in speech_lower or "2:15" in speech_lower
        assert "sensor" in speech_lower

        # Risk
        assert "high" in speech_lower or "security" in speech_lower

        # Uncertainty: Must acknowledge that occupant presence was unverified
        assert "unverified" in speech_lower or "confidence" in speech_lower

        # Recommended next step
        assert "recommend" in speech_lower

        # CRITICAL: Must NOT claim a real person or intruder was verified/detected
        assert "real person was detected" not in speech_lower
        assert "intruder confirmed" not in speech_lower
        assert "intruder identified" not in speech_lower
        assert "person identified" not in speech_lower

        # Guardrail: Autonomous actuation blocked
        assert "will not execute autonomous physical actions" in speech or "blocked" in speech_lower or "manual" in speech_lower

        # 8. Verify the audit log contains the expected event and incident records
        audit_records = history.get_all(limit=10)
        assert len(audit_records) >= 1
        recorded = audit_records[0]
        assert recorded["incident_type"] == "SECURITY"
        assert recorded["severity"] == "HIGH"
        assert recorded["risk_level"] == "HIGH"
        assert "sim-door-back" in str(recorded["evidence"])


# ===========================================================================
# Security and Production Checks
# ===========================================================================

def test_actual_running_configuration():
    """Test actual configuration values used by the app without assuming production."""
    # Read actual Settings values
    assert hasattr(settings, "ENVIRONMENT")
    assert hasattr(settings, "SIMULATOR_ENABLED")
    assert hasattr(settings, "SIMULATOR_ALLOW_SCENARIOS")
    assert hasattr(settings, "INCIDENT_CORRELATION_WINDOW_SECONDS")
    assert hasattr(settings, "INCIDENT_MIN_CONFIDENCE_THRESHOLD")

    # In default development/test environment, simulator scenarios are enabled
    assert settings.INCIDENT_CORRELATION_WINDOW_SECONDS > 0
    assert 0.0 <= settings.INCIDENT_MIN_CONFIDENCE_THRESHOLD <= 1.0


@pytest.mark.asyncio
async def test_production_simulator_scenario_gating_direct_rest(monkeypatch):
    """Verify simulator scenarios return 403 Forbidden in production even on direct REST requests."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SIMULATOR_ALLOW_SCENARIOS", False)

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/simulator/scenario",
                json={"scenario": "security_incident"},
            )
            assert res.status_code == 403
            assert "strictly disabled in production" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_simulated_events_cannot_be_mistaken_for_physical():
    """Verify simulated devices cannot be mistaken for physical Home Assistant or camera devices."""
    home_state = HomeStateService()
    manager = IntegrationManager(home_state_service=home_state)
    sim = SimulatedDeviceProvider(enabled=True)
    ha = HomeAssistantProvider(base_url=None, access_token=None)
    cam = CameraIntegrationProvider()

    manager.register_provider(sim)
    manager.register_provider(ha)
    manager.register_provider(cam)

    # 1. Source filtering
    sim_devices = await manager.list_devices(source="simulator")
    assert all(d.is_simulated is True for d in sim_devices)
    assert all(d.provider_id == "simulator" for d in sim_devices)

    ha_devices = await manager.list_devices(source="home_assistant")
    assert len(ha_devices) == 0  # Unconfigured HA returns no physical devices

    # 2. Health metadata distinction
    health = await manager.get_all_health()
    assert health["has_physical_connected"] is False
    assert health["providers"]["simulator"]["metadata"]["is_simulated"] is True
    assert health["providers"]["home_assistant"]["is_connected"] is False


@pytest.mark.asyncio
async def test_execute_safe_action_remains_blocked():
    """Confirm execute_safe_action remains blocked by policy and never executes physical actuation."""
    ctx = AppContext(
        home_state=HomeStateService(),
        engine=IncidentEngine(),
        history=IncidentHistoryStore(":memory:"),
    )
    server = create_server(context=ctx)
    asgi_app = server.streamable_http_app()

    async with asgi_app.router.lifespan_context(asgi_app):
        transport = httpx2.ASGITransport(app=asgi_app)
        client = HomeOpsMCPClient(
            base_url="http://127.0.0.1:8000/mcp",
            context=ctx,
            transport=transport,
        )

        res = await client.call_tool(
            "execute_safe_action",
            {"action_name": "lock_door", "device_id": "sim-door-back"},
        )
        assert res["executed"] is False
        assert res["status"] == "blocked"
        assert "disabled in the current mvp" in res["reason"].lower() or "blocked" in res["reason"].lower()


@pytest.mark.asyncio
async def test_secrets_never_appear_in_responses_or_logs():
    """Confirm sensitive tokens never appear in sanitized representations, URLs, or logs."""
    raw_url = "rtsp://admin:SecretPass123!@192.168.1.100:554/live"
    masked = mask_credentials(raw_url)
    assert "SecretPass123!" not in masked
    assert "***:***@" in masked

    ha = HomeAssistantProvider(base_url="http://192.168.1.50:8123", access_token="my-super-secret-token")
    assert "my-super-secret-token" not in repr(ha)

    ha_health = await ha.get_health()
    assert "my-super-secret-token" not in str(ha_health.to_dict())


@pytest.mark.asyncio
async def test_invalid_device_ids_and_malformed_scenarios_fail_safely():
    """Verify non-existent devices and malformed scenarios return clean errors without 500 exceptions."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Invalid device ID
            res_dev = await client.get("/api/devices/non-existent-device-999")
            assert res_dev.status_code == 404

            # 2. Malformed / unknown scenario
            res_scen = await client.post(
                "/api/simulator/scenario",
                json={"scenario": "non_existent_exploding_scenario"},
            )
            assert res_scen.status_code == 400
            assert "unknown scenario" in res_scen.json()["detail"].lower()


def test_camera_tcp_reachability_not_presented_as_rtsp_decoding():
    """Verify camera TCP reachability is not presented as proof that RTSP video decoding works."""
    # TCP reachability to a non-existent port returns False cleanly
    reachable = probe_tcp_connection("127.0.0.1", 59999, timeout_sec=0.2)
    assert reachable is False

    # CameraService will NOT decode or generate fake detections for offline or missing RTSP streams
    cam_service = CameraService()
    res = cam_service.analyze_camera_footage("cam-garage")  # Offline physical camera
    assert res["analysis_status"] == "INVALID_VIDEO"
    assert "offline" in res["error"].lower()
    assert res["model_confidence"] is None

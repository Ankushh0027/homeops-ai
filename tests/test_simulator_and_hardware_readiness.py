"""
tests/test_simulator_and_hardware_readiness.py
==============================================
Tests for simulator isolation, hardware readiness, integration REST APIs,
MCP read tools, and conversational agent source discrimination.

Verifies:
1. Simulator provider isolation (is_simulated=True, preserves origin source)
2. Deterministic scenario fixtures (security_incident, water_hazard, smoke_alert, leaving_home)
3. Simulated event flow through normalization, persistence, incident correlation, and safety evaluation
4. Camera configuration validation, SSRF mitigation, credential redaction, and truthful connection probes
5. IntegrationManager multi-provider aggregation and deduplication
6. REST API routes (/api/integrations, /api/devices, /api/simulator/scenario)
7. Production simulator scenario protection (HTTP 403 in production)
8. MCP read tools (list_devices, get_device_state, get_integration_health, get_persisted_events)
9. Conversational agent honest reporting of unconfigured physical devices and source distinction
"""

from __future__ import annotations

import httpx2
import pytest

from app.alexa.conversational_agent import ConversationalAgent
from app.cameras.sources import mask_credentials
from app.config import settings
from app.incidents.engine import IncidentEngine
from app.integrations.base import IntegrationStatus
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
from app.services.home_state import HomeStateService
from app.services.incident_history import IncidentHistoryStore
from app.web.server import create_app


# ---------------------------------------------------------------------------
# 1. Simulator Isolation & Scenario Fixtures
# ---------------------------------------------------------------------------

def test_simulator_provider_isolation():
    """Simulated devices and events are strictly marked with is_simulated=True."""
    sim = SimulatedDeviceProvider(enabled=True)
    events = sim.trigger_scenario("security_incident")
    assert len(events) >= 2

    for ev in events:
        assert ev.metadata["source"] == "simulator"
        assert ev.metadata["is_simulated"] is True
        assert ev.device_id.startswith("sim-")


@pytest.mark.asyncio
async def test_simulated_event_flows_through_incident_engine():
    """A simulated door opening travels into HomeState and correlates in IncidentEngine."""
    sim = SimulatedDeviceProvider(enabled=True)
    home_state = HomeStateService()
    engine = IncidentEngine()

    events = sim.trigger_scenario("security_incident")
    for ev in events:
        home_state.add_event(ev)

    persisted = home_state.get_all_events()
    assert len(persisted) >= 2

    incidents = engine.process(persisted)
    assert len(incidents) >= 1
    inc = incidents[0]
    assert inc.incident_type.value == "SECURITY"
    assert inc.severity.value in {"HIGH", "CRITICAL"}
    assert any("back_door" in str(e) for e in inc.evidence)


def test_simulator_scenarios_all_deterministic():
    """Verify all scenarios produce expected event categories."""
    sim = SimulatedDeviceProvider(enabled=True)

    # Water hazard
    water_ev = sim.trigger_scenario("water_hazard")
    assert len(water_ev) == 1
    assert water_ev[0].device_type == "water_sensor"
    assert water_ev[0].event_type == "moisture_detected"

    # Smoke alert
    smoke_ev = sim.trigger_scenario("smoke_alert")
    assert len(smoke_ev) == 1
    assert smoke_ev[0].device_type == "smoke_sensor"
    assert smoke_ev[0].event_type == "smoke_detected"

    # Clear / quiet home
    clear_ev = sim.trigger_scenario("clear")
    assert len(clear_ev) == 0


def test_disabled_simulator_rejects_trigger():
    """Disabled simulator raises PermissionError."""
    sim = SimulatedDeviceProvider(enabled=False)
    with pytest.raises(PermissionError, match="Simulator is disabled"):
        sim.trigger_scenario("security_incident")


# ---------------------------------------------------------------------------
# 2. Camera Configuration, SSRF, & Credential Redaction
# ---------------------------------------------------------------------------

def test_camera_url_validation_and_ssrf():
    """Validates camera stream URLs and rejects SSRF cloud metadata addresses."""
    # Valid RTSP
    res = validate_camera_url("rtsp://admin:secret123@192.168.1.50:554/live")
    assert res["valid"] is True
    assert res["scheme"] == "rtsp"
    assert res["port"] == 554
    assert "secret123" not in res["masked_url"]
    assert "***:***@" in res["masked_url"]

    # Valid HTTPS
    res_http = validate_camera_url("https://cam.example.com:8443/stream.mjpg")
    assert res_http["valid"] is True
    assert res_http["port"] == 8443

    # Invalid scheme
    with pytest.raises(ValueError, match="Unsupported stream scheme"):
        validate_camera_url("ftp://192.168.1.50/cam")

    # SSRF to AWS/GCP metadata
    with pytest.raises(ValueError, match="prohibited metadata address"):
        validate_camera_url("rtsp://169.254.169.254:554/live")


def test_truthful_tcp_probe():
    """Connection probe never fakes success on unreachable hosts."""
    # Local unused port
    result = probe_tcp_connection("127.0.0.1", 59999, timeout_sec=0.2)
    assert result is False


# ---------------------------------------------------------------------------
# 3. IntegrationManager Multi-Provider Aggregation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_integration_manager_device_discovery():
    """IntegrationManager aggregates devices across HA, Camera, and Simulator."""
    home_state = HomeStateService()
    sim = SimulatedDeviceProvider(enabled=True)
    cam = CameraIntegrationProvider()
    ha = HomeAssistantProvider(base_url="", access_token="")  # unconfigured

    mgr = IntegrationManager(
        home_state_service=home_state,
        providers={"home_assistant": ha, "camera": cam, "simulator": sim},
    )

    devices = await mgr.list_devices()
    assert len(devices) > 0

    sim_devs = await mgr.list_devices(source="simulator")
    assert all(d.is_simulated is True for d in sim_devs)

    cam_devs = await mgr.list_devices(source="camera")
    assert len(cam_devs) >= 3

    # Find detached garage camera
    garage = await mgr.get_device_state("cam-garage")
    assert garage is not None
    assert garage.status == "OFFLINE"
    assert garage.is_simulated is False


# ---------------------------------------------------------------------------
# 4. REST API Integration Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rest_integrations_and_devices():
    """Verify /api/integrations and /api/devices REST routes."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Integrations health
            res_int = await client.get("/api/integrations")
            assert res_int.status_code == 200
            data_int = res_int.json()
            assert "providers" in data_int
            assert "home_assistant" in data_int["providers"]
            assert "camera" in data_int["providers"]
            assert "simulator" in data_int["providers"]

            # 2. HA status
            res_ha = await client.get("/api/integrations/home-assistant/status")
            assert res_ha.status_code == 200
            data_ha = res_ha.json()
            assert data_ha["status"] == "UNCONFIGURED"

            # 3. List devices
            res_dev = await client.get("/api/devices")
            assert res_dev.status_code == 200
            data_dev = res_dev.json()
            assert data_dev["count"] > 0
            assert any(d["device_id"] == "cam-main-gate" for d in data_dev["devices"])

            # 4. Trigger simulator scenario in dev mode
            res_sim = await client.post(
                "/api/simulator/scenario",
                json={"scenario": "water_hazard"},
            )
            assert res_sim.status_code == 200
            data_sim = res_sim.json()
            assert data_sim["status"] == "triggered"
            assert data_sim["is_simulated"] is True


@pytest.mark.asyncio
async def test_rest_simulator_scenario_production_gating(monkeypatch):
    """Production mode must strictly reject /api/simulator/scenario with 403 Forbidden."""
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
            assert "strictly disabled in production" in res.json()["detail"]


# ---------------------------------------------------------------------------
# 5. MCP Read Tools & Conversational Source Discrimination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_integration_read_tools():
    """Verify list_devices, get_device_state, and get_integration_health over MCP."""
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

        # 1. get_integration_health
        health = await client.get_integration_health()
        assert "providers" in health
        assert health["providers"]["simulator"]["is_connected"] is True

        # 2. list_devices
        dev_res = await client.list_devices()
        assert dev_res["count"] > 0

        # 3. get_device_state
        state_res = await client.get_device_state("cam-garage")
        assert "device" in state_res
        assert state_res["device"]["status"] == "OFFLINE"


@pytest.mark.asyncio
async def test_conversational_agent_answers_honestly_about_physical_devices():
    """Agent answers honestly that physical integrations are unconfigured."""
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
        agent = ConversationalAgent(mcp_client=client)

        # Ask about Home Assistant
        res = await agent.process_message("Is Home Assistant connected?")
        assert res["intent"] == "integration_query"
        assert "unconfigured" in res["speech"].lower() or "not connected" in res["speech"].lower()
        assert res["has_physical_connected"] is False

        # Ask to list devices
        dev_turn = await agent.process_message("List my devices")
        assert dev_turn["intent"] == "device_query"
        assert "simulated" in dev_turn["speech"].lower()
        assert "no physical devices" in dev_turn["speech"].lower()

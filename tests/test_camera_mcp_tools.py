"""
tests/test_camera_mcp_tools.py
==============================
Focused test suite for Phase 3:
1. Tool registration and parameter schemas for the 5 camera MCP tools:
   - list_cameras
   - get_camera_status
   - inspect_camera
   - analyze_camera_footage
   - get_camera_events
2. Camera status retrieval and detailed inspection (with credential masking).
3. Footage analysis and honest event persistence:
   - Genuine person detection creates a traceable HomeEvent.
   - Negative / no-person footage does NOT fabricate events.
   - Offline or missing camera produces honest non-crash status.
   - Snapshot paths only referenced when files exist.
4. Camera event retrieval: reads real persisted records without inventing history.
5. Safety guardrail preservation: autonomous physical actions remain strictly blocked.
6. Conversational agent integration: natural-language camera queries and evidence-grounded speech.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from app.alexa.conversational_agent import ConversationalAgent
from app.cameras.analyzer import TorchvisionPersonAnalyzer, AnalysisStatus
from app.cameras.service import CameraService
from app.cameras.sources import CameraRegistry, DemoCameraSource, OfflineCameraSource
from app.incidents.engine import IncidentEngine
from app.mcp.client import HomeOpsMCPClient
from app.mcp.context import AppContext
from app.mcp.server import create_server
from app.services.home_state import HomeStateService
from app.services.incident_history import IncidentHistoryStore


@pytest.fixture()
def isolated_ctx() -> AppContext:
    """Isolated AppContext with fresh in-memory stores and a test camera registry."""
    registry = CameraRegistry()
    registry.register(
        DemoCameraSource(
            camera_id="cam-main-gate",
            name="Main Gate Camera",
            location="Front Yard / Gate",
            clip_filename="main_gate_demo.mp4",
        )
    )
    registry.register(
        DemoCameraSource(
            camera_id="cam-back-patio",
            name="Back Patio Camera",
            location="Backyard Patio",
            clip_filename="back_patio_demo.mp4",
        )
    )
    registry.register(
        DemoCameraSource(
            camera_id="cam-empty-yard",
            name="Side Yard Camera",
            location="Side Yard",
            clip_filename="empty_yard_demo.mp4",
        )
    )
    registry.register(
        OfflineCameraSource(
            camera_id="cam-garage",
            name="Detached Garage Camera",
            location="Garage",
            status_reason="Device unreachable: timeout on RTSP port 554",
        )
    )

    home_state = HomeStateService()
    camera_svc = CameraService(
        registry=registry,
        analyzer=TorchvisionPersonAnalyzer(),
        home_state=home_state,
    )
    return AppContext(
        home_state=home_state,
        engine=IncidentEngine(),
        history=IncidentHistoryStore(":memory:"),
        camera_service=camera_svc,
    )


@pytest.fixture()
def mcp_server(isolated_ctx: AppContext):
    return create_server(context=isolated_ctx)


@pytest.fixture()
def mcp_client(mcp_server, isolated_ctx: AppContext) -> HomeOpsMCPClient:
    return HomeOpsMCPClient(server=mcp_server, context=isolated_ctx)


# ---------------------------------------------------------------------------
# 1. Registration & Schema Validation
# ---------------------------------------------------------------------------


class TestCameraToolRegistrationAndSchemas:
    def test_all_five_camera_tools_registered(self, mcp_server):
        registered = {t.name for t in mcp_server._tool_manager.list_tools()}
        camera_tools = {
            "list_cameras",
            "get_camera_status",
            "inspect_camera",
            "analyze_camera_footage",
            "get_camera_events",
        }
        assert camera_tools.issubset(registered)

    def test_tool_schemas_and_descriptions(self, mcp_server):
        tools = {t.name: t for t in mcp_server._tool_manager.list_tools()}
        assert "camera_id" in tools["get_camera_status"].parameters.get("properties", {})
        assert "camera_id" in tools["inspect_camera"].parameters.get("properties", {})
        assert "camera_id" in tools["analyze_camera_footage"].parameters.get("properties", {})
        assert "camera_id" in tools["get_camera_events"].parameters.get("properties", {})


# ---------------------------------------------------------------------------
# 2. Camera Status and Inspection
# ---------------------------------------------------------------------------


class TestCameraStatusAndInspection:
    @pytest.mark.asyncio
    async def test_list_cameras_returns_registered_cameras(self, mcp_client: HomeOpsMCPClient):
        result = await mcp_client.list_cameras()
        assert "cameras" in result
        assert result["count"] >= 4
        ids = [c["camera_id"] for c in result["cameras"]]
        assert "cam-main-gate" in ids
        assert "cam-garage" in ids
        # Verify demo flags
        main_gate = next(c for c in result["cameras"] if c["camera_id"] == "cam-main-gate")
        assert main_gate["is_demo"] is True
        assert main_gate["status"] == "DEMO"

    @pytest.mark.asyncio
    async def test_get_camera_status_online_and_offline(self, mcp_client: HomeOpsMCPClient):
        # Demo camera
        gate_status = await mcp_client.get_camera_status("cam-main-gate")
        assert gate_status["camera_id"] == "cam-main-gate"
        assert gate_status["status"] == "DEMO"
        assert gate_status["is_demo"] is True
        assert gate_status["clip_available"] is True

        # Offline camera
        garage_status = await mcp_client.get_camera_status("cam-garage")
        assert garage_status["camera_id"] == "cam-garage"
        assert garage_status["status"] == "OFFLINE"
        assert garage_status["clip_available"] is False
        assert "timeout" in garage_status.get("status_reason", "").lower()

    @pytest.mark.asyncio
    async def test_get_camera_status_unknown_id(self, mcp_client: HomeOpsMCPClient):
        res = await mcp_client.get_camera_status("cam-unknown-999")
        assert res["status"] == "ERROR"
        assert "not found" in res.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_inspect_camera_details_and_credential_redaction(self, mcp_client: HomeOpsMCPClient, isolated_ctx: AppContext):
        # Add an RTSP camera with credentials to test safe masking
        from app.cameras.sources import RTSPStreamSource
        isolated_ctx.camera_service.registry.register(
            RTSPStreamSource(
                camera_id="cam-driveway-rtsp",
                name="Driveway Stream",
                location="Driveway",
                raw_stream_url="rtsp://admin:super_secret_password123@192.168.1.120:554/live",
            )
        )

        res = await mcp_client.inspect_camera("cam-driveway-rtsp")
        assert "super_secret_password123" not in str(res)
        assert "***:***" in res["stream_url"]

    @pytest.mark.asyncio
    async def test_inspect_camera_unknown_id(self, mcp_client: HomeOpsMCPClient):
        res = await mcp_client.inspect_camera("cam-does-not-exist")
        assert res["status"] == "ERROR"
        assert "not found" in res.get("error", "").lower()


# ---------------------------------------------------------------------------
# 3. Real Footage Analysis and Event Persistence
# ---------------------------------------------------------------------------


class TestAnalysisAndEventPersistence:
    @pytest.mark.asyncio
    async def test_successful_detection_and_honest_persistence(self, mcp_client: HomeOpsMCPClient, isolated_ctx: AppContext):
        """Main gate demo footage contains a walking person.
        Analysis must yield genuine detection and persist a single deduplicated event.
        """
        assert len(isolated_ctx.home_state._events) == 0

        res = await mcp_client.analyze_camera_footage("cam-main-gate")
        assert res["analysis_status"] == AnalysisStatus.PERSON_DETECTED.value
        assert res["model_confidence"] is not None
        assert 0.4 <= res["model_confidence"] <= 1.0
        assert res["bounding_box"] is not None
        assert len(res["bounding_box"]) == 4

        # Verify event reference was generated and persisted
        event_ref = res.get("event_reference")
        assert event_ref is not None
        assert event_ref.startswith("evt-cam-")

        # Verify event in isolated home_state
        events = isolated_ctx.home_state.get_recent_events(limit=10)
        assert len(events) == 1
        stored = events[0]
        assert stored.event_id == event_ref
        assert stored.device_id == "cam-main-gate"
        assert stored.device_type == "camera"
        assert stored.event_type == "person_detected"
        assert stored.metadata["model_confidence"] == res["model_confidence"]
        assert stored.metadata["source_mode"] == "DEMO"

        # Verify snapshot path only if referenced
        snap_url = res.get("snapshot_url")
        if snap_url:
            filename = snap_url.split("/")[-1]
            snap_file = Path("app/web/static/snapshots") / filename
            assert snap_file.exists()

    @pytest.mark.asyncio
    async def test_no_detection_does_not_persist_false_event(self, mcp_client: HomeOpsMCPClient, isolated_ctx: AppContext):
        """Empty yard demo clip contains no persons.
        Analysis must return NO_PERSON_DETECTED and persist zero events.
        """
        assert len(isolated_ctx.home_state._events) == 0

        res = await mcp_client.analyze_camera_footage("cam-empty-yard")
        assert res["analysis_status"] == AnalysisStatus.NO_PERSON_DETECTED.value
        assert res.get("model_confidence") is None
        assert res.get("event_reference") is None

        # Confirm zero events were persisted
        events = isolated_ctx.home_state.get_recent_events()
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_offline_camera_analysis_fails_gracefully(self, mcp_client: HomeOpsMCPClient, isolated_ctx: AppContext):
        res = await mcp_client.analyze_camera_footage("cam-garage")
        assert res["analysis_status"] == AnalysisStatus.INVALID_VIDEO.value
        assert res["source_mode"] == "OFFLINE"
        assert res.get("event_reference") is None
        assert len(isolated_ctx.home_state._events) == 0

    @pytest.mark.asyncio
    async def test_unknown_camera_analysis_returns_not_found(self, mcp_client: HomeOpsMCPClient):
        res = await mcp_client.analyze_camera_footage("cam-phantom")
        assert res["analysis_status"] == AnalysisStatus.INVALID_VIDEO.value
        assert "not found" in res.get("error", "").lower()


# ---------------------------------------------------------------------------
# 4. Camera Event Retrieval
# ---------------------------------------------------------------------------


class TestCameraEventRetrieval:
    @pytest.mark.asyncio
    async def test_get_camera_events_empty_initial(self, mcp_client: HomeOpsMCPClient):
        res = await mcp_client.get_camera_events("cam-main-gate")
        assert res["camera_id"] == "cam-main-gate"
        assert res["count"] == 0
        assert res["events"] == []

    @pytest.mark.asyncio
    async def test_get_camera_events_after_analysis(self, mcp_client: HomeOpsMCPClient):
        # Run analysis to create an event
        analysis = await mcp_client.analyze_camera_footage("cam-main-gate")
        assert analysis["analysis_status"] == AnalysisStatus.PERSON_DETECTED.value
        evt_id = analysis["event_reference"]

        # Retrieve events
        res = await mcp_client.get_camera_events("cam-main-gate")
        assert res["count"] == 1
        evt = res["events"][0]
        assert evt["event_id"] == evt_id
        assert evt["camera_id"] == "cam-main-gate"
        assert evt["detection_type"] == "person_detected"
        assert "confidence" in evt
        assert "bounding_box" in evt
        assert evt["source_mode"] == "DEMO"

    @pytest.mark.asyncio
    async def test_get_camera_events_unknown_camera(self, mcp_client: HomeOpsMCPClient):
        res = await mcp_client.get_camera_events("cam-unknown")
        assert res["camera_id"] == "cam-unknown"
        assert res["count"] == 0
        assert res["events"] == []


# ---------------------------------------------------------------------------
# 5. Legacy Tools and Safety Guardrails Preserved
# ---------------------------------------------------------------------------


class TestLegacyToolsAndSafetyGuardrail:
    @pytest.mark.asyncio
    async def test_all_seven_legacy_tools_work(self, mcp_client: HomeOpsMCPClient, isolated_ctx: AppContext):
        state = await mcp_client.get_home_state()
        assert "devices" in state

        events = await mcp_client.get_recent_events()
        assert "events" in events

        investigate = await mcp_client.investigate_incident()
        assert "incidents" in investigate

        risk = await mcp_client.assess_risk(
            incident_type="SECURITY",
            severity="HIGH",
            confidence=0.88,
            title="Gate test",
            summary="Testing legacy MCP tools",
            evidence=["Gate sensor opened"],
            recommended_next_step="Inspect gate.",
        )
        assert "risk_level" in risk

        rec = await mcp_client.recommend_response(
            incident_type="SECURITY",
            severity="HIGH",
            confidence=0.88,
        )
        assert "recommended_action" in rec

        rec_inc = await mcp_client.record_incident(
            incident_type="SECURITY",
            severity="HIGH",
            confidence=0.88,
            title="Gate alert",
            summary="Gate opened unexpectedly.",
            evidence=["Sensor trigger"],
            recommended_next_step="Inspect gate.",
        )
        assert "incident_id" in rec_inc

    @pytest.mark.asyncio
    async def test_execute_safe_action_remains_blocked(self, mcp_client: HomeOpsMCPClient):
        """Guardrail invariant: execute_safe_action must NEVER execute autonomous physical changes."""
        res = await mcp_client.execute_safe_action(
            action_name="lock_all_doors",
        )
        assert res["status"] == "blocked"
        assert "physical" in res["reason"].lower() or "blocked" in res["reason"].lower()


# ---------------------------------------------------------------------------
# 6. Conversational Agent Camera Queries
# ---------------------------------------------------------------------------


class TestConversationalCameraIntegration:
    @pytest.fixture()
    def agent(self, mcp_client: HomeOpsMCPClient) -> ConversationalAgent:
        return ConversationalAgent(mcp_client=mcp_client)

    @pytest.mark.asyncio
    async def test_list_cameras_conversational(self, agent: ConversationalAgent):
        res = await agent.process_message("List my cameras")
        speech = res["speech"].lower()
        assert "camera" in speech
        assert "main gate" in speech
        tools = [t["tool"] for t in res["tool_calls"]]
        assert "list_cameras" in tools

    @pytest.mark.asyncio
    async def test_check_camera_offline_conversational(self, agent: ConversationalAgent):
        res = await agent.process_message("Check the garage camera")
        speech = res["speech"].lower()
        assert "garage" in speech
        assert "offline" in speech or "reach" in speech
        tools = [t["tool"] for t in res["tool_calls"]]
        assert any(t in tools for t in ["get_camera_status", "inspect_camera"])

    @pytest.mark.asyncio
    async def test_analyze_camera_footage_conversational(self, agent: ConversationalAgent):
        res = await agent.process_message("Analyze the main gate demo footage")
        speech = res["speech"].lower()
        assert "main gate" in speech
        assert "person" in speech
        # Critical requirement: do not call a detected person an intruder without verified evidence
        assert "intruder" not in speech
        assert "unknown visitor" not in speech
        tools = [t["tool"] for t in res["tool_calls"]]
        assert "analyze_camera_footage" in tools

    @pytest.mark.asyncio
    async def test_get_camera_events_conversational(self, agent: ConversationalAgent, mcp_client: HomeOpsMCPClient):
        # First analyze footage to persist an event
        await mcp_client.analyze_camera_footage("cam-main-gate")

        res = await agent.process_message("What person detections were recorded at the main gate?")
        speech = res["speech"].lower()
        assert "recorded" in speech or "person detection" in speech or "event" in speech
        tools = [t["tool"] for t in res["tool_calls"]]
        assert "get_camera_events" in tools

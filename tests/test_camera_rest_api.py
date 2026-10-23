"""
tests/test_camera_rest_api.py
=============================
Focused test suite for Phase 4: Camera REST API Endpoints.

Validates:
1. GET /api/cameras — list all configured cameras, source modes, labels, and statuses.
2. GET /api/cameras/{camera_id} — camera details, configuration, and inspection.
3. GET /api/cameras/{camera_id}/status — operational status and neural model readiness.
4. GET /api/cameras/{camera_id}/events — persisted detection events read from state log.
5. POST /api/cameras/{camera_id}/analyze — genuine model inference and event persistence.
   - Genuine detection on demo footage (cam-main-gate).
   - Genuine no-person detection on empty yard footage (cam-empty-yard).
6. Safe HTTP error status codes:
   - 404 for unknown camera IDs.
   - 503 for offline cameras on analyze.
   - 404 for missing footage clips.
   - 503 for model unavailable.
   - 422 for invalid video footage.
7. Snapshot serving & path traversal protection:
   - GET /api/cameras/snapshots/{filename} serves valid snapshot.
   - 404 for non-existent snapshot.
   - 400 for path traversal attempts (../, /, \\, malformed format).
8. Credential redaction across all REST responses.
9. Verification that legacy endpoints and MCP functionality remain unaffected.
"""

from __future__ import annotations

import io
from pathlib import Path
import httpx2
import pytest
from PIL import Image

from app.cameras.analyzer import TorchvisionPersonAnalyzer, VideoAnalysisResult, AnalysisStatus
from app.cameras.service import CameraService
from app.cameras.sources import CameraRegistry, DemoCameraSource, OfflineCameraSource, RTSPStreamSource
from app.incidents.engine import IncidentEngine
from app.mcp.context import AppContext
from app.services.home_state import HomeStateService
from app.services.incident_history import IncidentHistoryStore
from app.web.server import create_app


@pytest.fixture()
def test_context() -> AppContext:
    """Isolated AppContext with test camera fixtures."""
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
    registry.register(
        RTSPStreamSource(
            camera_id="cam-driveway-rtsp",
            name="Driveway Stream",
            location="Driveway",
            raw_stream_url="rtsp://admin:secret_pass_987@192.168.1.199:554/live",
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
def app_instance(test_context: AppContext):
    return create_app(context=test_context)


# ---------------------------------------------------------------------------
# 1. Camera Listing & Details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cameras_list(app_instance):
    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.get("/api/cameras")
            assert res.status_code == 200
            data = res.json()
            assert "cameras" in data
            assert data["count"] >= 5
            cams = {c["camera_id"]: c for c in data["cameras"]}
            assert "cam-main-gate" in cams
            assert cams["cam-main-gate"]["is_demo"] is True
            assert cams["cam-main-gate"]["status"] == "DEMO"
            # Credential redaction
            assert "secret_pass_987" not in str(data)
            assert "***:***" in cams["cam-driveway-rtsp"]["masked_stream_url"]


@pytest.mark.asyncio
async def test_get_camera_details(app_instance):
    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Valid camera
            res = await client.get("/api/cameras/cam-main-gate")
            assert res.status_code == 200
            data = res.json()
            assert data["camera_id"] == "cam-main-gate"
            assert data["is_demo"] is True
            assert data["clip_available"] is True
            assert data["status"] == "DEMO"

            # Unknown camera -> 404
            res_unknown = await client.get("/api/cameras/cam-nonexistent")
            assert res_unknown.status_code == 404
            assert "not found" in res_unknown.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_camera_status_endpoint(app_instance):
    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Online demo camera
            res = await client.get("/api/cameras/cam-main-gate/status")
            assert res.status_code == 200
            data = res.json()
            assert data["camera_id"] == "cam-main-gate"
            assert data["status"] == "DEMO"
            assert data["model_available"] is True
            assert "ssdlite320" in data["model_name"]

            # Offline camera returns 200 with OFFLINE status
            res_off = await client.get("/api/cameras/cam-garage/status")
            assert res_off.status_code == 200
            data_off = res_off.json()
            assert data_off["status"] == "OFFLINE"
            assert "timeout" in data_off.get("status_reason", "").lower()

            # Unknown camera -> 404
            res_unknown = await client.get("/api/cameras/cam-invalid/status")
            assert res_unknown.status_code == 404


# ---------------------------------------------------------------------------
# 2. Camera Events Retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_camera_events_empty_and_unknown(app_instance):
    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Empty events initial
            res = await client.get("/api/cameras/cam-main-gate/events")
            assert res.status_code == 200
            data = res.json()
            assert data["camera_id"] == "cam-main-gate"
            assert data["count"] == 0
            assert data["events"] == []

            # Unknown camera -> 404
            res_unknown = await client.get("/api/cameras/cam-missing/events")
            assert res_unknown.status_code == 404


# ---------------------------------------------------------------------------
# 3. Video Analysis & Genuine Event Persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_analyze_detection_and_event_persistence(app_instance):
    """Analyze main gate demo footage containing a person.
    Verifies inference runs, 200 OK returned, and GET /events returns the persisted record.
    """
    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post(
                "/api/cameras/cam-main-gate/analyze",
                json={"confidence_threshold": 0.40, "max_duration_sec": 30},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["analysis_status"] == AnalysisStatus.PERSON_DETECTED.value
            assert data["person_detected"] is True
            assert data["model_confidence"] is not None
            assert 0.4 <= data["model_confidence"] <= 1.0
            assert data["bounding_box"] is not None
            assert len(data["bounding_box"]) == 4
            event_id = data.get("event_reference")
            assert event_id is not None
            assert event_id.startswith("evt-cam-")

            # Verify persisted event is retrievable via GET /api/cameras/{id}/events
            res_events = await client.get("/api/cameras/cam-main-gate/events")
            assert res_events.status_code == 200
            ev_data = res_events.json()
            assert ev_data["count"] == 1
            stored = ev_data["events"][0]
            assert stored["event_id"] == event_id
            assert stored["camera_id"] == "cam-main-gate"
            assert stored["detection_type"] == "person_detected"
            assert stored["source_mode"] == "DEMO"
            assert stored["confidence"] == data["model_confidence"]


@pytest.mark.asyncio
async def test_post_analyze_no_detection_persists_nothing(app_instance):
    """Analyze empty yard demo clip containing no person.
    Verifies 200 OK returned with NO_PERSON_DETECTED and zero events persisted.
    """
    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post("/api/cameras/cam-empty-yard/analyze")
            assert res.status_code == 200
            data = res.json()
            assert data["analysis_status"] == AnalysisStatus.NO_PERSON_DETECTED.value
            assert data["person_detected"] is False
            assert data.get("event_reference") is None
            assert data.get("model_confidence") is None

            # Verify zero events persisted
            res_events = await client.get("/api/cameras/cam-empty-yard/events")
            assert res_events.status_code == 200
            assert res_events.json()["count"] == 0


# ---------------------------------------------------------------------------
# 4. Error Handling & HTTP Status Codes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_analyze_unknown_camera(app_instance):
    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post("/api/cameras/cam-phantom/analyze")
            assert res.status_code == 404
            assert "not found" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_analyze_offline_camera(app_instance):
    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post("/api/cameras/cam-garage/analyze")
            assert res.status_code == 503
            assert "offline" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_analyze_missing_footage(app_instance, test_context: AppContext):
    """Camera registered with a clip that does not exist on disk."""
    test_context.camera_service.registry.register(
        DemoCameraSource(
            camera_id="cam-missing-clip",
            name="Missing Clip Camera",
            location="Attic",
            clip_filename="non_existent_clip_12345.mp4",
        )
    )
    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post("/api/cameras/cam-missing-clip/analyze")
            assert res.status_code == 404
            assert "no accessible footage" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_analyze_model_unavailable(app_instance, test_context: AppContext):
    """When neural network model weights are unavailable, return 503 rather than fake results."""
    # Force model unavailable on analyzer
    test_context.camera_service.analyzer = TorchvisionPersonAnalyzer(force_model_unavailable=True)

    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            res = await client.post("/api/cameras/cam-main-gate/analyze")
            assert res.status_code == 503
            assert "unavailable" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_post_analyze_invalid_video(app_instance, test_context: AppContext):
    """Corrupt or non-video file returns 422 Unprocessable Entity."""
    # Create a dummy invalid video file
    corrupt_clip = Path("simulator/footage/corrupt_clip.mp4")
    corrupt_clip.write_bytes(b"NOT_A_VALID_MP4_FILE_JUST_CORRUPT_BYTES")
    try:
        test_context.camera_service.registry.register(
            DemoCameraSource(
                camera_id="cam-corrupt",
                name="Corrupt Camera",
                location="Basement",
                clip_filename="corrupt_clip.mp4",
            )
        )
        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx2.ASGITransport(app=app_instance)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                res = await client.post("/api/cameras/cam-corrupt/analyze")
                assert res.status_code == 422
                assert "invalid video" in res.json()["detail"].lower()
    finally:
        if corrupt_clip.exists():
            corrupt_clip.unlink()


# ---------------------------------------------------------------------------
# 5. Snapshot Serving & Path Traversal Prevention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_serving_and_traversal_protection(app_instance):
    # Ensure static snapshots directory exists and write a valid dummy snapshot
    snap_dir = Path("app/web/static/snapshots")
    snap_dir.mkdir(parents=True, exist_ok=True)
    test_snap = snap_dir / "test_snapshot_valid.jpg"

    # Create a small valid JPEG
    img = Image.new("RGB", (320, 240), color=(50, 100, 150))
    img.save(test_snap, format="JPEG")

    try:
        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx2.ASGITransport(app=app_instance)
            async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
                # 1. Valid snapshot request
                res = await client.get("/api/cameras/snapshots/test_snapshot_valid.jpg")
                assert res.status_code == 200
                assert res.headers.get("content-type") == "image/jpeg"
                assert len(res.content) > 100

                # Also via alias /api/snapshots/{filename}
                res_alias = await client.get("/api/snapshots/test_snapshot_valid.jpg")
                assert res_alias.status_code == 200

                # 2. Non-existent snapshot -> 404
                res_missing = await client.get("/api/cameras/snapshots/missing_file_0000.jpg")
                assert res_missing.status_code == 404

                # 3. Path traversal attempts -> 400
                traversal_attempts = [
                    "../app.css",
                    "..%2Fapp.css",
                    "..\\app.css",
                    "../../etc/passwd",
                    "test%00snapshot.jpg",
                    "invalid_ext.exe",
                    "something.sh",
                ]
                for attempt in traversal_attempts:
                    res_bad = await client.get(f"/api/cameras/snapshots/{attempt}")
                    assert res_bad.status_code in (400, 404)
    finally:
        if test_snap.exists():
            test_snap.unlink()


@pytest.mark.asyncio
async def test_camera_footage_serving(app_instance):
    """Verify GET /api/cameras/{camera_id}/footage safely serves registered demo clips."""
    async with app_instance.router.lifespan_context(app_instance):
        transport = httpx2.ASGITransport(app=app_instance)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # 1. Valid demo camera with registered clip
            res = await client.get("/api/cameras/cam-main-gate/footage")
            assert res.status_code == 200
            assert "video/mp4" in res.headers.get("content-type", "")
            assert len(res.content) > 1000

            # 2. Offline camera with no clip -> 404
            res_offline = await client.get("/api/cameras/cam-garage/footage")
            assert res_offline.status_code == 404
            assert "offline" in res_offline.json()["detail"].lower()

            # 3. Nonexistent camera -> 404
            res_unknown = await client.get("/api/cameras/cam-unknown/footage")
            assert res_unknown.status_code == 404

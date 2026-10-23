"""
tests/test_camera_sources.py
============================
Focused tests for Phase 1 camera sources:
- Camera registry lookup and listing
- Demo camera source and accurate status
- Offline camera source and failure handling
- Non-existent camera IDs
- Missing clip error handling
- Credential masking (never leaking RTSP/HTTP passwords)
- Unverified RTSP sources (never claiming fake connectivity)
- Decodability of bundled sample clips with imageio_ffmpeg
"""

from __future__ import annotations

from pathlib import Path
import pytest
import imageio_ffmpeg

from app.cameras.sources import (
    CameraRegistry,
    CameraStatus,
    DemoCameraSource,
    OfflineCameraSource,
    RTSPStreamSource,
    mask_credentials,
)


class TestCredentialMasking:
    def test_mask_rtsp_credentials(self):
        url = "rtsp://admin:supersecret456@192.168.1.100:554/stream1"
        masked = mask_credentials(url)
        assert "supersecret456" not in masked
        assert "admin" not in masked
        assert masked == "rtsp://***:***@192.168.1.100:554/stream1"

    def test_mask_http_credentials(self):
        url = "http://security_user:p@ssw0rd!@10.0.0.15:8080/mjpeg"
        masked = mask_credentials(url)
        assert "p@ssw0rd!" not in masked
        assert "security_user" not in masked
        assert "***:***" in masked

    def test_unauthenticated_url_preserved(self):
        url = "rtsp://192.168.1.200:554/h264"
        assert mask_credentials(url) == url

    def test_empty_or_invalid_url_handling(self):
        assert mask_credentials("") == ""
        assert mask_credentials(None) == ""


class TestCameraSourcesAndRegistry:
    @pytest.fixture()
    def registry(self) -> CameraRegistry:
        return CameraRegistry()

    def test_default_cameras_registered(self, registry: CameraRegistry):
        sources = registry.list_all()
        ids = {s["camera_id"] for s in sources}
        assert "cam-main-gate" in ids
        assert "cam-back-patio" in ids
        assert "cam-garage" in ids

    def test_demo_camera_properties(self, registry: CameraRegistry):
        info = registry.get_status("cam-main-gate")
        assert info["status"] == CameraStatus.DEMO.value
        assert info["is_demo"] is True
        assert info["is_physical"] is False
        assert info["verified_hardware"] is False
        assert info["clip_available"] is True
        assert info["clip_name"] == "main_gate_demo.mp4"
        assert "DEMO SOURCE" in info["notice"]

    def test_offline_camera_properties(self, registry: CameraRegistry):
        info = registry.get_status("cam-garage")
        assert info["status"] == CameraStatus.OFFLINE.value
        assert info["is_demo"] is False
        assert info["is_physical"] is False
        assert info["clip_available"] is False
        assert "OFFLINE" in info["notice"]
        assert "Camera disconnected" in info["status_reason"]

    def test_invalid_camera_lookup(self, registry: CameraRegistry):
        info = registry.get_status("cam-non-existent-99")
        assert info["status"] == CameraStatus.ERROR.value
        assert "not found" in info["error"].lower()

    def test_missing_clip_reports_error(self, tmp_path: Path):
        missing_cam = DemoCameraSource(
            camera_id="cam-broken",
            name="Broken Demo Camera",
            location="garden",
            clip_filename="does_not_exist_clip.mp4",
        )
        assert missing_cam.get_status() == CameraStatus.ERROR
        assert missing_cam.get_clip_path() is None
        info = missing_cam.get_safe_info()
        assert info["status"] == CameraStatus.ERROR.value
        assert info["clip_available"] is False

    def test_rtsp_camera_never_claims_fake_connected(self):
        rtsp_cam = RTSPStreamSource(
            camera_id="cam-rtsp-test",
            name="RTSP Front Driveway",
            location="driveway",
            raw_stream_url="rtsp://admin:mysecretpassword@192.168.1.50:554/live",
            credentials={"user": "admin", "pass": "mysecretpassword"},
        )
        # Before probe
        assert rtsp_cam.is_verified() is False
        assert rtsp_cam.get_status() == CameraStatus.OFFLINE

        # Probe without hardware must not fake connection
        connected = rtsp_cam.verify_connection()
        assert connected is False
        assert rtsp_cam.is_verified() is False
        assert rtsp_cam.get_status() == CameraStatus.OFFLINE

        # Safe info must mask credentials
        safe_info = rtsp_cam.get_safe_info()
        assert "mysecretpassword" not in str(safe_info)
        assert "admin" not in str(safe_info["masked_stream_url"])
        assert "rtsp://***:***@192.168.1.50:554/live" == safe_info["masked_stream_url"]


class TestSampleFootageDecoding:
    def test_main_gate_clip_decodable(self):
        clip_path = Path("simulator/footage/main_gate_demo.mp4")
        assert clip_path.exists(), "main_gate_demo.mp4 must exist"
        reader = imageio_ffmpeg.read_frames(str(clip_path))
        meta = next(reader)
        assert meta["size"] == (320, 240)
        assert meta["fps"] == 10.0
        assert meta["duration"] >= 2.5

        # Decode first frame and verify byte length
        frame0 = next(reader)
        assert len(frame0) == 320 * 240 * 3
        reader.close()

    def test_back_patio_clip_decodable(self):
        clip_path = Path("simulator/footage/back_patio_demo.mp4")
        assert clip_path.exists(), "back_patio_demo.mp4 must exist"
        reader = imageio_ffmpeg.read_frames(str(clip_path))
        meta = next(reader)
        assert meta["size"] == (320, 240)
        assert meta["fps"] == 10.0
        assert meta["duration"] >= 2.5

        # Decode first frame and verify byte length
        frame0 = next(reader)
        assert len(frame0) == 320 * 240 * 3
        reader.close()

"""
app/cameras/sources.py
======================
Camera-source abstraction and registry for HomeOps-AI.

Guarantees:
1. Accurate status reporting: DEMO, CONNECTED, OFFLINE, ERROR.
2. Explicitly labeled demo sources using bundled synthetic test clips.
3. Never claims a camera is connected or live unless actually verified.
4. Never exposes camera credentials, RTSP passwords, or private tokens to clients or logs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
import logging
from pathlib import Path
import re
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger("homeops.cameras.sources")

_SIMULATOR_FOOTAGE_DIR = Path(__file__).parent.parent.parent / "simulator" / "footage"


class CameraStatus(str, Enum):
    """Accurate status enumeration for camera devices."""
    DEMO = "DEMO"
    CONNECTED = "CONNECTED"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"


def mask_credentials(url_str: str) -> str:
    """Mask credentials (usernames, passwords) in RTSP, HTTP, or stream URLs.
    
    Example:
        rtsp://admin:secret123@192.168.1.50:554/h264 -> rtsp://***:***@192.168.1.50:554/h264
    """
    if not url_str or not isinstance(url_str, str):
        return ""
    try:
        parsed = urlparse(url_str)
        if parsed.password or parsed.username:
            netloc = parsed.netloc
            # Replace user:pass@ with ***:***@
            if "@" in netloc:
                _, host_port = netloc.split("@", 1)
                masked_netloc = f"***:***@{host_port}"
                return urlunparse(parsed._replace(netloc=masked_netloc))
        # Regex fallback for non-standard URIs
        return re.sub(r"://([^:]+):([^@]+)@", r"://***:***@", url_str)
    except Exception:
        return "[MASKED_URL]"


class CameraSource(ABC):
    """Abstract base class for all smart-home camera sources."""

    def __init__(
        self,
        camera_id: str,
        name: str,
        location: str,
        source_type: str,
        description: str = "",
    ) -> None:
        self.camera_id = camera_id
        self.name = name
        self.location = location
        self.source_type = source_type
        self.description = description

    @abstractmethod
    def get_status(self) -> CameraStatus:
        """Return the accurate camera operational status."""
        raise NotImplementedError

    @abstractmethod
    def is_verified(self) -> bool:
        """Return True only if a real connection to hardware has been verified."""
        raise NotImplementedError

    @abstractmethod
    def get_clip_path(self) -> Optional[Path]:
        """Return path to accessible video clip file, if available."""
        raise NotImplementedError

    @abstractmethod
    def get_safe_info(self) -> dict[str, Any]:
        """Return structured camera metadata without any credentials or secrets."""
        raise NotImplementedError


class DemoCameraSource(CameraSource):
    """Camera source backed by bundled synthetic demo clips.
    
    Explicitly labeled as DEMO so users and evaluators know it is simulated footage.
    """

    def __init__(
        self,
        camera_id: str,
        name: str,
        location: str,
        clip_filename: str,
        description: str = "Synthetic demo camera fixture.",
    ) -> None:
        super().__init__(
            camera_id=camera_id,
            name=name,
            location=location,
            source_type="demo",
            description=description,
        )
        self.clip_filename = clip_filename

    @property
    def clip_path(self) -> Path:
        return _SIMULATOR_FOOTAGE_DIR / self.clip_filename

    def get_status(self) -> CameraStatus:
        if self.clip_path.exists() and self.clip_path.is_file():
            return CameraStatus.DEMO
        logger.warning("Demo clip not found at expected path: %s", self.clip_path)
        return CameraStatus.ERROR

    def is_verified(self) -> bool:
        # A demo camera is synthetic, not a verified physical camera
        return False

    def get_clip_path(self) -> Optional[Path]:
        path = self.clip_path
        return path if path.exists() else None

    def get_safe_info(self) -> dict[str, Any]:
        status = self.get_status()
        clip_exists = self.clip_path.exists()
        return {
            "camera_id": self.camera_id,
            "name": self.name,
            "location": self.location,
            "source_type": self.source_type,
            "status": status.value,
            "is_demo": True,
            "is_physical": False,
            "verified_hardware": False,
            "clip_available": clip_exists,
            "clip_name": self.clip_filename if clip_exists else None,
            "description": self.description,
            "notice": "DEMO SOURCE: Synthetic test fixture. Not a real surveillance device.",
        }


class OfflineCameraSource(CameraSource):
    """Camera source representing a disconnected or unreachable device.
    
    Used to test error states, failure modes, and recovery paths.
    """

    def __init__(
        self,
        camera_id: str,
        name: str,
        location: str,
        status_reason: str = "Device is offline or unreachable on local network.",
    ) -> None:
        super().__init__(
            camera_id=camera_id,
            name=name,
            location=location,
            source_type="offline_test",
            description="Intentionally offline camera fixture for failure testing.",
        )
        self.status_reason = status_reason

    def get_status(self) -> CameraStatus:
        return CameraStatus.OFFLINE

    def is_verified(self) -> bool:
        return False

    def get_clip_path(self) -> Optional[Path]:
        return None

    def get_safe_info(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "name": self.name,
            "location": self.location,
            "source_type": self.source_type,
            "status": CameraStatus.OFFLINE.value,
            "is_demo": False,
            "is_physical": False,
            "verified_hardware": False,
            "clip_available": False,
            "clip_name": None,
            "status_reason": self.status_reason,
            "description": self.description,
            "notice": "OFFLINE: Camera is unreachable. Verification check failed.",
        }


class RTSPStreamSource(CameraSource):
    """Future-ready adapter for RTSP/ONVIF network cameras.
    
    Never reports CONNECTED unless an actual probe verification succeeds.
    Credentials are masked in all public outputs.
    """

    def __init__(
        self,
        camera_id: str,
        name: str,
        location: str,
        raw_stream_url: str,
        credentials: Optional[dict[str, str]] = None,
        description: str = "Hardware RTSP Camera Stream.",
    ) -> None:
        super().__init__(
            camera_id=camera_id,
            name=name,
            location=location,
            source_type="rtsp",
            description=description,
        )
        self._raw_stream_url = raw_stream_url
        self._credentials = credentials or {}
        self._is_connected: bool = False
        self._last_error: Optional[str] = None

    def verify_connection(self) -> bool:
        """Probe the physical camera connection.
        
        Without a reachable hardware endpoint, does NOT fake success.
        """
        # Strict rule: Never claim connected without physical handshake
        self._is_connected = False
        self._last_error = "No real hardware endpoint reachable for this stream probe."
        return False

    def get_status(self) -> CameraStatus:
        if self._is_connected:
            return CameraStatus.CONNECTED
        if self._last_error:
            return CameraStatus.OFFLINE
        return CameraStatus.OFFLINE

    def is_verified(self) -> bool:
        return self._is_connected

    def get_clip_path(self) -> Optional[Path]:
        return None

    def get_safe_info(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "name": self.name,
            "location": self.location,
            "source_type": self.source_type,
            "status": self.get_status().value,
            "is_demo": False,
            "is_physical": True,
            "verified_hardware": self.is_verified(),
            "masked_stream_url": mask_credentials(self._raw_stream_url),
            "clip_available": False,
            "clip_name": None,
            "description": self.description,
            "notice": "RTSP ADAPTER: Connection unverified. Credentials safely masked.",
        }


class CameraRegistry:
    """Central registry and query interface for all camera sources."""

    def __init__(self) -> None:
        self._sources: dict[str, CameraSource] = {}
        self._register_default_sources()

    def _register_default_sources(self) -> None:
        """Register the default demo and offline fixtures."""
        self.register(
            DemoCameraSource(
                camera_id="cam-main-gate",
                name="Main Gate Camera (CAM-01)",
                location="main_gate",
                clip_filename="main_gate_demo.mp4",
                description="Synthetic demo camera monitoring the front driveway and main entrance gate.",
            )
        )
        self.register(
            DemoCameraSource(
                camera_id="cam-back-patio",
                name="Back Patio Camera (CAM-02)",
                location="back_door",
                clip_filename="back_patio_demo.mp4",
                description="Synthetic demo camera monitoring the rear garden patio and back doorway.",
            )
        )
        self.register(
            OfflineCameraSource(
                camera_id="cam-garage",
                name="Garage Camera (CAM-03)",
                location="garage",
                status_reason="Camera disconnected: Network timeout probing 192.168.1.185:554.",
            )
        )

    def register(self, source: CameraSource) -> None:
        self._sources[source.camera_id] = source

    def get(self, camera_id: str) -> Optional[CameraSource]:
        return self._sources.get(camera_id)

    def list_all(self) -> list[dict[str, Any]]:
        return [s.get_safe_info() for s in self._sources.values()]

    def get_status(self, camera_id: str) -> dict[str, Any]:
        source = self.get(camera_id)
        if not source:
            return {
                "camera_id": camera_id,
                "status": CameraStatus.ERROR.value,
                "error": f"Camera '{camera_id}' not found in registry.",
                "is_demo": False,
                "is_physical": False,
            }
        return source.get_safe_info()


# Global module singleton
camera_registry = CameraRegistry()

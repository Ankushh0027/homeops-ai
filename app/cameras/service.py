"""
app/cameras/service.py
======================
Camera Event & Analysis Coordination Service for HomeOps-AI.

Coordinates:
1. Camera registry lookups and operational status reporting.
2. Real video analysis on available clips.
3. Event persistence into HomeStateService when genuine person detections occur.
4. Safe retrieval of camera-specific events.
5. Strict adherence to safety boundaries: never fabricates confidence, boxes, or
   risk classifications, and never executes physical actions.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any, Optional
import uuid

from app.cameras.analyzer import (
    AnalysisStatus,
    BaseVideoAnalyzer,
    TorchvisionPersonAnalyzer,
    VideoAnalysisResult,
    default_video_analyzer,
)
from app.cameras.sources import (
    CameraRegistry,
    CameraSource,
    CameraStatus,
    camera_registry as _default_registry,
)
from app.models.events import HomeEvent
from app.services.home_state import HomeStateService, home_state as _default_home_state

logger = logging.getLogger("homeops.cameras.service")


class CameraService:
    """Service layer managing camera state, video analysis, and event persistence."""

    def __init__(
        self,
        registry: Optional[CameraRegistry] = None,
        home_state: Optional[HomeStateService] = None,
        analyzer: Optional[BaseVideoAnalyzer] = None,
    ) -> None:
        self.registry = registry or _default_registry
        self.home_state = home_state or _default_home_state
        self.analyzer = analyzer or default_video_analyzer

    def list_cameras(self) -> list[dict[str, Any]]:
        """Return safe metadata for all registered cameras."""
        return self.registry.list_all()

    def get_camera_status(self, camera_id: str) -> dict[str, Any]:
        """Return accurate operational status and details for a camera."""
        if not camera_id or not isinstance(camera_id, str):
            return {
                "camera_id": camera_id,
                "status": CameraStatus.ERROR.value,
                "error": "Invalid camera ID provided. Must be a non-empty string.",
            }
        return self.registry.get_status(camera_id.strip())

    def inspect_camera(self, camera_id: str) -> dict[str, Any]:
        """Inspect a camera's current operational state, location, and clip status."""
        source = self.registry.get(camera_id)
        if not source:
            return {
                "camera_id": camera_id,
                "status": CameraStatus.ERROR.value,
                "error": f"Camera '{camera_id}' not found in registry.",
            }

        safe_info = source.get_safe_info()
        recent_events = self.get_camera_events(camera_id, limit=3)
        return {
            "camera_id": camera_id,
            "name": source.name,
            "location": source.location,
            "status": safe_info.get("status"),
            "source_type": source.source_type,
            "is_demo": safe_info.get("is_demo", False),
            "clip_available": safe_info.get("clip_available", False),
            "clip_name": safe_info.get("clip_name"),
            "footage_url": f"/api/cameras/{camera_id}/footage" if safe_info.get("clip_available") else None,
            "stream_url": safe_info.get("masked_stream_url"),
            "notice": safe_info.get("notice"),
            "recent_events_count": len(recent_events),
            "last_event": recent_events[0] if recent_events else None,
        }

    def analyze_camera_footage(
        self,
        camera_id: str,
        confidence_threshold: float = 0.40,
        max_duration_sec: int = 60,
    ) -> dict[str, Any]:
        """Execute video analysis on a camera's available footage and persist genuine detections.
        
        Guarantees:
        - Only genuine model inference is run.
        - Only persists a HomeEvent when a person is genuinely detected by the model.
        - Never fabricates detections or events for offline cameras or missing footage.
        """
        source = self.registry.get(camera_id)
        if not source:
            return {
                "camera_id": camera_id,
                "analysis_status": AnalysisStatus.INVALID_VIDEO.value,
                "error": f"Camera '{camera_id}' not found in registry.",
                "model_name": getattr(self.analyzer, "MODEL_NAME", "ssdlite320_mobilenet_v3_large"),
                "model_confidence": None,
                "bounding_box": None,
                "event_reference": None,
                "snapshot_url": None,
            }

        # Handle offline or error states
        status = source.get_status()
        if status == CameraStatus.OFFLINE:
            safe_info = source.get_safe_info()
            return {
                "camera_id": camera_id,
                "source_mode": CameraStatus.OFFLINE.value,
                "analysis_status": AnalysisStatus.INVALID_VIDEO.value,
                "error": f"Cannot analyze camera '{camera_id}': Camera is OFFLINE.",
                "details": safe_info.get("status_reason", "Camera unreachable."),
                "model_confidence": None,
                "bounding_box": None,
                "event_reference": None,
                "snapshot_url": None,
            }

        clip_path = source.get_clip_path()
        if not clip_path or not clip_path.exists():
            return {
                "camera_id": camera_id,
                "source_mode": status.value,
                "analysis_status": AnalysisStatus.INVALID_VIDEO.value,
                "error": f"No accessible footage clip found for camera '{camera_id}'.",
                "model_confidence": None,
                "bounding_box": None,
                "event_reference": None,
                "snapshot_url": None,
            }

        # Run genuine model analysis
        analysis_result: VideoAnalysisResult = self.analyzer.analyze_clip(
            clip_path=clip_path,
            camera_id=camera_id,
            source_mode=status.value,
            confidence_threshold=confidence_threshold,
        )

        # If a person was genuinely detected, persist an auditable HomeEvent
        if analysis_result.analysis_status == AnalysisStatus.PERSON_DETECTED.value:
            # Verify snapshot file exists before referencing
            verified_snapshot_url = None
            if analysis_result.snapshot_url:
                filename = analysis_result.snapshot_url.split("/")[-1]
                disk_path = Path(__file__).parent.parent / "web" / "static" / "snapshots" / filename
                if disk_path.exists():
                    verified_snapshot_url = analysis_result.snapshot_url

            event_id = f"evt-cam-{uuid.uuid4().hex[:8]}"
            event_timestamp = datetime.now(timezone.utc)

            home_event = HomeEvent(
                event_id=event_id,
                timestamp=event_timestamp,
                device_id=camera_id,
                device_type="camera",
                event_type="person_detected",
                location=source.location,
                value=analysis_result.model_confidence,
                metadata={
                    "camera_name": source.name,
                    "source_mode": status.value,
                    "detection_type": "person_detected",
                    "model_name": analysis_result.model_name,
                    "model_confidence": analysis_result.model_confidence,
                    "bounding_box": analysis_result.bounding_box,
                    "snapshot_url": verified_snapshot_url,
                    "analysis_status": analysis_result.analysis_status,
                    "provenance": "video_analysis",
                    "deduplicated_events_count": analysis_result.deduplicated_events_count,
                    "frame_index": analysis_result.detected_frame_index,
                },
            )

            self.home_state.add_event(home_event)
            analysis_result.event_reference = event_id
            analysis_result.snapshot_url = verified_snapshot_url
            logger.info("Persisted camera detection event: %s for %s", event_id, camera_id)

        return analysis_result.to_dict()

    def get_camera_events(self, camera_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve persisted events for a specific camera from the home state log."""
        if not camera_id:
            return []
        events = self.home_state.get_recent_events(limit=limit, device_type="camera")
        matched = [e for e in events if e.device_id == camera_id]
        return [
            {
                "event_id": e.event_id,
                "timestamp": e.timestamp.isoformat(),
                "camera_id": e.device_id,
                "camera_name": e.metadata.get("camera_name", e.device_id),
                "location": e.location,
                "event_type": e.event_type,
                "detection_type": e.metadata.get("detection_type", e.event_type),
                "model_name": e.metadata.get("model_name"),
                "confidence": e.value,
                "bounding_box": e.metadata.get("bounding_box"),
                "snapshot_url": e.metadata.get("snapshot_url"),
                "source_mode": e.metadata.get("source_mode"),
                "analysis_status": e.metadata.get("analysis_status"),
                "provenance": e.metadata.get("provenance", "video_analysis"),
            }
            for e in matched
        ]


# Global singleton instance
camera_service = CameraService()

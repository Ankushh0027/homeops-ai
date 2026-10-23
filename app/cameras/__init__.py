"""
app/cameras
===========
Camera-aware smart-home safety subsystem for HomeOps-AI.
"""

from app.cameras.analyzer import (
    AnalysisStatus,
    BaseVideoAnalyzer,
    TorchvisionPersonAnalyzer,
    VideoAnalysisResult,
    default_video_analyzer,
)
from app.cameras.service import (
    CameraService,
    camera_service,
)
from app.cameras.sources import (
    CameraRegistry,
    CameraSource,
    CameraStatus,
    DemoCameraSource,
    OfflineCameraSource,
    RTSPStreamSource,
    camera_registry,
    mask_credentials,
)

__all__ = [
    "AnalysisStatus",
    "BaseVideoAnalyzer",
    "CameraRegistry",
    "CameraService",
    "CameraSource",
    "CameraStatus",
    "DemoCameraSource",
    "OfflineCameraSource",
    "RTSPStreamSource",
    "TorchvisionPersonAnalyzer",
    "VideoAnalysisResult",
    "camera_registry",
    "camera_service",
    "default_video_analyzer",
    "mask_credentials",
]

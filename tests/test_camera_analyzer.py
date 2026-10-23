"""
tests/test_camera_analyzer.py
=============================
Focused tests for Phase 2 real video analysis and person detection:
- Genuine model inference on synthetic sample clips
- Real bounding box and confidence parsing
- Accurate NO_PERSON_DETECTED handling on empty footage
- Explicit MODEL_UNAVAILABLE handling without fake fallbacks
- INVALID_VIDEO handling on missing or corrupt files
- Reviewable snapshot generation in static directory
- Temporal deduplication across adjacent detection frames
- Strict privacy: no covert identification or fabricated identity
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from app.cameras.analyzer import (
    AnalysisStatus,
    TorchvisionPersonAnalyzer,
    VideoAnalysisResult,
    default_video_analyzer,
)

FOOTAGE_DIR = Path("simulator/footage")


class TestVideoAnalyzer:
    @pytest.fixture()
    def analyzer(self) -> TorchvisionPersonAnalyzer:
        return default_video_analyzer

    def test_real_inference_on_main_gate_clip(self, analyzer: TorchvisionPersonAnalyzer):
        clip_path = FOOTAGE_DIR / "main_gate_demo.mp4"
        assert clip_path.exists()

        result = analyzer.analyze_clip(clip_path=clip_path, camera_id="cam-main-gate")
        assert isinstance(result, VideoAnalysisResult)
        assert result.analysis_status == AnalysisStatus.PERSON_DETECTED.value
        assert result.detection_label == "person_detected"
        assert result.model_name == "ssdlite320_mobilenet_v3_large"
        assert result.total_frames_analyzed == 30
        assert result.detected_frame_index is not None

        # Real model inference checks
        assert result.model_confidence is not None
        assert 0.40 <= result.model_confidence <= 1.0
        assert result.bounding_box is not None
        assert len(result.bounding_box) == 4
        x1, y1, x2, y2 = result.bounding_box
        assert x1 < x2 and y1 < y2

        # Reviewable snapshot check
        assert result.snapshot_url is not None
        assert result.snapshot_url.startswith("/static/snapshots/")
        snapshot_filename = result.snapshot_url.split("/")[-1]
        snapshot_path = Path("app/web/static/snapshots") / snapshot_filename
        assert snapshot_path.exists()
        assert snapshot_path.stat().st_size > 500

    def test_real_inference_on_back_patio_clip(self, analyzer: TorchvisionPersonAnalyzer):
        clip_path = FOOTAGE_DIR / "back_patio_demo.mp4"
        assert clip_path.exists()

        result = analyzer.analyze_clip(clip_path=clip_path, camera_id="cam-back-patio")
        assert result.analysis_status == AnalysisStatus.PERSON_DETECTED.value
        assert result.detection_label == "person_detected"
        assert result.model_confidence is not None
        assert result.model_confidence >= 0.40
        assert result.bounding_box is not None

    def test_no_person_detected_on_empty_yard(self, analyzer: TorchvisionPersonAnalyzer):
        clip_path = FOOTAGE_DIR / "empty_yard_demo.mp4"
        assert clip_path.exists()

        result = analyzer.analyze_clip(clip_path=clip_path, camera_id="cam-quiet-yard")
        assert result.analysis_status == AnalysisStatus.NO_PERSON_DETECTED.value
        assert result.detection_label is None
        assert result.model_confidence is None
        assert result.bounding_box is None
        assert result.snapshot_url is None
        assert result.total_frames_analyzed == 20
        assert result.deduplicated_events_count == 0

    def test_invalid_video_missing_file(self, analyzer: TorchvisionPersonAnalyzer):
        missing_path = Path("simulator/footage/missing_video_99.mp4")
        result = analyzer.analyze_clip(clip_path=missing_path, camera_id="cam-test")

        assert result.analysis_status == AnalysisStatus.INVALID_VIDEO.value
        assert result.model_confidence is None
        assert result.bounding_box is None
        assert result.snapshot_url is None
        assert "missing" in result.details.lower()

    def test_model_unavailable_explicit_handling(self):
        # Force model unavailable to verify no fake fallbacks or fabricated detections
        unavail_analyzer = TorchvisionPersonAnalyzer(force_model_unavailable=True)
        assert unavail_analyzer.is_available() is False

        clip_path = FOOTAGE_DIR / "main_gate_demo.mp4"
        result = unavail_analyzer.analyze_clip(clip_path=clip_path, camera_id="cam-main-gate")

        assert result.analysis_status == AnalysisStatus.MODEL_UNAVAILABLE.value
        assert result.model_confidence is None
        assert result.bounding_box is None
        assert result.snapshot_url is None
        assert result.detection_label is None
        assert "unavailable" in result.details.lower()
        assert "no fake detections" in result.details.lower()

    def test_temporal_deduplication(self, analyzer: TorchvisionPersonAnalyzer):
        clip_path = FOOTAGE_DIR / "main_gate_demo.mp4"
        # The main gate clip has a person in almost every frame of the 30 frames.
        # Temporal deduplication must cluster adjacent frames into 1 or 2 tracks rather than 30 separate events.
        result = analyzer.analyze_clip(
            clip_path=clip_path,
            camera_id="cam-main-gate",
            temporal_window_frames=15,
        )
        assert result.analysis_status == AnalysisStatus.PERSON_DETECTED.value
        assert result.deduplicated_events_count in [1, 2]
        assert result.total_frames_analyzed == 30

    def test_no_fabricated_identity_or_event_reference(self, analyzer: TorchvisionPersonAnalyzer):
        clip_path = FOOTAGE_DIR / "main_gate_demo.mp4"
        result = analyzer.analyze_clip(clip_path=clip_path, camera_id="cam-main-gate")

        # Must not assume or fabricate named identity
        assert result.detection_label == "person_detected"
        assert result.event_reference is None
        # Must not claim known visitor without configured recognition adapter
        assert "known_visitor" not in (result.detection_label or "")

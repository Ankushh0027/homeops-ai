"""
app/cameras/analyzer.py
=======================
Genuine video analysis and person detection pipeline for HomeOps-AI.

Guarantees & Constraints:
1. Real model inference: Uses PyTorch / Torchvision `ssdlite320_mobilenet_v3_large`
   trained on COCO dataset (class 1: person).
2. No fake detections: If model/weights are unavailable, returns MODEL_UNAVAILABLE
   with clear instructions. Never substitutes fake detections or heuristics.
3. Temporal deduplication: Groups adjacent detection frames within a temporal window
   into a single track/incident to prevent duplicate alert storms.
4. Reviewable snapshots: Generates JPEG snapshots with bounding-box overlays in
   `app/web/static/snapshots/`.
5. Privacy-first visitor taxonomy:
   - Default: `person_detected` / `unmatched_person`.
   - Never infers identity from appearance alone.
   - `known_visitor_match` is reserved strictly for real, user-approved matching adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageDraw
import imageio_ffmpeg

logger = logging.getLogger("homeops.cameras.analyzer")

SNAPSHOTS_DIR = Path(__file__).parent.parent / "web" / "static" / "snapshots"


class AnalysisStatus(str, Enum):
    """Explicit analysis outcome statuses."""
    PERSON_DETECTED = "PERSON_DETECTED"
    NO_PERSON_DETECTED = "NO_PERSON_DETECTED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    INVALID_VIDEO = "INVALID_VIDEO"


@dataclass
class VideoAnalysisResult:
    """Structured evidence returned by video analysis.
    
    Fields like model_confidence and bounding_box are ONLY populated when
    produced by real model inference.
    """
    camera_id: str
    source_mode: str
    analysis_status: str
    model_name: str
    model_version: Optional[str] = None
    timestamp: str = ""
    detection_label: Optional[str] = None
    model_confidence: Optional[float] = None
    bounding_box: Optional[list[float]] = None
    snapshot_url: Optional[str] = None
    event_reference: Optional[str] = None
    total_frames_analyzed: int = 0
    detected_frame_index: Optional[int] = None
    deduplicated_events_count: int = 0
    details: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseVideoAnalyzer(ABC):
    """Abstract interface for video clip analyzers."""

    @abstractmethod
    def analyze_clip(
        self,
        clip_path: Path,
        camera_id: str,
        source_mode: str = "demo",
        confidence_threshold: float = 0.40,
    ) -> VideoAnalysisResult:
        """Decode frames and run object detection on the provided video clip."""
        raise NotImplementedError


class TorchvisionPersonAnalyzer(BaseVideoAnalyzer):
    """Genuine person-detection analyzer powered by Torchvision SSDLite MobileNetV3."""

    MODEL_NAME: str = "ssdlite320_mobilenet_v3_large"
    MODEL_VERSION: str = "torchvision-coco-v1"
    PERSON_CLASS_INDEX: int = 1  # COCO class 1 is person

    def __init__(self, force_model_unavailable: bool = False) -> None:
        """Initialize the analyzer.
        
        Parameters
        ----------
        force_model_unavailable:
            Used in tests to simulate weight loading failure or missing PyTorch weights.
        """
        self._force_model_unavailable = force_model_unavailable
        self._model = None
        self._transforms = None
        self._load_error: Optional[str] = None
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

        if not self._force_model_unavailable:
            self._try_load_model()

    def _try_load_model(self) -> None:
        """Attempt to load genuine pretrained SSDLite model weights."""
        try:
            import torch
            import torchvision.models.detection as detection_models

            weights = detection_models.SSDLite320_MobileNet_V3_Large_Weights.DEFAULT
            model = detection_models.ssdlite320_mobilenet_v3_large(weights=weights)
            model.eval()
            self._model = model
            self._transforms = weights.transforms()
            self._load_error = None
            logger.info("Torchvision %s model loaded successfully.", self.MODEL_NAME)
        except Exception as exc:
            self._model = None
            self._transforms = None
            self._load_error = (
                f"Pretrained model '{self.MODEL_NAME}' weights could not be loaded: {exc}. "
                "Ensure PyTorch and Torchvision can access model weights cache. "
                "No heuristic or fake detections will be substituted."
            )
            logger.warning(self._load_error)

    def is_available(self) -> bool:
        """Return True only if the real pretrained model is loaded in memory."""
        return self._model is not None and not self._force_model_unavailable

    def analyze_clip(
        self,
        clip_path: Path,
        camera_id: str,
        source_mode: str = "demo",
        confidence_threshold: float = 0.40,
        temporal_window_frames: int = 15,
    ) -> VideoAnalysisResult:
        """Decode frames and run genuine object detection inference."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # 1. Model Availability Check
        if not self.is_available():
            err_msg = self._load_error or "Model weights unavailable. No fake detections substituted."
            return VideoAnalysisResult(
                camera_id=camera_id,
                source_mode=source_mode,
                analysis_status=AnalysisStatus.MODEL_UNAVAILABLE.value,
                model_name=self.MODEL_NAME,
                model_version=self.MODEL_VERSION,
                timestamp=now_iso,
                detection_label=None,
                model_confidence=None,
                bounding_box=None,
                snapshot_url=None,
                event_reference=None,
                total_frames_analyzed=0,
                details=err_msg,
            )

        # 2. File / Video Verification Check
        if not clip_path or not Path(clip_path).exists() or not Path(clip_path).is_file():
            return VideoAnalysisResult(
                camera_id=camera_id,
                source_mode=source_mode,
                analysis_status=AnalysisStatus.INVALID_VIDEO.value,
                model_name=self.MODEL_NAME,
                model_version=self.MODEL_VERSION,
                timestamp=now_iso,
                detection_label=None,
                model_confidence=None,
                bounding_box=None,
                snapshot_url=None,
                event_reference=None,
                total_frames_analyzed=0,
                details=f"Video file '{clip_path}' is missing or not a readable file.",
            )

        # 3. Decode Frames using imageio_ffmpeg
        try:
            reader = imageio_ffmpeg.read_frames(str(clip_path))
            meta = next(reader)
            width, height = meta["size"]
        except Exception as exc:
            logger.error("Failed to decode video '%s': %s", clip_path, exc)
            return VideoAnalysisResult(
                camera_id=camera_id,
                source_mode=source_mode,
                analysis_status=AnalysisStatus.INVALID_VIDEO.value,
                model_name=self.MODEL_NAME,
                model_version=self.MODEL_VERSION,
                timestamp=now_iso,
                detection_label=None,
                model_confidence=None,
                bounding_box=None,
                snapshot_url=None,
                event_reference=None,
                total_frames_analyzed=0,
                details=f"Video decoding failed: {exc}",
            )

        import torch

        frame_idx = 0
        raw_detections: list[dict[str, Any]] = []

        try:
            for frame_bytes in reader:
                pil_img = Image.frombytes("RGB", (width, height), frame_bytes)
                input_tensor = self._transforms(pil_img).unsqueeze(0)

                with torch.no_grad():
                    prediction = self._model(input_tensor)[0]

                labels = prediction["labels"].tolist()
                scores = prediction["scores"].tolist()
                boxes = prediction["boxes"].tolist()

                # Filter strictly for person class (index 1) with confidence >= threshold
                best_person_score = 0.0
                best_person_box = None

                for label, score, box in zip(labels, scores, boxes):
                    if label == self.PERSON_CLASS_INDEX and score >= confidence_threshold:
                        if score > best_person_score:
                            best_person_score = float(score)
                            best_person_box = [round(float(c), 1) for c in box]

                if best_person_box:
                    raw_detections.append({
                        "frame_index": frame_idx,
                        "score": best_person_score,
                        "box": best_person_box,
                        "pil_img": pil_img,
                    })

                frame_idx += 1
        finally:
            reader.close()

        total_frames = frame_idx

        # 4. Handle Case: No Person Detected
        if not raw_detections:
            return VideoAnalysisResult(
                camera_id=camera_id,
                source_mode=source_mode,
                analysis_status=AnalysisStatus.NO_PERSON_DETECTED.value,
                model_name=self.MODEL_NAME,
                model_version=self.MODEL_VERSION,
                timestamp=now_iso,
                detection_label=None,
                model_confidence=None,
                bounding_box=None,
                snapshot_url=None,
                event_reference=None,
                total_frames_analyzed=total_frames,
                deduplicated_events_count=0,
                details="Model completed inference across all frames. No person detected above threshold.",
            )

        # 5. Temporal Deduplication across nearby frames
        # Cluster detections within `temporal_window_frames`
        clusters: list[list[dict[str, Any]]] = []
        current_cluster: list[dict[str, Any]] = [raw_detections[0]]

        for det in raw_detections[1:]:
            if det["frame_index"] - current_cluster[-1]["frame_index"] <= temporal_window_frames:
                current_cluster.append(det)
            else:
                clusters.append(current_cluster)
                current_cluster = [det]
        if current_cluster:
            clusters.append(current_cluster)

        # Select the peak detection from the primary cluster
        primary_cluster = clusters[0]
        peak_detection = max(primary_cluster, key=lambda d: d["score"])

        peak_score = peak_detection["score"]
        peak_box = peak_detection["box"]
        peak_frame_idx = peak_detection["frame_index"]
        peak_img = peak_detection["pil_img"]

        # 6. Save Reviewable Snapshot with Bounding Box Overlay
        snapshot_url = self._save_reviewable_snapshot(
            pil_img=peak_img,
            camera_id=camera_id,
            frame_idx=peak_frame_idx,
            score=peak_score,
            box=peak_box,
        )

        return VideoAnalysisResult(
            camera_id=camera_id,
            source_mode=source_mode,
            analysis_status=AnalysisStatus.PERSON_DETECTED.value,
            model_name=self.MODEL_NAME,
            model_version=self.MODEL_VERSION,
            timestamp=now_iso,
            detection_label="person_detected",
            model_confidence=round(peak_score, 4),
            bounding_box=peak_box,
            snapshot_url=snapshot_url,
            event_reference=None,  # Event persistence is handled by camera service in Phase 3
            total_frames_analyzed=total_frames,
            detected_frame_index=peak_frame_idx,
            deduplicated_events_count=len(clusters),
            details=(
                f"Real model detection: person observed with {peak_score*100:.1f}% confidence. "
                f"Temporal deduplication grouped {len(raw_detections)} detection frames into {len(clusters)} track(s)."
            ),
        )

    def _save_reviewable_snapshot(
        self,
        pil_img: Image.Image,
        camera_id: str,
        frame_idx: int,
        score: float,
        box: list[float],
    ) -> Optional[str]:
        """Save a snapshot image with bounding box and telemetry text overlay."""
        try:
            snapshot_copy = pil_img.copy()
            draw = ImageDraw.Draw(snapshot_copy)
            x1, y1, x2, y2 = box

            # Bounding Box
            draw.rectangle([x1, y1, x2, y2], outline=(255, 153, 0), width=3)
            # Corner accents
            c_len = min(12, int((x2 - x1) / 4))
            draw.line([x1, y1, x1 + c_len, y1], fill=(255, 255, 255), width=3)
            draw.line([x1, y1, x1, y1 + c_len], fill=(255, 255, 255), width=3)

            # Label banner
            tag_text = f"PERSON: {score*100:.1f}%"
            draw.rectangle([x1, max(0, y1 - 18), x1 + 105, y1], fill=(255, 153, 0))
            draw.text((x1 + 4, max(2, y1 - 16)), tag_text, fill=(15, 23, 42))

            # Bottom telemetry watermark
            draw.rectangle([0, snapshot_copy.height - 18, snapshot_copy.width, snapshot_copy.height], fill=(16, 20, 30))
            draw.text((6, snapshot_copy.height - 15), f"HOMEOPS EVIDENCE • {camera_id.upper()} • FRAME {frame_idx}", fill=(200, 210, 225))

            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"snapshot_{camera_id}_{timestamp_str}_f{frame_idx}.jpg"
            output_path = SNAPSHOTS_DIR / filename
            snapshot_copy.save(str(output_path), "JPEG", quality=90)

            return f"/static/snapshots/{filename}"
        except Exception as exc:
            logger.error("Failed to save reviewable snapshot: %s", exc)
            return None


# Module-level default analyzer instance
default_video_analyzer = TorchvisionPersonAnalyzer()

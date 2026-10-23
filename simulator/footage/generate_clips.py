"""
simulator/footage/generate_clips.py
===================================
Generates short, lightweight synthetic demo video clips (H.264 MP4) for
HomeOps-AI camera evaluation.

NOTICE: All generated clips are explicitly synthetic test fixtures designed
for algorithmic testing and UI demonstration. They are NOT real surveillance
recordings.
"""

from __future__ import annotations

import os
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

FOOTAGE_DIR = Path(__file__).parent


def _draw_synthetic_person(draw: ImageDraw.ImageDraw, x: int, y: int, height: int = 100, color: tuple[int, int, int] = (40, 70, 120)) -> None:
    """Draw a stylized, anatomically proportioned human silhouette for object detection."""
    head_radius = height // 8
    head_cy = y + head_radius
    draw.ellipse(
        [x - head_radius, head_cy - head_radius, x + head_radius, head_cy + head_radius],
        fill=color,
    )
    # Torso
    torso_top = head_cy + head_radius
    torso_bottom = y + int(height * 0.6)
    torso_w = int(head_radius * 1.6)
    draw.rectangle([x - torso_w, torso_top, x + torso_w, torso_bottom], fill=color)
    # Arms
    arm_w = max(2, height // 25)
    draw.line([x - torso_w, torso_top + 5, x - torso_w - 8, torso_bottom - 5], fill=color, width=arm_w)
    draw.line([x + torso_w, torso_top + 5, x + torso_w + 8, torso_bottom - 5], fill=color, width=arm_w)
    # Legs
    leg_w = max(3, height // 20)
    leg_len = y + height
    draw.line([x - torso_w // 2, torso_bottom, x - torso_w // 2, leg_len], fill=color, width=leg_w)
    draw.line([x + torso_w // 2, torso_bottom, x + torso_w // 2, leg_len], fill=color, width=leg_w)


def generate_main_gate_clip(output_path: Path, num_frames: int = 30, fps: int = 10) -> None:
    """Generate synthetic Main Gate demonstration footage.
    
    Contains a person silhouette walking into the gate area over 3 seconds (30 frames @ 10fps).
    """
    width, height = 320, 240
    writer = imageio_ffmpeg.write_frames(
        str(output_path),
        size=(width, height),
        fps=fps,
        codec="libx264",
        pix_fmt_in="rgb24",
    )
    writer.send(None)

    for i in range(num_frames):
        img = Image.new("RGB", (width, height), color=(215, 222, 228))
        draw = ImageDraw.Draw(img)

        # Ground & Wall / Gate Architecture
        draw.rectangle([0, 150, width, height], fill=(130, 138, 145))
        draw.rectangle([0, 60, 90, 150], fill=(170, 155, 140))  # Brick pillar left
        draw.rectangle([230, 60, 320, 150], fill=(170, 155, 140))  # Brick pillar right
        # Gate bars
        for bar_x in range(95, 230, 15):
            draw.line([bar_x, 70, bar_x, 150], fill=(60, 65, 70), width=2)

        # Person moving horizontally from left gate towards center
        progress = i / max(1, num_frames - 1)
        person_x = int(70 + progress * 100)
        person_y = 90
        _draw_synthetic_person(draw, person_x, person_y, height=80, color=(35, 55, 95))

        # Explicit Synthetic Demo Notice
        draw.rectangle([0, 0, width, 24], fill=(18, 24, 38))
        draw.text((8, 6), "DEMO FOOTAGE • SYNTHETIC FIXTURE • MAIN GATE", fill=(255, 165, 0))
        draw.text((8, height - 16), f"CAM-01 • FRAME {i+1:02d}/{num_frames} • 10 FPS", fill=(240, 240, 240))

        frame_bytes = np.array(img, dtype=np.uint8)
        writer.send(frame_bytes)

    writer.close()


def generate_back_patio_clip(output_path: Path, num_frames: int = 30, fps: int = 10) -> None:
    """Generate synthetic Back Patio demonstration footage.
    
    Contains a person silhouette approaching a doorway over 3 seconds (30 frames @ 10fps).
    """
    width, height = 320, 240
    writer = imageio_ffmpeg.write_frames(
        str(output_path),
        size=(width, height),
        fps=fps,
        codec="libx264",
        pix_fmt_in="rgb24",
    )
    writer.send(None)

    for i in range(num_frames):
        img = Image.new("RGB", (width, height), color=(185, 200, 190))
        draw = ImageDraw.Draw(img)

        # Patio floor & Doorway
        draw.rectangle([0, 140, width, height], fill=(110, 115, 120))  # Pavers
        draw.rectangle([130, 50, 210, 140], fill=(70, 80, 95))  # Door frame
        draw.rectangle([140, 60, 200, 140], fill=(225, 230, 235))  # Glass door

        # Person stepping toward doorway
        progress = i / max(1, num_frames - 1)
        person_x = int(100 + progress * 40)
        person_y = 80
        _draw_synthetic_person(draw, person_x, person_y, height=85, color=(45, 45, 50))

        # Explicit Synthetic Demo Notice
        draw.rectangle([0, 0, width, 24], fill=(18, 24, 38))
        draw.text((8, 6), "DEMO FOOTAGE • SYNTHETIC FIXTURE • BACK PATIO", fill=(255, 165, 0))
        draw.text((8, height - 16), f"CAM-02 • FRAME {i+1:02d}/{num_frames} • 10 FPS", fill=(240, 240, 240))

        frame_bytes = np.array(img, dtype=np.uint8)
        writer.send(frame_bytes)

    writer.close()


def generate_empty_yard_clip(output_path: Path, num_frames: int = 20, fps: int = 10) -> None:
    """Generate synthetic empty yard footage without any persons or moving subjects."""
    width, height = 320, 240
    writer = imageio_ffmpeg.write_frames(
        str(output_path),
        size=(width, height),
        fps=fps,
        codec="libx264",
        pix_fmt_in="rgb24",
    )
    writer.send(None)

    for i in range(num_frames):
        img = Image.new("RGB", (width, height), color=(180, 210, 190))
        draw = ImageDraw.Draw(img)
        # Empty lawn and hedge, no human silhouette
        draw.rectangle([0, 120, width, height], fill=(100, 140, 100))
        draw.rectangle([0, 90, width, 120], fill=(60, 100, 60))

        # Explicit Synthetic Demo Notice
        draw.rectangle([0, 0, width, 24], fill=(18, 24, 38))
        draw.text((8, 6), "DEMO FOOTAGE • SYNTHETIC FIXTURE • QUIET YARD", fill=(255, 165, 0))
        draw.text((8, height - 16), f"CAM-QUIET • FRAME {i+1:02d}/{num_frames} • 10 FPS", fill=(240, 240, 240))

        frame_bytes = np.array(img, dtype=np.uint8)
        writer.send(frame_bytes)

    writer.close()


def generate_all() -> None:
    FOOTAGE_DIR.mkdir(parents=True, exist_ok=True)
    main_gate_path = FOOTAGE_DIR / "main_gate_demo.mp4"
    back_patio_path = FOOTAGE_DIR / "back_patio_demo.mp4"
    empty_yard_path = FOOTAGE_DIR / "empty_yard_demo.mp4"

    print(f"Generating synthetic clip: {main_gate_path}")
    generate_main_gate_clip(main_gate_path)
    print(f"Generating synthetic clip: {back_patio_path}")
    generate_back_patio_clip(back_patio_path)
    print(f"Generating synthetic clip: {empty_yard_path}")
    generate_empty_yard_clip(empty_yard_path)
    print("Synthetic demo clips generated successfully.")


if __name__ == "__main__":
    generate_all()


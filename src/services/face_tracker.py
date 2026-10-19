"""
Computer Vision Face Tracking Module.
Uses deep-learning YuNet (OpenCV FaceDetectorYN) or Haar Cascades to detect speaker faces
and calculate smoothly stabilized 9:16 crop coordinates.
"""

import os
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple
import cv2
import numpy as np

from src.console import log_info, log_success, log_warning, console
from src.models import FaceTrackingBox

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "models"
YUNET_MODEL_PATH = MODEL_DIR / "yunet.onnx"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"


class FaceTracker:
    """Computer vision face tracking and EMA smoothing filter."""

    def __init__(self, smoothing_factor: float = 0.15, deadband_px: int = 25) -> None:
        self.smoothing_factor = smoothing_factor
        self.deadband_px = deadband_px
        self.detector_type = "none"
        self.yunet_detector = None
        self.cascade_detector = None
        self._init_detector()

    def _init_detector(self) -> None:
        """Initialize the best available face detector."""
        # 1. Try OpenCV FaceDetectorYN (YuNet)
        if hasattr(cv2, "FaceDetectorYN_create"):
            try:
                MODEL_DIR.mkdir(parents=True, exist_ok=True)
                if not YUNET_MODEL_PATH.exists() or YUNET_MODEL_PATH.stat().st_size < 5000:
                    log_info("FACE_TRACKER", "Fetching YuNet ONNX face detection model...")
                    req = urllib.request.Request(YUNET_URL, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req) as resp, open(YUNET_MODEL_PATH, "wb") as f:
                        f.write(resp.read())

                self.yunet_detector = cv2.FaceDetectorYN_create(
                    str(YUNET_MODEL_PATH),
                    "",
                    (320, 320),
                    score_threshold=0.6,
                    nms_threshold=0.3,
                )
                self.detector_type = "yunet"
                return
            except Exception as e:
                log_warning("FACE_TRACKER", f"Could not initialize YuNet: {e}")

        # 2. Try OpenCV Haar Cascade (OpenCV 4.x fallback)
        if hasattr(cv2, "CascadeClassifier"):
            try:
                cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
                if os.path.exists(cascade_path):
                    self.cascade_detector = cv2.CascadeClassifier(cascade_path)
                    self.detector_type = "cascade"
                    return
            except Exception as e:
                log_warning("FACE_TRACKER", f"Could not initialize Haar cascade: {e}")

        log_warning("FACE_TRACKER", "Running with center-anchor face tracking fallback.")

    def detect_face(self, frame: np.ndarray) -> Optional[FaceTrackingBox]:
        """Detect the most prominent face in a single video frame."""
        h, w = frame.shape[:2]

        if self.detector_type == "yunet" and self.yunet_detector is not None:
            try:
                self.yunet_detector.setInputSize((w, h))
                _, faces = self.yunet_detector.detect(frame)
                if faces is not None and len(faces) > 0:
                    # Sort by bounding box area (w * h)
                    largest_face = max(faces, key=lambda f: f[2] * f[3])
                    fx, fy, fw, fh = [int(v) for v in largest_face[:4]]
                    conf = float(largest_face[-1])
                    return FaceTrackingBox(
                        x=fx,
                        y=fy,
                        w=fw,
                        h=fh,
                        center_x=fx + fw // 2,
                        center_y=fy + fh // 2,
                        confidence=conf,
                    )
            except Exception:
                pass

        elif self.detector_type == "cascade" and self.cascade_detector is not None:
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                small_gray = cv2.resize(gray, (0, 0), fx=0.5, fy=0.5)
                faces = self.cascade_detector.detectMultiScale(
                    small_gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(30, 30),
                )
                if len(faces) > 0:
                    largest_face = max(faces, key=lambda b: b[2] * b[3])
                    fx, fy, fw, fh = [int(v * 2) for v in largest_face]
                    return FaceTrackingBox(
                        x=fx,
                        y=fy,
                        w=fw,
                        h=fh,
                        center_x=fx + fw // 2,
                        center_y=fy + fh // 2,
                    )
            except Exception:
                pass

        return None

    def track_clip(
        self,
        video_path: str,
        start_time: float,
        end_time: float,
        sample_fps: int = 5,
    ) -> List[Tuple[float, int]]:
        """
        Sample frames across the clip timestamp range and compute smoothed crop centers.
        Returns a list of (timestamp, smoothed_crop_x_offset).
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            log_warning("FACE_TRACKER", f"Could not open video file: {video_path}")
            return []

        orig_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)

        crop_w = int(frame_height * (9 / 16))
        default_center_x = frame_width // 2

        current_smoothed_center = float(default_center_x)
        results: List[Tuple[float, int]] = []

        start_frame = int(start_time * orig_fps)
        end_frame = int(end_time * orig_fps)
        step_frames = max(1, int(orig_fps / sample_fps))

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        curr_frame_idx = start_frame

        log_info(
            "FACE_TRACKER",
            f"Analyzing face coordinates from {start_time:.1f}s to {end_time:.1f}s ({self.detector_type.upper()} detector)...",
        )

        logged_samples = 0
        while curr_frame_idx <= end_frame:
            cap.set(cv2.CAP_PROP_POS_FRAMES, curr_frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            timestamp = curr_frame_idx / orig_fps
            face_box = self.detect_face(frame)

            if face_box:
                target_center_x = face_box.center_x
                if abs(target_center_x - current_smoothed_center) > self.deadband_px:
                    current_smoothed_center = (
                        self.smoothing_factor * target_center_x
                        + (1 - self.smoothing_factor) * current_smoothed_center
                    )
            else:
                current_smoothed_center = (
                    0.05 * default_center_x + 0.95 * current_smoothed_center
                )

            left_x = int(current_smoothed_center - crop_w // 2)
            left_x = max(0, min(frame_width - crop_w, left_x))

            results.append((timestamp, left_x))

            if logged_samples < 8 or curr_frame_idx % (step_frames * 10) == 0:
                if face_box:
                    console.print(
                        f"[dim white][{timestamp:06.2f}s][/dim white] "
                        f"[bold cyan]Face Detected:[/bold cyan] (x={face_box.x}, y={face_box.y}, w={face_box.w}, h={face_box.h}) "
                        f"-> [bold green]Smoothed 9:16 Crop X:[/bold green] [{left_x} : {left_x + crop_w}]"
                    )
                else:
                    console.print(
                        f"[dim white][{timestamp:06.2f}s][/dim white] "
                        f"[dim yellow]No Face[/dim yellow] -> Holding Crop X at [{left_x} : {left_x + crop_w}]"
                    )
                logged_samples += 1

            curr_frame_idx += step_frames

        cap.release()
        log_success("FACE_TRACKER", f"Face tracking analysis complete for {len(results)} sample points.")
        return results

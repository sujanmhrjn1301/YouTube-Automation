"""
Audio Energy & YouTube Heatmap Peak Detection Service.
Scans audio RMS volume spikes and integrates YouTube Most Replayed curves
to locate high-energy candidate windows without human clipping.
"""

import math
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.console import log_info, log_success, log_warning


class PeakDetectorService:
    """Detects peak viral moments via audio volume energy (RMS) and YouTube heatmap."""

    def __init__(self, window_size_sec: float = 4.0, step_size_sec: float = 2.0) -> None:
        self.window_size_sec = window_size_sec
        self.step_size_sec = step_size_sec

    def compute_audio_energy(self, wav_path: Path) -> List[Tuple[float, float, float]]:
        """
        Compute normalized RMS audio energy across the audio file in sliding windows.
        Returns list of (start_time, end_time, normalized_energy).
        """
        if not wav_path.exists():
            log_warning("PEAK_DETECTOR", f"Audio file not found: {wav_path}")
            return []

        try:
            with wave.open(str(wav_path), "rb") as wf:
                sample_rate = wf.getframerate()
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                total_frames = wf.getnframes()

                dtype = np.int16 if sampwidth == 2 else np.uint8
                raw_data = wf.readframes(total_frames)

            audio_data = np.frombuffer(raw_data, dtype=dtype)
            if n_channels > 1:
                audio_data = audio_data.reshape(-1, n_channels).mean(axis=1)

            audio_data = audio_data.astype(np.float32)
            max_val = np.max(np.abs(audio_data))
            if max_val > 0:
                audio_data /= max_val

            total_sec = total_frames / sample_rate
            window_samples = int(self.window_size_sec * sample_rate)
            step_samples = int(self.step_size_sec * sample_rate)

            results: List[Tuple[float, float, float]] = []
            for start_idx in range(0, len(audio_data) - window_samples, step_samples):
                chunk = audio_data[start_idx : start_idx + window_samples]
                rms = float(np.sqrt(np.mean(chunk**2)))
                start_t = start_idx / sample_rate
                end_t = (start_idx + window_samples) / sample_rate
                results.append((start_t, end_t, rms))

            if not results:
                return []

            rms_vals = [r[2] for r in results]
            min_rms = min(rms_vals)
            max_rms = max(rms_vals)
            rng = max_rms - min_rms if (max_rms - min_rms) > 1e-6 else 1.0

            normalized = [
                (r[0], r[1], round((r[2] - min_rms) / rng, 4))
                for r in results
            ]
            return normalized

        except Exception as e:
            log_warning("PEAK_DETECTOR", f"Audio energy analysis failed: {e}")
            return []

    def find_top_peak_windows(
        self,
        wav_path: Path,
        total_duration: float,
        window_duration: float = 180.0,
        top_k: int = 3,
        heatmap_points: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Tuple[float, float, float]]:
        """
        Identify top K non-overlapping peak windows combining audio RMS spikes
        and optional YouTube heatmap curves.
        Guarantees extracting top_k distinct candidate windows by dynamically adapting
        window duration and using progressive gap relaxation.
        Returns: [(window_start, window_end, peak_score), ...]
        """
        if top_k <= 1:
            if total_duration <= window_duration:
                return [(0.0, total_duration, 1.0)]

        # Dynamically adapt window duration if requested clips cannot physically fit
        if top_k > 1:
            if (window_duration * top_k) > (total_duration * 0.95) and total_duration >= 45.0:
                window_duration = max(35.0, min(window_duration, (total_duration / top_k) * 1.15))
            if total_duration < window_duration:
                window_duration = max(20.0, total_duration)

        audio_energy = self.compute_audio_energy(wav_path)
        if not audio_energy:
            step = max(10.0, (total_duration - window_duration) / max(1, top_k + 1))
            return [(round(i * step, 1), round(min(total_duration, i * step + window_duration), 1), 0.8) for i in range(1, top_k + 1)]

        num_secs = int(math.ceil(total_duration))
        combined_scores = np.zeros(num_secs, dtype=np.float32)

        for s, e, score in audio_energy:
            idx_s = max(0, min(num_secs - 1, int(s)))
            idx_e = max(0, min(num_secs, int(e)))
            combined_scores[idx_s:idx_e] = np.maximum(combined_scores[idx_s:idx_e], score)

        if heatmap_points:
            log_info("PEAK_DETECTOR", f"Integrating {len(heatmap_points)} YouTube Most Replayed heatmap points...")
            for pt in heatmap_points:
                s = pt.get("start_time", 0.0)
                e = pt.get("end_time", s + 1.0)
                val = pt.get("value", 0.0)
                idx_s = max(0, min(num_secs - 1, int(s)))
                idx_e = max(0, min(num_secs, int(e)))
                combined_scores[idx_s:idx_e] = (0.6 * val) + (0.4 * combined_scores[idx_s:idx_e])

        win_size = int(window_duration)
        window_scores: List[Tuple[int, float]] = []
        scan_step = max(2, min(10, int(window_duration // 10)))

        for start_sec in range(0, max(1, num_secs - win_size), scan_step):
            w_score = float(np.mean(combined_scores[start_sec : start_sec + win_size]))
            window_scores.append((start_sec, w_score))

        window_scores.sort(key=lambda x: x[1], reverse=True)

        ideal_gap = (total_duration - window_duration) / max(1, top_k)
        min_gap = max(20.0, min(window_duration * 0.75, ideal_gap * 0.9))

        selected_windows: List[Tuple[float, float, float]] = []

        # Pass 1: Strict peak selection with ideal gap
        for start_sec, score in window_scores:
            end_sec = min(total_duration, start_sec + window_duration)
            overlaps = any(abs(start_sec - sw[0]) < min_gap for sw in selected_windows)
            if not overlaps:
                selected_windows.append((float(start_sec), float(end_sec), round(score, 3)))
                if len(selected_windows) >= top_k:
                    break

        # Pass 2: Progressive gap relaxation to guarantee reaching top_k
        for gap_factor in [0.6, 0.4, 0.25]:
            if len(selected_windows) >= top_k:
                break
            relaxed_gap = max(15.0, min_gap * gap_factor)
            for start_sec, score in window_scores:
                end_sec = min(total_duration, start_sec + window_duration)
                if not any(abs(start_sec - sw[0]) < relaxed_gap for sw in selected_windows):
                    selected_windows.append((float(start_sec), float(end_sec), round(score, 3)))
                    if len(selected_windows) >= top_k:
                        break

        # Pass 3: Evenly-spaced filler across timeline if still under top_k
        if len(selected_windows) < top_k and total_duration >= 30.0:
            step = (total_duration - window_duration) / max(1, top_k + 1)
            for i in range(1, top_k + 2):
                cand_start = round(i * step, 1)
                if cand_start + window_duration > total_duration:
                    cand_start = max(0.0, total_duration - window_duration)
                if not any(abs(cand_start - sw[0]) < 12.0 for sw in selected_windows):
                    s_idx = max(0, min(num_secs - 1, int(cand_start)))
                    e_idx = max(0, min(num_secs, int(cand_start + window_duration)))
                    sc = float(np.mean(combined_scores[s_idx:e_idx])) if e_idx > s_idx else 0.5
                    selected_windows.append((float(cand_start), float(min(total_duration, cand_start + window_duration)), round(sc, 3)))
                    if len(selected_windows) >= top_k:
                        break

        selected_windows.sort(key=lambda x: x[0])
        selected_windows = selected_windows[:top_k]
        log_success(
            "PEAK_DETECTOR",
            f"Identified {len(selected_windows)} high-energy viral candidate windows across {total_duration / 60:.1f} mins (Target: {top_k}).",
        )
        return selected_windows


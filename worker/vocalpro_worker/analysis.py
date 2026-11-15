"""Audio Analysis (BPM, Musical Key, Duration, 8,000-point Waveform) for VocalPro v3 Worker."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import soundfile as sf

from .engine import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS, resolve_ffmpeg


def _ensure_ffmpeg_in_path() -> None:
    ffmpeg_bin = resolve_ffmpeg()
    if ffmpeg_bin and Path(ffmpeg_bin).is_file():
        ffmpeg_dir = str(Path(ffmpeg_bin).parent)
        cur_path = os.environ.get("PATH", "")
        if ffmpeg_dir not in cur_path.split(os.pathsep):
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + cur_path


def _resolve_audio_target(audio_path: str | Path) -> Path:
    p = Path(audio_path)
    if p.is_dir():
        supported = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
        candidates = sorted(
            [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in supported],
            key=lambda f: (0 if "_vocals" in f.stem.lower() else 1, f.name.lower()),
        )
        if not candidates:
            raise ValueError(f"No audio files found in folder: {p}")
        return candidates[0]
    return p


def analyze_audio_file(audio_path: str | Path) -> dict[str, Any]:
    """Compute BPM, musical key (Krumhansl-Schmuckler), duration, and 8000-point peak waveform.

    Fixes P-01 (runs inside worker process off UI/host thread) and P-02 (uses fast soundfile
    streaming/read for waveform instead of double librosa.load full-file decode).
    Preserves exact BPM & Key parity with api_server/main.py:868-990.
    """
    _ensure_ffmpeg_in_path()
    path_str = str(_resolve_audio_target(audio_path))

    # 1. Decode up to 30 seconds at 22050 Hz mono for BPM and Krumhansl-Schmuckler Key detection
    try:
        y_30s, sr = librosa.load(path_str, duration=30, res_type="soxr_hq", mono=True)
    except Exception:
        y_30s, sr = librosa.load(path_str, duration=30, res_type="scipy", mono=True)
    if len(y_30s) == 0:
        raise ValueError(f"Empty audio stream in {path_str}")

    tempo, _ = librosa.beat.beat_track(y=y_30s, sr=sr)
    bpm = float(round(float(np.asarray(tempo).flat[0])))

    chroma = librosa.feature.chroma_stft(y=y_30s, sr=sr, n_fft=2048, hop_length=1024)
    chroma_vals = np.sum(chroma, axis=1)

    pitches = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    maj_profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    min_profile = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]

    if float(np.std(chroma_vals)) < 1e-8:
        pitch_name = "C"
        scale = "major"
        key_label = "C Major"
    else:
        maj_corrs = [float(np.corrcoef(chroma_vals, np.roll(maj_profile, i))[0, 1]) for i in range(12)]
        min_corrs = [float(np.corrcoef(chroma_vals, np.roll(min_profile, i))[0, 1]) for i in range(12)]
        maj_corrs = [0.0 if np.isnan(c) else c for c in maj_corrs]
        min_corrs = [0.0 if np.isnan(c) else c for c in min_corrs]

        max_maj = max(maj_corrs)
        max_min = max(min_corrs)
        if max_maj > max_min:
            pitch_name = pitches[maj_corrs.index(max_maj)]
            scale = "major"
            key_label = f"{pitch_name} Major"
        else:
            pitch_name = pitches[min_corrs.index(max_min)]
            scale = "minor"
            key_label = f"{pitch_name} Minor"

    # 2. Fast waveform & duration computation using soundfile (with librosa fallback for video containers)
    try:
        data, native_sr = sf.read(path_str, dtype="float32", always_2d=True)
        duration_s = float(data.shape[0]) / float(native_sr)
        y_mono = data.mean(axis=1)
    except Exception:
        y_mono, native_sr = librosa.load(path_str, sr=None, mono=True)
        duration_s = float(len(y_mono)) / float(native_sr)

    target_points = 8000
    if len(y_mono) > target_points:
        step = len(y_mono) // target_points
        trimmed = y_mono[: step * target_points].reshape((target_points, step))
        waveform = np.max(np.abs(trimmed), axis=1).tolist()
    else:
        waveform = np.abs(y_mono).tolist()

    max_val = max(waveform) if waveform else 1.0
    if max_val > 0:
        waveform = [round(float(x) / float(max_val), 3) for x in waveform]

    return {
        "bpm": bpm,
        "key": key_label,
        "pitch": pitch_name,
        "scale": scale,
        "duration_s": round(duration_s, 3),
        "waveform": waveform,
    }

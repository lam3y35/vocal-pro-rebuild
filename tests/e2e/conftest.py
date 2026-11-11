"""Deterministic Pytest fixtures and audio generators for VocalPro v3.0.0 E2E tests."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Generator

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

import math
import os
import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from tests.e2e.harness.audio_validator import AudioValidator
from tests.e2e.harness.ipc_client import IpcClient
from tests.e2e.harness.process_monitor import ProcessMonitor

REF_DIR = WORKSPACE_ROOT / "benchmarks" / "reference-set"


def make_sine_audio(
    freq: float = 440.0,
    duration: float = 2.0,
    sr: int = 44100,
    channels: int = 2,
    amp: float = 0.5,
) -> np.ndarray:
    """Generate deterministic stereo or mono sine tone array in float32."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False, dtype=np.float32)
    tone = (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)
    if channels == 1:
        return tone[:, np.newaxis]
    elif channels == 2:
        # Slight stereo frequency spread for realistic channel balance
        tone_r = (amp * np.sin(2.0 * np.pi * (freq * 1.01) * t)).astype(np.float32)
        return np.column_stack([tone, tone_r])
    else:
        return np.repeat(tone[:, np.newaxis], channels, axis=1)


def generate_sine_wav(
    path: str | Path,
    freq: float = 440.0,
    duration: float = 2.0,
    sr: int = 44100,
    channels: int = 2,
    amp: float = 0.5,
    bit_depth: str = "PCM_16",
) -> Path:
    """Write deterministic sine WAV file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    audio = make_sine_audio(freq=freq, duration=duration, sr=sr, channels=channels, amp=amp)
    sf.write(str(p), audio, sr, subtype=bit_depth)
    return p


def generate_silence_wav(
    path: str | Path,
    duration: float = 2.0,
    sr: int = 44100,
    channels: int = 2,
    bit_depth: str = "PCM_16",
) -> Path:
    """Write digital silence WAV file (all zeros)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    audio = np.zeros((int(sr * duration), channels), dtype=np.float32)
    sf.write(str(p), audio, sr, subtype=bit_depth)
    return p


def generate_zero_byte_file(path: str | Path) -> Path:
    """Create a 0-byte file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p


def generate_corrupt_wav(path: str | Path) -> Path:
    """Create a corrupt WAV file (valid RIFF header followed by garbage or truncation)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Truncated 19 bytes header missing format chunks
    p.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00")
    return p


def generate_multiformat_sample(
    path: str | Path,
    fmt: str = "mp3",
    duration: float = 2.0,
    freq: float = 440.0,
) -> Path:
    """Generate a valid compressed audio sample (MP3, FLAC, OGG)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    sr = 44100
    audio = make_sine_audio(freq=freq, duration=duration, sr=sr, channels=2, amp=0.6)

    fmt_clean = fmt.lower().lstrip(".")
    if fmt_clean == "flac":
        sf.write(str(p), audio, sr, format="FLAC", subtype="PCM_16")
    elif fmt_clean == "ogg":
        sf.write(str(p), audio, sr, format="OGG", subtype="VORBIS")
    elif fmt_clean == "mp3":
        tmp_wav = p.with_suffix(".tmp.wav")
        sf.write(str(tmp_wav), audio, sr, subtype="PCM_16")
        ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
        subprocess.run(
            [ffmpeg_bin, "-y", "-i", str(tmp_wav), "-codec:a", "libmp3lame", "-b:a", "320k", str(p)],
            check=True,
            capture_output=True,
        )
        tmp_wav.unlink(missing_ok=True)
    else:
        sf.write(str(p), audio, sr, subtype="PCM_16")

    return p


def generate_video_sample(path: str | Path, duration: float = 2.0) -> Path:
    """Generate a test MP4 video container with deterministic video testsrc and sine audio."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=320x240:rate=24",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}:sample_rate=44100",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(p),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return p


def generate_arabic_named_wav(
    dir_path: str | Path,
    name: str = "موسيقى_2026.wav",
    duration: float = 2.0,
) -> Path:
    """Generate a WAV file with Arabic / RTL Unicode filename."""
    p = Path(dir_path) / name
    return generate_sine_wav(p, duration=duration)


@pytest.fixture
def sandbox_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Provide a clean isolated sandbox directory per test."""
    sb = tmp_path / "sandbox"
    sb.mkdir(parents=True, exist_ok=True)
    yield sb


@pytest.fixture
def audio_validator() -> AudioValidator:
    """Provide an AudioValidator instance."""
    return AudioValidator()


@pytest.fixture
def process_monitor() -> ProcessMonitor:
    """Provide a ProcessMonitor instance."""
    return ProcessMonitor()


@pytest.fixture
def ipc_client() -> Generator[IpcClient, None, None]:
    """Provide a running IpcClient connected to vocalpro_worker, automatically closed after test."""
    client = IpcClient()
    client.start()
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def sample_sine_wav(sandbox_dir: Path) -> Path:
    """Return a deterministic 2-second stereo 440 Hz WAV file."""
    return generate_sine_wav(sandbox_dir / "sine_440_stereo.wav", duration=2.0)


@pytest.fixture
def sample_silence_wav(sandbox_dir: Path) -> Path:
    """Return a deterministic 2-second silent WAV file."""
    return generate_silence_wav(sandbox_dir / "silence_stereo.wav", duration=2.0)


@pytest.fixture
def sample_zero_byte_wav(sandbox_dir: Path) -> Path:
    """Return a 0-byte file."""
    return generate_zero_byte_file(sandbox_dir / "zero_bytes.wav")


@pytest.fixture
def sample_corrupt_wav(sandbox_dir: Path) -> Path:
    """Return a corrupted WAV file."""
    return generate_corrupt_wav(sandbox_dir / "corrupted_header.wav")


@pytest.fixture
def sample_video_mp4(sandbox_dir: Path) -> Path:
    """Return a valid test MP4 video container."""
    ref_vid = REF_DIR / "track_06_video_sample.mp4"
    if ref_vid.is_file():
        target = sandbox_dir / "track_06_video_sample.mp4"
        shutil.copyfile(ref_vid, target)
        return target
    return generate_video_sample(sandbox_dir / "test_video.mp4", duration=2.0)


@pytest.fixture
def sample_arabic_wav(sandbox_dir: Path) -> Path:
    """Return a WAV file with Arabic UTF-8 filename."""
    return generate_arabic_named_wav(sandbox_dir, name="موسيقى_2026.wav", duration=2.0)


@pytest.fixture
def sample_stereo_pop(sandbox_dir: Path) -> Path:
    """Return reference stereo pop music track."""
    ref_track = REF_DIR / "track_01_pop_stereo_44k.wav"
    if ref_track.is_file():
        target = sandbox_dir / "track_01_pop_stereo_44k.wav"
        shutil.copyfile(ref_track, target)
        return target
    # Fallback generation
    return generate_sine_wav(sandbox_dir / "pop_stereo_ref.wav", freq=440.0, duration=3.0)

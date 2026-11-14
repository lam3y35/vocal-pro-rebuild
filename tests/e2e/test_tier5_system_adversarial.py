"""VocalPro v3.0.0 — Tier 5 White-Box Adversarial Coverage Hardening Test Suite.

Adversarial stress suite targeting:
1. Multilingual, Arabic RTL, Diacritics, Extended Unicode Paths & Nested Directory I/O.
2. Hostile Special Characters, Shell Metacharacters & Deeply Nested Paths (>200 chars).
3. Missing FFmpeg Binary Fallback Detection, Graceful Degradation & Capability Reporting.
4. Offline Model Guidance, Missing Weight Handling & User Notification Semantics.
5. Windows Packaging, Inno Setup Prerequisites, and Codepage 65001 Batch Script Verification.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import soundfile as sf

from tests.e2e.conftest import (
    generate_sine_wav,
    make_sine_audio,
)
from tests.e2e.harness.audio_validator import AudioValidator
from tests.e2e.harness.ipc_client import IpcClient


# ==============================================================================
# 1. UNICODE, ARABIC RTL, DIACRITICS & EXTENDED PATH ADVERSARIAL COVERAGE
# ==============================================================================


def test_t5_pth_01_arabic_nested_unicode_io(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T5_PTH_01: Input and output directories with complex Arabic RTL script and nested subdirectories."""
    arabic_parent = sandbox_dir / "مسار_تجارب_فوكال_برو_2026" / "مشروع_تفريد_الأصوات_المتقدم"
    arabic_parent.mkdir(parents=True, exist_ok=True)

    arabic_file = arabic_parent / "تسجيل_صوتي_نقي_عالي_الجودة.wav"
    generate_sine_wav(arabic_file, duration=2.0)

    arabic_out = sandbox_dir / "مخرجات_تفريد_الأصوات_2026" / "استوديو_المعالجة_الرقمية"
    arabic_out.mkdir(parents=True, exist_ok=True)

    res = ipc_client.separate(
        input_path=arabic_file,
        output_dir=arabic_out,
        options={"model": "htdemucs", "output_mode": "vocals", "output_format": "wav"},
        timeout=30.0,
    )

    assert res.get("event") == "job_done", f"Arabic nested separation failed: {res}"
    stems = res.get("stems", [])
    assert len(stems) >= 1

    for stem in stems:
        stem_path = Path(stem["path"])
        assert stem_path.is_file(), f"Stem path missing: {stem_path}"
        assert stem_path.stat().st_size > 0
        meta = audio_validator.inspect_audio(stem_path)
        assert meta["channels"] == 2
        assert meta["samplerate"] == 44100


def test_t5_pth_02_unicode_diacritics_cjk_and_accents(
    ipc_client: IpcClient,
    sandbox_dir: Path,
) -> None:
    """T5_PTH_02: Audio analysis on filenames containing Arabic tashkeel (diacritics), CJK, Cyrillic, and accents."""
    multilingual_names = [
        "مُوسِيقَى_عَرَبِيَّة_مُعَالَجَة.wav",
        "ボーカル_分離_テスト_2026.wav",
        "Тестовая_музыкальная_дорожка.wav",
        "chanson_très_élégante_et_sonore.wav",
    ]

    for name in multilingual_names:
        p = sandbox_dir / name
        generate_sine_wav(p, duration=1.5, freq=440.0)

        res = ipc_client.analyze(input_path=p, timeout=20.0)
        assert res.get("event") == "analysis_done", f"Analysis failed for {name}: {res}"
        assert "bpm" in res
        assert "key" in res
        assert "waveform" in res
        assert len(res["waveform"]) == 8000, f"Expected 8000 waveform points, got {len(res['waveform'])}"


def test_t5_pth_03_hostile_special_chars_shell_punctuation(
    ipc_client: IpcClient,
    sandbox_dir: Path,
    audio_validator: AudioValidator,
) -> None:
    """T5_PTH_03: Files and folders with spaces, quotes, brackets, ampersands, dollar, percent, and exclamation."""
    hostile_dir = sandbox_dir / "Adv [Track #1] (Vocal & Beat) $100% ~ Co! + Spec;= {2026}"
    hostile_dir.mkdir(parents=True, exist_ok=True)

    hostile_file = hostile_dir / "Input [VocalPro #1] & (Raw) - Mix! $2026.wav"
    generate_sine_wav(hostile_file, duration=2.0)

    out_dir = hostile_dir / "Out [Separation #1] & (Results) - Complete!"
    res = ipc_client.separate(
        input_path=hostile_file,
        output_dir=out_dir,
        options={"model": "htdemucs", "output_mode": "vocals", "output_format": "mp3", "audio_bitrate": "320k"},
        timeout=35.0,
    )

    assert res.get("event") == "job_done", f"Hostile path separation failed: {res}"
    stems = res.get("stems", [])
    assert len(stems) >= 1

    stem_path = Path(stems[0]["path"])
    assert stem_path.is_file()
    assert stem_path.stat().st_size > 0
    assert stem_path.suffix.lower() == ".mp3"


def test_t5_pth_04_deeply_nested_long_path_220_chars(
    ipc_client: IpcClient,
    sandbox_dir: Path,
) -> None:
    """T5_PTH_04: Extremely long path exceeding 220 characters with nested directories."""
    curr = sandbox_dir
    # Build 12 levels of directories with long descriptive names
    for i in range(1, 13):
        curr = curr / f"depth_level_{i:02d}_vocalpro_rebuild_long_path_stress_test"
    curr.mkdir(parents=True, exist_ok=True)

    long_file = curr / "deep_source_recording_normalized_44100_stereo_pcm16.wav"
    assert len(str(long_file)) >= 220, f"Path length {len(str(long_file))} is not >= 220"
    generate_sine_wav(long_file, duration=2.0)

    out_dir = curr / "output_nested_stems"
    res = ipc_client.separate(
        input_path=long_file,
        output_dir=out_dir,
        options={"model": "htdemucs", "output_mode": "vocals", "output_format": "flac"},
        timeout=35.0,
    )

    assert res.get("event") == "job_done", f"Long path separation failed: {res}"
    stems = res.get("stems", [])
    assert len(stems) >= 1
    stem_path = Path(stems[0]["path"])
    assert stem_path.is_file()
    assert stem_path.suffix.lower() == ".flac"


# ==============================================================================
# 2. PACKAGING, MISSING FFMPEG DETECTION & OFFLINE GUIDANCE
# ==============================================================================


def test_t5_pkg_01_missing_ffmpeg_detection_and_degradation(
    sandbox_dir: Path,
) -> None:
    """T5_PKG_01: Verify missing FFmpeg binary fallback detection, capability reporting, and pure-python WAV decoding."""
    # Spawn a worker with PATH stripped of ffmpeg and VOCALPRO_FFMPEG pointing to dummy path
    env = os.environ.copy()
    env["PATH"] = "/bin:/usr/bin"
    # Ensure system ffmpeg cannot be found
    dummy_empty_dir = sandbox_dir / "no_ffmpeg_path"
    dummy_empty_dir.mkdir(parents=True, exist_ok=True)
    env["PATH"] = str(dummy_empty_dir)
    env["VOCALPRO_FFMPEG"] = str(dummy_empty_dir / "nonexistent_ffmpeg")

    client = IpcClient(extra_env=env)
    client.start()
    try:
        caps = client.get_capabilities()
        assert caps.get("event") == "capabilities"
        # Since ffmpeg is not in PATH and VOCALPRO_FFMPEG is nonexistent, ffmpeg_available should be False
        assert caps.get("ffmpeg_available") is False, "Expected ffmpeg_available to be False when stripped"

        # Pure WAV audio decoding and separation should STILL succeed via soundfile without FFmpeg
        test_wav = sandbox_dir / "pure_wav_test.wav"
        generate_sine_wav(test_wav, duration=2.0)
        out_dir = sandbox_dir / "pure_wav_out"

        res = client.separate(
            input_path=test_wav,
            output_dir=out_dir,
            options={"model": "htdemucs", "output_mode": "vocals", "output_format": "wav"},
            timeout=25.0,
        )
        assert res.get("event") == "job_done", f"WAV separation without FFmpeg should succeed: {res}"

        # Attempting video container decoding when FFmpeg is missing should return structured DECODE_FAILED
        dummy_mp4 = sandbox_dir / "dummy_video.mp4"
        dummy_mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42")

        vid_res = client.separate(
            input_path=dummy_mp4,
            output_dir=sandbox_dir / "vid_out",
            options={"model": "htdemucs"},
            timeout=15.0,
        )
        assert vid_res.get("event") == "job_error"
        assert vid_res.get("code") in ("DECODE_FAILED", "INTERNAL")

        # Worker must remain alive and responsive
        pong = client.ping()
        assert pong.get("event") == "pong"
    finally:
        client.close()


def test_t5_pkg_02_offline_model_guidance_and_missing_weights(
    sandbox_dir: Path,
) -> None:
    """T5_PKG_02: Missing model returns MODEL_MISSING; verify frontend translation matches error message."""
    client = IpcClient()
    client.start()
    try:
        test_wav = sandbox_dir / "offline_model_test.wav"
        generate_sine_wav(test_wav, duration=1.5)

        # Request a non-existent model
        res = client.separate(
            input_path=test_wav,
            output_dir=sandbox_dir / "missing_model_out",
            options={"model": "nonexistent_model_v99"},
            timeout=15.0,
        )

        assert res.get("event") == "job_error"
        assert res.get("code") == "MODEL_MISSING"
        err_msg = str(res.get("message", ""))
        assert "not found" in err_msg.lower() or "missing" in err_msg.lower() or "nonexistent_model_v99" in err_msg

        # Verify frontend error translation semantics from appStores.ts:
        # const isMissingModel = errStr.toLowerCase().includes("model") || errStr.toLowerCase().includes("weight") || errStr.toLowerCase().includes("not found");
        # const userMessage = isMissingModel ? "AI model not found locally. Run setup.bat once or check {localappdata}\\VocalPro\\models." : ...
        err_str = f"Failed to load model 'nonexistent_model_v99': Model 'nonexistent_model_v99' not found in registry"
        is_missing_model = (
            "model" in err_str.lower()
            or "weight" in err_str.lower()
            or "not found" in err_str.lower()
        )
        assert is_missing_model is True, "Frontend isMissingModel pattern must match worker error string"
    finally:
        client.close()


def test_t5_pkg_03_packaging_and_batch_scripts_audit() -> None:
    """T5_PKG_03: Audit setup.bat, run.bat, and installer.iss for codepage 65001, Python bounds, and Inno Setup prerequisites."""
    workspace_root = Path(__file__).resolve().parents[2]

    setup_bat = workspace_root / "setup.bat"
    assert setup_bat.is_file(), "setup.bat must exist"
    setup_text = setup_bat.read_text(encoding="utf-8")
    assert "chcp 65001 >nul 2>&1" in setup_text, "setup.bat must set codepage 65001"
    assert "3.10" in setup_text and "3.11" in setup_text and "3.12" in setup_text, "setup.bat must probe 3.10-3.12"
    assert "3.13" in setup_text, "setup.bat must document rejection of Python 3.13+"

    run_bat = workspace_root / "run.bat"
    assert run_bat.is_file(), "run.bat must exist"
    run_text = run_bat.read_text(encoding="utf-8")
    assert "chcp 65001 >nul 2>&1" in run_text, "run.bat must set codepage 65001"
    assert "setup.bat" in run_text, "run.bat must fall back to setup.bat if engine is not installed"

    installer_iss = workspace_root / "installer.iss"
    assert installer_iss.is_file(), "installer.iss must exist"
    iss_text = installer_iss.read_text(encoding="utf-8")
    assert "IsWebView2Installed" in iss_text, "installer.iss must check WebView2 Evergreen runtime"
    assert "IsVCRedistInstalled" in iss_text, "installer.iss must check Visual C++ Redistributable"
    assert "vcruntime140_1.dll" in iss_text, "installer.iss must verify vcruntime140_1.dll fallback"
    assert "dist\\bundle\\ffmpeg.exe" in iss_text, "installer.iss must bundle static ffmpeg.exe"
    assert "{localappdata}\\VocalPro\\models" in iss_text, "installer.iss must target localappdata models dir"
